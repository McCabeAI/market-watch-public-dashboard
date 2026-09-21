"""Euro-area rates, policy path, official curve and fragmentation collectors (isolated I4).

Germany is the EUR cash-rates benchmark (Bundesbank BBSSY). ECB €STR, ECB analytical
curves, and peripheral-vs-Bund spreads are separate instrument families.
"""

from __future__ import annotations

import csv
import io
import json
import re
import urllib.parse
import urllib.request
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Any, Callable, Mapping

FetchBytes = Callable[..., bytes]

USER_AGENT = "MarketWatch-MarketState/1.0 (+https://github.com/McCabeAI/market-watch-public-dashboard)"

STALE_AFTER_DAYS_EA = 4

BUNDESBANK_API_BASE = "https://api.statistiken.bundesbank.de/rest/data/BBSSY"
BUNDESBANK_PAGE = "https://www.bundesbank.de/en/statistics/time-series-databases"

BUND_SERIES: dict[str, str] = {
    "2Y": "D.REN.EUR.A610.000000WT0202.A",
    "5Y": "D.REN.EUR.A620.000000WT0505.A",
    "10Y": "D.REN.EUR.A630.000000WT1010.A",
    "30Y": "D.REN.EUR.A640.000000WT3030.A",
}

ECB_ESTR_SERIES_KEY = "EST.B.EU000A2X2A25.WT"
ECB_ESTR_URL = (
    "https://data-api.ecb.europa.eu/service/data/EST/B.EU000A2X2A25.WT?format=csvdata"
)
ECB_ESTR_PAGE = "https://data.ecb.europa.eu/data/datasets/EST/data-information"

ECB_YC_API_BASE = "https://data-api.ecb.europa.eu/service/data/YC"
ECB_YC_PAGE = (
    "https://www.ecb.europa.eu/stats/financial_markets_and_interest_rates/"
    "euro_area_yield_curves/html/index.en.html"
)
ECB_YC_TECHNICAL_NOTES = (
    "https://www.ecb.europa.eu/stats/financial_markets_and_interest_rates/"
    "euro_area_yield_curves/shared/pdf/technical_notes.pdf"
)

# All-euro-area government bonds, all ratings, Svensson spot rates (daily business week).
ECB_YC_ALL_PREFIX = "B.U2.EUR.4F.G_N_C.SV_C_YM"
ECB_YC_AAA_PREFIX = "B.U2.EUR.4F.G_N_A.SV_C_YM"

YC_SPOT_TENORS: tuple[str, ...] = ("2Y", "5Y", "10Y", "30Y")

FST3_URLS_TRIED: tuple[str, ...] = (
    "https://www.eurex.com/ex-en/markets/int/fixing/3-month-estr-futures-FST3",
    "https://www.eurex.com/ex-en/data/trading-files/product-and-price-report",
    "https://www.eurex.com/ex-en/data/market-statistics/settlement-prices/FST3",
    "https://www.eurex.com/api/v1/marketdata/settlement/FST3",
    "https://www.eurex.com/api/v2/marketdata/statistics/FST3/settlement",
)
# Eurex STIR futures are quoted as 100 minus the interest rate (same convention as
# Three-Month €STR futures / legacy Euribor futures). See Eurex contract specifications:
# https://www.eurex.com/ex-en/rules-regs/eurex-rules-and-regulations-contract-specifications

EUROSTAT_MCBY_URL = (
    "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
    "irt_lt_mcby_m"
)
EUROSTAT_MCBY_PAGE = (
    "https://ec.europa.eu/eurostat/databrowser/view/irt_lt_mcby_m/default/table"
)

FRAGMENTATION_COUNTRIES: tuple[str, ...] = ("IT", "FR", "ES")
FRAGMENTATION_TENORS: tuple[str, ...] = ("2Y", "5Y", "10Y")


class EuroAreaRatesError(RuntimeError):
    """Raised when a required euro-area rates source fails."""


