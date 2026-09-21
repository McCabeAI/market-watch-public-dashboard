"""Free, maintained U.S. housing data for Market Watch."""

from __future__ import annotations

import csv
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from typing import Any, Callable, Mapping

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"

SERIES = {
    "HPIPONM226S": ("FHFA Purchase Only House Price Index", "index", "monthly", 12, "Federal Housing Finance Agency"),
    "HSN1F": ("New One Family Houses Sold", "thousands SAAR", "monthly", 12, "U.S. Census Bureau / HUD"),
    "MSACSR": ("Monthly Supply of New Houses", "months", "monthly", 12, "U.S. Census Bureau / HUD"),
    "HNFSEPUSSA": ("New One Family Houses for Sale", "thousands", "monthly", 12, "U.S. Census Bureau / HUD"),
    "MSPNHSUS": ("Median Sales Price of New Houses Sold", "USD", "monthly", 12, "U.S. Census Bureau / HUD"),
    "PERMIT": ("New Privately Owned Housing Units Authorized by Building Permits", "thousands SAAR", "monthly", 12, "U.S. Census Bureau / HUD"),
    "HOUST": ("Housing Starts: Total", "thousands SAAR", "monthly", 12, "U.S. Census Bureau / HUD"),
    "HOUST1F": ("Housing Starts: Single Family", "thousands SAAR", "monthly", 12, "U.S. Census Bureau / HUD"),
    "COMPUTSA": ("Housing Completions: Total", "thousands SAAR", "monthly", 12, "U.S. Census Bureau / HUD"),
    "COMPU1USA": ("Housing Completions: Single Family", "thousands SAAR", "monthly", 12, "U.S. Census Bureau / HUD"),
    "HHMSDODNS": ("Household One-to-Four-Family Residential Mortgage Liabilities", "USD millions", "quarterly", 4, "Federal Reserve Board"),
    "MORTGAGE30US": ("30-Year Fixed Rate Mortgage Average", "percent", "weekly", 52, "Freddie Mac"),
    "MDSP": ("Mortgage Debt Service Payments as Percent of Disposable Personal Income", "percent", "quarterly", 4, "Federal Reserve Board"),
}

FEEDS = {
    "prices": ("HPIPONM226S",),
    "sales_inventory": ("HSN1F", "MSACSR", "HNFSEPUSSA", "MSPNHSUS"),
    "construction": ("PERMIT", "HOUST", "HOUST1F", "COMPUTSA", "COMPU1USA"),
    "mortgage_credit": ("HHMSDODNS",),
    "mortgage_rates": ("MORTGAGE30US",),
    "mortgage_burden": ("MDSP",),
}


class USHousingError(RuntimeError):
    pass


def _num(value: object) -> float | None:
    try:
        v = float(str(value).strip().replace(",", ""))
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def _date(value: object) -> date | None:
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def parse_fred_csv(text: str) -> dict[str, list[tuple[date, float]]]:
    reader = csv.DictReader(io.StringIO(text))
    fields = reader.fieldnames or []
    date_col = "observation_date" if "observation_date" in fields else "DATE" if "DATE" in fields else None
    if not date_col:
        raise USHousingError("FRED response missing date column")
    found = [sid for sid in SERIES if sid in fields]
    if not found:
        raise USHousingError("FRED response contains none of the requested housing series")
    out = {sid: [] for sid in found}
    for row in reader:
        d = _date(row.get(date_col))
        if not d:
            continue
        for sid in found:
            v = _num(row.get(sid))
            if v is not None:
                out[sid].append((d, v))
    return out


def _changes(items: list[tuple[date, float]], lag: int) -> dict[str, float | None]:
    if not items:
        return {"value": None, "change_prev": None, "change_prev_pct": None, "change_yoy": None, "change_yoy_pct": None}
    items = sorted(items)
    latest = items[-1][1]
    prev = items[-2][1] if len(items) > 1 else None
    yoy = items[-1 - lag][1] if len(items) > lag else None
    def pct(old):
        return None if old in (None, 0) else (latest / old - 1.0) * 100.0
    return {
        "value": latest,
        "change_prev": None if prev is None else latest - prev,
        "change_prev_pct": pct(prev),
        "change_yoy": None if yoy is None else latest - yoy,
        "change_yoy_pct": pct(yoy),
    }


