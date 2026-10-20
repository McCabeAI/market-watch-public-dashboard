"""Tests for medium-term Prima-pressure link (not a B2 forecast input)."""

from __future__ import annotations

import inspect
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.canadian_cpi_release.cli import _nowcast_payload, main as cli_main
from scripts.canadian_cpi_release.engine import forecast_release
from scripts.canadian_cpi_release.prima_link import (
    _ols_intercept_and_slope,
    attach_medium_term_prima,
    evaluate_ippi_gate,
)
from scripts.canadian_cpi_release.report import render_nowcast_report
from scripts.canadian_cpi_release.sources.acquire import FIXTURE_ROOT, load_snapshot

FIXTURE_PATH = FIXTURE_ROOT / "snapshot.json"
SEPT_HEADLINE = 0.1325763171949602
SECTION_TITLE = "Medium-term Prima-pressure (distinct from the B2 next-print nowcast)"


def _synthetic_rows_linear(n: int, scale: float = 0.5) -> list[dict]:
    """Percent-scale component MoM with IPPI lag on the same numeric scale."""
    rows: list[dict] = []
    for i in range(n):
        x = 4.0 + 0.5 * ((i % 13) - 6) + 0.05 * (i % 5)
        rows.append(
            {
                "component_mom": scale * x,
                "ippi_ex_energy_mom_lag1": x,
            }
        )
    return rows


def _synthetic_rows_b2_incremental(n: int) -> list[dict]:
    rows: list[dict] = []
    for i in range(n):
        x = 100.0 + ((i % 13) - 6)
        b2 = 0.10 + 0.01 * (i % 3)
        actual = b2 + 0.08 * (x - 100.0)
        rows.append(
            {
                "component_mom": actual,
                "ippi_ex_energy_mom_lag1": x,
                "b2_ex_energy_forecast": b2,
            }
        )
    return rows


class PrimaLinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = load_snapshot(FIXTURE_PATH)

    def test_ippi_gate_admits_exact_linear_history(self) -> None:
        gate = evaluate_ippi_gate(_synthetic_rows_linear(80))
        self.assertFalse(gate["admitted"])
        self.assertEqual(gate["decision"], "shadow_only")
        self.assertIn("b2_ex_energy_forecast", gate["reason"].lower())

    def test_ols_slope_uses_centered_predictors(self) -> None:
        x = [100.0 + i for i in range(-5, 6)]
        residual = [0.5 * (xi - 100.0) for xi in x]
        _, beta = _ols_intercept_and_slope(residual, x)
        self.assertAlmostEqual(beta, 0.5, places=9)
        buggy = sum(r * xi for r, xi in zip(residual, x)) / sum(xi * xi for xi in x)
        self.assertGreater(abs(buggy - 0.5), 0.2)
        self.assertNotAlmostEqual(buggy, beta, places=3)

    def test_ippi_gate_admits_incremental_value_over_b2(self) -> None:
        rows = _synthetic_rows_b2_incremental(80)
        gate = evaluate_ippi_gate(rows)
        self.assertTrue(gate["admitted"])
        self.assertEqual(gate["decision"], "admitted")
        self.assertEqual(gate["benchmark"], "b2_ex_energy_forecast")
        self.assertGreaterEqual(gate["evaluation_points"], 24)
        self.assertGreaterEqual(gate["mae_improvement"], 0.02)
        self.assertIsNotNone(gate["residual_beta"])
        self.assertAlmostEqual(gate["residual_beta"], 0.08, places=6)

        eval_rows = rows[24:]
        b2_errors = [abs(r["component_mom"] - r["b2_ex_energy_forecast"]) for r in eval_rows]
        mean_b2_mae = sum(b2_errors) / len(b2_errors)
        ys = [r["component_mom"] for r in eval_rows]
        mean_y_mae = sum(abs(y - sum(ys) / len(ys)) for y in ys) / len(ys)
        self.assertNotAlmostEqual(mean_b2_mae, mean_y_mae, places=6)
        self.assertAlmostEqual(gate["baseline_mae"], mean_b2_mae, places=9)

    def test_ippi_gate_shadow_when_b2_already_perfect(self) -> None:
        rows: list[dict] = []
        for i in range(80):
            x = 2.0 + 0.3 * ((i % 11) - 5)
            b2 = 0.12 + 0.04 * x
            rows.append(
                {
                    "component_mom": b2,
                    "ippi_ex_energy_mom_lag1": x,
                    "b2_ex_energy_forecast": b2,
                }
            )
        gate = evaluate_ippi_gate(rows)
        self.assertFalse(gate["admitted"])
        self.assertEqual(gate["decision"], "shadow_only")
        self.assertIsNotNone(gate["mae_improvement"])
        self.assertLess(abs(gate["mae_improvement"]), 0.02)

    def test_ippi_gate_shadow_on_noise_or_constant_lag(self) -> None:
        import random

        rng = random.Random(42)
        noise_rows = [
            {
                "component_mom": rng.uniform(-0.2, 0.2),
                "ippi_ex_energy_mom_lag1": rng.uniform(-0.05, 0.05),
                "b2_ex_energy_forecast": 0.05,
            }
            for _ in range(80)
        ]
        gate_noise = evaluate_ippi_gate(noise_rows)
        self.assertFalse(gate_noise["admitted"])
        self.assertEqual(gate_noise["decision"], "shadow_only")

        const_rows = [
            {
                "component_mom": 0.1 + 0.01 * (i % 5),
                "ippi_ex_energy_mom_lag1": 0.02,
                "b2_ex_energy_forecast": 0.09 + 0.005 * (i % 7),
            }
            for i in range(80)
        ]
        gate_const = evaluate_ippi_gate(const_rows)
        self.assertFalse(gate_const["admitted"])
        self.assertEqual(gate_const["decision"], "shadow_only")

    def test_attach_leaves_headline_unchanged(self) -> None:
        result = forecast_release(self.snapshot, "2026-09", "2026-10-16")
        payload = _nowcast_payload(result, self.snapshot)
        headline_before = payload["headline_nsa_mom"]
        block = {"direction": "RISING", "status": "ok", "coverage": 0.8}
        gate = evaluate_ippi_gate(_synthetic_rows_b2_incremental(80))
        out = attach_medium_term_prima(payload, block=block, gate=gate)
        self.assertEqual(out["headline_nsa_mom"], headline_before)
        self.assertAlmostEqual(out["headline_nsa_mom"], SEPT_HEADLINE, places=6)
        self.assertFalse(out["medium_term_prima_pressure"]["forecast_active"])
        self.assertEqual(
            out["medium_term_prima_pressure"]["activation_held"],
            "gate_passed_but_not_wired_into_b2",
        )

    def test_report_includes_section_and_disclaimer(self) -> None:
        result = forecast_release(self.snapshot, "2026-09", "2026-10-16")
        payload = attach_medium_term_prima(
            _nowcast_payload(result, self.snapshot),
            block=None,
            gate=evaluate_ippi_gate([]),
        )
        text = render_nowcast_report(payload)
        self.assertIn(SECTION_TITLE, text)
        self.assertIn("not an input", text.lower())

    def test_forecast_release_not_wired_to_prima_block(self) -> None:
        sig = inspect.signature(forecast_release)
        param_names = list(sig.parameters)
        self.assertNotIn("block", param_names)
        self.assertNotIn("prima", " ".join(param_names).lower())

        result = forecast_release(self.snapshot, "2026-09", "2026-10-16")
        self.assertAlmostEqual(result.headline_nsa_mom, SEPT_HEADLINE, places=6)

    def test_cli_nowcast_adds_section_without_changing_headline(self) -> None:
        direct = forecast_release(self.snapshot, "2026-09", "2026-10-16")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            code = cli_main(
                [
                    "nowcast",
                    "--release",
                    "2026-09",
                    "--as-of",
                    "2026-10-16",
                    "--out",
                    str(out),
                    "--fixture",
                    str(FIXTURE_PATH),
                ]
            )
            self.assertEqual(code, 0)
            text = out.joinpath("nowcast.txt").read_text(encoding="utf-8")
            data = json.loads(out.joinpath("nowcast.json").read_text(encoding="utf-8"))
            self.assertIn(SECTION_TITLE, text)
            self.assertAlmostEqual(data["headline_nsa_mom"], direct.headline_nsa_mom, places=12)
            self.assertAlmostEqual(data["headline_nsa_mom"], SEPT_HEADLINE, places=6)


if __name__ == "__main__":
    unittest.main()
