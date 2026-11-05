from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.overnight.constants import ROOT
from scripts.trader_room import agent_config

LEGACY_ONDEMAND = agent_config.legacy_pin("ondemand")
TRADER_SEATS = agent_config.pin_trader_ids(LEGACY_ONDEMAND)


class TraderRoomBudgetHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.active = Path("/tmp/mw-trader-room-active.json")
        self.lock = Path("/tmp/mw-trader-room-budget.lock")
        self.active.unlink(missing_ok=True)
        self.lock.unlink(missing_ok=True)
        self.tmp = tempfile.TemporaryDirectory()
        self.transcript = Path(self.tmp.name) / "transcript.txt"
        self.script = ROOT / ".cursor" / "hooks" / "enforce-overnight-budget.py"
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.repo, check=True)
        registry_src = ROOT / "scripts" / "trader_room" / "model_registry.json"
        registry_dst = self.repo / "scripts" / "trader_room" / "model_registry.json"
        registry_dst.parent.mkdir(parents=True)
        shutil.copy2(registry_src, registry_dst)
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "seed registry"], cwd=self.repo, check=True)
        cfg = dict(agent_config.load_config(registry_dst, honor_env=False))
        cfg["_source"] = "default"
        self.pin = agent_config.assert_acceptable_pin(agent_config.build_pin("ondemand", config=cfg))
        self.advocate_model = self.pin["roles"]["advocate"]
        self.transcript.write_text(agent_config.trader_room_policy_marker(self.pin) + "\n", encoding="utf-8")

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
            cwd=self.repo,
            check=False,
        )

    def test_full_contract_budget_allows_28_grok_children_and_28_composer(self) -> None:
        advocates = []
        for seat in TRADER_SEATS:
            child = f"adv-{seat}"
            advocates.append(child)
            self.assertEqual(
                self._call("root", child, self.advocate_model, f"MW_ROLE=advocate:{seat}").returncode,
                0,
            )
        for seat in TRADER_SEATS:
            self.assertEqual(
                self._call("root", f"rebuttal-{seat}", self.advocate_model, f"MW_ROLE=rebuttal:{seat}").returncode,
                0,
            )
        for advocate in advocates:
            self.assertEqual(self._call(advocate, f"{advocate}-c1", "composer-2.5").returncode, 0)
            self.assertEqual(self._call(advocate, f"{advocate}-c2", "composer-2.5").returncode, 0)
        blocked = self._call("root", "extra-grok", self.advocate_model, f"MW_ROLE=advocate:{TRADER_SEATS[0]}")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("cap", blocked.stdout.lower())

    def test_advocate_cannot_launch_third_composer(self) -> None:
        self.assertEqual(
            self._call("root", "adv", self.advocate_model, f"MW_ROLE=advocate:{TRADER_SEATS[0]}").returncode,
            0,
        )
        self.assertEqual(self._call("adv", "c1", "composer-2.5").returncode, 0)
        self.assertEqual(self._call("adv", "c2", "composer-2.5").returncode, 0)
        blocked = self._call("adv", "c3", "composer-2.5")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("cap", blocked.stdout.lower())

    def test_non_advocate_cannot_launch_composer(self) -> None:
        seat = TRADER_SEATS[0]
        self.assertEqual(
            self._call("root", "adv", self.advocate_model, f"MW_ROLE=advocate:{seat}").returncode,
            0,
        )
        self.assertEqual(
            self._call("root", "reb", self.advocate_model, f"MW_ROLE=rebuttal:{seat}").returncode,
            0,
        )
        blocked = self._call("reb", "c1", "composer-2.5")
        self.assertNotEqual(blocked.returncode, 0)

    def test_root_cannot_launch_composer(self) -> None:
        blocked = self._call("root", "bad", "composer-2.5", "MW_ROLE=advocate_subagent")
        self.assertNotEqual(blocked.returncode, 0)

    def test_other_model_is_denied(self) -> None:
        blocked = self._call("root", "bad", "claude-sonnet-5", f"MW_ROLE=advocate:{TRADER_SEATS[0]}")
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
