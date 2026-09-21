#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.overnight.books import (
    allocation_limit_usd,
    apply_action,
    apply_review,
    deployed_notional,
    empty_books,
    empty_seat,
    mark_to_market,
    position_pnl,
    public_books_view,
    realized_increment,
)
from scripts.overnight.clock import overnight_run_id, stage_for_time, stage_window
from scripts.funding.sofr import FUNDING_CONVENTION, FUNDING_DAY_COUNT, FUNDING_SOURCE
from scripts.overnight.constants import LOCAL_CRON, SPOT_SEATS, STAGES, STANDING_SEATS, STARTING_NAV_USD
from scripts.overnight.errors import EvidenceBoundaryError, FreshnessError, PublicationError, SchemaError
from scripts.overnight.expression import expression_rule, validate_expression_memo
from scripts.trader_room.rates_scan import synthetic_rates_tenor_scan, with_tenor_scan
from scripts.overnight.freshness import assert_action_allowed, publication_decision
from scripts.overnight.paper_marks import PaperMarkError, resolve_paper_mid
from scripts.overnight.pipeline import dry_run, reconcile_due_stages, run_stage
from scripts.overnight.publish import publication_gate
from scripts.overnight.review import dry_run_reviews
from scripts.overnight.store import OvernightStore
from scripts.trader_room_public import select_newest_complete_run

NY = ZoneInfo("America/New_York")
AS_OF = datetime(2026, 9, 18, 12, 0, tzinfo=NY)


def _fresh_families() -> dict:
    return {
        "macro_hard": {"status": "fresh", "as_of": "2026-09-18T00:07:00-04:00", "digest": "m"},
        "news": {"status": "fresh", "as_of": "2026-09-18T00:07:00-04:00", "digest": "n"},
        "central_bank_research": {"status": "fresh", "as_of": "2026-09-18T00:07:00-04:00", "digest": "c"},
        "market_state": {"status": "fresh", "as_of": "2026-09-18T00:07:00-04:00", "digest": "s"},
    }


def _spot_memo(instrument: str = "USDCAD") -> dict:
    return {
        "rates_candidate": None,
        "spot_candidate": {"instrument": instrument, "asset_class": "spot_fx", "rationale": "spot"},
        "options_candidate": None,
        "selected": "spot",
        "rationale": "Dedicated spot seat.",
    }


def _rates_memo(selected: str = "rates") -> dict:
    return with_tenor_scan({
        "rates_candidate": {"instrument": "US 10Y", "asset_class": "rates", "rationale": "duration"},
        "spot_candidate": {"instrument": "USDJPY", "asset_class": "spot_fx", "rationale": "spot alt"},
        "options_candidate": None,
        "selected": selected,
        "rationale": "Rates-first comparison complete after scanning STIR, 2Y, 5Y, 10Y, curve, and cross-market RV.",
    })


class ClockAndScheduleTests(unittest.TestCase):
    def test_run_id_is_ny_date(self):
        self.assertEqual(overnight_run_id(AS_OF), "overnight-20260918")
        self.assertTrue(overnight_run_id(AS_OF, dry_run=True, suffix="ci").startswith("overnight-20260918-dryrun-ci"))

    def test_stage_windows_avoid_top_of_hour(self):
        self.assertEqual(stage_for_time(datetime(2026, 9, 18, 0, 7, tzinfo=NY)), "collect")
        self.assertEqual(stage_for_time(datetime(2026, 9, 18, 1, 40, tzinfo=NY)), "pre_trader_delta")
        self.assertEqual(stage_for_time(datetime(2026, 9, 18, 1, 50, tzinfo=NY)), "freeze_evidence")
        self.assertEqual(stage_for_time(datetime(2026, 9, 18, 2, 5, tzinfo=NY)), "trader_review")
        self.assertEqual(stage_for_time(datetime(2026, 9, 18, 3, 35, tzinfo=NY)), "final_delta")
        self.assertEqual(stage_for_time(datetime(2026, 9, 18, 3, 50, tzinfo=NY)), "assemble")
        self.assertEqual(stage_for_time(datetime(2026, 9, 18, 4, 7, tzinfo=NY)), "publish")
        self.assertIsNone(stage_for_time(datetime(2026, 9, 18, 0, 0, tzinfo=NY)))
        for stage, window in (
            ("collect", stage_window("collect", AS_OF)),
            ("publish", stage_window("publish", AS_OF)),
        ):
            self.assertFalse(window["et_time"].endswith(":00"), stage)
        self.assertEqual(len(LOCAL_CRON), 6)
        self.assertNotIn("trader_review", LOCAL_CRON)



class ReconcileScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="overnight-reconcile-"))
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_reconcile_catches_up_missing_pre_freeze_stages(self):
        when = datetime(2026, 9, 21, 1, 55, tzinfo=NY)
        result = reconcile_due_stages(
            root=ROOT,
            state_root=self.tmp,
            when=when,
            live_market_state=False,
        )
        self.assertEqual(
            result["completed"],
            ["collect", "pre_trader_delta", "freeze_evidence"],
        )
        self.assertEqual(result["model_calls"], 0)
        store = OvernightStore(root=ROOT, state_root=self.tmp)
        run_id = "overnight-20260921"
        self.assertTrue(store.has_artifact(run_id, "evidence_snapshot.json"))
        run = store.read_artifact(run_id, "run.json")
        self.assertEqual(run["stages"]["collect"]["status"], "succeeded")
        self.assertEqual(run["stages"]["pre_trader_delta"]["status"], "succeeded")
        self.assertEqual(run["stages"]["freeze_evidence"]["status"], "succeeded")
        self.assertEqual(run["stages"]["trader_review"]["status"], "pending")

        second = reconcile_due_stages(
            root=ROOT,
            state_root=self.tmp,
            when=when,
            live_market_state=False,
        )
        self.assertEqual(second["completed"], [])
        self.assertEqual(
            second["skipped_succeeded"],
            ["collect", "pre_trader_delta", "freeze_evidence"],
        )

    def test_reconcile_does_not_run_future_stages(self):
        when = datetime(2026, 9, 21, 0, 5, tzinfo=NY)
        result = reconcile_due_stages(
            root=ROOT,
            state_root=self.tmp,
            when=when,
            live_market_state=False,
        )
        self.assertEqual(result["completed"], [])
        self.assertIn("collect", result["not_due"])


