"""Deterministic positioning inputs for Market Watch.

Core ownership data comes from the CFTC Traders in Financial Futures (TFF)
futures-only public dataset. CME's public Volume & Open Interest service
supplements it with daily futures and options open-interest history. No model
calls, credentials, or paid feeds are required.

These are research/reference observations, not executable prices.
"""
from __future__ import annotations

import json
import math
import statistics
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Callable, Mapping, Sequence

CFTC_TFF_DATASET = "gpe5-46if"
CFTC_TFF_API = f"https://publicreporting.cftc.gov/resource/{CFTC_TFF_DATASET}.json"
CFTC_TFF_PAGE = "https://publicreporting.cftc.gov/stories/s/TFF-Futures-Only/98ig-3k9y/"
CME_VOLUME_PAGE = "https://www.cmegroup.com/market-data/volume-open-interest.html"
CME_LAST_TOTALS = "https://www.cmegroup.com/CmeWS/mvc/Volume/LastTotals/{product_id}?days=30"
CME_FX_PRODUCTS = {
    "EUR": "58",
    "GBP": "42",
    "JPY": "69",
    "CHF": "86",
    "CAD": "48",
    "AUD": "37",
    "NZD": "78",
    "NOK": "825",
    "SEK": "826",
}

CFTC_STALE_DAYS = 10
CME_STALE_DAYS = 4
CME_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

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
    "US2Y": ("TREASURY",),
    "US5Y": ("TREASURY",),
    "US10Y": ("TREASURY",),
    "US30Y": ("TREASURY",),
}
CFTC_CONTRACT_CODES = {
    "EUR": "099741",
    "GBP": "096742",
    "JPY": "097741",
    "CHF": "092741",
    "CAD": "090741",
    "AUD": "232741",
    "NZD": "112741",
    "US2Y": "042601",
    "US5Y": "044601",
    "US10Y": "043602",
    "US30Y": "020601",
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
    contract_code = CFTC_CONTRACT_CODES.get(key)
    if contract_code:
        return str(row.get("cftc_contract_market_code") or "").strip() == contract_code
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
            f"'{start.isoformat()}T00:00:00.000' AND "
            "cftc_contract_market_code in ("
            + ",".join(f"'{code}'" for code in CFTC_CONTRACT_CODES.values())
            + ")"
        ),
        "$order": "report_date_as_yyyy_mm_dd ASC",
        "$limit": "50000",
    }
    url = f"{CFTC_TFF_API}?{urllib.parse.urlencode(params)}"
    payload = json.loads(fetch_bytes(url, timeout=30, retries=2).decode("utf-8"))
    if not isinstance(payload, list):
        raise PositioningError("CFTC TFF API did not return a list")
    result = parse_cftc_tff_rows(payload, today=today)
    result["source_url"] = CFTC_TFF_PAGE
    result["api_url"] = CFTC_TFF_API
    result["dataset_id"] = CFTC_TFF_DATASET
    return result


def parse_cme_last_totals(payload: Mapping[str, object], *, ccy: str, today: date) -> dict:
    rows = payload.get("vdate")
    if not isinstance(rows, list) or not rows:
        raise PositioningError(f"CME LastTotals returned no history for {ccy}")
    observations: list[dict] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        raw_date = str(row.get("formattedDate") or "")
        if len(raw_date) != 8 or not raw_date.isdigit():
            continue
        d = date(int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:8]))
        future_oi = _number(row.get("futureOi"))
        option_oi = _number(row.get("optionOi"))
        future_volume = _number(row.get("futureVolume"))
        option_volume = _number(row.get("optionVolume"))
        if future_oi is None:
            continue
        observations.append(
            {
                "date": d,
                "future_open_interest": future_oi,
                "option_open_interest": option_oi,
                "future_volume": future_volume,
                "option_volume": option_volume,
            }
        )
    if not observations:
        raise PositioningError(f"CME LastTotals had no usable observations for {ccy}")
    observations.sort(key=lambda x: x["date"])
    latest = observations[-1]
    prior = observations[-2] if len(observations) > 1 else None
    age_days = max(0, (today - latest["date"]).days)
    future_hist = [x["future_open_interest"] for x in observations]
    option_hist = [x["option_open_interest"] for x in observations if x["option_open_interest"] is not None]
    future_oi = latest["future_open_interest"]
    option_oi = latest["option_open_interest"]
    return {
        "status": "stale" if age_days > CME_STALE_DAYS else "ok",
        "trade_date": latest["date"].isoformat(),
        "age_days": age_days,
        "product_id": CME_FX_PRODUCTS[ccy],
        "future_open_interest": future_oi,
        "future_oi_daily_change": (
            None if prior is None else future_oi - prior["future_open_interest"]
        ),
        "future_oi_pctile_30d": _pct_rank(future_hist, future_oi),
        "future_oi_z_30d": _z(future_hist, future_oi),
        "future_volume": latest["future_volume"],
        "option_open_interest": option_oi,
        "option_oi_daily_change": (
            None
            if prior is None or option_oi is None or prior["option_open_interest"] is None
            else option_oi - prior["option_open_interest"]
        ),
        "option_oi_pctile_30d": (
            None if option_oi is None else _pct_rank(option_hist, option_oi)
        ),
        "option_oi_z_30d": None if option_oi is None else _z(option_hist, option_oi),
        "option_volume": latest["option_volume"],
        "options_to_futures_oi_ratio": (
            None if option_oi is None or not future_oi else option_oi / future_oi
        ),
        "history": [
            {
                "date": x["date"].isoformat(),
                "future_open_interest": x["future_open_interest"],
                "option_open_interest": x["option_open_interest"],
            }
            for x in observations
        ],
    }


