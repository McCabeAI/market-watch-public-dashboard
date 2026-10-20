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


class PrimaLinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = load_snapshot(FIXTURE_PATH)

    def test_ippi_gate_admits_exact_linear_history(self) -> None:
        gate = evaluate_ippi_gate(_synthetic_rows_linear(80))
        self.assertTrue(gate["admitted"])
        self.assertEqual(gate["decision"], "admitted")
        self.assertGreaterEqual(gate["evaluation_points"], 24)
        self.assertIsNotNone(gate["mae_improvement"])
        self.assertGreaterEqual(gate["mae_improvement"], 0.02)

    def test_ippi_gate_shadow_on_noise_or_constant_lag(self) -> None:
        import random

        rng = random.Random(42)
        noise_rows = [
            {
                "component_mom": rng.uniform(-0.2, 0.2),
                "ippi_ex_energy_mom_lag1": rng.uniform(-0.05, 0.05),
            }
            for _ in range(80)
        ]
        gate_noise = evaluate_ippi_gate(noise_rows)
        self.assertFalse(gate_noise["admitted"])
        self.assertEqual(gate_noise["decision"], "shadow_only")

        const_rows = [
            {"component_mom": 0.1 + 0.01 * (i % 5), "ippi_ex_energy_mom_lag1": 0.02}
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
        gate = evaluate_ippi_gate(_synthetic_rows_linear(80))
        out = attach_medium_term_prima(payload, block=block, gate=gate)
        self.assertEqual(out["headline_nsa_mom"], headline_before)
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
