"""Stage 03: pre-trader quality gate (macro rows + market preflight)."""

from __future__ import annotations

import copy
import math
import re
from datetime import date
from typing import Any

from scripts.country_registry import economies, paper_sovereign_admission
from scripts.policy_path_data import _iso_calendar_date

from scripts.market_watch_launch.contract import (
    BLOCKING_SERIES_STATUSES,
    COUNTRIES,
    OPTIONAL_GAP_STATUSES,
    VERIFIED_OBSERVATION_STATUSES,
    stage_receipt,
)
from scripts.macro_source_health import carried_forward, effective_release_due, source_health_entries
from scripts.market_watch_launch.acquire import read_collect_families
from scripts.market_watch_launch.ingest import load_ingestion_rows
from scripts.run_state.policy import evaluate_policy
_STAGE = "03_quality_gate"
_BLOCKING_LEG_STATUSES = frozenset({"stale", "missing", "invalid", "unavailable"})
_ZERO_WEIGHT_ROLES = frozenset({"context", "registry_unweighted", "explanatory_alias"})


def _is_scored_row(row: dict[str, Any]) -> bool:
    if str(row.get("role") or "") == "scored":
        return True
    weight = row.get("weight")
    if weight is None:
        return False
    try:
        return float(weight) > 0
    except (TypeError, ValueError):
        return False


def _effective_status(row: dict[str, Any]) -> str:
    raw = str(row.get("status") or "")
    release_due = effective_release_due(row)
    if raw not in VERIFIED_OBSERVATION_STATUSES:
        return raw
    if not release_due:
        return raw
    observation_period = row.get("observation_period")
    due_period = row.get("due_period")
    if observation_period and due_period and str(observation_period) == str(due_period):
        return raw
    return "due_missing"


def _is_optional_gap(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or "")
    if status == "license_gap":
        return True
    if str(row.get("role") or "") in _ZERO_WEIGHT_ROLES:
        return True
    series_id = str(row.get("series_id") or "")
    weight = row.get("weight")
    weight_zero = weight is None or weight == 0 or weight == 0.0
    if "pmi" in series_id.lower() and weight_zero and status in OPTIONAL_GAP_STATUSES:
        return True
    return False


def _optional_expression(row: dict[str, Any]) -> str | None:
    series_id = str(row.get("series_id") or "")
    if "pmi" not in series_id.lower():
        return None
    country = str(row.get("country") or "")
    if not country:
        return None
    return f"activity:{country}"


def _market_packet(families: dict[str, Any]) -> dict[str, Any] | None:
    block = families.get("market_state") or {}
    data = block.get("data") if isinstance(block, dict) else None
    return data if isinstance(data, dict) else None


def _explicit_status(block: Any) -> str | None:
    if not isinstance(block, dict):
        return None
    status = block.get("status")
    if isinstance(status, str) and status:
        return status
    return None


def _has_numeric_mark(block: dict[str, Any]) -> bool:
    for value in block.values():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return True
    return False


def _rate_leg_status(packet: dict[str, Any], code: str) -> str:
    rates = packet.get("rates") if isinstance(packet.get("rates"), dict) else {}
    block = rates.get(code)
    explicit = _explicit_status(block)
    if explicit:
        return explicit
    if isinstance(block, dict) and _has_numeric_mark(block):
        return "ok"
    policy = packet.get("policy_paths") if isinstance(packet.get("policy_paths"), dict) else {}
    countries = policy.get("countries") if isinstance(policy.get("countries"), dict) else {}
    policy_status = _explicit_status(countries.get(code))
    if policy_status:
        return policy_status
    return "missing"


def _fx_leg_status(packet: dict[str, Any]) -> str:
    fx = packet.get("fx") if isinstance(packet.get("fx"), dict) else {}
    explicit = _explicit_status(fx)
    if explicit:
        return explicit
    for value in fx.values():
        if isinstance(value, dict) and any(key in value for key in ("spot", "mid", "rate")):
            return "ok"
    return "missing"


