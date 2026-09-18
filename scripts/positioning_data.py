"""Deterministic positioning inputs for Market Watch.

Core ownership data comes from the CFTC Traders in Financial Futures (TFF)
futures-only public dataset. CME Daily Bulletin data supplements it with
previous-trade-date futures open interest and monthly-options call/put open
interest. No model calls, credentials, or paid feeds are required.

These are research/reference observations, not executable prices.
"""
from __future__ import annotations

import io
import json
import math
import re
import statistics
import urllib.parse
from datetime import date, datetime
from typing import Callable, Mapping, Sequence

CFTC_TFF_DATASET = "gpe5-46if"
CFTC_TFF_API = f"https://publicreporting.cftc.gov/resource/{CFTC_TFF_DATASET}.json"
CFTC_TFF_PAGE = "https://publicreporting.cftc.gov/stories/s/TFF-Futures-Only/98ig-3k9y/"
CME_DAILY_BULLETIN_PAGE = "https://www.cmegroup.com/market-data/daily-bulletin.html"
CME_FX_SUMMARY_PDF = (
    "https://www.cmegroup.com/daily_bulletin/current/"
    "Section01B_Summary_Volume_And_Open_Interest_FX_Futures_And_Options.pdf"
)

CFTC_STALE_DAYS = 10
CME_STALE_DAYS = 4

CFTC_SELECT_FIELDS = (
    "market_and_exchange_names",
    "report_date_as_yyyy_mm_dd",
    "contract_market_name",
    "cftc_contract_market_code",
    "cftc_market_code",
    "cftc_commodity_code",
    "commodity_name",
    "open_interest_all",
    "dealer_positions_long_all",
    "dealer_positions_short_all",
    "dealer_positions_spread_all",
    "asset_mgr_positions_long",
    "asset_mgr_positions_short",
    "asset_mgr_positions_spread",
    "lev_money_positions_long",
    "lev_money_positions_short",
    "lev_money_positions_spread",
    "other_rept_positions_long",
    "other_rept_positions_short",
    "other_rept_positions_spread",
    "nonrept_positions_long_all",
    "nonrept_positions_short_all",
)

# Match the standard CFTC financial futures. Micro/mini/cross variants are
# excluded before matching. We preserve the selected market name/code in the
# output so the mapping is auditable rather than silently inferred.
CFTC_INSTRUMENT_PATTERNS: dict[str, tuple[str, ...]] = {
    "EUR": ("EURO FX",),
    "GBP": ("BRITISH POUND",),
    "JPY": ("JAPANESE YEN",),
    "CHF": ("SWISS FRANC",),
    "CAD": ("CANADIAN DOLLAR",),
    "AUD": ("AUSTRALIAN DOLLAR",),
    "NZD": ("NEW ZEALAND DOLLAR",),
    "US2Y": ("2-YEAR", "TREASURY"),
    "US5Y": ("5-YEAR", "TREASURY"),
    "US10Y": ("10-YEAR", "TREASURY"),
    "US_LONG": ("TREASURY BOND",),
}
CFTC_EXCLUSIONS = ("MICRO", "E-MINI", "EMINI", "CROSS RATE", "ULTRA")

CATEGORIES: dict[str, tuple[str, str, str | None]] = {
    "dealer": (
        "dealer_positions_long_all",
        "dealer_positions_short_all",
        "dealer_positions_spread_all",
    ),
    "asset_manager": (
        "asset_mgr_positions_long",
        "asset_mgr_positions_short",
        "asset_mgr_positions_spread",
    ),
    "leveraged_funds": (
        "lev_money_positions_long",
        "lev_money_positions_short",
        "lev_money_positions_spread",
    ),
    "other_reportable": (
        "other_rept_positions_long",
        "other_rept_positions_short",
        "other_rept_positions_spread",
    ),
    "nonreportable": (
        "nonrept_positions_long_all",
        "nonrept_positions_short_all",
        None,
    ),
}