def _num(value: Any) -> float | None:
    if value is None:
        return None
    s = str(value).strip().replace(",", ".").replace("%", "")
    if not s or s in {".", "-", "—", "N/A", "NA", "_"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_iso_date(value: str) -> date | None:
    s = (value or "").strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _month_end(ym: str) -> date:
    year, month = int(ym[:4]), int(ym[5:7])
    return date(year, month, monthrange(year, month)[1])


def default_fetch_bytes(url: str, *, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def parse_bundesbank_csv(text: str) -> dict[date, float]:
    """Parse a single-series Bundesbank BBSSY CSV.

    The REST CSV dialect follows Accept-Language: German locale uses semicolons
    and comma decimals (``2,45``); English locale uses commas and period decimals
    (``2.45``). Missing values are ``.``.
    """
    out: dict[date, float] = {}
    for raw in text.lstrip("\ufeff").splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line:
            continue
        lowered = line.lower()
        if lowered.startswith('"stand vom') or lowered.startswith("stand vom"):
            continue
        if lowered.startswith("last update"):
            continue
        delimiter = ";" if ";" in line else ","
        parts = [p.strip().strip('"') for p in line.split(delimiter)]
        if len(parts) < 2:
            continue
        d = _parse_iso_date(parts[0])
        if d is None:
            continue
        v = _num(parts[1])
        if v is not None:
            out[d] = v
    if not out:
        raise EuroAreaRatesError("Bundesbank CSV contains no dated yield observations")
    return out


def bundesbank_series_url(series_key: str, start: date, end: date) -> str:
    qs = urllib.parse.urlencode(
        {
            "format": "csv",
            "startPeriod": start.isoformat(),
            "endPeriod": end.isoformat(),
        }
    )
    return f"{BUNDESBANK_API_BASE}/{series_key}?{qs}"


def fetch_ea_bund_rates(
    start: date,
    end: date,
    fetch_bytes: FetchBytes = default_fetch_bytes,
) -> dict[str, dict[date, float]]:
    out: dict[str, dict[date, float]] = {t: {} for t in BUND_SERIES}
    for tenor, series_key in BUND_SERIES.items():
        url = bundesbank_series_url(series_key, start, end)
        body = fetch_bytes(url).decode("utf-8", errors="replace")
        parsed = parse_bundesbank_csv(body)
        out[tenor] = {d: v for d, v in parsed.items() if start <= d <= end}
    missing = [t for t in ("2Y", "5Y", "10Y", "30Y") if not out[t]]
    if missing:
        raise EuroAreaRatesError(f"Bundesbank missing required tenors after filter: {missing}")
    return out


def parse_ecb_estr_csv(text: str) -> dict[date, float]:
    rows = list(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))))
    out: dict[date, float] = {}
    for row in rows:
        d = _parse_iso_date(row.get("TIME_PERIOD", ""))
        v = _num(row.get("OBS_VALUE"))
        if d is not None and v is not None:
            out[d] = v
    if not out:
        raise EuroAreaRatesError("€STR CSV contains no observations")
    return out


def ecb_estr_url(start: date, end: date) -> str:
    qs = urllib.parse.urlencode(
        {"format": "csvdata", "startPeriod": start.isoformat(), "endPeriod": end.isoformat()}
    )
    return f"https://data-api.ecb.europa.eu/service/data/EST/B.EU000A2X2A25.WT?{qs}"


def fetch_estr_history(
    start: date,
    end: date,
    fetch_bytes: FetchBytes = default_fetch_bytes,
) -> dict[date, float]:
    url = ecb_estr_url(start, end)
    text = fetch_bytes(url).decode("utf-8", errors="replace")
    parsed = parse_ecb_estr_csv(text)
    return {d: v for d, v in parsed.items() if start <= d <= end}


def _contract_row(
    *,
    expiry: str,
    code: str | None,
    price: float,
    benchmark: float,
    source: str,
    volume: float | None = None,
    open_interest: float | None = None,
) -> dict[str, Any]:
    implied = 100.0 - price
    return {
        "expiry": expiry,
        "code": code,
        "price": round(price, 6),
        "implied_rate": round(implied, 6),
        "change_from_overnight_bps": round((implied - benchmark) * 100.0, 2),
        "volume": volume,
        "open_interest": open_interest,
        "source": source,
    }


def parse_fst3_settlement_csv(text: str, *, benchmark: float) -> list[dict[str, Any]]:
    """Parse a minimal FST3 settlement table (contract code, settlement price, optional vol/OI)."""
    rows: list[dict[str, Any]] = []
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise EuroAreaRatesError("FST3 settlement CSV missing header")
    fields = {f.lower(): f for f in reader.fieldnames}
    code_key = fields.get("contract") or fields.get("code") or fields.get("instrument")
    price_key = fields.get("settlement") or fields.get("settle") or fields.get("price")
    expiry_key = fields.get("expiry") or fields.get("maturity")
    vol_key = fields.get("volume")
    oi_key = fields.get("open_interest") or fields.get("oi")
    if not code_key or not price_key:
        raise EuroAreaRatesError("FST3 settlement CSV missing contract/price columns")
    for row in reader:
        code = (row.get(code_key) or "").strip() or None
        price = _num(row.get(price_key))
        if price is None:
            continue
        expiry = (row.get(expiry_key) or "").strip() if expiry_key else ""
        if not expiry and code:
            m = re.search(r"FST3([A-Z])(\d{2})$", code.upper())
            if m:
                month_code = m.group(1)
                year_suffix = int(m.group(2))
                months = "FGHJKMNQUVXZ"
                if month_code in months:
                    month = months.index(month_code) + 1
                    year = 2000 + year_suffix if year_suffix < 80 else 1900 + year_suffix
                    expiry = f"{year}-{month:02d}"
        rows.append(
            _contract_row(
                expiry=expiry or "unknown",
                code=code,
                price=price,
                benchmark=benchmark,
                source="EUREX_FST3_SETTLEMENT",
                volume=_num(row.get(vol_key)) if vol_key else None,
                open_interest=_num(row.get(oi_key)) if oi_key else None,
            )
        )
    if not rows:
        raise EuroAreaRatesError("FST3 settlement CSV contains no contracts")
    return rows


def _latest_estr(observations: Mapping[date, float]) -> dict[str, Any]:
    if not observations:
        raise EuroAreaRatesError("€STR history empty")
    d = max(observations)
    return {"rate": round(float(observations[d]), 6), "as_of": d.isoformat()}


def collect_ea_policy_path(
    today: date,
    fetch_bytes: FetchBytes = default_fetch_bytes,
) -> dict[str, Any]:
    start = today - timedelta(days=120)
    errors: list[str] = []
    benchmark: dict[str, Any] | None = None
    contracts_3m: list[dict[str, Any]] = []
    fst3_status = "unavailable"
    fst3_error = (
        "No credential-free machine-readable FST3 settlement feed responded reliably "
        f"(tried: {', '.join(FST3_URLS_TRIED)})"
    )

    try:
        estr_hist = fetch_estr_history(start, today, fetch_bytes=fetch_bytes)
        benchmark = {"name": "€STR", "source": "ECB_EST", **(_latest_estr(estr_hist))}
        benchmark["source_url"] = ECB_ESTR_PAGE
    except Exception as exc:
        errors.append(f"€STR: {exc}")

    # FST3: document attempts; do not mark tradable without a working public settlement feed.
    for url in FST3_URLS_TRIED:
        try:
            body = fetch_bytes(url)
            text = body.decode("utf-8", errors="replace")
            if "settlement" in text.lower() and text.count(",") > 5:
                # Heuristic only; hosted runners did not return a parseable CSV in validation.
                pass
        except Exception:
            continue

    tradable_curve = {
        "curve_id": "ESTR",
        "status": fst3_status,
        "error": fst3_error,
        "mark_convention": "implied_rate = 100 - futures_price (Eurex STIR convention)",
        "source_urls_tried": list(FST3_URLS_TRIED),
        "contracts": contracts_3m,
    }

    if benchmark is None:
        return {
            "status": "unavailable",
            "country": "EA",
            "error": "; ".join(errors) or "€STR unavailable",
            "benchmark": None,
            "contracts_3m": [],
            "tradable_curve": tradable_curve,
            "sources": {
                "benchmark_url": ECB_ESTR_PAGE,
                "futures_urls_tried": list(FST3_URLS_TRIED),
            },
        }

    status = "partial" if fst3_status != "ok" else "ok"
    return {
        "status": status,
        "country": "EA",
        "benchmark": benchmark,
        "contracts_3m": contracts_3m,
        "tradable_curve": tradable_curve,
        "terminal": contracts_3m[-1] if contracts_3m else None,
        "method": (
            "Overnight: ECB €STR. Policy futures: Eurex FST3 (3M €STR) when a public "
            "settlement feed is available; implied_rate = 100 - price per Eurex STIR quoting."
        ),
        "sources": {
            "benchmark_url": ECB_ESTR_PAGE,
            "estr_series_key": ECB_ESTR_SERIES_KEY,
            "futures_urls_tried": list(FST3_URLS_TRIED),
        },
        "errors": errors,
    }


