#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]

from scripts.overnight.books import (
    allocation_limit_usd,
    apply_action,
    apply_review,
    deployed_notional,
    empty_books,
    empty_seat,
    public_books_view,
)
from scripts.overnight.constants import STANDING_SEATS, STARTING_NAV_USD
from scripts.overnight.publish import emit_trader_books_json
from scripts.overnight.store import OvernightStore, write_json
from scripts.trader_room.paper_book import (
    action_from_paper_capital,
    paper_actions_from_contribution,
    persist_ondemand_trader_books,
    reviews_from_run,
)
from scripts.trading.apply import apply_trader_review_with_memory
from scripts.trading.constants import ALL_IDENTITIES
from scripts.trading.ledger import find_trade_by_position
from scripts.trading.memory import build_memory_context
from scripts.trading.store import TradingStore

NY = ZoneInfo("America/New_York")
AS_OF = datetime(2026, 9, 20, 12, 0, tzinfo=NY)
MARKET = {
    "fx": {
        "pairs": {
            "USDCAD": {"spot": 1.36, "as_of": "2026-09-20"},
            "USDJPY": {"spot": 148.0, "as_of": "2026-09-20"},
        }
    }
}


def _fresh_families() -> dict:
    return {
        "macro_hard": {"status": "fresh", "as_of": "2026-09-20T00:07:00-04:00", "digest": "m"},
        "news": {"status": "fresh", "as_of": "2026-09-20T00:07:00-04:00", "digest": "n"},
        "central_bank_research": {"status": "fresh", "as_of": "2026-09-20T00:07:00-04:00", "digest": "c"},
        "market_state": {"status": "fresh", "as_of": "2026-09-20T00:07:00-04:00", "digest": "s", "data": MARKET},
    }


def _spot_memo(instrument: str = "USDCAD") -> dict:
    return {
        "rates_candidate": None,
        "spot_candidate": {"instrument": instrument, "asset_class": "spot_fx", "rationale": "spot"},
        "options_candidate": None,
        "selected": "spot",
        "rationale": "spot expression",
    }


