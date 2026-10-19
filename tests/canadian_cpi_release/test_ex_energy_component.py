"""Offline tests for Canadian ex-energy component nowcast (C1)."""

from __future__ import annotations

import copy
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.canadian_cpi_release.contract import Observation
from scripts.canadian_cpi_release.ex_energy_component import (
    component_ex_energy_nowcast,
    month_actual_ex_energy_mom,
    walk_forward_ex_energy,
)
from scripts.canadian_cpi_release.ex_energy_interfaces import (
    CANONICAL_BASKET_LINK,
    CANONICAL_BASKET_YEAR,
    CANONICAL_EX_ENERGY_NSA_MOM,
    CANONICAL_EX_ENERGY_YOY,
    EX_ENERGY_ID,
    EX_FOOD_ENERGY_ID,
    FOOD_ID,
    combine_partition_mom,
)
from scripts.canadian_cpi_release.sources.acquire import FIXTURE_ROOT, load_snapshot

FIXTURE_PATH = FIXTURE_ROOT / "snapshot.json"


def _load_fixture():
    return load_snapshot(FIXTURE_PATH)


class ExEnergyComponentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _load_fixture()

    def test_september_2026_direct_matches_canonical(self) -> None:
        for as_of in ("2026-10-18", "2026-10-16"):
            out = component_ex_energy_nowcast(self.snapshot, "2026-09", as_of)
            self.assertEqual(out["status"], "ok")
            self.assertEqual(out["basket_year"], CANONICAL_BASKET_YEAR)
            self.assertEqual(out["basket_link"], CANONICAL_BASKET_LINK)
            direct = out["forecasts"]["direct"]
            self.assertAlmostEqual(
                direct["nsa_mom"], CANONICAL_EX_ENERGY_NSA_MOM, delta=1e-12
            )
            self.assertAlmostEqual(direct["yoy"], CANONICAL_EX_ENERGY_YOY, delta=1e-12)

    def test_component_partition_not_double_count(self) -> None:
        out = component_ex_energy_nowcast(self.snapshot, "2026-09", "2026-10-18")
        shares = out["shares"]
        bw = out["basket_weight_percent"]
        self.assertAlmostEqual(
            shares["partition_sum"],
            shares["food"] + shares["ex_food_energy"],
            places=12,
        )
        self.assertLess(abs(bw["weight_gap"]), 0.02)
        for key in ("component", "blend_equal"):
            mom = out["forecasts"][key]["nsa_mom"]
            self.assertTrue(math.isfinite(mom))
            self.assertNotAlmostEqual(
                mom,
                out["forecasts"]["direct"]["nsa_mom"] + shares["food"],
                places=3,
            )

    def test_future_actual_ignored(self) -> None:
        clean = component_ex_energy_nowcast(self.snapshot, "2026-09", "2026-10-18")
        snap = copy.deepcopy(self.snapshot)
        snap.observations = list(snap.observations)
        pub = "2026-10-19T12:00:00-04:00"
        for cid in (FOOD_ID, EX_FOOD_ENERGY_ID, EX_ENERGY_ID):
            snap.observations.append(
                Observation(
                    canonical_id=cid,
                    period="2026-09",
                    value=100.0,
                    published_at=pub,
                    retrieved_at="2026-10-19T00:00:00Z",
                    source_hash="fake",
                    units="index_2002_100",
                    seasonal_status="NSA",
                    source_url="fixture",
                    vector_id=1,
                    table_pid=18100004,
                    status="official",
                )
            )
        polluted = component_ex_energy_nowcast(snap, "2026-09", "2026-10-18")
        for model in ("direct", "component", "blend_equal"):
            self.assertAlmostEqual(
                polluted["forecasts"][model]["nsa_mom"],
                clean["forecasts"][model]["nsa_mom"],
                places=12,
            )

    def test_identity_recent_mae_september_2026(self) -> None:
        out = component_ex_energy_nowcast(self.snapshot, "2026-09", "2026-10-18")
        ident = out["identity"]
        self.assertIsNone(ident["residual_mom"])
        self.assertIsNotNone(ident["recent_mae"])
        self.assertTrue(math.isfinite(ident["recent_mae"]))
        self.assertGreater(ident["recent_n"], 0)

    def test_short_walk_forward_excludes_september_2026(self) -> None:
        bt = walk_forward_ex_energy(
            self.snapshot, "2026-10-18", start="2026-01", end="2026-08"
        )
        periods = {r["period"] for r in bt["rows"]}
        self.assertNotIn("2026-09", periods)
        direct_metrics = [
            m for m in bt["metrics"] if m["model"] == "direct" and m["regime"] == "all"
        ]
        self.assertTrue(direct_metrics)
        self.assertGreater(direct_metrics[0]["n"], 0)

    def test_component_mom_matches_combine_helper(self) -> None:
        out = component_ex_energy_nowcast(self.snapshot, "2026-09", "2026-10-18")
        shares = out["shares"]
        from scripts.canadian_cpi_release.engine import ObsIndex
        from scripts.canadian_cpi_release.model import compute_moms, forecast_model_a

        idx = ObsIndex.build(self.snapshot, "2026-10-18", "2026-09")
        mom_food, _ = forecast_model_a(compute_moms(idx.levels_before(FOOD_ID)), "2026-09")
        mom_exfe, _ = forecast_model_a(
            compute_moms(idx.levels_before(EX_FOOD_ENERGY_ID)), "2026-09"
        )
        expected = combine_partition_mom(
            shares["food"], mom_food, shares["ex_food_energy"], mom_exfe
        )
        self.assertAlmostEqual(
            out["forecasts"]["component"]["nsa_mom"], expected, places=12
        )


if __name__ == "__main__":
    unittest.main()
