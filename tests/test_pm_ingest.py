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
            "prior_book",
            "allowable_actions",
            "unresolved_future_data_requests",
            "source",
        ):
            self.assertIn(required, self.packet)
        self.assertEqual(self.packet["pm_id"], "chatgpt")
        self.assertEqual(self.packet["prior_book"]["pm_id"], "chatgpt")
        self.assertFalse(self.packet["independence"]["sees_other_current_pm_decisions"])
        self.assertIn(self.packet["source"], {"overnight_scheduled_review", "on_demand_trader_room_fallback"})
        if self.packet["source"] == "on_demand_trader_room_fallback":
            self.assertIn("trader_room", self.packet)
        else:
            self.assertIn("overnight_review", self.packet)

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

    def test_stale_apply_does_not_mutate_state(self) -> None:
        books_before = json.dumps(self.store.read_books(), sort_keys=True)
        requests_before = json.dumps(self.store.read_requests(), sort_keys=True)
        public_before = json.dumps(self.store.read_json(self.store.public_path()), sort_keys=True)
        with self.assertRaises(FreshnessError):
            apply_chatgpt_decision(
                self.store,
                _decision(self.packet, review_packet_sha256="deadbeef"),
                write=True,
            )
        self.assertEqual(json.dumps(self.store.read_books(), sort_keys=True), books_before)
        self.assertEqual(json.dumps(self.store.read_requests(), sort_keys=True), requests_before)
        self.assertEqual(json.dumps(self.store.read_json(self.store.public_path()), sort_keys=True), public_before)
        if self.store.decisions_dir().is_dir():
            self.assertEqual(list(self.store.decisions_dir().glob("*.json")), [])

    def test_valid_decision_applies_exactly_once_and_replay_is_idempotent(self) -> None:
        first = apply_chatgpt_decision(
            self.store,
            _decision(
                self.packet,
                actions=[{"action": "OPEN", "instrument": "USDCAD", "side": "long", "notional_usd": 10_000_000, "asset_class": "spot_fx"}],
            ),
            write=True,
        )
        self.assertFalse(first["already_applied"])
        book = first["books"]["pms"]["chatgpt"]
        self.assertEqual(len(book["positions"]), 1)
        self.assertEqual(book["positions"][0]["instrument"], "USDCAD")
        self.assertEqual(book["positions"][0]["entry_price"], book["positions"][0]["mark_price"])
        self.assertNotEqual(book["positions"][0]["entry_price"], 9.99)
        opens = [row for row in book["history"] if row.get("action") == "OPEN"]
        self.assertEqual(len(opens), 1)
        self.assertEqual(len(first["registry"]["requests"]), 1)
        self.assertEqual(first["registry"]["requests"][0]["repeat_count"], 1)
        public = self.store.read_json(self.store.public_path())
        self.assertEqual(public["pms"][0]["decision_status"], book["decision_status"])

        replay = apply_chatgpt_decision(
            self.store,
            _decision(
                self.packet,
                actions=[{"action": "OPEN", "instrument": "USDCAD", "side": "long", "notional_usd": 10_000_000, "asset_class": "spot_fx"}],
            ),
            write=True,
        )
        self.assertTrue(replay["already_applied"])
        replayed = replay["books"]["pms"]["chatgpt"]
        self.assertEqual(len(replayed["positions"]), 1)
        self.assertEqual(len([row for row in replayed["history"] if row.get("action") == "OPEN"]), 1)
        self.assertEqual(len(replay["registry"]["requests"]), 1)
        self.assertEqual(replay["registry"]["requests"][0]["repeat_count"], 1)

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


    def test_chatgpt_workflow_is_trusted_apply_not_validate_only(self) -> None:
        workflow = (REPO / ".github" / "workflows" / "pm-chatgpt-decision.yml").read_text(encoding="utf-8")
        self.assertIn("pull_request_target", workflow)
        self.assertIn("chatgpt_ingest.py apply", workflow)
        self.assertIn("chatgpt_ingest.py validate", workflow)
        self.assertIn("github.event.pull_request.base.sha", workflow)
        self.assertIn("data/pm/inbox/chatgpt_decision.json", workflow)
        self.assertIn("chore: apply trusted ChatGPT PM decision", workflow)
        self.assertNotIn("CURSOR_API_KEY", workflow)
        self.assertNotIn("agent -p", workflow)


if __name__ == "__main__":
    unittest.main()
