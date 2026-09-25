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

_TRANSIENT_RE = re.compile(
    r"timed out|timeout|time-out|http\s*\d{3}|connection|source outage|"
    r"temporarily unavailable|network|unreachable",
    re.IGNORECASE,
)


def is_budget_deferred(row: dict[str, Any]) -> bool:
    return str(row.get("error") or "") == "budget_deferred"


def is_transient_fetch_failure(row: dict[str, Any]) -> bool:
    """Timeouts, HTTP failures, and source outages. Not structural catalog gaps."""
    if str(row.get("status") or "") != "source_failed":
        return False
    if is_budget_deferred(row):
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
    if bool(row.get("release_due")):
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
    if bool(out.get("release_due")) or not is_transient_fetch_failure(out):
        return out
    prior = prior_verified_observation(
        out,
        history,
        transformation=transformation,
        source_series_id=source_series_id,
    )
    if prior is None:
        return out
    classification = "budget_deferred" if is_budget_deferred(out) else "transient_fetch"
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
    return out


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
                "carried_forward": bool(health.get("carried_forward")) and not bool(row.get("release_due")),
                "blocks_new_risk": bool(row.get("release_due")) or not bool(health.get("carried_forward")),
                "observation_period": health.get("observation_period") or row.get("observation_period"),
                "retrieved_at": health.get("retrieved_at"),
                "fetch_error": health.get("fetch_error") or row.get("error"),
            }
        )
    return entries
