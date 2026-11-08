#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.asx_eod import (
    ASX_EOD_TEMPLATE,
    SYDNEY,
    acquire_asx_cash_futures,
    bbsw_ois_basis_evidence,
    expected_latest_published_session,
    ib_last_trading_day,
    ir_last_trading_day,
    ir_settlement_day,
    legacy_ib_rows,
    parse_asx_eod_products,
)
from scripts.asx_eod_runner_probe import evaluate_probe_payload
from scripts.asx_futures_cache import save_product

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "asx"


def _load(name: str) -> str:
    return FIXTURES.joinpath(name).read_bytes().decode("utf-8", errors="replace")


class ExpectedPublishedSessionTests(unittest.TestCase):
    def test_sunday_noon_expects_friday(self) -> None:
        now = datetime(2026, 11, 8, 12, 0, tzinfo=SYDNEY)
        self.assertEqual(expected_latest_published_session(now), date(2026, 11, 6))

    def test_friday_holiday_expects_thursday(self) -> None:
        now = datetime(2026, 11, 8, 12, 0, tzinfo=SYDNEY)
        extra = frozenset({date(2026, 11, 6)})
        self.assertEqual(
            expected_latest_published_session(now, extra_holidays=extra),
            date(2026, 11, 5),
        )

    def test_monday_morning_still_friday(self) -> None:
        now = datetime(2026, 11, 9, 5, 30, tzinfo=SYDNEY)
        self.assertEqual(expected_latest_published_session(now), date(2026, 11, 6))

    def test_tuesday_morning_before_monday_publication(self) -> None:
        now = datetime(2026, 11, 10, 5, 30, tzinfo=SYDNEY)
        self.assertEqual(expected_latest_published_session(now), date(2026, 11, 6))

    def test_tuesday_after_monday_publication(self) -> None:
        now = datetime(2026, 11, 10, 7, 0, tzinfo=SYDNEY)
        self.assertEqual(expected_latest_published_session(now), date(2026, 11, 9))

    def test_monday_evening_still_friday(self) -> None:
        now = datetime(2026, 11, 9, 18, 0, tzinfo=SYDNEY)
        self.assertEqual(expected_latest_published_session(now), date(2026, 11, 6))


