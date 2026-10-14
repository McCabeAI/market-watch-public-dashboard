"""AU labour reliability catalog baseline updates and committed catalog sync."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from scripts.macro_ingestion.au_leading import jsa_ivi, jsa_reos
from scripts.macro_ingestion.contract import (
    BASELINE_CATALOG_PATH,
    FRAGMENTS_DIR,
    index_series_rows,
    load_baseline_catalog,
    load_catalog,
    load_json,
    validate_catalog_against_baseline,
)

ROOT = Path(__file__).resolve().parents[2]
CONTEXT_ROWS_PATH = ROOT / "data/macro_ingestion/au_labor_context_rows.json"
COMMITTED_CATALOG_PATH = ROOT / "data/macro_ingestion/catalog.json"
AU_FRAGMENT_PATH = FRAGMENTS_DIR / "au.json"

_OVERLAY_FROM_LOAD_CATALOG = frozenset(
    {
        "AU.Labor.unemployment",
        "AU.Labor.employment",
        "AU.Labor.participation",
    }
)

_PARTICIPATION_TEMPLATE_ID = "AU.Labor.participation"


def _participation_boilerplate(baseline: dict[str, Any]) -> dict[str, Any]:
    row = index_series_rows(baseline["series"])[_PARTICIPATION_TEMPLATE_ID]
    keys = (
        "metadata_availability",
        "raw_provenance",
        "observation_count",
        "latest_period",
        "latest_value_held",
        "latest_retrieved_at",
        "ledger_vintage",
        "verification_state",
        "freshness_state",
        "blocked_reason",
        "history_notes",
        "score_weight_policy",
    )
    return {key: copy.deepcopy(row[key]) for key in keys if key in row}


def _unemployment_release_rule_from_fragment() -> dict[str, Any]:
    fragment = load_json(AU_FRAGMENT_PATH)
    for row in fragment.get("series") or []:
        if row.get("id") == "AU.Labor.unemployment":
            return copy.deepcopy(row["release_rule"])
    raise KeyError("AU.Labor.unemployment release_rule missing from au.json fragment")


def _leading_publisher_rows(boilerplate: dict[str, Any]) -> list[dict[str, Any]]:
    base = {
        "country": "AU",
        "dimension": "Labor",
        "role": "context",
        "weight": 0.0,
        "distributor": None,
        "classification": "official",
        "seasonal_adjustment": True,
        "cadence": "monthly",
        "timezone": "Australia/Sydney",
        "adapter": "scripts.macro_ingestion.adapters.au",
        "score_weight_policy": "weight_must_remain_zero",
        "added_by": "au-labor-reliability-20261014",
        **boilerplate,
    }
    return [
        {
            **base,
            "id": "AU.Labor.jsa_ivi_national_sa",
            "component": "jsa_ivi_national_sa",
            "series_id": "AUSTRALIAN_TOTAL",
            "canonical_name": "Internet Vacancy Index, Australian total, seasonally adjusted",
            "publisher": "Jobs and Skills Australia",
            "endpoint": jsa_ivi.IVI_LANDING_URL,
            "registry_urls": [jsa_ivi.IVI_LANDING_URL],
            "units": "vacancies",
            "transform": "sa_level",
            "retrieval_method": "jsa_ivi_xlsx",
            "release_rule": {
                "kind": "country_local_schedule_required",
                "timezone": "Australia/Sydney",
                "dates": [],
                "note": (
                    "September 2026 IVI is unpublished until 2026-10-21; "
                    "August 2026 released 2026-09-23 per publisher landing copy."
                ),
            },
        },
        {
            **base,
            "id": "AU.Labor.anz_indeed_job_ads_sa",
            "component": "anz_indeed_job_ads_sa",
            "series_id": "ANZ_INDEED_JOB_ADS_SA",
            "canonical_name": "ANZ-Indeed Australian job advertisements, seasonally adjusted",
            "publisher": "ANZ-Indeed",
            "endpoint": "https://www.anz.com.au/newsroom/media/2026/october/job-ads-up-again/",
            "registry_urls": [
                "https://www.anz.com.au/newsroom/media/2026/october/job-ads-up-again/"
            ],
            "units": "index",
            "transform": "sa_level",
            "retrieval_method": "anz_indeed_xlsx",
            "release_rule": {
                "kind": "explicit_timestamp",
                "timezone": "Australia/Sydney",
                "dates": ["2026-10-06T00:00:00+11:00"],
                "expected_periods": {"2026-10-06T00:00:00+11:00": "2026-09"},
                "note": "release_day_start_not_print_time",
            },
        },
        {
            **base,
            "id": "AU.Labor.nab_employment_subindex",
            "component": "nab_employment_subindex",
            "series_id": "NAB_EMPLOYMENT_SUBINDEX",
            "canonical_name": "NAB Monthly Business Survey employment sub-index",
            "publisher": "NAB",
            "endpoint": (
                "https://www.nabtrade.com.au/insights/news/2026/10/"
                "nab-business-survey---september-2026"
            ),
            "registry_urls": [
                "https://www.nabtrade.com.au/insights/news/2026/10/"
                "nab-business-survey---september-2026"
            ],
            "units": "index_points",
            "transform": "level",
            "retrieval_method": "nab_monthly_business_survey_pdf",
            "release_rule": {
                "kind": "explicit_timestamp",
                "timezone": "Australia/Sydney",
                "dates": ["2026-10-13T00:00:00+11:00"],
                "expected_periods": {"2026-10-13T00:00:00+11:00": "2026-09"},
                "note": "release_day_start_not_print_time",
            },
        },
        {
            **base,
            "id": "AU.Labor.seek_job_ad_trend",
            "component": "seek_job_ad_trend",
            "series_id": "SEEK_JOB_AD_TREND",
            "canonical_name": "SEEK job advertisement trend, month-on-month percent",
            "publisher": "SEEK",
            "endpoint": "https://au.seek.com/about/news/category/seek-employment-reports/0",
            "registry_urls": [
                "https://au.seek.com/about/news/category/seek-employment-reports/0"
            ],
            "units": "percent",
            "transform": "trend_mom_pct",
            "retrieval_method": "seek_employment_report_html",
            "release_rule": {
                "kind": "explicit_timestamp",
                "timezone": "Australia/Sydney",
                "dates": ["2026-09-17T00:00:00+11:00"],
                "expected_periods": {"2026-09-17T00:00:00+11:00": "2026-08"},
                "note": "release_day_start_not_print_time",
            },
        },
        {
            **base,
            "id": "AU.Labor.jsa_reos_recruiting_share",
            "component": "jsa_reos_recruiting_share",
            "series_id": "AU.Labor.jsa_reos_recruiting_share",
            "canonical_name": "REOS recruiting share (employers recruiting)",
            "publisher": "Jobs and Skills Australia",
            "endpoint": jsa_reos.REOS_LANDING_URL,
            "registry_urls": [
                "https://www.jobsandskills.gov.au/data/recruitment-experiences-and-outlook-survey"
            ],
            "units": "percent",
            "transform": "percent",
            "retrieval_method": "jsa_reos_xlsx",
            "verification_state": "license_gap",
            "release_rule": {
                "kind": "country_local_schedule_required",
                "timezone": "Australia/Sydney",
                "dates": [],
                "note": (
                    "August 2026 REOS workbook was not retrieved (live timeout; no archived copy)."
                ),
            },
        },
        {
            **base,
            "id": "AU.Labor.jsa_reos_recruitment_difficulty",
            "component": "jsa_reos_recruitment_difficulty",
            "series_id": "AU.Labor.jsa_reos_recruitment_difficulty",
            "canonical_name": "REOS recruitment difficulty share",
            "publisher": "Jobs and Skills Australia",
            "endpoint": (
                "https://www.jobsandskills.gov.au/data/recruitment-experiences-and-outlook-survey"
            ),
            "registry_urls": [
                "https://www.jobsandskills.gov.au/data/recruitment-experiences-and-outlook-survey"
            ],
            "units": "percent",
            "transform": "percent",
            "retrieval_method": "jsa_reos_xlsx",
            "verification_state": "license_gap",
            "release_rule": {
                "kind": "country_local_schedule_required",
                "timezone": "Australia/Sydney",
                "dates": [],
                "note": (
                    "August 2026 REOS workbook was not retrieved (live timeout; no archived copy)."
                ),
            },
        },
        {
            **base,
            "id": "AU.Labor.jsa_reos_hiring_intent",
            "component": "jsa_reos_hiring_intent",
            "series_id": "AU.Labor.jsa_reos_hiring_intent",
            "canonical_name": "REOS hiring intent share (expect to increase staff)",
            "publisher": "Jobs and Skills Australia",
            "endpoint": (
                "https://www.jobsandskills.gov.au/data/recruitment-experiences-and-outlook-survey"
            ),
            "registry_urls": [
                "https://www.jobsandskills.gov.au/data/recruitment-experiences-and-outlook-survey"
            ],
            "units": "percent",
            "transform": "percent",
            "retrieval_method": "jsa_reos_xlsx",
            "verification_state": "license_gap",
            "release_rule": {
                "kind": "country_local_schedule_required",
                "timezone": "Australia/Sydney",
                "dates": [],
                "note": (
                    "August 2026 REOS workbook was not retrieved (live timeout; no archived copy)."
                ),
            },
        },
    ]


def apply_au_labor_baseline_updates(
    baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return baseline with AU labour reliability rows appended and unemployment transform fixed."""
    baseline = copy.deepcopy(baseline or load_baseline_catalog())
    by_id = index_series_rows(baseline["series"])
    by_id["AU.Labor.unemployment"]["transform"] = "percent"

    labour_rule = _unemployment_release_rule_from_fragment()
    context_rows = json.loads(CONTEXT_ROWS_PATH.read_text(encoding="utf-8"))
    boilerplate = _participation_boilerplate(baseline)
    append_rows: list[dict[str, Any]] = []
    for row in context_rows:
        row = copy.deepcopy(row)
        if row.get("release_rule", {}).get("dates") == []:
            row["release_rule"] = copy.deepcopy(labour_rule)
        for key, value in boilerplate.items():
            row.setdefault(key, copy.deepcopy(value))
        append_rows.append(row)

    append_rows.extend(_leading_publisher_rows(boilerplate))

    series_list = list(baseline["series"])
    for idx, row in enumerate(series_list):
        rid = row["id"]
        if rid in by_id and rid == "AU.Labor.unemployment":
            series_list[idx] = copy.deepcopy(by_id[rid])
    present = {row["id"] for row in series_list}
    for row in append_rows:
        if row["id"] in present:
            for idx, existing in enumerate(series_list):
                if existing["id"] == row["id"]:
                    series_list[idx] = copy.deepcopy(row)
                    break
        else:
            series_list.append(copy.deepcopy(row))
            present.add(row["id"])

    baseline["series"] = series_list
    validate_catalog_against_baseline(baseline, baseline=baseline)
    return baseline


