"""Attribution accounting identity and honest diagnostic labeling."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.country_detail.render import _render_us_employment_context
from scripts.macro_ingestion.us_employment.derived import attribution_channels


class TestSeptemberStyleAccounting(unittest.TestCase):
    def test_adversarial_september_2026_levels(self) -> None:
        prior = {
            "unemployed": 7031,
            "labor_force": 169777,
            "household_employment": 162746,
        }
        now = {
            "unemployed": 7109,
            "labor_force": 170262,
            "household_employment": 163152,
        }
        report = attribution_channels(now, prior)
        accounting = report["accounting"]

        self.assertNotIn("primary_cause", report)
        self.assertNotIn("labor_force_expansion", report["diagnostic_channels"])
        self.assertFalse(accounting["additive_labor_force_cause"])
        self.assertAlmostEqual(accounting["labor_force_absorption"], -79.0)
        self.assertAlmostEqual(accounting["identity_implied_unemployment_change"], 79.0)
        self.assertAlmostEqual(accounting["identity_residual"], -1.0)
        self.assertFalse(report["diagnostic_channels_are_additive_decomposition"])

    def test_render_shows_accounting_not_primary_cause(self) -> None:
        block = {
            "sections": {
                "post_print_attribution": {
                    "metrics": [],
                    "accounting": {
                        "identity": "delta_unemployed = delta_labor_force - delta_household_employment",
                        "delta_unemployed": 78.0,
                        "delta_labor_force": 485.0,
                        "delta_household_employment": 406.0,
                        "labor_force_absorption": -79.0,
                        "identity_implied_unemployment_change": 79.0,
                        "identity_residual": -1.0,
                        "additive_labor_force_cause": False,
                    },
                    "diagnostic_channels": {},
                    "diagnostic_channels_are_additive_decomposition": False,
                    "diagnostic_sources": {},
                },
            },
        }
        html = _render_us_employment_context(block)
        lowered = html.lower()
        self.assertNotIn("primary cause", lowered)
        self.assertNotIn("labor-force expansion", lowered)
        self.assertIn("-79", html)
        self.assertIn("485", html)
        self.assertIn("406", html)
        self.assertIn("78", html)
        self.assertIn("not an additive decomposition", lowered)

    def test_job_losers_only_does_not_create_primary_cause(self) -> None:
        report = attribution_channels(
            {"unemployed": 100, "job_losers": 50},
            {"unemployed": 0, "job_losers": 0},
        )
        self.assertNotIn("primary_cause", report)
        self.assertEqual(report["diagnostic_channels"]["job_loss"], 50)


if __name__ == "__main__":
    unittest.main()
