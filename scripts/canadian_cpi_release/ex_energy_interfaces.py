"""Locked interface for the Canadian ex-energy pre-release shadow.

G0 lock. C1, C2, and C3 import this module and do not change formulas,
promotion thresholds, source ids, or the candidate schema keys below.

The canonical B2 nowcast is unchanged. These helpers feed a separate
candidate only.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

# Special aggregates already stored on the frozen B2 snapshot.
FOOD_ID = "cpi_nsa_food"
EX_FOOD_ENERGY_ID = "cpi_nsa_ex_food_energy"
EX_ENERGY_ID = "cpi_nsa_ex_energy"
ALL_ITEMS_ID = "cpi_nsa_all_items"

# Verified 2026-10-18 via StatCan WDS getCubeMetadata +
# getSeriesInfoFromCubePidCoord. Table 18-10-0004 cubeEndDate was 2026-08-01
# (releaseTime 2026-09-14T08:30). No 2026-09 point was present.
# Weight coordinate uses the same price-period slot as the B2 basket series:
# "Weight at basket link month prices".
AIRFARE_ID = "cpi_nsa_air_transportation"
AIRFARE_WEIGHT_ID = "cpi_nsa_air_transportation__weight"
AIRFARE_INDEX_SPEC: dict[str, Any] = {
    "canonical_id": AIRFARE_ID,
    "title": "Air transportation",
    "table_pid": 18100004,
    "table": "18-10-0004",
    "vector_id": 41691151,
    "coordinate": "2.199.0.0.0.0.0.0.0.0",
    "product_member_id": 199,
    "geography": "Canada",
    "units": "index_2002_100",
    "seasonal_status": "NSA",
    "decimals": 1,
}
AIRFARE_WEIGHT_SPEC: dict[str, Any] = {
    "canonical_id": AIRFARE_WEIGHT_ID,
    "title": "Air transportation",
    "table_pid": 18100007,
    "table": "18-10-0007",
    "vector_id": 91859102,
    "coordinate": "1.183.1.1.0.0.0.0.0.0",
    "product_member_id": 183,
    "price_period": "weight_at_basket_link_month_prices",
    "geography": "Canada",
    "units": "basket_weight_percent",
}

# Predeclared. Not fit on the 2019+ evaluation window.
BLEND_DIRECT_WEIGHT = 0.5
AIRFARE_SEASONAL_PRIMARY = "same_month_mean_10"
AIRFARE_SEASONAL_N = 10
AIRFARE_COMPARATORS = ("season5_engine", "ridge_model_a")

BACKTEST_START = "2017-01"
BACKTEST_END = "2026-08"
EVAL_PRIMARY_START = "2019-01"
EVAL_RECENT_START = "2025-01"
MAE_IMPROVEMENT_MIN_PP = 0.005

CANDIDATE_RELEASE = "2026-09"
CANDIDATE_AS_OF = "2026-10-18"
CANDIDATE_AS_OF_TIMEZONE = "America/Toronto"
ORIGINAL_AS_OF = "2026-10-16"
FREEZE_BEFORE = "2026-10-19T08:30:00-04:00"
FORBIDDEN_ACTUAL_PERIOD = "2026-09"

# Canonical September 2026 B2 replay. Do not recompute these into the fixture.
CANONICAL_HEADLINE_NSA_MOM = 0.1325763171949602
CANONICAL_EX_ENERGY_NSA_MOM = -0.03422140158634876
CANONICAL_EX_ENERGY_YOY = 2.1817687643883366
CANONICAL_BASKET_YEAR = 2025
CANONICAL_BASKET_LINK = "2026-04"

CANDIDATE_SCHEMA = "canadian_cpi_ex_energy_candidate_v1"
BACKTEST_SCHEMA = "canadian_cpi_ex_energy_backtest_v1"

# Official basket weights add (food + ex-food-and-energy = ex-energy) within
# 0.01 percentage point of rounding. The price-updated MoM identity versus the
# published ex-energy index is approximate (about 0.03 MAE on 2019-2026 in the
# frozen fixture) for the same reason the eight-major identity is approximate.
IDENTITY_NOTE = (
    "food and all-items-excluding-food-and-energy partition all-items-excluding-energy "
    "in the published basket weights. The month-over-month reconstruction uses "
    "price-updated shares and is an approximation of the published ex-energy index, "
    "not a second official index."
)


def price_updated_share(
    *,
    basket_weight_percent: float,
    index_link: float,
    index_tm1: float,
    all_items_link: float,
    all_items_tm1: float,
) -> float:
    """Same Lowe share update as ``weights.compute_shares``."""
    if index_link == 0 or all_items_link == 0:
        raise ValueError("zero_link_level")
    ratio_all = all_items_tm1 / all_items_link
    return (basket_weight_percent / 100.0) * (index_tm1 / index_link) / ratio_all


def combine_partition_mom(
    share_a: float,
    mom_a: float,
    share_b: float,
    mom_b: float,
) -> float:
    """MoM of a two-part partition. Shares are all-items shares at t-1."""
    denom = share_a + share_b
    if denom <= 0:
        raise ValueError("nonpositive_partition_share")
    return (share_a * mom_a + share_b * mom_b) / denom


def replace_child_within_parent(
    parent_mom: float,
    parent_share: float,
    child_share: float,
    child_baseline_mom: float,
    child_replacement_mom: float,
) -> float:
    """Replace a child inside a parent. Do not add the child again afterwards.

    ``parent_mom`` already contains ``child_baseline_mom``. The result replaces
    that baseline with ``child_replacement_mom`` and leaves the rest of the
    parent unchanged. ``child_share`` and ``parent_share`` are all-items shares.
    """
    if parent_share <= 0:
        raise ValueError("nonpositive_parent_share")
    if child_share < 0:
        raise ValueError("negative_child_share")
    if child_share > parent_share + 5e-3:
        raise ValueError("child_share_not_inside_parent")
    weight = child_share / parent_share
    return parent_mom + weight * (child_replacement_mom - child_baseline_mom)


def equal_blend(direct: float, component: float, direct_weight: float = BLEND_DIRECT_WEIGHT) -> float:
    """Predeclared convex blend. ``direct_weight`` is not estimated in-sample."""
    if direct_weight < 0 or direct_weight > 1:
        raise ValueError("blend_weight_out_of_range")
    return direct_weight * direct + (1.0 - direct_weight) * component


def index_from_mom(previous_index: float, mom_percent: float) -> float:
    return previous_index * (1.0 + mom_percent / 100.0)


def yoy_from_index(forecast_index: float, index_t12: float) -> float:
    if index_t12 <= 0:
        raise ValueError("nonpositive_t12_index")
    return 100.0 * (forecast_index / index_t12 - 1.0)


def same_month_mean(moms: Mapping[str, float], target: str, n: int = AIRFARE_SEASONAL_N) -> float | None:
    """Mean of the last ``n`` MoMs in the same calendar month, strictly before ``target``."""
    month = target[5:7]
    prior = [moms[p] for p in sorted(moms) if p < target and p[5:7] == month]
    if not prior:
        return None
    return float(sum(prior[-n:]) / len(prior[-n:]))


def paired_abs_error_summary(baseline: Sequence[float], alternative: Sequence[float]) -> dict[str, float | int]:
    """Paired absolute-error comparison. Negative mae_delta favors the alternative."""
    if len(baseline) != len(alternative):
        raise ValueError("paired_length_mismatch")
    if not baseline:
        return {"n": 0, "mae_delta": 0.0, "n_improved": 0, "n_worse": 0, "n_tie": 0}
    deltas = [abs(a) - abs(b) for b, a in zip(baseline, alternative)]
    n_improved = sum(1 for d in deltas if d < 0)
    n_worse = sum(1 for d in deltas if d > 0)
    n_tie = sum(1 for d in deltas if d == 0)
    return {
        "n": len(deltas),
        "mae_delta": float(sum(deltas) / len(deltas)),
        "n_improved": n_improved,
        "n_worse": n_worse,
        "n_tie": n_tie,
    }


def promotion_decision(
    *,
    direct_mae_primary: float,
    direct_mae_recent: float,
    alt_mae_primary: float,
    alt_mae_recent: float,
    paired_mae_delta_primary: float,
) -> bool:
    """True only when a predeclared alternative beats direct ex-energy on both windows."""
    improved_primary = (direct_mae_primary - alt_mae_primary) >= MAE_IMPROVEMENT_MIN_PP
    not_worse_recent = alt_mae_recent <= direct_mae_recent
    paired = paired_mae_delta_primary < 0
    return bool(improved_primary and not_worse_recent and paired)


def candidate_point_estimate(
    *,
    direct: float,
    component: float | None,
    blend: float | None,
    airfare_on_base: float | None,
    component_promoted: bool,
    blend_promoted: bool,
    airfare_promoted: bool,
) -> tuple[float, str, bool]:
    """Pick one predeclared estimate. Direct remains the default.

    Order is fixed: component, then equal blend, then one airfare replacement
    applied to whichever of those two was promoted (or to direct if neither was).
    Comparators cannot be selected.
    """
    chosen = direct
    name = "direct_ex_energy"
    promoted = False
    if component_promoted and component is not None:
        chosen = component
        name = "component_food_ex_food_energy"
        promoted = True
    elif blend_promoted and blend is not None:
        chosen = blend
        name = "blend_equal_predeclared"
        promoted = True
    if airfare_promoted and airfare_on_base is not None:
        chosen = airfare_on_base
        name = f"{name}+airfare_{AIRFARE_SEASONAL_PRIMARY}"
        promoted = True
    return chosen, name, promoted
