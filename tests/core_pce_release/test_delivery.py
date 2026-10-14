"""Delivery layer tests (track C4)."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.core_pce_release.listener import run_listener
from scripts.core_pce_release.packet import load_packet, prepare

G0_CENTRAL = "0.3688405280179773205064998201"
FIRST_LINE = "HOT baseline 0.3688% low 0.1759% high 0.5031%"


def _hospital_observations() -> list[dict]:
    rows = []
    for period, mom in (("2026-09", "1.5"), ("2026-08", "1.0")):
        rows.append(
            {
                "line": 185,
                "series_id": "PCU622---622---",
                "period": period,
                "mom_percent": mom,
                "role": "raw_bls_reference",
                "source_family": "PPI",
                "seasonal_status": "BLS_NSA",
            }
        )
    return rows


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = Path(tempfile.mkdtemp())
        self.packet_dir = self.tempdir / "packet"
        self.inbox = self.packet_dir / "inbox"

    def tearDown(self):
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_prepare_ppi_writes_baseline_offline(self):
        code, text = prepare("ppi", "2026-09", self.packet_dir)
        self.assertEqual(code, 0)
        first_line = text.splitlines()[0]
        self.assertEqual(first_line, FIRST_LINE)
        self.assertIn("stage: awaiting current PPI", text)
        packet = load_packet(self.packet_dir)
        self.assertEqual(packet["status"], "READY")
        self.assertEqual(packet["listener"], "not_armed")
        self.assertEqual(packet["central_mom_percent"], G0_CENTRAL)
        detailed = json.loads((self.packet_dir / "detailed.json").read_text(encoding="utf-8"))
        self.assertEqual(detailed["central_mom_percent"], G0_CENTRAL)
        for name in ("pre_release_state.json", "flash.txt", "detailed.txt", "detailed.json", "PREPARE.txt"):
            self.assertTrue((self.packet_dir / name).exists())

    def test_listener_baseline_before_fetch_and_ppi_revision(self):
        prepare("ppi", "2026-09", self.packet_dir)
        emits: list[str] = []
        fetch_calls = 0

        def emit(text: str) -> None:
            emits.append(text)

        def fetch(_series_ids, _release):
            nonlocal fetch_calls
            fetch_calls += 1
            if fetch_calls == 1:
                return {"observations": []}
            return {"observations": _hospital_observations()}

        clock = [0.0]

        def now():
            return clock[0]

        def sleep(seconds):
            clock[0] += max(seconds, 0.1)

        outcome = run_listener(
            self.packet_dir,
            self.inbox,
            now=now,
            sleep=sleep,
            max_runtime_seconds=30,
            interval_seconds=1,
            fetch=fetch,
            emit=emit,
        )
        self.assertGreaterEqual(fetch_calls, 1)
        self.assertIn("awaiting current PPI", emits[0])
        self.assertIn("0.3688%", emits[0])
        self.assertGreater(len(emits), 1)
        later = emits[-1]
        self.assertIn("PPI updated", later)
        self.assertNotIn("0.3688%", later.splitlines()[0])
        self.assertNotIn("BEA_SA", later)

        detailed = json.loads((self.packet_dir / "detailed.json").read_text(encoding="utf-8"))
        row346 = next(r for r in detailed["components"] if r["line"] == 346)
        self.assertEqual(row346["mom_percent"], "0")

        revisions = (self.packet_dir / "revisions.jsonl").read_text(encoding="utf-8").strip().splitlines()
        self.assertGreaterEqual(len(revisions), 2)
        second = json.loads(revisions[1])
        self.assertIsNotNone(second.get("contribution_delta_vs_previous"))
        self.assertIsNotNone(outcome.get("headline"))

    def test_duplicate_observations_do_not_reflash(self):
        prepare("ppi", "2026-09", self.packet_dir)
        emits: list[str] = []
        poll = 0

        def fetch(_series_ids, _release):
            nonlocal poll
            poll += 1
            if poll >= 2:
                return {"observations": _hospital_observations()}
            return {"observations": []}

        clock = [0.0]

        run_listener(
            self.packet_dir,
            self.inbox,
            now=lambda: clock[0],
            sleep=lambda s: clock.__setitem__(0, clock[0] + max(s, 0.1)),
            max_runtime_seconds=5,
            interval_seconds=0.5,
            fetch=fetch,
            emit=emits.append,
        )
        self.assertEqual(len(emits), 2)
        self.assertNotEqual(emits[0].splitlines()[0], emits[1].splitlines()[0])

        emits.clear()
        poll = 0
        run_listener(
            self.packet_dir,
            self.inbox,
            now=lambda: clock[0],
            sleep=lambda s: clock.__setitem__(0, clock[0] + max(s, 0.1)),
            max_runtime_seconds=3,
            interval_seconds=0.5,
            fetch=fetch,
            emit=emits.append,
        )
        self.assertEqual(len(emits), 1)

    def test_fetch_error_keeps_baseline_flash(self):
        prepare("ppi", "2026-09", self.packet_dir)
        baseline_flash = (self.packet_dir / "flash.txt").read_text(encoding="utf-8")

        def fetch(_series_ids, _release):
            raise RuntimeError("network down")

        run_listener(
            self.packet_dir,
            self.inbox,
            now=lambda: 0.0,
            sleep=lambda _s: None,
            max_runtime_seconds=0,
            interval_seconds=1,
            fetch=fetch,
            emit=lambda _t: None,
        )
        flash = (self.packet_dir / "flash.txt").read_text(encoding="utf-8")
        self.assertIn("0.3688%", flash)
        self.assertEqual(flash.splitlines()[0], baseline_flash.splitlines()[0])

    def test_cancel_before_second_poll(self):
        prepare("ppi", "2026-09", self.packet_dir)
        poll = 0

        def fetch(_series_ids, _release):
            nonlocal poll
            poll += 1
            if poll == 1:
                (self.packet_dir / "CANCEL").write_text("1\n", encoding="utf-8")
            return {"observations": []}

        clock = [0.0]
        run_listener(
            self.packet_dir,
            self.inbox,
            now=lambda: clock[0],
            sleep=lambda s: clock.__setitem__(0, clock[0] + 1),
            max_runtime_seconds=60,
            interval_seconds=1,
            fetch=fetch,
            emit=lambda _t: None,
        )
        flash = (self.packet_dir / "flash.txt").read_text(encoding="utf-8")
        self.assertIn("0.3688%", flash)

    def test_max_runtime_zero_one_baseline_emit(self):
        prepare("ppi", "2026-09", self.packet_dir)
        emits: list[str] = []

        def fetch(_series_ids, _release):
            self.fail("fetch should not be required for max_runtime 0 baseline-only stop")

        run_listener(
            self.packet_dir,
            self.inbox,
            now=lambda: 0.0,
            sleep=lambda _s: None,
            max_runtime_seconds=0,
            interval_seconds=1,
            fetch=fetch,
            emit=emits.append,
        )
        self.assertEqual(len(emits), 1)
        self.assertIn("0.3688%", emits[0])

    def test_no_scheduler_tokens_in_delivery_modules(self):
        for path in (
            ROOT / "scripts/core_pce_release/listener.py",
            ROOT / "scripts/core_pce_release/cli.py",
        ):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("schedule", text.lower())
            self.assertNotIn("BackgroundScheduler", text)
            self.assertNotIn("cron", text.lower())


if __name__ == "__main__":
    unittest.main()
