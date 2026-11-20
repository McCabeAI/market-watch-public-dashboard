#!/usr/bin/env python3
"""Deterministic Market Watch market-state generator.

No model calls. No API keys. Live official/ECB authorities remain the source
of truth. The script fetches sovereign yield history and ECB G10 FX reference
history, computes a compact research snapshot, and exits non-zero if a
required source is missing or fabricated substitution would be required.

This is research/reference state, not executable pricing.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from html.parser import HTMLParser
from pathlib import Path
from typing import Mapping, Sequence

from scripts.australia_housing_data import collect_australia_housing, validate_australia_housing


def _relative_rate_analytics(tradable: object, fx_pairs: object) -> dict:
    from scripts.rates.read_model import build_relative_analytics

    pairs = fx_pairs if isinstance(fx_pairs, dict) else {}
    curves = tradable if isinstance(tradable, dict) else {}
    return build_relative_analytics({"tradable_rate_curves": curves, "fx": {"pairs": pairs}})
from scripts.canada_housing_data import collect_canada_housing, validate_canada_housing
from scripts.country_registry import (
    extra_rate_tenor,
    rate_countries,
    required_preflight_countries,
    rv_pairs as registry_rv_pairs,
    stale_after_days,
)
from scripts.euro_area_rates_data import (
    BUNDESBANK_PAGE,
    collect_ea_fragmentation,
    fetch_ea_bund_rates,
)
from scripts.canada_rates_calendar import (
    CA_FRESHNESS_RULE,
    CA_PUBLICATION_LAG_BUSINESS_DAYS,
    ca_observation_status,
    canada_business_days_since,
    minimum_fresh_ca_observation,
)
from scripts.japan_rates_data import (
    MOF_JGB_CURRENT_EN,
    MOF_JGB_PAGE_EN,
    fetch_jp_jgb_rates,
    japan_business_days_since,
    jgb_observation_status,
)
from scripts.us_housing_data import collect_us_housing, validate_us_housing
from scripts.cross_asset_data import collect_cross_assets, compact_cross_assets, stamp_latest_values
from scripts.market_opportunities import build_opportunities
from scripts.official_curve_data import collect_official_curves, validate_official_curves
from scripts.positioning_data import build_positioning, validate_positioning
from scripts.policy_path_data import (
    build_tradable_rate_curves,
    collect_policy_paths,
    validate_policy_paths,
    validate_tradable_rate_curves,
)

USER_AGENT = (
    "MarketWatch-MarketState/1.0 "
    "(+https://github.com/McCabeAI/market-watch-public-dashboard)"
)
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT = 45
RETRIES = 3
ECB_TIMEOUT = 90
ECB_RETRIES = 4

G10 = ("EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "NOK", "SEK", "JPY")
FX_ORDER = G10
RATE_TENORS = ("2Y", "5Y", "10Y")
RATE_COUNTRIES = rate_countries()
RV_PAIRS = registry_rv_pairs()
CORE_RV_PAIRS = (("CA", "US"), ("AU", "US"), ("CA", "AU"))
# Preserve published RV key order for existing pairs (CA-US, not US-CA).
_RV_LEG_ORDER = {
    frozenset({"CA", "US"}): ("CA", "US"),
    frozenset({"AU", "US"}): ("AU", "US"),
    frozenset({"NZ", "US"}): ("NZ", "US"),
    frozenset({"AU", "NZ"}): ("AU", "NZ"),
    frozenset({"CA", "AU"}): ("CA", "AU"),
}
REQUIRED_POLICY_COUNTRIES = ("US", "CA", "AU")
REQUIRED_OFFICIAL_CURVE_COUNTRIES = ("US", "CA", "AU")
UNAVAILABLE_OK_RATE_COUNTRIES = frozenset(RATE_COUNTRIES)

# Daily sources may miss weekends/holidays. RBA F2 is weekly with a 2-business-day lag.
STALE_AFTER_DAYS = stale_after_days()
FAIL_AFTER_DAYS = 21

TREASURY_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/{year}/all?_format=csv&field_tdr_date_value={year}"
    "&page=&type=daily_treasury_yield_curve"
)
TREASURY_PAGE = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "TextView?type=daily_treasury_yield_curve"
)
BOC_SERIES = {
    "BD.CDN.2YR.DQ.YLD": "2Y",
    "BD.CDN.5YR.DQ.YLD": "5Y",
    "BD.CDN.10YR.DQ.YLD": "10Y",
    "BD.CDN.LONG.DQ.YLD": "LONG",
}
BOC_GROUP_URL = "https://www.bankofcanada.ca/valet/observations/group/bond_yields_benchmark/json"
BOC_SERIES_URL = "https://www.bankofcanada.ca/valet/observations/{series}/json"
BOC_DOCS = "https://www.bankofcanada.ca/valet/docs/"
RBA_URL = "https://www.rba.gov.au/statistics/tables/csv/f2-data.csv"
RBA_PAGE = "https://www.rba.gov.au/statistics/tables/"
RBNZ_URL = "https://www.rbnz.govt.nz/-/media/project/sites/rbnz/files/statistics/series/b/b2/hb2-daily-close.xlsx"
RBNZ_PAGE = (
    "https://www.rbnz.govt.nz/statistics/series/exchange-and-interest-rates/"
    "wholesale-interest-rates"
)
RBNZ_HTML_URL = RBNZ_PAGE
ECB_FX_SDMX_URL = (
    "https://data-api.ecb.europa.eu/service/data/EXR/"
    "D.{currencies}.EUR.SP00.A"
)
ECB_FX_PAGE = (
    "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/"
    "euro_reference_exchange_rates/html/index.en.html"
)
# Classic hist CSV is retained only as a parser test fixture. The public
# eurofxref-hist.csv file is not used in production because CDN copies have
# been observed stale or corrupted; SDMX is the live official series.


class MarketStateError(RuntimeError):
    """Hard failure: a required official source or calculation is unusable."""


def fetch_bytes(
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = RETRIES,
    user_agent: str | None = None,
    referer: str | None = None,
) -> bytes:
    last: Exception | None = None
    headers = {
        "User-Agent": user_agent or USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    if "rbnz.govt.nz" in url:
        headers["Referer"] = RBNZ_PAGE
        headers["Accept"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = getattr(resp, "status", 200)
                if status != 200:
                    raise MarketStateError(f"HTTP {status} from {url}")
                data = resp.read()
                if not data:
                    raise MarketStateError(f"empty response from {url}")
                return data
        except urllib.error.HTTPError as exc:
            last = exc
            if attempt + 1 < retries:
                # 5xx and timeouts are retried; 403/404 are still retried a bounded number of times
                time.sleep(2.0 * (attempt + 1) if exc.code >= 500 else 1.5 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError, MarketStateError) as exc:
            last = exc
            if attempt + 1 < retries:
                time.sleep(1.5 * (attempt + 1))
    if isinstance(last, urllib.error.HTTPError) and last.code == 403 and "rbnz.govt.nz" in url:
        kind = "B2 workbook" if str(url).lower().endswith(".xlsx") else "page"
        raise MarketStateError(
            f"RBNZ official {kind} returned HTTP 403 from {url}. "
            "Refusing to substitute a third-party or vendor feed."
        ) from last
    raise MarketStateError(f"failed to fetch {url}: {last}")


def parse_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%d-%b-%Y", "%Y/%m/%d", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def to_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return float(value)
    s = str(value).strip().replace("%", "").replace(",", "")
    if not s or s in {"..", "-", "—", "n/a", "NA", "na"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def filter_since(series: Mapping[date, float], start: date) -> dict[date, float]:
    return {d: v for d, v in series.items() if d >= start}


def percentile_rank(values: Sequence[float], x: float) -> float | None:
    if not values:
        return None
    lt = sum(v < x for v in values)
    eq = sum(v == x for v in values)
    return 100.0 * (lt + 0.5 * eq) / len(values)


def zscore(values: Sequence[float], x: float) -> float | None:
    if len(values) < 2:
        return None
    sd = statistics.pstdev(values)
    if sd == 0:
        return 0.0
    return (x - statistics.fmean(values)) / sd


def lookback_value(items: Sequence[tuple[date, float]], n_obs: int) -> float | None:
    if len(items) <= n_obs:
        return None
    return items[-1 - n_obs][1]


def _move_analogs(
    series: Mapping[date, float],
    *,
    lookback: int = 21,
    scale: float = 100.0,
    forward_1m: int = 21,
    forward_3m: int = 63,
    count: int = 4,
) -> list[dict]:
    """Closest prior 1-month moves plus subsequent outcomes.

    The dates/math are deterministic. A trader must still explain why an
    episode is economically comparable and which regime differences matter.
    """
    items = sorted(series.items())
    if len(items) <= lookback + forward_3m + 20:
        return []
    current_move = (items[-1][1] - items[-1 - lookback][1]) * scale
    candidates: list[tuple[float, int, dict]] = []
    last_candidate = len(items) - 1 - forward_3m
    for i in range(lookback, last_candidate + 1):
        prior_move = (items[i][1] - items[i - lookback][1]) * scale
        row = {
            "as_of": items[i][0].isoformat(),
            "level": items[i][1],
            "prior_1m_move": round(prior_move, 4),
            "forward_1m_move": round((items[i + forward_1m][1] - items[i][1]) * scale, 4),
            "forward_3m_move": round((items[i + forward_3m][1] - items[i][1]) * scale, 4),
            "distance_from_current_move": round(abs(prior_move - current_move), 4),
        }
        candidates.append((abs(prior_move - current_move), i, row))
    selected: list[dict] = []
    selected_i: list[int] = []
    for _distance, idx, row in sorted(candidates, key=lambda x: x[0]):
        if any(abs(idx - old) < 21 for old in selected_i):
            continue
        selected.append(row)
        selected_i.append(idx)
        if len(selected) >= count:
            break
    return selected


def rate_metrics(series: Mapping[date, float]) -> dict:
    items = sorted(series.items())
    if not items:
        raise MarketStateError("empty rate series")
    latest_date, latest = items[-1]
    vals_1y = [v for _, v in items[-252:]]
    vals_5y = [v for _, v in items[-1260:]]

    def bp(n: int) -> float | None:
        old = lookback_value(items, n)
        return None if old is None else (latest - old) * 100.0

    return {
        "as_of": latest_date.isoformat(),
        "value": latest,
        "bp_1d": bp(1),
        "bp_5d": bp(5),
        "bp_1m": bp(21),
        "bp_3m": bp(63),
        "bp_6m": bp(126),
        "bp_1y": bp(252),
        "historical_move_analogs": _move_analogs(series, scale=100.0),
        "pctile_1y": percentile_rank(vals_1y, latest),
        "pctile_5y": percentile_rank(vals_5y, latest) if len(vals_5y) >= 60 else None,
        "z_1y": zscore(vals_1y, latest),
        "z_5y": zscore(vals_5y, latest) if len(vals_5y) >= 60 else None,
    }


def fx_metrics(series: Mapping[date, float]) -> dict:
    items = sorted(series.items())
    if not items:
        raise MarketStateError("empty FX series")
    latest_date, latest = items[-1]
    vals = [v for _, v in items]
    vals_1y = vals[-252:]
    vals_5y = vals[-1260:]

    def ret(n: int) -> float | None:
        old = lookback_value(items, n)
        return None if old in (None, 0) else 100.0 * (latest / old - 1.0)

    logrets = [math.log(vals[i] / vals[i - 1]) for i in range(1, len(vals)) if vals[i] > 0 and vals[i - 1] > 0]

    def rv(n: int) -> float | None:
        if len(logrets) < n:
            return None
        return statistics.pstdev(logrets[-n:]) * math.sqrt(252.0) * 100.0

    return {
        "as_of": latest_date.isoformat(),
        "spot": latest,
        "ret_1d": ret(1),
        "ret_5d": ret(5),
        "ret_1m": ret(21),
        "ret_3m": ret(63),
        "rv_20d": rv(20),
        "rv_60d": rv(60),
        "pctile_1y": percentile_rank(vals_1y, latest),
        "pctile_5y": percentile_rank(vals_5y, latest) if len(vals_5y) >= 60 else None,
        "z_1y": zscore(vals_1y, latest),
        "z_5y": zscore(vals_5y, latest) if len(vals_5y) >= 60 else None,
    }


def parse_treasury_csv(text: str) -> dict[str, dict[date, float]]:
    out = {"2Y": {}, "5Y": {}, "10Y": {}, "30Y": {}}
    rows = csv.DictReader(io.StringIO(text))
    keymap = {"2Y": "2 Yr", "5Y": "5 Yr", "10Y": "10 Yr", "30Y": "30 Yr"}
    for row in rows:
        d = parse_date(row.get("Date"))
        if not d:
            continue
        for tenor, col in keymap.items():
            v = to_float(row.get(col))
            if v is not None:
                out[tenor][d] = v
    if any(not out[k] for k in ("2Y", "5Y", "10Y", "30Y")):
        raise MarketStateError("Treasury CSV missing required tenors")
    return out


def fetch_us_rates(start: date, end: date) -> dict[str, dict[date, float]]:
    merged = {"2Y": {}, "5Y": {}, "10Y": {}, "30Y": {}}
    for year in range(start.year, end.year + 1):
        text = fetch_bytes(TREASURY_URL.format(year=year)).decode("utf-8-sig")
        parsed = parse_treasury_csv(text)
        for tenor, series in parsed.items():
            merged[tenor].update(series)
    out = {k: filter_since(v, start) for k, v in merged.items()}
    if any(not out[k] for k in ("2Y", "5Y", "10Y", "30Y")):
        raise MarketStateError("Treasury history missing required tenors after date filter")
    return out


def parse_boc_json(payload: Mapping, *, require_all: bool = True) -> dict[str, dict[date, float]]:
    out = {v: {} for v in BOC_SERIES.values()}
    for obs in payload.get("observations", []):
        d = parse_date(obs.get("d"))
        if not d:
            continue
        for sid, tenor in BOC_SERIES.items():
            cell = obs.get(sid)
            value = cell.get("v") if isinstance(cell, Mapping) else cell
            v = to_float(value)
            if v is not None:
                out[tenor][d] = v
    if require_all and (any(not out[k] for k in RATE_TENORS) or not out["LONG"]):
        raise MarketStateError("BoC response missing required benchmark tenors")
    return out


def fetch_ca_rates(start: date, end: date) -> dict[str, dict[date, float]]:
    """Fetch current BoC benchmark bond yields.

    The legacy V39051/V39053/V39055/V39056 series IDs now 404. Use the official
    `bond_yields_benchmark` group, then fail closed if a required tenor is absent.
    """
    qs = urllib.parse.urlencode({"start_date": start.isoformat(), "end_date": end.isoformat()})
    payload = json.loads(fetch_bytes(f"{BOC_GROUP_URL}?{qs}").decode("utf-8"))
    parsed = parse_boc_json(payload)
    missing = [k for k in (*RATE_TENORS, "LONG") if not parsed.get(k)]
    if not missing:
        return parsed
    for series_id, tenor in BOC_SERIES.items():
        if parsed.get(tenor):
            continue
        series_payload = json.loads(fetch_bytes(f"{BOC_SERIES_URL.format(series=series_id)}?{qs}").decode("utf-8"))
        extra = parse_boc_json(series_payload, require_all=False)
        parsed[tenor].update(extra.get(tenor, {}))
    if any(not parsed[k] for k in RATE_TENORS) or not parsed["LONG"]:
        raise MarketStateError("BoC benchmark group missing required tenors")
    return parsed


def parse_rba_csv(text: str) -> dict[str, dict[date, float]]:
    rows = list(csv.reader(io.StringIO(text)))
    metadata: dict[str, list[str]] = {}
    series_row_idx = None
    for i, row in enumerate(rows):
        if not row:
            continue
        first = row[0].strip().lower()
        if first in {"title", "description", "frequency", "type", "units", "source", "publication date", "series id"}:
            metadata[first] = row
        if first == "series id":
            series_row_idx = i
            break
    if series_row_idx is None:
        raise MarketStateError("RBA F2 CSV missing Series ID row")
    selected: dict[int, str] = {}
    for key in ("title", "description"):
        labels = metadata.get(key)
        if not labels:
            continue
        candidate: dict[int, str] = {}
        for idx in range(1, len(labels)):
            label = labels[idx].strip().lower() if idx < len(labels) else ""
            if "indexed" in label:
                continue
            if "australian government" not in label and "government" not in label:
                continue
            for n, tenor in ((2, "2Y"), (5, "5Y"), (10, "10Y")):
                if re.search(rf"\b{n}\s*[- ]?years?\b", label):
                    candidate[idx] = tenor
        if set(candidate.values()) == set(RATE_TENORS):
            selected = candidate
            break
    if set(selected.values()) != set(RATE_TENORS):
        raise MarketStateError(f"RBA F2 tenor discovery failed: {selected}")
    out = {k: {} for k in RATE_TENORS}
    for row in rows[series_row_idx + 1 :]:
        if not row:
            continue
        d = parse_date(row[0])
        if not d:
            continue
        for idx, tenor in selected.items():
            if idx < len(row):
                v = to_float(row[idx])
                if v is not None:
                    out[tenor][d] = v
    if any(not out[k] for k in RATE_TENORS):
        raise MarketStateError("RBA F2 data rows missing required tenors")
    return out


def fetch_au_rates(start: date, end: date) -> dict[str, dict[date, float]]:
    parsed = parse_rba_csv(fetch_bytes(RBA_URL).decode("utf-8-sig", errors="replace"))
    out = {k: {d: v for d, v in s.items() if start <= d <= end} for k, s in parsed.items()}
    if any(not out[k] for k in RATE_TENORS):
        raise MarketStateError("RBA F2 history missing required tenors after date filter")
    return out


def parse_rbnz_xlsx(data: bytes) -> dict[str, dict[date, float]]:
    try:
        import openpyxl
    except ImportError as exc:
        raise MarketStateError("openpyxl is required for the RBNZ workbook") from exc
    # The published B2 workbook sets dimension ref="A1" while the Data sheet
    # holds the full history. read_only mode trusts that dimension and would
    # report tenor discovery failed on an otherwise official file.
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=False, data_only=True)
    best = None
    out = {k: {} for k in RATE_TENORS}
    try:
        for ws in wb.worksheets:
            preview = list(ws.iter_rows(min_row=1, max_row=min(ws.max_row or 40, 40), values_only=True))
            for ri, row in enumerate(preview):
                if not row:
                    continue
                labels = [str(v).strip().lower() if v not in (None, "") else "" for v in row]
                # Current B2 files put dates in column A with no "Date" label.
                # Older fixtures and the HTML table still use an explicit Date header.
                if not any(label == "date" or "year" in label for label in labels):
                    continue
                header_start = max(0, ri - 5)
                max_cols = max(len(r) for r in preview[header_start : ri + 1])
                header_rows = preview[header_start : ri + 1]
                filled_rows = []
                for rr in header_rows:
                    filled = []
                    carry = None
                    for ci in range(max_cols):
                        val = rr[ci] if ci < len(rr) else None
                        if val not in (None, ""):
                            carry = val
                        filled.append(carry)
                    filled_rows.append(filled)
                col_headers: dict[int, str] = {}
                for ci in range(max_cols):
                    parts = []
                    for rr in filled_rows:
                        if rr[ci] not in (None, ""):
                            parts.append(str(rr[ci]).strip())
                    col_headers[ci] = " | ".join(parts).lower()
                selected: dict[int, str] = {}
                for ci, header in col_headers.items():
                    if "government" not in header and "bond" not in header:
                        continue
                    for n, tenor in ((2, "2Y"), (5, "5Y"), (10, "10Y")):
                        if re.search(rf"\b{n}\s*year\b", header):
                            selected[ci] = tenor
                if set(selected.values()) == set(RATE_TENORS):
                    best = (ws, ri + 1, selected)
                    break
            if best:
                break
        if not best:
            raise MarketStateError("RBNZ workbook tenor discovery failed")
        ws, header_row, selected = best
        for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
            if not row:
                continue
            d = None
            for v in row[:3]:
                d = parse_date(v)
                if d:
                    break
            if not d:
                continue
            for ci, tenor in selected.items():
                if ci < len(row):
                    v = to_float(row[ci])
                    if v is not None:
                        out[tenor][d] = v
    finally:
        wb.close()
    if any(not out[k] for k in RATE_TENORS):
        raise MarketStateError("RBNZ workbook missing required government tenors")
    return out


class _HtmlTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            text = re.sub(r"\s+", " ", " ".join(self._cell)).strip()
            self._row.append(text)
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if any(cell for cell in self._row):
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            if self._table:
                self.tables.append(self._table)
            self._table = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None and data.strip():
            self._cell.append(data.strip())


def _curl_cffi_get(url: str, *, referer: str | None = None) -> bytes | None:
    """Browser-TLS fetch for official hosts that 403 urllib on hosted runners."""
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        return None
    headers = {
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    for impersonate in ("chrome", "safari18_0"):
        try:
            resp = cffi_requests.get(url, impersonate=impersonate, timeout=DEFAULT_TIMEOUT, headers=headers)
        except Exception:
            continue
        if getattr(resp, "status_code", 0) == 200 and resp.content:
            return bytes(resp.content)
    return None


def _download_rbnz_xlsx() -> bytes:
    errors: list[str] = []
    for label, loader in (
        ("browser-ua", lambda: fetch_bytes(RBNZ_URL, user_agent=BROWSER_USER_AGENT)),
        ("default-ua", lambda: fetch_bytes(RBNZ_URL)),
    ):
        try:
            data = loader()
        except MarketStateError as exc:
            errors.append(f"{label}: {exc}")
            continue
        if data[:2] == b"PK":
            return data
        errors.append(f"{label}: response was not an xlsx workbook")
    data = _curl_cffi_get(RBNZ_URL, referer=RBNZ_PAGE)
    if data and data[:2] == b"PK":
        return data
    if data is not None:
        errors.append("curl_cffi: response was not an xlsx workbook")
    else:
        errors.append("curl_cffi: official B2 workbook still blocked")
    raise MarketStateError(
        "RBNZ official B2 workbook was blocked or unusable ("
        + "; ".join(errors)
        + "). Refusing to substitute a third-party or vendor feed."
    )


def _download_rbnz_html() -> str:
    errors: list[str] = []
    try:
        data = fetch_bytes(RBNZ_HTML_URL, user_agent=BROWSER_USER_AGENT, referer=RBNZ_PAGE)
        text = data.decode("utf-8", errors="replace")
        if "2 year" in text.lower() and "<table" in text.lower():
            return text
        errors.append("urllib: official page did not contain the B2 yield table")
    except MarketStateError as exc:
        errors.append(f"urllib: {exc}")
    data = _curl_cffi_get(RBNZ_HTML_URL, referer=RBNZ_PAGE)
    if data:
        text = data.decode("utf-8", errors="replace")
        if "2 year" in text.lower() and "<table" in text.lower():
            return text
        errors.append("curl_cffi: official page did not contain the B2 yield table")
    else:
        errors.append("curl_cffi: official B2 page still blocked")
    raise MarketStateError(
        "RBNZ official B2 HTML table was blocked or unusable ("
        + "; ".join(errors)
        + "). Refusing to substitute a third-party or vendor feed."
        " No preselected distributor was verified to republish the same RBNZ B2"
        " government-bond closing yields (2Y/5Y/10Y); packet NZ rates stay unavailable."
    )


def parse_rbnz_b2_html(text: str) -> dict[str, dict[date, float]]:
    """Parse the official RBNZ B2 wholesale-rate HTML table.

    The page publishes the same secondary-market government-bond closing
    yields as the B2 workbook: 2-year, 5-year and 10-year. The on-page table
    is a recent window, not the full workbook history.
    """
    parser = _HtmlTableParser()
    parser.feed(text)
    selected: tuple[list[list[str]], dict[int, str]] | None = None
    for table in parser.tables:
        for index, row in enumerate(table):
            headers = [re.sub(r"\s+", " ", cell).strip().lower() for cell in row]
            if not headers or headers[0] != "date":
                continue
            columns: dict[int, str] = {}
            for ci, header in enumerate(headers):
                for tenor, pattern in (("2Y", r"\b2\s*year\b"), ("5Y", r"\b5\s*year\b"), ("10Y", r"\b10\s*year\b")):
                    if re.search(pattern, header):
                        columns[ci] = tenor
            if set(columns.values()) == set(RATE_TENORS):
                selected = (table[index + 1 :], columns)
                break
        if selected:
            break
    if not selected:
        raise MarketStateError("RBNZ HTML table did not expose government 2Y/5Y/10Y yields")
    body, columns = selected
    out = {k: {} for k in RATE_TENORS}
    for row in body:
        if not row:
            continue
        raw_date = re.sub(r"\bSept\b", "Sep", row[0], flags=re.IGNORECASE)
        d = parse_date(raw_date)
        if not d:
            continue
        for ci, tenor in columns.items():
            if ci < len(row):
                v = to_float(row[ci])
                if v is not None:
                    out[tenor][d] = v
    if any(not out[k] for k in RATE_TENORS):
        raise MarketStateError("RBNZ HTML table missing required government tenors")
    return out


def _clip_rate_history(
    parsed: Mapping[str, Mapping[date, float]],
    start: date,
    end: date,
    *,
    empty_message: str,
) -> dict[str, dict[date, float]]:
    out = {k: {d: v for d, v in s.items() if start <= d <= end} for k, s in parsed.items()}
    if any(not out[k] for k in RATE_TENORS):
        raise MarketStateError(empty_message)
    return out


def fetch_nz_rates_with_provenance(
    start: date,
    end: date,
    *,
    workbook_bytes: bytes | None = None,
    html_text: str | None = None,
) -> tuple[dict[str, dict[date, float]], dict[str, str]]:
    """Official RBNZ only. XLSX first; HTML table if the workbook is blocked."""
    if workbook_bytes is not None:
        if workbook_bytes[:2] != b"PK":
            raise MarketStateError("RBNZ download was not an xlsx workbook; refusing to parse a substitute page")
        parsed = parse_rbnz_xlsx(workbook_bytes)
        series = _clip_rate_history(
            parsed,
            start,
            end,
            empty_message="RBNZ history missing required tenors after date filter",
        )
        return series, {
            "source_kind": "rbnz_b2_xlsx",
            "download_url": RBNZ_URL,
            "note": "Indicative closing government-bond yields with a one-day publication lag.",
        }
    if html_text is not None:
        parsed = parse_rbnz_b2_html(html_text)
        series = _clip_rate_history(
            parsed,
            start,
            end,
            empty_message="RBNZ HTML history missing required tenors after date filter",
        )
        return series, {
            "source_kind": "rbnz_b2_html",
            "download_url": RBNZ_HTML_URL,
            "note": (
                "Official RBNZ B2 HTML table of secondary-market government-bond closing yields. "
                "Used because the B2 XLSX workbook was blocked. The page table is a recent window, "
                "not a vendor substitute."
            ),
        }
    xlsx_error: Exception | None = None
    try:
        workbook = _download_rbnz_xlsx()
    except MarketStateError as exc:
        xlsx_error = exc
    else:
        try:
            parsed = parse_rbnz_xlsx(workbook)
            series = _clip_rate_history(
                parsed,
                start,
                end,
                empty_message="RBNZ history missing required tenors after date filter",
            )
        except MarketStateError as exc:
            xlsx_error = exc
        else:
            return series, {
                "source_kind": "rbnz_b2_xlsx",
                "download_url": RBNZ_URL,
                "note": "Indicative closing government-bond yields with a one-day publication lag.",
            }
    try:
        page = _download_rbnz_html()
    except MarketStateError as exc:
        raise MarketStateError(
            f"{xlsx_error}; official RBNZ HTML fallback also failed: {exc}"
        ) from exc
    parsed = parse_rbnz_b2_html(page)
    series = _clip_rate_history(
        parsed,
        start,
        end,
        empty_message="RBNZ HTML history missing required tenors after date filter",
    )
    return series, {
        "source_kind": "rbnz_b2_html",
        "download_url": RBNZ_HTML_URL,
        "note": (
            "Official RBNZ B2 HTML table of secondary-market government-bond closing yields. "
            f"Used because the B2 XLSX workbook was blocked ({xlsx_error}). "
            "The page table is a recent window, not a vendor substitute."
        ),
    }


def fetch_nz_rates(
    start: date,
    end: date,
    *,
    workbook_bytes: bytes | None = None,
    html_text: str | None = None,
) -> dict[str, dict[date, float]]:
    series, provenance = fetch_nz_rates_with_provenance(
        start,
        end,
        workbook_bytes=workbook_bytes,
        html_text=html_text,
    )
    fetch_nz_rates.last_provenance = provenance  # type: ignore[attr-defined]
    return series


def _preflight_blocking_source(source_key: str) -> bool:
    """US/AU registry preflight, ECB FX, and CFTC ownership drive packet status.

    CA uses a Canadian business-day publication lag and does not flip packet status.
    NZ, EA and JP are required_for_trader_preflight=false. CME open interest is
    a supplemental overlay: it stays visible and must not flip the packet.
    SR3/CORRA/AONIA curve gaps are expression-specific and are not global blockers.
    """
    required = {
        f"{code}_rates"
        for code in required_preflight_countries()
        if code != "CA"
    }
    return source_key in required or source_key in {"FX", "CFTC_positioning"}


def parse_ecb_sdmx_csv(text: str) -> dict[str, dict[date, float]]:
    """Parse ECB Data Portal SDMX-CSV daily EUR reference rates.

    Completeness is checked by the caller so a combined query and a
    per-currency fallback can share the same parser.
    """
    reader = csv.DictReader(io.StringIO(text))
    currency = {c: {} for c in G10}
    needed = {c for c in G10 if c != "EUR"}
    for row in reader:
        ccy = str(row.get("CURRENCY") or "").strip()
        if ccy not in needed:
            continue
        d = parse_date(row.get("TIME_PERIOD"))
        v = to_float(row.get("OBS_VALUE"))
        if d and v is not None and v > 0:
            currency[ccy][d] = v
            currency["EUR"][d] = 1.0
    if not any(currency[c] for c in needed):
        raise MarketStateError("ECB SDMX FX contained no G10 observations")
    return currency


def require_g10_fx(currency: Mapping[str, Mapping[date, float]]) -> None:
    missing = [c for c in G10 if not currency.get(c)]
    if missing:
        raise MarketStateError(f"ECB SDMX FX missing G10 currencies: {missing}")


def parse_ecb_fx_csv(text: str) -> dict[str, dict[date, float]]:
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = [x.strip() for x in (reader.fieldnames or [])]
    missing = [c for c in G10 if c != "EUR" and c not in fieldnames]
    if missing:
        raise MarketStateError(f"ECB FX CSV missing G10 currencies: {missing}")
    currency = {c: {} for c in G10}
    for row in reader:
        clean = {str(k).strip(): v for k, v in row.items() if k is not None}
        d = parse_date(clean.get("Date"))
        if not d:
            continue
        currency["EUR"][d] = 1.0
        for c in G10:
            if c == "EUR":
                continue
            v = to_float(clean.get(c))
            if v is not None and v > 0:
                currency[c][d] = v
    if any(not currency[c] for c in G10):
        raise MarketStateError("ECB FX history missing one or more G10 currency histories")
    return currency


def fx_pair_names() -> tuple[str, ...]:
    pairs: list[str] = []
    for i, base in enumerate(FX_ORDER):
        for quote in FX_ORDER[i + 1 :]:
            pairs.append(f"{base}{quote}")
    return tuple(pairs)


def _fx_pair_legs(pair: str) -> tuple[str, str]:
    for i, base in enumerate(FX_ORDER):
        for quote in FX_ORDER[i + 1 :]:
            if f"{base}{quote}" == pair:
                return base, quote
    raise MarketStateError(f"unknown FX pair {pair}")


def _fx_unavailable_pair_record(*, reason: str, error: str, missing_currencies: Sequence[str]) -> dict:
    return {
        "status": "unavailable",
        "spot": None,
        "as_of": None,
        "reason": reason,
        "error": error,
        "missing_currencies": list(missing_currencies),
    }


def build_fx_crosses(currency_per_eur: Mapping[str, Mapping[date, float]], start: date) -> dict[str, dict[date, float]]:
    """Derive all 45 unique G10 crosses from the same ECB EUR fixing date.

    ECB publishes foreign-currency units per EUR. BASEQUOTE = QUOTE_per_EUR / BASE_per_EUR.
    Legs from different fixing dates are never mixed.
    """
    out: dict[str, dict[date, float]] = {}
    for i, base in enumerate(FX_ORDER):
        for quote in FX_ORDER[i + 1 :]:
            base_series = currency_per_eur.get(base) or {}
            quote_series = currency_per_eur.get(quote) or {}
            common = sorted(set(base_series) & set(quote_series))
            series = {
                d: quote_series[d] / base_series[d]
                for d in common
                if d >= start and base_series[d] > 0
            }
            if series:
                out[f"{base}{quote}"] = series
    return out


def _build_fx_book(
    parsed: Mapping[str, Mapping[date, float]],
    start: date,
    *,
    errors: list[str],
    currency_errors: Mapping[str, str],
) -> dict:
    crosses = build_fx_crosses(parsed, start)
    unavailable: dict[str, dict] = {}
    pairs: dict[str, dict[date, float]] = {}
    for pair in fx_pair_names():
        base, quote = _fx_pair_legs(pair)
        missing_ccys = [c for c in (base, quote) if not parsed.get(c)]
        if pair in crosses and crosses[pair]:
            pairs[pair] = crosses[pair]
        else:
            err = currency_errors.get(missing_ccys[0]) if len(missing_ccys) == 1 else "; ".join(
                f"{c}: {currency_errors.get(c, 'missing observations')}" for c in missing_ccys
            )
            unavailable[pair] = _fx_unavailable_pair_record(
                reason=f"missing FX leg(s): {', '.join(missing_ccys) if missing_ccys else pair}",
                error=err or "missing FX observations",
                missing_currencies=missing_ccys,
            )
    currencies: dict[str, dict] = {}
    for ccy in G10:
        if parsed.get(ccy):
            currencies[ccy] = {"status": "ok"}
        else:
            currencies[ccy] = {
                "status": "unavailable",
                "error": currency_errors.get(ccy, "missing observations"),
            }
    source_observation = None
    if pairs:
        latest = max(max(series) for series in pairs.values())
        source_observation = latest.isoformat()
    status = "unavailable" if not pairs else "partial"
    return {
        "status": status,
        "pairs": pairs,
        "unavailable": unavailable,
        "currencies": currencies,
        "errors": errors,
        "source_observation": source_observation,
    }


def _fetch_ecb_sdmx(
    currencies: str,
    start: date,
    *,
    timeout: int = ECB_TIMEOUT,
    retries: int = ECB_RETRIES,
) -> dict[str, dict[date, float]]:
    qs = urllib.parse.urlencode({"format": "csvdata", "startPeriod": start.isoformat()})
    url = f"{ECB_FX_SDMX_URL.format(currencies=currencies)}?{qs}"
    return parse_ecb_sdmx_csv(fetch_bytes(url, timeout=timeout, retries=retries).decode("utf-8-sig"))


def _merge_fx_legs(
    dest: dict[str, dict[date, float]], extra: Mapping[str, Mapping[date, float]]
) -> None:
    for key, series in extra.items():
        dest.setdefault(key, {}).update(series)


def fetch_fx(start: date) -> dict[str, dict[date, float]] | dict:
    needed = [c for c in G10 if c != "EUR"]
    parsed: dict[str, dict[date, float]] = {c: {} for c in G10}
    errors: list[str] = []
    currency_errors: dict[str, str] = {}
    combined_failed = False
    try:
        # Combined 5-year query is one round-trip but ECB sometimes 504s it.
        merged = _fetch_ecb_sdmx("+".join(needed), start, timeout=60, retries=2)
        require_g10_fx(merged)
        parsed = merged
    except MarketStateError as exc:
        combined_failed = True
        errors.append(str(exc))
        for ccy in needed:
            try:
                extra = _fetch_ecb_sdmx(ccy, start, timeout=ECB_TIMEOUT, retries=ECB_RETRIES)
            except MarketStateError as inner:
                msg = f"{ccy}: {inner}"
                errors.append(msg)
                currency_errors[ccy] = str(inner)
                continue
            _merge_fx_legs(parsed, extra)
    usd = parsed.get("USD") or {}
    if usd:
        latest_usd = usd[max(usd)]
        if not (0.5 < latest_usd < 2.5):
            usd_err = f"implausible ECB EURUSD reference rate: {latest_usd}"
            parsed["USD"] = {}
            currency_errors["USD"] = usd_err
            errors.append(usd_err)
    missing = [c for c in G10 if not parsed.get(c)]
    if missing:
        if combined_failed:
            errors.append(
                "ECB SDMX combined query failed and per-currency fallback still missing "
                f"{missing}: {errors[-1]}"
            )
        for ccy in missing:
            if ccy != "EUR" and ccy not in currency_errors:
                currency_errors[ccy] = "missing observations"
        return _build_fx_book(parsed, start, errors=errors, currency_errors=currency_errors)

    latest = max(max(series) for series in parsed.values() if series)
    if (datetime.now(timezone.utc).date() - latest).days > FAIL_AFTER_DAYS:
        raise MarketStateError(f"ECB SDMX latest observation {latest.isoformat()} is too old")
    crosses = build_fx_crosses(parsed, start)
    if len(crosses) != 45 or any(not s for s in crosses.values()):
        raise MarketStateError(f"expected 45 populated G10 crosses, got {len(crosses)}")
    return crosses


def curve_spread(short: Mapping[date, float], long: Mapping[date, float]) -> dict[date, float]:
    return {d: (long[d] - short[d]) * 100.0 for d in set(short) & set(long)}


def rv_spread(a: Mapping[date, float], b: Mapping[date, float]) -> dict[date, float]:
    """Matching-tenor spread in basis points. Common observation dates only; no forward-fill."""
    return {d: (a[d] - b[d]) * 100.0 for d in set(a) & set(b)}


def spread_metrics_bps(series: Mapping[date, float]) -> dict:
    items = sorted(series.items())
    if not items:
        raise MarketStateError("empty spread series")
    latest_date, latest = items[-1]
    vals_1y = [v for _, v in items[-252:]]
    vals_5y = [v for _, v in items[-1260:]]

    def chg(n: int) -> float | None:
        old = lookback_value(items, n)
        return None if old is None else latest - old

    return {
        "as_of": latest_date.isoformat(),
        "bps": latest,
        "chg_1d_bps": chg(1),
        "chg_5d_bps": chg(5),
        "chg_1m_bps": chg(21),
        "chg_3m_bps": chg(63),
        "chg_6m_bps": chg(126),
        "chg_1y_bps": chg(252),
        "historical_move_analogs": _move_analogs(series, scale=1.0),
        "pctile_1y": percentile_rank(vals_1y, latest),
        "pctile_5y": percentile_rank(vals_5y, latest) if len(vals_5y) >= 60 else None,
        "z_1y": zscore(vals_1y, latest),
        "z_5y": zscore(vals_5y, latest) if len(vals_5y) >= 60 else None,
    }


def _freshness(age_days: int, key: str) -> str:
    if age_days > FAIL_AFTER_DAYS:
        raise MarketStateError(
            f"{key} observation is {age_days} days old; refusing to emit a fabricated or silently substituted substitute"
        )
    return "stale" if age_days > STALE_AFTER_DAYS[key] else "ok"


def _empty_tenor_metrics() -> dict:
    return {
        "as_of": None,
        "value": None,
        "bp_1d": None,
        "bp_5d": None,
        "bp_1m": None,
        "bp_3m": None,
        "pctile_1y": None,
        "pctile_5y": None,
        "z_1y": None,
        "z_5y": None,
    }


def _rv_leg_order(a: str, b: str) -> tuple[str, str]:
    pinned = _RV_LEG_ORDER.get(frozenset({a, b}))
    if pinned:
        return pinned
    if a == "US":
        return (b, "US")
    if b == "US":
        return (a, "US")
    return (a, b)


def _housing_unavailable(country: str, reason: str) -> dict:
    return {
        "country": country,
        "status": "unavailable",
        "error": reason,
        "feeds": {},
        "method": {
            "model_calls": 0,
            "credentials_required": [],
            "purpose": f"{country} housing transmission context; non-blocking for core macro/rates.",
            "trader_packet_delivery": "market_state_passthrough",
        },
    }


def _housing_feed_block(country: str, feed_names: Sequence[str], error: str) -> dict:
    """Unavailable housing block that still names every required feed."""
    return {
        "country": country,
        "status": "unavailable",
        "error": error,
        "feeds": {
            name: {"status": "unavailable", "url": "unavailable", "as_of": None, "error": error}
            for name in feed_names
        },
        "method": {
            "model_calls": 0,
            "credentials_required": [],
            "purpose": f"{country} housing transmission context; non-blocking for core macro/rates.",
            "trader_packet_delivery": "market_state_passthrough",
        },
    }


_AU_HOUSING_FEEDS = (
    "prices_and_turnover",
    "building_approvals",
    "housing_lending",
    "housing_credit",
    "mortgage_rates",
    "mortgage_cash_flow",
)
_US_HOUSING_FEEDS = (
    "prices",
    "sales_inventory",
    "construction",
    "mortgage_credit",
    "mortgage_rates",
    "mortgage_burden",
)
_CA_HOUSING_FEEDS = (
    "new_home_prices",
    "construction",
    "building_permits",
    "mortgage_lending",
    "mortgage_balances",
    "mortgage_rates",
    "mortgage_burden",
)


def _unavailable_rate_rv(reason: str) -> dict:
    return {
        "as_of": None,
        "bps": None,
        "chg_1d_bps": None,
        "chg_5d_bps": None,
        "chg_1m_bps": None,
        "chg_3m_bps": None,
        "pctile_1y": None,
        "pctile_5y": None,
        "z_1y": None,
        "z_5y": None,
        "status": "unavailable",
        "reason": reason,
    }


def _country_rates_unavailable(error: str) -> tuple[dict[str, dict[date, float]], dict]:
    """Return empty raw series and a rates block with explicit provenance."""
    empty = {t: {} for t in RATE_TENORS}
    block = {
        "tenors": {t: _empty_tenor_metrics() for t in RATE_TENORS},
        "curves": {},
        "latest_observation": None,
        "age_days": None,
        "status": "unavailable",
        "error": error,
    }
    return empty, block


def _nz_rates_unavailable(error: str) -> tuple[dict[str, dict[date, float]], dict]:
    return _country_rates_unavailable(error)


def _is_fx_book(obj: object) -> bool:
    return isinstance(obj, Mapping) and "pairs" in obj and "status" in obj and "unavailable" in obj


def fx_clock_from_packet(packet: Mapping | None) -> date | None:
    """Calendar date of a snapshot clock. Missing clocks do not invent a fixing date."""
    if not isinstance(packet, Mapping):
        return None
    raw = packet.get("generated_at")
    if not isinstance(raw, str) or len(raw) < 10:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def fx_pair_age_status(as_of: object, clock: date | None) -> str | None:
    """Per-cross freshness against ``clock``.

    ``None`` means the cross is inside the FX window, or the clock/date is
    absent and the caller must use an explicit status. A week-old fixing is
    stale. A fixing older than ``FAIL_AFTER_DAYS`` is unavailable.
    """
    if clock is None or not as_of:
        return None
    try:
        observed = date.fromisoformat(str(as_of)[:10])
    except ValueError:
        return "invalid"
    age = (clock - observed).days
    if age < 0:
        return None
    if age > FAIL_AFTER_DAYS:
        return "unavailable"
    if age > STALE_AFTER_DAYS["FX"]:
        return "stale"
    return None


def _stamp_cross_freshness(pairs_out: dict[str, dict], numeric: dict, *, today: date) -> None:
    """Mark each cross from its own last common fixing.

    A newer cross in the same bundle does not refresh an older one, and a
    too-old fixing is not left behind as a numeric mark.
    """
    limit = STALE_AFTER_DAYS["FX"]
    for pair, row in list(pairs_out.items()):
        if not isinstance(row, dict):
            continue
        if row.get("status") == "unavailable" or row.get("spot") is None:
            continue
        try:
            observed = date.fromisoformat(str(row.get("as_of")))
        except (TypeError, ValueError):
            pairs_out[pair] = _fx_unavailable_pair_record(
                reason=f"{pair} missing observation date",
                error=f"{pair} missing observation date",
                missing_currencies=[],
            )
            numeric.pop(pair, None)
            continue
        age = max(0, (today - observed).days)
        if age > FAIL_AFTER_DAYS:
            pairs_out[pair] = _fx_unavailable_pair_record(
                reason=f"{pair} observation {observed.isoformat()} is {age} days old",
                error=(
                    f"{pair} observation is {age} days old; refusing to emit a fabricated "
                    "or silently substituted substitute"
                ),
                missing_currencies=[],
            )
            numeric.pop(pair, None)
            continue
        if age > limit:
            stamped = dict(row)
            stamped["status"] = "stale"
            stamped["age_days"] = age
            pairs_out[pair] = stamped


def _fx_family_status(pairs_out: dict[str, dict], newest_status: str, *, from_book: bool) -> str:
    statuses = [str((row or {}).get("status") or "ok") for row in pairs_out.values() if isinstance(row, dict)]
    if not statuses or all(status == "unavailable" for status in statuses):
        return "unavailable"
    if newest_status == "stale" or all(status in {"stale", "unavailable"} for status in statuses):
        return "stale"
    if from_book or any(status != "ok" for status in statuses):
        return "partial"
    return "ok"


def _fx_snapshot_from_fetch(
    fx_raw: object,
    *,
    today: date,
) -> tuple[dict[str, dict], dict[str, dict[date, float]], date | None, int | None, str, str | None, list[str]]:
    """Return pair metrics, numeric series for opportunities, dates, status, error, FX_ccy unavailable ids."""
    fx_currency_unavailable: list[str] = []
    if _is_fx_book(fx_raw):
        book = fx_raw
        numeric = dict(book.get("pairs") or {})
        pairs_out: dict[str, dict] = {}
        for pair in fx_pair_names():
            if pair in numeric and numeric[pair]:
                pairs_out[pair] = fx_metrics(numeric[pair])
            else:
                pairs_out[pair] = (book.get("unavailable") or {}).get(
                    pair,
                    _fx_unavailable_pair_record(
                        reason="missing FX observations",
                        error="missing FX observations",
                        missing_currencies=[],
                    ),
                )
        for ccy, meta in (book.get("currencies") or {}).items():
            if ccy != "EUR" and (meta or {}).get("status") == "unavailable":
                fx_currency_unavailable.append(f"FX_{ccy}")
        latest_fx_date: date | None = None
        fx_age: int | None = None
        if numeric:
            latest_fx_date = max(max(series) for series in numeric.values())
            fx_age = max(0, (today - latest_fx_date).days)
        book_errors = "; ".join(str(item) for item in (book.get("errors") or []) if item) or None
        book_status = str(book.get("status") or "unavailable")
        if book_status == "unavailable" or not numeric:
            return pairs_out, {}, None, None, "unavailable", book_errors, fx_currency_unavailable
        try:
            freshness = _freshness(fx_age or 0, "FX")
        except MarketStateError as exc:
            return _fx_family_unavailable(str(exc))
        _stamp_cross_freshness(pairs_out, numeric, today=today)
        fx_status = _fx_family_status(pairs_out, freshness, from_book=True)
        return pairs_out, numeric, latest_fx_date, fx_age, fx_status, book_errors, fx_currency_unavailable

    if not isinstance(fx_raw, Mapping):
        raise MarketStateError("fetch_fx returned unexpected payload")
    numeric_plain = {k: v for k, v in fx_raw.items() if isinstance(v, Mapping) and v}
    pairs_out = {pair: fx_metrics(series) for pair, series in numeric_plain.items()}
    latest_fx_date = max(date.fromisoformat(v["as_of"]) for v in pairs_out.values())
    fx_age = max(0, (today - latest_fx_date).days)
    try:
        freshness = _freshness(fx_age, "FX")
    except MarketStateError as exc:
        return _fx_family_unavailable(str(exc))
    _stamp_cross_freshness(pairs_out, numeric_plain, today=today)
    fx_status = _fx_family_status(pairs_out, freshness, from_book=False)
    return pairs_out, numeric_plain, latest_fx_date, fx_age, fx_status, None, []


def _fx_family_unavailable(error: str) -> tuple[dict[str, dict], dict[str, dict[date, float]], None, None, str, str, list[str]]:
    record = _fx_unavailable_pair_record(reason="FX family unavailable", error=error, missing_currencies=[])
    pairs = {pair: dict(record) for pair in fx_pair_names()}
    return pairs, {}, None, None, "unavailable", error, []


def build_snapshot(
    *,
    today: date | None = None,
    nz_workbook: Path | None = None,
    include_cross_assets: bool = True,
    include_positioning: bool | None = None,
    include_policy_paths: bool | None = None,
    include_official_curves: bool | None = None,
    include_australia_housing: bool | None = None,
    include_us_housing: bool | None = None,
    include_canada_housing: bool | None = None,
    include_fragmentation: bool | None = None,
    short_rate_store: Path | None = None,
) -> dict:
    caller_supplied_today = today is not None
    today = today or datetime.now(timezone.utc).date()
    start = today - timedelta(days=366 * 5 + 15)
    nz_bytes = nz_workbook.read_bytes() if nz_workbook else None
    nz_error: str | None = None
    nz_provenance: dict[str, str] | None = None
    try:
        # Call the public wrapper so tests that patch fetch_nz_rates still supply
        # the series. Provenance is only trusted when the live function recorded a dict.
        nz_raw = fetch_nz_rates(start, today, workbook_bytes=nz_bytes)
    except MarketStateError as exc:
        nz_error = str(exc)
        nz_raw, nz_block = _nz_rates_unavailable(nz_error)
    else:
        nz_block = None
        recorded = getattr(fetch_nz_rates, "last_provenance", None)
        nz_provenance = recorded if isinstance(recorded, dict) else None

    unavailable_rate_countries: set[str] = set()
    country_errors: dict[str, str] = {}
    rates_raw: dict[str, dict[str, dict[date, float]]] = {"NZ": nz_raw}
    if nz_error:
        unavailable_rate_countries.add("NZ")
        country_errors["NZ"] = nz_error

    rate_fetchers = {
        "US": lambda: fetch_us_rates(start, today),
        "CA": lambda: fetch_ca_rates(start, today),
        "AU": lambda: fetch_au_rates(start, today),
        "EA": lambda: fetch_ea_bund_rates(start, today, fetch_bytes=fetch_bytes),
        "JP": lambda: fetch_jp_jgb_rates(start, today, fetch_bytes=fetch_bytes),
    }
    for country, fetcher in rate_fetchers.items():
        try:
            rates_raw[country] = fetcher()
        except MarketStateError as exc:
            err = str(exc)
            country_errors[country] = err
            empty, _ = _country_rates_unavailable(err)
            rates_raw[country] = empty
            unavailable_rate_countries.add(country)

    rates: dict[str, dict] = {}
    stale_sources: list[str] = []
    unavailable_sources: list[str] = []
    for country in sorted(unavailable_rate_countries):
        src = f"{country}_rates"
        if src not in unavailable_sources:
            unavailable_sources.append(src)
        if country == "NZ" and src not in stale_sources:
            stale_sources.append(src)

    def _set_country_unavailable(country: str, error: str) -> None:
        empty, block = _country_rates_unavailable(error)
        rates_raw[country] = empty
        rates[country] = block
        unavailable_rate_countries.add(country)
        country_errors[country] = error
        src = f"{country}_rates"
        if src not in unavailable_sources:
            unavailable_sources.append(src)
        if country == "NZ" and src not in stale_sources:
            stale_sources.append(src)

    for country in RATE_COUNTRIES:
        if country in unavailable_rate_countries:
            _, block = _country_rates_unavailable(country_errors.get(country, "leg rates unavailable"))
            rates[country] = block
            continue
        tenors = rates_raw[country]
        extra = extra_rate_tenor(country)
        required = RATE_TENORS + ((extra,) if extra else ())
        missing = [t for t in required if t not in tenors or not tenors[t]]
        if missing:
            _set_country_unavailable(country, f"{country} missing required tenors: {missing}")
            continue
        metrics = {tenor: rate_metrics(series) for tenor, series in tenors.items() if series}
        curves = {
            "2s10s": spread_metrics_bps(curve_spread(tenors["2Y"], tenors["10Y"])),
            "5s10s": spread_metrics_bps(curve_spread(tenors["5Y"], tenors["10Y"])),
        }
        latest_as_of = max(date.fromisoformat(metrics[t]["as_of"]) for t in RATE_TENORS)
        age_days = max(0, (today - latest_as_of).days)
        freshness_fields: dict[str, object] = {}
        try:
            if country == "JP":
                if age_days > FAIL_AFTER_DAYS:
                    raise MarketStateError(
                        f"JP observation is {age_days} days old; refusing to emit a fabricated or silently substituted substitute"
                    )
                status = jgb_observation_status(latest_as_of, today)
                freshness_fields = {
                    "age_business_days": japan_business_days_since(latest_as_of, today),
                    "freshness_rule": "japan_business_day_publication_lag",
                }
            elif country == "CA":
                if age_days > FAIL_AFTER_DAYS:
                    raise MarketStateError(
                        f"CA observation is {age_days} days old; refusing to emit a fabricated or silently substituted substitute"
                    )
                status = ca_observation_status(latest_as_of, today)
                freshness_fields = {
                    "age_calendar_days": age_days,
                    "age_business_days": canada_business_days_since(latest_as_of, today),
                    "freshness_rule": CA_FRESHNESS_RULE,
                    "minimum_fresh_observation": minimum_fresh_ca_observation(today).isoformat(),
                    "publication_lag_business_days": CA_PUBLICATION_LAG_BUSINESS_DAYS,
                }
            else:
                status = _freshness(age_days, country)
        except MarketStateError as exc:
            _set_country_unavailable(country, str(exc))
            continue
        if status == "stale":
            stale_sources.append(f"{country}_rates")
        rates[country] = {
            "tenors": metrics,
            "curves": curves,
            "latest_observation": latest_as_of.isoformat(),
            "age_days": age_days,
            "status": status,
            **freshness_fields,
        }

    rate_rv: dict[str, dict] = {}
    for a, b in RV_PAIRS:
        left, right = _rv_leg_order(a, b)
        for tenor in RATE_TENORS:
            if left in unavailable_rate_countries or right in unavailable_rate_countries:
                leg_err = country_errors.get(left) or country_errors.get(right) or "leg rates unavailable"
                rate_rv[f"{left}-{right}_{tenor}"] = _unavailable_rate_rv(leg_err)
                continue
            left_series = (rates_raw.get(left) or {}).get(tenor) or {}
            right_series = (rates_raw.get(right) or {}).get(tenor) or {}
            common = rv_spread(left_series, right_series) if left_series and right_series else {}
            if not common:
                rate_rv[f"{left}-{right}_{tenor}"] = _unavailable_rate_rv(
                    f"no overlapping {left}/{right} {tenor} observation dates"
                )
                continue
            rate_rv[f"{left}-{right}_{tenor}"] = spread_metrics_bps(common)

    try:
        fx_fetched = fetch_fx(start)
    except MarketStateError as exc:
        fx, fx_numeric, latest_fx_date, fx_age, fx_status, fx_error, _fx_ccy_unavail = _fx_family_unavailable(
            str(exc)
        )
        unavailable_sources.append("FX")
        stale_sources.append("FX")
    else:
        fx, fx_numeric, latest_fx_date, fx_age, fx_status, fx_error, fx_ccy_unavail = _fx_snapshot_from_fetch(
            fx_fetched, today=today
        )
        for key in sorted(set(fx_ccy_unavail)):
            if key not in unavailable_sources:
                unavailable_sources.append(key)
        if fx_status == "stale":
            stale_sources.append("FX")
        if fx_status == "unavailable":
            unavailable_sources.append("FX")
            stale_sources.append("FX")
            fx_error = fx_error or "FX unavailable"

    if include_australia_housing is None:
        include_australia_housing = include_cross_assets
    if include_australia_housing:
        try:
            australia_housing = collect_australia_housing(
                today=today,
                fetch_bytes=lambda url: fetch_bytes(url, timeout=20, retries=2, user_agent=BROWSER_USER_AGENT),
            )
        except Exception as exc:
            australia_housing = _housing_feed_block("AU", _AU_HOUSING_FEEDS, str(exc))
            unavailable_sources.append("AU_housing")
    else:
        australia_housing = {
            "country": "AU",
            "status": "unavailable",
            "feeds": {
                name: {
                    "status": "unavailable",
                    "url": "disabled",
                    "as_of": None,
                    "error": "Australian housing collection disabled for this invocation",
                }
                for name in (
                    "prices_and_turnover",
                    "building_approvals",
                    "housing_lending",
                    "housing_credit",
                    "mortgage_rates",
                    "mortgage_cash_flow",
                )
            },
            "method": {
                "model_calls": 0,
                "credentials_required": [],
                "purpose": "Official Australian housing transmission data for Market Watch and Trader Room context.",
                "trader_packet_delivery": "market_state_passthrough",
            },
        }

    if include_us_housing is None:
        include_us_housing = include_cross_assets
    if include_us_housing:
        try:
            us_housing = collect_us_housing(
                today=today,
                fetch_bytes=lambda url: fetch_bytes(url, timeout=20, retries=2),
            )
        except Exception as exc:
            us_housing = _housing_feed_block("US", _US_HOUSING_FEEDS, str(exc))
            unavailable_sources.append("US_housing")
    else:
        us_housing = {
            "country": "US",
            "status": "unavailable",
            "feeds": {
                name: {"status": "unavailable", "url": "disabled", "as_of": None, "error": "U.S. housing collection disabled for this invocation"}
                for name in ("prices", "sales_inventory", "construction", "mortgage_credit", "mortgage_rates", "mortgage_burden")
            },
            "method": {"model_calls": 0, "credentials_required": [], "trader_packet_delivery": "market_state_passthrough"},
        }

    if include_canada_housing is None:
        include_canada_housing = include_cross_assets
    if include_canada_housing:
        try:
            canada_housing = collect_canada_housing(
                today=today,
                fetch_bytes=lambda url: fetch_bytes(url, timeout=20, retries=2),
            )
        except Exception as exc:
            canada_housing = _housing_feed_block("CA", _CA_HOUSING_FEEDS, str(exc))
            unavailable_sources.append("CA_housing")
    else:
        canada_housing = {
            "country": "CA",
            "status": "unavailable",
            "feeds": {
                name: {"status": "unavailable", "url": "disabled", "as_of": None, "error": "Canadian housing collection disabled for this invocation"}
                for name in ("new_home_prices", "construction", "building_permits", "mortgage_lending", "mortgage_balances", "mortgage_rates", "mortgage_burden")
            },
            "method": {"model_calls": 0, "credentials_required": [], "trader_packet_delivery": "market_state_passthrough"},
        }

    cross_assets_error: str | None = None
    if include_cross_assets:
        try:
            cross_raw, cross_meta = collect_cross_assets(start, today, fetch_bytes)
            stamp_latest_values(cross_raw, cross_meta)
            cross_assets_status = "partial" if any(m["status"] != "ok" for m in cross_meta.values()) else "ok"
        except Exception as exc:
            cross_raw, cross_meta = {}, {}
            cross_assets_status = "unavailable"
            cross_assets_error = str(exc)
            unavailable_sources.append("cross_assets")
    else:
        cross_raw, cross_meta = {}, {}
        cross_assets_status = "ok"
    opportunities = build_opportunities(rates_raw, fx_numeric, cross_raw, cross_meta, today)
    if include_policy_paths is None:
        include_policy_paths = include_cross_assets
    if include_policy_paths:
        try:
            policy_paths = collect_policy_paths(
                today=today,
                fetch_bytes=fetch_bytes,
                short_rate_store=short_rate_store,
                as_of=(
                    None
                    if caller_supplied_today
                    else datetime.now(ZoneInfo("Australia/Sydney"))
                ),
            )
        except Exception as exc:
            policy_paths = {
                "status": "unavailable",
                "error": str(exc),
                "countries": {
                    c: {"status": "unavailable", "error": str(exc)}
                    for c in REQUIRED_POLICY_COUNTRIES
                },
                "sources": {},
                "method": {
                    "model_calls": 0,
                    "credentials_required": [],
                    "purpose": "policy expectations context before sovereign-curve/RV trade construction",
                },
            }
            unavailable_sources.append("policy_paths")
    else:
        policy_paths = {
            "status": "unavailable",
            "countries": {
                c: {"status": "unavailable", "error": "policy path collection disabled for this invocation"}
                for c in REQUIRED_POLICY_COUNTRIES
            },
            "sources": {},
            "method": {
                "model_calls": 0,
                "credentials_required": [],
                "purpose": "policy expectations context before sovereign-curve/RV trade construction",
            },
        }
    tradable_rate_curves = build_tradable_rate_curves(policy_paths)
    if include_policy_paths and tradable_rate_curves.get("status") != "ok":
        from scripts.country_registry import required_tradable_curve_ids

        required_curves = set(required_tradable_curve_ids())
        for curve_id, block in (tradable_rate_curves.get("curves") or {}).items():
            if curve_id not in required_curves:
                continue
            if (block or {}).get("status") != "ok":
                unavailable_sources.append(f"{curve_id}_tradable_curve")

    if include_official_curves is None:
        include_official_curves = include_cross_assets
    if include_official_curves:
        try:
            official_curves = collect_official_curves(today=today, fetch_bytes=fetch_bytes)
        except Exception as exc:
            official_curves = {
                "status": "unavailable",
                "error": str(exc),
                "countries": {
                    c: {"status": "unavailable", "error": str(exc)}
                    for c in REQUIRED_OFFICIAL_CURVE_COUNTRIES
                },
                "errors": {c: str(exc) for c in REQUIRED_OFFICIAL_CURVE_COUNTRIES},
                "method": {
                    "model_calls": 0,
                    "credentials_required": [],
                    "purpose": "official government zero/forward curve proxy for deterministic paper fwd-fwd and curve marks",
                    "ois_equivalence": "proxy_only",
                },
            }
            unavailable_sources.append("official_curves")
    else:
        official_curves = {
            "status": "unavailable",
            "countries": {
                c: {"status": "unavailable", "error": "official curve collection disabled for this invocation"}
                for c in REQUIRED_OFFICIAL_CURVE_COUNTRIES
            },
            "errors": {},
            "method": {
                "model_calls": 0,
                "credentials_required": [],
                "purpose": "official government zero/forward curve proxy for deterministic paper fwd-fwd and curve marks",
                "ois_equivalence": "proxy_only",
            },
        }
    if include_official_curves and official_curves.get("status") != "ok":
        for country in REQUIRED_OFFICIAL_CURVE_COUNTRIES:
            if (official_curves.get("countries", {}).get(country) or {}).get("status") != "ok":
                unavailable_sources.append(f"{country}_official_curve")
    if include_fragmentation is None:
        include_fragmentation = include_cross_assets
    if include_fragmentation:
        try:
            euro_area_fragmentation = collect_ea_fragmentation(today, fetch_bytes=fetch_bytes)
        except Exception as exc:
            euro_area_fragmentation = {
                "status": "unavailable",
                "block": "euro_area_fragmentation",
                "error": str(exc),
                "method": "Peripheral minus German Bund cash yield; exact common dates only; no forward fill",
            }
            unavailable_sources.append("EA_fragmentation")
    else:
        euro_area_fragmentation = {
            "status": "unavailable",
            "block": "euro_area_fragmentation",
            "error": "euro-area fragmentation collection disabled for this invocation",
            "method": "Peripheral minus German Bund cash yield; exact common dates only; no forward fill",
        }
    euro_area_housing = _housing_unavailable(
        "EA",
        "No official/free euro-area housing transmission feed met the source contract; housing is non-blocking.",
    )
    japan_housing = _housing_unavailable(
        "JP",
        "No official/free Japan housing transmission feed met the source contract; housing is non-blocking.",
    )
    if include_positioning is None:
        include_positioning = include_cross_assets
    positioning_start = today - timedelta(days=366 * 3 + 30)
    if include_positioning:
        try:
            positioning = build_positioning(today=today, start=positioning_start, fetch_bytes=fetch_bytes)
        except Exception as exc:
            err = str(exc)
            positioning = {
                "status": "unavailable",
                "error": err,
                "cftc_tff": {"status": "unavailable", "error": err, "instruments": {}},
                "cme": {"status": "unavailable", "error": err, "instruments": {}},
                "method": {"model_calls": 0, "credentials_required": []},
            }
            unavailable_sources.append("positioning")
    else:
        positioning = {
            "status": "unavailable",
            "error": "positioning collection disabled for this invocation",
            "cftc_tff": {"status": "unavailable", "error": "positioning collection disabled for this invocation", "instruments": {}},
            "cme": {"status": "unavailable", "error": "positioning collection disabled for this invocation", "instruments": {}},
            "method": {"model_calls": 0, "credentials_required": []},
        }
    if include_positioning:
        if positioning["cftc_tff"].get("status") == "unavailable":
            unavailable_sources.append("CFTC_positioning")
        if positioning["cme"].get("status") == "unavailable":
            unavailable_sources.append("CME_positioning")
        if positioning["cftc_tff"].get("status") == "stale":
            stale_sources.append("CFTC_positioning")
        if positioning["cme"].get("status") == "stale":
            stale_sources.append("CME_positioning")
    preflight_stale = [source for source in stale_sources if _preflight_blocking_source(source)]
    packet_status = "stale" if preflight_stale else "ok"
    nz_source = {
        "name": "Reserve Bank of New Zealand B2 wholesale interest rates",
        "url": RBNZ_PAGE,
        "download_url": (nz_provenance or {}).get("download_url") or RBNZ_URL,
        "observation_date": rates["NZ"]["latest_observation"],
        "status": rates["NZ"]["status"],
        "note": (nz_provenance or {}).get("note")
        or "Indicative closing government-bond yields with a one-day publication lag.",
        "source_kind": (nz_provenance or {}).get("source_kind") or "rbnz_b2_xlsx",
    }
    if nz_error or rates["NZ"].get("status") == "unavailable":
        nz_source["error"] = nz_error or rates["NZ"].get("error")
        nz_source["observation_date"] = None
    from scripts.prima_pressure.handoff import prima_block_for_snapshot, unavailable_block as prima_unavailable_block

    usdcad_history: list[tuple[date, float]] | None = None
    usdcad_series = (fx_numeric or {}).get("USDCAD")
    if usdcad_series:
        usdcad_history = sorted((d, float(v)) for d, v in usdcad_series.items())

    try:
        canada_prima_pressure = prima_block_for_snapshot(
            today,
            include_cross_assets=include_cross_assets,
            usdcad_history=usdcad_history,
        )
    except Exception as exc:
        canada_prima_pressure = prima_unavailable_block(str(exc))
        unavailable_sources.append("canada_prima_pressure")

    # Source lists are part of the serialized packet. Set iteration and fetch
    # order must not change bytes or digests.
    stale_sources = sorted(set(stale_sources))
    unavailable_sources = sorted(set(unavailable_sources))
    preflight_stale = [source for source in stale_sources if _preflight_blocking_source(source)]

    cross_assets_block: dict = {
        "series": cross_meta,
        "status": cross_assets_status,
        "compact": compact_cross_assets(
            {
                "generated_at": None,
                "cross_assets": {
                    "series": cross_meta,
                    "status": cross_assets_status,
                },
            }
        ),
    }
    if cross_assets_error:
        cross_assets_block["error"] = cross_assets_error

    def _sovereign_rate_source(
        *,
        name: str,
        url: str,
        download_url: str,
        country: str,
        note: str | None = None,
    ) -> dict:
        block = rates[country]
        out: dict = {
            "name": name,
            "url": url,
            "download_url": download_url,
            "observation_date": block.get("latest_observation"),
            "status": block.get("status"),
        }
        if note:
            out["note"] = note
        if block.get("status") == "unavailable":
            out["error"] = block.get("error")
            out["observation_date"] = None
        return out

    fx_source: dict = {
        "name": "ECB euro foreign exchange reference rates",
        "url": ECB_FX_PAGE,
        "download_url": ECB_FX_SDMX_URL.format(
            currencies="+".join(c for c in G10 if c != "EUR")
        ),
        "observation_date": latest_fx_date.isoformat() if latest_fx_date else None,
        "status": fx_status,
        "note": "Information/reference rates, not executable prices. All 45 G10 crosses are deterministic ratios of the same ECB EUR fixing date.",
    }
    observed_fixings = {
        str(row.get("as_of"))
        for row in fx.values()
        if isinstance(row, dict) and row.get("spot") is not None and row.get("as_of")
    }
    if len(observed_fixings) > 1:
        fx_source["note"] = (
            "Each cross is a ratio of its two legs on one shared ECB fixing date. "
            "Legs from different fixing dates are never mixed. A cross whose own fixing "
            "is stale is marked stale and is not a mark."
        )
    if fx_error and fx_status != "ok":
        fx_source["error"] = fx_error

    policy_meeting_prices = _policy_meeting_prices(today, policy_paths)
    from scripts.fx_technical.packet import technical_research_for_snapshot

    us10 = (rates_raw.get("US") or {}).get("10Y") or {}
    fx_technical = technical_research_for_snapshot(
        fx_series=fx_numeric,
        as_of=today,
        clock=today,
        cross_asset_series=cross_raw,
        cross_asset_meta=cross_meta,
        rate_series={"US10Y": us10} if us10 else None,
    )
    return {
        "policy_paths": policy_paths,
        "futures_basis": policy_paths.get("futures_basis")
        if isinstance(policy_paths, dict)
        else {"status": "unavailable", "reason": "policy paths missing", "curves": {}},
        "policy_meeting_prices": policy_meeting_prices,
        "tradable_rate_curves": tradable_rate_curves,
        "official_curves": official_curves,
        "australia_housing": australia_housing,
        "us_housing": us_housing,
        "canada_housing": canada_housing,
        "euro_area_housing": euro_area_housing,
        "japan_housing": japan_housing,
        "euro_area_fragmentation": euro_area_fragmentation,
        "cross_assets": cross_assets_block,
        "opportunities": opportunities,
        "relative_rate_analytics": _relative_rate_analytics(tradable_rate_curves, fx),
        "positioning": positioning,
        "canada_prima_pressure": canada_prima_pressure,
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "window_start": start.isoformat(),
        "status": packet_status,
        "preflight_status": packet_status,
        "stale_sources": stale_sources,
        "preflight_stale_sources": preflight_stale,
        "unavailable_sources": unavailable_sources,
        "rates": rates,
        "rate_rv": rate_rv,
        "fx": {
            "source_observation": latest_fx_date.isoformat() if latest_fx_date else None,
            "age_days": fx_age,
            "status": fx_status,
            "pairs": fx,
            **({"error": fx_error} if fx_error else {}),
        },
        "fx_technical": fx_technical,
        "sources": {
            "US_rates": _sovereign_rate_source(
                name="U.S. Treasury daily par yield curve",
                url=TREASURY_PAGE,
                download_url=TREASURY_URL.format(year=today.year),
                country="US",
            ),
            "CA_rates": _sovereign_rate_source(
                name="Bank of Canada Valet benchmark bonds",
                url=BOC_DOCS,
                download_url=BOC_GROUP_URL,
                country="CA",
                note=(
                    "Bank of Canada Valet selected benchmark bond yields are prior mid-market closing "
                    "yields published once each Canadian business day at 09:30–10:00 ET, with a one "
                    "Canadian business-day publication lag. Weekends and Bank publication holidays do "
                    "not age the series. Observation dates are the printed session and are never "
                    "rewritten forward. A missing Friday print is not evidence the Friday session "
                    "was a holiday."
                ),
            ),
            "AU_rates": _sovereign_rate_source(
                name="Reserve Bank of Australia F2 government-bond yields",
                url=RBA_PAGE,
                download_url=RBA_URL,
                country="AU",
                note="RBA assessed closing yields; research context only; not a financial benchmark; typically weekly with a two-business-day lag.",
            ),
            "NZ_rates": nz_source,
            "EA_rates": _sovereign_rate_source(
                name="Deutsche Bundesbank BBSSY German Bund par yields",
                url=BUNDESBANK_PAGE,
                download_url="https://api.statistiken.bundesbank.de/rest/data/BBSSY",
                country="EA",
                note="Germany is the EUR cash-rates benchmark only; EA temperature is euro-area macro/policy.",
            ),
            "JP_rates": _sovereign_rate_source(
                name="Ministry of Finance Japan JGB benchmark par yields",
                url=MOF_JGB_PAGE_EN,
                download_url=MOF_JGB_CURRENT_EN,
                country="JP",
            ),
            "CFTC_positioning": {
                "name": "CFTC Traders in Financial Futures - Futures Only",
                "url": positioning["cftc_tff"].get("source_url", "https://publicreporting.cftc.gov/stories/s/TFF-Futures-Only/98ig-3k9y/"),
                "download_url": positioning["cftc_tff"].get("api_url", "https://publicreporting.cftc.gov/resource/gpe5-46if.json"),
                "observation_date": positioning["cftc_tff"].get("report_date"),
                "status": positioning["cftc_tff"].get("status"),
                **({"error": positioning["cftc_tff"].get("error")} if positioning["cftc_tff"].get("status") == "unavailable" else {}),
            },
            "CME_positioning": {
                "name": "CME Group FX futures and options volume/open-interest service",
                "url": positioning["cme"].get("source_url", "https://www.cmegroup.com/market-data/volume-open-interest.html"),
                "download_url": positioning["cme"].get("api_template", "https://www.cmegroup.com/CmeWS/mvc/Volume/LastTotals/{product_id}?days=30"),
                "observation_date": positioning["cme"].get("trade_date"),
                "status": positioning["cme"].get("status"),
                **({"error": positioning["cme"].get("error")} if positioning["cme"].get("status") == "unavailable" else {}),
            },
            "FX": fx_source,
        },
        "method": {
            "model_calls": 0,
            "fx_source": "ecb_euro_reference_crosses",
            "fx_cross_construction": True,
            "fx_pair_count": len(fx),
            "rate_rv_count": len(rate_rv),
            "credentials_required": [],
            "note": (
                "Live authorities remain canonical. This artifact is a compact research snapshot. "
                "US, Australia, ECB FX, and CFTC positioning remain packet-level preflight. "
                "A stale Canadian benchmark yield stays visible on CA_rates and does not by itself "
                "mark the packet stale. CA-dependent expressions and existing-book positions that "
                "depend on that leg fail closed. Canadian benchmark freshness uses the Canadian "
                "business-day calendar and a one-session publication lag. "
                "NZ and Japan are not required_for_trader_preflight; a blocked RBNZ source or a "
                "Japan holiday-calendar print stays visible on that source and does not by itself "
                "mark the packet stale. NZ-dependent and JP-dependent expressions still fail closed. "
                "The official RBNZ B2 XLSX is tried first, including a browser-TLS retry, then the "
                "official RBNZ B2 HTML table. No vendor or media substitute is used. "
                "Japan JGB freshness uses the Tokyo business-day calendar and a one-session publication lag. "
                "Euro-area Bund (Germany) and Japan JGB cash curves remain six-economy rate legs. "
                "Cross-country spreads use exact common observation dates only. "
                "Policy-path context uses official overnight benchmarks plus public money-market data. "
                "The required tradable paper rates universe remains SOFR via CME SR3, CORRA via MX CRA, and AONIA via ASX IB. "
                "TONA is included when JPX OSE 3M settlements pass identity checks. "
                "CME ESR final settlements are collected for research; the €STR curve stays observe_only; Eurex FST3 is not a mark. "
                "Official government zero/forward curves are supplemental bond-curve inputs and are not required to manufacture a swap curve. "
                "Euro-area sovereign fragmentation (IT/FR/ES vs Bund) is market context, never an EA temperature input. "
                "Housing context is collected for the US, Canada and Australia from free maintained public sources: FHFA/Census/Fed/Freddie Mac via FRED for the US, Statistics Canada/CMHC/Bank of Canada for Canada, and ABS/RBA for Australia. "
                "EA/JP housing is omitted until an official/free source meets the contract. "
                "CFTC TFF supplies trader-class ownership/crowding context and can mark the packet stale. "
                "CME's public volume/open-interest service is a supplemental overlay and does not flip packet status. "
                "No historical warehouse is written to GitHub or Supabase."
            ),
        },
    }


def validate_snapshot(s: Mapping) -> None:
    if s.get("method", {}).get("model_calls") != 0:
        raise MarketStateError("generator must make zero model calls")
    if s.get("method", {}).get("credentials_required") not in ([], None):
        raise MarketStateError("MVP path must not require credentials")
    if s.get("method", {}).get("fx_source") != "ecb_euro_reference_crosses":
        raise MarketStateError("FX source must be same-fixing ECB EUR reference crosses")
    if s.get("method", {}).get("fx_pair_count") != 45:
        raise MarketStateError("generator must produce exactly 45 G10 FX crosses")
    if s.get("method", {}).get("rate_rv_count") != len(RV_PAIRS) * len(RATE_TENORS):
        raise MarketStateError("unexpected rate RV count")
    try:
        validate_positioning(s.get("positioning") or {})
    except Exception as exc:
        raise MarketStateError(f"invalid positioning block: {exc}") from exc
    try:
        validate_policy_paths(s.get("policy_paths") or {})
    except Exception as exc:
        raise MarketStateError(f"invalid policy_paths block: {exc}") from exc
    try:
        validate_tradable_rate_curves(s.get("tradable_rate_curves") or {})
    except Exception as exc:
        raise MarketStateError(f"invalid tradable_rate_curves block: {exc}") from exc
    try:
        validate_official_curves(s.get("official_curves") or {})
    except Exception as exc:
        raise MarketStateError(f"invalid official_curves block: {exc}") from exc
    try:
        validate_australia_housing(s.get("australia_housing") or {})
    except Exception as exc:
        raise MarketStateError(f"invalid australia_housing block: {exc}") from exc
    try:
        validate_us_housing(s.get("us_housing") or {})
    except Exception as exc:
        raise MarketStateError(f"invalid us_housing block: {exc}") from exc
    try:
        validate_canada_housing(s.get("canada_housing") or {})
    except Exception as exc:
        raise MarketStateError(f"invalid canada_housing block: {exc}") from exc
    if set(s.get("rates", {})) != set(RATE_COUNTRIES):
        raise MarketStateError("rates block must contain every registry rate country")
    for c in RATE_COUNTRIES:
        block = s["rates"][c]
        if block.get("status") == "unavailable":
            if c not in UNAVAILABLE_OK_RATE_COUNTRIES:
                raise MarketStateError(f"only {sorted(UNAVAILABLE_OK_RATE_COUNTRIES)} may be unavailable, not {c}")
            if not block.get("error"):
                raise MarketStateError(f"{c} unavailable block must include error provenance")
            continue
        for t in RATE_TENORS:
            value = block["tenors"][t]["value"]
            if not (-2.0 < value < 25):
                raise MarketStateError(f"implausible {c} {t} yield: {value}")
            if not block["tenors"][t].get("as_of"):
                raise MarketStateError(f"{c} {t} missing observation date")
        extra = extra_rate_tenor(c)
        if extra and extra not in block["tenors"]:
            raise MarketStateError(f"{c} missing {extra} tenor")
    frag = s.get("euro_area_fragmentation") or {}
    if frag.get("status") not in {"ok", "partial", "unavailable"}:
        raise MarketStateError("euro_area_fragmentation missing or invalid status")
    if frag.get("status") == "unavailable" and not frag.get("error"):
        raise MarketStateError("euro_area_fragmentation unavailable without provenance")
    for housing_key in ("euro_area_housing", "japan_housing"):
        housing = s.get(housing_key) or {}
        if housing.get("status") not in {"ok", "partial", "unavailable"}:
            raise MarketStateError(f"{housing_key} missing or invalid status")
        if housing.get("status") == "unavailable" and not housing.get("error"):
            raise MarketStateError(f"{housing_key} unavailable without provenance")
    for _key, rv in s.get("rate_rv", {}).items():
        if rv.get("status") == "unavailable":
            if rv.get("bps") is not None:
                raise MarketStateError("unavailable RV spread must not include fabricated bps")
            continue
        if rv.get("bps") is None:
            raise MarketStateError("available RV spread missing bps")
    if len(s["fx"]["pairs"]) != 45:
        raise MarketStateError("FX pairs must be exactly 45")
    for required in ("EURUSD", "USDJPY", "AUDNZD", "NOKSEK", "USDCAD"):
        if required not in s["fx"]["pairs"]:
            raise MarketStateError(f"missing required FX pair {required}")
    fx_family_status = str((s.get("fx") or {}).get("status") or "")
    for pair, m in s["fx"]["pairs"].items():
        if m.get("status") == "unavailable":
            if m.get("spot") is not None:
                raise MarketStateError(f"unavailable FX pair {pair} must not include numeric spot")
            if not (m.get("reason") or m.get("error")):
                raise MarketStateError(f"unavailable FX pair {pair} missing provenance")
            continue
        if m.get("status") not in {None, "ok", "stale"}:
            raise MarketStateError(f"{pair} invalid status {m.get('status')}")
        if m.get("status") == "stale":
            age = m.get("age_days")
            if not isinstance(age, int) or isinstance(age, bool) or age <= STALE_AFTER_DAYS["FX"]:
                raise MarketStateError(f"{pair} stale without a stale observation age")
            if age > FAIL_AFTER_DAYS:
                raise MarketStateError(f"{pair} is too old to remain a stale mark")
            if fx_family_status == "ok":
                raise MarketStateError("fresh FX family contains a stale cross")
        if not (0 < m["spot"] < 1000):
            raise MarketStateError(f"implausible FX spot {pair}: {m['spot']}")
        if not m.get("as_of"):
            raise MarketStateError(f"{pair} missing observation date")
    for key, src in s.get("sources", {}).items():
        if not src.get("url"):
            raise MarketStateError(f"source {key} missing url")
        if src.get("status") == "unavailable":
            if not src.get("error"):
                raise MarketStateError(f"source {key} unavailable without provenance")
            continue
        if not src.get("observation_date"):
            raise MarketStateError(f"source {key} missing observation_date")
    if not s.get("generated_at"):
        raise MarketStateError("generated_at missing")


def _policy_meeting_prices(today: date, policy_paths: dict) -> dict:
    """Price meetings from the in-memory futures strip and the stored calendar.

    A missing calendar or a bank failure leaves that bank unavailable. It does
    not fail the rest of the snapshot.
    """
    root = Path(__file__).resolve().parents[1]
    try:
        from scripts.policy_calendar import load_calendar
        from scripts.policy_meeting_book import attach_outcomes
        from scripts.policy_meeting_pricing import build_policy_meeting_prices, load_history
        from scripts.policy_state import load_policy_state

        calendar = load_calendar(root) or {"banks": {}}
        policy_state = load_policy_state(root) or {"countries": {}}
        history = load_history(root)
        from scripts.policy_meeting_pricing import guard_policy_meeting_prices_for_publication

        block = build_policy_meeting_prices(
            as_of=today,
            calendar=calendar,
            policy_state=policy_state,
            policy_paths=policy_paths,
            history_doc=history,
        )
        block = guard_policy_meeting_prices_for_publication(block)
        return attach_outcomes(block, policy_state, today, calendar)
    except Exception as exc:
        return {
            "schema_version": 1,
            "construction_version": "policy_meeting_v1",
            "as_of": today.isoformat(),
            "status": "unavailable",
            "error": str(exc),
            "banks": {},
        }


def _refresh_meeting_calendars() -> None:
    """Best-effort official calendars. One bank failure keeps that bank's last schedule."""
    root = Path(__file__).resolve().parents[1]
    try:
        from scripts.policy_calendar import load_calendar, refresh_calendars

        def fetch(url: str) -> str:
            return fetch_bytes(url, retries=1).decode("utf-8", "replace")

        refresh_calendars(fetch, load_calendar(root), save=True, root=root)
    except Exception as exc:
        print(f"policy calendar refresh skipped: {exc}", file=sys.stderr)


