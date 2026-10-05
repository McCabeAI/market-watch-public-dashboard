"""Build and update ReleaseExpectation documents from series definitions."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Mapping, Optional

from scripts.run_state.schema import (
    SCHEMA_RELEASE_EXPECTATION,
    expectation_id_from_body,
    validate_release_expectation,
)


def _parse_instant(iso: str) -> datetime:
    normalized = iso.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        raise ValueError(f"timezone required in instant: {iso!r}")
    return dt


def build_expectation(
    definition: Mapping[str, Any],
    *,
    run_id: str,
    cutoff_at: str,
    release_at: Optional[str] = None,
    expected_period: Optional[str] = None,
    overlay: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    series_id = definition.get("id") or definition.get("series_id")
    if not isinstance(series_id, str) or series_id == "":
        raise ValueError("definition must include id or series_id")

    cal_status = definition.get("calendar_status", "unknown")
    if cal_status not in ("known", "unknown"):
        raise ValueError("definition calendar_status must be known or unknown")

    eff_release = release_at
    eff_period = expected_period
    if overlay:
        if overlay.get("calendar_status") == "known":
            cal_status = "known"
            if "release_at" in overlay:
                eff_release = overlay["release_at"]
            if "period" in overlay:
                eff_period = overlay["period"]

    scheduled: Optional[bool]
    if cal_status == "unknown":
        scheduled = None
        eff_release = None
        eff_period = None
    else:
        if eff_release is None:
            raise ValueError("known calendar requires release instant")
        cutoff_dt = _parse_instant(cutoff_at)
        release_dt = _parse_instant(eff_release)
        scheduled = release_dt <= cutoff_dt
        if scheduled and eff_period is None:
            raise ValueError("known occurred release requires expected_period")

    body: Dict[str, Any] = {
        "schema_version": SCHEMA_RELEASE_EXPECTATION,
        "run_id": run_id,
        "series_id": series_id,
        "calendar_status": cal_status,
        "scheduled_release_occurred_by_cutoff": scheduled,
        "expectation_satisfied_by_verified_evidence": False,
        "expected_release_at": eff_release,
        "expected_period": eff_period,
        "cutoff_at": cutoff_at,
        "satisfaction_observation_id": None,
    }
    transform = definition.get("transform")
    if isinstance(transform, str) and transform != "":
        body["expected_transformation"] = transform
    units = definition.get("units")
    if isinstance(units, str) and units != "":
        body["expected_units"] = units
    body["expectation_id"] = expectation_id_from_body(body)
    return validate_release_expectation(body)


def apply_satisfaction(
    expectation: Mapping[str, Any],
    observation_or_none: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    out = dict(expectation)
    satisfied = False
    sat_id: Optional[str] = None
    if observation_or_none is not None:
        obs_period = observation_or_none.get("period")
        expected_period = out.get("expected_period")
        obs_units = observation_or_none.get("units")
        obs_transform = observation_or_none.get("transformation")
        period_ok = (
            isinstance(obs_period, str)
            and isinstance(expected_period, str)
            and obs_period == expected_period
        )
        units_present = isinstance(obs_units, str) and obs_units != ""
        transform_present = isinstance(obs_transform, str) and obs_transform != ""
        if period_ok and units_present and transform_present:
            transform_ok = True
            exp_transform = out.get("expected_transformation")
            if isinstance(exp_transform, str) and exp_transform != "":
                transform_ok = obs_transform == exp_transform
            units_ok = True
            exp_units = out.get("expected_units")
            if isinstance(exp_units, str) and exp_units != "":
                units_ok = obs_units == exp_units
            if transform_ok and units_ok:
                satisfied = True
                oid = observation_or_none.get("observation_id")
                if isinstance(oid, str):
                    sat_id = oid
    out["expectation_satisfied_by_verified_evidence"] = satisfied
    out["satisfaction_observation_id"] = sat_id
    out["expectation_id"] = expectation_id_from_body(out)
    return validate_release_expectation(out)
