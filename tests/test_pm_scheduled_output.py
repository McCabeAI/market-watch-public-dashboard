from __future__ import annotations

import unittest

from scripts.overnight.scheduled_output import apply_output, validate_output
from scripts.pm.automated import validate_pm_decisions
from scripts.pm.errors import SchemaError
from scripts.pm.portfolio import synthetic_portfolio_construction
from tests.test_overnight_scheduled_output import ScheduledOutputTests


def _pm_block(run_id: str, packet_hash: str, cutoff: str) -> dict:
    out = {}
    for pm_id in ("swinger", "pragmatist", "grinder"):
        out[pm_id] = {
            "pm_id": pm_id,
            "overnight_run_id": run_id,
            "packet_sha256": packet_hash,
            "evidence_cutoff": cutoff,
            "principal_model": "grok-4.6",
            "subagent_count": 0,
            "subagent_models": [],
            "actions": [{"action": "HOLD"}],
            "thesis": "Await cleaner setup.",
            "invalidation": None,
            "conviction": 20,
        }
        if pm_id == "pragmatist":
            out[pm_id]["portfolio_construction"] = synthetic_portfolio_construction(
                existing_book="Pragmatist book is flat in this scheduled-output fixture.",
                rationale="No independent markable complementary trade improves the opportunistic book; HOLD is explicit.",
            )
    return out


class OptionalAutomatedPMDecisionTests(ScheduledOutputTests):
    def test_legacy_fourteen_seat_output_without_pm_decisions_remains_valid(self) -> None:
        self.assertNotIn("pm_decisions", self.payload)
        validate_output(self.store, self.payload)
        review = apply_output(self.store, self.payload)
        self.assertEqual(review["status"], "succeeded")
        self.assertNotIn("pm_books", review)
        self.assertEqual(review["pm_packets"]["source"], "overnight_scheduled_review")
        self.assertEqual(review["pm_packets"]["overnight_run_id"], self.run_id)
        from scripts.pm.store import PMStore

        pm_store = PMStore(root=self.store.root, state_root=self.state_root)
        chatgpt = pm_store.read_json(pm_store.packet_path("chatgpt"))
        self.assertEqual(chatgpt["overnight_run_id"], self.run_id)
        self.assertEqual(chatgpt["source"], "overnight_scheduled_review")
        self.assertEqual(pm_store.read_books()["pms"]["chatgpt"]["decision_status"], "awaiting_chatgpt_decision")

    def test_complete_three_pm_block_is_accepted(self) -> None:
        packet = self.payload["agent_packet"]
        self.payload["pm_decisions"] = _pm_block(
            self.run_id, packet["packet_sha256"], packet["evidence_cutoff"]
        )
        validate_output(self.store, self.payload)
        review = self._simulate()
        self.assertIn("pm_books", review)
        self.assertEqual(review["pm_books"]["pms"]["swinger"]["decision_status"], "hold")
        self.assertEqual(review["pm_books"]["pms"]["chatgpt"]["decision_status"], "awaiting_chatgpt_decision")

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
            )
        block = _pm_block(self.run_id, packet["packet_sha256"], packet["evidence_cutoff"])
        block["chatgpt"] = block.pop("grinder")
        with self.assertRaises(Exception):
            validate_pm_decisions(
                block,
                overnight_run_id=self.run_id,
                packet_sha256=packet["packet_sha256"],
                evidence_cutoff=packet["evidence_cutoff"],
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
            )
        swinger_only = _pm_block(self.run_id, packet["packet_sha256"], packet["evidence_cutoff"])
        self.assertNotIn("portfolio_construction", swinger_only["swinger"])
        self.assertNotIn("portfolio_construction", swinger_only["grinder"])
        validate_pm_decisions(
            swinger_only,
            overnight_run_id=self.run_id,
            packet_sha256=packet["packet_sha256"],
            evidence_cutoff=packet["evidence_cutoff"],
        )
        incomplete = _pm_block(self.run_id, packet["packet_sha256"], packet["evidence_cutoff"])
        incomplete["pragmatist"]["portfolio_construction"]["adverse_scenario"] = " "
        with self.assertRaises(SchemaError):
            validate_pm_decisions(
                incomplete,
                overnight_run_id=self.run_id,
                packet_sha256=packet["packet_sha256"],
                evidence_cutoff=packet["evidence_cutoff"],
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
            )

    def _simulate(self):
        from scripts.overnight.scheduled_output import simulate_output

        return simulate_output(self.store, self.payload)


if __name__ == "__main__":
    unittest.main()
