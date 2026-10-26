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
    SECTOR_PPI_FREQUENCY_CODE,
    SECTOR_PPI_LATEST_N,
    SECTOR_PPI_PRODUCT_ID,
    SECTOR_PPI_QUARTER_START_MONTHS,
    SECTOR_PPI_REVISION_QUARTERS,
    SECTOR_PPI_SERIES,
    SECTOR_PPI_STALE_RELEASE_DAYS,
    STATCAN_WDS_DATA_URL,
    sector_ppi_unavailable,
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
    # Monthly IPPI/RMPI stay on the pre-existing latest-two-points read.
    # Quarterly sector PIT filtering is separate and does not change these prints.
    vector_ids = [row["vector_id"] for row in PRODUCER_SERIES]
    by_vector = fetch_vectors(vector_ids, latest_n=2, opener=opener)
    series_out: list[dict[str, Any]] = []
    for row in PRODUCER_SERIES:
        vid = row["vector_id"]
        points_raw = by_vector.get(vid) or []
        points_sorted = sorted(points_raw, key=lambda p: _period_from_ref(str(p.get("refPer", ""))))
        latest = points_sorted[-1] if points_sorted else None
        prior_pt = points_sorted[-2] if len(points_sorted) >= 2 else None
        period = None
        value = None
        prior_period = None
        prior_value = None
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
        if prior_pt:
            prior_period = _period_from_ref(str(prior_pt.get("refPer", "")))
            try:
                prior_value = float(prior_pt.get("value"))
            except (TypeError, ValueError):
                prior_value = None

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
                "prior_period": prior_period,
                "prior_value": prior_value,
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
        "sector_ppi": build_sector_ppi_layer(as_of, opener),
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


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ref_year_month(ref_per: str) -> tuple[int, int] | None:
    text = str(ref_per or "")
    if len(text) < 7:
        return None
    try:
        year = int(text[:4])
        month = int(text[5:7])
    except ValueError:
        return None
    if month < 1 or month > 12:
        return None
    return year, month


def _quarter_period(year: int, month: int) -> str | None:
    if month not in SECTOR_PPI_QUARTER_START_MONTHS:
        return None
    quarter = SECTOR_PPI_QUARTER_START_MONTHS.index(month) + 1
    return f"{year:04d}-Q{quarter}"


def _months_between(start: tuple[int, int], end: tuple[int, int]) -> int:
    return (end[0] * 12 + end[1]) - (start[0] * 12 + start[1])


def _fetch_statcan_blocks(
    vector_ids: list[int],
    latest_n: int,
    opener: Opener,
) -> tuple[list[dict[str, Any]], str | None]:
    if not vector_ids:
        return [], "no_vectors_requested"
    body = json.dumps(
        [{"vectorId": int(v), "latestN": int(latest_n)} for v in vector_ids]
    ).encode("utf-8")
    try:
        raw = opener(STATCAN_WDS_DATA_URL, data=body)
        payload = json.loads(raw)
    except Exception as exc:
        detail = str(exc).strip().replace("\n", " ")[:180]
        return [], f"statcan_wds_fetch_failed:{type(exc).__name__}:{detail}"
    if isinstance(payload, dict) and payload.get("message") and "object" not in payload:
        return [], f"statcan_wds_error:{str(payload.get('message'))[:180]}"
    blocks = payload if isinstance(payload, list) else [payload]
    out = [block for block in blocks if isinstance(block, dict)]
    if not out:
        return [], "statcan_wds_empty_response"
    return out, None


def _block_object(block: dict[str, Any]) -> dict[str, Any] | None:
    status = block.get("status")
    if status not in (None, "SUCCESS"):
        return None
    obj = block.get("object") if isinstance(block.get("object"), dict) else block
    if not isinstance(obj, dict):
        return None
    return obj