def parse_ecb_yc_spot_csv(text: str) -> dict[date, float]:
    rows = list(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))))
    out: dict[date, float] = {}
    for row in rows:
        d = _parse_iso_date(row.get("TIME_PERIOD", ""))
        v = _num(row.get("OBS_VALUE"))
        if d is not None and v is not None:
            out[d] = v
    if not out:
        raise EuroAreaRatesError("ECB yield-curve CSV contains no observations")
    return out


def _ecb_yc_spot_url(prefix: str, spot_key: str, start: date, end: date) -> str:
    qs = urllib.parse.urlencode(
        {
            "format": "csvdata",
            "startPeriod": start.isoformat(),
            "endPeriod": end.isoformat(),
        }
    )
    return f"{ECB_YC_API_BASE}/{prefix}.{spot_key}?{qs}"


def _curve_row(value: float, *, as_of: str, maturity_years: float, source: str) -> dict[str, Any]:
    return {
        "value": round(float(value), 10),
        "as_of": as_of,
        "maturity_years": round(float(maturity_years), 8),
        "source": source,
    }


def _maturity_label(years: float) -> str:
    rounded = round(float(years), 8)
    if abs(rounded - round(rounded)) < 1e-8:
        return f"{int(round(rounded))}Y"
    text = f"{rounded:.8f}".rstrip("0").rstrip(".")
    return f"{text}Y"


def collect_ea_official_curve(
    today: date,
    fetch_bytes: FetchBytes = default_fetch_bytes,
) -> dict[str, Any]:
    start = today - timedelta(days=90)
    spot_keys = {"2Y": "SR_2Y", "5Y": "SR_5Y", "10Y": "SR_10Y", "30Y": "SR_30Y"}
    blocks: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}

    for label, prefix in (("all_ratings", ECB_YC_ALL_PREFIX), ("aaa", ECB_YC_AAA_PREFIX)):
        series_by_tenor: dict[str, dict[date, float]] = {}
        try:
            for tenor, spot in spot_keys.items():
                url = _ecb_yc_spot_url(prefix, spot, start, today)
                text = fetch_bytes(url).decode("utf-8", errors="replace")
                series_by_tenor[tenor] = parse_ecb_yc_spot_csv(text)
            dates = {max(s) for s in series_by_tenor.values() if s}
            if len(dates) != 1:
                raise EuroAreaRatesError(f"ECB YC {label} mixed latest dates: {sorted(dates)}")
            as_of = max(dates)
            zero: dict[str, Any] = {}
            for tenor, spot in spot_keys.items():
                val = series_by_tenor[tenor].get(as_of)
                if val is None:
                    continue
                years = float(tenor[:-1])
                zero[tenor] = _curve_row(
                    val,
                    as_of=as_of.isoformat(),
                    maturity_years=years,
                    source=f"ECB_YC_{label.upper()}_SPOT",
                )
            if not zero:
                raise EuroAreaRatesError(f"ECB YC {label} empty on latest date")
            blocks[label] = {
                "status": "ok",
                "as_of": as_of.isoformat(),
                "curve_type": "ecb_svensson_spot_zero_proxy",
                "zero_yields": zero,
                "compounding": (
                    "ECB Svensson spot rates are continuously compounded zero yields in percent"
                ),
                "source_url": ECB_YC_PAGE,
                "technical_notes": ECB_YC_TECHNICAL_NOTES,
                "series_prefix": prefix,
            }
        except Exception as exc:
            blocks[label] = {"status": "unavailable", "error": str(exc)}
            errors[label] = str(exc)

    primary = blocks.get("all_ratings") or {}
    status = "ok" if primary.get("status") == "ok" else "unavailable"
    return {
        "status": status,
        "country": "EA",
        "curves": blocks,
        "errors": errors,
        "method": {
            "model_calls": 0,
            "credentials_required": [],
            "purpose": "official euro-area government zero-curve proxy (ECB Svensson)",
            "ois_equivalence": "proxy_only",
        },
    }


