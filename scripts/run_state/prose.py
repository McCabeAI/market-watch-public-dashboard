"""Factual room caveat prose from canonical country lists and consistency checks."""

from __future__ import annotations

import re
from typing import Any, Dict, List

_NOT_DUE_PHRASE = "no new release was due"
_SCOPED_NOT_DUE_RE = re.compile(
    r"Latest verified vintages for (.+?) are carried forward; no new release was due\."
)
_CONFLICT_CARRY_REASONS = frozenset({"overdue_unverified", "unknown_calendar"})


def project_factual_prose(
    *,
    blocked_countries: list[str],
    carried_not_blocked: list[str],
    unknown_calendar_countries: list[str],
) -> str:
    parts: list[str] = []
    carried = [code for code in carried_not_blocked if code]
    blocked = [code for code in blocked_countries if code]
    unknown = [code for code in unknown_calendar_countries if code]
    if carried:
        parts.append(
            "Latest verified vintages for "
            + ", ".join(carried)
            + " are carried forward; no new release was due."
        )
    if blocked:
        parts.append(
            "New risk stays restricted in "
            + ", ".join(blocked)
            + " because a due release could not be verified."
        )
    if unknown:
        parts.append(
            "The release calendar for "
            + ", ".join(unknown)
            + " is unknown; a not-due claim is not allowed."
        )
    if not parts:
        return ""
    return " ".join(parts)


def _state_country(state: Dict[str, Any]) -> str | None:
    country = state.get("country")
    if country is None:
        series_id = state.get("series_id")
        if isinstance(series_id, str) and "." in series_id:
            return series_id.split(".", 1)[0]
    if isinstance(country, str) and country:
        return country
    return None


def _conflicting_states(states: list[dict]) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for state in states:
        if not isinstance(state, dict):
            continue
        country = _state_country(state)
        if not country:
            continue
        occurred = state.get("scheduled_release_occurred_by_cutoff")
        reason = state.get("carry_forward_reason")
        if occurred is True or occurred is None:
            out.append((country, state))
            continue
        if reason in _CONFLICT_CARRY_REASONS:
            out.append((country, state))
    return out


def _scoped_not_due_country_sets(text: str) -> list[frozenset[str]]:
    sets: list[frozenset[str]] = []
    for match in _SCOPED_NOT_DUE_RE.finditer(text):
        raw = match.group(1)
        codes = frozenset(code.strip() for code in raw.split(",") if code.strip())
        sets.append(codes)
    return sets


def _has_unscoped_not_due(text: str) -> bool:
    remaining = _SCOPED_NOT_DUE_RE.sub("", text)
    return _NOT_DUE_PHRASE in remaining


def assert_prose_consistent(text: str, states: list[dict]) -> None:
    if _NOT_DUE_PHRASE not in text:
        return
    conflicts = _conflicting_states(states)
    if not conflicts:
        return
    if _has_unscoped_not_due(text):
        raise ValueError("prose_conflict")
    scoped_sets = _scoped_not_due_country_sets(text)
    if not scoped_sets:
        raise ValueError("prose_conflict")
    scoped_union = frozenset().union(*scoped_sets)
    for country, _state in conflicts:
        if country in scoped_union:
            raise ValueError("prose_conflict")


__all__ = ["project_factual_prose", "assert_prose_consistent"]
