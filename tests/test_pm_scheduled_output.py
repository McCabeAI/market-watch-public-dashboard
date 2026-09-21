from __future__ import annotations

import unittest
from copy import deepcopy
from unittest import mock

from scripts.overnight.scheduled_output import apply_output, validate_output
from scripts.pm.automated import apply_automated_pm_decisions, validate_pm_decisions
from scripts.pm.errors import SchemaError
from scripts.pm.grinder import validate_grinder_hurdle
from scripts.pm.portfolio import synthetic_portfolio_construction
from tests.test_overnight_scheduled_output import ScheduledOutputTests, _pm_block


class OptionalAutomatedPMDecisionTests(ScheduledOutputTests):
    def test_missing_pm_decisions_is_invalid(self) -> None:
        del self.payload["pm_decisions"]
        with self.assertRaises(Exception):
            validate_output(self.store, self.payload)

    def test_complete_three_pm_block_is_accepted(self) -> None:
        validate_output(self.store, self.payload)
        review = self._simulate()
        self.assertIn("pm_books", review)
        self.assertEqual(review["pm_books"]["pms"]["swinger"]["decision_status"], "hold")
        self.assertEqual(review["pm_books"]["pms"]["chatgpt"]["decision_status"], "awaiting_chatgpt_decision")
        self.assertNotEqual(
            review["pm_books"]["pms"]["swinger"]["decision_status"],
            "awaiting_automated_pm_review",
        )
        self.assertNotEqual(
            review["pm_books"]["pms"]["pragmatist"]["decision_status"],
            "awaiting_automated_pm_review",
        )
        self.assertNotEqual(
            review["pm_books"]["pms"]["grinder"]["decision_status"],
            "awaiting_automated_pm_review",
        )

    def test_chatgpt_key_in_pm_decisions_rejected(self) -> None:
        packet = self.payload["agent_packet"]
        block = _pm_block(self.run_id, packet["packet_sha256"], packet["evidence_cutoff"])
        block["chatgpt"] = block.pop("grinder")
        with self.assertRaises(Exception):
            validate_pm_decisions(
                block,
                overnight_run_id=self.run_id,
                packet_sha256=packet["packet_sha256"],
                evidence_cutoff=packet["evidence_cutoff"],
                required=True,
            )

    def test_wrong_principal_model_rejected_for_overnight_pm(self) -> None:
        packet = self.payload["agent_packet"]
        block = _pm_block(self.run_id, packet["packet_sha256"], packet["evidence_cutoff"])
        block["swinger"]["principal_model"] = "composer-2.5"
        with self.assertRaises(SchemaError):
            validate_pm_decisions(
                block,
                overnight_run_id=self.run_id,
                packet_sha256=packet["packet_sha256"],
                evidence_cutoff=packet["evidence_cutoff"],
                required=True,
            )

    def test_expanding_pm_open_requires_frozen_pm_memory_hash(self) -> None:
        hashes = (self.base.get("pm_memory") or {}).get("hashes") or {}
        if not hashes.get("swinger"):
            self.skipTest("freeze snapshot has no pm_memory hashes in this fixture")
        packet = self.payload["agent_packet"]
        block = _pm_block(self.run_id, packet["packet_sha256"], packet["evidence_cutoff"])
        block["swinger"]["actions"] = [
            {
                "action": "OPEN",
                "instrument": "USDCAD",
                "side": "long",
                "notional_usd": 5_000_000,
                "asset_class": "spot_fx",
            }
        ]
        self.payload["pm_decisions"] = block
        with self.assertRaises(Exception):
            validate_output(self.store, self.payload)
        block["swinger"]["memory_context_sha256"] = "not-the-freeze-hash"
        with self.assertRaises(Exception):
            validate_output(self.store, self.payload)
        block["swinger"]["memory_context_sha256"] = hashes["swinger"]
        validate_output(self.store, self.payload)

    def test_apply_automated_pm_decisions_preserves_independence(self) -> None:
        from scripts.pm.books import empty_books

        books = empty_books(overnight_run_id=self.run_id)
        packet = self.payload["agent_packet"]
        block = _pm_block(self.run_id, packet["packet_sha256"], packet["evidence_cutoff"])
        block["swinger"]["actions"] = [
            {
                "action": "OPEN",
                "instrument": "USDCAD",
                "side": "long",
                "notional_usd": 5_000_000,
                "asset_class": "spot_fx",
            }
        ]
        prior_calls: list[dict] = []

        def _capture_prior(books_arg, *args, **kwargs):
            prior_calls.append(deepcopy(books_arg))
            return books_arg

        with mock.patch("scripts.pm.automated.apply_pm_decision_with_memory", side_effect=_capture_prior):
            apply_automated_pm_decisions(
                books,
                block,
                market_state=None,
                run_id=self.run_id,
                evidence_cutoff=packet["evidence_cutoff"],
            )
        self.assertGreaterEqual(len(prior_calls), 2)
        pragmatist_prior = prior_calls[1]
        swinger_positions = pragmatist_prior["pms"]["swinger"].get("positions") or []
        self.assertEqual(swinger_positions, [])

    def test_partial_or_wrong_roster_rejected(self) -> None:
        packet = self.payload["agent_packet"]
        block = _pm_block(self.run_id, packet["packet_sha256"], packet["evidence_cutoff"])
        del block["grinder"]
        with self.assertRaises(Exception):
            validate_pm_decisions(
                block,
                overnight_run_id=self.run_id,
                packet_sha256=packet["packet_sha256"],
                evidence_cutoff=packet["evidence_cutoff"],
                required=True,
            )
        block = _pm_block(self.run_id, packet["packet_sha256"], packet["evidence_cutoff"])
        block["chatgpt"] = block.pop("grinder")
        with self.assertRaises(Exception):
            validate_pm_decisions(
                block,
                overnight_run_id=self.run_id,
                packet_sha256=packet["packet_sha256"],
                evidence_cutoff=packet["evidence_cutoff"],
                required=True,
            )

    def test_pragmatist_requires_portfolio_construction(self) -> None:
        packet = self.payload["agent_packet"]
        block = _pm_block(self.run_id, packet["packet_sha256"], packet["evidence_cutoff"])
        del block["pragmatist"]["portfolio_construction"]
        with self.assertRaises(SchemaError):
            validate_pm_decisions(
                block,
                overnight_run_id=self.run_id,
                packet_sha256=packet["packet_sha256"],
                evidence_cutoff=packet["evidence_cutoff"],
                required=True,
            )
        swinger_only = _pm_block(self.run_id, packet["packet_sha256"], packet["evidence_cutoff"])
        self.assertNotIn("portfolio_construction", swinger_only["swinger"])
        self.assertNotIn("portfolio_construction", swinger_only["grinder"])
        validate_pm_decisions(
            swinger_only,
            overnight_run_id=self.run_id,
            packet_sha256=packet["packet_sha256"],
            evidence_cutoff=packet["evidence_cutoff"],
            required=True,
        )
        incomplete = _pm_block(self.run_id, packet["packet_sha256"], packet["evidence_cutoff"])
        incomplete["pragmatist"]["portfolio_construction"]["adverse_scenario"] = " "
        with self.assertRaises(SchemaError):
            validate_pm_decisions(
                incomplete,
                overnight_run_id=self.run_id,
                packet_sha256=packet["packet_sha256"],
                evidence_cutoff=packet["evidence_cutoff"],
                required=True,
            )

    def test_pragmatist_empty_opportunity_list_rejected_when_handoff_is_markable(self) -> None:
        hashes = self.base["seat_memory"]["hashes"]
        usd_memo = {
            "rates_candidate": None,
            "spot_candidate": {"instrument": "USDCAD", "asset_class": "spot_fx", "rationale": "spot"},
            "options_candidate": None,
            "selected": "spot",
            "rationale": "Dedicated USD spot seat.",
        }
        aud_memo = {
            "rates_candidate": None,
            "spot_candidate": {"instrument": "AUDUSD", "asset_class": "spot_fx", "rationale": "spot"},
            "options_candidate": None,
            "selected": "spot",
            "rationale": "Dedicated non-USD spot seat.",
        }
        dollar = self.payload["decisions"]["dollar-king"]
        dollar["expression_memo"] = usd_memo
        dollar["memory_context_sha256"] = hashes["dollar-king"]
        dollar["actions"] = [{
            "action": "OPEN",
            "instrument": "USDCAD",
            "side": "long",
            "notional_usd": 10_000_000,
            "asset_class": "spot_fx",
            "expression_memo": usd_memo,
        }]
        cross = self.payload["decisions"]["cross-merchant"]
        cross["expression_memo"] = aud_memo
        cross["memory_context_sha256"] = hashes["cross-merchant"]
        cross["actions"] = [{
            "action": "OPEN",
            "instrument": "AUDUSD",
            "side": "long",
            "notional_usd": 10_000_000,
            "asset_class": "spot_fx",
            "expression_memo": aud_memo,
        }]
        packet = self.payload["agent_packet"]
        block = _pm_block(self.run_id, packet["packet_sha256"], packet["evidence_cutoff"])
        self.payload["pm_decisions"] = block
        with self.assertRaises(Exception):
            validate_output(self.store, self.payload)
        block["pragmatist"]["portfolio_construction"] = synthetic_portfolio_construction(
            opportunities=[
                {
                    "instrument": "USDCAD",
                    "rationale": "Independent markable USD-CAD handoff; does not improve the opportunistic book.",
                    "markable": True,
                },
                {
                    "instrument": "AUDUSD",
                    "rationale": "Independent markable AUD-USD handoff; rejected after the adverse-scenario check.",
                    "markable": True,
                },
            ],
            existing_book="Pragmatist book is flat in this scheduled-output fixture.",
            rationale="Both independent markable handoffs were evaluated; HOLD remains valid.",
        )
        validate_output(self.store, self.payload)

    def test_grinder_requires_deployment_hurdle(self) -> None:
        packet = self.payload["agent_packet"]
        block = _pm_block(self.run_id, packet["packet_sha256"], packet["evidence_cutoff"])
        del block["grinder"]["deployment_hurdle"]
        with self.assertRaises(SchemaError):
            validate_pm_decisions(
                block,
                overnight_run_id=self.run_id,
                packet_sha256=packet["packet_sha256"],
                evidence_cutoff=packet["evidence_cutoff"],
                required=True,
            )

    def test_grinder_not_evaluable_requires_trade_specific_missing_data(self) -> None:
        decision = {
            "actions": [{"action": "NO_TRADE"}],
            "deployment_hurdle": {
                "benchmark": "Official SOFR 3.85% ACT/360.",
                "candidate_assessments": [
                    {
                        "instrument": "CORRA_2027-03",
                        "markable": True,
                        "hurdle_result": "not_evaluable",
                        "rationale": "Cannot evaluate.",
                        "material_missing_data": [],
                        "ignored_unrelated_gaps": ["NZ_rates"],
                    }
                ],
                "chosen_action_rationale": "Stay flat.",
            }
        }
        with self.assertRaises(SchemaError):
            validate_grinder_hurdle(decision, pm_id="grinder", packet=None)

    def test_grinder_packet_coverage_ignores_unrelated_gaps(self) -> None:
        packet = {
            "market_state": {
                "fx": {
                    "pairs": {
                        "USDCAD": {"spot": 1.36, "as_of": "2026-09-18"},
                        "AUDUSD": {"spot": 0.71, "as_of": "2026-09-18"},
                    }
                }
            },
            "proposed_trades": [
                {"trade": {"instrument": "USDCAD", "asset_class": "spot_fx"}},
                {"trade": {"instrument": "AUDUSD", "asset_class": "spot_fx"}},
            ],
        }
        decision = {
            "deployment_hurdle": {
                "benchmark": "Official SOFR 3.85% ACT/360.",
                "candidate_assessments": [
                    {
                        "instrument": "USDCAD",
                        "markable": True,
                        "hurdle_result": "does_not_clear",
                        "rationale": "Expected edge does not clear the funding hurdle.",
                        "material_missing_data": [],
                        "ignored_unrelated_gaps": ["NZ_rates", "options_iv"],
                    },
                    {
                        "instrument": "AUDUSD",
                        "markable": True,
                        "hurdle_result": "does_not_clear",
                        "rationale": "Expected edge does not clear the funding hurdle.",
                        "material_missing_data": [],
                        "ignored_unrelated_gaps": ["CA_official_curve"],
                    },
                ],
                "chosen_action_rationale": "Both markable candidates fail on economics, not packet completeness.",
            }
        }
        validate_grinder_hurdle(decision, pm_id="grinder", packet=packet)

    def test_more_than_three_subagents_or_unsupported_model_rejected(self) -> None:
        packet = self.payload["agent_packet"]
        block = _pm_block(self.run_id, packet["packet_sha256"], packet["evidence_cutoff"])
        block["swinger"]["subagent_count"] = 4
        block["swinger"]["subagent_models"] = ["grok-4.6"] * 4
        with self.assertRaises(SchemaError):
            validate_pm_decisions(
                block,
                overnight_run_id=self.run_id,
                packet_sha256=packet["packet_sha256"],
                evidence_cutoff=packet["evidence_cutoff"],
                required=True,
            )
        block = _pm_block(self.run_id, packet["packet_sha256"], packet["evidence_cutoff"])
        block["pragmatist"]["subagent_count"] = 1
        block["pragmatist"]["subagent_models"] = ["claude-sonnet-5"]
        with self.assertRaises(SchemaError):
            validate_pm_decisions(
                block,
                overnight_run_id=self.run_id,
                packet_sha256=packet["packet_sha256"],
                evidence_cutoff=packet["evidence_cutoff"],
                required=True,
            )

    def _simulate(self):
        from scripts.overnight.scheduled_output import simulate_output

        return simulate_output(self.store, self.payload)


if __name__ == "__main__":
    unittest.main()
