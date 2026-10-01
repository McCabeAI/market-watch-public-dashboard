"""Fail-closed semantic checks for macro observation values."""

from __future__ import annotations

import math

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


def is_nz_employment_qoq_point(point: dict) -> bool:
    transformation = point.get("transformation")
    if transformation != "qoq_change_thousands_sa":
        return False
    if point.get("series_id") == "HLFQ.S1A3S":
        return True
    if point.get("catalog_id") == "NZ.Labor.employment":
        return True
    return False
