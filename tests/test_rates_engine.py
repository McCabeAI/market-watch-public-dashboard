"""Instrument DV01, native structures, restatement, and neutral analytics."""

from __future__ import annotations

import unittest
from copy import deepcopy

from scripts.overnight.books import empty_seat, position_pnl, realized_increment
from scripts.trader_room.errors import SchemaError
from scripts.overnight.paper_marks import PaperMarkError, resolve_paper_mid
from scripts.rates.contract_economics import dv01_per_contract, parse_contract_id
from scripts.rates.contract_economics import IB, SR3
from scripts.rates.read_model import analytics_for_seat, build_relative_analytics
from scripts.rates.restatement import restate_positions
from scripts.rates.structures import StructureError, build_structure, leg_pnl_usd
from scripts.risk_capital import position_risk_capital
from scripts.trader_room.constants import STANDING_ADVOCATES
from scripts.trader_room.rates_scan import validate_rates_tenor_scan


def _curve(curve_id: str, rows: list[tuple[str, float]]) -> dict:
    return {
        "status": "ok",
        "contracts": [{"expiry": expiry, "implied_rate": rate, "as_of": "2026-10-23"} for expiry, rate in rows],
    }


MARKET = {
    "generated_at": "2026-10-23T21:00:00Z",
    "fx": {"pairs": {"USDCAD": {"spot": 1.36, "as_of": "2026-10-23"}, "AUDUSD": {"spot": 0.65, "as_of": "2026-10-23"}}},
    "tradable_rate_curves": {
        "status": "ok",
        "curves": {
            "SOFR": _curve("SOFR", [("2026-12", 3.70), ("2027-03", 3.55), ("2027-06", 3.40)]),
            "CORRA": _curve("CORRA", [("2026-12", 2.720), ("2027-03", 2.995), ("2027-06", 3.195), ("2027-09", 3.340), ("2027-12", 3.435)]),
            "AONIA": _curve("AONIA", [("2026-10", 3.60), ("2026-11", 3.55), ("2026-12", 3.50)]),
        },
    },
}