class ExpressionRuleTests(unittest.TestCase):
    def test_spot_seats_and_rates_first_partition(self):
        self.assertEqual(set(SPOT_SEATS), {"dollar-king", "cross-merchant"})
        for seat in STANDING_SEATS:
            rule = expression_rule(seat)
            if seat in SPOT_SEATS:
                self.assertEqual(rule, "spot_only")
            else:
                self.assertEqual(rule, "rates_first")

    def test_spot_seat_cannot_select_rates(self):
        with self.assertRaises(SchemaError):
            validate_expression_memo(_rates_memo("rates"), seat="dollar-king", action="OPEN")

    def test_rates_first_must_compare_both(self):
        with self.assertRaises(SchemaError):
            validate_expression_memo(
                {
                    "rates_candidate": None,
                    "spot_candidate": {"instrument": "AUDUSD", "asset_class": "spot_fx", "rationale": "x"},
                    "options_candidate": None,
                    "selected": "spot",
                    "rationale": "missing rates compare",
                },
                seat="rate-hawk",
                action="OPEN",
            )
        validate_expression_memo(_rates_memo("rates"), seat="rate-hawk", action="OPEN")
        mismatched = _rates_memo("rates")
        mismatched["rates_candidate"] = {
            "instrument": "US 2Y",
            "asset_class": "rates",
            "rationale": "A different tenor than the selected scan bucket.",
        }
        with self.assertRaises(SchemaError):
            validate_expression_memo(mismatched, seat="rate-hawk", action="OPEN")
        free_text = _rates_memo("rates")
        free_text["rates_candidate"] = "US 10Y duration"
        with self.assertRaises(SchemaError):
            validate_expression_memo(free_text, seat="rate-hawk", action="OPEN")
        missing_scan = {
            "rates_candidate": {"instrument": "US 10Y", "asset_class": "rates", "rationale": "duration"},
            "spot_candidate": {"instrument": "AUDUSD", "asset_class": "spot_fx", "rationale": "x"},
            "options_candidate": None,
            "selected": "rates",
            "rationale": "Rates-first comparison without a tenor scan.",
        }
        with self.assertRaises(SchemaError):
            validate_expression_memo(missing_scan, seat="rate-hawk", action="OPEN")
        malformed = with_tenor_scan(missing_scan)
        del malformed["rates_tenor_scan"]["two_year"]
        with self.assertRaises(SchemaError):
            validate_expression_memo(malformed, seat="rate-hawk", action="OPEN")
        validate_expression_memo(_rates_memo("rates"), seat="vol-convexity", action="OPEN")
        vol_no_scan = {
            "rates_candidate": {"instrument": "US 10Y", "asset_class": "rates", "rationale": "duration"},
            "spot_candidate": {"instrument": "AUDUSD", "asset_class": "spot_fx", "rationale": "spot alt"},
            "options_candidate": {
                "instrument": "USDCAD_25D_RR",
                "asset_class": "options",
                "rationale": "Bounded-risk options last resort versus rates and spot.",
            },
            "selected": "options",
            "rationale": "Options used as last resort versus rates and spot.",
        }
        validate_expression_memo(vol_no_scan, seat="vol-convexity", action="OPEN")
        validate_expression_memo(_spot_memo(), seat="dollar-king", action="OPEN")


