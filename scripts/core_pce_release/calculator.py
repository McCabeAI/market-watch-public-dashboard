"""First-order CPI/PPI/mixed/implicit bridge. One function for flash and detailed."""

from __future__ import annotations

from decimal import Decimal

from scripts.core_pce_release.history import (
    annualized,
    break_even_mom,
    project_level,
    rates_ending,
    shift_month,
)
from scripts.core_pce_release.observations import accept_observation
from scripts.core_pce_release.verdict import classify_momentum

UNRESOLVED_ABS_WEIGHT_LIMIT = Decimal("0.0025")
CARRY_SENSITIVITY_PP = (Decimal("0.25"), Decimal("0.50"))
HORIZONS = (3, 6, 9)


def _text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def _cpi_context(observations: list[dict]) -> dict | None:
    for row in observations:
        if row.get("series_id") != "CUSR0000SA0L1E":
            continue
        level = row.get("index_level")
        prior = row.get("prior_index_level")
        if level in (None, "") or prior in (None, ""):
            continue
        mom = (Decimal(str(level)) / Decimal(str(prior)) - 1) * 100
        return {
            "series_id": "CUSR0000SA0L1E",
            "role": "cpi_context_only",
            "used_in_core_pce": False,
            "index_level": str(level),
            "prior_index_level": str(prior),
            "mom_percent": format(mom, "f"),
        }
    return None