def _approved_curve_markable(packet: dict[str, Any], code: str) -> bool:
    """True when an approved country's tradable curve carries a usable mark.

    Research-only sovereigns and observe-only curves do not count. A blocking
    curve status is not a mark, even when a number is still present.
    """
    if _research_only_sovereign(code):
        return False
    spec = economies().get(code) or {}
    if not spec.get("has_tradable_short_rate_curve"):
        return False
    curve_id = spec.get("tradable_curve_id")
    if not isinstance(curve_id, str) or not curve_id:
        return False
    curves = packet.get("tradable_rate_curves")
    curve_map = curves.get("curves") if isinstance(curves, dict) else None
    block = curve_map.get(curve_id) if isinstance(curve_map, dict) else None
    if not isinstance(block, dict):
        return False
    explicit = _explicit_status(block)
    if explicit in _BLOCKING_LEG_STATUSES:
        return False
    if explicit == "ok":
        return True
    if explicit:
        return False
    contracts = block.get("contracts")
    if not isinstance(contracts, list):
        return False
    for row in contracts:
        if not isinstance(row, dict):
            continue
        row_status = _explicit_status(row)
        if row_status in _BLOCKING_LEG_STATUSES:
            continue
        for key in ("implied_rate", "rate", "value"):
            value = row.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if math.isfinite(float(value)):
                return True
    return False


def _research_only_sovereign(code: str) -> bool:
    return paper_sovereign_admission(code) == "research_only"


_SOFR_CONTRACT_INSTRUMENT = re.compile(r"^SOFR_(20\d{2}-\d{2})$", re.I)


def _session_calendar_date(packet: dict[str, Any]) -> date | None:
    observed = _iso_calendar_date(packet.get("generated_at"))
    if not observed:
        return None
    return date.fromisoformat(observed)


def _sofr_contract_row(packet: dict[str, Any], expiry: str) -> dict[str, Any] | None:
    curves = packet.get("tradable_rate_curves")
    curve_map = curves.get("curves") if isinstance(curves, dict) else None
    block = curve_map.get("SOFR") if isinstance(curve_map, dict) else None
    if not isinstance(block, dict):
        return None
    target = expiry.upper()
    for row in block.get("contracts") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("expiry") or "").upper() == target:
            return row
    return None


def _sofr_contract_provenance(
    packet: dict[str, Any],
    expiry: str,
) -> tuple[str | None, str]:
    """Return (observation_date, dependency_status) for a held SOFR contract."""
    session = _session_calendar_date(packet)
    if session is None:
        row = _sofr_contract_row(packet, expiry)
        row_date = None
        if row is not None:
            for key in ("observation_date", "as_of"):
                candidate = _iso_calendar_date(row.get(key))
                if candidate and candidate != expiry:
                    row_date = candidate
                    break
        return row_date, "invalid"

    row = _sofr_contract_row(packet, expiry)
    if row is None:
        return None, "missing"
    provenance = None
    for key in ("observation_date", "as_of"):
        candidate = _iso_calendar_date(row.get(key))
        if candidate and candidate != expiry:
            provenance = candidate
            break
    if not provenance:
        return None, "invalid"

    observed = date.fromisoformat(provenance)
    delta = (session - observed).days
    if delta > 8:
        return provenance, "stale"
    if delta < -1:
        return provenance, "invalid"
    return provenance, "ok"


def _sofr_contract_unmarkable_row(
    packet: dict[str, Any],
    position: dict[str, Any],
    *,
    expiry: str,
    failure: str,
    dependency_status: str,
    observation_date: str | None,
) -> dict[str, Any]:
    instrument = position.get("instrument")
    return {
        "position_id": position.get("position_id"),
        "seat": position.get("seat"),
        "instrument": instrument,
        "asset_class": position.get("asset_class"),
        "paper_expression": position.get("paper_expression") or position.get("expression"),
        "dependency": "SOFR_curve",
        "dependency_status": dependency_status,
        "observation_date": observation_date,
        "reason": (
            f"position {instrument!r} SOFR contract {expiry} is unmarkable ({failure})"
        ),
    }