class BookTransitionTests(unittest.TestCase):
    def setUp(self):
        self.seat = empty_seat("dollar-king")
        self.families = _fresh_families()

    def test_open_add_hold_reduce_hedge_close_and_pnl(self):
        apply_action(
            self.seat,
            {
                "action": "OPEN",
                "instrument": "USDCAD",
                "side": "long",
                "notional_usd": 10_000_000,
                "price": 1.36,
                "asset_class": "spot_fx",
                "expression_memo": _spot_memo(),
            },
            families=self.families,
            run_id="overnight-20260918-dryrun-t",
            when=AS_OF,
        )
        pos = self.seat["positions"][0]
        pos["mark_price"] = 1.3736
        mark_to_market(self.seat)
        self.assertAlmostEqual(self.seat["unrealized_pnl_usd"], 100_000.0, places=1)
        self.assertAlmostEqual(self.seat["nav_usd"], STARTING_NAV_USD + 100_000.0, places=1)

        apply_action(
            self.seat,
            {
                "action": "ADD",
                "position_id": pos["position_id"],
                "notional_usd": 2_000_000,
                "price": 1.36,
                "expression_memo": _spot_memo(),
            },
            families=self.families,
            run_id="overnight-20260918-dryrun-t",
            when=AS_OF,
        )
        self.assertAlmostEqual(self.seat["positions"][0]["notional_usd"], 12_000_000)
        apply_action(
            self.seat,
            {"action": "HOLD", "expression_memo": _spot_memo()},
            families=self.families,
            run_id="overnight-20260918-dryrun-t",
            when=AS_OF,
        )
        apply_action(
            self.seat,
            {
                "action": "HEDGE",
                "hedge_of": pos["position_id"],
                "notional_usd": 1_000_000,
                "price": 1.3736,
                "expression_memo": _spot_memo(),
            },
            families=self.families,
            run_id="overnight-20260918-dryrun-t",
            when=AS_OF,
        )
        self.assertEqual(len(self.seat["positions"]), 2)
        self.assertEqual(self.seat["positions"][1]["hedge_of"], pos["position_id"])
        apply_action(
            self.seat,
            {
                "action": "REDUCE",
                "position_id": pos["position_id"],
                "notional_usd": 2_000_000,
                "price": 1.3736,
                "expression_memo": _spot_memo(),
            },
            families=self.families,
            run_id="overnight-20260918-dryrun-t",
            when=AS_OF,
        )
        self.assertGreater(self.seat["realized_pnl_usd"], 0)
        apply_action(
            self.seat,
            {
                "action": "CLOSE",
                "position_id": pos["position_id"],
                "price": 1.3736,
                "expression_memo": _spot_memo(),
            },
            families=self.families,
            run_id="overnight-20260918-dryrun-t",
            when=AS_OF,
        )
        self.assertFalse(any(p["position_id"] == pos["position_id"] for p in self.seat["positions"]))
        self.assertEqual({row["action"] for row in self.seat["history"]}, {"OPEN", "ADD", "HOLD", "HEDGE", "REDUCE", "CLOSE"})

    def test_rates_quote_units_convert_one_bp_consistently(self):
        outright = {
            "side": "long",
            "asset_class": "rates",
            "notional_usd": 100_000_000,
            "entry_price": 4.76,
            "mark_price": 4.75,
        }
        curve = {
            "side": "long",
            "asset_class": "curve",
            "notional_usd": 100_000_000,
            "entry_price": 25.0,
            "mark_price": 24.0,
        }
        rv = {
            "side": "long",
            "asset_class": "rates_rv",
            "notional_usd": 100_000_000,
            "entry_price": -140.0,
            "mark_price": -141.0,
        }
        self.assertEqual(position_pnl(outright)["unrealized_pnl_usd"], 10_000.0)
        self.assertEqual(position_pnl(curve)["unrealized_pnl_usd"], 10_000.0)
        self.assertEqual(position_pnl(rv)["unrealized_pnl_usd"], 10_000.0)
        self.assertEqual(
            realized_increment(curve, exit_price=24.0, closed_notional=100_000_000),
            10_000.0,
        )
        self.assertEqual(
            realized_increment(rv, exit_price=-141.0, closed_notional=100_000_000),
            10_000.0,
        )

    def test_flat_trader_has_cash_hurdle_and_zero_risk_funding(self):
        market = {
            "policy_paths": {
                "countries": {
                    "US": {
                        "status": "ok",
                        "benchmark": {
                            "name": "SOFR",
                            "rate": 3.60,
                            "as_of": "2026-09-18",
                            "source": "NY_FED",
                            "history": [
                                {"effective_date": "2026-09-18", "percent_rate": 3.60, "source": "NY_FED"},
                            ],
                        },
                    }
                }
            }
        }
        apply_action(
            self.seat,
            {"action": "HOLD", "expression_memo": _spot_memo()},
            families=self.families,
            run_id="overnight-20260918-dryrun-funding",
            when=AS_OF,
            market_state=market,
        )
        next_day = AS_OF + timedelta(days=1)
        apply_action(
            self.seat,
            {"action": "HOLD", "expression_memo": _spot_memo()},
            families=self.families,
            run_id="overnight-20260919-dryrun-funding",
            when=next_day,
            market_state=market,
        )
        expected = round(STARTING_NAV_USD * 0.036 / FUNDING_DAY_COUNT, 2)
        self.assertEqual(self.seat["funding_cost_usd"], 0.0)
        self.assertEqual(self.seat["cash_yield_usd"], expected)
        self.assertEqual(self.seat["benchmark_cost_usd"], expected)
        self.assertEqual(self.seat["gross_pnl_usd"], 0.0)
        self.assertEqual(self.seat["net_pnl_usd"], 0.0)
        self.assertEqual(self.seat["net_financing_pnl_usd"], 0.0)
        self.assertEqual(self.seat["nav_usd"], STARTING_NAV_USD)
        self.assertNotEqual(self.seat["funding_rate_annual"], 0.05)
        self.assertEqual(self.seat["funding_convention"], FUNDING_CONVENTION)
        self.assertEqual(self.seat["funding_source"], FUNDING_SOURCE)

    def test_skeptic_pays_same_sofr_on_same_shocked_risk(self):
        skeptic = empty_seat("no-trade-skeptic")
        memo = _rates_memo("rates")
        market = {
            "policy_paths": {
                "countries": {
                    "US": {
                        "status": "ok",
                        "benchmark": {
                            "name": "SOFR",
                            "rate": 3.60,
                            "as_of": "2026-09-18",
                            "source": "NY_FED",
                            "history": [
                                {"effective_date": "2026-09-18", "percent_rate": 3.60, "source": "NY_FED"},
                                {"effective_date": "2026-09-19", "percent_rate": 3.60, "source": "NY_FED"},
                            ],
                        },
                    }
                }
            }
        }
        apply_action(
            skeptic,
            {"action": "HOLD", "expression_memo": {
                "rates_candidate": None,
                "spot_candidate": None,
                "options_candidate": None,
                "selected": "none",
                "rationale": "Stay in cash.",
            }},
            families=self.families,
            run_id="overnight-20260918-dryrun-cash",
            when=AS_OF,
            market_state=market,
        )
        day_one = AS_OF + timedelta(days=1)
        apply_action(
            skeptic,
            {
                "action": "OPEN",
                "instrument": "US 10Y",
                "side": "long",
                "notional_usd": 40_000_000,
                "price": 4.20,
                "asset_class": "rates",
                "expression_memo": memo,
            },
            families=self.families,
            run_id="overnight-20260919-dryrun-cash",
            when=day_one,
            market_state=market,
        )
        full_cash_yield = round(STARTING_NAV_USD * 0.036 / FUNDING_DAY_COUNT, 2)
        self.assertEqual(skeptic["cash_yield_usd"], full_cash_yield)
        day_two = AS_OF + timedelta(days=2)
        apply_action(
            skeptic,
            {"action": "HOLD", "expression_memo": memo},
            families=self.families,
            run_id="overnight-20260920-dryrun-cash",
            when=day_two,
            market_state=market,
        )
        risk_funding = round(400_000 * 0.036 / FUNDING_DAY_COUNT, 2)
        self.assertEqual(skeptic["risk_capital_usd"], 400_000.0)
        self.assertEqual(skeptic["funding_cost_usd"], risk_funding)
        expected_cash = round(full_cash_yield * 2, 2)
        self.assertEqual(skeptic["cash_yield_usd"], expected_cash)
        self.assertEqual(skeptic["benchmark_cost_usd"], expected_cash)
        self.assertEqual(skeptic["net_pnl_usd"], round(-risk_funding, 2))
        self.assertEqual(skeptic["net_financing_pnl_usd"], round(-risk_funding, 2))

    def test_exactly_10m_shocked_risk_cap_succeeds(self):
        apply_action(
            self.seat,
            {
                "action": "OPEN",
                "instrument": "USDCAD",
                "side": "long",
                "notional_usd": 600_000_000,
                "price": 1.36,
                "asset_class": "spot_fx",
                "expression_memo": _spot_memo(),
                "thesis": "First leg.",
            },
            families=self.families,
            run_id="overnight-cap-1",
            when=AS_OF,
        )
        apply_action(
            self.seat,
            {
                "action": "OPEN",
                "instrument": "USDJPY",
                "side": "long",
                "notional_usd": 400_000_000,
                "price": 148.0,
                "asset_class": "spot_fx",
                "expression_memo": _spot_memo("USDJPY"),
                "thesis": "Second leg.",
            },
            families=self.families,
            run_id="overnight-cap-1",
            when=AS_OF,
        )
        self.assertEqual(deployed_notional(self.seat), 1_000_000_000)
        self.assertEqual(self.seat["risk_capital_usd"], allocation_limit_usd())
        self.assertEqual(len(self.seat["positions"]), 2)

    def test_over_cap_open_blocked_without_corruption(self):
        cash_before = self.seat["cash_usd"]
        positions_before = len(self.seat["positions"])
        apply_action(
            self.seat,
            {
                "action": "OPEN",
                "instrument": "USDCAD",
                "side": "long",
                "notional_usd": 1_000_000_001,
                "price": 1.36,
                "asset_class": "spot_fx",
                "expression_memo": _spot_memo(),
                "thesis": "Too large.",
            },
            families=self.families,
            run_id="overnight-cap-block",
            when=AS_OF,
        )
        self.assertEqual(len(self.seat["positions"]), positions_before)
        self.assertEqual(self.seat["cash_usd"], cash_before)
        self.assertTrue(any(row.get("result") == "blocked_risk_capital" for row in self.seat["history"]))

    def test_mixed_derisk_and_over_cap_open(self):
        apply_action(
            self.seat,
            {
                "action": "OPEN",
                "instrument": "USDCAD",
                "side": "long",
                "notional_usd": 800_000_000,
                "price": 1.36,
                "asset_class": "spot_fx",
                "expression_memo": _spot_memo(),
                "thesis": "Base risk.",
            },
            families=self.families,
            run_id="overnight-mixed-base",
            when=AS_OF,
        )
        pos_id = self.seat["positions"][0]["position_id"]
        books = empty_books(overnight_run_id="overnight-mixed", when=AS_OF)
        books["seats"]["dollar-king"] = self.seat
        reviews = {
            seat: {"seat": seat, "actions": [{"action": "HOLD", "expression_memo": _spot_memo()}]}
            for seat in STANDING_SEATS
        }
        reviews["dollar-king"] = {
            "seat": "dollar-king",
            "actions": [
                {
                    "action": "REDUCE",
                    "position_id": pos_id,
                    "notional_usd": 100_000_000,
                    "price": 1.36,
                    "expression_memo": _spot_memo(),
                },
                {
                    "action": "OPEN",
                    "instrument": "USDJPY",
                    "side": "long",
                    "notional_usd": 310_000_000,
                    "price": 148.0,
                    "asset_class": "spot_fx",
                    "expression_memo": _spot_memo("USDJPY"),
                    "thesis": "Would exceed cap.",
                },
            ],
        }
        updated = apply_review(
            books,
            reviews,
            families=self.families,
            run_id="overnight-mixed",
            evidence_cutoff="2026-09-18T12:00:00-04:00",
            when=AS_OF,
        )
        seat = updated["seats"]["dollar-king"]
        self.assertEqual(deployed_notional(seat), 700_000_000)
        self.assertEqual(len(seat["positions"]), 1)
        self.assertTrue(any(row.get("result") == "blocked_risk_capital" for row in seat["history"]))

    def test_over_cap_add_and_hedge_blocked(self):
        apply_action(
            self.seat,
            {
                "action": "OPEN",
                "instrument": "USDCAD",
                "side": "long",
                "notional_usd": 900_000_000,
                "price": 1.36,
                "asset_class": "spot_fx",
                "expression_memo": _spot_memo(),
                "thesis": "Near cap.",
            },
            families=self.families,
            run_id="overnight-cap-add",
            when=AS_OF,
        )
        pos_id = self.seat["positions"][0]["position_id"]
        cash_before = self.seat["cash_usd"]
        apply_action(
            self.seat,
            {
                "action": "ADD",
                "position_id": pos_id,
                "notional_usd": 200_000_000,
                "price": 1.36,
                "expression_memo": _spot_memo(),
                "thesis": "Add would exceed cap.",
            },
            families=self.families,
            run_id="overnight-cap-add",
            when=AS_OF,
        )
        self.assertEqual(self.seat["positions"][0]["notional_usd"], 900_000_000)
        self.assertEqual(self.seat["cash_usd"], cash_before)
        apply_action(
            self.seat,
            {
                "action": "HEDGE",
                "hedge_of": pos_id,
                "notional_usd": 150_000_000,
                "price": 1.36,
                "expression_memo": _spot_memo(),
                "thesis": "Hedge would exceed cap.",
            },
            families=self.families,
            run_id="overnight-cap-hedge",
            when=AS_OF,
        )
        self.assertEqual(len(self.seat["positions"]), 1)
        self.assertEqual(deployed_notional(self.seat), 900_000_000)
        blocked = {row.get("action") for row in self.seat["history"] if row.get("result") == "blocked_risk_capital"}
        self.assertEqual(blocked, {"ADD", "HEDGE"})

    def test_rates_notional_may_exceed_100m_inside_risk_cap(self):
        hawk = empty_seat("rate-hawk")
        apply_action(
            hawk,
            {
                "action": "OPEN",
                "instrument": "US 10Y",
                "side": "long",
                "notional_usd": 500_000_000,
                "price": 4.20,
                "asset_class": "rates",
                "expression_memo": _rates_memo("rates"),
                "thesis": "Risk-equivalent rates size.",
            },
            families=self.families,
            run_id="rates-over-notional",
            when=AS_OF,
        )
        self.assertEqual(deployed_notional(hawk), 500_000_000)
        self.assertEqual(hawk["risk_capital_usd"], 5_000_000.0)
        self.assertLess(hawk["risk_capital_usd"], hawk["risk_capital_limit_usd"])
        apply_action(
            hawk,
            {
                "action": "OPEN",
                "instrument": "US 2Y",
                "side": "long",
                "notional_usd": 600_000_000,
                "price": 4.00,
                "asset_class": "rates",
                "expression_memo": _rates_memo("rates"),
                "thesis": "Would exceed $10m shocked risk.",
            },
            families=self.families,
            run_id="rates-over-risk",
            when=AS_OF,
        )
        self.assertEqual(len(hawk["positions"]), 1)
        self.assertTrue(any(row.get("result") == "blocked_risk_capital" for row in hawk["history"]))

    def test_risk_capital_updates_on_add_reduce_close_and_hedge(self):
        apply_action(
            self.seat,
            {
                "action": "OPEN",
                "instrument": "USDCAD",
                "side": "long",
                "notional_usd": 100_000_000,
                "price": 1.36,
                "asset_class": "spot_fx",
                "expression_memo": _spot_memo(),
            },
            families=self.families,
            run_id="rc-open",
            when=AS_OF,
        )
        self.assertEqual(self.seat["risk_capital_usd"], 1_000_000.0)
        pos_id = self.seat["positions"][0]["position_id"]
        apply_action(
            self.seat,
            {
                "action": "ADD",
                "position_id": pos_id,
                "notional_usd": 50_000_000,
                "price": 1.36,
                "expression_memo": _spot_memo(),
            },
            families=self.families,
            run_id="rc-add",
            when=AS_OF,
        )
        self.assertEqual(self.seat["risk_capital_usd"], 1_500_000.0)
        apply_action(
            self.seat,
            {
                "action": "REDUCE",
                "position_id": pos_id,
                "notional_usd": 25_000_000,
                "price": 1.36,
                "expression_memo": _spot_memo(),
            },
            families=self.families,
            run_id="rc-reduce",
            when=AS_OF,
        )
        self.assertEqual(self.seat["risk_capital_usd"], 1_250_000.0)
        apply_action(
            self.seat,
            {
                "action": "HEDGE",
                "hedge_of": pos_id,
                "notional_usd": 10_000_000,
                "price": 1.36,
                "expression_memo": _spot_memo(),
            },
            families=self.families,
            run_id="rc-hedge",
            when=AS_OF,
        )
        self.assertEqual(self.seat["risk_capital_usd"], 1_350_000.0)
        apply_action(
            self.seat,
            {
                "action": "CLOSE",
                "position_id": pos_id,
                "price": 1.36,
                "expression_memo": _spot_memo(),
            },
            families=self.families,
            run_id="rc-close",
            when=AS_OF,
        )
        self.assertEqual(self.seat["risk_capital_usd"], 100_000.0)

    def test_high_water_ratchets_and_drawdown_is_from_peak(self):
        apply_action(
            self.seat,
            {
                "action": "OPEN",
                "instrument": "USDCAD",
                "side": "long",
                "notional_usd": 100_000_000,
                "price": 1.0,
                "asset_class": "spot_fx",
                "expression_memo": _spot_memo(),
            },
            families=self.families,
            run_id="hw-open",
            when=AS_OF,
        )
        self.seat["positions"][0]["mark_price"] = 1.10
        mark_to_market(self.seat, when=AS_OF, run_id="hw-gain")
        self.assertEqual(self.seat["high_water_nav_usd"], 110_000_000.0)
        self.assertEqual(self.seat["drawdown_usd"], 0.0)
        self.seat["positions"][0]["mark_price"] = 1.04
        mark_to_market(self.seat, when=AS_OF, run_id="hw-giveback")
        self.assertEqual(self.seat["high_water_nav_usd"], 110_000_000.0)
        self.assertEqual(self.seat["drawdown_usd"], 6_000_000.0)
        self.assertTrue(self.seat["risk_stopped"])
        self.assertEqual(self.seat["positions"], [])

    def test_hard_drawdown_forces_flat_and_blocks_reentry(self):
        apply_action(
            self.seat,
            {
                "action": "OPEN",
                "instrument": "USDCAD",
                "side": "long",
                "notional_usd": 1_000_000_000,
                "price": 1.0,
                "asset_class": "spot_fx",
                "expression_memo": _spot_memo(),
                "thesis": "Max shocked-risk book.",
            },
            families=self.families,
            run_id="risk-stop-open",
            when=AS_OF,
        )
        self.seat["positions"][0]["mark_price"] = 0.994
        mark_to_market(self.seat, when=AS_OF, run_id="risk-stop-mark")
        self.assertTrue(self.seat["risk_stopped"])
        self.assertEqual(self.seat["positions"], [])
        self.assertEqual(self.seat["realized_pnl_usd"], -6_000_000.0)
        self.assertGreaterEqual(self.seat["drawdown_usd"], 5_000_000.0)
        apply_action(
            self.seat,
            {
                "action": "OPEN",
                "instrument": "USDJPY",
                "side": "long",
                "notional_usd": 10_000_000,
                "price": 148.0,
                "asset_class": "spot_fx",
                "expression_memo": _spot_memo("USDJPY"),
                "thesis": "Must remain blocked.",
            },
            families=self.families,
            run_id="risk-stop-reentry",
            when=AS_OF,
        )
        self.assertEqual(self.seat["positions"], [])
        self.assertTrue(any(row.get("result") == "blocked_risk_stop" for row in self.seat["history"]))
        realized = self.seat["realized_pnl_usd"]
        stops = [row for row in self.seat["history"] if row.get("action") == "RISK_STOP"]
        mark_to_market(self.seat, when=AS_OF, run_id="risk-stop-mark-2")
        from scripts.overnight.books import validate_books, empty_books

        books = empty_books(when=AS_OF)
        books["seats"]["dollar-king"] = self.seat
        validate_books(books)
        self.assertEqual(self.seat["realized_pnl_usd"], realized)
        self.assertEqual(len([row for row in self.seat["history"] if row.get("action") == "RISK_STOP"]), len(stops))
        apply_action(
            self.seat,
            {"action": "HOLD", "expression_memo": _spot_memo()},
            families=self.families,
            run_id="risk-stop-hold",
            when=AS_OF,
        )
        self.assertTrue(self.seat["risk_stopped"])
        self.assertEqual(self.seat["positions"], [])

    def test_missing_exit_mark_pending_stop_does_not_invent_price(self):
        apply_action(
            self.seat,
            {
                "action": "OPEN",
                "instrument": "USDCAD",
                "side": "long",
                "notional_usd": 600_000_000,
                "price": 1.0,
                "asset_class": "spot_fx",
                "expression_memo": _spot_memo(),
            },
            families=self.families,
            run_id="pending-open-1",
            when=AS_OF,
        )
        apply_action(
            self.seat,
            {
                "action": "OPEN",
                "instrument": "USDJPY",
                "side": "long",
                "notional_usd": 100_000_000,
                "price": 148.0,
                "asset_class": "spot_fx",
                "expression_memo": _spot_memo("USDJPY"),
            },
            families=self.families,
            run_id="pending-open-2",
            when=AS_OF,
        )
        cad = next(p for p in self.seat["positions"] if p["instrument"] == "USDCAD")
        yen = next(p for p in self.seat["positions"] if p["instrument"] == "USDJPY")
        cad["mark_price"] = 0.99
        yen["mark_price"] = None
        mark_to_market(self.seat, when=AS_OF, run_id="pending-stop")
        self.assertTrue(self.seat["risk_stopped"])
        self.assertTrue(self.seat["risk_stop_pending"])
        self.assertEqual(len(self.seat["positions"]), 1)
        self.assertEqual(self.seat["positions"][0]["instrument"], "USDJPY")
        self.assertEqual(self.seat["positions"][0]["mark_price"], None)
        self.assertEqual(self.seat["realized_pnl_usd"], -6_000_000.0)
        apply_action(
            self.seat,
            {
                "action": "OPEN",
                "instrument": "AUDUSD",
                "side": "long",
                "notional_usd": 10_000_000,
                "price": 0.66,
                "asset_class": "spot_fx",
                "expression_memo": _spot_memo("AUDUSD"),
            },
            families=self.families,
            run_id="pending-block",
            when=AS_OF,
        )
        self.assertTrue(any(row.get("result") == "blocked_risk_stop" for row in self.seat["history"]))
        remaining_id = self.seat["positions"][0]["position_id"]
        apply_action(
            self.seat,
            {
                "action": "CLOSE",
                "position_id": remaining_id,
                "price": 148.0,
                "expression_memo": _spot_memo("USDJPY"),
            },
            families=self.families,
            run_id="pending-close",
            when=AS_OF,
        )
        self.assertEqual(self.seat["positions"], [])
        self.assertTrue(self.seat["risk_stopped"])
        realized = self.seat["realized_pnl_usd"]
        mark_to_market(self.seat, when=AS_OF, run_id="pending-repeat")
        mark_to_market(self.seat, when=AS_OF, run_id="pending-repeat-2")
        self.assertEqual(self.seat["realized_pnl_usd"], realized)

    def test_canonical_trader_books_migrate_without_rewriting_trades(self):
        from copy import deepcopy
        from pathlib import Path
        from scripts.overnight.books import validate_books, public_books_view

        raw = json.loads((Path(__file__).resolve().parents[1] / "data" / "overnight" / "books" / "latest.json").read_text())
        before = deepcopy(raw)
        validated = validate_books(deepcopy(raw))
        view = public_books_view(deepcopy(raw))
        self.assertEqual(len(validated["seats"]), 14)
        for seat, item in validated["seats"].items():
            orig = before["seats"][seat]
            self.assertEqual(item["risk_capital_limit_usd"], 10_000_000)
            self.assertEqual(item["max_drawdown_usd"], 5_000_000)
            self.assertEqual(item["realized_pnl_usd"], orig["realized_pnl_usd"])
            self.assertEqual(len(item["positions"]), len(orig["positions"]))
            self.assertLessEqual(item["risk_capital_usd"], item["risk_capital_limit_usd"])
            for pos, old in zip(item["positions"], orig["positions"]):
                self.assertEqual(pos["position_id"], old["position_id"])
                self.assertEqual(pos["notional_usd"], old["notional_usd"])
                self.assertEqual(pos["entry_price"], old["entry_price"])
                self.assertIsNotNone(pos["risk_capital_usd"])
        public_with_pos = next(row for row in view["seats"] if row["positions"])
        self.assertIn("risk_capital_usd", public_with_pos)
        self.assertIn("drawdown_usd", public_with_pos)
        for seat, item in validated["seats"].items():
            if not item["positions"]:
                self.assertEqual(item["net_pnl_usd"], 0.0, seat)
                self.assertEqual(item["net_financing_pnl_usd"], 0.0, seat)
        self.assertEqual(validated["seats"]["no-trade-skeptic"]["net_pnl_usd"], 0.0)
        self.assertEqual(validated["seats"]["no-trade-skeptic"]["net_financing_pnl_usd"], 0.0)
        self.assertEqual(validated["seats"]["no-trade-skeptic"]["funding_regime"], "sofr_zero_benchmark")
        self.assertEqual(
            validated["seats"]["no-trade-skeptic"]["realized_pnl_usd"],
            before["seats"]["no-trade-skeptic"]["realized_pnl_usd"],
        )
        self.assertEqual(
            validated["seats"]["no-trade-skeptic"]["unrealized_pnl_usd"],
            before["seats"]["no-trade-skeptic"]["unrealized_pnl_usd"],
        )
        self.assertEqual(
            validated["seats"]["no-trade-skeptic"]["gross_pnl_usd"],
            before["seats"]["no-trade-skeptic"]["gross_pnl_usd"],
        )
        self.assertIn("risk_stopped", public_with_pos)
        self.assertIn("risk_capital_usd", public_with_pos["positions"][0])

    def test_missing_mark_does_not_invent_pnl(self):
        pos = {
            "side": "long",
            "notional_usd": 5_000_000,
            "entry_price": 148.0,
            "mark_price": None,
            "asset_class": "spot_fx",
        }
        pnl = position_pnl(pos)
        self.assertTrue(pnl["pnl_unavailable"])
        self.assertIsNone(pnl["unrealized_pnl_usd"])



