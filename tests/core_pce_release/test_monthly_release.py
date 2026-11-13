"""Monthly bundle selection, October 2026 replay, and the September lock."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from scripts.core_pce_release.calculator import calculate
from scripts.core_pce_release.cli import main
from scripts.core_pce_release.history import load_levels
from scripts.core_pce_release.oneshot import run_oneshot
from scripts.core_pce_release.packet import prepare
from scripts.core_pce_release.preflight import assess_release
from scripts.core_pce_release.release_bundle import resolve_release
from scripts.core_pce_release.snapshot import load_snapshot

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "core_pce_release"
SEPTEMBER_PRE = "0.3688405280179773205064998201"
SEPTEMBER_POST = "0.3674603939775941051607229995"
REFERENCE = json.loads((DATA / "october_2026_reference.json").read_text(encoding="utf-8"))
PRE = REFERENCE["post_cpi_pre_ppi"]
POST = REFERENCE["post_ppi"]
PPI_POINTS = DATA / "ppi_points_2026-11-13.json"


class MonthlyPreflightTests(unittest.TestCase):
    def test_october_preflight_is_ready_without_treating_ppi_as_integrity(self) -> None:
        report = assess_release("2026-10")
        self.assertEqual(report["status"], "READY")
        self.assertTrue(report["checks"]["target_cpi_present"])
        self.assertTrue(report["checks"]["anchor_component_indexes"])
        self.assertTrue(report["checks"]["weights_verified"])
        self.assertGreater(report["checks"]["current_period_cpi_observations"], 0)
        self.assertTrue(report["checks"]["ppi_target_present"])
        self.assertNotIn("ppi_not_yet_applied", report["blocking_gaps"])

    def test_missing_ppi_does_not_block_the_cpi_baseline(self) -> None:
        bundle = resolve_release("2026-10")
        assert bundle is not None
        bundle["ppi_points"] = None
        with mock.patch("scripts.core_pce_release.preflight.resolve_release", return_value=bundle):
            report = assess_release("2026-10")
        self.assertEqual(report["status"], "READY")
        self.assertIn("ppi_not_yet_applied", report["awaiting"])
        self.assertFalse(report["checks"]["ppi_target_present"])
        self.assertEqual(report["blocking_gaps"], [])

    def test_september_cpi_cache_is_not_ready_for_october(self) -> None:
        bundle = resolve_release("2026-10")
        assert bundle is not None
        bundle["cpi_cache"] = DATA / "cpi_cache_2026-10-14.json"
        with mock.patch("scripts.core_pce_release.preflight.resolve_release", return_value=bundle):
            report = assess_release("2026-10")
        self.assertEqual(report["status"], "NOT READY")
        self.assertIn("stale_cpi_cache", report["blocking_gaps"])
        self.assertFalse(report["checks"]["target_cpi_present"])

    def test_unknown_month_is_not_ready_and_not_a_forecast(self) -> None:
        report = assess_release("2026-11")
        self.assertEqual(report["status"], "NOT READY")
        self.assertIn("sources_not_yet_acquired", report["blocking_gaps"])


class OctoberReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_post_cpi_baseline_matches_the_frozen_reference(self) -> None:
        out = self.tempdir / "cpi"
        code, text = prepare("cpi", "2026-10", out)
        self.assertEqual(code, 0, text)
        state = json.loads((out / "pre_release_state.json").read_text(encoding="utf-8"))
        detailed = json.loads((out / "detailed.json").read_text(encoding="utf-8"))
        self.assertEqual(state["release"], "2026-10")
        self.assertEqual(state["anchor_period"], "2026-09")
        self.assertEqual(state["information_stage"], "post_cpi_pre_ppi")
        self.assertEqual(detailed["central_mom_percent"], PRE["central_mom_percent"])
        self.assertEqual(detailed["low_mom_percent"], PRE["low_mom_percent"])
        self.assertEqual(detailed["high_mom_percent"], PRE["high_mom_percent"])
        self.assertEqual(detailed["headline"], "NEUTRAL")
        self.assertEqual(detailed["low_headline"], "COLD")
        self.assertEqual(detailed["high_headline"], "HOT")
        self.assertEqual(detailed["nine_month_direction"], "decelerating")
        self.assertTrue(detailed["classification_sensitive"])
        for months in ("3", "6", "9"):
            self.assertEqual(detailed["horizons"][months]["before"], PRE["horizons_before_annualized_percent"][months])
            self.assertEqual(detailed["horizons"][months]["after"], PRE["horizons_after_annualized_percent"][months])
        context = detailed["cpi_context"]
        self.assertFalse(context["used_in_core_pce"])
        self.assertNotEqual(context["mom_percent"], detailed["central_mom_percent"])
        self.assertEqual(context["series_id"], "CUSR0000SA0L1E")
        self.assertIn("snapshot_2026-10-29", state["snapshot_dir"])
        self.assertNotIn("snapshot_2026-09-30", state["snapshot_dir"])

    def test_ppi_update_replays_and_does_not_double_add(self) -> None:
        first = self.tempdir / "first"
        second = self.tempdir / "second"
        code = main(
            ["run-ppi", "--release", "2026-10", "--out", str(first), "--ppi-points", str(PPI_POINTS)]
        )
        self.assertEqual(code, 0)
        again = main(
            ["run-ppi", "--release", "2026-10", "--out", str(second), "--ppi-points", str(PPI_POINTS)]
        )
        self.assertEqual(again, 0)
        audit = json.loads((first / "audit.json").read_text(encoding="utf-8"))
        replay = json.loads((second / "audit.json").read_text(encoding="utf-8"))
        self.assertEqual(audit["availability"], "FRESH")
        self.assertEqual(audit["offline_baseline"]["central_mom_percent"], PRE["central_mom_percent"])
        self.assertEqual(audit["revised"]["central_mom_percent"], POST["central_mom_percent"])
        self.assertEqual(replay["revised"]["central_mom_percent"], POST["central_mom_percent"])
        self.assertEqual(audit["revised"]["headline"], "HOT")
        self.assertEqual(audit["revised"]["low_headline"], "NEUTRAL")
        self.assertEqual(audit["revised"]["high_headline"], "HOT")
        self.assertEqual(audit["revised"]["information_stage"], "ppi_partial")
        self.assertEqual(audit["http"]["requests_made"], 0)
        for months in ("3", "6", "9"):
            self.assertEqual(
                audit["revised"]["horizons"][months]["after"],
                POST["horizons_after_annualized_percent"][months],
            )
        detailed = json.loads((first / "detailed.json").read_text(encoding="utf-8"))
        touched = {row["line"]: row for row in detailed["components"]}
        for line in (184, 185, 186):
            self.assertEqual(touched[line]["seasonal_status_output"], "modeled_not_bea_sa")
            self.assertNotEqual(touched[line]["seasonal_status_output"], "BEA_SA")
        for offset, primary in ((359, 184), (360, 188), (364, 325), (365, 326)):
            self.assertEqual(touched[offset]["mom_percent"], touched[primary]["mom_percent"])
        same_packet = run_oneshot(first, release="2026-10", ppi_points_path=PPI_POINTS)
        self.assertEqual(same_packet["revised"]["central_mom_percent"], POST["central_mom_percent"])
        self.assertEqual(same_packet["http"]["requests_made"], 0)

    def test_october_calculate_without_bundle_does_not_reuse_september(self) -> None:
        snapshot = load_snapshot(DATA / "snapshot_2026-10-29")
        result = calculate(snapshot["components"], snapshot["levels"], "2026-10", [])
        self.assertIsNone(result["central_mom_percent"])
        self.assertEqual(result["headline_reason"], "stale_default_inputs")
        self.assertNotEqual(result.get("central_mom_percent"), SEPTEMBER_PRE)


class SeptemberLockTests(unittest.TestCase):
    def test_official_september_comparison_uses_the_published_index_ratio(self) -> None:
        comparison = json.loads((DATA / "september_2026_official_comparison.json").read_text(encoding="utf-8"))
        official = comparison["official_source"]
        mom = (Decimal(official["index_2026-09"]) / Decimal(official["index_2026-08"]) - 1) * 100
        self.assertEqual(format(mom, "f"), official["index_mom_percent"])
        levels = load_levels(DATA / "snapshot_2026-10-29" / "pcepilfe.csv")
        self.assertEqual(levels["2026-09"], Decimal(official["index_2026-09"]))
        self.assertEqual(levels["2026-08"], Decimal(official["index_2026-08"]))
        self.assertNotIn("2026-10", levels)
        self.assertEqual(comparison["locked_forecast"]["pre_ppi_central_mom_percent"], SEPTEMBER_PRE)
        self.assertEqual(comparison["locked_forecast"]["post_ppi_central_mom_percent"], SEPTEMBER_POST)
        self.assertEqual(
            format(Decimal(SEPTEMBER_POST) - mom, "f"),
            comparison["post_ppi_minus_official_index_mom_percent"],
        )

    def test_september_snapshot_still_excludes_september_pce(self) -> None:
        levels = load_levels(DATA / "snapshot_2026-09-30" / "pcepilfe.csv")
        self.assertEqual(levels["2026-08"], Decimal("130.455"))
        self.assertNotIn("2026-09", levels)


if __name__ == "__main__":
    unittest.main()
