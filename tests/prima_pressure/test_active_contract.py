"""Expiry-aware front selection, refinery activity, and historical quarantine."""

from __future__ import annotations

import hashlib
import json
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from scripts.prima_pressure.contract import contract_symbol
from scripts.prima_pressure.curve import (
    QUOTE_FRESHNESS_MAX_AGE_DAYS,
    build_curve,
    build_refinery_margin,
    quote_is_fresh,
)
from scripts.prima_pressure.expiry import (
    active_front_contract,
    assess_stored_shock_inputs,
    brent_final_trade_date,
    contract_is_active,
    england_wales_bank_holidays,
    is_london_business_day,
    is_nymex_business_day,
    nymex_full_closures,
    product_final_trade_date,
    wti_final_trade_date,
)
from scripts.prima_pressure.presentation import build_presentation
from scripts.prima_pressure.proxy import compute_prima_proxy
from tests.prima_pressure.test_proxy import _curve_point, _stable_flat_bundle

ROOT = Path(__file__).resolve().parents[2]
NOV4_SNAPSHOT = (
    ROOT
    / "data/overnight/runs/overnight-20261104/reviews/review-001/evidence_snapshot.json"
)


def _yahoo_bytes(closes_by_date: dict[date, float], *, symbol: str) -> bytes:
    dates = sorted(closes_by_date)
    timestamps = [
        int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()) for d in dates
    ]
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": timestamps,
                    "indicators": {"quote": [{"close": [closes_by_date[d] for d in dates]}]},
                    "meta": {"symbol": symbol, "instrumentType": "FUTURE", "exchangeName": "NYM"},
                }
            ]
        }
    }
    return json.dumps(payload).encode("utf-8")


def _series(end: date, n: int, price: float) -> dict[date, float]:
    return {end - timedelta(days=n - i): price for i in range(n)}


def _opener_for(charts: dict[str, dict[date, float]], seen: list[str] | None = None):
    def opener(url: str, data: bytes | None = None) -> bytes:
        if seen is not None:
            seen.append(url)
        for symbol, series in charts.items():
            if symbol in url:
                return _yahoo_bytes(series, symbol=symbol)
        raise OSError(f"HTTP Error 404: Not Found {url}")

    return opener


