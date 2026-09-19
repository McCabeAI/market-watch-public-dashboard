"""Per-identity structured decision journal. No hidden chain-of-thought."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from scripts.overnight.clock import isoformat, now_ny
from scripts.trading.constants import JOURNAL_EVENT_KINDS, SCHEMA_VERSION
from scripts.trading.errors import SchemaError
from scripts.trading.store import TradingStore, assert_identity


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def compact_actions(actions: list[Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for action in actions or []:
        if not isinstance(action, dict):
            continue
        rows.append(
            {
                "action": action.get("action"),
                "instrument": action.get("instrument"),
                "side": action.get("side"),
                "notional_usd": action.get("notional_usd"),
                "asset_class": action.get("asset_class"),
                "position_id": action.get("position_id"),
                "hedge_of": action.get("hedge_of"),
                "rationale": _text(action.get("rationale") or action.get("note") or action.get("thesis")),
                "rationale_status": action.get("rationale_status"),
                "exit_reason_category": action.get("exit_reason_category"),
            }
        )
    return rows


def record_event(
    store: TradingStore,
    *,
    owner_type: str,
    owner_id: str,
    kind: str,
    when: datetime | None = None,
    run_id: str | None = None,
    actions: list[Any] | None = None,
    rationale: str | None = None,
    thesis: str | None = None,
    invalidation: str | None = None,
    conviction: Any = None,
    linked_trade_ids: list[str] | None = None,
    linked_position_ids: list[str] | None = None,
    memory_context_sha256: str | None = None,
    evidence_cutoff: str | None = None,
    evidence_hash: str | None = None,
    overnight_run_id: str | None = None,
    trader_room_run_id: str | None = None,
    review_packet_id: str | None = None,
    source_ref: str | None = None,
    outcome_links: list[str] | None = None,
    postmortem_links: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assert_identity(owner_type, owner_id)
    if kind not in JOURNAL_EVENT_KINDS:
        raise SchemaError(f"unknown journal event kind {kind}")
    event = {
        "schema_version": SCHEMA_VERSION,
        "event_id": f"jde-{uuid4().hex[:16]}",
        "owner_type": owner_type,
        "owner_id": owner_id,
        "kind": kind,
        "at": isoformat(now_ny(when)),
        "run_id": run_id,
        "actions": compact_actions(actions),
        "rationale": _text(rationale),
        "thesis": _text(thesis),
        "invalidation": _text(invalidation),
        "conviction": None if conviction is None else int(conviction),
        "linked_trade_ids": list(linked_trade_ids or []),
        "linked_position_ids": list(linked_position_ids or []),
        "memory_context_sha256": memory_context_sha256,
        "outcome_links": list(outcome_links or []),
        "postmortem_links": list(postmortem_links or []),
        "provenance": {
            "overnight_run_id": overnight_run_id,
            "trader_room_run_id": trader_room_run_id,
            "review_packet_id": review_packet_id,
            "evidence_cutoff": evidence_cutoff,
            "evidence_hash": evidence_hash,
            "source_ref": source_ref,
        },
    }
    if extra:
        event["payload"] = extra
    journal = store.read_journal(owner_type, owner_id)
    journal.setdefault("events", []).append(event)
    store.write_journal(owner_type, owner_id, journal)
    return event
