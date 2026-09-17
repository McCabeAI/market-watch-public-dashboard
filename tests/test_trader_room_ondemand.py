#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.trader_room.artifacts import retrieve
from scripts.trader_room.budget import BudgetLedger
from scripts.trader_room.conflict import currency_exposure, detect_conflicts, rebuttal_assignments
from scripts.trader_room.constants import (
    ADVOCATE_MODEL,
    ADVOCATE_REMITS,
    COMPARISON_AGENTS,
    COMPOSER_CEILING,
    GROK_CEILING,
    HANDOFF_MARKER,
    NO_TRADE_AGENT,
    SPOT_SPECIALIST_AGENTS,
    STANDING_ADVOCATES,
    SUBAGENT_MODEL,
    TRADE_REQUIRED_AGENTS,
    VOL_SPECIALIST_AGENT,
)
from scripts.trader_room.mandate import validate_expression_comparison
from scripts.trader_room.errors import (
    BudgetError,
    DataBoundaryError,
    EvidenceImmutabilityError,
    EvidencePreflightError,
    IndependentSeatRequired,
    LiveRunBlocked,
    ModelPolicyError,
    ParentAuthoredSeatError,
    SchemaError,
)
from scripts.trader_room.evidence import (
    assemble_packet,
    assess_families,
    assert_same_frozen_packet,
    freeze_packet,
    load_synthetic_packet,
    validate_preflight,
)
from scripts.trader_room.models import (
    assert_advocate_model,
    assert_subagent_model,
    load_registry,
    trader_room_hook_policy,
)
from scripts.trader_room.artifacts import sanitize_packet
from scripts.trader_room.hook_enforce import decide as hook_decide
from scripts.trader_room.independent import persist_independent_run
from scripts.trader_room.orchestrator import go, prepare_evidence, run_debate, run_recorded_debate
from scripts.trader_room.production_live import build_live_originals, build_live_rebuttals
from scripts.trader_room.provenance import stamp_independent_invocation
from scripts.trader_room.runners import DryRunRunner, LiveRunner
from scripts.trader_room.schema import validate_contribution, validate_pm_handoff, validate_trade


def _packet() -> dict:
    raw = load_synthetic_packet(ROOT / "trader-room" / "fixtures" / "minimal_evidence.json")
    frozen, _ = freeze_packet(raw)
    return frozen


class ModelPolicyTests(unittest.TestCase):
    def test_registry_pins_exact_ids(self):
        registry = load_registry()
        self.assertEqual(registry["advocate_model"], "grok-4.6")
        self.assertEqual(registry["aggregator_model"], "grok-4.6")
        self.assertEqual(registry["agent_frontmatter_model"], "grok-4.6[]")
        self.assertEqual(registry["subagent_models"], ["composer-2.5"])
        self.assertIn("grok-4.5", registry["forbidden_models"])

    def test_frontmatter_normalizes_to_grok(self):
        self.assertEqual(assert_advocate_model("grok-4.6[]"), "grok-4.6")
        with self.assertRaises(ModelPolicyError):
            assert_advocate_model("grok-4.5")
        with self.assertRaises(ModelPolicyError):
            assert_subagent_model("composer-2.5-fast")
        with self.assertRaises(ModelPolicyError):
            assert_subagent_model("grok-4.6")

    def test_hook_policy_line(self):
        line = trader_room_hook_policy()
        self.assertIn('"advocate_model":"grok-4.6"', line)
        self.assertIn('"subagent_models":["composer-2.5"]', line)


