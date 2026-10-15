"""Weighted-series contract preflight (network-free)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_ingestion.contract import load_calibration, load_catalog
from scripts.macro_ingestion.series_preflight import run_weighted_series_preflight
from scripts.run_state.identity import (
    REASON_SOURCE_SERIES_MISMATCH,
    REASON_TRANSFORM_MISMATCH,
)
from scripts.temperature_level import load_history

HISTORY_DIR = ROOT / "data" / "temperature_history"


class TestSeriesContractPreflight(unittest.TestCase):
    def _histories(self) -> dict:
        return load_history(HISTORY_DIR)

    def test_baseline_preflight_ok_and_checked_positive(self) -> None:
        report = run_weighted_series_preflight(
            catalog=load_catalog(),
            calibration=load_calibration(),
            histories=self._histories(),
        )
        self.assertTrue(report["ok"])
        self.assertGreater(report["checked"], 0)
        self.assertEqual(report["mismatches"], [])
        self.assertEqual(report["blocked_countries"], [])

    def test_au_unemployment_series_id_drift_blocks_au_only(self) -> None:
        catalog = load_catalog()
        calibration = load_calibration()
        histories = self._histories()
        for row in catalog["series"]:
            if row["id"] == "AU.Labor.unemployment":
                row["series_id"] = "A84423050A_WRONG"
                break
        report = run_weighted_series_preflight(
            catalog=catalog,
            calibration=calibration,
            histories=histories,
        )
        self.assertFalse(report["ok"])
        self.assertEqual(report["blocked_countries"], ["AU"])
        au = [m for m in report["mismatches"] if m["concept_id"] == "AU.Labor.unemployment"]
        self.assertEqual(len(au), 1)
        self.assertEqual(au[0]["field"], "series_id")
        self.assertEqual(au[0]["expected"], "A84423050A")
        self.assertEqual(au[0]["actual"], "A84423050A_WRONG")
        countries = {m["country"] for m in report["mismatches"]}
        self.assertEqual(countries, {"AU"})

    def test_weighted_transform_disagreement_reports_field_and_values(self) -> None:
        catalog = load_catalog()
        calibration = load_calibration()
        histories = self._histories()
        for row in catalog["series"]:
            if row["id"] == "US.Inflation.core_pce":
                row["transform"] = "yoy_pct"
                break
        report = run_weighted_series_preflight(
            catalog=catalog,
            calibration=calibration,
            histories=histories,
        )
        self.assertFalse(report["ok"])
        hits = [m for m in report["mismatches"] if m["concept_id"] == "US.Inflation.core_pce"]
        self.assertTrue(hits)
        transform_hits = [m for m in hits if m["field"] == "transform"]
        self.assertTrue(transform_hits)
        self.assertEqual(transform_hits[0]["reason"], REASON_TRANSFORM_MISMATCH)
        self.assertNotEqual(transform_hits[0]["expected"], transform_hits[0]["actual"])

    def test_preflight_does_not_invent_future_periods(self) -> None:
        report = run_weighted_series_preflight(
            catalog=load_catalog(),
            calibration=load_calibration(),
            histories=self._histories(),
        )
        blob = json.dumps(report)
        self.assertNotIn("future_release", blob)
        for item in report.get("mismatches") or []:
            self.assertNotIn("period", item)
            self.assertNotIn("reference_period", item)

    def test_ca_unemployment_unknown_source_id_is_exact_not_fuzzy(self) -> None:
        catalog = load_catalog()
        calibration = load_calibration()
        histories = self._histories()
        wrong_id = "LFS_unemployment_rate_v2062815"
        for row in catalog["series"]:
            if row["id"] == "CA.Labor.unemployment":
                self.assertEqual(row["series_id"], "v2062815")
                row["series_id"] = wrong_id
                break
        report = run_weighted_series_preflight(
            catalog=catalog,
            calibration=calibration,
            histories=histories,
        )
        self.assertFalse(report["ok"])
        hits = [m for m in report["mismatches"] if m["concept_id"] == "CA.Labor.unemployment"]
        self.assertTrue(hits)
        series_hits = [m for m in hits if m["field"] == "series_id"]
        self.assertTrue(series_hits)
        self.assertEqual(series_hits[0]["reason"], REASON_SOURCE_SERIES_MISMATCH)
        self.assertEqual(series_hits[0]["expected"], "v2062815")
        self.assertEqual(series_hits[0]["actual"], wrong_id)
        self.assertEqual(report["blocked_countries"], ["CA"])


if __name__ == "__main__":
    unittest.main()
