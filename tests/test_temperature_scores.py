from __future__ import annotations

import copy
import unittest

from scripts.apply_temperature_scores import _patch_top_board, all_scores, load_state, temperature_class


class TemperatureScoresTest(unittest.TestCase):
    def test_bootstrap_scores_from_50(self) -> None:
        scores = all_scores(load_state())
        expected = {
            "US": {"Inflation": 52.0, "Labor": 50.2, "Activity": 49.92, "Consumer": 48.5},
            "CA": {"Inflation": 50.0, "Labor": 48.8, "Activity": 53.2, "Consumer": 52.5},
            "AU": {"Inflation": 49.2, "Labor": 47.8, "Activity": 49.2, "Consumer": 51.0},
            "NZ": {"Inflation": 51.6, "Labor": 47.0, "Activity": 52.0, "Consumer": 48.5},
        }
        for country, dimensions in expected.items():
            for dimension, value in dimensions.items():
                self.assertAlmostEqual(scores[country][dimension], value, places=6)

    def test_us_mapped_bridge_can_use_documented_dynamic_weight(self) -> None:
        state = load_state()
        bridged = copy.deepcopy(state)
        bridged["countries"]["US"]["Inflation"]["events"].append(
            {
                "id": "test-bridge",
                "as_of": "2026-09",
                "component": "mapped_bridge",
                "weight": 0.07,
                "impulse": 4,
                "basis": "test",
                "source": "test",
            }
        )
        scores = all_scores(bridged)
        self.assertAlmostEqual(scores["US"]["Inflation"], 52.28, places=6)


    def test_top_board_is_ledger_driven(self) -> None:
        state = load_state()
        scores = all_scores(state)
        html = '<div class="stitle">Temperature Board</div><div>legacy cards</div>'
        out = _patch_top_board(html, scores, state)
        self.assertIn('data-score-overview="live"', out)
        self.assertIn('Live 1–100 Score Board', out)
        self.assertIn('Macro Snapshot', out)
        self.assertIn('AU</b><div style="margin-top:4px;font-size:12px;">Inf 49.2 · Lab 47.8 · Act 49.2 · Con 51', out)
        self.assertIn('NZ</b><div style="margin-top:4px;font-size:12px;">Inf 51.6 · Lab 47 · Act 52 · Con 48.5', out)
        self.assertNotIn('Temperature Board', out)

    def test_temperature_bands(self) -> None:
        self.assertEqual(temperature_class(20), "cold")
        self.assertEqual(temperature_class(40), "cool")
        self.assertEqual(temperature_class(50), "neutral")
        self.assertEqual(temperature_class(80), "warm")
        self.assertEqual(temperature_class(81), "hot")


if __name__ == "__main__":
    unittest.main()
