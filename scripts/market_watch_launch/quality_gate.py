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
from scripts.macro_source_health import carried_forward, source_health_entries
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
        if effective in BLOCKING_SERIES_STATUSES and bool(row.get("release_due")):
            blocked.append(row)
    return blocked


def _macro_eligible_countries(rows: list[dict[str, Any]]) -> list[str]:
    eligible: list[str] = []
    for code in COUNTRIES:
        if _country_release_due_blocking(rows, code):
            continue
        if _country_has_verified_scored(rows, code):
            eligible.append(code)
    return eligible


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
) -> dict[str, Any]:
    if catalog_roles:
        for row in rows:
            spec = catalog_roles.get(str(row.get("series_id") or ""))
            if spec and not row.get("role"):
                row["role"] = spec.get("role")
            if spec and row.get("weight") is None:
                row["weight"] = spec.get("weight")

    scored_rows = [row for row in rows if _is_scored_row(row)]
    verified_scored = [row for row in scored_rows if _counts_as_verified_scored(row)]
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
        if _effective_status(row) in BLOCKING_SERIES_STATUSES
        and not bool(row.get("release_due"))
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

    blocked_sources = [str(row.get("series_id")) for row in blocking_scored if row.get("series_id")]
    blocked_expressions: list[str] = []
    for code in COUNTRIES:
        if _country_release_due_blocking(rows, code):
            expr = f"macro:{code}"
            if expr not in blocked_expressions:
                blocked_expressions.append(expr)

    countries = _country_rollups(rows)

    base: dict[str, Any] = {
        "outcome": "PASS",
        "coverage": "COMPLETE",
        "reason": None,
        "blocked_sources": blocked_sources,
        "blocked_expressions": blocked_expressions,
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

    if not scored_rows or len(verified_scored) == 0:
        base["outcome"] = "BLOCKED"
        base["coverage"] = "NONE"
        base["reason"] = "all_critical_missing"
        base["eligible"] = False
        for code in countries:
            countries[code]["eligible"] = False
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

    legs = _leg_statuses(packet)
    fx_status = legs.get("FX", "missing")
    macro_eligible = _macro_eligible_countries(rows)
    if fx_status in _BLOCKING_LEG_STATUSES:
        base["outcome"] = "BLOCKED"
        base["coverage"] = "NONE"
        base["reason"] = "no_markable_universe"
        base["blocked_legs"] = ["FX"]
        base["countries_unaffected"] = macro_eligible
        base["eligible"] = False
        return base

    partial_legs: list[str] = []
    trade_eligible_countries: list[str] = []
    for code in COUNTRIES:
        due_block = _country_release_due_blocking(rows, code)
        rate_status = legs.get(f"{code}_rates", "missing")
        rates_ok = rate_status not in _BLOCKING_LEG_STATUSES
        country_eligible = (
            not due_block
            and _country_has_verified_scored(rows, code)
            and rates_ok
        )
        countries[code]["eligible"] = country_eligible
        if country_eligible:
            trade_eligible_countries.append(code)
        elif rate_status in _BLOCKING_LEG_STATUSES:
            partial_legs.append(f"{code}_rates")

    if not trade_eligible_countries:
        base["outcome"] = "BLOCKED"
        base["coverage"] = "NONE"
        base["reason"] = "no_markable_universe"
        base["eligible"] = False
        return base

    base["partial_legs"] = partial_legs
    base["trade_eligible_countries"] = trade_eligible_countries
    has_partial = bool(
        optional_gaps
        or partial_legs
        or nondue_scored_gaps
        or blocking_scored
        or blocked_expressions
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


def _overlay_state_country(state: dict[str, Any]) -> str | None:
    country = state.get("country")
    if isinstance(country, str) and country:
        return country
    series_id = state.get("series_id")
    if isinstance(series_id, str) and "." in series_id:
        return series_id.split(".", 1)[0]
    return None


def _overlay_trade_critical(state: dict[str, Any]) -> bool:
    if "trade_critical" in state:
        return bool(state["trade_critical"])
    role = state.get("role")
    weight = state.get("weight")
    if role == "scored" and weight is not None:
        try:
            return float(weight) > 0
        except (TypeError, ValueError):
            return False
    return False


def _legacy_country_blocked(result: dict[str, Any], code: str) -> bool:
    countries = result.get("countries")
    if isinstance(countries, dict):
        bucket = countries.get(code)
        if isinstance(bucket, dict) and bucket.get("eligible") is False:
            return True
    for expr in result.get("blocked_expressions") or []:
        if expr == f"macro:{code}":
            return True
    return False


def _legacy_country_series_ids(result: dict[str, Any], code: str) -> set[str]:
    ids: set[str] = set()
    prefix = f"{code}."
    for sid in result.get("blocked_sources") or []:
        text = str(sid)
        if text.startswith(prefix):
            ids.add(text)
    for sid in result.get("partial_series") or []:
        text = str(sid)
        if text.startswith(prefix):
            ids.add(text)
    countries = result.get("countries")
    if isinstance(countries, dict):
        bucket = countries.get(code)
        if isinstance(bucket, dict):
            for sid in bucket.get("gaps") or []:
                ids.add(str(sid))
    return ids


def _policy_may_clear_legacy_block(
    states: list[dict[str, Any]], code: str, legacy: dict[str, Any]
) -> bool:
    country_states = [
        st for st in states if isinstance(st, dict) and _overlay_state_country(st) == code
    ]
    if not country_states:
        return False
    trade_critical_states = [st for st in country_states if _overlay_trade_critical(st)]
    if any(st.get("carry_forward_reason") == "overdue_unverified" for st in trade_critical_states):
        return False
    tc_series_in_states = {
        str(st.get("series_id"))
        for st in trade_critical_states
        if st.get("series_id")
    }
    legacy_series = _legacy_country_series_ids(legacy, code)
    if legacy_series and not legacy_series.issubset(tc_series_in_states):
        return False
    if not legacy_series and not tc_series_in_states:
        return False
    return True


def _apply_policy_overlay(
    result: dict[str, Any], policy: dict[str, Any], states: list[dict[str, Any]]
) -> dict[str, Any]:
    out = dict(result)
    legacy_outcome = out.get("outcome")
    out["policy_version"] = policy["policy_version"]

    states_by_country: dict[str, list[dict[str, Any]]] = {}
    for st in states:
        if not isinstance(st, dict):
            continue
        code = _overlay_state_country(st)
        if code:
            states_by_country.setdefault(code, []).append(st)

    policy_blocks = list(policy.get("blocked_expressions") or [])
    legacy_blocks = list(result.get("blocked_expressions") or [])
    merged_blocks: list[str] = []
    for expr in policy_blocks:
        if expr not in merged_blocks:
            merged_blocks.append(expr)
    for expr in legacy_blocks:
        if not isinstance(expr, str) or not expr.startswith("macro:"):
            continue
        code = expr.split(":", 1)[1]
        if code not in states_by_country and expr not in merged_blocks:
            merged_blocks.append(expr)

    countries = out.get("countries")
    if not isinstance(countries, dict):
        countries = {}
        out["countries"] = countries

    policy_blocked_codes = {
        expr.split(":", 1)[1]
        for expr in policy_blocks
        if isinstance(expr, str) and expr.startswith("macro:") and ":" in expr
    }

    trade_eligible: list[str] = []
    for code in COUNTRIES:
        bucket = countries.get(code)
        if not isinstance(bucket, dict):
            bucket = {}
            countries[code] = bucket
        policy_info = (policy.get("countries") or {}).get(code) or {}
        policy_eligible = bool(policy_info.get("eligible"))
        legacy_blocked = _legacy_country_blocked(result, code)

        if code not in states_by_country:
            if legacy_blocked:
                eligible = False
            else:
                eligible = bool(bucket.get("eligible"))
        elif code in policy_blocked_codes:
            eligible = False
        elif legacy_blocked and not _policy_may_clear_legacy_block(states, code, result):
            eligible = False
        else:
            eligible = policy_eligible

        bucket["eligible"] = eligible
        if eligible:
            trade_eligible.append(code)

    for code in COUNTRIES:
        if code not in states_by_country and _legacy_country_blocked(result, code):
            expr = f"macro:{code}"
            if expr not in merged_blocks:
                merged_blocks.append(expr)
        elif not countries.get(code, {}).get("eligible"):
            expr = f"macro:{code}"
            if expr not in merged_blocks:
                merged_blocks.append(expr)

    out["blocked_expressions"] = merged_blocks
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
        macro["status"] = "invalid"
        macro["fresh_countries"] = []
        macro["stale_countries"] = list(COUNTRIES)
        notes.append("macro ingestion rows empty")
    else:
        fresh_countries: list[str] = []
        stale_countries: list[str] = []
        for code in COUNTRIES:
            verified = _country_has_verified_scored(rows, code)
            due_block = _country_release_due_blocking(rows, code)
            if verified and not due_block:
                fresh_countries.append(code)
            else:
                stale_countries.append(code)

        macro["fresh_countries"] = fresh_countries
        macro["stale_countries"] = stale_countries
        macro["status"] = "fresh" if fresh_countries else ("stale" if stale_countries else "invalid")
        if stale_countries:
            notes.append("country-specific macro restrictions: " + ", ".join(stale_countries))
        carried = sorted({str(row.get("country")) for row in rows if carried_forward(row) and row.get("country")})
        if carried:
            macro["source_health_countries"] = carried
            stale_set = set(stale_countries)
            carried_not_stale = [code for code in carried if code not in stale_set]
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
    result = evaluate_gate(rows=rows, families=families)
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