class ExpiryCalendarTests(unittest.TestCase):
    def test_brent_december_2026_expires_last_london_day_of_october(self) -> None:
        self.assertEqual(brent_final_trade_date(2026, 12), date(2026, 10, 30))
        self.assertTrue(is_london_business_day(date(2026, 10, 30)))
        self.assertFalse(is_london_business_day(date(2026, 10, 31)))

    def test_day_before_expiry_day_and_first_business_day_after(self) -> None:
        self.assertTrue(contract_is_active("BZ", 2026, 12, date(2026, 10, 29)))
        self.assertTrue(contract_is_active("BZ", 2026, 12, date(2026, 10, 30)))
        self.assertFalse(contract_is_active("BZ", 2026, 12, date(2026, 10, 31)))
        self.assertFalse(contract_is_active("BZ", 2026, 12, date(2026, 11, 2)))
        front = active_front_contract(date(2026, 11, 2), "BZ")
        self.assertEqual(front["contract_month"], "2027-01")
        self.assertEqual(front["final_trade_date"], date(2026, 11, 30))

    def test_england_wales_bank_holidays_are_not_london_business_days(self) -> None:
        self.assertIn(date(2026, 4, 3), england_wales_bank_holidays(2026))
        self.assertFalse(is_london_business_day(date(2026, 4, 3)))
        self.assertFalse(is_london_business_day(date(2026, 4, 6)))  # Easter Monday
        self.assertFalse(is_london_business_day(date(2026, 5, 4)))  # Early May
        self.assertFalse(is_london_business_day(date(2026, 5, 25)))  # Spring bank
        self.assertFalse(is_london_business_day(date(2027, 5, 31)))  # Spring bank
        self.assertFalse(is_london_business_day(date(2026, 8, 31)))  # Summer bank
        self.assertFalse(is_london_business_day(date(2027, 8, 30)))  # Summer bank
        self.assertFalse(is_london_business_day(date(2026, 12, 25)))
        self.assertFalse(is_london_business_day(date(2026, 12, 28)))  # Boxing substitute
        self.assertTrue(is_london_business_day(date(2026, 12, 31)))
        self.assertFalse(is_london_business_day(date(2027, 1, 1)))

    def test_brent_last_trade_dates_uk_bank_holiday_month_ends(self) -> None:
        self.assertEqual(brent_final_trade_date(2026, 10), date(2026, 8, 28))
        self.assertEqual(brent_final_trade_date(2027, 7), date(2027, 5, 28))
        self.assertEqual(brent_final_trade_date(2026, 12), date(2026, 10, 30))
        self.assertEqual(brent_final_trade_date(2027, 1), date(2026, 11, 30))
        self.assertEqual(brent_final_trade_date(2027, 2), date(2026, 12, 30))

    def test_brent_january_and_february_2025_fail_closed(self) -> None:
        for month in (1, 2):
            with self.subTest(month=month):
                with self.assertRaises(Exception) as caught:
                    brent_final_trade_date(2025, month)
                self.assertEqual(
                    getattr(caught.exception, "reason", None), "expiry_calendar_unavailable"
                )

    def test_brent_final_trade_dates_match_ice_expiry_table(self) -> None:
        ice_last_trade = {
            (2025, 3): date(2025, 1, 31),
            (2025, 4): date(2025, 2, 28),
            (2025, 5): date(2025, 3, 31),
            (2025, 6): date(2025, 4, 30),
            (2025, 7): date(2025, 5, 30),
            (2025, 8): date(2025, 6, 30),
            (2025, 9): date(2025, 7, 31),
            (2025, 10): date(2025, 8, 29),
            (2025, 11): date(2025, 9, 30),
            (2025, 12): date(2025, 10, 31),
            (2026, 1): date(2025, 11, 28),
            (2026, 2): date(2025, 12, 30),
            (2026, 3): date(2026, 1, 30),
            (2026, 4): date(2026, 2, 27),
            (2026, 5): date(2026, 3, 31),
            (2026, 6): date(2026, 4, 30),
            (2026, 7): date(2026, 5, 29),
            (2026, 8): date(2026, 6, 30),
            (2026, 9): date(2026, 7, 31),
            (2026, 10): date(2026, 8, 28),
            (2026, 11): date(2026, 9, 30),
            (2026, 12): date(2026, 10, 30),
            (2027, 1): date(2026, 11, 30),
            (2027, 2): date(2026, 12, 30),
            (2027, 3): date(2027, 1, 29),
            (2027, 4): date(2027, 2, 26),
            (2027, 5): date(2027, 3, 31),
            (2027, 6): date(2027, 4, 30),
            (2027, 7): date(2027, 5, 28),
            (2027, 8): date(2027, 6, 30),
            (2027, 9): date(2027, 7, 30),
            (2027, 10): date(2027, 8, 31),
            (2027, 11): date(2027, 9, 30),
            (2027, 12): date(2027, 10, 29),
            (2028, 1): date(2027, 11, 30),
            (2028, 2): date(2027, 12, 30),
            (2028, 3): date(2028, 1, 31),
            (2028, 4): date(2028, 2, 29),
            (2028, 5): date(2028, 3, 31),
            (2028, 6): date(2028, 4, 28),
            (2028, 7): date(2028, 5, 31),
            (2028, 8): date(2028, 6, 30),
            (2028, 9): date(2028, 7, 31),
            (2028, 10): date(2028, 8, 31),
            (2028, 11): date(2028, 9, 29),
            (2028, 12): date(2028, 10, 31),
            (2029, 1): date(2028, 11, 30),
            (2029, 2): date(2028, 12, 28),
            (2029, 3): date(2029, 1, 31),
            (2029, 4): date(2029, 2, 28),
            (2029, 5): date(2029, 3, 29),
            (2029, 6): date(2029, 4, 30),
            (2029, 7): date(2029, 5, 31),
            (2029, 8): date(2029, 6, 29),
            (2029, 9): date(2029, 7, 31),
            (2029, 10): date(2029, 8, 31),
            (2029, 11): date(2029, 9, 28),
            (2029, 12): date(2029, 10, 31),
            (2030, 1): date(2029, 11, 30),
            (2030, 2): date(2029, 12, 28),
            (2030, 3): date(2030, 1, 31),
            (2030, 4): date(2030, 2, 28),
            (2030, 5): date(2030, 3, 29),
            (2030, 6): date(2030, 4, 30),
            (2030, 7): date(2030, 5, 31),
            (2030, 8): date(2030, 6, 28),
            (2030, 9): date(2030, 7, 31),
            (2030, 10): date(2030, 8, 30),
            (2030, 11): date(2030, 9, 30),
            (2030, 12): date(2030, 10, 31),
            (2031, 1): date(2030, 11, 29),
            (2031, 2): date(2030, 12, 30),
            (2031, 3): date(2031, 1, 31),
            (2031, 4): date(2031, 2, 28),
            (2031, 5): date(2031, 3, 31),
            (2031, 6): date(2031, 4, 30),
            (2031, 7): date(2031, 5, 30),
            (2031, 8): date(2031, 6, 30),
            (2031, 9): date(2031, 7, 31),
            (2031, 10): date(2031, 8, 29),
            (2031, 11): date(2031, 9, 30),
            (2031, 12): date(2031, 10, 31),
            (2032, 1): date(2031, 11, 28),
            (2032, 2): date(2031, 12, 30),
            (2032, 3): date(2032, 1, 30),
            (2032, 4): date(2032, 2, 27),
            (2032, 5): date(2032, 3, 31),
            (2032, 6): date(2032, 4, 30),
            (2032, 7): date(2032, 5, 28),
            (2032, 8): date(2032, 6, 30),
            (2032, 9): date(2032, 7, 30),
            (2032, 10): date(2032, 8, 31),
            (2032, 11): date(2032, 9, 30),
            (2032, 12): date(2032, 10, 29),
            (2033, 1): date(2032, 11, 30),
            (2033, 2): date(2032, 12, 30),
        }
        for (year, month), expected in ice_last_trade.items():
            with self.subTest(year=year, month=month):
                self.assertEqual(brent_final_trade_date(year, month), expected)

    def test_nov4_brent_front_is_january_2027_not_expired_december(self) -> None:
        as_of = date(2026, 11, 4)
        self.assertFalse(contract_is_active("BZ", 2026, 12, as_of))
        front = active_front_contract(as_of, "BZ")
        self.assertEqual(front["symbol"], "BZF27.NYM")
        self.assertEqual(front["contract_month"], "2027-01")
        rejected = {row["symbol"] for row in front["rejected_expired"]}
        self.assertIn("BZZ26.NYM", rejected)
        self.assertTrue(quote_is_fresh(date(2026, 10, 30), as_of))
        self.assertLessEqual((as_of - date(2026, 10, 30)).days, QUOTE_FRESHNESS_MAX_AGE_DAYS)

    def test_wti_holiday_moves_expiration_and_rb_skips_weekend(self) -> None:
        self.assertIn(date(2026, 12, 25), nymex_full_closures(2026))
        self.assertNotIn(date(2026, 10, 12), nymex_full_closures(2026))
        self.assertNotIn(date(2026, 11, 27), nymex_full_closures(2026))
        self.assertFalse(is_nymex_business_day(date(2026, 4, 3)))
        self.assertEqual(wti_final_trade_date(2027, 1), date(2026, 12, 21))
        self.assertNotEqual(wti_final_trade_date(2027, 1), date(2026, 12, 22))
        self.assertEqual(wti_final_trade_date(2026, 11), date(2026, 10, 20))
        self.assertTrue(contract_is_active("CL", 2026, 11, date(2026, 10, 20)))
        self.assertFalse(contract_is_active("CL", 2026, 11, date(2026, 10, 21)))
        self.assertEqual(product_final_trade_date(2026, 6), date(2026, 5, 29))
        self.assertEqual(product_final_trade_date(2026, 12), date(2026, 11, 30))

    def test_calendar_outside_coverage_fails_closed(self) -> None:
        with self.assertRaises(Exception) as caught:
            brent_final_trade_date(2035, 1)
        self.assertEqual(getattr(caught.exception, "reason", None), "expiry_calendar_unavailable")