def _unmarkable_positions(
    packet: dict[str, Any],
    positions: list[Any],
) -> list[dict[str, Any]]:
    from scripts.overnight.freshness import _dependency_status, expression_dependencies
    from scripts.overnight.paper_marks import PaperMarkError, resolve_paper_mid

    out: list[dict[str, Any]] = []
    for position in positions:
        if not isinstance(position, dict):
            continue
        instrument = position.get("instrument")
        asset_class = position.get("asset_class")
        expression = position.get("paper_expression") or position.get("expression")
        seat = position.get("seat")
        position_id = position.get("position_id")
        for dependency in sorted(
            expression_dependencies(
                instrument,
                asset_class=asset_class,
                expression=expression,
            )
        ):
            status = _dependency_status(packet, dependency)
            if status in _BLOCKING_LEG_STATUSES:
                observation_date = None
                if dependency.endswith("_rates"):
                    code = dependency[: -len("_rates")]
                    rates = packet.get("rates") if isinstance(packet.get("rates"), dict) else {}
                    block = rates.get(code) if isinstance(rates, dict) else None
                    if isinstance(block, dict):
                        observation_date = block.get("latest_observation")
                out.append(
                    {
                        "position_id": position_id,
                        "seat": seat,
                        "instrument": instrument,
                        "asset_class": asset_class,
                        "paper_expression": expression,
                        "dependency": dependency,
                        "dependency_status": status,
                        "observation_date": observation_date,
                        "reason": (
                            f"position {instrument!r} depends on {dependency} ({status}); "
                            f"latest observation {observation_date}"
                        ),
                    }
                )
                break
            if dependency != "SOFR_curve":
                continue
            match = _SOFR_CONTRACT_INSTRUMENT.match(str(instrument or ""))
            if not match:
                continue
            expiry = match.group(1)
            try:
                mark = resolve_paper_mid(
                    packet,
                    str(instrument),
                    asset_class=asset_class,
                )
                rate = float(mark["value"])
                if not math.isfinite(rate) or rate <= -2 or rate >= 25:
                    raise PaperMarkError(f"SOFR contract {expiry} implied rate out of bounds")
            except PaperMarkError:
                provenance, dep_status = _sofr_contract_provenance(packet, expiry)
                if _sofr_contract_row(packet, expiry) is None:
                    failure = "missing"
                    dep_status = "missing"
                else:
                    failure = "invalid"
                    dep_status = dep_status if dep_status != "ok" else "invalid"
                out.append(
                    _sofr_contract_unmarkable_row(
                        packet,
                        position,
                        expiry=expiry,
                        failure=failure,
                        dependency_status=dep_status,
                        observation_date=provenance,
                    )
                )
                break
            provenance, dep_status = _sofr_contract_provenance(packet, expiry)
            if dep_status != "ok":
                if dep_status == "invalid" and provenance is None:
                    failure = "undated"
                else:
                    failure = {
                        "missing": "missing",
                        "stale": "stale",
                        "invalid": "invalid",
                    }.get(dep_status, dep_status)
                out.append(
                    _sofr_contract_unmarkable_row(
                        packet,
                        position,
                        expiry=expiry,
                        failure=failure,
                        dependency_status=dep_status,
                        observation_date=provenance,
                    )
                )
                break
    return out


def _leg_statuses(packet: dict[str, Any]) -> dict[str, str]:
    legs = {f"{code}_rates": _rate_leg_status(packet, code) for code in COUNTRIES}
    legs["FX"] = _fx_leg_status(packet)
    return legs


def _counts_as_verified_scored(row: dict[str, Any]) -> bool:
    """Verified vintage, including a not-due series carried forward after a fetch failure."""
    if _effective_status(row) in VERIFIED_OBSERVATION_STATUSES:
        return True
    return carried_forward(row)


def _country_has_verified_scored(rows: list[dict[str, Any]], country: str) -> bool:
    for row in rows:
        if str(row.get("country") or "") != country:
            continue
        if not _is_scored_row(row):
            continue
        if _counts_as_verified_scored(row):
            return True
    return False


