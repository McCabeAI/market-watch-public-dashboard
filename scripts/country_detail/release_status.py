"""Country Detail release state from the macro-ingestion calendar.

This module does not invent publication lags or a second date table. It calls
``scripts.macro_ingestion.calendar`` and, when the projected source already
carries ``release_due`` or ``due_missing``, reuses that flag.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from scripts.country_detail import policy
from scripts.macro_ingestion.calendar import latest_due_release, schedule_parseable

_EXPLICIT_DUE_STATUSES = frozenset({"due_missing", "release_due_missing"})
_CATALOG_INDEX: dict[str, dict[str, Any]] | None = None


def _catalog_index() -> dict[str, dict[str, Any]]:
    global _CATALOG_INDEX
    if _CATALOG_INDEX is None:
        from scripts.macro_ingestion.contract import load_catalog

        _CATALOG_INDEX = {str(row["id"]): row for row in load_catalog()["series"]}
    return _CATALOG_INDEX


def _as_of_datetime(as_of: str) -> datetime | None:
    text = str(as_of or "").strip()
    if not text:
        return None
    try:
        if len(text) == 10:
            # Date-only evaluation includes that UTC calendar day.
            return datetime.fromisoformat(text + "T23:59:59+00:00")
        if text.endswith("Z"):
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _covers(held: str, expected: str) -> bool:
    if not held or not expected:
        return False
    return policy.period_sort_key(held) >= policy.period_sort_key(expected)


def _publisher_date(observation: Mapping[str, Any]) -> date | None:
    raw = observation.get("release_date")
    if raw is None or raw == "":
        return None
    try:
        return date.fromisoformat(str(raw).strip()[:10])
    except ValueError:
        return None


def _series_spec(observation: Mapping[str, Any]) -> dict[str, Any] | None:
    """Observation overlay, otherwise the merged catalog row for ``catalog_id``."""
    rule = observation.get("release_rule")
    if isinstance(rule, dict):
        spec: dict[str, Any] = {
            "id": observation.get("catalog_id") or observation.get("series_id"),
            "country": observation.get("country") or "US",
            "timezone": observation.get("timezone") or rule.get("timezone") or "UTC",
            "release_rule": rule,
        }
        if isinstance(observation.get("known_fixture"), dict):
            spec["known_fixture"] = observation["known_fixture"]
        return spec
    catalog_id = observation.get("catalog_id")
    if not catalog_id:
        return None
    return _catalog_index().get(str(catalog_id))


def _explicit_repository_due(observation: Mapping[str, Any]) -> bool | None:
    """Reuse stored launch/ingestion due state. None means the field is absent."""
    status = str(observation.get("status") or observation.get("ingestion_status") or "")
    if status in _EXPLICIT_DUE_STATUSES:
        return True
    if "release_due" not in observation:
        return None
    if not observation.get("release_due"):
        return False
    due_period = observation.get("due_period")
    held = str(observation.get("reference_period") or "")
    if due_period and _covers(held, str(due_period)):
        return False
    return True


def _rule_timezone(spec: Mapping[str, Any]) -> ZoneInfo:
    rule = spec.get("release_rule") or {}
    name = rule.get("timezone") or rule.get("local_timezone") or spec.get("timezone") or "UTC"
    return ZoneInfo(str(name))


def assess_release(observation: Mapping[str, Any], *, as_of: str) -> dict[str, Any]:
    """Whether a successor release is due and the expected observation is absent.

    ``release_calendar`` is ``explicit``, ``unavailable``, ``not_due``,
    ``satisfied``, or ``due``. ``due`` is the only value that marks the row
    ``due_late``. An unparseable schedule stays ``unavailable`` and does not
    invent a deadline.
    """
    explicit = _explicit_repository_due(observation)
    if explicit is not None:
        return {"due": explicit, "release_calendar": "explicit"}

    spec = _series_spec(observation)
    rule = (spec or {}).get("release_rule") if spec else None
    if spec is None or not schedule_parseable(rule if isinstance(rule, dict) else None):
        return {"due": False, "release_calendar": "unavailable"}

    when = _as_of_datetime(as_of)
    if when is None:
        return {"due": False, "release_calendar": "unavailable"}

    due_slot = latest_due_release(spec, when)
    if due_slot is None:
        return {"due": False, "release_calendar": "not_due"}

    held = str(observation.get("reference_period") or "")
    fixture = (spec.get("known_fixture") or {}).get("period")
    fixture_period = str(fixture) if fixture else ""
    # Same order as scripts/macro_ingestion/runner.py: a known fixture period
    # that is not in hand is due_missing once a release instant has been reached.
    if fixture_period and not _covers(held, fixture_period):
        return {"due": True, "release_calendar": "due"}

    bound = due_slot.get("period")
    if bound:
        if _covers(held, str(bound)):
            return {"due": False, "release_calendar": "satisfied"}
        return {"due": True, "release_calendar": "due"}

    if fixture_period and _covers(held, fixture_period):
        return {"due": False, "release_calendar": "satisfied"}

    # The instant is authoritative and expected_periods did not name it.
    # The successor is present only when this print's publisher date is on or
    # after that instant. Retrieval time is not a publisher date.
    published = _publisher_date(observation)
    if published is not None:
        slot_day = due_slot["instant"].astimezone(_rule_timezone(spec)).date()
        if published >= slot_day:
            return {"due": False, "release_calendar": "satisfied"}
    return {"due": True, "release_calendar": "due"}