class ActiveFrontSelectionTests(unittest.TestCase):
    def test_recent_final_bar_cannot_select_expired_bzz26(self) -> None:
        as_of = date(2026, 11, 4)
        expired = contract_symbol("BZ", 2026, 12)
        active = contract_symbol("BZ", 2027, 1)
        charts = {expired: _series(date(2026, 10, 30), 40, 117.64)}
        for symbol in (
            active,
            contract_symbol("BZ", 2027, 4),
            contract_symbol("BZ", 2027, 7),
            contract_symbol("BZ", 2028, 1),
            contract_symbol("BZ", 2029, 1),
        ):
            charts[symbol] = _series(date(2026, 11, 3), 40, 82.0)
        seen: list[str] = []
        curve = build_curve("brent_last_day", as_of, _opener_for(charts, seen))
        self.assertEqual(curve["front_symbol"], active)
        self.assertEqual(curve["front_contract_month"], "2027-01")
        self.assertEqual(curve["front_final_trade_date"], "2026-11-30")
        self.assertTrue(curve["front_active_as_of"])
        self.assertTrue(curve["front_selection"]["quote_fresh"])
        self.assertTrue(curve["front_active_as_of"])
        symbols = [point["symbol"] for point in curve["points"]]
        self.assertNotIn(expired, symbols)
        self.assertFalse(any(expired in url for url in seen))
        by_mat = {point["maturity_months"]: point["contract_month"] for point in curve["points"]}
        self.assertEqual(
            by_mat,
            {0: "2027-01", 3: "2027-04", 6: "2027-07", 12: "2028-01", 24: "2029-01"},
        )

    def test_stale_active_quote_does_not_roll_forward(self) -> None:
        as_of = date(2026, 11, 4)
        active = contract_symbol("BZ", 2027, 1)
        following = contract_symbol("BZ", 2027, 2)
        charts = {
            active: _series(date(2026, 10, 1), 5, 80.0),
            following: _series(date(2026, 11, 3), 5, 81.0),
        }
        seen: list[str] = []
        curve = build_curve("brent_last_day", as_of, _opener_for(charts, seen))
        self.assertEqual(curve["status"], "unavailable")
        self.assertEqual(curve["selection_failure"], "stale_active_quote")
        self.assertEqual(curve["points"], [])
        self.assertFalse(any(following in url for url in seen))
        self.assertIn("stale_active_quote", curve["error"])

    def test_missing_target_maturity_is_not_substituted(self) -> None:
        as_of = date(2026, 11, 4)
        charts = {
            contract_symbol("BZ", 2027, 1): _series(date(2026, 11, 3), 40, 82.0),
            contract_symbol("BZ", 2027, 4): _series(date(2026, 11, 3), 40, 81.0),
            contract_symbol("BZ", 2027, 7): _series(date(2026, 11, 3), 40, 80.0),
            contract_symbol("BZ", 2029, 1): _series(date(2026, 11, 3), 40, 76.0),
        }
        curve = build_curve("brent_last_day", as_of, _opener_for(charts))
        self.assertIn(12, curve["missing_maturities"])
        self.assertEqual(curve["missing_maturity_reasons"]["12"], "missing_maturity_contract")
        self.assertIsNone(curve["slopes_usd"]["12m_minus_front"])
        months = {point["contract_month"] for point in curve["points"]}
        self.assertNotIn("2027-12", months)
        self.assertNotIn("2028-12", months)

    def test_expired_rbob_recent_bar_does_not_price_crack(self) -> None:
        as_of = date(2026, 11, 4)
        expired_rb = contract_symbol("RB", 2026, 11)
        wti_curve = {
            "points": [
                {
                    "maturity_months": 0,
                    "contract_month": "2026-11",
                    "symbol": contract_symbol("CL", 2026, 11),
                    "price": 70.0,
                    "observation_date": "2026-10-30",
                }
            ]
        }
        seen: list[str] = []

        def opener(url: str, data: bytes | None = None) -> bytes:
            seen.append(url)
            if expired_rb in url:
                return _yahoo_bytes(_series(date(2026, 10, 30), 5, 2.2), symbol=expired_rb)
            raise OSError(f"HTTP Error 404: Not Found {url}")

        margin = build_refinery_margin(as_of, wti_curve, opener)
        self.assertEqual(margin["status"], "unavailable")
        self.assertEqual(margin["reason"], "expired_contract")
        self.assertNotIn("gasoline_crack_usd_per_bbl", margin)
        self.assertEqual(seen, [])

    def test_expired_product_leg_is_rejected_before_its_last_bar(self) -> None:
        from scripts.prima_pressure.curve import _product_price

        as_of = date(2026, 11, 4)
        seen: list[str] = []

        def opener(url: str, data: bytes | None = None) -> bytes:
            seen.append(url)
            symbol = contract_symbol("RB", 2026, 11)
            return _yahoo_bytes(_series(date(2026, 10, 30), 5, 2.2), symbol=symbol)

        price, reason = _product_price("RB", 2026, 11, as_of, opener)
        self.assertIsNone(price)
        self.assertEqual(reason, "expired_contract")
        self.assertEqual(seen, [])


