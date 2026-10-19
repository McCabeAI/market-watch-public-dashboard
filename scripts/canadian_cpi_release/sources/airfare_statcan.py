"""StatCan WDS acquisition for Canadian CPI air transportation (separate fixture)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from scripts.canadian_cpi_release.contract import (
    STATCAN_WDS_DATA_URL,
    STATCAN_WDS_INFO_URL,
    Observation,
    Snapshot,
)
from scripts.canadian_cpi_release.ex_energy_interfaces import (
    AIRFARE_INDEX_SPEC,
    AIRFARE_WEIGHT_SPEC,
    FORBIDDEN_ACTUAL_PERIOD,
)
from scripts.canadian_cpi_release.sources.cache import SourceError, fetch_bytes

STATCAN_CUBE_URL = "https://www150.statcan.gc.ca/t1/wds/rest/getCubeMetadata"
AIRFARE_INDEX_LATEST_N = 420
AIRFARE_WEIGHT_LATEST_N = 20
AIRFARE_FIXTURE_SCHEMA = "canadian_cpi_airfare_snapshot_v1"


@dataclass
class AirfareRawBatch:
    filename: str
    url: str
    body: bytes
    vector_id: int
    role: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()


def _title_matches_airfare_index(series_title_en: str) -> bool:
    title = (series_title_en or "").strip()
    if not title:
        return False
    lower = title.lower()
    return "air transportation" in lower and "canada" in lower


def _title_matches_airfare_weight(series_title_en: str) -> bool:
    title = (series_title_en or "").strip()
    if not title:
        return False
    lower = title.lower()
    return "air transportation" in lower and "weight at basket link month prices" in lower


def verify_series_titles_from_info_payload(payload: list[Any]) -> None:
    """Raise SourceError when StatCan series info does not match locked airfare specs."""
    if not isinstance(payload, list):
        raise SourceError("airfare_title_invalid_json", "series info response not a list")
    expected: dict[tuple[int, str], str] = {
        (int(AIRFARE_INDEX_SPEC["vector_id"]), str(AIRFARE_INDEX_SPEC["coordinate"])): "index",
        (int(AIRFARE_WEIGHT_SPEC["vector_id"]), str(AIRFARE_WEIGHT_SPEC["coordinate"])): "weight",
    }
    seen: set[tuple[int, str]] = set()
    for item in payload:
        if not isinstance(item, dict) or item.get("status") != "SUCCESS":
            raise SourceError("airfare_title_failed", str(item))
        obj = item.get("object") or {}
        vid = int(obj.get("vectorId"))
        coordinate = str(obj.get("coordinate") or "")
        key = (vid, coordinate)
        role = expected.get(key)
        if role is None:
            raise SourceError("airfare_title_unexpected_vector", f"{vid}:{coordinate}")
        seen.add(key)
        title_en = str(obj.get("SeriesTitleEn") or "")
        if role == "index":
            if int(AIRFARE_INDEX_SPEC["vector_id"]) != vid:
                raise SourceError("airfare_title_vector_mismatch", "index")
            if not _title_matches_airfare_index(title_en):
                raise SourceError("airfare_title_mismatch", f"index: {title_en}")
        else:
            if int(AIRFARE_WEIGHT_SPEC["vector_id"]) != vid:
                raise SourceError("airfare_title_vector_mismatch", "weight")
            if not _title_matches_airfare_weight(title_en):
                raise SourceError("airfare_title_mismatch", f"weight: {title_en}")
    if seen != set(expected):
        raise SourceError("airfare_title_incomplete", str(sorted(expected - seen)))


def _period_from_ref(ref_per: str) -> str | None:
    text = (ref_per or "").strip()
    if len(text) >= 7 and text[4] == "-":
        return text[:7]
    return None


def _parse_wds_blocks(payload: list[Any]) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = {}
    for block in payload:
        if not isinstance(block, dict):
            continue
        obj = block.get("object") if isinstance(block.get("object"), dict) else block
        vid = obj.get("vectorId")
        if vid is None:
            continue
        points = obj.get("vectorDataPoint") or obj.get("vectorDataPoints") or []
        out[int(vid)] = [p for p in points if isinstance(p, dict)]
    return out


def _fetch_cube_end_date(opener: Callable[..., Any], sleeper: Callable[[float], None] | None) -> str:
    body = json.dumps([{"productId": int(AIRFARE_INDEX_SPEC["table_pid"])}]).encode("utf-8")
    raw = fetch_bytes(opener, STATCAN_CUBE_URL, data=body, sleeper=sleeper)
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, list) or not payload:
        raise SourceError("airfare_cube_invalid", "empty cube metadata")
    item = payload[0]
    if not isinstance(item, dict) or item.get("status") != "SUCCESS":
        raise SourceError("airfare_cube_failed", str(item))
    obj = item.get("object") or {}
    end = str(obj.get("cubeEndDate") or "")
    if not end:
        raise SourceError("airfare_cube_missing_end", str(obj))
    return end


def _observations_from_points(
    *,
    canonical_id: str,
    points: list[dict[str, Any]],
    retrieved_at: str,
    source_hash: str,
    units: str,
    seasonal_status: str,
    vector_id: int,
    table_pid: int,
) -> list[Observation]:
    rows: list[Observation] = []
    for point in points:
        period = _period_from_ref(str(point.get("refPer") or ""))
        if not period:
            continue
        try:
            value = float(point.get("value"))
        except (TypeError, ValueError):
            continue
        published_at = point.get("releaseTime")
        published_text = str(published_at) if published_at not in (None, "") else None
        rows.append(
            Observation(
                canonical_id=canonical_id,
                period=period,
                value=value,
                published_at=published_text,
                retrieved_at=retrieved_at,
                source_hash=source_hash,
                units=units,
                seasonal_status=seasonal_status,
                source_url=STATCAN_WDS_DATA_URL,
                vector_id=vector_id,
                table_pid=table_pid,
            )
        )
    return rows


def collect_airfare_statcan(
    *,
    opener: Callable[..., Any],
    sleeper: Callable[[float], None] | None,
    retrieved_at: str,
) -> tuple[list[Observation], list[AirfareRawBatch], dict[str, Any]]:
    """Verify vectors, fetch history, and apply September-2026 fail-closed gate."""
    blockers: list[str] = []
    notes: list[str] = []

    info_body = json.dumps(
        [
            {
                "productId": int(AIRFARE_INDEX_SPEC["table_pid"]),
                "coordinate": str(AIRFARE_INDEX_SPEC["coordinate"]),
            },
            {
                "productId": int(AIRFARE_WEIGHT_SPEC["table_pid"]),
                "coordinate": str(AIRFARE_WEIGHT_SPEC["coordinate"]),
            },
        ]
    ).encode("utf-8")
    info_raw = fetch_bytes(opener, STATCAN_WDS_INFO_URL, data=info_body, sleeper=sleeper)
    info_payload = json.loads(info_raw.decode("utf-8"))
    verify_series_titles_from_info_payload(info_payload)

    cube_end = _fetch_cube_end_date(opener, sleeper)
    cube_end_period = cube_end[:7] if len(cube_end) >= 7 else cube_end

    raw_batches: list[AirfareRawBatch] = []
    all_obs: list[Observation] = []

    for spec, latest_n, role, filename in (
        (AIRFARE_INDEX_SPEC, AIRFARE_INDEX_LATEST_N, "index", "airfare_index.json"),
        (AIRFARE_WEIGHT_SPEC, AIRFARE_WEIGHT_LATEST_N, "weight", "airfare_weight.json"),
    ):
        vid = int(spec["vector_id"])
        body = json.dumps([{"vectorId": vid, "latestN": int(latest_n)}]).encode("utf-8")
        raw = fetch_bytes(opener, STATCAN_WDS_DATA_URL, data=body, sleeper=sleeper)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, list):
            raise SourceError("airfare_invalid_json", role)
        parsed = _parse_wds_blocks(payload)
        if vid not in parsed:
            raise SourceError("airfare_missing_vector", str(vid))
        batch = AirfareRawBatch(filename=filename, url=STATCAN_WDS_DATA_URL, body=raw, vector_id=vid, role=role)
        raw_batches.append(batch)
        points = parsed[vid]
        filtered_points: list[dict[str, Any]] = []
        for point in points:
            period = _period_from_ref(str(point.get("refPer") or ""))
            if period is None:
                continue
            if period >= FORBIDDEN_ACTUAL_PERIOD:
                blockers.append("september_actual_present")
                continue
            filtered_points.append(point)
        all_obs.extend(
            _observations_from_points(
                canonical_id=str(spec["canonical_id"]),
                points=filtered_points,
                retrieved_at=retrieved_at,
                source_hash=batch.sha256,
                units=str(spec["units"]),
                seasonal_status="weight" if role == "weight" else str(spec.get("seasonal_status", "NSA")),
                vector_id=vid,
                table_pid=int(spec["table_pid"]),
            )
        )

    if cube_end_period < FORBIDDEN_ACTUAL_PERIOD:
        notes.append(f"StatCan cubeEndDate {cube_end} precedes {FORBIDDEN_ACTUAL_PERIOD}; no September actual expected.")
    else:
        notes.append(
            f"StatCan cubeEndDate {cube_end} is on or after {FORBIDDEN_ACTUAL_PERIOD}; "
            "September points are excluded fail-closed."
        )

    provenance = {
        "index_vector_id": int(AIRFARE_INDEX_SPEC["vector_id"]),
        "weight_vector_id": int(AIRFARE_WEIGHT_SPEC["vector_id"]),
        "index_coordinate": str(AIRFARE_INDEX_SPEC["coordinate"]),
        "weight_coordinate": str(AIRFARE_WEIGHT_SPEC["coordinate"]),
        "cube_end_date": cube_end,
        "info_sha256": hashlib.sha256(info_raw).hexdigest(),
    }
    return all_obs, raw_batches, {"blockers": blockers, "notes": notes, "provenance": provenance, "info_raw": info_raw}


def write_airfare_fixture(
    dest_dir: Path,
    *,
    observations: list[Observation],
    raw_batches: list[AirfareRawBatch],
    retrieved_at: str,
    notes: list[str],
    provenance: dict[str, Any],
    blockers: list[str],
) -> Snapshot:
    dest_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = dest_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    source_records: list[dict[str, Any]] = []
    for batch in raw_batches:
        path = f"raw/{batch.filename}"
        (dest_dir / path).write_bytes(batch.body)
        source_records.append(
            {
                "url": batch.url,
                "sha256": batch.sha256,
                "bytes": len(batch.body),
                "vector_id": batch.vector_id,
                "role": batch.role,
                "path": path,
            }
        )

    sorted_obs = sorted(
        observations,
        key=lambda obs: (obs.canonical_id, obs.period, obs.published_at or "", obs.vector_id or 0),
    )
    snapshot = Snapshot(
        schema_version=AIRFARE_FIXTURE_SCHEMA,
        retrieved_at=retrieved_at,
        observations=sorted_obs,
        source_records=source_records,
        notes=list(notes),
    )
    snap_bytes = json.dumps(snapshot.to_json(), indent=2, sort_keys=True).encode("utf-8")
    (dest_dir / "snapshot.json").write_bytes(snap_bytes)

    counts = {}
    for obs in sorted_obs:
        counts[obs.canonical_id] = counts.get(obs.canonical_id, 0) + 1
    manifest = {
        "schema_version": AIRFARE_FIXTURE_SCHEMA,
        "retrieved_at": retrieved_at,
        "snapshot_path": "snapshot.json",
        "snapshot_sha256": hashlib.sha256(snap_bytes).hexdigest(),
        "observation_count": len(sorted_obs),
        "observation_counts_by_canonical_id": counts,
        "source_records": source_records,
        "provenance": provenance,
        "blockers": blockers,
        "notes": notes,
    }
    (dest_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return snapshot


def verify_and_fetch_airfare(
    dest_dir: Path,
    retrieved_at: str,
    *,
    opener: Callable[..., Any] | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Live verify + fetch; writes fixture unless hard verification fails."""
    from scripts.canadian_cpi_release.sources.cache import default_opener

    effective_opener = opener or default_opener
    observations, raw_batches, meta = collect_airfare_statcan(
        opener=effective_opener,
        sleeper=sleeper,
        retrieved_at=retrieved_at,
    )
    blockers = list(meta["blockers"])
    if "september_actual_present" in blockers:
        # Still write fixture without forbidden points; caller must not use September actual.
        pass
    snapshot = write_airfare_fixture(
        dest_dir,
        observations=observations,
        raw_batches=raw_batches,
        retrieved_at=retrieved_at,
        notes=list(meta["notes"]),
        provenance=dict(meta["provenance"]),
        blockers=blockers,
    )
    return {
        "snapshot": snapshot,
        "blockers": blockers,
        "provenance": meta["provenance"],
        "notes": meta["notes"],
    }


def load_airfare_snapshot(path: Path) -> Snapshot:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return Snapshot.from_json(payload)
