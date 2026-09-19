from __future__ import annotations

import unittest

from scripts.overnight.scheduled_output import validate_output
from scripts.pm.automated import validate_pm_decisions
from scripts.pm.errors import SchemaError
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
    return out


class OptionalAutomatedPMDecisionTests(ScheduledOutputTests):
    def test_legacy_fourteen_seat_output_without_pm_decisions_remains_valid(self) -> None:
        self.assertNotIn("pm_decisions", self.payload)
        validate_output(self.store, self.payload)
        review = self._simulate()
        self.assertEqual(review["status"], "succeeded")
        self.assertNotIn("pm_books", review)

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
