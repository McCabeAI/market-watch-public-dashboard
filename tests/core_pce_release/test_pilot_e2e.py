"""September 2026 PPI pilot end-to-end checks (track C5)."""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.core_pce_release.listener import run_listener
from scripts.core_pce_release.packet import prepare
from scripts.core_pce_release.snapshot import load_snapshot

MODEL_SPEC = json.loads((ROOT / "data" / "core_pce_release" / "model_spec.json").read_text(encoding="utf-8"))
G0 = MODEL_SPEC["g0_reference_post_cpi_pre_ppi"]
SENTINELS = MODEL_SPEC["sentinels_august_actuals_not_september_forecasts"]
PREPARE_FIRST_LINE = "HOT baseline 0.3688% low 0.1759% high 0.5031%"
SYNTHETIC_FIXTURE = ROOT / "tests" / "core_pce_release" / "fixtures" / "synthetic_september_ppi_hospitals.json"

# Measured in test_response_received_to_flash_under_five_seconds (perf_counter).
MEASURED_RESPONSE_TO_FLASH_SECONDS: float | None = None
MEASURED_FIRST_DETECTION_TO_FLASH_SECONDS: float | None = None


def _synthetic_batch() -> dict:
    payload = json.loads(SYNTHETIC_FIXTURE.read_text(encoding="utf-8"))
    observations = list(payload["observations"])
    return {
        "observations": observations,
        "series_latest": {"PCU622---622---": "2026-09"},
        "source_latency_seconds": 0.0,
        "gaps": [],
    }


