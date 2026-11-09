"""Attach frozen overnight fields to a PM review packet."""

from __future__ import annotations

from typing import Any

from scripts.dashboard_repair.calendar_packet import economic_calendar_from_frozen


def attach_economic_calendar(packet: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    packet = dict(packet)
    packet["economic_calendar"] = economic_calendar_from_frozen(snapshot)
    return packet


__all__ = ["attach_economic_calendar"]