class PaperMarkTests(unittest.TestCase):
    def test_direct_mid_overrides_model_price_in_paper_book(self):
        books = empty_books(overnight_run_id="overnight-20260918", when=AS_OF)
        reviews = {
            seat: {
                "seat": seat,
                "actions": [{"action": "HOLD", "expression_memo": (
                    _spot_memo() if seat in {"dollar-king", "cross-merchant"} else
                    {
                        "rates_candidate": None,
                        "spot_candidate": None,
                        "options_candidate": None,
                        "selected": "none",
                        "rationale": "hold",
                    }
                )}],
            }
            for seat in STANDING_SEATS
        }
        reviews["dollar-king"] = {
            "seat": "dollar-king",
            "conviction": 60,
            "thesis": "test",
            "expression_memo": _spot_memo("USDCAD"),
            "actions": [{
                "action": "OPEN",
                "instrument": "USDCAD",
                "side": "long",
                "notional_usd": 10_000_000,
                "price": 9.99,
                "asset_class": "spot_fx",
                "expression_memo": _spot_memo("USDCAD"),
            }],
        }
        market_state = {"fx": {"USDCAD": {"spot": 1.36, "as_of": "2026-09-18"}}}
        updated = apply_review(
            books,
            reviews,
            families=_fresh_families(),
            run_id="overnight-20260918",
            evidence_cutoff="2026-09-18T12:00:00-04:00",
            when=AS_OF,
            market_state=market_state,
        )
        pos = updated["seats"]["dollar-king"]["positions"][0]
        self.assertEqual(pos["entry_price"], 1.36)
        self.assertEqual(pos["mark_price"], 1.36)
        self.assertIn("market_state.fx.USDCAD.spot", pos["entry_price_source"])

    def test_linear_curve_expression_is_recomputed_from_source_legs(self):
        state = {
            "rates": {
                "US": {
                    "tenors": {
                        "2Y": {"value": 4.50, "as_of": "2026-09-18"},
                        "10Y": {"value": 5.00, "as_of": "2026-09-18"},
                    }
                }
            }
        }
        mark = resolve_paper_mid(
            state,
            "US_2s10s_custom",
            asset_class="curve",
            expression={
                "type": "linear_combo",
                "output_unit": "bps",
                "legs": [
                    {"instrument": "US_10Y", "asset_class": "rates", "weight": 1},
                    {"instrument": "US_2Y", "asset_class": "rates", "weight": -1},
                ],
            },
        )
        self.assertEqual(mark["value"], 50.0)
        self.assertEqual(mark["quote_unit"], "bps")
        self.assertEqual(mark["kind"], "derived")

    def test_tradable_curve_contract_alias_marks_from_locked_curve(self):
        state = {
            "generated_at": "2026-09-19T14:00:00Z",
            "tradable_rate_curves": {
                "curves": {
                    "SOFR": {
                        "status": "ok",
                        "contracts": [
                            {"expiry": "2027-03", "code": "SR3H7", "implied_rate": 3.35}
                        ],
                    }
                }
            },
        }
        mark = resolve_paper_mid(state, "SOFR_2027-03", asset_class="rates")
        self.assertEqual(mark["value"], 3.35)
        self.assertIn("tradable_rate_curves.SOFR", mark["source"])

    def test_futures_strip_average_recomputes_locked_forward_window(self):
        state = {
            "generated_at": "2026-09-19T14:00:00Z",
            "tradable_rate_curves": {
                "curves": {
                    "CORRA": {
                        "status": "ok",
                        "contracts": [
                            {"expiry": "2028-03", "code": "CRAH28", "implied_rate": 3.50},
                            {"expiry": "2028-06", "code": "CRAM28", "implied_rate": 3.60},
                            {"expiry": "2028-09", "code": "CRAU28", "implied_rate": 3.70},
                            {"expiry": "2028-12", "code": "CRAZ28", "implied_rate": 3.80},
                        ],
                    }
                }
            },
        }
        mark = resolve_paper_mid(
            state,
            "CA_forward_window",
            asset_class="rates",
            expression={
                "type": "futures_strip_average",
                "curve_id": "CORRA",
                "expiries": ["2028-03", "2028-06", "2028-09", "2028-12"],
            },
        )
        self.assertAlmostEqual(mark["value"], 3.65)
        self.assertIn("futures_strip_average:CORRA", mark["source"])

    def test_2y2y_forward_swap_math_uses_discount_factors(self):
        state = {
            "discount_factors": {
                "US": {
                    "2Y": {"discount_factor": 0.93, "as_of": "2026-09-18"},
                    "3Y": {"discount_factor": 0.88, "as_of": "2026-09-18"},
                    "4Y": {"discount_factor": 0.83, "as_of": "2026-09-18"},
                }
            }
        }
        mark = resolve_paper_mid(
            state,
            "US_2y2y",
            asset_class="rates",
            expression={
                "type": "forward_swap",
                "start_discount_ref": "discount_factors.US.2Y",
                "end_discount_ref": "discount_factors.US.4Y",
                "payment_discount_refs": [
                    {"ref": "discount_factors.US.3Y", "accrual": 1.0},
                    {"ref": "discount_factors.US.4Y", "accrual": 1.0},
                ],
            },
        )
        expected = 100.0 * (0.93 - 0.83) / (0.88 + 0.83)
        self.assertAlmostEqual(mark["value"], expected, places=8)

    def test_2y2y_uses_official_curve_proxy_compact_syntax(self):
        state = {
            "official_curves": {
                "countries": {
                    "US": {
                        "status": "ok",
                        "as_of": "2026-09-11",
                        "discount_factors": {
                            "2Y": {"value": 0.93, "maturity_years": 2.0, "as_of": "2026-09-11", "source": "FED"},
                            "3Y": {"value": 0.88, "maturity_years": 3.0, "as_of": "2026-09-11", "source": "FED"},
                            "4Y": {"value": 0.83, "maturity_years": 4.0, "as_of": "2026-09-11", "source": "FED"},
                        },
                    }
                }
            }
        }
        mark = resolve_paper_mid(
            state,
            "US_2y2y",
            asset_class="rates",
            expression={
                "type": "forward_swap",
                "curve_country": "US",
                "start_years": 2,
                "tenor_years": 2,
                "payment_frequency": 1,
            },
        )
        expected = 100.0 * (0.93 - 0.83) / (0.88 + 0.83)
        self.assertAlmostEqual(mark["value"], expected, places=8)
        self.assertIn("official_curves.US", mark["source"])

    def test_forward_swap_proxy_loglinearly_interpolates_missing_coupon_nodes(self):
        state = {
            "official_curves": {
                "countries": {
                    "US": {
                        "status": "ok",
                        "as_of": "2026-09-11",
                        "discount_factors": {
                            "2Y": {"value": 0.93, "maturity_years": 2.0, "as_of": "2026-09-11", "source": "FED"},
                            "3Y": {"value": 0.88, "maturity_years": 3.0, "as_of": "2026-09-11", "source": "FED"},
                            "4Y": {"value": 0.83, "maturity_years": 4.0, "as_of": "2026-09-11", "source": "FED"},
                        },
                    }
                }
            }
        }
        mark = resolve_paper_mid(
            state,
            "US_2y2y_semiannual",
            asset_class="rates",
            expression={
                "type": "forward_swap",
                "curve_country": "US",
                "start_years": 2,
                "tenor_years": 2,
                "payment_frequency": 2,
            },
        )
        self.assertGreater(mark["value"], 0)
        self.assertIn("loglinear", mark["source"])

    def test_forward_swap_refuses_to_fake_missing_curve_inputs(self):
        with self.assertRaises(PaperMarkError):
            resolve_paper_mid(
                {"rates": {"US": {"tenors": {"2Y": {"value": 4.5}, "5Y": {"value": 4.9}}}}},
                "US_2y2y",
                asset_class="rates",
                expression={
                    "type": "forward_swap",
                    "start_discount_ref": "discount_factors.US.2Y",
                    "end_discount_ref": "discount_factors.US.4Y",
                    "payment_discount_refs": [
                        {"ref": "discount_factors.US.3Y", "accrual": 1.0},
                        {"ref": "discount_factors.US.4Y", "accrual": 1.0},
                    ],
                },
            )


