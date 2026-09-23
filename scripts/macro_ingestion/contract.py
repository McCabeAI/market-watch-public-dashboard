"""Baseline catalog load and validation against frozen calibration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BASELINE_CATALOG_PATH = ROOT / "data/macro_ingestion/baseline_catalog.json"
CALIBRATION_PATH = ROOT / "data/temperature_calibration.json"
FRAGMENTS_DIR = ROOT / "data/macro_ingestion/fragments"

STATUS_VOCABULARY: tuple[str, ...] = (
    "checked_unchanged",
    "new_observation",
    "revision_applied",
    "revision_pending",
    "due_missing",
    "source_failed",
    "license_gap",
    "not_applicable",
    "calendar_unparsed",
    "incomplete_country",
)

_ZERO_WEIGHT_ROLES = frozenset({"context", "registry_unweighted", "explanatory_alias"})
COUNTRY_CODES = ("US", "CA", "AU", "NZ", "EA", "JP")
_ROLE_PRIORITY = {
    "scored": 4,
    "context": 3,
    "registry_unweighted": 2,
    "explanatory_alias": 1,
}


class CatalogValidationError(ValueError):
    """Raised when the ingestion catalog violates the parent contract."""


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_baseline_catalog(path: Path = BASELINE_CATALOG_PATH) -> dict[str, Any]:
    catalog = load_json(path)
    validate_status_vocabulary(catalog)
    return catalog


def load_calibration(path: Path = CALIBRATION_PATH) -> dict[str, Any]:
    return load_json(path)


def validate_status_vocabulary(catalog: dict[str, Any]) -> None:
    expected = list(STATUS_VOCABULARY)
    found = catalog.get("status_vocabulary")
    if found != expected:
        raise CatalogValidationError(
            f"status_vocabulary must match architecture doc exactly; got {found!r}"
        )


def _calibration_weight(cal: dict[str, Any], country: str, dimension: str, component: str) -> float:
    try:
        return float(cal["weights"][country][dimension][component])
    except (KeyError, TypeError) as exc:
        raise CatalogValidationError(
            f"No calibration weight for scored row {country}.{dimension}.{component}"
        ) from exc


def index_series_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Collapse duplicate ids; keep the highest-priority role (scored beats alias)."""
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        rid = row["id"]
        existing = by_id.get(rid)
        if existing is None:
            by_id[rid] = row
            continue
        new_pri = _ROLE_PRIORITY.get(str(row.get("role")), 0)
        old_pri = _ROLE_PRIORITY.get(str(existing.get("role")), 0)
        if new_pri >= old_pri:
            by_id[rid] = row
    return by_id


def validate_catalog_against_baseline(
    catalog: dict[str, Any],
    *,
    baseline: dict[str, Any] | None = None,
    calibration: dict[str, Any] | None = None,
) -> None:
    """Ensure merged catalog retains every baseline id and frozen weights."""
    baseline = baseline or load_baseline_catalog()
    calibration = calibration or load_calibration()
    validate_status_vocabulary(catalog)

    baseline_by_id = index_series_rows(baseline["series"])
    catalog_by_id = index_series_rows(catalog["series"])

    missing = sorted(set(baseline_by_id) - set(catalog_by_id))
    if missing:
        raise CatalogValidationError(f"Missing baseline series ids: {missing[:5]}{'...' if len(missing) > 5 else ''}")

    scored_count = 0
    for row in catalog_by_id.values():
        role = row.get("role")
        weight = float(row.get("weight", 0.0))
        country, dimension, component = row["country"], row["dimension"], row["component"]

        if role in _ZERO_WEIGHT_ROLES:
            if weight != 0.0:
                raise CatalogValidationError(f"{row['id']} role={role} must have weight 0, got {weight}")
            continue

        if role == "scored":
            scored_count += 1
            expected = _calibration_weight(calibration, country, dimension, component)
            if weight != expected:
                raise CatalogValidationError(
                    f"{row['id']} weight {weight} != calibration {expected}"
                )

    if scored_count != int(baseline.get("scored_weight_row_count", 66)):
        raise CatalogValidationError(f"Expected 66 scored rows, found {scored_count}")


def load_catalog(
    *,
    baseline_path: Path = BASELINE_CATALOG_PATH,
    fragments_dir: Path = FRAGMENTS_DIR,
) -> dict[str, Any]:
    """Baseline plus optional country fragment overlays."""
    baseline = load_baseline_catalog(baseline_path)
    merged = json.loads(json.dumps(baseline))
    by_id = index_series_rows(merged["series"])

    if fragments_dir.is_dir():
        for fragment_path in sorted(fragments_dir.glob("*.json")):
            fragment = load_json(fragment_path)
            for row in fragment.get("series", []):
                if row["id"] not in by_id:
                    raise CatalogValidationError(f"Fragment adds unknown id {row['id']}")
                by_id[row["id"]] = {**by_id[row["id"]], **row}

    merged["series"] = list(by_id.values())
    validate_catalog_against_baseline(merged, baseline=baseline)
    return merged


def calibration_as_of(catalog: dict[str, Any] | None = None) -> str:
    if catalog and catalog.get("calibration_as_of"):
        return str(catalog["calibration_as_of"])
    return str(load_baseline_catalog().get("calibration_as_of", "2026-09-21"))
