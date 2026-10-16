"""Cross-component checks: preflight semantics, quality gate, runner contract."""

from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_ingestion.contract import load_calibration, load_catalog
from scripts.macro_ingestion.runner import run_ingestion
from scripts.macro_ingestion.series_preflight import run_weighted_series_preflight
from scripts.market_watch_launch.quality_gate import evaluate_gate
from scripts.run_state.identity import (
    REASON_FREQUENCY_MISMATCH,
    REASON_SEASONAL_ADJUSTMENT_MISMATCH,
    REASON_UNITS_MISMATCH,
)
NOW = datetime(2026, 10, 15, 8, 52, 22, tzinfo=timezone.utc)


def _fresh_market_families() -> dict:
    return {
        "macro_hard": {"status": "fresh", "digest": "abc"},
        "news": {"status": "fresh", "digest": "def"},
        "central_bank_research": {"status": "fresh", "digest": "ghi"},
        "market_state": {
            "status": "fresh",
            "digest": "jkl",
            "data": {
                "generated_at": "2026-10-15T08:52:00-04:00",
                "rates": {
                    "US": {"status": "ok"},
                    "CA": {"status": "ok"},
                    "AU": {"status": "ok"},
                    "NZ": {"status": "ok"},
                    "EA": {"status": "ok"},
                    "JP": {"status": "ok"},
                },
                "fx": {"status": "ok"},
            },
        },
    }


def _mutate_ca_unemployment_catalog(**field_overrides: object) -> tuple[dict, dict]:
    catalog = load_catalog()
    calibration = load_calibration()
    for row in catalog["series"]:
        if row["id"] == "CA.Labor.unemployment":
            row.update(field_overrides)
            break
    return catalog, calibration


class TestWeightedSemanticPreflight(unittest.TestCase):
    def test_units_mismatch_reports_field_and_blocks_ca_only(self) -> None:
        catalog, calibration = _mutate_ca_unemployment_catalog(units="index")
        report = run_weighted_series_preflight(
            catalog=catalog,
            calibration=calibration,
            histories=None,
        )
        self.assertFalse(report["ok"])
        self.assertEqual(report["blocked_countries"], ["CA"])
        hits = [m for m in report["mismatches"] if m["concept_id"] == "CA.Labor.unemployment"]
        units_hits = [m for m in hits if m["field"] == "units" and m["source"] == "v2062815"]
        self.assertEqual(len(units_hits), 1)
        self.assertEqual(units_hits[0]["expected"], "percent")
        self.assertEqual(units_hits[0]["actual"], "index")
        self.assertEqual(units_hits[0]["reason"], REASON_UNITS_MISMATCH)
        self.assertEqual(units_hits[0]["country"], "CA")
        self.assertEqual({m["country"] for m in report["mismatches"]}, {"CA"})

    def test_cadence_mismatch_reports_field_and_blocks_ca_only(self) -> None:
        catalog, calibration = _mutate_ca_unemployment_catalog(cadence="quarterly")
        report = run_weighted_series_preflight(
            catalog=catalog,
            calibration=calibration,
            histories=None,
        )
        self.assertFalse(report["ok"])
        self.assertEqual(report["blocked_countries"], ["CA"])
        hits = [m for m in report["mismatches"] if m["concept_id"] == "CA.Labor.unemployment"]
        cadence_hits = [m for m in hits if m["field"] == "cadence" and m["source"] == "v2062815"]
        self.assertEqual(len(cadence_hits), 1)
        self.assertEqual(cadence_hits[0]["expected"], "monthly")
        self.assertEqual(cadence_hits[0]["actual"], "quarterly")
        self.assertEqual(cadence_hits[0]["reason"], REASON_FREQUENCY_MISMATCH)
        self.assertEqual(cadence_hits[0]["country"], "CA")
        self.assertEqual({m["country"] for m in report["mismatches"]}, {"CA"})

    def test_seasonal_adjustment_mismatch_blocks_ca_only(self) -> None:
        catalog, calibration = _mutate_ca_unemployment_catalog(seasonal_adjustment=False)
        report = run_weighted_series_preflight(
            catalog=catalog,
            calibration=calibration,
            histories=None,
        )
        self.assertFalse(report["ok"])
        self.assertEqual(report["blocked_countries"], ["CA"])
        hits = [m for m in report["mismatches"] if m["concept_id"] == "CA.Labor.unemployment"]
        sa_hits = [
            m for m in hits if m["field"] == "seasonal_adjustment" and m["source"] == "v2062815"
        ]
        self.assertEqual(len(sa_hits), 1)
        self.assertEqual(sa_hits[0]["expected"], True)
        self.assertEqual(sa_hits[0]["actual"], False)
        self.assertEqual(sa_hits[0]["reason"], REASON_SEASONAL_ADJUSTMENT_MISMATCH)
        self.assertEqual(sa_hits[0]["country"], "CA")
        self.assertEqual({m["country"] for m in report["mismatches"]}, {"CA"})


