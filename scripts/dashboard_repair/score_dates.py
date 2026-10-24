"""Shared score-state date labels (calibration anchor vs input ingestion)."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any, Mapping

_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
_QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def _parse_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        stamp = datetime.fromisoformat(text)
        if stamp.tzinfo is not None:
            stamp = stamp.astimezone(timezone.utc)
        return stamp.date()
    except ValueError:
        pass
    head = text[:10]
    try:
        return date.fromisoformat(head)
    except ValueError:
        return None


def format_reference_period_through(period: str) -> str:
    text = str(period or "").strip()
    q = _QUARTER_RE.match(text)
    if q:
        return f"{q.group(1)} Q{q.group(2)}"
    m = _MONTH_RE.match(text)
    if m:
        month = int(m.group(2))
        if 1 <= month <= 12:
            return f"{_MONTHS[month - 1]} {m.group(1)}"
    return text


def format_calibration_anchor(value: object) -> str:
    if value in (None, ""):
        return ""
    day = _parse_date(value)
    if day is None:
        text = str(value).strip()
        month = re.fullmatch(r"(\d{4})-(\d{2})", text)
        if month:
            return f"{_MONTHS[int(month.group(2)) - 1]} {month.group(1)}"
        return text
    return f"{day.day} {_MONTHS[day.month - 1]} {day.year}"


def format_ingestion_day(value: object) -> str:
    day = _parse_date(value)
    if day is None:
        return format_calibration_anchor(value)
    return f"{day.day} {_MONTHS[day.month - 1]} {day.year}"


def score_dates_summary(scores: Mapping[str, Any], *, prefix: str = "Scores") -> str:
    anchor = scores.get("calibration_anchor_date") or scores.get("as_of")
    ingested = scores.get("score_inputs_last_ingested_at")
    cutoff = scores.get("scoring_cutoff") or scores.get("score_inputs_latest_reference_period")
    parts: list[str] = []
    if ingested:
        parts.append(f"inputs last ingested {format_ingestion_day(ingested)}")
    if cutoff:
        parts.append(f"reference periods through {format_reference_period_through(str(cutoff))}")
    if anchor:
        parts.append(f"calibration anchor {format_calibration_anchor(anchor)}")
    if not parts:
        if anchor:
            return f"Calibration anchor {format_calibration_anchor(anchor)}"
        return "Score dates not published in this build"
    head = f"{prefix}: " if prefix else ""
    return head + " · ".join(parts)


def scoreboard_asof_line(scores: Mapping[str, Any]) -> str:
    return score_dates_summary(scores, prefix="Published scores")


def header_score_line(scores: Mapping[str, Any]) -> str:
    return score_dates_summary(scores, prefix="Scores")
