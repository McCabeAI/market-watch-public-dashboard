#!/usr/bin/env python3
"""Regression coverage for trader learning v2 acceptance cases."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.overnight.books import empty_books, mark_to_market, public_books_view, validate_books
from scripts.overnight.errors import SchemaError as OvernightSchemaError
from scripts.overnight.constants import STANDING_SEATS
from scripts.overnight.scheduled_output import TOTAL_MODEL_CAP, validate_execution
from scripts.overnight.store import OvernightStore
from scripts.pm.books import empty_books as empty_pm_books
from scripts.pm.books import public_pm_view
from scripts.pm.books import validate_books as validate_pm_books
from scripts.pm.store import PMStore
from scripts.trading.apply import apply_pm_decision_with_memory, apply_trader_review_with_memory
from scripts.trading.capital_owner import build_capital_owner
from scripts.trading.consequence import build_pm_consequence, build_trader_consequence
from scripts.trading.constants import ESTABLISHED_REINFORCEMENT_THRESHOLD
from scripts.trading.errors import LearningGateError, SchemaError
from scripts.trading.gate import evaluate_decision_actions
from scripts.overnight.scheduled_output import _enforce_learning_quality
from scripts.trading.learning import (
    assert_examiner_coverage,
    compliance_learning_triggers,
    drop_inadequate_learning_submissions,
    inadequate_submission_refs,
    journal_learning_triggers,
    migrate_lesson,
    read_learning_state,
    record_retrieved_lessons,
    validate_learning_quality_review,
)
from scripts.trading.memory import (
    accept_performance_reflection,
    accept_postmortem,
    apply_memory_update,
    build_memory_context,
    reflection_obligation_already_covered,
)
from scripts.trading.store import TradingStore

NY = ZoneInfo("America/New_York")
AS_OF = datetime(2026, 9, 19, 12, 0, tzinfo=NY)
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
LESSON_SCOPE = {
    "instruments": ["USDCAD"],
    "asset_class": "spot_fx",
    "setup_type": "crowded_extension",
    "catalyst_type": "growth_data",
    "market_drivers": ["dollar", "growth"],
    "failure_mode": "crowded_expression",
    "decision_dimension": "expression",
}
FINGERPRINT = {
    "setup_type": "crowded_extension",
    "catalyst_type": "growth_data",
    "market_drivers": ["dollar", "growth"],
    "failure_mode": "crowded_expression",
    "decision_dimension": "expression",
}


def _families() -> dict:
    market = {"generated_at": "2026-09-19T12:00:00Z", "fx": {"pairs": {"USDCAD": {"spot": 1.36}}}}
    return {
        "macro_hard": {"status": "fresh", "as_of": "2026-09-19T00:07:00-04:00", "digest": "m"},
        "news": {"status": "fresh", "as_of": "2026-09-19T00:07:00-04:00", "digest": "n"},
        "central_bank_research": {"status": "fresh", "as_of": "2026-09-19T00:07:00-04:00", "digest": "c"},
        "market_state": {"status": "fresh", "as_of": "2026-09-19T00:07:00-04:00", "digest": "s", "data": market},
    }


class TraderLearningV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = TradingStore(root=self.root, state_root=self.root)
        self.store.ensure_initialized()
        self.overnight = OvernightStore(root=self.root, state_root=self.root)
        self.pm_store = PMStore(root=self.root, state_root=self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _books(self) -> dict:
        books = empty_books(overnight_run_id="overnight-20260919", when=AS_OF)
        for seat in STANDING_SEATS:
            mark_to_market(books["seats"][seat], when=AS_OF)
        self.overnight.write_books(validate_books(books))
        return books

    def _due_reflection(self) -> str:
        books = self._books()
        books["seats"]["dollar-king"]["realized_pnl_usd"] = -2_100_000.0
        for seat in STANDING_SEATS:
            mark_to_market(books["seats"][seat], when=AS_OF)
        self.overnight.write_books(validate_books(books))
        context = build_memory_context(self.store, "trader", "dollar-king")
        return context["reflections_due"][0]["reflection_due_id"]

    def _hold_reviews(self, hashes: dict[str, str]) -> dict:
        return {
            seat: {
                "seat": seat,
                "memory_context_sha256": hashes.get(seat),
                "actions": [{"action": "HOLD"}],
            }
            for seat in STANDING_SEATS
        }

    def test_prior_debt_is_mandatory_on_hold_and_shallow_text_does_not_clear_it(self) -> None:
        due_id = self._due_reflection()
        with self.assertRaises(SchemaError):
            accept_performance_reflection(
                self.store,
                {
                    "reflection_due_id": due_id,
                    "what_happened_vs_expected": "I lost money",
                    "attribution": ["timing"],
                    "pressure_effect": "none",
                    "skill_vs_luck": "luck",
                    "overconfidence_risk": "no",
                    "chase_or_revenge": "no",
                    "causal": {"original_belief": "timing was bad"},
                    "no_new_lesson": "timing was bad",
                },
                owner_type="trader",
                owner_id="dollar-king",
                run_id="overnight-20260920",
            )
        self.assertEqual(self.store.read_reflections_due("trader", "dollar-king")["items"][0]["status"], "due")
        hashes = {seat: build_memory_context(self.store, "trader", seat)["memory_context_sha256"] for seat in STANDING_SEATS}
        books = self.overnight.read_books()
        updated = apply_trader_review_with_memory(
            books,
            self._hold_reviews(hashes),
            families=_families(),
            run_id="overnight-20260920",
            evidence_cutoff="c",
            store=self.store,
            memory_hashes=hashes,
            when=AS_OF,
        )
        self.assertEqual(updated["seats"]["dollar-king"]["last_action"], "HOLD")
        state = read_learning_state(self.store, "trader", "dollar-king")
        self.assertEqual(state["learning_status"], "learning_default")
        self.assertFalse(state["competition_eligible"])
        consequence = build_trader_consequence(self.store, "dollar-king")
        self.assertEqual(consequence["raw_pnl_rank"], consequence["competition_rank"])
        self.assertIsNone(consequence["competitive_rank"])
        self.assertIsNotNone(consequence["net_pnl_usd"])

    def test_substantive_no_new_lesson_and_candidate_lesson(self) -> None:
        due_id = self._due_reflection()
        accept_performance_reflection(
            self.store,
            {
                "reflection_due_id": due_id,
                "what_happened_vs_expected": "The drawdown stayed inside the planned risk budget.",
                "attribution": ["variance_luck"],
                "pressure_effect": "none",
                "skill_vs_luck": "luck",
                "overconfidence_risk": "no",
                "chase_or_revenge": "no",
                "causal": CAUSAL,
                "no_new_lesson": "This was ordinary bounded variance and the prior process remains sound.",
            },
            owner_type="trader",
            owner_id="dollar-king",
            run_id="overnight-20260920",
        )
        self.assertEqual(build_memory_context(self.store, "trader", "dollar-king")["reflections_due"], [])
        self.assertTrue(read_learning_state(self.store, "trader", "dollar-king")["competition_eligible"])
        due = self.store.read_reflections_due("trader", "dollar-king")
        due["items"].append({
            "reflection_due_id": "rfd-second",
            "status": "due",
            "created_run_id": "overnight-20260920",
            "trigger_ids": ["thesis_invalidated"],
            "fingerprint": "second-fingerprint",
        })
        self.store.write_reflections_due("trader", "dollar-king", due)
        due_id = "rfd-second"
        accept_performance_reflection(
            self.store,
            {
                "reflection_due_id": due_id,
                "what_happened_vs_expected": "The crowded expression faded the catalyst.",
                "attribution": ["expression"],
                "pressure_effect": "none",
                "skill_vs_luck": "mixed",
                "overconfidence_risk": "no",
                "chase_or_revenge": "no",
                "causal": CAUSAL,
                "lesson": "Fade the first extension when the dollar expression is already crowded.",
                "future_rule": "When USDCAD is a crowded extension into growth data, do not add, because the reaction function fades it.",
                "scope": LESSON_SCOPE,
            },
            owner_type="trader",
            owner_id="dollar-king",
            run_id="overnight-20260921",
        )
        lesson = build_memory_context(self.store, "trader", "dollar-king")["active_lessons"][0]
        self.assertEqual(lesson["maturity"], "candidate")
        self.assertIn("future_rule", lesson)
        self.assertFalse(build_memory_context(self.store, "trader", "perma-bear")["active_lessons"])

    def test_legacy_lesson_migrates_and_unrelated_lesson_does_not_block(self) -> None:
        legacy = migrate_lesson(
            {
                "lesson_id": "les-legacy",
                "text": "Old prose lesson about oil supply shocks and spare capacity.",
                "status": "active",
                "reinforcement_count": 2,
                "trade_ids": [],
            }
        )
        self.assertEqual(legacy["maturity"], "candidate")
        self.assertEqual(legacy["future_rule"], legacy["text"])
        self.assertEqual(legacy["contradiction_count"], 0)
        doc = self.store.read_lessons("trader", "dollar-king")
        doc["lessons"] = [legacy]
        self.store.write_lessons("trader", "dollar-king", doc)
        context = build_memory_context(self.store, "trader", "dollar-king")
        decision = {
            "memory_context_sha256": context["memory_context_sha256"],
            "actions": [{
                "action": "OPEN",
                "instrument": "AUDUSD",
                "asset_class": "spot_fx",
                "side": "long",
                "rationale": "Different setup.",
                "setup_fingerprint": {"setup_type": "rates_carry", "catalyst_type": "rba", "market_drivers": ["carry"]},
            }],
        }
        allowed, blocked = evaluate_decision_actions(
            self.store,
            owner_type="trader",
            owner_id="dollar-king",
            decision=decision,
            run_id="overnight-20260922",
            expected_memory_sha256=context["memory_context_sha256"],
        )
        self.assertTrue(allowed)
        self.assertFalse(blocked)

    def test_matching_lesson_requires_disposition_and_ignore_blocks(self) -> None:
        due_id = self._due_reflection()
        accept_performance_reflection(
            self.store,
            {
                "reflection_due_id": due_id,
                "what_happened_vs_expected": "The crowded expression faded the catalyst.",
                "attribution": ["expression"],
                "pressure_effect": "none",
                "skill_vs_luck": "mixed",
                "overconfidence_risk": "no",
                "chase_or_revenge": "no",
                "causal": CAUSAL,
                "lesson": "Fade the first extension when the dollar expression is already crowded.",
                "future_rule": "When USDCAD is a crowded extension into growth data, do not add.",
                "scope": LESSON_SCOPE,
            },
            owner_type="trader",
            owner_id="dollar-king",
            run_id="overnight-20260921",
        )
        context = build_memory_context(self.store, "trader", "dollar-king")
        lesson_id = context["active_lessons"][0]["lesson_id"]
        ignored = {
            "memory_context_sha256": context["memory_context_sha256"],
            "actions": [{
                "action": "OPEN",
                "instrument": "USDCAD",
                "asset_class": "spot_fx",
                "side": "long",
                "rationale": "Add anyway.",
                "setup_fingerprint": FINGERPRINT,
            }],
        }
        _, blocked = evaluate_decision_actions(
            self.store,
            owner_type="trader",
            owner_id="dollar-king",
            decision=ignored,
            run_id="overnight-20260922",
            expected_memory_sha256=context["memory_context_sha256"],
        )
        self.assertTrue(blocked)
        self.assertIn("lesson_not_addressed", blocked[0]["reason"])
        addressed = {
            **ignored,
            "lesson_considerations": [{
                "lesson_id": lesson_id,
                "disposition": "OVERRIDE",
                "rationale": "The crowding has cleared and the new catalyst is a different growth surprise than the failed extension.",
            }],
        }
        allowed, blocked_ok = evaluate_decision_actions(
            self.store,
            owner_type="trader",
            owner_id="dollar-king",
            decision=addressed,
            run_id="overnight-20260922",
            expected_memory_sha256=context["memory_context_sha256"],
        )
        self.assertTrue(allowed)
        self.assertFalse(blocked_ok)

    def test_reinforcement_promotion_and_contradiction_history(self) -> None:
        self.store.write_trade({
            "trade_id": "trd-cite",
            "owner_type": "trader",
            "owner_id": "dollar-king",
            "status": "closed",
        })
        lesson = apply_memory_update(
            self.store,
            {"op": "add", "text": "Fade crowded dollar extensions after a faded growth catalyst.", "trade_ids": ["trd-cite"], "scope": LESSON_SCOPE},
            owner_type="trader",
            owner_id="dollar-king",
            run_id="r1",
        )
        self.assertEqual(lesson["maturity"], "candidate")
        for run in ("r2", "r3"):
            lesson = apply_memory_update(
                self.store,
                {"op": "reinforce", "lesson_id": lesson["lesson_id"], "trade_ids": ["trd-cite"]},
                owner_type="trader",
                owner_id="dollar-king",
                run_id=run,
            )
        self.assertGreaterEqual(lesson["reinforcement_count"], ESTABLISHED_REINFORCEMENT_THRESHOLD)
        self.assertEqual(lesson["maturity"], "established")
        self.store.write_learning_state(
            "trader",
            "dollar-king",
            {
                **read_learning_state(self.store, "trader", "dollar-king"),
                "retrieved_lessons": [{"lesson_id": lesson["lesson_id"], "run_id": "r3"}],
            },
        )
        contradicted = apply_memory_update(
            self.store,
            {"op": "contradict", "lesson_id": lesson["lesson_id"], "text": "A later clean growth surprise extended instead of fading."},
            owner_type="trader",
            owner_id="dollar-king",
            run_id="r4",
        )
        self.assertEqual(contradicted["contradiction_count"], 1)
        self.assertTrue(any(row.get("op") == "add" or row.get("op") == "reinforce" for row in contradicted["history"]))
        self.assertTrue(read_learning_state(self.store, "trader", "dollar-king")["repeated_error_escalations"])

    def test_pm_learning_default_sets_probation_without_failing_the_book(self) -> None:
        trader_books = self._books()
        pm_books = empty_pm_books()
        self.pm_store.write_books(validate_pm_books(pm_books))
        due = self.store.read_reflections_due("pm", "grinder")
        due["items"] = [{
            "reflection_due_id": "rfd-grinder",
            "status": "due",
            "created_run_id": "overnight-20260919",
            "trigger_ids": ["material_loss"],
            "fingerprint": "abc",
        }]
        self.store.write_reflections_due("pm", "grinder", due)
        context = build_memory_context(self.store, "pm", "grinder", trader_books=trader_books)
        updated = apply_pm_decision_with_memory(
            pm_books,
            {"pm_id": "grinder", "memory_context_sha256": context["memory_context_sha256"], "actions": [{"action": "HOLD"}]},
            pm_id="grinder",
            store=self.store,
            market_state={},
            run_id="overnight-20260920",
            evidence_cutoff="c",
            review_packet_id="pkt",
            review_packet_sha256="hash",
            expected_memory_sha256=context["memory_context_sha256"],
            when=AS_OF,
            trader_books=trader_books,
        )
        self.assertEqual(updated["pms"]["grinder"]["positions"], [])
        owner = build_capital_owner(self.store, "grinder", consequence=build_pm_consequence(self.store, "grinder"), pm_book=updated["pms"]["grinder"])
        self.assertEqual(owner["standing"], "probation")
        accept_performance_reflection(
            self.store,
            {
                "reflection_due_id": "rfd-grinder",
                "what_happened_vs_expected": "The flat result was ordinary variance against the hurdle.",
                "attribution": ["variance_luck"],
                "pressure_effect": "not_applicable",
                "skill_vs_luck": "luck",
                "overconfidence_risk": "not_applicable",
                "chase_or_revenge": "not_applicable",
                "causal": CAUSAL,
                "no_new_lesson": "The outcome was ordinary bounded variance and the prior process remains sound.",
            },
            owner_type="pm",
            owner_id="grinder",
            run_id="overnight-20260921",
        )
        hashes_context = build_memory_context(self.store, "pm", "grinder", trader_books=trader_books)
        apply_pm_decision_with_memory(
            updated,
            {"pm_id": "grinder", "memory_context_sha256": hashes_context["memory_context_sha256"], "actions": [{"action": "HOLD"}]},
            pm_id="grinder",
            store=self.store,
            market_state={},
            run_id="overnight-20260921",
            evidence_cutoff="c",
            review_packet_id="pkt2",
            review_packet_sha256="hash2",
            expected_memory_sha256=hashes_context["memory_context_sha256"],
            when=AS_OF,
            trader_books=trader_books,
        )
        self.assertTrue(read_learning_state(self.store, "pm", "grinder")["competition_eligible"])
        self.assertNotEqual(read_learning_state(self.store, "pm", "grinder")["learning_status"], "learning_default")

    def test_public_output_hides_learning_machinery_and_examiner_cannot_trade(self) -> None:
        books = self._books()
        books["seats"]["dollar-king"]["alerts"] = [
            "dollar-king learning_default lesson_considerations setup_fingerprint",
            "max drawdown breached but one or more positions lack a deterministic exit mark",
        ]
        view = public_books_view(books)
        seat = next(row for row in view["seats"] if row["seat"] == "dollar-king")
        joined = " ".join(seat["alerts"]).lower()
        self.assertNotIn("learning_default", joined)
        self.assertNotIn("lesson_considerations", joined)
        self.assertTrue(any("drawdown" in alert.lower() for alert in seat["alerts"]))
        pm_books = empty_pm_books()
        pm_books["pms"]["grinder"]["alerts"] = ["learning_quality examiner said OVERRIDE"]
        pm_view = public_pm_view(pm_books)
        grinder = next(row for row in pm_view["pms"] if row["pm_id"] == "grinder")
        self.assertFalse(grinder["alerts"])
        with self.assertRaises(SchemaError):
            validate_learning_quality_review({
                "role": "learning_quality_examiner",
                "model": "composer-2.5",
                "call_count": 1,
                "actions": [{"action": "OPEN"}],
                "assessments": [],
            })
        review = validate_learning_quality_review({
            "role": "learning_quality_examiner",
            "model": "composer-2.5",
            "call_count": 1,
            "assessments": [{
                "owner_type": "trader",
                "owner_id": "dollar-king",
                "submission_kind": "performance_reflection",
                "submission_ref": "rfd-1",
                "adequate": False,
                "reasons": ["causal divergence is only a P&L restatement"],
            }],
        })
        self.assertFalse(review["assessments"][0]["adequate"])
        self.assertNotIn("actions", review)

    def test_postmortem_causal_gate_and_budget_contract(self) -> None:
        self.store.write_trade({
            "trade_id": "trd-pm",
            "owner_type": "trader",
            "owner_id": "dollar-king",
            "status": "closed",
            "instrument": "USDCAD",
            "realized_pnl_usd": -10.0,
        })
        with self.assertRaises(SchemaError):
            accept_postmortem(
                self.store,
                {"trade_id": "trd-pm", "what_failed": "I lost money", "lesson": "I lost money"},
                owner_type="trader",
                owner_id="dollar-king",
                run_id="overnight-20260920",
            )
        execution = validate_execution({
            "parent_model": "grok-4.6",
            "allowed_subagent_models": ["composer-2.5", "grok-4.6"],
            "total_model_cap": TOTAL_MODEL_CAP,
            "grok_cap": 18,
            "composer_cap": 2,
            "declared_total_model_calls": 20,
            "declared_grok_calls": 18,
            "declared_composer_calls": 2,
            "other_models_calls": 0,
            "auto_used": False,
        })
        self.assertEqual(execution["declared_total_model_calls"], 20)
        self.assertEqual(TOTAL_MODEL_CAP, 20)

    def test_examiner_coverage_is_one_for_one(self) -> None:
        submission = ("trader", "dollar-king", {"reflection_due_id": "rfd-1"}, "performance_reflection")
        good = [{
            "owner_type": "trader",
            "owner_id": "dollar-king",
            "submission_kind": "performance_reflection",
            "submission_ref": "rfd-1",
            "adequate": True,
            "reasons": [],
        }]
        assert_examiner_coverage([submission], good)
        cases = {
            "missing": [],
            "duplicate": good + good,
            "unknown": [{
                **good[0],
                "owner_id": "value-guy",
                "submission_ref": "rfd-unknown",
            }],
            "wrong-owner": [{**good[0], "owner_id": "value-guy"}],
            "wrong-kind": [{**good[0], "submission_kind": "postmortem"}],
            "wrong-reference": [{**good[0], "submission_ref": "rfd-other"}],
        }
        for token, assessments in cases.items():
            with self.assertRaises(SchemaError) as ctx:
                assert_examiner_coverage([submission], assessments)
            self.assertIn(token, str(ctx.exception))

        payload = {
            "decisions": {
                "dollar-king": {
                    "performance_reflections": [{
                        "reflection_due_id": "rfd-1",
                        "what_happened_vs_expected": "The crowded expression faded.",
                    }],
                },
            },
        }
        with self.assertRaises(OvernightSchemaError) as missing_review:
            _enforce_learning_quality(dict(payload))
        self.assertIn("learning_quality_review", str(missing_review.exception))
        rejected = {
            **payload,
            "learning_quality_review": {
                "role": "learning_quality_examiner",
                "model": "composer-2.5",
                "call_count": 1,
                "assessments": [{**good[0], "adequate": False, "reasons": ["causal account is a platitude"]}],
            },
        }
        _enforce_learning_quality(rejected)
        self.assertEqual(rejected["decisions"]["dollar-king"]["performance_reflections"], [])
        with self.assertRaises(OvernightSchemaError) as duplicate:
            _enforce_learning_quality({
                **payload,
                "learning_quality_review": {
                    "role": "learning_quality_examiner",
                    "model": "composer-2.5",
                    "call_count": 1,
                    "assessments": good + [{**good[0], "adequate": False}],
                },
            })
        self.assertIn("duplicate", str(duplicate.exception))

    def test_rejected_or_shallow_learning_cannot_clear_debt(self) -> None:
        due_id = self._due_reflection()
        reflection = {
            "reflection_due_id": due_id,
            "what_happened_vs_expected": "The drawdown stayed inside the planned risk budget.",
            "attribution": ["variance_luck"],
            "pressure_effect": "none",
            "skill_vs_luck": "luck",
            "overconfidence_risk": "no",
            "chase_or_revenge": "no",
            "causal": CAUSAL,
            "no_new_lesson": "This was ordinary bounded variance and the prior process remains sound.",
        }
        blocked = inadequate_submission_refs({
            "assessments": [{
                "owner_type": "trader",
                "owner_id": "dollar-king",
                "submission_kind": "performance_reflection",
                "submission_ref": due_id,
                "adequate": False,
                "reasons": ["rejected"],
            }],
        })
        dropped = drop_inadequate_learning_submissions(
            {"performance_reflections": [reflection], "actions": [{"action": "HOLD"}]},
            owner_type="trader",
            owner_id="dollar-king",
            blocked_refs=blocked,
        )
        self.assertEqual(dropped["performance_reflections"], [])
        hashes = {seat: build_memory_context(self.store, "trader", seat)["memory_context_sha256"] for seat in STANDING_SEATS}
        reviews = self._hold_reviews(hashes)
        reviews["dollar-king"] = {
            **dropped,
            "seat": "dollar-king",
            "memory_context_sha256": hashes["dollar-king"],
        }
        apply_trader_review_with_memory(
            self.overnight.read_books(),
            reviews,
            families=_families(),
            run_id="overnight-20260920",
            evidence_cutoff="c",
            store=self.store,
            memory_hashes=hashes,
            when=AS_OF,
        )
        self.assertEqual(self.store.read_reflections_due("trader", "dollar-king")["items"][0]["status"], "due")
        self.assertEqual(read_learning_state(self.store, "trader", "dollar-king")["learning_status"], "learning_default")
        with self.assertRaises(SchemaError):
            accept_performance_reflection(
                self.store,
                {**reflection, "what_happened_vs_expected": "I lost money", "no_new_lesson": "I lost money"},
                owner_type="trader",
                owner_id="dollar-king",
                run_id="overnight-20260920",
            )
        self.assertEqual(self.store.read_reflections_due("trader", "dollar-king")["items"][0]["status"], "due")

    def test_journal_triggers_use_ledger_facts_and_ignore_dead_fields(self) -> None:
        phantom = {
            "trade_id": "trd-phantom",
            "status": "closed",
            "entry_thesis": "Dollar strength extends.",
            "instrument": "USDCAD",
            "asset_class": "spot_fx",
            "paper_expression": {"type": "spot", "pair": "USDCAD"},
            "events": [{
                "kind": "CLOSE",
                "exit_reason_category": "target_reached",
                "close_path": "diverged_from_thesis",
                "expression_vs_thesis": "right_thesis_wrong_expression",
                "reaction_vs_expectation": "materially_different",
            }],
        }
        ids = {row["id"] for row in journal_learning_triggers([phantom])}
        self.assertFalse(ids & {"close_reason_diverges", "right_thesis_wrong_expression", "catalyst_or_reaction_diverged"})

        funding = {
            "trade_id": "trd-fund",
            "status": "closed",
            "entry_thesis": "Carry would pay for the draw.",
            "events": [{"kind": "CLOSE", "exit_reason_category": "funding"}],
        }
        self.assertIn("close_reason_diverges", {row["id"] for row in journal_learning_triggers([funding])})

        invalidated = {
            "trade_id": "trd-expr",
            "status": "closed",
            "entry_thesis": "USDCAD spot would extend.",
            "instrument": "USDCAD",
            "asset_class": "spot_fx",
            "paper_expression": {"type": "futures_strip_average", "curve_id": "sofr", "contracts": ["SR3U6"]},
            "catalysts": ["growth_data"],
            "events": [{"kind": "CLOSE", "exit_reason_category": "thesis_invalidated"}],
        }
        invalidated_ids = {row["id"] for row in journal_learning_triggers([invalidated])}
        self.assertEqual(invalidated_ids, {"thesis_invalidated"})

        mismatched = {
            **invalidated,
            "trade_id": "trd-risk",
            "events": [{"kind": "CLOSE", "exit_reason_category": "risk_cut"}],
        }
        mismatched_ids = {row["id"] for row in journal_learning_triggers([mismatched])}
        self.assertEqual(mismatched_ids, {"stop_or_forced_exit", "right_thesis_wrong_expression"})

        state = {
            "repeated_error_escalations": [{"lesson_id": "les-1", "failure_mode": "crowded_expression", "count": 2}],
        }
        lessons = [{"lesson_id": "les-1", "history": [{"op": "contradict", "run_id": "r4"}]}]
        compliance_ids = {row["id"] for row in compliance_learning_triggers(state, lessons)}
        self.assertEqual(compliance_ids, {"repeated_same_failure_mode", "explicit_lesson_contradiction"})
        again = compliance_learning_triggers(
            state,
            lessons,
            already_obligated={
                ("repeated_same_failure_mode", "les-1"),
                ("explicit_lesson_contradiction", "les-1"),
            },
        )
        self.assertEqual(again, [])

    def test_distinct_lesson_contradictions_stay_distinct_obligations(self) -> None:
        covered = [{
            "trigger_ids": ["material_loss", "explicit_lesson_contradiction"],
            "facts": {
                "net_pnl_usd": -2_100_000.0,
                "drawdown_usd": 0.0,
                "competition_rank": 3,
                "lesson_ids": ["les-1"],
                "trade_ids": [],
            },
        }]
        same_economics = {
            "net_pnl": -2_100_000.0,
            "drawdown": 0.0,
            "rank": 3,
        }
        self.assertTrue(reflection_obligation_already_covered(
            covered,
            [{"id": "material_loss"}],
            **same_economics,
        ))
        self.assertFalse(reflection_obligation_already_covered(
            covered,
            [{"id": "explicit_lesson_contradiction", "lesson_id": "les-2"}],
            **same_economics,
        ))
        self.assertFalse(reflection_obligation_already_covered(
            covered,
            [{"id": "material_loss"}],
            net_pnl=-2_600_000.0,
            drawdown=0.0,
            rank=3,
        ))

    def test_lesson_disposition_is_persisted_for_the_owner_only(self) -> None:
        due_id = self._due_reflection()
        accept_performance_reflection(
            self.store,
            {
                "reflection_due_id": due_id,
                "what_happened_vs_expected": "The crowded expression faded the catalyst.",
                "attribution": ["expression"],
                "pressure_effect": "none",
                "skill_vs_luck": "mixed",
                "overconfidence_risk": "no",
                "chase_or_revenge": "no",
                "causal": CAUSAL,
                "lesson": "Fade the first extension when the dollar expression is already crowded.",
                "future_rule": "When USDCAD is a crowded extension into growth data, do not add.",
                "scope": LESSON_SCOPE,
            },
            owner_type="trader",
            owner_id="dollar-king",
            run_id="overnight-20260921",
        )
        context = build_memory_context(self.store, "trader", "dollar-king")
        lesson_id = context["active_lessons"][0]["lesson_id"]
        hashes = {seat: build_memory_context(self.store, "trader", seat)["memory_context_sha256"] for seat in STANDING_SEATS}
        reviews = self._hold_reviews(hashes)
        reviews["dollar-king"] = {
            "seat": "dollar-king",
            "memory_context_sha256": hashes["dollar-king"],
            "actions": [{
                "action": "OPEN",
                "instrument": "USDCAD",
                "asset_class": "spot_fx",
                "side": "long",
                "notional_usd": 1_000_000,
                "price": 1.36,
                "rationale": "The crowding has cleared enough to express the dollar view in the cash pair.",
                "setup_fingerprint": FINGERPRINT,
                "lesson_considerations": [{
                    "lesson_id": lesson_id,
                    "disposition": "APPLIES",
                    "rationale": "The same crowded growth-data extension is back, so the lesson applies and size stays small.",
                }],
            }],
        }
        apply_trader_review_with_memory(
            self.overnight.read_books(),
            reviews,
            families=_families(),
            run_id="overnight-20260922",
            evidence_cutoff="c",
            store=self.store,
            memory_hashes=hashes,
            when=AS_OF,
            market_state=_families()["market_state"]["data"],
        )
        rows = read_learning_state(self.store, "trader", "dollar-king")["retrieved_lessons"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["lesson_id"], lesson_id)
        self.assertEqual(rows[0]["disposition"], "APPLIES")
        self.assertEqual(rows[0]["owner_id"], "dollar-king")
        self.assertEqual(rows[0]["owner_type"], "trader")
        self.assertEqual(rows[0]["run_id"], "overnight-20260922")
        self.assertTrue(rows[0]["rationale"])
        self.assertEqual(rows[0]["instruments"], ["USDCAD"])
        self.assertEqual(read_learning_state(self.store, "trader", "mean-reverter")["retrieved_lessons"], [])
        record_retrieved_lessons(
            self.store,
            "trader",
            "dollar-king",
            lesson_ids=[lesson_id],
            run_id="overnight-20260922",
            dispositions={lesson_id: {"disposition": "OVERRIDE", "rationale": "should not replace"}},
        )
        again = read_learning_state(self.store, "trader", "dollar-king")["retrieved_lessons"]
        self.assertEqual(len(again), 1)
        self.assertEqual(again[0]["disposition"], "APPLIES")

    def test_expansion_still_raises_when_debt_remains(self) -> None:
        self._due_reflection()
        context = build_memory_context(self.store, "trader", "dollar-king")
        with self.assertRaises(LearningGateError):
            hashes = {seat: build_memory_context(self.store, "trader", seat)["memory_context_sha256"] for seat in STANDING_SEATS}
            reviews = self._hold_reviews(hashes)
            reviews["dollar-king"]["actions"] = [{
                "action": "OPEN",
                "instrument": "USDCAD",
                "side": "long",
                "notional_usd": 1_000_000,
                "price": 1.36,
                "asset_class": "spot_fx",
                "rationale": "Still expanding with debt.",
            }]
            apply_trader_review_with_memory(
                self.overnight.read_books(),
                reviews,
                families=_families(),
                run_id="overnight-20260920",
                evidence_cutoff="c",
                store=self.store,
                memory_hashes=hashes,
                when=AS_OF,
                market_state=_families()["market_state"]["data"],
            )
        self.assertIn("learning", context)


if __name__ == "__main__":
    unittest.main()
