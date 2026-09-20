#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]

from scripts.overnight.books import apply_review as apply_trader_book_review, empty_books as empty_trader_books, validate_books as validate_trader_books
from scripts.overnight.constants import STANDING_SEATS
from scripts.overnight.pipeline import dry_run as overnight_dry_run, run_stage
from scripts.overnight.scheduled_output import AGENT_PACKET_TYPE, SCHEDULE_ID, apply_output, simulate_output
from scripts.overnight.store import OvernightStore, sha256_json
from scripts.pm.books import empty_books as empty_pm_books
from scripts.pm.constants import PM_IDS
from scripts.trading.apply import (
    apply_pm_decision_with_memory,
    apply_trader_review_with_memory,
    journal_trader_room_pitch,
    journal_trader_room_rebuttal,
)
from scripts.trading.constants import ALL_IDENTITIES, LESSON_CAP
from scripts.trading.errors import LearningGateError, OwnershipError, RationaleError
from scripts.trading.gate import action_rationale
from scripts.trading.ledger import find_trade_by_position
from scripts.trading.memory import accept_postmortem, apply_memory_update, build_memory_context
from scripts.trading.migrate import backfill_from_books
from scripts.trading.snapshot import snapshot_trader_room
from scripts.trading.store import TradingStore
from scripts.trader_room.constants import STANDING_ADVOCATES
from scripts.trader_room.orchestrator import go as trader_room_go

NY = ZoneInfo("America/New_York")
AS_OF = datetime(2026, 9, 19, 12, 0, tzinfo=NY)
MARKET = {
    "generated_at": "2026-09-19T12:00:00Z",
    "fx": {"pairs": {"USDCAD": {"spot": 1.36, "as_of": "2026-09-19"}, "AUDUSD": {"spot": 0.66}}},
}


def _fresh_families() -> dict:
    return {
        "macro_hard": {"status": "fresh", "as_of": "2026-09-19T00:07:00-04:00", "digest": "m"},
        "news": {"status": "fresh", "as_of": "2026-09-19T00:07:00-04:00", "digest": "n"},
        "central_bank_research": {"status": "fresh", "as_of": "2026-09-19T00:07:00-04:00", "digest": "c"},
        "market_state": {"status": "fresh", "as_of": "2026-09-19T00:07:00-04:00", "digest": "s", "data": MARKET},
    }


def _spot_memo() -> dict:
    return {
        "rates_candidate": None,
        "spot_candidate": {"instrument": "USDCAD", "asset_class": "spot_fx", "rationale": "spot"},
        "options_candidate": None,
        "selected": "spot",
        "rationale": "Dedicated USD spot seat.",
    }


def _hold_reviews(memory_hashes: dict[str, str], *, extra: dict[str, dict] | None = None) -> dict:
    reviews = {}
    for seat in STANDING_SEATS:
        reviews[seat] = {
            "seat": seat,
            "conviction": 30,
            "thesis": "No incremental edge.",
            "memory_context_sha256": memory_hashes.get(seat),
            "expression_memo": {
                "rates_candidate": None,
                "spot_candidate": None,
                "options_candidate": None,
                "selected": "none",
                "rationale": "Hold.",
            },
            "actions": [{"action": "HOLD"}],
        }
    if extra:
        reviews.update(extra)
    return reviews


class TradingMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = TradingStore(root=self.root, state_root=self.root)
        self.store.ensure_initialized()
        self.hashes = {
            owner_id: build_memory_context(self.store, owner_type, owner_id)["memory_context_sha256"]
            for owner_type, owner_id in ALL_IDENTITIES
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _trader_open(self, books, *, thesis="USD premium is still the cleanest expression.", **action_extra):
        action = {
            "action": "OPEN",
            "instrument": "USDCAD",
            "side": "long",
            "notional_usd": 10_000_000,
            "price": 1.36,
            "asset_class": "spot_fx",
            "expression_memo": _spot_memo(),
            "thesis": thesis,
        }
        action.update(action_extra)
        reviews = _hold_reviews(self.hashes)
        reviews["dollar-king"] = {
            "seat": "dollar-king",
            "conviction": 70,
            "thesis": thesis,
            "invalidation": "A clean US easing surprise.",
            "memory_context_sha256": self.hashes["dollar-king"],
            "expression_memo": _spot_memo(),
            "actions": [action],
        }
        return apply_trader_review_with_memory(
            books,
            reviews,
            families=_fresh_families(),
            run_id="overnight-20260919",
            evidence_cutoff="2026-09-19T12:00:00-04:00",
            store=self.store,
            memory_hashes=self.hashes,
            evidence_hash="pkt-hash",
            when=AS_OF,
            market_state=MARKET,
        )

    def test_empty_books_initialize_all_eighteen_identities(self) -> None:
        index = backfill_from_books(
            self.store,
            trader_books=empty_trader_books(overnight_run_id="overnight-20260919", when=AS_OF),
            pm_books=empty_pm_books(),
            when=AS_OF,
        )
        self.assertEqual(len(index["identities"]), 18)
        self.assertEqual(index["trade_ids"], [])
        for owner_type, owner_id in ALL_IDENTITIES:
            context = build_memory_context(self.store, owner_type, owner_id)
            self.assertEqual(context["calibration"]["closed_trade_count"], 0)
            self.assertEqual(context["active_lessons"], [])
            self.assertEqual(context["postmortems_due"], [])
            other = "perma-bear" if owner_id != "perma-bear" else "dollar-king"
            if owner_type == "trader":
                blob = json.dumps(context)
                self.assertNotIn(f"trd-trader-{other}-", blob)

    def test_trader_room_sidecar_backfills_current_canonical_positions(self) -> None:
        books = empty_trader_books(overnight_run_id="tr-prior", when=AS_OF)
        reviews = {
            seat: {
                "seat": seat,
                "actions": [{"action": "HOLD"}],
            }
            for seat in STANDING_SEATS
        }
        reviews["dollar-king"] = {
            "seat": "dollar-king",
            "thesis": "Canonical book position must reach the private sidecar.",
            "actions": [{
                "action": "OPEN",
                "instrument": "USDCAD",
                "side": "long",
                "notional_usd": 10_000_000,
                "asset_class": "spot_fx",
                "expression_memo": _spot_memo(),
                "thesis": "Canonical book position must reach the private sidecar.",
            }],
        }
        books = apply_trader_book_review(
            books,
            reviews,
            families=_fresh_families(),
            run_id="tr-prior",
            evidence_cutoff="2026-09-19T12:00:00-04:00",
            when=AS_OF,
            market_state=MARKET,
        )
        OvernightStore(root=self.root, state_root=self.root).write_books(books)

        run_dir = self.root / "trader-room" / "runs" / "tr-next"
        snapshot_trader_room(
            self.store,
            run_dir=run_dir,
            run_id="tr-next",
            common_evidence_sha256="common-hash",
            when=AS_OF,
        )
        context = json.loads((run_dir / "memory" / "dollar-king.json").read_text(encoding="utf-8"))
        self.assertEqual(len(context["open_positions"]), 1)
        self.assertEqual(context["open_positions"][0]["instrument"], "USDCAD")
        self.assertEqual(context["open_positions"][0]["current_notional_usd"], 10_000_000)

    def test_trader_open_creates_ledger_and_journal(self) -> None:
        books = empty_trader_books(overnight_run_id="overnight-20260919", when=AS_OF)
        updated = self._trader_open(books)
        pos = updated["seats"]["dollar-king"]["positions"][0]
        trade = find_trade_by_position(self.store, owner_type="trader", owner_id="dollar-king", position_id=pos["position_id"])
        self.assertIsNotNone(trade)
        assert trade is not None
        self.assertEqual(trade["status"], "open")
        self.assertEqual(trade["instrument"], "USDCAD")
        self.assertEqual(trade["entry_mark"], 1.36)
        self.assertEqual(trade["entry_rationale"], "USD premium is still the cleanest expression.")
        self.assertEqual(trade["opened_run_id"], "overnight-20260919")
        self.assertEqual(trade["provenance"]["evidence_hash"], "pkt-hash")
        journal = self.store.read_journal("trader", "dollar-king")
        self.assertEqual(journal["events"][0]["kind"], "OVERNIGHT_DECISION")
        self.assertEqual(journal["events"][0]["actions"][0]["action"], "OPEN")
        self.assertEqual(journal["events"][0]["memory_context_sha256"], self.hashes["dollar-king"])

    def test_trader_add_reduce_close_preserves_closed_ledger(self) -> None:
        books = self._trader_open(empty_trader_books(overnight_run_id="overnight-20260919", when=AS_OF))
        pos_id = books["seats"]["dollar-king"]["positions"][0]["position_id"]
        self.hashes["dollar-king"] = build_memory_context(self.store, "trader", "dollar-king")["memory_context_sha256"]
        add = _hold_reviews(self.hashes)
        add["dollar-king"] = {
            "seat": "dollar-king",
            "conviction": 72,
            "thesis": "Add while the USD premium holds.",
            "memory_context_sha256": self.hashes["dollar-king"],
            "actions": [{
                "action": "ADD",
                "position_id": pos_id,
                "notional_usd": 2_000_000,
                "price": 1.36,
                "rationale": "Increase risk after confirmation.",
                "expression_memo": _spot_memo(),
            }],
        }
        books = apply_trader_review_with_memory(
            books, add, families=_fresh_families(), run_id="overnight-20260920",
            evidence_cutoff="2026-09-20T12:00:00-04:00", store=self.store,
            memory_hashes=self.hashes, when=AS_OF, market_state=MARKET,
        )
        reduced_market = {"fx": {"pairs": {"USDCAD": {"spot": 1.40, "as_of": "2026-09-21"}}}}
        reduce = _hold_reviews(self.hashes)
        reduce["dollar-king"] = {
            "seat": "dollar-king",
            "conviction": 60,
            "thesis": "Trim.",
            "memory_context_sha256": self.hashes["dollar-king"],
            "actions": [{
                "action": "REDUCE",
                "position_id": pos_id,
                "notional_usd": 4_000_000,
                "price": 1.40,
                "rationale": "Take partial profits.",
                "expression_memo": _spot_memo(),
            }],
        }
        books = apply_trader_review_with_memory(
            books, reduce, families=_fresh_families(), run_id="overnight-20260921",
            evidence_cutoff="2026-09-21T12:00:00-04:00", store=self.store,
            memory_hashes=self.hashes, when=AS_OF, market_state=reduced_market,
        )
        trade = find_trade_by_position(self.store, owner_type="trader", owner_id="dollar-king", position_id=pos_id)
        assert trade is not None
        partial = float(trade["realized_pnl_usd"])
        self.assertGreater(partial, 0)
        close = _hold_reviews(self.hashes)
        close["dollar-king"] = {
            "seat": "dollar-king",
            "conviction": 40,
            "thesis": "Exit.",
            "memory_context_sha256": self.hashes["dollar-king"],
            "actions": [{
                "action": "CLOSE",
                "position_id": pos_id,
                "price": 1.40,
                "rationale": "Thesis complete.",
                "exit_reason_category": "target_reached",
                "expression_memo": _spot_memo(),
            }],
        }
        books = apply_trader_review_with_memory(
            books, close, families=_fresh_families(), run_id="overnight-20260922",
            evidence_cutoff="2026-09-22T12:00:00-04:00", store=self.store,
            memory_hashes=self.hashes, when=AS_OF, market_state=reduced_market,
        )
        self.assertFalse(any(p["position_id"] == pos_id for p in books["seats"]["dollar-king"]["positions"]))
        trade = self.store.read_trade(trade["trade_id"])
        self.assertEqual(trade["status"], "closed")
        self.assertEqual(trade["exit_mark"], 1.4)
        self.assertEqual(trade["exit_rationale"], "Thesis complete.")
        self.assertGreater(trade["realized_pnl_usd"], partial)
        self.assertIsNotNone(trade["holding_duration_seconds"])
        increments = [event["realized_pnl_increment_usd"] for event in trade["events"] if event["kind"] in {"REDUCE", "CLOSE"}]
        self.assertAlmostEqual(sum(increments), trade["realized_pnl_usd"], places=2)
        reloaded = TradingStore(root=self.root, state_root=self.root)
        self.assertTrue(reloaded.has_trade(trade["trade_id"]))
        self.assertEqual(reloaded.read_trade(trade["trade_id"])["status"], "closed")

    def test_pm_lifecycle_and_missing_exit_rationale(self) -> None:
        books = empty_pm_books()
        opened = apply_pm_decision_with_memory(
            books,
            {
                "pm_id": "chatgpt",
                "thesis": "CAD cheap vs the packet mid.",
                "rationale": "Open USDCAD from the frozen mid.",
                "memory_context_sha256": self.hashes["chatgpt"],
                "actions": [{"action": "OPEN", "instrument": "USDCAD", "side": "long", "notional_usd": 25_000_000, "asset_class": "spot_fx"}],
            },
            pm_id="chatgpt",
            store=self.store,
            market_state=MARKET,
            run_id="overnight-20260919",
            evidence_cutoff="2026-09-19T12:00:00-04:00",
            review_packet_id="prp-chatgpt-test",
            review_packet_sha256="hash",
            expected_memory_sha256=self.hashes["chatgpt"],
            when=AS_OF,
        )
        pos_id = opened["pms"]["chatgpt"]["positions"][0]["position_id"]
        closed = apply_pm_decision_with_memory(
            opened,
            {
                "pm_id": "chatgpt",
                "memory_context_sha256": self.hashes["chatgpt"],
                "actions": [{"action": "CLOSE", "position_id": pos_id, "price": 1.40}],
            },
            pm_id="chatgpt",
            store=self.store,
            market_state={**MARKET, "fx": {"pairs": {"USDCAD": {"spot": 1.40}}}},
            run_id="overnight-20260920",
            evidence_cutoff="c",
            review_packet_id="prp-chatgpt-test-2",
            review_packet_sha256="hash2",
            expected_memory_sha256=self.hashes["chatgpt"],
            when=AS_OF,
        )
        self.assertEqual(closed["pms"]["chatgpt"]["positions"], [])
        trade = find_trade_by_position(self.store, owner_type="pm", owner_id="chatgpt", position_id=pos_id)
        assert trade is not None
        self.assertEqual(trade["status"], "closed")
        self.assertEqual(trade["events"][-1]["rationale_status"], "missing_required")
        self.assertTrue(any("missing_required" in row for row in closed["pms"]["chatgpt"]["alerts"]))
        due = build_memory_context(self.store, "pm", "chatgpt")["postmortems_due"]
        self.assertEqual(due[0]["trade_id"], trade["trade_id"])

    def test_journal_hold_and_expansion_rationale_gate(self) -> None:
        books = empty_trader_books(overnight_run_id="overnight-20260919", when=AS_OF)
        held = apply_trader_review_with_memory(
            books,
            _hold_reviews(self.hashes),
            families=_fresh_families(),
            run_id="overnight-20260919",
            evidence_cutoff="2026-09-19T12:00:00-04:00",
            store=self.store,
            memory_hashes=self.hashes,
            when=AS_OF,
        )
        self.assertEqual(held["seats"]["dollar-king"]["last_action"], "HOLD")
        self.assertEqual(self.store.read_journal("trader", "dollar-king")["events"][0]["actions"][0]["action"], "HOLD")
        bad = _hold_reviews(self.hashes)
        bad["dollar-king"] = {
            "seat": "dollar-king",
            "memory_context_sha256": self.hashes["dollar-king"],
            "actions": [{"action": "OPEN", "instrument": "USDCAD", "side": "long", "notional_usd": 1_000_000, "asset_class": "spot_fx", "price": 1.36}],
        }
        with self.assertRaises(RationaleError):
            apply_trader_review_with_memory(
                held, bad, families=_fresh_families(), run_id="overnight-20260920",
                evidence_cutoff="c", store=self.store, memory_hashes=self.hashes, when=AS_OF, market_state=MARKET,
            )

    def test_learning_gate_and_postmortem_ownership(self) -> None:
        books = self._trader_open(empty_trader_books(overnight_run_id="overnight-20260919", when=AS_OF))
        pos_id = books["seats"]["dollar-king"]["positions"][0]["position_id"]
        close = _hold_reviews(self.hashes)
        close["dollar-king"] = {
            "seat": "dollar-king",
            "thesis": "Exit.",
            "memory_context_sha256": self.hashes["dollar-king"],
            "actions": [{"action": "CLOSE", "position_id": pos_id, "price": 1.36, "rationale": "Cut."}],
        }
        books = apply_trader_review_with_memory(
            books, close, families=_fresh_families(), run_id="overnight-20260919",
            evidence_cutoff="c", store=self.store, memory_hashes=self.hashes, when=AS_OF, market_state=MARKET,
        )
        trade = find_trade_by_position(self.store, owner_type="trader", owner_id="dollar-king", position_id=pos_id)
        assert trade is not None
        later_hash = build_memory_context(self.store, "trader", "dollar-king")["memory_context_sha256"]
        blocked = _hold_reviews({**self.hashes, "dollar-king": later_hash})
        blocked["dollar-king"] = {
            "seat": "dollar-king",
            "thesis": "Re-enter.",
            "memory_context_sha256": later_hash,
            "actions": [{
                "action": "OPEN", "instrument": "USDCAD", "side": "long", "notional_usd": 1_000_000,
                "price": 1.36, "asset_class": "spot_fx", "expression_memo": _spot_memo(), "rationale": "Again.",
            }],
        }
        with self.assertRaises(LearningGateError):
            apply_trader_review_with_memory(
                books, blocked, families=_fresh_families(), run_id="overnight-20260923",
                evidence_cutoff="c", store=self.store, memory_hashes={**self.hashes, "dollar-king": later_hash},
                when=AS_OF, market_state=MARKET,
            )
        hold = _hold_reviews({**self.hashes, "dollar-king": "stale"})
        hold["dollar-king"]["memory_context_sha256"] = "stale"
        apply_trader_review_with_memory(
            books, hold, families=_fresh_families(), run_id="overnight-20260923",
            evidence_cutoff="c", store=self.store, memory_hashes={**self.hashes, "dollar-king": later_hash},
            when=AS_OF, market_state=MARKET,
        )
        with self.assertRaises(OwnershipError):
            accept_postmortem(
                self.store,
                {"trade_id": trade["trade_id"], "lesson": "Do not steal this."},
                owner_type="trader",
                owner_id="perma-bull",
                run_id="overnight-20260923",
            )
        before_pnl = trade["realized_pnl_usd"]
        accept_postmortem(
            self.store,
            {
                "trade_id": trade["trade_id"],
                "what_worked": "Entry mark was honest.",
                "what_failed": "No follow-through.",
                "thesis_assessment": "Incomplete.",
                "lesson": "Wait for confirmation.",
                "future_rule": "Do not re-enter the same mid without a catalyst.",
            },
            owner_type="trader",
            owner_id="dollar-king",
            run_id="overnight-20260923",
        )
        self.assertEqual(self.store.read_trade(trade["trade_id"])["realized_pnl_usd"], before_pnl)
        context = build_memory_context(self.store, "trader", "dollar-king")
        self.assertEqual(context["calibration"]["closed_trade_count"], 1)
        self.assertLessEqual(len(context["active_lessons"]), LESSON_CAP)
        self.assertEqual(context["active_lessons"][0]["trade_ids"], [trade["trade_id"]])
        self.assertNotIn("trd-trader-perma-bull", json.dumps(context))
        with self.assertRaises(OwnershipError):
            apply_memory_update(
                self.store,
                {"op": "add", "text": "Vague lesson", "trade_ids": ["trd-trader-perma-bull-missing"]},
                owner_type="trader",
                owner_id="dollar-king",
                run_id="overnight-20260923",
            )

    def test_stale_hash_blocks_only_expansion(self) -> None:
        books = empty_trader_books(overnight_run_id="overnight-20260919", when=AS_OF)
        bad = _hold_reviews(self.hashes)
        bad["dollar-king"] = {
            "seat": "dollar-king",
            "thesis": "Open anyway.",
            "memory_context_sha256": "not-the-frozen-hash",
            "actions": [{
                "action": "OPEN", "instrument": "USDCAD", "side": "long", "notional_usd": 1_000_000,
                "price": 1.36, "asset_class": "spot_fx", "expression_memo": _spot_memo(),
            }],
        }
        with self.assertRaises(LearningGateError):
            apply_trader_review_with_memory(
                books, bad, families=_fresh_families(), run_id="overnight-20260919",
                evidence_cutoff="c", store=self.store, memory_hashes=self.hashes, when=AS_OF, market_state=MARKET,
            )
        missing = deepcopy(bad)
        missing["dollar-king"].pop("memory_context_sha256")
        missing["dollar-king"]["actions"] = [{"action": "HOLD"}]
        apply_trader_review_with_memory(
            books, missing, families=_fresh_families(), run_id="overnight-20260919",
            evidence_cutoff="c", store=self.store, memory_hashes=self.hashes, when=AS_OF,
        )

    def test_migration_does_not_invent_closed_trades(self) -> None:
        books = empty_trader_books(overnight_run_id="overnight-20260919", when=AS_OF)
        books["seats"]["dollar-king"]["history"] = [{
            "action": "CLOSE",
            "result": "applied",
            "instrument": "EURUSD",
            "position_id": "ghost-1",
            "price": 1.10,
            "notional_usd": 5_000_000,
        }]
        backfill_from_books(self.store, trader_books=books, when=AS_OF)
        self.assertEqual(self.store.list_trade_ids("trader", "dollar-king"), [])

    def test_action_rationale_helper(self) -> None:
        self.assertEqual(action_rationale({"action": "OPEN"}, {"thesis": "Because."}), "Because.")
        self.assertIsNone(action_rationale({"action": "OPEN"}, {}))

    def test_mixed_trader_reduce_executes_when_add_rationale_missing(self) -> None:
        books = self._trader_open(empty_trader_books(overnight_run_id="overnight-20260919", when=AS_OF))
        pos_id = books["seats"]["dollar-king"]["positions"][0]["position_id"]
        prior_notional = books["seats"]["dollar-king"]["positions"][0]["notional_usd"]
        self.hashes["dollar-king"] = build_memory_context(self.store, "trader", "dollar-king")["memory_context_sha256"]
        mixed = _hold_reviews(self.hashes)
        mixed["dollar-king"] = {
            "seat": "dollar-king",
            "conviction": 55,
            "memory_context_sha256": self.hashes["dollar-king"],
            "actions": [
                {
                    "action": "REDUCE",
                    "position_id": pos_id,
                    "notional_usd": 4_000_000,
                    "price": 1.36,
                    "rationale": "Cut risk.",
                    "expression_memo": _spot_memo(),
                },
                {
                    "action": "ADD",
                    "position_id": pos_id,
                    "notional_usd": 2_000_000,
                    "price": 1.36,
                    "asset_class": "spot_fx",
                    "expression_memo": {
                        "rates_candidate": None,
                        "spot_candidate": {"instrument": "USDCAD", "asset_class": "spot_fx"},
                        "options_candidate": None,
                        "selected": "spot",
                    },
                },
            ],
        }
        updated = apply_trader_review_with_memory(
            books, mixed, families=_fresh_families(), run_id="overnight-20260920",
            evidence_cutoff="2026-09-20T12:00:00-04:00", store=self.store,
            memory_hashes=self.hashes, when=AS_OF, market_state=MARKET,
        )
        remaining = updated["seats"]["dollar-king"]["positions"][0]["notional_usd"]
        self.assertAlmostEqual(remaining, prior_notional - 4_000_000, places=2)
        hist = updated["seats"]["dollar-king"]["history"]
        self.assertTrue(any(row.get("action") == "REDUCE" and row.get("result") == "applied" for row in hist))
        blocked = [row for row in hist if row.get("action") == "ADD" and row.get("result") == "blocked"]
        self.assertEqual(len(blocked), 1)
        self.assertIn("missing required expansion rationale", blocked[0]["blocked_reason"])
        trade = find_trade_by_position(self.store, owner_type="trader", owner_id="dollar-king", position_id=pos_id)
        assert trade is not None
        self.assertEqual([event["kind"] for event in trade["events"]], ["OPEN", "REDUCE"])
        event = self.store.read_journal("trader", "dollar-king")["events"][-1]
        results = {row["action"]: row for row in event["actions"]}
        self.assertEqual(results["REDUCE"]["result"], "applied")
        self.assertEqual(results["ADD"]["result"], "blocked")
        self.assertIn("missing required expansion rationale", results["ADD"]["blocked_reason"])

    def test_mixed_pm_close_executes_when_open_memory_is_stale(self) -> None:
        books = empty_pm_books()
        opened = apply_pm_decision_with_memory(
            books,
            {
                "pm_id": "chatgpt",
                "thesis": "CAD cheap vs the packet mid.",
                "rationale": "Open USDCAD from the frozen mid.",
                "memory_context_sha256": self.hashes["chatgpt"],
                "actions": [{"action": "OPEN", "instrument": "USDCAD", "side": "long", "notional_usd": 25_000_000, "asset_class": "spot_fx"}],
            },
            pm_id="chatgpt",
            store=self.store,
            market_state=MARKET,
            run_id="overnight-20260919",
            evidence_cutoff="2026-09-19T12:00:00-04:00",
            review_packet_id="prp-chatgpt-open",
            review_packet_sha256="hash-open",
            expected_memory_sha256=self.hashes["chatgpt"],
            when=AS_OF,
        )
        pos_id = opened["pms"]["chatgpt"]["positions"][0]["position_id"]
        mixed = apply_pm_decision_with_memory(
            opened,
            {
                "pm_id": "chatgpt",
                "thesis": "Exit the old risk; skip the stale re-entry.",
                "memory_context_sha256": "stale-not-the-frozen-hash",
                "actions": [
                    {"action": "CLOSE", "position_id": pos_id, "price": 1.40, "rationale": "Cut the risk."},
                    {
                        "action": "OPEN",
                        "instrument": "AUDUSD",
                        "side": "long",
                        "notional_usd": 10_000_000,
                        "asset_class": "spot_fx",
                        "rationale": "Would re-enter if memory were current.",
                    },
                ],
            },
            pm_id="chatgpt",
            store=self.store,
            market_state={"fx": {"pairs": {"USDCAD": {"spot": 1.40, "as_of": "2026-09-20"}, "AUDUSD": {"spot": 0.66}}}},
            run_id="overnight-20260920",
            evidence_cutoff="c",
            review_packet_id="prp-chatgpt-mixed",
            review_packet_sha256="hash-mixed",
            expected_memory_sha256=self.hashes["chatgpt"],
            when=AS_OF,
        )
        self.assertEqual(mixed["pms"]["chatgpt"]["positions"], [])
        hist = mixed["pms"]["chatgpt"]["history"]
        self.assertTrue(any(row.get("action") == "CLOSE" and row.get("result") == "applied" for row in hist))
        blocked = [row for row in hist if row.get("action") == "OPEN" and row.get("result") == "blocked"]
        self.assertEqual(len(blocked), 1)
        self.assertIn("stale_memory_context", blocked[0]["blocked_reason"])
        trade = find_trade_by_position(self.store, owner_type="pm", owner_id="chatgpt", position_id=pos_id)
        assert trade is not None
        self.assertEqual(trade["status"], "closed")
        self.assertGreater(trade["realized_pnl_usd"], 0)
        close_event = next(event for event in trade["events"] if event["kind"] == "CLOSE")
        journal = self.store.read_journal("pm", "chatgpt")["events"][-1]
        self.assertEqual(journal["kind"], "PM_DECISION")
        self.assertEqual(close_event["source_journal_event_id"], journal["event_id"])
        self.assertIn(trade["trade_id"], journal["linked_trade_ids"])
        self.assertIn(pos_id, journal["linked_position_ids"])
        results = {row["action"]: row for row in journal["actions"]}
        self.assertEqual(results["CLOSE"]["result"], "applied")
        self.assertEqual(results["OPEN"]["result"], "blocked")
        due = build_memory_context(self.store, "pm", "chatgpt")["postmortems_due"]
        self.assertEqual(due[0]["trade_id"], trade["trade_id"])
        self.assertEqual(self.store.list_trade_ids("pm", "chatgpt"), [trade["trade_id"]])

    def test_pure_invalid_expansion_cannot_mutate_risk(self) -> None:
        books = empty_trader_books(overnight_run_id="overnight-20260919", when=AS_OF)
        for kind, extra in (
            ("OPEN", {"instrument": "USDCAD", "side": "long", "notional_usd": 1_000_000, "asset_class": "spot_fx", "price": 1.36}),
            ("ADD", {"position_id": "missing", "notional_usd": 1_000_000, "price": 1.36}),
            ("HEDGE", {"hedge_of": "missing", "instrument": "USDCAD", "side": "short", "notional_usd": 1_000_000, "asset_class": "spot_fx", "price": 1.36}),
        ):
            bad = _hold_reviews(self.hashes)
            bad["dollar-king"] = {
                "seat": "dollar-king",
                "memory_context_sha256": self.hashes["dollar-king"],
                "actions": [{"action": kind, **extra}],
            }
            with self.assertRaises(RationaleError):
                apply_trader_review_with_memory(
                    books, bad, families=_fresh_families(), run_id="overnight-20260919",
                    evidence_cutoff="c", store=self.store, memory_hashes=self.hashes, when=AS_OF, market_state=MARKET,
                )
            self.assertEqual(books["seats"]["dollar-king"]["positions"], [])
            self.assertEqual(self.store.list_trade_ids("trader", "dollar-king"), [])

    def test_derisk_actions_remain_possible_under_stale_or_missing_memory(self) -> None:
        books = self._trader_open(empty_trader_books(overnight_run_id="overnight-20260919", when=AS_OF))
        pos_id = books["seats"]["dollar-king"]["positions"][0]["position_id"]
        hold = _hold_reviews(self.hashes)
        hold["dollar-king"] = {
            "seat": "dollar-king",
            "actions": [{"action": "HOLD", "expression_memo": _spot_memo()}],
        }
        books = apply_trader_review_with_memory(
            books, hold, families=_fresh_families(), run_id="overnight-20260920",
            evidence_cutoff="c", store=self.store, memory_hashes=self.hashes, when=AS_OF, market_state=MARKET,
        )
        self.assertEqual(books["seats"]["dollar-king"]["last_action"], "HOLD")
        reduce = _hold_reviews(self.hashes)
        reduce["dollar-king"] = {
            "seat": "dollar-king",
            "memory_context_sha256": "stale",
            "actions": [{
                "action": "REDUCE", "position_id": pos_id, "notional_usd": 1_000_000,
                "price": 1.36, "rationale": "De-risk without current memory.", "expression_memo": _spot_memo(),
            }],
        }
        books = apply_trader_review_with_memory(
            books, reduce, families=_fresh_families(), run_id="overnight-20260921",
            evidence_cutoff="c", store=self.store, memory_hashes=self.hashes, when=AS_OF, market_state=MARKET,
        )
        close = _hold_reviews(self.hashes)
        close["dollar-king"] = {
            "seat": "dollar-king",
            "actions": [{
                "action": "CLOSE", "position_id": pos_id, "price": 1.36,
                "rationale": "Exit under missing memory.", "expression_memo": _spot_memo(),
            }],
        }
        books = apply_trader_review_with_memory(
            books, close, families=_fresh_families(), run_id="overnight-20260922",
            evidence_cutoff="c", store=self.store, memory_hashes=self.hashes, when=AS_OF, market_state=MARKET,
        )
        self.assertFalse(any(p["position_id"] == pos_id for p in books["seats"]["dollar-king"]["positions"]))
        trade = find_trade_by_position(self.store, owner_type="trader", owner_id="dollar-king", position_id=pos_id)
        assert trade is not None
        self.assertEqual(trade["status"], "closed")

    def test_trader_and_pm_lifecycle_events_cross_link_journal(self) -> None:
        trader_books = self._trader_open(empty_trader_books(overnight_run_id="overnight-20260919", when=AS_OF))
        pos_id = trader_books["seats"]["dollar-king"]["positions"][0]["position_id"]
        open_journal = self.store.read_journal("trader", "dollar-king")["events"][0]
        trade = find_trade_by_position(self.store, owner_type="trader", owner_id="dollar-king", position_id=pos_id)
        assert trade is not None
        self.assertEqual(trade["source_journal_event_id"], open_journal["event_id"])
        self.assertEqual(trade["events"][0]["source_journal_event_id"], open_journal["event_id"])
        self.assertEqual(open_journal["linked_trade_ids"], [trade["trade_id"]])
        self.assertEqual(open_journal["linked_position_ids"], [pos_id])
        close = _hold_reviews(self.hashes)
        close["dollar-king"] = {
            "seat": "dollar-king",
            "thesis": "Exit.",
            "memory_context_sha256": self.hashes["dollar-king"],
            "actions": [{"action": "CLOSE", "position_id": pos_id, "price": 1.36, "rationale": "Done.", "expression_memo": _spot_memo()}],
        }
        apply_trader_review_with_memory(
            trader_books, close, families=_fresh_families(), run_id="overnight-20260920",
            evidence_cutoff="c", store=self.store, memory_hashes=self.hashes, when=AS_OF, market_state=MARKET,
        )
        trade = self.store.read_trade(trade["trade_id"])
        close_journal = self.store.read_journal("trader", "dollar-king")["events"][-1]
        close_event = next(event for event in trade["events"] if event["kind"] == "CLOSE")
        self.assertEqual(close_event["source_journal_event_id"], close_journal["event_id"])
        self.assertEqual(close_journal["linked_trade_ids"], [trade["trade_id"]])
        self.assertIn(pos_id, close_journal["linked_position_ids"])

        pm_books = apply_pm_decision_with_memory(
            empty_pm_books(),
            {
                "pm_id": "swinger",
                "thesis": "Open from the packet.",
                "rationale": "Swinger takes the CAD discrepancy.",
                "memory_context_sha256": self.hashes["swinger"],
                "actions": [{"action": "OPEN", "instrument": "USDCAD", "side": "long", "notional_usd": 20_000_000, "asset_class": "spot_fx"}],
            },
            pm_id="swinger",
            store=self.store,
            market_state=MARKET,
            run_id="overnight-20260919",
            evidence_cutoff="c",
            review_packet_id="prp-swinger-open",
            review_packet_sha256="hash-s",
            expected_memory_sha256=self.hashes["swinger"],
            when=AS_OF,
        )
        pm_pos = pm_books["pms"]["swinger"]["positions"][0]["position_id"]
        pm_trade = find_trade_by_position(self.store, owner_type="pm", owner_id="swinger", position_id=pm_pos)
        pm_journal = self.store.read_journal("pm", "swinger")["events"][0]
        assert pm_trade is not None
        self.assertEqual(pm_trade["source_journal_event_id"], pm_journal["event_id"])
        self.assertEqual(pm_trade["events"][0]["source_journal_event_id"], pm_journal["event_id"])
        self.assertEqual(pm_journal["linked_trade_ids"], [pm_trade["trade_id"]])
        closed = apply_pm_decision_with_memory(
            pm_books,
            {
                "pm_id": "swinger",
                "memory_context_sha256": self.hashes["swinger"],
                "actions": [{"action": "CLOSE", "position_id": pm_pos, "price": 1.40, "rationale": "Take it off."}],
            },
            pm_id="swinger",
            store=self.store,
            market_state={**MARKET, "fx": {"pairs": {"USDCAD": {"spot": 1.40}}}},
            run_id="overnight-20260920",
            evidence_cutoff="c",
            review_packet_id="prp-swinger-close",
            review_packet_sha256="hash-s2",
            expected_memory_sha256=self.hashes["swinger"],
            when=AS_OF,
        )
        self.assertEqual(closed["pms"]["swinger"]["positions"], [])
        pm_trade = self.store.read_trade(pm_trade["trade_id"])
        pm_close_journal = self.store.read_journal("pm", "swinger")["events"][-1]
        pm_close_event = next(event for event in pm_trade["events"] if event["kind"] == "CLOSE")
        self.assertEqual(pm_close_event["source_journal_event_id"], pm_close_journal["event_id"])
        self.assertEqual(pm_close_journal["linked_trade_ids"], [pm_trade["trade_id"]])

    def test_replay_does_not_duplicate_journal_or_ledger(self) -> None:
        books = empty_trader_books(overnight_run_id="overnight-20260919", when=AS_OF)
        first = self._trader_open(books)
        second = self._trader_open(first)
        journal = self.store.read_journal("trader", "dollar-king")
        self.assertEqual(len(journal["events"]), 1)
        self.assertEqual(len(second["seats"]["dollar-king"]["positions"]), 1)
        trade_ids = self.store.list_trade_ids("trader", "dollar-king")
        self.assertEqual(len(trade_ids), 1)
        trade = self.store.read_trade(trade_ids[0])
        self.assertEqual([event["kind"] for event in trade["events"]], ["OPEN"])
        pm_books = apply_pm_decision_with_memory(
            empty_pm_books(),
            {
                "pm_id": "chatgpt",
                "thesis": "Open once.",
                "rationale": "Idempotent apply.",
                "memory_context_sha256": self.hashes["chatgpt"],
                "actions": [{"action": "OPEN", "instrument": "USDCAD", "side": "long", "notional_usd": 15_000_000, "asset_class": "spot_fx"}],
            },
            pm_id="chatgpt",
            store=self.store,
            market_state=MARKET,
            run_id="overnight-20260919",
            evidence_cutoff="c",
            review_packet_id="prp-chatgpt-once",
            review_packet_sha256="hash-once",
            expected_memory_sha256=self.hashes["chatgpt"],
            when=AS_OF,
        )
        replayed = apply_pm_decision_with_memory(
            pm_books,
            {
                "pm_id": "chatgpt",
                "thesis": "Open once.",
                "rationale": "Idempotent apply.",
                "memory_context_sha256": self.hashes["chatgpt"],
                "actions": [{"action": "OPEN", "instrument": "USDCAD", "side": "long", "notional_usd": 15_000_000, "asset_class": "spot_fx"}],
            },
            pm_id="chatgpt",
            store=self.store,
            market_state=MARKET,
            run_id="overnight-20260919",
            evidence_cutoff="c",
            review_packet_id="prp-chatgpt-once",
            review_packet_sha256="hash-once",
            expected_memory_sha256=self.hashes["chatgpt"],
            when=AS_OF,
        )
        self.assertEqual(len(self.store.read_journal("pm", "chatgpt")["events"]), 1)
        self.assertEqual(len(replayed["pms"]["chatgpt"]["positions"]), 1)
        self.assertEqual(len([row for row in replayed["pms"]["chatgpt"]["history"] if row.get("action") == "OPEN"]), 1)

    def test_migration_does_not_fabricate_journal_links(self) -> None:
        books = empty_trader_books(overnight_run_id="overnight-20260919", when=AS_OF)
        books["seats"]["dollar-king"]["positions"] = [{
            "position_id": "legacy-open-1",
            "instrument": "USDCAD",
            "asset_class": "spot_fx",
            "side": "long",
            "notional_usd": 5_000_000,
            "entry_price": 1.36,
            "mark_price": 1.36,
            "opened_at": "2026-09-18T12:00:00-04:00",
            "opened_run_id": "overnight-20260918",
            "thesis": "Legacy live position.",
        }]
        backfill_from_books(self.store, trader_books=books, when=AS_OF)
        trade = find_trade_by_position(
            self.store, owner_type="trader", owner_id="dollar-king", position_id="legacy-open-1"
        )
        assert trade is not None
        self.assertIsNone(trade["source_journal_event_id"])
        self.assertIsNone(trade["events"][0]["source_journal_event_id"])
        self.assertEqual(self.store.read_journal("trader", "dollar-king")["events"], [])

    def test_same_decision_close_does_not_block_sibling_derisk(self) -> None:
        books = self._trader_open(empty_trader_books(overnight_run_id="overnight-20260919", when=AS_OF))
        first = books["seats"]["dollar-king"]["positions"][0]["position_id"]
        second_open = _hold_reviews(self.hashes)
        second_open["dollar-king"] = {
            "seat": "dollar-king",
            "conviction": 70,
            "thesis": "Second USD expression.",
            "memory_context_sha256": self.hashes["dollar-king"],
            "expression_memo": _spot_memo(),
            "actions": [{
                "action": "OPEN", "instrument": "USDCAD", "side": "long", "notional_usd": 3_000_000,
                "price": 1.36, "asset_class": "spot_fx", "expression_memo": _spot_memo(),
                "rationale": "Second open.",
            }],
        }
        books = apply_trader_review_with_memory(
            books, second_open, families=_fresh_families(), run_id="overnight-20260920",
            evidence_cutoff="c", store=self.store, memory_hashes=self.hashes, when=AS_OF,
            market_state=MARKET,
        )
        second = next(p["position_id"] for p in books["seats"]["dollar-king"]["positions"] if p["position_id"] != first)
        both_close = _hold_reviews(self.hashes)
        both_close["dollar-king"] = {
            "seat": "dollar-king",
            "memory_context_sha256": "stale",
            "actions": [
                {"action": "CLOSE", "position_id": first, "price": 1.36, "rationale": "Cut first.", "expression_memo": _spot_memo()},
                {"action": "CLOSE", "position_id": second, "price": 1.36, "rationale": "Cut second.", "expression_memo": _spot_memo()},
            ],
        }
        books = apply_trader_review_with_memory(
            books, both_close, families=_fresh_families(), run_id="overnight-20260921",
            evidence_cutoff="c", store=self.store, memory_hashes=self.hashes, when=AS_OF,
            market_state=MARKET,
        )
        self.assertEqual(books["seats"]["dollar-king"]["positions"], [])
        for pos_id in (first, second):
            trade = find_trade_by_position(self.store, owner_type="trader", owner_id="dollar-king", position_id=pos_id)
            assert trade is not None
            self.assertEqual(trade["status"], "closed")


class OvernightAndTraderRoomMemoryTests(unittest.TestCase):
    def test_overnight_dry_run_snapshots_per_seat_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            result = overnight_dry_run(
                root=ROOT,
                state_root=state,
                when=datetime(2026, 9, 18, 4, 10, tzinfo=NY),
                suffix="memory",
                market_state_path=ROOT / "data" / "overnight" / "fixtures" / "market_state.json",
                review_scenario="default",
            )
            run_id = result["overnight_run_id"]
            store = OvernightStore(root=ROOT, state_root=state)
            snapshot = store.read_artifact(run_id, "evidence_snapshot.json")
            hashes = snapshot["seat_memory"]["hashes"]
            self.assertEqual(set(hashes), set(STANDING_SEATS))
            dollar = json.loads((store.run_dir(run_id) / "memory" / "dollar-king.json").read_text(encoding="utf-8"))
            bear = json.loads((store.run_dir(run_id) / "memory" / "perma-bear.json").read_text(encoding="utf-8"))
            self.assertEqual(dollar["owner_id"], "dollar-king")
            self.assertEqual(bear["owner_id"], "perma-bear")
            self.assertNotEqual(dollar["memory_context_sha256"], "")
            self.assertNotIn("trd-trader-perma-bear", json.dumps(dollar))
            trading = TradingStore(root=ROOT, state_root=state)
            journal = trading.read_journal("trader", "dollar-king")
            self.assertTrue(journal["events"])
            self.assertEqual(journal["events"][0]["memory_context_sha256"], hashes["dollar-king"])
            if trading.list_trade_ids("trader", "dollar-king"):
                trade = trading.read_trade(trading.list_trade_ids("trader", "dollar-king")[0])
                self.assertIn(trade["status"], {"open", "closed"})
                self.assertIsNotNone(trade["entry_mark"])

    def test_scheduled_output_binds_memory_hash_and_persists_trading_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            run_id = "overnight-20260918"
            as_of = datetime.fromisoformat("2026-09-18T01:55:00-04:00")
            for stage in ("collect", "pre_trader_delta", "freeze_evidence"):
                run_stage(
                    stage, root=ROOT, state_root=state, run_id=run_id, when=as_of, dry_run=True,
                    market_state_path=ROOT / "data" / "overnight" / "fixtures" / "market_state.json",
                )
            store = OvernightStore(root=ROOT, state_root=state)
            base = store.read_artifact(run_id, "evidence_snapshot.json")
            packet = {
                "schema_version": 1,
                "type": AGENT_PACKET_TYPE,
                "overnight_run_id": run_id,
                "base_packet_sha256": base["packet_sha256"],
                "base_evidence_cutoff": base["as_of"],
                "evidence_cutoff": "2026-09-18T02:20:00-04:00",
                "competition": base["competition"],
                "research_supplement": {"summary": "none", "news": [], "central_bank_research": [], "sources": []},
            }
            packet["packet_sha256"] = sha256_json(packet)
            decisions = {}
            for seat in STANDING_SEATS:
                decisions[seat] = {
                    "seat": seat,
                    "overnight_run_id": run_id,
                    "packet_sha256": packet["packet_sha256"],
                    "evidence_cutoff": packet["evidence_cutoff"],
                    "conviction": 25,
                    "thesis": "No incremental edge.",
                    "memory_context_sha256": base["seat_memory"]["hashes"][seat],
                    "actions": [{"action": "HOLD", "expression_memo": {"selected": "none", "rationale": "Hold.", "rates_candidate": None, "spot_candidate": None, "options_candidate": None}}],
                }
                if seat == "no-trade-skeptic":
                    decisions[seat]["funding_view"] = {
                        "current_sofr": "Frozen official NY Fed SOFR fixing in funding_context.",
                        "sr3_forward_view": "Frozen SR3 contracts are the relevant forward-funding path.",
                        "forward_funding_assessment": "about_the_same",
                        "implication": "Prefer cash earning official SOFR unless a packet-supported trade beats that hurdle.",
                    }
            payload = {
                "schema_version": 1,
                "type": "OVERNIGHT_SCHEDULED_OUTPUT",
                "schedule_id": SCHEDULE_ID,
                "overnight_run_id": run_id,
                "base_packet_sha256": base["packet_sha256"],
                "agent_packet": packet,
                "decisions": decisions,
                "execution": {
                    "parent_model": "grok-4.6",
                    "allowed_subagent_models": ["composer-2.5", "grok-4.6"],
                    "total_model_cap": 18,
                    "grok_cap": 16,
                    "composer_cap": 2,
                    "declared_total_model_calls": 16,
                    "declared_grok_calls": 15,
                    "declared_composer_calls": 1,
                    "other_models_calls": 0,
                    "auto_used": False,
                },
            }
            apply_output(store, payload)
            trading = TradingStore(root=ROOT, state_root=state)
            event = trading.read_journal("trader", "no-trade-skeptic")["events"][0]
            self.assertEqual(event["kind"], "OVERNIGHT_DECISION")
            self.assertEqual(event["memory_context_sha256"], base["seat_memory"]["hashes"]["no-trade-skeptic"])
            self.assertTrue((state / "data" / "trading" / "index.json").is_file())

    def test_trader_room_dry_run_journals_without_executing_trades(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_root = Path(tmp)
            result = trader_room_go(topic="go", synthetic=True, artifact_root=artifact_root)
            plan = result["launch_plan"]
            self.assertEqual(plan["common_evidence_sha256"], result["packet_sha256"])
            self.assertEqual({row["name"] for row in plan["advocates"]}, set(STANDING_ADVOCATES))
            hashes = {row["name"]: row["memory_context_sha256"] for row in plan["advocates"]}
            self.assertEqual(len(set(hashes.values())), len(STANDING_ADVOCATES) or 1)
            for row in plan["advocates"]:
                self.assertTrue(row["memory_sidecar_path"].endswith(f"{row['name']}.json"))
            trading = TradingStore(root=artifact_root, state_root=artifact_root)
            dollar = trading.read_journal("trader", "dollar-king")
            kinds = {event["kind"] for event in dollar["events"]}
            self.assertIn("TRADER_ROOM_PROPOSAL", kinds)
            self.assertEqual(trading.list_trade_ids("trader", "dollar-king"), [])
            other = json.dumps(trading.read_context("trader", "dollar-king") or {})
            self.assertNotIn("trd-pm-chatgpt", other)
            proposal = next(event for event in dollar["events"] if event["kind"] == "TRADER_ROOM_PROPOSAL")
            rebuttal = next(event for event in dollar["events"] if event["kind"] == "TRADER_ROOM_REBUTTAL")
            contribution = proposal["payload"]["contribution"]
            original = result["originals"]["dollar-king"]
            self.assertEqual(contribution["type"], "TRADER_ROOM_CONTRIBUTION")
            self.assertEqual(contribution["stance_summary"], original["stance_summary"])
            self.assertEqual(contribution["conflict_synopsis"], original["conflict_synopsis"])
            self.assertEqual(contribution["trade"]["context_build"], original["trade"]["context_build"])
            self.assertEqual(contribution["macro_assumptions"], original["macro_assumptions"])
            self.assertNotIn("reasoning", contribution)
            self.assertNotIn("evidence_packet", contribution)
            self.assertTrue(proposal["provenance"]["source_ref"].endswith("submissions/dollar-king.json"))
            stored_rebuttal = rebuttal["payload"]["rebuttal"]
            original_rebuttal = result["rebuttals"]["dollar-king"]
            self.assertEqual(stored_rebuttal["type"], "TRADER_ROOM_REBUTTAL")
            self.assertEqual(stored_rebuttal["holes_in_opposing_case"], original_rebuttal["holes_in_opposing_case"])
            self.assertEqual(stored_rebuttal["attack"], original_rebuttal["attack"])
            self.assertEqual(stored_rebuttal["defense"], original_rebuttal["defense"])
            self.assertEqual(stored_rebuttal["revised_trade"], original_rebuttal["revised_trade"])
            self.assertTrue(rebuttal["provenance"]["source_ref"].endswith("rebuttals/dollar-king.json"))
            on_disk = json.loads((artifact_root / "data" / "trading" / "trader" / "dollar-king" / "journal.json").read_text(encoding="utf-8"))
            self.assertEqual(on_disk["events"][0]["payload"]["contribution"]["trade"]["thesis"], original["trade"]["thesis"])
            self.assertEqual(trading.list_trade_ids("trader", "dollar-king"), [])

    def test_ondemand_journal_helpers_keep_source_ref_and_drop_hidden_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TradingStore(root=root, state_root=root)
            store.ensure_initialized()
            contribution = {
                "type": "TRADER_ROOM_CONTRIBUTION",
                "run_id": "tr-test-1",
                "round": 1,
                "agent": "dollar-king",
                "archetype": "dollar-king",
                "stance_summary": "USD premium remains the cleanest expression.",
                "trade": {"instrument": "USDCAD", "direction": "long", "thesis": "USD still pays.", "context_build": {"causal_mechanism": "policy premium"}},
                "confidence": 61,
                "remit": "USD-centric",
                "conflict_synopsis": {"seat": "dollar-king", "core_view": "USD firm"},
                "macro_assumptions": {"policy": "hawkish"},
                "reasoning": "hidden private chain of thought",
                "evidence_packet": {"do_not_store": True},
            }
            event = journal_trader_room_pitch(
                store,
                contribution,
                run_id="tr-test-1",
                evidence_cutoff="2026-09-19T12:00:00-04:00",
                evidence_hash="pkt",
                memory_context_sha256="mem",
                source_ref="trader-room/runs/tr-test-1/submissions/dollar-king.json",
            )
            replay = journal_trader_room_pitch(
                store,
                contribution,
                run_id="tr-test-1",
                evidence_cutoff="2026-09-19T12:00:00-04:00",
                evidence_hash="pkt",
                memory_context_sha256="mem",
                source_ref="trader-room/runs/tr-test-1/submissions/dollar-king.json",
            )
            self.assertEqual(event["event_id"], replay["event_id"])
            self.assertEqual(len(store.read_journal("trader", "dollar-king")["events"]), 1)
            payload = event["payload"]["contribution"]
            self.assertEqual(payload["stance_summary"], contribution["stance_summary"])
            self.assertEqual(payload["trade"]["context_build"], contribution["trade"]["context_build"])
            self.assertNotIn("reasoning", payload)
            self.assertNotIn("evidence_packet", payload)
            self.assertEqual(event["provenance"]["source_ref"], "trader-room/runs/tr-test-1/submissions/dollar-king.json")
            rebuttal = journal_trader_room_rebuttal(
                store,
                {
                    "type": "TRADER_ROOM_REBUTTAL",
                    "run_id": "tr-test-1",
                    "round": 2,
                    "agent": "dollar-king",
                    "opponents": ["perma-bull"],
                    "own_original_ref": "submissions/dollar-king.json",
                    "holes_in_opposing_case": ["The opposing AUD case does not own the USD premium."],
                    "attack": ["Cross risk is less clean."],
                    "defense": ["USD spot remains the remit."],
                    "trade_change": "unchanged",
                    "revised_trade": contribution["trade"],
                    "thinking": "runtime only",
                },
                run_id="tr-test-1",
                evidence_cutoff="2026-09-19T12:00:00-04:00",
                evidence_hash="pkt",
                memory_context_sha256="mem",
                source_ref="trader-room/runs/tr-test-1/rebuttals/dollar-king.json",
            )
            self.assertEqual(rebuttal["payload"]["rebuttal"]["holes_in_opposing_case"], ["The opposing AUD case does not own the USD premium."])
            self.assertNotIn("thinking", rebuttal["payload"]["rebuttal"])
            self.assertEqual(store.list_trade_ids("trader", "dollar-king"), [])

    def test_pm_review_packet_includes_own_memory_only(self) -> None:
        from scripts.pm.cli import init_layer
        from scripts.pm.store import PMStore

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            pm_store = PMStore(root=ROOT, state_root=state)
            init_layer(pm_store)
            packet = pm_store.read_json(pm_store.packet_path("chatgpt"))
            self.assertIn("memory", packet)
            self.assertEqual(packet["memory"]["owner_id"], "chatgpt")
            self.assertEqual(packet["memory_context_sha256"], packet["memory"]["memory_context_sha256"])
            self.assertIn("postmortems_due", packet)
            leaked = json.dumps(packet["memory"])
            for other in ("swinger", "pragmatist", "grinder"):
                self.assertNotIn(f'"owner_id": "{other}"', leaked)


if __name__ == "__main__":
    unittest.main()
