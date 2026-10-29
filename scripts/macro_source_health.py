"""Separate source-health failures from missing or invalid economic observations.

A scored series that already has a verified vintage, and whose next release is
not due at the freeze cutoff, keeps that vintage when the fresh fetch fails
for a transient reason or is budget-deferred. Due releases and absent history
stay fail-closed.
"""

from __future__ import annotations

import math
import re
from typing import Any

from scripts.market_watch_launch.contract import BLOCKING_SERIES_STATUSES, VERIFIED_OBSERVATION_STATUSES

_TRANSIENT_RE = re.compile(
    r"timed out|timeout|time-out|http\s*\d{3}|connection|source outage|"
    r"temporarily unavailable|network|unreachable",
    re.IGNORECASE,
)


def is_host_deferred(row: dict[str, Any]) -> bool:
    return str(row.get("error") or "") == "host_deferred"


RESEARCH_STATUS_CURRENT = "current release"
RESEARCH_STATUS_PREVIOUS = "previous release retained"
RESEARCH_STATUS_UNAVAILABLE = "unavailable"


def effective_release_due(row: dict[str, Any]) -> bool:
    """Calendar backstop marks an older held print as no longer the current release."""
    if row.get("cadence_backstop_due"):
        return True
    return bool(row.get("release_due"))


def research_status_for_row(row: dict[str, Any]) -> str:
    status = str(row.get("status") or "")
    if status in BLOCKING_SERIES_STATUSES and not carried_forward(row):
        return RESEARCH_STATUS_UNAVAILABLE
    if carried_forward(row) or (
        status in VERIFIED_OBSERVATION_STATUSES and row.get("cadence_backstop_due")
    ):
        return RESEARCH_STATUS_PREVIOUS
    if status in VERIFIED_OBSERVATION_STATUSES:
        return RESEARCH_STATUS_CURRENT
    if status in {"license_gap", "not_applicable", "calendar_unparsed"}:
        if row.get("observation_period") and status == "calendar_unparsed":
            return RESEARCH_STATUS_PREVIOUS
        return RESEARCH_STATUS_UNAVAILABLE
    return RESEARCH_STATUS_UNAVAILABLE


def _attach_research_status(row: dict[str, Any]) -> dict[str, Any]:
    status_label = research_status_for_row(row)
    row["research_status"] = status_label
    health = row.get("source_health")
    if isinstance(health, dict):
        merged = dict(health)
        merged["research_status"] = status_label
        row["source_health"] = merged
    return row


def is_budget_deferred(row: dict[str, Any]) -> bool:
    return str(row.get("error") or "") == "budget_deferred"


def is_transient_fetch_failure(row: dict[str, Any]) -> bool:
    """Timeouts, HTTP failures, and source outages. Not structural catalog gaps."""
    if str(row.get("status") or "") == "calendar_unparsed" and row.get("observation_period"):
        return False
    if str(row.get("status") or "") != "source_failed":
        return False
    if is_budget_deferred(row) or is_host_deferred(row):
        return True
    return bool(_TRANSIENT_RE.search(str(row.get("error") or "")))


