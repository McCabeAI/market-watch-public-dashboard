"""Compact identity-specific learning memory derived from factual history."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from scripts.overnight.clock import isoformat, now_ny
from scripts.overnight.store import sha256_json
from scripts.trading.constants import (
    CALIBRATION_SAMPLE_NOTE,
    CONVICTION_BUCKETS,
    LESSON_CAP,
    LESSON_OPS,
    LESSON_STATUSES,
    MEMORY_SCHEMA_VERSION,
    POSTMORTEM_STATUSES,
    RECENT_CLOSED_CAP,
)
from scripts.trading.errors import OwnershipError, SchemaError
from scripts.trading.store import TradingStore, assert_identity


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def conviction_bucket(value: Any) -> str | None:
    if value in (None, ""):
        return None
    number = int(value)
    for name, (low, high) in CONVICTION_BUCKETS.items():
        if low <= number <= high:
            return name
    return None


def _hit_rate(wins: int, losses: int) -> float | None:
    denom = wins + losses
    if denom == 0:
        return None
    return round(wins / denom, 4)


def calibration_from_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [row for row in trades if row.get("status") == "closed"]
    wins = losses = breakeven = 0
    total_pnl = 0.0
    hold_samples: list[int] = []
    buckets = {name: {"count": 0, "wins": 0, "losses": 0, "pnl": 0.0} for name in CONVICTION_BUCKETS}
    by_asset: dict[str, dict[str, Any]] = {}
    for trade in closed:
        pnl = float(trade.get("realized_pnl_usd") or 0.0)
        total_pnl += pnl
        if pnl > 0.01:
            wins += 1
            outcome = "win"
        elif pnl < -0.01:
            losses += 1
            outcome = "loss"
        else:
            breakeven += 1
            outcome = "breakeven"
        if trade.get("holding_duration_seconds") is not None:
            hold_samples.append(int(trade["holding_duration_seconds"]))
        bucket = conviction_bucket(trade.get("conviction"))
        if bucket:
            buckets[bucket]["count"] += 1
            buckets[bucket]["pnl"] += pnl
            if outcome == "win":
                buckets[bucket]["wins"] += 1
            elif outcome == "loss":
                buckets[bucket]["losses"] += 1
        asset = trade.get("asset_class") or "unknown"
        asset_row = by_asset.setdefault(asset, {"count": 0, "total_realized_pnl_usd": 0.0})
        asset_row["count"] += 1
        asset_row["total_realized_pnl_usd"] = round(asset_row["total_realized_pnl_usd"] + pnl, 2)

    count = len(closed)
    bucket_out = {}
    for name, row in buckets.items():
        bucket_out[name] = {
            "count": row["count"],
            "hit_rate": _hit_rate(row["wins"], row["losses"]),
            "average_pnl_usd": None if row["count"] == 0 else round(row["pnl"] / row["count"], 2),
        }
    return {
        "closed_trade_count": count,
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "total_realized_pnl_usd": round(total_pnl, 2),
        "average_realized_pnl_usd": None if count == 0 else round(total_pnl / count, 2),
        "average_holding_seconds": None if not hold_samples else int(sum(hold_samples) / len(hold_samples)),
        "conviction_buckets": bucket_out,
        "by_asset_class": by_asset,
        "sample_note": CALIBRATION_SAMPLE_NOTE,
    }


def recent_closed(trades: list[dict[str, Any]], *, limit: int = RECENT_CLOSED_CAP) -> list[dict[str, Any]]:
    closed = [row for row in trades if row.get("status") == "closed"]
    closed.sort(key=lambda row: row.get("closed_at") or "", reverse=True)
    out = []
    for trade in closed[:limit]:
        out.append(
            {
                "trade_id": trade.get("trade_id"),
                "instrument": trade.get("instrument"),
                "side": trade.get("side"),
                "asset_class": trade.get("asset_class"),
                "realized_pnl_usd": trade.get("realized_pnl_usd"),
                "holding_duration_seconds": trade.get("holding_duration_seconds"),
                "opened_at": trade.get("opened_at"),
                "closed_at": trade.get("closed_at"),
                "conviction": trade.get("conviction"),
            }
        )
    return out


def open_position_context(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    open_rows = [row for row in trades if row.get("status") == "open"]
    return [
        {
            "trade_id": row.get("trade_id"),
            "position_id": row.get("position_id"),
            "instrument": row.get("instrument"),
            "side": row.get("side"),
            "asset_class": row.get("asset_class"),
            "current_notional_usd": row.get("current_notional_usd"),
            "entry_mark": row.get("entry_mark"),
            "opened_at": row.get("opened_at"),
            "conviction": row.get("conviction"),
        }
        for row in open_rows
    ]


def active_lessons(store: TradingStore, owner_type: str, owner_id: str, *, cap: int = LESSON_CAP) -> list[dict[str, Any]]:
    lessons = list(store.read_lessons(owner_type, owner_id).get("lessons") or [])
    active = [row for row in lessons if row.get("status") == "active"]
    active.sort(key=lambda row: (-int(row.get("reinforcement_count") or 0), row.get("updated_at") or ""))
    return active[:cap]


def outstanding_due(store: TradingStore, owner_type: str, owner_id: str, *, exclude_run_id: str | None = None) -> list[dict[str, Any]]:
    items = []
    for row in store.read_postmortems_due(owner_type, owner_id).get("items") or []:
        if row.get("status") != "due":
            continue
        if exclude_run_id and row.get("created_run_id") == exclude_run_id:
            continue
        items.append(row)
    return items


def build_memory_context(
    store: TradingStore,
    owner_type: str,
    owner_id: str,
    *,
    when: datetime | None = None,
    exclude_run_id: str | None = None,
) -> dict[str, Any]:
    assert_identity(owner_type, owner_id)
    store.ensure_initialized()
    trades = store.trades_for(owner_type, owner_id)
    lessons = active_lessons(store, owner_type, owner_id)
    due = outstanding_due(store, owner_type, owner_id, exclude_run_id=exclude_run_id)
    body = {
        "schema_version": MEMORY_SCHEMA_VERSION,
        "type": "IDENTITY_MEMORY_CONTEXT",
        "owner_type": owner_type,
        "owner_id": owner_id,
        "as_of": isoformat(now_ny(when)),
        "calibration": calibration_from_trades(trades),
        "recent_closed_trades": recent_closed(trades),
        "active_lessons": [
            {
                "lesson_id": row.get("lesson_id"),
                "text": row.get("text"),
                "trade_ids": row.get("trade_ids") or [],
                "postmortem_ids": row.get("postmortem_ids") or [],
                "reinforcement_count": row.get("reinforcement_count"),
            }
            for row in lessons
        ],
        "postmortems_due": [
            {
                "postmortem_id": row.get("postmortem_id"),
                "trade_id": row.get("trade_id"),
                "created_at": row.get("created_at"),
                "created_run_id": row.get("created_run_id"),
                "facts": row.get("facts") or {},
            }
            for row in due
        ],
        "open_positions": open_position_context(trades),
        "recent_funding_views": [
            event.get("funding_view")
            for event in reversed(store.read_journal(owner_type, owner_id).get("events") or [])
            if event.get("funding_view")
        ][:4],
    }
    digest = sha256_json({k: v for k, v in body.items() if k not in {"memory_context_sha256", "as_of"}})
    body["memory_context_sha256"] = digest
    store.write_context(owner_type, owner_id, body)
    return body


def create_postmortem_due(
    store: TradingStore,
    trade: dict[str, Any],
    *,
    run_id: str | None,
    when: datetime | None = None,
) -> dict[str, Any]:
    if trade.get("status") != "closed":
        raise SchemaError("postmortem_due requires a closed trade")
    owner_type, owner_id = trade["owner_type"], trade["owner_id"]
    due = store.read_postmortems_due(owner_type, owner_id)
    for item in due.get("items") or []:
        if item.get("trade_id") == trade["trade_id"] and item.get("status") == "due":
            return item
    item = {
        "postmortem_id": f"pmd-{uuid4().hex[:12]}",
        "trade_id": trade["trade_id"],
        "owner_type": owner_type,
        "owner_id": owner_id,
        "created_at": isoformat(now_ny(when)),
        "created_run_id": run_id,
        "status": "due",
        "facts": {
            "instrument": trade.get("instrument"),
            "side": trade.get("side"),
            "asset_class": trade.get("asset_class"),
            "realized_pnl_usd": trade.get("realized_pnl_usd"),
            "holding_duration_seconds": trade.get("holding_duration_seconds"),
            "entry_mark": trade.get("entry_mark"),
            "exit_mark": trade.get("exit_mark"),
            "opened_at": trade.get("opened_at"),
            "closed_at": trade.get("closed_at"),
            "conviction": trade.get("conviction"),
            "rationale_status": next(
                (
                    event.get("rationale_status")
                    for event in reversed(trade.get("events") or [])
                    if event.get("kind") == "CLOSE"
                ),
                None,
            ),
        },
    }
    due.setdefault("items", []).append(item)
    store.write_postmortems_due(owner_type, owner_id, due)
    return item


def _owned_trade(store: TradingStore, owner_type: str, owner_id: str, trade_id: str) -> dict[str, Any]:
    if not store.has_trade(trade_id):
        raise OwnershipError(f"{owner_id} referenced unknown trade_id {trade_id}")
    trade = store.read_trade(trade_id)
    if trade.get("owner_type") != owner_type or trade.get("owner_id") != owner_id:
        raise OwnershipError(f"{owner_id} does not own trade {trade_id}")
    return trade


def accept_postmortem(
    store: TradingStore,
    payload: dict[str, Any],
    *,
    owner_type: str,
    owner_id: str,
    run_id: str | None,
    when: datetime | None = None,
) -> dict[str, Any]:
    assert_identity(owner_type, owner_id)
    trade_id = payload.get("trade_id")
    if not isinstance(trade_id, str) or not trade_id:
        raise SchemaError("postmortem requires trade_id")
    trade = _owned_trade(store, owner_type, owner_id, trade_id)
    if trade.get("status") != "closed":
        raise SchemaError(f"postmortem is only accepted for a closed trade; {trade_id} is {trade.get('status')}")
    due_doc = store.read_postmortems_due(owner_type, owner_id)
    matched = None
    for item in due_doc.get("items") or []:
        if item.get("trade_id") == trade_id and item.get("status") == "due":
            matched = item
            item["status"] = "submitted"
            break
    record = {
        "postmortem_id": (matched or {}).get("postmortem_id") or f"pmr-{uuid4().hex[:12]}",
        "trade_id": trade_id,
        "owner_type": owner_type,
        "owner_id": owner_id,
        "at": isoformat(now_ny(when)),
        "run_id": run_id,
        "what_worked": _text(payload.get("what_worked")),
        "what_failed": _text(payload.get("what_failed")),
        "thesis_assessment": _text(payload.get("thesis_assessment")),
        "expression_assessment": _text(payload.get("expression_assessment")),
        "timing_assessment": _text(payload.get("timing_assessment")),
        "sizing_assessment": _text(payload.get("sizing_assessment")),
        "lesson": _text(payload.get("lesson")),
        "future_rule": _text(payload.get("future_rule") or payload.get("what_to_do_differently")),
        "tags": [tag for tag in (payload.get("tags") or []) if isinstance(tag, str) and tag.strip()],
        "facts": (matched or {}).get("facts") or {
            "realized_pnl_usd": trade.get("realized_pnl_usd"),
            "entry_mark": trade.get("entry_mark"),
            "exit_mark": trade.get("exit_mark"),
        },
    }
    if any(key in payload for key in ("realized_pnl_usd", "entry_mark", "exit_mark", "mfe_usd", "mae_usd")):
        raise SchemaError("postmortem cannot mutate canonical P&L or marks")
    submitted = store.read_postmortems(owner_type, owner_id)
    submitted.setdefault("items", []).append(record)
    store.write_postmortems(owner_type, owner_id, submitted)
    store.write_postmortems_due(owner_type, owner_id, due_doc)
    if record.get("lesson"):
        apply_memory_update(
            store,
            {
                "op": "add",
                "text": record["lesson"],
                "trade_ids": [trade_id],
                "postmortem_ids": [record["postmortem_id"]],
            },
            owner_type=owner_type,
            owner_id=owner_id,
            run_id=run_id,
            when=when,
        )
    return record


def apply_memory_update(
    store: TradingStore,
    update: dict[str, Any],
    *,
    owner_type: str,
    owner_id: str,
    run_id: str | None,
    when: datetime | None = None,
) -> dict[str, Any]:
    assert_identity(owner_type, owner_id)
    op = update.get("op")
    if op not in LESSON_OPS:
        raise SchemaError(f"memory update op must be one of {LESSON_OPS}")
    trade_ids = [tid for tid in (update.get("trade_ids") or []) if isinstance(tid, str)]
    postmortem_ids = [pid for pid in (update.get("postmortem_ids") or []) if isinstance(pid, str)]
    for trade_id in trade_ids:
        _owned_trade(store, owner_type, owner_id, trade_id)
    known_pm = {row.get("postmortem_id") for row in store.read_postmortems(owner_type, owner_id).get("items") or []}
    known_pm.update(row.get("postmortem_id") for row in store.read_postmortems_due(owner_type, owner_id).get("items") or [])
    for postmortem_id in postmortem_ids:
        if postmortem_id not in known_pm:
            raise OwnershipError(f"{owner_id} referenced unknown postmortem_id {postmortem_id}")
    if op == "add" and not trade_ids and not postmortem_ids:
        raise SchemaError("durable lessons must cite one or more owned trade_ids or postmortem_ids")
    text = _text(update.get("text"))
    lessons = store.read_lessons(owner_type, owner_id)
    rows = lessons.setdefault("lessons", [])
    stamp = isoformat(now_ny(when))
    if op == "add":
        if not text:
            raise SchemaError("add lesson requires text")
        lesson = {
            "lesson_id": f"les-{uuid4().hex[:12]}",
            "text": text,
            "trade_ids": trade_ids,
            "postmortem_ids": postmortem_ids,
            "status": "active",
            "reinforcement_count": 1,
            "created_at": stamp,
            "updated_at": stamp,
            "source_run_id": run_id,
        }
        rows.append(lesson)
        active = [row for row in rows if row.get("status") == "active"]
        if len(active) > LESSON_CAP:
            active.sort(key=lambda row: (int(row.get("reinforcement_count") or 0), row.get("updated_at") or ""))
            for extra in active[: len(active) - LESSON_CAP]:
                extra["status"] = "retired"
                extra["updated_at"] = stamp
        store.write_lessons(owner_type, owner_id, lessons)
        return lesson
    lesson_id = update.get("lesson_id")
    lesson = next((row for row in rows if row.get("lesson_id") == lesson_id), None)
    if lesson is None:
        raise SchemaError(f"unknown lesson_id {lesson_id}")
    if op == "reinforce":
        lesson["reinforcement_count"] = int(lesson.get("reinforcement_count") or 0) + 1
        lesson["updated_at"] = stamp
        if text:
            lesson["text"] = text
        for trade_id in trade_ids:
            if trade_id not in lesson["trade_ids"]:
                lesson["trade_ids"].append(trade_id)
        for postmortem_id in postmortem_ids:
            if postmortem_id not in lesson["postmortem_ids"]:
                lesson["postmortem_ids"].append(postmortem_id)
    elif op == "retire":
        lesson["status"] = "retired"
        lesson["updated_at"] = stamp
    if lesson.get("status") not in LESSON_STATUSES:
        raise SchemaError(f"invalid lesson status {lesson.get('status')}")
    store.write_lessons(owner_type, owner_id, lessons)
    return lesson


def apply_reflections(
    store: TradingStore,
    decision: dict[str, Any],
    *,
    owner_type: str,
    owner_id: str,
    run_id: str | None,
    when: datetime | None = None,
) -> dict[str, Any]:
    accepted = []
    for payload in decision.get("postmortems") or []:
        if not isinstance(payload, dict):
            continue
        accepted.append(
            accept_postmortem(
                store,
                payload,
                owner_type=owner_type,
                owner_id=owner_id,
                run_id=run_id,
                when=when,
            )
        )
    updates = []
    for payload in decision.get("memory_updates") or []:
        if not isinstance(payload, dict):
            continue
        updates.append(
            apply_memory_update(
                store,
                payload,
                owner_type=owner_type,
                owner_id=owner_id,
                run_id=run_id,
                when=when,
            )
        )
    return {"postmortems": accepted, "memory_updates": updates}
