"""Compute context-only employment diagnostics from already retrieved batches."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable

from scripts.macro_ingestion.us_employment.bls_public import load_bls_batch
from scripts.macro_ingestion.us_employment.chicago_fed import load_chicago_bundle
from scripts.macro_ingestion.us_employment.claims import load_claims_batch
from scripts.macro_ingestion.us_employment.contract import (
    BLS_CPS_SERIES,
    BLS_JOLTS_SERIES,
    CLAIMS_COVERED_SERIES,
    CLAIMS_SERIES,
)
from scripts.macro_ingestion.us_employment.derived import (
    attribution_channels,
    chicago_fed_error,
    initial_claims_rate_of_covered,
    labor_force_absorption,
    monthly_delta,
    payroll_vs_breakeven,
    unrounded_u3,
)
from scripts.macro_ingestion.us_employment.labor_supply import current_breakeven_snapshot

_HISTORY = 13


def _failed(bundle: dict[str, Any], fallback: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": bundle.get("status") or "source_failed",
        "error": bundle.get("error") or fallback,
        "http_status": bundle.get("http_status"),
        "body": bundle.get("body") or b"",
        "challenge_page": bundle.get("challenge_page"),
    }


def _as_map(pairs: list[tuple[str, float]]) -> dict[str, float]:
    return {period: value for period, value in pairs}


def _series_pairs(bundle: dict[str, Any], series_id: str) -> list[tuple[str, float]]:
    return list((bundle.get("series") or {}).get(series_id) or [])


def _point(
    *,
    period: str,
    value: float,
    transform: str,
    formula: str,
    inputs: dict[str, Any],
    source_url: str,
    prior: float | None = None,
    vintage: str = "derived",
    revision_status: str = "final",
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "period": period,
        "value": value,
        "transformation": transform,
        "revision_status": revision_status,
        "source_url": source_url,
        "vintage": vintage,
        "derivation": {
            "publisher": "Market Watch",
            "deterministic": True,
            "formula": formula,
            "inputs": inputs,
            "score_input": False,
        },
    }
    if prior is not None:
        row["prior"] = prior
    return row


def _ok(points: list[dict[str, Any]], bundle: dict[str, Any]) -> dict[str, Any]:
    if not points:
        return {
            "ok": False,
            "status": "source_failed",
            "error": "derived_inputs_missing",
            "body": bundle.get("body") or b"",
            "http_status": bundle.get("http_status"),
        }
    return {
        "ok": True,
        "points": points[-_HISTORY:],
        "vintage": "derived",
        "raw_sha256": bundle.get("raw_sha256"),
        "http_status": bundle.get("http_status"),
        "body": bundle.get("body") or b"",
    }


def _levels_at(cps: dict[str, Any], period: str) -> dict[str, float]:
    wanted = {
        "unemployed": BLS_CPS_SERIES["US.Labor.unemployed"],
        "labor_force": BLS_CPS_SERIES["US.Labor.labor_force"],
        "household_employment": BLS_CPS_SERIES["US.Labor.household_employment"],
        "population": BLS_CPS_SERIES["US.Labor.population"],
        "job_losers": BLS_CPS_SERIES["US.Labor.unemployed_job_losers"],
        "job_leavers": BLS_CPS_SERIES["US.Labor.unemployed_job_leavers"],
        "reentrants": BLS_CPS_SERIES["US.Labor.unemployed_reentrants"],
        "new_entrants": BLS_CPS_SERIES["US.Labor.unemployed_new_entrants"],
        "flow_eu": BLS_CPS_SERIES["US.Labor.flow_eu"],
        "flow_ue": BLS_CPS_SERIES["US.Labor.flow_ue"],
        "flow_nu": BLS_CPS_SERIES["US.Labor.flow_nu"],
        "flow_un": BLS_CPS_SERIES["US.Labor.flow_un"],
        "flow_ne": BLS_CPS_SERIES["US.Labor.flow_ne"],
        "flow_en": BLS_CPS_SERIES["US.Labor.flow_en"],
    }
    levels: dict[str, float] = {}
    for name, series_id in wanted.items():
        values = _as_map(_series_pairs(cps, series_id))
        if period in values:
            levels[name] = values[period]
    return levels


def fetch_derived_series(
    spec: dict[str, Any],
    *,
    opener: Callable[..., Any],
    timeout: float,
    now: datetime,
) -> dict[str, Any]:
    catalog_id = str(spec["id"])
    transform = str(spec.get("transform") or "")
    end_year = now.year
    cps = load_bls_batch(opener, "cps", timeout=timeout, end_year=end_year)

    if catalog_id == "US.Labor.initial_claims_normalized":
        claims = load_claims_batch(opener, timeout=timeout, now=now)
        if not claims.get("ok"):
            return _failed(claims, "claims_batch_unavailable")
        initial = _as_map(_series_pairs(claims, CLAIMS_SERIES["US.Labor.initial_claims_revised"]))
        covered_levels = _as_map(_series_pairs(claims, CLAIMS_COVERED_SERIES))
        points = []
        previous = None
        for stamp in sorted(set(initial) & set(covered_levels)):
            covered = covered_levels[stamp]
            value = initial_claims_rate_of_covered(initial[stamp], covered)
            if value is None:
                continue
            period = stamp[:10]
            points.append(
                _point(
                    period=period,
                    value=value,
                    transform=transform or "percent",
                    formula="revised_initial_claims_sa / eta539_covered_employment * 100",
                    inputs={
                        "week_ending": period,
                        "initial_claims": initial[stamp],
                        "ui_covered_employment": covered,
                        "covered_employment_series": CLAIMS_COVERED_SERIES,
                        "claims_form": "ETA 539",
                        "vintage_kind": "revised",
                        "not_the_thursday_advance": True,
                        "monthly_interpolation": False,
                    },
                    source_url=claims.get("batch_url") or "",
                    prior=previous,
                    revision_status="revised",
                )
            )
            previous = value
        return _ok(points, claims)

    if not cps.get("ok"):
        return _failed(cps, "cps_batch_unavailable")

    unemployed = _series_pairs(cps, BLS_CPS_SERIES["US.Labor.unemployed"])
    labor_force = _series_pairs(cps, BLS_CPS_SERIES["US.Labor.labor_force"])
    household = _series_pairs(cps, BLS_CPS_SERIES["US.Labor.household_employment"])
    population = _series_pairs(cps, BLS_CPS_SERIES["US.Labor.population"])

    if catalog_id == "US.Labor.unrounded_u3":
        by_u = _as_map(unemployed)
        by_l = _as_map(labor_force)
        points = []
        previous = None
        for period in sorted(set(by_u) & set(by_l)):
            value = unrounded_u3(by_u[period], by_l[period])
            if value is None:
                continue
            points.append(
                _point(
                    period=period,
                    value=value,
                    transform=transform or "percent",
                    formula="unemployed / labor_force * 100",
                    inputs={
                        "unemployed": by_u[period],
                        "labor_force": by_l[period],
                        "unemployed_series": BLS_CPS_SERIES["US.Labor.unemployed"],
                        "labor_force_series": BLS_CPS_SERIES["US.Labor.labor_force"],
                        "replaces_published_unrate": False,
                    },
                    source_url="https://data.bls.gov/timeseries/LNS13000000",
                    prior=previous,
                )
            )
            previous = value
        return _ok(points, cps)

    def _delta_series(pairs: list[tuple[str, float]], formula: str, source_url: str) -> dict[str, Any]:
        if len(pairs) < 2:
            return {"ok": False, "status": "source_failed", "error": "derived_inputs_missing", "body": cps.get("body") or b""}
        points = []
        for (prev_period, prev_value), (period, value) in zip(pairs, pairs[1:]):
            if prev_period >= period:
                continue
            delta = monthly_delta(value, prev_value)
            points.append(
                _point(
                    period=period,
                    value=delta,
                    transform=transform or "mom_change_thousands",
                    formula=formula,
                    inputs={"period": period, "latest": value, "prior_period": prev_period, "prior": prev_value},
                    source_url=source_url,
                    prior=None,
                )
            )
        return _ok(points, cps)

    if catalog_id in {"US.Labor.delta_labor_force", "US.Labor.labor_force_change"}:
        return _delta_series(labor_force, "labor_force_t - labor_force_t-1", "https://data.bls.gov/timeseries/LNS11000000")
    if catalog_id == "US.Labor.delta_household_employment":
        return _delta_series(household, "household_employment_t - household_employment_t-1", "https://data.bls.gov/timeseries/LNS12000000")
    if catalog_id == "US.Labor.delta_unemployed":
        return _delta_series(unemployed, "unemployed_t - unemployed_t-1", "https://data.bls.gov/timeseries/LNS13000000")
    if catalog_id == "US.Labor.population_change":
        return _delta_series(population, "population_t - population_t-1", "https://data.bls.gov/timeseries/LNU00000000")

    if catalog_id == "US.Labor.labor_force_absorption":
        by_e = _as_map(household)
        by_l = _as_map(labor_force)
        periods = sorted(set(by_e) & set(by_l))
        points = []
        for previous_period, period in zip(periods, periods[1:]):
            delta_e = monthly_delta(by_e[period], by_e[previous_period])
            delta_l = monthly_delta(by_l[period], by_l[previous_period])
            points.append(
                _point(
                    period=period,
                    value=labor_force_absorption(delta_e, delta_l),
                    transform=transform or "mom_change_thousands",
                    formula="delta_household_employment - delta_labor_force",
                    inputs={
                        "delta_household_employment": delta_e,
                        "delta_labor_force": delta_l,
                        "prior_period": previous_period,
                    },
                    source_url="https://www.bls.gov/news.release/empsit.htm",
                )
            )
        return _ok(points, cps)

    if catalog_id == "US.Labor.chicago_fed_error":
        chicago = load_chicago_bundle(opener, timeout=timeout)
        if not chicago.get("ok"):
            return _failed(chicago, "chicago_fed_unavailable")
        by_u = _as_map(unemployed)
        by_l = _as_map(labor_force)
        nowcast = _as_map((chicago.get("series") or {}).get("CFLMIFORECASTFIN50") or [])
        points = []
        for period in sorted(set(by_u) & set(by_l) & set(nowcast)):
            actual = unrounded_u3(by_u[period], by_l[period])
            if actual is None:
                continue
            points.append(
                _point(
                    period=period,
                    value=chicago_fed_error(actual, nowcast[period]),
                    transform=transform or "percentage_points",
                    formula="unrounded_u3 - chicago_fed_final_nowcast_p50",
                    inputs={
                        "unrounded_u3": actual,
                        "chicago_fed_final_nowcast": nowcast[period],
                        "nowcast_series": "CFLMIFORECASTFIN50",
                        "release_type": "final",
                    },
                    source_url=str(chicago.get("source_url") or ""),
                    vintage=str(chicago.get("vintage") or "derived"),
                )
            )
        result = _ok(points, chicago if points else cps)
        if not points:
            result["error"] = "chicago_fed_error_waiting_for_overlapping_print"
        return result

    if catalog_id == "US.Labor.payroll_vs_breakeven":
        jolts = load_bls_batch(opener, "jolts", timeout=timeout, end_year=end_year)
        if not jolts.get("ok"):
            return _failed(jolts, "ces_payroll_unavailable")
        ces = _series_pairs(jolts, BLS_JOLTS_SERIES["US.Labor.payroll_level_ces"])
        snapshot = current_breakeven_snapshot(on=now.date())
        if snapshot is None or len(ces) < 2:
            return {"ok": False, "status": "source_failed", "error": "payroll_or_breakeven_unavailable", "body": jolts.get("body") or b""}
        published = date.fromisoformat(str(snapshot["publication_date"]))
        expires = date.fromisoformat(str(snapshot["expires_after"]))
        breakeven = float(snapshot["value_thousands_per_month"])
        points = []
        for (prev_period, prev_value), (period, value) in zip(ces, ces[1:]):
            year, month = int(period[:4]), int(period[5:7])
            payroll_day = date(year, month, 1)
            if payroll_day < date(published.year, published.month, 1) or payroll_day > expires:
                continue
            change = monthly_delta(value, prev_value)
            points.append(
                _point(
                    period=period,
                    value=payroll_vs_breakeven(change, breakeven),
                    transform=transform or "thousands",
                    formula="ces_total_nonfarm_mom_change - structural_breakeven",
                    inputs={
                        "payroll_change_thousands": change,
                        "payroll_level": value,
                        "prior_payroll_level": prev_value,
                        "prior_period": prev_period,
                        "breakeven_thousands_per_month": breakeven,
                        "breakeven_value_kind": snapshot.get("value_kind"),
                        "breakeven_period": snapshot.get("period"),
                        "breakeven_source_url": snapshot.get("source_url"),
                        "applied_as_regime": True,
                        "monthly_interpolation": False,
                        "score_anchor_unchanged": True,
                    },
                    source_url=str(snapshot.get("source_url") or ""),
                )
            )
        return _ok(points, jolts)

    diagnostic_ids = {
        "US.Labor.attr_job_loss": "job_loss",
        "US.Labor.attr_weak_job_finding": "weak_job_finding",
        "US.Labor.attr_entrant_reentrant": "entrant_reentrant",
    }
    accounting_ids = {
        "US.Labor.attr_labor_force_expansion": "labor_force_absorption",
        "US.Labor.attr_labor_force_exit": "identity_residual",
    }
    if catalog_id in diagnostic_ids or catalog_id in accounting_ids:
        periods = sorted(_as_map(unemployed))
        if len(periods) < 2:
            return {"ok": False, "status": "source_failed", "error": "derived_inputs_missing", "body": cps.get("body") or b""}
        points = []
        for previous_period, period in zip(periods, periods[1:]):
            report = attribution_channels(_levels_at(cps, period), _levels_at(cps, previous_period))
            accounting = report.get("accounting") or {}
            if catalog_id in diagnostic_ids:
                key = diagnostic_ids[catalog_id]
                value = (report.get("diagnostic_channels") or {}).get(key)
                formula = f"diagnostic_channel:{key}"
                source = (report.get("diagnostic_sources") or {}).get(key)
                additive = False
            else:
                key = accounting_ids[catalog_id]
                value = accounting.get(key)
                formula = f"accounting:{key}"
                source = "labor_force_and_household_employment"
                additive = False
            if value is None:
                continue
            points.append(
                _point(
                    period=period,
                    value=float(value),
                    transform=transform or "mom_change_thousands",
                    formula=formula,
                    inputs={
                        "prior_period": previous_period,
                        "source": source,
                        "additive_decomposition": additive,
                        "additive_labor_force_cause": False,
                        "delta_unemployed": accounting.get("delta_unemployed"),
                        "delta_labor_force": accounting.get("delta_labor_force"),
                        "delta_household_employment": accounting.get("delta_household_employment"),
                        "labor_force_absorption": accounting.get("labor_force_absorption"),
                        "identity_residual": accounting.get("identity_residual"),
                    },
                    source_url="https://www.bls.gov/news.release/empsit.htm",
                )
            )
        if not points:
            return {"ok": False, "status": "source_failed", "error": "attribution_inputs_missing", "body": cps.get("body") or b""}
        return _ok(points, cps)

    return {"ok": False, "status": "source_failed", "error": f"unknown_derived_series:{catalog_id}"}
