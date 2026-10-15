"""As-of eligibility for publisher observations.

Missing release instants are not eligible. A known timezone-aware instant is
compared exactly. Date-only publisher dates stay quarantined until the next
calendar day so a same-day print cannot be used before its unknown clock time.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

MISSING = "missing_release_instant"
NAIVE = "naive_release_quarantine"
TIME_UNKNOWN = "time_unknown_quarantine"
BEFORE = "before_release"
ELIGIBLE = "eligible"


def _as_date(value: date | datetime | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return None
        return value.astimezone(value.tzinfo).date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or "T" in text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_instant(value: datetime | str) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return None
        return value.astimezone(timezone.utc)
    text = str(value).strip()
    if "T" not in text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _as_of_instant(as_of: date | datetime) -> datetime | None:
    if isinstance(as_of, datetime):
        if as_of.tzinfo is None:
            return None
        return as_of.astimezone(timezone.utc)
    return datetime(as_of.year, as_of.month, as_of.day, tzinfo=timezone.utc)


def _as_of_calendar_date(as_of: date | datetime) -> date | None:
    if isinstance(as_of, datetime):
        if as_of.tzinfo is None:
            return None
        return as_of.astimezone(as_of.tzinfo).date()
    return as_of


def release_gate(
    release_date: date | datetime | str | None,
    as_of: date | datetime,
) -> str:
    """Classify whether ``release_date`` may be used at ``as_of``.

    Returns ``eligible`` or a quarantine/exclusion reason. Never invents a
    publication timestamp from the present clock.
    """
    if release_date is None or (isinstance(release_date, str) and not release_date.strip()):
        return MISSING
    if isinstance(as_of, datetime) and as_of.tzinfo is None:
        return NAIVE

    if isinstance(release_date, datetime) or (
        isinstance(release_date, str) and "T" in release_date
    ):
        if isinstance(release_date, datetime) and release_date.tzinfo is None:
            return NAIVE
        if isinstance(release_date, str) and "T" in release_date:
            probe = release_date.replace("Z", "+00:00")
            try:
                parsed = datetime.fromisoformat(probe)
            except ValueError:
                return MISSING
            if parsed.tzinfo is None:
                return NAIVE
        instant = _parse_instant(release_date)
        cutoff = _as_of_instant(as_of)
        if instant is None or cutoff is None:
            return MISSING
        if cutoff < instant:
            return BEFORE
        return ELIGIBLE

    released = _as_date(release_date)
    if released is None:
        return MISSING
    cutoff_day = _as_of_calendar_date(as_of)
    if cutoff_day is None:
        return NAIVE
    if cutoff_day <= released:
        return TIME_UNKNOWN
    return ELIGIBLE


def observation_eligible(
    release_date: date | datetime | str | None,
    as_of: date | datetime,
) -> bool:
    """True only when the publisher instant is known to be in the past at ``as_of``."""
    return release_gate(release_date, as_of) == ELIGIBLE


def filter_observations_by_asof(
    points: list[dict[str, Any]],
    as_of: date | datetime,
) -> list[dict[str, Any]]:
    """Drop points that are missing, quarantined, or not yet released at ``as_of``."""
    return [p for p in points if observation_eligible(p.get("release_date"), as_of)]
