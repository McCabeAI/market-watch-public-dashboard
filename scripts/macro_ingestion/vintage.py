"""Append-only macro observation store."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.macro_freshness import values_close

ROOT = Path(__file__).resolve().parents[2]
OBSERVATIONS_DIR = ROOT / "data/macro_ingestion/observations"

_ALIAS_CAP = 8


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


def latest_period_in_store(
    store: dict[str, Any], series_id: str, transformation: str
) -> str | None:
    periods = [
        str(row["period"])
        for row in store.get("observations", [])
        if row.get("series_id") == series_id and row.get("transformation", "") == transformation
    ]
    if not periods:
        return None
    return max(periods)


def _record_sha_alias(row: dict[str, Any], raw_sha256: str) -> None:
    primary = str(row.get("raw_sha256", ""))
    if raw_sha256 == primary:
        return
    aliases = list(row.get("raw_sha256_aliases") or [])
    seen = {primary, *aliases}
    if raw_sha256 in seen:
        return
    aliases.append(raw_sha256)
    row["raw_sha256_aliases"] = aliases[-_ALIAS_CAP:]


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
    release_date: str | None = None,
    vintage: str | None = None,
    revision_status: str | None = None,
    source_url: str | None = None,
    prior: float | None = None,
) -> AppendResult:
    key = ObservationKey(series_id, period, transformation, raw_sha256)
    if find_observation(store, key):
        prior_row = latest_for_period(store, series_id, period, transformation)
        if prior_row is not None:
            _record_sha_alias(prior_row, raw_sha256)
        return AppendResult(appended=False, duplicate=True, observation=prior_row)

    prior_row = latest_for_period(store, series_id, period, transformation)
    if prior_row is not None and values_close(float(prior_row["value"]), value):
        _record_sha_alias(prior_row, raw_sha256)
        return AppendResult(appended=False, duplicate=True, observation=prior_row)

    earliest_release = release_date
    latest_release = release_date
    if prior_row is not None:
        earliest_release = (
            prior_row.get("earliest_release_vintage")
            or prior_row.get("release_date")
            or release_date
        )
        latest_release = release_date

    row = {
        "series_id": series_id,
        "period": period,
        "transformation": transformation,
        "value": value,
        "raw_sha256": raw_sha256,
        "retrieved_at": retrieved_at,
        "release_date": release_date,
        "vintage": vintage,
        "earliest_release_vintage": earliest_release,
        "latest_release_vintage": latest_release,
        "revision_status": revision_status,
        "source_url": source_url,
        "prior": prior,
    }
    store.setdefault("observations", []).append(row)
    return AppendResult(appended=True, duplicate=False, observation=row)