def parse_eurostat_mcby_json(payload: Mapping[str, Any]) -> dict[str, dict[date, float]]:
    """EMU convergence criterion bond yield (~10Y), monthly → month-end dates."""
    dim_ids: list[str] = list(payload.get("id") or [])
    if dim_ids != ["freq", "int_rt", "geo", "time"]:
        raise EuroAreaRatesError("Unexpected Eurostat MCBY JSON shape")
    dimension = payload.get("dimension") or {}
    geo_idx = dimension.get("geo", {}).get("category", {}).get("index") or {}
    time_idx = dimension.get("time", {}).get("category", {}).get("index") or {}
    n_geo = len(geo_idx)
    n_time = len(time_idx)
    values = payload.get("value") or {}
    out: dict[str, dict[date, float]] = {g: {} for g in geo_idx}
    # JSON-stat flattens the last dimension fastest. With id
    # [freq, int_rt, geo, time] and singleton freq/int_rt, time varies
    # fastest and geo is the next outer dimension.
    for flat_key, value in values.items():
        idx = int(flat_key)
        geo_i = idx // n_time
        time_i = idx % n_time
        if geo_i >= n_geo or time_i >= n_time:
            continue
        geo = next(g for g, i in geo_idx.items() if i == geo_i)
        time_key = next(t for t, i in time_idx.items() if i == time_i)
        v = _num(value)
        if v is None:
            continue
        out[geo][_month_end(time_key)] = v
    if not any(out[g] for g in out):
        raise EuroAreaRatesError("Eurostat MCBY JSON contains no values")
    return out


def parse_peripheral_yields_csv(
    text: str,
    *,
    country: str,
    tenor: str,
) -> dict[date, float]:
    """Fixture-friendly daily peripheral yield CSV: date,yield_percent."""
    out: dict[date, float] = {}
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise EuroAreaRatesError(f"{country} {tenor} yield CSV missing header")
    date_key = next((f for f in reader.fieldnames if f.lower() in {"date", "time_period"}), None)
    val_key = next(
        (f for f in reader.fieldnames if f.lower() in {"yield", "yield_percent", "obs_value", "value"}),
        None,
    )
    if not date_key or not val_key:
        raise EuroAreaRatesError(f"{country} {tenor} yield CSV missing date/value columns")
    for row in reader:
        d = _parse_iso_date(row.get(date_key, ""))
        v = _num(row.get(val_key))
        if d is not None and v is not None:
            out[d] = v
    return out


