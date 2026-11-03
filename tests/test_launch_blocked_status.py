"""Launch CLI and workflow must treat blocked launches as job failures."""

from __future__ import annotations

import argparse
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.market_watch_launch.cli import cmd_launch, launch_job_failed

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "launch-market-watch.yml"


class LaunchJobFailedTests(unittest.TestCase):
    def test_blocked_is_failure(self) -> None:
        self.assertTrue(launch_job_failed({"status": "blocked"}))

    def test_failed_is_failure(self) -> None:
        self.assertTrue(launch_job_failed({"status": "failed"}))

    def test_succeeded_is_not_failure(self) -> None:
        self.assertFalse(launch_job_failed({"status": "succeeded"}))

    def test_running_is_not_failure(self) -> None:
        self.assertFalse(launch_job_failed({"status": "running"}))


class WorkflowFailStepTests(unittest.TestCase):
    def test_workflow_uses_launch_job_failed_in_orchestrate(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("launch_job_failed", text)
        orchestrate_start = text.index("  orchestrate:")
        research_start = text.index("\n  research:", orchestrate_start)
        orchestrate_block = text[orchestrate_start:research_start]
        self.assertIn("Fail the job when the launch itself failed", orchestrate_block)
        self.assertIn("from scripts.market_watch_launch.cli import launch_job_failed", orchestrate_block)


class CmdLaunchExitCodeTests(unittest.TestCase):
    def _args(self) -> argparse.Namespace:
        return argparse.Namespace(
            root=".",
            state_root=".",
            session_date=None,
            rerun=False,
            mode="live",
            provider="acp",
            as_of=None,
            source="workflow_dispatch",
            actor_type="User",
            actor=None,
            issue_number=None,
            issue_title=None,
            issue_url=None,
            market_state=None,
            repository_permission=None,
            through=None,
            publish_production=False,
        )

    @patch("scripts.market_watch_launch.cli.run_launch")
    def test_cmd_launch_blocked_returns_one(self, mock_run_launch) -> None:
        mock_run_launch.return_value = {
            "launch_id": "x",
            "status": "blocked",
            "stages": {},
        }
        self.assertEqual(cmd_launch(self._args()), 1)

    @patch("scripts.market_watch_launch.cli.run_launch")
    def test_cmd_launch_succeeded_returns_zero(self, mock_run_launch) -> None:
        mock_run_launch.return_value = {
            "launch_id": "x",
            "status": "succeeded",
            "stages": {},
        }
        self.assertEqual(cmd_launch(self._args()), 0)


if __name__ == "__main__":
    unittest.main()
