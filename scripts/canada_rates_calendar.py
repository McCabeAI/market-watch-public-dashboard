"""Canadian business-day calendar for Bank of Canada benchmark bond-yield freshness.

Stdlib only; no network. Mirrors the publication-lag helpers in japan_rates_data.py.
"""

from __future__ import annotations

from datetime import date, timedelta

CA_PUBLICATION_LAG_BUSINESS_DAYS = 1
CA_FRESHNESS_RULE = "canada_business_day_publication_lag"


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    shift = (weekday - first.weekday()) % 7
    return date(year, month, 1 + shift + 7 * (n - 1))


def _easter_sunday(year: int) -> date:
    """Anonymous Gregorian computus."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = ((h + ell - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _victoria_day(year: int) -> date:
    """Monday on or immediately before 24 May (Canadian Victoria Day)."""
    may24 = date(year, 5, 24)
    if may24.weekday() == 0:
        return may24
    return may24 - timedelta(days=(may24.weekday() + 7) % 7 or 7)


def _base_canada_publication_holidays(year: int) -> set[date]:
    good_friday = _easter_sunday(year) - timedelta(days=2)
    return {
        date(year, 1, 1),
        _nth_weekday(year, 2, 0, 3),
        good_friday,
        _victoria_day(year),
        date(year, 7, 1),
        _nth_weekday(year, 8, 0, 1),
        _nth_weekday(year, 9, 0, 1),
        date(year, 9, 30),
        _nth_weekday(year, 10, 0, 2),
        date(year, 11, 11),
        date(year, 12, 25),
        date(year, 12, 26),
    }


def canada_publication_holidays(year: int) -> set[date]:
    """Closed days on the Bank of Canada Valet benchmark bond-yield publication calendar."""
    holidays = _base_canada_publication_holidays(year)
    substitutes: set[date] = set()
    for holiday in sorted(holidays):
        if holiday.weekday() < 5:
            continue
        nxt = holiday + timedelta(days=1)
        while nxt.weekday() >= 5 or nxt in holidays or nxt in substitutes:
            nxt += timedelta(days=1)
        substitutes.add(nxt)
    return holidays | substitutes


def _holiday_set_for_day(day: date) -> set[date]:
    return (
        canada_publication_holidays(day.year - 1)
        | canada_publication_holidays(day.year)
        | canada_publication_holidays(day.year + 1)
    )


def is_canada_business_day(day: date) -> bool:
    if day.weekday() >= 5:
        return False
    return day not in _holiday_set_for_day(day)


def previous_canada_business_day(day: date) -> date:
    cursor = day - timedelta(days=1)
    while not is_canada_business_day(cursor):
        cursor -= timedelta(days=1)
    return cursor


def shift_canada_business_days(day: date, sessions: int) -> date:
    cursor = day
    for _ in range(sessions):
        cursor = previous_canada_business_day(cursor)
    return cursor


def canada_business_days_since(observation: date, today: date) -> int:
    """Canadian business days strictly after `observation` through `today` inclusive."""
    if today <= observation:
        return 0
    count = 0
    cursor = observation + timedelta(days=1)
    while cursor <= today:
        if is_canada_business_day(cursor):
            count += 1
        cursor += timedelta(days=1)
    return count


def minimum_fresh_ca_observation(
    today: date,
    *,
    publication_lag_business_days: int = CA_PUBLICATION_LAG_BUSINESS_DAYS,
) -> date:
    """Oldest Bank of Canada benchmark print that is still current on `today`.

    The anchor is the previous Canadian business day: today's close is not
    required on a session day, and a holiday uses the last completed session.
    The print of that anchor session may itself be unpublished for
    `publication_lag_business_days` further Canadian business sessions.
    """
    anchor = previous_canada_business_day(today)
    if publication_lag_business_days <= 0:
        return anchor
    return shift_canada_business_days(anchor, publication_lag_business_days)


def ca_observation_status(
    observation: date,
    today: date,
    *,
    publication_lag_business_days: int = CA_PUBLICATION_LAG_BUSINESS_DAYS,
) -> str:
    minimum = minimum_fresh_ca_observation(
        today,
        publication_lag_business_days=publication_lag_business_days,
    )
    return "ok" if observation >= minimum else "stale"
