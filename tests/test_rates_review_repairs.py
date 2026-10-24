"""Regression coverage for the seven blocking findings on PR 249."""

from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.overnight.books import apply_action, empty_seat, position_pnl, realized_increment
from scripts.overnight.constants import RISK_CAPITAL_LIMIT_USD
from scripts.overnight.errors import SchemaError
from scripts.overnight.paper_marks import clear_unresolved_mark, refresh_positions
from scripts.pm.books import apply_decision, empty_books
from scripts.rates.contract_economics import IB_PUBLISHED_BPV_AUD, dv01_per_contract, whole_lots
from scripts.rates.contract_economics import CRA, IB, SR3
from scripts.rates.restatement import restate_positions
from scripts.rates.structures import build_structure
from scripts.rates.valuation import stamp_open_valuation
from scripts.risk_capital import position_risk_capital
from scripts.trading.harvest import enforce_harvest_hold, harvest_metrics, material_winner_threshold_usd
from scripts.trader_room.rates_scan import with_tenor_scan

NY = ZoneInfo("America/New_York")
AS_OF = datetime(2026, 10, 23, 12, 0, tzinfo=NY)


def _curve(rows):
    return {
        "status": "ok",
        "contracts": [{"expiry": expiry, "implied_rate": rate, "as_of": "2026-10-23"} for expiry, rate in rows],
    }


MARKET = {
    "generated_at": "2026-10-23T21:00:00Z",
    "fx": {
        "status": "ok",
        "pairs": {
            "USDCAD": {"spot": 1.36, "as_of": "2026-10-23", "status": "ok"},
            "AUDUSD": {"spot": 0.65, "as_of": "2026-10-23", "status": "ok"},
        },
    },
    "tradable_rate_curves": {
        "status": "ok",
        "curves": {
            "SOFR": _curve([("2026-12", 3.70), ("2027-03", 3.55), ("2027-06", 3.40)]),
            "CORRA": _curve([("2026-12", 2.720), ("2027-03", 2.995), ("2027-06", 3.195)]),
            "AONIA": _curve([("2026-10", 3.60), ("2026-11", 3.55), ("2027-02", 3.40)]),
        },
    },
}

FAMILIES = {
    "macro_hard": {"status": "fresh"},
    "news": {"status": "fresh"},
    "central_bank_research": {"status": "fresh"},
    "market_state": {"status": "fresh", "data": MARKET},
}


def _memo(instrument: str, asset: str, bucket: str) -> dict:
    return with_tenor_scan(
        {
            "rates_candidate": {"instrument": instrument, "asset_class": asset, "rationale": "markable structure"},
            "spot_candidate": {"instrument": "USDCAD", "asset_class": "spot_fx", "rationale": "spot alternative"},
            "options_candidate": None,
            "selected": "rates",
            "rationale": "The structure is independently specified from the frozen curves.",
        },
        selected_bucket=bucket,
    )


class AdmissionTests(unittest.TestCase):
    def test_two_billion_sofr_calendar_is_five_million_not_twenty(self) -> None:
        seat = empty_seat("rate-dove")
        expression = {
            "type": "calendar_spread",
            "curve_id": "SOFR",
            "near_expiry": "2026-12",
            "far_expiry": "2027-06",
        }
        action = {
            "action": "OPEN",
            "instrument": "SOFR_2026-12/2027-06",
            "asset_class": "curve",
            "side": "long",
            "notional_usd": 2_000_000_000,
            "paper_expression": expression,
            "expression_memo": _memo("SOFR_2026-12/2027-06", "curve", "curve"),
            "expected_mark_direction": "lower",
        }
        apply_action(seat, action, families=FAMILIES, run_id="admit", when=AS_OF, market_state=MARKET)
        self.assertEqual(len(seat["positions"]), 1)
        near = next(leg for leg in seat["positions"][0]["legs"] if leg["role"] == "near")
        self.assertEqual(near["contracts"], 2000)
        self.assertIsInstance(near["contracts"], int)
        self.assertEqual(seat["risk_capital_usd"], 5_000_000.0)
        self.assertLess(seat["risk_capital_usd"], RISK_CAPITAL_LIMIT_USD)
        self.assertFalse(any(row.get("result") == "blocked_risk_capital" for row in seat["history"]))

    def test_calendar_over_the_cap_is_rejected(self) -> None:
        seat = empty_seat("rate-dove")
        expression = {
            "type": "calendar_spread",
            "curve_id": "SOFR",
            "near_expiry": "2026-12",
            "far_expiry": "2027-06",
        }
        # 4,100 lots × $25 × 100bp = $10.25m, over the $10m cap.
        apply_action(
            seat,
            {
                "action": "OPEN",
                "instrument": "SOFR_2026-12/2027-06",
                "asset_class": "curve",
                "side": "long",
                "notional_usd": 4_100_000_000,
                "paper_expression": expression,
                "expression_memo": _memo("SOFR_2026-12/2027-06", "curve", "curve"),
                "expected_mark_direction": "lower",
            },
            families=FAMILIES,
            run_id="reject",
            when=AS_OF,
            market_state=MARKET,
        )
        self.assertEqual(seat["positions"], [])
        self.assertTrue(any(row.get("result") == "blocked_risk_capital" for row in seat["history"]))


