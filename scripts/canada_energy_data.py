"""Canadian physical energy and hard-activity series (acquisition only).

Official machine-readable sources:

- Alberta Energy Regulator ST3 "Supply and Disposition of Crude Oil and
  Equivalent" workbook (``Oil_current.xlsx`` plus one archived prior-year
  workbook for a bounded backfill). Monthly cubic metres.
- Statistics Canada WDS vectors (``getDataFromVectorsAndLatestNPeriods``) for
  marketable natural gas production and the volume-based activity context
  series. Each data point carries its own ``releaseTime`` and
  ``symbolCode`` (preliminary/revised), which are preserved.

Every physical-production series is stored twice: the official monthly level
in the publisher's units, and a derived calendar-day rate
``monthly_level / days_in_month`` so month-length effects do not contaminate
month-over-month comparisons. The derivation is written on each derived
observation. Nothing here scores, weights, or interprets.
"""

from __future__ import annotations

import calendar
import io
import re
from datetime import date, datetime
from typing import Any

AER_ST3_PAGE = "https://www.aer.ca/providing-information/data-and-reports/statistical-reports/st3"
AER_ST3_OIL_CURRENT_XLSX = "https://www.aer.ca/documents/sts/st3/Oil_current.xlsx"
# Archived yearly workbooks. The 2025 file lives under /prd/; older years under
# /documents/. Backfill is best-effort and never fails the current-year read.
AER_ST3_OIL_ARCHIVE_XLSX = {
    2025: "https://www.aer.ca/prd/documents/sts/st3/Oil_2025.xlsx",
}

STATCAN_WDS_VECTORS_URL = (
    "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods"
)

MONTHLY_LEVEL = "monthly_level"
CALENDAR_DAY_RATE = "calendar_day_rate"
CALENDAR_DAY_RATE_FORMULA = "calendar_day_rate = monthly_level / days_in_calendar_month(period)"

# Row labels in the AER ST3 oil workbook "Data" sheet -> canonical series key.
# Labels are matched after whitespace normalisation and case folding.
AER_OIL_ROW_LABELS: dict[str, str] = {
    "total production": "ab_oil_total_production",
    "total oil sands production": "ab_oil_sands_production",
    "total crude oil production": "ab_conventional_crude_production",
    "condensate production": "ab_condensate_production",
}
AER_OIL_UNITS = "cubic metres"
_MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# StatCan WDS scalar factor codes -> unit prefix.
_SCALAR_PREFIX = {
    0: "",
    1: "tens of ",
    2: "hundreds of ",
    3: "thousands of ",
    4: "tens of thousands of ",
    5: "hundreds of thousands of ",
    6: "millions of ",
    7: "tens of millions of ",
    8: "hundreds of millions of ",
    9: "billions of ",
}
# StatCan WDS symbol codes.
_SYMBOL_REVISION = {0: "final", 1: "preliminary", 3: "revised"}


class CanadaEnergyError(RuntimeError):
    """Raised when an official payload cannot be parsed into observations."""


# --------------------------------------------------------------------------
# Calendar-day normalisation
# --------------------------------------------------------------------------


def days_in_period(period: str) -> int:
    """Calendar days in a ``YYYY-MM`` period (leap years included)."""
    match = re.fullmatch(r"(\d{4})-(\d{2})", str(period))
    if not match:
        raise ValueError(f"period must be YYYY-MM, got {period!r}")
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        raise ValueError(f"invalid month in period {period!r}")
    return calendar.monthrange(year, month)[1]


def calendar_day_rate(period: str, monthly_level: float) -> float:
    """Official monthly level divided by the number of calendar days."""
    return float(monthly_level) / float(days_in_period(period))


def derivation_metadata(period: str, units: str) -> dict[str, Any]:
    """Explicit lineage for a derived calendar-day observation."""
    return {
        "formula": CALENDAR_DAY_RATE_FORMULA,
        "days_in_month": days_in_period(period),
        "derived_from_transformation": MONTHLY_LEVEL,
        "derived_units": f"{units} per calendar day",
    }


