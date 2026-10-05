from __future__ import annotations

import unittest

from scripts.market_watch_launch.quality_gate import _apply_policy_overlay
from scripts.run_state.policy import evaluate_policy


class PolicyOverlayLegacyBlockTests(unittest.TestCase):
    RUN_ID = "mwl-20261005T100821Z-3f9807cb"

    def test_uncovered_legacy_us_block_preserved_with_partial_states(self) -> None:
        legacy = {
            "outcome": "PASS",
            "eligible": True,
            "blocked_expressions": ["macro:US"],
            "countries": {
                "US": {"eligible": False, "scored_status": "blocked", "gaps": []},
                "CA": {"eligible": True, "scored_status": "ok", "gaps": []},
            },
        }
        states = [
            {
                "run_id": self.RUN_ID,
                "series_id": "CA.Labor.unemployment",
                "state_id": f"{self.RUN_ID}:CA.Labor.unemployment",
                "country": "CA",
                "trade_critical": True,
                "carry_forward_reason": "old_but_current",
            }
        ]
        policy = evaluate_policy(states)
        out = _apply_policy_overlay(legacy, policy, states)
        self.assertIn("macro:US", out["blocked_expressions"])
        self.assertFalse(out["countries"]["US"]["eligible"])
        self.assertTrue(out["countries"]["CA"]["eligible"])
        self.assertEqual(out["outcome"], "PASS")


if __name__ == "__main__":
    unittest.main()
