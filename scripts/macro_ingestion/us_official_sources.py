"""Official US publisher fallbacks when FRED graph CSV is unavailable."""

from __future__ import annotations

import calendar
import csv
import hashlib
import io
import re
from datetime import date, datetime
from typing import Any, Callable

from scripts.temperature_level import month_before, period_sort_key

BEA_SECTION2_XLSX_URL = "https://apps.bea.gov/national/Release/XLS/Survey/Section2All_xls.xlsx"
BEA_SECTION1_XLSX_URL = "https://apps.bea.gov/national/Release/XLS/Survey/Section1All_xls.xlsx"
CENSUS_RETAIL_TXT_URL = "https://www.census.gov/retail/marts/www/adv44X72.txt"
MICHIGAN_TBCICS_CSV_URL = "https://www.sca.isr.umich.edu/files/tbcics.csv"

_PERIOD_HEADER = re.compile(r"^(?P<year>\d{4})(?:M(?P<month>\d{2})|Q(?P<quarter>[1-4]))$")
_DATA_PUBLISHED = re.compile(
    r"Data published\s+(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4})",
    re.IGNORECASE,
)
_MONTH_INDEX = {
    name.lower(): idx
    for idx, name in enumerate(
        [
            "JAN",
            "FEB",
            "MAR",
            "APR",
            "MAY",
            "JUN",
            "JUL",
            "AUG",
            "SEP",
            "OCT",
            "NOV",
            "DEC",
        ],
        start=1,
    )
}

CatalogId = str


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bea_period_token(cell: Any) -> str | None:
    if cell is None:
        return None
    text = str(cell).strip().upper()
    match = _PERIOD_HEADER.match(text)
    if not match:
        return None
    year = int(match.group("year"))
    if match.group("month"):
        return f"{year}-{int(match.group('month')):02d}"
    quarter = int(match.group("quarter"))
    return f"{year}-Q{quarter}"


def _parse_published_date(text: str) -> str | None:
    match = _DATA_PUBLISHED.search(text or "")
    if not match:
        return None
    month_name = match.group("month").lower()
    month_num = None
    for idx, name in enumerate(calendar.month_name):
        if idx == 0:
            continue
        if name and name.lower() == month_name:
            month_num = idx
            break
    if month_num is None:
        for idx, abbr in enumerate(calendar.month_abbr):
            if idx == 0:
                continue
            if abbr and abbr.lower() == month_name[:3].lower():
                month_num = idx
                break
    if month_num is None:
        return None
    try:
        day = int(match.group("day"))
        year = int(match.group("year"))
        return date(year, month_num, day).isoformat()
    except ValueError:
        return None


def _bea_release_date(sheet_rows: list[tuple[Any, ...]]) -> str | None:
    for row in sheet_rows[:12]:
        for cell in row:
            if cell is None:
                continue
            parsed = _parse_published_date(str(cell))
            if parsed:
                return parsed
    return None


def _scan_sheet_rows(body: bytes, sheet_name: str, *, row_limit: int = 400) -> list[tuple[Any, ...]]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(body), read_only=True, data_only=True)
    if sheet_name not in wb.sheetnames:
        wb.close()
        raise ValueError(f"bea_sheet_missing:{sheet_name}")
    ws = wb[sheet_name]
    rows: list[tuple[Any, ...]] = []
    for index, row in enumerate(ws.iter_rows(values_only=True)):
        if index >= row_limit:
            break
        rows.append(tuple(row))
    wb.close()
    return rows


def _bea_header_map(header_row: tuple[Any, ...]) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for col_index, cell in enumerate(header_row):
        period = _bea_period_token(cell)
        if period:
            mapping[col_index] = period
    if not mapping:
        raise ValueError("bea_header_not_found")
    return mapping


def _bea_find_header_row(rows: list[tuple[Any, ...]]) -> tuple[int, dict[int, str]]:
    for row_index, row in enumerate(rows):
        try:
            header = _bea_header_map(row)
        except ValueError:
            continue
        return row_index, header
    raise ValueError("bea_header_not_found")


def _row_description(row: tuple[Any, ...]) -> str:
    if len(row) < 2 or row[1] is None:
        return ""
    return str(row[1]).strip()


def _row_series_code(row: tuple[Any, ...]) -> str:
    if len(row) < 3 or row[2] is None:
        return ""
    return str(row[2]).strip().upper()


