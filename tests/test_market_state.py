import io
import unittest
from datetime import date, timedelta
from unittest import mock

from scripts.market_state import (
    FAIL_AFTER_DAYS,
    G10,
    MarketStateError,
    build_fx_crosses,
    build_snapshot,
    curve_spread,
    fetch_fx,
    fetch_nz_rates,
    fx_metrics,
    parse_boc_json,
    parse_ecb_fx_csv,
    parse_ecb_sdmx_csv,
    parse_rba_csv,
    parse_rbnz_xlsx,
    parse_treasury_csv,
    percentile_rank,
    rate_metrics,
    require_g10_fx,
    rv_spread,
    validate_snapshot,
)


def _series(start: date, values: list[float]) -> dict[date, float]:
    return {date.fromordinal(start.toordinal() + i): v for i, v in enumerate(values)}


class MarketStateTests(unittest.TestCase):
    def test_treasury_parser(self):
        text = "Date,2 Yr,5 Yr,10 Yr,30 Yr\n09/08/2026,4.39,4.57,4.80,5.25\n"
        parsed = parse_treasury_csv(text)
        self.assertEqual(parsed["2Y"][date(2026, 9, 8)], 4.39)
        self.assertEqual(parsed["30Y"][date(2026, 9, 8)], 5.25)

    def test_treasury_parser_rejects_missing_30y(self):
        text = "Date,2 Yr,5 Yr,10 Yr,30 Yr\n09/08/2026,4.39,4.57,4.80,\n"
        with self.assertRaises(MarketStateError):
            parse_treasury_csv(text)

    def test_boc_parser(self):
        payload = {
            "observations": [
                {
                    "d": "2026-09-08",
                    "BD.CDN.2YR.DQ.YLD": {"v": "2.50"},
                    "BD.CDN.5YR.DQ.YLD": {"v": "2.75"},
                    "BD.CDN.10YR.DQ.YLD": {"v": "3.00"},
                    "BD.CDN.LONG.DQ.YLD": {"v": "3.40"},
                }
            ]
        }
        parsed = parse_boc_json(payload)
        self.assertEqual(parsed["10Y"][date(2026, 9, 8)], 3.0)
        self.assertEqual(parsed["LONG"][date(2026, 9, 8)], 3.4)

    def test_boc_parser_rejects_missing_long(self):
        payload = {
            "observations": [
                {
                    "d": "2026-09-08",
                    "BD.CDN.2YR.DQ.YLD": {"v": "2.50"},
                    "BD.CDN.5YR.DQ.YLD": {"v": "2.75"},
                    "BD.CDN.10YR.DQ.YLD": {"v": "3.00"},
                }
            ]
        }
        with self.assertRaises(MarketStateError):
            parse_boc_json(payload)

    def test_rba_parser(self):
        text = "\n".join(
            [
                "Title,Australian Government 2 year bond,Australian Government 5 year bond,Australian Government 10 year bond",
                "Description,Australian Government 2 year bond,Australian Government 5 year bond,Australian Government 10 year bond",
                "Frequency,Daily,Daily,Daily",
                "Series ID,F2Y,F5Y,F10Y",
                "2026-09-07,3.10,3.40,3.70",
            ]
        )
        parsed = parse_rba_csv(text)
        self.assertEqual(parsed["5Y"][date(2026, 9, 7)], 3.4)

    def test_rba_parser_prefers_title_and_skips_indexed(self):
        text = "\n".join(
            [
                "Title,Australian Government 2 year bond,Australian Government 3 year bond,Australian Government 5 year bond,Australian Government 10 year bond,Australian Government Indexed Bond",
                'Description,"Yields on Australian government bonds, interpolated, 2 years maturity","Yields on Australian government bonds, interpolated, 3 years maturity","Yields on Australian government bonds, interpolated, 5 years maturity","Yields on Australian government bonds, interpolated, 10 years maturity","Yields on Australian government indexed bonds, interpolated, 10 years maturity"',
                "Frequency,Daily,Daily,Daily,Daily,Daily",
                "Series ID,FCMYGBAG2D,FCMYGBAG3D,FCMYGBAG5D,FCMYGBAG10D,FCMYGBAGID",
                "2026-09-09,3.10,3.20,3.40,3.70,1.50",
            ]
        )
        parsed = parse_rba_csv(text)
        self.assertEqual(parsed["2Y"][date(2026, 9, 9)], 3.10)
        self.assertEqual(parsed["10Y"][date(2026, 9, 9)], 3.70)
        self.assertNotIn(1.50, parsed["10Y"].values())

    def test_ecb_and_all_45_crosses(self):
        headers = ["Date", "USD", "JPY", "GBP", "CHF", "CAD", "AUD", "NZD", "SEK", "NOK"]
        rows = [
            ["2026-09-07", "1.20", "180", "0.86", "0.94", "1.60", "1.62", "1.98", "11.2", "10.8"],
            ["2026-09-08", "1.21", "181", "0.87", "0.95", "1.61", "1.63", "1.99", "11.3", "10.9"],
        ]
        text = ",".join(headers) + "\n" + "\n".join(",".join(r) for r in rows) + "\n"
        currencies = parse_ecb_fx_csv(text)
        crosses = build_fx_crosses(currencies, date(2026, 1, 1))
        self.assertEqual(len(crosses), 45)
        self.assertAlmostEqual(crosses["EURUSD"][date(2026, 9, 8)], 1.21)
        self.assertAlmostEqual(crosses["USDCAD"][date(2026, 9, 8)], 1.61 / 1.21)
        self.assertAlmostEqual(crosses["AUDNZD"][date(2026, 9, 8)], 1.99 / 1.63)
        self.assertAlmostEqual(crosses["USDJPY"][date(2026, 9, 8)], 181 / 1.21)
        self.assertIn("NOKSEK", crosses)

    def test_ecb_sdmx_parser(self):
        text = "\n".join(
            [
                "CURRENCY,TIME_PERIOD,OBS_VALUE",
                "USD,2026-09-16,1.1537",
                "GBP,2026-09-16,0.8600",
                "JPY,2026-09-16,178.10",
                "CHF,2026-09-16,0.9470",
                "CAD,2026-09-16,1.6070",
                "AUD,2026-09-16,1.6120",
                "NZD,2026-09-16,1.9980",
                "SEK,2026-09-16,11.20",
                "NOK,2026-09-16,10.80",
            ]
        )
        parsed = parse_ecb_sdmx_csv(text)
        self.assertEqual(parsed["EUR"][date(2026, 9, 16)], 1.0)
        self.assertAlmostEqual(parsed["USD"][date(2026, 9, 16)], 1.1537)
        require_g10_fx(parsed)
        crosses = build_fx_crosses(parsed, date(2026, 1, 1))
        self.assertEqual(len(crosses), 45)
        self.assertAlmostEqual(crosses["EURUSD"][date(2026, 9, 16)], 1.1537)

    def test_ecb_sdmx_parser_accepts_partial_for_fallback_merge(self):
        parsed = parse_ecb_sdmx_csv("CURRENCY,TIME_PERIOD,OBS_VALUE\nUSD,2026-09-16,1.1537\n")
        self.assertAlmostEqual(parsed["USD"][date(2026, 9, 16)], 1.1537)
        self.assertEqual(parsed["EUR"][date(2026, 9, 16)], 1.0)
        self.assertEqual(parsed["GBP"], {})
        with self.assertRaises(MarketStateError):
            require_g10_fx(parsed)
        with self.assertRaises(MarketStateError):
            parse_ecb_sdmx_csv("CURRENCY,TIME_PERIOD,OBS_VALUE\n")

    def test_fetch_fx_falls_back_to_per_currency_sdmx(self):
        asof = date(2026, 9, 16)
        legs = {
            ccy: {ccy: {asof: 1.1 + i * 0.01}, "EUR": {asof: 1.0}}
            for i, ccy in enumerate(c for c in G10 if c != "EUR")
        }
        legs["USD"]["USD"][asof] = 1.15

        def fake_sdmx(currencies, start, timeout=90, retries=4):
            if "+" in currencies:
                raise MarketStateError("HTTP 504 from combined SDMX")
            if currencies not in legs:
                raise MarketStateError(f"unexpected currency {currencies}")
            return {c: dict(series) for c, series in legs[currencies].items()} | {
                c: {} for c in G10 if c not in legs[currencies]
            }

        with mock.patch("scripts.market_state._fetch_ecb_sdmx", side_effect=fake_sdmx):
            crosses = fetch_fx(date(2021, 1, 1))
        self.assertEqual(len(crosses), 45)
        self.assertAlmostEqual(crosses["EURUSD"][asof], 1.15)

    def test_fetch_fx_fails_loudly_if_fallback_still_incomplete(self):
        def fake_sdmx(currencies, start, timeout=90, retries=4):
            if "+" in currencies:
                raise MarketStateError("HTTP 504 from combined SDMX")
            if currencies == "USD":
                return {"USD": {date(2026, 9, 16): 1.15}, "EUR": {date(2026, 9, 16): 1.0}}
            raise MarketStateError(f"{currencies} 504")

        with mock.patch("scripts.market_state._fetch_ecb_sdmx", side_effect=fake_sdmx):
            with self.assertRaises(MarketStateError) as ctx:
                fetch_fx(date(2021, 1, 1))
        self.assertIn("per-currency fallback still missing", str(ctx.exception))

    def test_ecb_rejects_missing_g10_currency(self):
        text = "Date,USD,JPY\n2026-09-08,1.21,181\n"
        with self.assertRaises(MarketStateError):
            parse_ecb_fx_csv(text)

    def test_fx_crosses_use_same_fixing_date_only(self):
        currencies = {
            "EUR": {date(2026, 9, 7): 1.0, date(2026, 9, 8): 1.0},
            "USD": {date(2026, 9, 7): 1.20, date(2026, 9, 8): 1.21},
            "CAD": {date(2026, 9, 8): 1.61},
        }
        for ccy in ("GBP", "AUD", "NZD", "CHF", "NOK", "SEK", "JPY"):
            currencies[ccy] = {date(2026, 9, 8): 1.0 + hash(ccy) % 7}
        crosses = build_fx_crosses(currencies, date(2026, 1, 1))
        self.assertNotIn(date(2026, 9, 7), crosses["USDCAD"])
        self.assertIn(date(2026, 9, 8), crosses["USDCAD"])

    def test_spread_orientation_and_common_dates(self):
        d1, d2 = date(2026, 9, 7), date(2026, 9, 8)
        self.assertEqual(curve_spread({d2: 2.0}, {d2: 3.0})[d2], 100.0)
        self.assertEqual(rv_spread({d2: 3.0}, {d2: 4.25})[d2], -125.0)
        spread = rv_spread({d1: 3.0, d2: 3.1}, {d2: 4.0})
        self.assertEqual(set(spread), {d2})
        self.assertAlmostEqual(spread[d2], -90.0)

    def test_percentile(self):
        self.assertEqual(percentile_rank([1, 2, 3, 4], 4), 87.5)

    def test_fx_metric_orientation(self):
        metrics = fx_metrics({date(2026, 1, 1): 1.0, date(2026, 1, 2): 1.1})
        self.assertAlmostEqual(metrics["ret_1d"], 10.0)
        self.assertIsNone(metrics["ret_5d"])
        self.assertIsNone(metrics["rv_20d"])

    def test_rate_metrics_changes_and_no_fabricated_lookbacks(self):
        series = _series(date(2026, 1, 1), [4.00, 4.01, 4.10])
        metrics = rate_metrics(series)
        self.assertEqual(metrics["as_of"], "2026-01-03")
        self.assertAlmostEqual(metrics["value"], 4.10)
        self.assertAlmostEqual(metrics["bp_1d"], 9.0)
        self.assertIsNone(metrics["bp_5d"])
        self.assertIsNone(metrics["bp_1m"])

    def test_rbnz_workbook_parser(self):
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append([None, "Secondary market government bond closing yields (%pa)", None, None])
        ws.append(["Date", "2 year", "5 year", "10 year"])
        ws.append([date(2026, 9, 8), 3.6, 4.2, 4.8])
        buf = io.BytesIO()
        wb.save(buf)
        parsed = parse_rbnz_xlsx(buf.getvalue())
        self.assertEqual(parsed["2Y"][date(2026, 9, 8)], 3.6)
        self.assertEqual(parsed["10Y"][date(2026, 9, 8)], 4.8)
        local = fetch_nz_rates(date(2026, 9, 1), date(2026, 9, 17), workbook_bytes=buf.getvalue())
        self.assertEqual(local["10Y"][date(2026, 9, 8)], 4.8)

    def test_nz_rejects_html_challenge_page(self):
        with self.assertRaises(MarketStateError):
            fetch_nz_rates(date(2026, 9, 1), date(2026, 9, 17), workbook_bytes=b"<html>cloudflare</html>")

    def test_nz_blocked_still_emits_packet(self):
        start = date(2026, 8, 1)
        us = {
            "2Y": _series(start, [4.0] * 30),
            "5Y": _series(start, [4.2] * 30),
            "10Y": _series(start, [4.4] * 30),
            "30Y": _series(start, [4.7] * 30),
        }
        ca = {
            "2Y": _series(start, [2.5] * 30),
            "5Y": _series(start, [2.7] * 30),
            "10Y": _series(start, [3.0] * 30),
            "LONG": _series(start, [3.3] * 30),
        }
        au = {
            "2Y": _series(start, [3.5] * 30),
            "5Y": _series(start, [3.8] * 30),
            "10Y": _series(start, [4.1] * 30),
        }
        fx_hist = _series(start, [1.10 + i * 0.001 for i in range(30)])
        fx = {
            f"{a}{b}": dict(fx_hist)
            for i, a in enumerate(("EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "NOK", "SEK", "JPY"))
            for b in ("EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "NOK", "SEK", "JPY")[i + 1 :]
        }
        with mock.patch("scripts.market_state.fetch_us_rates", return_value=us), mock.patch(
            "scripts.market_state.fetch_ca_rates", return_value=ca
        ), mock.patch("scripts.market_state.fetch_au_rates", return_value=au), mock.patch(
            "scripts.market_state.fetch_nz_rates", side_effect=MarketStateError("RBNZ HTTP 403")
        ), mock.patch("scripts.market_state.fetch_fx", return_value=fx):
            snapshot = build_snapshot(today=date(2026, 8, 30))
        validate_snapshot(snapshot)
        self.assertEqual(snapshot["rates"]["NZ"]["status"], "unavailable")
        self.assertIn("NZ_rates", snapshot["unavailable_sources"])
        self.assertIsNone(snapshot["rate_rv"]["NZ-US_2Y"]["bps"])
        self.assertEqual(snapshot["rate_rv"]["NZ-US_2Y"]["status"], "unavailable")
        self.assertAlmostEqual(snapshot["rate_rv"]["CA-US_2Y"]["bps"], -150.0)

    def test_build_snapshot_contract_and_staleness(self):
        start = date(2026, 8, 1)
        us = {
            "2Y": _series(start, [4.0] * 30),
            "5Y": _series(start, [4.2] * 30),
            "10Y": _series(start, [4.4] * 30),
            "30Y": _series(start, [4.7] * 30),
        }
        ca = {
            "2Y": _series(start, [2.5] * 30),
            "5Y": _series(start, [2.7] * 30),
            "10Y": _series(start, [3.0] * 30),
            "LONG": _series(start, [3.3] * 30),
        }
        au = {
            "2Y": _series(start, [3.5] * 30),
            "5Y": _series(start, [3.8] * 30),
            "10Y": _series(start, [4.1] * 30),
        }
        nz = {
            "2Y": _series(start, [3.2] * 30),
            "5Y": _series(start, [3.6] * 30),
            "10Y": _series(start, [4.0] * 30),
        }
        fx_hist = _series(start, [1.10 + i * 0.001 for i in range(30)])
        fx = {f"{a}{b}": dict(fx_hist) for i, a in enumerate(("EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "NOK", "SEK", "JPY")) for b in ("EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "NOK", "SEK", "JPY")[i + 1 :]}

        with mock.patch("scripts.market_state.fetch_us_rates", return_value=us), mock.patch(
            "scripts.market_state.fetch_ca_rates", return_value=ca
        ), mock.patch("scripts.market_state.fetch_au_rates", return_value=au), mock.patch(
            "scripts.market_state.fetch_nz_rates", return_value=nz
        ), mock.patch("scripts.market_state.fetch_fx", return_value=fx):
            snapshot = build_snapshot(today=date(2026, 8, 30))

        validate_snapshot(snapshot)
        self.assertEqual(snapshot["status"], "ok")
        self.assertEqual(snapshot["stale_sources"], [])
        self.assertEqual(snapshot["method"]["fx_pair_count"], 45)
        self.assertEqual(snapshot["method"]["rate_rv_count"], 15)
        self.assertEqual(snapshot["method"]["credentials_required"], [])
        self.assertEqual(snapshot["method"]["fx_source"], "ecb_euro_reference_crosses")
        self.assertEqual(snapshot["method"]["model_calls"], 0)
        self.assertIn("30Y", snapshot["rates"]["US"]["tenors"])
        self.assertIn("LONG", snapshot["rates"]["CA"]["tenors"])
        self.assertIn("2s10s", snapshot["rates"]["US"]["curves"])
        self.assertIn("CA-US_2Y", snapshot["rate_rv"])
        self.assertEqual(snapshot["sources"]["FX"]["url"].startswith("https://www.ecb.europa.eu"), True)
        self.assertNotIn("TWELVE_DATA", str(snapshot))

        with mock.patch("scripts.market_state.fetch_us_rates", return_value=us), mock.patch(
            "scripts.market_state.fetch_ca_rates", return_value=ca
        ), mock.patch("scripts.market_state.fetch_au_rates", return_value=au), mock.patch(
            "scripts.market_state.fetch_nz_rates", return_value=nz
        ), mock.patch("scripts.market_state.fetch_fx", return_value=fx):
            stale = build_snapshot(today=date(2026, 9, 6))
        self.assertEqual(stale["status"], "stale")
        self.assertIn("US_rates", stale["stale_sources"])
        self.assertIn("FX", stale["stale_sources"])

        with mock.patch("scripts.market_state.fetch_us_rates", return_value=us), mock.patch(
            "scripts.market_state.fetch_ca_rates", return_value=ca
        ), mock.patch("scripts.market_state.fetch_au_rates", return_value=au), mock.patch(
            "scripts.market_state.fetch_nz_rates", return_value=nz
        ), mock.patch("scripts.market_state.fetch_fx", return_value=fx):
            with self.assertRaises(MarketStateError):
                build_snapshot(today=date(2026, 8, 30) + timedelta(days=FAIL_AFTER_DAYS + 2))


if __name__ == "__main__":
    unittest.main()
