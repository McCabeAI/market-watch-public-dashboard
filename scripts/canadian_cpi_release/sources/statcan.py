"""StatCan WDS vector acquisition for Canadian CPI release."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable

from scripts.canadian_cpi_release.contract import (
    HISTORY_LATEST_N,
    SERIES,
    STATCAN_WDS_DATA_URL,
    STATCAN_WDS_INFO_URL,
    WEIGHT_LATEST_N,
    WEIGHT_TABLE_PID,
    Observation,
    SeriesSpec,
)
from scripts.canadian_cpi_release.sources.cache import SourceError
from scripts.canadian_cpi_release.sources.cache import fetch_bytes

BATCH_SIZE = 8


@dataclass
class StatCanRawBatch:
    filename: str
    url: str
    body: bytes
    vector_ids: list[int]
    canonical_ids: list[str]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()


def _chunks(items: list[int], size: int) -> list[list[int]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


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


def _period_from_ref(ref_per: str) -> str | None:
    text = (ref_per or "").strip()
    if len(text) >= 7 and text[4] == "-":
        return text[:7]
    return None


def _title_matches(expected: str, series_title_en: str) -> bool:
    title = (series_title_en or "").strip()
    if not title:
        return False
    if title == expected:
        return True
    if ";" in title:
        tail = title.split(";")[-1].strip()
        if tail == expected:
            return True
    return expected.lower() in title.lower()


def _verify_titles(
    opener: Callable[..., Any],
    specs: list[SeriesSpec],
    *,
    sleeper: Callable[[float], None] | None,
    use_weight: bool,
) -> None:
    requests: list[dict[str, Any]] = []
    for spec in specs:
        if use_weight:
            if spec.weight_vector_id is None or spec.weight_coordinate is None:
                continue
            requests.append({"productId": WEIGHT_TABLE_PID, "coordinate": spec.weight_coordinate})
        else:
            if spec.vector_id is None or spec.table_pid is None or spec.coordinate is None:
                continue
            requests.append({"productId": spec.table_pid, "coordinate": spec.coordinate})

    for slice_req in _chunks(requests, BATCH_SIZE):
        if not slice_req:
            continue
        body = json.dumps(slice_req).encode("utf-8")
        raw = fetch_bytes(
            opener,
            STATCAN_WDS_INFO_URL,
            data=body,
            sleeper=sleeper,
        )
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, list):
            raise SourceError("statcan_title_invalid_json", "series info response not a list")
        for item in payload:
            if not isinstance(item, dict) or item.get("status") != "SUCCESS":
                raise SourceError("statcan_title_failed", str(item))
            obj = item.get("object") or {}
            vid = int(obj.get("vectorId"))
            coordinate = str(obj.get("coordinate") or "")
            title_en = str(obj.get("SeriesTitleEn") or "")
            matched_spec: SeriesSpec | None = None
            for spec in specs:
                if use_weight:
                    if spec.weight_vector_id == vid and spec.weight_coordinate == coordinate:
                        matched_spec = spec
                        break
                elif spec.vector_id == vid and spec.coordinate == coordinate:
                    matched_spec = spec
                    break
            if matched_spec is None:
                raise SourceError("statcan_title_unexpected_vector", str(vid))
            expected_vid = matched_spec.weight_vector_id if use_weight else matched_spec.vector_id
            if expected_vid != vid:
                raise SourceError("statcan_title_vector_mismatch", matched_spec.canonical_id)
            if not _title_matches(matched_spec.title, title_en):
                raise SourceError(
                    "statcan_title_mismatch",
                    f"{matched_spec.canonical_id}: expected '{matched_spec.title}' in '{title_en}'",
                )


def _fetch_vector_batches(
    vector_ids: list[int],
    latest_n: int,
    *,
    opener: Callable[..., Any],
    sleeper: Callable[[float], None] | None,
    batch_prefix: str,
) -> tuple[dict[int, list[dict[str, Any]]], list[StatCanRawBatch]]:
    if not vector_ids:
        return {}, []
    ordered = list(dict.fromkeys(vector_ids))
    all_points: dict[int, list[dict[str, Any]]] = {}
    raw_batches: list[StatCanRawBatch] = []
    for batch_index, batch_ids in enumerate(_chunks(ordered, BATCH_SIZE)):
        body = json.dumps([{"vectorId": int(v), "latestN": int(latest_n)} for v in batch_ids]).encode("utf-8")
        raw = fetch_bytes(opener, STATCAN_WDS_DATA_URL, data=body, sleeper=sleeper)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, list):
            raise SourceError("statcan_invalid_json", f"batch {batch_index}")
        parsed = _parse_wds_blocks(payload)
        for vid in batch_ids:
            if vid not in parsed:
                raise SourceError("statcan_missing_vector", str(vid))
        unexpected = set(parsed) - set(batch_ids)
        if unexpected:
            raise SourceError("statcan_unexpected_vector", ",".join(str(v) for v in sorted(unexpected)))
        for vid, points in parsed.items():
            all_points[vid] = points
        filename = f"{batch_prefix}_{batch_index}.json"
        raw_batches.append(
            StatCanRawBatch(
                filename=filename,
                url=STATCAN_WDS_DATA_URL,
                body=raw,
                vector_ids=batch_ids,
                canonical_ids=[],
            )
        )
    return all_points, raw_batches


def _observations_from_points(
    spec: SeriesSpec,
    points: list[dict[str, Any]],
    *,
    retrieved_at: str,
    source_hash: str,
    source_url: str,
    canonical_id: str,
    units: str,
    seasonal_status: str,
    vector_id: int | None,
    table_pid: int | None,
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
                source_url=source_url,
                vector_id=vector_id,
                table_pid=table_pid,
            )
        )
    return rows


def collect_statcan(
    *,
    opener: Callable[..., Any],
    sleeper: Callable[[float], None] | None,
    retrieved_at: str,
) -> tuple[list[Observation], list[StatCanRawBatch]]:
    history_specs = [spec for spec in SERIES if spec.source == "statcan_wds" and spec.vector_id is not None]
    weight_specs = [spec for spec in SERIES if spec.source == "statcan_wds" and spec.weight_vector_id is not None]

    _verify_titles(opener, history_specs, sleeper=sleeper, use_weight=False)
    _verify_titles(opener, weight_specs, sleeper=sleeper, use_weight=True)

    history_ids = [int(spec.vector_id) for spec in history_specs]
    weight_ids = [int(spec.weight_vector_id) for spec in weight_specs]

    vid_to_spec: dict[int, SeriesSpec] = {int(spec.vector_id): spec for spec in history_specs}
    wvid_to_spec: dict[int, SeriesSpec] = {int(spec.weight_vector_id): spec for spec in weight_specs}

    history_points, history_raw = _fetch_vector_batches(
        history_ids,
        HISTORY_LATEST_N,
        opener=opener,
        sleeper=sleeper,
        batch_prefix="statcan",
    )
    weight_points, weight_raw = _fetch_vector_batches(
        weight_ids,
        WEIGHT_LATEST_N,
        opener=opener,
        sleeper=sleeper,
        batch_prefix="statcan_weight",
    )

    hash_by_batch: dict[str, str] = {batch.filename: batch.sha256 for batch in history_raw + weight_raw}

    for batch in history_raw:
        batch.canonical_ids = sorted(
            {vid_to_spec[vid].canonical_id for vid in batch.vector_ids if vid in vid_to_spec}
        )
    for batch in weight_raw:
        batch.canonical_ids = sorted(
            {f"{wvid_to_spec[vid].canonical_id}__weight" for vid in batch.vector_ids if vid in wvid_to_spec}
        )

    observations: list[Observation] = []
    for vid, spec in vid_to_spec.items():
        points = history_points.get(vid) or []
        if not points and spec.mandatory:
            raise SourceError("statcan_empty_series", spec.canonical_id)
        batch_hash = _hash_for_vector(vid, history_raw, hash_by_batch)
        observations.extend(
            _observations_from_points(
                spec,
                points,
                retrieved_at=retrieved_at,
                source_hash=batch_hash,
                source_url=STATCAN_WDS_DATA_URL,
                canonical_id=spec.canonical_id,
                units=spec.units,
                seasonal_status=spec.seasonal_status,
                vector_id=spec.vector_id,
                table_pid=spec.table_pid,
            )
        )

    for vid, spec in wvid_to_spec.items():
        points = weight_points.get(vid) or []
        if not points and spec.mandatory:
            raise SourceError("statcan_empty_weight_series", f"{spec.canonical_id}__weight")
        batch_hash = _hash_for_vector(vid, weight_raw, hash_by_batch)
        observations.extend(
            _observations_from_points(
                spec,
                points,
                retrieved_at=retrieved_at,
                source_hash=batch_hash,
                source_url=STATCAN_WDS_DATA_URL,
                canonical_id=f"{spec.canonical_id}__weight",
                units="basket_weight_percent",
                seasonal_status="weight",
                vector_id=spec.weight_vector_id,
                table_pid=WEIGHT_TABLE_PID,
            )
        )

    return observations, history_raw + weight_raw


def _hash_for_vector(vector_id: int, batches: list[StatCanRawBatch], hash_by_batch: dict[str, str]) -> str:
    for batch in batches:
        if vector_id in batch.vector_ids:
            return hash_by_batch[batch.filename]
    return hashlib.sha256(b"").hexdigest()
