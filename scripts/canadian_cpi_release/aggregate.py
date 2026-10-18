"""Headline aggregation and disjoint contribution leaves."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scripts.canadian_cpi_release.contract import MAJOR_IDS

GASOLINE_ID = "cpi_nsa_gasoline"
FUEL_OIL_ID = "cpi_nsa_fuel_oil"
REPLACEMENT_ID = "cpi_nsa_replacement_cost"
TRANSPORT_ID = "cpi_nsa_transportation"
SHELTER_ID = "cpi_nsa_shelter"


@dataclass
class ComponentForecast:
    canonical_id: str
    mom_a: float
    mom_used: float
    method: str
    bridge_applied: bool
    bridge_delta_pp: float  # share * (mom_used - mom_a) when bridge applied


def headline_from_components(
    shares: dict[str, float],
    components: dict[str, ComponentForecast],
) -> tuple[float, float, dict[str, float]]:
    """Return headline_A, headline_B2, per-bridge delta pp (child id -> delta)."""
    headline_a = sum(shares.get(m, 0.0) * components[m].mom_a for m in MAJOR_IDS)
    bridge_delta = 0.0
    deltas: dict[str, float] = {}
    for child_id in (GASOLINE_ID, FUEL_OIL_ID, REPLACEMENT_ID):
        cf = components.get(child_id)
        if cf is None:
            continue
        sh = shares.get(child_id, 0.0)
        d = sh * (cf.mom_used - cf.mom_a) if cf.bridge_applied else 0.0
        deltas[child_id] = d
        bridge_delta += d
    headline_b2 = headline_a + bridge_delta
    return headline_a, headline_b2, deltas


def weighted_baseline_headline(
    shares: dict[str, float],
    major_moms: dict[str, float],
) -> float:
    return sum(shares.get(m, 0.0) * major_moms.get(m, 0.0) for m in MAJOR_IDS)


def build_contribution_leaves(
    shares: dict[str, float],
    components: dict[str, ComponentForecast],
    headline_b2: float,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Disjoint leaves that sum to headline_B2."""
    blockers: list[str] = []
    leaves: list[dict[str, Any]] = []

    skip = {TRANSPORT_ID, SHELTER_ID}
    for m in MAJOR_IDS:
        if m in skip:
            continue
        cf = components[m]
        leaves.append(
            {
                "canonical_id": m,
                "role": "contribution_leaf",
                "share": shares.get(m, 0.0),
                "mom": cf.mom_a,
                "contribution_pp": shares.get(m, 0.0) * cf.mom_a,
                "status": "modeled",
            }
        )

    g_cf = components[GASOLINE_ID]
    g_sh = shares.get(GASOLINE_ID, 0.0)
    g_delta = g_sh * (g_cf.mom_used - g_cf.mom_a) if g_cf.bridge_applied else 0.0
    g_leaf_pp = g_sh * g_cf.mom_used
    g_status = "observed_bridge" if g_cf.bridge_applied else "modeled"
    leaves.append(
        {
            "canonical_id": GASOLINE_ID,
            "role": "contribution_leaf",
            "share": g_sh,
            "mom": g_cf.mom_used,
            "contribution_pp": g_leaf_pp,
            "status": g_status,
        }
    )
    t_cf = components[TRANSPORT_ID]
    t_pp = shares.get(TRANSPORT_ID, 0.0) * t_cf.mom_a + g_delta - g_leaf_pp
    leaves.append(
        {
            "canonical_id": "transportation_ex_gasoline",
            "role": "contribution_leaf",
            "share": shares.get(TRANSPORT_ID, 0.0),
            "mom": None,
            "contribution_pp": t_pp,
            "status": "attribution_residual",
            "note": "Not an official ex-gasoline index.",
        }
    )

    f_cf = components[FUEL_OIL_ID]
    f_sh = shares.get(FUEL_OIL_ID, 0.0)
    f_delta = f_sh * (f_cf.mom_used - f_cf.mom_a) if f_cf.bridge_applied else 0.0
    f_leaf_pp = f_sh * f_cf.mom_used
    f_status = "observed_bridge" if f_cf.bridge_applied else "modeled"
    leaves.append(
        {
            "canonical_id": FUEL_OIL_ID,
            "role": "contribution_leaf",
            "share": f_sh,
            "mom": f_cf.mom_used,
            "contribution_pp": f_leaf_pp,
            "status": f_status,
        }
    )

    r_cf = components[REPLACEMENT_ID]
    r_sh = shares.get(REPLACEMENT_ID, 0.0)
    r_delta = r_sh * (r_cf.mom_used - r_cf.mom_a) if r_cf.bridge_applied else 0.0
    r_leaf_pp = r_sh * r_cf.mom_used
    r_status = "lagged_official_bridge" if r_cf.bridge_applied else "modeled"
    leaves.append(
        {
            "canonical_id": REPLACEMENT_ID,
            "role": "contribution_leaf",
            "share": r_sh,
            "mom": r_cf.mom_used,
            "contribution_pp": r_leaf_pp,
            "status": r_status,
        }
    )

    s_cf = components[SHELTER_ID]
    s_pp = (
        shares.get(SHELTER_ID, 0.0) * s_cf.mom_a + f_delta + r_delta - f_leaf_pp - r_leaf_pp
    )
    leaves.append(
        {
            "canonical_id": "shelter_ex_fuel_and_replacement",
            "role": "contribution_leaf",
            "share": shares.get(SHELTER_ID, 0.0),
            "mom": None,
            "contribution_pp": s_pp,
            "status": "attribution_residual",
            "note": "Not an official shelter ex-fuel/replacement index.",
        }
    )

    # Research table nests the replacement-cost bridge inside "shelter excluding
    # fuel oil". That line is not an extra leaf; the disjoint sum uses
    # shelter_ex_fuel_and_replacement plus the replacement leaf instead.
    shelter_after_fuel = (
        shares.get(SHELTER_ID, 0.0) * s_cf.mom_a + f_delta + r_delta - f_leaf_pp
    )
    leaves.append(
        {
            "canonical_id": "shelter_ex_fuel_oil",
            "role": "nested_diagnostic",
            "share": shares.get(SHELTER_ID, 0.0),
            "mom": None,
            "contribution_pp": shelter_after_fuel,
            "status": "nested_diagnostic",
            "note": (
                "Includes the lagged replacement-cost bridge. "
                "Not part of the disjoint leaf sum."
            ),
        }
    )

    leaf_sum = sum(x["contribution_pp"] for x in leaves if x["role"] == "contribution_leaf")
    if abs(leaf_sum - headline_b2) >= 1e-8:
        blockers.append("contribution_residual")

    return leaves, blockers
