"""CA StatCan source-to-score identity mapping and Oct 15 2026 launch replay."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_ingestion.ca_score_identity import expand_equal_mean_points, prepare_ca_score_point
from scripts.run_state.identity import normalize_score_point
from scripts.macro_ingestion.canonical_bridge import merge_scored_points
from scripts.macro_ingestion.score_bridge import points_from_observation_stores
from scripts.market_watch_launch.lineage import stage_verified_lineage
from scripts.macro_ingestion.contract import load_catalog
from scripts.temperature_level import CALIBRATION_PATH, load_calibration, load_history

LAUNCH = ROOT / "data/market_watch_launches/mwl-20261015T085222Z-b4bbe448"
OBS_DIR = LAUNCH / "ingestion/observations"
CHECKED_AT = "2026-10-15T08:52:22Z"

LAUNCH_OCT20 = ROOT / "data/market_watch_launches/mwl-20261020T111300Z-56f4da26"
OBS_DIR_OCT20 = LAUNCH_OCT20 / "ingestion/observations"
CHECKED_AT_OCT20 = "2026-10-20T11:13:00Z"
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


OCT20_PROMOTED_CPI_ROWS: tuple[dict, ...] = (
    {
        "component": "Inflation.headline",
        "series_id": "CPI_all_items_index_v41690973",
        "reference_period": "2026-09",
        "transformation": "yoy_pct",
        "value": 3.092783505154628,
        "source_series_id": "v41690973_derived_yoy",
    },
    {
        "component": "Inflation.underlying",
        "series_id": "CPI_trim_yoy_v108785715",
        "reference_period": "2026-09",
        "transformation": "yoy_pct",
        "value": 1.8,
        "source_series_id": "CPI_trim_and_median_yoy",
    },
    {
        "component": "Inflation.underlying",
        "series_id": "CPI_median_yoy_v108785714",
        "reference_period": "2026-09",
        "transformation": "yoy_pct",
        "value": 1.9,
        "source_series_id": "CPI_trim_and_median_yoy",
    },
)

_PROMOTED_CPI_MATCH_KEYS = {
    (row["component"], row["series_id"], row["reference_period"], row["transformation"])
    for row in OCT20_PROMOTED_CPI_ROWS
}


def _pre_promotion_ca_histories(histories: dict) -> tuple[dict, list[dict]]:
    work = copy.deepcopy(histories)
    ca = work["CA"]
    removed: list[dict] = []
    for comp_key, comp_data in ca.get("components", {}).items():
        obs_list = comp_data.get("observations") or []
        kept: list[dict] = []
        for obs in obs_list:
            key = (
                comp_key,
                obs.get("series_id"),
                obs.get("reference_period"),
                obs.get("transformation"),
            )
            if key in _PROMOTED_CPI_MATCH_KEYS:
                removed.append(
                    {
                        "component": comp_key,
                        "series_id": obs.get("series_id"),
                        "reference_period": obs.get("reference_period"),
                        "transformation": obs.get("transformation"),
                        "value": obs.get("value"),
                        "source_series_id": obs.get("source_series_id"),
                    }
                )
            else:
                kept.append(obs)
        comp_data["observations"] = kept
    return work, removed


def _assert_exact_promoted_cpi_removed(test: unittest.TestCase, removed: list[dict]) -> None:
    test.assertEqual(len(removed), 3)
    for expected in OCT20_PROMOTED_CPI_ROWS:
        key = (
            expected["component"],
            expected["series_id"],
            expected["reference_period"],
            expected["transformation"],
        )
        matches = [
            row
            for row in removed
            if (
                row["component"],
                row["series_id"],
                row["reference_period"],
                row["transformation"],
            )
            == key
        ]
        test.assertEqual(len(matches), 1, msg=f"missing removal for {key}")
        row = matches[0]
        test.assertEqual(row["source_series_id"], expected["source_series_id"])
        test.assertEqual(row["series_id"], expected["series_id"])
        test.assertEqual(row["transformation"], expected["transformation"])
        test.assertAlmostEqual(float(row["value"]), float(expected["value"]))


def _write_pre_promotion_history_dir(dest: Path, histories: dict) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for src in HISTORY_DIR.glob("*.json"):
        shutil.copy2(src, dest / src.name)
    (dest / "ca.json").write_text(
        json.dumps(histories["CA"], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


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
            # July 2026 retail is already in canonical history; replay appends nothing new.
            self.assertEqual(result["appended_count"], 0)
            self.assertEqual(result.get("appended_points") or [], [])

            staged_ca = json.loads((launch_dir / "lineage" / "history" / "ca.json").read_text(encoding="utf-8"))
            [july] = [
                o
                for o in staged_ca["components"]["Consumer.retail"]["observations"]
                if o.get("reference_period") == "2026-07"
            ]
            self.assertEqual(july["series_id"], "retail_total_sa_v1446859483")
            self.assertAlmostEqual(july["value"], -0.8148385765720634)
            # The June template row's release date and level are not carried over.
            self.assertNotIn("release_date", july)
            self.assertNotIn("raw_level", july)
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

            staged_au = json.loads((launch_dir / "lineage" / "history" / "au.json").read_text(encoding="utf-8"))
            for key in ("Labor.employment", "Labor.unemployment"):
                self.assertTrue(any(
                    row.get("reference_period") == "2026-09"
                    for row in staged_au["components"][key]["observations"]
                ), key)

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
        self.assertFalse(any(a["id"].startswith("CA.Labor.") for a in first["appended"]))
        second = merge_scored_points(work, cal, points, checked_at=CHECKED_AT)
        for outcome in (first, second):
            labor_dup = [
                s
                for s in outcome["skipped"]
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
            "period": "2026-10",
            "value": 6.5,
            "transformation": "percent",
        }
        future = {
            "country": "CA",
            "catalog_id": "CA.Labor.unemployment",
            "role": "scored",
            "series_id": "v2062815",
            "period": "2026-12",
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
                checked_at="2026-11-15T08:52:22Z",
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
            ("CA.Labor.unemployment", "2026-10", "partial_series_mismatch", "wrong_series", "percent"),
            reasons,
        )
        self.assertIn(
            ("CA.Labor.unemployment", "2026-12", "future_release", "v2062815", "percent"),
            reasons,
        )
        self.assertIn(
            ("CA.Activity.gdp_domestic_demand", "2026-Q3", "partial_transform_mismatch", GDP_COMBINED, "mom_sa_pct"),
            reasons,
        )
    def test_already_calibrated_unemployment_idempotent_and_forward_merges(self) -> None:
        cal = load_calibration(CALIBRATION_PATH)
        work = copy.deepcopy(load_history(HISTORY_DIR))
        point = {
            "country": "CA",
            "catalog_id": "CA.Labor.unemployment",
            "role": "scored",
            "series_id": "LFS_unemployment_rate_v2062815",
            "period": "2026-09",
            "value": 6.5,
            "transformation": "percent",
        }
        replay = merge_scored_points(work, cal, [dict(point)], checked_at=CHECKED_AT)
        self.assertEqual(replay["appended"], [])
        self.assertEqual(replay["skipped"], [{"id": "CA.Labor.unemployment", "reason": "duplicate_value"}])

        forward = {**point, "period": "2026-10", "value": 6.6}
        accepted = merge_scored_points(work, cal, [forward], checked_at="2026-11-15T08:52:22Z")
        self.assertEqual(len(accepted["appended"]), 1, accepted)
        rows = work["CA"]["components"]["Labor.unemployment"]["observations"]
        self.assertEqual(rows[-1]["reference_period"], "2026-10")
        self.assertEqual(rows[-1]["series_id"], point["series_id"])


class CaInflationOct20LineageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cal_sha = _sha256_file(CALIBRATION_PATH)
        cls.ca_hist_sha = _sha256_file(HISTORY_DIR / "ca.json")
        cls.scores_sha = _sha256_file(SCORES_PATH)
        cls.artifact = json.loads(
            (LAUNCH_OCT20 / "artifacts" / "01_ingest.json").read_text(encoding="utf-8")
        )
        cls.ca_store = json.loads((OBS_DIR_OCT20 / "ca.json").read_text(encoding="utf-8"))

    def test_oct20_artifact_rejections_reproduced_without_repair(self) -> None:
        rejections = {r["id"]: r for r in self.artifact["lineage"]["rejections"]}
        self.assertEqual(
            rejections["CA.Inflation.headline"],
            {
                "id": "CA.Inflation.headline",
                "period": "2026-09",
                "reason": "partial_series_mismatch",
                "series_id": "v41690973_derived_yoy",
                "transformation": "yoy_pct",
            },
        )
        self.assertEqual(
            rejections["CA.Inflation.underlying"],
            {
                "id": "CA.Inflation.underlying",
                "period": "2026-09",
                "reason": "partial_series_mismatch",
                "series_id": "CPI_trim_and_median_yoy",
                "transformation": "yoy_pct",
            },
        )
        cal = load_calibration(CALIBRATION_PATH)
        histories = load_history(HISTORY_DIR)
        catalog = load_catalog()
        points = points_from_observation_stores(
            observations_dir=OBS_DIR_OCT20, catalog=catalog, checked_at=CHECKED_AT_OCT20
        )
        headline_pt = next(
            p for p in points if p.get("catalog_id") == "CA.Inflation.headline"
        )
        underlying_pt = next(
            p for p in points if p.get("catalog_id") == "CA.Inflation.underlying"
        )
        headline_copy = copy.deepcopy(headline_pt)
        self.assertIsNone(
            prepare_ca_score_point(headline_copy, checked_at=CHECKED_AT_OCT20)
        )
        self.assertEqual(headline_copy["series_id"], "v41690973_derived_yoy")
        self.assertIsNone(
            normalize_score_point(headline_copy, checked_at=CHECKED_AT_OCT20, scored_gate=None)
        )
        self.assertEqual(headline_copy["series_id"], "v41690973_derived_yoy")

        u_merge = merge_scored_points(
            copy.deepcopy(histories), cal, [underlying_pt], checked_at=CHECKED_AT_OCT20
        )
        self.assertEqual(u_merge["skipped"][0]["reason"], "partial_series_mismatch")

    def test_oct20_stage_verified_lineage_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            canonical_histories = load_history(HISTORY_DIR)
            before_counts = {
                key: len(canonical_histories["CA"]["components"][key]["observations"])
                for key in canonical_histories["CA"]["components"]
            }
            stripped_histories, removed = _pre_promotion_ca_histories(canonical_histories)
            _assert_exact_promoted_cpi_removed(self, removed)
            after_counts = {
                key: len(stripped_histories["CA"]["components"][key]["observations"])
                for key in stripped_histories["CA"]["components"]
            }
            self.assertEqual(before_counts["Inflation.headline"] - 1, after_counts["Inflation.headline"])
            self.assertEqual(
                before_counts["Inflation.underlying"] - 2, after_counts["Inflation.underlying"]
            )
            for key, count in before_counts.items():
                if key not in ("Inflation.headline", "Inflation.underlying"):
                    self.assertEqual(count, after_counts[key])

            canonical_history_dir = tmp_root / "canonical_history"
            _write_pre_promotion_history_dir(canonical_history_dir, stripped_histories)
            written_ca = json.loads(
                (canonical_history_dir / "ca.json").read_text(encoding="utf-8")
            )
            for expected in OCT20_PROMOTED_CPI_ROWS:
                comp_obs = written_ca["components"][expected["component"]]["observations"]
                matches = [
                    o
                    for o in comp_obs
                    if o.get("series_id") == expected["series_id"]
                    and o.get("reference_period") == expected["reference_period"]
                    and o.get("transformation") == expected["transformation"]
                ]
                self.assertEqual(matches, [], msg=expected)
            for name in ("us.json", "au.json", "nz.json", "ea.json", "jp.json"):
                self.assertEqual(
                    (canonical_history_dir / name).read_bytes(),
                    (HISTORY_DIR / name).read_bytes(),
                )

            launch_dir = tmp_root / "launch"
            launch_dir.mkdir()
            result = stage_verified_lineage(
                launch_dir=launch_dir,
                checked_at=CHECKED_AT_OCT20,
                canonical_history_dir=canonical_history_dir,
                calibration_path=CALIBRATION_PATH,
                observations_dir=OBS_DIR_OCT20,
                mode="live",
            )
            self.assertTrue(result["ok"], msg=result.get("error"))
            self.assertNotEqual(result.get("error"), "score_lineage_rejected")
            self.assertEqual(result.get("rejections") or [], [])

            staged_ca = json.loads(
                (launch_dir / "lineage" / "history" / "ca.json").read_text(encoding="utf-8")
            )
            headline_rows = [
                o
                for o in staged_ca["components"]["Inflation.headline"]["observations"]
                if o.get("reference_period") == "2026-09"
            ]
            self.assertEqual(len(headline_rows), 1)
            self.assertEqual(headline_rows[0]["series_id"], "CPI_all_items_index_v41690973")
            self.assertEqual(headline_rows[0]["transformation"], "yoy_pct")
            self.assertAlmostEqual(float(headline_rows[0]["value"]), 3.092783505154628)
            self.assertEqual(headline_rows[0]["source_series_id"], "v41690973_derived_yoy")
            headline_provenance = [
                row
                for row in result["appended_points"]
                if row.get("catalog_id") == "CA.Inflation.headline"
            ]
            self.assertEqual(len(headline_provenance), 1)
            self.assertEqual(headline_provenance[0]["source_series_id"], "v41690973_derived_yoy")
            self.assertEqual(headline_provenance[0]["transformation"], "yoy_pct")
            self.assertAlmostEqual(float(headline_provenance[0]["value"]), 3.092783505154628)
            headline_series_ids = {
                o["series_id"]
                for o in staged_ca["components"]["Inflation.headline"]["observations"]
                if o.get("reference_period") == "2026-09"
            }
            self.assertEqual(headline_series_ids, {"CPI_all_items_index_v41690973"})

            underlying = staged_ca["components"]["Inflation.underlying"]["observations"]
            trim_sep = next(
                o
                for o in underlying
                if o.get("reference_period") == "2026-09"
                and o.get("series_id") == "CPI_trim_yoy_v108785715"
            )
            med_sep = next(
                o
                for o in underlying
                if o.get("reference_period") == "2026-09"
                and o.get("series_id") == "CPI_median_yoy_v108785714"
            )
            self.assertAlmostEqual(float(trim_sep["value"]), 1.8)
            self.assertAlmostEqual(float(med_sep["value"]), 1.9)
            self.assertEqual(trim_sep["source_series_id"], "CPI_trim_and_median_yoy")
            self.assertEqual(med_sep["source_series_id"], "CPI_trim_and_median_yoy")
            self.assertEqual(trim_sep["transformation"], "yoy_pct")
            self.assertEqual(med_sep["transformation"], "yoy_pct")
            underlying_provenance = [
                row
                for row in result["appended_points"]
                if row.get("catalog_id") == "CA.Inflation.underlying"
            ]
            self.assertEqual(len(underlying_provenance), 2)
            self.assertEqual(
                {row["source_series_id"] for row in underlying_provenance},
                {"CPI_trim_and_median_yoy"},
            )
            self.assertEqual(
                {row["source_transformation"] for row in underlying_provenance},
                {"yoy_pct"},
            )
            self.assertEqual(
                {float(row["value"]) for row in underlying_provenance},
                {1.8, 1.9},
            )
            self.assertNotAlmostEqual(float(trim_sep["value"]), 1.85)
            self.assertNotAlmostEqual(float(med_sep["value"]), 1.85)

            aug_trim = next(
                o
                for o in underlying
                if o.get("reference_period") == "2026-08"
                and o.get("series_id") == "CPI_trim_yoy_v108785715"
            )
            aug_med = next(
                o
                for o in underlying
                if o.get("reference_period") == "2026-08"
                and o.get("series_id") == "CPI_median_yoy_v108785714"
            )
            self.assertAlmostEqual(float(aug_trim["value"]), 1.9)
            self.assertAlmostEqual(float(aug_med["value"]), 2.0)

            # Three CPI prints; July retail is already in canonical history.
            self.assertEqual(result["appended_count"], 3)
            self.assertEqual(len(result["appended_points"]), 3)
            retail_prov = [
                (row["period"], row["source_series_id"])
                for row in result["appended_points"]
                if row.get("catalog_id") == "CA.Consumer.retail"
            ]
            self.assertEqual(retail_prov, [])
            headline_prov = next(
                row
                for row in result["appended_points"]
                if row.get("catalog_id") == "CA.Inflation.headline"
            )
            self.assertEqual(headline_prov["source_series_id"], "v41690973_derived_yoy")
            self.assertEqual(headline_prov["transformation"], "yoy_pct")
            self.assertNotIn("source_transformation", headline_prov)
            underlying_prov = [
                row
                for row in result["appended_points"]
                if row.get("catalog_id") == "CA.Inflation.underlying"
            ]
            self.assertEqual(len(underlying_prov), 2)
            for row in underlying_prov:
                self.assertEqual(row["source_series_id"], "CPI_trim_and_median_yoy")
                self.assertEqual(row["source_transformation"], "yoy_pct")
                self.assertEqual(row["transformation"], "yoy_pct")

            self.assertEqual(_sha256_file(CALIBRATION_PATH), self.cal_sha)
            self.assertEqual(_sha256_file(HISTORY_DIR / "ca.json"), self.ca_hist_sha)
            self.assertEqual(_sha256_file(SCORES_PATH), self.scores_sha)

    def test_oct20_inflation_adversarial_fail_closed(self) -> None:
        cal = load_calibration(CALIBRATION_PATH)
        histories = load_history(HISTORY_DIR)
        catalog = load_catalog()
        points = points_from_observation_stores(
            observations_dir=OBS_DIR_OCT20, catalog=catalog, checked_at=CHECKED_AT_OCT20
        )
        headline = _obs_by_series_period(
            self.ca_store, "v41690973_derived_yoy", "2026-09", "yoy_pct"
        )
        underlying = _obs_by_series_period(
            self.ca_store, "CPI_trim_and_median_yoy", "2026-09", "yoy_pct"
        )

        def merge_one(point: dict) -> dict:
            work = copy.deepcopy(histories)
            before_h = len(work["CA"]["components"]["Inflation.headline"]["observations"])
            before_u = len(work["CA"]["components"]["Inflation.underlying"]["observations"])
            out = merge_scored_points(work, cal, [point], checked_at=CHECKED_AT_OCT20)
            self.assertEqual(
                len(work["CA"]["components"]["Inflation.headline"]["observations"]), before_h
            )
            self.assertEqual(
                len(work["CA"]["components"]["Inflation.underlying"]["observations"]), before_u
            )
            return out

        base_h = {
            "country": "CA",
            "catalog_id": "CA.Inflation.headline",
            "role": "scored",
            "series_id": "v41690973_derived_yoy",
            "period": "2026-09",
            "value": float(headline["value"]),
            "transformation": "yoy_pct",
            "raw_sha256": headline["raw_sha256"],
        }
        for bad in (
            {**base_h, "series_id": "wrong_series"},
            {**base_h, "transformation": "mom_sa_pct"},
            {**base_h, "period": "2026-Q3"},
            {**base_h, "period": "2026-11"},
            {
                **base_h,
                "period": "2026-08",
                "value": 3.033980582524265,
            },
        ):
            out = merge_one(bad)
            self.assertEqual(len(out["appended"]), 0)
            self.assertTrue(out["skipped"])
        august = merge_one({**base_h, "period": "2026-08", "value": 3.033980582524265})
        self.assertEqual(august["skipped"][0]["reason"], "partial_series_mismatch")

        future_trim = {
            "country": "CA",
            "catalog_id": "CA.Inflation.underlying",
            "role": "scored",
            "series_id": "CPI_trim_yoy_v108785715",
            "transformation": "yoy_pct",
            "period": "2026-11",
            "value": 1.8,
        }
        future_out = merge_one(future_trim)
        self.assertEqual(future_out["skipped"][0]["reason"], "future_release")
        self.assertEqual(future_trim["series_id"], "CPI_trim_yoy_v108785715")
        self.assertNotIn("source_series_id", future_trim)

        base_u = {
            "country": "CA",
            "catalog_id": "CA.Inflation.underlying",
            "role": "scored",
            "period": "2026-09",
            "value": float(underlying["value"]),
            "transformation": "yoy_pct",
            "series_id": "CPI_trim_and_median_yoy",
            "raw_sha256": underlying["raw_sha256"],
        }
        for bad in (
            {**base_u, "raw_sha256": "0" * 64},
            {**base_u, "value": 9.99},
            {**base_u, "period": "2026-10"},
            {**base_u, "period": "2026-11"},
        ):
            expanded = expand_equal_mean_points(
                [bad], observations_dir=OBS_DIR_OCT20, checked_at=CHECKED_AT_OCT20
            )
            out = merge_scored_points(
                copy.deepcopy(histories), cal, expanded, checked_at=CHECKED_AT_OCT20
            )
            self.assertEqual(len(out["appended"]), 0)

        trim_only = expand_equal_mean_points(
            [base_u], observations_dir=OBS_DIR_OCT20, checked_at=CHECKED_AT_OCT20
        )[0]
        trim_only["series_id"] = "CPI_all_items_index_v41690973"
        merge_one(trim_only)
        med_as_headline = dict(trim_only)
        med_as_headline["series_id"] = "CPI_median_yoy_v108785714"
        med_as_headline["catalog_id"] = "CA.Inflation.headline"
        merge_one(med_as_headline)

        us_headline = {**base_h, "series_id": "v41690973_derived_yoy", "country": "US"}
        merge_one(us_headline)
        other_id = {**base_h, "series_id": "v41690973_derived_yoy", "catalog_id": "CA.Labor.wages"}
        merge_one(other_id)

    def test_oct20_expanded_september_idempotent_second_merge(self) -> None:
        cal = load_calibration(CALIBRATION_PATH)
        histories = load_history(HISTORY_DIR)
        catalog = load_catalog()
        raw_points = points_from_observation_stores(
            observations_dir=OBS_DIR_OCT20, catalog=catalog, checked_at=CHECKED_AT_OCT20
        )
        inflation = [
            p
            for p in raw_points
            if str(p.get("catalog_id") or "").startswith("CA.Inflation.")
        ]
        expanded = expand_equal_mean_points(
            inflation, observations_dir=OBS_DIR_OCT20, checked_at=CHECKED_AT_OCT20
        )

        canonical_replay = merge_scored_points(
            copy.deepcopy(histories),
            cal,
            copy.deepcopy(expanded),
            checked_at=CHECKED_AT_OCT20,
        )
        self.assertEqual(canonical_replay["appended"], [])
        canonical_dup = [
            s
            for s in canonical_replay["skipped"]
            if str(s.get("id", "")).startswith("CA.Inflation.")
            and s.get("reason") == "duplicate_value"
        ]
        self.assertEqual(len(canonical_dup), 3)

        stripped_histories, removed = _pre_promotion_ca_histories(copy.deepcopy(histories))
        _assert_exact_promoted_cpi_removed(self, removed)

        work = copy.deepcopy(stripped_histories)
        first = merge_scored_points(
            work, cal, copy.deepcopy(expanded), checked_at=CHECKED_AT_OCT20
        )
        self.assertEqual(len(first["appended"]), 3)
        appended_series = {
            (row["series_id"], row["reference_period"], row["transformation"])
            for row in first["appended"]
        }
        self.assertEqual(
            appended_series,
            {
                ("CPI_all_items_index_v41690973", "2026-09", "yoy_pct"),
                ("CPI_trim_yoy_v108785715", "2026-09", "yoy_pct"),
                ("CPI_median_yoy_v108785714", "2026-09", "yoy_pct"),
            },
        )
        headline_row = next(
            o
            for o in work["CA"]["components"]["Inflation.headline"]["observations"]
            if o.get("reference_period") == "2026-09"
            and o.get("series_id") == "CPI_all_items_index_v41690973"
        )
        trim_row = next(
            o
            for o in work["CA"]["components"]["Inflation.underlying"]["observations"]
            if o.get("reference_period") == "2026-09"
            and o.get("series_id") == "CPI_trim_yoy_v108785715"
        )
        med_row = next(
            o
            for o in work["CA"]["components"]["Inflation.underlying"]["observations"]
            if o.get("reference_period") == "2026-09"
            and o.get("series_id") == "CPI_median_yoy_v108785714"
        )
        self.assertAlmostEqual(float(headline_row["value"]), 3.092783505154628)
        self.assertAlmostEqual(float(trim_row["value"]), 1.8)
        self.assertAlmostEqual(float(med_row["value"]), 1.9)
        self.assertEqual(headline_row["source_series_id"], "v41690973_derived_yoy")
        self.assertEqual(trim_row["source_series_id"], "CPI_trim_and_median_yoy")
        self.assertEqual(med_row["source_series_id"], "CPI_trim_and_median_yoy")

        second = merge_scored_points(
            work, cal, copy.deepcopy(expanded), checked_at=CHECKED_AT_OCT20
        )
        self.assertEqual(second["appended"], [])
        inflation_dup = [
            s
            for s in second["skipped"]
            if str(s.get("id", "")).startswith("CA.Inflation.")
            and s.get("reason") == "duplicate_value"
        ]
        self.assertEqual(len(inflation_dup), 3)

        self.assertEqual(_sha256_file(CALIBRATION_PATH), self.cal_sha)
        self.assertEqual(_sha256_file(HISTORY_DIR / "ca.json"), self.ca_hist_sha)
        self.assertEqual(_sha256_file(SCORES_PATH), self.scores_sha)


if __name__ == "__main__":
    unittest.main()