CME_FUTURES_PREFIXES = {
    "EUR": "EC EURO FX FUTURES",
    "JPY": "JY JAPANESE YEN FUTURE",
    "GBP": "BP BRITISH POUND FUTURE",
    "AUD": "AD AUSTRALIAN DLR FUTURES",
    "CAD": "CD CANADIAN DOLLAR FUTURE",
    "NZD": "NE NEW ZEALAND DOLLAR FUTURES",
    "CHF": "SF SWISS FRANC FUTURES",
    "SEK": "SE SKR/USD CROSS RATE FUTURES",
    "NOK": "UN NKR/USD CROSS RATE FUTURES",
}
CME_MONTHLY_OPTION_PREFIXES = {
    "EUR": ("EUU EUR/USD Monthly Options C", "EUU EUR/USD Monthly Options P"),
    "JPY": ("JPU JPY/USD Monthly Options C", "JPU JPY/USD Monthly Options P"),
    "GBP": ("GBU GBP/USD Monthly Options C", "GBU GBP/USD Monthly Options P"),
    "AUD": ("ADU AUD/USD Monthly Options C", "ADU AUD/USD Monthly Options P"),
    "CAD": ("CAU CAD/USD Monthly Options C", "CAU CAD/USD Monthly Options P"),
    "NZD": ("ZN NZD/USD Monthly Options C", "ZN NZD/USD Monthly Options P"),
    "CHF": ("CHU CHF/USD Monthly Options C", "CHU CHF/USD Monthly Options P"),
}


class PositioningError(RuntimeError):
    pass


