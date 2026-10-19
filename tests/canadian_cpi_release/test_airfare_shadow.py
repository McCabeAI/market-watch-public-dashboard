"""Tests for Canadian CPI air transportation shadow fixture and model."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.canadian_cpi_release.airfare_shadow import (
    AirfareObsIndex,
    airfare_shadow_month,
    walk_forward_airfare,
)
from scripts.canadian_cpi_release.contract import Observation
from scripts.canadian_cpi_release.ex_energy_interfaces import (
    AIRFARE_ID,
    AIRFARE_INDEX_SPEC,
    AIRFARE_WEIGHT_SPEC,
    FORBIDDEN_ACTUAL_PERIOD,
    replace_child_within_parent,
    same_month_mean,
)
from scripts.canadian_cpi_release.model import compute_moms
from scripts.canadian_cpi_release.sources.acquire import FIXTURE_ROOT, load_snapshot
from scripts.canadian_cpi_release.sources.airfare_statcan import (
    load_airfare_snapshot,
    verify_series_titles_from_info_payload,
)
from scripts.canadian_cpi_release.sources.cache import SourceError

AIRFARE_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "canadian_cpi_release"
    / "fixtures"
    / "airfare_pre_2026-10-19"
)


class AirfareShadowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cpi = load_snapshot(FIXTURE_ROOT / "snapshot.json")
        cls.airfare = load_airfare_snapshot(AIRFARE_FIXTURE_ROOT / "snapshot.json")

    def test_locked_vector_ids_match_fixture(self) -> None:
        for obs in self.airfare.observations:
            if obs.canonical_id == AIRFARE_ID:
                self.assertEqual(obs.vector_id, AIRFARE_INDEX_SPEC["vector_id"])
            elif obs.canonical_id.endswith("__weight"):
                self.assertEqual(obs.vector_id, AIRFARE_WEIGHT_SPEC["vector_id"])

    def test_no_observation_period_ge_september_2026(self) -> None:
        for obs in self.airfare.observations:
            self.assertLess(obs.period, FORBIDDEN_ACTUAL_PERIOD)

    def test_title_verification_rejects_gasoline(self) -> None:
        fake = [
            {
                "status": "SUCCESS",
                "object": {
                    "vectorId": AIRFARE_INDEX_SPEC["vector_id"],
                    "coordinate": AIRFARE_INDEX_SPEC["coordinate"],
                    "SeriesTitleEn": "Canada;Gasoline",
                },
            },
            {
                "status": "SUCCESS",
                "object": {
                    "vectorId": AIRFARE_WEIGHT_SPEC["vector_id"],
                    "coordinate": AIRFARE_WEIGHT_SPEC["coordinate"],
                    "SeriesTitleEn": "Canada;Air transportation;Weight at basket link month prices",
                },
            },
        ]
        with self.assertRaises(SourceError) as ctx:
            verify_series_titles_from_info_payload(fake)
        self.assertEqual(ctx.exception.code, "airfare_title_mismatch")

    def test_same_month_mean_10_september_2026(self) -> None:
        idx = AirfareObsIndex.build(self.airfare, "2026-10-18", "2026-09")
        levels = idx.levels_before(AIRFARE_ID)
        moms = compute_moms(levels)
        seasonal = same_month_mean(moms, "2026-09", n=10)
        self.assertIsNotNone(seasonal)
        self.assertAlmostEqual(seasonal, -11.749, delta=0.05)

    def test_replace_child_not_applied_twice(self) -> None:
        parent_mom = 0.5
        parent_share = 0.2
        child_share = 0.02
        baseline = 1.0
        replacement = -10.0
        once = replace_child_within_parent(
            parent_mom, parent_share, child_share, baseline, replacement
        )
        twice = replace_child_within_parent(
            once, parent_share, child_share, baseline, replacement
        )
        self.assertNotAlmostEqual(twice, once, places=8)

    def test_september_2026_shadow_at_as_of(self) -> None:
        out = airfare_shadow_month(self.cpi, self.airfare, "2026-09", "2026-10-18")
        self.assertTrue(all(out["moms"][k] is not None for k in out["moms"]))
        air_share = out["shares"][AIRFARE_ID]
        self.assertIsNotNone(air_share)
        self.assertAlmostEqual(air_share, 0.01333, delta=1e-4)
        self.assertAlmostEqual(out["basket_weight_2025_percent"], 1.10, delta=0.01)
        for obs in self.airfare.observations:
            if obs.canonical_id == AIRFARE_ID and obs.period == "2026-09":
                self.fail("fixture contains September 2026 airfare actual")

    def test_published_after_as_of_ineligible(self) -> None:
        snap = copy.deepcopy(self.airfare)
        snap.observations = [
            o for o in snap.observations if not (o.canonical_id == AIRFARE_ID and o.period == "2026-08")
        ]
        snap.observations.append(
            Observation(
                canonical_id=AIRFARE_ID,
                period="2026-08",
                value=999.0,
                published_at="2026-10-19T08:30:00-04:00",
                retrieved_at="2026-10-18T12:00:00Z",
                source_hash="test",
                units="index_2002_100",
                seasonal_status="NSA",
                source_url="test",
                vector_id=AIRFARE_INDEX_SPEC["vector_id"],
            )
        )
        idx = AirfareObsIndex.build(snap, "2026-10-18", "2026-09")
        self.assertIsNone(idx.level(AIRFARE_ID, "2026-08"))

    def test_walk_forward_produces_metrics(self) -> None:
        bt = walk_forward_airfare(self.cpi, self.airfare, "2026-10-18")
        self.assertGreater(len(bt["rows"]), 50)
        self.assertIn("airfare_promoted", bt)
        models = {m["model"] for m in bt["metrics"]}
        self.assertIn("same_month_mean_10", models)
        self.assertIn("airfare_on_direct", models)


if __name__ == "__main__":
    unittest.main()
