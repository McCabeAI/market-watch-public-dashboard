"""Profit-harvest review: lifecycle, triggers, full-size holds, and the USDCAD replay."""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.overnight.books import empty_books as empty_trader_books
from scripts.overnight.books import position_pnl
from scripts.overnight.constants import STANDING_SEATS
from scripts.pm.books import empty_books as empty_pm_books
from scripts.trading.apply import apply_pm_decision_with_memory, apply_trader_review_with_memory
from scripts.trading.errors import HarvestReviewError, SchemaError
from scripts.trading.harvest import (
    HARVEST_QUESTION,
    assert_expansion_lifecycle,
    enforce_harvest_hold,
    harvest_metrics,
    justification_reason,
    normalize_lifecycle,
    persist_accepted_harvest,
    replay_mark_path,
)
from scripts.trading.ledger import find_trade_by_position, observe_open_mark, record_lifecycle_event
from scripts.trading.memory import accept_performance_reflection, build_memory_context, ensure_reflections_due
from scripts.trading.store import TradingStore
from scripts.trader_room.schema import _validate_paper_action_row

ROOT = Path(__file__).resolve().parents[1]
NY = ZoneInfo("America/New_York")
AS_OF = datetime(2026, 9, 19, 12, 0, tzinfo=NY)
MARKET = {
    "generated_at": "2026-09-19T12:00:00Z",
    "fx": {"pairs": {"USDCAD": {"spot": 1.36, "as_of": "2026-09-19"}}},
}


def _open_winner(
    *,
    position_id: str = "pos-win",
    trade_id: str = "trd-trader-dollar-king-pos-win",
    notional: float = 55_000_000,
    pnl: float = 610_000,
) -> tuple[dict, dict, datetime]:
    trade = {
        "trade_id": trade_id,
        "position_id": position_id,
        "instrument": "USDCAD",
        "asset_class": "spot_fx",
        "side": "long",
        "status": "open",
        "opened_at": "2026-09-19T12:00:00-04:00",
        "entry_mark": 1.36,
        "peak_notional_usd": notional,
        "current_notional_usd": notional,
        "realized_pnl_usd": 0,
        "mfe_usd": pnl,
    }
    position = {
        "position_id": position_id,
        "instrument": "USDCAD",
        "asset_class": "spot_fx",
        "side": "long",
        "notional_usd": notional,
        "entry_price": 1.36,
        "mark_price": 1.38,
        "unrealized_pnl_usd": pnl,
        "opened_at": trade["opened_at"],
    }
    return trade, position, datetime(2026, 9, 28, 8, 0, tzinfo=NY)


def _lifecycle(**overrides) -> dict:
    payload = {
        "framing": "tactical",
        "horizon_days": 10,
        "realization_logic": "Spot continuation of the incomplete USD move versus CAD.",
        "catalyst_logic": "The next BoC or oil window inside the tactical horizon.",
    }
    payload.update(overrides)
    return payload


def _review(**overrides) -> dict:
    payload = {
        "thesis_still_valid": True,
        "remaining_edge": True,
        "would_initiate_flat": "yes",
        "remaining_edge_reason": (
            "If flat today I would still initiate this exact size at this level because "
            "the remaining policy gap is larger than the move already captured."
        ),
    }
    payload.update(overrides)
    return payload


def _families() -> dict:
    return {
        "macro_hard": {"status": "fresh", "as_of": "2026-09-19T00:07:00-04:00", "digest": "m"},
        "news": {"status": "fresh", "as_of": "2026-09-19T00:07:00-04:00", "digest": "n"},
        "central_bank_research": {"status": "fresh", "as_of": "2026-09-19T00:07:00-04:00", "digest": "c"},
        "market_state": {"status": "fresh", "as_of": "2026-09-19T00:07:00-04:00", "digest": "s", "data": MARKET},
    }


def _hold_reviews(hashes: dict[str, str]) -> dict:
    reviews = {}
    for seat in STANDING_SEATS:
        reviews[seat] = {
            "seat": seat,
            "conviction": 30,
            "thesis": "No incremental edge.",
            "memory_context_sha256": hashes.get(seat),
            "actions": [{"action": "HOLD"}],
        }
    return reviews