def _finite(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def _history_component(history: dict[str, Any], series_id: str) -> dict[str, Any]:
    parts = str(series_id).split(".", 1)
    if len(parts) != 2:
        return {}
    return (history.get("components") or {}).get(parts[1]) or {}


def prior_verified_observation(
    row: dict[str, Any],
    history: dict[str, Any] | None,
    *,
    transformation: str = "",
    source_series_id: str | None = None,
) -> dict[str, Any] | None:
    """Latest finite canonical-history point for this scored series, if any."""
    embedded = row.get("prior_verified")
    if isinstance(embedded, dict) and embedded.get("observation_period") and _finite(embedded.get("value")) is not None:
        return dict(embedded)
    if not isinstance(history, dict):
        return None
    comp = _history_component(history, str(row.get("series_id") or ""))
    preferred = transformation or str(comp.get("preferred_scoring_transformation") or "")
    candidates: list[dict[str, Any]] = []
    for obs in comp.get("observations") or []:
        if not isinstance(obs, dict):
            continue
        if source_series_id and obs.get("series_id") and str(obs.get("series_id")) != source_series_id:
            continue
        period = obs.get("reference_period") or obs.get("period")
        value = _finite(obs.get("value"))
        if period is None or value is None:
            continue
        obs_transform = str(obs.get("transformation") or "")
        if preferred and obs_transform and obs_transform != preferred:
            continue
        if not obs.get("retrieved_at") and not obs.get("vintage"):
            continue
        candidates.append(obs)
    if not candidates and preferred:
        for obs in comp.get("observations") or []:
            if not isinstance(obs, dict):
                continue
            period = obs.get("reference_period") or obs.get("period")
            value = _finite(obs.get("value"))
            if period is None or value is None:
                continue
            if not obs.get("retrieved_at") and not obs.get("vintage"):
                continue
            candidates.append(obs)
    if not candidates:
        return None
    obs = max(candidates, key=lambda item: str(item.get("reference_period") or item.get("period") or ""))
    return {
        "observation_period": str(obs.get("reference_period") or obs.get("period")),
        "value": _finite(obs.get("value")),
        "retrieved_at": obs.get("retrieved_at"),
        "vintage": obs.get("vintage"),
        "transformation": obs.get("transformation"),
        "series_id": obs.get("series_id"),
    }


def carried_forward(row: dict[str, Any]) -> bool:
    health = row.get("source_health")
    if not isinstance(health, dict) or not health.get("carried_forward"):
        return False
    if effective_release_due(row):
        return False
    prior = row.get("prior_verified")
    return isinstance(prior, dict) and bool(prior.get("observation_period"))


def annotate_row(
    row: dict[str, Any],
    *,
    history: dict[str, Any] | None = None,
    transformation: str = "",
    source_series_id: str | None = None,
) -> dict[str, Any]:
    """Attach carry-forward metadata. Does not invent a vintage the history lacks."""
    out = dict(row)
    if effective_release_due(out) or not is_transient_fetch_failure(out):
        return _attach_research_status(out)
    prior = prior_verified_observation(
        out,
        history,
        transformation=transformation,
        source_series_id=source_series_id,
    )
    if prior is None:
        return _attach_research_status(out)
    classification = "budget_deferred" if is_budget_deferred(out) else "transient_fetch"
    if is_host_deferred(out):
        classification = "host_deferred"
    out["prior_verified"] = prior
    if not out.get("observation_period"):
        out["observation_period"] = prior["observation_period"]
    out["source_health"] = {
        "state": "carried_forward",
        "classification": classification,
        "carried_forward": True,
        "blocks_new_risk": False,
        "fetch_status": out.get("status"),
        "fetch_error": out.get("error"),
        "observation_period": prior["observation_period"],
        "value": prior["value"],
        "retrieved_at": prior.get("retrieved_at"),
        "vintage": prior.get("vintage"),
    }
    return _attach_research_status(out)


def annotate_rows(
    rows: list[dict[str, Any]],
    *,
    histories: dict[str, dict[str, Any]] | None = None,
    catalog_by_id: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    histories = histories or {}
    catalog_by_id = catalog_by_id or {}
    annotated: list[dict[str, Any]] = []
    for row in rows:
        spec = catalog_by_id.get(str(row.get("series_id") or "")) or {}
        country = str(row.get("country") or spec.get("country") or "")
        annotated.append(
            annotate_row(
                row,
                history=histories.get(country),
                transformation=str(spec.get("transform") or ""),
                source_series_id=str(spec.get("series_id") or "") or None,
            )
        )
    return annotated


def source_health_entries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for row in rows:
        health = row.get("source_health")
        if not isinstance(health, dict):
            continue
        entries.append(
            {
                "series_id": row.get("series_id"),
                "country": row.get("country"),
                "classification": health.get("classification"),
                "carried_forward": bool(health.get("carried_forward"))
                and not effective_release_due(row),
                "blocks_new_risk": effective_release_due(row)
                or not bool(health.get("carried_forward")),
                "observation_period": health.get("observation_period") or row.get("observation_period"),
                "retrieved_at": health.get("retrieved_at"),
                "fetch_error": health.get("fetch_error") or row.get("error"),
                "research_status": row.get("research_status") or health.get("research_status"),
            }
        )
    return entries