class ContractEconomicsTests(unittest.TestCase):
    def test_sr3_one_bp_is_twenty_five_dollars(self) -> None:
        parsed = parse_contract_id("SOFR_2027-03")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.spec.product_code, "SR3")
        self.assertEqual(parsed.spec.currency, "USD")
        self.assertEqual(dv01_per_contract(parsed.spec, year=parsed.year, month=parsed.month), 25.0)
        pnl = position_pnl(
            {
                "instrument": "SR3H7",
                "asset_class": "rates",
                "side": "long",
                "notional_usd": 1_000_000,
                "entry_price": 4.00,
                "mark_price": 3.99,
                "valuation_method": "instrument_dv01",
                "fx_usd_per_unit": 1.0,
                "contract_currency": "USD",
            }
        )
        self.assertEqual(pnl["unrealized_pnl_usd"], 25.0)
        self.assertFalse(pnl["pnl_unavailable"])
        self.assertEqual(pnl["valuation_method"], "instrument_dv01")

    def test_cra_converts_with_usdcad_and_refuses_missing_fx(self) -> None:
        priced = position_pnl(
            {
                "instrument": "CORRA_2027-06",
                "asset_class": "rates",
                "side": "long",
                "notional_usd": 1_000_000 / 1.36,
                "entry_price": 3.195,
                "mark_price": 3.185,
                "valuation_method": "instrument_dv01",
                "fx_usd_per_unit": 1.0 / 1.36,
                "contract_currency": "CAD",
            }
        )
        self.assertAlmostEqual(priced["unrealized_pnl_usd"], 25.0 / 1.36, places=2)
        missing = position_pnl(
            {
                "instrument": "CORRA_2027-06",
                "asset_class": "rates",
                "side": "long",
                "notional_usd": 1_000_000,
                "entry_price": 3.195,
                "mark_price": 3.185,
                "valuation_method": "instrument_dv01",
                "contract_currency": "CAD",
            }
        )
        self.assertTrue(missing["pnl_unavailable"])
        self.assertIsNone(missing["unrealized_pnl_usd"])
        self.assertTrue(missing["isolated"])

    def test_ib_dv01_uses_days_in_the_contract_month(self) -> None:
        november = dv01_per_contract(IB, year=2026, month=11)
        october = dv01_per_contract(IB, year=2026, month=10)
        self.assertAlmostEqual(november, 3_000_000 * 0.0001 * 30 / 365, places=8)
        self.assertAlmostEqual(october, 3_000_000 * 0.0001 * 31 / 365, places=8)
        self.assertIsNone(dv01_per_contract(IB))
        self.assertNotEqual(SR3.currency, IB.currency)

    def test_historical_row_keeps_duration_one_until_restated(self) -> None:
        historical = {
            "position_id": "pos-historical",
            "instrument": "SOFR_2027-03",
            "asset_class": "rates",
            "side": "long",
            "notional_usd": 100_000_000,
            "entry_price": 4.76,
            "mark_price": 4.75,
        }
        self.assertEqual(position_pnl(historical)["unrealized_pnl_usd"], 10_000.0)
        self.assertEqual(position_pnl(historical)["valuation_method"], "legacy_duration_one")
        report = restate_positions([historical])
        self.assertFalse(report["ledger_mutated"])
        self.assertEqual(report["rows"][0]["legacy"]["unrealized_pnl_usd"], 10_000.0)
        self.assertEqual(report["rows"][0]["corrected"]["unrealized_pnl_usd"], 2_500.0)
        self.assertEqual(historical["mark_price"], 4.75)

    def test_sovereign_and_strip_are_isolated_not_invented(self) -> None:
        sovereign = {
            "position_id": "pos-bond",
            "instrument": "US 10Y",
            "asset_class": "rates",
            "side": "long",
            "notional_usd": 100_000_000,
            "entry_price": 4.20,
            "mark_price": 4.10,
        }
        report = restate_positions([sovereign])
        self.assertTrue(report["rows"][0]["corrected"]["isolated"])
        self.assertIsNone(report["rows"][0]["corrected"]["unrealized_pnl_usd"])
        self.assertEqual(report["rows"][0]["legacy"]["unrealized_pnl_usd"], 100_000.0)
        strip = {
            "position_id": "pos-strip",
            "instrument": "CORRA_2027-03",
            "asset_class": "rates",
            "side": "long",
            "notional_usd": 75_000_000,
            "entry_price": 3.40,
            "mark_price": 3.44,
            "paper_expression": {"type": "futures_strip_average", "curve_id": "CORRA", "expiries": ["2027-03", "2027-06", "2027-09", "2027-12"]},
        }
        corrected = restate_positions([strip])["rows"][0]["corrected"]
        self.assertEqual(corrected["structure_label"], "futures_strip_average")
        self.assertIsNone(corrected["unrealized_pnl_usd"])
        self.assertIn("curve spread", corrected["isolation_reason"])