class FreshnessMatrixTests(unittest.TestCase):
    def test_stale_blocks_open_add_but_allows_hold_reduce_close(self):
        stale = _fresh_families()
        stale["news"]["status"] = "stale"
        assert_action_allowed("HOLD", stale, seat="dollar-king")
        assert_action_allowed("REDUCE", stale, seat="dollar-king")
        assert_action_allowed("CLOSE", stale, seat="dollar-king")
        with self.assertRaises(FreshnessError):
            assert_action_allowed("OPEN", stale, seat="dollar-king")
        with self.assertRaises(FreshnessError):
            assert_action_allowed("ADD", stale, seat="dollar-king")

    def test_open_records_block_on_the_book(self):
        seat = empty_seat("dollar-king")
        stale = _fresh_families()
        stale["macro_hard"]["status"] = "stale"
        apply_action(
            seat,
            {
                "action": "OPEN",
                "instrument": "USDCAD",
                "side": "long",
                "notional_usd": 1_000_000,
                "price": 1.36,
                "asset_class": "spot_fx",
                "expression_memo": _spot_memo(),
            },
            families=stale,
            run_id="overnight-20260918-dryrun-t",
            when=AS_OF,
        )
        self.assertEqual(seat["positions"], [])
        self.assertEqual(seat["history"][-1]["result"], "blocked_freshness")

    def test_catastrophic_core_blocks_publish_stale_review_does_not(self):
        ok = publication_decision(families=_fresh_families(), trader_review_status="failed", last_successful_review_run_id="overnight-20260917")
        self.assertTrue(ok["may_publish"])
        self.assertEqual(ok["trader_books_status"], "failed")
        self.assertEqual(ok["last_successful_review_run_id"], "overnight-20260917")
        bad = _fresh_families()
        bad["news"]["status"] = "invalid"
        blocked = publication_decision(families=bad, trader_review_status="fresh")
        self.assertFalse(blocked["may_publish"])
        self.assertEqual(blocked["core_status"], "catastrophic_fail")


class PipelineDryRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="overnight-"))
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_complete_dry_run_no_model_calls(self):
        result = dry_run(root=ROOT, state_root=self.tmp, when=AS_OF, suffix="test")
        self.assertEqual(result["model_calls"], 0)
        self.assertTrue(result["dry_run"])
        self.assertEqual([row["status"] for row in result["stages"]], ["succeeded"] * 7)
        store = OvernightStore(root=ROOT, state_root=self.tmp)
        run_id = result["overnight_run_id"]
        run = store.read_artifact(run_id, "run.json")
        self.assertEqual(run["overnight_run_id"], run_id)
        self.assertEqual(set(run["stages"]), set(STAGES))
        snapshot = store.read_artifact(run_id, "evidence_snapshot.json")
        review = store.read_artifact(run_id, "trader_review.json")
        self.assertEqual(review["packet_sha256"], snapshot["packet_sha256"])
        self.assertFalse(review["full_trader_room"])
        self.assertEqual(review["model_calls"], 0)
        books = store.read_books()
        self.assertEqual(set(books["seats"]), set(STANDING_SEATS))
        self.assertGreater(len(books["seats"]["dollar-king"]["positions"]), 0)
        self.assertEqual(books["seats"]["dollar-king"]["positions"][0]["asset_class"], "spot_fx")
        self.assertEqual(books["seats"]["rate-hawk"]["positions"][0]["asset_class"], "rates")
        dataset = store.read_artifact(run_id, "assembled_dataset.json")
        self.assertEqual(dataset["trader_books"]["seat_count"], 14)
        self.assertTrue(dataset["publication"]["may_publish"])
        self.assertTrue(dataset["preservation"]["sep18_news_fixes"])
        view = public_books_view(books)
        self.assertIn("overnight_changes", view)
        self.assertNotEqual(view.get("funding_rate_annual"), 0.05)
        self.assertEqual(view["funding_convention"], FUNDING_CONVENTION)
        self.assertEqual(view["funding_source"], FUNDING_SOURCE)
        self.assertEqual(view["competition_metric"], "net_pnl_after_funding")
        self.assertEqual(len(view["leaderboard"]), 14)
        pm_memory = snapshot.get("pm_memory") or {}
        pm_hashes = pm_memory.get("hashes") or {}
        for pm_id in ("chatgpt", "swinger", "pragmatist", "grinder"):
            self.assertIn(pm_id, pm_hashes, msg="freeze snapshot must include pm_memory hashes (sibling freeze)")
            sidecar = store.run_dir(run_id) / "pm_memory" / f"{pm_id}.json"
            self.assertTrue(sidecar.is_file(), msg=f"expected pm_memory sidecar for {pm_id}")
        self.assertIn("pm_books", review)
        self.assertIn("pm_packets", review)
        from scripts.pm.constants import AUTOMATED_PM_IDS
        from scripts.pm.store import PMStore

        pm_store = PMStore(root=ROOT, state_root=self.tmp)
        pm_books = pm_store.read_books()
        for pm_id in AUTOMATED_PM_IDS:
            self.assertNotEqual(
                pm_books["pms"][pm_id]["decision_status"],
                "awaiting_automated_pm_review",
            )
        self.assertEqual(pm_books["pms"]["chatgpt"]["decision_status"], "awaiting_chatgpt_decision")
        self.assertIn("pm_books_status", dataset["publication"])

    def test_failed_review_still_publishes_stale(self):
        run_id = "overnight-20260918-dryrun-fail"
        for stage in ("collect", "pre_trader_delta", "freeze_evidence"):
            run_stage(stage, root=ROOT, state_root=self.tmp, run_id=run_id, when=AS_OF, dry_run=True)
        store = OvernightStore(root=ROOT, state_root=self.tmp)
        store.write_artifact(
            run_id,
            "trader_review.json",
            {
                "schema_version": 1,
                "type": "OVERNIGHT_TRADER_REVIEW",
                "overnight_run_id": run_id,
                "status": "failed",
                "errors": ["cursor review crashed"],
                "model_calls": 0,
                "full_trader_room": False,
                "books": empty_books(overnight_run_id=run_id, when=AS_OF),
            },
        )
        store.write_books(empty_books(overnight_run_id="overnight-20260917", when=AS_OF))
        books = store.read_books()
        books["last_successful_review_run_id"] = "overnight-20260917"
        store.write_books(books)
        for stage in ("final_delta", "assemble"):
            run_stage(stage, root=ROOT, state_root=self.tmp, run_id=run_id, when=AS_OF, dry_run=True)
        dataset = store.read_artifact(run_id, "assembled_dataset.json")
        self.assertTrue(dataset["publication"]["may_publish"])
        self.assertEqual(dataset["publication"]["trader_books_status"], "failed")
        self.assertEqual(dataset["publication"]["last_successful_review_run_id"], "overnight-20260917")
        gate = publication_gate(store, run_id=run_id, require_dataset=True)
        self.assertTrue(gate["may_publish"])

    def test_catastrophic_news_fails_publication(self):
        result = dry_run(root=ROOT, state_root=self.tmp, when=AS_OF, suffix="boom")
        store = OvernightStore(root=ROOT, state_root=self.tmp)
        run_id = result["overnight_run_id"]
        dataset = store.read_artifact(run_id, "assembled_dataset.json")
        dataset["core"]["news"]["status"] = "invalid"
        dataset["publication"] = publication_decision(families={
            "macro_hard": dataset["core"]["macro_hard"],
            "news": dataset["core"]["news"],
            "central_bank_research": dataset["core"]["central_bank_research"],
            "market_state": dataset["core"]["market_state"],
        }, trader_review_status="fresh")
        store.write_artifact(run_id, "assembled_dataset.json", dataset)
        with self.assertRaises(PublicationError):
            publication_gate(store, run_id=run_id, require_dataset=True)

    def test_manage_scenario_add_reduce_hedge_close(self):
        dry_run(root=ROOT, state_root=self.tmp, when=AS_OF, suffix="open")
        store = OvernightStore(root=ROOT, state_root=self.tmp)
        opened = store.read_books()
        trend_id = opened["seats"]["trend-follower"]["positions"][0]["position_id"]
        second = dry_run(
            root=ROOT,
            state_root=self.tmp,
            when=AS_OF,
            suffix="manage",
            review_scenario="manage",
        )
        self.assertEqual(second["publication"]["may_publish"], True)
        books = store.read_books()
        frozen_prior = store.read_artifact(second["overnight_run_id"], "evidence_snapshot.json")["prior_books"]
        self.assertEqual(
            frozen_prior["seats"]["dollar-king"]["positions"][0]["position_id"],
            opened["seats"]["dollar-king"]["positions"][0]["position_id"],
        )
        self.assertAlmostEqual(books["seats"]["dollar-king"]["positions"][0]["notional_usd"], 12_000_000)
        self.assertAlmostEqual(books["seats"]["rate-hawk"]["positions"][0]["notional_usd"], 10_000_000)
        self.assertEqual(books["seats"]["perma-bull"]["positions"], [])
        self.assertTrue(any(p.get("hedge_of") == trend_id for p in books["seats"]["trend-follower"]["positions"]))

    def test_review_cannot_fetch_new_evidence(self):
        run_id = "overnight-20260918-dryrun-bound"
        for stage in ("collect", "pre_trader_delta", "freeze_evidence"):
            run_stage(stage, root=ROOT, state_root=self.tmp, run_id=run_id, when=AS_OF, dry_run=True)
        reviews = dry_run_reviews()
        reviews["dollar-king"]["web_search"] = True
        with self.assertRaises(EvidenceBoundaryError):
            run_stage(
                "trader_review",
                root=ROOT,
                state_root=self.tmp,
                run_id=run_id,
                when=AS_OF,
                dry_run=False,
                live_reviews=reviews,
            )


