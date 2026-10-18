"""Bounded live acquisition and frozen snapshot I/O."""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from scripts.canadian_cpi_release import SCHEMA_VERSION
from scripts.canadian_cpi_release.contract import Snapshot
from scripts.canadian_cpi_release.sources.cache import default_opener
from scripts.canadian_cpi_release.sources.nrcan import collect_nrcan
from scripts.canadian_cpi_release.sources.statcan import collect_statcan

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "pre_2026-10-19"

_PENDING_RAW: dict[str, bytes] = {}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _default_sleeper(seconds: float) -> None:
    time.sleep(seconds)


def _sort_observations(observations: list) -> list:
    return sorted(
        observations,
        key=lambda obs: (obs.canonical_id, obs.period, obs.published_at or "", obs.vector_id or 0),
    )


def fetch_live(
    retrieved_at: str | None = None,
    *,
    opener: Callable[..., Any] | None = None,
    sleeper: Callable[[float], None] | None = None,
    through_period: str = "2026-09",
) -> Snapshot:
    """Bounded official fetch. No silent fake data. Raises SourceError on mandatory failure."""
    effective_opener = opener or default_opener
    effective_sleeper = sleeper or _default_sleeper
    when = retrieved_at or _utc_now_iso()

    statcan_obs, statcan_raw = collect_statcan(
        opener=effective_opener,
        sleeper=effective_sleeper,
        retrieved_at=when,
    )
    nrcan_obs, nrcan_pages, nrcan_notes = collect_nrcan(
        opener=effective_opener,
        sleeper=effective_sleeper,
        retrieved_at=when,
        through_period=through_period,
        require_full_history=False,
    )

    notes = [
        "StatCan table 18-10-0259 (real-time CPI vintages) was not bulk-downloaded; cube coverage "
        "known from this task is reference periods through 2026-03 and releases through 2026-04-20, "
        "so May–August 2026 core vintages are not in that table. Current core indexes are from 18-10-0256.",
    ]
    notes.extend(nrcan_notes)

    source_records: list[dict[str, Any]] = []
    for batch in statcan_raw:
        source_records.append(
            {
                "url": batch.url,
                "sha256": batch.sha256,
                "bytes": len(batch.body),
                "canonical_ids": batch.canonical_ids,
                "path": f"raw/{batch.filename}",
            }
        )
    for page in nrcan_pages:
        source_records.append(
            {
                "url": page.url,
                "sha256": page.sha256,
                "bytes": len(page.body),
                "canonical_ids": [page.canonical_id],
                "path": f"raw/{page.filename}",
            }
        )

    _PENDING_RAW.clear()
    for batch in statcan_raw:
        _PENDING_RAW[f"raw/{batch.filename}"] = batch.body
    for page in nrcan_pages:
        _PENDING_RAW[f"raw/{page.filename}"] = page.body

    observations = _sort_observations(statcan_obs + nrcan_obs)
    return Snapshot(
        schema_version=SCHEMA_VERSION,
        retrieved_at=when,
        observations=observations,
        source_records=source_records,
        notes=notes,
    )


def load_snapshot(path: Path) -> Snapshot:
    """Load snapshot.json. No HTTP."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return Snapshot.from_json(payload)


def save_snapshot(snapshot: Snapshot, directory: Path) -> dict[str, Any]:
    """Write snapshot.json. Return manifest summary."""
    directory.mkdir(parents=True, exist_ok=True)
    raw_dir = directory / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for rel_path, body in _PENDING_RAW.items():
        target = directory / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)

    sorted_obs = _sort_observations(list(snapshot.observations))
    normalized = Snapshot(
        schema_version=snapshot.schema_version,
        retrieved_at=snapshot.retrieved_at,
        observations=sorted_obs,
        source_records=snapshot.source_records,
        notes=list(snapshot.notes),
    )

    snapshot_path = directory / "snapshot.json"
    snapshot_bytes = (json.dumps(normalized.to_json(), indent=2, sort_keys=True) + "\n").encode("utf-8")
    snapshot_path.write_bytes(snapshot_bytes)
    snapshot_sha = hashlib.sha256(snapshot_bytes).hexdigest()

    counts = Counter(obs.canonical_id for obs in sorted_obs)
    manifest = {
        "schema_version": normalized.schema_version,
        "retrieved_at": normalized.retrieved_at,
        "snapshot_path": "snapshot.json",
        "snapshot_sha256": snapshot_sha,
        "observation_count": len(sorted_obs),
        "observation_counts_by_canonical_id": dict(sorted(counts.items())),
        "source_records": normalized.source_records,
        "notes": normalized.notes,
    }
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest
