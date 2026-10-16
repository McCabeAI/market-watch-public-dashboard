"""Import-price incremental sensitivity (October 16, 2026 bundle)."""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.core_pce_release.import_price_bridge import (
    ImportPriceBlocked,
    assert_not_published_rounding,
    composite_nsa_mom,
    index_ratio_mom,
    line_335_central_update,
    nsa_sensitivity_envelope,
)
from scripts.core_pce_release.import_price_fixture import ImportPriceSourceError, load_import_price_bundle
from scripts.core_pce_release.import_price_line335 import (
    load_line335_history,
    predict_month,
    september_2026_estimate,
    walk_forward,
)
from scripts.core_pce_release.import_price_report import reconstruct_import_price_increment

BUNDLE = ROOT / "data" / "core_pce_release" / "import_price_2026-10-16"
CONTRACT = json.loads((BUNDLE / "g0_contract.json").read_text(encoding="utf-8"))
HISTORY_PATH = BUNDLE / "line335_history.json"

IMPORT_INDEX = Decimal("190.8")
IMPORT_PRIOR = Decimal("169.4")
PPI_INDEX = Decimal("265.040")
PPI_PRIOR = Decimal("276.479")
IMPORT_MOM = Decimal("12.63282172373081463990554900")
PPI_MOM = Decimal("-4.137384756165929419594254900")
CARRIED_335 = Decimal("3.920759759301939753741850400")
WEIGHT_335 = Decimal("0.003967987953834691354596872703")
DELTA_IMPORT = "0.03456935692791517287606283182"
DELTA_PPI = "-0.03197462036763559059953097081"
OCT15_CENTRAL = CONTRACT["prior_post_ppi_central_mom_percent"]


class ImportPriceIncrementalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = load_import_price_bundle(BUNDLE)
        cls.history = load_line335_history(HISTORY_PATH)

    def test_source_identity(self):
        import_leg = self.bundle["import_leg"]
        ppi_leg = self.bundle["ppi_leg"]
        prov = self.bundle["provenance"]
        self.assertEqual(import_leg["series_id"], "EIUIV142")
        self.assertEqual(import_leg["period"], "2026-09")
        self.assertEqual(import_leg["prior_period"], "2026-08")
        self.assertEqual(import_leg["seasonal_status"], "NSA")
        self.assertEqual(import_leg["index"], "190.8")
        self.assertEqual(import_leg["prior_index"], "169.4")
        self.assertEqual(ppi_leg["series_id"], "PCU4811114811112")
        self.assertEqual(ppi_leg["seasonal_status"], "NSA")
        self.assertEqual(ppi_leg["index"], "265.040")
        self.assertEqual(ppi_leg["prior_index"], "276.479")
        self.assertEqual(ppi_leg["footnote_code"], "P")
        rel = prov["series"]["import_leg"]["release"]
        self.assertEqual(rel["release_id"], "USDL-26-1577")
        self.assertEqual(rel["embargo_until"], "2026-10-16T08:30:00-04:00")

    def test_index_to_mom(self):
        mom = index_ratio_mom(IMPORT_INDEX, IMPORT_PRIOR)
        self.assertEqual(mom, IMPORT_MOM)
        self.assertNotEqual(mom, Decimal("12.6"))
        assert_not_published_rounding(mom, Decimal("12.6"))
        with self.assertRaises(ImportPriceBlocked) as ctx:
            assert_not_published_rounding(Decimal("12.6"), Decimal("12.6"))
        self.assertEqual(ctx.exception.reason, "published_rounding_substituted")
        ppi_mom = index_ratio_mom(PPI_INDEX, PPI_PRIOR)
        self.assertEqual(ppi_mom, PPI_MOM)

    def test_multi_leg_arithmetic(self):
        w = Decimal("0.25")
        composite = composite_nsa_mom(IMPORT_MOM, PPI_MOM, w)
        self.assertEqual(composite, w * IMPORT_MOM + (Decimal(1) - w) * PPI_MOM)
        blocked = line_335_central_update(
            import_mom=IMPORT_MOM,
            ppi_mom=PPI_MOM,
            import_seasonal_status="NSA",
            ppi_seasonal_status="NSA",
        )
        self.assertEqual(blocked["reason"], "weights_unverified")
        self.assertFalse(blocked["central_revision_allowed"])

    def test_signed_contribution_endpoints(self):
        envelope = nsa_sensitivity_envelope(IMPORT_MOM, PPI_MOM, CARRIED_335, WEIGHT_335)
        w1 = envelope["endpoints"]["w_import_1"]["contribution_delta_percent"]
        w0 = envelope["endpoints"]["w_import_0"]["contribution_delta_percent"]
        self.assertEqual(w1, DELTA_IMPORT)
        self.assertEqual(w0, DELTA_PPI)
        self.assertGreater(Decimal(w1), 0)
        self.assertLess(Decimal(w0), 0)
        self.assertGreater(WEIGHT_335, 0)

    def test_missing_international_ppi_leg(self):
        envelope = nsa_sensitivity_envelope(IMPORT_MOM, None, CARRIED_335, WEIGHT_335)
        self.assertEqual(envelope["status"], "blocked")
        self.assertEqual(envelope["reason"], "missing_international_ppi_leg")
        self.assertNotIn("endpoints", envelope)
        blocked = line_335_central_update(import_mom=IMPORT_MOM, ppi_mom=None)
        self.assertFalse(blocked["central_revision_allowed"])

    def test_nsa_labeled_as_bea_sa(self):
        blocked = line_335_central_update(
            import_mom=IMPORT_MOM,
            ppi_mom=PPI_MOM,
            import_seasonal_status="BEA_SA",
            ppi_seasonal_status="NSA",
        )
        self.assertEqual(blocked["reason"], "nsa_passed_as_bea_sa")

    def test_no_september_2026_bea_index_in_history(self):
        self.assertNotIn("2026-09", self.history["bea_indexes"])

    def test_september_bls_indexes_in_history(self):
        imp = self.history["predictors"]["import_air_passenger_fares"]["indexes"]
        ppi = self.history["predictors"]["ppi_international_scheduled_passenger"]["indexes"]
        self.assertEqual(imp["2026-09"], "190.8")
        self.assertEqual(imp["2026-08"], "169.4")
        self.assertEqual(ppi["2026-09"], "265.040")
        self.assertEqual(ppi["2026-08"], "276.479")

    def test_gate_passes_and_model_beats_baselines(self):
        wf = walk_forward(self.history)
        self.assertTrue(wf["gate_passed"])
        self.assertGreaterEqual(wf["n"], 60)
        self.assertLess(wf["mae"]["model"], wf["mae"]["carry"])
        self.assertLess(wf["mae"]["model"], wf["mae"]["three_month"])

    def test_predict_month_matches_walk_forward(self):
        wf = walk_forward(self.history)
        pred = predict_month(self.history, "2019-06")
        record = next(r for r in wf["records"] if r["period"] == "2019-06")
        self.assertAlmostEqual(pred["prediction"], record["prediction"], places=9)

    def test_predict_month_ignores_future_bea_labels(self):
        pred_base = predict_month(self.history, "2019-06")
        trimmed = copy.deepcopy(self.history)
        trimmed["bea_indexes"] = {k: v for k, v in trimmed["bea_indexes"].items() if k < "2019-06"}
        pred_trim = predict_month(trimmed, "2019-06")
        self.assertAlmostEqual(pred_base["prediction"], pred_trim["prediction"], places=9)

    def test_september_estimate_ignores_injected_bea_label(self):
        base = september_2026_estimate(self.history)
        poisoned = copy.deepcopy(self.history)
        poisoned["bea_indexes"]["2026-09"] = "999.0"
        alt = september_2026_estimate(poisoned)
        self.assertEqual(base["model_mom"], alt["model_mom"])

    def test_exact_prior_replication_and_determinism(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            report = reconstruct_import_price_increment(out, release="2026-09", bundle_dir=BUNDLE)
            self.assertEqual(report["october15_ppi_central_mom_percent"], OCT15_CENTRAL)
            self.assertEqual(report["pre_ppi_central_mom_percent"], CONTRACT["prior_post_cpi_pre_ppi_central_mom_percent"])
            for line in ("207", "336", "339"):
                self.assertTrue(report["protected_lines"][line]["unchanged"])
            model_mom = Decimal(report["line_335"]["model_mom_percent"])
            if report["line_335"]["model"]["gate_passed"]:
                expected_delta = WEIGHT_335 * (model_mom - CARRIED_335)
                actual_delta = Decimal(report["delta_versus_october_15_ppi_central_percent"])
                self.assertEqual(actual_delta, Decimal(report["central_mom_percent"]) - Decimal(OCT15_CENTRAL))
                self.assertEqual(
                    Decimal(report["attribution"][0]["central_contribution_delta_percent"]),
                    actual_delta,
                )
                self.assertAlmostEqual(actual_delta, expected_delta, places=27)
                self.assertNotEqual(report["central_mom_percent"], OCT15_CENTRAL)
                self.assertTrue(report["line_335"]["central_updated"])
            else:
                self.assertEqual(report["central_mom_percent"], OCT15_CENTRAL)
                self.assertEqual(report["delta_versus_october_15_ppi_central_percent"], "0")
            first = (out / "incremental_report.json").read_bytes()
            reconstruct_import_price_increment(out, release="2026-09", bundle_dir=BUNDLE)
            second = (out / "incremental_report.json").read_bytes()
            self.assertEqual(first, second)

    def test_component_attribution(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = reconstruct_import_price_increment(Path(tmp), bundle_dir=BUNDLE)
            row = report["attribution"][0]
            self.assertEqual(row["line"], 335)
            self.assertIn("w_import_1", row["endpoint_contribution_deltas_percent"])
            self.assertIn("w_import_0", row["endpoint_contribution_deltas_percent"])
            if report["line_335"]["model"]["gate_passed"]:
                self.assertNotEqual(row["central_contribution_delta_percent"], "0")

    def test_source_failure_fixture_sha_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            corrupt_root = Path(tmp) / "bundle"
            shutil.copytree(BUNDLE, corrupt_root)
            bls_path = corrupt_root / "bls_api_air_2026.json"
            bls_path.write_text(bls_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            out = Path(tmp) / "out"
            with self.assertRaises(ImportPriceSourceError) as ctx:
                reconstruct_import_price_increment(out, bundle_dir=corrupt_root)
            self.assertEqual(ctx.exception.reason, "fixture_sha_mismatch")
            if (out / "incremental_report.json").exists():
                payload = json.loads((out / "incremental_report.json").read_text(encoding="utf-8"))
                self.assertEqual(
                    payload.get("october15_ppi_central_mom_percent"),
                    OCT15_CENTRAL,
                )

    def test_reconstruct_refuses_other_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                reconstruct_import_price_increment(Path(tmp), release="2026-08", bundle_dir=BUNDLE)


if __name__ == "__main__":
    unittest.main()
