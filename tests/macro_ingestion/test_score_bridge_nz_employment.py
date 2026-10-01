"""Defense-in-depth: bad NZ employment qoq values must not enter staged lineage."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.market_watch_launch.lineage import stage_verified_lineage
from scripts.macro_ingestion.score_bridge import recompute_scores_after_observation
from scripts.temperature_level import CALIBRATION_PATH, HISTORY_DIR


def _employment_obs_values(history: dict) -> list[float]:
    comp = history["components"]["Labor.employment"]
    return [
        float(obs["value"])
        for obs in comp.get("observations") or []
        if obs.get("transformation") == "qoq_change_thousands_sa"
    ]


class TestScoreBridgeNzEmploymentQoQ(unittest.TestCase):
    def test_recompute_rejects_1511_level_masquerading_as_change(self) -> None:
        bad_point = {
            "country": "NZ",
            "catalog_id": "NZ.Labor.employment",
            "series_id": "HLFQ.S1A3S",
            "period": "2026-Q2",
            "value": 1511.0,
            "transformation": "qoq_change_thousands_sa",
            "revision_status": "final",
            "source_url": "https://example.test",
            "raw_sha256": "deadbeef",
            "retrieved_at": "2026-10-01T08:50:57Z",
        }
        with tempfile.TemporaryDirectory() as tmp:
            history_dir = Path(tmp) / "history"
            history_dir.mkdir()
            for src in HISTORY_DIR.glob("*.json"):
                (history_dir / src.name).write_bytes(src.read_bytes())
            outcome = recompute_scores_after_observation(
                persist_history=True,
                persist_scores=False,
                calibration_path=CALIBRATION_PATH,
                history_dir=history_dir,
                points=[bad_point],
                checked_at="2026-10-01T08:50:57Z",
            )
            self.assertTrue(outcome.ok)
            nz = json.loads((history_dir / "nz.json").read_text(encoding="utf-8"))
            self.assertNotIn(1511.0, _employment_obs_values(nz))

    def test_stage_verified_lineage_rejects_1511(self) -> None:
        bad_point = {
            "country": "NZ",
            "catalog_id": "NZ.Labor.employment",
            "series_id": "HLFQ.S1A3S",
            "period": "2026-Q2",
            "value": 1511.0,
            "transformation": "qoq_change_thousands_sa",
            "revision_status": "final",
            "source_url": "https://example.test",
            "raw_sha256": "deadbeef",
            "retrieved_at": "2026-10-01T08:50:57Z",
        }
        with tempfile.TemporaryDirectory() as tmp:
            launch_dir = Path(tmp) / "launch"
            launch_dir.mkdir()
            result = stage_verified_lineage(
                launch_dir=launch_dir,
                checked_at="2026-10-01T08:50:57Z",
                canonical_history_dir=HISTORY_DIR,
                calibration_path=CALIBRATION_PATH,
                points=[bad_point],
            )
            self.assertTrue(result["ok"])
            nz_path = launch_dir / "lineage" / "history" / "nz.json"
            nz = json.loads(nz_path.read_text(encoding="utf-8"))
            self.assertNotIn(1511.0, _employment_obs_values(nz))


if __name__ == "__main__":
    unittest.main()
