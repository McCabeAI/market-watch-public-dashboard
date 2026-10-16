"""Import-price incremental sensitivity (October 16, 2026 bundle)."""

from __future__ import annotations

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
from scripts.core_pce_release.import_price_report import reconstruct_import_price_increment

BUNDLE = ROOT / "data" / "core_pce_release" / "import_price_2026-10-16"
CONTRACT = json.loads((BUNDLE / "g0_contract.json").read_text(encoding="utf-8"))

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


class ImportPriceIncrementalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = load_import_price_bundle(BUNDLE)

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

    def test_exact_prior_replication_and_determinism(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            report = reconstruct_import_price_increment(out, release="2026-09", bundle_dir=BUNDLE)
            self.assertEqual(report["central_mom_percent"], CONTRACT["prior_post_ppi_central_mom_percent"])
            self.assertEqual(report["low_mom_percent"], CONTRACT["prior_post_ppi_low_mom_percent"])
            self.assertEqual(report["high_mom_percent"], CONTRACT["prior_post_ppi_high_mom_percent"])
            self.assertEqual(report["delta_versus_october_15_ppi_central_percent"], "0")
            self.assertFalse(report["line_335"]["central_updated"])
            self.assertEqual(report["pre_ppi_central_mom_percent"], CONTRACT["prior_post_cpi_pre_ppi_central_mom_percent"])
            for line in ("207", "336", "339"):
                self.assertTrue(report["protected_lines"][line]["unchanged"])
            first = (out / "incremental_report.json").read_bytes()
            reconstruct_import_price_increment(out, release="2026-09", bundle_dir=BUNDLE)
            second = (out / "incremental_report.json").read_bytes()
            self.assertEqual(first, second)

    def test_component_attribution(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = reconstruct_import_price_increment(Path(tmp), bundle_dir=BUNDLE)
            row = report["attribution"][0]
            self.assertEqual(row["line"], 335)
            self.assertEqual(row["central_contribution_delta_percent"], "0")
            self.assertIn("w_import_1", row["endpoint_contribution_deltas_percent"])
            self.assertIn("w_import_0", row["endpoint_contribution_deltas_percent"])

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
                    payload.get("central_mom_percent"),
                    CONTRACT["prior_post_ppi_central_mom_percent"],
                )

    def test_reconstruct_refuses_other_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                reconstruct_import_price_increment(Path(tmp), release="2026-08", bundle_dir=BUNDLE)


if __name__ == "__main__":
    unittest.main()
