"""StatCan producer-price and CPI breadth inputs for the Prima bundle."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Callable

from scripts.prima_pressure.contract import (
    CPI_BREADTH_SERIES,
    CPI_MAJOR_IDS,
    PRODUCER_SERIES,
    PRODUCER_STALE_RELEASE_DAYS,
    SECTOR_PPI_GAP,
    STATCAN_WDS_DATA_URL,
)

Opener = Callable[..., bytes]


def _parse_release_date(release_time: str | None) -> date | None:
    if not release_time:
        return None
    try:
        return datetime.fromisoformat(release_time.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(release_time[:10])
        except ValueError:
            return None


def _period_from_ref(ref_per: str) -> str:
    return ref_per[:7] if len(ref_per) >= 7 else ref_per


def fetch_vectors(
    vector_ids: list[int],
    latest_n: int,
    opener: Opener,
) -> dict[int, list[dict[str, Any]]]:
    if not vector_ids:
        return {}
    body = json.dumps([{"vectorId": int(v), "latestN": int(latest_n)} for v in vector_ids]).encode("utf-8")
    try:
        raw = opener(STATCAN_WDS_DATA_URL, data=body)
        payload = json.loads(raw)
    except Exception:
        return {}
    blocks = payload if isinstance(payload, list) else [payload]
    out: dict[int, list[dict[str, Any]]] = {}
    for block in blocks:
        if not isinstance(block, dict):
            continue
        obj = block.get("object") if isinstance(block.get("object"), dict) else block
        vid = obj.get("vectorId")
        if vid is None:
            continue
        points = obj.get("vectorDataPoint") or obj.get("vectorDataPoints") or []
        out[int(vid)] = [p for p in points if isinstance(p, dict)]
    return out


def _mom_from_points(points: list[dict[str, Any]]) -> float | None:
    if len(points) < 2:
        return None
    try:
        latest = float(points[-1]["value"])
        prior = float(points[-2]["value"])
    except (TypeError, ValueError, KeyError):
        return None
    if prior == 0:
        return None
    return latest / prior - 1.0


def build_producer_prices(as_of: date, opener: Opener) -> dict[str, Any]:
    vector_ids = [row["vector_id"] for row in PRODUCER_SERIES]
    by_vector = fetch_vectors(vector_ids, latest_n=2, opener=opener)
    series_out: list[dict[str, Any]] = []
    for row in PRODUCER_SERIES:
        vid = row["vector_id"]
        points_raw = by_vector.get(vid) or []
        points_sorted = sorted(points_raw, key=lambda p: _period_from_ref(str(p.get("refPer", ""))))
        latest = points_sorted[-1] if points_sorted else None
        period = None
        value = None
        release_time = None
        release_date = None
        if latest:
            period = _period_from_ref(str(latest.get("refPer", "")))
            try:
                value = float(latest.get("value"))
            except (TypeError, ValueError):
                value = None
            release_time = latest.get("releaseTime")
            release_date = _parse_release_date(str(release_time) if release_time else None)

        stale = False
        status = "ok"
        if value is None:
            status = "unavailable"
            stale = True
        elif release_date is None or (as_of - release_date).days > PRODUCER_STALE_RELEASE_DAYS:
            status = "stale"
            stale = True

        mom = _mom_from_points(points_sorted) if len(points_sorted) >= 2 else None

        series_out.append(
            {
                **row,
                "period": period,
                "value": value,
                "release_time": release_time,
                "mom": mom,
                "status": status,
                "stale": stale,
                "source_url": STATCAN_WDS_DATA_URL,
            }
        )

    any_ok = any(s["status"] == "ok" for s in series_out)
    any_data = any(s["value"] is not None for s in series_out)
    top_status = "unavailable"
    if any_ok:
        top_status = "ok"
    elif any_data:
        top_status = "partial"

    return {
        "as_of": as_of.isoformat(),
        "status": top_status,
        "sector_ppi": dict(SECTOR_PPI_GAP),
        "series": series_out,
        "source_url": STATCAN_WDS_DATA_URL,
    }


def build_cpi_breadth_inputs(as_of: date, opener: Opener) -> dict[str, Any]:
    vector_ids = [row["vector_id"] for row in CPI_BREADTH_SERIES]
    by_vector = fetch_vectors(vector_ids, latest_n=16, opener=opener)
    series_out: list[dict[str, Any]] = []
    for row in CPI_BREADTH_SERIES:
        vid = row["vector_id"]
        points_raw = by_vector.get(vid) or []
        points_sorted = sorted(points_raw, key=lambda p: _period_from_ref(str(p.get("refPer", ""))))
        points: list[dict[str, Any]] = []
        for pt in points_sorted:
            period = _period_from_ref(str(pt.get("refPer", "")))
            try:
                val = float(pt.get("value"))
            except (TypeError, ValueError):
                continue
            points.append(
                {
                    "period": period,
                    "value": val,
                    "release_time": pt.get("releaseTime"),
                }
            )
        latest_mom = _mom_from_points(points_sorted) if len(points) >= 2 else None
        status = "ok" if points else "unavailable"
        series_out.append({**row, "points": points, "latest_mom": latest_mom, "status": status})

    by_id = {s["series_id"]: s for s in series_out}
    required = list(CPI_MAJOR_IDS) + ["core_trim_index", "core_median_index"]
    with_five = [sid for sid in required if len(by_id.get(sid, {}).get("points") or []) >= 5]
    if len(with_five) == len(required):
        top_status = "ok"
    elif with_five:
        top_status = "partial"
    else:
        top_status = "unavailable"

    return {
        "as_of": as_of.isoformat(),
        "status": top_status,
        "series": series_out,
        "source_url": STATCAN_WDS_DATA_URL,
    }
