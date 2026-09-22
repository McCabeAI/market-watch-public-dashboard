from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.country_registry import temperature_countries
from scripts.temperature_level import (
    PATHS_PATH,
    all_levels,
    build_paths,
    build_score_state,
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

_COMPONENT_STATE_KEYS = ("observed", "as_of", "transform_value", "level", "impulse")
_DIMENSION_SCORE_KEYS = (
    "level",
    "impulse",
    "direction",
    "coverage",
    "temperature_class",
    "component_state",
)


def _component_state_slice(component_state: dict) -> dict:
    return {
        name: {k: comp.get(k) for k in _COMPONENT_STATE_KEYS}
        for name, comp in component_state.items()
    }


def _dimension_scores_from_state(state: dict) -> dict:
    out: dict = {}
    for country in temperature_countries():
        out[country] = {}
        for dim in ("Inflation", "Labor", "Activity", "Consumer"):
            spec = state["countries"][country][dim]
            out[country][dim] = {
                k: spec[k] if k != "component_state" else _component_state_slice(spec["component_state"])
                for k in _DIMENSION_SCORE_KEYS
            }
    return out


class TemperatureLevelEngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cal = load_calibration()
        cls.histories = load_history()

    def test_twenty_four_dimensions_and_score_range(self) -> None:
        state = load_state()
        countries = temperature_countries()
        self.assertEqual(len(countries) * 4, 24)
        for country in countries:
            for dim in ("Inflation", "Labor", "Activity", "Consumer"):
                spec = state["countries"][country][dim]
                lvl = spec["level"]
                if lvl is None:
                    self.assertLess(float(spec["coverage"]), 1.0)
                    continue
                self.assertGreaterEqual(lvl, 1.0)
                self.assertLessEqual(lvl, 100.0)

    def test_validate_score_sources_passes(self) -> None:
        state = load_state()
        registry = json.loads((REPO / "data" / "score_source_registry.json").read_text())
        errors = validate_registry(state, registry)
        self.assertEqual(errors, [])

    def test_us_inflation_uses_three_month_core_pce_annualized(self) -> None:
        """Smoke: live history produces a scored US Inflation dimension (not pinned to a BEA vintage)."""
        state = load_state()
        inf = state["countries"]["US"]["Inflation"]
        self.assertAlmostEqual(inf["coverage"], 1.0)
        self.assertIsNotNone(inf["level"])
        self.assertGreaterEqual(float(inf["level"]), 1.0)
        self.assertLessEqual(float(inf["level"]), 100.0)
        core = inf["component_state"]["core_pce"]
        self.assertTrue(core["observed"])
        self.assertIsNotNone(core["transform_value"])
        self.assertIsNotNone(core["level"])

    def test_state_on_disk_matches_engine(self) -> None:
        computed = compute_state(self.cal, self.histories, cutoff="2026-09")
        engine_doc = build_score_state(self.cal, computed)
        disk = load_state()
        self.assertEqual(
            _dimension_scores_from_state(engine_doc),
            _dimension_scores_from_state(disk),
        )
        engine_paths = build_paths(self.cal, self.histories)
        disk_paths = json.loads(PATHS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(engine_paths["paths"], disk_paths["paths"])
        self.assertEqual(engine_paths["pathology"], disk_paths["pathology"])

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


class ActivityTransformTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cal = load_calibration()
        cls.histories = load_history()

    def test_gdp_level_two_quarter_mean_saar_and_impulse_one_quarter(self) -> None:
        for cc in ("US", "CA", "AU", "NZ", "EA", "JP"):
            spec = self.cal["components"][f"{cc}.Activity.gdp_domestic_demand"]
            res = score_component(self.histories[cc], spec, self.cal, "2026-09", 0.6)
            self.assertTrue(res.observed, cc)
            self.assertIsNotNone(res.level)
            if cc == "CA":
                self.assertAlmostEqual(res.level, 50.2, delta=0.3)
                self.assertAlmostEqual(res.impulse or 0, 28.4, delta=0.5)
            if cc == "NZ":
                self.assertAlmostEqual(res.level, 52.2, delta=0.3)
                self.assertAlmostEqual(res.impulse or 0, -28.5, delta=0.5)

    def test_us_survey_three_month_level_and_month_impulse(self) -> None:
        for comp in ("services_surveys", "manufacturing_surveys"):
            spec = self.cal["components"][f"US.Activity.{comp}"]
            res = score_component(self.histories["US"], spec, self.cal, "2026-08", 0.28)
            self.assertTrue(res.observed)
            # Jun-Jul-Aug 2026 services: 54.0, 54.1, 55.4 -> mean 54.5
            if comp == "services_surveys":
                self.assertAlmostEqual(res.transform_value or 0, 54.5, delta=0.05)
                self.assertAlmostEqual(res.impulse or 0, 1.3, delta=0.05)

    def test_us_activity_weights_unchanged(self) -> None:
        weights = self.cal["weights"]["US"]["Activity"]
        self.assertAlmostEqual(weights["gdp_domestic_demand"], 0.6)
        self.assertAlmostEqual(weights["services_surveys"], 0.28)
        self.assertAlmostEqual(weights["manufacturing_surveys"], 0.12)

    def test_ivey_not_scored_when_conflict_series_only(self) -> None:
        spec = self.cal["components"]["CA.Activity.business_surveys"]
        history = copy.deepcopy(self.histories["CA"])
        comp = history["components"]["Activity.business_surveys"]
        comp["observations"] = [
            {
                "reference_period": "2026-08",
                "value": 60.0,
                "units": "diffusion_index",
                "transformation": "diffusion_index",
                "publisher": "Ivey",
                "source_url": "https://www.iveypmi.ca/",
                "vintage": "test",
                "retrieved_at": "2026-09-21",
                "series_id": "Ivey_PMI_conflict",
            }
        ]
        res = score_component(history, spec, self.cal, "2026-09", 0.4)
        self.assertFalse(res.observed)

    def test_ca_au_nz_surveys_scored_from_primary_series(self) -> None:
        computed = compute_state(self.cal, self.histories, cutoff="2026-09")
        for cc, sid in (
            ("CA", "SP_GLOBAL_CA_COMPOSITE"),
            ("AU", "SP_GLOBAL_AU_COMPOSITE_PMI"),
            ("NZ", "BUSINESSNZ_PCI_GDP_WEIGHTED"),
        ):
            act = computed["countries"][cc]["Activity"]
            self.assertAlmostEqual(act["coverage"], 1.0, places=3, msg=cc)
            bs = act["component_state"]["business_surveys"]
            self.assertTrue(bs["observed"], cc)
            self.assertIsNotNone(bs["level"])
            spec = self.cal["components"][f"{cc}.Activity.business_surveys"]
            self.assertEqual(spec["series_id"], sid)
            self.assertNotEqual(spec.get("observed"), False)

        ca_spec = self.cal["components"]["CA.Activity.business_surveys"]
        ivey_rows = [
            o
            for o in self.histories["CA"]["components"]["Activity.business_surveys"]["observations"]
            if o.get("series_id") == "Ivey_PMI_conflict"
        ]
        self.assertGreaterEqual(len(ivey_rows), 12)
        scored = raw_values_by_period(self.histories["CA"], ca_spec, "2026-09")
        self.assertIn("2026-08", scored)
        self.assertAlmostEqual(scored["2026-08"], 47.8)
        ivey_aug = next(o for o in ivey_rows if o["reference_period"] == "2026-08")
        self.assertEqual(ivey_aug["value"], 64.3)
        self.assertNotEqual(scored["2026-08"], ivey_aug["value"])
        self.assertIn("2026-05", scored)
        ca_notes = self.histories["CA"]["components"]["Activity.business_surveys"].get("notes", "")
        self.assertIn("S&P Global Canada Composite", ca_notes)
        self.assertNotIn("Scored target: CFIB", ca_notes)

        for cc, sid in (
            ("EA", "SP_GLOBAL_EA_COMPOSITE_PMI"),
            ("JP", "SP_GLOBAL_JP_COMPOSITE_PMI"),
        ):
            spec = self.cal["components"][f"{cc}.Activity.business_surveys"]
            self.assertEqual(spec["series_id"], sid)
            act = computed["countries"][cc]["Activity"]
            gdp = act["component_state"]["gdp_domestic_demand"]
            self.assertTrue(gdp["observed"], cc)
            bs = act["component_state"]["business_surveys"]
            if bs["observed"]:
                self.assertIsNotNone(bs["level"])

    def test_gapped_survey_months_are_explicit_not_fabricated(self) -> None:
        ca_comp = self.histories["CA"]["components"]["Activity.business_surveys"]
        gap_periods = {g["expected_period"] for g in ca_comp["gaps"]}
        self.assertIn("2026-09", gap_periods)
        scored_ids = {
            o["source_url"]
            for o in ca_comp["observations"]
            if o.get("series_id") == "SP_GLOBAL_CA_COMPOSITE"
        }
        for url in scored_ids:
            self.assertFalse("tradingeconomics" in url.lower())
            self.assertFalse("reddit.com" in url.lower())
        for cc, sid in (
            ("AU", "SP_GLOBAL_AU_COMPOSITE_PMI"),
            ("NZ", "BUSINESSNZ_PCI_GDP_WEIGHTED"),
        ):
            urls = {
                o["source_url"]
                for o in self.histories[cc]["components"]["Activity.business_surveys"]["observations"]
                if o.get("series_id") == sid
            }
            for url in urls:
                self.assertFalse("tradingeconomics" in url.lower(), url)
                self.assertFalse("reddit.com" in url.lower(), url)
                self.assertFalse("reuters.com" in url.lower(), url)


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
        res = score_component(history, spec, cal, "2026-07", 1.0)
        self.assertTrue(res.observed)
        self.assertAlmostEqual(res.transform_value or 0, 2.426, places=2)
        self.assertAlmostEqual(res.level or 0, 55.33, places=1)
        second = score_component(history, spec, cal, "2026-07", 1.0)
        self.assertEqual(res.level, second.level)


class JapanConsumerCalibrationTest(unittest.TestCase):
    """JP Consumer: 3-month LEVEL on monthly flows; identity IMPULSE; CCI SA mean 38.1."""

    FLOW_KEYS = ("JP.Consumer.retail", "JP.Consumer.income", "JP.Consumer.spending")

    @classmethod
    def setUpClass(cls) -> None:
        cls.cal = load_calibration()
        cls.histories = load_history()

    def test_consumer_weights_unchanged(self) -> None:
        weights = self.cal["weights"]["JP"]["Consumer"]
        self.assertEqual(
            weights,
            {"retail": 0.25, "income": 0.25, "spending": 0.25, "confidence": 0.25},
        )

    def test_flow_level_is_trailing_mean_impulse_is_identity(self) -> None:
        for key in self.FLOW_KEYS:
            spec = self.cal["components"][key]
            self.assertEqual(spec["level_scoring_transform"], "trailing_mean_n3", key)
            self.assertEqual(spec["impulse_scoring_transform"], "identity", key)
            self.assertEqual(spec["n_periods"], 3, key)
            self.assertEqual(spec["anchor"], 2.6, key)
            self.assertEqual(spec["scale_per_unit"], 12.5, key)

    def test_confidence_anchor_is_current_methodology_mean_not_fifty(self) -> None:
        spec = self.cal["components"]["JP.Consumer.confidence"]
        self.assertEqual(spec["level_scoring_transform"], "identity")
        self.assertEqual(spec["impulse_scoring_transform"], "identity")
        self.assertAlmostEqual(float(spec["anchor"]), 38.1)
        self.assertNotEqual(float(spec["anchor"]), 50.0)
        self.assertIn("2013-04", spec["anchor_meaning"])
        self.assertIn("38.1", spec["anchor_meaning"])

    def test_live_income_level_uses_three_month_mean_not_latest_print(self) -> None:
        spec = self.cal["components"]["JP.Consumer.income"]
        res = score_component(self.histories["JP"], spec, self.cal, "2026-09", 0.25)
        values = raw_values_by_period(self.histories["JP"], spec, "2026-09")
        self.assertAlmostEqual(values["2026-07"], -1.7)
        expected_mean = (values["2026-05"] + values["2026-06"] + values["2026-07"]) / 3.0
        self.assertAlmostEqual(res.transform_value or 0, expected_mean, places=4)
        self.assertNotAlmostEqual(res.transform_value or 0, -1.7, places=2)
        identity_level = component_level(-1.7, spec, self.cal)
        self.assertAlmostEqual(identity_level, 1.0)
        self.assertGreater(res.level or 0, 20.0)
        prior_level = component_level(values["2026-06"], spec, self.cal)
        latest_identity_level = component_level(values["2026-07"], spec, self.cal)
        self.assertAlmostEqual(res.impulse or 0, latest_identity_level - prior_level, places=2)

    def test_single_weak_fies_print_does_not_floor_level(self) -> None:
        """Regression: a one-month FIES collapse must not revert LEVEL to single-print flooring."""
        spec = copy.deepcopy(self.cal["components"]["JP.Consumer.income"])
        history = {
            "country": "JP",
            "components": {
                "Consumer.income": {
                    "observations": [
                        {
                            "reference_period": "2026-05",
                            "value": 2.6,
                            "transformation": "yoy_pct",
                            "series_id": "FIES_WORKER_HH_REAL_INCOME_NOMINAL_YOY",
                        },
                        {
                            "reference_period": "2026-06",
                            "value": 2.6,
                            "transformation": "yoy_pct",
                            "series_id": "FIES_WORKER_HH_REAL_INCOME_NOMINAL_YOY",
                        },
                        {
                            "reference_period": "2026-07",
                            "value": -10.0,
                            "transformation": "yoy_pct",
                            "series_id": "FIES_WORKER_HH_REAL_INCOME_NOMINAL_YOY",
                        },
                    ]
                }
            },
        }
        res = score_component(history, spec, self.cal, "2026-07", 0.25)
        self.assertAlmostEqual(res.transform_value or 0, (2.6 + 2.6 - 10.0) / 3.0, places=4)
        self.assertGreater(res.level or 0, 1.01)
        identity_floor = component_level(-10.0, spec, self.cal)
        self.assertAlmostEqual(identity_floor, 1.0)
        self.assertGreater(res.level or 0, identity_floor)
        prior_identity = component_level(2.6, spec, self.cal)
        self.assertAlmostEqual(res.impulse or 0, identity_floor - prior_identity, places=2)

        identity_spec = copy.deepcopy(spec)
        identity_spec.pop("level_scoring_transform")
        identity_spec.pop("impulse_scoring_transform")
        identity_spec["scoring_transform"] = "identity"
        reverted = score_component(history, identity_spec, self.cal, "2026-07", 0.25)
        self.assertAlmostEqual(reverted.level or 0, 1.0)
        self.assertNotAlmostEqual(res.level or 0, reverted.level or 0, places=1)

    def test_reconstructed_path_reduces_fies_sawtooth(self) -> None:
        paths = build_paths(self.cal, self.histories)
        series = paths["paths"]["JP"]["Consumer"]
        levels = [float(row["level"]) for row in series if row["level"] is not None]
        self.assertEqual([row["period"] for row in series], [
            "2025-09",
            "2025-10",
            "2025-11",
            "2025-12",
            "2026-01",
            "2026-02",
            "2026-03",
            "2026-04",
            "2026-05",
            "2026-06",
            "2026-07",
            "2026-08",
            "2026-09",
        ])
        jumps = [abs(b - a) for a, b in zip(levels, levels[1:])]
        self.assertTrue(jumps)
        self.assertLess(max(jumps), 12.0, f"JP Consumer still sawtoothing: {levels}")
        # Pre-repair path printed 26.1 / 26.25 from FIES floors; smoothed LEVEL stays off the clip.
        self.assertGreater(min(levels), 26.5)
        latest = series[-1]
        self.assertAlmostEqual(float(latest["level"]), 38.0, delta=1.0)
        jp_consumer_findings = [
            f
            for f in paths["pathology"]["findings"]
            if f.get("country") == "JP" and f.get("dimension") == "Consumer"
        ]
        self.assertEqual(jp_consumer_findings, [])


if __name__ == "__main__":
    unittest.main()
