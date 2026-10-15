"""CA/AU source-to-score identity via scripts.run_state.identity."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_ingestion.ca_score_identity import prepare_ca_score_point
from scripts.macro_ingestion.contract import load_catalog
from scripts.run_state.identity import (
    REASON_FREQUENCY_MISMATCH,
    REASON_FUTURE_RELEASE,
    REASON_TRANSFORM_MISMATCH,
    REASON_UNKNOWN_SERIES,
    classify_source_point,
    normalize_score_point,
)
from scripts.temperature_level import CALIBRATION_PATH, load_calibration, load_history

CHECKED_AT = "2026-10-15T08:52:22Z"
HISTORY_DIR = ROOT / "data" / "temperature_history"

GDP_COMBINED = "monthly_v65201210;quarterly_v1594571783"
GDP_COMPOUND_TF = "mom_sa_pct_and_qoq_sa_pct"
GDP_SCORING_SERIES = "GDP_real_market_prices_qq_v1594571783"
GDP_SCORING_TF = "qoq_sa_pct"


def _ca_base(**overrides: object) -> dict:
    point = {
        "country": "CA",
        "role": "scored",
        "period": "2026-09",
        "value": 1.0,
    }
    point.update(overrides)
    return point


class SeriesIdentityTests(unittest.TestCase):
    def test_oct15_ca_unemployment_alias(self) -> None:
        point = _ca_base(
            catalog_id="CA.Labor.unemployment",
            series_id="v2062815",
            transformation="percent",
            value=6.5,
        )
        before = copy.deepcopy(point)
        reason = prepare_ca_score_point(point, checked_at=CHECKED_AT)
        self.assertIsNone(reason)
        self.assertEqual(point["series_id"], "LFS_unemployment_rate_v2062815")
        self.assertEqual(point["transformation"], "percent")
        self.assertEqual(point["source_series_id"], "v2062815")
        self.assertNotEqual(point["series_id"], before["series_id"])

    def test_oct15_ca_employment_mom_alias_not_bare_level(self) -> None:
        point = _ca_base(
            catalog_id="CA.Labor.employment",
            series_id="v2062811_derived_mom_change",
            transformation="mom_sa_change_thousands",
            value=-68.3,
        )
        reason = prepare_ca_score_point(point, checked_at=CHECKED_AT)
        self.assertIsNone(reason)
        self.assertEqual(point["series_id"], "LFS_employment_level_v2062811")
        self.assertEqual(point["transformation"], "mom_sa_change_thousands")
        self.assertEqual(point["source_series_id"], "v2062811_derived_mom_change")

        bare = _ca_base(
            catalog_id="CA.Labor.employment",
            series_id="v2062811",
            transformation="mom_sa_change_thousands",
        )
        bare_copy = copy.deepcopy(bare)
        self.assertIsNone(prepare_ca_score_point(bare, checked_at=CHECKED_AT))
        self.assertEqual(bare, bare_copy)

    def test_oct15_ca_wages_yoy_alias(self) -> None:
        point = _ca_base(
            catalog_id="CA.Labor.wages",
            series_id="v105812645_derived_yoy",
            transformation="yoy_pct",
            value=2.338,
        )
        reason = prepare_ca_score_point(point, checked_at=CHECKED_AT)
        self.assertIsNone(reason)
        self.assertEqual(point["series_id"], "LFS_avg_hourly_wage_v105812645")
        self.assertEqual(point["transformation"], "yoy_pct")
        self.assertEqual(point["source_series_id"], "v105812645_derived_yoy")

    def test_oct15_ca_gdp_quarterly_maps_to_score_identity(self) -> None:
        point = _ca_base(
            catalog_id="CA.Activity.gdp_domestic_demand",
            series_id=GDP_COMBINED,
            transformation=GDP_COMPOUND_TF,
            period="2026-Q2",
            value=0.8,
        )
        reason = prepare_ca_score_point(point, checked_at=CHECKED_AT)
        self.assertIsNone(reason)
        self.assertEqual(point["series_id"], GDP_SCORING_SERIES)
        self.assertEqual(point["transformation"], GDP_SCORING_TF)
        self.assertEqual(point["source_series_id"], GDP_COMBINED)
        self.assertEqual(point["source_transformation"], GDP_COMPOUND_TF)

    def test_oct15_ca_gdp_monthly_combined_stays_context(self) -> None:
        point = _ca_base(
            catalog_id="CA.Activity.gdp_domestic_demand",
            series_id=GDP_COMBINED,
            transformation=GDP_COMPOUND_TF,
            period="2026-07",
            value=-0.00484846236286085,
        )
        reason = prepare_ca_score_point(point, checked_at=CHECKED_AT)
        self.assertIsNone(reason)
        self.assertEqual(point.get("role"), "context")
        self.assertEqual(point["series_id"], GDP_COMBINED)
        self.assertEqual(point["transformation"], GDP_COMPOUND_TF)
        self.assertNotEqual(point["transformation"], GDP_SCORING_TF)
        self.assertEqual(point["source_series_id"], GDP_COMBINED)
        self.assertEqual(point["source_transformation"], GDP_COMPOUND_TF)

    def test_gdp_monthly_masquerade_partial_transform_and_classify_frequency(self) -> None:
        for point in (
            _ca_base(
                catalog_id="CA.Activity.gdp_domestic_demand",
                series_id=GDP_SCORING_SERIES,
                transformation=GDP_SCORING_TF,
                period="2026-07",
                value=0.5,
            ),
            _ca_base(
                catalog_id="CA.Activity.gdp_domestic_demand",
                series_id=GDP_COMBINED,
                transformation=GDP_SCORING_TF,
                period="2026-07",
                value=0.5,
            ),
        ):
            snapshot = copy.deepcopy(point)
            reason = normalize_score_point(point, checked_at=CHECKED_AT)
            self.assertEqual(reason, "partial_transform_mismatch")
            self.assertEqual(point["series_id"], snapshot["series_id"])
            self.assertEqual(point["transformation"], snapshot["transformation"])
            self.assertNotIn("source_series_id", point)

            classified = classify_source_point(snapshot, checked_at=CHECKED_AT)
            self.assertEqual(classified["reason"], REASON_FREQUENCY_MISMATCH)
            self.assertEqual(classified["action"], "reject")

    def test_mismatch_unknown_series_and_transform(self) -> None:
        wrong_series = _ca_base(
            catalog_id="CA.Labor.unemployment",
            series_id="not_a_real_series",
            transformation="percent",
        )
        snap = copy.deepcopy(wrong_series)
        self.assertIsNone(normalize_score_point(wrong_series, checked_at=CHECKED_AT))
        self.assertEqual(wrong_series, snap)
        cls = classify_source_point(snap, checked_at=CHECKED_AT)
        self.assertEqual(cls["reason"], REASON_UNKNOWN_SERIES)

        wrong_tf = _ca_base(
            catalog_id="CA.Labor.employment",
            series_id="v2062811_derived_mom_change",
            transformation="percent",
        )
        snap_tf = copy.deepcopy(wrong_tf)
        self.assertIsNone(normalize_score_point(wrong_tf, checked_at=CHECKED_AT))
        self.assertEqual(wrong_tf, snap_tf)
        cls_tf = classify_source_point(snap_tf, checked_at=CHECKED_AT)
        self.assertEqual(cls_tf["reason"], REASON_TRANSFORM_MISMATCH)

    def test_future_unemployment_before_rewrite(self) -> None:
        point = _ca_base(
            catalog_id="CA.Labor.unemployment",
            series_id="v2062815",
            transformation="percent",
            period="2026-11",
            value=6.5,
        )
        reason = prepare_ca_score_point(point, checked_at=CHECKED_AT)
        self.assertEqual(reason, "future_release")
        self.assertEqual(point["series_id"], "v2062815")
        self.assertNotIn("source_series_id", point)

        cls = classify_source_point(
            {
                "country": "CA",
                "catalog_id": "CA.Labor.unemployment",
                "series_id": "v2062815",
                "transformation": "percent",
                "period": "2026-11",
            },
            checked_at=CHECKED_AT,
        )
        self.assertEqual(cls["reason"], REASON_FUTURE_RELEASE)

    def test_au_labor_no_rewrite_and_catalog_calibration_history_parity(self) -> None:
        catalog = load_catalog()
        cal = load_calibration(CALIBRATION_PATH)
        histories = load_history(HISTORY_DIR)

        for catalog_id, history_key in (
            ("AU.Labor.unemployment", "Labor.unemployment"),
            ("AU.Labor.employment", "Labor.employment"),
        ):
            row = next(s for s in catalog["series"] if s["id"] == catalog_id)
            comp = cal["components"][catalog_id]
            hist = histories["AU"]["components"][history_key]
            self.assertEqual(row.get("series_id"), comp.get("series_id"))
            self.assertEqual(row.get("transform"), comp.get("source_transformation"))
            self.assertEqual(hist.get("series_id"), row.get("series_id"))
            self.assertEqual(hist.get("preferred_scoring_transformation"), row.get("transform"))

            point = {
                "country": "AU",
                "catalog_id": catalog_id,
                "series_id": row["series_id"],
                "transformation": row["transform"],
                "period": "2026-09",
                "value": 1.0,
            }
            snap = copy.deepcopy(point)
            self.assertIsNone(normalize_score_point(point, checked_at=CHECKED_AT))
            self.assertEqual(point, snap)
            self.assertNotIn("source_series_id", point)

    def test_idempotent_score_unemployment_id(self) -> None:
        point = _ca_base(
            catalog_id="CA.Labor.unemployment",
            series_id="LFS_unemployment_rate_v2062815",
            transformation="percent",
        )
        snap = copy.deepcopy(point)
        self.assertIsNone(prepare_ca_score_point(point, checked_at=CHECKED_AT))
        self.assertEqual(point["series_id"], snap["series_id"])
        self.assertNotIn("source_series_id", point)

    def test_wrong_country_us_not_rewritten(self) -> None:
        point = {
            "country": "US",
            "catalog_id": "CA.Labor.unemployment",
            "series_id": "v2062815",
            "transformation": "percent",
            "period": "2026-09",
            "value": 6.5,
        }
        snap = copy.deepcopy(point)
        self.assertIsNone(prepare_ca_score_point(point, checked_at=CHECKED_AT))
        self.assertEqual(point, snap)


if __name__ == "__main__":
    unittest.main()