def sync_committed_catalog(
    *,
    committed_path: Path = COMMITTED_CATALOG_PATH,
    baseline_path: Path = BASELINE_CATALOG_PATH,
    write_baseline: bool = True,
) -> tuple[int, int]:
    """Apply baseline labour updates and merge load_catalog() rows into catalog.json.

    Returns (series_count_before, series_count_after).
    """
    baseline = apply_au_labor_baseline_updates(load_baseline_catalog(baseline_path))
    if write_baseline:
        baseline_path.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")

    on_disk = load_json(committed_path)
    before = len(on_disk["series"])
    merged_catalog = load_catalog(baseline_path=baseline_path)
    merged_by_id = index_series_rows(merged_catalog["series"])
    on_disk_by_id = index_series_rows(on_disk["series"])

    new_series: list[dict[str, Any]] = []
    for row in on_disk["series"]:
        rid = row["id"]
        if rid in _OVERLAY_FROM_LOAD_CATALOG:
            new_series.append(copy.deepcopy(merged_by_id[rid]))
        else:
            new_series.append(row)

    present = {row["id"] for row in new_series}
    for rid, row in merged_by_id.items():
        if rid not in present:
            new_series.append(copy.deepcopy(row))
            present.add(rid)

    on_disk["series"] = new_series
    validate_catalog_against_baseline(on_disk, baseline=baseline)
    committed_path.write_text(json.dumps(on_disk, indent=2) + "\n", encoding="utf-8")
    after = len(on_disk["series"])
    return before, after
