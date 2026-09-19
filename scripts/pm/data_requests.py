"""Consolidated future-data-request registry. Never acquires evidence now."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any

from scripts.overnight.clock import isoformat, now_ny
from scripts.pm.constants import PM_IDS, PRIORITIES, SCHEMA_VERSION
from scripts.pm.errors import SchemaError


_WS = re.compile(r"\s+")


def empty_registry(*, when: datetime | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "PM_FUTURE_DATA_REQUESTS",
        "as_of": isoformat(now_ny(when)),
        "requests": [],
    }


def normalize_request_key(request: str) -> str:
    return _WS.sub(" ", str(request or "").strip().lower())


def _request_id(key: str) -> str:
    return "fdr-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def validate_entry(entry: dict[str, Any], *, pm_id: str) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise SchemaError(f"{pm_id} future_data_requests entry must be an object")
    request = str(entry.get("request") or "").strip()
    reason = str(entry.get("reason") or "").strip()
    impact = str(entry.get("decision_impact") or "").strip()
    priority = entry.get("priority")
    if not request:
        raise SchemaError(f"{pm_id} future_data_requests.request is required")
    if not reason:
        raise SchemaError(f"{pm_id} future_data_requests.reason is required")
    if not impact:
        raise SchemaError(f"{pm_id} future_data_requests.decision_impact is required")
    if priority not in PRIORITIES:
        raise SchemaError(f"{pm_id} future_data_requests.priority must be low|medium|high")
    source = entry.get("suggested_source")
    if source is not None and (not isinstance(source, str) or not source.strip()):
        raise SchemaError(f"{pm_id} future_data_requests.suggested_source must be a string or null")
    return {
        "request": request,
        "reason": reason,
        "decision_impact": impact,
        "priority": priority,
        "suggested_source": source.strip() if isinstance(source, str) else None,
    }


def apply_requests(
    registry: dict[str, Any],
    entries: list[dict[str, Any]] | None,
    *,
    pm_id: str,
    when: datetime | None = None,
) -> dict[str, Any]:
    if pm_id not in PM_IDS:
        raise SchemaError(f"unknown originating PM {pm_id}")
    out = {
        "schema_version": SCHEMA_VERSION,
        "type": "PM_FUTURE_DATA_REQUESTS",
        "as_of": isoformat(now_ny(when)),
        "requests": list(registry.get("requests") or []),
    }
    if not entries:
        return out
    stamp = isoformat(now_ny(when))
    by_key = {normalize_request_key(row["request"]): row for row in out["requests"]}
    for raw in entries:
        item = validate_entry(raw, pm_id=pm_id)
        key = normalize_request_key(item["request"])
        existing = by_key.get(key)
        if existing is None:
            row = {
                "request_id": _request_id(key),
                "request": item["request"],
                "reason": item["reason"],
                "decision_impact": item["decision_impact"],
                "priority": item["priority"],
                "suggested_source": item["suggested_source"],
                "originating_pms": [pm_id],
                "first_requested": stamp,
                "last_requested": stamp,
                "repeat_count": 1,
                "status": "requested",
                "attributions": [
                    {
                        "pm_id": pm_id,
                        "reason": item["reason"],
                        "decision_impact": item["decision_impact"],
                        "priority": item["priority"],
                        "at": stamp,
                    }
                ],
            }
            out["requests"].append(row)
            by_key[key] = row
            continue
        existing["last_requested"] = stamp
        existing["repeat_count"] = int(existing.get("repeat_count") or 1) + 1
        existing["status"] = "requested"
        pms = list(existing.get("originating_pms") or [])
        if pm_id not in pms:
            pms.append(pm_id)
        existing["originating_pms"] = pms
        if PRIORITIES.index(item["priority"]) > PRIORITIES.index(existing.get("priority") or "low"):
            existing["priority"] = item["priority"]
        if item["suggested_source"] and not existing.get("suggested_source"):
            existing["suggested_source"] = item["suggested_source"]
        existing.setdefault("attributions", []).append(
            {
                "pm_id": pm_id,
                "reason": item["reason"],
                "decision_impact": item["decision_impact"],
                "priority": item["priority"],
                "at": stamp,
            }
        )
    return out


def unresolved_for_pm(registry: dict[str, Any], pm_id: str) -> list[dict[str, Any]]:
    rows = []
    for row in registry.get("requests") or []:
        if row.get("status") != "requested":
            continue
        if pm_id in (row.get("originating_pms") or []):
            rows.append(row)
    return rows


def public_requests_view(registry: dict[str, Any]) -> dict[str, Any]:
    requests = []
    for row in registry.get("requests") or []:
        requests.append(
            {
                "request_id": row.get("request_id"),
                "request": row.get("request"),
                "reason": row.get("reason"),
                "decision_impact": row.get("decision_impact"),
                "priority": row.get("priority"),
                "suggested_source": row.get("suggested_source"),
                "originating_pms": row.get("originating_pms") or [],
                "first_requested": row.get("first_requested"),
                "last_requested": row.get("last_requested"),
                "repeat_count": row.get("repeat_count") or 1,
                "status": row.get("status") or "requested",
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "PM_PUBLIC_DATA_REQUESTS",
        "as_of": registry.get("as_of"),
        "request_count": len(requests),
        "requests": requests,
        "note": "Future runs only. These requests never break the current evidence freeze and do not launch collectors.",
    }
