"""Release-aware admission and retry scheduling with protected trade-critical budget."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from scripts.run_state.schema import (
    SCHEMA_SCHEDULER_EVENT,
    sha256_json,
    validate_scheduler_event,
)

TIERS = ("due_trade_critical", "due_context", "unknown_calendar", "non_due_check")


def tier_for(definition: Mapping[str, Any], expectation: Mapping[str, Any]) -> str:
    if expectation.get("calendar_status") == "unknown":
        return "unknown_calendar"
    occurred = expectation.get("scheduled_release_occurred_by_cutoff")
    if occurred is None:
        return "unknown_calendar"
    if expectation.get("calendar_status") == "known":
        if occurred is True:
            if definition.get("trade_critical"):
                return "due_trade_critical"
            return "due_context"
        return "non_due_check"
    return "unknown_calendar"


def classify_failure(*, error: str = "", http_status: int | None = None) -> str:
    if http_status == 404:
        return "http_404"
    err = error or ""
    if "404" in err or err == "HTTP 404":
        return "http_404"
    if http_status == 429:
        return "http_429"
    if http_status is not None and 500 <= http_status <= 599:
        return "http_5xx"
    lower = err.lower()
    if "schema" in lower or "drift" in lower:
        return "schema_drift"
    if "timeout" in lower or "timed out" in lower:
        return "timeout"
    if "license" in lower:
        return "license_gap"
    if "empty" in lower:
        return "empty_parse"
    return "transport_error"


def _resolve_tier(item: Mapping[str, Any]) -> str:
    definition = item.get("definition")
    expectation = item.get("expectation")
    if definition is not None and expectation is not None:
        return tier_for(definition, expectation)
    tier = item.get("tier")
    if not isinstance(tier, str) or tier not in TIERS:
        raise ValueError(f"item missing tier or definition+expectation: {item.get('series_id')}")
    return tier


def _sort_key(item: Mapping[str, Any]) -> tuple:
    return (item["country"], item["series_id"])


def _admission_grant(item: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "series_id": item["series_id"],
        "country": item["country"],
        "tier": item["tier"],
        "run_id": item["run_id"],
    }


def _retry_grant(item: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "series_id": item["series_id"],
        "country": item["country"],
        "tier": item["tier"],
        "run_id": item["run_id"],
        "supersedes_attempt_id": item["attempt_id"],
    }


def _scheduler_event(
    *,
    run_id: str,
    series_id: str,
    kind: str,
    reason: str,
    priority_tier: str,
    recorded_at: str,
    related_attempt_id: Optional[str] = None,
) -> Dict[str, Any]:
    identity = {
        "run_id": run_id,
        "series_id": series_id,
        "kind": kind,
        "reason": reason,
    }
    doc: Dict[str, Any] = {
        "schema_version": SCHEMA_SCHEDULER_EVENT,
        "event_id": "sk_" + sha256_json(identity)[:20],
        "run_id": run_id,
        "series_id": series_id,
        "kind": kind,
        "reason": reason,
        "priority_tier": priority_tier,
        "recorded_at": recorded_at,
    }
    if related_attempt_id is not None:
        doc["related_attempt_id"] = related_attempt_id
    return validate_scheduler_event(doc)


def _bucket_items(items: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    buckets: Dict[str, List[Dict[str, Any]]] = {t: [] for t in TIERS}
    for raw in items:
        tier = _resolve_tier(raw)
        entry = {
            "series_id": raw["series_id"],
            "country": raw["country"],
            "run_id": raw["run_id"],
            "tier": tier,
        }
        if "attempt_id" in raw:
            entry["attempt_id"] = raw["attempt_id"]
        buckets[tier].append(entry)
    for tier in TIERS:
        buckets[tier].sort(key=_sort_key)
    return buckets


def plan_admission(
    items: list[dict],
    *,
    budget_slots: int,
    recorded_at: str,
) -> dict:
    buckets = _bucket_items(list(items))
    admitted: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    slots = budget_slots

    critical = buckets["due_trade_critical"]
    for item in critical:
        if slots > 0:
            admitted.append(_admission_grant(item))
            slots -= 1
        else:
            skipped.append(
                _scheduler_event(
                    run_id=item["run_id"],
                    series_id=item["series_id"],
                    kind="skipped_admission",
                    reason="protected_budget_exhausted",
                    priority_tier=item["tier"],
                    recorded_at=recorded_at,
                )
            )

    all_critical_admitted = len(admitted) == len(critical)

    if not all_critical_admitted:
        for tier in TIERS[1:]:
            for item in buckets[tier]:
                skipped.append(
                    _scheduler_event(
                        run_id=item["run_id"],
                        series_id=item["series_id"],
                        kind="skipped_admission",
                        reason="starved_by_critical_reservation",
                        priority_tier=item["tier"],
                        recorded_at=recorded_at,
                    )
                )
    else:
        for tier in TIERS[1:]:
            for item in buckets[tier]:
                if slots > 0:
                    admitted.append(_admission_grant(item))
                    slots -= 1
                else:
                    skipped.append(
                        _scheduler_event(
                            run_id=item["run_id"],
                            series_id=item["series_id"],
                            kind="skipped_admission",
                            reason="budget_exhausted",
                            priority_tier=item["tier"],
                            recorded_at=recorded_at,
                        )
                    )

    return {"admitted": admitted, "skipped": skipped}


def plan_retries(
    failed: list[dict],
    *,
    budget_slots: int,
    recorded_at: str,
) -> dict:
    buckets = _bucket_items(list(failed))
    admitted: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    slots = budget_slots

    critical = buckets["due_trade_critical"]
    for item in critical:
        if slots > 0:
            admitted.append(_retry_grant(item))
            slots -= 1
        else:
            skipped.append(
                _scheduler_event(
                    run_id=item["run_id"],
                    series_id=item["series_id"],
                    kind="skipped_retry",
                    reason="protected_budget_exhausted",
                    priority_tier=item["tier"],
                    recorded_at=recorded_at,
                    related_attempt_id=item["attempt_id"],
                )
            )

    all_critical_admitted = sum(1 for g in admitted if g["tier"] == "due_trade_critical") == len(
        critical
    )

    if not all_critical_admitted:
        for tier in TIERS[1:]:
            for item in buckets[tier]:
                skipped.append(
                    _scheduler_event(
                        run_id=item["run_id"],
                        series_id=item["series_id"],
                        kind="skipped_retry",
                        reason="starved_by_critical_reservation",
                        priority_tier=item["tier"],
                        recorded_at=recorded_at,
                        related_attempt_id=item["attempt_id"],
                    )
                )
    else:
        for tier in TIERS[1:]:
            for item in buckets[tier]:
                if slots > 0:
                    admitted.append(_retry_grant(item))
                    slots -= 1
                else:
                    skipped.append(
                        _scheduler_event(
                            run_id=item["run_id"],
                            series_id=item["series_id"],
                            kind="skipped_retry",
                            reason="budget_exhausted",
                            priority_tier=item["tier"],
                            recorded_at=recorded_at,
                            related_attempt_id=item["attempt_id"],
                        )
                    )

    return {"admitted": admitted, "skipped": skipped}
