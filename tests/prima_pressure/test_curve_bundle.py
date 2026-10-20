"""Unit tests for prima_pressure curve, producer, MPR, and bundle."""

from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timedelta, timezone

from scripts.prima_pressure.bundle import build_observation_bundle
from scripts.prima_pressure.contract import (
    PRODUCER_SERIES,
    STATCAN_WDS_DATA_URL,
    contract_symbol,
)
from scripts.prima_pressure.curve import build_curve, build_refinery_margin
from scripts.prima_pressure.mpr import build_mpr_comparison
from scripts.prima_pressure.producer import build_producer_prices


def _yahoo_bytes(closes_by_date: dict[date, float]) -> bytes:
    dates = sorted(closes_by_date)
    timestamps = [int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()) for d in dates]
    closes = [closes_by_date[d] for d in dates]
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": timestamps,
                    "indicators": {"quote": [{"close": closes}]},
                }
            ]
        }
    }
    return json.dumps(payload).encode("utf-8")


def _daily_series(end: date, n: int, start_price: float, step: float = 0.0) -> dict[date, float]:
    out: dict[date, float] = {}
    price = start_price
    for i in range(n):
        d = end - timedelta(days=n - i)
        out[d] = price
        price += step
    return out


class CurveBundleTests(unittest.TestCase):
    def test_missing_twelve_month_not_filled_from_front(self):
        as_of = date(2026, 10, 20)
        front_y, front_m = 2026, 11
        front_symbol = contract_symbol("BZ", front_y, front_m)
        front_end = as_of - timedelta(days=1)
        charts = {front_symbol: _daily_series(front_end, 40, 80.0)}

        def opener(url: str, data: bytes | None = None) -> bytes:
            if data is not None:
                raise AssertionError("unexpected POST")
            for sym, series in charts.items():
                if sym in url:
                    return _yahoo_bytes(series)
            raise FileNotFoundError(url)

        curve = build_curve("brent_last_day", as_of, opener)
        self.assertIn(12, curve["missing_maturities"])
        self.assertIsNone(curve["slopes_usd"]["12m_minus_front"])
        by_mat = {p["maturity_months"]: p for p in curve["points"]}
        self.assertIn(0, by_mat)
        self.assertNotIn(12, by_mat)
        if 0 in by_mat and 12 not in by_mat:
            self.assertNotEqual(by_mat[0]["price"], None)

    def test_full_brent_strip_slopes(self):
        as_of = date(2026, 10, 20)
        front_y, front_m = 2026, 11
        maturities = {0: 70.0, 3: 71.0, 6: 72.0, 12: 80.0, 24: 90.0}
        charts: dict[str, dict[date, float]] = {}
        from scripts.prima_pressure.contract import add_months

        for maturity, price in maturities.items():
            y, m = add_months(front_y, front_m, maturity)
            sym = contract_symbol("BZ", y, m)
            charts[sym] = _daily_series(as_of - timedelta(days=1), 5, price)

        def opener(url: str, data: bytes | None = None) -> bytes:
            for sym, series in charts.items():
                if sym in url:
                    return _yahoo_bytes(series)
            raise FileNotFoundError(url)

        curve = build_curve("brent_last_day", as_of, opener)
        by_mat = {p["maturity_months"]: p for p in curve["points"]}
        self.assertEqual(by_mat[12]["price"], 80.0)
        self.assertEqual(by_mat[24]["price"], 90.0)
        self.assertEqual(curve["slopes_usd"]["24m_minus_front"], 20.0)

    def test_no_continuous_symbols_requested(self):
        as_of = date(2026, 10, 10)
        seen: list[str] = []

        def opener(url: str, data: bytes | None = None) -> bytes:
            seen.append(url)
            if "BZ=F" in url or "CL=F" in url:
                raise AssertionError("continuous symbol requested")
            if ".NYM" not in url:
                raise FileNotFoundError(url)
            # minimal single-bar response for any listed contract
            return _yahoo_bytes(_daily_series(as_of - timedelta(days=1), 3, 75.0))

        build_curve("brent_last_day", as_of, opener)
        build_curve("wti", as_of, opener)
        for url in seen:
            self.assertIn(".NYM", url)
            self.assertNotIn("BZ=F", url)
            self.assertNotIn("CL=F", url)

    def test_producer_parser_roles_and_sector_gap(self):
        as_of = date(2026, 10, 20)

        def wds_payload(vid: int, value: float) -> dict:
            return {
                "status": "SUCCESS",
                "object": {
                    "vectorId": vid,
                    "vectorDataPoint": [
                        {
                            "refPer": "2026-08-01",
                            "value": value - 0.5,
                            "releaseTime": "2026-09-04T08:30",
                        },
                        {
                            "refPer": "2026-09-01",
                            "value": value,
                            "releaseTime": "2026-10-04T08:30",
                        },
                    ],
                },
            }

        def opener(url: str, data: bytes | None = None) -> bytes:
            self.assertIsNotNone(data)
            req = json.loads(data.decode("utf-8"))
            blocks = []
            for item in req:
                blocks.append(wds_payload(int(item["vectorId"]), 120.0))
            return json.dumps(blocks).encode("utf-8")

        out = build_producer_prices(as_of, opener)
        self.assertEqual(out["sector_ppi"]["status"], "unavailable")
        by_id = {row["series_id"]: row for row in out["series"]}
        self.assertEqual(by_id["ippi_ex_energy"]["channel_role"], "production_network_fallback")
        self.assertEqual(by_id["rmpi_ex_crude_energy"]["channel_role"], "imported_pressure_fallback")
        self.assertEqual(by_id["ippi_energy"]["channel_role"], "context_only_energy")
        self.assertEqual(by_id["rmpi_crude_energy"]["channel_role"], "context_only_crude_energy")

    def test_mpr_brent_2027_12_and_front_only_bundle(self):
        oil_full = {
            "brent_last_day": {
                "points": [
                    {"maturity_months": 0, "contract_month": "2026-11", "price": 75.0},
                    {"maturity_months": 12, "contract_month": "2027-12", "price": 80.0},
                ]
            },
            "wti": {"points": []},
        }
        mpr = build_mpr_comparison(oil_full, as_of=date(2026, 10, 20))
        leg = next(l for l in mpr["legs"] if l["leg"] == "brent_end_2027_vs_prose")
        self.assertEqual(leg["status"], "ok")
        self.assertEqual(leg["delta_usd_bbl"], 10.0)

        oil_front_only = {
            "brent_last_day": {
                "points": [{"maturity_months": 0, "contract_month": "2026-11", "price": 75.0}]
            },
            "wti": {"points": []},
        }
        mpr2 = build_mpr_comparison(oil_front_only, as_of=date(2026, 10, 20))
        leg2 = next(l for l in mpr2["legs"] if l["leg"] == "brent_end_2027_vs_prose")
        self.assertEqual(leg2["status"], "unavailable")

    def test_offline_bundle_zero_opener_calls(self):
        calls = 0

        def opener(url: str, data: bytes | None = None) -> bytes:
            nonlocal calls
            calls += 1
            return b"{}"

        bundle = build_observation_bundle(date(2026, 10, 20), allow_network=False, opener=None)
        self.assertEqual(calls, 0)
        self.assertEqual(bundle["oil_curves"]["brent_last_day"]["status"], "unavailable")
        self.assertEqual(bundle["producer_prices"]["sector_ppi"]["status"], "unavailable")

    def test_refinery_crack_missing_rbob(self):
        as_of = date(2026, 10, 20)
        wti_curve = {
            "points": [
                {
                    "maturity_months": 0,
                    "contract_month": "2026-11",
                    "symbol": contract_symbol("CL", 2026, 11),
                    "price": 70.0,
                    "observation_date": "2026-10-19",
                }
            ]
        }
        ho_sym = contract_symbol("HO", 2026, 11)

        def opener(url: str, data: bytes | None = None) -> bytes:
            if ho_sym in url:
                return _yahoo_bytes(_daily_series(as_of - timedelta(days=1), 2, 2.0))
            raise FileNotFoundError(url)

        margin = build_refinery_margin(as_of, wti_curve, opener)
        self.assertNotIn("gasoline_crack_usd_per_bbl", margin)
        self.assertEqual(margin["gasoline_crack_status"], "unavailable")
        self.assertAlmostEqual(margin["heating_oil_crack_usd_per_bbl"], 2.0 * 42 - 70.0)

    def test_fetch_error_is_visible_and_does_not_walk_the_strip(self) -> None:
        as_of = date(2026, 10, 20)
        seen: list[str] = []

        def opener(url: str, data: bytes | None = None) -> bytes:
            seen.append(url)
            raise OSError("HTTP Error 429: Too Many Requests")

        curve = build_curve("brent_last_day", as_of, opener)
        self.assertEqual(curve["status"], "unavailable")
        self.assertIn("429", curve["error"])
        self.assertEqual(curve["points"], [])
        self.assertEqual(len(seen), 1)
        self.assertNotIn("BZ=F", seen[0])


if __name__ == "__main__":
    unittest.main()
