"""Free, maintained Canadian housing data for Market Watch."""

from __future__ import annotations

import csv
import html
import io
import json
import re
from datetime import date, datetime
from typing import Any, Callable, Mapping

STATCAN_NHPI_CSV = "https://www150.statcan.gc.ca/t1/tbl1/en/dtl!downloadDbLoadingData-nonTraduit.action?pid=1810020501&latestN=5&startDate=&endDate=&csvLocale=en&selectedMembers=%5B%5B1%5D%2C%5B1%2C2%2C3%5D%5D&checkedLevels="
STATCAN_PERMITS_CSV = "https://www150.statcan.gc.ca/t1/tbl1/en/dtl!downloadDbLoadingData-nonTraduit.action?pid=3410029201&latestN=5&startDate=&endDate=&csvLocale=en&selectedMembers=%5B%5B1%5D%2C%5B4%2C7%2C15%2C33%2C36%2C49%2C73%5D%2C%5B1%5D%2C%5B1%5D%2C%5B2%5D%5D&checkedLevels=1D1"
STATCAN_DSR_CSV = "https://www150.statcan.gc.ca/t1/tbl1/en/dtl!downloadDbLoadingData-nonTraduit.action?pid=1110006501&latestN=5&startDate=&endDate=&csvLocale=en&selectedMembers=%5B%5B1%5D%2C%5B1%5D%2C%5B1%2C2%2C3%2C4%2C5%2C6%2C7%2C8%2C9%2C10%2C11%2C12%2C13%2C14%2C15%2C16%2C17%2C18%2C19%2C20%2C21%2C22%2C23%2C24%2C25%2C26%2C27%2C28%2C29%5D%5D&checkedLevels="
STATCAN_NHPI_PAGE = "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1810020501"
STATCAN_PERMITS_PAGE = "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3410029201"
STATCAN_DSR_PAGE = "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1110006501"
CMHC_STARTS_PAGE = "https://www.cmhc-schl.gc.ca/professionals/housing-markets-data-and-research/housing-data/data-tables/housing-market-data/monthly-housing-starts-construction-data-tables"
BOC_VALET = "https://www.bankofcanada.ca/valet/observations/{series}/json?recent=16"
BOC_RATES_PAGE = "https://www.bankofcanada.ca/rates/banking-and-financial-statistics/interest-rates-for-new-and-existing-lending-by-chartered-banks/"
BOC_LENDING_PAGE = "https://www.bankofcanada.ca/rates/banking-and-financial-statistics/funds-advanced-and-outstanding-balances-for-new-and-existing-lending-by-chartered-banks/"

# Exact Bank of Canada Valet IDs from the chartered-bank lending tables.
BOC_FUNDS = {
    "insured_funds_advanced": "V122667724",
    "uninsured_funds_advanced": "V122667730",
    "insured_outstanding_balance": "V122667736",
    "uninsured_outstanding_balance": "V122667742",
}
BOC_RATES = {
    "insured_new_rate": "V122667775",
    "uninsured_new_rate": "V122667781",
    "insured_outstanding_rate": "V122667787",
    "uninsured_outstanding_rate": "V122667793",
}
FEEDS = {
    "new_home_prices",
    "construction",
    "building_permits",
    "mortgage_lending",
    "mortgage_balances",
    "mortgage_rates",
    "mortgage_burden",
}


class CanadaHousingError(RuntimeError):
    pass


def _num(value: object) -> float | None:
    try:
        v = float(str(value).strip().replace(",", "").replace("$", "").replace("%", ""))
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def _date(value: object) -> date | None:
    s = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%YQ%q"):
        if "%q" in fmt:
            continue
        try:
            d = datetime.strptime(s, fmt)
            if fmt == "%Y-%m":
                return date(d.year, d.month, 1)
            return d.date()
        except ValueError:
            pass
    q = re.fullmatch(r"(\d{4})Q([1-4])", s)
    if q:
        return date(int(q.group(1)), int(q.group(2)) * 3, 1)
    return None


def _clean_html(raw: str) -> str:
    raw = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(raw)).strip()


def _statcan_rows(url: str, fetch_bytes: Callable[..., bytes]) -> list[dict[str, str]]:
    """Fetch only the small displayed/selected slice, never the full national cube."""
    text = fetch_bytes(url).decode("utf-8-sig", errors="replace")
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise CanadaHousingError("Statistics Canada selected-data CSV returned no rows")
    return rows


