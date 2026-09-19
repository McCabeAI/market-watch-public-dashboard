"""Backfill durable trading state from current canonical books only."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from scripts.overnight.clock import now_ny, parse_iso
from scripts.overnight.constants import STANDING_SEATS
from scripts.pm.constants import PM_IDS
from scripts.trading.ledger import find_trade_by_position, record_lifecycle_event
from scripts.trading.memory import build_memory_context
from scripts.trading.store import TradingStore


def _stamp(value: Any, fallback: datetime) -> datetime:
    if not value:
        return fallback
    try:
        return parse_iso(str(value))
    except (TypeError, ValueError):
        return fallback


def _backfill_open_positions(
    store: TradingStore,
    *,
    owner_type: str,
    owner_id: str,
    positions: list[dict[str, Any]],
    history: list[dict[str, Any]],
    when: datetime,
) -> None:
    """Create OPEN records for live positions. Never invent closed trades."""
    for position in positions:
        position_id = position.get("position_id")
        if not position_id:
            continue
        if find_trade_by_position(store, owner_type=owner_type, owner_id=owner_id, position_id=position_id):
            continue
        opened = _stamp(position.get("opened_at"), when)
        record_lifecycle_event(
            store,
            owner_type=owner_type,
            owner_id=owner_id,
            kind="OPEN",
            position_id=position_id,
            when=opened,
            run_id=position.get("opened_run_id"),
            instrument=position.get("instrument"),
            asset_class=position.get("asset_class"),
            side=position.get("side"),
            mark=position.get("entry_price"),
            mark_source=position.get("entry_price_source"),
            mark_as_of=position.get("entry_price_as_of"),
            notional_change_usd=position.get("notional_usd"),
            current_notional_usd=position.get("notional_usd"),
            rationale=position.get("thesis"),
            rationale_status="present" if position.get("thesis") else "not_required",
            thesis=position.get("thesis"),
            invalidation=position.get("invalidation"),
            paper_expression=position.get("paper_expression"),
            locked_expression_family=position.get("locked_expression_family"),
            hedge_of_position_id=position.get("hedge_of"),
        )
    # History rows may prove later ADD/REDUCE on still-open positions. Skip CLOSE
    # rows: the live book no longer has those positions, so a closed trade would
    # be fabricated from incomplete remnants.
    for row in history:
        if row.get("result") != "applied":
            continue
        kind = row.get("action")
        if kind not in {"ADD", "REDUCE"}:
            continue
        position_id = row.get("position_id")
        if not position_id:
            continue
        trade = find_trade_by_position(store, owner_type=owner_type, owner_id=owner_id, position_id=position_id)
        if trade is None or trade.get("status") != "open":
            continue
        already = {
            (event.get("kind"), event.get("run_id"), event.get("notional_change_usd"))
            for event in trade.get("events") or []
        }
        key = (kind, row.get("overnight_run_id") or row.get("run_id"), row.get("notional_usd"))
        if key in already:
            continue
        record_lifecycle_event(
            store,
            owner_type=owner_type,
            owner_id=owner_id,
            kind=kind,
            position_id=position_id,
            when=_stamp(row.get("at"), when),
            run_id=row.get("overnight_run_id") or row.get("run_id"),
            mark=row.get("price"),
            mark_source=row.get("paper_mid_source"),
            mark_as_of=row.get("paper_mid_as_of"),
            notional_change_usd=row.get("notional_usd"),
            realized_increment_usd=row.get("realized_pnl_usd"),
            rationale=row.get("note"),
            rationale_status="present" if row.get("note") else "not_required",
        )


def backfill_from_books(
    store: TradingStore,
    *,
    trader_books: dict[str, Any] | None = None,
    pm_books: dict[str, Any] | None = None,
    when: datetime | None = None,
) -> dict[str, Any]:
    """Initialize identities and reconstruct only fields proven by live books."""
    stamp = now_ny(when)
    store.ensure_initialized(when=stamp)
    if trader_books:
        for seat in STANDING_SEATS:
            item = (trader_books.get("seats") or {}).get(seat) or {}
            _backfill_open_positions(
                store,
                owner_type="trader",
                owner_id=seat,
                positions=list(item.get("positions") or []),
                history=list(item.get("history") or []),
                when=stamp,
            )
            build_memory_context(store, "trader", seat, when=stamp)
    if pm_books:
        for pm_id in PM_IDS:
            item = (pm_books.get("pms") or {}).get(pm_id) or {}
            _backfill_open_positions(
                store,
                owner_type="pm",
                owner_id=pm_id,
                positions=list(item.get("positions") or []),
                history=list(item.get("history") or []),
                when=stamp,
            )
            build_memory_context(store, "pm", pm_id, when=stamp)
    if not trader_books and not pm_books:
        from scripts.trading.constants import ALL_IDENTITIES

        for owner_type, owner_id in ALL_IDENTITIES:
            build_memory_context(store, owner_type, owner_id, when=stamp)
    return store.read_index()
