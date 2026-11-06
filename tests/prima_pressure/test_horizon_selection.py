"""Deterministic tests for Brent 12m/24m horizon listed-contract selection."""

from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timedelta, timezone

from scripts.prima_pressure.contract import PATH_PERSISTENCE_PCT, contract_symbol
from scripts.prima_pressure.curve import QUOTE_FRESHNESS_MAX_AGE_DAYS, build_curve
from scripts.prima_pressure.expiry import validate_stored_oil_row
from scripts.prima_pressure.proxy import compute_prima_proxy, compact_block
from scripts.country_detail._prima_section import render_prima_pressure_block
from tests.prima_pressure.test_active_contract import (
    NOV4_SNAPSHOT,
    _opener_for,
    _series,
    _yahoo_bytes,
)
from tests.prima_pressure.test_proxy import _stable_flat_bundle


def _daily_ramp(end: date, n: int, start: float, step: float) -> dict[date, float]:
    out: dict[date, float] = {}
    price = start
    for i in range(n):
        d = end - timedelta(days=n - i - 1)
        out[d] = price
        price += step
    return out


def _esc_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


class HorizonSelectionCurveTests(unittest.TestCase):
    def test_nov6_2026_fallback_24m_to_dec_2028_when_jan_2029_missing(self) -> None:
        as_of = date(2026, 11, 6)
        charts: dict[str, dict[date, float]] = {}
        fy, fm = 2027, 1
        end = as_of - timedelta(days=1)
        for sym, start, step in (
            (contract_symbol("BZ", 2027, 1), 82.0, 0.06),
            (contract_symbol("BZ", 2027, 4), 81.5, 0.06),
            (contract_symbol("BZ", 2027, 7), 81.0, 0.06),
            (contract_symbol("BZ", 2028, 1), 80.0, 0.06),
        ):
            charts[sym] = _daily_ramp(end, 45, start, step)
        bzf29 = contract_symbol("BZ", 2029, 1)
        bzz28 = contract_symbol("BZ", 2028, 12)
        charts[bzz28] = _daily_ramp(end, 42, 76.0, 0.08)

        seen: list[str] = []

        def opener(url: str, data: bytes | None = None) -> bytes:
            seen.append(url)
            if bzf29 in url:
                raise OSError(f"HTTP Error 404: Not Found {url}")
            for symbol, series in charts.items():
                if symbol in url:
                    return _yahoo_bytes(series, symbol=symbol)
            raise OSError(f"HTTP Error 404: Not Found {url}")

        curve = build_curve("brent_last_day", as_of, opener)
        self.assertEqual(curve["front_symbol"], contract_symbol("BZ", 2027, 1))
        self.assertEqual(curve["front_contract_month"], "2027-01")
        by_mat = {p["maturity_months"]: p for p in curve["points"]}
        p24 = by_mat[24]
        dec_series = charts[bzz28]
        last_day = max(dec_series)
        prior_day = last_day - timedelta(days=30)
        self.assertEqual(p24["symbol"], bzz28)
        self.assertEqual(p24["contract_month"], "2028-12")
        self.assertEqual(p24["maturity_months"], 24)
        self.assertEqual(p24["actual_maturity_months"], 23)
        self.assertTrue(p24.get("fallback"))
        self.assertIn(p24.get("selection"), ("nearest_listed", "farthest_viable_listed"))
        self.assertEqual(p24["target_contract_month"], "2029-01")
        self.assertEqual(p24["coverage"], "shortened")
        self.assertEqual(p24["coverage_shortfall_months"], 1)
        self.assertEqual(p24["source_kind"], "specific_listed_contract")
        self.assertEqual(p24["price"], dec_series[last_day])
        self.assertNotEqual(p24["price"], dec_series[prior_day])
        one_m = (p24.get("changes") or {}).get("1m") or {}
        self.assertEqual(one_m.get("prior_date"), prior_day.isoformat())
        self.assertAlmostEqual(one_m.get("abs"), dec_series[last_day] - dec_series[prior_day])
        self.assertEqual(p24["observation_date"], last_day.isoformat())
        self.assertTrue(p24.get("quote_fresh"))
        self.assertTrue(p24.get("active_as_of"))
        self.assertNotIn("BZZ26.NYM", str(seen))
        self.assertNotIn("BZ=F", str(seen))

        bundle = _stable_flat_bundle(as_of=as_of.isoformat())
        bundle["oil_curve"]["brent_last_day"] = curve
        proxy = compute_prima_proxy(bundle)
        shock = proxy["subcomponents"]["shock_persistence"]
        self.assertEqual(shock["direction"], "RISING")
        self.assertNotEqual(shock["direction"], "UNAVAILABLE")
        drv_24 = next(
            (
                d
                for d in shock["drivers"]
                if isinstance(d, dict) and d.get("maturity_months") == 24
            ),
            None,
        )
        self.assertIsNotNone(drv_24)
        assert drv_24 is not None
        self.assertEqual(drv_24.get("symbol"), bzz28)
        self.assertEqual(drv_24.get("actual_maturity_months"), 23)
        text = " ".join(proxy.get("largest_drivers") or [])
        self.assertIn("BZZ28.NYM", text)
        self.assertIn("23m listed", text)

        block_view = {"current": compact_block(proxy), "trend": []}
        html = render_prima_pressure_block(block_view, _esc_html)
        self.assertIn("BZZ28", html)
        self.assertIn("23m", html)
        self.assertIn("not in the Inflation score", html)

        ev = compact_block(proxy)["channel_evidence"]["shock_persistence"]
        note = ev.get("note") or ""
        self.assertIn("BZZ28.NYM", note)
        self.assertIn("2028-12", note)
        self.assertIn("23", note)
        self.assertIn("2029-01", note)

    def test_exact_jan_2029_used_when_present(self) -> None:
        as_of = date(2026, 11, 6)
        charts: dict[str, dict[date, float]] = {}
        base_syms = [
            contract_symbol("BZ", 2027, 1),
            contract_symbol("BZ", 2027, 4),
            contract_symbol("BZ", 2027, 7),
            contract_symbol("BZ", 2028, 1),
            contract_symbol("BZ", 2029, 1),
        ]
        end = as_of - timedelta(days=1)
        for i, sym in enumerate(base_syms):
            charts[sym] = _daily_ramp(end, 45, 80.0 - i * 0.5, 0.02)
        seen: list[str] = []

        def opener(url: str, data: bytes | None = None) -> bytes:
            seen.append(url)
            for symbol, series in charts.items():
                if symbol in url:
                    return _yahoo_bytes(series, symbol=symbol)
            raise FileNotFoundError(url)

        curve = build_curve("brent_last_day", as_of, opener)
        p24 = next(p for p in curve["points"] if p["maturity_months"] == 24)
        self.assertEqual(p24["symbol"], contract_symbol("BZ", 2029, 1))
        self.assertFalse(p24.get("fallback", False))
        self.assertEqual(p24.get("selection"), "exact")
        self.assertEqual(p24.get("actual_maturity_months"), 24)
        self.assertNotIn(contract_symbol("BZ", 2028, 12), seen)

    def test_no_long_maturity_in_window_marks_24_missing(self) -> None:
        as_of = date(2026, 11, 6)
        charts: dict[str, dict[date, float]] = {}
        for sym in (
            contract_symbol("BZ", 2027, 1),
            contract_symbol("BZ", 2027, 4),
            contract_symbol("BZ", 2027, 7),
            contract_symbol("BZ", 2028, 1),
        ):
            charts[sym] = _series(as_of - timedelta(days=1), 45, 80.0)
        seen: list[str] = []

        def opener(url: str, data: bytes | None = None) -> bytes:
            seen.append(url)
            for symbol, series in charts.items():
                if symbol in url:
                    return _yahoo_bytes(series, symbol=symbol)
            raise OSError("404")

        curve = build_curve("brent_last_day", as_of, opener)
        self.assertIn(
            "no_economically_meaningful_long_maturity",
            (curve.get("missing_maturity_reasons") or {}).get("24", ""),
        )
        proxy = compute_prima_proxy(
            _stable_flat_bundle(
                as_of=as_of.isoformat(),
                oil_curve={"brent_last_day": curve, "wti": {"points": []}},
            )
        )
        shock = proxy["subcomponents"]["shock_persistence"]
        self.assertEqual(shock["direction"], "UNAVAILABLE")
        self.assertIn("no_economically_meaningful_long_maturity", shock.get("note") or "")

    def test_expired_bzz26_not_fetched_in_horizon_search(self) -> None:
        as_of = date(2026, 11, 6)
        bzz26 = contract_symbol("BZ", 2026, 12)
        charts = {
            contract_symbol("BZ", 2027, 1): _series(as_of - timedelta(days=1), 40, 82.0),
            contract_symbol("BZ", 2027, 4): _series(as_of - timedelta(days=1), 40, 81.0),
            contract_symbol("BZ", 2027, 7): _series(as_of - timedelta(days=1), 40, 80.0),
            contract_symbol("BZ", 2028, 1): _series(as_of - timedelta(days=1), 40, 79.0),
            contract_symbol("BZ", 2029, 1): _series(as_of - timedelta(days=1), 40, 76.0),
        }
        # Include chart data for expired month — opener must not be called for it.
        charts[bzz26] = _series(date(2026, 10, 30), 40, 99.0)
        seen: list[str] = []

        def opener(url: str, data: bytes | None = None) -> bytes:
            seen.append(url)
            for symbol, series in charts.items():
                if symbol in url:
                    return _yahoo_bytes(series, symbol=symbol)
            raise OSError("404")

        build_curve("brent_last_day", as_of, opener)
        self.assertFalse(any(bzz26 in u for u in seen))

    def test_stale_exact_24m_prefers_fresh_dec_2028(self) -> None:
        as_of = date(2026, 11, 6)
        bzf29 = contract_symbol("BZ", 2029, 1)
        bzz28 = contract_symbol("BZ", 2028, 12)
        stale_day = as_of - timedelta(days=QUOTE_FRESHNESS_MAX_AGE_DAYS + 1)
        charts = {
            contract_symbol("BZ", 2027, 1): _series(as_of - timedelta(days=1), 40, 82.0),
            contract_symbol("BZ", 2027, 4): _series(as_of - timedelta(days=1), 40, 81.0),
            contract_symbol("BZ", 2027, 7): _series(as_of - timedelta(days=1), 40, 80.0),
            contract_symbol("BZ", 2028, 1): _series(as_of - timedelta(days=1), 40, 79.0),
            bzf29: _series(stale_day, 40, 76.0),
            bzz28: _daily_ramp(as_of - timedelta(days=1), 40, 75.0, 0.04),
        }

        curve = build_curve("brent_last_day", as_of, _opener_for(charts))
        p24 = next(p for p in curve["points"] if p["maturity_months"] == 24)
        self.assertEqual(p24["symbol"], bzz28)
        self.assertNotEqual(p24["price"], 76.0)
        self.assertEqual(p24.get("target_status"), "stale_active_quote")

    def test_fresh_exact_24m_five_bars_prefers_neighbor_with_1m(self) -> None:
        as_of = date(2026, 11, 6)
        bzf29 = contract_symbol("BZ", 2029, 1)
        bzz28 = contract_symbol("BZ", 2028, 12)
        charts = {
            contract_symbol("BZ", 2027, 1): _series(as_of - timedelta(days=1), 40, 82.0),
            contract_symbol("BZ", 2027, 4): _series(as_of - timedelta(days=1), 40, 81.0),
            contract_symbol("BZ", 2027, 7): _series(as_of - timedelta(days=1), 40, 80.0),
            contract_symbol("BZ", 2028, 1): _series(as_of - timedelta(days=1), 40, 79.0),
            bzf29: _series(as_of - timedelta(days=1), 5, 76.0),
            bzz28: _daily_ramp(as_of - timedelta(days=1), 40, 74.0, 0.05),
        }
        curve = build_curve("brent_last_day", as_of, _opener_for(charts))
        p24 = next(p for p in curve["points"] if p["maturity_months"] == 24)
        self.assertEqual(p24["symbol"], bzz28)

    def test_exact_24m_five_bars_no_neighbor_unavailable_not_stable(self) -> None:
        as_of = date(2026, 11, 6)
        bzf29 = contract_symbol("BZ", 2029, 1)
        charts = {
            contract_symbol("BZ", 2027, 1): _series(as_of - timedelta(days=1), 40, 82.0),
            contract_symbol("BZ", 2027, 4): _series(as_of - timedelta(days=1), 40, 81.0),
            contract_symbol("BZ", 2027, 7): _series(as_of - timedelta(days=1), 40, 80.0),
            contract_symbol("BZ", 2028, 1): _series(as_of - timedelta(days=1), 40, 79.0),
            bzf29: _series(as_of - timedelta(days=1), 5, 76.0),
        }

        def opener(url: str, data: bytes | None = None) -> bytes:
            for symbol, series in charts.items():
                if symbol in url:
                    return _yahoo_bytes(series, symbol=symbol)
            raise OSError("404 Not Found")

        curve = build_curve("brent_last_day", as_of, opener)
        p24 = next(p for p in curve["points"] if p["maturity_months"] == 24)
        self.assertEqual(p24["symbol"], bzf29)
        self.assertIsNone((p24.get("changes") or {}).get("1m"))
        proxy = compute_prima_proxy(
            _stable_flat_bundle(
                as_of=as_of.isoformat(),
                oil_curve={"brent_last_day": curve, "wti": {"points": []}},
            )
        )
        self.assertEqual(proxy["subcomponents"]["shock_persistence"]["direction"], "UNAVAILABLE")

    def test_saturday_as_of_still_fresh(self) -> None:
        as_of = date(2026, 11, 7)
        charts: dict[str, dict[date, float]] = {}
        fy, fm = 2027, 1
        charts[contract_symbol("BZ", 2027, 1)] = _series(date(2026, 11, 6), 40, 82.0)
        charts[contract_symbol("BZ", 2027, 4)] = _series(date(2026, 11, 6), 40, 81.0)
        charts[contract_symbol("BZ", 2027, 7)] = _series(date(2026, 11, 6), 40, 80.0)
        charts[contract_symbol("BZ", 2028, 1)] = _daily_ramp(date(2026, 11, 6), 40, 79.0, 0.02)
        bzf29 = contract_symbol("BZ", 2029, 1)
        bzz28 = contract_symbol("BZ", 2028, 12)
        charts[bzz28] = _daily_ramp(date(2026, 11, 6), 40, 75.0, 0.03)

        seen: list[str] = []

        def opener(url: str, data: bytes | None = None) -> bytes:
            seen.append(url)
            if bzf29 in url:
                raise OSError("404")
            for symbol, series in charts.items():
                if symbol in url:
                    return _yahoo_bytes(series, symbol=symbol)
            raise OSError("404")

        curve = build_curve("brent_last_day", as_of, opener)
        p24 = next(p for p in curve["points"] if p["maturity_months"] == 24)
        self.assertEqual(p24["symbol"], bzz28)

    def test_summer_bank_holiday_does_not_fetch_expired_october(self) -> None:
        """31 Aug 2026 is an England-and-Wales bank holiday. Oct-2026 Brent expired 28 Aug."""
        as_of = date(2026, 8, 31)
        expired = contract_symbol("BZ", 2026, 10)
        front = contract_symbol("BZ", 2026, 11)
        charts = {
            front: _series(date(2026, 8, 28), 40, 80.0),
            contract_symbol("BZ", 2027, 2): _series(date(2026, 8, 28), 40, 79.0),
            contract_symbol("BZ", 2027, 5): _series(date(2026, 8, 28), 40, 78.0),
            contract_symbol("BZ", 2027, 11): _series(date(2026, 8, 28), 40, 77.0),
            contract_symbol("BZ", 2028, 11): _series(date(2026, 8, 28), 40, 74.0),
            expired: _series(date(2026, 8, 28), 40, 120.0),
        }
        seen: list[str] = []

        def opener(url: str, data: bytes | None = None) -> bytes:
            seen.append(url)
            for symbol, series in charts.items():
                if symbol in url:
                    return _yahoo_bytes(series, symbol=symbol)
            raise OSError("404")

        curve = build_curve("brent_last_day", as_of, opener)
        self.assertEqual(curve["front_symbol"], front)
        self.assertEqual(curve["front_contract_month"], "2026-11")
        self.assertFalse(any(expired in url for url in seen))
        symbols = {point["symbol"] for point in curve["points"]}
        self.assertNotIn(expired, symbols)
        self.assertIn(contract_symbol("BZ", 2028, 11), symbols)

    def test_monday_nov2_2026_no_bzz26_front_bzf27(self) -> None:
        as_of = date(2026, 11, 2)
        charts = {
            contract_symbol("BZ", 2027, 1): _series(as_of - timedelta(days=1), 40, 82.0),
            contract_symbol("BZ", 2027, 4): _series(as_of - timedelta(days=1), 40, 81.0),
            contract_symbol("BZ", 2027, 7): _series(as_of - timedelta(days=1), 40, 80.0),
            contract_symbol("BZ", 2028, 1): _series(as_of - timedelta(days=1), 40, 79.0),
            contract_symbol("BZ", 2029, 1): _series(as_of - timedelta(days=1), 40, 76.0),
        }
        charts[contract_symbol("BZ", 2026, 12)] = _series(date(2026, 10, 30), 40, 120.0)
        seen: list[str] = []

        def opener(url: str, data: bytes | None = None) -> bytes:
            seen.append(url)
            for symbol, series in charts.items():
                if symbol in url:
                    return _yahoo_bytes(series, symbol=symbol)
            raise OSError("404")

        curve = build_curve("brent_last_day", as_of, opener)
        self.assertEqual(curve["front_symbol"], contract_symbol("BZ", 2027, 1))
        self.assertFalse(any(contract_symbol("BZ", 2026, 12) in u for u in seen))

    def test_legacy_row_without_selection_stays_misanchored(self) -> None:
        before = NOV4_SNAPSHOT.read_bytes()
        row = {
            "symbol": "BZZ28.NYM",
            "contract_month": "2028-12",
            "maturity_months": 24,
        }
        r = validate_stored_oil_row(row, date(2026, 11, 4))
        self.assertFalse(r["valid"])
        self.assertIn("misanchored_maturity", r["reasons"])
        self.assertEqual(NOV4_SNAPSHOT.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
