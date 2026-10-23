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
from scripts.overnight.constants import MAX_DRAWDOWN_USD, ROOT, STANDING_SEATS
from scripts.overnight.public_prose import public_prose_issues, sanitize_public_prose
from scripts.overnight.scheduled_output import FORBIDDEN_MODEL_STATE_KEYS, _walk_forbidden
from scripts.overnight.store import OvernightStore
from scripts.pm.books import public_pm_view
from scripts.pm.constants import MAX_DRAWDOWN_USD as PM_MAX_DRAWDOWN_USD
from scripts.trading.apply import apply_trader_review_with_memory
from scripts.trading.capital_owner import build_capital_owner
from scripts.trading.constants import (
    ALL_IDENTITIES,
    MATERIAL_DRAWDOWN_FRACTION,
    PSYCH_AXES,
    PSYCH_DEAD_BAND_FRACTION,
    PSYCH_FLAG_IDS,
    PSYCH_UNIT_FRACTION,
)
from scripts.overnight.errors import ReviewAlreadyApplied
from scripts.trading.errors import LearningGateError
from scripts.trading.gate import evaluate_decision_actions, raise_if_unexecutable
from scripts.trading.memory import build_memory_context
from scripts.trading.psychology import assert_psychology_clean, fold_cycle, replay, seed_state
from scripts.trading.psychology_events import detect_cycle_events, observe_psychology_cycle, revenge_family
from scripts.trading.psychology_profiles import is_not_applicable
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


# Same-family revenge tags last three folded cycles, including the cycle that plants them.
_FAMILY_REVENGE_TTL = 3
_TRADER_DEAD_BAND_USD = PSYCH_DEAD_BAND_FRACTION * MATERIAL_DRAWDOWN_FRACTION * MAX_DRAWDOWN_USD
_TRADER_UNIT_USD = PSYCH_UNIT_FRACTION * MATERIAL_DRAWDOWN_FRACTION * MAX_DRAWDOWN_USD


def _book_seats(books: dict | None, key: str) -> dict:
    if not isinstance(books, dict):
        return {}
    rows = books.get(key) or {}
    return rows if isinstance(rows, dict) else {}


def _dead_band_usd(owner_type: str) -> float:
    max_drawdown = MAX_DRAWDOWN_USD if owner_type == "trader" else PM_MAX_DRAWDOWN_USD
    return PSYCH_DEAD_BAND_FRACTION * MATERIAL_DRAWDOWN_FRACTION * float(max_drawdown)


def _close_row(trade: dict) -> dict:
    for event in reversed(trade.get("events") or []):
        if isinstance(event, dict) and event.get("kind") == "CLOSE":
            return event
    return {}


