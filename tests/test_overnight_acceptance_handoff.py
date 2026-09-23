"""Regression coverage for the Sep 22 scheduled-output handoff gaps."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from scripts.overnight.constants import ROOT

RUN_ID = "overnight-20260922"
HEAD_REF = "cursor/scheduled-output"
JOURNAL = {
    "events": [
        {
            "kind": "OVERNIGHT_DECISION",
            "review_id": "review-004",
            "trade_id": "trd-once",
            "funding_usd": 12.5,
        }
    ]
}
TRADE = {"trade_id": "trd-once", "funding_usd": 12.5}
BOOK = {"funding_usd": 12.5, "trades": ["trd-once"]}


def _run(cmd: list[str], *, cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(cmd, cwd=cwd, env=merged, text=True, capture_output=True, check=False)


def _git(repo: Path, *args: str) -> None:
    result = _run(["git", *args], cwd=repo)
    if result.returncode != 0:
        raise AssertionError(f"git {args} failed\n{result.stdout}\n{result.stderr}")


class AcceptanceWorkflowContractTests(unittest.TestCase):
    def test_draft_merge_and_pages_dispatch_stay_behind_existing_gates(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "overnight-scheduled-output.yml").read_text(encoding="utf-8")
        merge_script = (ROOT / "scripts" / "overnight" / "merge_accepted_output.sh").read_text(encoding="utf-8")
        append_script = (ROOT / "scripts" / "overnight" / "append_generated_state.sh").read_text(encoding="utf-8")
        pages = (ROOT / ".github" / "workflows" / "deploy-pages.yml").read_text(encoding="utf-8")

        self.assertIn("pull_request_target", workflow)
        self.assertIn('[ "$HEAD_REPO" = "$BASE_REPO" ]', workflow)
        self.assertIn("scheduled_output.json", workflow)
        self.assertIn("ref: main", workflow)
        self.assertIn("scheduled_output.py validate", workflow)
        self.assertIn("scheduled_output.py apply", workflow)
        self.assertIn("Canonical trader books on main changed", workflow)
        self.assertIn("Canonical PM books on main changed", workflow)
        self.assertIn("actions: write", workflow)
        self.assertNotIn("github.event.pull_request.draft", workflow)
        self.assertNotIn("gh pr merge", workflow)
        self.assertNotIn("gh workflow run", workflow)
        self.assertEqual(workflow.count("merge_accepted_output.sh"), 1)
        self.assertIn("restore_assembly_stale_overlay_for_acceptance", workflow)
        self.assertLess(
            workflow.index("restore_assembly_stale_overlay_for_acceptance"),
            workflow.index("scheduled_output.py validate"),
        )
        self.assertLess(workflow.index("scheduled_output.py validate"), workflow.index("scheduled_output.py apply"))
        self.assertLess(workflow.index("scheduled_output.py apply"), workflow.index("append_generated_state.sh"))
        self.assertLess(workflow.index("append_generated_state.sh"), workflow.index("Revalidate canonical book blobs"))
        self.assertLess(workflow.index("Revalidate canonical book blobs"), workflow.index("merge_accepted_output.sh"))

        self.assertLess(merge_script.index("gh pr ready"), merge_script.index("gh pr merge"))
        self.assertLess(merge_script.index("gh pr merge"), merge_script.index("gh workflow run deploy-pages.yml --ref main"))
        self.assertIn('if [ "$draft" = "true" ]', merge_script)
        self.assertIn('if [ "$state" != "MERGED" ]', merge_script)
        self.assertIn("Pages deployment was not dispatched", merge_script)
        self.assertLess(append_script.index("git clean -fd"), append_script.index('git checkout -B "$HEAD_REF"'))
        self.assertIn("workflow_dispatch:", pages)


class MergeAcceptedOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.log = self.root / "gh.log"
        self.state = self.root / "state"
        self.state.write_text("OPEN\n", encoding="utf-8")
        self.draft = self.root / "draft"
        self.draft.write_text("true\n", encoding="utf-8")
        self.merge_fail = self.root / "merge_fail"
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "gh"
        fake.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                set -euo pipefail
                printf '%s\\n' "$*" >> {self.log}
                if [[ "$1" == "pr" && "$2" == "view" && "$*" == *isDraft* ]]; then
                  tr -d '[:space:]' < {self.draft}
                  printf '\\n'
                  exit 0
                fi
                if [[ "$1" == "pr" && "$2" == "view" && "$*" == *state* ]]; then
                  tr -d '[:space:]' < {self.state}
                  printf '\\n'
                  exit 0
                fi
                if [[ "$1" == "pr" && "$2" == "ready" ]]; then
                  printf 'false\\n' > {self.draft}
                  exit 0
                fi
                if [[ "$1" == "pr" && "$2" == "merge" ]]; then
                  if [[ -f {self.merge_fail} ]]; then
                    echo "merge rejected" >&2
                    exit 1
                  fi
                  printf 'MERGED\\n' > {self.state}
                  exit 0
                fi
                if [[ "$1" == "workflow" && "$2" == "run" ]]; then
                  exit 0
                fi
                echo "unexpected gh invocation: $*" >&2
                exit 1
                """
            ),
            encoding="utf-8",
        )
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        self.env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}", "PR_URL": "https://example.test/pull/97"}

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _merge(self) -> subprocess.CompletedProcess[str]:
        script = ROOT / "scripts" / "overnight" / "merge_accepted_output.sh"
        return _run(["bash", str(script)], cwd=self.root, env=self.env)

    def _calls(self) -> list[str]:
        if not self.log.exists():
            return []
        return [line.strip() for line in self.log.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_draft_pr_is_marked_ready_then_merged_then_pages_dispatched(self) -> None:
        result = self._merge()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self._calls()
        self.assertEqual(
            calls,
            [
                "pr view https://example.test/pull/97 --json isDraft --jq .isDraft",
                "pr ready https://example.test/pull/97",
                "pr view https://example.test/pull/97 --json state --jq .state",
                "pr merge https://example.test/pull/97 --squash --delete-branch",
                "pr view https://example.test/pull/97 --json state --jq .state",
                "workflow run deploy-pages.yml --ref main",
            ],
        )

    def test_ready_pr_merges_without_another_ready_call(self) -> None:
        self.draft.write_text("false\n", encoding="utf-8")
        result = self._merge()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self._calls()
        self.assertFalse(any(call.startswith("pr ready") for call in calls))
        self.assertIn("pr merge https://example.test/pull/97 --squash --delete-branch", calls)
        self.assertEqual(calls[-1], "workflow run deploy-pages.yml --ref main")

    def test_already_merged_pr_dispatches_pages_without_merging_again(self) -> None:
        self.draft.write_text("false\n", encoding="utf-8")
        self.state.write_text("MERGED\n", encoding="utf-8")
        result = self._merge()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self._calls()
        self.assertFalse(any(call.startswith("pr merge") for call in calls))
        self.assertEqual(calls[-1], "workflow run deploy-pages.yml --ref main")

    def test_failed_merge_does_not_dispatch_pages(self) -> None:
        self.merge_fail.write_text("1\n", encoding="utf-8")
        result = self._merge()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("workflow run deploy-pages.yml --ref main", self._calls())

    def test_unmerged_state_does_not_dispatch_pages(self) -> None:
        fake_bin = Path(self.env["PATH"].split(os.pathsep)[0])
        (fake_bin / "gh").write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                set -euo pipefail
                printf '%s\\n' "$*" >> {self.log}
                if [[ "$1" == "pr" && "$2" == "view" && "$*" == *isDraft* ]]; then
                  printf 'false\\n'
                  exit 0
                fi
                if [[ "$1" == "pr" && "$2" == "view" && "$*" == *state* ]]; then
                  printf 'OPEN\\n'
                  exit 0
                fi
                if [[ "$1" == "pr" && "$2" == "merge" ]]; then
                  exit 0
                fi
                if [[ "$1" == "workflow" && "$2" == "run" ]]; then
                  exit 0
                fi
                exit 1
                """
            ),
            encoding="utf-8",
        )
        (fake_bin / "gh").chmod((fake_bin / "gh").stat().st_mode | stat.S_IEXEC)
        result = self._merge()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Pages deployment was not dispatched", result.stdout + result.stderr)
        self.assertNotIn("workflow run deploy-pages.yml --ref main", self._calls())


class AppendGeneratedStateRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.remote = self.root / "remote.git"
        self.work = self.root / "work"
        self.generated = self.root / "generated"
        self.work.mkdir()
        _git(self.work, "init", "-b", "main")
        _git(self.work, "config", "user.email", "test@example.com")
        _git(self.work, "config", "user.name", "Test")
        inbox = self.work / "data" / "overnight" / "inbox" / RUN_ID
        inbox.mkdir(parents=True)
        (inbox / "scheduled_output.json").write_text("{}\n", encoding="utf-8")
        (self.work / "README.md").write_text("base\n", encoding="utf-8")
        _git(self.work, "add", ".")
        _git(self.work, "commit", "-m", "base")
        _run(["git", "init", "--bare", "-b", "main", str(self.remote)], cwd=self.root)
        _git(self.work, "remote", "add", "origin", str(self.remote))
        _git(self.work, "push", "-u", "origin", "main")
        _git(self.work, "checkout", "-b", HEAD_REF)
        _git(self.work, "push", "-u", "origin", HEAD_REF)
        _git(self.work, "checkout", "main")
        self._write_generated()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_generated(self) -> None:
        if self.generated.exists():
            shutil.rmtree(self.generated)
        journal = self.generated / "trading" / "trader" / "cross-merchant" / "journal.json"
        trade = self.generated / "trading" / "trades" / "trd-once.json"
        book = self.generated / "books" / "latest.json"
        pm_book = self.generated / "pm" / "books" / "latest.json"
        run_json = self.generated / "runs" / RUN_ID / "run.json"
        for path in (journal, trade, book, pm_book, run_json):
            path.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text(json.dumps(JOURNAL, indent=2) + "\n", encoding="utf-8")
        trade.write_text(json.dumps(TRADE, indent=2) + "\n", encoding="utf-8")
        book.write_text(json.dumps(BOOK, indent=2) + "\n", encoding="utf-8")
        pm_book.write_text(json.dumps(BOOK, indent=2) + "\n", encoding="utf-8")
        run_json.write_text("{}\n", encoding="utf-8")

    def _append(self) -> subprocess.CompletedProcess[str]:
        script = ROOT / "scripts" / "overnight" / "append_generated_state.sh"
        return _run(
            ["bash", str(script)],
            cwd=self.work,
            env={
                "HEAD_REF": HEAD_REF,
                "RUN_ID": RUN_ID,
                "GENERATED_DIR": str(self.generated),
                "REMOTE": "origin",
                "PUSH": "1",
            },
        )

    def _branch_file(self, relative: str) -> str:
        show = _run(["git", "show", f"origin/{HEAD_REF}:{relative}"], cwd=self.work)
        self.assertEqual(show.returncode, 0, show.stderr)
        return show.stdout

    def test_retry_after_generated_state_is_idempotent(self) -> None:
        first = self._append()
        self.assertEqual(first.returncode, 0, first.stderr)
        _git(self.work, "fetch", "origin", HEAD_REF)
        first_tip = _run(["git", "rev-parse", f"origin/{HEAD_REF}"], cwd=self.work).stdout.strip()

        _git(self.work, "checkout", "main")
        collision_journal = self.work / "data" / "trading" / "trader" / "cross-merchant" / "journal.json"
        collision_trade = self.work / "data" / "trading" / "trades" / "trd-once.json"
        collision_journal.parent.mkdir(parents=True, exist_ok=True)
        collision_trade.parent.mkdir(parents=True, exist_ok=True)
        collision_journal.write_text(json.dumps(JOURNAL) + "\n" + json.dumps(JOURNAL) + "\n", encoding="utf-8")
        collision_trade.write_text('{"trade_id":"trd-once"}\n{"trade_id":"trd-duplicate"}\n', encoding="utf-8")

        bare_checkout = _run(["git", "checkout", "-B", HEAD_REF, f"origin/{HEAD_REF}"], cwd=self.work)
        self.assertNotEqual(bare_checkout.returncode, 0)
        self.assertIn("would be overwritten by checkout", bare_checkout.stderr)
        _git(self.work, "checkout", "--force", "main")

        second = self._append()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("already matches", second.stdout)
        _git(self.work, "fetch", "origin", HEAD_REF)
        second_tip = _run(["git", "rev-parse", f"origin/{HEAD_REF}"], cwd=self.work).stdout.strip()
        self.assertEqual(first_tip, second_tip)

        journal = self._branch_file("data/trading/trader/cross-merchant/journal.json")
        trade = self._branch_file("data/trading/trades/trd-once.json")
        book = self._branch_file("data/overnight/books/latest.json")
        self.assertEqual(journal.count("trd-once"), 1)
        self.assertEqual(journal.count("OVERNIGHT_DECISION"), 1)
        self.assertEqual(trade.count("trd-once"), 1)
        self.assertNotIn("trd-duplicate", trade)
        self.assertEqual(json.loads(book)["funding_usd"], 12.5)
        self.assertEqual(json.loads(book)["trades"], ["trd-once"])
        commits = _run(["git", "log", "--oneline", f"origin/{HEAD_REF}"], cwd=self.work)
        self.assertEqual(commits.stdout.count("chore: apply overnight decisions"), 1)


class TrustedRunnerStatusRestoreTests(unittest.TestCase):
    """A late assembly status overlay must not invalidate a frozen decision cycle."""

    def setUp(self) -> None:
        from scripts.overnight.reviews import persist_review
        from scripts.overnight.store import OvernightStore, sha256_json, write_json
        from scripts.pm.store import PMStore

        self.tmp = tempfile.TemporaryDirectory()
        self.run_id = "overnight-20260923"
        self.review_id = "review-001"
        self.store = OvernightStore(root=ROOT, state_root=Path(self.tmp.name))
        self.pm_store = PMStore(root=ROOT, state_root=Path(self.tmp.name))
        self.trader = {
            "review_status": "fresh",
            "last_successful_review_run_id": "overnight-20260922",
            "seats": {"sample": {"positions": [{"instrument": "AONIA", "notional_usd": 12}], "nav_usd": 100}},
        }
        self.pm = {
            "overnight_run_id": "overnight-20260922",
            "pms": {
                name: {
                    "review_status": "fresh",
                    "last_decision_at": "2026-09-22T10:00:00Z",
                    "positions": [{"instrument": "CORRA", "notional_usd": 50}],
                }
                for name in ("swinger", "pragmatist", "grinder")
            },
        }
        self.pm["pms"]["chatgpt"] = {
            "review_status": "fresh", "last_decision_at": "2026-09-22T10:00:00Z",
            "positions": [{"instrument": "CORRA", "notional_usd": 60}],
        }
        write_json(self.store.books_path(), self.trader)
        write_json(self.pm_store.books_path(), self.pm)
        trader_sha, pm_sha = sha256_json(self.trader), sha256_json(self.pm)
        snapshot = {
            "schema_version": 1,
            "type": "OVERNIGHT_EVIDENCE_SNAPSHOT",
            "overnight_run_id": self.run_id,
            "review_id": self.review_id,
            "as_of": "2026-09-23T05:07:56-04:00",
            "prior_books": self.trader,
            "prior_pm_books": self.pm,
            "starting_trader_books_sha256": trader_sha,
            "starting_pm_books_sha256": pm_sha,
        }
        snapshot["packet_sha256"] = sha256_json(snapshot)
        self.store.write_artifact(
            self.run_id, "evidence_snapshot.json", snapshot, review_id=self.review_id
        )
        self.meta = {
            "schema_version": 1,
            "type": "OVERNIGHT_REVIEW",
            "overnight_run_id": self.run_id,
            "review_id": self.review_id,
            "status": "frozen",
            "packet_sha256": snapshot["packet_sha256"],
            "starting_state_binding": "canonical_file",
            "starting_trader_books_present": True,
            "starting_pm_books_present": True,
            "starting_trader_books_sha256": trader_sha,
            "starting_pm_books_sha256": pm_sha,
        }
        persist_review(self.store, self.meta)
        self.store.write_artifact(
            self.run_id, "assembled_dataset.json",
            {
                "overnight_run_id": self.run_id,
                "publication": {
                    "trader_books_status": "stale",
                    "pm_books_status": "stale",
                    "last_successful_review_run_id": "overnight-20260922",
                },
            },
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _mark_stale_as_assembly_does(self) -> None:
        from scripts.overnight.store import write_json
        from scripts.pm.books import overlay_automated_pm_stale_for_cycle

        trader = json.loads(self.store.books_path().read_text())
        trader["review_status"] = "stale"
        write_json(self.store.books_path(), trader)
        pm = json.loads(self.pm_store.books_path().read_text())
        write_json(self.pm_store.books_path(), overlay_automated_pm_stale_for_cycle(pm))

    def _restore(self) -> bool:
        from scripts.overnight.reviews import restore_assembly_stale_overlay_for_acceptance

        return restore_assembly_stale_overlay_for_acceptance(
            self.store, run_id=self.run_id, review_id=self.review_id
        )

    def test_restores_only_exact_assembler_overlay_to_frozen_hashes(self) -> None:
        from scripts.overnight.reviews import starting_books_match

        self._mark_stale_as_assembly_does()
        self.assertFalse(starting_books_match(self.store, self.meta))
        self.assertTrue(self._restore())
        self.assertTrue(starting_books_match(self.store, self.meta))
        self.assertEqual(json.loads(self.store.books_path().read_text()), self.trader)
        self.assertEqual(json.loads(self.pm_store.books_path().read_text()), self.pm)
        self.assertFalse(self._restore())

    def test_rejects_substantive_trader_change_and_preserves_books(self) -> None:
        from scripts.overnight.errors import EvidenceBoundaryError
        from scripts.overnight.store import write_json

        self._mark_stale_as_assembly_does()
        trader = json.loads(self.store.books_path().read_text())
        trader["seats"]["sample"]["positions"][0]["notional_usd"] = 13
        write_json(self.store.books_path(), trader)
        old_trader, old_pm = self.store.books_path().read_bytes(), self.pm_store.books_path().read_bytes()
        with self.assertRaises(EvidenceBoundaryError):
            self._restore()
        self.assertEqual(self.store.books_path().read_bytes(), old_trader)
        self.assertEqual(self.pm_store.books_path().read_bytes(), old_pm)

    def test_rejects_substantive_pm_change_and_preserves_books(self) -> None:
        from scripts.overnight.errors import EvidenceBoundaryError
        from scripts.overnight.store import write_json

        self._mark_stale_as_assembly_does()
        pm = json.loads(self.pm_store.books_path().read_text())
        pm["pms"]["swinger"]["positions"][0]["notional_usd"] = 51
        write_json(self.pm_store.books_path(), pm)
        old_trader, old_pm = self.store.books_path().read_bytes(), self.pm_store.books_path().read_bytes()
        with self.assertRaises(EvidenceBoundaryError):
            self._restore()
        self.assertEqual(self.store.books_path().read_bytes(), old_trader)
        self.assertEqual(self.pm_store.books_path().read_bytes(), old_pm)

    def test_rejects_cross_session_assembly(self) -> None:
        from scripts.overnight.errors import EvidenceBoundaryError
        from scripts.overnight.store import write_json

        self._mark_stale_as_assembly_does()
        dataset = self.store.read_artifact(self.run_id, "assembled_dataset.json")
        dataset["overnight_run_id"] = "overnight-20260924"
        write_json(self.store.run_dir(self.run_id) / "assembled_dataset.json", dataset)
        with self.assertRaises(EvidenceBoundaryError):
            self._restore()


if __name__ == "__main__":
    unittest.main()
