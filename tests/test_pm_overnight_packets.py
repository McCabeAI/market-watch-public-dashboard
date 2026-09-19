from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.overnight.scheduled_output import apply_output
from scripts.pm.books import apply_decision, empty_books
from scripts.pm.cli import init_layer, refresh_packets
from scripts.pm.constants import PM_IDS
from scripts.pm.review_packets import (
    SOURCE_OVERNIGHT,
    SOURCE_TRADER_ROOM_FALLBACK,
    build_all_packets,
    select_daily_pm_source,
    select_newest_successful_overnight_review,
)
from scripts.pm.store import PMStore
from tests.test_overnight_scheduled_output import ScheduledOutputTests


REPO = Path(__file__).resolve().parents[1]
MARKET = {
    "generated_at": "2026-09-19T12:00:00Z",
    "fx": {"pairs": {"USDCAD": {"spot": 1.36, "as_of": "2026-09-19"}}},
}


class OvernightPMPacketTests(unittest.TestCase):
    def setUp(self) -> None:
        self._fixture = ScheduledOutputTests()
        self._fixture.setUp()
        self.store = self._fixture.store
        self.state_root = self._fixture.state_root
        self.run_id = self._fixture.run_id
        self.payload = self._fixture.payload

    def tearDown(self) -> None:
        self._fixture.tearDown()
    def test_daily_packets_advance_to_newer_overnight_without_trader_room_run(self) -> None:
        review = apply_output(self.store, self.payload)
        self.assertEqual(review["status"], "succeeded")
        self.assertIn("pm_packets", review)
        self.assertEqual(review["pm_packets"]["source"], SOURCE_OVERNIGHT)
        self.assertEqual(review["pm_packets"]["overnight_run_id"], self.run_id)

        selected = select_newest_successful_overnight_review(self.state_root)
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.name, self.run_id)

        pm_store = PMStore(root=REPO, state_root=self.state_root)
        packets = {
            pm_id: pm_store.read_json(pm_store.packet_path(pm_id))
            for pm_id in PM_IDS
        }
        cutoffs = {packets[pm_id]["evidence_cutoff"] for pm_id in PM_IDS}
        hashes = {packets[pm_id]["evidence_packet_sha256"] for pm_id in PM_IDS}
        overnight_ids = {packets[pm_id]["overnight_run_id"] for pm_id in PM_IDS}
        sources = {packets[pm_id]["source"] for pm_id in PM_IDS}
        self.assertEqual(cutoffs, {self.payload["agent_packet"]["evidence_cutoff"]})
        self.assertEqual(hashes, {self.payload["agent_packet"]["packet_sha256"]})
        self.assertEqual(overnight_ids, {self.run_id})
        self.assertEqual(sources, {SOURCE_OVERNIGHT})
        for pm_id, packet in packets.items():
            self.assertEqual(packet["pm_id"], pm_id)
            self.assertTrue(packet["independence"]["sees_own_prior_book_only"])
            self.assertFalse(packet["independence"]["sees_other_current_pm_decisions"])
            self.assertEqual(packet["prior_book"]["pm_id"], pm_id)
            self.assertIsNotNone(packet["overnight_review"])
            self.assertEqual(packet["overnight_review"]["seat_count"], 14)
            self.assertEqual(
                {row["seat"] for row in packet["overnight_review"]["decisions"]},
                {row["seat"] for row in packets["chatgpt"]["overnight_review"]["decisions"]},
            )
            self.assertIsNone(packet["trader_room"])
            self.assertNotEqual(packet["review_packet_id"], f"prp-{pm_id}-tr-20260919T123430Z-ondemand")
            self.assertTrue(packet["review_packet_id"].startswith(f"prp-{pm_id}-{self.run_id}"))

    def test_newer_incomplete_overnight_is_ignored(self) -> None:
        apply_output(self.store, self.payload)
        newer = self.state_root / "data" / "overnight" / "runs" / "overnight-20260919"
        newer.mkdir(parents=True)
        (newer / "trader_review.json").write_text(
            json.dumps({"status": "failed", "overnight_run_id": "overnight-20260919", "reviews": {}}),
            encoding="utf-8",
        )
        selected = select_newest_successful_overnight_review(self.state_root)
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.name, self.run_id)
        source = select_daily_pm_source(REPO, self.state_root, allow_trader_room_fallback=False)
        self.assertEqual(source.kind, SOURCE_OVERNIGHT)
        self.assertEqual(source.overnight_run_id, self.run_id)

    def test_each_pm_sees_same_overnight_evidence_but_only_own_book(self) -> None:
        apply_output(self.store, self.payload)
        pm_store = PMStore(root=REPO, state_root=self.state_root)
        books = pm_store.read_books()
        books = apply_decision(
            books,
            {"pm_id": "swinger", "actions": [{"action": "OPEN", "instrument": "USDCAD", "side": "long", "notional_usd": 25_000_000, "asset_class": "spot_fx"}]},
            pm_id="swinger",
            market_state=MARKET,
            run_id=self.run_id,
            evidence_cutoff=self.payload["agent_packet"]["evidence_cutoff"],
            review_packet_id="seed-swinger",
            review_packet_sha256="seed",
        )
        pm_store.write_books(books)
        summary = refresh_packets(pm_store, allow_trader_room_fallback=False, overnight_run_id=self.run_id)
        self.assertEqual(summary["source"], SOURCE_OVERNIGHT)
        packets = {pm_id: pm_store.read_json(pm_store.packet_path(pm_id)) for pm_id in PM_IDS}
        evidence_hashes = {packets[pm_id]["evidence_packet_sha256"] for pm_id in PM_IDS}
        seats = {
            pm_id: tuple((row["seat"], row["actions"][0]["action"]) for row in packets[pm_id]["overnight_review"]["decisions"])
            for pm_id in PM_IDS
        }
        self.assertEqual(len(evidence_hashes), 1)
        self.assertEqual(seats["chatgpt"], seats["swinger"])
        self.assertEqual(seats["chatgpt"], seats["pragmatist"])
        self.assertEqual(seats["chatgpt"], seats["grinder"])
        self.assertEqual(len(packets["swinger"]["prior_book"]["positions"]), 1)
        self.assertEqual(packets["swinger"]["prior_book"]["positions"][0]["instrument"], "USDCAD")
        for other in ("chatgpt", "pragmatist", "grinder"):
            self.assertEqual(packets[other]["prior_book"]["positions"], [])
            leaked = json.dumps(packets[other]["prior_book"])
            self.assertNotIn("USDCAD", leaked)

    def test_trader_room_fallback_is_explicit_and_never_beats_overnight(self) -> None:
        apply_output(self.store, self.payload)
        source = select_daily_pm_source(REPO, self.state_root, allow_trader_room_fallback=True)
        self.assertEqual(source.kind, SOURCE_OVERNIGHT)
        self.assertEqual(source.overnight_run_id, self.run_id)
        self.assertIsNone(source.trader_room_run_id)

        with tempfile.TemporaryDirectory() as empty_tmp:
            empty = Path(empty_tmp)
            fallback = select_daily_pm_source(REPO, empty, allow_trader_room_fallback=True)
            self.assertEqual(fallback.kind, SOURCE_TRADER_ROOM_FALLBACK)
            self.assertEqual(fallback.trader_room_run_id, "tr-20260919T123430Z-ondemand")
            self.assertIsNone(fallback.overnight_run_id)
            packets = build_all_packets(
                root=REPO,
                state_root=empty,
                books=empty_books(),
                registry={"requests": []},
                source=fallback,
            )
            self.assertIn("on-demand Trader Room fallback", " ".join(packets["chatgpt"]["stale_or_missing_warnings"]))
            self.assertEqual(packets["chatgpt"]["source"], SOURCE_TRADER_ROOM_FALLBACK)
            self.assertIsNone(packets["chatgpt"]["overnight_run_id"])


class RepoInitFallbackTests(unittest.TestCase):
    def test_init_without_overnight_uses_explicit_trader_room_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PMStore(root=REPO, state_root=Path(tmp))
            summary = init_layer(store)
            self.assertTrue(summary["fallback"])
            self.assertEqual(summary["source"], SOURCE_TRADER_ROOM_FALLBACK)
            packet = store.read_json(store.packet_path("chatgpt"))
            self.assertEqual(packet["source"], SOURCE_TRADER_ROOM_FALLBACK)
            self.assertEqual(packet["trader_room_run_id"], "tr-20260919T123430Z-ondemand")
            self.assertIsNone(packet["overnight_run_id"])


if __name__ == "__main__":
    unittest.main()
