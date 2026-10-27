"""Confirmed Pages dispatch is not publication.

A human launch may request deploy-pages only after acceptance and finalization.
``gh workflow run`` exiting 0 does not confirm a run. Stage 08 stays pending and
the one-live-launch guard stays closed until a successful main workflow_dispatch
is reconciled. Failed deploys, replayed events, and the wrong ref or launch do
not release the guard or rerun traders.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.market_watch_launch.continuation import continue_accepted_launch
from scripts.market_watch_launch.contract import CONCURRENCY_BLOCK, STAGES, empty_launch, stage_receipt
from scripts.market_watch_launch.graph import run_launch
from scripts.market_watch_launch.pages import PAGES_RECONCILED, reconcile_published_pages
from scripts.market_watch_launch.pages_dispatch import (
    assert_public_dataset,
    confirm_pages_dispatch,
    dispatch_command,
    verify_public_dataset,
)
from scripts.market_watch_launch.pages_recovery import workflow_run_decision
from scripts.market_watch_launch.state import LaunchStateStore
from scripts.overnight.constants import ROOT

NY = ZoneInfo("America/New_York")
LAUNCH_ID = "mwl-20261022T110951Z-9a049b03"
BLOCKED_ID = "mwl-20261023T130116Z-14063697"
PACKET = "89996a8d48b7bb3a14eed2ec835ad5b6f6968c38a7dfc635d865fe5ea147fb58"
REVIEW = "review-001"
RUN_ID = "39779281989"
RUN_URL = f"https://github.com/McCabeAI/market-watch-public-dashboard/actions/runs/{RUN_ID}"
HEAD = "65c5600877d234d483820a3957bed1c11bf2de96"
REPO = "McCabeAI/market-watch-public-dashboard"
NEXT_DAY = datetime(2026, 10, 24, 9, 0, tzinfo=NY)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stage(name: str, *, status: str, reason: str | None = None, details: dict | None = None) -> dict:
    return {
        "stage": name,
        "status": status,
        "input_sha256": PACKET,
        "output_sha256": PACKET if status == "succeeded" else None,
        "started_at": "2026-10-22T07:09:51.753996-04:00",
        "finished_at": "2026-10-22T08:33:04.927005-04:00" if status == "succeeded" else None,
        "reason": reason,
        "source_run_url": None,
        "artifact": None,
        "details": details or {},
    }


def _ready_launch(launch_id: str = LAUNCH_ID, *, session_date: str = "2026-10-22") -> dict:
    launch = empty_launch(
        launch_id=launch_id,
        session_date=session_date,
        created_at="2026-10-22T07:09:51.753996-04:00",
        request={
            "actor": "example-user",
            "actor_type": "User",
            "mode": "live",
            "provider": "acp",
            "publish_production": True,
            "repository_permission": "admin",
            "rerun": False,
            "session_date": session_date,
            "source": "github_issue",
        },
    )
    launch["review_id"] = REVIEW
    launch["overnight_run_id"] = "overnight-20261022"
    launch["base_packet_sha256"] = PACKET
    launch["status"] = "running"
    for name in STAGES:
        if name == "05_acp_handoff":
            launch["stages"][name] = _stage(
                name,
                status="succeeded",
                reason="provider_output_accepted",
                details={"provider_output_accepted": True},
            )
        elif name == "04_freeze":
            launch["stages"][name] = _stage(
                name,
                status="succeeded",
                details={"review_id": REVIEW, "packet_sha256": PACKET},
            )
        elif name == "07_finalize":
            launch["stages"][name] = _stage(
                name,
                status="succeeded",
                details={
                    "review_id": REVIEW,
                    "packet_sha256": PACKET,
                    "publication": {"may_publish": True, "core_status": "ok"},
                },
            )
        elif name == "08_pages":
            launch["stages"][name] = _stage(name, status="pending")
        else:
            launch["stages"][name] = _stage(name, status="succeeded")
    return launch


def _blocked_attempt(blocker: str) -> dict:
    launch = empty_launch(
        launch_id=BLOCKED_ID,
        session_date="2026-10-23",
        created_at="2026-10-23T09:01:16.409501-04:00",
        request={
            "actor": "example-user",
            "actor_type": "User",
            "mode": "live",
            "provider": "acp",
            "publish_production": True,
            "rerun": False,
            "session_date": "2026-10-23",
            "source": "github_issue",
        },
    )
    launch["status"] = "blocked"
    launch["stages"]["00_authenticate"]["status"] = "blocked"
    launch["stages"]["00_authenticate"]["reason"] = CONCURRENCY_BLOCK
    launch["stages"]["00_authenticate"]["details"] = {"blocked_by_launch_id": blocker}
    return launch


def _confirmed_result(**overrides: object) -> dict:
    payload = {
        "dispatched": True,
        "dispatch_confirmed": True,
        "workflow": "deploy-pages.yml",
        "event": "workflow_dispatch",
        "ref": "main",
        "run_id": RUN_ID,
        "run_url": RUN_URL,
        "head_sha": HEAD,
        "launch_id": LAUNCH_ID,
        "conclusion": "",
    }
    payload.update(overrides)
    return payload


def _run_row(**overrides: object) -> dict:
    payload = {
        "databaseId": int(RUN_ID),
        "headSha": HEAD,
        "status": "queued",
        "conclusion": "",
        "event": "workflow_dispatch",
        "url": RUN_URL,
        "displayTitle": "Deploy Market Watch Dashboard",
        "headBranch": "main",
        "name": "Deploy Market Watch Dashboard",
    }
    payload.update(overrides)
    return payload


def _actions_run(head_sha: str, **overrides: object) -> dict:
    payload = {
        "id": int(RUN_ID),
        "name": "Deploy Market Watch Dashboard",
        "path": ".github/workflows/deploy-pages.yml",
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "head_branch": "main",
        "head_sha": head_sha,
        "html_url": RUN_URL,
        "repository": {"full_name": REPO},
        "head_repository": {"full_name": REPO},
    }
    payload.update(overrides)
    return payload


def _handlers() -> dict:
    def make(stage: str):
        def _handler(launch, ctx):
            _ = (launch, ctx)
            return stage_receipt(stage, status="succeeded", input_sha256=None, details={"stage": stage})

        return _handler

    return {stage: make(stage) for stage in STAGES}


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


class DispatchConfirmationTests(unittest.TestCase):
    def test_command_carries_launch_identity_and_not_a_run_id(self) -> None:
        command = dispatch_command(
            workflow="deploy-pages.yml",
            ref="main",
            launch_id=LAUNCH_ID,
            review_id=REVIEW,
            packet_sha256=PACKET,
        )
        text = " ".join(command)
        self.assertIn("workflow run deploy-pages.yml --ref main", text)
        self.assertIn(f"launch_id={LAUNCH_ID}", text)
        self.assertIn(f"review_id={REVIEW}", text)
        self.assertIn(f"packet_sha256={PACKET}", text)

    def test_exit_zero_without_a_new_run_is_not_confirmation(self) -> None:
        calls = {"dispatch": 0}

        def list_runs() -> list[dict]:
            return []

        def request_dispatch() -> int:
            calls["dispatch"] += 1
            return 0

        result = confirm_pages_dispatch(
            plan={"workflow": "deploy-pages.yml", "ref": "main"},
            launch={"launch_id": LAUNCH_ID},
            expected_sha=HEAD,
            list_runs=list_runs,
            request_dispatch=request_dispatch,
            sleep=lambda _seconds: None,
            attempts=3,
            interval_seconds=5,
        )
        self.assertEqual(calls["dispatch"], 1)
        self.assertFalse(result["dispatched"])
        self.assertFalse(result["dispatch_confirmed"])
        self.assertEqual(result["reason"], "pages_run_not_observed")
        self.assertNotIn("run_id", result)

    def test_snapshot_failure_does_not_dispatch(self) -> None:
        calls = {"dispatch": 0}

        def list_runs() -> list[dict]:
            raise OSError("token not ready")

        def request_dispatch() -> int:
            calls["dispatch"] += 1
            return 0

        result = confirm_pages_dispatch(
            plan={"workflow": "deploy-pages.yml", "ref": "main"},
            launch={"launch_id": LAUNCH_ID},
            expected_sha=HEAD,
            list_runs=list_runs,
            request_dispatch=request_dispatch,
            sleep=lambda _seconds: None,
            attempts=2,
        )
        self.assertEqual(calls["dispatch"], 0)
        self.assertEqual(result["reason"], "pages_dispatch_not_confirmed")

    def test_nonzero_dispatch_is_not_confirmation(self) -> None:
        result = confirm_pages_dispatch(
            plan={"workflow": "deploy-pages.yml", "ref": "main"},
            launch={"launch_id": LAUNCH_ID},
            expected_sha=HEAD,
            list_runs=lambda: [_run_row()],
            request_dispatch=lambda: 1,
            sleep=lambda _seconds: None,
            attempts=2,
        )
        self.assertFalse(result["dispatch_confirmed"])
        self.assertEqual(result["reason"], "pages_dispatch_not_confirmed")

    def test_matching_run_is_confirmed_without_calling_publication(self) -> None:
        lists = iter([[], [_run_row()]])
        result = confirm_pages_dispatch(
            plan={"workflow": "deploy-pages.yml", "ref": "main", "review_id": REVIEW},
            launch={"launch_id": LAUNCH_ID, "base_packet_sha256": PACKET},
            expected_sha=HEAD,
            list_runs=lambda: next(lists),
            request_dispatch=lambda: 0,
            sleep=lambda _seconds: None,
            attempts=2,
        )
        self.assertTrue(result["dispatch_confirmed"])
        self.assertEqual(result["run_id"], RUN_ID)
        self.assertEqual(result["head_sha"], HEAD)
        self.assertNotEqual(result.get("conclusion"), "success")

    def test_wrong_sha_wrong_title_and_duplicate_runs_fail_closed(self) -> None:
        wrong_sha = confirm_pages_dispatch(
            plan={"workflow": "deploy-pages.yml", "ref": "main"},
            launch={"launch_id": LAUNCH_ID},
            expected_sha=HEAD,
            list_runs=lambda: [_run_row(headSha="b" * 40)],
            request_dispatch=lambda: 0,
            sleep=lambda _seconds: None,
            attempts=1,
        )
        self.assertEqual(wrong_sha["reason"], "pages_run_not_observed")
        other_launch = "mwl-20261023T130116Z-14063697"
        wrong_title = confirm_pages_dispatch(
            plan={"workflow": "deploy-pages.yml", "ref": "main"},
            launch={"launch_id": LAUNCH_ID},
            expected_sha=HEAD,
            list_runs=lambda: [_run_row(displayTitle=f"Deploy {other_launch}")],
            request_dispatch=lambda: 0,
            sleep=lambda _seconds: None,
            attempts=1,
        )
        self.assertEqual(wrong_title["reason"], "pages_run_not_observed")
        snapshots = iter(
            [
                [],
                [
                    _run_row(),
                    _run_row(
                        databaseId=39779281990,
                        url="https://github.com/McCabeAI/market-watch-public-dashboard/actions/runs/39779281990",
                    ),
                ],
            ]
        )
        ambiguous = confirm_pages_dispatch(
            plan={"workflow": "deploy-pages.yml", "ref": "main"},
            launch={"launch_id": LAUNCH_ID},
            expected_sha=HEAD,
            list_runs=lambda: next(snapshots),
            request_dispatch=lambda: 0,
            sleep=lambda _seconds: None,
            attempts=1,
        )
        self.assertEqual(ambiguous["reason"], "pages_dispatch_ambiguous")

    def test_public_dataset_must_match_the_deployed_run(self) -> None:
        trader = {
            "seats": [{"seat": str(i)} for i in range(14)],
            "publication": {"overnight_run_id": "overnight-20261022"},
        }
        pm = {"pms": [{"pm_id": "swinger"}, {"pm_id": "pragmatist"}, {"pm_id": "grinder"}]}
        assert_public_dataset(
            html="<h1>Trader Book</h1>",
            trader=trader,
            pm=pm,
            overnight_run_id="overnight-20261022",
        )
        with self.assertRaises(SystemExit):
            assert_public_dataset(
                html="<h1>Trader Book</h1>",
                trader={**trader, "seats": [{"seat": "only"}]},
                pm=pm,
                overnight_run_id="overnight-20261022",
            )
        with self.assertRaises(SystemExit):
            assert_public_dataset(
                html="<h1>Trader Book</h1>",
                trader=trader,
                pm={"pms": [{"pm_id": "swinger"}]},
                overnight_run_id="overnight-20261022",
            )
        pages = {
            "https://example.test/market-watch/": "<h1>Trader Book</h1>",
            "https://example.test/market-watch/trader-books.json": json.dumps(trader),
            "https://example.test/market-watch/pm-books.json": json.dumps(pm),
        }
        verify_public_dataset(
            page_url="https://example.test/market-watch/",
            overnight_run_id="overnight-20261022",
            attempts=1,
            opener=pages.get,
        )


class LaunchChainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sentinel = self.root / "do-not-touch.txt"
        self.sentinel.write_text("traders-and-pms\n", encoding="utf-8")
        self.store = LaunchStateStore(self.root)
        self.launch = _ready_launch()
        self.store.save_launch(self.launch)
        self.blocked = _blocked_attempt(LAUNCH_ID)
        self.store.save_launch(self.blocked)
        self.blocked_bytes = self.store.launch_path(BLOCKED_ID).read_bytes()
        self.sentinel_sha = _sha256_file(self.sentinel)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _ctx(self, pages_dispatch) -> dict:
        return {
            "root": self.root,
            "state_root": self.root,
            "launch_dir": self.store.launch_dir(LAUNCH_ID),
            "client_payload": {
                "launch_id": LAUNCH_ID,
                "review_id": REVIEW,
                "base_packet_sha256": PACKET,
            },
            "pages_dispatch": pages_dispatch,
        }

    def _assert_untouched(self) -> None:
        self.assertEqual(self.sentinel.read_text(encoding="utf-8"), "traders-and-pms\n")
        self.assertEqual(_sha256_file(self.sentinel), self.sentinel_sha)
        self.assertEqual(self.store.launch_path(BLOCKED_ID).read_bytes(), self.blocked_bytes)

    def _next_day(self) -> dict:
        return run_launch(
            {
                "session_date": "2026-10-24",
                "rerun": False,
                "mode": "fixture",
                "provider": "stub",
                "source": "workflow_dispatch",
                "actor_type": "User",
                "actor": "example-user",
            },
            root=self.root,
            state_root=self.root,
            handlers=_handlers(),
            when=NEXT_DAY,
        )

    def test_cli_success_without_a_run_keeps_the_guard_closed(self) -> None:
        calls = {"n": 0}

        def pages_dispatch(**_kwargs):
            calls["n"] += 1
            return {"dispatched": True}

        decision = continue_accepted_launch(self.store.load_launch(LAUNCH_ID), self._ctx(pages_dispatch))
        self.assertEqual(calls["n"], 1)
        self.assertEqual(decision["status"], "pending")
        self.assertFalse(decision["dispatch_confirmed"])
        self.assertFalse(decision["production_published"])
        current = self.store.load_launch(LAUNCH_ID)
        self.assertEqual(current["status"], "running")
        self.assertEqual(current["stages"]["08_pages"]["status"], "pending")
        self.assertNotEqual(current["stages"]["08_pages"]["reason"], PAGES_RECONCILED)
        nxt = self._next_day()
        self.assertNotEqual(nxt["status"], "blocked")
        self.assertEqual(nxt["launch"]["stages"]["00_authenticate"]["status"], "succeeded")
        self.assertEqual(current["status"], "running")
        self._assert_untouched()

    def test_confirmed_dispatch_then_successful_deploy_allows_the_next_day(self) -> None:
        calls = {"n": 0}

        def pages_dispatch(**_kwargs):
            calls["n"] += 1
            return _confirmed_result()

        decision = continue_accepted_launch(self.store.load_launch(LAUNCH_ID), self._ctx(pages_dispatch))
        self.assertEqual(decision["status"], "pending")
        self.assertEqual(decision["reason"], "pages_dispatch_requested")
        self.assertTrue(decision["dispatch_confirmed"])
        self.assertEqual(decision["run_id"], RUN_ID)
        self.assertFalse(decision["production_published"])
        again = continue_accepted_launch(self.store.load_launch(LAUNCH_ID), self._ctx(pages_dispatch))
        self.assertEqual(calls["n"], 1)
        self.assertEqual(again["run_id"], RUN_ID)
        self.assertFalse(again["production_published"])
        blocked_next = self._next_day()
        self.assertNotEqual(blocked_next["status"], "blocked")
        self.assertEqual(blocked_next["launch"]["stages"]["00_authenticate"]["status"], "succeeded")

        current = self.store.load_launch(LAUNCH_ID)
        evidence = {
            "workflow": "deploy-pages.yml",
            "event": "workflow_dispatch",
            "ref": "main",
            "conclusion": "success",
            "launch_id": LAUNCH_ID,
            "head_sha": HEAD,
            "run_url": RUN_URL,
            "run_id": RUN_ID,
            "finalized_launch": json.loads(json.dumps(current)),
        }
        failed = reconcile_published_pages(
            self.store.load_launch(LAUNCH_ID),
            {**evidence, "conclusion": "failure"},
            store=self.store,
        )
        self.assertEqual(failed["reason"], "pages_publication_not_proven")
        self.assertEqual(self.store.load_launch(LAUNCH_ID)["status"], "running")
        wrong = reconcile_published_pages(
            self.store.load_launch(LAUNCH_ID),
            {**evidence, "launch_id": BLOCKED_ID, "head_sha": "c" * 40},
            store=self.store,
        )
        self.assertEqual(wrong["status"], "blocked")
        proven = reconcile_published_pages(self.store.load_launch(LAUNCH_ID), evidence, store=self.store)
        self.assertEqual(proven["reason"], PAGES_RECONCILED)
        published = self.store.load_launch(LAUNCH_ID)
        self.assertEqual(published["status"], "succeeded")
        self.assertEqual(published["stages"]["08_pages"]["details"]["publication_evidence"]["run_id"], RUN_ID)
        replay = reconcile_published_pages(self.store.load_launch(LAUNCH_ID), evidence, store=self.store)
        self.assertEqual(replay["status"], "blocked")
        self.assertEqual(self.store.load_launch(LAUNCH_ID)["status"], "succeeded")
        follow = continue_accepted_launch(self.store.load_launch(LAUNCH_ID), self._ctx(pages_dispatch))
        self.assertEqual(calls["n"], 1)
        self.assertTrue(follow["production_published"])
        nxt = self._next_day()
        self.assertNotEqual(nxt["status"], "blocked")
        self.assertEqual(nxt["launch"]["stages"]["00_authenticate"]["status"], "succeeded")
        self._assert_untouched()

    def test_failed_pages_conclusion_does_not_publish_or_rerun(self) -> None:
        decision = continue_accepted_launch(
            self.store.load_launch(LAUNCH_ID),
            self._ctx(lambda **_: _confirmed_result(conclusion="failure")),
        )
        self.assertEqual(decision["reason"], "pages_deploy_failed")
        self.assertFalse(decision["production_published"])
        current = self.store.load_launch(LAUNCH_ID)
        self.assertEqual(current["status"], "running")
        self.assertEqual(current["stages"]["08_pages"]["status"], "pending")
        nxt = self._next_day()
        self.assertNotEqual(nxt["status"], "blocked")
        self.assertEqual(nxt["launch"]["stages"]["00_authenticate"]["status"], "succeeded")
        self.assertEqual(current["status"], "running")
        self._assert_untouched()


class WorkflowRunReconciliationTests(unittest.TestCase):
    def _repo(self) -> tuple[Path, str]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        _git(root, "init", "-q")
        _git(root, "config", "user.email", "test@example.com")
        _git(root, "config", "user.name", "test")
        launch = _ready_launch()
        store = LaunchStateStore(root)
        store.save_launch(launch)
        store.save_launch(_blocked_attempt(LAUNCH_ID))
        (root / "data" / "overnight").mkdir(parents=True)
        (root / "data" / "overnight" / "books").mkdir()
        (root / "data" / "overnight" / "books" / "latest.json").write_text('{"do":"not-touch"}\n', encoding="utf-8")
        _git(root, "add", "data")
        _git(root, "commit", "-q", "-m", "finalize")
        return root, _git(root, "rev-parse", "HEAD").stdout.strip()

    def test_successful_workflow_run_terminals_once_and_keeps_the_blocked_attempt(self) -> None:
        root, head = self._repo()
        blocked = _sha256_file(root / "data" / "market_watch_launches" / BLOCKED_ID / "launch.json")
        books = _sha256_file(root / "data" / "overnight" / "books" / "latest.json")
        first = workflow_run_decision(
            repo_root=root,
            state_root=root,
            run=_actions_run(head),
            run_id=RUN_ID,
        )
        self.assertEqual(first["action"], "reconciled")
        self.assertTrue(first["changed"])
        published = LaunchStateStore(root).load_launch(LAUNCH_ID)
        self.assertEqual(published["status"], "succeeded")
        self.assertEqual(published["stages"]["08_pages"]["reason"], PAGES_RECONCILED)
        self.assertEqual(published["stages"]["08_pages"]["details"]["publication_evidence"]["run_id"], RUN_ID)
        self.assertIsNone(LaunchStateStore(root)._read_index()["live_launch_id"])
        second = workflow_run_decision(
            repo_root=root,
            state_root=root,
            run=_actions_run(head),
            run_id=RUN_ID,
        )
        self.assertFalse(second["changed"])
        self.assertEqual(second["action"], "already_reconciled")
        self.assertEqual(_sha256_file(root / "data" / "market_watch_launches" / BLOCKED_ID / "launch.json"), blocked)
        self.assertEqual(_sha256_file(root / "data" / "overnight" / "books" / "latest.json"), books)
        historical = json.loads((root / "data" / "market_watch_launches" / BLOCKED_ID / "launch.json").read_text())
        self.assertEqual(historical["status"], "blocked")
        self.assertEqual(historical["stages"]["00_authenticate"]["reason"], CONCURRENCY_BLOCK)

    def test_failed_and_unrelated_runs_do_not_release_the_guard(self) -> None:
        root, head = self._repo()
        failed = workflow_run_decision(
            repo_root=root,
            state_root=root,
            run=_actions_run(head, conclusion="failure"),
            run_id=RUN_ID,
        )
        self.assertEqual(failed["action"], "noted_incomplete")
        self.assertTrue(failed["changed"])
        current = LaunchStateStore(root).load_launch(LAUNCH_ID)
        self.assertEqual(current["status"], "running")
        self.assertEqual(current["stages"]["08_pages"]["status"], "pending")
        self.assertEqual(current["stages"]["08_pages"]["reason"], "pages_deploy_failed")
        self.assertFalse(current["stages"]["08_pages"]["details"]["production_published"])
        replay = workflow_run_decision(
            repo_root=root,
            state_root=root,
            run=_actions_run(head, conclusion="failure"),
            run_id=RUN_ID,
        )
        self.assertFalse(replay["changed"])
        with self.assertRaises(SystemExit):
            workflow_run_decision(
                repo_root=root,
                state_root=root,
                run=_actions_run(head, event="pull_request", conclusion="success"),
                run_id=RUN_ID,
            )
        self.assertEqual(LaunchStateStore(root).load_launch(LAUNCH_ID)["status"], "running")
        nxt = run_launch(
            {
                "session_date": "2026-10-24",
                "rerun": False,
                "mode": "fixture",
                "provider": "stub",
                "source": "workflow_dispatch",
                "actor_type": "User",
                "actor": "example-user",
            },
            root=root,
            state_root=root,
            handlers=_handlers(),
            when=NEXT_DAY,
        )
        self.assertNotEqual(nxt["status"], "blocked")
        self.assertEqual(nxt["launch"]["stages"]["00_authenticate"]["status"], "succeeded")
        self.assertEqual(LaunchStateStore(root).load_launch(LAUNCH_ID)["status"], "running")

    def test_manual_deploy_without_a_pending_launch_is_a_noop(self) -> None:
        root, head = self._repo()
        launch = LaunchStateStore(root).load_launch(LAUNCH_ID)
        launch["status"] = "succeeded"
        launch["stages"]["08_pages"]["status"] = "succeeded"
        launch["stages"]["08_pages"]["reason"] = PAGES_RECONCILED
        LaunchStateStore(root).save_launch(launch)
        _git(root, "add", "data")
        _git(root, "commit", "-q", "-m", "already published")
        later = _git(root, "rev-parse", "HEAD").stdout.strip()
        decision = workflow_run_decision(
            repo_root=root,
            state_root=root,
            run=_actions_run(later),
            run_id=RUN_ID,
        )
        self.assertEqual(decision["action"], "skipped")
        self.assertFalse(decision["changed"])


class ContinuationProcessTests(unittest.TestCase):
    def test_process_treats_gh_exit_zero_as_unconfirmed_until_a_run_is_listed(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        _git(root, "init", "-q")
        _git(root, "config", "user.email", "test@example.com")
        _git(root, "config", "user.name", "test")
        store = LaunchStateStore(root)
        store.save_launch(_ready_launch())
        _git(root, "add", "data")
        _git(root, "commit", "-q", "-m", "finalize")
        head = _git(root, "rev-parse", "HEAD").stdout.strip()
        log = root / "gh.log"
        count = root / "count"
        count.write_text("0\n", encoding="utf-8")
        run_json = json.dumps([_run_row(headSha=head)])
        fake = root / "gh"
        fake.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                set -euo pipefail
                printf '%s\\n' "$*" >> {log}
                if [[ "$1" == "workflow" && "$2" == "run" ]]; then
                  exit 0
                fi
                if [[ "$1" == "run" && "$2" == "list" ]]; then
                  seen=$(cat {count})
                  echo $((seen + 1)) > {count}
                  if [[ "$seen" == "0" ]]; then
                    printf '[]\\n'
                  else
                    printf '%s\\n' '{run_json}'
                  fi
                  exit 0
                fi
                exit 1
                """
            ),
            encoding="utf-8",
        )
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        env = os.environ.copy()
        env["PATH"] = f"{root}{os.pathsep}{env.get('PATH', '')}"
        env["PYTHONPATH"] = str(ROOT)
        env["MW_ENABLE_PAGES_DISPATCH"] = "1"
        env["MW_PAGES_DISPATCH_ATTEMPTS"] = "3"
        env["MW_PAGES_DISPATCH_INTERVAL_SECONDS"] = "0"
        env["LAUNCH_ID"] = LAUNCH_ID
        env["CLIENT_PAYLOAD"] = json.dumps(
            {"launch_id": LAUNCH_ID, "review_id": REVIEW, "base_packet_sha256": PACKET}
        )
        first = subprocess.run(
            ["python3", "-m", "scripts.market_watch_launch.continuation"],
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        decision = json.loads(first.stdout)
        self.assertTrue(decision["dispatch_confirmed"])
        self.assertFalse(decision["production_published"])
        self.assertEqual(decision["run_id"], RUN_ID)
        calls = log.read_text(encoding="utf-8")
        self.assertIn(f"launch_id={LAUNCH_ID}", calls)
        self.assertIn(f"review_id={REVIEW}", calls)
        self.assertEqual(calls.count("workflow run "), 1)
        launch = store.load_launch(LAUNCH_ID)
        self.assertEqual(launch["status"], "running")
        second = subprocess.run(
            ["python3", "-m", "scripts.market_watch_launch.continuation"],
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(log.read_text(encoding="utf-8").count("workflow run "), 1)

        other = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(other)], check=False))
        # A fresh launch whose dispatcher exits 0 and never lists a run.
        _git(other, "init", "-q")
        _git(other, "config", "user.email", "test@example.com")
        _git(other, "config", "user.name", "test")
        LaunchStateStore(other).save_launch(_ready_launch())
        _git(other, "add", "data")
        _git(other, "commit", "-q", "-m", "finalize")
        empty = other / "gh"
        empty_log = other / "gh.log"
        empty.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                set -euo pipefail
                printf '%s\\n' "$*" >> {empty_log}
                if [[ "$1" == "workflow" && "$2" == "run" ]]; then
                  exit 0
                fi
                if [[ "$1" == "run" && "$2" == "list" ]]; then
                  printf '[]\\n'
                  exit 0
                fi
                exit 1
                """
            ),
            encoding="utf-8",
        )
        empty.chmod(empty.stat().st_mode | stat.S_IEXEC)
        missing_env = dict(env)
        missing_env["PATH"] = f"{other}{os.pathsep}{env.get('PATH', '')}"
        missed = subprocess.run(
            ["python3", "-m", "scripts.market_watch_launch.continuation"],
            cwd=other,
            env=missing_env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(missed.returncode, 1, missed.stdout + missed.stderr)
        self.assertIn("workflow run ", empty_log.read_text(encoding="utf-8"))
        saved = LaunchStateStore(other).load_launch(LAUNCH_ID)
        self.assertEqual(saved["status"], "running")
        self.assertFalse(saved["stages"]["08_pages"]["details"].get("production_published", False))
        self.assertNotEqual(saved["stages"]["08_pages"].get("reason"), PAGES_RECONCILED)


class WorkflowWiringTests(unittest.TestCase):
    def test_existing_workflows_confirm_and_reconcile_without_a_new_schedule(self) -> None:
        pages = (ROOT / ".github" / "workflows" / "deploy-pages.yml").read_text(encoding="utf-8")
        reconcile = (ROOT / ".github" / "workflows" / "reconcile-published-pages.yml").read_text(encoding="utf-8")
        overnight = (ROOT / ".github" / "workflows" / "overnight-scheduled-output.yml").read_text(encoding="utf-8")
        self.assertIn("launch_id:", pages)
        self.assertIn("packet_sha256:", pages)
        self.assertIn("pages_dispatch bind-checkout", pages)
        self.assertIn("pages_dispatch verify-public", pages)
        self.assertIn("pages-production", pages)
        self.assertNotIn("\n  schedule:", pages)
        self.assertNotIn("\n  push:", pages.split("jobs:", 1)[0])
        self.assertIn("workflow_run:", reconcile)
        self.assertIn("Deploy Market Watch Dashboard", reconcile)
        self.assertIn("PAGES_WORKFLOW_RUN", reconcile)
        self.assertNotIn("\n  schedule:", reconcile)
        self.assertNotIn("\n  push:", reconcile)
        self.assertIn("dispatch_confirmed", overnight)
        self.assertIn("pages_publication_reconciled", overnight)
        self.assertNotIn("\n  schedule:", overnight)
