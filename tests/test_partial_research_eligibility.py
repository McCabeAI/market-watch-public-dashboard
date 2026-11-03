"""Research publication eligibility when trader marks are partial or blocked."""

from __future__ import annotations

import unittest

from scripts.market_watch_launch.quality_gate import evaluate_gate
from scripts.market_watch_launch.research_pages import ResearchRefusal, _verify_quality_gate


def _fresh_market_families(**rate_overrides: dict) -> dict:
    rates = {code: {"status": "ok"} for code in ("US", "CA", "AU", "NZ", "EA", "JP")}
    rates.update(rate_overrides)
    return {
        "macro_hard": {"status": "fresh", "notes": []},
        "market_state": {
            "status": "fresh",
            "data": {
                "generated_at": "2026-11-02T08:00:00-05:00",
                "rates": rates,
                "fx": {"status": "ok"},
            },
        },
    }


def _nov2_macro_rows() -> list[dict]:
    us_ok = {
        "series_id": "US.Labor.payrolls",
        "country": "US",
        "role": "scored",
        "weight": 1.0,
        "status": "checked_unchanged",
        "release_due": False,
        "observation_period": "2026-10",
        "due_period": "2026-10",
    }
    gap_specs = [
        ("CA", "CA.Inflation.cpi", "due_missing"),
        ("AU", "AU.Labor.unemployment", "source_failed"),
        ("NZ", "NZ.Inflation.cpi", "due_missing"),
        ("EA", "EA.Inflation.core", "source_failed"),
        ("JP", "JP.Labor.unemployment", "due_missing"),
    ]
    rows = [us_ok]
    for country, series_id, status in gap_specs:
        rows.append(
            {
                "series_id": series_id,
                "country": country,
                "role": "scored",
                "weight": 1.0,
                "status": status,
                "release_due": True,
                "observation_period": "2026-08",
                "due_period": "2026-09",
            }
        )
    return rows


class PartialResearchEligibilityTests(unittest.TestCase):
    def test_fx_partial_one_pair_unavailable_does_not_block_fx_family(self) -> None:
        families = _fresh_market_families()
        families["market_state"]["data"]["fx"] = {
            "status": "partial",
            "pairs": {
                "EURUSD": {"status": "ok", "spot": 1.08, "as_of": "2026-11-02"},
                "USDCAD": {"status": "unavailable", "spot": None},
            },
        }
        result = evaluate_gate(rows=_nov2_macro_rows(), families=families)
        self.assertEqual(result["outcome"], "PASS")
        self.assertNotIn("FX", result.get("blocked_legs") or [])
        self.assertIn("US", result["trade_eligible_countries"])
        self.assertTrue(result["research_eligible"])
        self.assertTrue(result["eligible"])
        self.assertEqual(result["trader_execution"], "allowed")

    def test_fully_unmarkable_universe_with_macro_rows_research_pass(self) -> None:
        dead = {code: {"status": "unavailable"} for code in ("US", "CA", "AU", "NZ", "EA", "JP")}
        families = _fresh_market_families(**dead)
        families["market_state"]["data"]["fx"] = {"status": "unavailable"}
        result = evaluate_gate(rows=_nov2_macro_rows(), families=families)
        self.assertEqual(result["outcome"], "PASS")
        self.assertFalse(result["eligible"])
        self.assertTrue(result["research_eligible"])
        self.assertEqual(result["reason"], "no_markable_universe")
        self.assertEqual(result["trader_execution"], "blocked")

    def test_fully_unmarkable_without_research_evidence_blocked(self) -> None:
        dead = {code: {"status": "unavailable"} for code in ("US", "CA", "AU", "NZ", "EA", "JP")}
        families = {
            "macro_hard": {"status": "fresh", "notes": []},
            "market_state": {
                "status": "fresh",
                "data": {
                    "generated_at": "2026-11-02T08:00:00-05:00",
                    "rates": dead,
                    "fx": {"status": "unavailable"},
                },
            },
        }
        result = evaluate_gate(rows=[], families=families)
        self.assertEqual(result["outcome"], "BLOCKED")
        self.assertEqual(result["coverage"], "NONE")
        self.assertEqual(result["reason"], "no_markable_universe")

    def test_verify_quality_gate_research_eligible_without_trader_eligible(self) -> None:
        launch = {
            "stages": {
                "03_quality_gate": {
                    "details": {
                        "outcome": "PASS",
                        "coverage": "PARTIAL",
                        "eligible": False,
                        "research_eligible": True,
                        "trader_execution": "blocked",
                    }
                }
            }
        }
        verified = _verify_quality_gate(launch)
        self.assertTrue(verified["research_eligible"])
        self.assertEqual(verified["trader_execution"], "blocked")

        launch_fail = {
            "stages": {
                "03_quality_gate": {
                    "details": {
                        "outcome": "PASS",
                        "coverage": "PARTIAL",
                        "eligible": False,
                    }
                }
            }
        }
        with self.assertRaises(ResearchRefusal):
            _verify_quality_gate(launch_fail)


if __name__ == "__main__":
    unittest.main()
