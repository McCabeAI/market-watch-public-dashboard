"""Quarterly headline NSA identity and September 2026 forecast arithmetic."""

from __future__ import annotations

import unittest
from pathlib import Path

from scripts.au_cpi_release import NOWCAST_SCHEMA_V2
from scripts.au_cpi_release.engine import forecast_release
from scripts.au_cpi_release.models import (
    build_frame,
    build_quarterly_headline_identity,
    percent_change,
    quarter_average_headline,
    quarterly_headline_qoq_yoy,
    round_1dp,
)
from scripts.au_cpi_release.sources.acquire import load_snapshot

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "scripts" / "au_cpi_release" / "fixtures" / "pre_2026-10-28"
MONTHLY_CSV = FIXTURE / "raw" / "abs_cpi_headline_original.csv"
QUARTERLY_CSV = (
    REPO
    / "docs"
    / "au_cpi_release"
    / "provenance"
    / "2026-10-21T183259Z-abs-cpi-headline-quarterly"
    / "abs_cpi_headline_quarterly.csv"
)
AS_OF = "2026-10-22T01:50:00+11:00"
MOM = 0.5055526076899186


class QuarterlyHeadlineIdentityTests(unittest.TestCase):
    def test_archived_quarterly_csv_and_identity_gaps(self) -> None:
        self.assertTrue(QUARTERLY_CSV.is_file())
        report = build_quarterly_headline_identity(quarterly_csv=QUARTERLY_CSV, monthly_csv=MONTHLY_CSV)
        self.assertFalse(report["2026_q3_in_official_quarterly"])
        self.assertEqual(report["latest_official_quarter"], "2026-Q2")
        self.assertLessEqual(float(report["max_abs_index_gap_post_2025_q4"]), 0.01)
        self.assertGreaterEqual(float(report["max_abs_index_gap_2024_q2_through_2025_q2"]), 0.02)
        for quarter in ("2025-Q4", "2026-Q1", "2026-Q2"):
            row = next(r for r in report["rows"] if r.get("quarter") == quarter)
            self.assertEqual(row["qoq_from_monthly_average_1dp"], row["official_qoq_1dp"])

    def test_september_2026_forecast_arithmetic(self) -> None:
        snapshot = load_snapshot(FIXTURE / "snapshot.json")
        frame = build_frame(snapshot.observations, as_of=AS_OF)
        bundle = quarterly_headline_qoq_yoy(frame, "2026-Q3", last_month_mom=MOM)
        self.assertIsNotNone(bundle)
        self.assertAlmostEqual(bundle["month_levels"]["2026-09"], 104.02324694895907, places=9)
        self.assertAlmostEqual(bundle["prior_quarter_average"], 102.30666666666667, places=9)
        self.assertAlmostEqual(bundle["quarter_average"], 103.53108231631968, places=9)
        self.assertAlmostEqual(bundle["qoq"], 1.1968092496282612, places=9)
        self.assertAlmostEqual(bundle["yoy"], 3.8148428868771456, places=9)
        self.assertEqual(round_1dp(bundle["qoq"]), 1.2)
        self.assertEqual(round_1dp(bundle["yoy"]), 3.8)

    def test_official_denominator_diagnostics(self) -> None:
        from scripts.au_cpi_release.models import _observation_map_from_csv

        snapshot = load_snapshot(FIXTURE / "snapshot.json")
        frame = build_frame(snapshot.observations, as_of=AS_OF)
        bundle = quarterly_headline_qoq_yoy(frame, "2026-Q3", last_month_mom=MOM)
        official = _observation_map_from_csv(QUARTERLY_CSV, "quarterly_official")
        official_q2 = official.get(("headline_nsa_quarterly_index", "2026-Q2"))
        official_2025_q3 = official.get(("headline_nsa_quarterly_index", "2025-Q3"))
        self.assertIsNotNone(official_q2)
        self.assertIsNotNone(official_2025_q3)
        qoq_off = percent_change(bundle["quarter_average"], official_q2)  # type: ignore[arg-type]
        yoy_off = percent_change(bundle["quarter_average"], official_2025_q3)  # type: ignore[arg-type]
        self.assertAlmostEqual(qoq_off, 1.1935121848496433, places=9)
        self.assertAlmostEqual(yoy_off, 3.811373023483089, places=9)


