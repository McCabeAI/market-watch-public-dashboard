from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.temperature_level import (
    all_levels,
    build_paths,
    component_level,
    compute_state,
    load_calibration,
    load_history,
    load_state,
    raw_values_by_period,
    score_component,
    transform_at_period,
    write_state,
)
from scripts.validate_score_sources import validate_registry

REPO = Path(__file__).resolve().parents[1]


class TemperatureLevelEngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cal = load_calibration()
        cls.histories = load_history()

    def test_sixteen_dimensions_and_score_range(self) -> None:
        state = load_state()
        for country in ("US", "CA", "AU", "NZ"):
            for dim in ("Inflation", "Labor", "Activity", "Consumer"):
                spec = state["countries"][country][dim]
                lvl = spec["level"]
                self.assertIsNotNone(lvl)
                self.assertGreaterEqual(lvl, 1.0)
                self.assertLessEqual(lvl, 100.0)

    def test_validate_score_sources_passes(self) -> None:
        state = load_state()
        registry = json.loads((REPO / "data" / "score_source_registry.json").read_text())
        errors = validate_registry(state, registry)
        self.assertEqual(errors, [])

    def test_us_inflation_uses_three_month_core_pce_annualized(self) -> None:
        spec = self.cal["components"]["US.Inflation.core_pce"]
        res = score_component(self.histories["US"], spec, self.cal, "2026-09", 1.0)
        self.assertTrue(res.observed)
        self.assertAlmostEqual(res.transform_value or 0, 3.047776, places=3)
        self.assertAlmostEqual(res.level or 0, 63.1, places=1)

    def test_ca_underlying_equal_mean_trim_median(self) -> None:
        spec = self.cal["components"]["CA.Inflation.underlying"]
        values = raw_values_by_period(self.histories["CA"], spec, "2026-08")
        self.assertAlmostEqual(values["2026-08"], 1.95, places=2)

    def test_nz_gdp_pins_production_series_only(self) -> None:
        spec = self.cal["components"]["NZ.Activity.gdp_domestic_demand"]
        values = raw_values_by_period(self.histories["NZ"], spec, "2026-09")
        self.assertIn("2026-Q2", values)
        self.assertAlmostEqual(values["2026-Q2"], 0.2, places=3)
        for sid in ("SNEQ.SG02RSC31B15PC",):
            rows = [
                o
                for o in self.histories["NZ"]["components"][spec["history_key"]]["observations"]
                if o.get("series_id") == sid and o["transformation"] == spec["source_transformation"]
            ]
            self.assertTrue(rows, "expenditure GDP exists in history but must not be scored")

    def test_missing_component_reduces_coverage_not_fifty(self) -> None:
        computed = compute_state(self.cal, self.histories, cutoff="2026-09")
        au_consumer = computed["countries"]["AU"]["Consumer"]
        self.assertAlmostEqual(au_consumer["coverage"], 0.75, places=3)
        retail = au_consumer["component_state"]["retail"]
        self.assertFalse(retail["observed"])
        self.assertNotIn(retail.get("level"), (50, 50.0))

    def test_level_stable_when_no_new_observations(self) -> None:
        histories = copy.deepcopy(self.histories)
        histories["US"]["components"]["Inflation.core_pce"]["observations"].append(
            {
                "reference_period": "2099-12",
                "value": 999.0,
                "units": "index",
                "transformation": "index_level",
                "publisher": "test",
                "source_url": "data/test",
                "vintage": "test",
                "retrieved_at": "2099-01-01",
                "series_id": "PCEPILFE",
            }
        )
        a = compute_state(self.cal, self.histories, cutoff="2026-09")
        b = compute_state(self.cal, histories, cutoff="2026-09")
        self.assertEqual(
            all_levels(a),
            all_levels(b),
        )

    def test_reproducibility_from_fixture_history(self) -> None:
        fixture_dir = REPO / "tests" / "fixtures" / "temperature_level"
        if not fixture_dir.is_dir():
            self.skipTest("fixture directory not present")
        cal = json.loads((fixture_dir / "calibration.json").read_text())
        histories = {
            "US": json.loads((fixture_dir / "us.json").read_text()),
        }
        first = compute_state(cal, histories, cutoff="2026-06")
        second = compute_state(cal, histories, cutoff="2026-06")
        self.assertEqual(
            first["countries"]["US"]["Inflation"]["level"],
            second["countries"]["US"]["Inflation"]["level"],
        )

    def test_mapped_bridge_not_in_us_inflation_coverage(self) -> None:
        state = load_state()
        inf = state["countries"]["US"]["Inflation"]
        self.assertEqual(set(inf["components"]), {"core_pce"})
        self.assertAlmostEqual(inf["coverage"], 1.0)

    def test_write_state_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "temperature_scores.json"
            cal = load_calibration()
            computed = compute_state(cal, self.histories, cutoff="2026-09")
            from scripts.temperature_level import build_score_state, validate_state

            doc = build_score_state(cal, computed)
            validate_state(doc)
            path.write_text(json.dumps(doc), encoding="utf-8")
            loaded = json.loads(path.read_text())
            validate_state(loaded)


class TemperatureLevelFixtureTest(unittest.TestCase):
    """Inline minimal fixture for reproducibility without external files."""

    def test_minimal_us_inflation_reproducible(self) -> None:
        cal = load_calibration()
        history = {
            "country": "US",
            "window": {"start": "2025-09-21", "end": "2026-09-21"},
            "components": {
                "Inflation.core_pce": {
                    "observations": [
                        {
                            "reference_period": "2026-05",
                            "value": 0.1,
                            "transformation": "mom_sa_pct",
                            "series_id": "PCEPILFE",
                        },
                        {
                            "reference_period": "2026-06",
                            "value": 0.2,
                            "transformation": "mom_sa_pct",
                            "series_id": "PCEPILFE",
                        },
                        {
                            "reference_period": "2026-07",
                            "value": 0.3,
                            "transformation": "mom_sa_pct",
                            "series_id": "PCEPILFE",
                        },
                    ]
                }
            },
        }
        spec = cal["components"]["US.Inflation.core_pce"]
        a = score_component(history, spec, cal, "2026-07", 1.0)
        b = score_component(history, spec, cal, "2026-07", 1.0)
        self.assertEqual(a.level, b.level)
        self.assertIsNotNone(a.level)


if __name__ == "__main__":
    unittest.main()