def _latest_matching(
    rows: list[Mapping[str, str]],
    *,
    exact_values: tuple[str, ...] = (),
    vector: str | None = None,
) -> list[Mapping[str, str]]:
    matches = []
    for row in rows:
        vals = {str(v).strip() for v in row.values() if v is not None}
        if vector and str(row.get("VECTOR") or "").strip().lower() != vector.lower():
            continue
        if any(value not in vals for value in exact_values):
            continue
        d = _date(row.get("REF_DATE"))
        if d and _num(row.get("VALUE")) is not None:
            matches.append(row)
    if not matches:
        raise CanadaHousingError(f"Statistics Canada selector returned no rows: values={exact_values} vector={vector}")
    latest_ref = max(str(row["REF_DATE"]) for row in matches)
    return [row for row in matches if str(row["REF_DATE"]) == latest_ref]


def parse_statcan_nhpi(rows: list[Mapping[str, str]]) -> dict[str, Any]:
    latest = _latest_matching(rows, exact_values=("Canada", "Total (house and land)"))
    if len(latest) != 1:
        # Prefer the actual index level if a transformed/alternate unit is also present.
        idx = [r for r in latest if str(r.get("UOM") or "").startswith("Index")]
        latest = idx or latest
    row = latest[0]
    ref = str(row["REF_DATE"])
    return {
        "as_of": (_date(ref) or date.min).isoformat(),
        "reference_period": ref,
        "metrics": {
            "new_housing_price_index": {
                "value": _num(row["VALUE"]),
                "unit": row.get("UOM") or "Index",
                "component": "Total (house and land)",
            }
        },
        "note": "Statistics Canada's NHPI measures builders' selling prices for new residential houses; it is not a resale-home price index.",
    }


def parse_statcan_permits(rows: list[Mapping[str, str]]) -> dict[str, Any]:
    selectors = {
        "total_residential_permit_value": ("Canada", "Total residential", "Types of work, total", "Value of permits"),
        "single_dwelling_permit_value": ("Canada", "Single dwelling building total", "Types of work, total", "Value of permits"),
        "multiple_dwelling_permit_value": ("Canada", "Multiple dwelling building total", "Types of work, total", "Value of permits"),
    }
    metrics = {}
    latest_dates = []
    for key, selector in selectors.items():
        rows_match = _latest_matching(rows, exact_values=selector)
        # Prefer seasonally adjusted current-dollar rows when the table includes variants.
        preferred = [
            r for r in rows_match
            if "Seasonally adjusted, current" in {str(v).strip() for v in r.values() if v is not None}
        ]
        row = (preferred or rows_match)[0]
        d = _date(row["REF_DATE"])
        if d:
            latest_dates.append(d)
        metrics[key] = {
            "value": _num(row["VALUE"]),
            "unit": row.get("UOM") or "x 1,000 dollars",
            "scalar_factor": row.get("SCALAR_FACTOR"),
        }
    if not latest_dates:
        raise CanadaHousingError("Statistics Canada building permits missing dates")
    return {"as_of": max(latest_dates).isoformat(), "metrics": metrics}


def parse_statcan_mortgage_dsr(rows: list[Mapping[str, str]]) -> dict[str, Any]:
    rows_match = _latest_matching(rows, vector="v99451480")
    row = rows_match[0]
    ref = str(row["REF_DATE"])
    return {
        "as_of": (_date(ref) or date.min).isoformat(),
        "reference_period": ref,
        "metrics": {
            "mortgage_debt_service_ratio_pct": {
                "value": _num(row["VALUE"]),
                "unit": row.get("UOM") or "percent",
                "vector": "v99451480",
            }
        },
    }


