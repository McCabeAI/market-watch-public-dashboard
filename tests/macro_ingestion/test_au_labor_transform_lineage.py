"""AU labour unemployment transform alignment and lineage merge behavior."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_ingestion.canonical_bridge import merge_scored_points
from scripts.macro_ingestion.contract import load_catalog
from scripts.market_watch_launch.lineage import stage_verified_lineage
from scripts.temperature_level import CALIBRATION_PATH, load_calibration, load_history

CATALOG_ID = "AU.Labor.unemployment"
SERIES_ID = "A84423050A"
PERIOD = "2026-08"
VALUE = 4.6462961
TRANSFORM = "percent"


class AuLaborTransformLineageTests(unittest.TestCase):
    def test_unemployment_transform_contract_aligned(self) -> None:
        catalog = load_catalog()
        row = next(s for s in catalog["series"] if s["id"] == CATALOG_ID)
        self.assertEqual(row.get("series_id"), SERIES_ID)
        self.assertEqual(row.get("transform"), TRANSFORM)
        self.assertEqual(row.get("weight"), 0.7)
        self.assertEqual(row.get("units"), "percent")

        cal = load_calibration(CALIBRATION_PATH)
        comp = cal["components"][CATALOG_ID]
        self.assertEqual(comp.get("source_transformation"), TRANSFORM)
        self.assertEqual(comp.get("series_id"), SERIES_ID)

        histories = load_history(ROOT / "data" / "temperature_history")
        hist = histories["AU"]["components"]["Labor.unemployment"]
        self.assertEqual(hist.get("preferred_scoring_transformation"), TRANSFORM)
        self.assertEqual(hist.get("series_id"), SERIES_ID)

        obs_2026_08 = [
            o
            for o in hist.get("observations") or []
            if o.get("reference_period") == PERIOD and o.get("series_id") == SERIES_ID
        ]
        if obs_2026_08:
            self.assertEqual(obs_2026_08[0].get("transformation"), TRANSFORM)
        else:
            sample = next(
                o
                for o in hist.get("observations") or []
                if o.get("series_id") == SERIES_ID and o.get("transformation") == TRANSFORM
            )
            self.assertEqual(sample.get("transformation"), TRANSFORM)

    def test_merge_percent_point_appends_and_idempotent(self) -> None:
        cal_path = CALIBRATION_PATH
        cal_before = cal_path.read_bytes()
        cal = load_calibration(cal_path)
        histories = load_history(ROOT / "data" / "temperature_history")
        au = copy.deepcopy(histories["AU"])
        work = {"AU": au}

        point = {
            "country": "AU",
            "catalog_id": CATALOG_ID,
            "role": "scored",
            "series_id": SERIES_ID,
            "period": PERIOD,
            "value": VALUE,
            "transformation": TRANSFORM,
        }
        first = merge_scored_points(work, cal, [point], checked_at="2026-09-24T02:00:00Z")
        self.assertEqual(len(first["appended"]), 1)
        self.assertEqual(cal_path.read_bytes(), cal_before)

        second = merge_scored_points(work, cal, [point], checked_at="2026-09-24T02:01:00Z")
        self.assertEqual(second["skipped"], [{"id": CATALOG_ID, "reason": "duplicate_value"}])
        self.assertEqual(len(second["appended"]), 0)

    def test_merge_wrong_transform_skipped(self) -> None:
        cal = load_calibration(CALIBRATION_PATH)
        histories = load_history(ROOT / "data" / "temperature_history")
        work = {"AU": copy.deepcopy(histories["AU"])}
        before = len(work["AU"]["components"]["Labor.unemployment"]["observations"])

        bad = {
            "country": "AU",
            "catalog_id": CATALOG_ID,
            "role": "scored",
            "series_id": SERIES_ID,
            "period": PERIOD,
            "value": VALUE,
            "transformation": "unemployment_rate_sa",
        }
        result = merge_scored_points(work, cal, [bad], checked_at="2026-09-24T02:00:00Z")
        self.assertEqual(
            result["skipped"],
            [{"id": CATALOG_ID, "reason": "partial_transform_mismatch"}],
        )
        self.assertEqual(
            len(work["AU"]["components"]["Labor.unemployment"]["observations"]),
            before,
        )

    def test_lineage_rejects_transform_mismatch_fail_closed(self) -> None:
        bad_point = {
            "country": "AU",
            "catalog_id": CATALOG_ID,
            "role": "scored",
            "series_id": SERIES_ID,
            "period": PERIOD,
            "value": VALUE,
            "transformation": "unemployment_rate_sa",
        }
        with tempfile.TemporaryDirectory() as tmp:
            launch_dir = Path(tmp) / "launch"
            launch_dir.mkdir()
            result = stage_verified_lineage(
                launch_dir=launch_dir,
                checked_at="2026-09-24T02:00:00Z",
                canonical_history_dir=ROOT / "data" / "temperature_history",
                calibration_path=CALIBRATION_PATH,
                points=[bad_point],
                mode="live",
            )
            self.assertFalse(result["ok"])
            self.assertEqual(result["appended_count"], 0)
            self.assertTrue(result["rejections"])
            self.assertEqual(result["rejections"][0]["reason"], "partial_transform_mismatch")
            self.assertEqual(result["rejections"][0]["period"], PERIOD)
            scores = launch_dir / "lineage" / "temperature_scores.json"
            self.assertFalse(scores.is_file())

    def test_fixture_replay_keeps_preexisting_alias_nonblocking(self) -> None:
        from datetime import datetime, timezone

        from scripts.market_watch_launch.ingest import _fixture_ingestion

        with tempfile.TemporaryDirectory() as tmp:
            details, status, reason = _fixture_ingestion(
                root=ROOT,
                launch_dir=Path(tmp) / "launch",
                when=datetime(2026, 10, 14, 12, tzinfo=timezone.utc),
                checked_at="2026-10-14T12:00:00Z",
            )
        self.assertEqual(status, "succeeded", msg=reason)
        self.assertTrue(details["score_bridge"]["ok"])
        rejections = details["lineage"].get("rejections") or []
        self.assertFalse(any(row.get("id") == "AU.Consumer.confidence" for row in rejections))


if __name__ == "__main__":
    unittest.main()
