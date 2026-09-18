"""Parent-authored production briefs are INVALID and must not be used.

The prior run tr-20260917T231827Z-4ca9133b used this module to ghostwrite
the 14 standing-seat briefs instead of launching independent grok-4.6 seats.
That run is not a valid Trader Room result. The parent must launch the
standing seats and fail loudly if a required seat does not return.
"""

from __future__ import annotations

from typing import Any

from scripts.trader_room.constants import INVALID_PRIOR_LIVE_RUN_ID
from scripts.trader_room.errors import ParentAuthoredSeatError
from scripts.trader_room.provenance import INVALID_PRIOR_REASON

INVALID_RUN_ID = INVALID_PRIOR_LIVE_RUN_ID


def build_live_originals(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raise ParentAuthoredSeatError(
        "refusing to parent-author standing-seat originals from "
        f"{packet.get('run_id')}: {INVALID_PRIOR_REASON}"
    )


def build_live_rebuttals(
    packet: dict[str, Any],
    originals: dict[str, dict[str, Any]],
    assignments: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    raise ParentAuthoredSeatError(
        "refusing to parent-author rebuttals from "
        f"{packet.get('run_id')}: {INVALID_PRIOR_REASON}"
    )