def _country_release_due_blocking(rows: list[dict[str, Any]], country: str) -> list[dict[str, Any]]:
    blocked: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("country") or "") != country:
            continue
        if not _is_scored_row(row):
            continue
        effective = _effective_status(row)
        if effective in BLOCKING_SERIES_STATUSES and effective_release_due(row):
            blocked.append(row)
    return blocked


def _research_coverage_gaps(rows: list[dict[str, Any]]) -> list[str]:
    gaps: list[str] = []
    for code in COUNTRIES:
        scored = [
            row
            for row in rows
            if str(row.get("country") or "") == code and _is_scored_row(row)
        ]
        if not scored:
            continue
        if _country_release_due_blocking(rows, code):
            gaps.append(f"macro:{code}")
        elif not _country_has_verified_scored(rows, code):
            gaps.append(f"macro:{code}")
    return gaps


def _country_rollups(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {code: {"scored_status": "missing", "gaps": []} for code in COUNTRIES}
    for row in rows:
        country = str(row.get("country") or "")
        if country not in out:
            continue
        if not _is_scored_row(row):
            continue
        effective = _effective_status(row)
        bucket = out[country]
        if _counts_as_verified_scored(row):
            if bucket["scored_status"] in {"missing", "ok"}:
                bucket["scored_status"] = "ok"
        elif effective in BLOCKING_SERIES_STATUSES:
            if bucket["scored_status"] != "blocked":
                bucket["scored_status"] = "blocked" if bucket["scored_status"] == "missing" else "partial"
            bucket["gaps"].append(str(row.get("series_id")))
        elif _is_optional_gap(row):
            if bucket["scored_status"] == "missing":
                bucket["scored_status"] = "partial"
            bucket["gaps"].append(str(row.get("series_id")))
    for country, bucket in out.items():
        if bucket["scored_status"] == "missing":
            scored = [r for r in rows if r.get("country") == country and _is_scored_row(r)]
            if not scored:
                bucket["scored_status"] = "missing"
            elif all(
                _effective_status(r) in BLOCKING_SERIES_STATUSES and not _counts_as_verified_scored(r)
                for r in scored
            ):
                bucket["scored_status"] = "blocked"
    return out


def evaluate_gate(
    *,
    rows: list[dict[str, Any]],
    families: dict[str, Any],
    catalog_roles: dict[str, dict] | None = None,
    positions: list | None = None,
) -> dict[str, Any]:
    if catalog_roles:
        for row in rows:
            spec = catalog_roles.get(str(row.get("series_id") or ""))
            if spec and not row.get("role"):
                row["role"] = spec.get("role")
            if spec and row.get("weight") is None:
                row["weight"] = spec.get("weight")

    scored_rows = [row for row in rows if _is_scored_row(row)]
    # Macro release gaps stay on the research-coverage list. They do not block
    # a launch that still has a markable rate leg or FX leg.
    blocking_scored = [
        row
        for row in scored_rows
        if _effective_status(row) in BLOCKING_SERIES_STATUSES and effective_release_due(row)
    ]
    nondue_scored_gaps = [
        row
        for row in scored_rows
        if _effective_status(row) in BLOCKING_SERIES_STATUSES
        and not effective_release_due(row)
        and not carried_forward(row)
    ]
    source_health = source_health_entries(rows)
    optional_gaps = [row for row in rows if _is_optional_gap(row)]

    partial_expressions: list[str] = []
    for row in optional_gaps:
        expr = _optional_expression(row)
        if expr and expr not in partial_expressions:
            partial_expressions.append(expr)
    partial_series = [str(row.get("series_id")) for row in nondue_scored_gaps if row.get("series_id")]
    for row in nondue_scored_gaps:
        country = str(row.get("country") or "")
        if not country:
            continue
        expr = f"macro:{country}"
        if expr not in partial_expressions:
            partial_expressions.append(expr)

    research_coverage_series = [
        str(row.get("series_id")) for row in blocking_scored if row.get("series_id")
    ]
    research_coverage_gaps = _research_coverage_gaps(rows)
    blocked_sources: list[str] = []
    blocked_expressions: list[str] = []

    countries = _country_rollups(rows)

    base: dict[str, Any] = {
        "outcome": "PASS",
        "coverage": "COMPLETE",
        "reason": None,
        "blocked_sources": blocked_sources,
        "blocked_expressions": blocked_expressions,
        "research_coverage_gaps": research_coverage_gaps,
        "research_coverage_series": research_coverage_series,
        "blocked_legs": [],
        "partial_expressions": partial_expressions,
        "partial_series": partial_series,
        "eligible": False,
        "hold_decisions_emitted": 0,
        "synthetic_holds": False,
        "countries": countries,
        "countries_unaffected": [],
        "source_health": source_health,
    }

    if not scored_rows:
        base["research_coverage_gaps"] = [f"macro:{code}" for code in COUNTRIES]

    market_block = families.get("market_state") or {}
    market_status = str(market_block.get("status") or "missing")
    packet = _market_packet(families)
    if packet is None:
        base["outcome"] = "BLOCKED"
        base["coverage"] = "NONE"
        base["reason"] = "no_markable_universe"
        base["eligible"] = False
        return base
    if market_status in {"missing", "invalid", "unavailable"}:
        base["outcome"] = "BLOCKED"
        base["coverage"] = "NONE"
        base["reason"] = "no_markable_universe"
        base["eligible"] = False
        return base
    # A stale packet is not an empty universe. Each rate leg and the FX family
    # are judged on their own. One stale cash curve does not ban expressions
    # that do not use it. A missing, stale, invalid, or unavailable FX family
    # blocks FX expressions. Approved rate or curve marks stay eligible.

    legs = _leg_statuses(packet)
    fx_status = str(legs.get("FX") or "missing")
    fx_blocking = fx_status in _BLOCKING_LEG_STATUSES

    partial_legs: list[str] = []
    trade_eligible_countries: list[str] = []
    for code in COUNTRIES:
        rate_status = legs.get(f"{code}_rates", "missing")
        rates_blocking = rate_status in _BLOCKING_LEG_STATUSES
        research_only = _research_only_sovereign(code)
        if research_only:
            countries[code]["sovereign_admission"] = "research_only"
        if rates_blocking:
            partial_legs.append(f"{code}_rates")
        # NZ sovereign cash is research-only. An unsupported curve must not
        # label the country restricted while NZD spot still has a mark.
        # When the FX family cannot be marked, that spot is unavailable, and
        # a research-only curve does not count as an executable rates leg.
        curve_markable = False
        if fx_blocking and not research_only and rates_blocking:
            curve_markable = _approved_curve_markable(packet, code)
            if curve_markable:
                countries[code]["curve_markable"] = True
        if research_only:
            country_eligible = not fx_blocking
        else:
            country_eligible = (not rates_blocking) or curve_markable
        countries[code]["eligible"] = country_eligible
        if country_eligible:
            trade_eligible_countries.append(code)

    if fx_blocking:
        base["blocked_legs"] = ["FX"]
        partial_legs.append("FX")
        base["fx_leg_status"] = fx_status

    base["partial_legs"] = partial_legs
    base["trade_eligible_countries"] = trade_eligible_countries
    if positions:
        from scripts.overnight.mark_admission import quarantine_decision

        unmarkable = _unmarkable_positions(packet, positions)
        if unmarkable:
            decision = quarantine_decision(
                unmarkable, trade_eligible_countries=trade_eligible_countries
            )
            base["unmarkable_positions"] = unmarkable
            base.update(decision["gate_fields"])
            if decision["mode"] == "block":
                base["outcome"] = "BLOCKED"
                base["reason"] = "existing_book_unmarkable"
                base["eligible"] = False
                base["coverage"] = "PARTIAL" if trade_eligible_countries else "NONE"
                return base

    if not trade_eligible_countries:
        base["outcome"] = "BLOCKED"
        base["coverage"] = "NONE"
        base["reason"] = "no_markable_universe"
        base["eligible"] = False
        return base
    has_partial = bool(
        optional_gaps
        or partial_legs
        or nondue_scored_gaps
        or research_coverage_gaps
        or base.get("quarantined_positions")
    )
    base["coverage"] = "PARTIAL" if has_partial else "COMPLETE"
    base["eligible"] = True
    return base


def _minimal_passing_market_families() -> dict[str, Any]:
    return {
        "macro_hard": {"status": "fresh", "notes": []},
        "market_state": {
            "status": "fresh",
            "data": {
                "rates": {code: {"status": "ok"} for code in COUNTRIES},
                "fx": {"status": "ok"},
            },
        },
    }


def _gate_rows_from_states(states: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for state in states:
        series_id = str(state.get("series_id") or "")
        country = str(state.get("country") or (series_id.split(".", 1)[0] if "." in series_id else ""))
        trade_critical = bool(state.get("trade_critical"))
        if not trade_critical:
            role = state.get("role")
            weight = state.get("weight")
            if role == "scored" and weight is not None:
                try:
                    trade_critical = float(weight) > 0
                except (TypeError, ValueError):
                    trade_critical = False
        role = "scored" if trade_critical else str(state.get("role") or "context")
        weight = state.get("weight")
        if weight is None:
            weight = 1.0 if trade_critical else 0.0
        reason = state.get("carry_forward_reason")
        row: dict[str, Any] = {
            "series_id": series_id,
            "country": country,
            "role": role,
            "weight": weight,
        }
        if reason == "overdue_unverified":
            row.update({"status": "source_failed", "release_due": True})
        elif reason == "old_after_failed_check":
            row.update({"status": "source_failed", "release_due": False})
        elif reason == "old_but_current":
            row.update(
                {
                    "status": "checked_unchanged",
                    "release_due": False,
                    "observation_period": "2026-08",
                }
            )
        elif reason == "unknown_calendar":
            row.update({"status": "checked_unchanged", "release_due": False})
        else:
            row.update({"status": "checked_unchanged", "release_due": False, "observation_period": "2026-08"})
        rows.append(row)
    return rows


def _apply_policy_overlay(
    result: dict[str, Any], policy: dict[str, Any], states: list[dict[str, Any]]
) -> dict[str, Any]:
    del states  # Trade eligibility comes from the gate's rate legs, not these states.
    out = dict(result)
    legacy_outcome = out.get("outcome")
    out["policy_version"] = policy["policy_version"]

    research_coverage_gaps: list[str] = []
    for source in (
        result.get("research_coverage_gaps") or [],
        policy.get("research_coverage_gaps") or [],
    ):
        for item in source:
            text = str(item)
            if text not in research_coverage_gaps:
                research_coverage_gaps.append(text)

    merged_blocks: list[str] = []
    for expr in list(result.get("blocked_expressions") or []) + list(
        policy.get("blocked_expressions") or []
    ):
        if isinstance(expr, str) and expr.startswith("macro:"):
            if expr not in research_coverage_gaps:
                research_coverage_gaps.append(expr)
            continue
        if expr not in merged_blocks:
            merged_blocks.append(str(expr))

    research_coverage_series: list[str] = []
    for source in (
        result.get("research_coverage_series") or [],
        policy.get("research_coverage_series") or [],
    ):
        for sid in source:
            text = str(sid)
            if text not in research_coverage_series:
                research_coverage_series.append(text)

    partial_legs = list(out.get("partial_legs") or [])

    countries = out.get("countries")
    if not isinstance(countries, dict):
        countries = {}
        out["countries"] = countries

    trade_eligible: list[str] = []
    for code in COUNTRIES:
        bucket = countries.get(code)
        if not isinstance(bucket, dict):
            bucket = {}
            countries[code] = bucket
        rate_leg = f"{code}_rates"
        policy_info = (policy.get("countries") or {}).get(code) or {}
        research_cov = policy_info.get("research_coverage")
        if isinstance(research_cov, str) and research_cov:
            bucket["research_coverage"] = research_cov

        research_only = _research_only_sovereign(code)
        if research_only:
            bucket["sovereign_admission"] = "research_only"
        fx_blocked = "FX" in list(out.get("blocked_legs") or [])
        if research_only and fx_blocked:
            eligible = False
        elif rate_leg in partial_legs and not research_only:
            eligible = bool(bucket.get("curve_markable"))
        elif legacy_outcome == "BLOCKED":
            eligible = bool(bucket.get("eligible"))
        else:
            eligible = True

        bucket["eligible"] = eligible
        if eligible:
            trade_eligible.append(code)

    out["blocked_expressions"] = merged_blocks
    out["research_coverage_gaps"] = research_coverage_gaps
    out["research_coverage_series"] = research_coverage_series
    out["trade_eligible_countries"] = trade_eligible

    if legacy_outcome != "BLOCKED":
        if trade_eligible:
            out["eligible"] = True
        if legacy_outcome == "PASS":
            out["outcome"] = "PASS"
        elif trade_eligible and not merged_blocks:
            out["outcome"] = "PASS"
    return out


def evaluate_gate_canonical(
    states: list[dict[str, Any]],
    families: dict[str, Any] | None,
    *,
    cutoff_at: str | None = None,
    freeze_cutoff: str | None = None,
) -> dict[str, Any]:
    packet = families if families is not None else _minimal_passing_market_families()
    policy = evaluate_policy(states)
    rows = _gate_rows_from_states(states)
    result = evaluate_gate(rows=rows, families=packet)
    result = _apply_policy_overlay(result, policy, states)
    if cutoff_at is not None:
        result["cutoff_at"] = cutoff_at
    if freeze_cutoff is not None:
        result["freeze_cutoff"] = freeze_cutoff
    return result


def apply_macro_overlay(families: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Overlay live rows using the same due-aware country logic as the quality gate."""
    out = copy.deepcopy(families)
    macro = dict(out.get("macro_hard") or {})
    notes = list(macro.get("notes") or [])

    if not rows:
        macro["status"] = "stale"
        macro["fresh_countries"] = []
        macro["stale_countries"] = []
        macro["research_coverage_countries"] = list(COUNTRIES)
        notes.append("macro ingestion rows empty")
    else:
        fresh_countries: list[str] = []
        research_coverage_countries: list[str] = []
        for code in COUNTRIES:
            verified = _country_has_verified_scored(rows, code)
            due_block = _country_release_due_blocking(rows, code)
            if verified and not due_block:
                fresh_countries.append(code)
            else:
                research_coverage_countries.append(code)

        macro["fresh_countries"] = fresh_countries
        macro["research_coverage_countries"] = research_coverage_countries
        # Research coverage gaps are informational; they must not block trading legs.
        macro["stale_countries"] = []
        if fresh_countries:
            macro["status"] = "fresh"
        elif research_coverage_countries:
            macro["status"] = "stale"
        else:
            macro["status"] = "invalid"
        if research_coverage_countries:
            notes.append(
                "country-specific macro research coverage gaps: "
                + ", ".join(research_coverage_countries)
            )
        carried = sorted({str(row.get("country")) for row in rows if carried_forward(row) and row.get("country")})
        if carried:
            macro["source_health_countries"] = carried
            research_set = set(research_coverage_countries)
            carried_not_stale = [code for code in carried if code not in research_set]
            if carried_not_stale:
                notes.append(
                    "source-health carry-forward (not-due, prior vintage kept): "
                    + ", ".join(carried_not_stale)
                )

    macro["notes"] = notes
    macro["source_health"] = source_health_entries(rows)
    macro["components"] = [dict(row) for row in rows]
    out["macro_hard"] = macro
    return out


def _annotate_source_health(rows: list[dict[str, Any]], ctx: dict) -> list[dict[str, Any]]:
    """Carry forward canonical vintages when a not-due fetch failed transiently."""
    root = ctx.get("root")
    if root is None:
        return rows
    try:
        from pathlib import Path

        from scripts.macro_ingestion.contract import index_series_rows, load_catalog
        from scripts.macro_source_health import annotate_rows
        from scripts.temperature_level import load_history

        history_dir = Path(root) / "data" / "temperature_history"
        if not history_dir.is_dir():
            return rows
        histories = load_history(history_dir)
        catalog = load_catalog()
        return annotate_rows(rows, histories=histories, catalog_by_id=index_series_rows(catalog["series"]))
    except Exception:
        return rows


def _positions_from_books(books: dict[str, Any], *seat_keys: str) -> list[dict[str, Any]]:
    positions: list[dict[str, Any]] = []
    for seat_key in seat_keys:
        seats = books.get(seat_key) if isinstance(books.get(seat_key), dict) else {}
        for seat, seat_book in seats.items():
            if not isinstance(seat_book, dict):
                continue
            for position in seat_book.get("positions") or []:
                if not isinstance(position, dict):
                    continue
                row = dict(position)
                row.setdefault("seat", seat)
                positions.append(row)
    return positions


def _load_open_positions(ctx: dict) -> list[dict[str, Any]] | None:
    """Read-only open positions for the launch store. Missing files are an empty book.

    Trader books use ``seats``. PM books use ``pms``. A present file that cannot
    be read fails the stage instead of skipping the existing-book check.
    """
    root = ctx.get("overnight_store_root") or ctx.get("root")
    if root is None:
        return None
    from pathlib import Path

    from scripts.overnight.store import OvernightStore, read_json
    from scripts.pm.constants import BOOKS_RELPATH as PM_BOOKS_RELPATH

    state_root = Path(root)
    repo_root = Path(ctx.get("root") or state_root)
    positions: list[dict[str, Any]] = []
    overnight = OvernightStore(root=repo_root, state_root=state_root)
    if overnight.books_path().is_file():
        books = overnight.read_books()
        if isinstance(books, dict):
            positions.extend(_positions_from_books(books, "seats"))
    pm_path = state_root / PM_BOOKS_RELPATH
    if pm_path.is_file():
        pm_books = read_json(pm_path)
        if isinstance(pm_books, dict):
            positions.extend(_positions_from_books(pm_books, "pms", "seats"))
    return positions


def run(launch: dict, ctx: dict) -> dict:
    ingest_stage = (launch.get("stages") or {}).get("01_ingest") or {}
    acquire_stage = (launch.get("stages") or {}).get("02_acquire") or {}
    if ingest_stage.get("status") != "succeeded" or acquire_stage.get("status") != "succeeded":
        return stage_receipt(
            _STAGE,
            status="failed",
            input_sha256=None,
            reason="prior_stage_not_verified",
            details={"outcome": "BLOCKED", "reason": "prior_stage_not_verified"},
        )

    ingest_details = ingest_stage.get("details") or {}
    rows = load_ingestion_rows(ingest_details)
    if not rows:
        return stage_receipt(
            _STAGE,
            status="failed",
            input_sha256=None,
            reason="prior_stage_not_verified",
            details={"outcome": "BLOCKED", "reason": "prior_stage_not_verified"},
        )

    families = read_collect_families(ctx, launch)
    if not families:
        families = {}

    rows = _annotate_source_health(rows, ctx)
    result = evaluate_gate(rows=rows, families=families, positions=_load_open_positions(ctx))
    series_run_states = ingest_details.get("series_run_states")
    if isinstance(series_run_states, list) and series_run_states:
        policy = evaluate_policy(series_run_states)
        result = _apply_policy_overlay(result, policy, series_run_states)
        if ingest_details.get("score_state_sha256"):
            result["score_state_sha256"] = ingest_details["score_state_sha256"]
        state_ids = sorted(
            str(st["state_id"])
            for st in series_run_states
            if isinstance(st, dict) and st.get("state_id")
        )
        if state_ids:
            result["state_ids"] = state_ids
    if ctx.get("cutoff_at") is not None:
        result["cutoff_at"] = ctx["cutoff_at"]
    if ctx.get("freeze_cutoff") is not None:
        result["freeze_cutoff"] = ctx["freeze_cutoff"]
    if result["outcome"] == "BLOCKED":
        return stage_receipt(
            _STAGE,
            status="blocked",
            input_sha256=None,
            reason=str(result.get("reason")),
            details=result,
        )
    return stage_receipt(
        _STAGE,
        status="succeeded",
        input_sha256=None,
        details=result,
    )
