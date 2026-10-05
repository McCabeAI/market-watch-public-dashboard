"""Injected clock for hermetic run_state tests (no wall clock)."""

from __future__ import annotations

from datetime import datetime


class FrozenClock:
    """Fixed aware datetime returned from every ``now()`` call."""

    def __init__(self, iso_timestamp: str) -> None:
        instant = datetime.fromisoformat(iso_timestamp)
        if instant.tzinfo is None:
            raise ValueError(f"FrozenClock requires timezone-aware ISO timestamp, got: {iso_timestamp}")
        self._instant = instant

    def now(self) -> datetime:
        return self._instant
