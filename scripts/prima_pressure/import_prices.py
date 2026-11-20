"""Statistics Canada merchandise import price indexes (table 12-10-0168-01)."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Callable

from scripts.prima_pressure.contract import STATCAN_WDS_DATA_URL
from scripts.prima_pressure.producer import (
    _fetch_statcan_blocks,
    _objects_by_vector,
    _parse_release_date,
    _period_from_ref,
)

Opener = Callable[..., bytes]

IMPORT_PRICE_TABLE_PID = "12-10-0168-01"
IMPORT_PRICE_PRODUCT_ID = 12100168
IMPORT_PRICE_TABLE_URL = "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1210016801"
IMPORT_PRICE_FREQUENCY = "monthly"
IMPORT_PRICE_FREQUENCY_CODE = 6
IMPORT_PRICE_MEMBER_UOM_CODE = 373
IMPORT_PRICE_UNITS = "index_2017_100"
IMPORT_PRICE_INDEX_BASE = "2017=100"
IMPORT_PRICE_CURRENCY = "CAD"

# Verified 2026-11-11 via WDS getSeriesInfoFromCubePidCoord / getDataFromVectorsAndLatestNPeriods.
IMPORT_PRICE_SERIES = (
    {
        "series_id": "import_price_total",
        "label": (
            "Canada; Import; Balance of payments; Seasonally adjusted; "
            "Price index; Laspeyres fixed weighted; Total of all merchandise"
        ),
        "table_pid": IMPORT_PRICE_TABLE_PID,
        "product_id": IMPORT_PRICE_PRODUCT_ID,
        "vector_id": 1566914271,
        "coordinate": "1.1.2.2.1.2.1.0.0.0",
        "units": IMPORT_PRICE_UNITS,
        "index_base": IMPORT_PRICE_INDEX_BASE,
        "seasonal_status": "SA",
        "basis": "balance_of_payments",
        "currency": IMPORT_PRICE_CURRENCY,
        "frequency": IMPORT_PRICE_FREQUENCY,
    },
)

IMPORT_PRICE_MEASURE_VERIFIED = {
    "status": "available",
    "series_ids": ["import_price_total"],
    "documentation": (
        "Official Statistics Canada international merchandise import price index "
        f"(table {IMPORT_PRICE_TABLE_PID}, productId {IMPORT_PRICE_PRODUCT_ID}), "
        "monthly observed levels from WDS — not a live proxy and not RMPI. "
        "Pinned slice: Import, balance-of-payments basis, seasonally adjusted, "
        "Laspeyres price index, NAPCS member Total of all merchandise. "
        f"Unit of measure memberUomCode {IMPORT_PRICE_MEMBER_UOM_CODE}: Index, {IMPORT_PRICE_INDEX_BASE} "
        "(WDS getCodeSets). Prices on a balance-of-payments basis are expressed in Canadian dollars "
        "(national-accounts valuation). NAPCS has no published aggregate for total merchandise "
        "excluding energy; member 14 is Energy products only, not an ex-energy total."
    ),
}


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
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


def _months_between(start: tuple[int, int], end: tuple[int, int]) -> int:
    return (end[0] * 12 + end[1]) - (start[0] * 12 + start[1])


def _month_stale(latest_ym: tuple[int, int] | None, as_of: date) -> bool:
    if latest_ym is None:
        return True
    as_ym = (as_of.year, as_of.month)
    return _months_between(latest_ym, as_ym) > 3


def _mom_pct_decimal(kept: list[dict[str, Any]]) -> float | None:
    if len(kept) < 2:
        return None
    prior, latest = kept[-2], kept[-1]
    if _months_between(prior["year_month"], latest["year_month"]) != 1:
        return None
    if prior["value"] in (None, 0):
        return None
    if latest["value"] is None:
        return None
    return latest["value"] / prior["value"] - 1.0


def _change_3m_pct_decimal(kept: list[dict[str, Any]]) -> float | None:
    if len(kept) < 2:
        return None
    latest = kept[-1]
    if latest["value"] is None:
        return None
    for prior in reversed(kept[:-1]):
        if _months_between(prior["year_month"], latest["year_month"]) != 3:
            continue
        if prior["value"] in (None, 0):
            return None
        return latest["value"] / prior["value"] - 1.0
    return None


def _series_shell(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **row,
        "status": "unavailable",
        "stale": False,
        "observations": [],
        "latest_period": None,
        "latest_value": None,
        "mom_pct_decimal": None,
        "change_3m_pct_decimal": None,
        "source_url": STATCAN_WDS_DATA_URL,
    }


def _unavailable_payload(
    *,
    as_of: date,
    retrieved_at: str,
    reason: str,
) -> dict[str, Any]:
    series = {row["series_id"]: {**_series_shell(row), "reason": reason} for row in IMPORT_PRICE_SERIES}
    return {
        "status": "unavailable",
        "reason": reason,
        "frequency": IMPORT_PRICE_FREQUENCY,
        "table_pid": IMPORT_PRICE_TABLE_PID,
        "product_id": IMPORT_PRICE_PRODUCT_ID,
        "source_url": STATCAN_WDS_DATA_URL,
        "table_url": IMPORT_PRICE_TABLE_URL,
        "retrieved_at": retrieved_at,
        "release_time": None,
        "series": series,
        "notes": [],
        "measure_verified": IMPORT_PRICE_MEASURE_VERIFIED,
        "as_of": as_of.isoformat(),
    }


def _parse_series(
    row: dict[str, Any],
    obj: dict[str, Any] | None,
    *,
    as_of: date,
    notes: list[str],
) -> dict[str, Any]:
    base = _series_shell(row)
    if obj is None:
        base["reason"] = "vector_not_in_response"
        return base

    product_id = _as_int(obj.get("productId"))
    if product_id is not None and product_id != row["product_id"]:
        base["reason"] = "product_id_mismatch"
        base["detail"] = f"response productId {product_id} != {row['product_id']}"
        return base

    coordinate = obj.get("coordinate")
    if coordinate not in (None, "") and str(coordinate) != row["coordinate"]:
        base["reason"] = "coordinate_mismatch"
        base["detail"] = f"response coordinate {coordinate} != {row['coordinate']}"
        return base

    vector_id = _as_int(obj.get("vectorId"))
    if vector_id is not None and vector_id != row["vector_id"]:
        base["reason"] = "vector_id_mismatch"
        return base

    raw_points = obj.get("vectorDataPoint") or obj.get("vectorDataPoints") or []
    if not isinstance(raw_points, list):
        base["reason"] = "vector_points_not_a_list"
        return base

    parsed: list[dict[str, Any]] = []
    release_missing = 0
    for point in raw_points:
        if not isinstance(point, dict):
            continue
        ym = _ref_year_month(str(point.get("refPer") or ""))
        if ym is None:
            base["reason"] = "reference_period_unreadable"
            return base
        freq = _as_int(point.get("frequencyCode"))
        if freq is not None and freq != IMPORT_PRICE_FREQUENCY_CODE:
            base["reason"] = "frequency_code_not_monthly"
            return base
        release_time = point.get("releaseTime")
        release_date = _parse_release_date(str(release_time) if release_time else None)
        value = _as_float(point.get("value"))
        parsed.append(
            {
                "period": _period_from_ref(str(point.get("refPer") or "")),
                "year_month": ym,
                "value": value,
                "release_time": release_time,
                "release_date": release_date,
            }
        )
    parsed.sort(key=lambda item: item["year_month"])

    kept: list[dict[str, Any]] = []
    for point in parsed:
        if point["value"] is None:
            continue
        if point["release_date"] is None:
            release_missing += 1
            notes.append(
                f"{row['series_id']}: observation {point['period']} kept without releaseTime "
                "(release-date gating skipped for that point)"
            )
            kept.append(point)
            continue
        if point["release_date"] > as_of:
            continue
        kept.append(point)

    if not kept:
        base["reason"] = "no_points_released_by_as_of"
        return base

    latest = kept[-1]
    stale = _month_stale(latest["year_month"], as_of)
    observations = [
        {
            "period": p["period"],
            "value": p["value"],
            "release_time": p["release_time"],
        }
        for p in kept
    ]
    status = "stale" if stale else "ok"
    base.update(
        {
            "status": status,
            "stale": stale,
            "observations": observations,
            "latest_period": latest["period"],
            "latest_value": latest["value"],
            "mom_pct_decimal": _mom_pct_decimal(kept),
            "change_3m_pct_decimal": _change_3m_pct_decimal(kept),
            "release_time": latest["release_time"],
            "observation_count": len(kept),
            "release_time_missing": release_missing,
        }
    )
    return base


def _top_status(series: dict[str, Any]) -> str:
    statuses = [row.get("status") for row in series.values()]
    if all(s == "unavailable" for s in statuses):
        return "unavailable"
    if all(s == "ok" for s in statuses):
        return "ok"
    if any(s in ("ok", "stale") for s in statuses):
        return "partial"
    return "unavailable"


def _cube_release_time(blocks: list[dict[str, Any]]) -> str | None:
    for block in blocks:
        obj = block.get("object") if isinstance(block.get("object"), dict) else block
        if not isinstance(obj, dict):
            continue
        points = obj.get("vectorDataPoint") or obj.get("vectorDataPoints") or []
        if not isinstance(points, list):
            continue
        for point in reversed(points):
            if isinstance(point, dict) and point.get("releaseTime"):
                return str(point["releaseTime"])
    return None


def collect_import_prices(
    *,
    as_of: date,
    opener: Opener,
    retrieved_at: str,
    latest_n: int = 13,
) -> dict[str, Any]:
    """Collect monthly StatCan merchandise import price indexes. Never raises."""
    notes: list[str] = [
        "import_price_ex_energy: no NAPCS member for total merchandise excluding energy "
        "in table 12-10-0168-01 (verified 2026-11-11); only Energy products (member 14) "
        "is available as a separate commodity slice.",
    ]
    try:
        vector_ids = [row["vector_id"] for row in IMPORT_PRICE_SERIES]
        blocks, error = _fetch_statcan_blocks(vector_ids, latest_n, opener)
        if error:
            return _unavailable_payload(as_of=as_of, retrieved_at=retrieved_at, reason=error)

        by_vector = _objects_by_vector(blocks)
        series_out: dict[str, Any] = {}
        for row in IMPORT_PRICE_SERIES:
            series_out[row["series_id"]] = _parse_series(
                row, by_vector.get(row["vector_id"]), as_of=as_of, notes=notes
            )

        top = _top_status(series_out)
        release_time = _cube_release_time(blocks)
        return {
            "status": top,
            "frequency": IMPORT_PRICE_FREQUENCY,
            "table_pid": IMPORT_PRICE_TABLE_PID,
            "product_id": IMPORT_PRICE_PRODUCT_ID,
            "source_url": STATCAN_WDS_DATA_URL,
            "table_url": IMPORT_PRICE_TABLE_URL,
            "retrieved_at": retrieved_at,
            "release_time": release_time,
            "series": series_out,
            "notes": notes,
            "measure_verified": IMPORT_PRICE_MEASURE_VERIFIED,
            "as_of": as_of.isoformat(),
        }
    except Exception as exc:
        detail = str(exc).strip().replace("\n", " ")[:180]
        return _unavailable_payload(
            as_of=as_of,
            retrieved_at=retrieved_at,
            reason=f"import_prices_collect_failed:{type(exc).__name__}:{detail}",
        )
