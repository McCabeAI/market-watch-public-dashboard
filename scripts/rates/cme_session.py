"""CME session calendar helpers and short-rate mark freshness classification.

``latest_expected_cme_session(today)`` is the latest Monday–Friday on or before
``today``: weekends roll back to the prior Friday, and this repo does not
maintain a verified CME holiday calendar, so a weekday that is a CME holiday is
still treated as an expected session day (a settlement from before that weekday
is stale relative to that day, not freshly labeled as that session).
"""

from __future__ import annotations

from datetime import date, timedelta

LOOKBACK_DAYS = 8
FRESH_MAX_AGE_DAYS = LOOKBACK_DAYS

Freshness = str  # "fresh" | "stale" | "unavailable"


def latest_expected_cme_session(today: date) -> date:
    """Latest weekday on or before *today* (weekends map to previous Friday)."""
    d = today
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def classify_mark_freshness(
    *,
    curve_key: str,
    observation: date | None,
    today: date,
    mark_kind: str,
    trade_date_verified: bool,
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

    # ZQ and EURIBOR use the same official-versus-delayed rule as ESR.
    # A weekday CME holiday is still an expected session: this repo has no
    # verified holiday calendar, so a pre-holiday print is stale, not fresh.
    if curve_key in ("ESR", "ZQ", "EURIBOR"):
        if (
            mark_kind == "official_settlement"
            and trade_date_verified
            and observation is not None
            and observation == latest_expected_cme_session(today)
        ):
            return "fresh"
        if observation is not None and observation <= today:
            age = (today - observation).days
            if 0 <= age <= LOOKBACK_DAYS:
                return "stale"
        return "unavailable"

    raise ValueError(f"unknown curve_key {curve_key!r}")
