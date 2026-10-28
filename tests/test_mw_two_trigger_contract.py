"""End-to-end two-trigger publication contract scenarios."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.market_watch_launch.contract import (
    AWAITING_ACP,
    AWAITING_RESEARCH_PUBLICATION,
    CONCURRENCY_BLOCK,
    PHASE_AWAITING_TRADER,
    PHASE_RESEARCH_READY,
    STAGES,
    TWO_TRIGGER_CONTRACT,
)
from scripts.market_watch_launch.durability import record_remote_freeze
from scripts.market_watch_launch.graph import default_handlers, run_launch, run_stage
from scripts.market_watch_launch.milestones import launch_phase, research_publication, trader_acceptance_refusal
from scripts.market_watch_launch.publication_release import (
    SUPERSEDED,
    final_release_for_launch,
    guard_publication,
)
from scripts.market_watch_launch.research_pages import record_research_receipt
from scripts.market_watch_launch.state import LaunchStateStore
from scripts.overnight.store import sha256_json, write_json

NY = ZoneInfo("America/New_York")
DAY_N = datetime(2026, 10, 20, 10, 0, tzinfo=NY)
DAY_N1 = datetime(2026, 10, 21, 10, 0, tzinfo=NY)
PACKET = "aa" * 32
REVIEW = "review-100"


def _success_receipt(stage: str, launch: dict, ctx: dict, extra: dict | None = None) -> dict:
    from scripts.market_watch_launch.contract import stage_receipt

    details = {"stage": stage, "launch_id": launch["launch_id"]}
    if extra:
        details.update(extra)
    prev_idx = STAGES.index(stage)
    input_sha = None
    if prev_idx > 0:
        prev = STAGES[prev_idx - 1]
        input_sha = launch["stages"][prev].get("output_sha256")
    return stage_receipt(
        stage,
        status="succeeded",
        input_sha256=input_sha,
        output_sha256=sha256_json(details),
        details=details,
    )


class TwoTriggerContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.calls: list[str] = []

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _handlers(self, **overrides):
        def make(stage: str):
            def _handler(launch, ctx):
                self.calls.append(stage)
                if overrides.get(stage):
                    return overrides[stage](launch, ctx)
                if stage == "04_freeze":
                    return _success_receipt(
                        stage,
                        launch,
                        ctx,
                        {
                            "packet_sha256": PACKET,
                            "review_id": REVIEW,
                            "overnight_run_id": "overnight-20261020",
                        },
                    )
                return _success_receipt(stage, launch, ctx)

            return _handler

        handlers = dict(default_handlers())
        for stage in ("01_ingest", "02_acquire", "03_quality_gate", "04_freeze"):
            handlers[stage] = make(stage)
        handlers.update({k: v for k, v in overrides.items() if callable(v)})
        return handlers

    def _request(self, session_date: str = "2026-10-20", **kwargs) -> dict:
        base = {
            "session_date": session_date,
            "rerun": False,
            "mode": "live",
            "provider": "acp",
            "publish_production": True,
            "source": "github_issue",
            "actor_type": "User",
            "actor": "kevin",
            "issue_number": 1,
            "issue_url": "https://github.com/example/issues/1",
            "repository_permission": "admin",
        }
        base.update(kwargs)
        return base

    def _remote_freeze(self, launch_id: str) -> None:
        store = LaunchStateStore(self.root)
        launch_dir = store.launch_dir(launch_id)
        record_remote_freeze(
            launch_dir,
            commit_sha="c" * 40,
            packet_sha256=PACKET,
            trader_books_sha256="t" * 64,
            pm_books_sha256="p" * 64,
            score_state_sha256="s" * 64,
        )
        write_json(
            launch_dir / "freeze_binding.json",
            {"packet_sha256": PACKET, "review_id": REVIEW},
        )

    def _verified_receipt(self, launch: dict, run_id: str = "90001") -> None:
        from scripts.market_watch_launch.publication_release import (
            CHANNEL_PRODUCTION,
            PHASE_RESEARCH,
            RELEASE_SCHEMA_VERSION,
            RELEASE_TYPE,
        )

        release = {
            "type": RELEASE_TYPE,
            "schema_version": RELEASE_SCHEMA_VERSION,
            "phase": PHASE_RESEARCH,
            "channel": CHANNEL_PRODUCTION,
            "launch_id": launch["launch_id"],
            "session_date": launch["session_date"],
            "review_id": REVIEW,
            "packet_sha256": PACKET,
            "overnight_run_id": "overnight-20261020",
        }
        record_research_receipt(
            self.root,
            release,
            deploy={
                "run_id": run_id,
                "run_url": "https://example.test/r/1",
                "page_url": "https://example.test/",
                "public_state": "matched",
                "recorded_at": "2026-10-20T12:00:00Z",
            },
        )

    def test_trigger_a_day_n_happy_path(self) -> None:
        handlers = self._handlers()
        first = run_launch(
            self._request(),
            root=self.root,
            state_root=self.root,
            handlers=handlers,
            when=DAY_N,
            through="04_freeze",
        )
        launch = first["launch"]
        self.assertEqual(launch.get("publication_contract"), TWO_TRIGGER_CONTRACT)
        self.assertIsNotNone(LaunchStateStore(self.root).data_collection_holder("2026-10-20"))
        dup = run_launch(self._request(), root=self.root, state_root=self.root, handlers=handlers, when=DAY_N)
        self.assertTrue(dup["returned_existing"])
        self.assertEqual(dup["launch_id"], first["launch_id"])
        day_n_id = first["launch_id"]
        rerun = run_launch(
            self._request(rerun=True),
            root=self.root,
            state_root=self.root,
            handlers=handlers,
            when=DAY_N.replace(minute=DAY_N.minute + 1),
        )
        self.assertNotEqual(rerun["launch_id"], day_n_id)
        self.assertEqual(rerun["launch"]["stages"]["00_authenticate"]["reason"], CONCURRENCY_BLOCK)
        self._remote_freeze(day_n_id)
        stage05 = run_stage(
            day_n_id,
            "05_acp_handoff",
            root=self.root,
            state_root=self.root,
            handlers=handlers,
            when=DAY_N,
        )
        handoff = stage05["launch"]["stages"]["05_acp_handoff"]
        self.assertEqual(handoff["status"], "pending")
        self.assertEqual(handoff["reason"], AWAITING_RESEARCH_PUBLICATION)
        launch_dir = LaunchStateStore(self.root).launch_dir(day_n_id)
        self.assertFalse((launch_dir / "acp_one_shot_delegation_request.json").is_file())
        launch = stage05["launch"]
        launch["review_id"] = REVIEW
        launch["base_packet_sha256"] = PACKET
        LaunchStateStore(self.root).save_launch(launch)
        self._verified_receipt(launch)
        stage05b = run_stage(
            day_n_id,
            "05_acp_handoff",
            root=self.root,
            state_root=self.root,
            handlers=handlers,
            when=DAY_N,
        )
        handoff = stage05b["launch"]["stages"]["05_acp_handoff"]
        self.assertEqual(handoff["status"], "blocked")
        self.assertEqual(handoff["reason"], AWAITING_ACP)
        self.assertTrue((LaunchStateStore(self.root).launch_dir(day_n_id) / "acp_one_shot_delegation_request.json").is_file())
        self.assertEqual(handoff["details"]["live_model_calls"], 0)
        self.assertFalse(handoff["details"]["live_provider_dispatched"])
        pub = research_publication(LaunchStateStore(self.root).launch_dir(launch["launch_id"]), stage05b["launch"])
        self.assertEqual(
            launch_phase(stage05b["launch"], research_verified=pub is not None),
            PHASE_RESEARCH_READY,
        )
        index = LaunchStateStore(self.root)._read_index()
        self.assertIsNone(index["live_launch_id"])
        self.calls.clear()
        wait = run_launch(self._request(), root=self.root, state_root=self.root, handlers=handlers, when=DAY_N)
        self.assertTrue(wait["returned_existing"])
        self.assertEqual(self.calls, [])

    def test_next_day_supersedes_without_trader_b(self) -> None:
        handlers = self._handlers()
        first = run_launch(
            self._request(),
            root=self.root,
            state_root=self.root,
            handlers=handlers,
            when=DAY_N,
            through="04_freeze",
        )
        day_n_id = first["launch_id"]
        self._remote_freeze(day_n_id)
        self._verified_receipt(first["launch"])
        run_stage(day_n_id, "05_acp_handoff", root=self.root, state_root=self.root, handlers=handlers, when=DAY_N)
        n1 = run_launch(
            self._request(session_date="2026-10-21"),
            root=self.root,
            state_root=self.root,
            handlers=handlers,
            when=DAY_N1,
            through="04_freeze",
        )
        self.assertNotEqual(n1["status"], "blocked")
        old = LaunchStateStore(self.root).load_launch(day_n_id)
        self.assertIn("superseded_by", old)
        self.assertEqual(old["superseded_by"]["reason"], "newer_launch_frozen")
        self.assertFalse(old["superseded_by"]["trader_request_observed"])
        self.assertIn(old["status"], ("running", "blocked"))
        refusal = trader_acceptance_refusal(self.root, old)
        self.assertEqual(refusal, "superseded_by_newer_launch")

    def test_continuation_refuses_superseded_and_unverified_without_acceptance(self) -> None:
        from unittest import mock

        from scripts.market_watch_launch import continuation

        handlers = self._handlers()
        first = run_launch(
            self._request(), root=self.root, state_root=self.root, handlers=handlers, when=DAY_N, through="04_freeze"
        )
        day_n_id = first["launch_id"]
        self._remote_freeze(day_n_id)
        payload = {"launch_id": day_n_id, "review_id": REVIEW, "base_packet_sha256": PACKET}
        ctx = {"root": self.root, "state_root": self.root, "provider_payload": payload}

        with mock.patch.object(continuation, "acceptance_run") as acceptance:
            unverified = continuation.continue_accepted_launch(
                LaunchStateStore(self.root).load_launch(day_n_id), dict(ctx)
            )
            self.assertEqual(unverified["status"], "blocked")
            self.assertEqual(unverified["reason"], "research_publication_not_verified")

            self._verified_receipt(first["launch"])
            run_stage(day_n_id, "05_acp_handoff", root=self.root, state_root=self.root, handlers=handlers, when=DAY_N)
            run_launch(
                self._request(session_date="2026-10-21"),
                root=self.root,
                state_root=self.root,
                handlers=handlers,
                when=DAY_N1,
                through="04_freeze",
            )
            stale = continuation.continue_accepted_launch(LaunchStateStore(self.root).load_launch(day_n_id), dict(ctx))
            self.assertEqual(stale["status"], "blocked")
            self.assertEqual(stale["reason"], "superseded_by_newer_launch")
            self.assertFalse(stale["production_published"])
            acceptance.assert_not_called()
        old = LaunchStateStore(self.root).load_launch(day_n_id)
        self.assertEqual(old["stages"]["06_acceptance"]["status"], "pending")
        self.assertNotEqual(old["stages"]["05_acp_handoff"]["status"], "succeeded")

    def test_unverified_research_blocks_trader_and_next_day_allowed(self) -> None:
        handlers = self._handlers()
        first = run_launch(
            self._request(),
            root=self.root,
            state_root=self.root,
            handlers=handlers,
            when=DAY_N,
            through="04_freeze",
        )
        launch_id = first["launch_id"]
        self._remote_freeze(launch_id)
        from scripts.market_watch_launch.publication_release import (
            CHANNEL_PRODUCTION,
            PHASE_RESEARCH,
            RELEASE_SCHEMA_VERSION,
            RELEASE_TYPE,
            release_sha256,
        )

        release = {
            "type": RELEASE_TYPE,
            "schema_version": RELEASE_SCHEMA_VERSION,
            "phase": PHASE_RESEARCH,
            "channel": CHANNEL_PRODUCTION,
            "launch_id": launch_id,
            "session_date": "2026-10-20",
            "review_id": REVIEW,
            "packet_sha256": PACKET,
            "overnight_run_id": "overnight-20261020",
        }
        rel_sha = release_sha256(release)
        receipt = {
            "type": "MARKET_WATCH_RESEARCH_PUBLICATION",
            "launch_id": launch_id,
            "packet_sha256": PACKET,
            "review_id": REVIEW,
            "release": release,
            "release_sha256": rel_sha,
            "deploys": [
                {
                    "run_id": "1",
                    "public_state": "not_served:unreachable",
                    "release_sha256": rel_sha,
                }
            ],
        }
        path = LaunchStateStore(self.root).launch_dir(launch_id) / "research_pages.json"
        path.write_text(json.dumps(receipt), encoding="utf-8")
        run_stage(launch_id, "05_acp_handoff", root=self.root, state_root=self.root, handlers=handlers, when=DAY_N)
        launch = LaunchStateStore(self.root).load_launch(launch_id)
        self.assertEqual(launch["stages"]["05_acp_handoff"]["status"], "pending")
        self.assertEqual(trader_acceptance_refusal(self.root, launch), "research_publication_not_verified")
        rerun = run_launch(
            self._request(rerun=True),
            root=self.root,
            state_root=self.root,
            handlers=handlers,
            when=DAY_N.replace(minute=DAY_N.minute + 1),
        )
        self.assertEqual(rerun["launch"]["stages"]["00_authenticate"]["reason"], CONCURRENCY_BLOCK)
        n1 = run_launch(
            self._request(session_date="2026-10-21"),
            root=self.root,
            state_root=self.root,
            handlers=handlers,
            when=DAY_N1,
            through="00_authenticate",
        )
        self.assertEqual(n1["launch"]["stages"]["00_authenticate"]["status"], "succeeded")

    def test_trader_allowed_before_newer_freeze(self) -> None:
        handlers = self._handlers()
        first = run_launch(
            self._request(),
            root=self.root,
            state_root=self.root,
            handlers=handlers,
            when=DAY_N,
            through="04_freeze",
        )
        launch_id = first["launch_id"]
        self._remote_freeze(launch_id)
        self._verified_receipt(first["launch"])
        run_stage(launch_id, "05_acp_handoff", root=self.root, state_root=self.root, handlers=handlers, when=DAY_N)
        launch = LaunchStateStore(self.root).load_launch(launch_id)
        self.assertIsNone(trader_acceptance_refusal(self.root, launch))

    def test_publication_ordering_research_vs_final(self) -> None:
        handlers = self._handlers()
        day_n = run_launch(
            self._request(),
            root=self.root,
            state_root=self.root,
            handlers=handlers,
            when=DAY_N,
            through="04_freeze",
        )
        n_id = day_n["launch_id"]
        self._remote_freeze(n_id)
        self._verified_receipt(day_n["launch"])
        run_stage(n_id, "05_acp_handoff", root=self.root, state_root=self.root, handlers=handlers, when=DAY_N)
        n1 = run_launch(
            self._request(session_date="2026-10-21"),
            root=self.root,
            state_root=self.root,
            handlers=handlers,
            when=DAY_N1,
            through="04_freeze",
        )
        n1_id = n1["launch_id"]
        launch_n1 = LaunchStateStore(self.root).load_launch(n1_id)
        self._verified_receipt(launch_n1, run_id="90002")
        launch_n = LaunchStateStore(self.root).load_launch(n_id)
        launch_n["stages"]["06_acceptance"]["status"] = "succeeded"
        launch_n["stages"]["07_finalize"]["status"] = "succeeded"
        launch_n["stages"]["04_freeze"]["details"] = {
            "packet_sha256": PACKET,
            "review_id": REVIEW,
            "overnight_run_id": "overnight-20261020",
        }
        decision = guard_publication(final_release_for_launch(launch_n), root=self.root)
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["reason"], SUPERSEDED)
        launch_n1["stages"]["06_acceptance"]["status"] = "succeeded"
        launch_n1["stages"]["07_finalize"]["status"] = "succeeded"
        launch_n1["stages"]["04_freeze"]["details"] = {
            "packet_sha256": PACKET,
            "review_id": REVIEW,
            "overnight_run_id": "overnight-20261021",
        }
        decision_ok = guard_publication(final_release_for_launch(launch_n1), root=self.root)
        self.assertTrue(decision_ok["allowed"])

    def test_legacy_compatibility(self) -> None:
        from scripts.market_watch_launch.contract import empty_launch
        from scripts.market_watch_launch.milestones import holds_data_collection_lock

        store = LaunchStateStore(self.root)

        legacy_launch = empty_launch(
            launch_id="mwl-20261001T100000Z-legacy01",
            session_date="2026-10-01",
            created_at="2026-10-01T10:00:00-04:00",
            request={
                "provider": "acp",
                "mode": "live",
                "publish_production": True,
                "source": "github_issue",
                "actor_type": "User",
                "actor": "kevin",
            },
        )
        legacy_launch["status"] = "running"
        legacy_launch["stages"]["05_acp_handoff"]["status"] = "blocked"
        legacy_launch["stages"]["05_acp_handoff"]["reason"] = AWAITING_ACP
        store.save_launch(legacy_launch)
        self.assertEqual(
            launch_phase(legacy_launch, research_verified=False),
            PHASE_AWAITING_TRADER,
        )
        self.assertFalse(
            holds_data_collection_lock(
                legacy_launch,
                launch_dir=store.launch_dir(legacy_launch["launch_id"]),
                today=None,
            )
        )
        self.assertIsNone(trader_acceptance_refusal(self.root, legacy_launch))
        stuck = empty_launch(
            launch_id="mwl-20261027T100000Z-legacy02",
            session_date="2026-10-27",
            created_at="2026-10-27T10:00:00-04:00",
            request={"provider": "acp", "mode": "live", "publish_production": True},
        )
        stuck["status"] = "running"
        for stage in ("04_freeze", "05_acp_handoff", "06_acceptance", "07_finalize"):
            stuck["stages"][stage]["status"] = "succeeded"
        store.save_launch(stuck)
        nxt = run_launch(
            self._request(session_date="2026-10-28"),
            root=self.root,
            state_root=self.root,
            handlers=self._handlers(),
            when=datetime(2026, 10, 28, 10, 0, tzinfo=NY),
            through="00_authenticate",
        )
        self.assertEqual(nxt["launch"]["stages"]["00_authenticate"]["status"], "succeeded")

    def test_failure_injection_stages_01_to_04(self) -> None:
        for stage_name in ("01_ingest", "02_acquire", "03_quality_gate", "04_freeze"):
            self.calls.clear()
            root = Path(tempfile.mkdtemp())
            try:

                def fail(_launch, _ctx):
                    raise RuntimeError(f"fail at {stage_name}")

                handlers = self._handlers()
                handlers[stage_name] = fail
                result = run_launch(
                    self._request(),
                    root=root,
                    state_root=root,
                    handlers=handlers,
                    when=DAY_N,
                )
                self.assertEqual(result["status"], "failed")
                store = LaunchStateStore(root)
                self.assertIsNone(store.data_collection_holder(None))
                launch = store.load_launch(result["launch_id"])
                self.assertEqual(launch["stages"]["05_acp_handoff"]["status"], "pending")
            finally:
                import shutil

                shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
