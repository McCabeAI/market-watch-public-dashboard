"""Append-only macro observation store."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OBSERVATIONS_DIR = ROOT / "data/macro_ingestion/observations"


@dataclass(frozen=True)
class ObservationKey:
    series_id: str
    period: str
    transformation: str
    raw_sha256: str


def observation_path(country: str, base_dir: Path = OBSERVATIONS_DIR) -> Path:
    return base_dir / f"{country.lower()}.json"


def _empty_store(country: str) -> dict[str, Any]:
    return {"country": country.upper(), "observations": []}


def load_store(country: str, base_dir: Path = OBSERVATIONS_DIR) -> dict[str, Any]:
    path = observation_path(country, base_dir)
    if not path.exists():
        return _empty_store(country)
    return json.loads(path.read_text(encoding="utf-8"))


def save_store(store: dict[str, Any], base_dir: Path = OBSERVATIONS_DIR) -> Path:
    country = store["country"]
    path = observation_path(country, base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")
    return path


def _key_tuple(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row["series_id"]),
        str(row["period"]),
        str(row.get("transformation", "")),
        str(row["raw_sha256"]),
    )


def find_observation(store: dict[str, Any], key: ObservationKey) -> dict[str, Any] | None:
    target = (key.series_id, key.period, key.transformation, key.raw_sha256)
    for row in store.get("observations", []):
        if _key_tuple(row) == target:
            return row
    return None


def latest_for_period(
    store: dict[str, Any], series_id: str, period: str, transformation: str
) -> dict[str, Any] | None:
    matches = [
        row
        for row in store.get("observations", [])
        if row.get("series_id") == series_id
        and row.get("period") == period
        and row.get("transformation", "") == transformation
    ]
    if not matches:
        return None
    return sorted(matches, key=lambda r: r.get("retrieved_at", ""))[-1]


@dataclass
class AppendResult:
    appended: bool
    duplicate: bool
    observation: dict[str, Any] | None = None


def append_observation(
    store: dict[str, Any],
    *,
    series_id: str,
    period: str,
    transformation: str,
    value: float,
    raw_sha256: str,
    retrieved_at: str,
    revision_status: str | None = None,
    source_url: str | None = None,
    prior: float | None = None,
) -> AppendResult:
    key = ObservationKey(series_id, period, transformation, raw_sha256)
    if find_observation(store, key):
        return AppendResult(appended=False, duplicate=True)

    row = {
        "series_id": series_id,
        "period": period,
        "transformation": transformation,
        "value": value,
        "raw_sha256": raw_sha256,
        "retrieved_at": retrieved_at,
        "revision_status": revision_status,
        "source_url": source_url,
        "prior": prior,
    }
    store.setdefault("observations", []).append(row)
    return AppendResult(appended=True, duplicate=False, observation=row)