def fetch_cme_fx_positioning(*, today: date, fetch_bytes: Callable[..., bytes]) -> dict:
    instruments: dict[str, dict] = {}
    errors: dict[str, str] = {}
    latest: date | None = None

    def one(item: tuple[str, str]) -> tuple[str, dict | None, str | None]:
        ccy, product_id = item
        url = CME_LAST_TOTALS.format(product_id=product_id) + "&isProtected"
        try:
            payload = json.loads(
                fetch_bytes(
                    url,
                    timeout=15,
                    retries=2,
                    user_agent=CME_BROWSER_USER_AGENT,
                    referer=CME_VOLUME_PAGE,
                ).decode("utf-8")
            )
            return ccy, parse_cme_last_totals(payload, ccy=ccy, today=today), None
        except Exception as exc:
            return ccy, None, str(exc)

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(one, CME_FX_PRODUCTS.items()))
    for ccy, metrics, error in results:
        if error or metrics is None:
            errors[ccy] = error or "unknown CME collection failure"
            continue
        instruments[ccy] = metrics
        d = date.fromisoformat(metrics["trade_date"])
        latest = d if latest is None or d > latest else latest
    if not instruments:
        raise PositioningError(
            "CME LastTotals returned no mapped G10 FX products; "
            f"errors={errors}"
        )
    status = "partial" if errors else (
        "stale" if any(v["status"] == "stale" for v in instruments.values()) else "ok"
    )
    return {
        "status": status,
        "trade_date": latest.isoformat() if latest else None,
        "age_days": max(0, (today - latest).days) if latest else None,
        "instruments": instruments,
        "missing_instruments": sorted(errors),
        "errors": errors,
        "source_url": CME_VOLUME_PAGE,
        "api_template": CME_LAST_TOTALS,
        "note": (
            "CME public Volume & Open Interest service supplies daily product-level futures "
            "and aggregate options OI. It is a participation/crowding overlay, not trader identity."
        ),
    }


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
            "source_url": CME_VOLUME_PAGE,
            "api_template": CME_LAST_TOTALS,
            "instruments": {},
        }

    available = [block for block in (cftc, cme) if block.get("status") != "unavailable"]
    stale = any(block.get("status") == "stale" for block in available)
    if not available:
        status = "unavailable"
    elif cftc_error or cme_error or cftc.get("status") == "partial" or cme.get("status") == "partial":
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
            "daily_open_interest_source": "cme_volume_last_totals",
            "crowding_measure": (
                "Trader-class net positions are normalized by total open interest, "
                "with 1Y/3Y percentile and z-score context. CME daily futures/options OI is supplemental."
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
        for ccy, item in (cme.get("instruments") or {}).items():
            if item.get("future_open_interest") is None or item["future_open_interest"] < 0:
                raise PositioningError(f"invalid CME futures open interest for {ccy}")
            option_oi = item.get("option_open_interest")
            if option_oi is not None and option_oi < 0:
                raise PositioningError(f"invalid CME options open interest for {ccy}")
