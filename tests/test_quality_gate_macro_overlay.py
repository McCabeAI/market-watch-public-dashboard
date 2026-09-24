from __future__ import annotations

import unittest

from scripts.market_watch_launch.quality_gate import apply_macro_overlay


class QualityGateMacroOverlayTests(unittest.TestCase):
    def test_partial_country_failures_do_not_make_macro_global_stale(self) -> None:
        rows = [
            {
                "series_id": "US.Inflation.core_pce",
                "country": "US",
                "role": "scored",
                "weight": 1.0,
                "status": "source_failed",
                "release_due": False,
            },
            {
                "series_id": "CA.Inflation.underlying",
                "country": "CA",
                "role": "scored",
                "weight": 1.0,
                "status": "checked_unchanged",
                "release_due": False,
                "observation_period": "2026-08",
                "due_period": None,
            },
        ]
        families = {"macro_hard": {"status": "stale", "notes": []}}
        macro = apply_macro_overlay(families, rows)["macro_hard"]
        self.assertEqual(macro["status"], "fresh")
        self.assertIn("CA", macro["fresh_countries"])
        self.assertIn("US", macro["stale_countries"])

    def test_due_missing_country_stays_restricted(self) -> None:
        rows = [
            {
                "series_id": "AU.Labor.unemployment",
                "country": "AU",
                "role": "scored",
                "weight": 0.7,
                "status": "checked_unchanged",
                "release_due": True,
                "observation_period": "2026-07",
                "due_period": "2026-08",
            },
            {
                "series_id": "CA.Inflation.underlying",
                "country": "CA",
                "role": "scored",
                "weight": 1.0,
                "status": "checked_unchanged",
                "release_due": False,
                "observation_period": "2026-08",
                "due_period": None,
            },
        ]
        macro = apply_macro_overlay({"macro_hard": {"notes": []}}, rows)["macro_hard"]
        self.assertIn("AU", macro["stale_countries"])
        self.assertIn("CA", macro["fresh_countries"])
        self.assertEqual(macro["status"], "fresh")


if __name__ == "__main__":
    unittest.main()