class StructureTests(unittest.TestCase):
    def test_calendar_direction_and_parallel_move(self) -> None:
        # Mechanics only: pay the nearer contract and receive the farther one when long.
        built = build_structure(
            {
                "type": "calendar_spread",
                "curve_id": "SOFR",
                "near_expiry": "2026-12",
                "far_expiry": "2027-06",
                "near_rate": 3.70,
                "far_rate": 3.40,
            },
            side="long",
            notional_usd=1_000_000,
            market_state=MARKET,
        )
        self.assertEqual(built["type"], "calendar_spread")
        near = next(leg for leg in built["legs"] if leg["role"] == "near")
        far = next(leg for leg in built["legs"] if leg["role"] == "far")
        self.assertEqual(near["side"], "short")
        self.assertEqual(far["side"], "long")
        self.assertAlmostEqual(near["dv01_usd"], far["dv01_usd"], places=6)
        self.assertAlmostEqual(built["package_mark_bp"], (3.40 - 3.70) * 100, places=6)
        parallel = deepcopy(built["legs"])
        for leg in parallel:
            leg["mark_rate"] = leg["entry_rate"] + 0.01
        self.assertAlmostEqual(sum(leg_pnl_usd(leg) or 0 for leg in parallel), 0.0, places=6)
        steep = deepcopy(built["legs"])
        for leg in steep:
            if leg["role"] == "near":
                leg["mark_rate"] = leg["entry_rate"] + 0.01
        self.assertAlmostEqual(sum(leg_pnl_usd(leg) or 0 for leg in steep), near["dv01_usd"], places=4)
        risk = position_risk_capital(
            {
                "asset_class": "curve",
                "side": "long",
                "notional_usd": 1_000_000,
                "legs": built["legs"],
                "spread_dv01_usd": built["spread_dv01_usd"],
                "paper_expression": {"type": "calendar_spread", "curve_id": "SOFR"},
            }
        )
        self.assertAlmostEqual(risk, built["spread_dv01_usd"] * 100, places=2)

    def test_butterfly_body_and_wings(self) -> None:
        built = build_structure(
            {
                "type": "butterfly",
                "curve_id": "SOFR",
                "wing1_expiry": "2026-12",
                "body_expiry": "2027-03",
                "wing2_expiry": "2027-06",
                "wing1_rate": 3.70,
                "body_rate": 3.55,
                "wing2_rate": 3.40,
            },
            side="long",
            target_dv01_usd=25.0,
            market_state=MARKET,
        )
        body = next(leg for leg in built["legs"] if leg["role"] == "body")
        wing = next(leg for leg in built["legs"] if leg["role"] == "wing1")
        self.assertEqual(body["side"], "long")
        self.assertEqual(wing["side"], "short")
        self.assertAlmostEqual(body["dv01_usd"], 2 * wing["dv01_usd"], places=4)
        moved = deepcopy(built["legs"])
        for leg in moved:
            if leg["role"] == "body":
                leg["mark_rate"] = leg["entry_rate"] + 0.01
        # Body rate up 1bp raises the canonical fly 2bp, so the long package loses 2 × wing DV01.
        self.assertAlmostEqual(sum(leg_pnl_usd(leg) or 0 for leg in moved), -2 * wing["dv01_usd"], places=4)

    def test_cross_market_rv_balances_dv01_in_usd(self) -> None:
        outright = build_structure(
            {
                "type": "outright_rv",
                "receive": {"curve_id": "SOFR", "expiry": "2027-03", "rate": 3.55},
                "pay": {"curve_id": "CORRA", "expiry": "2027-03", "rate": 2.995},
            },
            side="long",
            target_dv01_usd=2500.0,
            market_state=MARKET,
        )
        receive = next(leg for leg in outright["legs"] if leg["role"] == "receive")
        pay = next(leg for leg in outright["legs"] if leg["role"] == "pay")
        self.assertEqual(receive["currency"], "USD")
        self.assertEqual(pay["currency"], "CAD")
        self.assertAlmostEqual(receive["dv01_usd"], pay["dv01_usd"], places=4)
        self.assertGreater(pay["contracts"], receive["contracts"])
        curve = build_structure(
            {
                "type": "curve_rv",
                "long_calendar": {"curve_id": "CORRA", "near_expiry": "2026-12", "far_expiry": "2027-06", "near_rate": 2.720, "far_rate": 3.195},
                "short_calendar": {"curve_id": "SOFR", "near_expiry": "2026-12", "far_expiry": "2027-06", "near_rate": 3.70, "far_rate": 3.40},
            },
            side="long",
            target_dv01_usd=2500.0,
            market_state=MARKET,
        )
        self.assertEqual(len(curve["legs"]), 4)
        self.assertTrue(curve["not_a_strip"])
        sides = {leg["role"]: leg["side"] for leg in curve["legs"]}
        self.assertEqual(sides["long_calendar_near"], "short")
        self.assertEqual(sides["long_calendar_far"], "long")
        self.assertEqual(sides["short_calendar_near"], "long")
        self.assertEqual(sides["short_calendar_far"], "short")
        roles = {leg["role"] for leg in curve["legs"]}
        self.assertEqual(
            roles,
            {"long_calendar_near", "long_calendar_far", "short_calendar_near", "short_calendar_far"},
        )

    def test_strip_cannot_be_built_or_marked_as_a_curve(self) -> None:
        with self.assertRaises(StructureError):
            build_structure({"type": "futures_strip_average", "curve_id": "CORRA", "expiries": ["2027-03"]}, notional_usd=1)
        with self.assertRaises(PaperMarkError):
            resolve_paper_mid(
                MARKET,
                "CORRA strip",
                asset_class="curve",
                expression={"type": "futures_strip_average", "curve_id": "CORRA", "expiries": ["2026-12", "2027-06"]},
            )

    def test_resize_scales_leg_quantities(self) -> None:
        from scripts.overnight.books import apply_action
        from scripts.trader_room.rates_scan import with_tenor_scan

        seat = empty_seat("rate-dove")
        memo = with_tenor_scan(
            {
                "rates_candidate": {"instrument": "SOFR calendar", "asset_class": "curve", "rationale": "structure"},
                "spot_candidate": {"instrument": "USDCAD", "asset_class": "spot_fx", "rationale": "spot"},
                "options_candidate": None,
                "selected": "rates",
                "rationale": "Calendar construction is markable from the packet.",
            },
            selected_bucket="curve",
        )
        families = {
            "macro_hard": {"status": "fresh"},
            "news": {"status": "fresh"},
            "central_bank_research": {"status": "fresh"},
            "market_state": {"status": "fresh", "data": MARKET},
        }
        expression = {
            "type": "calendar_spread",
            "curve_id": "SOFR",
            "near_expiry": "2026-12",
            "far_expiry": "2027-06",
        }
        apply_action(
            seat,
            {
                "action": "OPEN",
                "instrument": "SOFR_2026-12/2027-06",
                "asset_class": "curve",
                "side": "long",
                "notional_usd": 2_000_000,
                "paper_expression": expression,
                "expression_memo": memo,
                "expected_mark_direction": "lower",
            },
            families=families,
            run_id="r1",
            market_state=MARKET,
        )
        position = seat["positions"][0]
        self.assertEqual(len(position["legs"]), 2)
        opened_contracts = position["legs"][0]["contracts"]
        self.assertGreater(opened_contracts, 0)
        later = deepcopy(MARKET)
        later["tradable_rate_curves"]["curves"]["SOFR"]["contracts"][0]["implied_rate"] = 3.80
        apply_action(
            seat,
            {
                "action": "REDUCE",
                "position_id": position["position_id"],
                "notional_usd": 1_000_000,
                "expression_memo": memo,
            },
            families=families,
            run_id="r2",
            market_state=later,
        )
        reduced = seat["positions"][0]
        self.assertAlmostEqual(reduced["legs"][0]["contracts"], opened_contracts / 2, places=6)
        self.assertNotEqual(seat["realized_pnl_usd"], 0.0)
        closed = realized_increment(reduced, exit_price=reduced["mark_price"], closed_notional=reduced["notional_usd"])
        self.assertIsInstance(closed, float)


