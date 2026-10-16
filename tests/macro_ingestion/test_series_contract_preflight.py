"""Weighted-series contract preflight (network-free)."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_ingestion.contract import load_calibration, load_catalog
from scripts.macro_ingestion.series_preflight import (
    ledger_rows_for_preflight_mismatches,
    run_weighted_series_preflight,
)
from scripts.run_state.identity import (
    REASON_MISSING_CALIBRATION,
    REASON_SOURCE_SERIES_MISMATCH,
    REASON_TRANSFORM_MISMATCH,
    preflight_weighted_series,
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
        # Positively weighted scored rows with an explicit observed:false
        # calibration entry stay omitted. They are not missing-calibration failures.
        calibration = load_calibration()
        catalog_rows = {row["id"]: row for row in load_catalog()["series"]}
        for concept_id in ("CA.Consumer.confidence", "AU.Consumer.retail"):
            self.assertIs(calibration["components"][concept_id].get("observed"), False)
            self.assertEqual(catalog_rows[concept_id]["role"], "scored")
            self.assertGreater(float(catalog_rows[concept_id]["weight"]), 0.0)
            self.assertNotIn(concept_id, {m["concept_id"] for m in report["mismatches"]})

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

    def test_missing_calibration_deleted_component_blocks_au_only(self) -> None:
        catalog = load_catalog()
        calibration = copy.deepcopy(load_calibration())
        calibration["components"].pop("AU.Labor.unemployment")
        report = preflight_weighted_series(
            catalog=catalog,
            calibration=calibration,
            histories=self._histories(),
        )
        self.assertFalse(report["ok"])
        self.assertEqual(report["blocked_countries"], ["AU"])
        au = [m for m in report["mismatches"] if m["concept_id"] == "AU.Labor.unemployment"]
        self.assertEqual(len(au), 1)
        self.assertEqual(au[0]["country"], "AU")
        self.assertEqual(au[0]["component"], "unemployment")
        self.assertEqual(au[0]["source"], "calibration")
        self.assertEqual(au[0]["field"], "component")
        self.assertEqual(au[0]["expected"], "AU.Labor.unemployment")
        self.assertIsNone(au[0]["actual"])
        self.assertEqual(au[0]["reason"], REASON_MISSING_CALIBRATION)
        countries = {m["country"] for m in report["mismatches"]}
        self.assertEqual(countries, {"AU"})
        ledger = ledger_rows_for_preflight_mismatches(
            report["mismatches"],
            checked_at="2026-01-01",
            calibration_as_of_value="2026-01-01",
            cutoff_class_value="test",
        )
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger[0]["status"], "contract_mismatch")
        cm = ledger[0]["contract_mismatch"]
        for key in (
            "concept_id",
            "country",
            "component",
            "source",
            "field",
            "expected",
            "actual",
            "reason",
        ):
            self.assertIn(key, cm)

    def test_missing_calibration_null_or_non_mapping_blocks_ca_only(self) -> None:
        for bad_value, expected_actual in ((None, None), ("not_a_mapping", "str")):
            catalog = load_catalog()
            calibration = copy.deepcopy(load_calibration())
            calibration["components"]["CA.Labor.wages"] = bad_value
            report = preflight_weighted_series(
                catalog=catalog,
                calibration=calibration,
                histories=self._histories(),
            )
            self.assertFalse(report["ok"])
            self.assertEqual(report["blocked_countries"], ["CA"])
            hits = [m for m in report["mismatches"] if m["concept_id"] == "CA.Labor.wages"]
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["field"], "component")
            self.assertEqual(hits[0]["expected"], "CA.Labor.wages")
            self.assertEqual(hits[0]["actual"], expected_actual)
            self.assertEqual(hits[0]["reason"], REASON_MISSING_CALIBRATION)
            countries = {m["country"] for m in report["mismatches"]}
            self.assertEqual(countries, {"CA"})


if __name__ == "__main__":
    unittest.main()
