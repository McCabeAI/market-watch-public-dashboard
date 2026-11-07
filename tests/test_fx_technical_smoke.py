"""Chart Guy operational smoke gate. The blind exam is not the activation gate."""

from __future__ import annotations

import unittest

from scripts.fx_technical.smoke import run_smoke_gate


class ChartGuySmokeTests(unittest.TestCase):
    def test_operational_smoke_passes_without_treating_the_exam_as_a_pass(self) -> None:
        result = run_smoke_gate()
        self.assertEqual(result["failures"], [], result["failures"])
        self.assertEqual(result["gate"], "pass")
        self.assertFalse(result["historical_blind_exam_is_activation_gate"])
        replay = result["checks"]["historical_replay"]
        self.assertEqual(replay["snapshot_traders"], 14)
        self.assertEqual(replay["historical_exam_gate"], "fail")
        self.assertFalse(replay["historical_exam_is_activation_gate"])
        budgets = result["checks"]["budgets"]
        self.assertEqual(budgets["daily_14"], (20, 18, 2))
        self.assertEqual(budgets["daily_15"], (21, 19, 2))
        self.assertEqual(budgets["ondemand_15"], (61, 31, 30))
        paper = result["checks"]["paper_trade"]
        self.assertEqual(paper["unrealized_pnl_usd"], paper["realized_pnl_usd"])
        self.assertGreater(paper["unrealized_pnl_usd"], 0)
        self.assertEqual(paper["invalidation_class"], "weak_signal")
        self.assertEqual(paper["nav_usd"], 100_000_000)
        self.assertEqual(result["checks"]["no_trade"]["outcome"], "no_trade")
        self.assertEqual(result["checks"]["routing"]["model"], "grok-4.7[]")


if __name__ == "__main__":
    unittest.main()
