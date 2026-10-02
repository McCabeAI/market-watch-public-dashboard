"""Regression tests for Market Watch freeze git persistence boundary."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.country_registry import history_files
from scripts.market_watch_launch.persist_boundary import (
    ACP_ALLOWLIST,
    finalization_persist_allowlist,
    freeze_persist_allowlist,
    path_allowed,
    porcelain_paths,
    refresh_promoted_score_paths,
    stage_finalization_artifacts,
    stage_freeze_artifacts,
    unexpected_paths,
)
from scripts.market_watch_launch.recovery import (
    assert_accepted_inputs,
    launch_stages_finalized,
    sha256_file,
)
from scripts.overnight.constants import ROOT, STANDING_SEATS
from scripts.trading.memory import build_memory_context
from scripts.trading.store import TradingStore, empty_index
from scripts.trading.snapshot import snapshot_overnight_pms, snapshot_overnight_traders


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True)


def _init_remote_repo(tmp: Path) -> tuple[Path, Path]:
    bare = tmp / "origin.git"
    work = tmp / "work"
    _git(tmp, "init", "--bare", str(bare))
    _git(tmp, "clone", str(bare), str(work))
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "test")
    _git(work, "checkout", "-b", "main")
    return bare, work


def _seed_repo(work: Path) -> str:
    launch_id = "mwl-20260924T081911Z-9f1f9dce"
    seat = STANDING_SEATS[0]
    (work / "data" / "trading" / "trader" / seat).mkdir(parents=True)
    index = empty_index()
    (work / "data" / "trading" / "index.json").write_text(json.dumps(index), encoding="utf-8")
    context = {
        "schema_version": 1,
        "owner_type": "trader",
        "owner_id": seat,
        "as_of": "2026-09-24T08:00:00-04:00",
        "memory_context_sha256": "seed",
    }
    (work / "data" / "trading" / "trader" / seat / "context.json").write_text(
        json.dumps(context),
        encoding="utf-8",
    )
    (work / "data" / "unrelated.txt").write_text("stable\n", encoding="utf-8")
    _git(work, "add", "data")
    _git(work, "commit", "-m", "seed")
    return launch_id


def _simulate_freeze_dirty_tree(work: Path, launch_id: str) -> dict:
    seat = STANDING_SEATS[0]
    index_path = work / "data" / "trading" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["updated_at"] = "2026-09-24T08:19:11-04:00"
    index_path.write_text(json.dumps(index), encoding="utf-8")
    ctx_path = work / "data" / "trading" / "trader" / seat / "context.json"
    ctx = json.loads(ctx_path.read_text(encoding="utf-8"))
    ctx["as_of"] = "2026-09-24T08:19:12-04:00"
    ctx_path.write_text(json.dumps(ctx), encoding="utf-8")

    launch_dir = work / "data" / "market_watch_launches" / launch_id
    launch_dir.mkdir(parents=True)
    binding = {
        "launch_id": launch_id,
        "packet_sha256": "deadbeef" * 8,
        "starting_trader_books_sha256": "aa",
        "starting_pm_books_sha256": "bb",
        "score_state_sha256": "cc",
    }
    binding_path = launch_dir / "freeze_binding.json"
    binding_path.write_text(json.dumps(binding), encoding="utf-8")
    run_dir = work / "data" / "overnight" / "runs" / "overnight-20260924"
    run_dir.mkdir(parents=True)
    (run_dir / "stage_receipt.json").write_text('{"stage":"04_freeze"}\n', encoding="utf-8")
    (work / "data" / "overnight" / "latest.json").write_text('{"run_id":"overnight-20260924"}\n', encoding="utf-8")
    (work / "data" / "overnight" / "books").mkdir(parents=True, exist_ok=True)
    (work / "data" / "overnight" / "books" / "latest.json").write_text(
        '{"schema_version":1}\n',
        encoding="utf-8",
    )
    (work / "data" / "pm").mkdir(parents=True, exist_ok=True)
    (work / "data" / "pm" / "books").mkdir(parents=True, exist_ok=True)
    (work / "data" / "pm" / "books" / "latest.json").write_text(
        '{"schema_version":1}\n',
        encoding="utf-8",
    )
    return binding


def _old_stage_sequence(work: Path) -> None:
    _git(work, "add", "data/market_watch_launches")
    subprocess.run(
        [
            "git",
            "add",
            "data/overnight/runs",
            "data/overnight/books",
            "data/overnight/latest.json",
            "data/pm",
        ],
        cwd=work,
        check=False,
    )


def _advance_origin(bare: Path, tmp: Path) -> None:
    advance = tmp / "advance"
    _git(tmp, "clone", "-b", "main", str(bare), str(advance))
    _git(advance, "config", "user.email", "test@example.com")
    _git(advance, "config", "user.name", "test")
    (advance / "origin-move.txt").write_text("forward\n", encoding="utf-8")
    _git(advance, "add", "origin-move.txt")
    _git(advance, "commit", "-m", "advance main")
    _git(advance, "push", "origin", "main")


class PersistBoundaryTests(unittest.TestCase):
    def test_acp_allowlist_matches_workflow_commit_set(self) -> None:
        self.assertEqual(freeze_persist_allowlist("acp"), ACP_ALLOWLIST)
        self.assertTrue(path_allowed("data/trading/index.json", ACP_ALLOWLIST))
        self.assertTrue(path_allowed("data/overnight/runs/foo/evidence.json", ACP_ALLOWLIST))
        self.assertFalse(path_allowed("data/temperature_scores.json", ACP_ALLOWLIST))
        self.assertFalse(path_allowed("data", ACP_ALLOWLIST))
        self.assertFalse(path_allowed("data/overnight/fixtures/market_state.json", ACP_ALLOWLIST))

    def test_old_staging_fails_rebase_with_dirty_trading(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            bare, work = _init_remote_repo(tmp)
            launch_id = _seed_repo(work)
            _git(work, "push", "-u", "origin", "main")
            _advance_origin(bare, tmp)
            binding = _simulate_freeze_dirty_tree(work, launch_id)
            binding_bytes = (work / "data" / "market_watch_launches" / launch_id / "freeze_binding.json").read_bytes()

            _old_stage_sequence(work)
            _git(work, "commit", "-m", "freeze without trading")
            pull = _git(work, "pull", "--rebase", "origin", "main", check=False)
            self.assertNotEqual(pull.returncode, 0)
            self.assertIn("cannot pull with rebase", (pull.stderr or "") + (pull.stdout or ""))

            # New boundary on a clean replay of the same dirty tree state.
            _git(work, "reset", "--mixed", "HEAD~1")
            code = stage_freeze_artifacts("acp", repo_root=work)
            self.assertEqual(code, 0)
            _git(work, "commit", "-m", "freeze with boundary")
            pull2 = _git(work, "pull", "--rebase", "origin", "main")
            self.assertEqual(pull2.returncode, 0)
            _git(work, "push", "origin", "HEAD:main")

            committed = _git(work, "show", f"HEAD:data/market_watch_launches/{launch_id}/freeze_binding.json")
            self.assertEqual(committed.stdout.encode(), binding_bytes)
            self.assertEqual(json.loads(committed.stdout)["packet_sha256"], binding["packet_sha256"])
            self.assertEqual(json.loads(committed.stdout)["launch_id"], launch_id)

    def test_unexpected_path_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            bare, work = _init_remote_repo(tmp)
            launch_id = _seed_repo(work)
            _git(work, "push", "-u", "origin", "main")
            _simulate_freeze_dirty_tree(work, launch_id)
            surprise = work / "data" / "temperature_scores.json"
            surprise.write_text('{"blocked": true}\n', encoding="utf-8")

            code = stage_freeze_artifacts("acp", repo_root=work)
            self.assertEqual(code, 1)
            paths = porcelain_paths(work)
            self.assertIn("data/temperature_scores.json", paths)
            diff = _git(work, "diff", "--cached", "--name-only", check=False)
            self.assertNotIn("temperature_scores.json", diff.stdout or "")

    def test_trading_side_effects_only_touch_allowlisted_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "store"
            root.mkdir()
            store = TradingStore(root=root, state_root=root)
            store.ensure_initialized()
            seat = STANDING_SEATS[0]
            build_memory_context(store, "trader", seat)
            run_dir = root / "data" / "overnight" / "runs" / "overnight-test"
            run_dir.mkdir(parents=True)
            books = {"schema_version": 1, "traders": {}, "as_of": "2026-09-24T08:00:00-04:00"}
            snapshot_overnight_traders(
                store,
                run_dir=run_dir,
                run_id="overnight-test",
                trader_books=books,
            )
            snapshot_overnight_pms(store, run_dir=run_dir, run_id="overnight-test")

            written = [
                path.relative_to(root).as_posix()
                for path in root.rglob("*")
                if path.is_file()
            ]
            self.assertTrue(written)
            allowlist = freeze_persist_allowlist("acp")
            outside = sorted(rel for rel in written if not path_allowed(rel, allowlist))
            self.assertEqual(outside, [], f"paths outside acp allowlist: {outside}")

    def test_unexpected_paths_helper(self) -> None:
        allowlist = freeze_persist_allowlist("acp")
        bad = unexpected_paths(
            ["data/trading/index.json", "data/temperature_scores.json"],
            allowlist,
        )
        self.assertEqual(bad, ["data/temperature_scores.json"])

    def test_finalization_allowlist_includes_promoted_temperature_state(self) -> None:
        allowlist = finalization_persist_allowlist()
        self.assertIn("data/market_watch_launches", allowlist)
        self.assertIn("data/overnight", allowlist)
        self.assertIn("data/pm", allowlist)
        self.assertIn("data/trading", allowlist)
        self.assertIn("data/temperature_scores.json", allowlist)
        self.assertIn("data/temperature_history/score_paths.json", allowlist)
        for filename in history_files().values():
            self.assertIn(f"data/temperature_history/{filename}", allowlist)
            self.assertTrue(path_allowed(f"data/temperature_history/{filename}", allowlist))
        self.assertFalse(path_allowed("data/temperature_calibration.json", allowlist))
        self.assertFalse(path_allowed("data/temperature_history/raw/au/note.json", allowlist))
        self.assertFalse(path_allowed("data/temperature_scores.json", ACP_ALLOWLIST))

    def test_old_finalization_staging_fails_rebase_on_promoted_scores(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            bare, work = _init_remote_repo(tmp)
            launch_id = _seed_repo(work)
            scores = work / "data" / "temperature_scores.json"
            history = work / "data" / "temperature_history" / "au.json"
            history.parent.mkdir(parents=True)
            scores.write_text('{"version":3,"promoted":false}\n', encoding="utf-8")
            history.write_text('{"prior":true}\n', encoding="utf-8")
            _git(work, "add", "data/temperature_scores.json", "data/temperature_history/au.json")
            _git(work, "commit", "-m", "seed scores")
            _git(work, "push", "-u", "origin", "main")
            _advance_origin(bare, tmp)
            _simulate_freeze_dirty_tree(work, launch_id)
            scores.write_text('{"version":3,"promoted":true}\n', encoding="utf-8")
            history.write_text('{"promoted":true}\n', encoding="utf-8")

            _git(work, "add", "data/market_watch_launches", "data/overnight", "data/pm", "data/trading")
            _git(work, "commit", "-m", "finalize without temperature")
            pull = _git(work, "pull", "--rebase", "origin", "main", check=False)
            self.assertNotEqual(pull.returncode, 0)
            self.assertIn("cannot pull with rebase", (pull.stderr or "") + (pull.stdout or ""))

            _git(work, "reset", "--mixed", "HEAD~1")
            code = stage_finalization_artifacts(repo_root=work)
            self.assertEqual(code, 0, _git(work, "status", "--porcelain", check=False).stdout)
            _git(work, "commit", "-m", "finalize with temperature")
            pull2 = _git(work, "pull", "--rebase", "origin", "main")
            self.assertEqual(pull2.returncode, 0, pull2.stderr)
            committed = _git(work, "show", "HEAD:data/temperature_scores.json")
            self.assertIn("promoted\":true", committed.stdout.replace(" ", ""))
            history_committed = _git(work, "show", "HEAD:data/temperature_history/au.json")
            self.assertIn("promoted", history_committed.stdout)

    def test_finalization_unexpected_path_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            _bare, work = _init_remote_repo(tmp)
            _seed_repo(work)
            scores = work / "data" / "temperature_scores.json"
            scores.write_text('{"version":3,"promoted":true}\n', encoding="utf-8")
            surprise = work / "data" / "temperature_calibration.json"
            surprise.write_text('{"blocked":true}\n', encoding="utf-8")
            code = stage_finalization_artifacts(repo_root=work)
            self.assertEqual(code, 1)
            diff = _git(work, "diff", "--cached", "--name-only", check=False)
            self.assertEqual((diff.stdout or "").strip(), "")

    def test_score_path_refresh_matches_current_histories(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            history_dir = root / "data" / "temperature_history"
            history_dir.mkdir(parents=True)
            for filename in history_files().values():
                source = ROOT / "data" / "temperature_history" / filename
                (history_dir / filename).write_bytes(source.read_bytes())
            paths = history_dir / "score_paths.json"
            paths.write_bytes((ROOT / "data" / "temperature_history" / "score_paths.json").read_bytes())
            calibration = root / "data" / "temperature_calibration.json"
            calibration.write_bytes((ROOT / "data" / "temperature_calibration.json").read_bytes())
            before = paths.read_bytes()
            self.assertFalse(refresh_promoted_score_paths(root))
            self.assertEqual(paths.read_bytes(), before)


LAUNCH_ID = "mwl-20261002T094056Z-1d0ebea5"
RUN_ID = "overnight-20261002"
REVIEW_ID = "review-001"
PACKET = "abc123"


def _accepted_launch(*, finalized: bool) -> dict:
    finalize_status = "succeeded" if finalized else "pending"
    acceptance_status = "succeeded" if finalized else "pending"
    return {
        "launch_id": LAUNCH_ID,
        "overnight_run_id": RUN_ID,
        "review_id": REVIEW_ID,
        "base_packet_sha256": PACKET,
        "request": {"provider": "acp", "mode": "live", "publish_production": True},
        "stages": {
            "04_freeze": {
                "status": "succeeded",
                "details": {
                    "review_id": REVIEW_ID,
                    "packet_sha256": PACKET,
                    "overnight_run_id": RUN_ID,
                },
            },
            "06_acceptance": {"status": acceptance_status},
            "07_finalize": {
                "status": finalize_status,
                "details": {"publication": {"may_publish": True}} if finalized else {},
            },
        },
    }


class AcceptedFinalizationRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bare, self.work = _init_remote_repo(self.root)
        self.calls = self.root / "continuation_calls"
        self.calls.write_text("0", encoding="utf-8")
        self._seed(finalized=False)
        self.stub = self.root / "stub_continuation.py"
        self.stub.write_text(
            "\n".join(
                [
                    "import json, os",
                    "from pathlib import Path",
                    "root = Path('.')",
                    "launch_id = os.environ['LAUNCH_ID']",
                    "run_id = os.environ['RUN_ID']",
                    "calls = Path(os.environ['CALLS'])",
                    "calls.write_text(str(int(calls.read_text() or '0') + 1), encoding='utf-8')",
                    "if os.environ.get('STUB_UNEXPECTED') == '1':",
                    "    (root / 'data' / 'temperature_calibration.json').write_text('{\"mutated\": true}\\n', encoding='utf-8')",
                    "launch_path = root / 'data' / 'market_watch_launches' / launch_id / 'launch.json'",
                    "launch = json.loads(launch_path.read_text(encoding='utf-8'))",
                    "launch['stages']['06_acceptance']['status'] = 'succeeded'",
                    "launch['stages']['07_finalize']['status'] = 'succeeded'",
                    "launch['stages']['07_finalize']['details'] = {'publication': {'may_publish': True}}",
                    "launch_path.write_text(json.dumps(launch, indent=2) + '\\n', encoding='utf-8')",
                    "(root / 'data' / 'temperature_scores.json').write_text('{\"version\": 3, \"promoted\": true}\\n', encoding='utf-8')",
                    "(root / 'data' / 'temperature_history' / 'au.json').write_text('{\"promoted\": true}\\n', encoding='utf-8')",
                    "assembled = root / 'data' / 'overnight' / 'runs' / run_id / 'assembled_dataset.json'",
                    "assembled.parent.mkdir(parents=True, exist_ok=True)",
                    "assembled.write_text('{}\\n', encoding='utf-8')",
                    "latest = {'overnight_run_id': run_id, 'assembled_dataset': f'data/overnight/runs/{run_id}/assembled_dataset.json'}",
                    "(root / 'data' / 'overnight' / 'latest.json').write_text(json.dumps(latest) + '\\n', encoding='utf-8')",
                ]
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _seed(self, *, finalized: bool) -> None:
        launch_dir = self.work / "data" / "market_watch_launches" / LAUNCH_ID
        review_dir = self.work / "data" / "overnight" / "runs" / RUN_ID / "reviews" / REVIEW_ID
        inbox = self.work / "data" / "overnight" / "inbox" / RUN_ID
        history = self.work / "data" / "temperature_history"
        for path in (launch_dir, review_dir, inbox, history):
            path.mkdir(parents=True, exist_ok=True)
        (launch_dir / "launch.json").write_text(
            json.dumps(_accepted_launch(finalized=finalized), indent=2) + "\n",
            encoding="utf-8",
        )
        payload = {
            "launch_id": LAUNCH_ID,
            "overnight_run_id": RUN_ID,
            "review_id": REVIEW_ID,
            "base_packet_sha256": PACKET,
        }
        (inbox / "scheduled_output.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        (review_dir / "review.json").write_text(
            json.dumps({"status": "accepted", "packet_sha256": PACKET, "review_id": REVIEW_ID}) + "\n",
            encoding="utf-8",
        )
        (self.work / "data" / "temperature_scores.json").write_text('{"version": 3}\n', encoding="utf-8")
        (history / "au.json").write_text('{"prior": true}\n', encoding="utf-8")
        if finalized:
            latest = {
                "overnight_run_id": RUN_ID,
                "assembled_dataset": f"data/overnight/runs/{RUN_ID}/assembled_dataset.json",
            }
            assembled = self.work / "data" / "overnight" / "runs" / RUN_ID / "assembled_dataset.json"
            assembled.parent.mkdir(parents=True, exist_ok=True)
            assembled.write_text("{}\n", encoding="utf-8")
        else:
            latest = {"overnight_run_id": "overnight-20261001", "assembled_dataset": "data/overnight/runs/overnight-20261001/assembled_dataset.json"}
        (self.work / "data" / "overnight" / "latest.json").write_text(json.dumps(latest) + "\n", encoding="utf-8")
        _git(self.work, "add", "data")
        _git(self.work, "commit", "-m", "seed accepted launch")
        _git(self.work, "push", "-u", "origin", "main")

    def _recover(self, **env: str) -> subprocess.CompletedProcess[str]:
        script = ROOT / "scripts" / "market_watch_launch" / "recover_accepted_finalization.sh"
        merged = os.environ.copy()
        merged.update(
            {
                "LAUNCH_ID": LAUNCH_ID,
                "RUN_ID": RUN_ID,
                "CONTINUATION_CMD": f"python3 {self.stub}",
                "CALLS": str(self.calls),
                "REFRESH_SCORE_PATHS": "0",
                "PUSH": "1",
            }
        )
        merged.update(env)
        return subprocess.run(
            ["bash", str(script)],
            cwd=self.work,
            env=merged,
            text=True,
            capture_output=True,
            check=False,
        )

    def _origin_file(self, relative: str) -> str:
        show = _git(self.work, "show", f"origin/main:{relative}")
        return show.stdout

    def test_recovery_commits_promoted_scores_and_second_run_is_idempotent(self) -> None:
        before = sha256_file(self.work / "data" / "overnight" / "inbox" / RUN_ID / "scheduled_output.json")
        first = self._recover()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(self.calls.read_text(encoding="utf-8"), "1")
        self.assertIn("promoted", self._origin_file("data/temperature_scores.json"))
        self.assertIn("promoted", self._origin_file("data/temperature_history/au.json"))
        latest = json.loads(self._origin_file("data/overnight/latest.json"))
        self.assertEqual(latest["overnight_run_id"], RUN_ID)
        launched = json.loads(self._origin_file(f"data/market_watch_launches/{LAUNCH_ID}/launch.json"))
        self.assertTrue(launch_stages_finalized(launched))
        self.assertEqual(
            sha256_file(self.work / "data" / "overnight" / "inbox" / RUN_ID / "scheduled_output.json"),
            before,
        )
        tip = _git(self.work, "rev-parse", "origin/main").stdout.strip()

        second = self._recover()
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("skipping continuation", second.stdout)
        self.assertEqual(self.calls.read_text(encoding="utf-8"), "1")
        self.assertEqual(_git(self.work, "rev-parse", "origin/main").stdout.strip(), tip)
        log = _git(self.work, "log", "--oneline", "origin/main")
        self.assertEqual(log.stdout.count("chore: finalize market watch launch"), 1)

    def test_already_finalized_launch_does_not_run_continuation(self) -> None:
        launch_path = self.work / "data" / "market_watch_launches" / LAUNCH_ID / "launch.json"
        launch_path.write_text(
            json.dumps(_accepted_launch(finalized=True), indent=2) + "\n",
            encoding="utf-8",
        )
        assembled = self.work / "data" / "overnight" / "runs" / RUN_ID / "assembled_dataset.json"
        assembled.parent.mkdir(parents=True, exist_ok=True)
        assembled.write_text("{}\n", encoding="utf-8")
        latest = {
            "overnight_run_id": RUN_ID,
            "assembled_dataset": f"data/overnight/runs/{RUN_ID}/assembled_dataset.json",
        }
        (self.work / "data" / "overnight" / "latest.json").write_text(
            json.dumps(latest) + "\n",
            encoding="utf-8",
        )
        _git(self.work, "add", "data")
        _git(self.work, "commit", "-m", "already finalized")
        _git(self.work, "push", "origin", "main")
        result = self._recover()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("skipping continuation", result.stdout)
        self.assertEqual(self.calls.read_text(encoding="utf-8"), "0")
        log = _git(self.work, "log", "--oneline", "origin/main")
        self.assertNotIn("chore: finalize market watch launch", log.stdout)

    def test_unexpected_dirty_path_fails_without_publishing(self) -> None:
        before = _git(self.work, "rev-parse", "origin/main").stdout.strip()
        result = self._recover(STUB_UNEXPECTED="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unexpected paths outside finalization persistence boundary", result.stderr)
        self.assertIn("data/temperature_calibration.json", result.stderr)
        self.assertEqual(_git(self.work, "rev-parse", "origin/main").stdout.strip(), before)
        self.assertNotIn("promoted", self._origin_file("data/temperature_scores.json"))

    def test_payload_mismatch_fails_before_continuation(self) -> None:
        inbox = self.work / "data" / "overnight" / "inbox" / RUN_ID / "scheduled_output.json"
        payload = json.loads(inbox.read_text(encoding="utf-8"))
        payload["launch_id"] = "mwl-other"
        inbox.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        _git(self.work, "add", "data/overnight/inbox")
        _git(self.work, "commit", "-m", "wrong payload")
        _git(self.work, "push", "origin", "main")
        result = self._recover()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not match", result.stderr)
        self.assertEqual(self.calls.read_text(encoding="utf-8"), "0")

    def test_assert_accepted_inputs_rejects_unaccepted_review(self) -> None:
        review = self.work / "data" / "overnight" / "runs" / RUN_ID / "reviews" / REVIEW_ID / "review.json"
        review.write_text('{"status": "frozen", "packet_sha256": "%s"}\n' % PACKET, encoding="utf-8")
        with self.assertRaises(SystemExit):
            assert_accepted_inputs(self.work, launch_id=LAUNCH_ID, run_id=RUN_ID)


if __name__ == "__main__":
    unittest.main()
