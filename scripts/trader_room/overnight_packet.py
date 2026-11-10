"""Project the frozen overnight evidence snapshot onto a single trader seat packet."""

from __future__ import annotations

from typing import Any

from scripts.dashboard_repair.calendar_packet import economic_calendar_from_frozen


def project_trader_seat_packet(snapshot: dict[str, Any], *, seat_id: str) -> dict[str, Any]:
    """Deep-copy shared evidence fields; seat-specific memory stays outside this packet."""
    calendar = economic_calendar_from_frozen(snapshot)
    return {
        "type": "OVERNIGHT_TRADER_SEAT_PACKET",
        "seat_id": seat_id,
        "overnight_run_id": snapshot.get("overnight_run_id"),
        "review_id": snapshot.get("review_id"),
        "packet_sha256": snapshot.get("packet_sha256"),
        "evidence_cutoff": snapshot.get("as_of"),
        "economic_calendar": calendar,
    }


__all__ = ["project_trader_seat_packet"]
