"""Wire economic_calendar through collect, freeze, and seat/PM projections."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.dashboard_repair.evidence_calendar import build_evidence_calendar
from scripts.dashboard_repair.calendar_packet import economic_calendar_from_frozen
from scripts.market_watch_launch.provider_stub import build_stub_output
from scripts.overnight.evidence import freeze_snapshot
from scripts.overnight.errors import EvidenceBoundaryError
from scripts.overnight.pipeline import run_stage
from scripts.overnight.scheduled_output import validate_output
from scripts.overnight.store import OvernightStore
from scripts.pm.constants import PM_IDS
from scripts.pm.overnight_packet import attach_economic_calendar
from scripts.trader_room import agent_config
from scripts.trader_room.overnight_packet import project_trader_seat_packet

ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")
AS_OF = datetime(2026, 11, 9, 5, 37, 50, tzinfo=ET)
FIXTURE = ROOT / "data" / "overnight" / "fixtures" / "market_state.json"
IMMUTABLE_SNAPSHOT = (
    ROOT / "data/overnight/runs/overnight-20261109/reviews/review-001/evidence_snapshot.json"
)
EXPECTED_PACKET_SHA256 = "36b651b69a9e2951d8f7c97819999a9354668967f97c455af200a46c3662fb11"


class Nov9CalendarFrozenHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="mw-calendar-handoff-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.store = OvernightStore(root=ROOT, state_root=self.tmp)
        self.run_id = "overnight-20261109-handoff-test"
        for stage in ("collect", "pre_trader_delta"):
            run_stage(
                stage,
                root=ROOT,
                state_root=self.tmp,
                run_id=self.run_id,
                when=AS_OF,
                dry_run=True,
                offline=True,
                market_state_path=FIXTURE,
            )
        self.snapshot = freeze_snapshot(
            self.store, run_id=self.run_id, when=AS_OF, reuse_open=False
        )

    def test_collect_and_freeze_share_calendar_hash(self) -> None:
        expected = build_evidence_calendar(AS_OF, root=ROOT, allow_network=False)["content_hash"]
        collect = self.store.read_artifact(self.run_id, "collect.json")
        delta = self.store.read_artifact(self.run_id, "pre_trader_delta.json")
        self.assertEqual(collect["economic_calendar"]["content_hash"], expected)
        self.assertEqual(delta["economic_calendar"]["content_hash"], expected)
        self.assertEqual(self.snapshot["economic_calendar"]["content_hash"], expected)

    def test_seat_and_pm_packets_carry_identical_calendar(self) -> None:
        snap_hash = self.snapshot["economic_calendar"]["content_hash"]
        pin = self.snapshot.get("agent_roster_pin") or agent_config.build_pin("daily", as_of=AS_OF)
        seat_ids = list(agent_config.pin_trader_ids(pin))
        self.assertIn("chart-guy", seat_ids)
        self.assertEqual(len(seat_ids), 15)
        for seat_id in seat_ids:
            packet = project_trader_seat_packet(self.snapshot, seat_id=seat_id)
            self.assertEqual(packet["economic_calendar"]["content_hash"], snap_hash)
        for pm_id in PM_IDS:
            packet = attach_economic_calendar(
                {"type": "PM_REVIEW_PACKET", "pm_id": pm_id},
                self.snapshot,
            )
            self.assertEqual(packet["economic_calendar"]["content_hash"], snap_hash)

    def test_immutable_nov9_snapshot_unchanged(self) -> None:
        before = IMMUTABLE_SNAPSHOT.read_bytes()
        snapshot = json.loads(before.decode("utf-8"))
        self.assertEqual(snapshot.get("packet_sha256"), EXPECTED_PACKET_SHA256)
        self.assertNotIn("economic_calendar", snapshot)
        build_evidence_calendar(AS_OF, root=ROOT, allow_network=False)
        self.assertEqual(IMMUTABLE_SNAPSHOT.read_bytes(), before)

    def test_scheduled_output_enforces_identical_agent_packet_calendar(self) -> None:
        review_id = "review-099"
        self.store.write_artifact(
            self.run_id,
            "evidence_snapshot.json",
            self.snapshot,
            review_id=review_id,
        )
        launch = {
            "launch_id": "mwl-handoff-cal-test",
            "overnight_run_id": self.run_id,
            "review_id": review_id,
        }
        output = build_stub_output(self.store, launch=launch, base_packet=self.snapshot)
        validate_output(self.store, output)

        bad = json.loads(json.dumps(output))
        bad["agent_packet"]["economic_calendar"] = {
            **self.snapshot["economic_calendar"],
            "content_hash": "deadbeef",
        }
        with self.assertRaises(EvidenceBoundaryError):
            validate_output(self.store, bad)

    def test_review_snapshot_calendar_round_trip_for_pm_handoff(self) -> None:
        snap_hash = self.snapshot["economic_calendar"]["content_hash"]
        round_trip = economic_calendar_from_frozen(self.snapshot)
        self.assertEqual(round_trip["content_hash"], snap_hash)
        self.assertEqual(round_trip["events"], self.snapshot["economic_calendar"]["events"])

    def test_no_leak_and_us_prints_present(self) -> None:
        block = self.snapshot["economic_calendar"]
        families = {e.get("event_family") for e in block["events"]}
        self.assertIn("us_cpi", families)
        self.assertIn("us_empsit", families)
        cutoff = AS_OF
        for ev in block["events"]:
            clock = ev.get("clock")
            local_date = ev.get("local_date")
            time = ev.get("time")
            if clock in {"verified", "standing"} and time and local_date:
                from zoneinfo import ZoneInfo as ZI

                tz = ZI(str(ev.get("timezone") or "America/New_York"))
                naive = datetime.fromisoformat(f"{local_date}T{time}:00")
                instant = naive.replace(tzinfo=tz)
                self.assertGreaterEqual(instant.astimezone(ET), cutoff)


if __name__ == "__main__":
    unittest.main()