class ShockAndHistoryTests(unittest.TestCase):
    def test_expired_listed_12m_24m_are_unavailable_not_stable(self) -> None:
        bundle = _stable_flat_bundle(as_of="2026-11-04")
        bundle["oil_curve"]["brent_last_day"]["points"] = [
            _curve_point(0, 0.20, symbol="BZZ26.NYM", contract_month="2026-12"),
            _curve_point(12, 0.036, symbol="BZZ27.NYM", contract_month="2027-12"),
            _curve_point(24, 0.027, symbol="BZZ28.NYM", contract_month="2028-12"),
        ]
        proxy = compute_prima_proxy(bundle)
        shock = proxy["subcomponents"]["shock_persistence"]
        self.assertEqual(shock["direction"], "UNAVAILABLE")
        self.assertNotEqual(shock["direction"], "STABLE")
        self.assertNotEqual(shock["direction"], "RISING")
        self.assertEqual(proxy["front_shock_classification"], "unavailable")

    def test_valid_listed_12m_24m_still_set_persistence_without_front(self) -> None:
        bundle = _stable_flat_bundle(as_of="2026-11-04")
        bundle["oil_curve"]["brent_last_day"]["points"] = [
            _curve_point(0, 0.20, symbol="BZZ26.NYM", contract_month="2026-12"),
            _curve_point(12, 0.03, symbol="BZF28.NYM", contract_month="2028-01"),
            _curve_point(24, 0.03, symbol="BZF29.NYM", contract_month="2029-01"),
        ]
        proxy = compute_prima_proxy(bundle)
        shock = proxy["subcomponents"]["shock_persistence"]
        self.assertEqual(shock["direction"], "RISING")
        symbols = [drv.get("symbol") for drv in shock["drivers"] if drv.get("symbol")]
        self.assertNotIn("BZZ26.NYM", symbols)
        self.assertIn("BZF28.NYM", symbols)
        self.assertIn("BZF29.NYM", symbols)

    def test_canonical_nov4_snapshot_is_quarantined_and_unmodified(self) -> None:
        before = NOV4_SNAPSHOT.read_bytes()
        digest = hashlib.sha256(before).hexdigest()
        score_path = ROOT / "data/temperature_scores.json"
        calibration_path = ROOT / "data/temperature_calibration.json"
        score_before = score_path.read_bytes()
        calibration_before = calibration_path.read_bytes()
        preserved = {}
        for run_id in ("overnight-20261102", "overnight-20261103", "overnight-20261104", "overnight-20261105"):
            path = ROOT / "data/overnight/runs" / run_id / "reviews/review-001/evidence_snapshot.json"
            preserved[run_id] = path.read_bytes()
        snapshot = json.loads(before.decode("utf-8"))
        block = snapshot["canada_prima_pressure"]
        review = assess_stored_shock_inputs(block, date(2026, 11, 4))
        self.assertFalse(review["valid"])
        by_symbol = {row["symbol"]: row for row in review["findings"]}
        self.assertIn("expired_contract", by_symbol["BZZ26.NYM"]["reasons"])
        self.assertEqual(by_symbol["BZZ26.NYM"]["final_trade_date"], "2026-10-30")
        self.assertIn("misanchored_maturity", by_symbol["BZZ27.NYM"]["reasons"])
        self.assertEqual(by_symbol["BZZ27.NYM"]["expected_contract_month"], "2028-01")
        self.assertEqual(by_symbol["BZZ28.NYM"]["expected_contract_month"], "2029-01")
        self.assertEqual(block["direction"], "STABLE")
        self.assertEqual(block["channel_evidence"]["shock_persistence"]["direction"], "RISING")

        presentation = build_presentation(ROOT)
        nov4 = next(point for point in presentation["trend"] if point["run_id"] == "overnight-20261104")
        self.assertEqual(nov4["futures_validity"], "invalid")
        self.assertEqual(nov4["direction"], "UNAVAILABLE")
        self.assertNotEqual(nov4["direction"], "STABLE")
        self.assertEqual(nov4["subcomponent_directions"]["shock_persistence"], "UNAVAILABLE")
        self.assertEqual(nov4["subcomponent_directions"]["imported_pressure"], "FALLING")
        oct30 = next(point for point in presentation["trend"] if point["run_id"] == "overnight-20261030")
        self.assertEqual(oct30["futures_validity"], "valid")
        self.assertEqual(oct30["direction"], "RISING")
        oct21 = next(point for point in presentation["trend"] if point["run_id"] == "overnight-20261021")
        self.assertEqual(oct21["futures_validity"], "no_futures_inputs")
        self.assertEqual(oct21["direction"], "RISING")

        self.assertEqual(NOV4_SNAPSHOT.read_bytes(), before)
        self.assertEqual(hashlib.sha256(NOV4_SNAPSHOT.read_bytes()).hexdigest(), digest)
        self.assertEqual(score_path.read_bytes(), score_before)
        self.assertEqual(calibration_path.read_bytes(), calibration_before)
        for run_id, raw in preserved.items():
            path = ROOT / "data/overnight/runs" / run_id / "reviews/review-001/evidence_snapshot.json"
            self.assertEqual(path.read_bytes(), raw)
            if run_id == "overnight-20261104":
                continue
            point = next(row for row in presentation["trend"] if row["run_id"] == run_id)
            self.assertEqual(point["futures_validity"], "invalid")
            self.assertNotEqual(point["direction"], "STABLE")


if __name__ == "__main__":
    unittest.main()