def compute_mcby_fragmentation_spreads(
    *,
    mcby_yields: Mapping[str, Mapping[date, float]],
    countries: tuple[str, ...] = FRAGMENTATION_COUNTRIES,
    tenor: str = "10Y",
) -> dict[str, Any]:
    """Peripheral minus Germany from same Eurostat MCBY monthly map (month-end dates)."""
    de = mcby_yields.get("DE") or {}
    spreads: dict[str, dict[str, dict[str, float]]] = {}
    counts: dict[str, dict[str, int]] = {}
    for country in countries:
        pe = mcby_yields.get(country) or {}
        common = sorted(set(de) & set(pe))
        series: dict[str, float] = {}
        for d in common:
            series[d.isoformat()] = round(float(pe[d]) - float(de[d]), 6)
        spreads[country] = {tenor: series}
        counts[country] = {tenor: len(series)}
    return {"spreads": spreads, "counts": counts}


def compute_fragmentation_spreads(
    *,
    bund_yields: Mapping[str, Mapping[date, float]],
    peripheral_yields: Mapping[str, Mapping[str, Mapping[date, float]]],
    tenors: tuple[str, ...] = FRAGMENTATION_TENORS,
) -> dict[str, Any]:
    """Spreads peripheral minus Germany on exact common dates (no forward fill)."""
    spreads: dict[str, dict[str, dict[str, float]]] = {}
    counts: dict[str, dict[str, int]] = {}
    for country in FRAGMENTATION_COUNTRIES:
        spreads[country] = {}
        counts[country] = {}
        for tenor in tenors:
            de = bund_yields.get(tenor) or {}
            pe = (peripheral_yields.get(country) or {}).get(tenor) or {}
            common = sorted(set(de) & set(pe))
            series: dict[str, float] = {}
            for d in common:
                series[d.isoformat()] = round(float(pe[d]) - float(de[d]), 6)
            spreads[country][tenor] = series
            counts[country][tenor] = len(series)
    return {"spreads": spreads, "counts": counts}


def eurostat_mcby_url(since: str = "2020-01") -> str:
    qs = urllib.parse.urlencode(
        {
            "geo": ["IT", "FR", "ES", "DE"],
            "format": "JSON",
            "lang": "en",
            "sinceTimePeriod": since,
        },
        doseq=True,
    )
    return f"{EUROSTAT_MCBY_URL}?{qs}"


def collect_ea_fragmentation(
    today: date,
    fetch_bytes: FetchBytes = default_fetch_bytes,
) -> dict[str, Any]:
    start = today - timedelta(days=365 * 5)

    source_status: dict[str, dict[str, str]] = {
        c: {t: "unavailable" for t in FRAGMENTATION_TENORS} for c in FRAGMENTATION_COUNTRIES
    }
    mcby: dict[str, dict[date, float]] = {}
    mcby_meta: dict[str, Any] = {
        "dataset": "irt_lt_mcby_m",
        "frequency": "monthly",
        "page": EUROSTAT_MCBY_PAGE,
        "german_leg_10y": "EUROSTAT_MCBY_DE",
        "note": (
            "10Y fragmentation uses IT/FR/ES minus DE from the same Eurostat MCBY payload "
            "(month-end observation dates). Bundesbank BBSSY Bund yields are not mixed into 10Y spreads."
        ),
    }

    try:
        mcby_url = eurostat_mcby_url(since=start.strftime("%Y-%m"))
        mcby_meta["api_url"] = mcby_url
        payload = json.loads(fetch_bytes(mcby_url).decode("utf-8"))
        mcby = parse_eurostat_mcby_json(payload)
        for country in FRAGMENTATION_COUNTRIES:
            if mcby.get(country):
                source_status[country]["10Y"] = "ok"
        if mcby.get("DE"):
            source_status["DE"] = {"10Y": "ok"}
        source_status["_meta"] = {
            "10Y": f"Eurostat irt_lt_mcby_m ({EUROSTAT_MCBY_PAGE})",
            **mcby_meta,
        }
    except Exception as exc:
        source_status["_meta"] = {"10Y_error": str(exc), **mcby_meta}

    for tenor in ("2Y", "5Y"):
        for country in FRAGMENTATION_COUNTRIES:
            source_status[country][tenor] = "unavailable"
    if "_meta" in source_status:
        source_status["_meta"]["2Y"] = (
            "No credential-free daily official 2Y peripheral series pinned yet "
            "(ECB per-country YC keys 404; AFT/Banca d'Italia blocked or undocumented)."
        )
        source_status["_meta"]["5Y"] = source_status["_meta"]["2Y"]

    spread_block = compute_mcby_fragmentation_spreads(mcby_yields=mcby) if mcby else {
        "spreads": {c: {t: {} for t in FRAGMENTATION_TENORS} for c in FRAGMENTATION_COUNTRIES},
        "counts": {c: {t: 0 for t in FRAGMENTATION_TENORS} for c in FRAGMENTATION_COUNTRIES},
    }
    return {
        "status": "partial",
        "block": "euro_area_fragmentation",
        "method": (
            "10Y: peripheral minus Germany from same-source Eurostat irt_lt_mcby_m (monthly, "
            "month-end dates). 2Y/5Y unavailable without credential-free daily peripheral legs."
        ),
        "bund_benchmark": {
            "source": "BUNDESBANK_BBSSY",
            "tenors": list(BUND_SERIES),
            "page": BUNDESBANK_PAGE,
            "used_for_10y_fragmentation": False,
        },
        "mcby_benchmark_10y": mcby_meta,
        "peripheral_sources": source_status,
        "spreads": spread_block["spreads"],
        "observation_counts": spread_block["counts"],
        "as_of": today.isoformat(),
    }


