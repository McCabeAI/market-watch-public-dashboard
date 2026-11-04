"""Versioned compatibility between staged and recomputed temperature_scores.json."""

from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.temperature_level import (
    CALIBRATION_PATH,
    build_score_state,
    compute_state,
    load_calibration,
    load_history,
    scores_match_staged,
)

ROOT = Path(__file__).resolve().parents[1]
FROZEN_LAUNCH = ROOT / "data/market_watch_launches/mwl-20261027T093212Z-9512d95d"
FROZEN_SCORES = FROZEN_LAUNCH / "lineage/temperature_scores.json"
FROZEN_HISTORY = FROZEN_LAUNCH / "lineage/history"


class ScoresMatchStagedUnitTests(unittest.TestCase):
    def test_component_period_documents_require_exact_match(self) -> None:
        staged = {
            "version": 3,
            "as_of_representation": "component_period",
            "scoring_cutoff": "2026-10",
            "countries": {"US": {"Labor": {"as_of": "2026-09", "level": 51.0}}},
        }
        recomputed = copy.deepcopy(staged)
        self.assertIsNone(scores_match_staged(staged, recomputed))

        bad = copy.deepcopy(recomputed)
        bad["countries"]["US"]["Labor"]["level"] = 52.0
        mismatch = scores_match_staged(staged, bad)
        self.assertIsNotNone(mismatch)
        self.assertIn("level", mismatch or "")

        bad_as_of = copy.deepcopy(recomputed)
        bad_as_of["countries"]["US"]["Labor"]["as_of"] = "2026-08"
        mismatch2 = scores_match_staged(staged, bad_as_of)
        self.assertIsNotNone(mismatch2)
        self.assertIn("as_of", mismatch2 or "")

    def test_legacy_global_cutoff_normalizes_to_component_period(self) -> None:
        staged = {
            "version": 3,
            "scoring_cutoff": "2026-09",
            "date_semantics": {
                "scoring_cutoff": "Latest calendar month the LEVEL engine may read from history.",
            },
            "countries": {
                "US": {
                    "Inflation": {
                        "as_of": "2026-09",
                        "latest_reference_period": "2026-07",
                        "level": 63.1,
                    },
                    "Labor": {
                        "as_of": "2026-09",
                        "latest_reference_period": "2026-09",
                        "level": 51.0,
                    },
                }
            },
        }
        recomputed = {
            "version": 3,
            "as_of_representation": "component_period",
            "scoring_cutoff": "2026-09",
            "date_semantics": {
                "scoring_cutoff": (
                    "Latest calendar month present in history that a replay cutoff may include; "
                    "not the reference period every dimension card is current through."
                ),
            },
            "countries": {
                "US": {
                    "Inflation": {"as_of": "2026-07", "latest_reference_period": "2026-07", "level": 63.1},
                    "Labor": {"as_of": "2026-09", "latest_reference_period": "2026-09", "level": 51.0},
                }
            },
        }
        self.assertIsNone(scores_match_staged(staged, recomputed))

        wrong_level = copy.deepcopy(recomputed)
        wrong_level["countries"]["US"]["Inflation"]["level"] = 60.0
        self.assertIsNotNone(scores_match_staged(staged, wrong_level))

    def test_legacy_incompatible_dimension_as_of_fails(self) -> None:
        staged = {
            "scoring_cutoff": "2026-09",
            "countries": {"US": {"Labor": {"as_of": "2026-08", "latest_reference_period": "2026-09"}}},
        }
        recomputed = {"as_of_representation": "component_period", "countries": {}}
        self.assertEqual(
            scores_match_staged(staged, recomputed),
            "legacy staged scores: dimension as_of is not global scoring_cutoff",
        )


class FrozenLaunchScoresMatchTests(unittest.TestCase):
    def test_frozen_oct27_launch_scores_recompute(self) -> None:
        staged = json.loads(FROZEN_SCORES.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            hist_dir = Path(tmp) / "history"
            shutil.copytree(FROZEN_HISTORY, hist_dir)
            cal = load_calibration(CALIBRATION_PATH)
            histories = load_history(hist_dir)
            recomputed = build_score_state(cal, compute_state(cal, histories))
            self.assertIsNone(scores_match_staged(staged, recomputed))

            mutated = copy.deepcopy(staged)
            mutated["countries"]["US"]["Labor"]["component_state"]["unemployment"]["level"] = 0.0
            self.assertIsNotNone(scores_match_staged(mutated, recomputed))


if __name__ == "__main__":
    unittest.main()