def _parse_bea_levels(
    body: bytes,
    *,
    sheet_name: str,
    series_code: str,
    row_matcher: Callable[[str, str], bool],
) -> dict[str, Any]:
    rows = _scan_sheet_rows(body, sheet_name)
    header_index, header = _bea_find_header_row(rows)
    release_date = _bea_release_date(rows)
    matches: list[tuple[str, tuple[Any, ...]]] = []
    for row in rows[header_index + 1 :]:
        code = _row_series_code(row)
        if code != series_code.upper():
            continue
        desc = _row_description(row)
        if row_matcher(desc, code):
            matches.append((desc, row))
    if not matches:
        raise ValueError(f"bea_series_missing:{series_code}")
    if len(matches) > 1:
        raise ValueError(f"bea_series_ambiguous:{series_code}")
    _, data_row = matches[0]
    levels: list[tuple[str, float]] = []
    for col_index, period in header.items():
        if col_index >= len(data_row):
            continue
        raw = data_row[col_index]
        if raw is None or raw == "":
            continue
        if isinstance(raw, str) and raw.strip() in {"...", "(NA)"}:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        levels.append((period, value))
    if not levels:
        raise ValueError(f"bea_series_empty:{series_code}")
    levels.sort(key=lambda item: period_sort_key(item[0]))
    return {
        "levels": levels,
        "release_date": release_date,
        "source_url": BEA_SECTION2_XLSX_URL if "T20" in sheet_name else BEA_SECTION1_XLSX_URL,
    }


def _match_core_pce(desc: str, _code: str) -> bool:
    low = desc.lower()
    return "pce excluding food and energy" in low and "housing" not in low


def _match_income(desc: str, _code: str) -> bool:
    return desc.startswith("Equals: Disposable personal income")


def _match_spending(desc: str, _code: str) -> bool:
    low = desc.lower()
    return "personal consumption expenditures (pce)" in low and "excluding" not in low


def _match_gdp(desc: str, code: str) -> bool:
    return code == "A191RL" and desc.strip().lower() == "gross domestic product"


def parse_bea_core_pce(body: bytes) -> dict[str, Any]:
    return _parse_bea_levels(
        body, sheet_name="T20804-M", series_code="DPCCRG", row_matcher=_match_core_pce
    )


def parse_bea_income(body: bytes) -> dict[str, Any]:
    return _parse_bea_levels(
        body, sheet_name="T20600-M", series_code="A067RC", row_matcher=_match_income
    )


def parse_bea_spending(body: bytes) -> dict[str, Any]:
    return _parse_bea_levels(
        body, sheet_name="T20806-M", series_code="DPCERX", row_matcher=_match_spending
    )


def parse_bea_gdp_saar(body: bytes) -> dict[str, Any]:
    return _parse_bea_levels(
        body, sheet_name="T10101-Q", series_code="A191RL", row_matcher=_match_gdp
    )


def parse_census_retail_txt(body: bytes) -> dict[str, Any]:
    text = body.decode("utf-8", errors="replace")
    title = ""
    for line in text.splitlines():
        if line.strip():
            title = line.strip().upper()
            break
    # adv44000.txt is retail excluding food services. RSAFS is retail AND food services.
    if "FOOD SERVICES" not in title or "EXCL" in title:
        raise ValueError("census_retail_not_food_services_total")
    lines = text.splitlines()
    header: list[str] | None = None
    levels: list[tuple[str, float]] = []
    for line in lines:
        if line.startswith("SEASONAL"):
            break
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("YEAR"):
            header = stripped.split()
            continue
        if header is None:
            continue
        parts = stripped.split()
        if not parts or not parts[0].isdigit():
            continue
        year = int(parts[0])
        values = parts[1:]
        for month_label, raw in zip(header[1:], values):
            month_label = month_label.strip().upper()
            month_num = _MONTH_INDEX.get(month_label.lower()[:3])
            if month_num is None:
                continue
            if not raw or not re.fullmatch(r"-?\d+", raw):
                continue
            period = f"{year}-{month_num:02d}"
            levels.append((period, float(raw)))
    if not levels:
        raise ValueError("census_retail_empty")
    levels.sort(key=lambda item: period_sort_key(item[0]))
    return {"levels": levels, "release_date": None, "source_url": CENSUS_RETAIL_TXT_URL}


