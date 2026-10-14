"""First-order core PCE nowcast (nowcast_repair_v1)."""

from __future__ import annotations

from decimal import Decimal

from scripts.core_pce_release.acquire import load_registry
from scripts.core_pce_release.estimates import apply_observations
from scripts.core_pce_release.history import (
    annualized,
    break_even_mom,
    project_level,
    rates_ending,
    shift_month,
)
from scripts.core_pce_release.prepare_model import build_baseline, load_component_history, load_cpi_cache
from scripts.core_pce_release.uncertainty import classification_sensitive
from scripts.core_pce_release.verdict import classify_momentum, gap_to_two, nine_month_direction

HORIZONS = (3, 6, 9)
METHOD_VERSION = "nowcast_repair_v1"


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
    baseline: dict | None = None,
) -> dict:
    anchor = shift_month(target_period, -1)
    anchor_level = levels.get(anchor)

    if baseline is None:
        history = load_component_history()
        cpi_cache = load_cpi_cache()
        registry = load_registry()
        cpi_points = cpi_cache["points"]
        baseline = build_baseline(
            components,
            history,
            cpi_points,
            registry,
            target_period=target_period,
            anchor_period=anchor,
        )

    bundle = apply_observations(baseline, components, observations, target_period=target_period)
    integrity = bundle.get("integrity") or {"blocked": False, "reasons": []}
    blocked = bool(integrity.get("blocked"))

    pre_rates = rates_ending(levels, anchor)
    horizons: dict[str, dict] = {}
    history_ok = anchor_level is not None
    for months in HORIZONS:
        before = pre_rates[months]
        unchanged = break_even_mom(levels, anchor, months)
        if before is None or unchanged is None:
            history_ok = False
        horizons[str(months)] = {
            "before": _text(before),
            "after": None,
            "delta": None,
            "unchanged_momentum_mom_percent": _text(unchanged),
        }

    central_text = bundle["central_mom_percent"]
    low_text = bundle["low_mom_percent"]
    high_text = bundle["high_mom_percent"]
    low_headline = "INCOMPLETE"
    high_headline = "INCOMPLETE"
    headline = "INCOMPLETE"
    headline_reason = None
    projected: str | None = None
    post_rates: dict[int, Decimal] = {}
    gap: dict[int, str] = {}
    direction_9 = "unchanged"

    if history_ok and not blocked:
        projected = central_text
        assert anchor_level is not None
        central_mom = Decimal(central_text)
        low_mom = Decimal(low_text)
        high_mom = Decimal(high_text)

        for label, mom in (("central", central_mom), ("low", low_mom), ("high", high_mom)):
            new_level = project_level(anchor_level, mom)
            deltas: dict[int, Decimal] = {}
            posts: dict[int, Decimal] = {}
            for months in HORIZONS:
                base_period = shift_month(target_period, -months)
                post_rate = annualized(new_level, levels[base_period], months)
                posts[months] = post_rate
                before = Decimal(horizons[str(months)]["before"])
                if label == "central":
                    horizons[str(months)]["after"] = _text(post_rate)
                    horizons[str(months)]["delta"] = _text(post_rate - before)
                deltas[months] = post_rate - before
            if label == "central":
                post_rates = posts
                headline = classify_momentum(deltas)
            elif label == "low":
                low_headline = classify_momentum(deltas)
            else:
                high_headline = classify_momentum(deltas)

        direction_9 = nine_month_direction(Decimal(horizons["9"]["delta"]))
        gap = {months: _text(gap_to_two(post_rates)[months]) for months in HORIZONS}
    elif blocked:
        headline_reason = "integrity_blocked"
    elif not history_ok:
        headline_reason = "history_incomplete"

    reliability = bundle.get("reliability_abs_weight") or {}
    coverage = {
        "observed_absolute_weight": reliability.get("observed", "0"),
        "transformed_absolute_weight": reliability.get("transformed", "0"),
        "carried_absolute_weight": reliability.get("carried", "0"),
        "proxy_absolute_weight": reliability.get("proxy", "0"),
        "baseline_absolute_weight": reliability.get("baseline", "0"),
        "unresolved_absolute_weight": "0" if not blocked else reliability.get("baseline", "0"),
        "unresolved_limit": None,
        "rounding_residual_weight": format(residual_weight, "f"),
    }

    rejected = list(bundle.get("rejected_observations") or [])
    for row in observations:
        if row.get("series_id") == "CUSR0000SA0L1E" or row.get("role") == "cpi_context_only":
            if not any(item.get("reason") == "cpi_context_only" for item in rejected):
                rejected.append({"reason": "cpi_context_only", "series_id": row.get("series_id")})

    return {
        "headline": headline,
        "low_headline": low_headline,
        "high_headline": high_headline,
        "headline_reason": headline_reason,
        "classification_sensitive": classification_sensitive(headline, low_headline, high_headline),
        "nine_month_direction": direction_9,
        "gap_to_two_percent": gap,
        "target_period": target_period,
        "anchor_period": anchor,
        "projected_core_pce_mom_percent": projected,
        "central_mom_percent": central_text,
        "low_mom_percent": low_text,
        "high_mom_percent": high_text,
        "horizons": horizons,
        "coverage": coverage,
        "components": bundle["rows"],
        "attribution": bundle.get("attribution") or [],
        "rejected_observations": rejected,
        "cpi_context": _cpi_context(observations),
        "information_stage": bundle.get("information_stage") or "post_cpi_pre_ppi",
        "integrity": integrity,
        "method_version": METHOD_VERSION,
        "approximation": "first_order_signed_expenditure_share",
        "not_official_pce": True,
        "scenario_range_is_confidence_interval": False,
    }
