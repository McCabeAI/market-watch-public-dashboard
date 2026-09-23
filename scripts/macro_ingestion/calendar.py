"""Release calendar evaluation with zoneinfo and country holidays."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from scripts.macro_ingestion.holidays import is_non_business_day


def schedule_parseable(release_rule: dict[str, Any] | None) -> bool:
    if not release_rule:
        return False
    kind = release_rule.get("kind")
    if kind == "country_local_schedule_required":
        dates = release_rule.get("dates") or []
        return bool(dates)
    if kind == "explicit_timestamp":
        return bool(release_rule.get("dates"))
    if kind == "local_datetime_list":
        return bool(release_rule.get("dates"))
    return False


def _rule_timezone(release_rule: dict[str, Any], series: dict[str, Any]) -> ZoneInfo:
    tz_name = (
        release_rule.get("timezone")
        or release_rule.get("local_timezone")
        or series.get("timezone")
        or "UTC"
    )
    return ZoneInfo(str(tz_name))


def _parse_instant(raw: str, tz: ZoneInfo) -> datetime:
    text = str(raw).strip()
    if text.endswith("Z"):
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    if "+" in text[10:] or "-" in text[10:]:
        return datetime.fromisoformat(text)
    # Naive local clock in the rule timezone.
    naive = datetime.fromisoformat(text)
    return naive.replace(tzinfo=tz)


def _roll_local_release(day: date, local_t: time, country: str, tz: ZoneInfo) -> datetime:
    cursor = day
    while is_non_business_day(country, cursor):
        cursor += timedelta(days=1)
    return datetime.combine(cursor, local_t, tzinfo=tz)


def _period_for_raw(release_rule: dict[str, Any], raw: str) -> str | None:
    mapping = release_rule.get("expected_periods") or {}
    if not isinstance(mapping, dict):
        return None
    period = mapping.get(raw)
    if period is None or period == "":
        return None
    return str(period)


def _release_slots(series: dict[str, Any]) -> list[dict[str, Any]]:
    """Each pinned publisher instant, with the reference period bound to that date."""
    release_rule = series.get("release_rule") or {}
    kind = release_rule.get("kind")
    country = str(series.get("country", "US"))
    tz = _rule_timezone(release_rule, series)
    dates = release_rule.get("dates") or []
    slots: list[dict[str, Any]] = []

    def _add(raw: str, instant: datetime) -> None:
        slots.append(
            {
                "raw": str(raw),
                "instant": instant,
                "period": _period_for_raw(release_rule, str(raw)),
            }
        )

    if kind == "explicit_timestamp":
        for raw in dates:
            _add(raw, _parse_instant(raw, tz))
    elif kind in {"local_datetime_list", "country_local_schedule_required"} and dates:
        for raw in dates:
            dt = _parse_instant(raw, tz)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz)
            local = dt.astimezone(tz)
            instant = _roll_local_release(
                local.date(), local.timetz().replace(tzinfo=None), country, tz
            )
            _add(raw, instant)
    return slots


def _release_instants(series: dict[str, Any]) -> list[datetime]:
    return [slot["instant"] for slot in _release_slots(series)]


def latest_due_release(spec: dict[str, Any], when: datetime) -> dict[str, Any] | None:
    """Latest publisher instant at or before `when`, plus its bound period if any.

    `period` is set only when `release_rule.expected_periods` names that date.
    A missing period means the date is due but not tied to a reference period.
    """
    release_rule = spec.get("release_rule") or {}
    kind = release_rule.get("kind")
    if kind == "country_local_schedule_required" and not (release_rule.get("dates") or []):
        return None
    if not schedule_parseable(release_rule):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=ZoneInfo("UTC"))
    latest: dict[str, Any] | None = None
    for slot in _release_slots(spec):
        if when >= slot["instant"] and (latest is None or slot["instant"] > latest["instant"]):
            latest = slot
    return latest


def release_due(spec: dict[str, Any], when: datetime) -> bool:
    """True when `when` is at or after a scheduled release instant for the series."""
    release_rule = spec.get("release_rule") or {}
    kind = release_rule.get("kind")
    if kind == "country_local_schedule_required" and not (release_rule.get("dates") or []):
        return False
    if not schedule_parseable(release_rule):
        return False

    if when.tzinfo is None:
        when = when.replace(tzinfo=ZoneInfo("UTC"))

    instants = _release_instants(spec)
    if not instants:
        return False

    latest_due: datetime | None = None
    for instant in instants:
        if when >= instant:
            if latest_due is None or instant > latest_due:
                latest_due = instant
    return latest_due is not None


def next_release_instant(series: dict[str, Any]) -> datetime | None:
    instants = sorted(_release_instants(series))
    return instants[-1] if instants else None