def _objects_by_vector(blocks: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    found: dict[int, dict[str, Any]] = {}
    for block in blocks:
        obj = _block_object(block)
        if obj is None:
            continue
        vid = _as_int(obj.get("vectorId"))
        if vid is None:
            continue
        found[vid] = obj
    return found


def _identity(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "series_id": row["series_id"],
        "sector_label": row["sector_label"],
        "title": row["title"],
        "table": row["table"],
        "product_id": row["product_id"],
        "coordinate": row["coordinate"],
        "csv_coordinate": row["csv_coordinate"],
        "vector_id": row["vector_id"],
        "frequency": "quarterly",
        "frequency_code": SECTOR_PPI_FREQUENCY_CODE,
        "seasonal_status": row["seasonal_status"],
        "units": row["units"],
        "channel_role": row["channel_role"],
        "scored": False,
        "coverage_note": row["coverage_note"],
        "source_url": STATCAN_WDS_DATA_URL,
    }


def _unavailable_series(row: dict[str, Any], reason: str, *, detail: str | None = None) -> dict[str, Any]:
    out = _identity(row)
    out.update(
        {
            "status": "unavailable",
            "stale": False,
            "reason": reason,
            "period": None,
            "ref_per": None,
            "value": None,
            "prior_period": None,
            "prior_ref_per": None,
            "prior_value": None,
            "qoq": None,
            "release_time": None,
            "observation_count": 0,
            "empty_slots_not_filled": 0,
            "look_ahead_points_excluded": 0,
            "release_time_missing": 0,
        }
    )
    if detail:
        out["detail"] = detail[:300]
    return out


def _parse_sector_series(row: dict[str, Any], obj: dict[str, Any] | None, as_of: date) -> dict[str, Any]:
    if obj is None:
        return _unavailable_series(row, "vector_not_in_response")
    product_id = _as_int(obj.get("productId"))
    if product_id is not None and product_id != SECTOR_PPI_PRODUCT_ID:
        return _unavailable_series(
            row,
            "product_id_mismatch",
            detail=f"response productId {product_id} != {SECTOR_PPI_PRODUCT_ID}",
        )
    coordinate = obj.get("coordinate")
    if coordinate not in (None, "") and str(coordinate) != row["coordinate"]:
        return _unavailable_series(
            row,
            "coordinate_mismatch",
            detail=f"response coordinate {coordinate} != {row['coordinate']}",
        )
    vector_id = _as_int(obj.get("vectorId"))
    if vector_id is not None and vector_id != row["vector_id"]:
        return _unavailable_series(row, "vector_id_mismatch")

    raw_points = obj.get("vectorDataPoint") or obj.get("vectorDataPoints") or []
    if not isinstance(raw_points, list):
        return _unavailable_series(row, "vector_points_not_a_list")

    parsed: list[dict[str, Any]] = []
    for point in raw_points:
        if not isinstance(point, dict):
            continue
        ref = str(point.get("refPer") or "")
        ym = _ref_year_month(ref)
        if ym is None:
            return _unavailable_series(row, "reference_period_unreadable", detail=ref)
        freq = point.get("frequencyCode")
        if freq is None:
            freq = obj.get("frequencyCode")
        freq_code = _as_int(freq) if freq not in (None, "") else None
        if freq_code is not None and freq_code != SECTOR_PPI_FREQUENCY_CODE:
            return _unavailable_series(
                row,
                "frequency_code_not_quarterly",
                detail=f"frequencyCode {freq_code}",
            )
        if ym[1] not in SECTOR_PPI_QUARTER_START_MONTHS:
            return _unavailable_series(
                row,
                "reference_period_not_quarter_start",
                detail=ref,
            )
        parsed.append(
            {
                "ref_per": ref,
                "year_month": ym,
                "period": _quarter_period(*ym),
                "value": _as_float(point.get("value")),
                "release_time": point.get("releaseTime"),
                "release_date": _parse_release_date(
                    str(point.get("releaseTime")) if point.get("releaseTime") else None
                ),
            }
        )
    parsed.sort(key=lambda item: item["year_month"])

    empty_slots = 0
    missing_release = 0
    look_ahead = 0
    kept: list[dict[str, Any]] = []
    for point in parsed:
        if point["value"] is None:
            empty_slots += 1
            continue
        if point["release_date"] is None:
            missing_release += 1
            continue
        if point["release_date"] > as_of:
            look_ahead += 1
            continue
        kept.append(point)

    base = _identity(row)
    base.update(
        {
            "empty_slots_not_filled": empty_slots,
            "look_ahead_points_excluded": look_ahead,
            "release_time_missing": missing_release,
            "observation_count": len(kept),
            "qoq": None,
            "prior_period": None,
            "prior_ref_per": None,
            "prior_value": None,
        }
    )
    if not kept:
        reason = "no_points_released_by_as_of"
        if missing_release and not look_ahead and empty_slots == 0:
            reason = "release_time_missing"
        elif not parsed:
            reason = "no_points_in_response"
        base.update(
            {
                "status": "unavailable",
                "stale": False,
                "reason": reason,
                "period": None,
                "ref_per": None,
                "value": None,
                "release_time": None,
            }
        )
        return base

    latest = kept[-1]
    prior = kept[-2] if len(kept) >= 2 else None
    qoq = None
    qoq_reason = None
    if prior is None:
        qoq_reason = "no_prior_quarter_released_by_as_of"
    else:
        gap = _months_between(prior["year_month"], latest["year_month"])
        if gap != 3:
            qoq_reason = "quarterly_gap_not_filled"
        elif prior["value"] in (None, 0):
            qoq_reason = "prior_value_zero"
        else:
            qoq = latest["value"] / prior["value"] - 1.0
    release_date = latest["release_date"]
    stale = (as_of - release_date).days > SECTOR_PPI_STALE_RELEASE_DAYS
    release_times = sorted({str(point["release_time"]) for point in kept if point["release_time"]})
    base.update(
        {
            "status": "stale" if stale else "ok",
            "stale": stale,
            "period": latest["period"],
            "ref_per": latest["ref_per"][:10],
            "value": latest["value"],
            "prior_period": prior["period"] if prior else None,
            "prior_ref_per": prior["ref_per"][:10] if prior else None,
            "prior_value": prior["value"] if prior else None,
            "qoq": qoq,
            "release_time": latest["release_time"],
            "first_period": kept[0]["period"],
            "last_period": latest["period"],
            "release_times": release_times,
            "data_age_days": (as_of - release_date).days,
        }
    )
    if qoq_reason:
        base["reason"] = qoq_reason
    return base


def _revision_policy(series: list[dict[str, Any]]) -> dict[str, Any]:
    times: list[str] = []
    for row in series:
        for stamp in row.get("release_times") or []:
            if stamp not in times:
                times.append(stamp)
    return {
        "preceding_quarters_revised_each_release": SECTOR_PPI_REVISION_QUARTERS,
        "weight_update_revision": "back_to_the_start_of_the_new_weight_reference_year",
        "source": (
            "Statistics Canada The Daily, 9 October 2026, table 18-10-0292-01; "
            "Bank of Canada Staff Analytical Paper 2026-46, appendix section 5."
        ),
        "observable_vintages": len(times),
        "release_times": times,
        "latest_vintage_only": True,
        "real_time_history_before_first_public_release": False,
        "point_in_time_score_change_supported": False,
    }


def sector_layer_from_blocks(
    as_of: date,
    blocks: list[dict[str, Any]] | None,
    *,
    fetch_error: str | None = None,
) -> dict[str, Any]:
    """Build the quarterly sector layer. Levels are omitted when the fetch or the shape fails."""
    if fetch_error:
        layer = sector_ppi_unavailable("statcan_wds_fetch_failed", detail=fetch_error)
        layer["as_of"] = as_of.isoformat()
        layer["series"] = [
            _unavailable_series(row, "statcan_wds_fetch_failed", detail=fetch_error)
            for row in SECTOR_PPI_SERIES
        ]
        layer["revision_policy"] = {
            "preceding_quarters_revised_each_release": SECTOR_PPI_REVISION_QUARTERS,
            "observable_vintages": None,
            "point_in_time_score_change_supported": False,
            "latest_vintage_only": True,
        }
        return layer

    by_vector = _objects_by_vector(blocks or [])
    series = [
        _parse_sector_series(row, by_vector.get(row["vector_id"]), as_of)
        for row in SECTOR_PPI_SERIES
    ]
    statuses = [row["status"] for row in series]
    if all(status == "unavailable" for status in statuses):
        top = "unavailable"
    elif all(status == "ok" for status in statuses):
        top = "ok"
    elif all(status == "stale" for status in statuses):
        top = "stale"
    else:
        top = "partial"
    reason = None
    if top == "unavailable":
        reason = series[0]["reason"] if series else "no_sector_series"
    layer = sector_ppi_unavailable(reason or "ok")
    layer.update(
        {
            "as_of": as_of.isoformat(),
            "status": top,
            "reason": reason,
            "series": series,
            "revision_policy": _revision_policy(series),
            "forward_filled": False,
        }
    )
    if top != "unavailable":
        layer.pop("reason", None)
        layer["documentation"] = (
            "Quarterly observations from Statistics Canada table 18-10-0292-01, "
            "first released 2026-10-09. Shadow only: these levels are not inputs "
            "to the scored monthly IPPI or RMPI channels."
        )
    return layer


def build_sector_ppi_layer(as_of: date, opener: Opener) -> dict[str, Any]:
    vector_ids = [row["vector_id"] for row in SECTOR_PPI_SERIES]
    blocks, error = _fetch_statcan_blocks(vector_ids, SECTOR_PPI_LATEST_N, opener)
    return sector_layer_from_blocks(as_of, blocks, fetch_error=error)