def validate_ea_rates_bundle(payload: Mapping[str, Any]) -> None:
    """Validate a combined EA rates payload (fail loud on required Bund/€STR gaps)."""
    bund = payload.get("bund_rates")
    if not isinstance(bund, Mapping):
        raise EuroAreaRatesError("bundle missing bund_rates")
    for tenor in ("2Y", "5Y", "10Y", "30Y"):
        series = bund.get(tenor)
        if not isinstance(series, Mapping) or not series:
            raise EuroAreaRatesError(f"bundle missing Bund {tenor} history")

    policy = payload.get("policy_path")
    if not isinstance(policy, Mapping):
        raise EuroAreaRatesError("bundle missing policy_path")
    if policy.get("status") == "unavailable":
        raise EuroAreaRatesError(f"€STR policy path unavailable: {policy.get('error')}")
    bench = policy.get("benchmark") or {}
    if bench.get("name") != "€STR" or _num(bench.get("rate")) is None:
        raise EuroAreaRatesError("€STR benchmark missing rate")

    tradable = (policy.get("tradable_curve") or {}).get("status")
    if tradable == "ok":
        contracts = (policy.get("tradable_curve") or {}).get("contracts") or []
        if not contracts:
            raise EuroAreaRatesError("tradable FST3 marked ok without contracts")

    curve = payload.get("official_curve")
    if isinstance(curve, Mapping) and curve.get("status") == "ok":
        primary = (curve.get("curves") or {}).get("all_ratings") or {}
        zeros = primary.get("zero_yields") or {}
        for tenor in ("2Y", "5Y", "10Y"):
            if tenor not in zeros:
                raise EuroAreaRatesError(f"ECB official curve missing {tenor}")

    frag = payload.get("fragmentation")
    if isinstance(frag, Mapping):
        spreads = frag.get("spreads")
        if not isinstance(spreads, Mapping):
            raise EuroAreaRatesError("fragmentation missing spreads map")


def build_ea_rates_bundle(
    today: date,
    fetch_bytes: FetchBytes = default_fetch_bytes,
) -> dict[str, Any]:
    start = today - timedelta(days=365 * 5)
    bund = fetch_ea_bund_rates(start, today, fetch_bytes=fetch_bytes)
    return {
        "bund_rates": {t: {d.isoformat(): v for d, v in s.items()} for t, s in bund.items()},
        "policy_path": collect_ea_policy_path(today, fetch_bytes=fetch_bytes),
        "official_curve": collect_ea_official_curve(today, fetch_bytes=fetch_bytes),
        "fragmentation": collect_ea_fragmentation(today, fetch_bytes=fetch_bytes),
        "stale_after_days": STALE_AFTER_DAYS_EA,
    }
