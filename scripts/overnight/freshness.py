"""Exact freshness and publication failure matrix."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from scripts.overnight.clock import now_ny, parse_iso
from scripts.overnight.constants import (
    CATASTROPHIC_FAMILIES,
    EVIDENCE_FAMILIES,
    EXPANDING_ACTIONS,
    FAMILY_STATUSES,
    PUBLICATION_CORE,
    REQUIRED_OPEN_FAMILIES,
    REVIEW_STATUSES,
    STALE_AFTER_HOURS,
)
from scripts.overnight.errors import FreshnessError, PublicationError, SchemaError


def normalize_family_status(status: str) -> str:
    if status not in FAMILY_STATUSES:
        raise SchemaError(f"invalid family status {status}")
    return status


def family_is_blocking(status: str) -> bool:
    return normalize_family_status(status) in {"stale", "missing", "invalid", "unavailable"}


def family_is_catastrophic(family: str, status: str) -> bool:
    normalize_family_status(status)
    return family in CATASTROPHIC_FAMILIES and status == "invalid"


def age_status(as_of: str | None, *, when: datetime | None = None, stale_after_hours: int = STALE_AFTER_HOURS) -> str:
    if not as_of:
        return "missing"
    try:
        stamp = parse_iso(as_of)
    except ValueError:
        return "invalid"
    age = now_ny(when) - stamp
    if age.total_seconds() < 0:
        return "fresh"
    if age.total_seconds() > stale_after_hours * 3600:
        return "stale"
    return "fresh"


def assess_families(families: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(families, dict):
        raise SchemaError("families must be an object")
    out: dict[str, Any] = {}
    for name in EVIDENCE_FAMILIES:
        item = families.get(name) or {}
        status = item.get("status") or "missing"
        normalize_family_status(status)
        out[name] = {
            "status": status,
            "as_of": item.get("as_of"),
            "digest": item.get("digest"),
            "blocking": family_is_blocking(status),
            "catastrophic": family_is_catastrophic(name, status),
            "notes": list(item.get("notes") or []),
        }
    return out


def blocked_expanding_families(families: dict[str, Any], *, required: tuple[str, ...] = REQUIRED_OPEN_FAMILIES) -> list[str]:
    assessed = assess_families(families)
    return [name for name in required if assessed[name]["blocking"]]


def _market_packet(families: dict[str, Any]) -> dict[str, Any] | None:
    block = families.get("market_state") or {}
    data = block.get("data") if isinstance(block, dict) else None
    return data if isinstance(data, dict) else None


_G10 = ("EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "NOK", "SEK", "JPY")
_BLOCKING_SOURCE_STATUSES = {"stale", "missing", "invalid", "unavailable"}


def _bounded_token(name: str, *, allow_trailing_alnum: bool = False) -> str:
    """Match a source token even when the next character is '_' or '-'.

    ``\\b`` treats underscore as a word character, so ``SOFR_2027-03`` and
    ``TONA_2027-03`` would otherwise look unrelated. CME month codes such as
    ``SR3Z6`` keep a trailing alphanumeric on purpose.
    """
    tail = "" if allow_trailing_alnum else r"(?![A-Z0-9])"
    return rf"(?<![A-Z0-9]){name}{tail}"


def _walk_text(value: Any, parts: list[str]) -> None:
    if isinstance(value, str):
        parts.append(value)
    elif isinstance(value, dict):
        for key, item in value.items():
            parts.append(str(key))
            _walk_text(item, parts)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _walk_text(item, parts)


def expression_dependencies(
    instrument: Any = None,
    *,
    asset_class: str | None = None,
    expression: Any = None,
) -> set[str]:
    """Source legs the selected expression actually needs.

    Unevaluated alternate candidates are not included. Callers pass the
    instrument being opened and, when present, its expression object.
    """
    parts: list[str] = []
    _walk_text(instrument, parts)
    _walk_text(asset_class, parts)
    _walk_text(expression, parts)
    upper = " ".join(parts).upper()
    deps: set[str] = set()
    for token in re.findall(r"(?<![A-Z])([A-Z]{6})(?![A-Z])", upper):
        base, quote = token[:3], token[3:]
        if base not in _G10 or quote not in _G10:
            continue
        if "NZD" in (base, quote):
            deps.add("NZ_rates")
        if "JPY" in (base, quote):
            deps.add("JP_rates")
    for left, right in re.findall(r"(?<![A-Z0-9])([A-Z]{2})-([A-Z]{2})_[0-9A-Z]+", upper):
        if "NZ" in (left, right):
            deps.add("NZ_rates")
        if "JP" in (left, right):
            deps.add("JP_rates")
    if re.search(_bounded_token("NZD") + r"|" + _bounded_token("NZ") + r"(?![A-Z])", upper):
        deps.add("NZ_rates")
    if re.search(
        _bounded_token("JPY")
        + "|"
        + _bounded_token("JP")
        + r"(?![A-Z])|"
        + _bounded_token("TONA")
        + "|"
        + _bounded_token("TOA3M"),
        upper,
    ):
        deps.add("JP_rates")
    if re.search(_bounded_token("SOFR") + "|" + _bounded_token("SR3", allow_trailing_alnum=True), upper):
        deps.add("SOFR_curve")
    if re.search(_bounded_token("CORRA"), upper):
        deps.add("CORRA_curve")
    if re.search(_bounded_token("AONIA"), upper):
        deps.add("AONIA_curve")
    return deps


def _named_status(block: Any, *source_lists: Any, source_key: str) -> str:
    """Explicit stale/unavailable wins. A packet that never carried the leg does not."""
    if isinstance(block, dict) and block.get("status"):
        return str(block.get("status"))
    for items in source_lists:
        if isinstance(items, list) and source_key in items:
            return "unavailable"
    return "ok"


def _dependency_status(packet: dict[str, Any], dependency: str) -> str:
    rates = packet.get("rates") if isinstance(packet.get("rates"), dict) else {}
    curves = ((packet.get("tradable_rate_curves") or {}).get("curves") or {})
    stale = packet.get("stale_sources")
    unavailable = packet.get("unavailable_sources")
    if dependency == "NZ_rates":
        return _named_status(rates.get("NZ"), stale, unavailable, source_key="NZ_rates")
    if dependency == "JP_rates":
        return _named_status(rates.get("JP"), stale, unavailable, source_key="JP_rates")
    curve_ids = {"SOFR_curve": "SOFR", "CORRA_curve": "CORRA", "AONIA_curve": "AONIA"}
    curve_id = curve_ids.get(dependency)
    if curve_id:
        return _named_status(
            curves.get(curve_id),
            unavailable,
            source_key=f"{curve_id}_tradable_curve",
        )
    return "ok"


def required_preflight_block(families: dict[str, Any]) -> str | None:
    """Fail closed when a required US/CA/AU market-state leg is unusable.

    Non-preflight countries and an SR3-only gap do not trip this check.
    """
    packet = _market_packet(families)
    if packet is None:
        return None
    from scripts.country_registry import required_preflight_countries

    rates = packet.get("rates") if isinstance(packet.get("rates"), dict) else {}
    for code in required_preflight_countries():
        status = str((rates.get(code) or {}).get("status") or "")
        if status in _BLOCKING_SOURCE_STATUSES:
            return f"required preflight {code}_rates is {status}"
    fx = packet.get("fx") if isinstance(packet.get("fx"), dict) else {}
    fx_status = str(fx.get("status") or "")
    if fx_status in _BLOCKING_SOURCE_STATUSES:
        return f"required preflight FX is {fx_status}"
    countries = ((packet.get("policy_paths") or {}).get("countries") or {})
    if isinstance(countries, dict):
        for code in required_preflight_countries():
            block = countries.get(code)
            if not isinstance(block, dict):
                continue
            if block.get("status") == "unavailable":
                return f"required preflight {code} policy path is unavailable"
            if code == "US" and block.get("status") in {"ok", "partial"}:
                benchmark = block.get("benchmark") if isinstance(block.get("benchmark"), dict) else {}
                if benchmark.get("rate") is None:
                    return "required preflight US SOFR benchmark is missing"
    return None


def expression_evidence_block(
    families: dict[str, Any],
    *,
    instrument: Any = None,
    asset_class: str | None = None,
    expression: Any = None,
) -> str | None:
    packet = _market_packet(families)
    if packet is None:
        return None
    blocked: list[str] = []
    for dependency in sorted(
        expression_dependencies(instrument, asset_class=asset_class, expression=expression)
    ):
        status = _dependency_status(packet, dependency)
        if status in _BLOCKING_SOURCE_STATUSES:
            blocked.append(f"{dependency}={status}")
    if not blocked:
        return None
    return "expression blocked by stale/missing required leg: " + ", ".join(blocked)


def assert_action_allowed(
    action: str,
    families: dict[str, Any],
    *,
    seat: str,
    instrument: Any = None,
    asset_class: str | None = None,
    expression: Any = None,
) -> list[str]:
    blocked = blocked_expanding_families(families)
    if action in EXPANDING_ACTIONS and blocked:
        raise FreshnessError(
            f"{seat} {action} blocked by stale/missing required evidence: {blocked}"
        )
    if action in EXPANDING_ACTIONS:
        preflight = required_preflight_block(families)
        if preflight:
            raise FreshnessError(f"{seat} {action} blocked: {preflight}")
        specific = expression_evidence_block(
            families,
            instrument=instrument,
            asset_class=asset_class,
            expression=expression,
        )
        if specific:
            raise FreshnessError(f"{seat} {action} blocked: {specific}")
    return blocked


def review_status(value: str | None) -> str:
    status = value or "missing"
    if status not in REVIEW_STATUSES:
        raise SchemaError(f"invalid trader review status {status}")
    return status


def publication_decision(
    *,
    families: dict[str, Any],
    trader_review_status: str | None,
    last_successful_review_run_id: str | None = None,
    pm_books_status: str | None = None,
    last_successful_pm_run_id: str | None = None,
) -> dict[str, Any]:
    assessed = assess_families(families)
    catastrophic = [name for name, item in assessed.items() if item["catastrophic"]]
    # A morning release must never present stale news as current. The accepted
    # current-cycle ACP research supplement can upgrade this family during
    # assembly; without it, publication fails closed.
    if assessed["news"]["status"] != "fresh" and "news" not in catastrophic:
        catastrophic.append("news")
    review = review_status(trader_review_status)
    pm_review = pm_books_status
    if pm_review is None and review in {"stale", "failed", "missing"}:
        pm_review = review if review != "missing" else "stale"
    if catastrophic:
        core = "catastrophic_fail"
        may_publish = False
        reason = f"catastrophic core input invalid: {catastrophic}"
    else:
        core = "ok"
        may_publish = True
        reason = "core inputs are structurally valid"
        if review in {"stale", "failed", "missing"}:
            reason += f"; trader books {review}"
            if last_successful_review_run_id:
                reason += f"; last successful review {last_successful_review_run_id}"
        if pm_review in {"stale", "failed", "missing"}:
            reason += f"; PM books {pm_review}"
            if last_successful_pm_run_id:
                reason += f"; last successful automated PM cycle {last_successful_pm_run_id}"
    if core not in PUBLICATION_CORE:
        raise SchemaError("invalid publication core status")
    out: dict[str, Any] = {
        "core_status": core,
        "trader_books_status": review if review != "missing" else "stale",
        "last_successful_review_run_id": last_successful_review_run_id,
        "may_publish": may_publish,
        "catastrophic_families": catastrophic,
        "families": assessed,
        "reason": reason,
    }
    if pm_review is not None:
        out["pm_books_status"] = pm_review
    if last_successful_pm_run_id:
        out["last_successful_pm_run_id"] = last_successful_pm_run_id
    return out


def assert_may_publish(decision: dict[str, Any]) -> dict[str, Any]:
    if not decision.get("may_publish"):
        raise PublicationError(decision.get("reason") or "publication blocked")
    return decision