class QuarterlyTrimmedMeanAuditTests(unittest.TestCase):
    def test_candidate_models_locked(self) -> None:
        from scripts.au_cpi_release.models import CANDIDATE_MODELS, PROXY_BRIDGE_MODEL

        self.assertEqual(
            CANDIDATE_MODELS["trimmed_mean_quarterly_legacy_qoq"],
            ("persistence", "mean_4"),
        )
        self.assertNotIn(PROXY_BRIDGE_MODEL, CANDIDATE_MODELS["trimmed_mean_quarterly_legacy_qoq"])

    def test_bridge_gap_on_fixture(self) -> None:
        from scripts.au_cpi_release.models import quarterly_bridge_gap

        snapshot = load_snapshot(FIXTURE / "snapshot.json")
        frame = build_frame(snapshot.observations, as_of=AS_OF)
        gap = quarterly_bridge_gap(frame)
        self.assertEqual(gap["n_overlap"], 8)
        self.assertAlmostEqual(float(gap["mean_abs_gap_pp"]), 0.07323325535004699, places=9)

    def test_v2_september_selects_persistence_and_reports_bridge_shadow(self) -> None:
        snapshot = load_snapshot(FIXTURE / "snapshot.json")
        result = forecast_release(
            snapshot,
            release="2026-09",
            as_of=AS_OF,
            generated_at="2026-10-22T01:00:00+11:00",
            snapshot_dir=FIXTURE,
            schema_version=NOWCAST_SCHEMA_V2,
        )
        qoq = result["targets"]["trimmed_mean_quarterly_legacy_qoq"]
        self.assertEqual(qoq["method"], "persistence")
        self.assertAlmostEqual(float(qoq["value"]), 0.8125952260030544, places=9)
        bridge = result["diagnostics"]["quarterly_bridge"]
        self.assertEqual(bridge["model"], "proxy_bridge_non_equivalent")
        self.assertAlmostEqual(float(bridge["value"]), 1.0437709077788515, places=9)
        shadow = qoq.get("shadow_conflicts") or {}
        self.assertTrue(shadow.get("ineligible"))

    def test_persistence_beats_mean_4_and_seasonal_naive_on_cpi_q_index(self) -> None:
        from statistics import fmean

        from scripts.au_cpi_release.contract import previous_quarter
        from scripts.au_cpi_release.models import add_quarters, change_at, mean_last, quarter_months

        snapshot = load_snapshot(FIXTURE / "snapshot.json")
        frame = build_frame(snapshot.observations, as_of=AS_OF)
        quarters = frame.periods("trimmed_mean_quarterly_legacy_index")
        errors: dict[str, list[float]] = {"persistence": [], "mean_4": [], "seasonal_naive": []}
        for quarter in quarters:
            actual = change_at(frame, "trimmed_mean_quarterly_legacy_index", quarter, previous_quarter)
            if actual is None:
                continue
            preds = {
                "persistence": mean_last(
                    frame, "trimmed_mean_quarterly_legacy_index", quarter, 1, previous_quarter
                ),
                "mean_4": mean_last(
                    frame, "trimmed_mean_quarterly_legacy_index", quarter, 4, previous_quarter
                ),
                "seasonal_naive": frame.get(
                    "trimmed_mean_quarterly_legacy_qoq", add_quarters(quarter, -4)
                ),
            }
            for model, forecast in preds.items():
                if forecast is None:
                    continue
                errors[model].append(abs(float(forecast) - float(actual)))
        mae = {model: fmean(vals) for model, vals in errors.items() if vals}
        self.assertLess(mae["persistence"], mae["mean_4"])
        self.assertLess(mae["mean_4"], mae["seasonal_naive"])
        recent = [q for q in quarters if q >= "2024-Q1"]
        err_2024 = {"persistence": [], "mean_4": []}
        for quarter in recent:
            actual = change_at(frame, "trimmed_mean_quarterly_legacy_index", quarter, previous_quarter)
            p = mean_last(frame, "trimmed_mean_quarterly_legacy_index", quarter, 1, previous_quarter)
            m4 = mean_last(frame, "trimmed_mean_quarterly_legacy_index", quarter, 4, previous_quarter)
            if actual is None or p is None or m4 is None:
                continue
            err_2024["persistence"].append(abs(p - actual))
            err_2024["mean_4"].append(abs(m4 - actual))
        gap = fmean(err_2024["mean_4"]) - fmean(err_2024["persistence"])
        self.assertLess(gap, 0.02)


if __name__ == "__main__":
    unittest.main()