class EvidenceTests(unittest.TestCase):
    def test_freeze_is_immutable(self):
        packet = _packet()
        clone = deepcopy(packet)
        assert_same_frozen_packet(packet, clone)
        clone["news_and_research"] = []
        with self.assertRaises(EvidenceImmutabilityError):
            assert_same_frozen_packet(packet, clone)

    def test_four_family_preflight_fails_loud(self):
        packet = _packet()
        statuses = assess_families(packet)
        self.assertEqual(set(statuses), {
            "temperature_gauges", "central_bank_research", "market_state", "research_method"
        })
        validate_preflight(packet, statuses)
        broken = dict(statuses)
        broken["market_state"] = "unavailable"
        with self.assertRaises(EvidencePreflightError):
            validate_preflight(packet, broken)
        omitted = dict(statuses)
        omitted.pop("research_method")
        with self.assertRaises(EvidencePreflightError):
            validate_preflight(packet, omitted)

    def test_repo_assembly_has_mandatory_sections(self):
        packet = assemble_packet(topic="go", root=ROOT)
        statuses = assess_families(packet)
        self.assertEqual(statuses["temperature_gauges"], "available")
        self.assertEqual(statuses["research_method"], "available")
        self.assertTrue(packet["central_bank_research"] or packet["news_and_research"])

    def test_stale_market_state_records_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ms.json"
            path.write_text(
                json.dumps(
                    {
                        "status": "stale",
                        "stale_sources": ["NZ_rates"],
                        "unavailable_sources": ["NZ_rates"],
                    }
                ),
                encoding="utf-8",
            )
            packet = assemble_packet(topic="go", root=ROOT, market_state_path=path)
        self.assertTrue(any("NZ_rates" in gap for gap in packet["known_gaps"]))
        self.assertEqual(assess_families(packet)["market_state"], "stale")


PINNED_REMITS = {
    "perma-bull": "strongest pro-growth, risk-on, cyclical FX expression",
    "perma-bear": "strongest defensive, slowdown, stress or risk-off FX expression",
    "dollar-king": "express macro views through USD spot whenever a defensible USD pair exists",
    "cross-merchant": "cleaner relative-value expressions outside USD",
    "carry-is-king": "positive carry and patient expressions unless a catalyst overwhelms it",
    "rate-hawk": "currencies where inflation and policy risks are underpriced to the upside",
    "rate-dove": "currencies where easing or growth weakness is underpriced",
    "value-guy": "historically or fundamentally mispriced currencies and convergence trades",
    "trend-follower": "persistent price and macro trends; reject premature fades",
    "mean-reverter": "fade statistically or fundamentally stretched FX moves when reversal conditions exist",
    "positioning-cynic": "attack crowded ideas; prefer better ownership asymmetry",
    "catalyst-junkie": "credible path from mispricing to repricing",
    "vol-convexity": "asymmetric optionality; challenge spot expressions",
    "no-trade-skeptic": "apparent edges are priced, too noisy, too crowded or poorly timed; may submit no-trade",
}


class SchemaAndBoundaryTests(unittest.TestCase):
    def test_required_trade_and_null_levels(self):
        packet = _packet()
        trade = {
            "instrument": "AUDUSD",
            "structure": None,
            "direction": "long",
            "thesis": "Growth resilience is underpriced.",
            "mispricing": "AUDUSD prices excessive fragility.",
            "why_now": ["Cutoff is live."],
            "evidence_refs": ["temp:US:inflation"],
            "horizon": "1 month",
            "entry": None,
            "target": None,
            "stop": None,
            "invalidation": None,
            "catalysts": ["FOMC path"],
            "principal_risks": ["Growth miss"],
            "confidence": 55,
        }
        validate_trade(trade, agent="perma-bull", packet=packet)
        with self.assertRaises(SchemaError):
            validate_trade(None, agent="perma-bull", packet=packet)
        validate_trade(None, agent=NO_TRADE_AGENT, packet=packet)
        bad_ref = dict(trade, evidence_refs=["not-in-packet"])
        with self.assertRaises(DataBoundaryError):
            validate_trade(bad_ref, agent="perma-bull", packet=packet)

    def test_data_only_boundary_rejects_web_fields(self):
        packet = _packet()
        runner = DryRunRunner()
        budget = BudgetLedger()
        contribution = runner.run_advocate("perma-bull", packet, budget)
        validate_contribution(contribution, packet=packet, expected_agent="perma-bull")
        contribution["web_search"] = ["https://example.com"]
        with self.assertRaises(DataBoundaryError):
            validate_contribution(contribution, packet=packet, expected_agent="perma-bull")


