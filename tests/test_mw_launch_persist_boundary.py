"""Regression tests for Market Watch freeze git persistence boundary."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.market_watch_launch.persist_boundary import (
    ACP_ALLOWLIST,
    freeze_persist_allowlist,
    path_allowed,
    porcelain_paths,
    stage_freeze_artifacts,
    unexpected_paths,
)
from scripts.overnight.constants import STANDING_SEATS
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


if __name__ == "__main__":
    unittest.main()
