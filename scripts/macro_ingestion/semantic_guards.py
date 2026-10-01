"""Fail-closed semantic checks for macro observation values."""

from __future__ import annotations

import math
import re

_MONTH_PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")
_QUARTER_PERIOD_RE = re.compile(r"^(\d{4})-Q([1-4])$")

# Employment levels in HLFS Table 1 are ~1300–3000 (thousands); quarterly changes are tens.
QOQ_CHANGE_THOUSANDS_SA_MAX_ABS = 500.0


def qoq_change_thousands_sa_plausible(
    value: float,
    *,
    prior_level: float | None = None,
    latest_level: float | None = None,
) -> bool:
    """Reject employment levels masquerading as quarterly changes."""
    if not math.isfinite(value):
        return False
    if abs(value) >= QOQ_CHANGE_THOUSANDS_SA_MAX_ABS:
        return False
    if prior_level is not None and latest_level is not None:
        if not math.isfinite(prior_level) or not math.isfinite(latest_level):
            return False
        if abs(value) >= abs(prior_level) or abs(value) >= abs(latest_level):
            return False
        if abs(value - (latest_level - prior_level)) > 1e-6:
            return False
    return True


def implausible_nz_employment_qoq_values(document: dict) -> list[float]:
    """Return quarterly-change values in a history file that are employment levels."""
    components = document.get("components") or {}
    if not isinstance(components, dict):
        return []
    component = components.get("Labor.employment")
    if not isinstance(component, dict):
        return []
    if component.get("series_id") not in (None, "HLFQ.S1A3S"):
        return []
    bad: list[float] = []
    for obs in component.get("observations") or []:
        if not isinstance(obs, dict):
            continue
        if obs.get("transformation") != "qoq_change_thousands_sa":
            continue
        if obs.get("series_id") not in (None, "HLFQ.S1A3S"):
            continue
        try:
            value = float(obs["value"])
        except (KeyError, TypeError, ValueError):
            bad.append(float("nan"))
            continue
        if not qoq_change_thousands_sa_plausible(value):
            bad.append(value)
    return bad


def _period_sort_key(period: str) -> tuple[int, int] | None:
    if _MONTH_PERIOD_RE.match(period):
        year = int(period[:4])
        month = int(period[5:7])
        return year, month
    match = _QUARTER_PERIOD_RE.match(period)
    if match:
        year = int(match.group(1))
        quarter = int(match.group(2))
        return year, quarter * 3
    return None


def stale_pinned_artifact_error(payload: dict) -> str | None:
    """Block checked_unchanged when the read artifact is older than the official release."""
    official = payload.get("official_latest_period")
    artifact = payload.get("artifact_release_period")
    if not isinstance(official, str) or not isinstance(artifact, str):
        return None
    if not official or not artifact:
        return None
    official_key = _period_sort_key(official)
    artifact_key = _period_sort_key(artifact)
    if official_key is None or artifact_key is None:
        return None
    if official_key <= artifact_key:
        return None
    return f"stale_pinned_artifact:artifact={artifact}:official={official}"


def is_nz_employment_qoq_point(point: dict) -> bool:
    transformation = point.get("transformation")
    if transformation != "qoq_change_thousands_sa":
        return False
    if point.get("series_id") == "HLFQ.S1A3S":
        return True
    if point.get("catalog_id") == "NZ.Labor.employment":
        return True
    return False