class StaleMarkTests(unittest.TestCase):
    def _open_calendar(self):
        seat = empty_seat("rate-hawk")
        apply_action(
            seat,
            {
                "action": "OPEN",
                "instrument": "SOFR_2026-12/2027-06",
                "asset_class": "curve",
                "side": "long",
                "notional_usd": 2_000_000,
                "paper_expression": {
                    "type": "calendar_spread",
                    "curve_id": "SOFR",
                    "near_expiry": "2026-12",
                    "far_expiry": "2027-06",
                },
                "expression_memo": _memo("SOFR_2026-12/2027-06", "curve", "curve"),
                "expected_mark_direction": "lower",
            },
            families=FAMILIES,
            run_id="open",
            when=AS_OF,
            market_state=MARKET,
        )
        return seat

    def test_partial_and_full_miss_invalidate_every_leg_and_recover(self) -> None:
        seat = self._open_calendar()
        position = seat["positions"][0]
        self.assertTrue(all(leg.get("mark_rate") is not None for leg in position["legs"]))
        broken = deepcopy(MARKET)
        broken["tradable_rate_curves"]["curves"]["SOFR"]["contracts"] = [
            row for row in broken["tradable_rate_curves"]["curves"]["SOFR"]["contracts"] if row["expiry"] != "2027-06"
        ]
        refresh_positions([position], broken, alerts=seat["alerts"])
        self.assertIsNone(position["mark_price"])
        self.assertEqual(position["mark_status"], "unavailable")
        self.assertTrue(all(leg.get("mark_rate") is None for leg in position["legs"]))
        self.assertTrue(all(leg.get("mark_status") == "unavailable" for leg in position["legs"]))
        self.assertIsNone(position_pnl(position)["unrealized_pnl_usd"])
        with self.assertRaises(SchemaError):
            realized_increment(position, exit_price=0.0, closed_notional=position["notional_usd"])
        clear_unresolved_mark(position, reason="explicit clear")
        refresh_positions([position], MARKET)
        self.assertEqual(position["mark_status"], "ok")
        self.assertTrue(all(leg.get("mark_rate") is not None for leg in position["legs"]))
        self.assertIsNotNone(position_pnl(position)["unrealized_pnl_usd"])

    def test_reduce_without_a_current_mark_does_not_invent_pnl(self) -> None:
        seat = self._open_calendar()
        position = seat["positions"][0]
        before_lots = position["legs"][0]["contracts"]
        missing = deepcopy(MARKET)
        missing["tradable_rate_curves"]["curves"]["SOFR"]["status"] = "unavailable"
        missing["tradable_rate_curves"]["curves"]["SOFR"]["contracts"] = []
        apply_action(
            seat,
            {
                "action": "REDUCE",
                "position_id": position["position_id"],
                "notional_usd": 1_000_000,
                "expression_memo": _memo("SOFR_2026-12/2027-06", "curve", "curve"),
            },
            families=FAMILIES,
            run_id="reduce-pending",
            when=AS_OF,
            market_state=missing,
        )
        self.assertEqual(seat["positions"][0]["legs"][0]["contracts"], before_lots)
        self.assertEqual(seat["realized_pnl_usd"], 0.0)
        self.assertEqual(seat["history"][-1]["result"], "pending_mark")
        self.assertIsNone(seat["history"][-1]["realized_pnl_usd"])

    def test_pm_close_is_pending_when_the_curve_is_missing(self) -> None:
        expression = {
            "type": "calendar_spread",
            "curve_id": "SOFR",
            "near_expiry": "2026-12",
            "far_expiry": "2027-06",
        }
        books = apply_decision(
            empty_books(),
            {"pm_id": "pragmatist", "actions": [{
                "action": "OPEN",
                "instrument": "SOFR_2026-12/2027-06",
                "asset_class": "curve",
                "side": "long",
                "notional_usd": 2_000_000,
                "price": 1.0,
                "paper_expression": expression,
                "expected_mark_direction": "lower",
            }]},
            pm_id="pragmatist",
            market_state=MARKET,
            run_id="pm-open",
            evidence_cutoff="c",
            review_packet_id="p",
            review_packet_sha256="h",
            when=AS_OF,
        )
        position = books["pms"]["pragmatist"]["positions"][0]
        missing = deepcopy(MARKET)
        missing["tradable_rate_curves"]["curves"]["SOFR"] = {"status": "unavailable", "error": "down", "contracts": []}
        closed = apply_decision(
            books,
            {"pm_id": "pragmatist", "actions": [{
                "action": "CLOSE",
                "position_id": position["position_id"],
                "notional_usd": position["notional_usd"],
                "price": 1.0,
            }]},
            pm_id="pragmatist",
            market_state=missing,
            run_id="pm-close",
            evidence_cutoff="c2",
            review_packet_id="p2",
            review_packet_sha256="h2",
            when=AS_OF,
        )
        book = closed["pms"]["pragmatist"]
        self.assertEqual(len(book["positions"]), 1)
        self.assertEqual(book["realized_pnl_usd"], 0.0)
        self.assertEqual(book["history"][-1]["result"], "pending_mark")


