"""Per-country proof that canonical merge updates scores without touching calibration."""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.country_registry import history_files
from scripts.macro_ingestion.canonical_bridge import merge_scored_points, period_after, persist_if_changed
from scripts.macro_ingestion.windows import TRUSTED_PACKET_STATEMENT, write_post_freeze_delta
from scripts.temperature_level import (
    CALIBRATION_PATH,
    build_score_state,
    compute_state,
    load_calibration,
    load_history,
    scoring_cutoff,
)

from tests.macro_ingestion.test_canonical_bridge import (
    COUNTRY_FIXTURES,
    EXPECTED_EVIDENCE_SHA,
    EVIDENCE_PATH,
    _base_point,
    _latest_stored_period,
    _sha256_path,
)

NY = ZoneInfo("America/New_York")


class TestCountryScorePath(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.calibration = load_calibration()
        cls.calibration_sha = _sha256_path(CALIBRATION_PATH)

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.history_dir = self.tmp_path / "temperature_history"
        self.history_dir.mkdir()
        names = history_files()
        for code, filename in names.items():
            shutil.copy2(
                ROOT / "data/temperature_history" / filename,
                self.history_dir / filename,
            )
        self.histories = load_history(self.history_dir)
        self.scores_path = self.tmp_path / "temperature_scores.json"
        self.paths_path = self.tmp_path / "score_paths.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_each_country_forward_point_updates_scores_json(self) -> None:
        checked_at = "2026-09-23T12:00:00Z"
        for country, fixture in COUNTRY_FIXTURES.items():
            with self.subTest(country=country):
                histories = copy.deepcopy(self.histories)
                spec = self.calibration["components"][fixture["catalog_id"]]
                history_key = spec["history_key"]
                latest = _latest_stored_period(
                    histories[country],
                    history_key=history_key,
                    transformation=fixture["transformation"],
                    series_id=fixture["series_id"],
                )
                next_period = period_after(latest)
                dim = fixture["catalog_id"].split(".")[1]
                comp_name = fixture["catalog_id"].split(".", 2)[2]

                pre_cutoff = scoring_cutoff(self.calibration, histories)
                pre_state = build_score_state(
                    self.calibration, compute_state(self.calibration, histories, cutoff=pre_cutoff)
                )
                pre_comp = pre_state["countries"][country][dim]["component_state"][comp_name]

                point = _base_point(fixture, period=next_period, value=3.25)
                result = merge_scored_points(
                    histories, self.calibration, [point], checked_at=checked_at
                )
                self.assertEqual(len(result["appended"]), 1, result)

                persist_if_changed(
                    histories,
                    appended=result["appended"],
                    history_dir=self.history_dir,
                    scores_path=self.scores_path,
                    paths_path=self.paths_path,
                    calibration_path=CALIBRATION_PATH,
                )

                loaded = json.loads(self.scores_path.read_text(encoding="utf-8"))
                post_comp = loaded["countries"][country][dim]["component_state"][comp_name]
                self.assertEqual(post_comp["as_of"], next_period)
                self.assertNotEqual(post_comp["as_of"], pre_comp["as_of"])

        self.assertEqual(_sha256_path(CALIBRATION_PATH), self.calibration_sha)
        if EVIDENCE_PATH.is_file():
            self.assertEqual(_sha256_path(EVIDENCE_PATH), EXPECTED_EVIDENCE_SHA)

    def test_post_freeze_delta_excludes_evidence_snapshot(self) -> None:
        when = datetime(2026, 9, 23, 4, 0, tzinfo=NY)
        with tempfile.TemporaryDirectory() as tmp:
            path = write_post_freeze_delta(
                when=when,
                changed_series=[{"id": "EA.Activity.flash_composite_pmi", "period": "2026-09"}],
                base_dir=Path(tmp),
            )
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("evidence_snapshot", text.lower())
            self.assertIn(TRUSTED_PACKET_STATEMENT, text)


if __name__ == "__main__":
    unittest.main()
