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

    def test_two_year_strip_needs_eight_quarterlies(self) -> None:
        choices = two_year_choices(MARKET)
        self.assertEqual(len(choices), 4)
        strip = next(row for row in choices if row.get("instrument") == "SOFR_STRIP_2Y")
        self.assertEqual(strip["status"], "missing_input")
        self.assertIn("eight", strip["reason"].lower())
        self.assertIn("four quarterlies are not a 2Y swap", strip["reason"])
        self.assertIn("tradable_rate_curves.SOFR.quarterly_contracts", strip["missing_inputs"])

    def test_four_quarterlies_not_bookable_two_year_strip(self) -> None:
        market = copy.deepcopy(MARKET)
        market["tradable_rate_curves"]["curves"]["SOFR"] = _curve(
            "SOFR",
            [("2026-12", 3.70), ("2027-03", 3.55), ("2027-06", 3.40), ("2027-09", 3.35)],
        )
        verdict = select_two_year(market, family="futures_strip")
        self.assertEqual(verdict["status"], "missing_input")
        self.assertFalse(verdict["bookable"])
        self.assertIn("eight", verdict["reason"].lower())
        self.assertIn("four quarterlies are not a 2Y swap", verdict["reason"])

    def test_eight_quarterly_strip_bookable_sum_leg_dv01(self) -> None:
        market = copy.deepcopy(MARKET)
        expiries = [
            "2026-12",
            "2027-03",
            "2027-06",
            "2027-09",
            "2027-12",
            "2028-03",
            "2028-06",
            "2028-09",
        ]
        market["tradable_rate_curves"]["curves"]["SOFR"] = _curve(
            "SOFR",
            [(e, 4.00) for e in expiries],
        )
        picked = select_two_year(market, family="futures_strip", notional_usd=8_000_000)
        self.assertTrue(picked["bookable"])
        self.assertEqual(picked["instrument"], "SOFR_STRIP_2Y")
        expr = {
            "type": "futures_strip_average",
            "curve_id": "SOFR",
            "expiries": expiries,
        }
        verdict = assess_expression(
            "SOFR_STRIP_2Y",
            expression=expr,
            market_state=market,
            notional_usd=8_000_000,
        )
        self.assertTrue(verdict["bookable"])
        self.assertEqual(len(expr["expiries"]), 8)
        from scripts.rates.strips import build_strip

        built = build_strip(expr, side="long", notional_usd=8_000_000, market_state=market)
        leg_dv01 = sum(abs(float(leg.get("dv01_usd") or 0.0)) for leg in built["legs"])
        self.assertEqual(len(built["legs"]), 8)
        self.assertAlmostEqual(built["shock_dv01_usd"], leg_dv01, places=6)
        self.assertAlmostEqual(leg_dv01, 8 * 25.0, places=6)

    def test_catalog_includes_stir_rows(self) -> None:
        catalog = build_executable_catalog(MARKET)
        instruments = {row.get("instrument") for row in catalog["rows"]}
        self.assertIn("SOFR_2027-03", instruments)
        self.assertTrue(catalog["substitution_policy"].startswith("Refusing silent substitution"))
        self.assertIsNone(catalog["ranking"])
        self.assertIsNone(catalog["preference"])
        self.assertIn("does not rank", catalog["advisory"].lower())

    def test_catalog_advertises_ois_treasury_and_structure_recipes(self) -> None:
        catalog = build_executable_catalog(MARKET)
        by_instrument = {row.get("instrument"): row for row in catalog["rows"]}
        self.assertIn("USD_SOFR_OIS_2Y", by_instrument)
        self.assertIn("USD_SOFR_OIS_1Y1Y", by_instrument)
        self.assertNotEqual(
            by_instrument["USD_SOFR_OIS_2Y"]["expression"],
            by_instrument["USD_SOFR_OIS_1Y1Y"]["expression"],
        )
        self.assertFalse(by_instrument["USD_SOFR_OIS_2Y"]["bookable"])
        self.assertFalse(by_instrument["USD_SOFR_OIS_1Y1Y"]["bookable"])
        products = {row.get("product") or row.get("instrument") for row in catalog["rows"] if row.get("family") == "treasury_future"}
        self.assertTrue({"TU", "FV", "TY"} <= {str(item)[:2] for item in products})
        self.assertTrue(all(not row.get("bookable") for row in catalog["rows"] if row.get("family") == "treasury_future"))

        recipe_types = [recipe["expression_type"] for recipe in catalog["recipes"]]
        self.assertEqual(
            recipe_types,
            ["calendar_spread", "butterfly", "outright_rv", "curve_rv", "futures_strip_average"],
        )
        for recipe in catalog["recipes"]:
            self.assertFalse(recipe["executable_template"])
            self.assertFalse(recipe["ranked"])
            schema = recipe["schema"]
            self.assertIn("required", schema)
            self.assertIn("properties", schema)
            example = recipe["example"]
            for key in schema["required"]:
                self.assertIn(key, example)
            again = assess_expression(
                recipe["example_instrument"],
                expression=example,
                market_state=MARKET,
                notional_usd=recipe.get("assessed_notional_usd"),
            )
            self.assertEqual(recipe["bookable"], bool(again["bookable"]))
            self.assertEqual(recipe["example_bookable"], bool(again["bookable"]))
            self.assertEqual(recipe["example_verdict"]["status"], again["status"])
            if recipe["expression_type"] == "futures_strip_average":
                self.assertEqual(len(example["expiries"]), 4)
                self.assertNotEqual(recipe["example_instrument"], "SOFR_STRIP_2Y")
            if recipe["expression_type"] == "curve_rv":
                self.assertIn("long_calendar", example)
                self.assertIn("short_calendar", example)
            if recipe["expression_type"] == "outright_rv":
                self.assertNotEqual(example["receive"]["curve_id"], example["pay"]["curve_id"])

        for row in catalog["rows"]:
            again = assess_expression(
                row.get("instrument"),
                expression=row.get("expression"),
                market_state=MARKET,
                notional_usd=row.get("assessed_notional_usd"),
            )
            self.assertEqual(bool(row.get("bookable")), bool(again["bookable"]), msg=row.get("instrument"))
            if row.get("bookable") and row.get("representative"):
                self.assertTrue(again["bookable"])

        bookable_structures = [
            row for row in catalog["rows"] if row.get("family") == "curve_structure" and row.get("bookable")
        ]
        kinds = {row.get("expression_type") for row in bookable_structures}
        self.assertTrue({"calendar_spread", "butterfly", "outright_rv", "curve_rv"} <= kinds)
        four = next(row for row in catalog["rows"] if row.get("not_a_two_year_strip"))
        self.assertTrue(four["bookable"])
        self.assertEqual(len(four["expiries"]), 4)
        self.assertNotIn("2Y", str(four["instrument"]))
        strip_2y = by_instrument["SOFR_STRIP_2Y"]
        self.assertFalse(strip_2y["bookable"])
        self.assertEqual(len(strip_2y["expression"]["expiries"]), 8)

    def test_gapped_eight_sorted_quarterlies_are_not_a_two_year_strip(self) -> None:
        market = copy.deepcopy(MARKET)
        gapped = [
            "2026-12",
            "2027-03",
            "2027-09",
            "2027-12",
            "2028-03",
            "2028-06",
            "2028-09",
            "2028-12",
            "2029-03",
            "2029-06",
        ]
        market["tradable_rate_curves"]["curves"]["SOFR"] = _curve("SOFR", [(expiry, 4.0) for expiry in gapped])
        verdict = select_two_year(market, family="futures_strip")
        self.assertEqual(verdict["status"], "missing_input")
        self.assertFalse(verdict["bookable"])
        self.assertIn("2027-06", verdict["reason"])
        self.assertIn("tradable_rate_curves.SOFR.contracts.2027-06.implied_rate", verdict["missing_inputs"])
        self.assertEqual(
            verdict["expression"]["expiries"],
            ["2026-12", "2027-03", "2027-06", "2027-09", "2027-12", "2028-03", "2028-06", "2028-09"],
        )
        direct = assess_expression(
            "SOFR_STRIP_2Y",
            expression={
                "type": "futures_strip_average",
                "curve_id": "SOFR",
                "expiries": gapped[:8],
            },
            market_state=market,
            notional_usd=8_000_000,
        )
        self.assertFalse(direct["bookable"])
        self.assertIn("2027-06", direct["missing_inputs"][0])

        later = select_two_year(market, family="futures_strip", start_expiry="2027-09", notional_usd=8_000_000)
        self.assertTrue(later["bookable"])
        self.assertEqual(later["instrument"], "SOFR_STRIP_2Y")
        self.assertEqual(
            later["expiries"],
            ["2027-09", "2027-12", "2028-03", "2028-06", "2028-09", "2028-12", "2029-03", "2029-06"],
        )
        from scripts.rates.strips import build_strip

        built = build_strip(later["expression"], side="long", notional_usd=8_000_000, market_state=market)
        self.assertEqual([leg["expiry"] for leg in built["legs"]], later["expiries"])

        catalog = build_executable_catalog(market)
        catalog_strip = next(row for row in catalog["rows"] if row.get("instrument") == "SOFR_STRIP_2Y")
        self.assertFalse(catalog_strip["bookable"])
        self.assertEqual(catalog_strip["expression"]["expiries"][0], "2026-12")
        self.assertIn("2027-06", catalog_strip["expression"]["expiries"])

    def test_year_crossing_consecutive_strip_and_separate_four_contract_strip(self) -> None:
        market = copy.deepcopy(MARKET)
        eight = [
            "2027-03",
            "2027-06",
            "2027-09",
            "2027-12",
            "2028-03",
            "2028-06",
            "2028-09",
            "2028-12",
        ]
        market["tradable_rate_curves"]["curves"]["SOFR"] = _curve("SOFR", [(expiry, 3.9) for expiry in eight])
        picked = select_two_year(market, family="futures_strip", notional_usd=8_000_000)
        self.assertTrue(picked["bookable"])
        self.assertEqual(picked["expiries"], eight)
        self.assertEqual(picked["expiries"][0][:4], "2027")
        self.assertEqual(picked["expiries"][-1][:4], "2028")

        four = eight[:4]
        short = assess_expression(
            "SOFR_STRIP",
            expression={"type": "futures_strip_average", "curve_id": "SOFR", "expiries": four},
            market_state=market,
            notional_usd=4_000_000,
        )
        self.assertTrue(short["bookable"])
        self.assertNotEqual(short["instrument"], "SOFR_STRIP_2Y")
        named = select_two_year(market, family="futures_strip")
        self.assertEqual(len(named["expiries"]), 8)
        self.assertNotEqual(named["expiries"], four)

    def test_dated_treasury_and_both_ois_match_assess_expression(self) -> None:
        market = copy.deepcopy(MARKET)

        def treasury_row(product: str, expiry: str) -> dict:
            return {
                "product": product,
                "expiry": expiry,
                "futures_price": 108.0,
                "price_source": "fixture",
                "price_as_of": "2026-10-23",
                "conversion_factor": 0.9,
                "conversion_factor_source": "fixture",
                "conversion_factor_as_of": "2026-10-23",
                "ctd_modified_duration": 4.0,
                "ctd_dirty_price_per_100": 99.0,
                "ctd_source": "fixture",
                "ctd_as_of": "2026-10-23",
            }

        def ois_row(start: int, tenor: int, par: float) -> dict:
            return {
                "start_years": start,
                "tenor_years": tenor,
                "par_rate_percent": par,
                "annuity": 1.9 if tenor == 2 else 0.95,
                "quote_type": "observed_par",
                "source": "fixture",
                "as_of": "2026-10-23",
                "curve_kind": "sofr_ois",
                "status": "ok",
            }

        market["treasury_futures"] = {
            "status": "ok",
            "source": "fixture",
            "front": {"TU": "TU_2027-03", "FV": "FV_2027-06", "TY": "TY_2027-09"},
            "contracts": {
                "TU_2027-03": treasury_row("TU", "2027-03"),
                "TU_2027-06": treasury_row("TU", "2027-06"),
                "FV_2027-06": treasury_row("FV", "2027-06"),
                "TY_2027-09": treasury_row("TY", "2027-09"),
            },
        }
        market["usd_sofr_ois"] = {
            "status": "ok",
            "curve_kind": "sofr_ois",
            "source": "fixture",
            "as_of": "2026-10-23",
            "instruments": {
                "USD_SOFR_OIS_2Y": ois_row(0, 2, 4.0),
                "USD_SOFR_OIS_1Y1Y": ois_row(1, 1, 3.7),
            },
        }
        catalog = build_executable_catalog(market)
        rows = {row.get("instrument"): row for row in catalog["rows"]}
        for instrument, expiry in (
            ("TU_2027-03", "2027-03"),
            ("TU_2027-06", "2027-06"),
            ("FV_2027-06", "2027-06"),
            ("TY_2027-09", "2027-09"),
            ("USD_SOFR_OIS_2Y", None),
            ("USD_SOFR_OIS_1Y1Y", None),
        ):
            row = rows[instrument]
            self.assertTrue(row["bookable"], msg=instrument)
            if expiry is not None:
                self.assertEqual(row.get("expiry"), expiry)
            again = assess_expression(
                instrument,
                expression=row.get("expression"),
                market_state=market,
                notional_usd=row.get("assessed_notional_usd"),
            )
            self.assertEqual(bool(row["bookable"]), bool(again["bookable"]))
        self.assertNotEqual(rows["USD_SOFR_OIS_2Y"]["expression"]["tenor_years"], 1)
        self.assertEqual(rows["USD_SOFR_OIS_1Y1Y"]["expression"]["start_years"], 1)

        from scripts.trader_room.executable_catalog_section import _CATALOG_KNOWN_GAP, attach_executable_catalog

        packet = {"market_state": market, "known_gaps": []}
        attach_executable_catalog(packet)
        self.assertNotIn(_CATALOG_KNOWN_GAP, packet["known_gaps"])
        self.assertIsNone(packet["executable_catalog"]["ranking"])


if __name__ == "__main__":
    unittest.main()