def _hold_reviews(memory_hashes: dict[str, str], **overrides: dict) -> dict:
    reviews = {}
    for seat in STANDING_SEATS:
        reviews[seat] = {
            "seat": seat,
            "conviction": 30,
            "thesis": "Hold.",
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
    reviews.update(overrides)
    return reviews


def _two_open_actions() -> list[dict]:
    return [
        {
            "action": "OPEN",
            "instrument": "USDCAD",
            "side": "long",
            "notional_usd": 25_000_000,
            "asset_class": "spot_fx",
            "expression_memo": _spot_memo("USDCAD"),
            "thesis": "CAD leg.",
            "invalidation": "Canada growth reprices materially stronger.",
        },
        {
            "action": "OPEN",
            "instrument": "USDJPY",
            "side": "long",
            "notional_usd": 15_000_000,
            "asset_class": "spot_fx",
            "expression_memo": _spot_memo("USDJPY"),
            "thesis": "JPY leg.",
            "invalidation": "BoJ reprices materially more hawkish.",
        },
    ]


class TraderBookLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = TradingStore(root=self.root, state_root=self.root)
        self.store.ensure_initialized()
        self.hashes = {
            owner_id: build_memory_context(self.store, owner_type, owner_id)["memory_context_sha256"]
            for owner_type, owner_id in ALL_IDENTITIES
        }
        self.families = _fresh_families()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _apply_multi_open(self, books: dict, run_id: str) -> dict:
        reviews = _hold_reviews(self.hashes)
        reviews["dollar-king"] = {
            "seat": "dollar-king",
            "conviction": 70,
            "thesis": "Two spot legs.",
            "memory_context_sha256": self.hashes["dollar-king"],
            "actions": _two_open_actions(),
        }
        return apply_trader_review_with_memory(
            books,
            reviews,
            families=self.families,
            run_id=run_id,
            evidence_cutoff="2026-09-20T12:00:00-04:00",
            store=self.store,
            memory_hashes=self.hashes,
            evidence_hash="pkt-1",
            when=AS_OF,
            market_state=MARKET,
        )

    def test_multi_position_apply_and_public_views(self) -> None:
        books = empty_books(overnight_run_id="tr-multi-1", when=AS_OF)
        updated = self._apply_multi_open(books, "tr-multi-1")
        seat = updated["seats"]["dollar-king"]
        self.assertEqual(len(seat["positions"]), 2)
        view = public_books_view(updated)
        dk = next(row for row in view["seats"] if row["seat"] == "dollar-king")
        self.assertEqual(len(dk["positions"]), 2)
        instruments = {p["instrument"] for p in dk["positions"]}
        self.assertEqual(instruments, {"USDCAD", "USDJPY"})
        by_instrument = {p["instrument"]: p for p in dk["positions"]}
        self.assertEqual(by_instrument["USDCAD"]["thesis"], "CAD leg.")
        self.assertEqual(by_instrument["USDCAD"]["invalidation"], "Canada growth reprices materially stronger.")
        self.assertEqual(by_instrument["USDJPY"]["thesis"], "JPY leg.")
        self.assertEqual(by_instrument["USDJPY"]["invalidation"], "BoJ reprices materially more hawkish.")
        self.assertTrue(by_instrument["USDCAD"]["opened_at"])

    def test_successive_runs_preserve_independent_positions(self) -> None:
        books = self._apply_multi_open(empty_books(overnight_run_id="tr-multi-1", when=AS_OF), "tr-multi-1")
        positions = books["seats"]["dollar-king"]["positions"]
        cad = next(p for p in positions if p["instrument"] == "USDCAD")
        self.hashes["dollar-king"] = build_memory_context(self.store, "trader", "dollar-king")["memory_context_sha256"]
        add = _hold_reviews(self.hashes)
        add["dollar-king"] = {
            "seat": "dollar-king",
            "memory_context_sha256": self.hashes["dollar-king"],
            "actions": [
                {
                    "action": "ADD",
                    "position_id": cad["position_id"],
                    "notional_usd": 1_000_000,
                    "expression_memo": _spot_memo("USDCAD"),
                    "thesis": "Add CAD only.",
                }
            ],
        }
        books = apply_trader_review_with_memory(
            books,
            add,
            families=self.families,
            run_id="tr-multi-2",
            evidence_cutoff="2026-09-21T12:00:00-04:00",
            store=self.store,
            memory_hashes=self.hashes,
            when=AS_OF,
            market_state=MARKET,
        )
        seat = books["seats"]["dollar-king"]
        self.assertEqual(len(seat["positions"]), 2)
        cad_after = next(p for p in seat["positions"] if p["instrument"] == "USDCAD")
        self.assertEqual(cad_after["notional_usd"], 26_000_000)

        self.hashes["dollar-king"] = build_memory_context(self.store, "trader", "dollar-king")["memory_context_sha256"]
        reduce_close = _hold_reviews(self.hashes)
        reduce_close["dollar-king"] = {
            "seat": "dollar-king",
            "memory_context_sha256": self.hashes["dollar-king"],
            "actions": [
                {
                    "action": "REDUCE",
                    "position_id": cad["position_id"],
                    "notional_usd": 2_000_000,
                    "expression_memo": _spot_memo("USDCAD"),
                    "thesis": "Trim CAD only.",
                }
            ],
        }
        books = apply_trader_review_with_memory(
            books,
            reduce_close,
            families=self.families,
            run_id="tr-multi-3",
            evidence_cutoff="2026-09-22T12:00:00-04:00",
            store=self.store,
            memory_hashes=self.hashes,
            when=AS_OF,
            market_state=MARKET,
        )
        seat = books["seats"]["dollar-king"]
        self.assertEqual(len(seat["positions"]), 2)
        cad_trimmed = next(p for p in seat["positions"] if p["instrument"] == "USDCAD")
        jpy = next(p for p in seat["positions"] if p["instrument"] == "USDJPY")
        self.assertEqual(cad_trimmed["notional_usd"], 24_000_000)
        self.assertEqual(jpy["notional_usd"], 15_000_000)

        self.hashes["dollar-king"] = build_memory_context(self.store, "trader", "dollar-king")["memory_context_sha256"]
        close_cad = _hold_reviews(self.hashes)
        close_cad["dollar-king"] = {
            "seat": "dollar-king",
            "memory_context_sha256": self.hashes["dollar-king"],
            "actions": [
                {
                    "action": "CLOSE",
                    "position_id": cad["position_id"],
                    "expression_memo": _spot_memo("USDCAD"),
                    "thesis": "Close CAD; keep JPY.",
                }
            ],
        }
        books = apply_trader_review_with_memory(
            books,
            close_cad,
            families=self.families,
            run_id="tr-multi-4",
            evidence_cutoff="2026-09-23T12:00:00-04:00",
            store=self.store,
            memory_hashes=self.hashes,
            when=AS_OF,
            market_state=MARKET,
        )
        remaining = books["seats"]["dollar-king"]["positions"]
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["instrument"], "USDJPY")

    def test_no_trade_skeptic_cap(self) -> None:
        skeptic = empty_seat("no-trade-skeptic")
        families = self.families
        apply_action(
            skeptic,
            {
                "action": "OPEN",
                "instrument": "US 10Y",
                "side": "long",
                "notional_usd": 1_000_000_000,
                "price": 4.2,
                "asset_class": "rates",
                "expression_memo": {
                    "rates_candidate": {"instrument": "US 10Y", "asset_class": "rates", "rationale": "r"},
                    "spot_candidate": {"instrument": "USDCAD", "asset_class": "spot_fx", "rationale": "s"},
                    "options_candidate": None,
                    "selected": "rates",
                    "rationale": "Full deploy.",
                },
                "thesis": "Full book.",
            },
            families=families,
            run_id="tr-skeptic-ok",
            when=AS_OF,
        )
        self.assertEqual(deployed_notional(skeptic), 1_000_000_000)
        self.assertEqual(skeptic["risk_capital_usd"], allocation_limit_usd())
        apply_action(
            skeptic,
            {
                "action": "OPEN",
                "instrument": "US 2Y",
                "side": "long",
                "notional_usd": 1,
                "price": 4.0,
                "asset_class": "rates",
                "expression_memo": {
                    "rates_candidate": {"instrument": "US 2Y", "asset_class": "rates", "rationale": "r"},
                    "spot_candidate": {"instrument": "USDCAD", "asset_class": "spot_fx", "rationale": "s"},
                    "options_candidate": None,
                    "selected": "rates",
                    "rationale": "Too much.",
                },
                "thesis": "Blocked.",
            },
            families=families,
            run_id="tr-skeptic-block",
            when=AS_OF,
        )
        self.assertEqual(len(skeptic["positions"]), 1)
        self.assertTrue(any(row.get("result") == "blocked_risk_capital" for row in skeptic["history"]))

    def test_canonical_books_win_over_stale_assembled_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = OvernightStore(root=root, state_root=root)
            stale_books = public_books_view(empty_books(overnight_run_id="overnight-old", when=AS_OF))
            dataset = {
                "schema_version": 1,
                "type": "OVERNIGHT_MORNING_DATASET",
                "overnight_run_id": "overnight-old",
                "as_of": "2026-09-18T04:07:00-04:00",
                "timezone": "America/New_York",
                "dry_run": True,
                "core": {
                    "macro_hard": {"status": "fresh"},
                    "news": {"status": "fresh"},
                    "central_bank_research": {"status": "fresh"},
                    "market_state": {"status": "fresh"},
                },
                "agent_research": {"note": "morning research"},
                "trader_books": stale_books,
                "publication": {
                    "may_publish": True,
                    "core_status": "ok",
                    "trader_books_status": "fresh",
                    "reason": "ok",
                },
            }
            store.write_artifact("overnight-old", "assembled_dataset.json", dataset)
            write_json(store.latest_path(), {"overnight_run_id": "overnight-old", "as_of": dataset["as_of"]})
            live = empty_books(overnight_run_id="tr-newer", when=AS_OF)
            seat = live["seats"]["dollar-king"]
            seat["positions"] = [
                {
                    "position_id": "pos-test-1",
                    "instrument": "USDCAD",
                    "asset_class": "spot_fx",
                    "side": "long",
                    "notional_usd": 5_000_000,
                    "entry_price": 1.36,
                    "mark_price": 1.36,
                },
                {
                    "position_id": "pos-test-2",
                    "instrument": "USDJPY",
                    "asset_class": "spot_fx",
                    "side": "long",
                    "notional_usd": 3_000_000,
                    "entry_price": 148.0,
                    "mark_price": 148.0,
                },
            ]
            from scripts.overnight.books import mark_to_market, validate_books

            validate_books(live)
            store.write_books(live)
            site = root / "_site"
            emit_trader_books_json(store, site)
            payload = json.loads((site / "trader-books.json").read_text(encoding="utf-8"))
            dk = next(row for row in payload["seats"] if row["seat"] == "dollar-king")
            self.assertEqual(len(dk["positions"]), 2)
            self.assertEqual(payload.get("overnight_research"), {"note": "morning research"})
            self.assertEqual(payload.get("books_run_id"), "tr-newer")

    def test_trader_book_js_maps_all_positions_without_slice(self) -> None:
        js = (ROOT / "patch_v13" / "trader-book.js").read_text(encoding="utf-8")
        self.assertIn("(seat.positions || [])", js)
        self.assertIn("function renderPosition", js)
        self.assertEqual(js.count("positions.map(renderPosition)"), 2)
        self.assertIn("<b>Why:</b>", js)
        self.assertIn("<b>Invalidation:</b>", js)
        self.assertNotRegex(js, r"positions\.slice")

    def test_debate_only_does_not_invent_open(self) -> None:
        contribution = {
            "trade": {"instrument": "USDCAD", "direction": "long", "thesis": "Pitch only."},
        }
        self.assertEqual(paper_actions_from_contribution(contribution), [{"action": "HOLD"}])

    def test_legacy_paper_capital_maps_to_open(self) -> None:
        contribution = {
            "trade": {
                "instrument": "USDCAD",
                "direction": "long",
                "thesis": "Legacy capital.",
                "asset_class": "spot_fx",
                "expression_comparison": {
                    "rates_candidate": None,
                    "spot_candidate": "long USDCAD",
                    "selected": "spot",
                    "rationale": "spot",
                },
            }
        }
        action = action_from_paper_capital(
            {"action": "OPEN", "notional_usd": 10_000_000},
            contribution,
        )
        self.assertEqual(action["action"], "OPEN")
        self.assertEqual(action["instrument"], "USDCAD")
        self.assertEqual(action["side"], "long")

    def test_legacy_paper_capital_persists_with_string_comparison(self) -> None:
        run_id = "tr-legacy-capital"
        run_dir = self.root / "trader-room" / "runs" / run_id
        run_dir.mkdir(parents=True)
        packet = {
            "run_id": run_id,
            "as_of": "2026-09-20T12:00:00-04:00",
            "packet_sha256": "sha-legacy",
            "market_state": MARKET,
        }
        originals = {
            seat: {
                "agent": seat,
                "trade": None if seat == "no-trade-skeptic" else {"instrument": "USDCAD", "direction": "long"},
                "confidence": 50,
                "conflict_synopsis": {"key_invalidation": "x", "core_view": "hold"},
            }
            for seat in STANDING_SEATS
        }
        originals["dollar-king"] = {
            "agent": "dollar-king",
            "confidence": 60,
            "conflict_synopsis": {"key_invalidation": "x", "core_view": "USD premium"},
            "trade": {
                "instrument": "USDCAD",
                "direction": "long",
                "thesis": "USD versus CAD.",
                "asset_class": "spot_fx",
                "expression_comparison": {
                    "rates_candidate": None,
                    "spot_candidate": "long USDCAD",
                    "selected": "spot",
                    "rationale": "Dedicated USD spot seat.",
                },
            },
            "paper_capital": {
                "decision": "OPEN",
                "instrument": "USDCAD",
                "notional_usd": 25_000_000,
                "side": "long",
                "asset_class": "spot_fx",
                "rationale": "Legacy one-capital decision.",
            },
        }
        persist_ondemand_trader_books(
            root=self.root,
            run_dir=run_dir,
            packet=packet,
            originals=originals,
            rebuttals={},
            memory_hashes=self.hashes,
            when=AS_OF,
        )
        overnight = OvernightStore(root=self.root, state_root=self.root)
        books = json.loads(overnight.books_path().read_text(encoding="utf-8"))
        positions = books["seats"]["dollar-king"]["positions"]
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]["instrument"], "USDCAD")
        self.assertEqual(positions[0]["notional_usd"], 25_000_000)

    def test_persist_ondemand_two_opens_and_follow_on(self) -> None:
        run_id = "tr-persist-1"
        run_dir = self.root / "trader-room" / "runs" / run_id
        run_dir.mkdir(parents=True)
        packet = {
            "run_id": run_id,
            "as_of": "2026-09-20T12:00:00-04:00",
            "packet_sha256": "sha-persist",
            "market_state": MARKET,
        }
        originals = {
            seat: {
                "agent": seat,
                "trade": None if seat == "no-trade-skeptic" else {"instrument": "USDCAD", "direction": "long"},
                "confidence": 50,
                "conflict_synopsis": {"key_invalidation": "x", "core_view": "hold"},
            }
            for seat in STANDING_SEATS
        }
        originals["dollar-king"]["paper_actions"] = _two_open_actions()
        originals["dollar-king"]["trade"] = {
            "instrument": "USDCAD",
            "direction": "long",
            "thesis": "Two opens.",
            "asset_class": "spot_fx",
            "expression_comparison": {
                "rates_candidate": None,
                "spot_candidate": "long USDCAD",
                "selected": "spot",
                "rationale": "spot",
            },
        }
        rebuttals = {seat: {} for seat in STANDING_SEATS}
        persist_ondemand_trader_books(
            root=self.root,
            run_dir=run_dir,
            packet=packet,
            originals=originals,
            rebuttals=rebuttals,
            memory_hashes=self.hashes,
            when=AS_OF,
        )
        overnight = OvernightStore(root=self.root, state_root=self.root)
        books = json.loads(overnight.books_path().read_text(encoding="utf-8"))
        dk = books["seats"]["dollar-king"]
        self.assertEqual(len(dk["positions"]), 2)
        for pos in dk["positions"]:
            self.assertIsNotNone(find_trade_by_position(self.store, owner_type="trader", owner_id="dollar-king", position_id=pos["position_id"]))
        self.assertTrue((run_dir / "paper_books.json").is_file())

        positions = dk["positions"]
        cad = next(p for p in positions if p["instrument"] == "USDCAD")
        self.hashes["dollar-king"] = build_memory_context(self.store, "trader", "dollar-king")["memory_context_sha256"]
        originals["dollar-king"] = {
            "agent": "dollar-king",
            "trade": originals["dollar-king"]["trade"],
            "confidence": 55,
            "conflict_synopsis": originals["dollar-king"]["conflict_synopsis"],
            "paper_actions": [
                {
                    "action": "ADD",
                    "position_id": cad["position_id"],
                    "notional_usd": 1_000_000,
                    "expression_memo": _spot_memo("USDCAD"),
                    "thesis": "Add.",
                }
            ],
        }
        persist_ondemand_trader_books(
            root=self.root,
            run_dir=run_dir,
            packet={**packet, "run_id": "tr-persist-2"},
            originals=originals,
            rebuttals=rebuttals,
            memory_hashes=self.hashes,
            when=AS_OF,
        )
        books2 = json.loads(overnight.books_path().read_text(encoding="utf-8"))
        cad2 = next(p for p in books2["seats"]["dollar-king"]["positions"] if p["instrument"] == "USDCAD")
        self.assertEqual(cad2["notional_usd"], 26_000_000)

    def test_emit_includes_multi_position_from_canonical(self) -> None:
        books = self._apply_multi_open(empty_books(overnight_run_id="tr-emit", when=AS_OF), "tr-emit")
        overnight = OvernightStore(root=self.root, state_root=self.root)
        overnight.write_books(books)
        site = self.root / "site"
        emit_trader_books_json(overnight, site)
        payload = json.loads((site / "trader-books.json").read_text(encoding="utf-8"))
        dk = next(row for row in payload["seats"] if row["seat"] == "dollar-king")
        self.assertEqual(len(dk["positions"]), 2)


if __name__ == "__main__":
    unittest.main()