class TraderBookTabTests(unittest.TestCase):
    def test_tab_is_additive_and_keeps_existing_markers(self):
        html = """
        <style>
        #p-feed:checked~.app .nav label[for=p-feed],
        #p-marketdata:checked~.app .nav label[for=p-marketdata],
        {color:red}
        #p-feed:checked~.app .feed,
        #p-marketdata:checked~.app .marketdata,
        {display:block}
        </style>
        <input id="p-marketdata" name="page" type="radio"/>
        <input id="p-feed" name="page" type="radio"/>
        <label for="p-marketdata">Market Data</label>
        <label for="p-feed">Feed &amp; Momentum</label>
        <section class="page marketdata">Market Data · official snapshot</section>
        <section class="page relative"></section>
        <div>Last 24 Hours · Desk Summary</div>
        <div>7-Day Quick Digest</div>
        <div>Live 1–100 Score Board</div>
        """
        tmp = Path(tempfile.mkdtemp(prefix="tb-tab-"))
        self.addCleanup(shutil.rmtree, tmp)
        target = tmp / "index.html"
        target.write_text(html)
        from scripts.apply_trader_book_tab import apply_trader_book_tab

        apply_trader_book_tab(target, repo_root=ROOT)
        out = target.read_text()
        self.assertIn('id="p-traderbook"', out)
        self.assertIn("Trader Book · paper P&L", out)
        self.assertIn("14 Traders + 4 Portfolio Managers", out)
        self.assertIn("14 Traders · Total P&amp;L", out)
        self.assertIn("Last 24 Hours · Desk Summary", out)
        self.assertIn("Live 1–100 Score Board", out)
        self.assertIn("Market Data · official snapshot", out)
        self.assertIn("7-Day Quick Digest", out)
        self.assertTrue((tmp / "trader-book.js").is_file())


class SeedBooksTests(unittest.TestCase):
    def test_repo_canonical_books_cover_fourteen_seats(self):
        books = json.loads((ROOT / "data" / "overnight" / "books" / "latest.json").read_text())
        self.assertEqual(set(books["seats"]), set(STANDING_SEATS))
        self.assertEqual(books["starting_nav_usd"], STARTING_NAV_USD)
        newest = select_newest_complete_run(ROOT)
        self.assertIsNotNone(newest)
        assert newest is not None
        self.assertEqual(books.get("last_successful_review_run_id"), newest.name)
        for seat in books["seats"].values():
            self.assertIsInstance(seat.get("positions"), list)
            self.assertIn("nav_usd", seat)


if __name__ == "__main__":
    unittest.main()
