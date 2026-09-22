"""Exact freshness and publication failure matrix."""

from __future__ import annotations

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


def assert_action_allowed(action: str, families: dict[str, Any], *, seat: str) -> list[str]:
    blocked = blocked_expanding_families(families)
    if action in EXPANDING_ACTIONS and blocked:
        raise FreshnessError(
            f"{seat} {action} blocked by stale/missing required evidence: {blocked}"
        )
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