def parse_cmhc_starts(raw: str) -> dict[str, Any]:
    text = _clean_html(raw)
    trend = re.search(r"decrease of ([\d.]+)% to ([\d,]+) units", text, re.I)
    actual = re.search(r"Actual housing starts were down ([\d.]+)% year-over-year.*?([\d,]+) units were recorded in ([A-Za-z]+) (\d{4})", text, re.I)
    ytd = re.search(r"year-to-date total was ([\d,]+) units, down ([\d.]+)%", text, re.I)
    saar = re.search(r"annualized rate of housing starts for all areas in Canada was .*? at ([\d,]+)\s*units compared to ([\d,]+) units in ([A-Za-z]+) (\d{4})", text, re.I)
    published = re.search(r"Date Published:\s*([A-Za-z]+ \d{1,2}, \d{4})", text, re.I)
    if not (trend and actual and ytd and saar and published):
        raise CanadaHousingError("CMHC monthly housing-start highlights missing")
    pd = datetime.strptime(published.group(1), "%B %d, %Y").date()
    return {
        "as_of": pd.isoformat(),
        "metrics": {
            "six_month_start_trend_saar": {"value": _num(trend.group(2)), "unit": "units SAAR", "change_mom_pct": -abs(_num(trend.group(1)) or 0)},
            "actual_starts_centres_10k_plus": {"value": _num(actual.group(2)), "unit": "units", "change_yoy_pct": -abs(_num(actual.group(1)) or 0)},
            "year_to_date_starts": {"value": _num(ytd.group(1)), "unit": "units", "change_yoy_pct": -abs(_num(ytd.group(2)) or 0)},
            "standalone_monthly_starts_saar": {"value": _num(saar.group(1)), "unit": "units SAAR", "previous_value": _num(saar.group(2))},
        },
        "note": "CMHC monthly Starts and Completions Survey / Market Absorption Survey.",
    }


def _boc_history(series: str, fetch_bytes: Callable[..., bytes]) -> list[tuple[date, float]]:
    url = BOC_VALET.format(series=series)
    data = json.loads(fetch_bytes(url).decode("utf-8-sig", errors="replace"))
    points = []
    for obs in data.get("observations") or []:
        d = _date(obs.get("d"))
        v = _num((obs.get(series) or {}).get("v"))
        if d and v is not None:
            points.append((d, v))
    if not points:
        raise CanadaHousingError(f"Bank of Canada Valet returned no data for {series}")
    return sorted(points)


def _series_metric(points: list[tuple[date, float]], unit: str, yoy_lag: int = 12) -> dict[str, Any]:
    latest_d, latest = points[-1]
    prev = points[-2][1] if len(points) > 1 else None
    yoy = points[-1 - yoy_lag][1] if len(points) > yoy_lag else None
    return {
        "as_of": latest_d.isoformat(),
        "value": latest,
        "unit": unit,
        "change_prev": None if prev is None else latest - prev,
        "change_yoy_pct": None if yoy in (None, 0) else (latest / yoy - 1.0) * 100.0,
    }


def _boc_feed(mapping: Mapping[str, str], *, unit: str, page: str, today: date, fetch_bytes: Callable[..., bytes]) -> dict[str, Any]:
    metrics = {}
    dates = []
    try:
        for name, sid in mapping.items():
            points = _boc_history(sid, fetch_bytes)
            metrics[name] = {"series_id": sid, **_series_metric(points, unit)}
            dates.append(points[-1][0])
    except Exception as exc:
        return {"status": "unavailable", "source_name": "Bank of Canada Valet", "url": page, "as_of": None, "age_days": None, "error": str(exc)}
    as_of = max(dates)
    age = max(0, (today - as_of).days)
    return {
        "status": "stale" if age > 75 else "ok",
        "source_name": "Bank of Canada Valet",
        "url": page,
        "as_of": as_of.isoformat(),
        "age_days": age,
        "metrics": metrics,
    }


def _statcan_feed(name: str, csv_url: str, page: str, parser, *, today: date, fetch_bytes: Callable[..., bytes], quarterly: bool = False) -> dict[str, Any]:
    try:
        parsed = parser(_statcan_rows(csv_url, fetch_bytes))
        d = _date(parsed.get("as_of"))
        age = max(0, (today - d).days) if d else None
        max_age = 140 if quarterly else 75
        return {
            "status": "stale" if age is not None and age > max_age else "ok",
            "source_name": f"Statistics Canada table {name}",
            "url": page,
            "age_days": age,
            **parsed,
        }
    except Exception as exc:
        return {"status": "unavailable", "source_name": f"Statistics Canada table {name}", "url": page, "as_of": None, "age_days": None, "error": str(exc)}


