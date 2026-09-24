#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.overnight.books import empty_books, mark_to_market, public_books_view, validate_books
from scripts.pm.books import mark_pm_book, validate_books as validate_pm_books
from scripts.overnight.constants import MAX_DRAWDOWN_USD, STANDING_SEATS
from scripts.overnight.store import OvernightStore, write_json
from scripts.pm.books import empty_books as empty_pm_books
from scripts.pm.constants import PM_IDS
from scripts.pm.store import PMStore
from scripts.trader_room.paper_book import reviews_from_run
from scripts.trading.apply import apply_trader_review_with_memory
from scripts.trading.capital_owner import build_capital_owner
from scripts.trading.consequence import assert_trader_consequence_clean, build_pm_consequence, build_trader_consequence
from scripts.trading.constants import MATERIAL_DRAWDOWN_FRACTION, MEMORY_SCHEMA_VERSION
from scripts.trading.errors import LearningGateError, SchemaError
from scripts.trading.gate import evaluate_decision_actions
from scripts.trading.memory import accept_performance_reflection, accept_postmortem, build_memory_context
from scripts.trading.store import TradingStore

NY = ZoneInfo("America/New_York")
AS_OF = datetime(2026, 9, 19, 12, 0, tzinfo=NY)
MARKET = {
    "generated_at": "2026-09-19T12:00:00Z",
    "fx": {"pairs": {"USDCAD": {"spot": 1.36}}},
}


def _spot_memo() -> dict:
    return {
        "rates_candidate": None,
        "spot_candidate": {"instrument": "USDCAD", "asset_class": "spot_fx", "rationale": "spot"},
        "options_candidate": None,
        "selected": "spot",
        "rationale": "Dedicated USD spot seat.",
    }


def _fresh_families() -> dict:
    return {
        "macro_hard": {"status": "fresh", "as_of": "2026-09-19T00:07:00-04:00", "digest": "m"},
        "news": {"status": "fresh", "as_of": "2026-09-19T00:07:00-04:00", "digest": "n"},
        "central_bank_research": {"status": "fresh", "as_of": "2026-09-19T00:07:00-04:00", "digest": "c"},
        "market_state": {"status": "fresh", "as_of": "2026-09-19T00:07:00-04:00", "digest": "s", "data": MARKET},
    }


class TraderPsychologyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = TradingStore(root=self.root, state_root=self.root)
        self.store.ensure_initialized()
        self.overnight = OvernightStore(root=self.root, state_root=self.root)
        self.pm_store = PMStore(root=self.root, state_root=self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_trader_books(self, books: dict) -> None:
        for seat in STANDING_SEATS:
            mark_to_market(books["seats"][seat], when=AS_OF)
        self.overnight.write_books(validate_books(books))

    def _write_pm_books(self, books: dict) -> None:
        for pm_id in PM_IDS:
            mark_pm_book(books["pms"][pm_id], when=AS_OF)
        self.pm_store.write_books(validate_pm_books(books))

    def _memory_hashes(self) -> dict[str, str]:
        from scripts.trading.constants import ALL_IDENTITIES

        return {
            owner_id: build_memory_context(self.store, owner_type, owner_id)["memory_context_sha256"]
            for owner_type, owner_id in ALL_IDENTITIES
        }

    def test_trader_consequence_own_book_only(self) -> None:
        books = empty_books(overnight_run_id="overnight-20260919", when=AS_OF)
        books["seats"]["dollar-king"]["realized_pnl_usd"] = 1_500_000.0
        books["seats"]["perma-bull"]["realized_pnl_usd"] = 5_000_000.0
        self._write_trader_books(books)
        consequence = build_trader_consequence(self.store, "dollar-king")
        self.assertEqual(consequence["status"], "ok")
        self.assertEqual(consequence["net_pnl_usd"], 1_500_000.0)
        self.assertIn("competition_rank", consequence)
        self.assertNotIn("spread_to_leader", consequence)
        assert_trader_consequence_clean(consequence)
        dumped = json.dumps(consequence)
        self.assertNotIn("perma-bull", dumped)
        self.assertNotIn("5_000_000", dumped.replace("5000000", ""))

    def test_pm_consequence_spreads_and_best_trader(self) -> None:
        trader_books = empty_books(overnight_run_id="overnight-20260919", when=AS_OF)
        trader_books["seats"]["dollar-king"]["realized_pnl_usd"] = 8_000_000.0
        self._write_trader_books(trader_books)
        pm_books = empty_pm_books()
        pm_books["pms"]["swinger"]["realized_pnl_usd"] = 1_000_000.0
        pm_books["pms"]["pragmatist"]["realized_pnl_usd"] = 5_000_000.0
        self._write_pm_books(pm_books)
        consequence = build_pm_consequence(self.store, "swinger")
        self.assertFalse(consequence["capital_normalized"])
        self.assertEqual(consequence["spread_to_leader_pm_usd"], -4_000_000.0)
        self.assertEqual(consequence["best_trader_seat"], "dollar-king")
        self.assertEqual(consequence["gap_to_best_trader_usd"], -7_000_000.0)

    def test_swinger_drawdown_alone_not_punished(self) -> None:
        pm_books = empty_pm_books()
        pm_books["pms"]["swinger"]["drawdown_usd"] = 30_000_000.0
        pm_books["pms"]["swinger"]["net_after_funding_pnl_usd"] = 25_000_000.0
        consequence = {
            "status": "ok",
            "drawdown_usd": 30_000_000.0,
            "net_after_funding_pnl_usd": 25_000_000.0,
            "high_water_nav_usd": 1_030_000_000.0,
        }
        owner = build_capital_owner(
            self.store,
            "swinger",
            consequence=consequence,
            pm_book=pm_books["pms"]["swinger"],
        )
        self.assertEqual(owner["standing"], "good_standing")
        self.assertTrue(all("suck" not in note.lower() for note in owner.get("notes") or []))

    def test_swinger_uncompensated_pain_raises_pressure(self) -> None:
        pm_books = empty_pm_books()
        pm_books["pms"]["swinger"]["drawdown_usd"] = 30_000_000.0
        pm_books["pms"]["swinger"]["net_after_funding_pnl_usd"] = -1_000_000.0
        consequence = {
            "status": "ok",
            "drawdown_usd": 30_000_000.0,
            "net_after_funding_pnl_usd": -1_000_000.0,
            "high_water_nav_usd": 1_000_000_000.0,
        }
        owner = build_capital_owner(
            self.store,
            "swinger",
            consequence=consequence,
            pm_book=pm_books["pms"]["swinger"],
        )
        self.assertIn(owner["standing"], ("watch", "probation"))
        self.assertTrue(any("suck" in note.lower() for note in owner.get("notes") or []))

    def test_grinder_zero_alpha_not_forced(self) -> None:
        consequence = {"status": "ok", "net_after_funding_pnl_usd": 0.0, "max_drawdown_usd": 50_000_000.0}
        owner = build_capital_owner(self.store, "grinder", consequence=consequence, pm_book={"max_drawdown_usd": 50_000_000.0})
        self.assertTrue(owner["zero_alpha"])
        self.assertFalse(owner["persistent_zero_alpha"])
        self.assertFalse(owner["force_deployment"])

    def test_pragmatist_mandate_text_and_unavailable_spx(self) -> None:
        consequence = {"status": "ok", "net_after_funding_pnl_usd": 0.0}
        owner = build_capital_owner(self.store, "pragmatist", consequence=consequence, market_state=MARKET)
        joined = " ".join(owner.get("notes") or [])
        self.assertIn("2–6%", joined)
        self.assertIn("20", joined)
        self.assertEqual(owner["spx_context"]["status"], "unavailable")

    def test_material_drawdown_threshold_two_million(self) -> None:
        threshold = MATERIAL_DRAWDOWN_FRACTION * MAX_DRAWDOWN_USD
        self.assertEqual(threshold, 2_000_000.0)

    def test_reflection_due_blocks_expansion_not_hold(self) -> None:
        books = empty_books(overnight_run_id="overnight-20260919", when=AS_OF)
        books["seats"]["dollar-king"]["realized_pnl_usd"] = -2_100_000.0
        self._write_trader_books(books)
        context = build_memory_context(self.store, "trader", "dollar-king")
        self.assertTrue(context["reflections_due"])
        decision = {
            "memory_context_sha256": context["memory_context_sha256"],
            "actions": [{"action": "OPEN", "instrument": "USDCAD", "side": "long", "rationale": "test"}],
        }
        _, blocked = evaluate_decision_actions(
            self.store,
            owner_type="trader",
            owner_id="dollar-king",
            decision=decision,
            run_id="overnight-20260920",
            expected_memory_sha256=context["memory_context_sha256"],
        )
        self.assertTrue(blocked)
        hold = {
            "memory_context_sha256": context["memory_context_sha256"],
            "actions": [{"action": "HOLD"}],
        }
        allowed, blocked_hold = evaluate_decision_actions(
            self.store,
            owner_type="trader",
            owner_id="dollar-king",
            decision=hold,
            run_id="overnight-20260920",
            expected_memory_sha256=context["memory_context_sha256"],
        )
        self.assertEqual(allowed, [{"action": "HOLD"}])
        self.assertFalse(blocked_hold)

    def test_ack_only_postmortem_rejected(self) -> None:
        due = self.store.read_postmortems_due("trader", "dollar-king")
        due["items"] = [
            {
                "postmortem_id": "pmd-test",
                "trade_id": "trd-test",
                "status": "due",
            }
        ]
        self.store.write_postmortems_due("trader", "dollar-king", due)
        self.store.write_trade(
            {
                "trade_id": "trd-test",
                "owner_type": "trader",
                "owner_id": "dollar-king",
                "status": "closed",
            }
        )
        with self.assertRaises(SchemaError):
            accept_postmortem(
                self.store,
                {"trade_id": "trd-test", "lesson": "ack only"},
                owner_type="trader",
                owner_id="dollar-king",
                run_id="overnight-20260920",
            )
        self.assertEqual(self.store.read_postmortems_due("trader", "dollar-king")["items"][0]["status"], "due")

    def test_reviews_from_run_preserves_learning_fields(self) -> None:
        originals = {
            seat: {
                "agent": seat,
                "confidence": 50,
                "trade": {"thesis": "t"},
                "paper_actions": [{"action": "HOLD"}],
                "postmortems": [{"trade_id": "trd-x", "what_worked": "a"}],
                "performance_reflections": [{"what_happened_vs_expected": "x"}],
            }
            for seat in STANDING_SEATS
        }
        reviews = reviews_from_run(originals, {}, {}, {"run_id": "tr-1", "packet_sha256": "x"})
        self.assertIn("postmortems", reviews["dollar-king"])
        self.assertIn("performance_reflections", reviews["dollar-king"])

    def test_public_projection_strips_taunt(self) -> None:
        books = empty_books(overnight_run_id="overnight-20260919", when=AS_OF)
        books["seats"]["dollar-king"]["thesis"] = (
            "I love risk. I'm starting to think you just suck at taking it. Oil is bid."
        )
        view = public_books_view(books)
        thesis = view["seats"][0]["thesis"] if view["seats"][0]["seat"] != "dollar-king" else next(
            row["thesis"] for row in view["seats"] if row["seat"] == "dollar-king"
        )
        self.assertNotIn("suck", thesis.lower())
        dumped = json.dumps(view)
        self.assertNotIn("capital_owner", dumped)
        self.assertNotIn("performance_reflection", dumped)

    def test_memory_schema_version_two(self) -> None:
        context = build_memory_context(self.store, "trader", "dollar-king")
        self.assertEqual(context["schema_version"], MEMORY_SCHEMA_VERSION)
        self.assertIn("consequence", context)

    def _open_and_close_trader(self) -> tuple[dict, str]:
        hashes = self._memory_hashes()
        books = empty_books(overnight_run_id="overnight-20260919", when=AS_OF)
        reviews = {
            seat: {
                "seat": seat,
                "memory_context_sha256": hashes[seat],
                "expression_memo": _spot_memo(),
                "actions": [{"action": "HOLD"}],
            }
            for seat in STANDING_SEATS
        }
        reviews["dollar-king"] = {
            "seat": "dollar-king",
            "memory_context_sha256": hashes["dollar-king"],
            "expression_memo": _spot_memo(),
            "actions": [
                {
                    "action": "OPEN",
                    "instrument": "USDCAD",
                    "side": "long",
                    "notional_usd": 5_000_000,
                    "price": 1.36,
                    "asset_class": "spot_fx",
                    "rationale": "Open.",
                }
            ],
        }
        books = apply_trader_review_with_memory(
            books,
            reviews,
            families=_fresh_families(),
            run_id="overnight-20260919",
            evidence_cutoff="c",
            store=self.store,
            memory_hashes=hashes,
            when=AS_OF,
            market_state=MARKET,
        )
        pos_id = books["seats"]["dollar-king"]["positions"][0]["position_id"]
        close_reviews = deepcopy(reviews)
        hashes["dollar-king"] = build_memory_context(self.store, "trader", "dollar-king")["memory_context_sha256"]
        close_reviews["dollar-king"] = {
            "seat": "dollar-king",
            "memory_context_sha256": hashes["dollar-king"],
            "actions": [
                {"action": "CLOSE", "position_id": pos_id, "price": 1.36, "rationale": "Done."},
                {
                    "action": "OPEN",
                    "instrument": "USDCAD",
                    "side": "long",
                    "notional_usd": 1_000_000,
                    "price": 1.36,
                    "asset_class": "spot_fx",
                    "expression_memo": _spot_memo(),
                    "thesis": "Re-open.",
                    "rationale": "Re-open.",
                },
            ],
        }
        books = apply_trader_review_with_memory(
            books,
            close_reviews,
            families=_fresh_families(),
            run_id="overnight-20260919",
            evidence_cutoff="c",
            store=self.store,
            memory_hashes=hashes,
            when=AS_OF,
            market_state=MARKET,
        )
        return books, pos_id

    def test_same_run_close_does_not_block_sibling_open(self) -> None:
        books, _ = self._open_and_close_trader()
        self.assertEqual(len(books["seats"]["dollar-king"]["positions"]), 1)

    def test_reflection_no_new_lesson_clears_gate(self) -> None:
        books = empty_books(overnight_run_id="overnight-20260919", when=AS_OF)
        books["seats"]["dollar-king"]["realized_pnl_usd"] = -2_100_000.0
        self._write_trader_books(books)
        context = build_memory_context(self.store, "trader", "dollar-king")
        due_id = context["reflections_due"][0]["reflection_due_id"]
        accept_performance_reflection(
            self.store,
            {
                "reflection_due_id": due_id,
                "what_happened_vs_expected": "Drawdown matched risk budget use.",
                "attribution": ["sizing"],
                "pressure_effect": "none",
                "skill_vs_luck": "mixed",
                "overconfidence_risk": "no",
                "chase_or_revenge": "no",
                "no_new_lesson": "Sizing was intentional for the catalyst window.",
            },
            owner_type="trader",
            owner_id="dollar-king",
            run_id="overnight-20260920",
        )
        refreshed = build_memory_context(self.store, "trader", "dollar-king")
        self.assertEqual(refreshed["reflections_due"], [])
        decision = {
            "memory_context_sha256": refreshed["memory_context_sha256"],
            "actions": [{"action": "OPEN", "instrument": "USDCAD", "side": "long", "rationale": "ok"}],
        }
        allowed, blocked = evaluate_decision_actions(
            self.store,
            owner_type="trader",
            owner_id="dollar-king",
            decision=decision,
            run_id="overnight-20260921",
            expected_memory_sha256=refreshed["memory_context_sha256"],
        )
        self.assertFalse(blocked)
        self.assertTrue(allowed)

    def test_reflection_lesson_stays_on_own_identity(self) -> None:
        books = empty_books(overnight_run_id="overnight-20260919", when=AS_OF)
        books["seats"]["dollar-king"]["realized_pnl_usd"] = -2_100_000.0
        self._write_trader_books(books)
        context = build_memory_context(self.store, "trader", "dollar-king")
        due_id = context["reflections_due"][0]["reflection_due_id"]
        accept_performance_reflection(
            self.store,
            {
                "reflection_due_id": due_id,
                "what_happened_vs_expected": "Lost on timing.",
                "attribution": ["timing"],
                "pressure_effect": "distorting",
                "skill_vs_luck": "luck",
                "overconfidence_risk": "yes",
                "chase_or_revenge": "no",
                "lesson": "Wait for confirmation after drawdown.",
            },
            owner_type="trader",
            owner_id="dollar-king",
            run_id="overnight-20260920",
        )
        king = build_memory_context(self.store, "trader", "dollar-king")
        bear = build_memory_context(self.store, "trader", "perma-bear")
        self.assertTrue(king["active_lessons"])
        self.assertFalse(bear["active_lessons"])


if __name__ == "__main__":
    unittest.main()
