from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.overnight.constants import ROOT

POLICY = {
    "version": 1,
    "run_type": "trader-room-ondemand",
    "total_model_cap": 57,
    "grok_cap": 29,
    "composer_cap": 28,
    "parent_model": "grok-4.6",
    "parent_total": 1,
    "parent_grok": 1,
}


class TraderRoomBudgetHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.active = Path("/tmp/mw-trader-room-active.json")
        self.lock = Path("/tmp/mw-trader-room-budget.lock")
        self.active.unlink(missing_ok=True)
        self.lock.unlink(missing_ok=True)
        self.tmp = tempfile.TemporaryDirectory()
        self.transcript = Path(self.tmp.name) / "transcript.txt"
        marker = "MW_TRADER_ROOM_RUN_POLICY=" + json.dumps(POLICY, separators=(",", ":"))
        self.transcript.write_text(marker + "\n", encoding="utf-8")
        self.script = ROOT / ".cursor" / "hooks" / "enforce-overnight-budget.py"

    def tearDown(self) -> None:
        self.active.unlink(missing_ok=True)
        self.lock.unlink(missing_ok=True)
        self.tmp.cleanup()

    def _call(self, parent: str, child: str, model: str, task: str = "test") -> subprocess.CompletedProcess:
        event = {
            "subagent_id": child,
            "subagent_type": "generalPurpose",
            "task": task,
            "parent_conversation_id": parent,
            "tool_call_id": f"tc-{child}",
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

    def test_full_contract_budget_allows_28_grok_children_and_28_composer(self) -> None:
        advocates = []
        for i in range(14):
            child = f"adv-{i}"
            advocates.append(child)
            self.assertEqual(
                self._call("root", child, "grok-4.6", f"TRADER_ROOM_ADVOCATE=1 seat={i}").returncode,
                0,
            )
        for i in range(14):
            self.assertEqual(self._call("root", f"rebuttal-{i}", "grok-4.6").returncode, 0)
        for advocate in advocates:
            self.assertEqual(self._call(advocate, f"{advocate}-c1", "composer-2.5").returncode, 0)
            self.assertEqual(self._call(advocate, f"{advocate}-c2", "composer-2.5").returncode, 0)
        blocked = self._call("root", "extra-grok", "grok-4.6")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("cap", blocked.stdout.lower())

    def test_advocate_cannot_launch_third_composer(self) -> None:
        self.assertEqual(
            self._call("root", "adv", "grok-4.6", "TRADER_ROOM_ADVOCATE=1").returncode,
            0,
        )
        self.assertEqual(self._call("adv", "c1", "composer-2.5").returncode, 0)
        self.assertEqual(self._call("adv", "c2", "composer-2.5").returncode, 0)
        blocked = self._call("adv", "c3", "composer-2.5")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("cap", blocked.stdout.lower())

    def test_non_advocate_cannot_launch_composer(self) -> None:
        self.assertEqual(self._call("root", "agg", "grok-4.6", "conflict aggregator").returncode, 0)
        blocked = self._call("agg", "c1", "composer-2.5")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("only initial", blocked.stdout.lower())

    def test_root_cannot_launch_composer(self) -> None:
        blocked = self._call("root", "bad", "composer-2.5")
        self.assertNotEqual(blocked.returncode, 0)

    def test_other_model_is_denied(self) -> None:
        blocked = self._call("root", "bad", "claude-sonnet-5")
        self.assertNotEqual(blocked.returncode, 0)


class TraderRoomContinuationBudgetHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.active = Path("/tmp/mw-trader-room-continuation-active.json")
        self.lock = Path("/tmp/mw-trader-room-continuation-budget.lock")
        self.active.unlink(missing_ok=True)
        self.lock.unlink(missing_ok=True)
        self.tmp = tempfile.TemporaryDirectory()
        self.transcript = Path(self.tmp.name) / "transcript.txt"
        policy = {
            "version": 1,
            "run_type": "trader-room-continuation",
            "total_model_cap": 14,
            "grok_cap": 14,
            "composer_cap": 0,
            "parent_model": "grok-4.6",
            "parent_total": 1,
            "parent_grok": 1,
        }
        marker = "MW_TRADER_ROOM_CONTINUATION_POLICY=" + json.dumps(policy, separators=(",", ":"))
        self.transcript.write_text(marker + "\n", encoding="utf-8")
        self.script = ROOT / ".cursor" / "hooks" / "enforce-overnight-budget.py"

    def tearDown(self) -> None:
        self.active.unlink(missing_ok=True)
        self.lock.unlink(missing_ok=True)
        self.tmp.cleanup()

    def _call(self, child: str, model: str = "grok-4.6") -> subprocess.CompletedProcess:
        event = {
            "subagent_id": child,
            "subagent_type": "generalPurpose",
            "task": "continuation",
            "parent_conversation_id": "root",
            "tool_call_id": f"tc-{child}",
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

    def test_continuation_allows_exactly_13_grok_children_after_parent(self) -> None:
        for i in range(13):
            self.assertEqual(self._call(f"grok-{i}").returncode, 0)
        blocked = self._call("grok-overflow")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("cap", blocked.stdout.lower())

    def test_continuation_blocks_composer_and_other_models(self) -> None:
        self.assertNotEqual(self._call("composer", "composer-2.5").returncode, 0)
        self.assertNotEqual(self._call("other", "claude-sonnet-5").returncode, 0)


if __name__ == "__main__":
    unittest.main()
