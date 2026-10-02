"""US Employment Context block for the research / Market Data labor surface."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.macro_ingestion.contract import index_series_rows, load_catalog
from scripts.macro_ingestion.us_employment.contract import (
    SECTION_ATTRIBUTION,
    SECTION_CORROBORATION,
    SECTION_FLOWS,
    SECTION_FORECAST,
    SECTION_SUPPLY,
)
from scripts.macro_ingestion.us_employment.derived import attribution_channels
from scripts.macro_ingestion.vintage import load_store

_SECTION_ORDER = (
    SECTION_FORECAST,
    SECTION_FLOWS,
    SECTION_SUPPLY,
    SECTION_CORROBORATION,
    SECTION_ATTRIBUTION,
)

_LEVEL_KEYS = {
    "US.Labor.unemployed": "unemployed",
    "US.Labor.labor_force": "labor_force",
    "US.Labor.household_employment": "household_employment",
    "US.Labor.unemployed_job_losers": "job_losers",
    "US.Labor.unemployed_job_leavers": "job_leavers",
    "US.Labor.unemployed_reentrants": "reentrants",
    "US.Labor.unemployed_new_entrants": "new_entrants",
    "US.Labor.flow_eu": "flow_eu",
    "US.Labor.flow_ue": "flow_ue",
    "US.Labor.flow_nu": "flow_nu",
    "US.Labor.flow_un": "flow_un",
    "US.Labor.flow_ne": "flow_ne",
    "US.Labor.flow_en": "flow_en",
}


def _latest_by_catalog(
    store: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    series_to_ids: dict[tuple[str, str], str] = {}
    for catalog_id, row in by_id.items():
        if row.get("employment_section") is None and not str(catalog_id).startswith("US.Labor."):
            continue
        series_id = str(row.get("series_id") or "")
        transform = str(row.get("transform") or "")
        if series_id and transform:
            series_to_ids[(series_id, transform)] = catalog_id
    for obs in store.get("observations") or []:
        key = (str(obs.get("series_id") or ""), str(obs.get("transformation") or ""))
        catalog_id = series_to_ids.get(key)
        if catalog_id is None:
            continue
        grouped.setdefault(catalog_id, []).append(obs)
    return grouped


def _row_view(catalog_row: dict[str, Any], obs: dict[str, Any] | None, *, gap: str | None = None) -> dict[str, Any]:
    view = {
        "catalog_id": catalog_row["id"],
        "series_id": catalog_row.get("series_id"),
        "name": catalog_row.get("canonical_name"),
        "section": catalog_row.get("employment_section"),
        "weight": 0.0,
        "score_weight_policy": catalog_row.get("score_weight_policy"),
        "publisher": catalog_row.get("publisher"),
        "units": catalog_row.get("units"),
        "transform": catalog_row.get("transform"),
    }
    if gap:
        view["status"] = "license_gap"
        view["error"] = gap
        return view
    if obs is None:
        view["status"] = "not_yet_observed"
        return view
    view.update(
        {
            "status": "observed",
            "period": obs.get("period"),
            "value": obs.get("value"),
            "vintage": obs.get("vintage"),
            "revision_status": obs.get("revision_status"),
            "source_url": obs.get("source_url"),
            "raw_sha256": obs.get("raw_sha256"),
            "release_date": obs.get("release_date"),
            "derivation": obs.get("derivation"),
        }
    )
    return view


def _levels_from_history(history: list[dict[str, Any]], period: str) -> dict[str, float]:
    levels: dict[str, float] = {}
    for catalog_id, key in _LEVEL_KEYS.items():
        for obs in history:
            if obs.get("_catalog_id") == catalog_id and obs.get("period") == period:
                try:
                    levels[key] = float(obs["value"])
                except (KeyError, TypeError, ValueError):
                    continue
    return levels


def build_us_employment_context(
    *,
    catalog: dict[str, Any] | None = None,
    store: dict[str, Any] | None = None,
    observations_dir: Path | None = None,
) -> dict[str, Any]:
    """Assemble Forecast / Flows / Supply / Corroboration / Attribution.

    Reads the macro-ingestion catalog and observation store. Does not score.
    """
    catalog = catalog or load_catalog()
    by_id = index_series_rows(catalog.get("series") or [])
    if store is None:
        store = load_store("US", observations_dir) if observations_dir is not None else {"country": "US", "observations": []}
        if observations_dir is None:
            store = load_store("US")

    employment_rows = [
        row
        for row in by_id.values()
        if str(row.get("id", "")).startswith("US.Labor.") and row.get("employment_section")
    ]
    grouped = _latest_by_catalog(store, {row["id"]: row for row in employment_rows})
    sections: dict[str, list[dict[str, Any]]] = {name: [] for name in _SECTION_ORDER}
    flat_history: list[dict[str, Any]] = []

    for row in sorted(employment_rows, key=lambda item: str(item["id"])):
        catalog_id = str(row["id"])
        observations = sorted(grouped.get(catalog_id) or [], key=lambda item: str(item.get("period") or ""))
        for obs in observations:
            flat_history.append({**obs, "_catalog_id": catalog_id})
        latest = observations[-1] if observations else None
        gap = None
        if row.get("classification") == "proprietary_blocked" or row.get("retrieval_method") == "unavailable":
            gap = str(row.get("blocked_reason") or "license_gap")
        view = _row_view(row, None if gap else latest, gap=gap)
        section = str(row.get("employment_section") or SECTION_FLOWS)
        sections.setdefault(section, []).append(view)

    periods = sorted({str(obs.get("period")) for obs in flat_history if obs.get("_catalog_id") == "US.Labor.unemployed"})
    attribution: dict[str, Any] = {"primary_cause": "insufficient_data", "channels": {}}
    if len(periods) >= 2:
        attribution = attribution_channels(
            _levels_from_history(flat_history, periods[-1]),
            _levels_from_history(flat_history, periods[-2]),
        )
        attribution["period"] = periods[-1]
        attribution["prior_period"] = periods[-2]

    return {
        "country": "US",
        "block": "us_employment_context",
        "weight_policy": "context_only_weight_zero",
        "score_inputs_changed": False,
        "sections": {
            "forecast": sections.get(SECTION_FORECAST, []),
            "current_flows": sections.get(SECTION_FLOWS, []),
            "labor_supply_regime": sections.get(SECTION_SUPPLY, []),
            "corroboration": sections.get(SECTION_CORROBORATION, []),
            "post_print_attribution": {
                "metrics": sections.get(SECTION_ATTRIBUTION, []),
                "primary_cause": attribution.get("primary_cause"),
                "channels": attribution.get("channels") or {},
                "period": attribution.get("period"),
                "prior_period": attribution.get("prior_period"),
                "sources": attribution.get("sources"),
            },
        },
    }