def _number(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _pct_rank(values: Sequence[float], x: float) -> float | None:
    if not values:
        return None
    lt = sum(v < x for v in values)
    eq = sum(v == x for v in values)
    return 100.0 * (lt + 0.5 * eq) / len(values)


def _z(values: Sequence[float], x: float) -> float | None:
    if len(values) < 2:
        return None
    sd = statistics.pstdev(values)
    return 0.0 if sd == 0 else (x - statistics.fmean(values)) / sd


def _distribution(values: Sequence[float], current: float) -> dict[str, float | int | None]:
    one_year = list(values[-52:])
    three_year = list(values[-156:])
    return {
        "pctile_1y": _pct_rank(one_year, current),
        "z_1y": _z(one_year, current),
        "pctile_3y": _pct_rank(three_year, current) if len(three_year) >= 52 else None,
        "z_3y": _z(three_year, current) if len(three_year) >= 52 else None,
        "sample_weeks_1y": len(one_year),
        "sample_weeks_3y": len(three_year),
    }


def _row_date(row: Mapping[str, object]) -> date | None:
    raw = str(row.get("report_date_as_yyyy_mm_dd") or "")[:10]
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _row_label(row: Mapping[str, object]) -> str:
    return " | ".join(
        str(row.get(key) or "")
        for key in ("commodity_name", "contract_market_name", "market_and_exchange_names")
    ).upper()


def _matches_instrument(key: str, row: Mapping[str, object]) -> bool:
    label = _row_label(row)
    if any(term in label for term in CFTC_EXCLUSIONS):
        return False
    return all(term in label for term in CFTC_INSTRUMENT_PATTERNS[key])


def _select_series(rows: Sequence[Mapping[str, object]], key: str) -> list[Mapping[str, object]]:
    by_date: dict[date, list[Mapping[str, object]]] = {}
    for row in rows:
        d = _row_date(row)
        if d and _matches_instrument(key, row):
            by_date.setdefault(d, []).append(row)
    chosen: list[Mapping[str, object]] = []
    for d in sorted(by_date):
        # The standard contract should be unique. If CFTC exposes more than one
        # eligible row, use the largest OI and surface the actual chosen market.
        chosen.append(max(by_date[d], key=lambda r: _number(r.get("open_interest_all")) or -1.0))
    return chosen


def _category_metrics(series: Sequence[Mapping[str, object]], fields: tuple[str, str, str | None]) -> dict:
    long_field, short_field, spread_field = fields
    observations: list[tuple[date, float, float, float, float]] = []
    for row in series:
        d = _row_date(row)
        long_v = _number(row.get(long_field))
        short_v = _number(row.get(short_field))
        oi = _number(row.get("open_interest_all"))
        spread_v = _number(row.get(spread_field)) if spread_field else 0.0
        if d and long_v is not None and short_v is not None and oi not in (None, 0):
            observations.append((d, long_v, short_v, spread_v or 0.0, oi))
    if not observations:
        return {"status": "unavailable"}
    d, long_v, short_v, spread_v, oi = observations[-1]
    net = long_v - short_v
    net_pct = 100.0 * net / oi
    history = [100.0 * (long_i - short_i) / oi_i for _, long_i, short_i, _, oi_i in observations]
    prev_net = observations[-2][1] - observations[-2][2] if len(observations) > 1 else None
    return {
        "status": "ok",
        "as_of": d.isoformat(),
        "long": long_v,
        "short": short_v,
        "spreading": spread_v if spread_field else None,
        "net": net,
        "net_pct_open_interest": net_pct,
        "weekly_change_net": None if prev_net is None else net - prev_net,
        **_distribution(history, net_pct),
    }


def _instrument_metrics(series: Sequence[Mapping[str, object]]) -> dict:
    if not series:
        return {"status": "unavailable"}
    current = series[-1]
    d = _row_date(current)
    oi = _number(current.get("open_interest_all"))
    if d is None or oi is None:
        return {"status": "unavailable"}
    oi_history = [
        value
        for row in series
        if (value := _number(row.get("open_interest_all"))) is not None
    ]
    prev_oi = _number(series[-2].get("open_interest_all")) if len(series) > 1 else None
    return {
        "status": "ok",
        "as_of": d.isoformat(),
        "market_and_exchange_name": current.get("market_and_exchange_names"),
        "contract_market_name": current.get("contract_market_name"),
        "cftc_contract_market_code": current.get("cftc_contract_market_code"),
        "commodity_name": current.get("commodity_name"),
        "open_interest": {
            "contracts": oi,
            "weekly_change": None if prev_oi is None else oi - prev_oi,
            **_distribution(oi_history, oi),
        },
        "trader_classes": {
            name: _category_metrics(series, fields)
            for name, fields in CATEGORIES.items()
        },
    }


def parse_cftc_tff_rows(rows: Sequence[Mapping[str, object]], *, today: date) -> dict:
    instruments: dict[str, dict] = {}
    missing: list[str] = []
    latest: date | None = None
    for key in CFTC_INSTRUMENT_PATTERNS:
        series = _select_series(rows, key)
        metrics = _instrument_metrics(series)
        if metrics.get("status") != "ok":
            missing.append(key)
            continue
        instruments[key] = metrics
        d = date.fromisoformat(metrics["as_of"])
        latest = d if latest is None or d > latest else latest
    if latest is None:
        raise PositioningError("CFTC TFF response contained no mapped financial futures")
    age_days = max(0, (today - latest).days)
    return {
        "status": "stale" if age_days > CFTC_STALE_DAYS else ("partial" if missing else "ok"),
        "report_date": latest.isoformat(),
        "age_days": age_days,
        "instruments": instruments,
        "missing_instruments": missing,
        "classification": "CFTC Traders in Financial Futures, futures only",
    }


def fetch_cftc_tff(
    start: date,
    *,
    today: date,
    fetch_bytes: Callable[..., bytes],
) -> dict:
    params = {
        "$select": ",".join(CFTC_SELECT_FIELDS),
        "$where": (
            "report_date_as_yyyy_mm_dd >= "
            f"'{start.isoformat()}T00:00:00.000'"
        ),
        "$order": "report_date_as_yyyy_mm_dd ASC",
        "$limit": "50000",
    }
    url = f"{CFTC_TFF_API}?{urllib.parse.urlencode(params)}"
    payload = json.loads(fetch_bytes(url, timeout=60, retries=3).decode("utf-8"))
    if not isinstance(payload, list):
        raise PositioningError("CFTC TFF API did not return a list")
    result = parse_cftc_tff_rows(payload, today=today)
    result["source_url"] = CFTC_TFF_PAGE
    result["api_url"] = CFTC_TFF_API
    result["dataset_id"] = CFTC_TFF_DATASET
    return result


def extract_pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise PositioningError("pypdf is required for CME Daily Bulletin positioning") from exc
    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:
        raise PositioningError(f"could not parse CME Daily Bulletin PDF: {exc}") from exc


def _bulletin_date(text: str) -> date:
    match = re.search(
        r"BULLETIN\s+#\s*\d+@\s*(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s*"
        r"([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})",
        text,
    )
    if not match:
        raise PositioningError("CME Daily Bulletin trade date not found")
    return datetime.strptime(match.group(1), "%b %d, %Y").date()


def _find_line(text: str, prefix: str) -> str | None:
    for line in text.splitlines():
        clean = " ".join(line.split())
        if clean.startswith(prefix):
            return clean
    return None


def _oi_and_change(line: str, prefix: str) -> tuple[int | None, int | None]:
    tail = line[len(prefix) :].strip()
    matches = list(re.finditer(r"(\d[\d,]*)\s*([+-])\s*(\d[\d,]*)", tail))
    if matches:
        match = matches[0]
        oi = int(match.group(1).replace(",", ""))
        change = int(match.group(3).replace(",", ""))
        return oi, change if match.group(2) == "+" else -change
    unch = re.search(r"(\d[\d,]*)\s+UNCH\b", tail)
    if unch:
        return int(unch.group(1).replace(",", "")), 0
    nums = [int(x.replace(",", "")) for x in re.findall(r"(?<![.\w])\d[\d,]*(?![.\w])", tail)]
    if len(nums) == 1:
        return nums[0], 0
    return None, None


def parse_cme_fx_bulletin(text: str, *, today: date) -> dict:
    trade_date = _bulletin_date(text)
    age_days = max(0, (today - trade_date).days)
    futures: dict[str, dict] = {}
    for ccy, prefix in CME_FUTURES_PREFIXES.items():
        line = _find_line(text, prefix)
        if not line:
            continue
        oi, change = _oi_and_change(line, prefix)
        if oi is not None:
            futures[ccy] = {"open_interest": oi, "daily_change": change}

    monthly_options: dict[str, dict] = {}
    for ccy, (call_prefix, put_prefix) in CME_MONTHLY_OPTION_PREFIXES.items():
        call_line = _find_line(text, call_prefix)
        put_line = _find_line(text, put_prefix)
        call_oi, call_change = _oi_and_change(call_line, call_prefix) if call_line else (None, None)
        put_oi, put_change = _oi_and_change(put_line, put_prefix) if put_line else (None, None)
        if call_oi is None and put_oi is None:
            continue
        total = (call_oi or 0) + (put_oi or 0)
        monthly_options[ccy] = {
            "call_open_interest": call_oi,
            "put_open_interest": put_oi,
            "total_open_interest": total,
            "put_call_oi_ratio": None if not call_oi else (put_oi or 0) / call_oi,
            "call_daily_change": call_change,
            "put_daily_change": put_change,
        }

    def aggregate(prefix: str) -> dict | None:
        match = re.search(prefix + r"\s+([\d\s]+?)\s+(\d+)\s*([+-])\s*(\d+)", text)
        if not match:
            return None
        # Current OI is the integer immediately before the signed OI change.
        oi = int(match.group(2))
        chg = int(match.group(4)) * (1 if match.group(3) == "+" else -1)
        return {"open_interest": oi, "daily_change": chg}

    aggregate_futures = aggregate(r"FUTURES ONLY-\s*FX")
    aggregate_options = aggregate(r"OPTIONS ONLY-\s*FX")
    if not futures:
        raise PositioningError("CME FX summary contained no mapped G10 futures open interest")
    return {
        "status": "stale" if age_days > CME_STALE_DAYS else "ok",
        "trade_date": trade_date.isoformat(),
        "age_days": age_days,
        "futures": futures,
        "monthly_options": monthly_options,
        "aggregate_fx": {
            "futures": aggregate_futures,
            "options": aggregate_options,
            "options_to_futures_oi_ratio": (
                None
                if not aggregate_futures
                or not aggregate_options
                or not aggregate_futures["open_interest"]
                else aggregate_options["open_interest"] / aggregate_futures["open_interest"]
            ),
        },
        "note": (
            "CME Daily Bulletin is previous-trade-date official exchange open interest. "
            "Monthly option call/put OI is a participation/shape overlay, not trader identity."
        ),
    }


def fetch_cme_fx_positioning(*, today: date, fetch_bytes: Callable[..., bytes]) -> dict:
    data = fetch_bytes(CME_FX_SUMMARY_PDF, timeout=60, retries=3)
    result = parse_cme_fx_bulletin(extract_pdf_text(data), today=today)
    result["source_url"] = CME_DAILY_BULLETIN_PAGE
    result["download_url"] = CME_FX_SUMMARY_PDF
    return result


def build_positioning(
    *,
    today: date,
    start: date,
    fetch_bytes: Callable[..., bytes],
) -> dict:
    cftc_error = None
    cme_error = None
    try:
        cftc = fetch_cftc_tff(start, today=today, fetch_bytes=fetch_bytes)
    except Exception as exc:
        cftc_error = str(exc)
        cftc = {
            "status": "unavailable",
            "error": cftc_error,
            "source_url": CFTC_TFF_PAGE,
            "api_url": CFTC_TFF_API,
            "dataset_id": CFTC_TFF_DATASET,
            "instruments": {},
        }
    try:
        cme = fetch_cme_fx_positioning(today=today, fetch_bytes=fetch_bytes)
    except Exception as exc:
        cme_error = str(exc)
        cme = {
            "status": "unavailable",
            "error": cme_error,
            "source_url": CME_DAILY_BULLETIN_PAGE,
            "download_url": CME_FX_SUMMARY_PDF,
            "futures": {},
            "monthly_options": {},
        }

    available = [block for block in (cftc, cme) if block.get("status") != "unavailable"]
    stale = any(block.get("status") == "stale" for block in available)
    if not available:
        status = "unavailable"
    elif cftc_error or cme_error or cftc.get("status") == "partial":
        status = "partial"
    elif stale:
        status = "stale"
    else:
        status = "ok"
    return {
        "status": status,
        "cftc_tff": cftc,
        "cme": cme,
        "method": {
            "model_calls": 0,
            "credentials_required": [],
            "core_ownership_source": "cftc_tff_futures_only",
            "daily_open_interest_source": "cme_daily_bulletin",
            "crowding_measure": (
                "Trader-class net positions are normalized by total open interest, "
                "with 1Y/3Y percentile and z-score context. CME OI is supplemental."
            ),
        },
    }


def validate_positioning(block: Mapping[str, object]) -> None:
    if block.get("status") not in {"ok", "partial", "stale", "unavailable"}:
        raise PositioningError("positioning status invalid")
    method = block.get("method")
    if not isinstance(method, Mapping):
        raise PositioningError("positioning method missing")
    if method.get("model_calls") != 0 or method.get("credentials_required") not in ([], None):
        raise PositioningError("positioning collection must be deterministic and credential-free")
    cftc = block.get("cftc_tff")
    if isinstance(cftc, Mapping) and cftc.get("status") != "unavailable":
        for key, item in (cftc.get("instruments") or {}).items():
            oi = (item.get("open_interest") or {}).get("contracts")
            if oi is None or oi < 0:
                raise PositioningError(f"invalid CFTC open interest for {key}")
            for category, values in (item.get("trader_classes") or {}).items():
                if values.get("status") == "ok" and values.get("long", 0) < 0:
                    raise PositioningError(f"invalid CFTC long position for {key}/{category}")
    cme = block.get("cme")
    if isinstance(cme, Mapping) and cme.get("status") != "unavailable":
        for ccy, item in (cme.get("futures") or {}).items():
            if item.get("open_interest") is None or item["open_interest"] < 0:
                raise PositioningError(f"invalid CME open interest for {ccy}")