def _refresh_policy_state() -> None:
    """Best-effort official policy-state refresh during market-state acquisition.

    A failure leaves the previous canonical file in place and does not change
    the market-state snapshot or this process's exit status.
    """
    try:
        from scripts.policy_state import refresh_and_write

        refresh_and_write()
    except Exception as exc:
        print(f"policy state refresh skipped: {exc}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate the Market Watch daily market-state packet")
    ap.add_argument("--output", required=True, help="JSON snapshot path")
    ap.add_argument("--today", help="override current date (YYYY-MM-DD), useful for testing")
    ap.add_argument(
        "--nz-workbook",
        help="optional local official RBNZ B2 xlsx (same file as the public download URL)",
    )
    ap.add_argument("--public", action="store_true", help="Omit restricted index observations from the public read model")
    ap.add_argument(
        "--short-rate-store",
        help="optional path for short-rate last-good persistence (default: beside --output)",
    )
    args = ap.parse_args(argv)
    today = date.fromisoformat(args.today) if args.today else None
    nz_workbook = Path(args.nz_workbook) if args.nz_workbook else None
    if nz_workbook and not nz_workbook.is_file():
        raise MarketStateError(f"RBNZ workbook not found: {nz_workbook}")
    _refresh_meeting_calendars()
    _refresh_policy_state()
    if args.short_rate_store:
        store_path = Path(args.short_rate_store)
    else:
        store_path = Path(args.output).parent / "short_rate_last_good.json"
    snapshot = build_snapshot(
        today=today,
        nz_workbook=nz_workbook,
        short_rate_store=store_path,
    )
    validate_snapshot(snapshot)
    if args.public:
        from scripts.cross_asset_data import public_snapshot
        snapshot = public_snapshot(snapshot)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
    try:
        from scripts.policy_meeting_pricing import append_history

        root = Path(__file__).resolve().parents[1]
        prices = snapshot.get("policy_meeting_prices")
        if isinstance(prices, dict) and prices.get("as_of"):
            from scripts.policy_meeting_pricing import guard_policy_meeting_prices_for_publication

            prices = guard_policy_meeting_prices_for_publication(prices) or prices
            append_history(root, date.fromisoformat(str(prices["as_of"])), prices)
            sidecar = root / "data" / "policy_meeting_prices.json"
            sidecar.write_text(json.dumps(prices, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception as exc:
        print(f"policy meeting history skipped: {exc}", file=sys.stderr)
    print(
        json.dumps(
            {
                "status": snapshot["status"],
                "fx_pairs": snapshot["method"]["fx_pair_count"],
                "rate_rv": snapshot["method"]["rate_rv_count"],
                "fx_as_of": snapshot["fx"]["source_observation"],
                "rate_as_of": {c: snapshot["rates"][c]["latest_observation"] for c in RATE_COUNTRIES},
                "stale_sources": snapshot["stale_sources"],
                "positioning_status": snapshot["positioning"]["status"],
                "output": str(out),
            }
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except MarketStateError as exc:
        print(f"MARKET STATE ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