class ReadModelTests(unittest.TestCase):
    def test_analytics_are_identical_for_every_seat_and_do_not_recommend(self) -> None:
        payload = build_relative_analytics(MARKET)
        self.assertTrue(payload["optional_no_trade"])
        self.assertIsNone(payload["recommendation"])
        self.assertEqual(payload["available_to"], list(STANDING_ADVOCATES))
        calendars = [row for row in payload["rows"] if row["kind"] == "domestic_calendar" and row["curve_id"] == "CORRA"]
        dec_jun = next(row for row in calendars if row["near_expiry"] == "2026-12" and row["far_expiry"] == "2027-06")
        self.assertAlmostEqual(dec_jun["observed_spread_bp"], 47.5, places=6)
        self.assertIsNone(dec_jun["recommendation"])
        self.assertEqual(dec_jun["structure_label"], "calendar_spread")
        flies = [row for row in payload["rows"] if row["kind"] == "domestic_butterfly"]
        self.assertTrue(flies)
        crosses = [row for row in payload["rows"] if row["kind"] == "cross_market_curve"]
        self.assertTrue(crosses)
        first = analytics_for_seat(MARKET, "rate-dove")
        second = analytics_for_seat(MARKET, "dollar-king")
        self.assertEqual(first["rows"], second["rows"])
        self.assertNotEqual(first["seat"], second["seat"])
        self.assertTrue(all(row["edge"] is None for row in payload["rows"]))

    def test_curve_bucket_rejects_a_strip_label(self) -> None:
        scan = {
            "stir_policy_path": {"status": "not_compelling", "rationale": "Outright STIR was scanned."},
            "two_year": {"status": "not_compelling", "rationale": "Two-year was scanned."},
            "five_year": {"status": "not_compelling", "rationale": "Five-year was scanned."},
            "ten_year": {"status": "not_compelling", "rationale": "Ten-year was scanned."},
            "curve": {
                "status": "candidate",
                "instrument": "CORRA strip",
                "asset_class": "curve",
                "rationale": "This label is wrong.",
                "expression": {"type": "futures_strip_average", "curve_id": "CORRA", "expiries": ["2027-03"]},
            },
            "cross_market_rv": {"status": "not_compelling", "rationale": "Cross-market was scanned."},
            "selected_bucket": "curve",
            "selection_rationale": "Selected the mislabeled strip.",
        }
        with self.assertRaises(SchemaError):
            validate_rates_tenor_scan(scan, agent="rate-dove")


if __name__ == "__main__":
    unittest.main()
