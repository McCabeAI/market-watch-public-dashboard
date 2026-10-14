"""Turn verified BLS points into PCE observations. Raw PPI is not BEA-SA."""

from __future__ import annotations

from decimal import Decimal

from scripts.core_pce_release.history import shift_month

_MOM_MATCH = Decimal("0.0000001")


def _format(value: Decimal) -> str:
    return format(value, "f")


def _mom(points: dict[str, str], period: str, prior: str) -> Decimal | None:
    if period not in points or prior not in points:
        return None
    current = Decimal(points[period])
    base = Decimal(points[prior])
    if current <= 0 or base <= 0:
        return None
    return (current / base - 1) * 100


def _pair(points: dict[str, str], release: str, anchor: str, prior_anchor: str) -> tuple[str, str] | None:
    if release in points and anchor in points:
        return release, anchor
    if anchor in points and prior_anchor in points:
        return anchor, prior_anchor
    return None


def build_observations(registry: dict, points: dict[str, dict[str, str]], release: str) -> tuple[list[dict], list[dict]]:
    anchor = shift_month(release, -1)
    prior_anchor = shift_month(anchor, -1)
    observations: list[dict] = []
    gaps: list[dict] = []

    for entry in registry.get("verified") or []:
        series_id = entry["series_id"]
        series_points = points.get(series_id) or {}
        if entry.get("role") == "cpi_context_only":
            if release in series_points and anchor in series_points:
                observations.append(
                    {
                        "series_id": series_id,
                        "role": "cpi_context_only",
                        "period": release,
                        "index_level": series_points[release],
                        "prior_index_level": series_points[anchor],
                        "seasonal_status": "SA",
                        "source_family": "CPI",
                        "applied_to_estimate": False,
                    }
                )
            else:
                gaps.append(
                    {
                        "series_id": series_id,
                        "reason": "period_not_in_response",
                        "latest": max(series_points) if series_points else None,
                    }
                )
            continue
        chosen = _pair(series_points, release, anchor, prior_anchor)
        if chosen is None:
            gaps.append(
                {
                    "series_id": series_id,
                    "pce_lines": entry.get("pce_lines") or [],
                    "reason": "period_not_in_response",
                    "latest": max(series_points) if series_points else None,
                }
            )
            continue
        period, prior = chosen
        mom = _mom(series_points, period, prior)
        if mom is None:
            gaps.append({"series_id": series_id, "reason": "non_positive_index"})
            continue
        usable = bool(entry.get("usable_as_pce_rate")) and period == release
        for line in entry.get("pce_lines") or []:
            row = {
                "line": line,
                "period": period,
                "mom_percent": _format(mom),
                "index_level": series_points[period],
                "prior_index_level": series_points[prior],
                "source_family": entry["source_family"],
                "series_id": series_id,
                "bls_survey": entry.get("bls_survey"),
                "bls_seasonal": entry.get("bls_seasonal"),
                "bea_seasonal_status": entry.get("bea_seasonal_status"),
            }
            if usable:
                row["seasonal_status"] = "SA"
                row["applied_to_estimate"] = True
            else:
                row["role"] = "raw_bls_reference"
                row["seasonal_status"] = "BLS_SA" if entry.get("bls_seasonal") == "S" else "BLS_NSA"
                row["applied_to_estimate"] = False
                row["note"] = entry.get("not_a_pce_rate_because") or (
                    "Raw BLS print is not a BEA-adjusted PCE rate."
                )
            observations.append(row)

    for group in registry.get("ambiguous") or []:
        details = []
        moms: list[Decimal] = []
        chosen_period = None
        complete = True
        for candidate in group.get("candidates") or []:
            series_points = points.get(candidate["series_id"]) or {}
            chosen = _pair(series_points, release, anchor, prior_anchor)
            if chosen is None:
                complete = False
                break
            period, prior = chosen
            if chosen_period is None:
                chosen_period = period
            elif chosen_period != period:
                complete = False
                break
            mom = _mom(series_points, period, prior)
            if mom is None:
                complete = False
                break
            moms.append(mom)
            details.append(candidate["series_id"])
        if not complete or not moms or chosen_period is None:
            gaps.append(
                {
                    "pce_lines": group.get("pce_lines") or [],
                    "bea_source_text": group.get("bea_source_text"),
                    "reason": "ambiguous_aggregate_incomplete",
                }
            )
            continue
        if any(abs(value - moms[0]) > _MOM_MATCH for value in moms):
            gaps.append(
                {
                    "pce_lines": group.get("pce_lines") or [],
                    "bea_source_text": group.get("bea_source_text"),
                    "series_ids": details,
                    "reason": "ambiguous_aggregate_disagrees",
                }
            )
            continue
        for line in group.get("pce_lines") or []:
            observations.append(
                {
                    "role": "raw_bls_reference",
                    "line": line,
                    "period": chosen_period,
                    "mom_percent": _format(moms[0]),
                    "seasonal_status": "BLS_NSA",
                    "source_family": "PPI",
                    "series_id": details[0],
                    "series_ids": details,
                    "applied_to_estimate": False,
                    "note": (
                        "BLS products that share this BEA title printed the same MoM. "
                        "The rate is still raw BLS, not BEA-SA."
                    ),
                }
            )
    return observations, gaps
