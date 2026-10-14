"""Aggregate ingestion ledger rows into operator-facing health signals."""

from __future__ import annotations

from typing import Any

CORE_LABOR_IDS = frozenset(
    {
        "AU.Labor.unemployment",
        "AU.Labor.employment",
        "US.Labor.payrolls",
        "US.Labor.unemployment",
        "US.Labor.wages",
    }
)

LEADING_SOURCE_PREFIXES = (
    "AU.Labor.jsa_",
    "AU.Labor.anz_",
    "AU.Labor.nab_",
    "AU.Labor.seek_",
)


def _is_failed_status(status: str | None) -> bool:
    return status in {"source_failed", "license_gap"}


def _failed_attempt_count(row: dict[str, Any]) -> int:
    history = row.get("attempt_history") or []
    count = sum(1 for item in history if _is_failed_status(str(item.get("status") or "")))
    if _is_failed_status(str(row.get("status") or "")):
        count += 1
    return count


def _is_leading_source(series_id: str) -> bool:
    return any(series_id.startswith(prefix) for prefix in LEADING_SOURCE_PREFIXES)


def _missing_core_labor_row(row: dict[str, Any]) -> dict[str, Any] | None:
    series_id = str(row.get("series_id") or "")
    if series_id not in CORE_LABOR_IDS:
        return None
    status = str(row.get("status") or "")
    error = row.get("error")
    if error == "budget_deferred":
        return None
    if status == "due_missing":
        return {
            "series_id": series_id,
            "status": status,
            "error": error,
            "publication_state": row.get("publication_state"),
        }
    if status == "source_failed":
        return {
            "series_id": series_id,
            "status": status,
            "error": error,
            "publication_state": row.get("publication_state"),
        }
    return None


def build_source_health_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    missing_due_core_labor: list[dict[str, Any]] = []
    leading_source_alert: list[dict[str, Any]] = []

    for row in rows:
        missing = _missing_core_labor_row(row)
        if missing is not None:
            missing_due_core_labor.append(missing)

        series_id = str(row.get("series_id") or "")
        if not _is_leading_source(series_id):
            continue
        if _failed_attempt_count(row) < 2:
            continue
        leading_source_alert.append(
            {
                "series_id": series_id,
                "status": row.get("status"),
                "error": row.get("error"),
                "publication_state": row.get("publication_state"),
                "failed_attempts": _failed_attempt_count(row),
            }
        )

    return {
        "missing_due_core_labor": missing_due_core_labor,
        "leading_source_alert": leading_source_alert,
    }
