from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from scripts.temperature_level import (
    PATHS_PATH,
    build_paths,
    load_calibration,
    load_history,
    scoring_cutoff,
)
from scripts.temperature_trends import (
    add_months,
    cap_path_end,
    equal_weight_mean,
    inflation_labor_gap,
    period_change,
    proposed_composite,
    publication_month,
)

REPO = Path(__file__).resolve().parents[1]
SCORES_PATH = REPO / "data" / "temperature_scores.json"


class TemperatureTrendsCompositeTest(unittest.TestCase):
    def test_proposed_composite_weights_and_missing(self) -> None:
        full = {"Inflation": 60.0, "Labor": 40.0, "Activity": 50.0, "Consumer": 70.0}
        self.assertAlmostEqual(proposed_composite(full), 52.0)
        for missing in ("Inflation", "Labor", "Activity", "Consumer"):
            partial = dict(full)
            partial[missing] = None
            self.assertIsNone(proposed_composite(partial))

    def test_proposed_composite_not_equal_weight_mean(self) -> None:
        levels = {"Inflation": 100.0, "Labor": 0.0, "Activity": 0.0, "Consumer": 0.0}
        self.assertAlmostEqual(proposed_composite(levels), 40.0)
        self.assertAlmostEqual(equal_weight_mean(levels), 25.0)
        self.assertNotEqual(proposed_composite(levels), equal_weight_mean(levels))

    def test_inflation_labor_gap_signed_and_missing(self) -> None:
        self.assertAlmostEqual(inflation_labor_gap(72.0, 65.0), 7.0)
        self.assertAlmostEqual(inflation_labor_gap(40.0, 55.0), -15.0)
        self.assertIsNone(inflation_labor_gap(None, 50.0))
        self.assertIsNone(inflation_labor_gap(50.0, None))

    def test_period_change_requires_exact_prior_month(self) -> None:
        points = [
            {"period": "2026-07", "aggregate": 50.0},
            {"period": "2026-09", "aggregate": 55.0},
        ]
        self.assertIsNone(period_change(points, "2026-09", 1, "aggregate"))
        self.assertAlmostEqual(period_change(points, "2026-09", 2, "aggregate"), 5.0)

    def test_add_months_for_period_change(self) -> None:
        self.assertEqual(add_months("2026-09", -1), "2026-08")


class CapPathEndTest(unittest.TestCase):
    def test_cap_path_end_respects_publication_month(self) -> None:
        histories = {
            "US": {
                "components": {
                    "Inflation.core_pce": {
                        "observations": [
                            {
                                "reference_period": "2026-11",
                                "value": 0.2,
                                "transformation": "mom_sa_pct",
                                "retrieved_at": "2026-10-15T12:00:00Z",
                            }
                        ]
                    }
                }
            }
        }
        # Reference month ahead of retrieval month must not extend the graph.
        capped = cap_path_end("2026-11", histories)
        self.assertEqual(capped, "2026-10")
        self.assertEqual(publication_month(histories), "2026-10")


class RegeneratedScorePathsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cal = load_calibration()
        cls.histories = load_history()

    def test_regenerated_paths_provenance_and_window(self) -> None:
        scores_hash_before = hashlib.sha256(SCORES_PATH.read_bytes()).hexdigest()
        doc = build_paths(self.cal, self.histories)
        expected_end = cap_path_end(scoring_cutoff(self.cal, self.histories), self.histories)
        self.assertEqual(doc["window"]["end"], expected_end)
        self.assertEqual(doc["provenance"]["label"], "RECONSTRUCTED")
        self.assertEqual(doc["provenance"]["series_kind"], "reconstructed")
        for country in doc["paths"]:
            for dimension in doc["paths"][country]:
                for point in doc["paths"][country][dimension]:
                    self.assertEqual(point.get("provenance"), "reconstructed")
                    self.assertIn("source_period", point)
        on_disk = json.loads(PATHS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["provenance"]["label"], "RECONSTRUCTED")
        self.assertEqual(on_disk["window"]["end"], expected_end)
        scores_hash_after = hashlib.sha256(SCORES_PATH.read_bytes()).hexdigest()
        self.assertEqual(scores_hash_before, scores_hash_after)
        self.assertEqual(
            hashlib.sha256(SCORES_PATH.read_bytes()).hexdigest(),
            hashlib.sha256(SCORES_PATH.read_bytes()).hexdigest(),
        )

    def test_write_paths_matches_build_paths(self) -> None:
        built = build_paths(self.cal, self.histories)
        self.assertEqual(built["derived_composite"]["weights"]["Inflation"], 0.40)
        self.assertEqual(built["derived_composite"]["weights"]["Labor"], 0.40)
        on_disk = json.loads(PATHS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["paths"], built["paths"])
        self.assertEqual(on_disk["provenance"], built["provenance"])


if __name__ == "__main__":
    unittest.main()
