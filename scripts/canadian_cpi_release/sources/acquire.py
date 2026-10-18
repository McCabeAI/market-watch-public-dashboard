"""Bounded live acquisition and frozen snapshot I/O."""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from scripts.canadian_cpi_release import SCHEMA_VERSION
from scripts.canadian_cpi_release.contract import Snapshot
from scripts.canadian_cpi_release.sources.cache import SourceError, default_opener
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

    raw_files: dict[str, bytes] = {}
    for batch in statcan_raw:
        raw_files[f"raw/{batch.filename}"] = batch.body
    for page in nrcan_pages:
        raw_files[f"raw/{page.filename}"] = page.body
    _PENDING_RAW.clear()
    _PENDING_RAW.update(raw_files)

    observations = _sort_observations(statcan_obs + nrcan_obs)
    snapshot = Snapshot(
        schema_version=SCHEMA_VERSION,
        retrieved_at=when,
        observations=observations,
        source_records=source_records,
        notes=notes,
    )
    snapshot._raw_files = raw_files
    return snapshot


def load_snapshot(path: Path) -> Snapshot:
    """Load snapshot.json. No HTTP."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return Snapshot.from_json(payload)


def snapshot_canonical_bytes(snapshot: Snapshot) -> bytes:
    """Stable snapshot.json bytes. Raw payloads are not included."""
    sorted_obs = _sort_observations(list(snapshot.observations))
    normalized = Snapshot(
        schema_version=snapshot.schema_version,
        retrieved_at=snapshot.retrieved_at,
        observations=sorted_obs,
        source_records=list(snapshot.source_records),
        notes=list(snapshot.notes),
    )
    return (json.dumps(normalized.to_json(), indent=2, sort_keys=True) + "\n").encode("utf-8")


def _raw_files_for(snapshot: Snapshot) -> dict[str, bytes]:
    attached = getattr(snapshot, "_raw_files", None)
    if isinstance(attached, dict) and attached:
        return {str(key): bytes(value) for key, value in attached.items()}
    if _PENDING_RAW:
        return dict(_PENDING_RAW)
    return {}


def _manifest_for(snapshot: Snapshot, snapshot_sha: str) -> dict[str, Any]:
    counts = Counter(obs.canonical_id for obs in snapshot.observations)
    return {
        "schema_version": snapshot.schema_version,
        "retrieved_at": snapshot.retrieved_at,
        "snapshot_path": "snapshot.json",
        "snapshot_sha256": snapshot_sha,
        "observation_count": len(snapshot.observations),
        "observation_counts_by_canonical_id": dict(sorted(counts.items())),
        "source_records": snapshot.source_records,
        "notes": snapshot.notes,
    }


def _require_raw_files(snapshot: Snapshot, raw_files: dict[str, bytes]) -> None:
    expected = [rec for rec in snapshot.source_records if rec.get("path")]
    if expected and not raw_files:
        raise SourceError("archive_raw_missing", "live snapshot has source records but no raw bytes")
    for rec in expected:
        rel = str(rec["path"])
        body = raw_files.get(rel)
        if body is None:
            raise SourceError("archive_raw_missing", rel)
        digest = hashlib.sha256(body).hexdigest()
        recorded = rec.get("sha256")
        if recorded and digest != recorded:
            raise SourceError("archive_hash_mismatch", rel)
        if rec.get("bytes") is not None and int(rec["bytes"]) != len(body):
            raise SourceError("archive_hash_mismatch", rel)


def _archive_matches(directory: Path, snapshot_bytes: bytes, raw_files: dict[str, bytes]) -> bool:
    snapshot_path = directory / "snapshot.json"
    if not snapshot_path.is_file() or snapshot_path.read_bytes() != snapshot_bytes:
        return False
    for rel, body in raw_files.items():
        target = directory / rel
        if not target.is_file() or target.read_bytes() != body:
            return False
    return True


def save_snapshot(snapshot: Snapshot, directory: Path) -> dict[str, Any]:
    """Write snapshot.json, raw responses, and manifest.json.

    An existing archive with the same snapshot and raw bytes is left unchanged.
    A different existing archive raises SourceError and is not overwritten.
    """
    directory = Path(directory)
    raw_files = _raw_files_for(snapshot)
    _require_raw_files(snapshot, raw_files)
    snapshot_bytes = snapshot_canonical_bytes(snapshot)
    snapshot_sha = hashlib.sha256(snapshot_bytes).hexdigest()
    manifest = _manifest_for(snapshot, snapshot_sha)

    if directory.exists():
        if any(directory.iterdir()):
            if not _archive_matches(directory, snapshot_bytes, raw_files):
                raise SourceError(
                    "archive_conflict",
                    f"refusing to overwrite different inputs in {directory}",
                )
            manifest_path = directory / "manifest.json"
            if not manifest_path.is_file():
                manifest_path.write_text(
                    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            return manifest
        directory.rmdir()

    parent = directory.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = parent / f".{directory.name}.partial"
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    try:
        for rel_path, body in raw_files.items():
            target = temporary / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        (temporary / "snapshot.json").write_bytes(snapshot_bytes)
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.rename(directory)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return manifest
