"""CME session calendar helpers and short-rate mark publication freshness.

``expected_session_if_published(day)`` is the weekday session label for *day*
(weekends roll back to the prior Friday). It is the session that would be
current only after CME publishes that day's official settlement.

``latest_publishable_official_session`` is the latest session date for which an
official CME settlement may exist for a given clock. At Monday 05:37
America/New_York, and on Saturday/Sunday, that date is the previous Friday — not
the calendar Monday.

Date-only callers (no ``now``) use a conservative rule: a weekday's settlement
is never assumed published on that same calendar date (Monday morning does not
count as a published Monday settlement).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

NY_TZ = ZoneInfo("America/New_York")
# Conservative floor: CME STIR finals are treated as possibly published after this ET hour.
CME_OFFICIAL_PUBLISH_HOUR_ET = 18

LOOKBACK_DAYS = 8
FRESH_MAX_AGE_DAYS = LOOKBACK_DAYS

Freshness = str  # "fresh" | "stale" | "unavailable"


def _roll_to_weekday(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _previous_weekday(d: date) -> date:
    return _roll_to_weekday(d - timedelta(days=1))


def latest_expected_cme_session(today: date) -> date:
    """Alias for :func:`expected_session_if_published` (backward compatible)."""
    return expected_session_if_published(today)


def expected_session_if_published(on_day: date) -> date:
    """Weekday session label for *on_day* (weekends map to previous Friday)."""
    return _roll_to_weekday(on_day)


def latest_publishable_official_session(
    *,
    today: date,
    now: datetime | None = None,
) -> date:
    """Latest CME session date for which an official settlement may exist."""
    if now is not None:
        local = now.astimezone(NY_TZ)
        clock_day = local.date()
        if clock_day.weekday() >= 5:
            return expected_session_if_published(clock_day)
        if local.hour < CME_OFFICIAL_PUBLISH_HOUR_ET:
            return _previous_weekday(clock_day)
        return expected_session_if_published(clock_day)
    if today.weekday() >= 5:
        return expected_session_if_published(today)
    # Date-only Monday: do not assume Monday's settlement is published yet.
    if today.weekday() == 0:
        return _previous_weekday(today)
    return expected_session_if_published(today)


def cme_publication_status(
    *,
    curve_key: str,
    observation: date | None,
    today: date,
    mark_kind: str,
    trade_date_verified: bool,
    now: datetime | None = None,
    source_health: str = "ok",
) -> dict[str, Any]:
    """Publication and eligibility fields for one short-rate mark."""
    clock_day = today
    if now is not None:
        clock_day = now.astimezone(NY_TZ).date()

    publishable = latest_publishable_official_session(today=clock_day, now=now)
    expected = expected_session_if_published(clock_day)

    stale_age_days: int | None = None
    if observation is not None:
        stale_age_days = (clock_day - observation).days

    official = mark_kind == "official_settlement" and trade_date_verified
    latest_available_official = official and observation is not None

    research_eligible = False
    if (
        latest_available_official
        and observation is not None
        and observation == publishable
        and stale_age_days is not None
        and 0 <= stale_age_days <= LOOKBACK_DAYS
    ):
        research_eligible = True

    execution_eligible = False
    if (
        now is not None
        and official
        and observation is not None
        and observation == expected
        and observation == publishable
        and stale_age_days is not None
        and stale_age_days == 0
    ):
        local = now.astimezone(NY_TZ)
        if local.hour >= CME_OFFICIAL_PUBLISH_HOUR_ET and clock_day.weekday() < 5:
            execution_eligible = True

    return {
        "latest_available_official": latest_available_official,
        "observed_session": observation.isoformat() if observation else None,
        "expected_session_if_published": expected.isoformat(),
        "publishable_session": publishable.isoformat(),
        "mark_kind": mark_kind,
        "source_health": source_health,
        "stale_age_days": stale_age_days,
        "trade_date_verified": bool(trade_date_verified),
        "research_eligible": research_eligible,
        "execution_eligible": execution_eligible,
    }


def _freshness_from_publication_status(
    *,
    curve_key: str,
    status: dict[str, Any],
    observation: date | None,
    today: date,
) -> Freshness:
    if curve_key in ("SR1", "SR3"):
        if observation is None:
            return "unavailable"
        if observation > today:
            return "unavailable"
        age = (today - observation).days
        if 0 <= age <= LOOKBACK_DAYS:
            return "fresh"
        return "unavailable"

    if curve_key in ("ESR", "ZQ", "EURIBOR", "EUS"):
        if status["execution_eligible"]:
            return "fresh"
        if status["research_eligible"]:
            if today.weekday() >= 5 or observation == today:
                return "fresh"
            return "stale"
        if (
            observation is not None
            and observation <= today
            and status.get("stale_age_days") is not None
            and 0 <= int(status["stale_age_days"]) <= LOOKBACK_DAYS
            and status["mark_kind"] == "official_settlement"
            and status["trade_date_verified"]
        ):
            return "stale"
        if (
            observation is not None
            and observation <= today
            and status.get("stale_age_days") is not None
            and 0 <= int(status["stale_age_days"]) <= LOOKBACK_DAYS
            and status["mark_kind"] not in ("official_settlement",)
        ):
            return "stale"
        return "unavailable"

    raise ValueError(f"unknown curve_key {curve_key!r}")


def classify_mark_freshness(
    *,
    curve_key: str,
    observation: date | None,
    today: date,
    mark_kind: str,
    trade_date_verified: bool,
    now: datetime | None = None,
    source_health: str = "ok",
) -> Freshness:
    status = cme_publication_status(
        curve_key=curve_key,
        observation=observation,
        today=today,
        mark_kind=mark_kind,
        trade_date_verified=trade_date_verified,
        now=now,
        source_health=source_health,
    )
    return _freshness_from_publication_status(
        curve_key=curve_key,
        status=status,
        observation=observation,
        today=today,
    )


def stamp_cme_publication_fields(
    *,
    curve_key: str,
    rows: list[dict[str, Any]],
    today: date,
    mark_kind: str,
    trade_date_verified: bool,
    now: datetime | None = None,
    source_health: str = "ok",
) -> tuple[str, dict[str, Any]]:
    """Attach session and freshness fields to rows; return freshness and status."""
    observed_raw = None
    if rows:
        observed_raw = rows[0].get("observation_date") or rows[0].get("as_of")
    observation = (
        date.fromisoformat(str(observed_raw)[:10]) if observed_raw else None
    )
    status = cme_publication_status(
        curve_key=curve_key,
        observation=observation,
        today=today,
        mark_kind=mark_kind,
        trade_date_verified=trade_date_verified,
        now=now,
        source_health=source_health,
    )
    freshness = _freshness_from_publication_status(
        curve_key=curve_key,
        status=status,
        observation=observation,
        today=today,
    )
    session_expected = status["expected_session_if_published"]
    for row in rows:
        row["session_expected"] = session_expected
        row["publishable_session"] = status["publishable_session"]
        row["freshness"] = freshness
        row["research_eligible"] = status["research_eligible"]
        row["execution_eligible"] = status["execution_eligible"]
    return freshness, status
