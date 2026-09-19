from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.pm.chatgpt_ingest import apply_chatgpt_decision, validate_chatgpt_decision
from scripts.pm.cli import init_layer
from scripts.pm.constants import CHATGPT_PM_ID, SCHEMA_VERSION
from scripts.pm.errors import FreshnessError, SchemaError
from scripts.pm.store import PMStore


REPO = Path(__file__).resolve().parents[1]


def _decision(packet: dict, **overrides) -> dict:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "type": "PM_DECISION",
        "pm_id": CHATGPT_PM_ID,
        "review_packet_id": packet["review_packet_id"],
        "review_packet_sha256": packet["review_packet_sha256"],
        "evidence_cutoff": packet["evidence_cutoff"],
        "actions": [{"action": "NO_TRADE"}],
        "thesis": "No incremental edge after the freeze.",
        "invalidation": "A clean policy-path surprise.",
        "conviction": 40,
        "rationale": "Fourteen seats disagree; wait.",
        "synthesis": "Hold dry powder.",
        "alerts": [],
        "future_data_requests": [
            {
                "request": "Tradable SOFR/CORRA/AONIA strip in the frozen packet",
                "reason": "Cannot mark curve expressions from this vintage",
                "decision_impact": "Would unlock futures-curve OPEN for the next cycle",
                "priority": "high",
                "suggested_source": "CME/MX/ASX official settlements",
            }
        ],
    }
    payload.update(overrides)
    return payload


class ChatGPTIngestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.store = PMStore(root=REPO, state_root=self.state)
        init_layer(self.store)
        self.packet = self.store.read_json(self.store.packet_path("chatgpt"))
        for required in (
            "review_packet_id",
            "review_packet_sha256",
            "evidence_cutoff",
            "market_state",
            "trader_room",
            "prior_book",
            "allowable_actions",
            "unresolved_future_data_requests",
        ):
            self.assertIn(required, self.packet)
        self.assertEqual(self.packet["pm_id"], "chatgpt")
        self.assertEqual(self.packet["prior_book"]["pm_id"], "chatgpt")
        self.assertFalse(self.packet["independence"]["sees_other_current_pm_decisions"])

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_valid_no_trade_ingest_persists_requests(self) -> None:
        result = apply_chatgpt_decision(self.store, _decision(self.packet), write=True)
        book = result["books"]["pms"]["chatgpt"]
        self.assertEqual(book["decision_status"], "no_trade")
        self.assertEqual(book["positions"], [])
        self.assertEqual(book["review_status"], "fresh")
        requests = result["registry"]["requests"]
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["status"], "requested")
        self.assertEqual(requests[0]["originating_pms"], ["chatgpt"])
        self.assertEqual(requests[0]["repeat_count"], 1)
        public = self.store.read_json(self.store.public_path())
        self.assertEqual(public["data_requests"]["request_count"], 1)

    def test_stale_and_wrong_hash_rejected(self) -> None:
        with self.assertRaises(FreshnessError):
            validate_chatgpt_decision(_decision(self.packet, review_packet_sha256="deadbeef"), packet=self.packet)
        with self.assertRaises(FreshnessError):
            validate_chatgpt_decision(_decision(self.packet, review_packet_id="prp-old"), packet=self.packet)

    def test_malformed_and_model_authored_state_rejected(self) -> None:
        with self.assertRaises(SchemaError):
            validate_chatgpt_decision({"pm_id": "chatgpt"}, packet=self.packet)
        with self.assertRaises(SchemaError):
            validate_chatgpt_decision(_decision(self.packet, books={"nav_usd": 1}), packet=self.packet)
        with self.assertRaises(SchemaError):
            validate_chatgpt_decision(
                _decision(self.packet, realized_pnl_usd=12),
                packet=self.packet,
            )

    def test_repeated_request_is_deduped_with_attribution(self) -> None:
        apply_chatgpt_decision(self.store, _decision(self.packet), write=True)
        refreshed = self.store.read_json(self.store.packet_path("chatgpt"))
        apply_chatgpt_decision(self.store, _decision(refreshed), write=True)
        registry = self.store.read_requests()
        self.assertEqual(len(registry["requests"]), 1)
        self.assertEqual(registry["requests"][0]["repeat_count"], 2)
        self.assertEqual(len(registry["requests"][0]["attributions"]), 2)


if __name__ == "__main__":
    unittest.main()
