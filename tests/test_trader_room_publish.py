from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.trader_room.constants import HANDOFF_MARKER, STANDING_ADVOCATES
from scripts.trader_room_public import (
    build_public_packet,
    completeness_errors,
    is_complete_valid_run,
    select_newest_complete_run,
)


REPO = Path(__file__).resolve().parents[1]


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _minimal_complete_run(root: Path, run_id: str, *, seats: tuple[str, ...] = STANDING_ADVOCATES) -> Path:
    run = root / "trader-room" / "runs" / run_id
    _write_json(run / "evidence_packet.json", {"run_id": run_id, "as_of": run_id, "packet_sha256": "abc"})
    _write_json(run / "pm_handoff.json", {"run_id": run_id, "status": HANDOFF_MARKER})
    _write_json(run / "conflict_map.json", {"conflicts": [{"id": "c1"}]})
    _write_json(run / "artifact_index.json", {"run_id": run_id})
    for seat in seats:
        _write_json(
            run / "submissions" / f"{seat}.json",
            {
                "agent": seat,
                "stance_summary": f"{seat} stance",
                "confidence": 50,
                "why_now": f"{seat} wants in because the freeze still supports the pitch.",
                "trade": None if seat == "no-trade-skeptic" else {
                    "instrument": "USDCAD",
                    "direction": "long",
                    "structure": "spot",
                    "horizon": "1m",
                },
            },
        )
    return run


class TraderRoomPublishTests(unittest.TestCase):
    def test_repo_current_data_is_newest_complete_valid_run(self) -> None:
        selected = select_newest_complete_run(REPO)
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertTrue(is_complete_valid_run(selected))
        packet = build_public_packet(REPO)
        self.assertTrue(packet["available"])
        self.assertEqual(packet["run_id"], selected.name)
        self.assertEqual(packet["run_id"], packet["selection"]["selected_run_id"])
        self.assertEqual(packet["seat_count"], 14)
        self.assertEqual(packet["selection"]["mode"], "newest_complete_valid")
        self.assertFalse(packet["selection"]["manual_pointer"])
        self.assertTrue(any(row.get("entry_reason") for row in packet["trades"]))
        self.assertTrue(any(row.get("stance_summary") for row in packet["trades"]))
        leaked = json.dumps(packet)
        self.assertNotIn("private_methodology", leaked)
        self.assertNotIn("GOOGLE_DRIVE", leaked)

    def test_newer_complete_run_is_selected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _minimal_complete_run(root, "tr-20260918T182933Z-ondemand")
            _minimal_complete_run(root, "tr-20260921T080000Z-ondemand")
            selected = select_newest_complete_run(root)
            self.assertIsNotNone(selected)
            assert selected is not None
            self.assertEqual(selected.name, "tr-20260921T080000Z-ondemand")
            packet = build_public_packet(root)
            self.assertEqual(packet["run_id"], "tr-20260921T080000Z-ondemand")
            self.assertEqual(packet["selection"]["selected_run_id"], "tr-20260921T080000Z-ondemand")
            self.assertEqual(packet["selection"]["mode"], "newest_complete_valid")

    def test_newer_incomplete_run_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _minimal_complete_run(root, "tr-20260918T182933Z-ondemand")
            newer = _minimal_complete_run(root, "tr-20260920T010000Z-ondemand")
            (newer / "submissions" / "rate-hawk.json").unlink()
            self.assertTrue(completeness_errors(newer))
            selected = select_newest_complete_run(root)
            self.assertIsNotNone(selected)
            assert selected is not None
            self.assertEqual(selected.name, "tr-20260918T182933Z-ondemand")
            packet = build_public_packet(root)
            self.assertEqual(packet["run_id"], "tr-20260918T182933Z-ondemand")
            ignored = {row["run_id"] for row in packet["selection"]["ignored_incomplete"]}
            self.assertIn("tr-20260920T010000Z-ondemand", ignored)

    def test_newer_complete_wins_and_newer_incomplete_is_ignored_together(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(
                REPO / "trader-room" / "runs" / "tr-20260919T123430Z-ondemand",
                root / "trader-room" / "runs" / "tr-20260919T123430Z-ondemand",
            )
            _minimal_complete_run(root, "tr-20260922T090000Z-ondemand")
            incomplete = _minimal_complete_run(root, "tr-20260923T010000Z-ondemand")
            (incomplete / "pm_handoff.json").unlink()
            packet = build_public_packet(root)
            self.assertEqual(packet["run_id"], "tr-20260922T090000Z-ondemand")
            ignored = {row["run_id"] for row in packet["selection"]["ignored_incomplete"]}
            self.assertIn("tr-20260923T010000Z-ondemand", ignored)
            self.assertNotEqual(packet["run_id"], "tr-20260919T123430Z-ondemand")

    def test_pages_workflow_does_not_hardcode_a_run_id(self) -> None:
        workflow = (REPO / ".github" / "workflows" / "deploy-pages.yml").read_text(encoding="utf-8")
        self.assertNotIn('assert packet.get("run_id") == "tr-20260919T123430Z-ondemand"', workflow)
        self.assertIn("select_newest_complete_run", workflow)
        self.assertIn("newest_complete_valid", workflow)

    def test_pages_does_not_require_manual_latest_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(REPO / "trader-room" / "runs" / "tr-20260919T123430Z-ondemand", root / "trader-room" / "runs" / "tr-20260919T123430Z-ondemand")
            self.assertFalse((root / "data" / "trader-room" / "public" / "latest.json").is_file())
            packet = build_public_packet(root)
            self.assertEqual(packet["run_id"], "tr-20260919T123430Z-ondemand")
            self.assertEqual(packet["seat_count"], 14)


if __name__ == "__main__":
    unittest.main()