def calculate(
    components: list[dict],
    levels: dict[str, Decimal],
    target_period: str,
    observations: list[dict],
    *,
    residual_weight: Decimal = Decimal(0),
) -> dict:
    anchor = shift_month(target_period, -1)
    anchor_level = levels.get(anchor)
    grouped: dict[int, list[dict]] = {}
    rejected: list[dict] = []
    for row in observations:
        if row.get("series_id") == "CUSR0000SA0L1E":
            rejected.append(
                {
                    "reason": "cpi_context_only",
                    "series_id": row.get("series_id"),
                    "line": row.get("line"),
                }
            )
            continue
        if row.get("series_id") and row.get("line") in (None, ""):
            rejected.append({"reason": "not_a_pce_line", "series_id": row.get("series_id")})
            continue
        period = str(row.get("period") or "")
        if period not in {target_period, anchor}:
            rejected.append({"line": row.get("line"), "period": period, "reason": "stale_period"})
            continue
        try:
            line = int(row["line"])
        except (KeyError, TypeError, ValueError):
            rejected.append({"reason": "line_missing"})
            continue
        grouped.setdefault(line, []).append(row)

    resolved_rows: list[dict] = []
    unresolved_abs = abs(residual_weight)
    resolved_signed = Decimal(0)
    carry_abs = Decimal(0)
    resolved_contribution = Decimal(0)

    for component in components:
        weight = Decimal(component["weight_share"])
        line = int(component["line"])
        chosen_mom = None
        reason = "no_observation"
        assumption = None
        candidates = grouped.get(line, [])
        target_rows = [row for row in candidates if str(row.get("period")) == target_period]
        prior_rows = [row for row in candidates if str(row.get("period")) == anchor]
        pool = target_rows or prior_rows
        assumption = "observed" if target_rows else "carry_prior_mom" if prior_rows else None
        if len(pool) > 1:
            reason = "duplicate_observation"
            pool = []
        if pool:
            mom, error = accept_observation(component, pool[0])
            if error or mom is None:
                reason = error or "missing_mom"
                if assumption == "carry_prior_mom" and error == "index_level_without_base":
                    reason = "price_level_is_not_a_mom_carry"
            else:
                chosen_mom = mom
                reason = None
        status = "UNRESOLVED"
        contribution = None
        if chosen_mom is not None and assumption is not None:
            status = "CARRY" if assumption == "carry_prior_mom" else "OBSERVED"
            contribution = weight * chosen_mom
            resolved_contribution += contribution
            resolved_signed += weight
            if status == "CARRY":
                carry_abs += abs(weight)
        else:
            unresolved_abs += abs(weight)
        resolved_rows.append(
            {
                "line": line,
                "name": component.get("name"),
                "weight_share": format(weight, "f"),
                "source_family": component.get("source_family"),
                "policy": component.get("policy"),
                "seasonal_status": component.get("seasonal_status"),
                "source_text": component.get("source_text"),
                "status": status,
                "assumption": assumption if status != "UNRESOLVED" else None,
                "mom_percent": _text(chosen_mom),
                "contribution_percent": _text(contribution),
                "reason": reason,
            }
        )

    pre_rates = rates_ending(levels, anchor)
    horizons: dict[str, dict] = {}
    history_ok = anchor_level is not None
    post_rates: dict[int, Decimal | None] = {months: None for months in HORIZONS}
    for months in HORIZONS:
        before = pre_rates[months]
        unchanged = break_even_mom(levels, anchor, months)
        if before is None or unchanged is None or anchor_level is None:
            history_ok = False
        horizons[str(months)] = {
            "before": _text(before),
            "after": None,
            "delta": None,
            "unchanged_momentum_mom_percent": _text(unchanged),
        }

    coverage_ok = unresolved_abs <= UNRESOLVED_ABS_WEIGHT_LIMIT and history_ok
    headline = "INCOMPLETE"
    headline_reason = "history_incomplete" if not history_ok else "unresolved_weight"
    projected = None
    sensitivity_cases: list[dict] = []
    sensitivity_stable: bool | None = None

    if coverage_ok:
        projected = resolved_contribution
        assert anchor_level is not None
        new_level = project_level(anchor_level, projected)
        for months in HORIZONS:
            base_period = shift_month(target_period, -months)
            post_rate = annualized(new_level, levels[base_period], months)
            post_rates[months] = post_rate
            before = Decimal(horizons[str(months)]["before"])
            horizons[str(months)]["after"] = _text(post_rate)
            horizons[str(months)]["delta"] = _text(post_rate - before)
        deltas = {months: Decimal(horizons[str(months)]["delta"]) for months in HORIZONS}
        base_class = classify_momentum(deltas, post_rates[3] or Decimal(0))
        headline = base_class
        headline_reason = None
        sensitivity_stable = True
        carried = [row for row in resolved_rows if row["status"] == "CARRY" and row["mom_percent"] is not None]
        if carried:
            for shift in CARRY_SENSITIVITY_PP:
                for direction in (shift, -shift):
                    shocked = resolved_contribution
                    for row in carried:
                        weight = Decimal(row["weight_share"])
                        shocked += weight * direction
                    shocked_level = project_level(anchor_level, shocked)
                    shocked_post = {}
                    shocked_delta = {}
                    for months in HORIZONS:
                        base_period = shift_month(target_period, -months)
                        rate = annualized(shocked_level, levels[base_period], months)
                        shocked_post[months] = rate
                        shocked_delta[months] = rate - Decimal(horizons[str(months)]["before"])
                    shocked_class = classify_momentum(shocked_delta, shocked_post[3])
                    sensitivity_cases.append(
                        {
                            "carry_shift_mom_pp": format(direction, "f"),
                            "mom_percent": format(shocked, "f"),
                            "headline": shocked_class,
                        }
                    )
                    if shocked_class != base_class:
                        sensitivity_stable = False
            if not sensitivity_stable:
                headline = "INCOMPLETE"
                headline_reason = "carry_sensitivity"
                projected = None
                for months in HORIZONS:
                    horizons[str(months)]["after"] = None
                    horizons[str(months)]["delta"] = None

    return {
        "headline": headline,
        "headline_reason": headline_reason,
        "target_period": target_period,
        "anchor_period": anchor,
        "projected_core_pce_mom_percent": _text(projected),
        "resolved_contribution_percent": _text(resolved_contribution),
        "horizons": horizons,
        "coverage": {
            "resolved_signed_weight": format(resolved_signed, "f"),
            "unresolved_absolute_weight": format(unresolved_abs, "f"),
            "carry_absolute_weight": format(carry_abs, "f"),
            "unresolved_limit": format(UNRESOLVED_ABS_WEIGHT_LIMIT, "f"),
            "rounding_residual_weight": format(residual_weight, "f"),
        },
        "sensitivity": {"stable": sensitivity_stable, "cases": sensitivity_cases},
        "components": resolved_rows,
        "rejected_observations": rejected,
        "cpi_context": _cpi_context(observations),
        "approximation": "first_order_expenditure_share",
    }
