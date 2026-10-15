"""Network-free weighted-series contract preflight for launch ingestion."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from scripts.macro_ingestion.contract import calibration_as_of, load_calibration, load_catalog
from scripts.macro_ingestion.ledger import ledger_row
from scripts.macro_ingestion.windows import cutoff_class
from scripts.run_state.compiler import compile_catalog
from scripts.run_state.identity import preflight_weighted_series
from scripts.temperature_level import HISTORY_DIR, load_history

ROOT = Path(__file__).resolve().parents[2]


def _history_dir(root: Path | None) -> Path:
    base = root or ROOT
    history_dir = base / "data" / "temperature_history"
    if history_dir.is_dir():
        return history_dir
    return HISTORY_DIR


def compilable_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    """Catalog copy compile_catalog accepts (non-empty string series_id only)."""
    out = copy.deepcopy(catalog)
    out["series"] = [
        row
        for row in out.get("series") or []
        if isinstance(row, dict)
        and isinstance(row.get("series_id"), str)
        and row.get("series_id") != ""
    ]
    return out


def run_weighted_series_preflight(
    *,
    root: Path | None = None,
    catalog: dict[str, Any] | None = None,
    calibration: dict[str, Any] | None = None,
    histories: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Load repo artifacts (unless overridden) and run preflight_weighted_series."""
    catalog = catalog or load_catalog()
    calibration = calibration or load_calibration()
    if histories is None:
        histories = load_history(_history_dir(root))
    compilable = compilable_catalog(catalog)
    definitions = compile_catalog(compilable)
    return preflight_weighted_series(
        catalog,
        calibration,
        histories if isinstance(histories, dict) else None,
        definitions,
    )


def ledger_rows_for_preflight_mismatches(
    mismatches: list[dict[str, Any]],
    *,
    checked_at: str,
    calibration_as_of_value: str,
    cutoff_class_value: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in mismatches:
        concept_id = str(item.get("concept_id") or "")
        if not concept_id:
            continue
        extra = {
            "contract_mismatch": {
                "concept_id": concept_id,
                "country": item.get("country"),
                "component": item.get("component"),
                "source": item.get("source"),
                "field": item.get("field"),
                "expected": item.get("expected"),
                "actual": item.get("actual"),
                "reason": item.get("reason"),
            }
        }
        rows.append(
            ledger_row(
                series_id=concept_id,
                status="contract_mismatch",
                checked_at=checked_at,
                observation_vintage=None,
                calibration_as_of=calibration_as_of_value,
                cutoff_class=cutoff_class_value,
                error=str(item.get("reason") or "contract_mismatch"),
                extra=extra,
            )
        )
    return rows


def preflight_summary_for_details(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": bool(report.get("ok")),
        "checked": int(report.get("checked") or 0),
        "mismatch_count": len(report.get("mismatches") or []),
        "blocked_countries": list(report.get("blocked_countries") or []),
    }
