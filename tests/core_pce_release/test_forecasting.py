"""Forecasting layer tests (track C2, nowcast_repair_v1)."""

from __future__ import annotations

import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.core_pce_release.calculator import calculate
from scripts.core_pce_release.history import annualized, break_even_mom, project_level, shift_month
from scripts.core_pce_release.snapshot import load_snapshot
from scripts.core_pce_release.verdict import classify_momentum

MODEL_SPEC = json.loads((ROOT / "data" / "core_pce_release" / "model_spec.json").read_text(encoding="utf-8"))
G0 = MODEL_SPEC["g0_reference_post_cpi_pre_ppi"]
THRESHOLDS = MODEL_SPEC["unchanged_momentum_mom_percent"]


class ForecastingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        snapshot = load_snapshot()
        cls.components = snapshot["components"]
        cls.levels = snapshot["levels"]
        cls.target = "2026-09"
        cls.anchor = "2026-08"

    def _calc(self, observations):
        return calculate(self.components, self.levels, self.target, observations)

    def test_empty_observations_match_g0_reference(self):
        result = self._calc([])
        self.assertEqual(result["central_mom_percent"], G0["central_mom_percent"])
        self.assertEqual(result["low_mom_percent"], G0["low_mom_percent"])
        self.assertEqual(result["high_mom_percent"], G0["high_mom_percent"])
        self.assertEqual(result["headline"], G0["central_class"])
        self.assertEqual(result["low_headline"], G0["low_class"])
        self.assertEqual(result["high_headline"], G0["high_class"])
        self.assertTrue(result["classification_sensitive"])
        self.assertEqual(result["information_stage"], "post_cpi_pre_ppi")
        self.assertIsNotNone(result["projected_core_pce_mom_percent"])
        self.assertEqual(result["nine_month_direction"], "accelerating")
        for months in (3, 6, 9):
            self.assertEqual(
                result["horizons"][str(months)]["after"],
                G0["horizons_after_annualized_percent"][str(months)],
            )
            self.assertEqual(
                result["horizons"][str(months)]["unchanged_momentum_mom_percent"],
                THRESHOLDS[str(months)],
            )

    def test_point_two_eight_synthetic_aggregate_is_hot(self):
        anchor = self.levels[self.anchor]
        september = project_level(anchor, Decimal("0.28"))
        deltas = {}
        for months in (3, 6, 9):
            base = self.levels[shift_month(self.target, -months)]
            post = annualized(september, base, months)
            before = annualized(anchor, base, months)
            deltas[months] = post - before
        self.assertEqual(classify_momentum(deltas), "HOT")

    def test_exact_threshold_mom_is_not_hot_when_six_month_delta_zero(self):
        for months in (3, 6, 9):
            self.assertEqual(
                format(break_even_mom(self.levels, self.anchor, months), "f"),
                THRESHOLDS[str(months)],
            )
        deltas = {3: Decimal(0), 6: Decimal(0), 9: Decimal(1)}
        self.assertEqual(classify_momentum(deltas), "NEUTRAL")

    def test_hospital_ppi_news_moves_line_185_once(self):
        baseline = self._calc([])
        base_central = Decimal(baseline["central_mom_percent"])
        by_line = {r["line"]: r for r in baseline["components"]}
        weight_185 = Decimal(by_line[185]["weight_share"])
        weight_186 = Decimal(by_line[186]["weight_share"])
        baseline_mom_184 = Decimal(by_line[184]["mom_percent"])
        baseline_mom_185 = Decimal(by_line[185]["mom_percent"])
        baseline_mom_186 = Decimal(by_line[186]["mom_percent"])
        ppi_aug = Decimal("1.0")
        ppi_sep = Decimal("1.5")
        news = ppi_sep - ppi_aug
        hospital_lines = (184, 185, 186, 359)
        observations = []
        for period, mom in ((self.target, ppi_sep), (self.anchor, ppi_aug)):
            for line in hospital_lines:
                observations.append(
                    {
                        "line": line,
                        "series_id": "PCU622---622---",
                        "period": period,
                        "mom_percent": str(mom),
                        "role": "raw_bls_reference",
                        "source_family": "PPI",
                        "seasonal_status": "BLS_NSA",
                    }
                )
        updated = self._calc(observations)
        upd = {r["line"]: r for r in updated["components"]}
        self.assertEqual(Decimal(upd[184]["mom_percent"]), baseline_mom_184 + news)
        self.assertEqual(Decimal(upd[185]["mom_percent"]), baseline_mom_185 + news)
        self.assertEqual(Decimal(upd[186]["mom_percent"]), baseline_mom_186 + news)
        self.assertEqual(upd[184]["mom_percent"], upd[359]["mom_percent"])
        self.assertEqual(upd[184]["seasonal_status_output"], "modeled_not_bea_sa")
        self.assertEqual(upd[359]["seasonal_status_output"], "modeled_not_bea_sa")
        delta_agg = Decimal(updated["central_mom_percent"]) - base_central
        expected_delta = (weight_185 + weight_186) * news
        self.assertAlmostEqual(delta_agg, expected_delta, places=25)
        self.assertEqual(upd[346]["mom_percent"], by_line[346]["mom_percent"])
        second = self._calc(observations + observations)
        self.assertEqual(second["central_mom_percent"], updated["central_mom_percent"])

    def test_line_268_rejects_portfolio_ppi(self):
        baseline = self._calc([])
        row268 = next(r for r in baseline["components"] if r["line"] == 268)
        observations = [
            {
                "line": 268,
                "series_id": "PCU5231505231501011",
                "period": self.target,
                "mom_percent": "-1.6",
                "role": "raw_bls_reference",
                "source_family": "PPI",
            }
        ]
        result = self._calc(observations)
        row268_new = next(r for r in result["components"] if r["line"] == 268)
        self.assertEqual(row268_new["mom_percent"], row268["mom_percent"])
        reasons = {item.get("reason") for item in result["rejected_observations"]}
        self.assertIn("implicit_rejects_bls", reasons)

    def test_stale_period_and_extreme_mom_rejected(self):
        baseline = self._calc([])
        observations = [
            {
                "line": 174,
                "series_id": "PCU6211--6211--",
                "period": "2026-07",
                "mom_percent": "0.2",
                "role": "raw_bls_reference",
                "source_family": "PPI",
            },
            {
                "line": 174,
                "series_id": "PCU6211--6211--",
                "period": self.target,
                "mom_percent": "40",
                "role": "raw_bls_reference",
                "source_family": "PPI",
            },
        ]
        result = self._calc(observations)
        self.assertEqual(result["central_mom_percent"], baseline["central_mom_percent"])

    def test_raw_observation_keeps_modeled_not_bea_sa(self):
        observations = [
            {
                "line": 185,
                "series_id": "PCU622---622---",
                "period": self.target,
                "mom_percent": "0.5",
                "role": "raw_bls_reference",
                "source_family": "PPI",
                "seasonal_status": "BLS_NSA",
            }
        ]
        result = self._calc(observations)
        row = next(r for r in result["components"] if r["line"] == 185)
        self.assertEqual(row["seasonal_status_output"], "modeled_not_bea_sa")

    def test_scenario_class_difference_keeps_projected(self):
        result = self._calc([])
        self.assertTrue(result["classification_sensitive"])
        self.assertIsNotNone(result["projected_core_pce_mom_percent"])
        self.assertEqual(result["headline"], "HOT")
        self.assertEqual(result["low_headline"], "NEUTRAL")


if __name__ == "__main__":
    unittest.main()
