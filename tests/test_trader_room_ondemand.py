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
    COMPOSER_CEILING,
    GROK_CEILING,
    HANDOFF_MARKER,
    NO_TRADE_AGENT,
    RATES_FIRST_SEATS,
    SPOT_ONLY_SEATS,
    STANDING_ADVOCATES,
    SUBAGENT_MODEL,
    TRADE_REQUIRED_AGENTS,
)
from scripts.trader_room.errors import (
    BudgetError,
    DataBoundaryError,
    EvidenceImmutabilityError,
    EvidencePreflightError,
    LiveRunBlocked,
    ModelPolicyError,
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
from scripts.trader_room.handoff import build_pm_handoff
from scripts.trader_room.models import (
    assert_advocate_model,
    assert_subagent_model,
    load_registry,
    trader_room_hook_policy,
)
from scripts.trader_room.orchestrator import go, prepare_evidence, run_debate
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


class SchemaAndBoundaryTests(unittest.TestCase):
    def test_required_trade_and_null_levels(self):
        packet = _packet()
        trade = {
            "instrument": "AUDUSD",
            "asset_class": "spot_fx",
            "expression_comparison": {
                "rates_candidate": "Long AU 2Y vs US 2Y as the rates-first alternative.",
                "spot_candidate": "Long AUDUSD.",
                "selected": "spot",
                "rationale": "Spot is cleaner in this synthetic fixture after explicit rates comparison.",
            },
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

        missing_rates = deepcopy(trade)
        missing_rates["expression_comparison"]["rates_candidate"] = None
        with self.assertRaises(SchemaError):
            validate_trade(missing_rates, agent="perma-bull", packet=packet)

        dollar = deepcopy(trade)
        dollar["expression_comparison"] = {
            "rates_candidate": None,
            "spot_candidate": "Long USDJPY.",
            "selected": "spot",
            "rationale": "Dedicated spot-FX specialist seat.",
        }
        validate_trade(dollar, agent="dollar-king", packet=packet)

        wrong_dollar = deepcopy(dollar)
        wrong_dollar["asset_class"] = "rates"
        wrong_dollar["expression_comparison"]["selected"] = "rates"
        with self.assertRaises(SchemaError):
            validate_trade(wrong_dollar, agent="dollar-king", packet=packet)

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
        for agent in STANDING_ADVOCATES:
            budget.charge("rebuttal", ADVOCATE_MODEL, agent, f"reb-{agent}")
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
        self.assertEqual(conflict_map["method"], "deterministic_conflict_synopsis_v1")
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
            for agent in RATES_FIRST_SEATS:
                trade = result["originals"][agent]["trade"]
                if trade is not None:
                    self.assertTrue(trade["expression_comparison"]["rates_candidate"])
                    self.assertTrue(trade["expression_comparison"]["spot_candidate"])
            for agent in SPOT_ONLY_SEATS:
                self.assertEqual(result["originals"][agent]["trade"]["asset_class"], "spot_fx")
            self.assertIsNone(result["originals"][NO_TRADE_AGENT]["trade"])
            self.assertLessEqual(result["budget"]["grok"], GROK_CEILING)
            self.assertLessEqual(result["budget"]["composer"], COMPOSER_CEILING)
            self.assertEqual(result["budget"]["composer"], 28)
            self.assertEqual(result["budget"]["grok"], 14 + result["budget"]["rebuttals"])
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


class DeterministicHandoffTests(unittest.TestCase):
    def test_final_handoff_requires_zero_model_calls(self):
        packet = _packet()
        runner = DryRunRunner()
        budget = BudgetLedger()
        originals = {
            agent: runner.run_advocate(agent, packet, budget) for agent in STANDING_ADVOCATES
        }
        conflict_map = detect_conflicts(originals)
        assignments = rebuttal_assignments(conflict_map)
        rebuttals = {
            agent: runner.run_rebuttal(agent, packet, originals[agent], assignment, budget)
            for agent, assignment in assignments.items()
        }
        before = budget.snapshot()
        handoff = build_pm_handoff(
            packet=packet,
            originals=originals,
            conflict_map=conflict_map,
            rebuttals=rebuttals,
        )
        after = budget.snapshot()
        self.assertEqual(before["grok"], after["grok"])
        self.assertEqual(before["composer"], after["composer"])
        self.assertEqual(handoff["status"], HANDOFF_MARKER)
        self.assertEqual(set(handoff["rebuttals"]), set(rebuttals))


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

    def test_finalize_cli_regenerates_handoff_without_model_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_root = Path(tmp)
            result = go(topic="go", synthetic=True, artifact_root=artifact_root)
            run_dir = artifact_root / "trader-room" / "runs" / result["run_id"]
            (run_dir / "pm_handoff.json").unlink()
            (run_dir / "artifact_index.json").unlink()
            proc = subprocess.run(
                [
                    sys.executable,
                    "scripts/trader_room_finalize.py",
                    "--run-dir",
                    str(run_dir),
                    "--root",
                    str(artifact_root),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
                env={**os.environ, "PYTHONPATH": str(ROOT)},
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["final_handoff_model_calls"], 0)
            handoff = json.loads((run_dir / "pm_handoff.json").read_text())
            self.assertEqual(handoff["status"], HANDOFF_MARKER)
            receipt = json.loads((run_dir / "receipt.json").read_text())
            self.assertEqual(receipt["final_handoff_method"], "deterministic_pm_handoff_v1")
            self.assertEqual(receipt["final_handoff_model_calls"], 0)

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


if __name__ == "__main__":
    unittest.main()
