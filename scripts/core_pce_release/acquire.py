"""Live BLS acquisition for verified PCE component series."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.core_pce_release.bls import fetch_series
from scripts.core_pce_release.normalize import build_observations
from scripts.core_pce_release.snapshot import REPO_ROOT

REGISTRY_PATH = REPO_ROOT / "data" / "core_pce_release" / "series_registry.json"


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


def fetch_plan(registry: dict, kind: str) -> list[str]:
    """Series arm will request. PPI day still includes CPI series already published."""
    if kind not in {"cpi", "ppi"}:
        raise ValueError("kind must be cpi or ppi")
    series_ids: list[str] = []
    for row in registry.get("verified") or []:
        family = row.get("source_family")
        if row.get("role") == "cpi_context_only" or family == "CPI":
            series_ids.append(row["series_id"])
        elif family == "PPI" and kind == "ppi":
            series_ids.append(row["series_id"])
    if kind == "ppi":
        for group in registry.get("ambiguous") or []:
            if group.get("source_family") != "PPI":
                continue
            for candidate in group.get("candidates") or []:
                series_ids.append(candidate["series_id"])
    return list(dict.fromkeys(series_ids))


def acquire_official(series_ids: list[str], release: str, registry: dict | None = None) -> dict:
    """One bounded BLS pull. Does not arm a listener and does not loop forever."""
    document = registry if registry is not None else load_registry()
    fetched = fetch_series(series_ids, start_year=release[:4], end_year=release[:4])
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
    }
