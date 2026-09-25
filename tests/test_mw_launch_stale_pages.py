"""Sep 24 shape: stages 00–07 succeeded, stage 08 still pending.

A proven Pages deploy must terminal the launch without replaying traders, PMs,
or provider output, and the next session must authenticate.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.market_watch_launch.contract import CONCURRENCY_BLOCK, STAGES, empty_launch
from scripts.market_watch_launch.graph import run_launch
from scripts.market_watch_launch.pages import reconcile_published_pages
from scripts.market_watch_launch.state import LaunchStateStore
from scripts.overnight.store import sha256_json

NY = ZoneInfo("America/New_York")
SEP24 = "mwl-20260924T100633Z-e5b861a6"
SEP25_WHEN = datetime(2026, 9, 25, 7, 1, 0, tzinfo=NY)
PACKET = "36e3ba51622fba76a7f8474b02efc8b45e7fb8227af680d4926496a86787df63"
HEAD_SHA = "4738349560d675adb3b6f7479fa88c87cdfac74e"
RUN_URL = "https://github.com/McCabeAI/market-watch-public-dashboard/actions/runs/35999721201"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stage(name: str, *, status: str, reason: str | None = None, details: dict | None = None) -> dict:
    row = {
        "stage": name,
        "status": status,
        "input_sha256": PACKET if name != "00_authenticate" else None,
        "output_sha256": PACKET if status == "succeeded" else None,
        "started_at": "2026-09-24T06:06:33.355500-04:00",
        "finished_at": "2026-09-24T08:32:36.000000-04:00" if status == "succeeded" else None,
        "reason": reason,
        "source_run_url": None,
        "artifact": None,
        "details": details or {},
    }
    return row


def _sep24_launch() -> dict:
    request = {
        "actor": "example-user",
        "actor_type": "User",
        "issue_number": 116,
        "mode": "live",
        "provider": "acp",
        "publish_production": True,
        "repository_permission": "admin",
        "rerun": True,
        "session_date": "2026-09-24",
        "source": "github_issue",
    }
    launch = empty_launch(
        launch_id=SEP24,
        session_date="2026-09-24",
        created_at="2026-09-24T06:06:33.355500-04:00",
        request=request,
    )
    launch["review_id"] = "review-001"
    launch["overnight_run_id"] = "overnight-20260924"
    launch["base_packet_sha256"] = PACKET
    launch["starting_trader_books_sha256"] = "a" * 64
    launch["starting_pm_books_sha256"] = "b" * 64
    launch["status"] = "running"
    launch["rerun"] = True
    for name in STAGES:
        if name == "05_acp_handoff":
            launch["stages"][name] = _stage(
                name,
                status="succeeded",
                reason="provider_output_accepted",
                details={"provider_output_accepted": True, "live_provider_dispatched": True},
            )
        elif name == "06_acceptance":
            launch["stages"][name] = _stage(
                name,
                status="succeeded",
                details={"review_id": "review-001", "applied": True, "launch_id": SEP24},
            )
        elif name == "07_finalize":
            launch["stages"][name] = _stage(
                name,
                status="succeeded",
                details={
                    "launch_id": SEP24,
                    "review_id": "review-001",
                    "packet_sha256": PACKET,
                    "publication": {
                        "core_status": "ok",
                        "may_publish": True,
                        "reason": "core inputs are structurally valid",
                    },
                },
            )
        elif name == "08_pages":
            launch["stages"][name] = _stage(name, status="pending")
        else:
            launch["stages"][name] = _stage(name, status="succeeded")
    return launch


def _evidence(launch: dict) -> dict:
    return {
        "workflow": "deploy-pages.yml",
        "event": "workflow_dispatch",
        "ref": "main",
        "conclusion": "success",
        "launch_id": launch["launch_id"],
        "head_sha": HEAD_SHA,
        "run_url": RUN_URL,
        "finalized_launch": json.loads(json.dumps(launch)),
    }


def _success_handlers():
    from scripts.market_watch_launch.contract import stage_receipt

    def make(stage: str):
        def _handler(launch, ctx):
            _ = ctx
            details = {"stage": stage, "launch_id": launch["launch_id"]}
            return stage_receipt(
                stage,
                status="succeeded",
                input_sha256=None,
                output_sha256=sha256_json(details),
                details=details,
            )

        return _handler

    return {stage: make(stage) for stage in STAGES}


class StalePagesReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.state_root = Path(self.tmp.name)
        self.books = self.state_root / "books"
        self.books.mkdir()
        self.trader_book = self.books / "trader.json"
        self.pm_book = self.books / "pm.json"
        self.journal = self.books / "journal.json"
        self.provider_output = self.books / "provider_output.json"
        self.trader_book.write_text('{"seat":"value-guy","pnl":1}\n', encoding="utf-8")
        self.pm_book.write_text('{"pm":"grinder","pnl":2}\n', encoding="utf-8")
        self.journal.write_text('{"review_id":"review-001"}\n', encoding="utf-8")
        self.provider_output.write_text('{"status":"accepted"}\n', encoding="utf-8")
        self.before = {path: _sha256_file(path) for path in (self.trader_book, self.pm_book, self.journal, self.provider_output)}
        store = LaunchStateStore(self.state_root)
        self.launch = _sep24_launch()
        store.save_launch(self.launch)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _digests(self) -> dict[Path, str]:
        return {path: _sha256_file(path) for path in self.before}

    def test_unproven_pages_stay_live_and_block_the_next_day(self) -> None:
        store = LaunchStateStore(self.state_root)
        receipt = reconcile_published_pages(self.launch, None, store=store)
        self.assertEqual(receipt["status"], "blocked")
        self.assertEqual(receipt["reason"], "pages_publication_not_proven")
        reloaded = store.load_launch(SEP24)
        self.assertEqual(reloaded["status"], "running")
        self.assertEqual(reloaded["stages"]["08_pages"]["status"], "pending")
        nxt = run_launch(
            {
                "session_date": "2026-09-25",
                "rerun": False,
                "mode": "fixture",
                "provider": "stub",
                "source": "workflow_dispatch",
                "actor_type": "User",
                "actor": "example-user",
            },
            root=self.state_root,
            state_root=self.state_root,
            handlers=_success_handlers(),
            when=SEP25_WHEN,
        )
        self.assertEqual(nxt["status"], "blocked")
        self.assertEqual(nxt["launch"]["stages"]["00_authenticate"]["reason"], CONCURRENCY_BLOCK)
        self.assertEqual(self._digests(), self.before)

    def test_proven_pages_deploy_terminals_prior_launch_and_authenticates_next_day(self) -> None:
        store = LaunchStateStore(self.state_root)
        receipt = reconcile_published_pages(self.launch, _evidence(self.launch), store=store)
        self.assertEqual(receipt["status"], "succeeded")
        self.assertEqual(receipt["reason"], "pages_publication_reconciled")
        self.assertTrue(receipt["details"]["production_published"])
        reloaded = store.load_launch(SEP24)
        self.assertEqual(reloaded["status"], "succeeded")
        self.assertEqual(reloaded["stages"]["08_pages"]["status"], "succeeded")
        self.assertEqual(reloaded["stages"]["05_acp_handoff"]["reason"], "provider_output_accepted")
        self.assertEqual(reloaded["stages"]["06_acceptance"]["details"]["review_id"], "review-001")
        self.assertEqual(reloaded["review_id"], "review-001")
        self.assertEqual(reloaded["base_packet_sha256"], PACKET)
        self.assertIsNone(store.live_launch())
        _, digest = store.reread_artifact(SEP24, "08_pages")
        self.assertEqual(digest, reloaded["stages"]["08_pages"]["output_sha256"])

        nxt = run_launch(
            {
                "session_date": "2026-09-25",
                "rerun": False,
                "mode": "fixture",
                "provider": "stub",
                "source": "github_issue",
                "actor_type": "User",
                "actor": "example-user",
                "issue_number": 123,
                "issue_url": "https://github.com/example/issues/123",
                "repository_permission": "admin",
            },
            root=self.state_root,
            state_root=self.state_root,
            handlers=_success_handlers(),
            when=SEP25_WHEN,
        )
        self.assertNotEqual(nxt["status"], "blocked")
        self.assertEqual(nxt["launch"]["stages"]["00_authenticate"]["status"], "succeeded")
        self.assertNotEqual(nxt["launch"]["stages"]["00_authenticate"]["reason"], CONCURRENCY_BLOCK)
        self.assertEqual(self._digests(), self.before)

    def test_stale_concurrency_block_does_not_stick_after_reconciliation(self) -> None:
        store = LaunchStateStore(self.state_root)
        blocked = empty_launch(
            launch_id="mwl-20260925T110100Z-a665a459",
            session_date="2026-09-25",
            created_at="2026-09-25T07:01:00.822340-04:00",
            request={
                "session_date": "2026-09-25",
                "rerun": False,
                "mode": "live",
                "provider": "acp",
                "source": "github_issue",
                "actor_type": "User",
                "actor": "example-user",
            },
        )
        blocked["status"] = "blocked"
        blocked["stages"]["00_authenticate"]["status"] = "blocked"
        blocked["stages"]["00_authenticate"]["reason"] = CONCURRENCY_BLOCK
        blocked["stages"]["00_authenticate"]["details"] = {"blocked_by_launch_id": SEP24}
        store.save_launch(blocked)

        reconcile_published_pages(self.launch, _evidence(self.launch), store=store)
        nxt = run_launch(
            {
                "session_date": "2026-09-25",
                "rerun": False,
                "mode": "fixture",
                "provider": "stub",
                "source": "github_issue",
                "actor_type": "User",
                "actor": "example-user",
                "issue_number": 123,
                "issue_url": "https://github.com/example/issues/123",
                "repository_permission": "admin",
            },
            root=self.state_root,
            state_root=self.state_root,
            handlers=_success_handlers(),
            when=datetime(2026, 9, 25, 7, 5, 0, tzinfo=NY),
        )
        self.assertEqual(nxt["launch"]["stages"]["00_authenticate"]["status"], "succeeded")
        self.assertNotEqual(nxt["launch"]["stages"]["00_authenticate"]["reason"], CONCURRENCY_BLOCK)
        self.assertNotEqual(nxt["launch_id"], blocked["launch_id"])
        preserved = store.load_launch(blocked["launch_id"])
        self.assertEqual(preserved["status"], "blocked")
        self.assertEqual(preserved["stages"]["00_authenticate"]["reason"], CONCURRENCY_BLOCK)
        self.assertEqual(self._digests(), self.before)

class PagesPersistenceWorkflowTests(unittest.TestCase):
    def test_pages_step_stages_launch_index_before_rebase(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "overnight-scheduled-output.yml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'git add "data/market_watch_launches/$launch_id" "data/market_watch_launches/index.json"',
            workflow,
        )

