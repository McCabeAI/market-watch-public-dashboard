"""Prior-run learning obligations are a freeze-bound contract, not a submitted-row hint."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from scripts.overnight.books import empty_books, public_books_view
from scripts.overnight.constants import ROOT, STANDING_SEATS
from scripts.overnight.errors import SchemaError
from scripts.overnight.evidence import freeze_snapshot
from scripts.overnight.pipeline import run_stage
from scripts.overnight.public_prose import public_prose_issues, sanitize_public_prose
from scripts.overnight.scheduled_output import validate_execution, validate_output
from scripts.overnight.store import OvernightStore, sha256_json
from scripts.pm.books import public_pm_view
from scripts.pm.portfolio import synthetic_portfolio_construction
from scripts.trader_room.rates_scan import with_tenor_scan
from scripts.trading.apply import apply_trader_review_with_memory
from scripts.trading.gate import evaluate_decision_actions
from scripts.trading.consequence import build_trader_consequence
from scripts.trading.learning import (
    assert_obligation_coverage,
    read_learning_state,
    substantive_no_new_lesson,
)
from scripts.trading.memory import build_memory_context
from scripts.trading.obligations import manifest_from_frozen_review
from scripts.trading.store import TradingStore
from tests.test_overnight_scheduled_output import (
    AGENT_PACKET_TYPE,
    SCHEDULE_ID,
    _hold_decision,
    _pm_block,
)

AS_OF = datetime.fromisoformat("2026-09-28T01:55:00-04:00")
PRIOR_RUN = "overnight-20260925"
MONDAY = (
    ("value-guy", "pmd-d9e2764dea0f", "trd-vg-monday"),
    ("catalyst-junkie", "pmd-69691111cd40", "trd-cj-monday"),
    ("cross-merchant", "pmd-8ddf6ee19a94", "trd-cm-monday"),
    ("positioning-cynic", "pmd-86d9c87862a0", "trd-pc-monday-a"),
    ("positioning-cynic", "pmd-550c41ce938c", "trd-pc-monday-b"),
)
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
NO_NEW = "The outcome was ordinary bounded variance and the prior process remains sound."
LESSON = "When the dollar expression is already crowded, wait for confirmation before adding risk."
FUTURE_RULE = "Do not add to a crowded dollar expression until the reaction function confirms the thesis."
LESSON_SCOPE = {
    "instruments": ["EURUSD"],
    "setup_type": "crowded_extension",
    "failure_mode": "crowded_expression",
    "decision_dimension": "expression",
}


def _execution(total: int, grok: int, composer: int) -> dict:
    return {
        "parent_model": "grok-4.6",
        "allowed_subagent_models": ["composer-2.5", "grok-4.6"],
        "total_model_cap": 20,
        "grok_cap": 18,
        "composer_cap": 2,
        "declared_total_model_calls": total,
        "declared_grok_calls": grok,
        "declared_composer_calls": composer,
        "other_models_calls": 0,
        "auto_used": False,
    }


def _examiner(assessments: list[dict]) -> dict:
    return {
        "role": "learning_quality_examiner",
        "model": "composer-2.5",
        "call_count": 1,
        "assessments": assessments,
    }


def _grade(owner: str, obligation_id: str, state: str, *, kind: str = "postmortem") -> dict:
    return {
        "owner_type": "trader",
        "owner_id": owner,
        "submission_kind": kind,
        "submission_ref": obligation_id,
        "submission_state": state,
        "adequate": state == "adequate",
        "reasons": [] if state == "adequate" else [f"{state} causal reflection"],
    }


def _postmortem(trade_id: str, *, lesson: bool) -> dict:
    payload = {
        "trade_id": trade_id,
        "what_worked": "The growth differential was visible in the data I had before entry.",
        "what_failed": "The expression was already crowded relative to the catalyst that printed.",
        "causal": CAUSAL,
    }
    if lesson:
        payload["lesson"] = LESSON
        payload["future_rule"] = FUTURE_RULE
        payload["scope"] = LESSON_SCOPE
    else:
        payload["no_new_lesson"] = NO_NEW
    return payload


def _open_action(instrument: str = "USDCAD") -> dict:
    memo = {
        "rates_candidate": None,
        "spot_candidate": {"instrument": instrument, "asset_class": "spot_fx", "rationale": "spot"},
        "options_candidate": None,
        "selected": "spot",
        "rationale": "Dedicated spot expression from the frozen packet.",
    }
    return {
        "action": "OPEN",
        "instrument": instrument,
        "side": "long",
        "notional_usd": 10_000_000,
        "asset_class": "spot_fx",
        "expression_memo": memo,
        "thesis": "USD remains the cleanest expression against this pair.",
    }


def _rates_first_spot_open_action(instrument: str = "USDCAD") -> dict:
    memo = with_tenor_scan(
        {
            "rates_candidate": {"instrument": "US 10Y", "asset_class": "rates", "rationale": "duration"},
            "spot_candidate": {"instrument": instrument, "asset_class": "spot_fx", "rationale": "spot alt"},
            "options_candidate": None,
            "selected": "spot",
            "rationale": "Rates-first comparison complete after scanning STIR, 2Y, 5Y, 10Y, curve, and cross-market RV.",
        },
        selected_bucket="none",
    )
    return {
        "action": "OPEN",
        "instrument": instrument,
        "side": "long",
        "notional_usd": 10_000_000,
        "asset_class": "spot_fx",
        "expression_memo": memo,
        "thesis": "USD remains the cleanest expression against this pair.",
    }


class ObligationContractTests(unittest.TestCase):
    def test_shallow_no_new_lesson_is_rejected(self) -> None:
        with self.assertRaises(SchemaError):
            substantive_no_new_lesson("nothing learned from this crowded expression at all")
        with self.assertRaises(SchemaError):
            substantive_no_new_lesson(
                "Timing was bad, but I will call the rest ordinary variance so it looks complete."
            )
        self.assertIn("bounded variance", substantive_no_new_lesson(NO_NEW))

    def test_declared_nineteen_is_invalid_when_obligations_exist(self) -> None:
        with self.assertRaises(SchemaError) as caught:
            validate_execution(_execution(19, 18, 1), learning_examiner_required=True)
        self.assertIn("20/18/2", str(caught.exception))
        self.assertEqual(validate_execution(_execution(19, 18, 1))["declared_total_model_calls"], 19)
        self.assertEqual(
            validate_execution(_execution(20, 18, 2), learning_examiner_required=True)["declared_composer_calls"],
            2,
        )

    def test_coverage_rejects_spoofed_and_partial_grades(self) -> None:
        obligations = [
            {
                "owner_type": "trader",
                "owner_id": "value-guy",
                "kind": "postmortem",
                "obligation_id": "pmd-d9e2764dea0f",
                "reference": "trd-vg",
                "source_run_id": PRIOR_RUN,
            }
        ]
        submission = ("trader", "value-guy", _postmortem("trd-vg", lesson=False), "postmortem")
        good = [_grade("value-guy", "pmd-d9e2764dea0f", "adequate")]
        assert_obligation_coverage(obligations, [submission], good)
        with self.assertRaises(SchemaError) as unknown:
            assert_obligation_coverage(obligations, [submission], [_grade("value-guy", "pmd-deadbeef0000", "adequate")])
        self.assertIn("wrong-reference", str(unknown.exception))
        with self.assertRaises(SchemaError) as omitted:
            assert_obligation_coverage(obligations, [], [])
        self.assertIn("missing", str(omitted.exception))
        shallow = _postmortem("trd-vg", lesson=False)
        shallow["no_new_lesson"] = "nothing learned even though I mention ordinary variance and a sound process"
        with self.assertRaises(SchemaError) as spoof:
            assert_obligation_coverage(obligations, [("trader", "value-guy", shallow, "postmortem")], good)
        self.assertIn("shallow", str(spoof.exception))
        with self.assertRaises(SchemaError) as duplicate:
            assert_obligation_coverage(obligations, [submission, submission], good + good)
        self.assertIn("duplicate", str(duplicate.exception))


class _FrozenObligationCase(unittest.TestCase):
    obligations: tuple[tuple[str, str, str], ...] = MONDAY

    def _mutate_collect_before_freeze(self, store: OvernightStore, run_id: str) -> None:
        return None

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state_root = Path(self.tmp.name)
        self.run_id = "overnight-20260928"
        for stage in ("collect", "pre_trader_delta"):
            run_stage(
                stage,
                root=ROOT,
                state_root=self.state_root,
                run_id=self.run_id,
                when=AS_OF,
                dry_run=True,
                market_state_path=ROOT / "data" / "overnight" / "fixtures" / "market_state.json",
            )
        pre_freeze_store = OvernightStore(root=ROOT, state_root=self.state_root)
        self._mutate_collect_before_freeze(pre_freeze_store, self.run_id)
        self.trading = TradingStore(root=ROOT, state_root=self.state_root)
        self.trading.ensure_initialized()
        by_owner: dict[str, list[dict]] = {}
        for owner_id, obligation_id, trade_id in self.obligations:
            self.trading.write_trade(
                {
                    "trade_id": trade_id,
                    "owner_type": "trader",
                    "owner_id": owner_id,
                    "status": "closed",
                    "instrument": "USDCAD",
                    "side": "long",
                    "asset_class": "spot_fx",
                    "events": [{"kind": "CLOSE", "exit_reason_category": "other"}],
                }
            )
            by_owner.setdefault(owner_id, []).append(
                {
                    "postmortem_id": obligation_id,
                    "trade_id": trade_id,
                    "owner_type": "trader",
                    "owner_id": owner_id,
                    "created_at": "2026-09-25T12:00:00-04:00",
                    "created_run_id": PRIOR_RUN,
                    "status": "due",
                    "facts": {"instrument": "USDCAD", "side": "long"},
                }
            )
        for owner_id, items in by_owner.items():
            self.trading.write_postmortems_due(
                "trader",
                owner_id,
                {"schema_version": 1, "type": "TRADING_POSTMORTEMS_DUE", "items": items},
            )
        run_stage(
            "freeze_evidence",
            root=ROOT,
            state_root=self.state_root,
            run_id=self.run_id,
            when=AS_OF,
            dry_run=True,
            market_state_path=ROOT / "data" / "overnight" / "fixtures" / "market_state.json",
        )
        self.store = OvernightStore(root=ROOT, state_root=self.state_root)
        self.base = self.store.read_artifact(self.run_id, "evidence_snapshot.json")
        self.payload = self._payload()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _payload(self) -> dict:
        packet = {
            "schema_version": 1,
            "type": AGENT_PACKET_TYPE,
            "overnight_run_id": self.run_id,
            "review_id": self.base["review_id"],
            "base_packet_sha256": self.base["packet_sha256"],
            "base_evidence_cutoff": self.base["as_of"],
            "evidence_cutoff": "2026-09-28T02:20:00-04:00",
            "competition": self.base["competition"],
            "research_supplement": {
                "summary": "No material new research after the deterministic cutoff.",
                "news": [],
                "central_bank_research": [],
                "sources": [],
            },
        }
        packet["packet_sha256"] = sha256_json(packet)
        return {
            "schema_version": 1,
            "type": "OVERNIGHT_SCHEDULED_OUTPUT",
            "schedule_id": SCHEDULE_ID,
            "overnight_run_id": self.run_id,
            "review_id": self.base["review_id"],
            "base_packet_sha256": self.base["packet_sha256"],
            "agent_packet": packet,
            "decisions": {
                seat: _hold_decision(seat, self.run_id, packet["packet_sha256"], packet["evidence_cutoff"])
                for seat in STANDING_SEATS
            },
            "pm_decisions": _pm_block(self.run_id, packet["packet_sha256"], packet["evidence_cutoff"]),
            "execution": _execution(19, 18, 1),
        }

    def _ids(self) -> list[str]:
        return [row[1] for row in self.obligations]


class MondayManifestTests(_FrozenObligationCase):
    def test_manifest_is_freeze_bound_and_private_to_each_identity(self) -> None:
        binding = self.base["learning_obligations"]
        self.assertNotIn("obligations", binding)
        self.assertNotIn("pmd-", json.dumps(binding))
        manifest = self.store.read_artifact(self.run_id, "learning_obligations.json", review_id=self.base["review_id"])
        obligations = manifest["obligations"]
        ids = [row["obligation_id"] for row in obligations]
        self.assertCountEqual(ids, self._ids())
        sort_keys = [(row["owner_type"], row["owner_id"], row["kind"], row["obligation_id"]) for row in obligations]
        self.assertEqual(sort_keys, sorted(sort_keys))
        self.assertEqual(manifest["overnight_run_id"], self.run_id)
        self.assertEqual(manifest["review_id"], self.base["review_id"])
        self.assertEqual(binding["manifest_sha256"], manifest["manifest_sha256"])
        self.assertEqual(binding["obligation_count"], len(obligations))
        self.assertEqual(
            manifest["manifest_sha256"],
            self.store.read_artifact(self.run_id, "evidence_snapshot.json")["learning_obligations"]["manifest_sha256"],
        )
        derived = manifest_from_frozen_review(
            self.store,
            run_id=self.run_id,
            review_id=self.base["review_id"],
            seat_hashes=self.base["seat_memory"]["hashes"],
            pm_hashes=self.base["pm_memory"]["hashes"],
        )
        self.assertEqual(derived["manifest_sha256"], manifest["manifest_sha256"])
        mutated = json.loads(json.dumps(self.base))
        mutated["learning_obligations"]["manifest_sha256"] = "0" * 64
        self.assertNotEqual(
            sha256_json({k: v for k, v in mutated.items() if k != "packet_sha256"}),
            self.base["packet_sha256"],
        )
        review_dir = self.store.review_dir(self.run_id, self.base["review_id"])
        value = json.loads((review_dir / "memory" / "value-guy.json").read_text(encoding="utf-8"))
        catalyst = json.loads((review_dir / "memory" / "catalyst-junkie.json").read_text(encoding="utf-8"))
        grinder = json.loads((review_dir / "pm_memory" / "grinder.json").read_text(encoding="utf-8"))
        self.assertEqual([row["obligation_id"] for row in value["learning_obligations"]], ["pmd-d9e2764dea0f"])
        self.assertNotIn("pmd-d9e2764dea0f", json.dumps(catalyst))
        self.assertNotIn("pmd-69691111cd40", json.dumps(value))
        self.assertNotIn("pmd-d9e2764dea0f", json.dumps(grinder))
        self.assertEqual(grinder["learning_obligations"], [])

    def test_omitted_submissions_cannot_skip_the_examiner_or_declare_nineteen(self) -> None:
        with self.assertRaises(SchemaError) as nineteen:
            validate_output(self.store, self.payload)
        self.assertIn("20/18/2", str(nineteen.exception))
        self.payload["execution"] = _execution(20, 18, 2)
        with self.assertRaises(SchemaError) as missing_review:
            validate_output(self.store, json.loads(json.dumps(self.payload)))
        self.assertIn("learning_quality_review", str(missing_review.exception))

    def test_explicit_missing_grades_leave_debt_and_learning_default(self) -> None:
        self.payload["execution"] = _execution(20, 18, 2)
        self.payload["learning_quality_review"] = _examiner(
            [_grade(owner, obligation_id, "missing") for owner, obligation_id, _trade in self.obligations]
        )
        self.payload["decisions"]["value-guy"]["thesis"] = (
            "USD stays bid. learning_audit examiner_assessment pmd-d9e2764dea0f no_new_lesson."
        )
        from scripts.overnight.scheduled_output import apply_output

        review = apply_output(self.store, self.payload)
        audit = self.store.read_artifact(self.run_id, "learning_audit.json", review_id=self.base["review_id"])
        self.assertTrue(audit["examiner_invoked"])
        self.assertEqual(audit["prior_obligations"], 5)
        self.assertEqual(audit["submitted"], 0)
        self.assertEqual(audit["examiner_assessments"], 5)
        self.assertEqual(audit["missing"], 5)
        self.assertEqual(audit["adequate"], 0)
        self.assertEqual(audit["cleared"], 0)
        self.assertEqual(audit["unresolved_debt"], 5)
        self.assertEqual(audit["candidate_lessons_created"], 0)
        self.assertEqual(audit["no_new_lesson_count"], 0)
        self.assertNotIn("learning_audit", review)
        stored_output = self.store.read_artifact(self.run_id, "scheduled_output.json", review_id=self.base["review_id"])
        self.assertNotIn("_trusted_learning_audit_seed", stored_output)
        obligated = ("value-guy", "catalyst-junkie", "cross-merchant", "positioning-cynic")
        for seat in STANDING_SEATS:
            state = read_learning_state(self.trading, "trader", seat)
            if seat in obligated:
                self.assertEqual(state["learning_status"], "learning_default")
                self.assertFalse(state["competition_eligible"])
                self.assertGreaterEqual(state["learning_default_age_runs"], 1)
                self.assertIsNone(build_trader_consequence(self.trading, seat)["competitive_rank"])
            else:
                self.assertNotEqual(state["learning_status"], "learning_default")
                self.assertTrue(state["competition_eligible"])
        for _owner, obligation_id, _trade in self.obligations:
            owner = next(row[0] for row in self.obligations if row[1] == obligation_id)
            items = self.trading.read_postmortems_due("trader", owner)["items"]
            matched = next(row for row in items if row["postmortem_id"] == obligation_id)
            self.assertEqual(matched["status"], "due")
        public = json.dumps(public_books_view(review["books"]))
        self.assertNotIn("learning_audit", public)
        self.assertNotIn("examiner_assessment", public)
        self.assertNotIn("pmd-d9e2764dea0f", public)
        self.assertNotIn("no_new_lesson", public)
        self.assertTrue(public_prose_issues("learning_audit examiner_assessment pmd-d9e2764dea0f"))
        self.assertNotIn("learning_audit", sanitize_public_prose(self.payload["decisions"]["value-guy"]["thesis"], max_chars=700, fallback=""))
        pm_public = json.dumps(public_pm_view(review["pm_books"]))
        self.assertNotIn("learning_audit", pm_public)
        self.assertNotIn("pmd-", pm_public)


class MondayHappyPathTests(_FrozenObligationCase):
    def test_five_adequate_reflections_are_assessed_once_and_need_not_create_lessons(self) -> None:
        self.payload["execution"] = _execution(20, 18, 2)
        assessments = []
        for owner, obligation_id, trade_id in self.obligations:
            self.payload["decisions"][owner].setdefault("postmortems", []).append(_postmortem(trade_id, lesson=False))
            assessments.append(_grade(owner, obligation_id, "adequate"))
        self.payload["learning_quality_review"] = _examiner(assessments)
        from scripts.overnight.scheduled_output import apply_output

        apply_output(self.store, self.payload)
        audit = self.store.read_artifact(self.run_id, "learning_audit.json", review_id=self.base["review_id"])
        self.assertEqual(audit["examiner_assessments"], 5)
        self.assertEqual(len({row["obligation_id"] for row in audit["obligation_results"]}), 5)
        self.assertEqual(audit["adequate"], 5)
        self.assertEqual(audit["submitted"], 5)
        self.assertEqual(audit["cleared"], 5)
        self.assertEqual(audit["unresolved_debt"], 0)
        self.assertEqual(audit["missing"], 0)
        self.assertEqual(audit["no_new_lesson_count"], 5)
        self.assertEqual(audit["candidate_lessons_created"], 0)
        self.assertTrue(audit["examiner_invoked"])
        for owner, obligation_id, _trade in self.obligations:
            items = self.trading.read_postmortems_due("trader", owner)["items"]
            matched = next(row for row in items if row["postmortem_id"] == obligation_id)
            self.assertEqual(matched["status"], "submitted")
            state = read_learning_state(self.trading, "trader", owner)
            self.assertTrue(state["competition_eligible"])
            self.assertNotEqual(state["learning_status"], "learning_default")
            self.assertEqual(self.trading.read_lessons("trader", owner)["lessons"], [])


class MixedOutcomeTests(_FrozenObligationCase):
    obligations = (
        ("value-guy", "pmd-a11ade000001", "trd-mixed-lesson"),
        ("catalyst-junkie", "pmd-b22ade000002", "trd-mixed-nonew"),
        ("cross-merchant", "pmd-c33ade000003", "trd-mixed-bad"),
        ("positioning-cynic", "pmd-d44ade000004", "trd-mixed-miss"),
    )

    def _mutate_collect_before_freeze(self, store: OvernightStore, run_id: str) -> None:
        for artifact in ("collect.json", "pre_trader_delta.json"):
            if not store.has_artifact(run_id, artifact):
                continue
            doc = store.read_artifact(run_id, artifact)
            macro = doc["families"]["macro_hard"]
            macro["status"] = "fresh"
            macro["as_of"] = "2026-09-28T01:55:00-04:00"
            macro["fresh_countries"] = ["US", "CA", "AU", "NZ", "EA", "JP"]
            macro["stale_countries"] = []
            store.write_artifact(run_id, artifact, doc)

    def test_lesson_no_new_inadequate_and_missing_gate_expansion_independently(self) -> None:
        modes = {
            "value-guy": "lesson",
            "catalyst-junkie": "no_new",
            "cross-merchant": "inadequate",
            "positioning-cynic": "missing",
        }
        assessments = []
        for owner, obligation_id, trade_id in self.obligations:
            mode = modes[owner]
            decision = self.payload["decisions"][owner]
            decision["memory_context_sha256"] = self.base["seat_memory"]["hashes"][owner]
            decision["thesis"] = "USD remains the cleanest G10 expression in the frozen packet."
            if owner in ("value-guy", "catalyst-junkie"):
                open_action = _rates_first_spot_open_action()
            else:
                open_action = _open_action()
            if owner == "value-guy":
                open_action["setup_fingerprint"] = {
                    "setup_type": "usd_cad_handoff",
                    "catalyst_type": "frozen_overnight",
                    "market_drivers": ["usd"],
                }
            decision["actions"] = [{"action": "HOLD"}, open_action]
            if mode == "missing":
                state = "missing"
            elif mode == "inadequate":
                decision["postmortems"] = [_postmortem(trade_id, lesson=False)]
                state = "inadequate"
            else:
                decision["postmortems"] = [_postmortem(trade_id, lesson=mode == "lesson")]
                state = "adequate"
            assessments.append(_grade(owner, obligation_id, state))
        self.payload["execution"] = _execution(20, 18, 2)
        self.payload["learning_quality_review"] = _examiner(assessments)
        pm = self.payload["pm_decisions"]
        pm["pragmatist"]["portfolio_construction"] = synthetic_portfolio_construction(
            opportunities=[
                {
                    "instrument": "USDCAD",
                    "rationale": "Independent markable USD-CAD handoff from the frozen overnight review.",
                    "markable": True,
                },
            ],
            existing_book="Pragmatist book is flat in this scheduled-output fixture.",
            rationale="Evaluated the USD-CAD handoff; HOLD remains valid for the opportunistic book.",
        )
        from scripts.overnight.scheduled_output import apply_output

        review = apply_output(self.store, self.payload)
        audit = self.store.read_artifact(self.run_id, "learning_audit.json", review_id=self.base["review_id"])
        self.assertEqual(audit["submitted"], 3)
        self.assertEqual(audit["adequate"], 2)
        self.assertEqual(audit["inadequate"], 1)
        self.assertEqual(audit["missing"], 1)
        self.assertEqual(audit["cleared"], 2)
        self.assertEqual(audit["unresolved_debt"], 2)
        self.assertEqual(audit["candidate_lessons_created"], 1)
        self.assertEqual(audit["candidate_lessons_refined"], 0)
        self.assertEqual(audit["candidate_lessons_reinforced"], 0)
        self.assertEqual(audit["no_new_lesson_count"], 1)
        self.assertTrue(audit["examiner_invoked"])

        books = review["books"]["seats"]
        self.assertEqual(len(books["value-guy"]["positions"]), 1)
        self.assertEqual(len(books["catalyst-junkie"]["positions"]), 1)
        self.assertEqual(books["cross-merchant"]["positions"], [])
        self.assertEqual(books["positioning-cynic"]["positions"], [])
        self.assertEqual(books["cross-merchant"]["last_action"], "HOLD")
        self.assertEqual(books["positioning-cynic"]["last_action"], "HOLD")

        lesson_rows = self.trading.read_lessons("trader", "value-guy")["lessons"]
        self.assertEqual(len(lesson_rows), 1)
        lesson = lesson_rows[0]
        self.assertEqual(lesson["maturity"], "candidate")
        self.assertEqual(lesson["source_run_id"], self.run_id)
        self.assertIn("pmd-a11ade000001", lesson["postmortem_ids"])
        self.assertEqual(lesson["scope"]["instruments"], ["EURUSD"])
        retrieved = build_memory_context(self.trading, "trader", "value-guy", exclude_run_id=self.run_id)
        self.assertEqual(retrieved["active_lessons"][0]["lesson_id"], lesson["lesson_id"])
        self.assertEqual(retrieved["active_lessons"][0]["maturity"], "candidate")
        self.assertEqual(self.trading.read_lessons("trader", "catalyst-junkie")["lessons"], [])
        self.assertEqual(self.trading.read_postmortems_due("trader", "cross-merchant")["items"][0]["status"], "due")
        self.assertEqual(self.trading.read_postmortems_due("trader", "positioning-cynic")["items"][0]["status"], "due")
        self.assertEqual(self.trading.read_postmortems_due("trader", "value-guy")["items"][0]["status"], "submitted")
        self.assertEqual(self.trading.read_postmortems_due("trader", "catalyst-junkie")["items"][0]["status"], "submitted")
        for owner, eligible in (
            ("value-guy", True),
            ("catalyst-junkie", True),
            ("cross-merchant", False),
            ("positioning-cynic", False),
        ):
            state = read_learning_state(self.trading, "trader", owner)
            self.assertEqual(state["competition_eligible"], eligible)
            rank = build_trader_consequence(self.trading, owner)["competitive_rank"]
            if eligible:
                self.assertIsNotNone(rank)
            else:
                self.assertIsNone(rank)
                self.assertEqual(state["learning_status"], "learning_default")
        peer = json.dumps(build_memory_context(self.trading, "trader", "dollar-king", exclude_run_id=self.run_id))
        self.assertNotIn("pmd-a11ade000001", peer)
        self.assertNotIn(lesson["lesson_id"], peer)


class DeRiskWithDebtTests(unittest.TestCase):
    def test_debt_allows_derisk_and_same_run_close_stays_out_of_the_manifest(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        state = Path(tmp.name)
        trading = TradingStore(root=ROOT, state_root=state)
        overnight = OvernightStore(root=ROOT, state_root=state)
        trading.ensure_initialized()
        market = {
            "generated_at": "2026-09-27T12:00:00Z",
            "fx": {"pairs": {"USDCAD": {"spot": 1.36, "as_of": "2026-09-27"}, "USDJPY": {"spot": 148.0, "as_of": "2026-09-27"}}},
        }
        families = {
            "macro_hard": {"status": "fresh", "as_of": "2026-09-27T00:07:00-04:00", "digest": "m"},
            "news": {"status": "fresh", "as_of": "2026-09-27T00:07:00-04:00", "digest": "n"},
            "central_bank_research": {"status": "fresh", "as_of": "2026-09-27T00:07:00-04:00", "digest": "c"},
            "market_state": {"status": "fresh", "as_of": "2026-09-27T00:07:00-04:00", "digest": "s", "data": market},
        }
        when = datetime.fromisoformat("2026-09-27T12:00:00-04:00")
        hashes = {seat: build_memory_context(trading, "trader", seat, when=when)["memory_context_sha256"] for seat in STANDING_SEATS}
        reviews = {
            seat: {"seat": seat, "memory_context_sha256": hashes[seat], "actions": [{"action": "HOLD"}]}
            for seat in STANDING_SEATS
        }
        memo = {
            "rates_candidate": None,
            "spot_candidate": {"instrument": "USDCAD", "asset_class": "spot_fx", "rationale": "spot"},
            "options_candidate": None,
            "selected": "spot",
            "rationale": "Two spot legs.",
        }
        reviews["dollar-king"]["actions"] = [
            {
                "action": "OPEN",
                "instrument": "USDCAD",
                "side": "long",
                "notional_usd": 10_000_000,
                "asset_class": "spot_fx",
                "expression_memo": memo,
                "thesis": "CAD leg.",
            },
            {
                "action": "OPEN",
                "instrument": "USDJPY",
                "side": "long",
                "notional_usd": 8_000_000,
                "asset_class": "spot_fx",
                "expression_memo": {**memo, "spot_candidate": {"instrument": "USDJPY", "asset_class": "spot_fx", "rationale": "spot"}},
                "thesis": "JPY leg.",
            },
        ]
        books = apply_trader_review_with_memory(
            empty_books(overnight_run_id="overnight-20260927", when=when),
            reviews,
            families=families,
            run_id="overnight-20260927",
            evidence_cutoff="2026-09-27T12:00:00-04:00",
            store=trading,
            memory_hashes=hashes,
            when=when,
            market_state=market,
        )
        overnight.write_books(books)
        trading.write_trade(
            {
                "trade_id": "trd-prior-debt",
                "owner_type": "trader",
                "owner_id": "dollar-king",
                "status": "closed",
                "instrument": "EURUSD",
                "events": [{"kind": "CLOSE", "exit_reason_category": "other"}],
            }
        )
        trading.write_postmortems_due(
            "trader",
            "dollar-king",
            {
                "schema_version": 1,
                "type": "TRADING_POSTMORTEMS_DUE",
                "items": [
                    {
                        "postmortem_id": "pmd-priordebt001",
                        "trade_id": "trd-prior-debt",
                        "owner_type": "trader",
                        "owner_id": "dollar-king",
                        "created_at": "2026-09-25T12:00:00-04:00",
                        "created_run_id": PRIOR_RUN,
                        "status": "due",
                        "facts": {},
                    }
                ],
            },
        )
        run_id = "overnight-20260928"
        overnight.write_artifact(run_id, "collect.json", {"families": families, "as_of": "2026-09-28T01:55:00-04:00"})
        packet = freeze_snapshot(overnight, run_id=run_id, when=AS_OF, reuse_open=False)
        self.assertNotIn("pmd-priordebt001", json.dumps(packet["learning_obligations"]))
        private_manifest = overnight.read_artifact(run_id, "learning_obligations.json", review_id=packet["review_id"])
        manifest_ids = [row["obligation_id"] for row in private_manifest["obligations"]]
        self.assertEqual(manifest_ids, ["pmd-priordebt001"])
        self.assertEqual(packet["learning_obligations"]["manifest_sha256"], private_manifest["manifest_sha256"])
        prior = packet["prior_books"]
        positions = {row["instrument"]: row for row in prior["seats"]["dollar-king"]["positions"]}
        frozen_hash = packet["seat_memory"]["hashes"]["dollar-king"]
        close_reviews = {
            seat: {
                "seat": seat,
                "memory_context_sha256": packet["seat_memory"]["hashes"][seat],
                "actions": [{"action": "HOLD"}],
            }
            for seat in STANDING_SEATS
        }
        dollar_king_actions = [
            {"action": "HOLD"},
            {"action": "NO_TRADE"},
            {
                "action": "REDUCE",
                "position_id": positions["USDCAD"]["position_id"],
                "notional_usd": 1_000_000,
                "thesis": "Trim the CAD leg.",
            },
            {
                "action": "CLOSE",
                "position_id": positions["USDJPY"]["position_id"],
                "thesis": "Close the JPY leg.",
            },
            _open_action("EURUSD"),
        ]
        close_reviews["dollar-king"] = {
            "seat": "dollar-king",
            "memory_context_sha256": frozen_hash,
            "actions": dollar_king_actions,
        }
        allowed, gate_blocked = evaluate_decision_actions(
            trading,
            owner_type="trader",
            owner_id="dollar-king",
            decision=close_reviews["dollar-king"],
            run_id=run_id,
            expected_memory_sha256=frozen_hash,
            trader_books=prior,
        )
        self.assertEqual({row["action"] for row in allowed}, {"HOLD", "NO_TRADE", "REDUCE", "CLOSE"})
        self.assertEqual(len(gate_blocked), 1)
        self.assertEqual(gate_blocked[0]["action"]["action"], "OPEN")
        blocked_reason = gate_blocked[0].get("reason") or gate_blocked[0].get("blocked_reason") or ""
        self.assertIn("postmortems_due", blocked_reason)
        close_reviews["dollar-king"]["actions"] = [
            row for row in dollar_king_actions if row.get("action") != "NO_TRADE"
        ]
        updated = apply_trader_review_with_memory(
            prior,
            close_reviews,
            families=families,
            run_id=run_id,
            review_id=packet["review_id"],
            evidence_cutoff="2026-09-28T02:20:00-04:00",
            store=trading,
            memory_hashes=packet["seat_memory"]["hashes"],
            when=AS_OF,
            market_state=market,
        )
        seat = updated["seats"]["dollar-king"]
        kept = {row["instrument"]: row for row in seat["positions"]}
        self.assertIn("USDCAD", kept)
        self.assertNotIn("USDJPY", kept)
        self.assertNotIn("EURUSD", kept)
        self.assertEqual(kept["USDCAD"]["notional_usd"], 9_000_000)
        blocked = [row for row in seat["history"] if row.get("result") == "blocked"]
        self.assertTrue(any(row.get("action") == "OPEN" and "postmortems_due" in str(row.get("note") or row) for row in blocked))
        self.assertEqual(trading.read_postmortems_due("trader", "dollar-king")["items"][0]["status"], "due")
        created = [
            row
            for row in trading.read_postmortems_due("trader", "dollar-king")["items"]
            if row["postmortem_id"] != "pmd-priordebt001"
        ]
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["created_run_id"], run_id)
        self.assertNotIn(created[0]["postmortem_id"], manifest_ids)
        reread = overnight.read_artifact(run_id, "evidence_snapshot.json", review_id=packet["review_id"])
        self.assertEqual(reread["learning_obligations"], packet["learning_obligations"])
        again = manifest_from_frozen_review(
            overnight,
            run_id=run_id,
            review_id=packet["review_id"],
            seat_hashes=packet["seat_memory"]["hashes"],
            pm_hashes=packet["pm_memory"]["hashes"],
        )
        self.assertEqual([row["obligation_id"] for row in again["obligations"]], ["pmd-priordebt001"])
        state = read_learning_state(trading, "trader", "dollar-king")
        self.assertEqual(state["learning_status"], "learning_default")
        self.assertFalse(state["competition_eligible"])
        public = json.dumps(public_books_view(updated))
        self.assertNotIn("pmd-priordebt001", public)
        self.assertNotIn("postmortems_due", public)
        self.assertNotIn("learning_default", public)
