"""Unit tests for the paper rates executable catalog."""

from __future__ import annotations

import copy
import unittest

from scripts.rates.executable_catalog import (
    assess_expression,
    build_executable_catalog,
    select_two_year,
    two_year_choices,
)
from tests.test_rates_engine import MARKET


def _curve(curve_id: str, rows: list[tuple[str, float]]) -> dict:
    return {
        "status": "ok",
        "contracts": [{"expiry": expiry, "implied_rate": rate, "as_of": "2026-10-23"} for expiry, rate in rows],
    }


class ExecutableCatalogTests(unittest.TestCase):
    def test_sofr_outright_executable(self) -> None:
        verdict = assess_expression("SOFR_2027-03", market_state=MARKET)
        self.assertEqual(verdict["status"], "executable")
        self.assertTrue(verdict["bookable"])
        self.assertEqual(verdict["family"], "stir_outright")
        self.assertEqual(verdict["mark_status"], "ok")
        self.assertNotEqual(verdict["status"], "unsupported")

    def test_corra_unavailable_without_fx(self) -> None:
        ok = assess_expression("CORRA_2027-06", market_state=MARKET)
        self.assertEqual(ok["status"], "executable")
        self.assertTrue(ok["bookable"])

        no_fx = copy.deepcopy(MARKET)
        no_fx.pop("fx", None)
        blocked = assess_expression("CORRA_2027-06", market_state=no_fx)
        self.assertEqual(blocked["status"], "unavailable")
        self.assertFalse(blocked["bookable"])
        self.assertNotEqual(blocked["status"], "unsupported")

    def test_us_2y_missing_dv01_not_substituted(self) -> None:
        verdict = assess_expression("US_2Y", market_state=MARKET)
        self.assertEqual(verdict["status"], "missing_input")
        self.assertFalse(verdict["bookable"])
        self.assertNotEqual(verdict["status"], "unsupported")
        self.assertIn("modified duration", verdict["reason"].lower())

        swap_market = copy.deepcopy(MARKET)
        swap_market["rates"] = {
            "US": {
                "status": "ok",
                "tenors": {"2Y": {"value": 4.1, "as_of": "2026-10-23"}},
            }
        }
        gov = select_two_year(swap_market, family="government_yield")
        self.assertEqual(gov["instrument"], "US_2Y")
        self.assertEqual(gov["status"], "missing_input")

        ois = select_two_year(swap_market, family="usd_sofr_ois")
        self.assertNotEqual(ois.get("instrument"), "US_2Y")
        self.assertEqual(ois["family"], "usd_sofr_ois")

    def test_silent_substitution_refused(self) -> None:
        cases = [
            (
                "US_2Y",
                {"type": "usd_sofr_ois", "start_years": 0, "tenor_years": 2},
            ),
            (
                "US 2Y",
                {"type": "futures_strip_average", "curve_id": "SOFR", "expiries": ["2027-03"]},
            ),
            (
                "TU",
                {"type": "usd_sofr_ois", "start_years": 0, "tenor_years": 2},
            ),
            (
                "USD_SOFR_OIS_2Y",
                {"type": "futures_strip_average", "curve_id": "SOFR", "expiries": ["2027-03"]},
            ),
            (
                "SOFR_2027-03",
                {"type": "futures_strip_average", "curve_id": "SOFR", "expiries": ["2027-03"]},
            ),
        ]
        for instrument, expression in cases:
            verdict = assess_expression(instrument, expression=expression, market_state=MARKET)
            self.assertEqual(verdict["status"], "unsupported", msg=f"{instrument} {expression}")
            self.assertFalse(verdict["bookable"])
            self.assertTrue(verdict["reason"].startswith("refusing silent substitution"), msg=verdict["reason"])

    def test_preflight_matches_admission(self) -> None:
        probe = assess_expression(
            "CORRA_2027-03",
            market_state=MARKET,
            notional_usd=2_000_000,
        )
        again = assess_expression(
            "CORRA_2027-03",
            market_state=MARKET,
            notional_usd=2_000_000,
        )
        self.assertEqual(probe, again)

    def test_corra_calendar_spread_executable(self) -> None:
        verdict = assess_expression(
            "CORRA_2026-12",
            expression={
                "type": "calendar_spread",
                "curve_id": "CORRA",
                "near_expiry": "2026-12",
                "far_expiry": "2027-03",
            },
            market_state=MARKET,
            notional_usd=2_000_000,
        )
        self.assertEqual(verdict["status"], "executable")
        self.assertTrue(verdict["bookable"])
        self.assertEqual(verdict["family"], "curve_structure")

    def test_strip_delegates_when_assessor_missing(self) -> None:
        verdict = assess_expression(
            "SOFR_STRIP_2Y",
            expression={
                "type": "futures_strip_average",
                "curve_id": "SOFR",
                "expiries": ["2026-12", "2027-03", "2027-06"],
            },
            market_state=MARKET,
            notional_usd=10_000_000,
        )
        self.assertEqual(verdict["family"], "futures_strip")
        self.assertEqual(verdict["expression_type"], "futures_strip_average")
        self.assertNotIn(verdict["family"], {"stir_outright", "government_yield"})
        if verdict["status"] == "missing_input" and "assessor not installed" in verdict["reason"]:
            self.assertIn("scripts.rates.strips.assess_strip", verdict["missing_inputs"])

    def test_two_year_strip_needs_four_quarterlies(self) -> None:
        choices = two_year_choices(MARKET)
        self.assertEqual(len(choices), 4)
        strip = next(row for row in choices if row.get("instrument") == "SOFR_STRIP_2Y")
        self.assertEqual(strip["status"], "missing_input")
        self.assertIn("tradable_rate_curves.SOFR.quarterly_contracts", strip["missing_inputs"])

    def test_catalog_includes_stir_rows(self) -> None:
        catalog = build_executable_catalog(MARKET)
        instruments = {row.get("instrument") for row in catalog["rows"]}
        self.assertIn("SOFR_2027-03", instruments)
        self.assertTrue(catalog["substitution_policy"].startswith("Refusing silent substitution"))


if __name__ == "__main__":
    unittest.main()
