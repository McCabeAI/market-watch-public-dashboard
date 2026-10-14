"""Live BLS acquisition for verified PCE component series."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from scripts.core_pce_release.bls import fetch_series
from scripts.core_pce_release.normalize import build_observations
from scripts.core_pce_release.snapshot import REPO_ROOT

REGISTRY_PATH = REPO_ROOT / "data" / "core_pce_release" / "series_registry.json"

IMPLICIT_PCE_LINES = frozenset({163, 255, 268})
PRIORITY_PPI_CAP = 25
MAX_PPI_POLL_SERIES = 105


def load_registry(path: Path | None = None) -> dict:
    return json.loads((path or REGISTRY_PATH).read_text(encoding="utf-8"))


def live_fetch_status(registry: dict | None = None) -> dict:
    document = registry if registry is not None else load_registry()
    verified = document.get("verified") or []
    component_rows = [row for row in verified if row.get("role") == "pce_component"]
    usable = [row for row in component_rows if row.get("usable_as_pce_rate")]
    if not component_rows:
        status = "NOT READY"
    elif usable and document.get("live_component_fetch") == "READY":
        status = "READY"
    else:
        status = "PARTIAL" if component_rows else "NOT READY"
    return {
        "status": status,
        "blocker": None if status == "READY" else document.get("blocker"),
        "verified_context_series": [row["series_id"] for row in verified if row.get("role") == "cpi_context_only"],
        "pce_component_series_ids": len(component_rows),
        "usable_as_pce_rate_series": len(usable),
        "reference_only_series": len(component_rows) - len(usable),
        "ambiguous_groups": len(document.get("ambiguous") or []),
        "coverage": document.get("coverage"),
    }


def cached_cpi_series(registry: dict) -> list[str]:
    series_ids: list[str] = []
    for row in registry.get("verified") or []:
        if row.get("role") == "cpi_context_only" or row.get("source_family") == "CPI":
            series_ids.append(row["series_id"])
    return list(dict.fromkeys(series_ids))


def _implicit_only_ppi(row: dict) -> bool:
    if row.get("source_family") != "PPI" or row.get("role") != "pce_component":
        return False
    lines = set(row.get("pce_lines") or [])
    return bool(lines) and lines <= IMPLICIT_PCE_LINES


def priority_ppi_series(registry: dict) -> list[str]:
    rows = [
        row
        for row in registry.get("verified") or []
        if row.get("role") == "pce_component" and row.get("source_family") == "PPI" and not _implicit_only_ppi(row)
    ]
    rows.sort(key=lambda row: Decimal(str(row.get("absolute_weight") or "0")), reverse=True)
    return [row["series_id"] for row in rows[:PRIORITY_PPI_CAP]]


def optional_ambiguous_ppi_series(registry: dict) -> list[str]:
    series_ids: list[str] = []
    for group in registry.get("ambiguous") or []:
        if group.get("source_family") != "PPI":
            continue
        for candidate in group.get("candidates") or []:
            series_ids.append(candidate["series_id"])
    return list(dict.fromkeys(series_ids))


def fetch_plan(registry: dict, kind: str) -> list[str]:
    """Series arm will request."""
    if kind not in {"cpi", "ppi"}:
        raise ValueError("kind must be cpi or ppi")
    if kind == "cpi":
        return cached_cpi_series(registry)
    return priority_ppi_series(registry)


def _priority_fetch_succeeded(fetched: dict) -> bool:
    if fetched.get("budget_exhausted"):
        return False
    return not any(error.get("reason") in {"transport_error", "bls_status"} for error in fetched.get("errors") or [])


def _merge_fetched(primary: dict, secondary: dict) -> dict:
    merged = dict(primary)
    for key in ("points", "latest", "footnotes"):
        bucket = dict(primary.get(key) or {})
        bucket.update(secondary.get(key) or {})
        merged[key] = bucket
    merged["errors"] = list(primary.get("errors") or []) + list(secondary.get("errors") or [])
    merged["raw_documents"] = list(primary.get("raw_documents") or []) + list(secondary.get("raw_documents") or [])
    merged["requested"] = list(dict.fromkeys(list(primary.get("requested") or []) + list(secondary.get("requested") or [])))
    merged["source_latency_seconds"] = float(primary.get("source_latency_seconds") or 0) + float(
        secondary.get("source_latency_seconds") or 0
    )
    merged["requests_made"] = int(secondary.get("requests_made") or 0)
    merged["elapsed_seconds"] = float(secondary.get("elapsed_seconds") or 0)
    merged["budget_exhausted"] = bool(secondary.get("budget_exhausted"))
    merged["key_present"] = bool(primary.get("key_present"))
    return merged


def acquire_official(series_ids: list[str], release: str, registry: dict | None = None) -> dict:
    """One bounded BLS pull. Does not arm a listener and does not loop forever."""
    document = registry if registry is not None else load_registry()
    year = release[:4]
    budget_state: dict = {}
    fetched = fetch_series(series_ids, start_year=year, end_year=year, budget_state=budget_state)

    priority_ids = list(dict.fromkeys(series_ids))
    ambiguous_ids = optional_ambiguous_ppi_series(document)
    follow_up = [series_id for series_id in ambiguous_ids if series_id not in priority_ids]
    ppi_priority = set(priority_ppi_series(document))
    if (
        follow_up
        and priority_ids
        and ppi_priority
        and set(priority_ids) & ppi_priority
        and _priority_fetch_succeeded(fetched)
        and not fetched.get("budget_exhausted")
    ):
        room = MAX_PPI_POLL_SERIES - len(priority_ids)
        if room > 0:
            follow_up = follow_up[:room]
            secondary = fetch_series(
                follow_up,
                start_year=year,
                end_year=year,
                budget_state=budget_state,
            )
            fetched = _merge_fetched(fetched, secondary)

    observations, gaps = build_observations(document, fetched["points"], release)
    for observation in observations:
        notes = [
            note
            for note in (fetched["footnotes"].get(observation.get("series_id")) or [])
            if note.get("period") == observation.get("period") and (note.get("code") or note.get("text"))
        ]
        if notes:
            observation["bls_footnote_code"] = notes[0].get("code")
            observation["bls_footnote"] = notes[0].get("text")
    return {
        "observations": observations,
        "gaps": gaps + [{"reason": error["reason"], **{k: v for k, v in error.items() if k != "reason"}} for error in fetched["errors"]],
        "source_latency_seconds": fetched["source_latency_seconds"],
        "series_latest": fetched["latest"],
        "footnotes": fetched["footnotes"],
        "raw_documents": fetched["raw_documents"],
        "requested": fetched["requested"],
        "requests_made": fetched.get("requests_made", 0),
        "budget_exhausted": fetched.get("budget_exhausted", False),
        "key_present": fetched.get("key_present", False),
        "elapsed_seconds": fetched.get("elapsed_seconds", 0.0),
    }
