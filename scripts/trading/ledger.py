"""Canonical per-trade lifecycle records. Trusted code owns every fact."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

from scripts.overnight.clock import isoformat, now_ny, parse_iso
from scripts.overnight.store import sha256_json
from scripts.trading.constants import (
    EXIT_REASON_CATEGORIES,
    LEDGER_EVENT_KINDS,
    RATIONALE_STATUSES,
    SCHEMA_VERSION,
    TRADE_STATUSES,
)
from scripts.trading.errors import SchemaError
from scripts.trading.store import TradingStore, assert_identity


def trade_id_for(*, owner_type: str, owner_id: str, position_id: str) -> str:
    return f"trd-{owner_type}-{owner_id}-{position_id}"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _money(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return round(float(value), 2)


def _duration_seconds(opened_at: str | None, closed_at: str | None) -> int | None:
    if not opened_at or not closed_at:
        return None
    try:
        start = parse_iso(opened_at)
        end = parse_iso(closed_at)
    except (TypeError, ValueError):
        return None
    elapsed = (end - start).total_seconds()
    if elapsed < 0:
        return None
    return int(elapsed)


def empty_trade(
    *,
    owner_type: str,
    owner_id: str,
    position_id: str,
    instrument: str | None,
    asset_class: str | None,
    side: str | None,
    when: datetime,
    run_id: str | None,
) -> dict[str, Any]:
    assert_identity(owner_type, owner_id)
    return {
        "schema_version": SCHEMA_VERSION,
        "trade_id": trade_id_for(owner_type=owner_type, owner_id=owner_id, position_id=position_id),
        "position_id": position_id,
        "owner_type": owner_type,
        "owner_id": owner_id,
        "instrument": instrument,
        "asset_class": asset_class,
        "side": side,
        "locked_expression_family": None,
        "paper_expression": None,
        "status": "open",
        "opened_at": isoformat(when),
        "opened_run_id": run_id,
        "evidence_cutoff": None,
        "evidence_packet_id": None,
        "evidence_hash": None,
        "entry_mark": None,
        "entry_mark_source": None,
        "entry_mark_as_of": None,
        "initial_notional_usd": None,
        "current_notional_usd": 0.0,
        "peak_notional_usd": 0.0,
        "entry_thesis": None,
        "entry_rationale": None,
        "priced_or_disagreed": None,
        "catalysts": [],
        "invalidation": None,
        "conviction": None,
        "source_decision_id": None,
        "source_journal_event_id": None,
        "events": [],
        "closed_at": None,
        "closed_run_id": None,
        "exit_mark": None,
        "exit_mark_source": None,
        "exit_mark_as_of": None,
        "exit_rationale": None,
        "exit_reason_category": None,
        "realized_pnl_usd": 0.0,
        "holding_duration_seconds": None,
        "mfe_usd": None,
        "mae_usd": None,
        "hedge_of_position_id": None,
        "hedge_trade_id": None,
        "provenance": {
            "overnight_run_id": run_id if run_id and str(run_id).startswith("overnight-") else None,
            "trader_room_run_id": run_id if run_id and str(run_id).startswith("tr-") else None,
            "review_packet_id": None,
            "review_packet_sha256": None,
            "evidence_hash": None,
        },
    }


def find_trade_by_position(store: TradingStore, *, owner_type: str, owner_id: str, position_id: str) -> dict[str, Any] | None:
    expected = trade_id_for(owner_type=owner_type, owner_id=owner_id, position_id=position_id)
    if store.has_trade(expected):
        return store.read_trade(expected)
    for trade in store.trades_for(owner_type, owner_id):
        if trade.get("position_id") == position_id:
            return trade
    return None


def record_lifecycle_event(
    store: TradingStore,
    *,
    owner_type: str,
    owner_id: str,
    kind: str,
    position_id: str,
    when: datetime,
    run_id: str | None,
    instrument: str | None = None,
    asset_class: str | None = None,
    side: str | None = None,
    mark: Any = None,
    mark_source: Any = None,
    mark_as_of: Any = None,
    notional_change_usd: Any = None,
    current_notional_usd: Any = None,
    realized_increment_usd: Any = None,
    rationale: str | None = None,
    rationale_status: str = "not_required",
    thesis: str | None = None,
    invalidation: str | None = None,
    conviction: Any = None,
    priced_or_disagreed: str | None = None,
    catalysts: list[str] | None = None,
    exit_reason_category: str | None = None,
    paper_expression: Any = None,
    locked_expression_family: str | None = None,
    hedge_of_position_id: str | None = None,
    evidence_cutoff: str | None = None,
    evidence_hash: str | None = None,
    evidence_packet_id: str | None = None,
    source_decision_id: str | None = None,
    source_journal_event_id: str | None = None,
    review_packet_id: str | None = None,
    review_packet_sha256: str | None = None,
    overnight_run_id: str | None = None,
    trader_room_run_id: str | None = None,
) -> dict[str, Any]:
    if kind not in LEDGER_EVENT_KINDS:
        raise SchemaError(f"unknown ledger event kind {kind}")
    if rationale_status not in RATIONALE_STATUSES:
        raise SchemaError(f"invalid rationale_status {rationale_status}")
    if exit_reason_category not in (None, *EXIT_REASON_CATEGORIES):
        raise SchemaError(f"invalid exit_reason_category {exit_reason_category}")

    existing = find_trade_by_position(store, owner_type=owner_type, owner_id=owner_id, position_id=position_id)
    created = False
    if kind in {"OPEN", "HEDGE"} and existing is None:
        trade = empty_trade(
            owner_type=owner_type,
            owner_id=owner_id,
            position_id=position_id,
            instrument=instrument,
            asset_class=asset_class,
            side=side,
            when=when,
            run_id=run_id,
        )
        created = True
    elif existing is None:
        raise SchemaError(f"cannot {kind} unknown position {position_id} for {owner_id}")
    else:
        trade = deepcopy(existing)
        if trade.get("status") == "closed" and kind != "CLOSE":
            raise SchemaError(f"cannot {kind} closed trade {trade['trade_id']}")

    event = {
        "event_id": f"tle-{uuid4().hex[:12]}",
        "kind": kind,
        "at": isoformat(when),
        "run_id": run_id,
        "mark": _money(mark),
        "mark_source": _text(mark_source),
        "mark_as_of": _text(mark_as_of),
        "notional_change_usd": _money(notional_change_usd),
        "realized_pnl_increment_usd": _money(realized_increment_usd) or 0.0,
        "rationale": _text(rationale),
        "rationale_status": rationale_status,
        "exit_reason_category": exit_reason_category,
    }
    trade["events"].append(event)

    hedge_opens_new = kind == "HEDGE" and created
    if kind == "OPEN" or hedge_opens_new:
        if trade.get("initial_notional_usd") in (None, 0, 0.0):
            trade["initial_notional_usd"] = abs(_money(notional_change_usd) or 0.0)
        trade["instrument"] = instrument or trade.get("instrument")
        trade["asset_class"] = asset_class or trade.get("asset_class")
        trade["side"] = side or trade.get("side")
        if trade.get("entry_mark") is None:
            trade["entry_mark"] = _money(mark)
            trade["entry_mark_source"] = _text(mark_source)
            trade["entry_mark_as_of"] = _text(mark_as_of)
        trade["entry_thesis"] = _text(thesis) or trade.get("entry_thesis")
        trade["entry_rationale"] = _text(rationale) or trade.get("entry_rationale")
        trade["priced_or_disagreed"] = _text(priced_or_disagreed) or trade.get("priced_or_disagreed")
        if catalysts:
            existing_cat = list(trade.get("catalysts") or [])
            for item in catalysts:
                text = _text(item)
                if text and text not in existing_cat:
                    existing_cat.append(text)
            trade["catalysts"] = existing_cat
        trade["invalidation"] = _text(invalidation) or trade.get("invalidation")
        if conviction is not None:
            trade["conviction"] = int(conviction)
        trade["source_decision_id"] = source_decision_id or trade.get("source_decision_id")
        trade["source_journal_event_id"] = source_journal_event_id or trade.get("source_journal_event_id")
        if paper_expression is not None:
            trade["paper_expression"] = deepcopy(paper_expression)
        if locked_expression_family:
            trade["locked_expression_family"] = locked_expression_family
        if hedge_of_position_id:
            trade["hedge_of_position_id"] = hedge_of_position_id
            trade["hedge_trade_id"] = trade_id_for(
                owner_type=owner_type, owner_id=owner_id, position_id=hedge_of_position_id
            )
    if current_notional_usd is not None and not (kind == "HEDGE" and not created):
        current = abs(_money(current_notional_usd) or 0.0)
        trade["current_notional_usd"] = current
        peak = float(trade.get("peak_notional_usd") or 0.0)
        trade["peak_notional_usd"] = max(peak, current)
    elif notional_change_usd is not None and not (kind == "HEDGE" and not created):
        delta = abs(_money(notional_change_usd) or 0.0)
        if kind in {"OPEN", "ADD"} or hedge_opens_new:
            current = round(float(trade.get("current_notional_usd") or 0.0) + delta, 2)
        else:
            current = max(0.0, round(float(trade.get("current_notional_usd") or 0.0) - delta, 2))
        trade["current_notional_usd"] = current
        trade["peak_notional_usd"] = max(float(trade.get("peak_notional_usd") or 0.0), current)

    if not (kind == "HEDGE" and not created):
        increment = _money(realized_increment_usd) or 0.0
        trade["realized_pnl_usd"] = round(float(trade.get("realized_pnl_usd") or 0.0) + increment, 2)

    if evidence_cutoff:
        trade["evidence_cutoff"] = evidence_cutoff
    if evidence_hash:
        trade["evidence_hash"] = evidence_hash
        trade["provenance"]["evidence_hash"] = evidence_hash
    if evidence_packet_id:
        trade["evidence_packet_id"] = evidence_packet_id
    if overnight_run_id:
        trade["provenance"]["overnight_run_id"] = overnight_run_id
    if trader_room_run_id:
        trade["provenance"]["trader_room_run_id"] = trader_room_run_id
    if review_packet_id:
        trade["provenance"]["review_packet_id"] = review_packet_id
    if review_packet_sha256:
        trade["provenance"]["review_packet_sha256"] = review_packet_sha256

    if kind == "CLOSE":
        trade["status"] = "closed"
        trade["closed_at"] = isoformat(when)
        trade["closed_run_id"] = run_id
        trade["exit_mark"] = _money(mark)
        trade["exit_mark_source"] = _text(mark_source)
        trade["exit_mark_as_of"] = _text(mark_as_of)
        trade["exit_rationale"] = _text(rationale)
        trade["exit_reason_category"] = exit_reason_category
        trade["current_notional_usd"] = 0.0
        trade["holding_duration_seconds"] = _duration_seconds(trade.get("opened_at"), trade["closed_at"])
    else:
        trade["status"] = "open"

    if trade["status"] not in TRADE_STATUSES:
        raise SchemaError(f"invalid trade status {trade['status']}")
    store.write_trade(trade)
    return trade


def observe_open_mark(store: TradingStore, trade: dict[str, Any], *, unrealized_pnl_usd: Any) -> dict[str, Any]:
    """Update MFE/MAE from a canonical mark observed while the trade is open."""
    if trade.get("status") != "open":
        return trade
    pnl = _money(unrealized_pnl_usd)
    if pnl is None:
        return trade
    updated = deepcopy(trade)
    mfe = updated.get("mfe_usd")
    mae = updated.get("mae_usd")
    updated["mfe_usd"] = pnl if mfe is None else max(float(mfe), pnl)
    updated["mae_usd"] = pnl if mae is None else min(float(mae), pnl)
    if updated != trade:
        store.write_trade(updated)
    return updated


def trade_digest(trade: dict[str, Any]) -> str:
    return sha256_json({k: v for k, v in trade.items() if k != "digest"})