class AsxEodParserTests(unittest.TestCase):
    def test_nov6_ir_settlements_and_session(self) -> None:
        parsed = parse_asx_eod_products(
            _load("EODWebMarketSummary261106SFD.htm"),
            source_url=ASX_EOD_TEMPLATE.format(yymmdd="261106"),
        )
        self.assertEqual(parsed["session_date"], "2026-11-06")
        self.assertEqual(parsed["publication_time"], "2026-11-07T05:26:00")
        self.assertIsNone(parsed["document_error"])
        ir = parsed["products"]["IR"]
        self.assertEqual(ir["status"], "ok")
        self.assertEqual(len(ir["raw_contracts"]), 18)
        by_expiry = {r["expiry"]: r for r in ir["raw_contracts"]}
        dec = by_expiry["2026-12"]
        self.assertEqual(dec["price"], 95.05)
        self.assertEqual(dec["open_interest"], 418277.0)
        self.assertEqual(dec["volume"], 35082.0)
        self.assertEqual(dec["implied_rate"], 4.95)
        self.assertEqual(by_expiry["2027-03"]["implied_rate"], 4.96)
        self.assertEqual(by_expiry["2027-06"]["implied_rate"], 4.88)
        self.assertEqual(by_expiry["2027-09"]["implied_rate"], 4.77)
        self.assertEqual(by_expiry["2027-12"]["implied_rate"], 4.67)
        nov = by_expiry["2026-11"]
        self.assertIsNone(nov["open"])
        self.assertIsNone(nov["volume"])
        self.assertIsNone(nov["open_interest"])
        self.assertEqual(nov["price"], 95.23)
        jan = by_expiry["2027-01"]
        self.assertFalse(jan["tradable"])
        self.assertEqual(jan["exclusion_reason"], "illiquid_serial")

    def test_nov5_dec_settlement(self) -> None:
        parsed = parse_asx_eod_products(_load("EODWebMarketSummary261105SFD.htm"))
        self.assertEqual(parsed["session_date"], "2026-11-05")
        ir = parsed["products"]["IR"]
        dec = next(r for r in ir["raw_contracts"] if r["expiry"] == "2026-12")
        self.assertEqual(dec["price"], 95.03)
        self.assertEqual(dec["implied_rate"], 4.97)

    def test_serial_filter_and_quarterly_strip(self) -> None:
        parsed = parse_asx_eod_products(_load("EODWebMarketSummary261106SFD.htm"))
        ir = parsed["products"]["IR"]
        nov = next(r for r in ir["raw_contracts"] if r["expiry"] == "2026-11")
        self.assertFalse(nov["tradable"])
        self.assertEqual(nov["exclusion_reason"], "illiquid_serial")
        self.assertTrue(all(r["tradable"] for r in ir["contracts"] if r["listing_role"] == "quarterly"))
        sep2030 = next(r for r in ir["raw_contracts"] if r["expiry"] == "2030-09")
        self.assertEqual(sep2030["listing_role"], "quarterly")
        self.assertTrue(sep2030["tradable"])

    def test_url_session_mismatch_rejected_in_acquire(self) -> None:
        bodies: dict[str, bytes] = {
            ASX_EOD_TEMPLATE.format(yymmdd="261108"): _load("EODWebMarketSummary261106SFD.htm").encode(),
        }

        def fetch_bytes(url: str, **kwargs: object) -> bytes:
            if url in bodies:
                return bodies[url]
            raise FileNotFoundError(url)

        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/cache.json"
            result = acquire_asx_cash_futures(
                fetch_bytes,
                today=date(2026, 11, 8),
                cache_path=path,
                lookback_days=3,
            )
        self.assertIsNotNone(result["fetch_error"])
        self.assertEqual(result["products"]["IR"]["status"], "unavailable")

    def test_sunday_lookback_uses_friday_session(self) -> None:
        friday_url = ASX_EOD_TEMPLATE.format(yymmdd="261106")

        def fetch_bytes(url: str, **kwargs: object) -> bytes:
            if url == friday_url:
                return _load("EODWebMarketSummary261106SFD.htm").encode()
            raise FileNotFoundError(url)

        with tempfile.TemporaryDirectory() as tmp:
            result = acquire_asx_cash_futures(
                fetch_bytes,
                today=date(2026, 11, 8),
                cache_path=f"{tmp}/cache.json",
            )
        self.assertEqual(result["session_date"], "2026-11-06")
        self.assertEqual(result["products"]["IR"]["freshness"], "current")
        self.assertTrue(result["products"]["IR"]["execution_eligible"])
        self.assertEqual(result["products"]["IR"]["as_of"], "2026-11-06")

    def test_sunday_thursday_only_is_stale(self) -> None:
        thursday_url = ASX_EOD_TEMPLATE.format(yymmdd="261105")

        def fetch_bytes(url: str, **kwargs: object) -> bytes:
            if url == thursday_url:
                return _load("EODWebMarketSummary261105SFD.htm").encode()
            raise FileNotFoundError(url)

        with tempfile.TemporaryDirectory() as tmp:
            result = acquire_asx_cash_futures(
                fetch_bytes,
                today=date(2026, 11, 8),
                cache_path=f"{tmp}/cache.json",
            )
        ir = result["products"]["IR"]
        self.assertEqual(ir["status"], "stale")
        self.assertEqual(ir["freshness"], "stale")
        self.assertFalse(ir["execution_eligible"])
        self.assertEqual(ir["as_of"], "2026-11-05")
        dec = next(r for r in ir["contracts"] if r["expiry"] == "2026-12")
        self.assertAlmostEqual(dec["implied_rate"], 4.97)

    def test_friday_cache_on_sunday_stays_stale_not_current(self) -> None:
        def fetch_bytes(url: str, **kwargs: object) -> bytes:
            raise ConnectionError("down")

        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/cache.json"
            for product in ("IB", "IR"):
                save_product(
                    path,
                    product,
                    {
                        "session_date": "2026-11-06",
                        "as_of": "2026-11-06",
                        "source_url": "https://example.test",
                        "contracts": [
                            {
                                "expiry": "2026-12",
                                "price": 95.05 if product == "IR" else 95.6,
                                "implied_rate": 4.95 if product == "IR" else 4.4,
                                "as_of": "2026-11-06",
                            }
                        ],
                    },
                )
            result = acquire_asx_cash_futures(
                fetch_bytes,
                today=date(2026, 11, 8),
                cache_path=path,
            )
        for product in ("IB", "IR"):
            block = result["products"][product]
            self.assertEqual(block["status"], "stale")
            self.assertEqual(block["freshness"], "stale")
            self.assertFalse(block["execution_eligible"])
            self.assertEqual(block["provenance"], "last_good_cache")

    def test_expired_contract(self) -> None:
        html = _load("EODWebMarketSummary261106SFD.htm")
        parsed = parse_asx_eod_products(html)
        ir = parsed["products"]["IR"]
        dec = next(r for r in ir["raw_contracts"] if r["expiry"] == "2026-12")
        session_after = parse_asx_eod_products(
            html.replace("06/11/26", "15/12/26").replace("06/11/26", "15/12/26"),
        )
        dec2 = next(r for r in session_after["products"]["IR"]["raw_contracts"] if r["expiry"] == "2026-12")
        self.assertFalse(dec2["tradable"])
        self.assertEqual(dec2["exclusion_reason"], "expired")
        self.assertTrue(dec["tradable"])

    def test_calendar_last_trading_days(self) -> None:
        self.assertEqual(ir_settlement_day("2026-11"), date(2026, 11, 13))
        self.assertEqual(ir_last_trading_day("2026-11"), date(2026, 11, 12))
        self.assertEqual(ir_settlement_day("2026-12"), date(2026, 12, 11))
        self.assertEqual(ir_last_trading_day("2026-12"), date(2026, 12, 10))
        from scripts.asx_eod import _is_business_day

        self.assertFalse(_is_business_day(date(2026, 4, 3)))
        self.assertFalse(_is_business_day(date(2026, 4, 6)))

    def test_holiday_walkback_with_extra_set(self) -> None:
        extra = frozenset({date(2026, 11, 12)})
        self.assertEqual(ir_last_trading_day("2026-11", extra_holidays=extra), date(2026, 11, 11))

    def test_ib_only_and_ir_only_sections(self) -> None:
        base = """
        <html><head><title>close of trade date 06/11/26</title></head><body>
        close of trade date 06/11/26
        <table>
        <tr><td>IB - 30 Day Interbank Cash Rate</td></tr>
        <tr><td>Expiry</td><td>Open</td><td>High</td><td>Low</td><td>Last</td><td>Sett</td>
        <td>Sett Chg</td><td>Op Int</td><td>Op Int Chg</td><td>Volume</td></tr>
        <tr><td>Dec 2026</td><td>-</td><td>-</td><td>-</td><td>-</td><td>95.60</td>
        <td>-</td><td>1</td><td>-</td><td>2</td></tr>
        </table></body></html>
        """
        ib_only = parse_asx_eod_products(base, benchmark=4.35)
        self.assertEqual(ib_only["products"]["IB"]["status"], "ok")
        self.assertEqual(ib_only["products"]["IR"]["status"], "unavailable")

        ir_html = base.replace("IB - 30 Day", "XX - Dummy").replace(
            "XX - Dummy", "IR - 90-Day Bank Bills (100 minus yield % p.a.)"
        )
        # inject IR marker properly
        ir_html = base.replace(
            "IB - 30 Day Interbank Cash Rate",
            "IR - 90-Day Bank Bills (100 minus yield % p.a.)",
        ).replace("Dec 2026", "Mar 2027")
        ir_only = parse_asx_eod_products(ir_html)
        self.assertEqual(ir_only["products"]["IR"]["status"], "ok")
        self.assertEqual(ir_only["products"]["IB"]["status"], "unavailable")

    def test_ir_exception_does_not_drop_ib(self) -> None:
        html = _load("EODWebMarketSummary261106SFD.htm")
        # Corrupt one IR settlement cell to non-numeric while keeping IB intact.
        html = html.replace(
            "<TD align=\"right\">95.040</TD><TD align=\"right\">0.040</TD><TD align=\"right\">437,033</TD>",
            "<TD align=\"right\">BAD</TD><TD align=\"right\">0.040</TD><TD align=\"right\">437,033</TD>",
            1,
        )
        parsed = parse_asx_eod_products(html, benchmark=4.35)
        self.assertEqual(parsed["products"]["IB"]["status"], "ok")
        self.assertGreater(len(parsed["products"]["IB"]["contracts"]), 0)
        ir = parsed["products"]["IR"]
        self.assertEqual(ir["status"], "ok")
        mar = next(r for r in ir["raw_contracts"] if r["expiry"] == "2027-03")
        self.assertIsNone(mar["implied_rate"])

    def test_missing_trade_date(self) -> None:
        html = "<html><body><table><tr><td>IB - 30 Day Interbank Cash Rate</td></tr></table></body></html>"
        parsed = parse_asx_eod_products(html)
        self.assertIn("missing the trade date", parsed["document_error"] or "")
        self.assertEqual(parsed["products"]["IB"]["status"], "unavailable")

    def test_title_body_trade_date_mismatch(self) -> None:
        html = _load("EODWebMarketSummary261106SFD.htm")
        html = html.replace("<title>", "<title>MISMATCH close of trade date 05/11/26 ", 1)
        parsed = parse_asx_eod_products(html)
        self.assertIsNotNone(parsed["document_error"])

    def test_network_outage_no_cache(self) -> None:
        def fetch_bytes(url: str, **kwargs: object) -> bytes:
            raise ConnectionError("down")

        with tempfile.TemporaryDirectory() as tmp:
            result = acquire_asx_cash_futures(
                fetch_bytes,
                today=date(2026, 11, 8),
                cache_path=f"{tmp}/cache.json",
            )
        self.assertEqual(result["products"]["IB"]["status"], "unavailable")
        self.assertEqual(result["products"]["IR"]["status"], "unavailable")
        self.assertEqual(result["products"]["IB"]["contracts"], [])

    def test_independent_cache_replay(self) -> None:
        def fetch_bytes(url: str, **kwargs: object) -> bytes:
            raise ConnectionError("down")

        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/cache.json"
            save_product(
                path,
                "IB",
                {
                    "session_date": "2026-11-06",
                    "as_of": "2026-11-06",
                    "source_url": "https://example.test",
                    "contracts": [
                        {
                            "expiry": "2026-12",
                            "price": 95.6,
                            "implied_rate": 4.4,
                            "as_of": "2026-11-06",
                        }
                    ],
                },
            )
            result = acquire_asx_cash_futures(
                fetch_bytes,
                today=date(2026, 11, 8),
                cache_path=path,
            )
        self.assertEqual(result["products"]["IB"]["status"], "stale")
        self.assertFalse(result["products"]["IB"]["execution_eligible"])
        self.assertEqual(result["products"]["IB"]["provenance"], "last_good_cache")
        self.assertEqual(result["products"]["IR"]["status"], "unavailable")
        self.assertEqual(result["products"]["IR"]["contracts"], [])

    def test_success_ir_does_not_erase_ib_cache_without_ib_section(self) -> None:
        html = _load("EODWebMarketSummary261106SFD.htm")
        html = html.replace("IB - 30 Day Interbank Cash Rate", "IB - REMOVED PRODUCT")
        friday_url = ASX_EOD_TEMPLATE.format(yymmdd="261106")

        def fetch_bytes(url: str, **kwargs: object) -> bytes:
            if url == friday_url:
                return html.encode()
            raise FileNotFoundError(url)

        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/cache.json"
            save_product(
                path,
                "IB",
                {
                    "session_date": "2026-11-05",
                    "as_of": "2026-11-05",
                    "source_url": "https://example.test/ib",
                    "contracts": [
                        {
                            "expiry": "2026-12",
                            "price": 95.55,
                            "implied_rate": 4.45,
                            "as_of": "2026-11-05",
                        }
                    ],
                },
            )
            result = acquire_asx_cash_futures(
                fetch_bytes,
                today=date(2026, 11, 8),
                cache_path=path,
            )
        self.assertEqual(result["products"]["IR"]["provenance"], "asx_eod_report")
        self.assertEqual(result["products"]["IR"]["freshness"], "current")
        self.assertEqual(result["products"]["IB"]["provenance"], "last_good_cache")
        self.assertEqual(result["products"]["IB"]["as_of"], "2026-11-05")

    def test_legacy_ib_rows_matches_policy_test_html(self) -> None:
        html = """
        <table>
          <tr><td>IB - 30 Day Interbank Cash Rate (RBA Interbank Overnight Cash)</td></tr>
          <tr><th>Expiry</th><th>Open</th><th>High</th><th>Low</th><th>Last</th><th>Sett</th><th>Sett Chg</th><th>OI</th><th>OI Chg</th><th>Volume</th></tr>
          <tr><td>OCT 2026</td><td>95.50</td><td>95.70</td><td>95.40</td><td>95.60</td><td>95.60</td><td>.01</td><td>12000</td><td>10</td><td>500</td></tr>
          <tr><td>NOV 2026</td><td>95.40</td><td>95.60</td><td>95.30</td><td>95.50</td><td>95.50</td><td>.01</td><td>9000</td><td>5</td><td>350</td></tr>
        </table>
        """
        rows = legacy_ib_rows(html, benchmark=4.35)
        self.assertEqual(rows[0]["implied_rate"], 4.4)
        self.assertEqual(rows[1]["change_from_overnight_bps"], 15.0)
        self.assertIsNone(rows[0]["code"])
        with self.assertRaises(ValueError):
            legacy_ib_rows("<html></html>", benchmark=4.35)

    def test_bbsw_ois_basis_evidence_unavailable(self) -> None:
        out = bbsw_ois_basis_evidence(
            cash_basis={"status": "ok", "bank_bill_minus_ois_bps": 12.0, "as_of": "2026-11-06"},
            ir_product={"status": "ok"},
            ib_product={"status": "ok"},
        )
        self.assertEqual(out["status"], "unavailable")
        self.assertIn("not computed", out["reason"])
        self.assertNotIn("ir_minus_ib", json_dumps_safe(out))
        self.assertIn("reference", out.get("spot_3m_bank_bill_minus_ois", {}))

    def test_bbsw_basis_cross_vintage(self) -> None:
        out = bbsw_ois_basis_evidence(
            cash_basis={
                "status": "unavailable_cross_vintage",
                "ois_as_of": "2026-11-01",
                "bank_bill_as_of": "2026-11-06",
            },
            ir_product={},
            ib_product={},
        )
        self.assertEqual(out["spot_3m_bank_bill_minus_ois"]["status"], "unavailable_cross_vintage")


