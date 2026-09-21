#!/usr/bin/env python3
"""Collect official Japan macro observations for temperature history (no scoring)."""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.market_state import BROWSER_USER_AGENT, USER_AGENT, fetch_bytes  # noqa: E402

JP_JSON = _ROOT / "data" / "temperature_history" / "jp.json"
RAW_DIR = _ROOT / "data" / "temperature_history" / "raw" / "jp"

WINDOW_START = date(2025, 9, 21)
WINDOW_END = date(2026, 9, 21)


class SeriesUnavailableError(RuntimeError):
    """Raised when an official series cannot be parsed or is empty."""

    def __init__(self, series_id: str, reason: str) -> None:
        super().__init__(f"{series_id}: {reason}")
        self.series_id = series_id
        self.reason = reason

ESTAT_FILE_DOWNLOAD = "https://www.e-stat.go.jp/stat-search/file-download?statInfId={sid}&fileKind={fk}"

# Pinned statInfId / URLs verified live on 2026-09-21.
SOURCE_CONTRACT = {
    "Inflation.headline": {
        "series_id": "CPI_2025BASE_ALL_ITEMS_YOY",
        "stat_infid": "000032103932",
        "file_kind": 1,
        "column": "all_items_yoy",
    },
    "Inflation.underlying": {
        "series_id": "CPI_2025BASE_LESS_FRESH_FOOD_ENERGY_YOY",
        "stat_infid": "000032103932",
        "file_kind": 1,
        "column": "less_fresh_food_and_energy_yoy",
    },
    "Labor.unemployment": {
        "series_id": "LFS_1A1_UNEMPLOYMENT_RATE_SA",
        "stat_infid": "000031831358",
        "file_kind": 0,
    },
    "Labor.wages": {
        "series_id": "MLS_TOTAL_CASH_EARNINGS_YOY_5PLUS",
        "stat_infid": "000032189720",
        "file_kind": 4,
    },
    "Labor.employment": {
        "series_id": "LFS_1A1_EMPLOYED_PERSONS_SA",
        "stat_infid": "000031831358",
        "file_kind": 0,
    },
    "Activity.gdp_domestic_demand": {
        "series_id": "ESRI_REAL_GDP_QOQ_SAAR",
        "csv_name": "nritu-jk2622.csv",
        # Pinned from Cabinet Office 2026 Q2 preliminary (verified 2026-09-21).
        "pinned_csv_url": (
            "https://www.esri.cao.go.jp/jp/sna/data/data_list/sokuhou/files/2026/qe262_2/tables/nritu-jk2622.csv"
        ),
    },
    "Consumer.retail": {
        "series_id": "METI_CSC_RETAIL_SALES_YOY",
        "url_template": "https://www.meti.go.jp/statistics/tyo/syoudou/result/excel/DB_{yymm}S.xlsx",
    },
    "Consumer.income": {
        "series_id": "FIES_WORKER_HH_REAL_INCOME_NOMINAL_YOY",
        "stat_infid": "000040270658",
        "file_kind": 4,
    },
    "Consumer.spending": {
        "series_id": "FIES_TWO_PLUS_HH_CONSUMPTION_NOMINAL_YOY",
        "stat_infid": "000040270657",
        "file_kind": 4,
    },
    "Consumer.confidence": {
        "series_id": "CO_CONSUMER_SENTIMENT_INDEX_SA",
        "stat_infid": "000040450603",
        "file_kind": 0,
    },
    "context.Tankan_large_manufacturing_di": {
        "series_id": "BOJ_TANKAN_LARGE_MFG_BUSINESS_CONDITIONS_DI",
        "url_template": "https://www.boj.or.jp/en/statistics/tk/gaiyo/{year}/tka{yy}{month}.zip",
    },
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def period_in_window_monthly(period: str) -> bool:
    y, m = int(period[:4]), int(period[5:7])
    d = date(y, m, 1)
    return WINDOW_START.replace(day=1) <= d <= WINDOW_END.replace(day=1)


def period_in_window_quarter(period: str) -> bool:
    # period like 2025-Q3
    y = int(period[:4])
    q = int(period.split("-Q")[1])
    start_month = (q - 1) * 3 + 1
    d = date(y, start_month, 1)
    end_month = start_month + 2
    end_d = date(y, end_month, 28)
    return not (end_d < WINDOW_START or d > WINDOW_END)


def _curl_get(url: str, *, timeout: int = 120) -> bytes:
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        return fetch_bytes(url, user_agent=BROWSER_USER_AGENT, timeout=timeout, retries=3)
    resp = cffi_requests.get(url, impersonate="chrome", timeout=timeout)
    if resp.status_code != 200 or not resp.content:
        raise RuntimeError(f"HTTP {resp.status_code} from {url}")
    if resp.content[:5] == b"<!DOC":
        raise RuntimeError(f"HTML error body from {url}")
    return resp.content


def download_estat(sid: str, file_kind: int, *, fetcher: Callable[[str], bytes] | None = None) -> bytes:
    url = ESTAT_FILE_DOWNLOAD.format(sid=sid, fk=file_kind)
    if fetcher:
        return fetcher(url)
    return _curl_get(url)


def parse_cpi_yoy_csv(text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse e-Stat CPI YoY percent change wide CSV (2025 base)."""
    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 8:
        raise SeriesUnavailableError("CPI_2025BASE_ALL_ITEMS_YOY", "CPI YoY CSV too short")
    header_en = rows[1]
    # Columns: 0 period YYYYMM, 1 All items, 6 less fresh food and energy (BOJ core-core style)
    headline: list[dict[str, Any]] = []
    underlying: list[dict[str, Any]] = []
    for row in rows[7:]:
        if not row or not row[0] or not re.fullmatch(r"\d{6}", row[0].strip()):
            continue
        yyyymm = row[0].strip()
        period = f"{yyyymm[:4]}-{yyyymm[4:6]}"
        if not period_in_window_monthly(period):
            continue
        try:
            h = float(row[1])
            u = float(row[6])
        except (IndexError, ValueError):
            continue
        headline.append({"reference_period": period, "value": h})
        underlying.append({"reference_period": period, "value": u})
    if not headline:
        raise SeriesUnavailableError("CPI_2025BASE_ALL_ITEMS_YOY", "no CPI observations in window")
    return headline, underlying


def parse_lfs_major_items_xlsx(data: bytes) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb["季節調整値"]
    rows = list(ws.iter_rows(values_only=True))
    unemployment: list[dict[str, Any]] = []
    employment_levels: list[tuple[str, float]] = []
    year_carry: int | None = None
    for row in rows[10:]:
        if not row or len(row) < 20:
            continue
        y_raw, month_jp = row[0], row[1]
        if isinstance(y_raw, (int, float)) and y_raw > 1900:
            year_carry = int(y_raw)
        if month_jp is None:
            continue
        month_num = _japanese_month_to_num(str(month_jp))
        if month_num is None or year_carry is None:
            continue
        period = f"{year_carry:04d}-{month_num:02d}"
        try:
            employed = float(row[7])
            unemp_rate = float(row[19])
        except (TypeError, ValueError):
            continue
        if period_in_window_monthly(period):
            unemployment.append({"reference_period": period, "value": unemp_rate})
            employment_levels.append((period, employed))
    employment_levels.sort(key=lambda x: x[0])
    employment: list[dict[str, Any]] = []
    for i in range(1, len(employment_levels)):
        prev_p, prev_v = employment_levels[i - 1]
        cur_p, cur_v = employment_levels[i]
        if cur_p != prev_p:  # noqa: SIM114
            pass
        # Values are 万人 (ten thousand persons); delta in thousands = diff * 10
        delta_k = round((cur_v - prev_v) * 10.0, 3)
        if period_in_window_monthly(cur_p):
            employment.append({"reference_period": cur_p, "value": delta_k})
    return unemployment, employment, []


def _japanese_month_to_num(label: str) -> int | None:
    label = label.strip()
    if label.isdigit():
        m = int(label)
        return m if 1 <= m <= 12 else None
    mapping = {
        "1月": 1,
        "2月": 2,
        "3月": 3,
        "4月": 4,
        "5月": 5,
        "6月": 6,
        "7月": 7,
        "8月": 8,
        "9月": 9,
        "10月": 10,
        "11月": 11,
        "12月": 12,
    }
    return mapping.get(label)


def parse_mhlw_cash_earnings_yoy_xls(data: bytes) -> list[dict[str, Any]]:
    import xlrd

    book = xlrd.open_workbook(file_contents=data)
    sh = book.sheet_by_index(0)
    out: list[dict[str, Any]] = []
    for r in range(sh.nrows):
        row = sh.row_values(r)
        if not row or not isinstance(row[0], (int, float)) or row[0] < 1900:
            continue
        year = int(row[0])
        for month in range(1, 13):
            col = 7 + month
            if col >= len(row):
                continue
            val = row[col]
            if val in ("", "-", None, "***"):
                continue
            try:
                yoy = float(val)
            except (TypeError, ValueError):
                continue
            period = f"{year:04d}-{month:02d}"
            if period_in_window_monthly(period):
                out.append({"reference_period": period, "value": yoy})
    return out


def discover_esri_gdp_csv_url(*, fetcher: Callable[[str], bytes] | None = None) -> str:
    pinned = SOURCE_CONTRACT["Activity.gdp_domestic_demand"]["pinned_csv_url"]
    tops = (
        "https://www.esri.cao.go.jp/jp/sna/sokuhou/sokuhou_top.html",
        "https://www.esri.cao.go.jp/en/sna/sokuhou/sokuhou_top.html",
    )
    html = ""
    for top in tops:
        try:
            raw = fetcher(top) if fetcher else fetch_bytes(top, user_agent=BROWSER_USER_AGENT)
        except Exception:
            try:
                raw = fetch_bytes(top, user_agent=BROWSER_USER_AGENT)
            except Exception:
                continue
        if raw[:5] == b"<!DOC":
            continue
        html = raw.decode("utf-8", errors="replace")
        break
    if html:
        menu_path = re.search(
            r"/jp/sna/data/data_list/sokuhou/files/\d+/qe\d+_\d+/tables/nritu-jk\d+\.csv",
            html,
        )
        if menu_path:
            return "https://www.esri.cao.go.jp" + menu_path.group(0)
    return pinned


def parse_esri_real_gdp_qoq_saar_csv(text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    out: list[dict[str, Any]] = []
    year_carry: int | None = None
    quarter_map = {"1- 3.": 1, "4- 6.": 2, "7- 9.": 3, "10-12.": 4}
    for line in lines:
        if not line.strip() or line.startswith("実質") or line.startswith("Real"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if not parts:
            continue
        head = parts[0]
        ym = re.match(r"(\d{4})/\s*(\d)-\s*(\d)\.", head)
        if ym:
            year_carry = int(ym.group(1))
            q_label = f"{ym.group(2)}- {ym.group(3)}."
            q = quarter_map.get(q_label)
            if q and len(parts) > 1 and parts[1]:
                try:
                    gdp = float(parts[1])
                except ValueError:
                    continue
                period = f"{year_carry}-Q{q}"
                if period_in_window_quarter(period):
                    out.append({"reference_period": period, "value": gdp})
            continue
        qm = re.match(r"(\d)-\s*(\d)\.", head)
        if qm and year_carry:
            q_label = f"{qm.group(1)}- {qm.group(2)}."
            q = quarter_map.get(q_label)
            if q and len(parts) > 1 and parts[1]:
                try:
                    gdp = float(parts[1])
                except ValueError:
                    continue
                period = f"{year_carry}-Q{q}"
                if period_in_window_quarter(period):
                    out.append({"reference_period": period, "value": gdp})
    return out


def parse_meti_retail_yoy_xlsx(data: bytes) -> list[dict[str, Any]]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb["DB_MainC_Graph"]
    out: list[dict[str, Any]] = []
    for row in ws.iter_rows(min_row=5, values_only=True):
        if not row or not row[1]:
            continue
        ym = str(row[1])
        m = re.match(r"(\d{4})年(\d{1,2})月", ym)
        if not m:
            continue
        period = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"
        if not period_in_window_monthly(period):
            continue
        try:
            retail_yoy = float(row[5])
        except (TypeError, ValueError, IndexError):
            continue
        out.append({"reference_period": period, "value": retail_yoy})
    return out


def _fies_longtime_column_periods(sh) -> dict[int, str]:
    """Map column index -> YYYY-MM for Statistics Bureau FIES longtime xls layout."""
    year_row = sh.row_values(10)
    month_row = sh.row_values(11)
    periods: dict[int, str] = {}
    year: int | None = None
    for c in range(max(len(year_row), len(month_row))):
        y_cell = year_row[c] if c < len(year_row) else None
        if isinstance(y_cell, str):
            m = re.search(r"\((\d{4})年\)", y_cell)
            if m:
                year = int(m.group(1))
        m_cell = month_row[c] if c < len(month_row) else None
        if isinstance(m_cell, str) and "月" in m_cell and year is not None:
            month_digits = re.sub(r"\D", "", m_cell)
            if not month_digits:
                continue
            month = int(month_digits)
            periods[c] = f"{year:04d}-{month:02d}"
    return periods


def parse_fies_estat_nominal_yoy_xlsx(data: bytes, *, row_label: str) -> list[dict[str, Any]]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb["名目増減率（月）"]
    year_row = list(ws.iter_rows(min_row=10, max_row=10, values_only=True))[0]
    month_row = list(ws.iter_rows(min_row=12, max_row=12, values_only=True))[0]
    periods: dict[int, str] = {}
    for c, y_cell in enumerate(year_row):
        if isinstance(y_cell, str) and re.fullmatch(r"\d{4}年", y_cell.strip()):
            year = int(y_cell[:4])
            for i in range(12):
                col = c + i
                if col >= len(month_row):
                    break
                m_cell = month_row[col]
                if not isinstance(m_cell, str) or "月" not in m_cell:
                    break
                month_digits = re.sub(r"\D", "", m_cell)
                if not month_digits:
                    break
                periods[col] = f"{year:04d}-{int(month_digits):02d}"
    data_row = None
    for row in ws.iter_rows(min_row=14, values_only=True):
        if any(cell == row_label for cell in row if cell):
            data_row = row
            break
    if data_row is None:
        raise ValueError(f"Row {row_label!r} not found in e-Stat FIES nominal YoY sheet")
    out: list[dict[str, Any]] = []
    for col, period in periods.items():
        if col >= len(data_row):
            continue
        val = data_row[col]
        if val in (None, "", "...", "-", "***"):
            continue
        try:
            yoy = float(val)
        except (TypeError, ValueError):
            continue
        if period_in_window_monthly(period):
            out.append({"reference_period": period, "value": yoy})
    if not out:
        raise ValueError(f"No observations parsed for e-Stat FIES row {row_label!r}")
    return out


def parse_fies_nominal_yoy_row_xls(data: bytes, *, row_label: str) -> list[dict[str, Any]]:
    import xlrd

    book = xlrd.open_workbook(file_contents=data)
    sh = book.sheet_by_name("名目増減率（月）")
    periods = _fies_longtime_column_periods(sh)
    data_row = None
    for r in range(sh.nrows):
        row = sh.row_values(r)
        if any(isinstance(c, str) and row_label in c for c in row):
            data_row = row
            break
    if data_row is None:
        raise ValueError(f"Row {row_label!r} not found in FIES nominal YoY sheet")
    out: list[dict[str, Any]] = []
    for c, period in periods.items():
        if c >= len(data_row):
            continue
        val = data_row[c]
        if val in ("", None, "...", "-", "***"):
            continue
        try:
            yoy = float(val)
        except (TypeError, ValueError):
            continue
        if period_in_window_monthly(period):
            out.append({"reference_period": period, "value": yoy})
    if not out:
        raise ValueError(f"No observations parsed for FIES row {row_label!r}")
    return out


def parse_consumer_confidence_xlsx(data: bytes) -> list[dict[str, Any]]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    out: list[dict[str, Any]] = []
    for row in ws.iter_rows(min_row=7, values_only=True):
        code = row[0]
        if code is None:
            continue
        code_s = str(code).strip()
        if not re.fullmatch(r"\d{10}", code_s):
            continue
        year = int(code_s[:4])
        month = int(code_s[6:8])
        period = f"{year:04d}-{month:02d}"
        if not period_in_window_monthly(period):
            continue
        try:
            index_val = float(row[4])
        except (TypeError, ValueError, IndexError):
            continue
        out.append({"reference_period": period, "value": index_val})
    if not out:
        raise ValueError("Could not parse consumer confidence observations")
    return out


def parse_tankan_large_mfg_di_zip(data: bytes) -> list[dict[str, Any]]:
    """Optional context: large manufacturing business conditions DI (quarterly)."""
    out: list[dict[str, Any]] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not names:
            return out
        text = zf.read(names[0]).decode("cp932", errors="replace")
    for line in text.splitlines():
        if "Large" in line and "Manufacturing" in line:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2:
                try:
                    val = float(parts[-1])
                    out.append({"reference_period": "latest", "value": val, "notes": line[:120]})
                except ValueError:
                    pass
            break
    return out


def observation(
    *,
    reference_period: str,
    value: float,
    component_key: str,
    series_id: str,
    source_url: str,
    publisher: str,
    transformation: str,
    units: str,
    retrieved_at: str,
    notes: str = "",
    sa: bool | None = None,
) -> dict[str, Any]:
    obs: dict[str, Any] = {
        "reference_period": reference_period,
        "value": value,
        "units": units,
        "transformation": transformation,
        "vintage": "latest_available",
        "retrieved_at": retrieved_at,
        "publisher": publisher,
        "source_url": source_url,
        "series_id": series_id,
        "release_date": "",
    }
    if notes:
        obs["notes"] = notes
    if sa is not None:
        obs["sa"] = sa
    return obs


def component_shell(
    *,
    dimension: str,
    component: str,
    canonical_name: str,
    publisher: str,
    series_id: str,
    cadence: str,
    units: str,
    transformation: str,
    sa: bool,
    source_urls: list[str],
    retrieval_method: str,
    score_role: str = "scored",
) -> dict[str, Any]:
    return {
        "dimension": dimension,
        "component": component,
        "canonical_name": canonical_name,
        "publisher": publisher,
        "distributor": publisher,
        "series_id": series_id,
        "cadence": cadence,
        "units": units,
        "preferred_scoring_transformation": transformation,
        "sa": sa,
        "source_urls": source_urls,
        "original_authority_url": source_urls[0] if source_urls else "",
        "retrieval_method": retrieval_method,
        "score_role": score_role,
        "methodology_breaks": [],
        "observations": [],
        "gaps": [],
    }


@dataclass
class CollectResult:
    components: dict[str, Any]
    errors: list[str]
    raw_paths: list[str]


def collect_japan_macro(
    *,
    retrieved_at: str | None = None,
    fetcher: Callable[[str], bytes] | None = None,
    save_raw: bool = True,
) -> CollectResult:
    retrieved_at = retrieved_at or utc_now_iso()

    def fetch(url: str) -> bytes:
        if fetcher:
            return fetcher(url)
        return _curl_get(url)

    errors: list[str] = []
    raw_paths: list[str] = []
    components: dict[str, Any] = {}

    def save_raw_bytes(name: str, data: bytes) -> str:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        path = RAW_DIR / name
        if save_raw:
            path.write_bytes(data)
        raw_paths.append(str(path.relative_to(_ROOT)))
        return str(path)

    # --- CPI ---
    cpi_url = ESTAT_FILE_DOWNLOAD.format(sid=SOURCE_CONTRACT["Inflation.headline"]["stat_infid"], fk=1)
    try:
        cpi_bytes = download_estat(SOURCE_CONTRACT["Inflation.headline"]["stat_infid"], 1, fetcher=fetcher)
        save_raw_bytes("estat_cpi_2025base_yoy.csv", cpi_bytes)
        cpi_text = cpi_bytes.decode("cp932", errors="replace")
        headline, underlying = parse_cpi_yoy_csv(cpi_text)
        components["Inflation.headline"] = component_shell(
            dimension="Inflation",
            component="headline",
            canonical_name="Consumer Price Index, all items, 12-month percent change (2025 base)",
            publisher="Statistics Bureau of Japan",
            series_id=SOURCE_CONTRACT["Inflation.headline"]["series_id"],
            cadence="monthly",
            units="percent",
            transformation="yoy_pct",
            sa=False,
            source_urls=[cpi_url, "https://www.e-stat.go.jp/stat-search/files?layout=dataset&toukei=00200573"],
            retrieval_method="estat_file_download_csv",
        )
        components["Inflation.underlying"] = component_shell(
            dimension="Inflation",
            component="underlying",
            canonical_name="CPI less fresh food and energy, 12-month percent change (2025 base; BOJ core-core style)",
            publisher="Statistics Bureau of Japan",
            series_id=SOURCE_CONTRACT["Inflation.underlying"]["series_id"],
            cadence="monthly",
            units="percent",
            transformation="yoy_pct",
            sa=False,
            source_urls=[cpi_url],
            retrieval_method="estat_file_download_csv",
        )
        components["Inflation.headline"]["methodology_breaks"] = [
            {
                "period": "2025-01",
                "note": "2025-base CPI introduced; y/y series in e-Stat table 000032103932 uses 2025-base weights from 2025-01.",
            }
        ]
        for item in headline:
            components["Inflation.headline"]["observations"].append(
                observation(
                    reference_period=item["reference_period"],
                    value=item["value"],
                    component_key="Inflation.headline",
                    series_id=SOURCE_CONTRACT["Inflation.headline"]["series_id"],
                    source_url=cpi_url,
                    publisher="Statistics Bureau of Japan",
                    transformation="yoy_pct",
                    units="percent",
                    retrieved_at=retrieved_at,
                )
            )
        for item in underlying:
            components["Inflation.underlying"]["observations"].append(
                observation(
                    reference_period=item["reference_period"],
                    value=item["value"],
                    component_key="Inflation.underlying",
                    series_id=SOURCE_CONTRACT["Inflation.underlying"]["series_id"],
                    source_url=cpi_url,
                    publisher="Statistics Bureau of Japan",
                    transformation="yoy_pct",
                    units="percent",
                    retrieved_at=retrieved_at,
                )
            )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Inflation: {exc}")

    # --- Labor ---
    lfs_url = ESTAT_FILE_DOWNLOAD.format(sid=SOURCE_CONTRACT["Labor.unemployment"]["stat_infid"], fk=0)
    try:
        lfs_bytes = download_estat(SOURCE_CONTRACT["Labor.unemployment"]["stat_infid"], 0, fetcher=fetcher)
        save_raw_bytes("estat_lfs_1a1_major_items.xlsx", lfs_bytes)
        unemp, emp, _ = parse_lfs_major_items_xlsx(lfs_bytes)
        components["Labor.unemployment"] = component_shell(
            dimension="Labor",
            component="unemployment",
            canonical_name="Unemployment rate, seasonally adjusted, whole Japan",
            publisher="Statistics Bureau of Japan",
            series_id=SOURCE_CONTRACT["Labor.unemployment"]["series_id"],
            cadence="monthly",
            units="percent",
            transformation="rate_pct",
            sa=True,
            source_urls=[lfs_url],
            retrieval_method="estat_file_download_xlsx",
        )
        components["Labor.employment"] = component_shell(
            dimension="Labor",
            component="employment",
            canonical_name="Month-on-month change in employed persons (seasonally adjusted), derived from LFS 1-a-1",
            publisher="Statistics Bureau of Japan",
            series_id=SOURCE_CONTRACT["Labor.employment"]["series_id"],
            cadence="monthly",
            units="thousands",
            transformation="mom_change_thousands_sa",
            sa=True,
            source_urls=[lfs_url],
            retrieval_method="estat_file_download_xlsx_derived",
        )
        components["Labor.employment"]["notes"] = (
            "Employed persons level is published in 万人 (ten-thousand persons); "
            "mom_change_thousands_sa = (level_t - level_t-1) * 10."
        )
        for item in unemp:
            components["Labor.unemployment"]["observations"].append(
                observation(
                    reference_period=item["reference_period"],
                    value=item["value"],
                    component_key="Labor.unemployment",
                    series_id=SOURCE_CONTRACT["Labor.unemployment"]["series_id"],
                    source_url=lfs_url,
                    publisher="Statistics Bureau of Japan",
                    transformation="rate_pct",
                    units="percent",
                    retrieved_at=retrieved_at,
                    sa=True,
                )
            )
        for item in emp:
            components["Labor.employment"]["observations"].append(
                observation(
                    reference_period=item["reference_period"],
                    value=item["value"],
                    component_key="Labor.employment",
                    series_id=SOURCE_CONTRACT["Labor.employment"]["series_id"],
                    source_url=lfs_url,
                    publisher="Statistics Bureau of Japan",
                    transformation="mom_change_thousands_sa",
                    units="thousands",
                    retrieved_at=retrieved_at,
                    sa=True,
                )
            )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Labor.unemployment/employment: {exc}")

    wages_url = ESTAT_FILE_DOWNLOAD.format(sid=SOURCE_CONTRACT["Labor.wages"]["stat_infid"], fk=4)
    try:
        wage_bytes = download_estat(SOURCE_CONTRACT["Labor.wages"]["stat_infid"], 4, fetcher=fetcher)
        save_raw_bytes("estat_mhlw_total_cash_earnings_yoy.xls", wage_bytes)
        wages = parse_mhlw_cash_earnings_yoy_xls(wage_bytes)
        components["Labor.wages"] = component_shell(
            dimension="Labor",
            component="wages",
            canonical_name="Total cash earnings, year-on-year percent change, establishments with 5+ employees",
            publisher="Ministry of Health, Labour and Welfare",
            series_id=SOURCE_CONTRACT["Labor.wages"]["series_id"],
            cadence="monthly",
            units="percent",
            transformation="yoy_pct",
            sa=False,
            source_urls=[wages_url, "https://www.e-stat.go.jp/stat-search/files?toukei=00450071"],
            retrieval_method="estat_file_download_xls",
        )
        components["Labor.wages"]["notes"] = (
            "Nominal total cash earnings (現金給与総額), includes scheduled and non-scheduled pay; "
            "overtime-sensitive versus contractual/scheduled-only series also published in the same table set."
        )
        for item in wages:
            components["Labor.wages"]["observations"].append(
                observation(
                    reference_period=item["reference_period"],
                    value=item["value"],
                    component_key="Labor.wages",
                    series_id=SOURCE_CONTRACT["Labor.wages"]["series_id"],
                    source_url=wages_url,
                    publisher="Ministry of Health, Labour and Welfare",
                    transformation="yoy_pct",
                    units="percent",
                    retrieved_at=retrieved_at,
                )
            )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Labor.wages: {exc}")

    # --- GDP ---
    try:
        gdp_csv_url = discover_esri_gdp_csv_url(fetcher=fetch)
        try:
            gdp_bytes = fetch(gdp_csv_url)
        except Exception:
            gdp_bytes = fetch_bytes(gdp_csv_url, user_agent=BROWSER_USER_AGENT)
        save_raw_bytes(Path(gdp_csv_url).name, gdp_bytes)
        gdp_text = gdp_bytes.decode("cp932", errors="replace")
        gdp_obs = parse_esri_real_gdp_qoq_saar_csv(gdp_text)
        components["Activity.gdp_domestic_demand"] = component_shell(
            dimension="Activity",
            component="gdp_domestic_demand",
            canonical_name="Real GDP, seasonally adjusted quarter-on-quarter annualized rate (expenditure approach)",
            publisher="Cabinet Office (ESRI)",
            series_id=SOURCE_CONTRACT["Activity.gdp_domestic_demand"]["series_id"],
            cadence="quarterly",
            units="percent",
            transformation="qoq_pct_saar",
            sa=True,
            source_urls=[gdp_csv_url, "https://www.esri.cao.go.jp/en/sna/sokuhou/sokuhou_top.html"],
            retrieval_method="esri_sna_sokuhou_csv",
        )
        components["Activity.gdp_domestic_demand"]["notes"] = (
            "Uses real GDP (first column) from nritu-jk* SA q/q annualized table; "
            "latest vintage revises historical quarters each release."
        )
        for item in gdp_obs:
            components["Activity.gdp_domestic_demand"]["observations"].append(
                observation(
                    reference_period=item["reference_period"],
                    value=item["value"],
                    component_key="Activity.gdp_domestic_demand",
                    series_id=SOURCE_CONTRACT["Activity.gdp_domestic_demand"]["series_id"],
                    source_url=gdp_csv_url,
                    publisher="Cabinet Office (ESRI)",
                    transformation="qoq_pct_saar",
                    units="percent",
                    retrieved_at=retrieved_at,
                    sa=True,
                )
            )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Activity.gdp_domestic_demand: {exc}")

    # --- Retail ---
    meti_url = "https://www.meti.go.jp/statistics/tyo/syoudou/result/excel/DB_202607S.xlsx"
    try:
        meti_bytes = fetch(meti_url)
        save_raw_bytes("meti_commerce_survey_DB_202607S.xlsx", meti_bytes)
        retail = parse_meti_retail_yoy_xlsx(meti_bytes)
        components["Consumer.retail"] = component_shell(
            dimension="Consumer",
            component="retail",
            canonical_name="Retail sales value, year-on-year percent change (Current Survey of Commerce)",
            publisher="Ministry of Economy, Trade and Industry",
            series_id=SOURCE_CONTRACT["Consumer.retail"]["series_id"],
            cadence="monthly",
            units="percent",
            transformation="yoy_pct",
            sa=True,
            source_urls=[meti_url, "https://www.meti.go.jp/english/statistics/tyo/syoudou/index.html"],
            retrieval_method="meti_commerce_survey_excel",
        )
        for item in retail:
            components["Consumer.retail"]["observations"].append(
                observation(
                    reference_period=item["reference_period"],
                    value=item["value"],
                    component_key="Consumer.retail",
                    series_id=SOURCE_CONTRACT["Consumer.retail"]["series_id"],
                    source_url=meti_url,
                    publisher="Ministry of Economy, Trade and Industry",
                    transformation="yoy_pct",
                    units="percent",
                    retrieved_at=retrieved_at,
                    sa=True,
                )
            )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Consumer.retail: {exc}")

    # --- FIES income / spending ---
    income_url = ESTAT_FILE_DOWNLOAD.format(
        sid=SOURCE_CONTRACT["Consumer.income"]["stat_infid"],
        fk=SOURCE_CONTRACT["Consumer.income"]["file_kind"],
    )
    try:
        income_bytes = download_estat(
            SOURCE_CONTRACT["Consumer.income"]["stat_infid"],
            SOURCE_CONTRACT["Consumer.income"]["file_kind"],
            fetcher=fetcher,
        )
        save_raw_bytes("estat_fies_worker_income_nominal_yoy.xlsx", income_bytes)
        income = parse_fies_estat_nominal_yoy_xlsx(income_bytes, row_label="実収入")
        components["Consumer.income"] = component_shell(
            dimension="Consumer",
            component="income",
            canonical_name="Real income, nominal year-on-year percent change, worker households (two-or-more-person)",
            publisher="Statistics Bureau of Japan",
            series_id=SOURCE_CONTRACT["Consumer.income"]["series_id"],
            cadence="monthly",
            units="percent",
            transformation="yoy_pct",
            sa=False,
            source_urls=[income_url, "https://www.stat.go.jp/data/kakei/longtime/index.htm"],
            retrieval_method="estat_file_download_xlsx",
        )
        components["Consumer.income"]["notes"] = (
            "FIES Table 2 long-term series (e-Stat statInfId=000040270658): worker households among "
            "two-or-more-person households; 実収入 nominal y/y."
        )
        for item in income:
            components["Consumer.income"]["observations"].append(
                observation(
                    reference_period=item["reference_period"],
                    value=item["value"],
                    component_key="Consumer.income",
                    series_id=SOURCE_CONTRACT["Consumer.income"]["series_id"],
                    source_url=income_url,
                    publisher="Statistics Bureau of Japan",
                    transformation="yoy_pct",
                    units="percent",
                    retrieved_at=retrieved_at,
                )
            )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Consumer.income: {exc}")

    spend_url = ESTAT_FILE_DOWNLOAD.format(
        sid=SOURCE_CONTRACT["Consumer.spending"]["stat_infid"],
        fk=SOURCE_CONTRACT["Consumer.spending"]["file_kind"],
    )
    try:
        spend_bytes = download_estat(
            SOURCE_CONTRACT["Consumer.spending"]["stat_infid"],
            SOURCE_CONTRACT["Consumer.spending"]["file_kind"],
            fetcher=fetcher,
        )
        save_raw_bytes("estat_fies_two_plus_consumption_nominal_yoy.xlsx", spend_bytes)
        spending = parse_fies_estat_nominal_yoy_xlsx(spend_bytes, row_label="消費支出")
        components["Consumer.spending"] = component_shell(
            dimension="Consumer",
            component="spending",
            canonical_name="Consumption expenditure, nominal year-on-year percent change, two-or-more-person households",
            publisher="Statistics Bureau of Japan",
            series_id=SOURCE_CONTRACT["Consumer.spending"]["series_id"],
            cadence="monthly",
            units="percent",
            transformation="yoy_pct",
            sa=False,
            source_urls=[spend_url, "https://www.stat.go.jp/data/kakei/longtime/index.htm"],
            retrieval_method="estat_file_download_xlsx",
        )
        for item in spending:
            components["Consumer.spending"]["observations"].append(
                observation(
                    reference_period=item["reference_period"],
                    value=item["value"],
                    component_key="Consumer.spending",
                    series_id=SOURCE_CONTRACT["Consumer.spending"]["series_id"],
                    source_url=spend_url,
                    publisher="Statistics Bureau of Japan",
                    transformation="yoy_pct",
                    units="percent",
                    retrieved_at=retrieved_at,
                )
            )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Consumer.spending: {exc}")

    # --- Consumer confidence ---
    cci_url = ESTAT_FILE_DOWNLOAD.format(sid=SOURCE_CONTRACT["Consumer.confidence"]["stat_infid"], fk=0)
    try:
        cci_bytes = download_estat(SOURCE_CONTRACT["Consumer.confidence"]["stat_infid"], 0, fetcher=fetcher)
        save_raw_bytes("estat_consumer_confidence_longterm.xlsx", cci_bytes)
        cci = parse_consumer_confidence_xlsx(cci_bytes)
        components["Consumer.confidence"] = component_shell(
            dimension="Consumer",
            component="confidence",
            canonical_name="Consumer Sentiment Index (seasonally adjusted), two-or-more-person households",
            publisher="Cabinet Office",
            series_id=SOURCE_CONTRACT["Consumer.confidence"]["series_id"],
            cadence="monthly",
            units="index",
            transformation="diffusion_index",
            sa=True,
            source_urls=[cci_url, "https://www.esri.cao.go.jp/jp/stat/shouhi/shouhi.html"],
            retrieval_method="estat_file_download_xlsx",
        )
        for item in cci:
            components["Consumer.confidence"]["observations"].append(
                observation(
                    reference_period=item["reference_period"],
                    value=item["value"],
                    component_key="Consumer.confidence",
                    series_id=SOURCE_CONTRACT["Consumer.confidence"]["series_id"],
                    source_url=cci_url,
                    publisher="Cabinet Office",
                    transformation="diffusion_index",
                    units="index",
                    retrieved_at=retrieved_at,
                    sa=True,
                )
            )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Consumer.confidence: {exc}")

    # --- PMI placeholder shell (filled by harvest_jp_pmi) ---
    components["Activity.business_surveys"] = component_shell(
        dimension="Activity",
        component="business_surveys",
        canonical_name="au Jibun Bank / S&P Global Japan Composite PMI Output Index",
        publisher="S&P Global / au Jibun Bank",
        series_id="SP_GLOBAL_JP_COMPOSITE_PMI",
        cadence="monthly",
        units="diffusion_index",
        transformation="diffusion_index",
        sa=True,
        source_urls=["https://www.pmi.spglobal.com/Public/Release/PressReleases"],
        retrieval_method="sp_global_press_release_pdf",
    )
    components["Activity.business_surveys"]["gaps"] = [
        {
            "expected_period": "2025-09",
            "reason": "awaiting PMI harvester merge",
            "attempted_sources": ["scripts/harvest_jp_pmi.py"],
            "notes": "Run harvest_jp_pmi.py --write-jp-json to populate.",
        }
    ]

    # --- Tankan context (optional, not scored) ---
    tankan_url = "https://www.boj.or.jp/en/statistics/tk/gaiyo/2026/tka2606.zip"
    try:
        tankan_bytes = fetch(tankan_url)
        save_raw_bytes("boj_tankan_2026q2.zip", tankan_bytes)
        components["context.Tankan_large_manufacturing_di"] = component_shell(
            dimension="context",
            component="Tankan_large_manufacturing_di",
            canonical_name="Tankan large manufacturing business conditions DI (context only)",
            publisher="Bank of Japan",
            series_id=SOURCE_CONTRACT["context.Tankan_large_manufacturing_di"]["series_id"],
            cadence="quarterly",
            units="diffusion_index",
            transformation="diffusion_index",
            sa=False,
            source_urls=[tankan_url],
            retrieval_method="boj_tankan_zip",
            score_role="context",
        )
        for item in parse_tankan_large_mfg_di_zip(tankan_bytes):
            components["context.Tankan_large_manufacturing_di"]["observations"].append(
                observation(
                    reference_period=item["reference_period"],
                    value=item["value"],
                    component_key="context.Tankan_large_manufacturing_di",
                    series_id=SOURCE_CONTRACT["context.Tankan_large_manufacturing_di"]["series_id"],
                    source_url=tankan_url,
                    publisher="Bank of Japan",
                    transformation="diffusion_index",
                    units="diffusion_index",
                    retrieved_at=retrieved_at,
                    notes=item.get("notes", ""),
                )
            )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"context.Tankan (optional): {exc}")

    required = [
        "Inflation.headline",
        "Inflation.underlying",
        "Labor.unemployment",
        "Labor.wages",
        "Labor.employment",
        "Activity.gdp_domestic_demand",
        "Consumer.retail",
        "Consumer.income",
        "Consumer.spending",
        "Consumer.confidence",
    ]
    for key in required:
        if key not in components or not components[key].get("observations"):
            errors.append(f"Missing required observations for {key}")

    return CollectResult(components=components, errors=errors, raw_paths=raw_paths)


def build_jp_json(result: CollectResult, *, retrieved_at: str | None = None) -> dict[str, Any]:
    retrieved_at = retrieved_at or utc_now_iso()
    return {
        "country": "JP",
        "window": {"start": WINDOW_START.isoformat(), "end": WINDOW_END.isoformat()},
        "retrieved_at": retrieved_at,
        "notes": (
            "Japan G0 macro backfill via e-Stat file downloads, ESRI GDP CSV, METI commerce survey, "
            "and Statistics Bureau FIES longtime tables. PMI merged separately via harvest_jp_pmi.py."
        ),
        "components": result.components,
        "collection_errors": result.errors,
        "raw_artifacts": result.raw_paths,
    }


def write_jp_json(payload: dict[str, Any], path: Path = JP_JSON) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect Japan macro temperature source observations")
    parser.add_argument("--live", action="store_true", help="Fetch live official sources and write jp.json")
    parser.add_argument("--output", default=str(JP_JSON))
    args = parser.parse_args()
    if not args.live:
        print("Use --live to fetch official sources.")
        return 0
    result = collect_japan_macro()
    payload = build_jp_json(result)
    write_jp_json(payload, Path(args.output))
    print(json.dumps({"errors": result.errors, "components": list(result.components.keys())}))
    if result.errors:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