def with_calendar_day_rates(
    points: list[dict[str, Any]],
    *,
    units: str,
) -> list[dict[str, Any]]:
    """Return monthly-level points plus one derived calendar-day point each."""
    out: list[dict[str, Any]] = []
    for point in points:
        level_units = str(point.get("units") or units)
        level = dict(point)
        level["transformation"] = MONTHLY_LEVEL
        level["units"] = level_units
        out.append(level)
        derived = dict(point)
        derived["transformation"] = CALENDAR_DAY_RATE
        derived["value"] = calendar_day_rate(str(point["period"]), float(point["value"]))
        derived["units"] = f"{level_units} per calendar day"
        derived["derivation"] = derivation_metadata(str(point["period"]), level_units)
        out.append(derived)
    return out


# --------------------------------------------------------------------------
# AER ST3 oil workbook
# --------------------------------------------------------------------------


def _norm_label(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _parse_run_date(text: str) -> date | None:
    match = re.search(r"run date:\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text, re.IGNORECASE)
    if not match:
        return None
    text = f"{match.group(1)} {match.group(2)} {match.group(3)}"
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def parse_aer_st3_oil_workbook(body: bytes) -> dict[str, Any]:
    """Parse the AER ST3 crude oil and equivalent supply/disposition workbook.

    Returns ``{"year", "run_date", "units", "series": {key: {period: value}}}``.
    Months at or after the run-date month, and months where every production
    row is zero, are unpublished and are not returned as observations.
    """
    if body[:4] != b"PK\x03\x04":
        raise CanadaEnergyError("aer_st3_body_not_xlsx")
    try:
        import openpyxl  # noqa: PLC0415 — optional dependency at import time
    except ModuleNotFoundError as exc:  # pragma: no cover - environment guard
        raise CanadaEnergyError("openpyxl_missing") from exc

    try:
        workbook = openpyxl.load_workbook(io.BytesIO(body), data_only=True, read_only=True)
    except Exception as exc:  # noqa: BLE001
        raise CanadaEnergyError(f"aer_st3_workbook_unreadable:{exc.__class__.__name__}") from exc

    sheet = workbook["Data"] if "Data" in workbook.sheetnames else workbook.worksheets[-1]
    rows = [list(row) for row in sheet.iter_rows(values_only=True)]

    run_date: date | None = None
    year: int | None = None
    units: str | None = None
    month_columns: dict[int, int] | None = None
    supply_seen = False
    series: dict[str, dict[str, float]] = {key: {} for key in AER_OIL_ROW_LABELS.values()}

    for index, row in enumerate(rows):
        texts = [str(cell) for cell in row if isinstance(cell, str)]
        joined = " ".join(texts)
        if run_date is None:
            run_date = _parse_run_date(joined)
        if units is None:
            unit_match = re.search(r"unit\s*=\s*([^()]+?)\s*\(", joined, re.IGNORECASE)
            if unit_match:
                units = unit_match.group(1).strip().casefold()
        if month_columns is None:
            positions = {}
            for col, cell in enumerate(row):
                if isinstance(cell, str) and cell.strip() in _MONTH_ABBR:
                    positions[_MONTH_ABBR.index(cell.strip()) + 1] = col
            if len(positions) == 12:
                month_columns = positions
                for cell in row:
                    if isinstance(cell, (str, int)) and re.fullmatch(r"\d{4}", str(cell).strip()):
                        year = int(str(cell).strip())
                continue
        if month_columns is None:
            continue
        label = _norm_label(next((cell for cell in row if isinstance(cell, str)), ""))
        if label == "supply":
            supply_seen = True
        if label == "disposition":
            break
        key = AER_OIL_ROW_LABELS.get(label)
        if key is None or not supply_seen:
            continue
        if series[key]:
            continue  # first SUPPLY occurrence only
        for month, col in month_columns.items():
            value = _finite(row[col]) if col < len(row) else None
            if value is not None:
                series[key][month] = value

    if year is None:
        raise CanadaEnergyError("aer_st3_year_header_missing")
    if run_date is None:
        raise CanadaEnergyError("aer_st3_run_date_missing")
    if month_columns is None:
        raise CanadaEnergyError("aer_st3_month_header_missing")
    missing = [key for key, values in series.items() if not values]
    if missing:
        raise CanadaEnergyError(f"aer_st3_rows_missing:{','.join(sorted(missing))}")

    published: dict[str, dict[str, float]] = {key: {} for key in series}
    for month in range(1, 13):
        if (year, month) >= (run_date.year, run_date.month):
            continue
        month_values = [series[key].get(month) for key in series]
        if any(value is None for value in month_values):
            continue
        if all(value == 0 for value in month_values):
            continue
        period = f"{year:04d}-{month:02d}"
        for key in series:
            published[key][period] = series[key][month]

    return {
        "year": year,
        "run_date": run_date.isoformat(),
        "units": units or AER_OIL_UNITS,
        "series": published,
    }


def aer_oil_points(
    parsed: dict[str, Any],
    series_key: str,
    *,
    source_url: str,
) -> list[dict[str, Any]]:
    """Monthly-level points for one AER series (no derived rows yet)."""
    values = (parsed.get("series") or {}).get(series_key) or {}
    run_date = str(parsed.get("run_date") or "")
    points: list[dict[str, Any]] = []
    for period in sorted(values):
        points.append(
            {
                "period": period,
                "value": float(values[period]),
                "transformation": MONTHLY_LEVEL,
                "revision_status": "latest_available",
                "release_date": run_date or None,
                "source_url": source_url,
            }
        )
    return points


def aer_vintage(parsed: dict[str, Any]) -> str:
    """Publisher vintage label for one AER ST3 workbook read."""
    return f"aer_st3_run_date:{parsed.get('run_date')}"


def merge_aer_years(
    current: list[dict[str, Any]],
    backfill: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Current-year workbook wins on overlapping periods; backfill fills history."""
    by_period = {str(point["period"]): dict(point) for point in backfill}
    for point in current:
        by_period[str(point["period"])] = dict(point)
    return [by_period[period] for period in sorted(by_period)]


# --------------------------------------------------------------------------
# StatCan WDS vector history
# --------------------------------------------------------------------------


def statcan_units(uom_label: str, scalar_factor_code: int | None) -> str:
    prefix = _SCALAR_PREFIX.get(int(scalar_factor_code or 0), "")
    return f"{prefix}{uom_label}".strip()


def statcan_vector_history_points(
    payload: Any,
    vector_id: int,
    *,
    source_url: str,
    uom_label: str,
) -> list[dict[str, Any]]:
    """All monthly points for one vector, with release date and revision flag."""
    blocks = payload if isinstance(payload, list) else [payload]
    points: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        obj = block.get("object") if isinstance(block.get("object"), dict) else block
        try:
            if int(obj.get("vectorId")) != int(vector_id):
                continue
        except (TypeError, ValueError):
            continue
        for point in obj.get("vectorDataPoint") or obj.get("vectorDataPoints") or []:
            if not isinstance(point, dict):
                continue
            ref = str(point.get("refPer") or "")
            if len(ref) < 7:
                continue
            value = _finite(point.get("value"))
            if value is None:
                continue
            release = str(point.get("releaseTime") or "")[:10] or None
            try:
                symbol = int(point.get("symbolCode") or 0)
            except (TypeError, ValueError):
                symbol = 0
            try:
                scalar = int(point.get("scalarFactorCode") or 0)
            except (TypeError, ValueError):
                scalar = 0
            points.append(
                {
                    "period": ref[:7],
                    "value": value,
                    "transformation": MONTHLY_LEVEL,
                    "revision_status": _SYMBOL_REVISION.get(symbol, "final"),
                    "release_date": release,
                    "source_url": source_url,
                    "units": statcan_units(uom_label, scalar),
                    "statcan_scalar_factor_code": scalar,
                    "statcan_symbol_code": symbol,
                    "statcan_status_code": point.get("statusCode"),
                }
            )
    points.sort(key=lambda item: str(item["period"]))
    return points
