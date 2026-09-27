#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.overnight.books import empty_books, mark_to_market, public_books_view, validate_books
from scripts.pm.books import mark_pm_book, validate_books as validate_pm_books
from scripts.overnight.constants import MAX_DRAWDOWN_USD, STANDING_SEATS
from scripts.overnight.store import OvernightStore, write_json
from scripts.pm.books import empty_books as empty_pm_books
from scripts.pm.constants import PM_IDS
from scripts.pm.store import PMStore
from scripts.trader_room.paper_book import reviews_from_run
from scripts.trading.apply import apply_trader_review_with_memory
from scripts.trading.capital_owner import build_capital_owner
from scripts.trading.consequence import (
    assert_trader_consequence_clean,
    build_pm_consequence,
    build_trader_consequence,
    record_consequence_observation,
)
from scripts.trading.constants import MATERIAL_DRAWDOWN_FRACTION, MEMORY_SCHEMA_VERSION
from scripts.trading.errors import LearningGateError, SchemaError
from scripts.trading.gate import evaluate_decision_actions
from scripts.pm.books import public_pm_view
from scripts.pm.review_packets import memory_market_inputs
from scripts.trading.memory import accept_performance_reflection, accept_postmortem, build_memory_context, performance_triggers
from scripts.trading.snapshot import compact_memory_for_packet
from scripts.trading.store import TradingStore

NY = ZoneInfo("America/New_York")
AS_OF = datetime(2026, 9, 19, 12, 0, tzinfo=NY)
MARKET = {
    "generated_at": "2026-09-19T12:00:00Z",
    "fx": {"pairs": {"USDCAD": {"spot": 1.36}}},
}
CAUSAL = {
    "original_belief": "Dollar strength would extend because relative growth still favored the United States.",
    "observed_reality": "The pair reversed after the catalyst printed without the expected follow-through.",
    "assumptions_right": "The growth differential was real and visible at the decision time.",
    "assumptions_wrong_or_underweighted": "I underweighted how crowded the long-dollar expression already was.",
    "causal_divergence": "The reaction function faded the data instead of extending the prior trend.",
    "decision_quality_attribution": "expression",
    "same_information_counterfactual": "With the same information I would have used a smaller expression or waited for confirmation.",
    "future_implication": "When this crowded dollar setup reappears, fade the first extension rather than adding risk.",
}


def _spot_memo() -> dict:
    return {
        "rates_candidate": None,
        "spot_candidate": {"instrument": "USDCAD", "asset_class": "spot_fx", "rationale": "spot"},
        "options_candidate": None,
        "selected": "spot",
        "rationale": "Dedicated USD spot seat.",
    }


def _fresh_families() -> dict:
    return {
        "macro_hard": {"status": "fresh", "as_of": "2026-09-19T00:07:00-04:00", "digest": "m"},
        "news": {"status": "fresh", "as_of": "2026-09-19T00:07:00-04:00", "digest": "n"},
        "central_bank_research": {"status": "fresh", "as_of": "2026-09-19T00:07:00-04:00", "digest": "c"},
        "market_state": {"status": "fresh", "as_of": "2026-09-19T00:07:00-04:00", "digest": "s", "data": MARKET},
    }


class TraderPsychologyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = TradingStore(root=self.root, state_root=self.root)
        self.store.ensure_initialized()
        self.overnight = OvernightStore(root=self.root, state_root=self.root)
        self.pm_store = PMStore(root=self.root, state_root=self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_trader_books(self, books: dict) -> None:
        for seat in STANDING_SEATS:
            mark_to_market(books["seats"][seat], when=AS_OF)
        self.overnight.write_books(validate_books(books))

    def _write_pm_books(self, books: dict) -> None:
        for pm_id in PM_IDS:
            mark_pm_book(books["pms"][pm_id], when=AS_OF)
        self.pm_store.write_books(validate_pm_books(books))

    def _memory_hashes(self) -> dict[str, str]:
        from scripts.trading.constants import ALL_IDENTITIES

        return {
            owner_id: build_memory_context(self.store, owner_type, owner_id)["memory_context_sha256"]
            for owner_type, owner_id in ALL_IDENTITIES
        }

    def test_trader_consequence_own_book_only(self) -> None:
        books = empty_books(overnight_run_id="overnight-20260919", when=AS_OF)
        books["seats"]["dollar-king"]["realized_pnl_usd"] = 1_500_000.0
        books["seats"]["perma-bull"]["realized_pnl_usd"] = 5_000_000.0
        self._write_trader_books(books)
        consequence = build_trader_consequence(self.store, "dollar-king")
        self.assertEqual(consequence["status"], "ok")
        self.assertEqual(consequence["net_pnl_usd"], 1_500_000.0)
        self.assertIn("competition_rank", consequence)
        self.assertNotIn("spread_to_leader", consequence)
        assert_trader_consequence_clean(consequence)
        dumped = json.dumps(consequence)
        self.assertNotIn("perma-bull", dumped)
        self.assertNotIn("5_000_000", dumped.replace("5000000", ""))

    def test_pm_consequence_spreads_and_best_trader(self) -> None:
        trader_books = empty_books(overnight_run_id="overnight-20260919", when=AS_OF)
        trader_books["seats"]["dollar-king"]["realized_pnl_usd"] = 8_000_000.0
        self._write_trader_books(trader_books)
        pm_books = empty_pm_books()
        pm_books["pms"]["swinger"]["realized_pnl_usd"] = 1_000_000.0
        pm_books["pms"]["pragmatist"]["realized_pnl_usd"] = 5_000_000.0
        self._write_pm_books(pm_books)
        consequence = build_pm_consequence(self.store, "swinger")
        self.assertFalse(consequence["capital_normalized"])
        self.assertEqual(consequence["spread_to_leader_pm_usd"], -4_000_000.0)
        self.assertEqual(consequence["best_trader_seat"], "dollar-king")
        self.assertEqual(consequence["gap_to_best_trader_usd"], -7_000_000.0)

    def test_swinger_drawdown_alone_not_punished(self) -> None:
        pm_books = empty_pm_books()
        pm_books["pms"]["swinger"]["drawdown_usd"] = 30_000_000.0
        pm_books["pms"]["swinger"]["net_after_funding_pnl_usd"] = 25_000_000.0
        consequence = {
            "status": "ok",
            "drawdown_usd": 30_000_000.0,
            "net_after_funding_pnl_usd": 25_000_000.0,
            "high_water_nav_usd": 1_030_000_000.0,
        }
        owner = build_capital_owner(
            self.store,
            "swinger",
            consequence=consequence,
            pm_book=pm_books["pms"]["swinger"],
        )
        self.assertEqual(owner["standing"], "good_standing")
        self.assertTrue(all("suck" not in note.lower() for note in owner.get("notes") or []))

    def test_swinger_first_uncompensated_drawdown_is_tolerated(self) -> None:
        consequence = {
            "status": "ok",
            "drawdown_usd": 30_000_000.0,
            "net_after_funding_pnl_usd": -1_000_000.0,
            "high_water_nav_usd": 1_000_000_000.0,
        }
        owner = build_capital_owner(
            self.store,
            "swinger",
            consequence=consequence,
            pm_book={"max_drawdown_usd": 50_000_000.0, "cash_capital_usd": 1_000_000_000.0},
        )
        self.assertEqual(owner["standing"], "good_standing")
        self.assertNotIn("repeated_uncompensated_drawdown", owner.get("pressure_flags") or [])
        self.assertTrue(all("suck" not in note.lower() for note in owner.get("notes") or []))

    def test_swinger_repeated_uncompensated_pain_escalates(self) -> None:
        self.store.write_consequence_state(
            "pm",
            "swinger",
            {"swinger_uncompensated_episodes": 2},
        )
        consequence = {
            "status": "ok",
            "drawdown_usd": 30_000_000.0,
            "net_after_funding_pnl_usd": -5_000_000.0,
            "high_water_nav_usd": 1_000_000_000.0,
        }
        owner = build_capital_owner(
            self.store,
            "swinger",
            consequence=consequence,
            pm_book={"max_drawdown_usd": 50_000_000.0, "cash_capital_usd": 1_000_000_000.0},
        )
        self.assertEqual(owner["standing"], "watch")
        self.assertIn("repeated_uncompensated_drawdown", owner["pressure_flags"])
        self.assertTrue(any("suck" in note.lower() for note in owner.get("notes") or []))

    def _set_swinger_realized(self, realized: float) -> None:
        books = empty_pm_books()
        books["pms"]["swinger"]["realized_pnl_usd"] = realized
        self._write_pm_books(books)

    def test_unchanged_swinger_drawdown_does_not_accumulate_episodes(self) -> None:
        self._set_swinger_realized(-30_000_000.0)
        for _ in range(4):
            record_consequence_observation(self.store, "pm", "swinger")
        state = self.store.read_consequence_state("pm", "swinger")
        self.assertEqual(state["swinger_uncompensated_episodes"], 1)
        self.assertTrue(state["swinger_episode_open"])
        owner = build_capital_owner(
            self.store,
            "swinger",
            consequence=build_pm_consequence(self.store, "swinger"),
            pm_book={"max_drawdown_usd": 50_000_000.0, "cash_capital_usd": 1_000_000_000.0},
        )
        self.assertEqual(owner["standing"], "good_standing")
        self.assertTrue(all("suck" not in note.lower() for note in owner.get("notes") or []))

    def test_worsened_swinger_drawdown_opens_a_new_episode(self) -> None:
        self._set_swinger_realized(-22_000_000.0)
        record_consequence_observation(self.store, "pm", "swinger")
        self._set_swinger_realized(-45_000_000.0)
        record_consequence_observation(self.store, "pm", "swinger")
        state = self.store.read_consequence_state("pm", "swinger")
        self.assertEqual(state["swinger_uncompensated_episodes"], 2)
        owner = build_capital_owner(
            self.store,
            "swinger",
            consequence=build_pm_consequence(self.store, "swinger"),
            pm_book={"max_drawdown_usd": 50_000_000.0, "cash_capital_usd": 1_000_000_000.0},
        )
        self.assertEqual(owner["standing"], "watch")

    def test_recovered_then_distinct_swinger_drawdown_is_a_new_episode(self) -> None:
        self._set_swinger_realized(-30_000_000.0)
        record_consequence_observation(self.store, "pm", "swinger")
        self._set_swinger_realized(0.0)
        record_consequence_observation(self.store, "pm", "swinger")
        recovered = self.store.read_consequence_state("pm", "swinger")
        self.assertEqual(recovered["swinger_uncompensated_episodes"], 1)
        self.assertFalse(recovered["swinger_episode_open"])
        self._set_swinger_realized(-30_000_000.0)
        record_consequence_observation(self.store, "pm", "swinger")
        self.assertEqual(self.store.read_consequence_state("pm", "swinger")["swinger_uncompensated_episodes"], 2)

    def test_swinger_outsized_payoff_resets_episode_history(self) -> None:
        self._set_swinger_realized(-30_000_000.0)
        record_consequence_observation(self.store, "pm", "swinger")
        self._set_swinger_realized(25_000_000.0)
        record_consequence_observation(self.store, "pm", "swinger")
        state = self.store.read_consequence_state("pm", "swinger")
        self.assertEqual(state["swinger_uncompensated_episodes"], 0)
        self.assertFalse(state["swinger_episode_open"])

    def test_grinder_zero_alpha_not_forced(self) -> None:
        consequence = {"status": "ok", "net_after_funding_pnl_usd": 0.0, "max_drawdown_usd": 50_000_000.0}
        owner = build_capital_owner(self.store, "grinder", consequence=consequence, pm_book={"max_drawdown_usd": 50_000_000.0})
        self.assertTrue(owner["zero_alpha"])
        self.assertFalse(owner["persistent_zero_alpha"])
        self.assertEqual(owner["credible_opportunities"], "unknown")
        self.assertFalse(owner["force_deployment"])

    def test_grinder_flat_without_opportunities_stays_legitimate(self) -> None:
        self.store.write_consequence_state("pm", "grinder", {"grinder_flat_snapshots": 4})
        consequence = {"status": "ok", "net_after_funding_pnl_usd": 0.0, "max_drawdown_usd": 50_000_000.0}
        owner = build_capital_owner(
            self.store,
            "grinder",
            consequence=consequence,
            pm_book={"max_drawdown_usd": 50_000_000.0},
            review_packet={"trader_room": {"trades": []}, "overnight_review": {"decisions": []}},
        )
        self.assertEqual(owner["credible_opportunities"], "none")
        self.assertFalse(owner["persistent_zero_alpha"])
        self.assertFalse(owner["force_deployment"])
        self.assertEqual(owner["standing"], "good_standing")

    def test_grinder_missed_opportunity_flatness_raises_pressure(self) -> None:
        self.store.write_consequence_state("pm", "grinder", {"grinder_flat_snapshots": 2})
        consequence = {"status": "ok", "net_after_funding_pnl_usd": 0.0, "max_drawdown_usd": 50_000_000.0}
        packet = {
            "market_state": {"fx": {"USDCAD": {"spot": 1.36}}},
            "trader_room": {
                "trades": [
                    {"trade": {"instrument": "USDCAD", "asset_class": "spot_fx"}},
                ]
            },
        }
        owner = build_capital_owner(
            self.store,
            "grinder",
            consequence=consequence,
            pm_book={"max_drawdown_usd": 50_000_000.0},
            review_packet=packet,
        )
        self.assertEqual(owner["credible_opportunities"], "present")
        self.assertTrue(owner["persistent_zero_alpha"])
        self.assertFalse(owner["force_deployment"])
        self.assertEqual(owner["standing"], "watch")

    def _opportunity_packet(self) -> dict:
        return {
            "market_state": {"fx": {"USDCAD": {"spot": 1.36}}},
            "trader_room": {"trades": [{"trade": {"instrument": "USDCAD", "asset_class": "spot_fx"}}]},
        }

    def test_grinder_sitouts_do_not_become_missed_opportunity_pressure(self) -> None:
        self._write_pm_books(empty_pm_books())
        empty_packet = {"trader_room": {"trades": []}, "overnight_review": {"decisions": []}}
        record_consequence_observation(self.store, "pm", "grinder", review_packet=empty_packet)
        record_consequence_observation(self.store, "pm", "grinder", review_packet=None)
        record_consequence_observation(self.store, "pm", "grinder", review_packet=self._opportunity_packet())
        state = self.store.read_consequence_state("pm", "grinder")
        self.assertEqual(state["grinder_flat_snapshots"], 1)
        owner = build_capital_owner(
            self.store,
            "grinder",
            consequence=build_pm_consequence(self.store, "grinder"),
            pm_book={"max_drawdown_usd": 50_000_000.0},
            review_packet=self._opportunity_packet(),
        )
        self.assertFalse(owner["persistent_zero_alpha"])
        self.assertEqual(owner["standing"], "good_standing")
        self.assertFalse(owner["force_deployment"])

    def test_grinder_repeated_opportunity_flat_cycles_trigger_watch(self) -> None:
        self._write_pm_books(empty_pm_books())
        packet = self._opportunity_packet()
        record_consequence_observation(self.store, "pm", "grinder", review_packet=packet)
        record_consequence_observation(self.store, "pm", "grinder", review_packet=packet)
        self.assertEqual(self.store.read_consequence_state("pm", "grinder")["grinder_flat_snapshots"], 2)
        owner = build_capital_owner(
            self.store,
            "grinder",
            consequence=build_pm_consequence(self.store, "grinder"),
            pm_book={"max_drawdown_usd": 50_000_000.0},
            review_packet=packet,
        )
        self.assertTrue(owner["persistent_zero_alpha"])
        self.assertEqual(owner["standing"], "watch")
        self.assertFalse(owner["force_deployment"])

    def test_pragmatist_mandate_text_and_unavailable_spx(self) -> None:
        consequence = {"status": "ok", "net_after_funding_pnl_usd": 0.0}
        owner = build_capital_owner(self.store, "pragmatist", consequence=consequence, market_state=MARKET)
        joined = " ".join(owner.get("notes") or [])
        self.assertIn("2–6%", joined)
        self.assertIn("20", joined)
        self.assertEqual(owner["spx_context"]["status"], "unavailable")
        self.assertEqual(owner["stress_regime"], "unknown")

    def test_pragmatist_reads_frozen_market_state_when_present(self) -> None:
        self._write_pm_books(empty_pm_books())
        frozen = {
            "equities": {"spx": {"total_return_ytd": 11.0}},
            "stress_regime": "stress",
            "fx": {"USDCAD": {"spot": 1.36}},
        }
        evidence = {"market_state": frozen, "as_of": "2026-09-19T12:00:00Z"}
        market, memory_packet = memory_market_inputs(
            evidence,
            compact_market={"fx": {}},
            trader_room={"trades": []},
            overnight_review=None,
        )
        self.assertIs(market, frozen)
        context = compact_memory_for_packet(
            self.store,
            "pm",
            "pragmatist",
            market_state=market,
            review_packet=memory_packet,
        )
        owner = context["capital_owner"]
        self.assertEqual(owner["spx_context"]["status"], "ok")
        self.assertEqual(owner["spx_context"]["opportunity_cost_context_pct"], 7.0)
        self.assertEqual(owner["stress_regime"], "stress")

    def test_pragmatist_on_demand_packet_uses_same_frozen_market(self) -> None:
        on_demand_evidence = {
            "market_state": {
                "opportunities": {"series": [{"id": "SP500", "total_return_ytd": 8.0}]},
                "stress_regime": "normal",
            }
        }
        market, _packet = memory_market_inputs(on_demand_evidence, compact_market={"fx": {}})
        owner = build_capital_owner(
            self.store,
            "pragmatist",
            consequence={"status": "ok", "net_after_funding_pnl_usd": 0.0},
            market_state=market,
        )
        self.assertEqual(owner["spx_context"]["opportunity_cost_context_pct"], 4.0)
        self.assertEqual(owner["stress_regime"], "normal")

    def test_overnight_freeze_pm_sidecar_uses_frozen_market_state(self) -> None:
        from scripts.overnight.constants import ROOT
        from scripts.overnight.evidence import freeze_snapshot
        from scripts.overnight.store import OvernightStore

        self._write_pm_books(empty_pm_books())
        overnight = OvernightStore(root=ROOT, state_root=self.root)
        run_id = "overnight-20260919"
        frozen = {
            "equities": {"spx": {"total_return_ytd": 11.0}},
            "stress_regime": "stress",
        }
        overnight.write_artifact(
            run_id,
            "collect.json",
            {"families": {"market_state": {"status": "fresh", "data": frozen}}},
        )
        packet = freeze_snapshot(overnight, run_id=run_id, when=AS_OF, reuse_open=False)
        review_id = packet["review_id"]
        sidecar_path = overnight.review_dir(run_id, review_id) / "pm_memory" / "pragmatist.json"
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        owner = sidecar["capital_owner"]
        self.assertEqual(owner["spx_context"]["status"], "ok")
        self.assertEqual(owner["spx_context"]["opportunity_cost_context_pct"], 7.0)
        self.assertEqual(owner["stress_regime"], "stress")
        self.assertEqual(packet["pm_memory"]["hashes"]["pragmatist"], sidecar["memory_context_sha256"])
        trader_sidecar = json.loads(
            (overnight.review_dir(run_id, review_id) / "memory" / "dollar-king.json").read_text(encoding="utf-8")
        )
        self.assertIsNone(trader_sidecar.get("capital_owner"))
        self.assertNotEqual(packet["pm_memory"]["hashes"]["pragmatist"], packet["pm_memory"]["hashes"]["grinder"])

        bare = OvernightStore(root=ROOT, state_root=self.root / "bare")
        bare.write_artifact(
            run_id,
            "collect.json",
            {"families": {"market_state": {"status": "fresh", "data": {"fx": {"USDCAD": {"spot": 1.36}}}}}},
        )
        PMStore(root=self.root, state_root=self.root / "bare").write_books(empty_pm_books())
        bare_packet = freeze_snapshot(bare, run_id=run_id, when=AS_OF, reuse_open=False)
        bare_sidecar = json.loads(
            (bare.review_dir(run_id, bare_packet["review_id"]) / "pm_memory" / "pragmatist.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(bare_sidecar["capital_owner"]["spx_context"]["status"], "unavailable")
        self.assertEqual(bare_sidecar["capital_owner"]["stress_regime"], "unknown")

    def test_negative_pnl_is_material_loss_not_win(self) -> None:
        triggers = performance_triggers(
            owner_type="trader",
            book_row={"net_pnl_usd": -2_500_000.0, "drawdown_usd": 2_500_000.0, "high_water_nav_usd": 100_000_000.0, "max_drawdown_usd": 5_000_000.0},
            rank=8,
            prior_rank=None,
        )
        ids = {row["id"] for row in triggers}
        self.assertIn("material_loss", ids)
        self.assertNotIn("material_win", ids)
        self.assertIn("material_drawdown", ids)

    def test_unchanged_cumulative_pnl_does_not_create_a_new_event(self) -> None:
        books = empty_books(overnight_run_id="overnight-20260919", when=AS_OF)
        books["seats"]["dollar-king"]["realized_pnl_usd"] = -2_500_000.0
        self._write_trader_books(books)
        first = build_memory_context(self.store, "trader", "dollar-king")
        self.assertIn("material_loss", first["reflections_due"][0]["trigger_ids"])
        from scripts.trading.consequence import record_consequence_observation

        record_consequence_observation(self.store, "trader", "dollar-king", trader_books=self.overnight.read_books())
        second = build_memory_context(self.store, "trader", "dollar-king")
        due_items = self.store.read_reflections_due("trader", "dollar-king")["items"]
        self.assertEqual(len(due_items), 1)
        self.assertEqual(len(second["reflections_due"]), 1)

    def test_material_drawdown_threshold_two_million(self) -> None:
        threshold = MATERIAL_DRAWDOWN_FRACTION * MAX_DRAWDOWN_USD
        self.assertEqual(threshold, 2_000_000.0)

    def test_reflection_due_blocks_expansion_not_hold(self) -> None:
        books = empty_books(overnight_run_id="overnight-20260919", when=AS_OF)
        books["seats"]["dollar-king"]["realized_pnl_usd"] = -2_100_000.0
        self._write_trader_books(books)
        context = build_memory_context(self.store, "trader", "dollar-king")
        self.assertTrue(context["reflections_due"])
        decision = {
            "memory_context_sha256": context["memory_context_sha256"],
            "actions": [{"action": "OPEN", "instrument": "USDCAD", "side": "long", "rationale": "test"}],
        }
        _, blocked = evaluate_decision_actions(
            self.store,
            owner_type="trader",
            owner_id="dollar-king",
            decision=decision,
            run_id="overnight-20260920",
            expected_memory_sha256=context["memory_context_sha256"],
        )
        self.assertTrue(blocked)
        hold = {
            "memory_context_sha256": context["memory_context_sha256"],
            "actions": [{"action": "HOLD"}],
        }
        allowed, blocked_hold = evaluate_decision_actions(
            self.store,
            owner_type="trader",
            owner_id="dollar-king",
            decision=hold,
            run_id="overnight-20260920",
            expected_memory_sha256=context["memory_context_sha256"],
        )
        self.assertEqual(allowed, [{"action": "HOLD"}])
        self.assertFalse(blocked_hold)

    def test_ack_only_postmortem_rejected(self) -> None:
        due = self.store.read_postmortems_due("trader", "dollar-king")
        due["items"] = [
            {
                "postmortem_id": "pmd-test",
                "trade_id": "trd-test",
                "status": "due",
            }
        ]
        self.store.write_postmortems_due("trader", "dollar-king", due)
        self.store.write_trade(
            {
                "trade_id": "trd-test",
                "owner_type": "trader",
                "owner_id": "dollar-king",
                "status": "closed",
            }
        )
        with self.assertRaises(SchemaError):
            accept_postmortem(
                self.store,
                {"trade_id": "trd-test", "lesson": "ack only"},
                owner_type="trader",
                owner_id="dollar-king",
                run_id="overnight-20260920",
            )
        self.assertEqual(self.store.read_postmortems_due("trader", "dollar-king")["items"][0]["status"], "due")

    def test_reviews_from_run_preserves_learning_fields(self) -> None:
        originals = {
            seat: {
                "agent": seat,
                "confidence": 50,
                "trade": {"thesis": "t"},
                "paper_actions": [{"action": "HOLD"}],
                "postmortems": [{"trade_id": "trd-x", "what_worked": "a"}],
                "performance_reflections": [{"what_happened_vs_expected": "x"}],
            }
            for seat in STANDING_SEATS
        }
        reviews = reviews_from_run(originals, {}, {}, {"run_id": "tr-1", "packet_sha256": "x"})
        self.assertIn("postmortems", reviews["dollar-king"])
        self.assertIn("performance_reflections", reviews["dollar-king"])

    def test_public_projection_strips_taunt(self) -> None:
        books = empty_books(overnight_run_id="overnight-20260919", when=AS_OF)
        books["seats"]["dollar-king"]["thesis"] = (
            "I love risk. I'm starting to think you just suck at taking it. Oil is bid."
        )
        view = public_books_view(books)
        thesis = view["seats"][0]["thesis"] if view["seats"][0]["seat"] != "dollar-king" else next(
            row["thesis"] for row in view["seats"] if row["seat"] == "dollar-king"
        )
        self.assertNotIn("suck", thesis.lower())
        dumped = json.dumps(view)
        self.assertNotIn("capital_owner", dumped)
        self.assertNotIn("performance_reflection", dumped)

    def test_public_projection_drops_paraphrase_and_learning_gate_alerts(self) -> None:
        books = empty_books(overnight_run_id="overnight-20260919", when=AS_OF)
        books["seats"]["dollar-king"]["thesis"] = (
            "The allocator is wondering whether we should hand the book to the specialist. CAD is rich."
        )
        books["seats"]["dollar-king"]["alerts"] = [
            "dollar-king learning_gate: missing_pressure_assessment postmortems_due reflections_due",
            "max drawdown breached but one or more positions lack a deterministic exit mark",
        ]
        view = public_books_view(books)
        seat = next(row for row in view["seats"] if row["seat"] == "dollar-king")
        self.assertNotIn("allocator", seat["thesis"].lower())
        self.assertNotIn("hand the book", seat["thesis"].lower())
        joined = " ".join(seat["alerts"]).lower()
        self.assertNotIn("learning_gate", joined)
        self.assertNotIn("missing_pressure_assessment", joined)
        self.assertNotIn("postmortems_due", joined)
        self.assertNotIn("reflections_due", joined)
        self.assertTrue(any("drawdown" in alert.lower() for alert in seat["alerts"]))
        pm_books = empty_pm_books()
        pm_books["pms"]["grinder"]["alerts"] = [
            "grinder learning_gate: reflections_due rfd-abc123",
            "funding observation missing for one open position",
        ]
        pm_books["pms"]["grinder"]["thesis"] = "Maybe we should hand the book to the junior who earned more."
        pm_view = public_pm_view(pm_books)
        grinder = next(row for row in pm_view["pms"] if row["pm_id"] == "grinder")
        pm_alerts = " ".join(grinder["alerts"]).lower()
        self.assertNotIn("learning_gate", pm_alerts)
        self.assertNotIn("reflections_due", pm_alerts)
        self.assertNotIn("rfd-", pm_alerts)
        self.assertNotIn("hand the book", grinder["thesis"].lower())
        self.assertTrue(any("funding" in alert.lower() for alert in grinder["alerts"]))

    def test_memory_schema_version_two(self) -> None:
        context = build_memory_context(self.store, "trader", "dollar-king")
        self.assertEqual(context["schema_version"], MEMORY_SCHEMA_VERSION)
        self.assertIn("consequence", context)

    def _open_and_close_trader(self) -> tuple[dict, str]:
        hashes = self._memory_hashes()
        books = empty_books(overnight_run_id="overnight-20260919", when=AS_OF)
        reviews = {
            seat: {
                "seat": seat,
                "memory_context_sha256": hashes[seat],
                "expression_memo": _spot_memo(),
                "actions": [{"action": "HOLD"}],
            }
            for seat in STANDING_SEATS
        }
        reviews["dollar-king"] = {
            "seat": "dollar-king",
            "memory_context_sha256": hashes["dollar-king"],
            "expression_memo": _spot_memo(),
            "actions": [
                {
                    "action": "OPEN",
                    "instrument": "USDCAD",
                    "side": "long",
                    "notional_usd": 5_000_000,
                    "price": 1.36,
                    "asset_class": "spot_fx",
                    "rationale": "Open.",
                }
            ],
        }
        books = apply_trader_review_with_memory(
            books,
            reviews,
            families=_fresh_families(),
            run_id="overnight-20260919",
            evidence_cutoff="c",
            store=self.store,
            memory_hashes=hashes,
            when=AS_OF,
            market_state=MARKET,
        )
        pos_id = books["seats"]["dollar-king"]["positions"][0]["position_id"]
        close_reviews = deepcopy(reviews)
        hashes["dollar-king"] = build_memory_context(self.store, "trader", "dollar-king")["memory_context_sha256"]
        close_reviews["dollar-king"] = {
            "seat": "dollar-king",
            "memory_context_sha256": hashes["dollar-king"],
            "actions": [
                {"action": "CLOSE", "position_id": pos_id, "price": 1.36, "rationale": "Done."},
                {
                    "action": "OPEN",
                    "instrument": "USDCAD",
                    "side": "long",
                    "notional_usd": 1_000_000,
                    "price": 1.36,
                    "asset_class": "spot_fx",
                    "expression_memo": _spot_memo(),
                    "thesis": "Re-open.",
                    "rationale": "Re-open.",
                },
            ],
        }
        books = apply_trader_review_with_memory(
            books,
            close_reviews,
            families=_fresh_families(),
            run_id="overnight-20260919",
            evidence_cutoff="c",
            store=self.store,
            memory_hashes=hashes,
            when=AS_OF,
            market_state=MARKET,
        )
        return books, pos_id

    def test_same_run_close_does_not_block_sibling_open(self) -> None:
        books, _ = self._open_and_close_trader()
        self.assertEqual(len(books["seats"]["dollar-king"]["positions"]), 1)

    def test_reflection_no_new_lesson_clears_gate(self) -> None:
        books = empty_books(overnight_run_id="overnight-20260919", when=AS_OF)
        books["seats"]["dollar-king"]["realized_pnl_usd"] = -2_100_000.0
        self._write_trader_books(books)
        context = build_memory_context(self.store, "trader", "dollar-king")
        due_id = context["reflections_due"][0]["reflection_due_id"]
        accept_performance_reflection(
            self.store,
            {
                "reflection_due_id": due_id,
                "what_happened_vs_expected": "Drawdown matched the planned risk budget and stayed inside ordinary variance.",
                "attribution": ["sizing"],
                "pressure_effect": "none",
                "skill_vs_luck": "mixed",
                "overconfidence_risk": "no",
                "chase_or_revenge": "no",
                "causal": CAUSAL,
                "no_new_lesson": "The outcome was ordinary bounded variance and the prior process remains sound.",
            },
            owner_type="trader",
            owner_id="dollar-king",
            run_id="overnight-20260920",
        )
        refreshed = build_memory_context(self.store, "trader", "dollar-king")
        self.assertEqual(refreshed["reflections_due"], [])
        decision = {
            "memory_context_sha256": refreshed["memory_context_sha256"],
            "actions": [{"action": "OPEN", "instrument": "USDCAD", "side": "long", "rationale": "ok"}],
        }
        allowed, blocked = evaluate_decision_actions(
            self.store,
            owner_type="trader",
            owner_id="dollar-king",
            decision=decision,
            run_id="overnight-20260921",
            expected_memory_sha256=refreshed["memory_context_sha256"],
        )
        self.assertFalse(blocked)
        self.assertTrue(allowed)

    def test_reflection_lesson_stays_on_own_identity(self) -> None:
        books = empty_books(overnight_run_id="overnight-20260919", when=AS_OF)
        books["seats"]["dollar-king"]["realized_pnl_usd"] = -2_100_000.0
        self._write_trader_books(books)
        context = build_memory_context(self.store, "trader", "dollar-king")
        due_id = context["reflections_due"][0]["reflection_due_id"]
        accept_performance_reflection(
            self.store,
            {
                "reflection_due_id": due_id,
                "what_happened_vs_expected": "The extension failed because the expression was crowded.",
                "attribution": ["timing"],
                "pressure_effect": "distorting",
                "skill_vs_luck": "luck",
                "overconfidence_risk": "yes",
                "chase_or_revenge": "no",
                "causal": CAUSAL,
                "future_rule": "When the same crowded dollar setup appears, wait for confirmation before adding.",
                "lesson": "After a crowded dollar extension, wait for confirmation before adding risk.",
            },
            owner_type="trader",
            owner_id="dollar-king",
            run_id="overnight-20260920",
        )
        king = build_memory_context(self.store, "trader", "dollar-king")
        bear = build_memory_context(self.store, "trader", "perma-bear")
        self.assertTrue(king["active_lessons"])
        self.assertFalse(bear["active_lessons"])

    def test_pm_session_win_while_behind_does_not_increment_streak(self) -> None:
        trader_books = empty_books(overnight_run_id="overnight-20260919", when=AS_OF)
        trader_books["seats"]["dollar-king"]["realized_pnl_usd"] = 5_000_000.0
        self._write_trader_books(trader_books)
        pm_books = empty_pm_books()
        pm_books["pms"]["swinger"]["realized_pnl_usd"] = 0.0
        self._write_pm_books(pm_books)
        record_consequence_observation(self.store, "pm", "swinger")
        self.assertIsNone(self.store.read_consequence_state("pm", "swinger").get("best_trader_outearn_streak"))
        trader_books["seats"]["dollar-king"]["realized_pnl_usd"] = 6_000_000.0
        self._write_trader_books(trader_books)
        pm_books["pms"]["swinger"]["realized_pnl_usd"] = 2_000_000.0
        self._write_pm_books(pm_books)
        record_consequence_observation(self.store, "pm", "swinger")
        consequence = build_pm_consequence(self.store, "swinger")
        self.assertEqual(consequence["best_trader_outearn_streak"], 0)
        self.assertLess(consequence["gap_to_best_trader_usd"], 0)
        self.assertEqual(consequence["best_trader_net_pnl_usd"], 6_000_000.0)

    def test_consecutive_session_outearns_increment_streak(self) -> None:
        trader_books = empty_books(overnight_run_id="overnight-20260919", when=AS_OF)
        trader_books["seats"]["dollar-king"]["realized_pnl_usd"] = 1.0
        pm_books = empty_pm_books()
        self._write_trader_books(trader_books)
        self._write_pm_books(pm_books)
        record_consequence_observation(self.store, "pm", "pragmatist")
        trader_books["seats"]["dollar-king"]["realized_pnl_usd"] = 2_000_000.0
        pm_books["pms"]["pragmatist"]["realized_pnl_usd"] = 0.0
        self._write_trader_books(trader_books)
        self._write_pm_books(pm_books)
        record_consequence_observation(self.store, "pm", "pragmatist")
        self.assertEqual(build_pm_consequence(self.store, "pragmatist")["best_trader_outearn_streak"], 1)
        trader_books["seats"]["dollar-king"]["realized_pnl_usd"] = 4_000_000.0
        pm_books["pms"]["pragmatist"]["realized_pnl_usd"] = 1_000_000.0
        self._write_trader_books(trader_books)
        self._write_pm_books(pm_books)
        record_consequence_observation(self.store, "pm", "pragmatist")
        self.assertEqual(build_pm_consequence(self.store, "pragmatist")["best_trader_outearn_streak"], 2)

    def test_missing_prior_comparator_does_not_fabricate_streak(self) -> None:
        trader_books = empty_books(overnight_run_id="overnight-20260919", when=AS_OF)
        trader_books["seats"]["dollar-king"]["realized_pnl_usd"] = 3_000_000.0
        self._write_trader_books(trader_books)
        pm_books = empty_pm_books()
        pm_books["pms"]["grinder"]["realized_pnl_usd"] = 1_000_000.0
        self._write_pm_books(pm_books)
        record_consequence_observation(self.store, "pm", "grinder")
        self.assertIsNone(build_pm_consequence(self.store, "grinder")["best_trader_outearn_streak"])
        trader_books["seats"]["dollar-king"]["realized_pnl_usd"] = 1_000_000.0
        trader_books["seats"]["carry-is-king"]["realized_pnl_usd"] = 4_000_000.0
        self._write_trader_books(trader_books)
        record_consequence_observation(self.store, "pm", "grinder")
        self.assertIsNone(build_pm_consequence(self.store, "grinder")["best_trader_outearn_streak"])
        self.assertEqual(build_pm_consequence(self.store, "grinder")["best_trader_seat"], "carry-is-king")

    def test_invalid_memory_update_does_not_clear_reflection_debt(self) -> None:
        books = empty_books(overnight_run_id="overnight-20260919", when=AS_OF)
        books["seats"]["dollar-king"]["realized_pnl_usd"] = -2_100_000.0
        self._write_trader_books(books)
        context = build_memory_context(self.store, "trader", "dollar-king")
        due_id = context["reflections_due"][0]["reflection_due_id"]
        with self.assertRaises(SchemaError):
            accept_performance_reflection(
                self.store,
                {
                    "reflection_due_id": due_id,
                    "what_happened_vs_expected": "The loss came from chasing an entry that the packet did not confirm.",
                    "attribution": ["timing"],
                    "pressure_effect": "none",
                    "skill_vs_luck": "luck",
                    "overconfidence_risk": "no",
                    "chase_or_revenge": "no",
                    "causal": CAUSAL,
                    "memory_update": {
                        "op": "add",
                        "text": "Do not chase the same unconfirmed dollar entry after the catalyst has faded.",
                        "trade_ids": ["trd-missing"],
                    },
                },
                owner_type="trader",
                owner_id="dollar-king",
                run_id="overnight-20260920",
            )
        due = self.store.read_reflections_due("trader", "dollar-king")["items"]
        self.assertEqual(due[0]["status"], "due")
        self.assertEqual(self.store.read_reflections("trader", "dollar-king").get("items") or [], [])
        self.assertEqual(self.store.read_lessons("trader", "dollar-king").get("lessons") or [], [])

    def test_valid_reflection_commits_lesson_once(self) -> None:
        books = empty_books(overnight_run_id="overnight-20260919", when=AS_OF)
        books["seats"]["dollar-king"]["realized_pnl_usd"] = -2_100_000.0
        self._write_trader_books(books)
        context = build_memory_context(self.store, "trader", "dollar-king")
        due_id = context["reflections_due"][0]["reflection_due_id"]
        payload = {
            "reflection_due_id": due_id,
            "what_happened_vs_expected": "The loss came from chasing an entry that the packet did not confirm.",
            "attribution": ["timing"],
            "pressure_effect": "none",
            "skill_vs_luck": "luck",
            "overconfidence_risk": "no",
            "chase_or_revenge": "no",
            "causal": CAUSAL,
            "memory_update": {
                "op": "add",
                "text": "Do not chase the same unconfirmed dollar entry after the catalyst has faded.",
            },
        }
        accepted = accept_performance_reflection(
            self.store,
            payload,
            owner_type="trader",
            owner_id="dollar-king",
            run_id="overnight-20260920",
        )
        self.assertEqual(self.store.read_reflections_due("trader", "dollar-king")["items"][0]["status"], "submitted")
        self.assertEqual(len(self.store.read_reflections("trader", "dollar-king")["items"]), 1)
        self.assertEqual(len(self.store.read_lessons("trader", "dollar-king")["lessons"]), 1)
        self.assertEqual(accepted["lesson_id"], self.store.read_lessons("trader", "dollar-king")["lessons"][0]["lesson_id"])
        with self.assertRaises(SchemaError):
            accept_performance_reflection(
                self.store,
                payload,
                owner_type="trader",
                owner_id="dollar-king",
                run_id="overnight-20260921",
            )
        self.assertEqual(len(self.store.read_lessons("trader", "dollar-king")["lessons"]), 1)
        self.assertEqual(len(self.store.read_reflections("trader", "dollar-king")["items"]), 1)


if __name__ == "__main__":
    unittest.main()