class BudgetTests(unittest.TestCase):
    def test_ceilings_and_subagent_limits(self):
        budget = BudgetLedger()
        for agent in STANDING_ADVOCATES:
            budget.charge("advocate", ADVOCATE_MODEL, agent, agent)
            budget.charge("subagent", SUBAGENT_MODEL, agent, f"{agent}-1")
            budget.charge("subagent", SUBAGENT_MODEL, agent, f"{agent}-2")
            with self.assertRaises(BudgetError):
                budget.charge("subagent", SUBAGENT_MODEL, agent, f"{agent}-3")
        budget.charge("conflict-aggregator", ADVOCATE_MODEL, "conflict-aggregator", "agg1")
        for agent in STANDING_ADVOCATES:
            budget.charge("rebuttal", ADVOCATE_MODEL, agent, f"reb-{agent}")
        budget.charge("final-aggregator", ADVOCATE_MODEL, "final-aggregator", "agg2")
        self.assertEqual(budget.grok, GROK_CEILING)
        self.assertEqual(budget.composer, COMPOSER_CEILING)
        with self.assertRaises(BudgetError):
            budget.charge("rebuttal", ADVOCATE_MODEL, "perma-bull", "overflow")


class ConflictRoutingTests(unittest.TestCase):
    def test_opposite_direction_and_one_pass_rebuttal(self):
        packet = _packet()
        runner = DryRunRunner()
        budget = BudgetLedger()
        originals = {
            agent: runner.run_advocate(agent, packet, budget) for agent in STANDING_ADVOCATES
        }
        conflict_map = detect_conflicts(originals)
        kinds = {c["kind"] for c in conflict_map["conflicts"]}
        self.assertIn("opposite_direction", kinds)
        self.assertIn("incompatible_regime", kinds)
        self.assertNotIn("winner", conflict_map)
        self.assertNotIn("house_view", conflict_map)
        assignments = rebuttal_assignments(conflict_map)
        self.assertLessEqual(len(assignments), 14)
        self.assertIn("perma-bull", assignments)
        self.assertIn("perma-bear", assignments)
        self.assertIn("perma-bear", assignments["perma-bull"]["opponents"])
        bull = currency_exposure(originals["perma-bull"]["trade"])
        bear = currency_exposure(originals["perma-bear"]["trade"])
        self.assertEqual(bull["AUD"], -bear["AUD"])


class OrchestratorDryRunTests(unittest.TestCase):
    def test_end_to_end_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_root = Path(tmp)
            result = go(
                topic="go",
                synthetic=True,
                artifact_root=artifact_root,
                composer_calls_per_advocate=2,
            )
            self.assertEqual(result["handoff"]["status"], HANDOFF_MARKER)
            self.assertEqual(set(result["originals"]), set(STANDING_ADVOCATES))
            for agent in TRADE_REQUIRED_AGENTS:
                self.assertIsNotNone(result["originals"][agent]["trade"])
            self.assertIsNone(result["originals"][NO_TRADE_AGENT]["trade"])
            self.assertLessEqual(result["budget"]["grok"], GROK_CEILING)
            self.assertLessEqual(result["budget"]["composer"], COMPOSER_CEILING)
            self.assertEqual(result["budget"]["composer"], 28)
            self.assertEqual(result["budget"]["grok"], 16 + result["budget"]["rebuttals"])
            self.assertLessEqual(result["budget"]["rebuttals"], 14)
            retrieved = retrieve(artifact_root, result["run_id"], "submission", "dollar-king")
            self.assertEqual(retrieved["agent"], "dollar-king")
            rebuttal = retrieve(artifact_root, result["run_id"], "rebuttal", "perma-bull")
            self.assertEqual(rebuttal["round"], 2)
            self.assertEqual(rebuttal["subagent_calls"], 0)
            handoff = retrieve(artifact_root, result["run_id"], "pm_handoff")
            packet_stub = {
                "run_id": result["run_id"],
                "as_of": result["evidence_cutoff"],
                "packet_sha256": result["packet_sha256"],
            }
            validate_pm_handoff(
                handoff,
                packet=packet_stub,
                originals=result["originals"],
                conflict_map=result["conflict_map"],
                rebuttals=result["rebuttals"],
            )

    def test_live_run_is_blocked(self):
        with self.assertRaises(LiveRunBlocked):
            go(topic="go", live=True, synthetic=True)
        with mock.patch.dict(os.environ, {"TRADER_ROOM_LIVE": "1", "CI": "true"}):
            with self.assertRaises(LiveRunBlocked):
                LiveRunner()

    def test_prepare_then_debate_uses_same_hash(self):
        packet, preflight = prepare_evidence(topic="go", synthetic=True)
        with tempfile.TemporaryDirectory() as tmp:
            result = run_debate(packet, preflight, runner=DryRunRunner(), artifact_root=Path(tmp))
        hashes = {item["packet_sha256"] for item in result["originals"].values()}
        self.assertEqual(hashes, {packet["packet_sha256"]})
        for rebuttal in result["rebuttals"].values():
            self.assertEqual(rebuttal["packet_sha256"], packet["packet_sha256"])


