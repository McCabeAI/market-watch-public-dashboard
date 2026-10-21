"""Trim reconstruction verdict and the partial-boundary weighted mean."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.au_cpi_release.cli import main
from scripts.au_cpi_release.sources.acquire import load_snapshot
from scripts.au_cpi_release.trim import (
    expenditure_class_ids,
    trimmed_weighted_mean,
    verify_trim,
)

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "au_cpi_release"
    / "fixtures"
    / "pre_2026-10-28"
    / "snapshot.json"
)


class TrimTests(unittest.TestCase):
    def test_partial_boundary_weight(self) -> None:
        # 15% trimmed from each tail. Boundary classes keep only the inside weight.
        result = trimmed_weighted_mean([1.0, 2.0, 10.0, 100.0], [0.25, 0.25, 0.25, 0.25])
        self.assertAlmostEqual(result, 13.1 / 0.7, places=9)

    def test_leaf_rule_on_a_small_codelist(self) -> None:
        structure = {
            "data": {
                "codelists": [
                    {
                        "id": "CL_CPI_INDEX",
                        "codes": [
                            {"id": "10001", "name": "All groups", "annotations": [{"type": "ORDER", "text": "1"}]},
                            {"id": "20001", "name": "Group", "parent": "10001", "annotations": [{"type": "ORDER", "text": "2"}]},
                            {"id": "40001", "name": "Class A", "parent": "20001", "annotations": [{"type": "ORDER", "text": "3"}]},
                            {"id": "40002", "name": "Class B", "parent": "20001", "annotations": [{"type": "ORDER", "text": "4"}]},
                            {"id": "999902", "name": "Trimmed mean", "annotations": [{"type": "ORDER", "text": "9"}]},
                        ],
                    }
                ]
            }
        }
        leaves, depths = expenditure_class_ids(structure)
        self.assertEqual(leaves, ["40001", "40002"])
        self.assertEqual(depths, {"2": 2})

    def test_fixture_verifier_returns_a_structured_verdict(self) -> None:
        snapshot = load_snapshot(FIXTURE)
        report = verify_trim(snapshot, FIXTURE.parent)
        self.assertEqual(report["schema_version"], "au_cpi_trim_verification_v1")
        self.assertEqual(report["class_identification"]["class_count"], 87)
        self.assertEqual(report["class_identification"]["depth_histogram"], {"3": 87})
        self.assertIn(report["g5_verdict"], ("pass", "fail"))
        self.assertIn(report["g5_claim"], ("reconstruction", "proxy"))
        self.assertEqual(report["g5_claim"], "reconstruction" if report["g5_verdict"] == "pass" else "proxy")
        primary = report["variants"][0]
        self.assertEqual(primary["variant_id"], report["primary_variant"])
        self.assertGreaterEqual(primary["months_covered"], 12)
        self.assertGreaterEqual(primary["rounded_match_rate"], 0.90)
        self.assertLessEqual(primary["max_abs_error_unrounded_pp"], 0.05)
        self.assertEqual(primary["class_count_min"], 87)
        self.assertTrue(report["coverage_note"])
        quarterly = report["quarterly_legacy_equivalence"]
        self.assertIn(quarterly["verdict"], ("equivalent", "not_equivalent", "blocked", "equivalent_vs_rba_appendix_not_obtained", "equivalent_vs_rba_appendix_not_equivalent"))
        rba = quarterly["cpi_q_vs_rba_g1_GCPIOCPMTMQP"]
        self.assertGreaterEqual(rba["n_overlap"], 12)
        self.assertEqual(rba["verdict"], "equivalent")
        self.assertEqual(rba["max_abs_diff_pp"], 0.0)
        appendix = quarterly["cpi_q_vs_appendix_1a"]
        self.assertEqual(appendix["verdict"], "equivalent")
        self.assertEqual(quarterly["verdict"], "equivalent")

    def test_verify_trim_cli_is_offline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code = main(["verify-trim", "--fixture", str(FIXTURE), "--out", tmp])
            self.assertEqual(code, 0)
            payload = json.loads((Path(tmp) / "trim_verification.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["g5_verdict"], "pass")
            self.assertEqual(payload["g5_claim"], "reconstruction")


if __name__ == "__main__":
    unittest.main()