class ContractConventionTests(unittest.TestCase):
    def test_exchange_bpv_and_integer_lots(self) -> None:
        self.assertEqual(dv01_per_contract(SR3), 25.0)
        self.assertEqual(dv01_per_contract(CRA), 25.0)
        self.assertEqual(dv01_per_contract(IB, year=2027, month=2), IB_PUBLISHED_BPV_AUD)
        self.assertEqual(dv01_per_contract(IB, year=2026, month=10), IB_PUBLISHED_BPV_AUD)
        self.assertEqual(whole_lots(13.6), 13)
        built = build_structure(
            {
                "type": "calendar_spread",
                "curve_id": "CORRA",
                "near_expiry": "2026-12",
                "far_expiry": "2027-06",
                "near_rate": 2.720,
                "far_rate": 3.195,
            },
            side="long",
            notional_usd=13.6 * 1_000_000 / 1.36,
            market_state=MARKET,
        )
        near = next(leg for leg in built["legs"] if leg["role"] == "near")
        self.assertEqual(near["contracts"], 13)
        self.assertIsInstance(near["contracts"], int)
        self.assertAlmostEqual(near["contracts_unrounded"], 13.6, places=6)
        self.assertGreater(near["residual_contracts"], 0)
        self.assertEqual(near["notional_usd"] if "notional_usd" in near else None, None)


class FxVintageTests(unittest.TestCase):
    def test_mark_fx_drift_changes_usd_risk_and_close_uses_exit_fx(self) -> None:
        built = build_structure(
            {
                "type": "outright_rv",
                "receive": {"curve_id": "SOFR", "expiry": "2027-03", "rate": 3.55},
                "pay": {"curve_id": "CORRA", "expiry": "2027-03", "rate": 2.995},
            },
            side="long",
            target_dv01_usd=2500,
            market_state=MARKET,
        )
        entry_pay = next(leg for leg in built["legs"] if leg["role"] == "pay")["entry_fx_usd_per_unit"]
        position = {
            "asset_class": "rates_rv",
            "side": "long",
            "notional_usd": 1_000_000,
            "valuation_method": "instrument_dv01",
            "structure_label": "outright_rv",
            "paper_expression": {
                "type": "outright_rv",
                "receive": {"curve_id": "SOFR", "expiry": "2027-03"},
                "pay": {"curve_id": "CORRA", "expiry": "2027-03"},
            },
            "legs": built["legs"],
            "mark_price": built["package_mark_bp"],
            "entry_price": built["package_mark_bp"],
            "mark_status": "ok",
        }
        before = position_risk_capital(position)
        drifted = deepcopy(MARKET)
        drifted["fx"]["pairs"]["USDCAD"] = {"spot": 1.20, "as_of": "2026-10-24", "status": "ok"}
        refresh_positions([position], drifted)
        pay = next(leg for leg in position["legs"] if leg["role"] == "pay")
        self.assertNotEqual(pay["mark_fx_usd_per_unit"], entry_pay)
        self.assertEqual(pay["entry_fx_usd_per_unit"], entry_pay)
        after = position_risk_capital(position)
        self.assertNotEqual(after, before)
        pay["mark_rate"] = pay["entry_rate"] + 0.01
        realized = realized_increment(position, exit_price=position["mark_price"], closed_notional=position["notional_usd"])
        local = -1 * (-1 if pay["side"] == "short" else 1)
        # short pay, rate up 1bp, profits one bp of CAD DV01 translated at the drifted FX
        self.assertAlmostEqual(
            realized,
            pay["contracts"] * pay["dv01_per_contract_local"] * pay["mark_fx_usd_per_unit"],
            places=2,
        )
        stale = deepcopy(drifted)
        stale["fx"]["status"] = "stale"
        refresh_positions([position], stale)
        self.assertEqual(position["mark_status"], "unavailable")
        self.assertIsNone(position_pnl(position)["unrealized_pnl_usd"])
        del local