class PilotEndToEndTests(unittest.TestCase):
    def test_prepare_ppi_baseline_packet(self):
        with tempfile.TemporaryDirectory() as raw:
            packet = Path(raw)
            code, text = prepare("ppi", "2026-09", packet)
            self.assertEqual(code, 0)
            self.assertEqual(text.splitlines()[0], PREPARE_FIRST_LINE)
            self.assertIn("stage: awaiting current PPI", text)
            detailed = json.loads((packet / "detailed.json").read_text(encoding="utf-8"))
            self.assertEqual(detailed["central_mom_percent"], G0["central_mom_percent"])
            self.assertEqual(detailed["low_mom_percent"], G0["low_mom_percent"])
            self.assertEqual(detailed["high_mom_percent"], G0["high_mom_percent"])
            self.assertEqual(detailed["headline"], "HOT")
            self.assertEqual(detailed["information_stage"], "post_cpi_pre_ppi")
            by_line = {row["line"]: row for row in detailed["components"]}
            hospital_mom = SENTINELS["184_and_359_nonprofit_hospital_mom_percent"]
            self.assertEqual(by_line[184]["mom_percent"], hospital_mom)
            self.assertEqual(by_line[359]["mom_percent"], hospital_mom)
            self.assertEqual(
                by_line[268]["mom_percent"],
                SENTINELS["268_portfolio_management_mom_percent"],
            )

    def test_listener_synthetic_hospital_ppi_revision(self):
        global MEASURED_RESPONSE_TO_FLASH_SECONDS, MEASURED_FIRST_DETECTION_TO_FLASH_SECONDS
        synthetic = _synthetic_batch()
        with tempfile.TemporaryDirectory() as raw:
            packet = Path(raw) / "packet"
            prepare("ppi", "2026-09", packet)
            prepared = json.loads((packet / "detailed.json").read_text(encoding="utf-8"))
            prepared_central = Decimal(prepared["central_mom_percent"])
            by_line = {row["line"]: row for row in prepared["components"]}
            weight_185 = Decimal(by_line[185]["weight_share"])
            weight_186 = Decimal(by_line[186]["weight_share"])
            expected_delta = (weight_185 + weight_186) * Decimal("0.5")

            emits: list[str] = []
            fetch_calls = 0
            handler_started: float | None = None

            def emit(text: str) -> None:
                global MEASURED_RESPONSE_TO_FLASH_SECONDS, MEASURED_FIRST_DETECTION_TO_FLASH_SECONDS
                if handler_started is not None and "stage: PPI updated" in text:
                    elapsed = time.perf_counter() - handler_started
                    MEASURED_RESPONSE_TO_FLASH_SECONDS = elapsed
                    if MEASURED_FIRST_DETECTION_TO_FLASH_SECONDS is None:
                        MEASURED_FIRST_DETECTION_TO_FLASH_SECONDS = elapsed
                emits.append(text)

            def fetch(_series_ids, _release):
                nonlocal fetch_calls, handler_started
                fetch_calls += 1
                if fetch_calls == 1:
                    return {"observations": []}
                handler_started = time.perf_counter()
                return synthetic

            clock = [0.0]

            def now():
                return clock[0]

            def sleep(seconds):
                clock[0] += max(seconds, 0.1)

            run_listener(
                packet,
                packet / "inbox",
                now=now,
                sleep=sleep,
                max_runtime_seconds=15,
                interval_seconds=0.5,
                fetch=fetch,
                emit=emit,
            )

            self.assertGreaterEqual(fetch_calls, 2)
            self.assertGreaterEqual(len(emits), 2)
            self.assertIn("0.3688%", emits[0])
            self.assertIn("awaiting current PPI", emits[0])
            self.assertIn("stage: PPI updated", emits[-1])

            detailed = json.loads((packet / "detailed.json").read_text(encoding="utf-8"))
            updated_central = Decimal(detailed["central_mom_percent"])
            self.assertGreater(updated_central, prepared_central)
            delta = updated_central - prepared_central
            self.assertAlmostEqual(delta, expected_delta, places=24)
            by_line = {row["line"]: row for row in detailed["components"]}
            self.assertEqual(by_line[184]["mom_percent"], by_line[359]["mom_percent"])
            self.assertEqual(by_line[346]["mom_percent"], "0")
            self.assertEqual(by_line[185]["seasonal_status_output"], "modeled_not_bea_sa")

            emits.clear()
            fetch_calls = 0

            def fetch_again(_series_ids, _release):
                nonlocal fetch_calls
                fetch_calls += 1
                return synthetic

            run_listener(
                packet,
                packet / "inbox",
                now=now,
                sleep=sleep,
                max_runtime_seconds=2,
                interval_seconds=0.5,
                fetch=fetch_again,
                emit=lambda _text: None,
            )
            detailed_again = json.loads((packet / "detailed.json").read_text(encoding="utf-8"))
            self.assertEqual(detailed_again["central_mom_percent"], detailed["central_mom_percent"])
            self.assertLess(MEASURED_RESPONSE_TO_FLASH_SECONDS, 5.0)

    def test_response_received_to_flash_under_five_seconds(self):
        self.assertIsNotNone(MEASURED_RESPONSE_TO_FLASH_SECONDS)
        self.assertLess(MEASURED_RESPONSE_TO_FLASH_SECONDS, 5.0)

    def test_cancel_keeps_baseline_flash(self):
        with tempfile.TemporaryDirectory() as raw:
            packet = Path(raw) / "packet"
            prepare("ppi", "2026-09", packet)
            emits: list[str] = []
            polls = 0

            def fetch(_series_ids, _release):
                nonlocal polls
                polls += 1
                if polls == 1:
                    (packet / "CANCEL").write_text("stop\n", encoding="utf-8")
                return {"observations": []}

            clock = [0.0]
            run_listener(
                packet,
                packet / "inbox",
                now=lambda: clock[0],
                sleep=lambda s: clock.__setitem__(0, clock[0] + 1),
                max_runtime_seconds=60,
                interval_seconds=1,
                fetch=fetch,
                emit=emits.append,
            )
            self.assertIn("0.3688%", (packet / "flash.txt").read_text(encoding="utf-8"))

    def test_extreme_and_stale_observations_leave_central_unchanged(self):
        snapshot = load_snapshot()
        with tempfile.TemporaryDirectory() as raw:
            packet = Path(raw) / "packet"
            prepare("ppi", "2026-09", packet)
            baseline = json.loads((packet / "detailed.json").read_text(encoding="utf-8"))["central_mom_percent"]
            inbox = packet / "inbox"
            inbox.mkdir()
            payload = {
                "target_period": "2026-09",
                "observations": [
                    {
                        "line": 174,
                        "series_id": "PCU6211--6211--",
                        "period": "2026-09",
                        "mom_percent": "40",
                        "role": "raw_bls_reference",
                        "source_family": "PPI",
                        "seasonal_status": "BLS_NSA",
                    },
                    {
                        "line": 174,
                        "series_id": "PCU6211--6211--",
                        "period": "2026-07",
                        "mom_percent": "0.2",
                        "role": "raw_bls_reference",
                        "source_family": "PPI",
                        "seasonal_status": "BLS_NSA",
                    },
                ],
            }
            (inbox / "bad.json").write_text(json.dumps(payload) + "\n", encoding="utf-8")
            clock = [0.0]
            run_listener(
                packet,
                inbox,
                now=lambda: clock[0],
                sleep=lambda s: clock.__setitem__(0, clock[0] + 1),
                max_runtime_seconds=5,
                interval_seconds=1,
                fetch=lambda *_a, **_k: {"observations": []},
            )
            detailed = json.loads((packet / "detailed.json").read_text(encoding="utf-8"))
            self.assertEqual(detailed["central_mom_percent"], baseline)


if __name__ == "__main__":
    unittest.main()