def _scoped_family_revenge_flags(root: Path) -> list[str]:
    """Family revenge flags justified by the written tag contract.

    A tag is planted when that owner's own closed trade on a folded run is
    outside the dead band and is a loss or a risk-cut. Shadow replay does not
    pass forced-flat alerts, so a risk-cut inside the band does not count.
    The tag lasts three folded cycles and decrements only on cycles where that
    identity is actually folded. This is independent of ``shadow_report``'s
    flag assembly so a phantom or dropped flag cannot hide inside it.
    """
    trades: list[dict] = []
    trades_dir = root / "data" / "trading" / "trades"
    if trades_dir.is_dir():
        for path in sorted(trades_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                trades.append(payload)
    identities = [
        (owner_type, owner_id)
        for owner_type, owner_id in ALL_IDENTITIES
        if not is_not_applicable(owner_id)
    ]
    active: dict[str, dict[str, int]] = {owner_id: {} for _owner_type, owner_id in identities}
    runs_root = root / "data" / "overnight" / "runs"
    run_names = sorted(path.name for path in runs_root.iterdir() if path.is_dir()) if runs_root.is_dir() else []
    for run_name in run_names:
        review_dirs = sorted((runs_root / run_name / "reviews").glob("review-*"))
        if not review_dirs:
            continue
        review_dir = review_dirs[-1]
        review_path = review_dir / "trader_review.json"
        if not review_path.is_file():
            continue
        review = json.loads(review_path.read_text(encoding="utf-8"))
        snapshot_path = review_dir / "evidence_snapshot.json"
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8")) if snapshot_path.is_file() else {}
        current_traders = _book_seats(review.get("books"), "seats")
        prior_traders = _book_seats(snapshot.get("prior_books"), "seats")
        current_pms = _book_seats(review.get("pm_books"), "pms")
        prior_pms = _book_seats(snapshot.get("prior_pm_books"), "pms")
        for owner_type, owner_id in identities:
            current = (current_traders if owner_type == "trader" else current_pms).get(owner_id) or {}
            prior = (prior_traders if owner_type == "trader" else prior_pms).get(owner_id) or {}
            if not current or not prior:
                continue
            dead = _dead_band_usd(owner_type)
            refreshed: set[str] = set()
            for trade in trades:
                if trade.get("owner_id") != owner_id or trade.get("status") != "closed":
                    continue
                if trade.get("closed_run_id") != run_name:
                    continue
                realized = float(trade.get("realized_pnl_usd") or 0.0)
                if abs(realized) < dead:
                    continue
                category = _close_row(trade).get("exit_reason_category") or trade.get("exit_reason_category")
                if category != "risk_cut" and realized >= 0:
                    continue
                refreshed.add(
                    revenge_family(
                        trade.get("instrument"),
                        trade.get("asset_class"),
                        trade.get("paper_expression"),
                    )
                )
            tags = active[owner_id]
            for family in refreshed:
                tags[family] = _FAMILY_REVENGE_TTL
            for family in list(tags):
                if family in refreshed:
                    continue
                remaining = int(tags[family]) - 1
                if remaining > 0:
                    tags[family] = remaining
                else:
                    del tags[family]
    flags: list[str] = []
    for _owner_type, owner_id in identities:
        families = sorted(active[owner_id])
        if families:
            flags.append(f"{owner_id}:{','.join(families)}")
    return flags


def _book_row(pnl: float) -> dict:
    return {
        "net_pnl_usd": pnl,
        "high_water_nav_usd": 100_000_000.0,
        "drawdown_usd": 0.0,
        "positions": [],
    }


def _write_shadow_root(root: Path, runs: list[tuple[str, dict[str, float]]], trades: list[dict]) -> None:
    for trade in trades:
        path = root / "data" / "trading" / "trades" / f"{trade['trade_id']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(trade), encoding="utf-8")
    for run_id, seats in runs:
        review_dir = root / "data" / "overnight" / "runs" / run_id / "reviews" / "review-001"
        review_dir.mkdir(parents=True, exist_ok=True)
        current = {owner_id: _book_row(pnl) for owner_id, pnl in seats.items()}
        prior = {owner_id: _book_row(pnl) for owner_id, pnl in seats.items()}
        (review_dir / "trader_review.json").write_text(
            json.dumps({"review_id": "review-001", "books": {"seats": current}}),
            encoding="utf-8",
        )
        (review_dir / "evidence_snapshot.json").write_text(
            json.dumps(
                {
                    "prior_books": {"seats": prior},
                    "families": {"market_state": {"status": "stale"}},
                }
            ),
            encoding="utf-8",
        )


def _closed_trade(
    *,
    trade_id: str,
    owner_id: str,
    instrument: str,
    asset_class: str,
    realized: float,
    run_id: str,
    status: str = "closed",
    exit_reason: str | None = None,
) -> dict:
    return {
        "trade_id": trade_id,
        "owner_id": owner_id,
        "owner_type": "trader",
        "status": status,
        "instrument": instrument,
        "asset_class": asset_class,
        "paper_expression": None,
        "side": "short",
        "initial_notional_usd": 50_000_000.0,
        "realized_pnl_usd": realized,
        "closed_run_id": run_id,
        "exit_reason_category": exit_reason,
        "events": [
            {"kind": "OPEN", "run_id": "open-run"},
            {
                "kind": "CLOSE",
                "run_id": run_id,
                "exit_reason_category": exit_reason,
                "realized_pnl_increment_usd": realized,
            },
        ],
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
        forged = {
            "actions": [
                {
                    "action": "OPEN",
                    "instrument": "USDCAD",
                    "asset_class": "spot_fx",
                    "side": "long",
                    "notional_usd": 1000000,
                    "thesis": "USD still leads.",
                    "rationale": "USD still leads on growth.",
                }
            ],
            "thesis": "USD still leads.",
            "rationale": "USD still leads on growth.",
            "memory_context_sha256": digest,
            "psychology_check": {"state_sha256": "stale", "flags_acknowledged": [], "answers": {}, "proceed_despite_flags": True},
            "_memory_context": {},
        }
        forged_allowed, forged_blocked = evaluate_decision_actions(
            self.store,
            owner_type="trader",
            owner_id="dollar-king",
            decision=forged,
            run_id="overnight-20260926",
            expected_memory_sha256=digest,
        )
        self.assertEqual(forged_allowed, [])
        self.assertIn("stale_psychology_state", forged_blocked[0]["reason"])
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

    def test_close_journals_optional_capitulation_without_blocking(self) -> None:
        from scripts.trading.psychology import derive_flags, seed_state, state_digest
        from scripts.trading.psychology_gate import psychology_journal_payload

        close_state = seed_state("trader", "dollar-king")
        close_state["axes"]["defensiveness"]["value"] = 0.70
        close_state["axes"]["frustration"]["value"] = 0.50
        close_state["flags"] = derive_flags(close_state)
        close_state["state_sha256"] = state_digest(close_state)
        self.store.write_psychology_state("trader", "dollar-king", close_state)
        de_risk = {"actions": [{"action": "CLOSE", "position_id": "pos-1", "instrument": "USDCAD"}]}
        allowed, blocked = evaluate_decision_actions(
            self.store,
            owner_type="trader",
            owner_id="dollar-king",
            decision=de_risk,
            run_id="overnight-20260926",
            expected_memory_sha256="unused",
        )
        self.assertEqual([row["action"] for row in allowed], ["CLOSE"])
        self.assertEqual(blocked, [])
        payload = psychology_journal_payload(de_risk, blocked)
        self.assertEqual(payload["state_sha256"], close_state["state_sha256"])
        self.assertIn("capitulation_risk", payload["active_flags"])
        self.assertEqual(payload["check_status"], "missing_optional")

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
        for prose in (
            "self_trust=0.91 and the dollar still leads on the growth gap versus the rest of G10.",
            "self trust is 0.91 and the dollar still leads on the growth gap versus the rest of G10.",
            "self_trust=.91 and the dollar still leads on the growth gap versus the rest of G10.",
            "frustration (0.80) does not change the growth gap that still supports the dollar.",
            "complacency was 0.47 and the growth gap still supports the dollar versus the rest of G10.",
            "Heater risk is elevated, but the growth gap remains the reason to hold the dollar.",
            "Heater-risk is elevated, but the growth gap remains the reason to hold the dollar.",
            "Learning Default does not change the growth gap that still supports the dollar.",
            "Learning-Default does not change the growth gap that still supports the dollar.",
            "Lesson matching would hide the same growth gap that still supports the dollar.",
            "Rank distortion would hide the same growth gap that still supports the dollar.",
            "chase pressure is 0.62 and the growth gap still supports the dollar versus the rest of G10.",
            "self_trust is high at 0.91 and the dollar still leads on the growth gap versus the rest of G10.",
            "complacency was about 0.47 and the growth gap still supports the dollar versus the rest of G10.",
            "A self-report is unreliable, but the growth gap still supports the dollar versus the rest of G10.",
            "self_trust sits at 47. The growth gap still supports the dollar versus the rest of G10.",
            "self_trust after one quiet week away still prints 0.91. The growth gap still supports the dollar versus the rest of G10.",
            "Learning\u200b Default does not change the growth gap that still supports the dollar.",
            "heater\u200b_risk says add. The growth gap still supports the dollar versus the rest of G10.",
        ):
            kept_macro = [
                "Frustration in the rates market is evident as 10y yields sit at 4.25 percent.",
                "Vol complacency is the risk here with VIX at 12 and 2s10s at 0.35.",
            ]
            for macro in kept_macro:
                self.assertFalse(public_prose_issues(macro), macro)
                self.assertIn("4.25" if "4.25" in macro else "0.35", sanitize_public_prose(macro))
            self.assertTrue(public_prose_issues(prose), prose)
            cleaned = sanitize_public_prose(prose)
            lowered = cleaned.lower()
            self.assertNotIn("self_trust", lowered)
            self.assertNotIn("self trust", lowered)
            self.assertNotIn("0.91", lowered)
            self.assertNotIn(".91", lowered)
            self.assertNotIn("0.80", lowered)
            self.assertNotIn("0.47", lowered)
            self.assertNotIn("0.62", lowered)
            self.assertNotIn("heater risk", lowered)
            self.assertNotIn("heater-risk", lowered)
            self.assertNotIn("learning default", lowered)
            self.assertNotIn("learning-default", lowered)
            self.assertNotIn("lesson matching", lowered)
            self.assertNotIn("rank distortion", lowered)
            self.assertNotIn("frustration", lowered)
            self.assertNotIn("complacency", lowered)
            self.assertNotIn("chase pressure", lowered)
            self.assertNotIn("self-report", lowered)
            self.assertNotIn("unreliable", lowered)
            self.assertNotIn("sits at 47", lowered)
            self.assertNotIn("prints 0.91", lowered)
            self.assertNotIn("heater_risk", lowered)
        books["seats"]["dollar-king"]["required_pitch"] = {
            "instrument": "USDJPY",
            "note": "self_trust=0.91 would add risk. The growth gap is still the reason to look at the dollar.",
            "Learning Default": "private",
        }
        books["seats"]["dollar-king"]["risk_put_on"] = {
            "instrument": "USDCAD",
            "note": "Learning Default is active. Actual risk stays in the smaller USDCAD long.",
        }
        books["seats"]["dollar-king"]["positions"] = [
            {
                "position_id": "pos-1",
                "instrument": "USDCAD",
                "asset_class": "spot_fx",
                "side": "long",
                "notional_usd": 1_000_000,
                "entry_price": 1.36,
                "mark_price": 1.36,
                "paper_expression": "heater risk says add. Long USDCAD remains the cash expression of the growth gap.",
                "thesis": "The growth gap still supports the dollar.",
                "invalidation": "The growth gap closes.",
            }
        ]
        view = public_books_view(validate_books(books))
        rendered = json.dumps(view)
        self.assertNotIn("self_trust", rendered)
        self.assertNotIn("heater risk", rendered.lower())
        self.assertNotIn("Learning Default", rendered)
        self.assertNotIn("learning_default", rendered)
        from scripts.pm.constants import FORBIDDEN_MODEL_STATE_KEYS as PM_FORBIDDEN
        from scripts.pm.data_requests import public_requests_view
        from scripts.trader_room_public import _trade_row

        self.assertTrue(
            {"psychology", "psychology_state", "psychology_events", "axes", "active_flags"} <= PM_FORBIDDEN
        )
        requests = public_requests_view(
            {
                "requests": [
                    {
                        "request_id": "req-1",
                        "request": "self_trust=0.91 feed for the desk",
                        "reason": "Learning Default needs a private score.",
                        "decision_impact": "heater risk would change the size of the dollar long.",
                        "suggested_source": "Learning Default heater risk self_trust=0.91",
                    }
                ]
            }
        )
        request_blob = json.dumps(requests)
        self.assertNotIn("self_trust", request_blob)
        self.assertNotIn("Learning Default", request_blob)
        self.assertNotIn("heater risk", request_blob.lower())
        row = _trade_row(
            "dollar-king",
            {
                "trade": {
                    "instrument": "USDCAD",
                    "structure": "self_trust=0.91 spot",
                    "direction": "Learning Default long",
                    "expression": "heater risk says add to the dollar.",
                    "horizon": "rank distortion risk into the next print",
                    "entry": "frustration (0.80) at 1.36",
                    "target": "Heater-risk at 1.40 if the growth gap holds through the next data.",
                    "invalidation": "self_trust=0.91 would be the private stop, and the growth gap closing is the real one.",
                }
            },
            None,
        )
        trade_blob = json.dumps(row)
        self.assertEqual(row["trade"]["instrument"], "USDCAD")
        leaked = _trade_row(
            "dollar-king",
            {"trade": {"instrument": "self_trust=0.91", "structure": "spot", "expression": "Long the dollar."}},
            None,
        )
        self.assertNotIn("self_trust", json.dumps(leaked))
        self.assertNotIn("0.91", json.dumps(leaked))
        self.assertNotIn("heater risk", trade_blob.lower())
        self.assertNotIn("heater-risk", trade_blob.lower())
        self.assertNotIn("self_trust", trade_blob)
        self.assertNotIn("0.91", trade_blob)
        self.assertNotIn("0.80", trade_blob)
        self.assertNotIn("Learning Default", trade_blob)
        self.assertNotIn("rank distortion", trade_blob.lower())
        self.assertNotIn("Learning Default", rendered)
        self.assertNotIn("Learning Default", request_blob)
        self.assertNotIn("0.91", request_blob)
        self.assertNotIn("heater risk", request_blob.lower())

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
        # Live overnight history moves, so this does not pin an exact distance
        # or an empty family-revenge list. A same-family tag is legitimate for
        # three folded cycles after that owner's own loss or risk-cut outside
        # the dead band, then it expires. Level flags stay empty: no axis
        # reaches the elevated-band enter (0.35) or a required-check threshold.
        # The October 1 fixture below remains the exact historical comparison.
        again = shadow_report(ROOT)
        self.assertEqual(again, report)
        self.assertEqual(report["provenance"], "shadow")
        self.assertLess(report["max_abs_distance"], 0.30)
        self.assertEqual(report["level_flags"], [])
        expected_family = _scoped_family_revenge_flags(ROOT)
        self.assertEqual(report["family_revenge_flags"], expected_family)
        known_flags = set(PSYCH_FLAG_IDS)
        for owner_id, row in report["identities"].items():
            for axis in PSYCH_AXES:
                self.assertLess(row["distances"][axis], 0.30)
            self.assertNotEqual(owner_id, "chatgpt")
            owned = [item for item in expected_family if item.startswith(f"{owner_id}:")]
            self.assertLessEqual(len(row["flags"]), 1)
            if not row["flags"]:
                self.assertEqual(owned, [])
                continue
            flag = row["flags"][0]
            self.assertEqual(flag["id"], "revenge_risk")
            self.assertIn(flag["id"], known_flags)
            self.assertEqual(flag["scope"], "family")
            self.assertTrue(flag["families"])
            self.assertEqual(owned, [f"{owner_id}:{','.join(flag['families'])}"])

    def test_family_revenge_flag_follows_scoped_material_loss(self) -> None:
        self.assertEqual(_TRADER_DEAD_BAND_USD, 40_000.0)
        self.assertEqual(_TRADER_UNIT_USD, 500_000.0)
        run = "overnight-20261020"
        seat = {"trend-follower": 0.0}

        def shadow(name: str, runs: list[tuple[str, dict[str, float]]], trades: list[dict]) -> dict:
            root = self.root / "family-revenge" / name
            _write_shadow_root(root, runs, trades)
            report = shadow_report(root)
            self.assertEqual(shadow_report(root), report)
            self.assertEqual(report["level_flags"], [])
            self.assertEqual(report["family_revenge_flags"], _scoped_family_revenge_flags(root))
            for owner_id, row in report["identities"].items():
                self.assertNotEqual(owner_id, "chatgpt")
                for flag in row["flags"]:
                    self.assertEqual(flag["id"], "revenge_risk")
                    self.assertEqual(flag["scope"], "family")
                    self.assertIn(flag["id"], PSYCH_FLAG_IDS)
            return report

        sofr = _closed_trade(
            trade_id="trd-sofr-loss",
            owner_id="trend-follower",
            instrument="SOFR_2027-03",
            asset_class="rates",
            realized=-76_250.0,
            run_id=run,
        )
        detected, notes = detect_cycle_events(
            owner_type="trader",
            owner_id="trend-follower",
            state=seed_state("trader", "trend-follower"),
            consequence={"session_pnl_change_usd": 0},
            prior={},
            decision={"actions": []},
            blocked=[],
            trades=[sofr],
            reflections=[],
            learning_state={},
            capital_standing=None,
            market_fresh=False,
            run_id=run,
            positions=[],
        )
        loss_events = [row for row in detected if row["kind"] in {"trade_loss_close", "stop_or_risk_cut_close", "trade_win_close"}]
        self.assertEqual([row["kind"] for row in loss_events], ["trade_loss_close"])
        self.assertEqual(loss_events[0]["subject"]["family"], "sofr")
        self.assertEqual(loss_events[0]["subject"]["trade_id"], "trd-sofr-loss")
        self.assertAlmostEqual(loss_events[0]["magnitude"], 76_250 / 500_000)
        state, records = fold_cycle(
            seed_state("trader", "trend-follower"),
            detected,
            run_id=run,
            review_id="review-001",
            flat_cycles=notes.get("flat_cycles"),
            annotations=notes,
        )
        self.assertEqual(len(state["flags"]), 1)
        planted = state["flags"][0]
        self.assertEqual(planted["id"], "revenge_risk")
        self.assertEqual(planted["scope"], "family")
        self.assertEqual(planted["families"], ["sofr"])
        self.assertEqual(planted["relevant_actions"], ["OPEN", "ADD"])
        self.assertEqual(planted["check"], "required")
        self.assertTrue(planted["basis"].startswith("revenge_pressure "))
        self.assertIn("families sofr", planted["basis"])
        self.assertLess(state["axes"]["revenge_pressure"]["value"], 0.45)
        self.assertEqual(state["tags"]["revenge"][0]["ttl"], _FAMILY_REVENGE_TTL)
        self.assertEqual(state["tags"]["revenge"][0]["trade_id"], "trd-sofr-loss")
        rebuilt = replay(records, owner_type="trader", owner_id="trend-follower")
        self.assertEqual(rebuilt["state_sha256"], state["state_sha256"])
        self.assertEqual(rebuilt["tags"]["revenge"][0]["family"], "sofr")
        for index, expected_ttl in enumerate((_FAMILY_REVENGE_TTL - 1, _FAMILY_REVENGE_TTL - 2), start=1):
            state, _records = fold_cycle(state, [], run_id=f"overnight-quiet-{index}", review_id="review-001")
            self.assertEqual(state["tags"]["revenge"][0]["ttl"], expected_ttl)
            self.assertEqual(state["flags"][0]["scope"], "family")
            self.assertEqual(state["flags"][0]["families"], ["sofr"])
        state, _records = fold_cycle(state, [], run_id="overnight-quiet-3", review_id="review-001")
        self.assertEqual(state["tags"]["revenge"], [])
        self.assertEqual(state["flags"], [])

        inside, _notes = detect_cycle_events(
            owner_type="trader",
            owner_id="trend-follower",
            state=seed_state("trader", "trend-follower"),
            consequence={"session_pnl_change_usd": 0},
            prior={},
            decision={"actions": []},
            blocked=[],
            trades=[
                _closed_trade(
                    trade_id="trd-inside",
                    owner_id="trend-follower",
                    instrument="SOFR_2027-03",
                    asset_class="rates",
                    realized=-(_TRADER_DEAD_BAND_USD - 1),
                    run_id=run,
                )
            ],
            reflections=[],
            learning_state={},
            capital_standing=None,
            market_fresh=False,
            run_id=run,
            positions=[],
        )
        self.assertFalse(any(row["kind"] in {"trade_loss_close", "stop_or_risk_cut_close"} for row in inside))
        spot, _notes = detect_cycle_events(
            owner_type="trader",
            owner_id="trend-follower",
            state=seed_state("trader", "trend-follower"),
            consequence={"session_pnl_change_usd": 0},
            prior={},
            decision={"actions": []},
            blocked=[],
            trades=[
                _closed_trade(
                    trade_id="trd-spot",
                    owner_id="trend-follower",
                    instrument="EURUSD",
                    asset_class="spot_fx",
                    realized=-80_000.0,
                    run_id=run,
                )
            ],
            reflections=[],
            learning_state={},
            capital_standing=None,
            market_fresh=False,
            run_id=run,
            positions=[],
        )
        spot_loss = next(row for row in spot if row["kind"] == "trade_loss_close")
        self.assertEqual(spot_loss["subject"]["family"], "EURUSD")
        self.assertNotEqual(spot_loss["subject"]["family"], "sofr")

        positive = shadow("sofr-loss", [(run, seat)], [sofr])
        self.assertEqual(positive["family_revenge_flags"], ["trend-follower:sofr"])
        self.assertLess(positive["max_abs_distance"], 0.30)
        self.assertEqual(
            positive["identities"]["trend-follower"]["flags"],
            [{"id": "revenge_risk", "scope": "family", "families": ["sofr"]}],
        )
        self.assertEqual(positive["identities"]["dollar-king"]["flags"], [])

        cases = [
            ("inside-band", [_closed_trade(trade_id="trd-inside", owner_id="trend-follower", instrument="SOFR_2027-03", asset_class="rates", realized=-(_TRADER_DEAD_BAND_USD - 1), run_id=run)], []),
            ("at-band", [_closed_trade(trade_id="trd-at-band", owner_id="trend-follower", instrument="SOFR_2027-03", asset_class="rates", realized=-_TRADER_DEAD_BAND_USD, run_id=run)], ["trend-follower:sofr"]),
            ("win", [_closed_trade(trade_id="trd-win", owner_id="trend-follower", instrument="SOFR_2027-03", asset_class="rates", realized=80_000.0, run_id=run)], []),
            ("spot", [_closed_trade(trade_id="trd-spot", owner_id="trend-follower", instrument="EURUSD", asset_class="spot_fx", realized=-80_000.0, run_id=run)], ["trend-follower:EURUSD"]),
            ("bond", [_closed_trade(trade_id="trd-bond", owner_id="trend-follower", instrument="US_10Y", asset_class="rates", realized=-80_000.0, run_id=run)], ["trend-follower:bond"]),
            ("open", [_closed_trade(trade_id="trd-open", owner_id="trend-follower", instrument="SOFR_2027-03", asset_class="rates", realized=-80_000.0, run_id=run, status="open")], []),
            ("other-run", [_closed_trade(trade_id="trd-other-run", owner_id="trend-follower", instrument="SOFR_2027-03", asset_class="rates", realized=-80_000.0, run_id="overnight-20260922")], []),
            ("risk-cut-gain", [_closed_trade(trade_id="trd-cut", owner_id="trend-follower", instrument="SOFR_2027-03", asset_class="rates", realized=80_000.0, run_id=run, exit_reason="risk_cut")], ["trend-follower:sofr"]),
            ("risk-cut-inside", [_closed_trade(trade_id="trd-cut-small", owner_id="trend-follower", instrument="SOFR_2027-03", asset_class="rates", realized=-10_000.0, run_id=run, exit_reason="risk_cut")], []),
        ]
        for name, trades, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(shadow(name, [(run, seat)], trades)["family_revenge_flags"], expected)

        both = shadow(
            "both-families",
            [(run, seat)],
            [
                sofr,
                _closed_trade(
                    trade_id="trd-bond-too",
                    owner_id="trend-follower",
                    instrument="US_10Y",
                    asset_class="rates",
                    realized=-80_000.0,
                    run_id=run,
                ),
            ],
        )
        self.assertEqual(both["family_revenge_flags"], ["trend-follower:bond,sofr"])

        scoped = shadow(
            "other-owner",
            [(run, {"trend-follower": 0.0, "dollar-king": 0.0})],
            [
                _closed_trade(
                    trade_id="trd-dollar-king",
                    owner_id="dollar-king",
                    instrument="SOFR_2027-03",
                    asset_class="rates",
                    realized=-76_250.0,
                    run_id=run,
                )
            ],
        )
        self.assertEqual(scoped["family_revenge_flags"], ["dollar-king:sofr"])
        self.assertEqual(scoped["identities"]["trend-follower"]["flags"], [])
        self.assertEqual(scoped["identities"]["trend-follower"]["cycle_count"], 1)

        held_runs = [
            ("overnight-20261020", seat),
            ("overnight-20261021", seat),
            ("overnight-20261022", seat),
        ]
        expired_runs = held_runs + [("overnight-20261023", seat)]
        held = shadow("ttl-held", held_runs, [sofr])
        self.assertEqual(held["family_revenge_flags"], ["trend-follower:sofr"])
        self.assertEqual(held["identities"]["trend-follower"]["cycle_count"], 3)
        expired = shadow("ttl-expired", expired_runs, [sofr])
        self.assertEqual(expired["family_revenge_flags"], [])
        self.assertEqual(expired["identities"]["trend-follower"]["flags"], [])
        self.assertEqual(expired["identities"]["trend-follower"]["cycle_count"], 4)
        refreshed = shadow(
            "ttl-refresh",
            expired_runs,
            [
                sofr,
                _closed_trade(
                    trade_id="trd-sofr-refresh",
                    owner_id="trend-follower",
                    instrument="SOFR_2027-03",
                    asset_class="rates",
                    realized=-80_000.0,
                    run_id="overnight-20261023",
                ),
            ],
        )
        self.assertEqual(refreshed["family_revenge_flags"], ["trend-follower:sofr"])
        self.assertEqual(refreshed["identities"]["trend-follower"]["cycle_count"], 4)

    def test_shadow_replay_matches_immutable_inputs(self) -> None:
        fixture_dir = ROOT / "tests" / "fixtures" / "psychology"
        report = shadow_report(fixture_dir / "replay_root")
        stored = json.loads((fixture_dir / "shadow_report.json").read_text(encoding="utf-8"))
        # October 1 snapshot. Do not retarget this at a later production run.
        self.assertEqual(stored["max_abs_distance"], 0.2192)
        self.assertEqual(report, stored)
        self.assertEqual(report["level_flags"], [])
        self.assertEqual(report["family_revenge_flags"], [])

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
