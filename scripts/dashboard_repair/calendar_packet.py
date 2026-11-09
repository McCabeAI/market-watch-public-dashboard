"""Passthrough helpers for the pre-freeze economic calendar block."""

from __future__ import annotations

import copy
from datetime import date, datetime
from pathlib import Path
from typing import Any

from scripts.dashboard_repair.evidence_calendar import build_evidence_calendar
from scripts.dashboard_repair.release_contract import (
    EconomicReleaseEvent,
    event_to_slot,
    validate_event,
)


def collect_economic_calendar(as_of: datetime, *, root: Path) -> dict[str, Any]:
    return build_evidence_calendar(as_of, root=root, allow_network=False)


def economic_calendar_from_frozen(packet: dict[str, Any]) -> dict[str, Any]:
    block = packet.get("economic_calendar")
    if not isinstance(block, dict) or not block.get("content_hash"):
        raise ValueError("frozen packet is missing economic_calendar.content_hash")
    return copy.deepcopy(block)


def ensure_economic_calendar(
    payload: dict[str, Any],
    *,
    root: Path,
    as_of: datetime,
) -> dict[str, Any]:
    """Attach a calendar block when absent (freeze-time backfill only)."""
    block = payload.get("economic_calendar")
    if isinstance(block, dict) and block.get("content_hash"):
        return block
    built = build_evidence_calendar(as_of, root=root, allow_network=False)
    return copy.deepcopy(built)


def _event_dict_to_slot(event: dict[str, Any]) -> dict[str, Any]:
    local_date = date.fromisoformat(str(event["local_date"])[:10])
    clock = str(event.get("clock") or "tba")
    time_raw = event.get("time")
    local_time: str | None
    if clock == "tba" or not time_raw:
        local_time = None
    else:
        text = str(time_raw).strip()
        local_time = text if ":" in text else None
    ev = EconomicReleaseEvent(
        event_family=str(event.get("event_family") or ""),
        country=str(event.get("country") or ""),
        title=str(event.get("title") or event.get("name") or ""),
        publisher=str(event.get("publisher") or ""),
        local_date=local_date,
        local_time=local_time,
        timezone=str(event.get("timezone") or "UTC"),
        reference_period=str(event.get("reference_period") or ""),
        source_url=str(event.get("source_url") or ""),
        fetched_at=str(event.get("retrieved_at") or event.get("fetched_at") or ""),
        status=clock,
        series_ids=tuple(str(s) for s in (event.get("series_ids") or [])),
        provenance=str(event.get("provenance") or "frozen economic_calendar"),
        date_confidence=str(event.get("release_validity") or event.get("date_confidence") or "confirmed"),
    )
    validate_event(ev)
    return dict(event_to_slot(ev))


def events_dicts_to_slots(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_event_dict_to_slot(ev) for ev in events if isinstance(ev, dict)]


def release_model_from_economic_calendar(
    block: dict[str, Any],
    now: datetime,
    *,
    score_as_of: str = "2026-09-21",
    score_inputs_last_ingested_at: str | None = None,
) -> dict[str, Any]:
    from scripts.dashboard_repair.calendar_view import build_release_model

    slots = events_dicts_to_slots(list(block.get("events") or []))
    return build_release_model(
        now,
        score_as_of=score_as_of,
        score_inputs_last_ingested_at=score_inputs_last_ingested_at,
        fetched_slots=slots,
        schedule_fetch={"slots": slots, "countries": {}},
    )


__all__ = [
    "collect_economic_calendar",
    "economic_calendar_from_frozen",
    "ensure_economic_calendar",
    "events_dicts_to_slots",
    "release_model_from_economic_calendar",
]
