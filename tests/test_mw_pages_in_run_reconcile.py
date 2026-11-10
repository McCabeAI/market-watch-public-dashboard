"""In-run Stage 08 reconciliation from deploy-pages.yml's reconcile job."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.market_watch_launch.pages import PAGES_RECONCILED
from scripts.market_watch_launch.pages_recovery import (
    apply_published_pages,
    in_run_actions_run,
    main,
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

NOV2 = "mwl-20261102T102838Z-f747870a"
NOV2_RUN_ID = "41438960943"
NOV2_HEAD_SHA = "3aaf22a786bf21fb17f0917f71e2377ba8412e87"


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


def _nov2_env(**overrides: str) -> dict[str, str]:
    base = {
        "GITHUB_RUN_ID": NOV2_RUN_ID,
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_SHA": NOV2_HEAD_SHA,
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_WORKFLOW_REF": f"{REPOSITORY}/.github/workflows/deploy-pages.yml@refs/heads/main",
    }
    base.update(overrides)
    return base


class InRunEvidenceCliTests(unittest.TestCase):
    def test_cli_in_run_evidence_without_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run.json"
            env = os.environ.copy()
            env.update(_happy_env())
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.market_watch_launch.pages_recovery",
                    "in-run-evidence",
                    "--deploy-result",
                    "success",
                    "--out",
                    str(out),
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["evidence_source"], "in_run_deploy_job")

            out2 = Path(tmp) / "run2.json"
            old_env = {
                key: os.environ.get(key)
                for key in (
                    "GITHUB_RUN_ID",
                    "GITHUB_SERVER_URL",
                    "GITHUB_REPOSITORY",
                    "GITHUB_SHA",
                    "GITHUB_EVENT_NAME",
                    "GITHUB_REF",
                    "GITHUB_WORKFLOW_REF",
                )
            }
            try:
                os.environ.update(_happy_env())
                rc = main(
                    [
                        "in-run-evidence",
                        "--deploy-result",
                        "success",
                        "--out",
                        str(out2),
                    ]
                )
            finally:
                for key, value in old_env.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
            self.assertEqual(rc, 0)
            self.assertEqual(
                json.loads(out2.read_text(encoding="utf-8"))["evidence_source"],
                "in_run_deploy_job",
            )

    def test_preflight_and_workflow_run_parse_repo_root_without_attribute_error(self) -> None:
        rc = main(["preflight", "--launch-id", "mwl-nonexistent-test-id", "--repo-root", str(ROOT)])
        self.assertEqual(rc, 1)

        with tempfile.TemporaryDirectory() as tmp:
            run_json = Path(tmp) / "run.json"
            run_json.write_text(json.dumps(_oct2_run()) + "\n", encoding="utf-8")
            state_root = Path(tmp) / "state"
            state_root.mkdir()
            rc = main(
                [
                    "workflow-run",
                    "--run-id",
                    RUN_ID,
                    "--run-json",
                    str(run_json),
                    "--repo-root",
                    str(ROOT),
                    "--state-root",
                    str(state_root),
                ]
            )
            self.assertEqual(rc, 0)


class Nov2Stage08RecoveryPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state_root = Path(self.tmp.name)
        launch_src = ROOT / "data" / "market_watch_launches" / NOV2 / "launch.json"
        self.assertTrue(launch_src.is_file(), "Nov 2 launch.json must exist in worktree")
        self.worktree_launch_bytes = launch_src.read_bytes()
        base = self.state_root / "data" / "market_watch_launches"
        nov2_dir = base / NOV2
        nov2_dir.mkdir(parents=True)
        (nov2_dir / "launch.json").write_bytes(self.worktree_launch_bytes)
        index_src = ROOT / "data" / "market_watch_launches" / "index.json"
        if index_src.is_file():
            base.mkdir(parents=True, exist_ok=True)
            (base / "index.json").write_bytes(index_src.read_bytes())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _nov2_in_run_run(self) -> dict:
        return in_run_actions_run(_nov2_env(), deploy_result="success")

    def test_hermetic_apply_reconciles_temp_copy_without_touching_worktree(self) -> None:
        run = self._nov2_in_run_run()
        self.assertEqual(run["evidence_source"], "in_run_deploy_job")
        self.assertEqual(str(run["id"]), NOV2_RUN_ID)
        self.assertEqual(run["head_sha"], NOV2_HEAD_SHA)

        decision = apply_published_pages(
            repo_root=ROOT,
            state_root=self.state_root,
            launch_id=NOV2,
            run=run,
            run_id=NOV2_RUN_ID,
            repository=REPOSITORY,
        )
        self.assertTrue(decision["changed"])
        self.assertEqual(decision["run_id"], NOV2_RUN_ID)
        self.assertEqual(decision["head_sha"], NOV2_HEAD_SHA)

        store = LaunchStateStore(self.state_root)
        launch = store.load_launch(NOV2)
        details = launch["stages"]["08_pages"]["details"]
        self.assertEqual(launch["status"], "succeeded")
        self.assertEqual(launch["stages"]["08_pages"]["reason"], PAGES_RECONCILED)
        self.assertTrue(details["production_published"])
        evidence = details["publication_evidence"]
        self.assertEqual(evidence["evidence_source"], "in_run_deploy_job")
        self.assertEqual(evidence.get("run_id"), NOV2_RUN_ID)
        self.assertEqual(evidence["head_sha"], NOV2_HEAD_SHA)

        worktree_launch = ROOT / "data" / "market_watch_launches" / NOV2 / "launch.json"
        self.assertEqual(worktree_launch.read_bytes(), self.worktree_launch_bytes)

    def test_api_failure_conclusion_is_not_successful_reconciliation(self) -> None:
        success = self._nov2_in_run_run()
        failed_api = {
            **success,
            "conclusion": "failure",
            "status": "completed",
        }
        with self.assertRaises(SystemExit) as ctx:
            apply_published_pages(
                repo_root=ROOT,
                state_root=self.state_root,
                launch_id=NOV2,
                run=failed_api,
                run_id=NOV2_RUN_ID,
                repository=REPOSITORY,
            )
        self.assertIn("non-success conclusion", str(ctx.exception))

        decision = workflow_run_decision(
            repo_root=ROOT,
            state_root=self.state_root,
            run=failed_api,
            run_id=NOV2_RUN_ID,
            repository=REPOSITORY,
        )
        self.assertEqual(decision["action"], "skipped")
        self.assertEqual(decision["reason"], "deploy_pages_intent_not_proven")

        store = LaunchStateStore(self.state_root)
        pending = store.load_launch(NOV2)
        self.assertFalse(
            ((pending.get("stages") or {}).get("08_pages") or {}).get("details", {}).get(
                "production_published"
            )
        )


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
        api_run["dispatch_inputs"] = {
            "launch_id": OCT2,
            "review_id": "review-001",
            "packet_sha256": "2b0c5980ac350ecd70d6149b08fef310ca461ba19924d01d4a1a8dd5c673688b",
        }
        api_run["publication_release"] = {
            "trigger": "launch",
            "launch_id": OCT2,
            "review_id": "review-001",
            "packet_sha256": "2b0c5980ac350ecd70d6149b08fef310ca461ba19924d01d4a1a8dd5c673688b",
        }
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
