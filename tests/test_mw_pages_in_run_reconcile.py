"""In-run Stage 08 reconciliation from deploy-pages.yml's reconcile job."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.market_watch_launch.pages import PAGES_RECONCILED
from scripts.market_watch_launch.pages_recovery import (
    apply_published_pages,
    in_run_actions_run,
    workflow_run_decision,
)
from scripts.market_watch_launch.state import LaunchStateStore
from scripts.overnight.constants import ROOT

from tests.test_mw_launch_pages_recovery import (
    HEAD_SHA,
    OCT2,
    REPOSITORY,
    RUN_ID,
    _materialize_pages_recovery_launch_state,
    _oct2_run,
)


def _happy_env(**overrides: str) -> dict[str, str]:
    base = {
        "GITHUB_RUN_ID": RUN_ID,
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_SHA": HEAD_SHA,
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_WORKFLOW_REF": f"{REPOSITORY}/.github/workflows/deploy-pages.yml@refs/heads/main",
    }
    base.update(overrides)
    return base


class InRunActionsRunTests(unittest.TestCase):
    def test_happy_path(self) -> None:
        payload = in_run_actions_run(_happy_env(), deploy_result="success")
        self.assertEqual(payload["evidence_source"], "in_run_deploy_job")
        self.assertEqual(payload["deploy_job_result"], "success")
        self.assertEqual(payload["id"], int(RUN_ID))
        self.assertEqual(payload["head_sha"], HEAD_SHA)

    def test_refuses_non_success_deploy_result(self) -> None:
        for result in ("failure", "cancelled", "skipped"):
            with self.assertRaises(SystemExit) as ctx:
                in_run_actions_run(_happy_env(), deploy_result=result)
            self.assertIn("non-success", str(ctx.exception))

    def test_refuses_pull_request_event(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            in_run_actions_run(_happy_env(GITHUB_EVENT_NAME="pull_request"), deploy_result="success")
        self.assertIn("non-workflow_dispatch", str(ctx.exception))

    def test_refuses_non_main_ref(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            in_run_actions_run(_happy_env(GITHUB_REF="refs/heads/gh-pages"), deploy_result="success")
        self.assertIn("non-main", str(ctx.exception))

    def test_refuses_wrong_workflow_ref(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            in_run_actions_run(
                _happy_env(GITHUB_WORKFLOW_REF=f"{REPOSITORY}/.github/workflows/launch-market-watch.yml@refs/heads/main"),
                deploy_result="success",
            )
        self.assertIn("workflow is not deploy-pages.yml", str(ctx.exception))

    def test_refuses_bad_sha(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            in_run_actions_run(_happy_env(GITHUB_SHA="not-a-sha"), deploy_result="success")
        self.assertIn("mismatched deploy head SHA", str(ctx.exception))

    def test_refuses_bad_run_id(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            in_run_actions_run(_happy_env(GITHUB_RUN_ID="abc"), deploy_result="success")
        self.assertIn("workflow run id", str(ctx.exception))

    def test_refuses_non_github_server(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            in_run_actions_run(_happy_env(GITHUB_SERVER_URL="https://example.com"), deploy_result="success")
        self.assertIn("target repository", str(ctx.exception))


class InRunReconcileApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state_root = Path(self.tmp.name)
        _materialize_pages_recovery_launch_state(self.state_root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _in_run_run(self) -> dict:
        return in_run_actions_run(_happy_env(), deploy_result="success")

    def test_apply_records_stage_08_with_in_run_evidence(self) -> None:
        run = self._in_run_run()
        decision = apply_published_pages(
            repo_root=ROOT,
            state_root=self.state_root,
            launch_id=OCT2,
            run=run,
            run_id=RUN_ID,
            repository=REPOSITORY,
        )
        self.assertTrue(decision["changed"])
        store = LaunchStateStore(self.state_root)
        launch = store.load_launch(OCT2)
        evidence = launch["stages"]["08_pages"]["details"]["publication_evidence"]
        self.assertEqual(evidence["evidence_source"], "in_run_deploy_job")
        self.assertEqual(evidence["head_sha"], HEAD_SHA)
        self.assertEqual(launch["status"], "succeeded")
        self.assertEqual(launch["stages"]["08_pages"]["reason"], PAGES_RECONCILED)

        second = apply_published_pages(
            repo_root=ROOT,
            state_root=self.state_root,
            launch_id=OCT2,
            run=run,
            run_id=RUN_ID,
            repository=REPOSITORY,
        )
        self.assertFalse(second["changed"])
        self.assertTrue(second["already_reconciled"])

    def test_later_workflow_run_decision_is_no_op(self) -> None:
        in_run = self._in_run_run()
        apply_published_pages(
            repo_root=ROOT,
            state_root=self.state_root,
            launch_id=OCT2,
            run=in_run,
            run_id=RUN_ID,
            repository=REPOSITORY,
        )
        api_run = _oct2_run()
        decision = workflow_run_decision(
            repo_root=ROOT,
            state_root=self.state_root,
            run=api_run,
            run_id=RUN_ID,
            repository=REPOSITORY,
        )
        self.assertEqual(decision["action"], "already_reconciled")
        self.assertFalse(decision["changed"])
        store = LaunchStateStore(self.state_root)
        evidence = store.load_launch(OCT2)["stages"]["08_pages"]["details"]["publication_evidence"]
        self.assertEqual(evidence.get("evidence_source"), "in_run_deploy_job")


if __name__ == "__main__":
    unittest.main()