def _feed(name: str, series_data: Mapping[str, list[tuple[date, float]]], today: date) -> dict[str, Any]:
    sids = FEEDS[name]
    missing = [sid for sid in sids if not series_data.get(sid)]
    if missing:
        return {
            "status": "unavailable",
            "source_name": "FRED / original series publishers",
            "url": FRED_CSV.format(series=",".join(sids)),
            "as_of": None,
            "age_days": None,
            "error": f"missing requested FRED housing series: {missing}",
        }
    latest_date = max(series_data[sid][-1][0] for sid in sids)
    metrics: dict[str, Any] = {}
    series_meta: dict[str, Any] = {}
    for sid in sids:
        label, unit, frequency, lag, publisher = SERIES[sid]
        points = series_data[sid]
        m = _changes(points, lag)
        metrics[sid] = {"as_of": points[-1][0].isoformat(), "unit": unit, **m}
        series_meta[sid] = {
            "label": label,
            "frequency": frequency,
            "publisher": publisher,
            "series_url": f"https://fred.stlouisfed.org/series/{sid}",
        }
    age = max(0, (today - latest_date).days)
    # Quarterly burden/credit can legitimately be months old; monthly and weekly data cannot.
    max_age = 140 if all(SERIES[sid][2] == "quarterly" for sid in sids) else 75
    return {
        "status": "stale" if age > max_age else "ok",
        "source_name": "FRED / original series publishers",
        "url": FRED_CSV.format(series=",".join(sids)),
        "as_of": latest_date.isoformat(),
        "age_days": age,
        "metrics": metrics,
        "series": series_meta,
    }


def collect_us_housing(*, today: date, fetch_bytes: Callable[..., bytes]) -> dict[str, Any]:
    def one(sid: str):
        try:
            raw = fetch_bytes(FRED_CSV.format(series=sid)).decode("utf-8-sig", errors="replace")
            parsed = parse_fred_csv(raw)
            return sid, parsed.get(sid) or [], None
        except Exception as exc:
            return sid, [], str(exc)

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(one, SERIES))
    data = {sid: points for sid, points, _ in results}
    errors = {sid: err for sid, _, err in results if err}

    feeds = {}
    for name, sids in FEEDS.items():
        missing_errors = {sid: errors[sid] for sid in sids if sid in errors}
        if missing_errors:
            feeds[name] = {
                "status": "unavailable",
                "source_name": "FRED / original series publishers",
                "url": FRED_CSV.format(series=",".join(sids)),
                "as_of": None,
                "age_days": None,
                "error": f"FRED series fetch failed: {missing_errors}",
            }
        else:
            feeds[name] = _feed(name, data, today)

    usable = sum(feed.get("status") in {"ok", "stale"} for feed in feeds.values())
    status = (
        "unavailable" if not usable
        else "partial" if usable != len(feeds) or any(feed.get("status") == "stale" for feed in feeds.values())
        else "ok"
    )
    return {
        "country": "US",
        "status": status,
        "feeds": feeds,
        "method": {
            "model_calls": 0,
            "credentials_required": [],
            "purpose": "Free maintained U.S. housing transmission data for Market Watch and Trader Room context.",
            "trader_packet_delivery": "market_state_passthrough",
            "note": "FRED is the automated distributor; each series preserves its original public publisher. Existing-home sales are not included because the canonical free official stack used here does not provide a maintained NAR resale-sales feed.",
        },
    }


def validate_us_housing(block: Mapping[str, Any]) -> None:
    if block.get("country") != "US" or block.get("status") not in {"ok", "partial", "unavailable"}:
        raise USHousingError("invalid U.S. housing block")
    feeds = block.get("feeds")
    if not isinstance(feeds, Mapping) or set(feeds) != set(FEEDS):
        raise USHousingError("U.S. housing feeds incomplete")
    for name, feed in feeds.items():
        if feed.get("status") not in {"ok", "stale", "unavailable"} or not feed.get("url"):
            raise USHousingError(f"invalid U.S. housing feed {name}")
        if feed.get("status") == "unavailable" and not feed.get("error"):
            raise USHousingError(f"{name} unavailable without provenance")
        if feed.get("status") != "unavailable" and not feed.get("as_of"):
            raise USHousingError(f"{name} missing as_of")
