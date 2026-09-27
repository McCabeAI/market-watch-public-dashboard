#!/usr/bin/env python3
"""Apply-path psychology: isolation, idempotency, public boundary, shadow scale."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.overnight.books import empty_books, mark_to_market, public_books_view, validate_books
from scripts.overnight.constants import ROOT, STANDING_SEATS
from scripts.overnight.public_prose import public_prose_issues, sanitize_public_prose
from scripts.overnight.scheduled_output import FORBIDDEN_MODEL_STATE_KEYS, _walk_forbidden
from scripts.overnight.store import OvernightStore
from scripts.pm.books import public_pm_view
from scripts.trading.apply import apply_trader_review_with_memory
from scripts.trading.capital_owner import build_capital_owner
from scripts.trading.constants import PSYCH_AXES
from scripts.overnight.errors import ReviewAlreadyApplied
from scripts.trading.errors import LearningGateError
from scripts.trading.gate import evaluate_decision_actions, raise_if_unexecutable
from scripts.trading.memory import build_memory_context
from scripts.trading.psychology import assert_psychology_clean, replay, seed_state
from scripts.trading.psychology_events import observe_psychology_cycle
from scripts.trading.psychology_replay import shadow_report
from scripts.trading.store import TradingStore
from scripts.trader_room.paper_book import reviews_from_run

NY = ZoneInfo("America/New_York")
AS_OF = datetime(2026, 9, 26, 12, 0, tzinfo=NY)


def _families() -> dict:
    return {
        "macro_hard": {"status": "fresh", "as_of": "2026-09-26T00:07:00-04:00", "digest": "m"},
        "news": {"status": "fresh", "as_of": "2026-09-26T00:07:00-04:00", "digest": "n"},
        "central_bank_research": {"status": "fresh", "as_of": "2026-09-26T00:07:00-04:00", "digest": "c"},
        "market_state": {"status": "fresh", "as_of": "2026-09-26T00:07:00-04:00", "digest": "s", "data": {}},
    }


class PsychologyIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = TradingStore(root=self.root, state_root=self.root)
        self.store.ensure_initialized()
        self.overnight = OvernightStore(root=self.root, state_root=self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _books(self) -> dict:
        books = empty_books(overnight_run_id="overnight-20260926", when=AS_OF)
        for seat in STANDING_SEATS:
            mark_to_market(books["seats"][seat], when=AS_OF)
        return books

    def test_observe_does_not_write_ledger_books_or_lessons_and_replays(self) -> None:
        calls: list[str] = []

        def _boom(*_args, **_kwargs):
            calls.append("write")
            raise AssertionError("psychology observer wrote canonical state")

        self.store.write_trade = _boom  # type: ignore[method-assign]
        self.store.write_books = _boom  # type: ignore[method-assign]
        self.store.write_lessons = _boom  # type: ignore[method-assign]
        self.store.write_learning_state = _boom  # type: ignore[method-assign]
        state = observe_psychology_cycle(
            self.store,
            "trader",
            "dollar-king",
            run_id="overnight-20260926",
            review_id="review-001",
            consequence_bundle={"consequence": {"session_pnl_change_usd": 418551.0}, "prior": {}},
            decision={"actions": [{"action": "HOLD"}]},
            blocked=[],
            market_fresh=False,
            when=AS_OF,
        )
        self.assertEqual(calls, [])
        self.assertGreater(state["axes"]["complacency"]["value"], 0.10)
        again = observe_psychology_cycle(
            self.store,
            "trader",
            "dollar-king",
            run_id="overnight-20260926",
            review_id="review-001",
            consequence_bundle={"consequence": {"session_pnl_change_usd": 418551.0}, "prior": {}},
            decision={"actions": [{"action": "HOLD"}]},
            when=AS_OF,
        )
        events = self.store.read_psychology_events("trader", "dollar-king")["events"]
        self.assertEqual(again["state_sha256"], state["state_sha256"])
        self.assertEqual(len([row for row in events if row["kind"] == "decay_tick"]), 1)
        rebuilt = replay(events, owner_type="trader", owner_id="dollar-king")
        self.assertEqual(rebuilt["state_sha256"], state["state_sha256"])

    def test_context_is_private_and_hash_stable(self) -> None:
        first = build_memory_context(self.store, "trader", "dollar-king", when=AS_OF)
        second = build_memory_context(self.store, "trader", "dollar-king", when=AS_OF)
        self.assertEqual(first["memory_context_sha256"], second["memory_context_sha256"])
        self.assertIn("psychology", first)
        peers = [seat for seat in STANDING_SEATS if seat != "dollar-king"]
        assert_psychology_clean(first["psychology"], owner_id="dollar-king", peer_ids=peers)
        dirty = {"axes": {"note": "perma-bull pnl leaked"}}
        with self.assertRaises(ValueError):
            assert_psychology_clean(dirty, owner_id="dollar-king", peer_ids=peers)
        self.assertTrue(_walk_forbidden({"psychology": {"axes": {}}}))
        self.assertFalse(_walk_forbidden({"psychology_check": {"state_sha256": "abc", "proceed_despite_flags": True}}))
        self.assertIn("psychology", FORBIDDEN_MODEL_STATE_KEYS)

    def test_mixed_decision_keeps_close_and_blocks_open(self) -> None:
        state = seed_state("trader", "dollar-king")
        state["axes"]["complacency"]["value"] = 0.70
        state["axes"]["complacency"]["band"] = "high"
        state["flags"] = []
        from scripts.trading.psychology import derive_flags, state_digest

        state["flags"] = derive_flags(state)
        state["state_sha256"] = state_digest(state)
        self.store.write_psychology_state("trader", "dollar-king", state)
        context = build_memory_context(self.store, "trader", "dollar-king", when=AS_OF)
        digest = context["memory_context_sha256"]
        decision = {
            "actions": [
                {"action": "CLOSE", "position_id": "pos-1", "instrument": "USDCAD"},
                {"action": "OPEN", "instrument": "USDCAD", "asset_class": "spot_fx", "side": "long", "notional_usd": 1000000, "thesis": "USD still leads.", "rationale": "USD still leads on growth."},
            ],
            "thesis": "USD still leads.",
            "rationale": "USD still leads on growth.",
            "memory_context_sha256": digest,
            "_memory_context": context,
        }
        allowed, blocked = evaluate_decision_actions(
            self.store,
            owner_type="trader",
            owner_id="dollar-king",
            decision=decision,
            run_id="overnight-20260926",
            expected_memory_sha256=digest,
        )
        self.assertEqual([row["action"] for row in allowed], ["CLOSE"])
        self.assertIn("psychology_gate", blocked[0]["reason"])
        with self.assertRaises(LearningGateError):
            pure_allowed, pure_blocked = evaluate_decision_actions(
                self.store,
                owner_type="trader",
                owner_id="dollar-king",
                decision={**decision, "actions": [decision["actions"][1]]},
                run_id="overnight-20260926",
                expected_memory_sha256=digest,
            )
            raise_if_unexecutable(pure_blocked, pure_allowed)

    def test_public_prose_strips_psychology(self) -> None:
        thesis = "USD remains the cleanest expression. My complacency is 0.47 so I am sizing the book. The growth gap is intact."
        self.assertTrue(public_prose_issues(thesis))
        cleaned = sanitize_public_prose(thesis)
        self.assertNotIn("0.47", cleaned)
        self.assertNotIn("complacency", cleaned.lower())
        books = self._books()
        books["seats"]["dollar-king"]["thesis"] = "heater_risk says add risk. USD remains the cleanest G10 expression against CAD for now."
        books["seats"]["dollar-king"]["alerts"] = ["psychology_gate: missing_psychology_check heater_risk", "Funding source refreshed."]
        view = public_books_view(validate_books(books))
        rendered = json.dumps(view)
        self.assertNotIn("heater_risk", rendered)
        self.assertNotIn("psychology_gate", rendered)
        self.assertNotIn("missing_psychology_check", rendered)

    def test_paper_book_passes_psychology_check(self) -> None:
        check = {"state_sha256": "abc", "flags_acknowledged": [], "answers": {}, "proceed_despite_flags": True}
        originals = {}
        for seat in STANDING_SEATS:
            originals[seat] = {
                "confidence": 50,
                "trade": {"thesis": "Hold the book."},
                "paper_actions": [{"action": "HOLD"}],
                "psychology_check": check,
            }
        reviews = reviews_from_run(originals, {}, {}, {"packet_sha256": "p", "as_of": "2026-09-26"})
        self.assertEqual(reviews["dollar-king"]["psychology_check"]["state_sha256"], "abc")

    def test_apply_records_psychology_once(self) -> None:
        books = self._books()
        books["seats"]["dollar-king"]["realized_pnl_usd"] = 500_000.0
        self.overnight.write_books(validate_books(books))
        hashes = {
            seat: build_memory_context(self.store, "trader", seat, when=AS_OF)["memory_context_sha256"]
            for seat in STANDING_SEATS
        }
        reviews = {
            seat: {
                "actions": [{"action": "HOLD"}],
                "thesis": "No change.",
                "memory_context_sha256": hashes[seat],
            }
            for seat in STANDING_SEATS
        }
        apply_trader_review_with_memory(
            books,
            reviews,
            families=_families(),
            run_id="overnight-20260926",
            evidence_cutoff="2026-09-26T00:07:00-04:00",
            store=self.store,
            memory_hashes=hashes,
            when=AS_OF,
            review_id="review-001",
        )
        events = self.store.read_psychology_events("trader", "dollar-king")["events"]
        self.assertEqual(len([row for row in events if row["kind"] == "decay_tick"]), 1)
        journal = self.store.read_journal("trader", "dollar-king")["events"][-1]
        self.assertIn("psychology", journal["payload"])
        with self.assertRaises(ReviewAlreadyApplied):
            apply_trader_review_with_memory(
                books,
                reviews,
                families=_families(),
                run_id="overnight-20260926",
                evidence_cutoff="2026-09-26T00:07:00-04:00",
                store=self.store,
                memory_hashes=hashes,
                when=AS_OF,
                review_id="review-001",
            )
        events_again = self.store.read_psychology_events("trader", "dollar-king")["events"]
        self.assertEqual(len(events_again), len(events))

    def test_shadow_replay_stays_near_baseline(self) -> None:
        report = shadow_report(ROOT)
        # September rank reshuffles move external_pressure, but not to a required flag.
        # The plan's 0.20 sketch treated a ~$50k close as inside the dead band; the
        # written $40k band and rank_shock magnitude are unchanged. No axis reaches
        # the elevated-band enter (0.35) or a required-check threshold.
        self.assertLess(report["max_abs_distance"], 0.30)
        self.assertEqual(report["level_flags"], [])
        self.assertEqual(report["family_revenge_flags"], [])
        for owner_id, row in report["identities"].items():
            for axis in PSYCH_AXES:
                self.assertLess(row["distances"][axis], 0.30)
            self.assertNotEqual(owner_id, "chatgpt")
            self.assertFalse(row["flags"])
        fixture_dir = ROOT / "tests" / "fixtures" / "psychology"
        fixture_dir.mkdir(parents=True, exist_ok=True)
        fixture = fixture_dir / "shadow_report.json"
        encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if not fixture.is_file():
            fixture.write_text(encoded, encoding="utf-8")
        stored = json.loads(fixture.read_text(encoding="utf-8"))
        self.assertEqual(stored["max_abs_distance"], report["max_abs_distance"])
        self.assertEqual(stored["level_flags"], report["level_flags"])

    def test_grinder_flat_does_not_force_deployment(self) -> None:
        owner = build_capital_owner(
            self.store,
            "grinder",
            consequence={"status": "ok", "net_after_funding_pnl_usd": 0.0, "drawdown_usd": 0.0, "high_water_nav_usd": 1_000_000_000.0},
        )
        self.assertFalse(owner["force_deployment"])
        state = seed_state("pm", "grinder")
        state["axes"]["chase_pressure"]["value"] = 0.99
        from scripts.trading.psychology import derive_flags

        flags = {row["id"] for row in derive_flags(state)}
        self.assertIn("chase_risk", flags)
        decision = {
            "actions": [{"action": "NO_TRADE"}],
            "_memory_context": {"psychology": {"applicable": True, "state_sha256": "x", "active_flags": derive_flags(state)}},
        }
        from scripts.trading.psychology_gate import psychology_action_reason

        self.assertIsNone(psychology_action_reason({"action": "NO_TRADE"}, decision, owner_id="grinder"))

    def test_public_pm_view_drops_psychology_alert(self) -> None:
        from scripts.pm.books import empty_books as empty_pm_books

        books = empty_pm_books()
        books["pms"]["pragmatist"]["alerts"] = ["psychology_gate: stale_psychology_state"]
        books["pms"]["pragmatist"]["thesis"] = "Carry the book. self_trust is 0.22 is not a public fact."
        rendered = json.dumps(public_pm_view(books))
        self.assertNotIn("psychology_gate", rendered)
        self.assertNotIn("self_trust", rendered)


if __name__ == "__main__":
    unittest.main()