class HarvestMoveTests(unittest.TestCase):
    def _stir(self, framing: str | None, pnl: float, *, expected_move_bp: float | None = None) -> tuple[dict, dict]:
        lifecycle = None
        if framing:
            lifecycle = {
                "framing": framing,
                "horizon_days": 10,
                "realization_logic": "The move is reviewed against the stored horizon.",
                "catalyst_logic": "A dated catalyst is already on the lifecycle.",
            }
            if expected_move_bp is not None:
                lifecycle["expected_move_bp"] = expected_move_bp
        trade = {
            "trade_id": "trd-stir",
            "asset_class": "rates",
            "status": "open",
            "lifecycle": lifecycle,
            "expected_mark_direction": "lower",
            "realized_pnl_usd": 0,
            "mfe_usd": pnl,
        }
        position = {
            "asset_class": "rates",
            "side": "long",
            "valuation_method": "instrument_dv01",
            "structure_label": "outright_future",
            "contract_currency": "USD",
            "contracts": 800,
            "notional_usd": 800_000_000,
            "contract": {"dv01_per_contract_local": 25.0},
            "mark_fx_usd_per_unit": 1.0,
            "mark_fx_status": "ok",
            "entry_price": 4.00,
            "mark_price": 3.95,
            "unrealized_pnl_usd": pnl,
        }
        return trade, position

    def test_five_ten_and_twenty_bp_reviews_do_not_require_a_hundred_bp_shock(self) -> None:
        # 800 SR3 lots × $25 = $20,000 per bp. 100bp shock risk is $2m.
        tactical, pos = self._stir("tactical", 100_000)
        self.assertEqual(material_winner_threshold_usd(tactical, pos), 100_000.0)
        self.assertIn("material_winner", harvest_metrics(tactical, pos, as_of=AS_OF)["review_triggers"])
        small, small_pos = self._stir("tactical", 80_000)
        self.assertNotIn("material_winner", harvest_metrics(small, small_pos, as_of=AS_OF)["review_triggers"])
        swing, swing_pos = self._stir("swing", 200_000)
        self.assertEqual(material_winner_threshold_usd(swing, swing_pos), 200_000.0)
        self.assertIn("material_winner", harvest_metrics(swing, swing_pos, as_of=AS_OF)["review_triggers"])
        structural, structural_pos = self._stir("structural", 400_000)
        self.assertEqual(material_winner_threshold_usd(structural, structural_pos), 400_000.0)
        self.assertIn("material_winner", harvest_metrics(structural, structural_pos, as_of=AS_OF)["review_triggers"])
        self.assertLess(material_winner_threshold_usd(structural, structural_pos), 2_000_000.0)

    def test_reduce_is_not_blocked_by_a_missing_harvest_review(self) -> None:
        trade, position = self._stir("tactical", 250_000)
        decision = {"actions": [{"action": "REDUCE", "position_id": "pos-1", "notional_usd": 1}]}
        result = enforce_harvest_hold(
            decision,
            [trade | {"position_id": "pos-1", "status": "open"}],
            [position | {"position_id": "pos-1"}],
            as_of=AS_OF,
            owner_id="rate-dove",
        )
        self.assertFalse(any((row.get("action") or {}).get("action") == "REDUCE" for row in result["blocked"]))


