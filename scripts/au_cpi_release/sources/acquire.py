"""Build and load an Australian CPI snapshot.

``visible`` keeps observations whose ``published_at`` is at or before ``as_of``.
A snapshot retrieved at or after the target release cannot feed a pre-release
view: later seasonal-factor revisions are already inside the file.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.au_cpi_release import SCHEMA_VERSION
from scripts.au_cpi_release.calendar import REPO_ROOT, published_on_or_before, parse_timestamp
from scripts.au_cpi_release.contract import Observation, Snapshot, sort_observations
from scripts.au_cpi_release.sources.abs_sdmx import fetch_abs
from scripts.au_cpi_release.sources.abs_workbook import attempt_wayback_workbooks, load_july_workbooks
from scripts.au_cpi_release.sources.http import SourceError
from scripts.au_cpi_release.sources.rba import fetch_rba

_SOURCE_FIELDS = ("bytes", "dataflow", "http_status", "retrieved_at", "sha256", "source_id", "url")


class InformationSetError(Exception):
    """As-of or pre-release guard refused the snapshot."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def snapshot_canonical_bytes(snapshot: Snapshot) -> bytes:
    """Stable snapshot.json bytes. Raw payloads are not embedded."""
    ordered = Snapshot(
        observations=sort_observations(snapshot.observations),
        source_records=tuple(sorted(snapshot.source_records, key=lambda rec: str(rec.get("source_id") or ""))),
        retrieved_at=snapshot.retrieved_at,
        notes=snapshot.notes,
        schema_version=snapshot.schema_version,
    )
    payload = ordered.to_json()
    return (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def snapshot_sha256(snapshot: Snapshot) -> str:
    return hashlib.sha256(snapshot_canonical_bytes(snapshot)).hexdigest()


def _merge_observations(groups: list[list[Observation]]) -> tuple[Observation, ...]:
    seen: dict[tuple[str, str, str, str], Observation] = {}
    for group in groups:
        for obs in group:
            identity = (obs.canonical_id, obs.period, obs.vintage, obs.source_id)
            seen.setdefault(identity, obs)
    return sort_observations(seen.values())


def build_snapshot(
    *,
    wayback: bool = True,
    wayback_budget_s: float = 180.0,
) -> tuple[Snapshot, dict[str, bytes]]:
    """Live official fetch. ``retrieved_at`` is the real UTC wall clock after the pulls return."""
    notes = [
        "ABS Data API rows are the latest vintage at retrieved_at. published_at is the "
        "calendar release time of each reference period, not a revision timestamp. "
        "Back-cast months 2024-04..2025-09 use the 26 November 2025 first publication.",
        "CPI_M (discontinued Monthly CPI Indicator, ABS,CPI_M,1.2.0) was not fetched "
        "and must not be used as complete-monthly history.",
        "In-repo July 2026 workbooks and the RBA G1 file are single vintages: every row "
        "from those files uses that file's publication time as published_at.",
    ]
    abs_obs, abs_records, raw, abs_notes = fetch_abs()
    notes.extend(abs_notes)
    rba_obs, rba_record, rba_body, rba_notes = fetch_rba()
    notes.extend(rba_notes)
    raw["raw/rba_g1.csv"] = rba_body
    wb_obs, wb_records, wb_notes = load_july_workbooks(retrieved_at=utc_now_iso())
    notes.extend(wb_notes)
    groups = [abs_obs, rba_obs, wb_obs]
    records = list(abs_records) + [rba_record] + list(wb_records)
    if wayback:
        wb_way_obs, wb_way_records, wb_way_raw, wb_way_notes = attempt_wayback_workbooks(
            budget_s=wayback_budget_s
        )
        notes.extend(wb_way_notes)
        groups.append(wb_way_obs)
        records.extend(wb_way_records)
        raw.update(wb_way_raw)
    else:
        notes.append("wayback workbook attempt was disabled for this snapshot")

    retrieved_at = utc_now_iso()
    observations = _merge_observations(groups)
    headline_periods = [
        obs.period
        for obs in observations
        if obs.canonical_id == "headline_nsa_index" and obs.vintage == "abs_api"
    ]
    if headline_periods:
        notes.append("latest_abs_api_headline_nsa_index_period=" + max(headline_periods))
    snapshot = Snapshot(
        observations=observations,
        source_records=tuple(sorted(records, key=lambda rec: str(rec.get("source_id") or ""))),
        retrieved_at=retrieved_at,
        notes=tuple(notes),
        schema_version=SCHEMA_VERSION,
    )
    return snapshot, raw


def resolve_source_path(snapshot_dir: Path, record: dict[str, object]) -> Path:
    relative = record.get("path")
    if relative:
        return snapshot_dir / str(relative)
    repo_path = record.get("repo_path")
    if repo_path:
        return REPO_ROOT / str(repo_path)
    raise SourceError("archive_raw_missing", str(record.get("source_id") or "source"))


def verify_snapshot_raw(snapshot: Snapshot, snapshot_dir: Path) -> None:
    """Re-hash every source file. Missing files and mismatches fail closed."""
    if not snapshot.source_records:
        raise SourceError("archive_raw_missing", "snapshot has no source records")
    for record in snapshot.source_records:
        for field in _SOURCE_FIELDS:
            if field not in record:
                raise SourceError("archive_raw_missing", f"{record.get('source_id')} missing {field}")
        path = resolve_source_path(snapshot_dir, record)
        if not path.is_file():
            raise SourceError("archive_raw_missing", str(path))
        body = path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if digest != record.get("sha256"):
            raise SourceError("archive_hash_mismatch", f"{path} sha256 {digest}")
        recorded_bytes = record.get("bytes")
        if recorded_bytes is not None and int(recorded_bytes) != len(body):
            raise SourceError("archive_hash_mismatch", f"{path} byte length")


def load_snapshot(path: Path) -> Snapshot:
    """Load snapshot.json and re-verify raw hashes. No HTTP."""
    snapshot_path = Path(path)
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot = Snapshot.from_json(payload)
    verify_snapshot_raw(snapshot, snapshot_path.parent)
    return snapshot


def visible(snapshot: Snapshot, as_of: str) -> tuple[Observation, ...]:
    """Observations whose publication time is at or before ``as_of``."""
    return tuple(obs for obs in snapshot.observations if published_on_or_before(obs.published_at, as_of))


def require_pre_release_view(snapshot: Snapshot, release_time: str) -> None:
    """Refuse when this snapshot was retrieved at or after the target release."""
    retrieved = parse_timestamp(snapshot.retrieved_at, date_only="start")
    release = parse_timestamp(release_time, date_only="start")
    if retrieved >= release:
        raise InformationSetError(
            "snapshot_retrieved_after_release",
            f"retrieved_at {snapshot.retrieved_at} >= release {release_time}",
        )
