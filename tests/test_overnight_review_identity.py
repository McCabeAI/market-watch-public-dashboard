"""Review identity is immutable inside a daily overnight session."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from scripts.overnight.constants import ROOT
from scripts.overnight.errors import EvidenceBoundaryError
from scripts.overnight.evidence import freeze_snapshot
from scripts.overnight.migrate_reviews import (
    MORNING_PACKET,
    MORNING_REVIEW,
    REFRESH_PACKET,
    REFRESH_REVIEW,
    SESSION_ID,
    migrate_sep22,
)
from scripts.overnight.pipeline import dry_run, run_stage
from scripts.overnight.scheduled_output import apply_output
from scripts.overnight.store import OvernightStore, sha256_file
from scripts.trading.store import TradingStore
from tests.test_overnight_scheduled_output import AS_OF, ScheduledOutputTests

FIXTURE = ROOT / "data" / "overnight" / "fixtures" / "market_state.json"


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReviewIdentityTests(ScheduledOutputTests):
    def _stage_through_freeze(self, run_id: str, when: datetime) -> dict:
        for stage in ("collect", "pre_trader_delta", "freeze_evidence"):
            run_stage(
                stage,
                root=ROOT,
                state_root=self.state_root,
                run_id=run_id,
                when=when,
                dry_run=True,
                market_state_path=FIXTURE,
            )
        return self.store.read_artifact(run_id, "evidence_snapshot.json")

    def _payload_for(self, base: dict, *, thesis: str) -> dict:
        payload = deepcopy(self.payload)
        payload["overnight_run_id"] = base["overnight_run_id"]
        payload["review_id"] = base["review_id"]
        payload["base_packet_sha256"] = base["packet_sha256"]
        packet = payload["agent_packet"]
        packet["overnight_run_id"] = base["overnight_run_id"]
        packet["review_id"] = base["review_id"]
        packet["base_packet_sha256"] = base["packet_sha256"]
        packet["base_evidence_cutoff"] = base["as_of"]
        packet["competition"] = base["competition"]
        packet.pop("packet_sha256", None)
        from scripts.overnight.store import sha256_json

        packet["packet_sha256"] = sha256_json(packet)
        payload["base_packet_sha256"] = base["packet_sha256"]
        for seat, decision in payload["decisions"].items():
            decision["overnight_run_id"] = base["overnight_run_id"]
            decision["review_id"] = base["review_id"]
            decision["packet_sha256"] = packet["packet_sha256"]
            decision["evidence_cutoff"] = packet["evidence_cutoff"]
            decision["thesis"] = thesis
            if seat in (base.get("seat_memory") or {}).get("hashes") or {}:
                decision["memory_context_sha256"] = base["seat_memory"]["hashes"][seat]
        for pm_id, decision in payload["pm_decisions"].items():
            decision["overnight_run_id"] = base["overnight_run_id"]
            decision["review_id"] = base["review_id"]
            decision["packet_sha256"] = packet["packet_sha256"]
            decision["evidence_cutoff"] = packet["evidence_cutoff"]
            decision["thesis"] = thesis
            hashes = (base.get("pm_memory") or {}).get("hashes") or {}
            if pm_id in hashes:
                decision["memory_context_sha256"] = hashes[pm_id]
        return payload

    def test_two_reviews_persist_and_replay_is_a_noop(self) -> None:
        run_id = "overnight-20260918"
        first = self.store.read_artifact(run_id, "evidence_snapshot.json", review_id="review-001")
        self.assertEqual(first["review_id"], "review-001")
        self.assertEqual(first["overnight_run_id"], run_id)
        before = sha256_file(self.store.books_path())
        first_payload = self._payload_for(first, thesis="First cycle holds.")
        first_review = apply_output(self.store, first_payload)
        self.assertEqual(first_review["review_id"], "review-001")
        self.assertEqual(first_review["status"], "succeeded")
        after_first = sha256_file(self.store.books_path())
        self.assertNotEqual(after_first, before)

        second_packet = freeze_snapshot(self.store, run_id=run_id, when=AS_OF, reuse_open=False)
        self.assertEqual(second_packet["review_id"], "review-002")
        self.assertNotEqual(second_packet["packet_sha256"], first["packet_sha256"])
        self.assertEqual(second_packet["starting_trader_books_sha256"], after_first)
        second_payload = self._payload_for(second_packet, thesis="Second cycle still holds.")
        second_review = apply_output(self.store, second_payload)
        self.assertEqual(second_review["review_id"], "review-002")
        after_second = sha256_file(self.store.books_path())
        self.assertNotEqual(after_second, after_first)

        first_dir = self.store.review_dir(run_id, "review-001")
        second_dir = self.store.review_dir(run_id, "review-002")
        self.assertTrue((first_dir / "evidence_snapshot.json").is_file())
        self.assertTrue((second_dir / "evidence_snapshot.json").is_file())
        self.assertTrue((first_dir / "scheduled_output.json").is_file())
        self.assertTrue((second_dir / "scheduled_output.json").is_file())
        self.assertNotEqual(
            self.store.read_artifact(run_id, "evidence_snapshot.json", review_id="review-001")["packet_sha256"],
            self.store.read_artifact(run_id, "evidence_snapshot.json", review_id="review-002")["packet_sha256"],
        )
        self.assertEqual(
            self.store.read_artifact(run_id, "evidence_snapshot.json", review_id="review-001")["packet_sha256"],
            first["packet_sha256"],
        )

        replay = apply_output(self.store, second_payload)
        self.assertEqual(replay["review_id"], "review-002")
        self.assertEqual(sha256_file(self.store.books_path()), after_second)
        trading = TradingStore(root=ROOT, state_root=self.state_root)
        events = [
            event
            for event in trading.read_journal("trader", "dollar-king")["events"]
            if event.get("kind") == "OVERNIGHT_DECISION"
        ]
        review_ids = [event["provenance"]["review_id"] for event in events]
        self.assertEqual(review_ids, ["review-001", "review-002"])
        self.assertTrue(all(event["provenance"]["overnight_run_id"] == run_id for event in events))

    def test_out_of_order_acceptance_fails_closed(self) -> None:
        run_id = "overnight-20260918"
        first = self.store.read_artifact(run_id, "evidence_snapshot.json", review_id="review-001")
        second_packet = freeze_snapshot(self.store, run_id=run_id, when=AS_OF, reuse_open=False)
        self.assertEqual(second_packet["review_id"], "review-002")
        second_payload = self._payload_for(second_packet, thesis="Later review is accepted first.")
        apply_output(self.store, second_payload)
        books_after = sha256_file(self.store.books_path())
        pm_after = sha256_file(self.state_root / "data" / "pm" / "books" / "latest.json")
        stale = self._payload_for(first, thesis="Stale earlier review must not apply.")
        with self.assertRaises(EvidenceBoundaryError):
            apply_output(self.store, stale)
        self.assertEqual(sha256_file(self.store.books_path()), books_after)
        self.assertEqual(sha256_file(self.state_root / "data" / "pm" / "books" / "latest.json"), pm_after)
        self.assertEqual(
            self.store.read_review_index(run_id)["reviews"][0]["status"],
            "frozen",
        )
        self.assertFalse((self.store.review_dir(run_id, "review-001") / "trader_review.json").is_file())

    def test_freeze_retry_reuses_review_id(self) -> None:
        run_id = "overnight-20260918"
        first = self.store.read_artifact(run_id, "evidence_snapshot.json", review_id="review-001")
        again = freeze_snapshot(self.store, run_id=run_id, when=AS_OF, reuse_open=True)
        self.assertEqual(again["review_id"], "review-001")
        self.assertEqual(again["packet_sha256"], first["packet_sha256"])
        self.assertEqual(len(self.store.review_rows(run_id)), 1)

    def test_next_day_dry_run_allocates_review_001(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = dry_run(
                root=ROOT,
                state_root=Path(tmp),
                when=datetime.fromisoformat("2026-09-23T04:10:00-04:00"),
                suffix="nextday",
                market_state_path=FIXTURE,
            )
            store = OvernightStore(root=ROOT, state_root=Path(tmp))
            run_id = result["overnight_run_id"]
            self.assertTrue(run_id.startswith("overnight-20260923"))
            snapshot = store.read_artifact(run_id, "evidence_snapshot.json")
            review = store.read_artifact(run_id, "trader_review.json")
            self.assertEqual(snapshot["review_id"], "review-001")
            self.assertEqual(review["review_id"], "review-001")
            self.assertEqual(review["overnight_run_id"], run_id)
            self.assertEqual(result["model_calls"], 0)
            self.assertTrue((store.review_dir(run_id, "review-001") / "memory" / "dollar-king.json").is_file())
            self.assertEqual(store.read_review_index(run_id)["reviews"][0]["status"], "accepted")


class Sep22MigrationTests(unittest.TestCase):
    def test_migration_preserves_canonical_economics_and_is_idempotent(self) -> None:
        books = ROOT / "data" / "overnight" / "books" / "latest.json"
        pm_books = ROOT / "data" / "pm" / "books" / "latest.json"
        before_books = _file_sha(books)
        before_pm = _file_sha(pm_books)
        first = migrate_sep22(ROOT)
        self.assertEqual(_file_sha(books), before_books)
        self.assertEqual(_file_sha(pm_books), before_pm)
        second = migrate_sep22(ROOT)
        self.assertEqual(second["books_sha256"], first["books_sha256"])
        self.assertEqual(_file_sha(books), before_books)
        self.assertEqual(_file_sha(pm_books), before_pm)

        store = OvernightStore(root=ROOT, state_root=ROOT)
        morning = store.read_artifact(SESSION_ID, "evidence_snapshot.json", review_id=MORNING_REVIEW)
        refresh = store.read_artifact(SESSION_ID, "evidence_snapshot.json", review_id=REFRESH_REVIEW)
        self.assertEqual(morning["packet_sha256"], MORNING_PACKET)
        self.assertEqual(refresh["packet_sha256"], REFRESH_PACKET)
        self.assertEqual(refresh["as_of"], "2026-09-22T11:28:31.273278-04:00")
        index = store.read_review_index(SESSION_ID)
        by_id = {row["review_id"]: row for row in index["reviews"]}
        self.assertEqual(by_id[MORNING_REVIEW]["status"], "accepted")
        self.assertEqual(by_id[REFRESH_REVIEW]["status"], "frozen")
        self.assertFalse((store.review_dir(SESSION_ID, REFRESH_REVIEW) / "scheduled_output.json").is_file())
        self.assertTrue((store.review_dir(SESSION_ID, MORNING_REVIEW) / "scheduled_output.json").is_file())
        self.assertFalse((store.run_dir(SESSION_ID) / "evidence_snapshot.json").exists())
        journal = json.loads(
            (ROOT / "data" / "trading" / "trader" / "dollar-king" / "journal.json").read_text(encoding="utf-8")
        )
        event = next(
            row
            for row in journal["events"]
            if row.get("run_id") == SESSION_ID and row.get("kind") == "OVERNIGHT_DECISION"
        )
        self.assertEqual(event["provenance"]["overnight_run_id"], SESSION_ID)
        self.assertEqual(event["provenance"]["review_id"], MORNING_REVIEW)


class ReviewScopedFreezeHookTests(unittest.TestCase):
    def test_budget_hook_reads_review_namespace(self) -> None:
        import json
        import subprocess
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from tests.test_overnight_scheduled_output import POLICY

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            today = datetime.now(ZoneInfo("America/New_York")).strftime("%Y%m%d")
            run_id = f"overnight-{today}"
            review = repo / "data" / "overnight" / "runs" / run_id / "reviews" / "review-001"
            review.mkdir(parents=True)
            snapshot = {
                "schema_version": 1,
                "type": "OVERNIGHT_EVIDENCE_SNAPSHOT",
                "overnight_run_id": run_id,
                "review_id": "review-001",
                "as_of": datetime.now(ZoneInfo("America/New_York")).isoformat(),
            }
            unsigned = json.dumps({k: v for k, v in snapshot.items()}, indent=2, sort_keys=True) + "\n"
            snapshot["packet_sha256"] = hashlib.sha256(unsigned.encode("utf-8")).hexdigest()
            (review / "evidence_snapshot.json").write_text(
                json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            index = {
                "overnight_run_id": run_id,
                "reviews": [{"review_id": "review-001", "status": "frozen"}],
            }
            (review.parent / "index.json").write_text(json.dumps(index), encoding="utf-8")
            run = {"stages": {"freeze_evidence": {"status": "succeeded"}}}
            (review.parent.parent / "run.json").write_text(json.dumps(run), encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "review freeze"], cwd=repo, check=True)
            transcript = Path(tmp) / "transcript.txt"
            transcript.write_text("MW_OVERNIGHT_RUN_POLICY=" + json.dumps(POLICY, separators=(",", ":")) + "\n")
            event = {
                "subagent_id": "sub-1",
                "subagent_type": "generalPurpose",
                "task": "test",
                "parent_conversation_id": "root",
                "tool_call_id": "tc",
                "subagent_model": "composer-2.5",
                "is_parallel_worker": False,
                "transcript_path": str(transcript),
            }
            for leftover in (Path("/tmp/mw-overnight-active.json"), Path("/tmp/mw-overnight-budget.lock")):
                leftover.unlink(missing_ok=True)
            result = subprocess.run(
                ["python3", str(ROOT / ".cursor" / "hooks" / "enforce-overnight-budget.py")],
                input=json.dumps(event),
                text=True,
                capture_output=True,
                cwd=repo,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
