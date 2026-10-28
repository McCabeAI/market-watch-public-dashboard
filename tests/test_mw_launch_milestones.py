"""Unit tests for launch publication milestones and acceptance gates."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.market_watch_launch.contract import (
    AWAITING_ACP,
    CONCURRENCY_BLOCK,
    PHASE_AWAITING_TRADER,
    PHASE_BLOCKED,
    PHASE_COLLECTING,
    PHASE_FAILED,
    PHASE_FINAL_PUBLISHED,
    PHASE_RESEARCH_PUBLISHING,
    PHASE_RESEARCH_READY,
    PHASE_SUPERSEDED,
    PHASE_TRADER_ACCEPTED,
    SUPERSEDED_BY_NEWER_FREEZE,
    TWO_TRIGGER_CONTRACT,
    empty_launch,
)
from scripts.market_watch_launch.milestones import (
    holds_data_collection_lock,
    launch_phase,
    mark_superseded_launches,
    research_publication,
    research_required,
    trader_acceptance_refusal,
)
from scripts.market_watch_launch.publication_release import (
    CHANNEL_PRODUCTION,
    PHASE_RESEARCH,
    RELEASE_SCHEMA_VERSION,
    RELEASE_TYPE,
    RESEARCH_RECEIPT_NAME,
    RESEARCH_RECEIPT_TYPE,
    release_sha256,
)
from scripts.market_watch_launch.research_pages import record_research_receipt
from scripts.market_watch_launch.state import LaunchStateStore
from scripts.overnight.store import write_json

REPO = Path(__file__).resolve().parents[1]


def _two_trigger_launch(launch_id: str, session_date: str = "2026-10-01") -> dict:
    launch = empty_launch(
        launch_id=launch_id,
        session_date=session_date,
        created_at="2026-10-01T10:00:00-04:00",
        request={
            "provider": "acp",
            "mode": "live",
            "publish_production": True,
            "session_date": session_date,
            "rerun": False,
            "source": "github_issue",
            "actor_type": "User",
            "actor": "user",
        },
    )
    launch["publication_contract"] = TWO_TRIGGER_CONTRACT
    return launch


def _freeze_details(packet: str = "a" * 64, review: str = "review-001") -> dict:
    return {
        "packet_sha256": packet,
        "review_id": review,
        "overnight_run_id": "overnight-20261001",
    }


def _research_release(launch: dict, packet: str, review: str) -> dict:
    return {
        "type": RELEASE_TYPE,
        "schema_version": RELEASE_SCHEMA_VERSION,
        "phase": PHASE_RESEARCH,
        "channel": CHANNEL_PRODUCTION,
        "launch_id": launch["launch_id"],
        "session_date": launch["session_date"],
        "review_id": review,
        "packet_sha256": packet,
        "overnight_run_id": "overnight-20261001",
    }


def _write_verified_receipt(root: Path, launch: dict, packet: str, review: str, run_id: str = "12345") -> None:
    store = LaunchStateStore(root)
    store.save_launch(launch)
    release = _research_release(launch, packet, review)
    record_research_receipt(
        root,
        release,
        deploy={
            "run_id": run_id,
            "run_url": "https://example.test/runs/1",
            "page_url": "https://example.test/",
            "public_state": "matched",
            "recorded_at": "2026-10-01T12:00:00Z",
        },
    )


class ResearchRequiredTests(unittest.TestCase):
    def test_two_trigger_live_acp_production(self) -> None:
        launch = _two_trigger_launch("mwl-20261001T100000Z-00000001")
        self.assertTrue(research_required(launch))

    def test_legacy_and_stub_skip(self) -> None:
        legacy = empty_launch(
            launch_id="mwl-20261001T100000Z-00000002",
            session_date="2026-10-01",
            created_at="2026-10-01T10:00:00-04:00",
            request={"provider": "acp", "mode": "live", "publish_production": True},
        )
        self.assertFalse(research_required(legacy))


class LaunchPhaseTests(unittest.TestCase):
    def test_phase_table(self) -> None:
        launch = _two_trigger_launch("mwl-20261001T100000Z-00000003")
        launch["status"] = "running"
        self.assertEqual(launch_phase(launch, research_verified=False), PHASE_COLLECTING)
        launch["stages"]["04_freeze"]["status"] = "succeeded"
        launch["stages"]["04_freeze"]["details"] = _freeze_details()
        self.assertEqual(launch_phase(launch, research_verified=False), PHASE_RESEARCH_PUBLISHING)
        self.assertEqual(launch_phase(launch, research_verified=True), PHASE_RESEARCH_READY)
        launch["stages"]["05_acp_handoff"]["status"] = "blocked"
        launch["stages"]["05_acp_handoff"]["reason"] = AWAITING_ACP
        self.assertEqual(launch_phase(launch, research_verified=False), PHASE_AWAITING_TRADER)
        self.assertEqual(launch_phase(launch, research_verified=True), PHASE_RESEARCH_READY)
        launch["stages"]["06_acceptance"]["status"] = "succeeded"
        self.assertEqual(launch_phase(launch, research_verified=False), PHASE_TRADER_ACCEPTED)
        launch["stages"]["08_pages"]["status"] = "succeeded"
        self.assertEqual(launch_phase(launch, research_verified=False), PHASE_FINAL_PUBLISHED)
        launch["status"] = "failed"
        launch["stages"]["06_acceptance"]["status"] = "pending"
        launch["stages"]["07_finalize"]["status"] = "pending"
        launch["stages"]["08_pages"]["status"] = "pending"
        self.assertEqual(launch_phase(launch, research_verified=False), PHASE_FAILED)
        launch = _two_trigger_launch("mwl-20261001T100000Z-00000004")
        launch["superseded_by"] = {"launch_id": "other"}
        self.assertEqual(launch_phase(launch, research_verified=False), PHASE_SUPERSEDED)
        blocked = empty_launch(
            launch_id="mwl-20261001T100000Z-00000005",
            session_date="2026-10-01",
            created_at="2026-10-01T10:00:00-04:00",
            request={},
        )
        blocked["status"] = "blocked"
        blocked["stages"]["00_authenticate"]["status"] = "blocked"
        blocked["stages"]["00_authenticate"]["reason"] = CONCURRENCY_BLOCK
        self.assertEqual(launch_phase(blocked, research_verified=False), PHASE_BLOCKED)
        legacy = empty_launch(
            launch_id="mwl-20261001T100000Z-00000006",
            session_date="2026-10-01",
            created_at="2026-10-01T10:00:00-04:00",
            request={"provider": "acp", "mode": "live", "publish_production": True},
        )
        legacy["stages"]["05_acp_handoff"]["status"] = "blocked"
        legacy["stages"]["05_acp_handoff"]["reason"] = AWAITING_ACP
        self.assertEqual(launch_phase(legacy, research_verified=False), PHASE_AWAITING_TRADER)


class DataCollectionLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_collecting_holds_same_day(self) -> None:
        launch = _two_trigger_launch("mwl-20261001T100000Z-00000010")
        launch["status"] = "running"
        launch["stages"]["01_ingest"]["status"] = "running"
        store = LaunchStateStore(self.root)
        store.save_launch(launch)
        self.assertTrue(
            holds_data_collection_lock(
                launch,
                launch_dir=store.launch_dir(launch["launch_id"]),
                today="2026-10-01",
            )
        )

    def test_research_publishing_holds_same_day(self) -> None:
        launch = _two_trigger_launch("mwl-20261001T100000Z-00000011")
        launch["status"] = "running"
        launch["stages"]["04_freeze"]["status"] = "succeeded"
        launch["stages"]["04_freeze"]["details"] = _freeze_details()
        store = LaunchStateStore(self.root)
        store.save_launch(launch)
        self.assertTrue(
            holds_data_collection_lock(
                launch,
                launch_dir=store.launch_dir(launch["launch_id"]),
                today="2026-10-01",
            )
        )

    def test_verified_receipt_releases(self) -> None:
        packet, review = "b" * 64, "review-002"
        launch = _two_trigger_launch("mwl-20261001T100000Z-00000012")
        launch["status"] = "running"
        launch["stages"]["04_freeze"]["status"] = "succeeded"
        launch["stages"]["04_freeze"]["details"] = _freeze_details(packet, review)
        _write_verified_receipt(self.root, launch, packet, review)
        launch = LaunchStateStore(self.root).load_launch(launch["launch_id"])
        store = LaunchStateStore(self.root)
        self.assertFalse(
            holds_data_collection_lock(
                launch,
                launch_dir=store.launch_dir(launch["launch_id"]),
                today="2026-10-01",
            )
        )

    def test_earlier_session_releases(self) -> None:
        launch = _two_trigger_launch("mwl-20261001T100000Z-00000013", session_date="2026-09-30")
        launch["status"] = "running"
        launch["stages"]["02_acquire"]["status"] = "running"
        store = LaunchStateStore(self.root)
        store.save_launch(launch)
        self.assertFalse(
            holds_data_collection_lock(
                launch,
                launch_dir=store.launch_dir(launch["launch_id"]),
                today="2026-10-01",
            )
        )

    def test_trader_accepted_does_not_hold(self) -> None:
        launch = _two_trigger_launch("mwl-20261001T100000Z-00000014")
        launch["status"] = "running"
        for name in ("04_freeze", "05_acp_handoff", "06_acceptance", "07_finalize"):
            launch["stages"][name]["status"] = "succeeded"
        launch["stages"]["04_freeze"]["details"] = _freeze_details()
        store = LaunchStateStore(self.root)
        store.save_launch(launch)
        self.assertFalse(
            holds_data_collection_lock(
                launch,
                launch_dir=store.launch_dir(launch["launch_id"]),
                today=None,
            )
        )


class ResearchPublicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _launch_on_disk(self, launch_id: str = "mwl-20261001T100000Z-00000020") -> dict:
        launch = _two_trigger_launch(launch_id)
        launch["status"] = "running"
        launch["stages"]["04_freeze"]["status"] = "succeeded"
        launch["stages"]["04_freeze"]["details"] = _freeze_details("c" * 64, "review-010")
        LaunchStateStore(self.root).save_launch(launch)
        return launch

    def test_positive_matched_row(self) -> None:
        launch = self._launch_on_disk()
        _write_verified_receipt(self.root, launch, "c" * 64, "review-010")
        pub = research_publication(LaunchStateStore(self.root).launch_dir(launch["launch_id"]), launch)
        self.assertIsNotNone(pub)
        self.assertEqual(pub["public_state"], "matched")
        self.assertEqual(pub["run_id"], 12345)

    def test_negative_cases(self) -> None:
        launch = self._launch_on_disk()
        store = LaunchStateStore(self.root)
        launch_dir = store.launch_dir(launch["launch_id"])
        self.assertIsNone(research_publication(launch_dir, launch))
        write_json(launch_dir / RESEARCH_RECEIPT_NAME, {"not": "json-object"})
        self.assertIsNone(research_publication(launch_dir, launch))
        bad = {"type": "wrong", "launch_id": launch["launch_id"]}
        (launch_dir / RESEARCH_RECEIPT_NAME).write_text(json.dumps(bad), encoding="utf-8")
        self.assertIsNone(research_publication(launch_dir, launch))
        release = _research_release(launch, "c" * 64, "review-010")
        receipt = {
            "type": RESEARCH_RECEIPT_TYPE,
            "launch_id": "other",
            "packet_sha256": "c" * 64,
            "review_id": "review-010",
            "release": release,
            "release_sha256": release_sha256(release),
            "deploys": [],
        }
        write_json(launch_dir / RESEARCH_RECEIPT_NAME, receipt)
        self.assertIsNone(research_publication(launch_dir, launch))
        receipt["launch_id"] = launch["launch_id"]
        receipt["packet_sha256"] = "d" * 64
        write_json(launch_dir / RESEARCH_RECEIPT_NAME, receipt)
        self.assertIsNone(research_publication(launch_dir, launch))
        receipt["packet_sha256"] = "c" * 64
        receipt["review_id"] = "review-999"
        write_json(launch_dir / RESEARCH_RECEIPT_NAME, receipt)
        self.assertIsNone(research_publication(launch_dir, launch))
        receipt["review_id"] = "review-010"
        receipt["release_sha256"] = "0" * 64
        write_json(launch_dir / RESEARCH_RECEIPT_NAME, receipt)
        self.assertIsNone(research_publication(launch_dir, launch))
        receipt["release_sha256"] = release_sha256(release)
        receipt["deploys"] = [{"run_id": "1", "public_state": "not_served:unreachable", "release_sha256": receipt["release_sha256"]}]
        write_json(launch_dir / RESEARCH_RECEIPT_NAME, receipt)
        self.assertIsNone(research_publication(launch_dir, launch))
        receipt["deploys"] = [{"run_id": "bad", "public_state": "matched", "release_sha256": receipt["release_sha256"]}]
        write_json(launch_dir / RESEARCH_RECEIPT_NAME, receipt)
        self.assertIsNone(research_publication(launch_dir, launch))


class TraderAcceptanceRefusalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = LaunchStateStore(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_happy_and_legacy(self) -> None:
        packet, review = "e" * 64, "review-020"
        launch = _two_trigger_launch("mwl-20261001T100000Z-00000030")
        launch["stages"]["04_freeze"]["status"] = "succeeded"
        launch["stages"]["04_freeze"]["details"] = _freeze_details(packet, review)
        launch["stages"]["05_acp_handoff"]["status"] = "blocked"
        launch["stages"]["05_acp_handoff"]["reason"] = AWAITING_ACP
        _write_verified_receipt(self.root, launch, packet, review)
        launch = self.store.load_launch(launch["launch_id"])
        pub = research_publication(self.store.launch_dir(launch["launch_id"]), launch)
        launch["stages"]["05_acp_handoff"]["details"] = {"research_publication": pub}
        self.store.save_launch(launch)
        self.assertIsNone(trader_acceptance_refusal(self.root, launch))
        legacy = empty_launch(
            launch_id="mwl-20261001T100000Z-00000031",
            session_date="2026-10-01",
            created_at="2026-10-01T10:00:00-04:00",
            request={"provider": "acp", "mode": "live", "publish_production": True},
        )
        legacy["stages"]["05_acp_handoff"]["status"] = "blocked"
        legacy["stages"]["05_acp_handoff"]["reason"] = AWAITING_ACP
        self.store.save_launch(legacy)
        self.assertIsNone(trader_acceptance_refusal(self.root, legacy))

    def test_refusals(self) -> None:
        launch = _two_trigger_launch("mwl-20261001T100000Z-00000032")
        launch["stages"]["04_freeze"]["status"] = "succeeded"
        launch["stages"]["04_freeze"]["details"] = _freeze_details()
        self.store.save_launch(launch)
        self.assertEqual(trader_acceptance_refusal(self.root, launch), "research_publication_not_verified")
        launch["superseded_by"] = {"launch_id": "newer"}
        self.assertEqual(trader_acceptance_refusal(self.root, launch), "superseded_by_newer_launch")
        newer = _two_trigger_launch("mwl-20261002T100000Z-00000033")
        newer["stages"]["04_freeze"]["status"] = "succeeded"
        newer["stages"]["04_freeze"]["details"] = _freeze_details()
        self.store.save_launch(newer)
        launch.pop("superseded_by")
        self.store.save_launch(launch)
        refusal = trader_acceptance_refusal(self.root, launch)
        self.assertTrue(refusal.startswith(SUPERSEDED_BY_NEWER_FREEZE))


class MarkSupersededTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = LaunchStateStore(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_marks_research_ready_older_only(self) -> None:
        older = _two_trigger_launch("mwl-20261001T100000Z-00000040")
        older["status"] = "running"
        older["stages"]["04_freeze"]["status"] = "succeeded"
        packet, review = "f" * 64, "review-040"
        older["stages"]["04_freeze"]["details"] = _freeze_details(packet, review)
        self.store.save_launch(older)
        _write_verified_receipt(self.root, older, packet, review)
        older = self.store.load_launch(older["launch_id"])
        newer = _two_trigger_launch("mwl-20261002T100000Z-00000041")
        newer["stages"]["04_freeze"]["status"] = "succeeded"
        newer["stages"]["04_freeze"]["details"] = _freeze_details("g" * 64, "review-041")
        self.store.save_launch(newer)
        marked = mark_superseded_launches(self.store, newer, when_iso="2026-10-02T10:00:00-04:00")
        self.assertEqual(marked, [older["launch_id"]])
        reloaded = self.store.load_launch(older["launch_id"])
        self.assertEqual(reloaded["status"], "running")
        self.assertEqual(reloaded["stages"]["04_freeze"]["status"], "succeeded")
        self.assertEqual(reloaded["superseded_by"]["reason"], "newer_launch_frozen")
        self.assertFalse(reloaded["superseded_by"]["trader_request_observed"])
        again = mark_superseded_launches(self.store, newer, when_iso="2026-10-02T10:00:00-04:00")
        self.assertEqual(again, [])
        legacy = empty_launch(
            launch_id="mwl-20260930T100000Z-00000042",
            session_date="2026-09-30",
            created_at="2026-09-30T10:00:00-04:00",
            request={},
        )
        legacy["status"] = "running"
        legacy["stages"]["04_freeze"]["status"] = "succeeded"
        self.store.save_launch(legacy)
        legacy_bytes = json.dumps(self.store.load_launch(legacy["launch_id"]), sort_keys=True)
        mark_superseded_launches(self.store, newer, when_iso="2026-10-02T10:00:00-04:00")
        self.assertEqual(json.dumps(self.store.load_launch(legacy["launch_id"]), sort_keys=True), legacy_bytes)


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_cli_exit_codes(self) -> None:
        launch = empty_launch(
            launch_id="mwl-20261001T100000Z-00000050",
            session_date="2026-10-01",
            created_at="2026-10-01T10:00:00-04:00",
            request={"provider": "acp", "mode": "live", "publish_production": True},
        )
        launch["stages"]["05_acp_handoff"]["status"] = "blocked"
        launch["stages"]["05_acp_handoff"]["reason"] = AWAITING_ACP
        LaunchStateStore(self.root).save_launch(launch)
        allowed = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.market_watch_launch.milestones",
                "acceptance-gate",
                "--launch-id",
                launch["launch_id"],
                "--root",
                str(self.root),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO),
            env={**os.environ, "PYTHONPATH": str(REPO)},
        )
        self.assertEqual(allowed.returncode, 0)
        phase = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.market_watch_launch.milestones",
                "phase",
                "--launch-id",
                launch["launch_id"],
                "--root",
                str(self.root),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO),
            env={**os.environ, "PYTHONPATH": str(REPO)},
        )
        self.assertEqual(phase.returncode, 0)
        self.assertIn(PHASE_AWAITING_TRADER, phase.stdout)


if __name__ == "__main__":
    unittest.main()
