"""Normalize CPI/PPI observations. Reject stale periods and invalid substitution."""

from __future__ import annotations

from decimal import Decimal

MOM_INDEX_TOLERANCE_PP = Decimal("0.01")
MOM_ABS_LIMIT = Decimal("15")
_DIRECT = frozenset({"CPI", "PPI"})


def _decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def derive_mom(payload: dict) -> tuple[Decimal | None, str | None]:
    mom = _decimal(payload.get("mom_percent"))
    level = _decimal(payload.get("index_level"))
    prior = _decimal(payload.get("prior_index_level"))
    if level is not None and prior is not None:
        if prior <= 0 or level <= 0:
            return None, "non_positive_index"
        implied = (level / prior - 1) * 100
        if mom is not None and abs(implied - mom) > MOM_INDEX_TOLERANCE_PP:
            return None, "inconsistent_mom_and_index_ratio"
        chosen = implied if mom is None else mom
    elif mom is None:
        if level is not None:
            return None, "index_level_without_base"
        return None, "missing_mom"
    else:
        chosen = mom
    if abs(chosen) > MOM_ABS_LIMIT:
        return None, "monthly_percent_out_of_range"
    return chosen, None


def _leg_mom(component: dict, leg: dict) -> tuple[Decimal | None, str | None]:
    mom, error = derive_mom(leg)
    if error:
        return None, "leg_" + error
    seasonal = str(leg.get("seasonal_status") or "")
    if component.get("seasonal_status") != "SA":
        if seasonal != "BEA_SA":
            return None, "leg_bea_seasonal_adjustment_required"
    elif seasonal != "SA":
        return None, "leg_sa_required"
    family = str(leg.get("source_family") or "")
    if family not in _DIRECT:
        return None, "leg_source_family"
    return mom, None


def raw_source_mom(observation: dict) -> Decimal | None:
    """Monthly percent from a raw BLS reference without BEA-SA relabeling."""
    mom, error = derive_mom(observation)
    if error:
        return None
    return mom


def accept_observation(component: dict, observation: dict) -> tuple[Decimal | None, str | None]:
    """Return a usable monthly percent or a rejection reason. Never invents one."""
    policy = component["policy"]
    family = str(observation.get("source_family") or "")
    seasonal = str(observation.get("seasonal_status") or "")

    if policy == "missing_source" or policy == "not_directly_usable":
        return None, "policy_not_directly_usable"
    if policy == "implicit_not_carried":
        if family != "IMPLICIT":
            return None, "implicit_rejects_cpi_ppi_carry"
        if not observation.get("method_id"):
            return None, "implicit_method_required"
        return derive_mom(observation)
    if policy == "bls_sa_direct":
        if family != component["source_family"]:
            return None, "source_family_mismatch"
        if seasonal != "SA":
            return None, "sa_required"
        return derive_mom(observation)
    if policy == "requires_explicit_seasonal_adjustment":
        if family != component["source_family"]:
            return None, "source_family_mismatch"
        if seasonal != "BEA_SA":
            return None, "bea_seasonal_adjustment_required"
        if not str(observation.get("adjustment_method") or "").strip():
            return None, "adjustment_method_required"
        return derive_mom(observation)
    if policy == "composite_explicit_only":
        if observation.get("aggregation") != "bea_composite":
            return None, "composite_aggregation_required"
        if seasonal != "BEA_SA":
            return None, "bea_seasonal_adjustment_required"
        if not str(observation.get("adjustment_method") or "").strip():
            return None, "adjustment_method_required"
        return derive_mom(observation)
    if policy == "mixed_legs_required":
        legs = observation.get("legs")
        if not isinstance(legs, list) or len(legs) < 2:
            return None, "mixed_legs_required"
        total = Decimal(0)
        weighted = Decimal(0)
        for leg in legs:
            try:
                weight = Decimal(str(leg["weight"]))
            except (KeyError, TypeError, ArithmeticError):
                return None, "leg_weight_missing"
            mom, error = _leg_mom(component, leg)
            if error:
                return None, error
            assert mom is not None
            total += weight
            weighted += weight * mom
        if abs(total - 1) > Decimal("0.000001"):
            return None, "leg_weights_must_sum_to_one"
        if abs(weighted) > MOM_ABS_LIMIT:
            return None, "monthly_percent_out_of_range"
        return weighted, None
    return None, "policy_not_directly_usable"