def collect_canada_housing(*, today: date, fetch_bytes: Callable[..., bytes]) -> dict[str, Any]:
    prices = _statcan_feed("18-10-0205-01", STATCAN_NHPI_CSV, STATCAN_NHPI_PAGE, parse_statcan_nhpi, today=today, fetch_bytes=fetch_bytes)
    permits = _statcan_feed("34-10-0292-01", STATCAN_PERMITS_CSV, STATCAN_PERMITS_PAGE, parse_statcan_permits, today=today, fetch_bytes=fetch_bytes)
    burden = _statcan_feed("11-10-0065-01", STATCAN_DSR_CSV, STATCAN_DSR_PAGE, parse_statcan_mortgage_dsr, today=today, fetch_bytes=fetch_bytes, quarterly=True)
    try:
        parsed_starts = parse_cmhc_starts(fetch_bytes(CMHC_STARTS_PAGE).decode("utf-8-sig", errors="replace"))
        d = _date(parsed_starts["as_of"])
        age = max(0, (today - d).days) if d else None
        construction = {
            "status": "stale" if age is not None and age > 75 else "ok",
            "source_name": "Canada Mortgage and Housing Corporation",
            "url": CMHC_STARTS_PAGE,
            "age_days": age,
            **parsed_starts,
        }
    except Exception as exc:
        construction = {"status": "unavailable", "source_name": "Canada Mortgage and Housing Corporation", "url": CMHC_STARTS_PAGE, "as_of": None, "age_days": None, "error": str(exc)}

    lending_balances = _boc_feed(BOC_FUNDS, unit="CAD millions", page=BOC_LENDING_PAGE, today=today, fetch_bytes=fetch_bytes)
    if lending_balances.get("status") == "unavailable":
        mortgage_lending = dict(lending_balances)
        mortgage_balances = dict(lending_balances)
    else:
        common = {**lending_balances, "metrics": {}}
        mortgage_lending = dict(common)
        mortgage_lending["metrics"] = {k: v for k, v in lending_balances["metrics"].items() if "funds_advanced" in k}
        mortgage_balances = dict(common)
        mortgage_balances["metrics"] = {k: v for k, v in lending_balances["metrics"].items() if "outstanding_balance" in k}

    feeds = {
        "new_home_prices": prices,
        "construction": construction,
        "building_permits": permits,
        "mortgage_lending": mortgage_lending,
        "mortgage_balances": mortgage_balances,
        "mortgage_rates": _boc_feed(BOC_RATES, unit="percent", page=BOC_RATES_PAGE, today=today, fetch_bytes=fetch_bytes),
        "mortgage_burden": burden,
    }
    usable = sum(feed.get("status") in {"ok", "stale"} for feed in feeds.values())
    status = (
        "unavailable" if not usable
        else "partial" if usable != len(feeds) or any(feed.get("status") == "stale" for feed in feeds.values())
        else "ok"
    )
    return {
        "country": "CA",
        "status": status,
        "feeds": feeds,
        "method": {
            "model_calls": 0,
            "credentials_required": [],
            "purpose": "Official/free Canadian housing transmission data for Market Watch and Trader Room context.",
            "trader_packet_delivery": "market_state_passthrough",
            "note": "Statistics Canada NHPI is a new-home price index, not a resale index. No paid or association-licensed resale-sales series is substituted.",
        },
    }


def validate_canada_housing(block: Mapping[str, Any]) -> None:
    if block.get("country") != "CA" or block.get("status") not in {"ok", "partial", "unavailable"}:
        raise CanadaHousingError("invalid Canadian housing block")
    feeds = block.get("feeds")
    if not isinstance(feeds, Mapping) or set(feeds) != FEEDS:
        raise CanadaHousingError("Canadian housing feeds incomplete")
    for name, feed in feeds.items():
        if feed.get("status") not in {"ok", "stale", "unavailable"} or not feed.get("url"):
            raise CanadaHousingError(f"invalid Canadian housing feed {name}")
        if feed.get("status") == "unavailable" and not feed.get("error"):
            raise CanadaHousingError(f"{name} unavailable without provenance")
        if feed.get("status") != "unavailable" and not feed.get("as_of"):
            raise CanadaHousingError(f"{name} missing as_of")
