"""As-of eligibility for publisher observations (release_date gate)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any


def _as_date(value: date | datetime | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    if "T" in text:
        text = text.split("T", 1)[0]
    return date.fromisoformat(text[:10])


def observation_eligible(
    release_date: date | datetime | str | None,
    as_of: date | datetime,
) -> bool:
    """True when the observation may be emitted at ``as_of``."""
    rel = _as_date(release_date)
    cutoff = _as_date(as_of)
    assert cutoff is not None
    if rel is None:
        return True
    return rel <= cutoff


def filter_observations_by_asof(
    points: list[dict[str, Any]],
    as_of: date | datetime,
) -> list[dict[str, Any]]:
    """Drop points whose publisher ``release_date`` is after ``as_of``."""
    return [p for p in points if observation_eligible(p.get("release_date"), as_of)]