def _usdcad_marks() -> list[dict]:
    """Canonical USDCAD spots from frozen overnight evidence, one row per quote date."""
    root = ROOT / "data" / "overnight" / "runs"
    found: dict[str, dict] = {}
    for snap in sorted(root.glob("*/reviews/*/evidence_snapshot.json")):
        text = snap.read_text(encoding="utf-8", errors="ignore")
        best = None
        for match in re.finditer(r'"USDCAD"\s*:\s*\{', text):
            chunk = text[match.start() : match.start() + 1200]
            if '"spot"' not in chunk or '"pctile_1y"' not in chunk:
                continue
            spot = re.search(r'"spot"\s*:\s*([0-9.]+)', chunk)
            as_of = re.search(r'"as_of"\s*:\s*"([^"]+)"', chunk)
            if spot and as_of:
                best = {"as_of": as_of.group(1), "mark": float(spot.group(1))}
                break
        if best:
            found[best["as_of"]] = best
    rows = [found[key] for key in sorted(found)]
    if len(rows) < 10:
        raise AssertionError("USDCAD evidence path is too short to replay")
    return rows


class ProfitHarvestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = TradingStore(root=self.root, state_root=self.root)
        self.store.ensure_initialized()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_legacy_trade_without_lifecycle_still_evaluates(self) -> None:
        trade = {
            "trade_id": "trd-legacy",
            "position_id": "pos-legacy",
            "instrument": "USDCAD",
            "side": "long",
            "asset_class": "spot_fx",
            "status": "open",
            "entry_mark": 1.40,
            "opened_at": "2026-09-19T22:36:50-04:00",
            "current_notional_usd": 55_000_000,
            "peak_notional_usd": 55_000_000,
            "realized_pnl_usd": 0,
            "mfe_usd": 953561.41,
        }
        position = {
            "position_id": "pos-legacy",
            "instrument": "USDCAD",
            "asset_class": "spot_fx",
            "side": "long",
            "notional_usd": 55_000_000,
            "entry_price": 1.40,
            "mark_price": 1.407,
            "unrealized_pnl_usd": 250_000,
        }
        metrics = harvest_metrics(trade, position, as_of=datetime(2026, 10, 19, tzinfo=NY))
        self.assertEqual(metrics["horizon_status"], "unspecified")
        self.assertIsNone(metrics["framing"])
        self.assertTrue(metrics["review_required"])
        self.assertIn("material_winner", metrics["review_triggers"])
        self.assertIn("giveback", metrics["review_triggers"])
        self.assertFalse(metrics["mechanical_order"])
        self.assertEqual(metrics["order_policy"], "review_only")
        self.assertNotIn("action", metrics)
        self.assertEqual(metrics["question"], HARVEST_QUESTION)

    def test_entry_lifecycle_persists_and_legacy_open_still_works(self) -> None:
        with self.assertRaises(SchemaError):
            assert_expansion_lifecycle({"action": "OPEN"}, owner_id="dollar-king")
        with self.assertRaises(SchemaError):
            _validate_paper_action_row({"action": "OPEN", "instrument": "USDCAD"}, label="dollar-king")
        stored = record_lifecycle_event(
            self.store,
            owner_type="trader",
            owner_id="dollar-king",
            kind="OPEN",
            position_id="pos-life",
            when=AS_OF,
            run_id="overnight-20260919",
            instrument="USDCAD",
            asset_class="spot_fx",
            side="long",
            mark=1.36,
            notional_change_usd=10_000_000,
            current_notional_usd=10_000_000,
            lifecycle=_lifecycle(framing="swing", horizon_days=40),
        )
        self.assertEqual(stored["lifecycle"]["framing"], "swing")
        self.assertEqual(stored["lifecycle"]["horizon_days"], 40)
        self.assertEqual(stored["entry_lifecycle"]["source"], "entry")
        self.assertEqual(stored["entry_mark"], 1.36)
        bare = record_lifecycle_event(
            self.store,
            owner_type="trader",
            owner_id="rate-hawk",
            kind="OPEN",
            position_id="pos-bare",
            when=AS_OF,
            run_id="overnight-20260919",
            instrument="US_10Y",
            asset_class="rates",
            side="short",
            mark=4.2,
            notional_change_usd=5_000_000,
            current_notional_usd=5_000_000,
        )
        self.assertNotIn("lifecycle", bare)

    def test_full_size_hold_requires_remaining_edge_not_thesis(self) -> None:
        trade = {
            "trade_id": "trd-trader-dollar-king-pos-win",
            "position_id": "pos-win",
            "instrument": "USDCAD",
            "asset_class": "spot_fx",
            "side": "long",
            "status": "open",
            "opened_at": "2026-09-19T12:00:00-04:00",
            "entry_mark": 1.36,
            "peak_notional_usd": 55_000_000,
            "current_notional_usd": 55_000_000,
            "realized_pnl_usd": 0,
            "mfe_usd": 610_000,
            "lifecycle": {**normalize_lifecycle(_lifecycle()), "anchored_at": "2026-09-19T12:00:00-04:00", "source": "entry"},
        }
        position = {
            "position_id": "pos-win",
            "instrument": "USDCAD",
            "asset_class": "spot_fx",
            "side": "long",
            "notional_usd": 55_000_000,
            "entry_price": 1.36,
            "mark_price": 1.38,
            "unrealized_pnl_usd": 610_000,
            "opened_at": trade["opened_at"],
        }
        as_of = datetime(2026, 9, 28, 8, 0, tzinfo=NY)
        metrics = harvest_metrics(trade, position, as_of=as_of)
        self.assertIn("material_winner", metrics["review_triggers"])
        self.assertNotIn("horizon_expired", metrics["review_triggers"])
        self.assertIsNotNone(justification_reason(metrics, None))
        self.assertIsNotNone(
            justification_reason(metrics, _review(thesis_still_valid=True, remaining_edge=False, would_initiate_flat="no"))
        )
        self.assertIsNone(
            justification_reason(metrics, _review(thesis_still_valid=False, remaining_edge=True, would_initiate_flat="yes"))
        )
        decision = {"actions": [{"action": "HOLD"}], "harvest_reviews": [_review(position_id="pos-win")]}
        accepted = enforce_harvest_hold(decision, [trade], [position], as_of=as_of, owner_id="dollar-king")
        self.assertEqual(len(accepted), 1)
        with self.assertRaises(HarvestReviewError):
            enforce_harvest_hold({"actions": [{"action": "HOLD"}]}, [trade], [position], as_of=as_of, owner_id="dollar-king")
        with self.assertRaises(HarvestReviewError):
            enforce_harvest_hold(
                {"actions": [{"action": "REDUCE", "position_id": "pos-win", "notional_usd": 20_000_000}]},
                [trade],
                [position],
                as_of=as_of,
                owner_id="dollar-king",
            )
        enforce_harvest_hold(
            {"actions": [{"action": "CLOSE", "position_id": "pos-win"}]},
            [trade],
            [position],
            as_of=as_of,
            owner_id="dollar-king",
        )

    def test_residual_size_review_blocks_token_and_round_trip_cuts(self) -> None:
        trade, position, as_of = _open_winner()
        other_trade, other_position, _as_of = _open_winner(position_id="pos-other", trade_id="trd-other")

        with self.assertRaises(HarvestReviewError):
            enforce_harvest_hold(
                {"actions": [{"action": "REDUCE", "position_id": "pos-win", "notional_usd": 1}]},
                [trade],
                [position],
                as_of=as_of,
                owner_id="dollar-king",
            )
        token = {
            "actions": [{"action": "REDUCE", "position_id": "pos-win", "notional_usd": 1}],
            "harvest_reviews": [_review(position_id="pos-win")],
        }
        accepted = enforce_harvest_hold(token, [trade], [position], as_of=as_of, owner_id="dollar-king")
        self.assertEqual(accepted[0]["residual_notional_usd"], 54_999_999.0)
        self.assertEqual(token["actions"][0]["action"], "REDUCE")
        self.assertNotIn("action", accepted[0])

        with self.assertRaises(HarvestReviewError):
            enforce_harvest_hold(
                {"actions": [{"action": "REDUCE", "position_id": "pos-win", "notional_usd": 20_000_000}]},
                [trade],
                [position],
                as_of=as_of,
                owner_id="dollar-king",
            )
        partial = enforce_harvest_hold(
            {
                "actions": [{"action": "REDUCE", "position_id": "pos-win", "notional_usd": 20_000_000}],
                "harvest_reviews": [_review(position_id="pos-win")],
            },
            [trade],
            [position],
            as_of=as_of,
            owner_id="dollar-king",
        )
        self.assertEqual(partial[0]["residual_notional_usd"], 35_000_000.0)

        enforce_harvest_hold(
            {"actions": [{"action": "REDUCE", "position_id": "pos-win", "notional_usd": 47_000_000}]},
            [trade],
            [position],
            as_of=as_of,
            owner_id="dollar-king",
        )
        with self.assertRaises(HarvestReviewError):
            enforce_harvest_hold(
                {"actions": [{"action": "REDUCE", "position_id": "pos-win", "notional_usd": 45_000_000}]},
                [trade],
                [position],
                as_of=as_of,
                owner_id="dollar-king",
            )

        with self.assertRaises(HarvestReviewError):
            enforce_harvest_hold(
                {
                    "actions": [
                        {"action": "REDUCE", "position_id": "pos-win", "notional_usd": 50_000_000},
                        {"action": "ADD", "position_id": "pos-win", "notional_usd": 40_000_000},
                    ]
                },
                [trade],
                [position],
                as_of=as_of,
                owner_id="dollar-king",
            )
        round_trip = enforce_harvest_hold(
            {
                "actions": [
                    {"action": "REDUCE", "position_id": "pos-win", "notional_usd": 47_000_000},
                    {"action": "ADD", "position_id": "pos-win", "notional_usd": 5_000_000},
                ],
                "harvest_reviews": [_review(position_id="pos-win")],
            },
            [trade],
            [position],
            as_of=as_of,
            owner_id="dollar-king",
        )
        self.assertEqual(round_trip[0]["residual_notional_usd"], 13_000_000.0)

        enforce_harvest_hold(
            {"actions": [{"action": "CLOSE", "position_id": "pos-win"}]},
            [trade],
            [position],
            as_of=as_of,
            owner_id="dollar-king",
        )
        enforce_harvest_hold(
            {"actions": [{"action": "REDUCE", "position_id": "pos-win", "notional_usd": 55_000_000}]},
            [trade],
            [position],
            as_of=as_of,
            owner_id="dollar-king",
        )

        books = [position, other_position]
        trades = [trade, other_trade]
        with self.assertRaises(HarvestReviewError):
            enforce_harvest_hold(
                {"actions": [{"action": "CLOSE", "position_id": "pos-win"}]},
                trades,
                books,
                as_of=as_of,
                owner_id="dollar-king",
            )
        with self.assertRaises(HarvestReviewError):
            enforce_harvest_hold(
                {
                    "actions": [
                        {"action": "REDUCE", "position_id": "pos-win", "notional_usd": 1},
                        {"action": "HOLD"},
                    ],
                    "harvest_reviews": [_review(position_id="pos-win")],
                },
                trades,
                books,
                as_of=as_of,
                owner_id="dollar-king",
            )
        both = enforce_harvest_hold(
            {
                "actions": [
                    {"action": "CLOSE", "position_id": "pos-win"},
                    {"action": "HOLD"},
                ],
                "harvest_reviews": [_review(position_id="pos-other")],
            },
            trades,
            books,
            as_of=as_of,
            owner_id="dollar-king",
        )
        self.assertEqual([row["metrics_position_id"] for row in both], ["pos-other"])

    def test_expired_horizon_requires_reunderwrite_from_current_conditions(self) -> None:
        opened = datetime(2026, 9, 1, 9, 0, tzinfo=NY)
        trade = record_lifecycle_event(
            self.store,
            owner_type="trader",
            owner_id="dollar-king",
            kind="OPEN",
            position_id="pos-tactical",
            when=opened,
            run_id="overnight-20260901",
            instrument="USDCAD",
            asset_class="spot_fx",
            side="long",
            mark=1.36,
            notional_change_usd=10_000_000,
            current_notional_usd=10_000_000,
            lifecycle=_lifecycle(horizon_days=10),
        )
        position = {
            "position_id": "pos-tactical",
            "instrument": "USDCAD",
            "asset_class": "spot_fx",
            "side": "long",
            "notional_usd": 10_000_000,
            "entry_price": 1.36,
            "mark_price": 1.361,
            "unrealized_pnl_usd": 7_000,
            "opened_at": trade["opened_at"],
        }
        as_of = opened + timedelta(days=11)
        metrics = harvest_metrics(trade, position, as_of=as_of)
        self.assertIn("horizon_expired", metrics["review_triggers"])
        self.assertNotIn("material_winner", metrics["review_triggers"])
        self.assertTrue(metrics["full_size_hold_requires_reunderwrite"])
        stale = _review(position_id="pos-tactical")
        with self.assertRaises(HarvestReviewError):
            enforce_harvest_hold(
                {"actions": [{"action": "HOLD"}], "harvest_reviews": [stale]},
                [trade],
                [position],
                as_of=as_of,
                owner_id="dollar-king",
            )
        fresh = _review(
            position_id="pos-tactical",
            reunderwrite=_lifecycle(framing="swing", horizon_days=30),
        )
        decision = {"actions": [{"action": "HOLD"}], "harvest_reviews": [fresh]}
        decision["_harvest_accepted"] = enforce_harvest_hold(
            decision, [trade], [position], as_of=as_of, owner_id="dollar-king"
        )
        persist_accepted_harvest(
            self.store,
            decision,
            owner_type="trader",
            owner_id="dollar-king",
            when=as_of,
            run_id="overnight-20260912",
        )
        updated = self.store.read_trade(trade["trade_id"])
        self.assertEqual(updated["entry_mark"], 1.36)
        self.assertEqual(updated["entry_lifecycle"]["framing"], "tactical")
        self.assertEqual(updated["lifecycle"]["framing"], "swing")
        self.assertEqual(updated["lifecycle"]["source"], "reunderwrite")
        self.assertEqual(updated["lifecycle"]["horizon_days"], 30)
        restarted = harvest_metrics(updated, position, as_of=as_of)
        self.assertEqual(restarted["horizon_status"], "within")

    def test_apply_paths_reject_unjustified_full_size_and_persist_lifecycle(self) -> None:
        hashes = {
            seat: build_memory_context(self.store, "trader", seat)["memory_context_sha256"] for seat in STANDING_SEATS
        }
        books = empty_trader_books(overnight_run_id="overnight-20260919", when=AS_OF)
        reviews = _hold_reviews(hashes)
        reviews["dollar-king"] = {
            "seat": "dollar-king",
            "conviction": 60,
            "thesis": "USD versus CAD still has room.",
            "memory_context_sha256": hashes["dollar-king"],
            "actions": [{
                "action": "OPEN",
                "instrument": "USDCAD",
                "side": "long",
                "notional_usd": 20_000_000,
                "price": 1.36,
                "asset_class": "spot_fx",
                "thesis": "USD versus CAD still has room.",
                "lifecycle": _lifecycle(),
            }],
        }
        updated = apply_trader_review_with_memory(
            books,
            reviews,
            families=_families(),
            run_id="overnight-20260919",
            evidence_cutoff="2026-09-19T12:00:00-04:00",
            store=self.store,
            memory_hashes=hashes,
            when=AS_OF,
            market_state=MARKET,
        )
        position = updated["seats"]["dollar-king"]["positions"][0]
        trade = find_trade_by_position(
            self.store, owner_type="trader", owner_id="dollar-king", position_id=position["position_id"]
        )
        self.assertEqual(trade["lifecycle"]["framing"], "tactical")
        position["unrealized_pnl_usd"] = 400_000
        position["mark_price"] = 1.39
        observe_open_mark(self.store, trade, unrealized_pnl_usd=400_000, mark=1.39)
        hold = _hold_reviews(hashes)
        with self.assertRaises(HarvestReviewError):
            apply_trader_review_with_memory(
                updated,
                hold,
                families=_families(),
                run_id="overnight-20260928",
                evidence_cutoff="2026-09-28T12:00:00-04:00",
                store=self.store,
                memory_hashes=hashes,
                when=datetime(2026, 9, 28, 12, 0, tzinfo=NY),
                market_state=MARKET,
            )
        self.assertEqual(updated["seats"]["dollar-king"]["positions"][0]["notional_usd"], 20_000_000)
        justified = _hold_reviews(hashes)
        justified["dollar-king"]["harvest_reviews"] = [_review(position_id=position["position_id"])]
        apply_trader_review_with_memory(
            updated,
            justified,
            families=_families(),
            run_id="overnight-20260929",
            evidence_cutoff="2026-09-29T12:00:00-04:00",
            store=self.store,
            memory_hashes=hashes,
            when=datetime(2026, 9, 29, 12, 0, tzinfo=NY),
            market_state=MARKET,
        )
        reduced = _hold_reviews(hashes)
        reduced["dollar-king"]["actions"] = [{
            "action": "REDUCE",
            "position_id": position["position_id"],
            "notional_usd": 16_000_000,
            "price": 1.39,
            "rationale": "Cut the line down to a stub that is no longer a meaningful residual winner.",
        }]
        after = apply_trader_review_with_memory(
            updated,
            reduced,
            families=_families(),
            run_id="overnight-20260930",
            evidence_cutoff="2026-09-30T12:00:00-04:00",
            store=self.store,
            memory_hashes=hashes,
            when=datetime(2026, 9, 30, 12, 0, tzinfo=NY),
            market_state=MARKET,
        )
        self.assertEqual(after["seats"]["dollar-king"]["positions"][0]["notional_usd"], 4_000_000)

    def test_pm_hold_uses_the_same_gate(self) -> None:
        context = build_memory_context(self.store, "pm", "pragmatist")
        books = empty_pm_books()
        opened = apply_pm_decision_with_memory(
            books,
            {
                "pm_id": "pragmatist",
                "memory_context_sha256": context["memory_context_sha256"],
                "thesis": "CAD policy gap.",
                "actions": [{
                    "action": "OPEN",
                    "instrument": "USDCAD",
                    "side": "long",
                    "notional_usd": 20_000_000,
                    "asset_class": "spot_fx",
                    "price": 1.36,
                    "lifecycle": _lifecycle(framing="structural", horizon_days=90),
                }],
            },
            pm_id="pragmatist",
            store=self.store,
            market_state=MARKET,
            run_id="overnight-20260919",
            evidence_cutoff="2026-09-19T12:00:00-04:00",
            review_packet_id="prp-pragmatist-open",
            review_packet_sha256="hash-open",
            expected_memory_sha256=context["memory_context_sha256"],
            when=AS_OF,
        )
        position = opened["pms"]["pragmatist"]["positions"][0]
        position["unrealized_pnl_usd"] = 500_000
        trade = find_trade_by_position(
            self.store, owner_type="pm", owner_id="pragmatist", position_id=position["position_id"]
        )
        observe_open_mark(self.store, trade, unrealized_pnl_usd=500_000, mark=1.40)
        with self.assertRaises(HarvestReviewError):
            apply_pm_decision_with_memory(
                opened,
                {"pm_id": "pragmatist", "actions": [{"action": "HOLD"}]},
                pm_id="pragmatist",
                store=self.store,
                market_state=MARKET,
                run_id="overnight-20261007",
                evidence_cutoff="2026-10-07T12:00:00-04:00",
                review_packet_id="prp-pragmatist-hold",
                review_packet_sha256="hash-hold",
                when=datetime(2026, 10, 7, 12, 0, tzinfo=NY),
            )
        closed = apply_pm_decision_with_memory(
            opened,
            {
                "pm_id": "pragmatist",
                "actions": [{
                    "action": "CLOSE",
                    "position_id": position["position_id"],
                    "price": 1.40,
                    "rationale": "The delivered move no longer has remaining edge.",
                }],
            },
            pm_id="pragmatist",
            store=self.store,
            market_state=MARKET,
            run_id="overnight-20261008",
            evidence_cutoff="2026-10-08T12:00:00-04:00",
            review_packet_id="prp-pragmatist-close",
            review_packet_sha256="hash-close",
            when=datetime(2026, 10, 8, 12, 0, tzinfo=NY),
        )
        self.assertEqual(closed["pms"]["pragmatist"]["positions"], [])

    def test_major_giveback_opens_causal_review_without_a_lesson(self) -> None:
        trade = record_lifecycle_event(
            self.store,
            owner_type="trader",
            owner_id="dollar-king",
            kind="OPEN",
            position_id="pos-gb",
            when=AS_OF,
            run_id="overnight-20260919",
            instrument="USDCAD",
            asset_class="spot_fx",
            side="long",
            mark=1.40,
            notional_change_usd=55_000_000,
            current_notional_usd=55_000_000,
            lifecycle=_lifecycle(framing="swing", horizon_days=45),
        )
        observe_open_mark(self.store, trade, unrealized_pnl_usd=900_000, mark=1.425)
        observe_open_mark(self.store, self.store.read_trade(trade["trade_id"]), unrealized_pnl_usd=200_000, mark=1.407)
        books = empty_trader_books(overnight_run_id="overnight-20261019", when=AS_OF)
        books["seats"]["dollar-king"]["positions"] = [{
            "position_id": "pos-gb",
            "instrument": "USDCAD",
            "asset_class": "spot_fx",
            "side": "long",
            "notional_usd": 55_000_000,
            "entry_price": 1.40,
            "mark_price": 1.407,
            "unrealized_pnl_usd": 200_000,
        }]
        ensure_reflections_due(
            self.store,
            "trader",
            "dollar-king",
            run_id="overnight-20261019",
            when=datetime(2026, 10, 19, 9, 0, tzinfo=NY),
            trader_books=books,
        )
        due = self.store.read_reflections_due("trader", "dollar-king")["items"]
        self.assertTrue(any("profit_giveback" in (item.get("trigger_ids") or []) for item in due))
        item = next(row for row in due if "profit_giveback" in (row.get("trigger_ids") or []))
        causal = {
            "original_belief": "The policy gap would keep paying after the first large spot extension.",
            "observed_reality": "The spot extension reversed after the move was largely delivered.",
            "assumptions_right": "The original policy disagreement was a real open.",
            "assumptions_wrong_or_underweighted": "Holding full size after the move assumed the remaining path equalled the entry path.",
            "causal_divergence": "The giveback came from exhausted spot extension rather than a new macro fact.",
            "same_information_counterfactual": "A flat book at the high would not have re-initiated the same full size.",
            "future_implication": "Revisit full size when the retained move is still the trade that was underwritten.",
            "decision_quality_attribution": "sizing",
        }
        accept_performance_reflection(
            self.store,
            {
                "reflection_due_id": item["reflection_due_id"],
                "what_happened_vs_expected": "The open winner gave back most of the favorable excursion without a thesis break.",
                "attribution": ["sizing"],
                "pressure_effect": "distorting",
                "skill_vs_luck": "mixed",
                "overconfidence_risk": "yes",
                "chase_or_revenge": "no",
                "no_new_lesson": "The prior process remains sound inside ordinary variance once full size is re-underwritten.",
                "causal": causal,
            },
            owner_type="trader",
            owner_id="dollar-king",
            run_id="overnight-20261020",
        )
        self.assertEqual(self.store.read_lessons("trader", "dollar-king")["lessons"], [])
        self.assertEqual(
            [row for row in self.store.read_reflections_due("trader", "dollar-king")["items"] if row.get("status") == "due"],
            [],
        )
        context = build_memory_context(
            self.store,
            "trader",
            "dollar-king",
            when=datetime(2026, 10, 20, 9, 0, tzinfo=NY),
            trader_books=books,
        )
        self.assertEqual(context["profit_harvest"]["order_policy"], "review_only")
        self.assertFalse(context["profit_harvest"]["mechanical_orders"])
        self.assertIn(HARVEST_QUESTION, context["profit_harvest"]["question"])
        self.assertIn("pos-gb", context["profit_harvest"]["review_required_position_ids"])
        self.assertIn("giveback", context["open_positions"][0]["harvest"]["review_triggers"])
        self.assertNotIn("action", context["open_positions"][0]["harvest"])

    def test_dollar_king_usdcad_replay_reviews_before_the_giveback(self) -> None:
        books = json.loads((ROOT / "data" / "overnight" / "books" / "latest.json").read_text(encoding="utf-8"))
        position = next(
            row for row in books["seats"]["dollar-king"]["positions"] if row.get("instrument") == "USDCAD"
        )
        trade = json.loads(
            (ROOT / "data" / "trading" / "trades" / "trd-trader-dollar-king-pos-5317bc96d4eb.json").read_text(
                encoding="utf-8"
            )
        )
        trade.pop("lifecycle", None)
        entry = float(position["entry_price"])
        path = replay_mark_path(
            trade,
            _usdcad_marks(),
            entry_price=entry,
            notional_usd=55_000_000,
            asset_class="spot_fx",
            side="long",
        )
        by_day = {row["as_of"]: row for row in path}
        early = by_day["2026-09-22"]
        delivered = by_day["2026-09-28"]
        peak = by_day["2026-10-07"]
        gave_back = by_day["2026-10-19"]
        self.assertGreater(early["total_pnl_usd"], 100_000)
        self.assertFalse(early["review_required"])
        self.assertTrue(delivered["review_required"])
        self.assertIn("material_winner", delivered["review_triggers"])
        self.assertNotIn("giveback", delivered["review_triggers"])
        self.assertGreaterEqual(delivered["retained_mfe_fraction"], 0.99)
        self.assertGreater(peak["mfe_usd"], 900_000)
        self.assertGreaterEqual(peak["retained_mfe_fraction"], 0.99)
        self.assertFalse(peak["mechanical_order"])
        self.assertLess(gave_back["retained_mfe_fraction"], 0.50)
        self.assertIn("giveback", gave_back["review_triggers"])
        self.assertLess(delivered["as_of"], gave_back["as_of"])
        self.assertIsNone(justification_reason(delivered, _review()))
        self.assertIsNotNone(justification_reason(delivered, None))
        # Canonical P&L identity at the recorded peak.
        peak_position = {
            "entry_price": entry,
            "mark_price": peak["current_mark"],
            "notional_usd": 55_000_000,
            "side": "long",
            "asset_class": "spot_fx",
        }
        self.assertAlmostEqual(position_pnl(peak_position)["unrealized_pnl_usd"], peak["total_pnl_usd"], places=2)
        self.assertGreater(float(trade["mfe_usd"]), 900_000)

        triggered = 0
        opened = 0
        for owner_type, book_key, owners in (
            ("trader", "seats", books["seats"]),
            ("pm", "pms", json.loads((ROOT / "data" / "pm" / "books" / "latest.json").read_text(encoding="utf-8"))["pms"]),
        ):
            for owner_id, book in owners.items():
                for live in book.get("positions") or []:
                    opened += 1
                    path_trade = ROOT / "data" / "trading" / "trades" / f"trd-{owner_type}-{owner_id}-{live['position_id']}.json"
                    stored = json.loads(path_trade.read_text(encoding="utf-8")) if path_trade.is_file() else {}
                    metrics = harvest_metrics(stored, live, as_of=datetime(2026, 10, 20, 9, 0, tzinfo=NY))
                    self.assertFalse(metrics["mechanical_order"])
                    if metrics["review_required"]:
                        triggered += 1
                    if owner_id == "dollar-king" and live.get("instrument") == "USDCAD":
                        self.assertTrue(metrics["review_required"])
                        self.assertIn("giveback", metrics["review_triggers"])
                    if owner_id == "carry-is-king" and live.get("instrument") == "AONIA_2027-03":
                        self.assertFalse(metrics["review_required"])
        self.assertGreater(opened, triggered)
        self.assertGreater(triggered, 0)


if __name__ == "__main__":
    unittest.main()