class NewVersusHistoricalTests(unittest.TestCase):
    def test_new_generic_rates_fail_closed_and_historical_rows_remain_comparable(self) -> None:
        fresh = {"instrument": "SOFR-CORRA_2Y", "asset_class": "rates_rv", "side": "long", "notional_usd": 50_000_000}
        stamp_open_valuation(fresh, MARKET)
        self.assertEqual(fresh["valuation_method"], "unavailable")
        self.assertTrue(fresh["isolated"])
        historical = {
            "position_id": "pos-old",
            "opened_at": "2026-09-01T00:00:00-04:00",
            "instrument": "US 10Y",
            "asset_class": "rates",
            "side": "long",
            "notional_usd": 100_000_000,
            "entry_price": 4.20,
            "mark_price": 4.10,
        }
        self.assertEqual(position_pnl(historical)["valuation_method"], "legacy_duration_one")
        self.assertEqual(position_pnl(historical)["unrealized_pnl_usd"], 100_000.0)
        report = restate_positions([historical])
        self.assertFalse(report["ledger_mutated"])
        self.assertIsNone(report["rows"][0]["corrected"]["unrealized_pnl_usd"])
        self.assertEqual(report["rows"][0]["legacy"]["unrealized_pnl_usd"], 100_000.0)
        seat = empty_seat("value-guy")
        apply_action(
            seat,
            {
                "action": "OPEN",
                "instrument": "SYNTHETIC_RV",
                "asset_class": "rates_rv",
                "side": "long",
                "notional_usd": 10_000_000,
                "price": 10,
                "expression_memo": _memo("SYNTHETIC_RV", "rates_rv", "cross_market_rv"),
                "expected_mark_direction": "lower",
            },
            families=FAMILIES,
            run_id="reject-generic",
            when=AS_OF,
            market_state=MARKET,
        )
        self.assertEqual(seat["positions"], [])
        self.assertTrue(any(row.get("result") == "blocked_risk_capital" for row in seat["history"]))


class IntegrationStructureTests(unittest.TestCase):
    def test_cad_dec_jun_and_four_leg_rv_book_and_add(self) -> None:
        seat = empty_seat("carry-is-king")
        calendar = {
            "type": "calendar_spread",
            "curve_id": "CORRA",
            "near_expiry": "2026-12",
            "far_expiry": "2027-06",
        }
        apply_action(
            seat,
            {
                "action": "OPEN",
                "instrument": "CORRA_2026-12/2027-06",
                "asset_class": "curve",
                "side": "long",
                "notional_usd": 13_600_000,
                "paper_expression": calendar,
                "expression_memo": _memo("CORRA_2026-12/2027-06", "curve", "curve"),
                "expected_mark_direction": "lower",
            },
            families=FAMILIES,
            run_id="cad-cal",
            when=AS_OF,
            market_state=MARKET,
        )
        booked = seat["positions"][0]
        self.assertEqual({leg["role"] for leg in booked["legs"]}, {"near", "far"})
        self.assertTrue(all(isinstance(leg["contracts"], int) and leg["contracts"] >= 1 for leg in booked["legs"]))
        self.assertEqual(booked["notional_usd"], 13_600_000)
        lots_before = booked["legs"][0]["contracts"]
        later = deepcopy(MARKET)
        later["tradable_rate_curves"]["curves"]["CORRA"]["contracts"][0]["implied_rate"] = 2.620
        apply_action(
            seat,
            {
                "action": "ADD",
                "position_id": booked["position_id"],
                "notional_usd": 13_600_000,
                "expression_memo": _memo("CORRA_2026-12/2027-06", "curve", "curve"),
            },
            families=FAMILIES,
            run_id="cad-add",
            when=AS_OF,
            market_state=later,
        )
        self.assertGreater(seat["positions"][0]["legs"][0]["contracts"], lots_before)
        self.assertTrue(all(isinstance(leg["contracts"], int) for leg in seat["positions"][0]["legs"]))
        curve = {
            "type": "curve_rv",
            "long_calendar": {"curve_id": "CORRA", "near_expiry": "2026-12", "far_expiry": "2027-06"},
            "short_calendar": {"curve_id": "SOFR", "near_expiry": "2026-12", "far_expiry": "2027-06"},
        }
        other = empty_seat("rate-dove")
        apply_action(
            other,
            {
                "action": "OPEN",
                "instrument": "CORRA-SOFR_2026-12/2027-06",
                "asset_class": "rates_rv",
                "side": "long",
                "notional_usd": 20_000_000,
                "paper_expression": curve,
                "expression_memo": _memo("CORRA-SOFR_2026-12/2027-06", "rates_rv", "cross_market_rv"),
                "expected_mark_direction": "lower",
            },
            families=FAMILIES,
            run_id="four-leg",
            when=AS_OF,
            market_state=MARKET,
        )
        legs = other["positions"][0]["legs"]
        self.assertEqual(len(legs), 4)
        self.assertTrue(all(isinstance(leg["contracts"], int) for leg in legs))
        self.assertIsNotNone(other["risk_capital_usd"])
        self.assertLess(other["risk_capital_usd"], RISK_CAPITAL_LIMIT_USD)


if __name__ == "__main__":
    unittest.main()
