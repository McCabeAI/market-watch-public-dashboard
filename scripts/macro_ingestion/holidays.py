"""Country holiday sets for 2025–2027 release-calendar rolling."""

from __future__ import annotations

from datetime import date, timedelta

# US federal — same observed dates as scripts/macro_freshness._HOLIDAYS (PR #108).
_US_FEDERAL: frozenset[date] = frozenset(
    {
        date(2025, 1, 1),
        date(2025, 1, 20),
        date(2025, 2, 17),
        date(2025, 5, 26),
        date(2025, 6, 19),
        date(2025, 7, 4),
        date(2025, 9, 1),
        date(2025, 10, 13),
        date(2025, 11, 11),
        date(2025, 11, 27),
        date(2025, 12, 25),
        date(2026, 1, 1),
        date(2026, 1, 19),
        date(2026, 2, 16),
        date(2026, 5, 25),
        date(2026, 6, 19),
        date(2026, 7, 3),
        date(2026, 9, 7),
        date(2026, 10, 12),
        date(2026, 11, 11),
        date(2026, 11, 26),
        date(2026, 12, 25),
        date(2027, 1, 1),
    }
)


def _easter_sunday(year: int) -> date:
    """Anonymous Gregorian algorithm."""
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
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    """weekday: Monday=0 .. Sunday=6; n=1 first such weekday in month."""
    d = date(year, month, 1)
    shift = (weekday - d.weekday()) % 7
    first = d + timedelta(days=shift)
    return first + timedelta(weeks=n - 1)


def _monday_before(year: int, month: int, day: int) -> date:
    target = date(year, month, day)
    return target - timedelta(days=(target.weekday() + 1) % 7)


def _canada_federal(year: int) -> set[date]:
    easter = _easter_sunday(year)
    out = {
        date(year, 1, 1),
        easter - timedelta(days=2),  # Good Friday
        _monday_before(year, 5, 25),  # Victoria Day
        date(year, 7, 1),
        _nth_weekday_of_month(year, 9, 0, 1),  # Labour Day
        date(year, 9, 30),  # National Day for Truth and Reconciliation
        _nth_weekday_of_month(year, 10, 0, 2),  # Thanksgiving
        date(year, 11, 11),
        date(year, 12, 25),
        date(year, 12, 26),
    }
    return out


def _australia_national(year: int) -> set[date]:
    easter = _easter_sunday(year)
    out = {
        date(year, 1, 1),
        date(year, 1, 26),
        easter - timedelta(days=2),
        easter + timedelta(days=1),
        date(year, 4, 25),
        date(year, 12, 25),
        date(year, 12, 26),
    }
    # King's Birthday — second Monday in June (national proxy for release rolling).
    out.add(_nth_weekday_of_month(year, 6, 0, 2))
    return out


def _nz_national(year: int) -> set[date]:
    easter = _easter_sunday(year)
    out = {
        date(year, 1, 1),
        date(year, 1, 2),
        date(year, 2, 6),
        easter - timedelta(days=2),
        easter + timedelta(days=1),
        date(year, 4, 25),
        _nth_weekday_of_month(year, 6, 0, 1),  # King's Birthday
        _nth_weekday_of_month(year, 10, 0, 4),  # Labour Day
        date(year, 12, 25),
        date(year, 12, 26),
    }
    return out


# ECB TARGET2 closing days (published schedule, 2025–2027 subset).
_ECB_TARGET2_FIXED: dict[int, set[date]] = {
    2025: {
        date(2025, 1, 1),
        date(2025, 4, 18),
        date(2025, 4, 21),
        date(2025, 5, 1),
        date(2025, 12, 25),
        date(2025, 12, 26),
    },
    2026: {
        date(2026, 1, 1),
        date(2026, 4, 3),
        date(2026, 4, 6),
        date(2026, 5, 1),
        date(2026, 12, 25),
        date(2026, 12, 26),
    },
    2027: {
        date(2027, 1, 1),
        date(2027, 4, 26),
        date(2027, 4, 29),
        date(2027, 5, 1),
        date(2027, 12, 27),  # Christmas observed
        date(2027, 12, 28),  # Boxing Day observed
    },
}


def _japan_national(year: int) -> set[date]:
    """Fixed national holidays; substitute days omitted (conservative for rolling)."""
    return {
        date(year, 1, 1),
        date(year, 1, 2),
        date(year, 1, 3),
        date(year, 2, 11),
        date(year, 2, 23),
        date(year, 3, 20) if year == 2025 else date(year, 3, 21) if year == 2026 else date(year, 3, 21),
        date(year, 4, 29),
        date(year, 5, 3),
        date(year, 5, 4),
        date(year, 5, 5),
        date(year, 7, 21) if year == 2025 else date(year, 7, 20) if year == 2026 else date(year, 7, 19),
        date(year, 8, 11),
        date(year, 9, 15) if year == 2025 else date(year, 9, 21) if year == 2026 else date(year, 9, 20),
        date(year, 9, 23) if year == 2025 else date(year, 9, 22) if year == 2026 else date(year, 9, 23),
        date(year, 10, 13) if year == 2025 else date(year, 10, 12) if year == 2026 else date(year, 10, 11),
        date(year, 11, 3),
        date(year, 11, 23),
        date(year, 12, 23) if year == 2025 else date(year, 12, 23),
    }


def _build_sets() -> dict[str, frozenset[date]]:
    years = (2025, 2026, 2027)
    ca: set[date] = set()
    au: set[date] = set()
    nz: set[date] = set()
    ea: set[date] = set()
    jp: set[date] = set()
    for y in years:
        ca |= _canada_federal(y)
        au |= _australia_national(y)
        nz |= _nz_national(y)
        ea |= _ECB_TARGET2_FIXED.get(y, set())
        jp |= _japan_national(y)
    return {
        "US": _US_FEDERAL,
        "CA": frozenset(ca),
        "AU": frozenset(au),
        "NZ": frozenset(nz),
        "EA": frozenset(ea),
        "JP": frozenset(jp),
    }


HOLIDAYS_BY_COUNTRY: dict[str, frozenset[date]] = _build_sets()


def is_holiday(country: str, day: date) -> bool:
    key = country.upper()
    if key not in HOLIDAYS_BY_COUNTRY:
        return False
    return day in HOLIDAYS_BY_COUNTRY[key]


def is_weekend(day: date) -> bool:
    return day.weekday() >= 5


def is_non_business_day(country: str, day: date) -> bool:
    return is_weekend(day) or is_holiday(country, day)
