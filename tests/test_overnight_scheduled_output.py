from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from scripts.overnight.clock import isoformat, now_ny
from scripts.overnight.constants import ROOT, STANDING_SEATS
from scripts.overnight.pipeline import run_stage
from scripts.overnight.scheduled_output import (
    AGENT_PACKET_TYPE,
    SCHEDULE_ID,
    apply_output,
    simulate_output,
    validate_output,
)
from scripts.overnight.store import OvernightStore, sha256_json

AS_OF = datetime.fromisoformat("2026-09-18T01:55:00-04:00")
POLICY = {
    "version": 1,
    "schedule_id": SCHEDULE_ID,
    "total_model_cap": 18,
    "grok_cap": 16,
    "composer_cap": 2,
    "parent_model": "grok-4.6",
    "parent_total": 1,
    "parent_grok": 1,
}


def _hold_decision(seat: str, run_id: str, packet_hash: str, cutoff: str) -> dict:
    return {
        "seat": seat,
        "overnight_run_id": run_id,
        "packet_sha256": packet_hash,
        "evidence_cutoff": cutoff,
        "conviction": 25,
        "thesis": "No incremental edge.",
        "invalidation": None,
        "required_pitch": None,
        "risk_put_on": None,
        "expression_memo": {
            "rates_candidate": None,
            "spot_candidate": None,
            "options_candidate": None,
            "selected": "none",
            "rationale": "Hold existing risk.",
        },
        "actions": [
            {
                "action": "HOLD",
                "expression_memo": {
                    "rates_candidate": None,
                    "spot_candidate": None,
                    "options_candidate": None,
                    "selected": "none",
                    "rationale": "Hold existing risk.",
                },
            }
        ],
        "alerts": [],
    }


class ScheduledOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state_root = Path(self.tmp.name)
        self.run_id = "overnight-20260918"
        for stage in ("collect", "pre_trader_delta", "freeze_evidence"):
            run_stage(
                stage,
                root=ROOT,
                state_root=self.state_root,
                run_id=self.run_id,
                when=AS_OF,
                dry_run=True,
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
            "base_packet_sha256": self.base["packet_sha256"],
            "base_evidence_cutoff": self.base["as_of"],
            "evidence_cutoff": "2026-09-18T02:20:00-04:00",
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
            "base_packet_sha256": self.base["packet_sha256"],
            "agent_packet": packet,
            "decisions": {
                seat: _hold_decision(seat, self.run_id, packet["packet_sha256"], packet["evidence_cutoff"])
                for seat in STANDING_SEATS
            },
            "execution": {
                "parent_model": "grok-4.6",
                "allowed_subagent_models": ["composer-2.5", "grok-4.6"],
                "total_model_cap": 18,
                "grok_cap": 16,
                "composer_cap": 2,
                "declared_total_model_calls": 16,
                "declared_grok_calls": 15,
                "declared_composer_calls": 1,
                "other_models_calls": 0,
                "auto_used": False,
            },
        }

    def test_valid_output_simulates_without_model_book_state(self) -> None:
        validate_output(self.store, self.payload)
        review = simulate_output(self.store, self.payload)
        self.assertEqual(review["status"], "succeeded")
        self.assertEqual(review["model_calls"], 16)
        self.assertEqual(set(review["reviews"]), set(STANDING_SEATS))

    def test_apply_writes_books_and_marks_trader_stage(self) -> None:
        review = apply_output(self.store, self.payload)
        self.assertEqual(review["status"], "succeeded")
        run = self.store.read_artifact(self.run_id, "run.json")
        self.assertEqual(run["stages"]["trader_review"]["status"], "succeeded")
        self.assertEqual(self.store.read_books()["last_successful_review_run_id"], self.run_id)

    def test_scheduled_open_uses_frozen_mid_not_model_price(self) -> None:
        memo = {
            "rates_candidate": None,
            "spot_candidate": {"instrument": "USDCAD", "asset_class": "spot_fx", "rationale": "spot"},
            "options_candidate": None,
            "selected": "spot",
            "rationale": "Dedicated USD spot seat.",
        }
        decision = self.payload["decisions"]["dollar-king"]
        decision["expression_memo"] = memo
        decision["actions"] = [{
            "action": "OPEN",
            "instrument": "USDCAD",
            "side": "long",
            "notional_usd": 10_000_000,
            "price": 9.99,
            "asset_class": "spot_fx",
            "expression_memo": memo,
        }]
        review = simulate_output(self.store, self.payload)
        pos = review["books"]["seats"]["dollar-king"]["positions"][0]
        self.assertEqual(pos["entry_price"], 1.36)
        self.assertEqual(pos["mark_price"], 1.36)
        self.assertIn("market_state.fx.USDCAD.spot", pos["entry_price_source"])

    def test_rejects_model_calculated_book_state(self) -> None:
        self.payload["books"] = {"nav_usd": 999}
        with self.assertRaises(Exception):
            validate_output(self.store, self.payload)

    def test_rejects_changed_competition_contract(self) -> None:
        self.payload["agent_packet"]["competition"]["funding_rate_annual"] = 0.0
        self.payload["agent_packet"]["packet_sha256"] = sha256_json(
            {k: v for k, v in self.payload["agent_packet"].items() if k != "packet_sha256"}
        )
        with self.assertRaises(Exception):
            validate_output(self.store, self.payload)

    def test_rejects_wrong_packet_hash(self) -> None:
        self.payload["agent_packet"]["packet_sha256"] = "bad"
        with self.assertRaises(Exception):
            validate_output(self.store, self.payload)

    def test_workflows_have_no_direct_cursor_runtime(self) -> None:
        overnight = (ROOT / ".github" / "workflows" / "overnight-pipeline.yml").read_text(encoding="utf-8")
        gate = (ROOT / ".github" / "workflows" / "overnight-scheduled-output.yml").read_text(encoding="utf-8")
        for forbidden in ("CURSOR_API_KEY", "curl https://cursor.com/install", "agent -p", "--model \"grok-4.6\""):
            self.assertNotIn(forbidden, overnight)
            self.assertNotIn(forbidden, gate)
        self.assertNotIn('"5 2 * * 1-5"', overnight)
        self.assertIn("pull_request_target", gate)
        self.assertIn("scheduled_output.py validate", gate)
        self.assertIn("scheduled_output.py apply", gate)


class BudgetHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.active = Path("/tmp/mw-overnight-active.json")
        self.lock = Path("/tmp/mw-overnight-budget.lock")
        self.active.unlink(missing_ok=True)
        self.lock.unlink(missing_ok=True)
        self.tmp = tempfile.TemporaryDirectory()
        self.transcript = Path(self.tmp.name) / "transcript.txt"
        marker = "MW_OVERNIGHT_RUN_POLICY=" + json.dumps(POLICY, separators=(",", ":"))
        self.transcript.write_text(marker + "\n", encoding="utf-8")
        self.script = ROOT / ".cursor" / "hooks" / "enforce-overnight-budget.py"

    def tearDown(self) -> None:
        self.active.unlink(missing_ok=True)
        self.lock.unlink(missing_ok=True)
        self.tmp.cleanup()

    def _call(self, parent: str, model: str) -> subprocess.CompletedProcess:
        event = {
            "subagent_id": f"sub-{model}",
            "subagent_type": "generalPurpose",
            "task": "test",
            "parent_conversation_id": parent,
            "tool_call_id": "tc",
            "subagent_model": model,
            "is_parallel_worker": False,
            "transcript_path": str(self.transcript),
        }
        return subprocess.run(
            ["python3", str(self.script)],
            input=json.dumps(event),
            text=True,
            capture_output=True,
            cwd=ROOT,
            check=False,
        )

    def test_budget_enforces_total_and_per_model_caps(self) -> None:
        self.assertEqual(self._call("root", "composer-2.5").returncode, 0)
        for _ in range(14):
            self.assertEqual(self._call("root", "grok-4.6").returncode, 0)
        self.assertEqual(self._call("root", "composer-2.5").returncode, 0)
        self.assertEqual(self._call("root", "grok-4.6").returncode, 0)
        blocked = self._call("root", "grok-4.6")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("cap", blocked.stdout.lower())

    def test_nested_child_is_denied(self) -> None:
        self.assertEqual(self._call("root", "composer-2.5").returncode, 0)
        blocked = self._call("child-conversation", "grok-4.6")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("nested", blocked.stdout.lower())

    def test_other_model_is_denied(self) -> None:
        blocked = self._call("root", "claude-sonnet-5")
        self.assertNotEqual(blocked.returncode, 0)


if __name__ == "__main__":
    unittest.main()
