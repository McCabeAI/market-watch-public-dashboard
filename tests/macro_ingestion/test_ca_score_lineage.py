"""CA StatCan source-to-score identity mapping and Oct 15 2026 launch replay."""

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
from scripts.market_watch_launch.lineage import stage_verified_lineage
from scripts.temperature_level import CALIBRATION_PATH, load_calibration, load_history

LAUNCH = ROOT / "data/market_watch_launches/mwl-20261015T085222Z-b4bbe448"
OBS_DIR = LAUNCH / "ingestion/observations"
CHECKED_AT = "2026-10-15T08:52:22Z"
HISTORY_DIR = ROOT / "data" / "temperature_history"
SCORES_PATH = ROOT / "data" / "temperature_scores.json"

GDP_COMBINED = "monthly_v65201210;quarterly_v1594571783"
GDP_COMPOUND_TF = "mom_sa_pct_and_qoq_sa_pct"
GDP_SCORING_SERIES = "GDP_real_market_prices_qq_v1594571783"
GDP_SCORING_TF = "qoq_sa_pct"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _obs_by_series_period(
    store: dict, series_id: str, period: str, transformation: str | None = None
) -> dict:
    for obs in store.get("observations") or []:
        if obs.get("series_id") != series_id or obs.get("period") != period:
            continue
        if transformation is not None and obs.get("transformation") != transformation:
            continue
        return obs
    raise AssertionError(f"missing {series_id} {period} {transformation}")


class CaScoreLineageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cal_sha = _sha256_file(CALIBRATION_PATH)
        cls.ca_hist_sha = _sha256_file(HISTORY_DIR / "ca.json")
        cls.scores_sha = _sha256_file(SCORES_PATH)
        cls.artifact = json.loads((LAUNCH / "artifacts" / "01_ingest.json").read_text(encoding="utf-8"))
        cls.ca_store = json.loads((OBS_DIR / "ca.json").read_text(encoding="utf-8"))

    def test_raw_blocking_observations_match_fixture(self) -> None:
        rejections = {r["id"]: r for r in self.artifact["lineage"]["rejections"]}
        self.assertEqual(
            rejections["CA.Activity.gdp_domestic_demand"],
            {
                "id": "CA.Activity.gdp_domestic_demand",
                "period": "2026-07",
                "reason": "partial_transform_mismatch",
                "series_id": GDP_COMBINED,
                "transformation": GDP_COMPOUND_TF,
            },
        )
        self.assertEqual(
            rejections["CA.Labor.employment"],
            {
                "id": "CA.Labor.employment",
                "period": "2026-09",
                "reason": "partial_series_mismatch",
                "series_id": "v2062811_derived_mom_change",
                "transformation": "mom_sa_change_thousands",
            },
        )
        self.assertEqual(
            rejections["CA.Labor.unemployment"],
            {
                "id": "CA.Labor.unemployment",
                "period": "2026-09",
                "reason": "partial_series_mismatch",
                "series_id": "v2062815",
                "transformation": "percent",
            },
        )
        self.assertEqual(
            rejections["CA.Labor.wages"],
            {
                "id": "CA.Labor.wages",
                "period": "2026-09",
                "reason": "partial_series_mismatch",
                "series_id": "v105812645_derived_yoy",
                "transformation": "yoy_pct",
            },
        )
        gdp_m = _obs_by_series_period(self.ca_store, GDP_COMBINED, "2026-07", GDP_COMPOUND_TF)
        self.assertAlmostEqual(float(gdp_m["value"]), -0.00484846236286085)

        gdp_q = _obs_by_series_period(self.ca_store, GDP_COMBINED, "2026-Q2", GDP_COMPOUND_TF)
        self.assertAlmostEqual(float(gdp_q["value"]), 0.8)

        emp = _obs_by_series_period(
            self.ca_store, "v2062811_derived_mom_change", "2026-09", "mom_sa_change_thousands"
        )
        self.assertAlmostEqual(float(emp["value"]), -68.29999999999927)
        self.assertEqual(rejections["CA.Labor.employment"]["series_id"], "v2062811_derived_mom_change")

        unemp = _obs_by_series_period(self.ca_store, "v2062815", "2026-09", "percent")
        self.assertAlmostEqual(float(unemp["value"]), 6.5)

        wages = _obs_by_series_period(self.ca_store, "v105812645_derived_yoy", "2026-09", "yoy_pct")
        self.assertAlmostEqual(float(wages["value"]), 2.338227297444262)

    def test_oct15_observation_store_lineage_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            launch_dir = Path(tmp) / "launch"
            launch_dir.mkdir()
            result = stage_verified_lineage(
                launch_dir=launch_dir,
                checked_at=CHECKED_AT,
                canonical_history_dir=HISTORY_DIR,
                calibration_path=CALIBRATION_PATH,
                observations_dir=OBS_DIR,
                mode="live",
            )
            self.assertTrue(result["ok"], msg=result.get("error"))
            self.assertNotEqual(result.get("error"), "score_lineage_rejected")
            self.assertEqual(result.get("rejections") or [], [])
            self.assertGreaterEqual(result["appended_count"], 5)

            appended = result["appended_points"]
            by_id = {p["catalog_id"]: p for p in appended}

            self.assertIn("CA.Labor.employment", by_id)
            self.assertEqual(by_id["CA.Labor.employment"]["period"], "2026-09")
            self.assertEqual(by_id["CA.Labor.employment"]["transformation"], "mom_sa_change_thousands")
            self.assertEqual(by_id["CA.Labor.employment"]["source_series_id"], "v2062811_derived_mom_change")
            self.assertAlmostEqual(float(by_id["CA.Labor.employment"]["value"]), -68.29999999999927)

            self.assertEqual(by_id["CA.Labor.unemployment"]["source_series_id"], "v2062815")
            self.assertAlmostEqual(float(by_id["CA.Labor.unemployment"]["value"]), 6.5)

            self.assertEqual(by_id["CA.Labor.wages"]["source_series_id"], "v105812645_derived_yoy")

            self.assertIn("AU.Labor.employment", by_id)
            self.assertIn("AU.Labor.unemployment", by_id)
            self.assertNotIn("CA.Activity.gdp_domestic_demand", by_id)

            staged_ca = json.loads((launch_dir / "lineage" / "history" / "ca.json").read_text(encoding="utf-8"))
            labor_expect = {
                "Labor.employment": (
                    "LFS_employment_level_v2062811",
                    "mom_sa_change_thousands",
                    "v2062811_derived_mom_change",
                ),
                "Labor.unemployment": (
                    "LFS_unemployment_rate_v2062815",
                    "percent",
                    "v2062815",
                ),
                "Labor.wages": (
                    "LFS_avg_hourly_wage_v105812645",
                    "yoy_pct",
                    "v105812645_derived_yoy",
                ),
            }
            for key, (series_id, tf, src) in labor_expect.items():
                rows = [
                    o
                    for o in staged_ca["components"][key]["observations"]
                    if o.get("reference_period") == "2026-09"
                ]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["series_id"], series_id)
                self.assertEqual(rows[0]["transformation"], tf)
                self.assertEqual(rows[0]["source_series_id"], src)

            gdp_obs = staged_ca["components"]["Activity.gdp_domestic_demand"]["observations"]
            q2_rows = [
                o
                for o in gdp_obs
                if o.get("reference_period") == "2026-Q2" and o.get("transformation") == GDP_SCORING_TF
            ]
            self.assertEqual(len(q2_rows), 1)
            self.assertFalse(
                any(o.get("reference_period") == "2026-07" and o.get("transformation") == GDP_SCORING_TF for o in gdp_obs)
            )

            self.assertEqual(_sha256_file(CALIBRATION_PATH), self.cal_sha)
            self.assertEqual(_sha256_file(HISTORY_DIR / "ca.json"), self.ca_hist_sha)
            self.assertEqual(_sha256_file(SCORES_PATH), self.scores_sha)

    def test_second_pass_labor_idempotent(self) -> None:
        from scripts.macro_ingestion.score_bridge import points_from_observation_stores
        from scripts.macro_ingestion.contract import load_catalog

        cal = load_calibration(CALIBRATION_PATH)
        histories = load_history(HISTORY_DIR)
        work = copy.deepcopy(histories)
        catalog = load_catalog()
        points = points_from_observation_stores(
            observations_dir=OBS_DIR, catalog=catalog, checked_at=CHECKED_AT
        )
        first = merge_scored_points(work, cal, points, checked_at=CHECKED_AT)
        self.assertTrue(any(a["id"].startswith("CA.Labor.") for a in first["appended"]))
        second = merge_scored_points(work, cal, points, checked_at=CHECKED_AT)
        labor_dup = [
            s
            for s in second["skipped"]
            if str(s.get("id", "")).startswith("CA.Labor.") and s.get("reason") == "duplicate_value"
        ]
        self.assertEqual(len(labor_dup), 3)

    def test_synthetic_quarterly_gdp_mapping(self) -> None:
        cal = load_calibration(CALIBRATION_PATH)
        histories = load_history(HISTORY_DIR)
        work = copy.deepcopy(histories)
        point = {
            "country": "CA",
            "catalog_id": "CA.Activity.gdp_domestic_demand",
            "role": "scored",
            "series_id": GDP_COMBINED,
            "period": "2026-Q3",
            "value": 0.4,
            "transformation": GDP_COMPOUND_TF,
        }
        original = dict(point)
        result = merge_scored_points(work, cal, [point], checked_at=CHECKED_AT)
        self.assertEqual(len(result["appended"]), 1)
        row = work["CA"]["components"]["Activity.gdp_domestic_demand"]["observations"][-1]
        self.assertEqual(row["reference_period"], "2026-Q3")
        self.assertEqual(row["series_id"], GDP_SCORING_SERIES)
        self.assertEqual(row["transformation"], GDP_SCORING_TF)
        self.assertAlmostEqual(float(row["value"]), 0.4)
        self.assertEqual(row["source_series_id"], GDP_COMBINED)
        self.assertEqual(row["source_transformation"], GDP_COMPOUND_TF)

        bad_tf = dict(original)
        bad_tf["transformation"] = "mom_sa_pct"
        bad_series = dict(original)
        bad_series["series_id"] = "not_the_gdp_vector"
        for bad in (bad_tf, bad_series):
            work2 = copy.deepcopy(histories)
            out = merge_scored_points(work2, cal, [bad], checked_at=CHECKED_AT)
            self.assertEqual(len(out["appended"]), 0)
            reasons = {s["reason"] for s in out["skipped"]}
            self.assertTrue(reasons & {"partial_transform_mismatch", "partial_series_mismatch"})

    def test_fail_closed_and_future_release(self) -> None:
        cal = load_calibration(CALIBRATION_PATH)
        histories = load_history(HISTORY_DIR)
        base = {
            "country": "CA",
            "role": "scored",
            "period": "2026-09",
        }

        wrong_unemp = {
            **base,
            "catalog_id": "CA.Labor.unemployment",
            "series_id": "wrong_series",
            "transformation": "percent",
            "value": 6.5,
        }
        r1 = merge_scored_points(copy.deepcopy(histories), cal, [wrong_unemp], checked_at=CHECKED_AT)
        self.assertEqual(r1["skipped"][0]["reason"], "partial_series_mismatch")

        wrong_emp_tf = {
            **base,
            "catalog_id": "CA.Labor.employment",
            "series_id": "v2062811_derived_mom_change",
            "transformation": "percent",
            "value": 1.0,
        }
        r2 = merge_scored_points(copy.deepcopy(histories), cal, [wrong_emp_tf], checked_at=CHECKED_AT)
        self.assertEqual(r2["skipped"][0]["reason"], "partial_transform_mismatch")

        us_alias = {
            "country": "US",
            "catalog_id": "CA.Labor.unemployment",
            "role": "scored",
            "series_id": "v2062815",
            "period": "2026-09",
            "transformation": "percent",
            "value": 6.5,
        }
        us_work = copy.deepcopy(histories)
        ca_before = len(us_work["CA"]["components"]["Labor.unemployment"]["observations"])
        us_before = len(us_work["US"]["components"]["Labor.unemployment"]["observations"])
        r3 = merge_scored_points(us_work, cal, [us_alias], checked_at=CHECKED_AT)
        self.assertEqual(r3["skipped"][0]["reason"], "partial_series_mismatch")
        self.assertEqual(us_alias["series_id"], "v2062815")
        self.assertEqual(len(us_work["CA"]["components"]["Labor.unemployment"]["observations"]), ca_before)
        self.assertEqual(len(us_work["US"]["components"]["Labor.unemployment"]["observations"]), us_before)

        malformed = {
            **base,
            "catalog_id": "CA.Labor.unemployment",
            "series_id": "v2062815",
            "transformation": "percent",
            "value": float("nan"),
        }
        r4 = merge_scored_points(copy.deepcopy(histories), cal, [malformed], checked_at=CHECKED_AT)
        self.assertEqual(r4["skipped"][0]["reason"], "partial_malformed")

        missing_series = {
            **base,
            "catalog_id": "CA.Labor.unemployment",
            "transformation": "percent",
            "value": 6.5,
        }
        r4b = merge_scored_points(copy.deepcopy(histories), cal, [missing_series], checked_at=CHECKED_AT)
        self.assertEqual(r4b["skipped"][0]["reason"], "partial_malformed")

        future = {
            **base,
            "catalog_id": "CA.Labor.unemployment",
            "series_id": "v2062815",
            "transformation": "percent",
            "value": 6.5,
            "period": "2026-11",
        }
        r5 = merge_scored_points(copy.deepcopy(histories), cal, [future], checked_at=CHECKED_AT)
        self.assertEqual(r5["skipped"][0]["reason"], "future_release")
        self.assertEqual(future["series_id"], "v2062815")
        self.assertNotIn("source_series_id", future)

        masquerade = {
            "country": "CA",
            "catalog_id": "CA.Activity.gdp_domestic_demand",
            "role": "scored",
            "series_id": GDP_SCORING_SERIES,
            "period": "2026-07",
            "value": 0.5,
            "transformation": GDP_SCORING_TF,
        }
        r6 = merge_scored_points(copy.deepcopy(histories), cal, [masquerade], checked_at=CHECKED_AT)
        self.assertEqual(r6["skipped"][0]["reason"], "partial_transform_mismatch")
        self.assertEqual(len(r6["appended"]), 0)

    def test_lineage_still_fails_closed_on_incompatible_scored_points(self) -> None:
        wrong = {
            "country": "CA",
            "catalog_id": "CA.Labor.unemployment",
            "role": "scored",
            "series_id": "wrong_series",
            "period": "2026-09",
            "value": 6.5,
            "transformation": "percent",
        }
        future = {
            "country": "CA",
            "catalog_id": "CA.Labor.unemployment",
            "role": "scored",
            "series_id": "v2062815",
            "period": "2026-11",
            "value": 6.5,
            "transformation": "percent",
        }
        bad_gdp = {
            "country": "CA",
            "catalog_id": "CA.Activity.gdp_domestic_demand",
            "role": "scored",
            "series_id": GDP_COMBINED,
            "period": "2026-Q3",
            "value": 0.4,
            "transformation": "mom_sa_pct",
        }
        with tempfile.TemporaryDirectory() as tmp:
            launch_dir = Path(tmp) / "launch"
            launch_dir.mkdir()
            result = stage_verified_lineage(
                launch_dir=launch_dir,
                checked_at=CHECKED_AT,
                canonical_history_dir=HISTORY_DIR,
                calibration_path=CALIBRATION_PATH,
                points=[wrong, future, bad_gdp],
                mode="live",
            )
            self.assertFalse((launch_dir / "lineage" / "temperature_scores.json").is_file())
        self.assertFalse(result["ok"])
        self.assertEqual(result.get("error"), "score_lineage_rejected")
        self.assertEqual(result["appended_count"], 0)
        reasons = {(row["id"], row["period"], row["reason"], row["series_id"], row["transformation"]) for row in result["rejections"]}
        self.assertIn(
            ("CA.Labor.unemployment", "2026-09", "partial_series_mismatch", "wrong_series", "percent"),
            reasons,
        )
        self.assertIn(
            ("CA.Labor.unemployment", "2026-11", "future_release", "v2062815", "percent"),
            reasons,
        )
        self.assertIn(
            ("CA.Activity.gdp_domestic_demand", "2026-Q3", "partial_transform_mismatch", GDP_COMBINED, "mom_sa_pct"),
            reasons,
        )
    def test_already_calibrated_unemployment_merges(self) -> None:
        cal = load_calibration(CALIBRATION_PATH)
        histories = load_history(HISTORY_DIR)
        point = {
            "country": "CA",
            "catalog_id": "CA.Labor.unemployment",
            "role": "scored",
            "series_id": "LFS_unemployment_rate_v2062815",
            "period": "2026-09",
            "value": 6.5,
            "transformation": "percent",
        }
        result = merge_scored_points(copy.deepcopy(histories), cal, [point], checked_at=CHECKED_AT)
        self.assertEqual(len(result["appended"]), 1)


if __name__ == "__main__":
    unittest.main()
