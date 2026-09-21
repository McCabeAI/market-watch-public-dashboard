"""Flag scored Activity surveys that omit a known newer public primary release.

This is a source-audit check only. It does not change score weights or add
staleness decay: a missing newer primary print is a harvest defect, not a
reason to down-weight the last observed survey.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data" / "temperature_history" / "activity_survey_release_catalog.json"
HISTORY_FILES = {
    "CA": ROOT / "data" / "temperature_history" / "ca.json",
    "AU": ROOT / "data" / "temperature_history" / "au.json",
    "NZ": ROOT / "data" / "temperature_history" / "nz.json",
}
HARVEST_REPORTS = {
    "CA": ROOT / "data" / "temperature_history" / "raw" / "ca" / "harvest_report.json",
    "AU": ROOT / "data" / "temperature_history" / "raw" / "au" / "harvest_report.json",
    "NZ": ROOT / "data" / "temperature_history" / "raw" / "nz" / "harvest_report.json",
}


def load_catalog(path: Path = CATALOG_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _scored_periods(history: dict[str, Any], series_id: str, history_key: str) -> set[str]:
    component = history["components"][history_key]
    return {
        str(obs["reference_period"])
        for obs in component.get("observations", [])
        if obs.get("series_id") == series_id
    }


def _period_ok_for_cutoff(reference_period: str, cutoff: str) -> bool:
    return reference_period <= cutoff[:7]


def freshness_errors(
    *,
    catalog: dict[str, Any] | None = None,
    histories: dict[str, dict[str, Any]] | None = None,
    harvest_reports: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    catalog = catalog or load_catalog()
    cutoff = str(catalog.get("cutoff") or "2026-09-21")
    if histories is None:
        histories = {
            code: json.loads(path.read_text(encoding="utf-8"))
            for code, path in HISTORY_FILES.items()
        }
    if harvest_reports is None:
        harvest_reports = {}
        for code, path in HARVEST_REPORTS.items():
            if path.exists():
                harvest_reports[code] = json.loads(path.read_text(encoding="utf-8"))

    errors: list[str] = []
    known: list[dict[str, Any]] = list(catalog.get("releases") or [])
    for code, report in harvest_reports.items():
        series_id = report.get("series_id")
        history_key = "Activity.business_surveys"
        for obs in report.get("recovered_months") or []:
            known.append(
                {
                    "country": code,
                    "history_key": history_key,
                    "series_id": obs.get("series_id") or series_id,
                    "reference_period": obs["reference_period"],
                    "source_url": obs.get("source_url"),
                    "retrievable": True,
                }
            )

    latest_known: dict[tuple[str, str], str] = {}
    latest_scored: dict[tuple[str, str], str] = {}
    for release in known:
        if not release.get("retrievable", True):
            continue
        country = release["country"]
        series_id = release["series_id"]
        history_key = release.get("history_key", "Activity.business_surveys")
        period = release["reference_period"]
        if not _period_ok_for_cutoff(period, cutoff):
            continue
        history = histories[country]
        scored = _scored_periods(history, series_id, history_key)
        key = (country, series_id)
        latest_known[key] = max(period, latest_known.get(key, period))
        if scored:
            latest_scored[key] = max(scored)
        if period not in scored:
            errors.append(
                f"{country} {series_id}: known public primary release {period} "
                f"({release.get('source_url')}) is missing from canonical history "
                "while an older survey print would retain full score weight"
            )

    for key, known_latest in latest_known.items():
        scored_latest = latest_scored.get(key)
        if scored_latest and scored_latest < known_latest:
            country, series_id = key
            errors.append(
                f"{country} {series_id}: latest scored period {scored_latest} is older than "
                f"known retrievable primary print {known_latest}"
            )
    return errors


def main() -> int:
    errors = freshness_errors()
    if errors:
        raise SystemExit("\n".join(errors))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
