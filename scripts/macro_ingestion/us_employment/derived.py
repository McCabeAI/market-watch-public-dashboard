"""Deterministic US employment diagnostics. No runtime model judgment."""

from __future__ import annotations

from typing import Any

def monthly_delta(latest: float, prior: float) -> float:
    return float(latest) - float(prior)


def unrounded_u3(unemployed: float, labor_force: float) -> float | None:
    """Official U-3 identity before BLS rounding: unemployed / labor force * 100."""
    if labor_force == 0:
        return None
    return float(unemployed) / float(labor_force) * 100.0


def labor_force_absorption(delta_household_employment: float, delta_labor_force: float) -> float:
    """Household employment change not absorbed by labor-force change."""
    return float(delta_household_employment) - float(delta_labor_force)


def chicago_fed_error(unrounded_unemployment_rate: float, final_nowcast: float) -> float:
    """Actual unrounded U-3 minus the final Chicago Fed nowcast, same reference month."""
    return float(unrounded_unemployment_rate) - float(final_nowcast)


def payroll_vs_breakeven(payroll_change_thousands: float, breakeven_thousands: float) -> float:
    """Latest payroll change minus the current sourced structural breakeven."""
    return float(payroll_change_thousands) - float(breakeven_thousands)


def initial_claims_rate_of_covered(
    initial_claims: float,
    covered_employment: float,
) -> float | None:
    """Initial claims as a percent of the published UI covered-employment level."""
    if covered_employment == 0:
        return None
    return float(initial_claims) / float(covered_employment) * 100.0


def initial_claims_per_covered_employment(
    initial_claims: float,
    continuing_claims: float,
    insured_unemployment_rate: float,
) -> float | None:
    """Initial claims as a percent of UI-covered employment.

    Covered employment is the DOL identity continuing claims / (insured rate / 100)
    for the same week. It is not a separately interpolated series.
    """
    if continuing_claims == 0 or insured_unemployment_rate == 0:
        return None
    covered = float(continuing_claims) / (float(insured_unemployment_rate) / 100.0)
    if covered == 0:
        return None
    return float(initial_claims) / covered * 100.0


def week_contains_calendar_day(week_ending_iso: str, day_of_month: int = 12) -> bool:
    """True when the 7-day week ending on `week_ending_iso` contains `day_of_month`."""
    from datetime import date, timedelta

    week_ending = date.fromisoformat(week_ending_iso[:10])
    start = week_ending - timedelta(days=6)
    return any((start + timedelta(days=offset)).day == day_of_month for offset in range(7))


def _delta(now: dict[str, float], prior: dict[str, float], key: str) -> float | None:
    if key not in now or key not in prior:
        return None
    return float(now[key]) - float(prior[key])


_ACCOUNTING_IDENTITY = "delta_unemployed = delta_labor_force - delta_household_employment"


def attribution_channels(
    now: dict[str, float],
    prior: dict[str, float],
) -> dict[str, Any]:
    """Labor-market attribution: accounting identity plus non-additive diagnostic channels.

    Missing inputs stay null. Nothing is filled in from another concept except
    the documented fallback from reason categories to the matching gross flow.
    """
    job_loss = _delta(now, prior, "job_losers")
    job_loss_source = "job_losers"
    if job_loss is None:
        job_loss = _delta(now, prior, "flow_eu")
        job_loss_source = "flow_eu" if job_loss is not None else None

    finding = _delta(now, prior, "flow_ue")
    weak_job_finding = None if finding is None else -finding

    reentrants = _delta(now, prior, "reentrants")
    new_entrants = _delta(now, prior, "new_entrants")
    if reentrants is None and new_entrants is None:
        entrant = _delta(now, prior, "flow_nu")
        entrant_source = "flow_nu" if entrant is not None else None
    else:
        entrant = (reentrants or 0.0) + (new_entrants or 0.0)
        entrant_source = "reentrants_plus_new_entrants"

    delta_unemployed = _delta(now, prior, "unemployed")
    delta_labor_force = _delta(now, prior, "labor_force")
    delta_household_employment = _delta(now, prior, "household_employment")

    absorption: float | None = None
    identity_implied: float | None = None
    identity_residual: float | None = None
    if delta_household_employment is not None and delta_labor_force is not None:
        absorption = labor_force_absorption(delta_household_employment, delta_labor_force)
        identity_implied = delta_labor_force - delta_household_employment
        if delta_unemployed is not None:
            identity_residual = delta_unemployed - identity_implied

    return {
        "accounting": {
            "identity": _ACCOUNTING_IDENTITY,
            "delta_unemployed": delta_unemployed,
            "delta_labor_force": delta_labor_force,
            "delta_household_employment": delta_household_employment,
            "labor_force_absorption": absorption,
            "identity_implied_unemployment_change": identity_implied,
            "identity_residual": identity_residual,
            "additive_labor_force_cause": False,
        },
        "diagnostic_channels": {
            "job_loss": job_loss,
            "weak_job_finding": weak_job_finding,
            "entrant_reentrant": entrant,
        },
        "diagnostic_sources": {
            "job_loss": job_loss_source,
            "weak_job_finding": "flow_ue" if weak_job_finding is not None else None,
            "entrant_reentrant": entrant_source,
        },
        "diagnostic_channels_are_additive_decomposition": False,
    }


def _empty_attribution() -> dict[str, Any]:
    return {
        "accounting": {
            "identity": _ACCOUNTING_IDENTITY,
            "delta_unemployed": None,
            "delta_labor_force": None,
            "delta_household_employment": None,
            "labor_force_absorption": None,
            "identity_implied_unemployment_change": None,
            "identity_residual": None,
            "additive_labor_force_cause": False,
        },
        "diagnostic_channels": {},
        "diagnostic_sources": {},
        "diagnostic_channels_are_additive_decomposition": False,
    }