class CliTests(unittest.TestCase):
    def test_cli_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [
                    sys.executable,
                    "scripts/trader_room_go.py",
                    "go",
                    "--synthetic",
                    "--topic",
                    "go",
                    "--artifact-root",
                    tmp,
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
                env={**os.environ, "PYTHONPATH": str(ROOT)},
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], HANDOFF_MARKER)
            self.assertTrue(payload["run_id"])

    def test_cli_live_flag_is_blocked(self):
        proc = subprocess.run(
            [sys.executable, "scripts/trader_room_go.py", "go", "--live", "--synthetic"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "PYTHONPATH": str(ROOT)},
        )
        self.assertEqual(proc.returncode, 3)
        self.assertIn("LIVE RUN BLOCKED", proc.stderr)


class HookTests(unittest.TestCase):
    def test_trader_room_hook_denies_non_allowlisted_models(self):
        hook = ROOT / ".cursor" / "hooks" / "enforce-subagent-models.sh"
        policy = trader_room_hook_policy()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write(policy + "\nparent prompt\n")
            transcript = handle.name
        try:
            denied = subprocess.run(
                ["sh", str(hook), json.dumps({"subagent_model": "grok-4.5", "transcript_path": transcript})],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(denied.returncode, 0)
            allowed_grok = subprocess.run(
                ["sh", str(hook), json.dumps({"subagent_model": "grok-4.6", "transcript_path": transcript})],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(allowed_grok.returncode, 0, allowed_grok.stdout)
            allowed_composer = subprocess.run(
                ["sh", str(hook), json.dumps({"subagent_model": "composer-2.5", "transcript_path": transcript})],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(allowed_composer.returncode, 0, allowed_composer.stdout)
        finally:
            Path(transcript).unlink(missing_ok=True)


class MandateAndHandoffTests(unittest.TestCase):
    def test_roster_remits_and_models_stay_pinned(self):
        self.assertEqual(len(STANDING_ADVOCATES), 14)
        self.assertEqual(ADVOCATE_REMITS, PINNED_REMITS)
        self.assertEqual(ADVOCATE_MODEL, "grok-4.6")
        self.assertEqual(SPOT_SPECIALIST_AGENTS, ("dollar-king", "cross-merchant"))
        self.assertEqual(VOL_SPECIALIST_AGENT, "vol-convexity")
        self.assertNotIn("vol-convexity", COMPARISON_AGENTS)
        self.assertNotIn("dollar-king", COMPARISON_AGENTS)

    def test_comparison_seat_must_compare_rates_and_spot(self):
        packet = _packet()
        runner = DryRunRunner()
        contribution = runner.run_advocate("rate-hawk", packet, BudgetLedger())
        validate_contribution(contribution, packet=packet, expected_agent="rate-hawk")
        self.assertEqual(contribution["expression_comparison"]["chosen_expression"], "outright_duration")
        broken = deepcopy(contribution)
        broken["expression_comparison"]["considered_rates"] = broken["expression_comparison"]["considered_rates"][:1]
        with self.assertRaises(SchemaError):
            validate_expression_comparison(broken, agent="rate-hawk")

    def test_spot_specialist_cannot_switch_to_rates(self):
        packet = _packet()
        contribution = DryRunRunner().run_advocate("dollar-king", packet, BudgetLedger())
        validate_contribution(contribution, packet=packet, expected_agent="dollar-king")
        contribution["trade"]["instrument"] = "UST 10Y"
        contribution["trade"]["direction"] = "short"
        with self.assertRaises(SchemaError):
            validate_contribution(contribution, packet=packet, expected_agent="dollar-king")

    def test_non_vol_seat_cannot_default_to_options(self):
        packet = _packet()
        contribution = DryRunRunner().run_advocate("perma-bull", packet, BudgetLedger())
        contribution["trade"]["instrument"] = "AUDUSD 1-month straddle"
        contribution["trade"]["structure"] = "long 1-month AUDUSD straddle"
        contribution["trade"]["direction"] = "long volatility"
        with self.assertRaises(SchemaError):
            validate_contribution(contribution, packet=packet, expected_agent="perma-bull")

    def test_vol_convexity_remains_unchanged(self):
        packet = _packet()
        contribution = DryRunRunner().run_advocate("vol-convexity", packet, BudgetLedger())
        self.assertIsNone(contribution.get("expression_comparison"))
        validate_contribution(contribution, packet=packet, expected_agent="vol-convexity")
        contribution["expression_comparison"] = {"seat_class": "vol_specialist"}
        with self.assertRaises(SchemaError):
            validate_contribution(contribution, packet=packet, expected_agent="vol-convexity")

    def test_sanitize_drops_paid_and_method_text(self):
        packet = _packet()
        packet["research_method"]["text"] = "Start with a causal question. PRIVATE METHOD BODY."
        packet["private_methodology_available"] = [{"text": "paid memo"}]
        packet["paid_source_text"] = "do not commit"
        clean = sanitize_packet(packet)
        self.assertTrue(clean["sanitized"])
        self.assertIsNone(clean["research_method"]["text"])
        self.assertEqual(clean["research_method"]["text_ref"], "docs/TRADER_RESEARCH_METHOD.md")
        self.assertEqual(clean["private_methodology_available"], [])
        self.assertNotIn("paid_source_text", clean)

    def test_recorded_debate_persists_markdown_handoff(self):
        packet, preflight = prepare_evidence(topic="go", synthetic=True)
        runner = DryRunRunner()
        originals = {
            agent: runner.run_advocate(agent, packet, BudgetLedger())
            for agent in STANDING_ADVOCATES
        }
        with tempfile.TemporaryDirectory() as tmp:
            result = run_recorded_debate(
                packet,
                preflight,
                originals,
                artifact_root=Path(tmp),
                live=False,
            )
            self.assertEqual(result["handoff"]["status"], HANDOFF_MARKER)
            self.assertNotIn("winner", result["handoff"])
            self.assertNotIn("house_view", result["handoff"])
            md = retrieve(Path(tmp), result["run_id"], "pm_handoff_markdown")
            self.assertIn(HANDOFF_MARKER, md["markdown"])
            self.assertIn("dollar-king", md["markdown"])
            packet_out = retrieve(Path(tmp), result["run_id"], "evidence_packet")
            self.assertTrue(packet_out["sanitized"])
            self.assertIsNone(packet_out["research_method"]["text"])
            for item in result["handoff"]["proposed_trades"]:
                self.assertIn("thesis", item)
                self.assertIn("catalysts", item)
                self.assertIn("invalidation", item)

    def test_production_briefs_are_refused(self):
        packet, preflight = prepare_evidence(topic="go", synthetic=True)
        with self.assertRaises(ParentAuthoredSeatError):
            build_live_originals(packet)
        with self.assertRaises(ParentAuthoredSeatError):
            build_live_rebuttals(packet, {}, {})
        with self.assertRaises(IndependentSeatRequired):
            run_recorded_debate(packet, preflight, {}, live=True)

    def test_parent_authored_contribution_is_rejected(self):
        packet = _packet()
        contribution = DryRunRunner().run_advocate("perma-bull", packet, BudgetLedger())
        validate_contribution(contribution, packet=packet, expected_agent="perma-bull")
        contribution["execution"] = "parent_authored_production_evidence"
        with self.assertRaises(ParentAuthoredSeatError):
            validate_contribution(contribution, packet=packet, expected_agent="perma-bull")


class IndependentExecutionTests(unittest.TestCase):
    def test_hook_role_policy_and_acp_is_not_an_immediate_grant(self):
        with tempfile.TemporaryDirectory() as tmp:
            count_dir = Path(tmp) / "counts"
            transcript = Path(tmp) / "transcript.txt"
            transcript.write_text(
                'ACP_SUBAGENT_POLICY={"version":1,"allowed_models":["grok-4.6","composer-2.5"]}\n'
                + trader_room_hook_policy()
                + "\n",
                encoding="utf-8",
            )
            ok, _ = hook_decide(
                json.dumps({"subagent_model": "grok-4.6", "subagent_type": "perma-bull", "transcript_path": str(transcript)}),
                count_dir=count_dir,
            )
            self.assertTrue(ok)
            ok, msg = hook_decide(
                json.dumps(
                    {
                        "subagent_model": "composer-2.5",
                        "subagent_type": "conflict-aggregator",
                        "transcript_path": str(transcript),
                    }
                ),
                count_dir=count_dir,
            )
            self.assertFalse(ok)
            self.assertIn("exact grok-4.6", msg)
            ok, msg = hook_decide(
                json.dumps(
                    {
                        "subagent_model": "composer-2.5",
                        "subagent_type": "generalPurpose",
                        "transcript_path": str(transcript),
                        "prompt": "TRADER_ROOM_SEAT_ROLE=rebuttal",
                    }
                ),
                count_dir=count_dir,
            )
            self.assertFalse(ok)
            research = json.dumps(
                {
                    "subagent_model": "composer-2.5",
                    "subagent_type": "generalPurpose",
                    "transcript_path": str(transcript),
                    "prompt": "TRADER_ROOM_SEAT_ROLE=advocate-research",
                }
            )
            ok, _ = hook_decide(research, count_dir=count_dir)
            self.assertTrue(ok)
            ok, _ = hook_decide(research, count_dir=count_dir)
            self.assertTrue(ok)
            ok, msg = hook_decide(research, count_dir=count_dir)
            self.assertFalse(ok)
            self.assertIn("max 2", msg)

    def test_persist_independent_requires_complete_grok_evidence(self):
        packet, preflight = prepare_evidence(topic="go", synthetic=True)
        runner = DryRunRunner()
        originals = {
            agent: stamp_independent_invocation(
                runner.run_advocate(agent, packet, BudgetLedger()),
                role="advocate",
                model="grok-4.6",
                invocation_id=f"seat-{agent}",
                agent=agent,
            )
            for agent in STANDING_ADVOCATES
        }
        with self.assertRaises(IndependentSeatRequired):
            persist_independent_run(
                packet=packet,
                preflight=preflight,
                originals=originals,
                conflict_map=None,  # type: ignore[arg-type]
                rebuttals={},
                handoff={},
            )
        missing = dict(originals)
        missing.pop("dollar-king")
        with self.assertRaises(IndependentSeatRequired):
            persist_independent_run(
                packet=packet,
                preflight=preflight,
                originals=missing,
                conflict_map={"type": "TRADER_ROOM_CONFLICT_MAP", "run_id": packet["run_id"], "conflicts": []},
                rebuttals={},
                handoff={"type": "TRADER_ROOM_PM_HANDOFF"},
            )

    def test_invalid_prior_run_is_not_latest(self):
        latest = json.loads((ROOT / "trader-room" / "runs" / "latest.json").read_text(encoding="utf-8"))
        catalog = json.loads((ROOT / "trader-room" / "runs" / "INDEX.json").read_text(encoding="utf-8"))
        self.assertFalse(latest.get("valid"))
        self.assertIsNone(latest.get("run_id"))
        marked = next(item for item in catalog["runs"] if item["run_id"] == "tr-20260917T231827Z-4ca9133b")
        self.assertFalse(marked["valid"])
        self.assertEqual(marked["status"], "INVALID")
        validity = json.loads(
            (ROOT / "trader-room" / "runs" / "tr-20260917T231827Z-4ca9133b" / "VALIDITY.json").read_text(encoding="utf-8")
        )
        self.assertFalse(validity["valid"])


if __name__ == "__main__":
    unittest.main()
