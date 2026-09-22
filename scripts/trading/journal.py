"""Per-identity structured decision journal. No hidden chain-of-thought."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

from scripts.overnight.clock import isoformat, now_ny
from scripts.overnight.store import sha256_json
from scripts.trading.constants import JOURNAL_EVENT_KINDS, SCHEMA_VERSION
from scripts.trading.errors import SchemaError
from scripts.trading.store import TradingStore, assert_identity

# Hidden / private CoT and runtime-only junk never enter the durable journal.
RUNTIME_ONLY_PAYLOAD_KEYS = frozenset(
    {
        "reasoning",
        "reasoning_content",
        "chain_of_thought",
        "hidden_reasoning",
        "private_thoughts",
        "scratchpad",
        "thinking",
        "tool_calls",
        "raw_response",
        "system_prompt",
        "internal",
        "evidence_packet",
    }
)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def new_event_id() -> str:
    return f"jde-{uuid4().hex[:16]}"


def decision_fingerprint(decision: dict[str, Any] | None) -> str:
    payload = decision or {}
    actions = payload.get("_original_actions") or payload.get("actions") or []
    return sha256_json(
        {
            "actions": [
                {
                    "action": row.get("action"),
                    "instrument": row.get("instrument"),
                    "side": row.get("side"),
                    "notional_usd": row.get("notional_usd"),
                    "position_id": row.get("position_id"),
                    "hedge_of": row.get("hedge_of"),
                    "price": row.get("price"),
                }
                for row in actions
                if isinstance(row, dict)
            ],
            "thesis": payload.get("thesis"),
            "rationale": payload.get("rationale"),
            "funding_view": payload.get("funding_view"),
            "memory_context_sha256": payload.get("memory_context_sha256"),
        }
    )


def durable_structured_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Keep the complete validated argument; drop hidden CoT and runtime-only junk."""
    if not isinstance(payload, dict):
        return {}
    return {key: deepcopy(value) for key, value in payload.items() if key not in RUNTIME_ONLY_PAYLOAD_KEYS}


def compact_actions(actions: list[Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for action in actions or []:
        if not isinstance(action, dict):
            continue
        row = {
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
            "result": action.get("result"),
            "blocked_reason": _text(action.get("blocked_reason")),
        }
        rows.append(row)
    return rows


def find_event(
    store: TradingStore,
    *,
    owner_type: str,
    owner_id: str,
    kind: str,
    run_id: str | None,
    review_packet_id: str | None = None,
    event_id: str | None = None,
    decision_fingerprint: str | None = None,
    review_id: str | None = None,
) -> dict[str, Any] | None:
    if event_id:
        for event in store.read_journal(owner_type, owner_id).get("events") or []:
            if event.get("event_id") == event_id:
                return event
        return None
    if not run_id and not review_id:
        return None
    for event in store.read_journal(owner_type, owner_id).get("events") or []:
        if event.get("kind") != kind:
            continue
        if run_id and event.get("run_id") != run_id:
            continue
        provenance = event.get("provenance") or {}
        if review_id is not None and provenance.get("review_id") != review_id:
            continue
        if review_packet_id and provenance.get("review_packet_id") != review_packet_id:
            continue
        if decision_fingerprint and event.get("decision_fingerprint") != decision_fingerprint:
            continue
        return event
    return None


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
    review_id: str | None = None,
    review_packet_id: str | None = None,
    source_ref: str | None = None,
    outcome_links: list[str] | None = None,
    postmortem_links: list[str] | None = None,
    extra: dict[str, Any] | None = None,
    event_id: str | None = None,
    decision_fingerprint: str | None = None,
    funding_view: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assert_identity(owner_type, owner_id)
    if kind not in JOURNAL_EVENT_KINDS:
        raise SchemaError(f"unknown journal event kind {kind}")
    existing = None
    if event_id:
        existing = find_event(
            store,
            owner_type=owner_type,
            owner_id=owner_id,
            kind=kind,
            run_id=run_id,
            event_id=event_id,
        )
    elif review_id:
        existing = find_event(
            store,
            owner_type=owner_type,
            owner_id=owner_id,
            kind=kind,
            run_id=run_id,
            review_id=review_id,
        )
    elif decision_fingerprint:
        existing = find_event(
            store,
            owner_type=owner_type,
            owner_id=owner_id,
            kind=kind,
            run_id=run_id,
            review_packet_id=review_packet_id,
            decision_fingerprint=decision_fingerprint,
        )
    else:
        existing = find_event(
            store,
            owner_type=owner_type,
            owner_id=owner_id,
            kind=kind,
            run_id=run_id,
            review_packet_id=review_packet_id,
        )
    reserved_id = (existing or {}).get("event_id") or event_id or new_event_id()
    event = {
        "schema_version": SCHEMA_VERSION,
        "event_id": reserved_id,
        "owner_type": owner_type,
        "owner_id": owner_id,
        "kind": kind,
        "at": (existing or {}).get("at") or isoformat(now_ny(when)),
        "run_id": run_id,
        "actions": compact_actions(actions),
        "rationale": _text(rationale),
        "thesis": _text(thesis),
        "invalidation": _text(invalidation),
        "conviction": None if conviction is None else int(conviction),
        "linked_trade_ids": list(linked_trade_ids or []),
        "linked_position_ids": list(linked_position_ids or []),
        "memory_context_sha256": memory_context_sha256,
        "decision_fingerprint": decision_fingerprint or (existing or {}).get("decision_fingerprint"),
        "funding_view": funding_view or (extra or {}).get("funding_view") or (existing or {}).get("funding_view"),
        "outcome_links": list(outcome_links or []),
        "postmortem_links": list(postmortem_links or []),
        "provenance": {
            "overnight_run_id": overnight_run_id,
            "trader_room_run_id": trader_room_run_id,
            "review_id": review_id,
            "review_packet_id": review_packet_id,
            "evidence_cutoff": evidence_cutoff,
            "evidence_hash": evidence_hash,
            "source_ref": source_ref,
        },
    }
    if extra:
        event["payload"] = extra
    journal = store.read_journal(owner_type, owner_id)
    rows = journal.setdefault("events", [])
    if existing:
        for index, row in enumerate(rows):
            if row.get("event_id") == existing.get("event_id"):
                rows[index] = event
                break
        else:
            rows.append(event)
    else:
        rows.append(event)
    store.write_journal(owner_type, owner_id, journal)
    return event