def parse_michigan_tbcics_csv(body: bytes) -> dict[str, Any]:
    text = body.decode("utf-8", errors="replace")
    lines = text.splitlines()
    levels: list[tuple[str, float]] = []
    revision_by_period: dict[str, str] = {}
    in_table = False
    for line in lines:
        if "DATE OF SURVEY" in line and "INDEX OF CONSUMER SENTIMENT" in line:
            in_table = True
            continue
        if not in_table:
            continue
        row = next(csv.reader([line], skipinitialspace=True)) if line else []
        if len(row) < 5:
            continue
        month_cell = (row[0] or "").strip()
        year_cell = ""
        value_cell = ""
        if len(row) > 1 and str(row[1] or "").strip().isdigit():
            year_cell = str(row[1]).strip()
            value_cell = (row[4] or row[3] or "").strip() if len(row) > 3 else ""
        elif len(row) > 2 and str(row[2] or "").strip().isdigit():
            year_cell = str(row[2]).strip()
            value_cell = (row[4] or "").strip() if len(row) > 4 else ""
        if not month_cell or not year_cell.isdigit() or not value_cell:
            continue
        preliminary = "(p)" in month_cell.lower()
        month_name = re.sub(r"\s*\([^)]*\)", "", month_cell, flags=re.IGNORECASE).strip()
        month_num = None
        for idx, name in enumerate(calendar.month_name):
            if idx == 0:
                continue
            if name and name.lower() == month_name.lower():
                month_num = idx
                break
        if month_num is None:
            for idx, abbr in enumerate(calendar.month_abbr):
                if idx == 0:
                    continue
                if abbr and month_name.lower().startswith(abbr.lower()):
                    month_num = idx
                    break
        if month_num is None:
            continue
        try:
            value = float(value_cell)
        except ValueError:
            continue
        period = f"{int(year_cell)}-{month_num:02d}"
        levels.append((period, value))
        if preliminary:
            revision_by_period[period] = "preliminary"
    if not levels:
        raise ValueError("michigan_sentiment_empty")
    levels.sort(key=lambda item: period_sort_key(item[0]))
    return {
        "levels": levels,
        "revision_by_period": revision_by_period,
        "release_date": None,
        "source_url": MICHIGAN_TBCICS_CSV_URL,
    }


_OFFICIAL_SPECS: dict[CatalogId, dict[str, Any]] = {
    "US.Inflation.core_pce": {
        "url": BEA_SECTION2_XLSX_URL,
        "accepted_source": "bea_survey_xlsx",
        "parse": parse_bea_core_pce,
    },
    "US.Consumer.income": {
        "url": BEA_SECTION2_XLSX_URL,
        "accepted_source": "bea_survey_xlsx",
        "parse": parse_bea_income,
    },
    "US.Consumer.spending": {
        "url": BEA_SECTION2_XLSX_URL,
        "accepted_source": "bea_survey_xlsx",
        "parse": parse_bea_spending,
    },
    "US.Activity.gdp_domestic_demand": {
        "url": BEA_SECTION1_XLSX_URL,
        "accepted_source": "bea_survey_xlsx",
        "parse": parse_bea_gdp_saar,
    },
    "US.Consumer.retail": {
        "url": CENSUS_RETAIL_TXT_URL,
        "accepted_source": "census_marts_txt",
        "parse": parse_census_retail_txt,
    },
    "US.Consumer.confidence": {
        "url": MICHIGAN_TBCICS_CSV_URL,
        "accepted_source": "michigan_tbcics_csv",
        "parse": parse_michigan_tbcics_csv,
    },
}

OFFICIAL_FALLBACK_CATALOG_IDS = frozenset(_OFFICIAL_SPECS)


def official_config(catalog_id: str) -> dict[str, Any] | None:
    return _OFFICIAL_SPECS.get(catalog_id)


def fetch_official_us_series(
    catalog_id: str,
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
    body: bytes | None = None,
) -> dict[str, Any]:
    spec = official_config(catalog_id)
    if spec is None:
        return {"ok": False, "error": "no_official_config"}
    url = str(spec["url"])
    if body is None:
        try:
            response = opener(url, timeout=timeout)
        except BaseException as exc:  # noqa: BLE001
            return {"ok": False, "error": f"official_fetch_failed:{type(exc).__name__}:{exc}"}
        if not response.get("ok"):
            return {
                "ok": False,
                "error": response.get("error") or "official_fetch_failed",
                "http_status": response.get("http_status"),
                "body": response.get("body") or b"",
            }
        body = response.get("body") or b""
        http_status = response.get("http_status")
    else:
        http_status = 200
    if not body:
        return {"ok": False, "error": "official_body_empty", "http_status": http_status, "body": b""}
    parser = spec["parse"]
    try:
        parsed = parser(body)
    except ValueError as exc:
        return {
            "ok": False,
            "error": f"official_parse_failed:{exc}",
            "http_status": http_status,
            "body": body,
        }
    except BaseException as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"official_parse_failed:{type(exc).__name__}:{exc}",
            "http_status": http_status,
            "body": body,
        }
    return {
        "ok": True,
        "levels": parsed.get("levels") or [],
        "revision_by_period": parsed.get("revision_by_period") or {},
        "release_date": parsed.get("release_date"),
        "source_url": parsed.get("source_url") or url,
        "accepted_source": spec["accepted_source"],
        "http_status": http_status,
        "body": body,
        "raw_sha256": _sha256(body),
    }


def bea_gdp_xlsx_fallback(
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
    body: bytes | None = None,
) -> dict[str, Any]:
    return fetch_official_us_series(
        "US.Activity.gdp_domestic_demand", opener=opener, timeout=timeout, body=body
    )


def period_before_for_cadence(period: str, cadence: str) -> str | None:
    if cadence == "quarterly":
        return month_before(period)
    return month_before(period)
