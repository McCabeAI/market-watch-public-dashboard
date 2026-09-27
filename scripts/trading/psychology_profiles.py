"""Versioned persona coefficients. One table, no per-seat control flow."""

from __future__ import annotations

from typing import Any

from scripts.trading.constants import PSYCH_AXES, PSYCH_PROFILE_VERSION

NEUTRAL_BASELINE = {
    "self_trust": 0.50,
    "frustration": 0.10,
    "defensiveness": 0.20,
    "chase_pressure": 0.10,
    "revenge_pressure": 0.05,
    "complacency": 0.10,
    "thesis_attachment": 0.25,
    "external_pressure": 0.10,
}
NEUTRAL_HALF_LIFE = {
    "self_trust": 12.0,
    "frustration": 3.0,
    "defensiveness": 6.0,
    "chase_pressure": 4.0,
    "revenge_pressure": 2.0,
    "complacency": 5.0,
    "thesis_attachment": 8.0,
    "external_pressure": 6.0,
}

# Absent fields mean neutral. flat_by_design scales E11 only.
_PROFILES: dict[str, dict[str, Any]] = {
    "dollar-king": {
        "baseline": {"self_trust": 0.60, "thesis_attachment": 0.35},
        "gain": {"complacency": 1.3, "defensiveness": 0.8},
        "half_life": {"complacency": 1.2},
        "tags": ("spot_only",),
    },
    "cross-merchant": {
        "gain": {"revenge_pressure": 1.1, "chase_pressure": 1.1},
        "tags": ("spot_only",),
    },
    "carry-is-king": {
        "gain": {"complacency": 1.2, "defensiveness": 0.8, "frustration": 0.9},
        "half_life": {"complacency": 1.3},
    },
    "rate-hawk": {
        "baseline": {"thesis_attachment": 0.35},
        "gain": {"external_pressure": 1.0, "thesis_attachment": 1.2},
    },
    "rate-dove": {
        "baseline": {"thesis_attachment": 0.35},
        "gain": {"thesis_attachment": 1.2},
    },
    "value-guy": {
        "gain": {"thesis_attachment": 1.3, "chase_pressure": 0.6, "frustration": 0.9},
        "half_life": {"thesis_attachment": 1.3},
    },
    "trend-follower": {
        "gain": {"complacency": 1.2, "defensiveness": 0.8, "revenge_pressure": 0.8},
        "half_life": {"frustration": 0.8},
    },
    "mean-reverter": {
        "gain": {"thesis_attachment": 1.4, "frustration": 1.2, "revenge_pressure": 1.2},
    },
    "positioning-cynic": {
        "gain": {"chase_pressure": 0.6, "complacency": 0.8, "self_trust": 1.2},
    },
    "catalyst-junkie": {
        "gain": {"chase_pressure": 1.5, "thesis_attachment": 0.7, "revenge_pressure": 0.9},
        "half_life": {"frustration": 0.7},
    },
    "vol-convexity": {
        "gain": {"defensiveness": 0.7, "frustration": 1.2, "complacency": 0.8},
        "tags": ("flat_by_design",),
        "flat_by_design": 0.5,
    },
    "no-trade-skeptic": {
        "baseline": {"defensiveness": 0.35, "self_trust": 0.55},
        "gain": {"chase_pressure": 0.4, "complacency": 0.6, "external_pressure": 0.6},
        "tags": ("flat_by_design",),
        "flat_by_design": 0.25,
    },
    "perma-bull": {
        "baseline": {"thesis_attachment": 0.40},
        "gain": {"thesis_attachment": 1.3, "complacency": 1.1},
    },
    "perma-bear": {
        "baseline": {"thesis_attachment": 0.40},
        "gain": {"thesis_attachment": 1.3, "defensiveness": 1.1},
    },
    "swinger": {
        "gain": {"complacency": 1.4, "defensiveness": 0.6, "external_pressure": 0.8, "revenge_pressure": 1.2},
    },
    "pragmatist": {
        "gain": {"external_pressure": 1.1},
    },
    "grinder": {
        "baseline": {"defensiveness": 0.35},
        "gain": {"chase_pressure": 0.5, "external_pressure": 1.2, "frustration": 0.8},
        "tags": ("flat_by_design",),
        "flat_by_design": 0.5,
    },
    "chatgpt": {"tags": ("not_applicable",)},
}

PROFILE_GUARD = {
    "baseline": (0.05, 0.60),
    "self_trust_baseline": (0.40, 0.65),
    "gain": (0.4, 1.6),
    "half_life": (0.6, 1.5),
}


def profile_ids() -> tuple[str, ...]:
    return tuple(_PROFILES)


def is_not_applicable(owner_id: str) -> bool:
    return "not_applicable" in _PROFILES.get(owner_id, {}).get("tags", ())


def profile_for(owner_id: str) -> dict[str, Any]:
    raw = _PROFILES.get(owner_id, {})
    baseline = dict(NEUTRAL_BASELINE)
    baseline.update(raw.get("baseline") or {})
    gain = {axis: 1.0 for axis in PSYCH_AXES}
    gain.update(raw.get("gain") or {})
    half_life = {axis: 1.0 for axis in PSYCH_AXES}
    half_life.update(raw.get("half_life") or {})
    return {
        "profile_version": PSYCH_PROFILE_VERSION,
        "owner_id": owner_id,
        "baseline": baseline,
        "gain": gain,
        "half_life": half_life,
        "tags": tuple(raw.get("tags") or ()),
        "flat_by_design": float(raw.get("flat_by_design") or 1.0),
    }


def validate_profile_table() -> list[str]:
    """Return guard-rail violations. Empty means the table is adoptable."""
    problems: list[str] = []
    lo_b, hi_b = PROFILE_GUARD["baseline"]
    lo_s, hi_s = PROFILE_GUARD["self_trust_baseline"]
    lo_g, hi_g = PROFILE_GUARD["gain"]
    lo_h, hi_h = PROFILE_GUARD["half_life"]
    for owner_id in _PROFILES:
        if is_not_applicable(owner_id):
            continue
        profile = profile_for(owner_id)
        for axis, value in profile["baseline"].items():
            low, high = (lo_s, hi_s) if axis == "self_trust" else (lo_b, hi_b)
            if not low <= float(value) <= high:
                problems.append(f"{owner_id} baseline {axis}={value} outside [{low}, {high}]")
        for axis, value in profile["gain"].items():
            if not lo_g <= float(value) <= hi_g:
                problems.append(f"{owner_id} gain {axis}={value} outside [{lo_g}, {hi_g}]")
        for axis, value in profile["half_life"].items():
            if not lo_h <= float(value) <= hi_h:
                problems.append(f"{owner_id} half_life {axis}={value} outside [{lo_h}, {hi_h}]")
    return problems