class AsxEodRunnerProbeTests(unittest.TestCase):
    def test_fixture_runner_probe_verified(self) -> None:
        body = _load("EODWebMarketSummary261106SFD.htm")
        url = ASX_EOD_TEMPLATE.format(yymmdd="261106")
        report = evaluate_probe_payload(
            url=url,
            http_status=200,
            body=body,
            error=None,
            expected_session=date(2026, 11, 6),
        )
        self.assertEqual(report["runner_claim"], "verified")
        self.assertEqual(report["session_date"], "2026-11-06")
        self.assertEqual(report["dec_2026_settlement"], 95.05)
        self.assertEqual(report["mar_2027_settlement"], 95.04)
        self.assertGreaterEqual(report["ir_quarterly_tradable_count"], 5)

    def test_fetch_failure_blocked(self) -> None:
        report = evaluate_probe_payload(
            url=ASX_EOD_TEMPLATE.format(yymmdd="261106"),
            http_status=None,
            body=None,
            error="timed out",
            expected_session=date(2026, 11, 6),
        )
        self.assertEqual(report["runner_claim"], "blocked_or_unconfirmed")
        self.assertIsNone(report["dec_2026_settlement"])
        self.assertIsNone(report["mar_2027_settlement"])


def json_dumps_safe(obj: object) -> str:
    import json

    return json.dumps(obj)


if __name__ == "__main__":
    unittest.main()
