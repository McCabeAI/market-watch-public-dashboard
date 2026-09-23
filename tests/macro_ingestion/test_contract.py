"""Catalog contract validation tests."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_ingestion.contract import (
    STATUS_VOCABULARY,
    CatalogValidationError,
    load_baseline_catalog,
    load_catalog,
    validate_catalog_against_baseline,
)


class TestMacroIngestionContract(unittest.TestCase):
    def test_baseline_loads_and_vocab_matches_architecture(self) -> None:
        catalog = load_baseline_catalog()
        self.assertEqual(catalog["scored_weight_row_count"], 66)
        self.assertEqual(tuple(catalog["status_vocabulary"]), STATUS_VOCABULARY)

    def test_baseline_validates_against_calibration(self) -> None:
        catalog = load_catalog()
        validate_catalog_against_baseline(catalog)

    def test_rejects_weight_drift(self) -> None:
        catalog = load_catalog()
        bad = copy.deepcopy(catalog)
        for row in bad["series"]:
            if row["id"] == "US.Inflation.core_pce":
                row["weight"] = 0.5
                break
        with self.assertRaises(CatalogValidationError):
            validate_catalog_against_baseline(bad)

    def test_rejects_missing_baseline_id(self) -> None:
        catalog = load_catalog()
        bad = copy.deepcopy(catalog)
        bad["series"] = [r for r in bad["series"] if r["id"] != "US.Inflation.core_pce"]
        with self.assertRaises(CatalogValidationError):
            validate_catalog_against_baseline(bad)

    def test_context_weight_must_be_zero(self) -> None:
        catalog = load_catalog()
        bad = copy.deepcopy(catalog)
        for row in bad["series"]:
            if row["role"] == "context":
                row["weight"] = 0.1
                break
        with self.assertRaises(CatalogValidationError):
            validate_catalog_against_baseline(bad)


if __name__ == "__main__":
    unittest.main()
