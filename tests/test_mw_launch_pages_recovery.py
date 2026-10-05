"""Oct 2 shape: a successful Pages dispatch left stage 08 pending.

Recovery must terminal that launch from the deploy commit without rerunning
traders, PMs, or provider output, and a second recovery must not add state.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.market_watch_launch.contract import CONCURRENCY_BLOCK
from scripts.market_watch_launch.graph import run_launch
from scripts.market_watch_launch.pages import PAGES_RECONCILED
from scripts.market_watch_launch.pages_recovery import apply_published_pages
from scripts.market_watch_launch.state import LaunchStateStore
from scripts.overnight.constants import ROOT

NY = ZoneInfo("America/New_York")
OCT2 = "mwl-20261002T094056Z-1d0ebea5"
OCT5 = "mwl-20261005T091406Z-a512db27"
HEAD_SHA = "ffec0735582a357277e2ffa6cfe571b29608c6dc"
RUN_ID = "37036473785"
RUN_URL = "https://github.com/McCabeAI/market-watch-public-dashboard/actions/runs/37036473785"
REPOSITORY = "McCabeAI/market-watch-public-dashboard"
PACKET = "2b0c5980ac350ecd70d6149b08fef310ca461ba19924d01d4a1a8dd5c673688b"
WHEN = datetime(2026, 10, 5, 12, 0, tzinfo=NY)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _oct2_run(**overrides: object) -> dict:
    payload: dict = {
        "id": int(RUN_ID),
        "name": "Deploy Market Watch Dashboard",
        "path": ".github/workflows/deploy-pages.yml",
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "head_branch": "main",
        "head_sha": HEAD_SHA,
        "html_url": RUN_URL,
        "repository": {"full_name": REPOSITORY},
        "head_repository": {"full_name": REPOSITORY},
    }
    payload.update(overrides)
    return payload


def _ensure_deploy_commit() -> None:
    probe = subprocess.run(
        ["git", "cat-file", "-e", HEAD_SHA],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if probe.returncode == 0:
        return
    fetched = subprocess.run(
        ["git", "fetch", "--depth", "1", "origin", HEAD_SHA],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if fetched.returncode != 0:
        raise AssertionError(fetched.stderr or fetched.stdout or "deploy commit is not available")


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True)


def _init_remote_repo(tmp: Path) -> Path:
    bare = tmp / "origin.git"
    work = tmp / "work"
    _git(tmp, "init", "--bare", str(bare))
    _git(tmp, "clone", str(bare), str(work))
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "test")
    _git(work, "checkout", "-b", "main")
    return work


class Oct2PagesRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        _ensure_deploy_commit()
        self.tmp = tempfile.TemporaryDirectory()
        self.state_root = Path(self.tmp.name)
        self._copy_launch_state()
        self.sentinel = self.state_root / "data" / "overnight" / "books" / "latest.json"
        self.sentinel.parent.mkdir(parents=True, exist_ok=True)
        self.sentinel.write_text('{"do":"not-touch"}\n', encoding="utf-8")
        self.before = {
            "oct2": _sha256_file(self._launch_path(OCT2)),
            "oct5": _sha256_file(self._launch_path(OCT5)),
            "sentinel": _sha256_file(self.sentinel),
        }
        self.root_status = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _copy_launch_state(self) -> None:
        source = ROOT / "data" / "market_watch_launches"
        for launch_id in (OCT2, OCT5):
            target = self.state_root / "data" / "market_watch_launches" / launch_id
            target.mkdir(parents=True)
            shutil.copy2(source / launch_id / "launch.json", target / "launch.json")
        shutil.copy2(source / "index.json", self.state_root / "data" / "market_watch_launches" / "index.json")

    def _launch_path(self, launch_id: str) -> Path:
        return self.state_root / "data" / "market_watch_launches" / launch_id / "launch.json"

    def _assert_untouched_inputs(self) -> None:
        self.assertEqual(_sha256_file(self._launch_path(OCT5)), self.before["oct5"])
        self.assertEqual(_sha256_file(self.sentinel), self.before["sentinel"])
        self.assertEqual(
            subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT),
            self.root_status,
        )

    def _request(self) -> dict:
        return {
            "session_date": "2026-10-05",
            "rerun": False,
            "mode": "fixture",
            "provider": "stub",
            "source": "github_issue",
            "actor_type": "User",
            "actor": "example-user",
            "issue_number": 160,
            "issue_url": "https://github.com/McCabeAI/market-watch-public-dashboard/issues/160",
            "repository_permission": "admin",
        }

    def _apply(self, run: dict | None = None, **kwargs: object) -> dict:
        return apply_published_pages(
            repo_root=ROOT,
            state_root=self.state_root,
            launch_id=kwargs.pop("launch_id", OCT2),  # type: ignore[arg-type]
            run=run if run is not None else _oct2_run(),
            run_id=str(kwargs.pop("run_id", RUN_ID)),
            repository=str(kwargs.pop("repository", REPOSITORY)),
        )

    def test_deployed_tree_matches_the_canonical_oct2_launch(self) -> None:
        deployed = subprocess.check_output(
            ["git", "show", f"{HEAD_SHA}:data/market_watch_launches/{OCT2}/launch.json"],
            cwd=ROOT,
        )
        current = (ROOT / "data" / "market_watch_launches" / OCT2 / "launch.json").read_bytes()
        self.assertEqual(deployed, current)
        payload = json.loads(current)
        self.assertEqual(payload["launch_id"], OCT2)
        self.assertEqual(payload["review_id"], "review-001")
        self.assertEqual(payload["base_packet_sha256"], PACKET)
        self.assertEqual(payload["status"], "running")
        self.assertEqual(payload["stages"]["08_pages"]["status"], "pending")
        for name in (
            "00_authenticate",
            "01_ingest",
            "02_acquire",
            "03_quality_gate",
            "04_freeze",
            "05_acp_handoff",
            "06_acceptance",
            "07_finalize",
        ):
            self.assertEqual(payload["stages"][name]["status"], "succeeded", name)

    def test_proven_oct2_deploy_releases_the_guard_without_touching_later_launches(self) -> None:
        blocked = run_launch(
            self._request(),
            root=self.state_root,
            state_root=self.state_root,
            when=WHEN,
            through="00_authenticate",
        )
        self.assertEqual(blocked["launch_id"], OCT5)
        self.assertEqual(blocked["launch"]["stages"]["00_authenticate"]["reason"], CONCURRENCY_BLOCK)
        self.assertEqual(_sha256_file(self._launch_path(OCT2)), self.before["oct2"])

        decision = self._apply()
        self.assertTrue(decision["changed"])
        self.assertFalse(decision["already_reconciled"])
        self.assertEqual(decision["reason"], PAGES_RECONCILED)
        self.assertEqual(decision["head_sha"], HEAD_SHA)
        self.assertNotIn("evidence", decision)

        store = LaunchStateStore(self.state_root)
        reconciled = store.load_launch(OCT2)
        self.assertEqual(reconciled["status"], "succeeded")
        self.assertEqual(reconciled["review_id"], "review-001")
        self.assertEqual(reconciled["base_packet_sha256"], PACKET)
        pages = reconciled["stages"]["08_pages"]
        self.assertEqual(pages["status"], "succeeded")
        self.assertEqual(pages["reason"], PAGES_RECONCILED)
        self.assertEqual(pages["details"]["publication_evidence"]["head_sha"], HEAD_SHA)
        self.assertEqual(pages["details"]["publication_evidence"]["run_url"], RUN_URL)
        self.assertEqual(pages["details"]["publication_evidence"]["event"], "workflow_dispatch")
        self.assertTrue(pages["details"]["production_published"])
        self.assertIsNone(store.live_launch())
        index = json.loads((self.state_root / "data" / "market_watch_launches" / "index.json").read_text(encoding="utf-8"))
        self.assertIsNone(index["live_launch_id"])
        oct5_row = next(row for row in index["launches"] if row["launch_id"] == OCT5)
        self.assertEqual(oct5_row["status"], "blocked")
        preserved = store.load_launch(OCT5)
        self.assertEqual(preserved["status"], "blocked")
        self.assertEqual(preserved["stages"]["00_authenticate"]["reason"], CONCURRENCY_BLOCK)
        _artifact, digest = store.reread_artifact(OCT2, "08_pages")
        self.assertEqual(digest, pages["output_sha256"])
        self._assert_untouched_inputs()

        launch_bytes = self._launch_path(OCT2).read_bytes()
        artifact_bytes = (
            self.state_root / "data" / "market_watch_launches" / OCT2 / "artifacts" / "08_pages.json"
        ).read_bytes()
        second = self._apply()
        self.assertFalse(second["changed"])
        self.assertTrue(second["already_reconciled"])
        self.assertEqual(self._launch_path(OCT2).read_bytes(), launch_bytes)
        self.assertEqual(
            (self.state_root / "data" / "market_watch_launches" / OCT2 / "artifacts" / "08_pages.json").read_bytes(),
            artifact_bytes,
        )
        self._assert_untouched_inputs()

        nxt = run_launch(
            self._request(),
            root=self.state_root,
            state_root=self.state_root,
            when=WHEN,
            through="00_authenticate",
        )
        self.assertNotEqual(nxt["launch_id"], OCT5)
        self.assertNotEqual(nxt["launch_id"], OCT2)
        self.assertEqual(nxt["launch"]["stages"]["00_authenticate"]["status"], "succeeded")
        self.assertNotEqual(nxt["launch"]["stages"]["00_authenticate"]["reason"], CONCURRENCY_BLOCK)
        self.assertEqual(store.load_launch(OCT2)["status"], "succeeded")
        self.assertEqual(store.load_launch(OCT5)["status"], "blocked")
        self._assert_untouched_inputs()

        forged = store.load_launch(OCT2)
        forged["stages"]["08_pages"]["details"]["publication_evidence"]["head_sha"] = "a" * 40
        store.save_launch(forged)
        with self.assertRaises(SystemExit) as ctx:
            self._apply()
        self.assertIn("terminal without matching pages publication evidence", str(ctx.exception))

    def _assert_refused(self, message: str, **kwargs: object) -> None:
        with self.assertRaises(SystemExit) as ctx:
            self._apply(**kwargs)
        self.assertIn(message, str(ctx.exception))
        self.assertEqual(_sha256_file(self._launch_path(OCT2)), self.before["oct2"])
        store = LaunchStateStore(self.state_root)
        self.assertEqual(store.load_launch(OCT2)["status"], "running")
        self.assertEqual(store.load_launch(OCT2)["stages"]["08_pages"]["status"], "pending")
        index = json.loads(
            (self.state_root / "data" / "market_watch_launches" / "index.json").read_text(encoding="utf-8")
        )
        self.assertEqual(index["live_launch_id"], OCT2)
        blocked = run_launch(
            self._request(),
            root=self.state_root,
            state_root=self.state_root,
            when=WHEN,
            through="00_authenticate",
        )
        self.assertEqual(blocked["launch"]["stages"]["00_authenticate"]["reason"], CONCURRENCY_BLOCK)
        self._assert_untouched_inputs()

    def test_fail_closed_on_mismatched_launch_id(self) -> None:
        payload = json.loads(self._launch_path(OCT2).read_text(encoding="utf-8"))
        payload["launch_id"] = "mwl-20261002T094056Z-ffffffff"
        self._launch_path(OCT2).write_text(json.dumps(payload), encoding="utf-8")
        self.before["oct2"] = _sha256_file(self._launch_path(OCT2))
        self._assert_refused("mismatched launch_id")

    def test_fail_closed_on_mismatched_review_id(self) -> None:
        payload = json.loads(self._launch_path(OCT2).read_text(encoding="utf-8"))
        payload["review_id"] = "review-009"
        self._launch_path(OCT2).write_text(json.dumps(payload), encoding="utf-8")
        self.before["oct2"] = _sha256_file(self._launch_path(OCT2))
        self._assert_refused("mismatched review_id")

    def test_fail_closed_on_mismatched_packet_sha(self) -> None:
        payload = json.loads(self._launch_path(OCT2).read_text(encoding="utf-8"))
        payload["base_packet_sha256"] = "a" * 64
        self._launch_path(OCT2).write_text(json.dumps(payload), encoding="utf-8")
        self.before["oct2"] = _sha256_file(self._launch_path(OCT2))
        self._assert_refused("mismatched packet SHA")

    def test_fail_closed_on_mismatched_deploy_head_sha(self) -> None:
        self._assert_refused("mismatched deploy head SHA", run=_oct2_run(head_sha="0" * 40))

    def test_fail_closed_on_non_success_conclusion(self) -> None:
        self._assert_refused("non-success conclusion", run=_oct2_run(conclusion="failure"))

    def test_fail_closed_on_non_main_ref(self) -> None:
        self._assert_refused("non-main ref", run=_oct2_run(head_branch="gh-pages"))

    def test_fail_closed_on_non_workflow_dispatch_event(self) -> None:
        self._assert_refused("non-workflow_dispatch event", run=_oct2_run(event="push"))

    def test_fail_closed_on_other_workflow(self) -> None:
        self._assert_refused(
            "workflow is not deploy-pages.yml",
            run=_oct2_run(path=".github/workflows/launch-market-watch.yml"),
        )

    def test_fail_closed_when_stages_00_through_07_are_not_all_succeeded(self) -> None:
        payload = json.loads(self._launch_path(OCT2).read_text(encoding="utf-8"))
        payload["stages"]["02_acquire"]["status"] = "failed"
        self._launch_path(OCT2).write_text(json.dumps(payload), encoding="utf-8")
        self.before["oct2"] = _sha256_file(self._launch_path(OCT2))
        self._assert_refused("stages 00-07 not all succeeded")

    def test_workflow_is_an_explicit_dispatch_of_the_recovery_script(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "reconcile-published-pages.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("\n  push:", workflow)
        self.assertNotIn("\n  schedule:", workflow)
        self.assertIn("reconcile_published_pages.sh", workflow)
        self.assertIn("actions: read", workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn(OCT2, workflow)
        self.assertIn(RUN_ID, workflow)


class PagesRecoveryCommitTests(unittest.TestCase):
    def _seed(self, tmp: Path) -> tuple[Path, str]:
        work = _init_remote_repo(tmp)
        launches = work / "data" / "market_watch_launches"
        for launch_id in (OCT2, OCT5):
            target = launches / launch_id
            target.mkdir(parents=True)
            shutil.copy2(
                ROOT / "data" / "market_watch_launches" / launch_id / "launch.json",
                target / "launch.json",
            )
        shutil.copy2(ROOT / "data" / "market_watch_launches" / "index.json", launches / "index.json")
        sentinel = work / "data" / "overnight" / "books" / "latest.json"
        sentinel.parent.mkdir(parents=True)
        sentinel.write_text('{"do":"not-touch"}\n', encoding="utf-8")
        _git(work, "add", "data")
        _git(work, "commit", "-m", "seed oct 2 launch")
        _git(work, "push", "-u", "origin", "main")
        return work, _git(work, "rev-parse", "HEAD").stdout.strip()

    def _run_json(self, directory: Path, head_sha: str, **overrides: object) -> Path:
        payload = _oct2_run(head_sha=head_sha, **overrides)
        path = directory / "run.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _recover(self, work: Path, run_json: Path, **env: str) -> subprocess.CompletedProcess[str]:
        script = ROOT / "scripts" / "market_watch_launch" / "reconcile_published_pages.sh"
        merged = os.environ.copy()
        merged.update(
            {
                "LAUNCH_ID": OCT2,
                "RUN_ID": RUN_ID,
                "PAGES_RUN_JSON": str(run_json),
                "PUSH": "1",
            }
        )
        merged.update(env)
        return subprocess.run(
            ["bash", str(script)],
            cwd=work,
            env=merged,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_script_commits_only_launch_state_and_second_run_is_a_no_op(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work, deploy_sha = self._seed(root)
            sentinel = _sha256_file(work / "data" / "overnight" / "books" / "latest.json")
            oct5 = _sha256_file(work / "data" / "market_watch_launches" / OCT5 / "launch.json")
            run_json = self._run_json(root, deploy_sha)
            first = self._recover(work, run_json)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            tip = _git(work, "rev-parse", "origin/main").stdout.strip()
            self.assertNotEqual(tip, deploy_sha)
            names = _git(
                work, "diff-tree", "--no-commit-id", "--name-only", "-r", "origin/main"
            ).stdout.split()
            self.assertEqual(
                sorted(names),
                sorted(
                    [
                        f"data/market_watch_launches/{OCT2}/artifacts/08_pages.json",
                        f"data/market_watch_launches/{OCT2}/launch.json",
                        "data/market_watch_launches/index.json",
                    ]
                ),
            )
            launched = json.loads(
                _git(work, "show", f"origin/main:data/market_watch_launches/{OCT2}/launch.json").stdout
            )
            self.assertEqual(launched["status"], "succeeded")
            self.assertEqual(launched["stages"]["08_pages"]["reason"], PAGES_RECONCILED)
            self.assertEqual(launched["stages"]["08_pages"]["details"]["publication_evidence"]["head_sha"], deploy_sha)
            self.assertEqual(_sha256_file(work / "data" / "overnight" / "books" / "latest.json"), sentinel)
            self.assertEqual(_sha256_file(work / "data" / "market_watch_launches" / OCT5 / "launch.json"), oct5)

            second = self._recover(work, run_json)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertIn("no additional commit", second.stdout)
            self.assertEqual(_git(work, "rev-parse", "origin/main").stdout.strip(), tip)
            log = _git(work, "log", "--oneline", "origin/main")
            self.assertEqual(log.stdout.count("chore: reconcile market watch launch"), 1)

    def test_unexpected_dirty_path_fails_without_publishing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work, deploy_sha = self._seed(root)
            run_json = self._run_json(root, deploy_sha)
            (work / "data" / "temperature_scores.json").write_text('{"mutated": true}\n', encoding="utf-8")
            result = self._recover(work, run_json)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("unexpected paths outside pages reconciliation persistence boundary", result.stderr)
            self.assertIn("data/temperature_scores.json", result.stderr)
            self.assertEqual(_git(work, "rev-parse", "origin/main").stdout.strip(), deploy_sha)
            launched = json.loads(
                _git(work, "show", f"origin/main:data/market_watch_launches/{OCT2}/launch.json").stdout
            )
            self.assertEqual(launched["status"], "running")
            self.assertEqual(launched["stages"]["08_pages"]["status"], "pending")

    def test_bad_conclusion_fails_without_publishing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work, deploy_sha = self._seed(root)
            run_json = self._run_json(root, deploy_sha, conclusion="cancelled")
            result = self._recover(work, run_json)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("non-success conclusion", result.stderr)
            self.assertEqual(_git(work, "rev-parse", "origin/main").stdout.strip(), deploy_sha)


if __name__ == "__main__":
    unittest.main()