class TestQualityGateContractMismatchIsolation(unittest.TestCase):
    def test_ca_contract_mismatch_due_blocks_macro_ca_not_au(self) -> None:
        rows = [
            {
                "series_id": "CA.Labor.unemployment",
                "country": "CA",
                "role": "scored",
                "weight": 0.7,
                "status": "contract_mismatch",
                "release_due": True,
                "observation_period": "2026-08",
                "due_period": "2026-09",
            },
            {
                "series_id": "AU.Labor.unemployment",
                "country": "AU",
                "role": "scored",
                "weight": 0.7,
                "status": "checked_unchanged",
                "release_due": False,
                "observation_period": "2026-08",
                "due_period": "2026-08",
            },
        ]
        result = evaluate_gate(rows=rows, families=_fresh_market_families())
        self.assertIn("macro:CA", result["blocked_expressions"])
        self.assertNotIn("macro:AU", result["blocked_expressions"])
        self.assertIn("CA.Labor.unemployment", result["blocked_sources"])
        self.assertNotIn("AU.Labor.unemployment", result.get("blocked_sources") or [])
        self.assertFalse(result["countries"]["CA"]["eligible"])
        self.assertTrue(result["countries"]["AU"]["eligible"])
        self.assertTrue(result["eligible"])


class TestRunnerTransformMismatchLedger(unittest.TestCase):
    def test_unexpected_transform_copies_raw_sha_and_skips_store(self) -> None:
        from scripts.macro_ingestion.adapters import clear_adapter_overrides, register_adapter_override
        from scripts.macro_ingestion.contract import index_series_rows

        catalog = load_catalog()
        by_id = index_series_rows(catalog["series"])
        spec = copy.deepcopy(by_id["CA.Labor.unemployment"])
        mini = copy.deepcopy(catalog)
        mini["series"] = [spec]
        payload_sha = "deadbeef" * 8

        def fake_fetch(spec, *, opener, now, timeout=20):
            return {
                "ok": True,
                "points": [
                    {"period": "2026-09", "value": 6.5, "transformation": "yoy_pct"},
                ],
                "vintage": "latest_available:test",
                "raw_sha256": payload_sha,
                "http_status": 200,
            }

        with tempfile.TemporaryDirectory() as tmp:
            obs_dir = Path(tmp) / "observations"
            health_dir = Path(tmp) / "health"
            register_adapter_override("CA", fake_fetch)
            try:
                result = run_ingestion(
                    mode="offline",
                    countries=["CA"],
                    catalog=mini,
                    now=NOW,
                    opener=lambda url, **kw: {"ok": False, "error": "unused"},
                    observations_dir=obs_dir,
                    health_dir=health_dir,
                )
            finally:
                clear_adapter_overrides()

        row = result["rows"][0]
        self.assertEqual(row["status"], "transform_mismatch")
        self.assertEqual(row.get("raw_sha256"), payload_sha)
        self.assertEqual(row.get("error"), "unexpected_transformation")
        store_path = obs_dir / "ca.json"
        self.assertFalse(store_path.exists())


if __name__ == "__main__":
    unittest.main()
