"""Stage 03: pre-trader quality gate (macro rows + market preflight)."""

from __future__ import annotations

import copy
from typing import Any

from scripts.country_registry import required_preflight_countries
from scripts.market_watch_launch.contract import (
    BLOCKING_SERIES_STATUSES,
    COUNTRIES,
    OPTIONAL_GAP_STATUSES,
    VERIFIED_OBSERVATION_STATUSES,
    stage_receipt,
)
from scripts.market_watch_launch.acquire import read_collect_families
from scripts.market_watch_launch.ingest import load_ingestion_rows
from scripts.overnight.freshness import required_preflight_block

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
    if raw not in VERIFIED_OBSERVATION_STATUSES:
        return raw
    release_due = bool(row.get("release_due"))
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


def _leg_statuses(packet: dict[str, Any]) -> dict[str, str]:
    legs = {f"{code}_rates": _rate_leg_status(packet, code) for code in COUNTRIES}
    legs["FX"] = _fx_leg_status(packet)
    return legs


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
        if effective in VERIFIED_OBSERVATION_STATUSES:
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
            elif all(_effective_status(r) in BLOCKING_SERIES_STATUSES for r in scored):
                bucket["scored_status"] = "blocked"
    return out


def evaluate_gate(
    *,
    rows: list[dict[str, Any]],
    families: dict[str, Any],
    catalog_roles: dict[str, dict] | None = None,
) -> dict[str, Any]:
    if catalog_roles:
        for row in rows:
            spec = catalog_roles.get(str(row.get("series_id") or ""))
            if spec and not row.get("role"):
                row["role"] = spec.get("role")
            if spec and row.get("weight") is None:
                row["weight"] = spec.get("weight")

    scored_rows = [row for row in rows if _is_scored_row(row)]
    verified_scored = [
        row for row in scored_rows if _effective_status(row) in VERIFIED_OBSERVATION_STATUSES
    ]
    # A scored failure blocks the launch only when that series is release-due.
    # Historical catalog gaps that are not due stay on the partial matrix.
    blocking_scored = [
        row
        for row in scored_rows
        if _effective_status(row) in BLOCKING_SERIES_STATUSES and bool(row.get("release_due"))
    ]
    nondue_scored_gaps = [
        row
        for row in scored_rows
        if _effective_status(row) in BLOCKING_SERIES_STATUSES and not bool(row.get("release_due"))
    ]
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

    blocked_sources = [str(row.get("series_id")) for row in blocking_scored if row.get("series_id")]

    base = {
        "outcome": "PASS",
        "coverage": "COMPLETE",
        "reason": None,
        "blocked_sources": blocked_sources,
        "blocked_legs": [],
        "partial_expressions": partial_expressions,
        "partial_series": partial_series,
        "eligible": False,
        "hold_decisions_emitted": 0,
        "synthetic_holds": False,
        "countries": _country_rollups(rows),
    }

    if not scored_rows or len(verified_scored) == 0:
        base["outcome"] = "BLOCKED"
        base["coverage"] = "NONE"
        base["reason"] = "all_critical_missing"
        base["eligible"] = False
        return base

    if blocking_scored:
        base["outcome"] = "BLOCKED"
        base["coverage"] = "NONE"
        base["reason"] = "stale_or_missing_source"
        base["eligible"] = False
        return base

    market_block = families.get("market_state") or {}
    market_status = str(market_block.get("status") or "missing")
    packet = _market_packet(families)
    if market_status in _BLOCKING_LEG_STATUSES or packet is None:
        base["outcome"] = "BLOCKED"
        base["coverage"] = "NONE"
        base["reason"] = "no_markable_universe"
        base["eligible"] = False
        return base

    preflight = required_preflight_block(families)
    if preflight:
        base["outcome"] = "BLOCKED"
        base["coverage"] = "NONE"
        base["reason"] = "missing_required_mark"
        base["blocked_legs"] = ["preflight"]
        base["eligible"] = False
        return base

    legs = _leg_statuses(packet)
    required = set(required_preflight_countries())
    partial_legs: list[str] = []
    blocked_legs: list[str] = []
    required_rate_ok = False
    for leg, status in legs.items():
        if leg == "FX":
            if status in _BLOCKING_LEG_STATUSES:
                blocked_legs.append("FX")
            continue
        country = leg.replace("_rates", "")
        if country in required:
            if status in _BLOCKING_LEG_STATUSES:
                blocked_legs.append(leg)
            elif status not in _BLOCKING_LEG_STATUSES:
                required_rate_ok = True
        elif status in _BLOCKING_LEG_STATUSES:
            partial_legs.append(leg)

    if blocked_legs:
        base["outcome"] = "BLOCKED"
        base["coverage"] = "NONE"
        base["reason"] = "no_markable_universe"
        base["blocked_legs"] = blocked_legs
        base["eligible"] = False
        return base

    fx_status = legs.get("FX", "missing")
    markable = required_rate_ok and fx_status not in _BLOCKING_LEG_STATUSES
    if not markable:
        base["outcome"] = "BLOCKED"
        base["coverage"] = "NONE"
        base["reason"] = "no_markable_universe"
        base["eligible"] = False
        return base

    base["partial_legs"] = partial_legs
    if optional_gaps or partial_legs or nondue_scored_gaps:
        base["coverage"] = "PARTIAL"
    else:
        base["coverage"] = "COMPLETE"
    base["eligible"] = True
    return base


def apply_macro_overlay(families: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    out = copy.deepcopy(families)
    macro = dict(out.get("macro_hard") or {})
    notes = list(macro.get("notes") or [])

    if not rows:
        macro["status"] = "invalid"
        notes.append("macro ingestion rows empty")
    else:
        blocking_countries: set[str] = set()
        scored_countries: set[str] = set()
        for row in rows:
            if not _is_scored_row(row):
                continue
            country = str(row.get("country") or "")
            if country:
                scored_countries.add(country)
            if _effective_status(row) in BLOCKING_SERIES_STATUSES:
                blocking_countries.add(country)
        if blocking_countries and blocking_countries == scored_countries:
            macro["status"] = "invalid"
        elif blocking_countries:
            macro["status"] = "stale"
        else:
            macro["status"] = "fresh"

    macro["notes"] = notes
    macro["components"] = [dict(row) for row in rows]
    out["macro_hard"] = macro
    return out


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

    result = evaluate_gate(rows=rows, families=families)
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
