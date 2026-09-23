"""Catalog observation-key priority and the Australia trimmed-mean score path."""

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

from scripts.macro_ingestion.contract import (
    ScoredSeriesKeyCollision,
    load_catalog,
    lookup_series_by_observation_key,
)
from scripts.macro_ingestion.score_bridge import (
    points_from_observation_stores,
    recompute_scores_after_observation,
)
from scripts.temperature_level import CALIBRATION_PATH, HISTORY_DIR, load_history

AU_HISTORY = HISTORY_DIR / "au.json"


class TestCatalogObservationKey(unittest.TestCase):
    def test_scored_outranks_later_alias(self) -> None:
        catalog = load_catalog()
        lookup = lookup_series_by_observation_key(catalog["series"])
        trimmed = lookup[("AU", "A130400382R", "yoy_pct")]
        self.assertEqual(trimmed["id"], "AU.Inflation.underlying")
        self.assertEqual(trimmed["role"], "scored")
        retail = lookup[("AU", "A3348586T", "mom_sa_pct")]
        self.assertEqual(retail["id"], "AU.Consumer.retail")
        self.assertEqual(retail["role"], "scored")

    def test_two_scored_rows_fail_closed(self) -> None:
        rows = [
            {
                "id": "AU.Inflation.left",
                "country": "AU",
                "series_id": "A130400382R",
                "transform": "yoy_pct",
                "role": "scored",
            },
            {
                "id": "AU.Inflation.right",
                "country": "AU",
                "series_id": "A130400382R",
                "transform": "yoy_pct",
                "role": "scored",
            },
        ]
        with self.assertRaises(ScoredSeriesKeyCollision):
            lookup_series_by_observation_key(rows)

    def test_au_underlying_store_updates_score_path(self) -> None:
        before_cal = CALIBRATION_PATH.read_bytes()
        before_au = hashlib.sha256(AU_HISTORY.read_bytes()).hexdigest()
        catalog = load_catalog()
        histories = load_history(HISTORY_DIR)
        working = copy.deepcopy(histories)
        with tempfile.TemporaryDirectory() as tmp:
            obs = Path(tmp) / "observations"
            obs.mkdir()
            store = {
                "country": "AU",
                "observations": [
                    {
                        "series_id": "A130400382R",
                        "period": "2026-08",
                        "value": 3.4,
                        "transformation": "yoy_pct",
                        "revision_status": "final",
                        "source_url": "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/consumer-price-index-australia",
                        "raw_sha256": "fixture-au-underlying-2026-08",
                        "retrieved_at": "2026-09-24T01:30:00Z",
                        "release_date": "2026-09-24",
                    },
                    {
                        "series_id": "A3348586T",
                        "period": "2026-08",
                        "value": 0.2,
                        "transformation": "mom_sa_pct",
                        "revision_status": "final",
                        "raw_sha256": "fixture-au-retail",
                        "retrieved_at": "2026-09-24T01:30:00Z",
                    },
                ],
            }
            (obs / "au.json").write_text(json.dumps(store), encoding="utf-8")
            points = points_from_observation_stores(
                observations_dir=obs,
                catalog=catalog,
                checked_at="2026-09-24T01:30:00Z",
            )
            underlying = next(p for p in points if p["series_id"] == "A130400382R")
            self.assertEqual(underlying["catalog_id"], "AU.Inflation.underlying")
            self.assertEqual(underlying["role"], "scored")
            retail = next(p for p in points if p["series_id"] == "A3348586T")
            self.assertEqual(retail["catalog_id"], "AU.Consumer.retail")
            self.assertEqual(retail["role"], "scored")

            result = recompute_scores_after_observation(
                points=points,
                histories=working,
                persist_history=False,
                persist_scores=False,
                checked_at="2026-09-24T01:30:00Z",
            )
            self.assertTrue(result.ok, result.score_recompute)
            reasons = {row["id"]: row["reason"] for row in result.merge["skipped"]}
            self.assertEqual(reasons.get("AU.Consumer.retail"), "retired_unobserved")
            appended_ids = [row["id"] for row in result.merge["appended"]]
            self.assertIn("AU.Inflation.underlying", appended_ids)
            self.assertNotIn("AU.Consumer.retail", appended_ids)

            observations = working["AU"]["components"]["Inflation.underlying"]["observations"]
            latest = observations[-1]
            self.assertEqual(latest["reference_period"], "2026-08")
            self.assertEqual(latest["value"], 3.4)
            self.assertEqual(latest["series_id"], "A130400382R")

            state = result.state["countries"]["AU"]["Inflation"]["component_state"]["underlying"]
            self.assertEqual(state["as_of"], "2026-08")
            self.assertEqual(state["transform_value"], 3.4)
            self.assertEqual(state["level"], 61.25)
            retail_obs = working["AU"]["components"]["Consumer.retail"]["observations"]
            self.assertFalse(any(row.get("reference_period") == "2026-08" for row in retail_obs))
            retail_state = result.state["countries"]["AU"]["Consumer"]["component_state"]["retail"]
            self.assertFalse(retail_state["observed"])
            self.assertIsNone(retail_state["as_of"])

        self.assertEqual(CALIBRATION_PATH.read_bytes(), before_cal)
        self.assertEqual(hashlib.sha256(AU_HISTORY.read_bytes()).hexdigest(), before_au)


if __name__ == "__main__":
    unittest.main()
