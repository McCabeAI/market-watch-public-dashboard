"""In-memory repair for Canada September 2026 CPI release provenance."""

from __future__ import annotations

from typing import Any

_SEPTEMBER_2026 = "2026-09"
_RELEASE_2026_10_19 = "2026-10-19"
_COMPONENT_KEYS = ("Inflation.headline", "Inflation.underlying")


def repair_ca_cpi_september_2026_provenance(history: dict[str, Any]) -> bool:
    """Correct September 2026 CPI release dates and gaps on ``history`` in place.

    Only ``Inflation.headline`` and ``Inflation.underlying`` are touched. Values,
    ``raw_level``, and pre-September ``release_date`` fields are left unchanged.
    Returns whether any field was modified.
    """
    components = history.get("components")
    if not isinstance(components, dict):
        return False
    changed = False
    for key in _COMPONENT_KEYS:
        component = components.get(key)
        if not isinstance(component, dict):
            continue
        observations = component.get("observations")
        if isinstance(observations, list):
            for row in observations:
                if not isinstance(row, dict):
                    continue
                if row.get("reference_period") != _SEPTEMBER_2026:
                    continue
                if row.get("release_date") != _RELEASE_2026_10_19:
                    row["release_date"] = _RELEASE_2026_10_19
                    changed = True
        gaps = component.get("gaps")
        if isinstance(gaps, list):
            filtered = [
                gap
                for gap in gaps
                if not (
                    isinstance(gap, dict)
                    and gap.get("expected_period") == _SEPTEMBER_2026
                    and gap.get("reason") == "not yet released"
                )
            ]
            if len(filtered) != len(gaps):
                component["gaps"] = filtered
                changed = True
            remaining_gaps = filtered
        else:
            remaining_gaps = gaps if isinstance(gaps, list) else []
        coverage = component.get("coverage")
        if not isinstance(coverage, dict):
            continue
        cov_updates: dict[str, Any] = {
            "latest_reference_period": _SEPTEMBER_2026,
            "latest_release_date": _RELEASE_2026_10_19,
            "gap_count": len(remaining_gaps),
            "status": "ok",
        }
        if key == "Inflation.headline":
            cov_updates["expected_periods_in_window"] = 13
            cov_updates["observed_periods_in_window"] = 13
        elif key == "Inflation.underlying":
            cov_updates["expected_periods_in_window"] = 13
            cov_updates["observed_periods_in_window"] = 26
        for field, value in cov_updates.items():
            if coverage.get(field) != value:
                coverage[field] = value
                changed = True
    return changed
