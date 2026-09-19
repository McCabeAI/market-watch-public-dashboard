"""Official government zero/forward curves for paper forward-forward marks.

These curves are deterministic research/reference proxies for swap/OIS forward curves in
Market Watch's paper competition. They are not executable swap/OIS quotes.

Sources:
- US: Federal Reserve staff nominal zero-coupon curve (Svensson), continuously compounded.
- CA: Bank of Canada Government of Canada zero-coupon curve, continuously compounded.
- AU: RBA F17 zero-coupon analytical series; use published discount factors directly.
"""

from __future__ import annotations

import csv
import io
import math
import urllib.parse
from datetime import date, datetime, timedelta
from typing import Any, Callable, Mapping

FetchBytes = Callable[..., bytes]

FED_ZERO_CSV = "https://www.federalreserve.gov/data/yield-curve-tables/feds200628.csv"
FED_ZERO_PAGE = "https://www.federalreserve.gov/data/nominal-yield-curve.htm"

BOC_ZERO_PAGE = "https://www.bankofcanada.ca/rates/interest-rates/bond-yield-curves/"
BOC_ZERO_CSV = "https://www.bankofcanada.ca/stats/results/csv"

RBA_F17_DISCOUNT_CSV = "https://www.rba.gov.au/statistics/tables/csv/f17-discount-factors.csv"
RBA_F17_FORWARD_CSV = "https://www.rba.gov.au/statistics/tables/csv/f17-forward-rates.csv"
RBA_F17_YIELD_CSV = "https://www.rba.gov.au/statistics/tables/csv/f17-yields.csv"
RBA_F17_PAGE = "https://www.rba.gov.au/statistics/tables/"

BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


class ForwardCurveError(ValueError):
    pass


def _num(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text.upper() in {"NA", "N/A", "..", "-", "—"}:
        return None
    try:
        value_f = float(text)
    except ValueError:
        return None
    return value_f if math.isfinite(value_f) else None


def _date(value: Any) -> date | None:
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _tenor_key(years: float) -> str:
    if abs(years - round(years)) < 1e-10:
        return f"{int(round(years))}Y"
    text = f"{years:.2f}".rstrip("0").rstrip(".")
    return f"{text}Y"


def _continuous_discount(zero_yield_pct: float, years: float) -> float:
    return math.exp(-(zero_yield_pct / 100.0) * years)


def _curve_status(as_of: date | None, today: date) -> tuple[str, int | None]:
    if as_of is None:
        return "unavailable", None
    age = max(0, (today - as_of).days)
    # These analytical curves publish on different schedules. Keep them usable as
    # explicit paper proxies while surfacing age; do not pretend delayed curves are live.
    return ("ok" if age <= 14 else "stale"), age


def _curve_block(
    *,
    country: str,
    as_of: date,
    zero_yields_pct: Mapping[str, float],
    discount_factors: Mapping[str, float],
    source_name: str,
    source_url: str,
    today: date,
    forward_rates_pct: Mapping[str, float] | None = None,
    notes: str,
) -> dict[str, Any]:
    status, age = _curve_status(as_of, today)
    zeros = {
        tenor: {"value": round(float(value), 8), "as_of": as_of.isoformat()}
        for tenor, value in zero_yields_pct.items()
    }
    dfs = {
        tenor: {"discount_factor": round(float(value), 12), "as_of": as_of.isoformat()}
        for tenor, value in discount_factors.items()
    }
    forwards = {
        tenor: {"value": round(float(value), 8), "as_of": as_of.isoformat()}
        for tenor, value in (forward_rates_pct or {}).items()
    }
    required = ("2Y", "3Y", "4Y")
    missing = [tenor for tenor in required if tenor not in dfs]
    if missing:
        raise ForwardCurveError(f"{country} curve missing required discount maturities {missing}")
    return {
        "status": status,
        "as_of": as_of.isoformat(),
        "age_days": age,
        "curve_type": "government_zero_curve_proxy",
        "proxy_for": f"{country} swap/OIS forward-forward paper marks",
        "zero_yields_pct": zeros,
        "discount_factors": dfs,
        "instantaneous_or_published_forwards_pct": forwards,
        "source": {
            "name": source_name,
            "url": source_url,
        },
        "notes": notes,
    }


def parse_fed_zero_csv(text: str, *, today: date) -> dict[str, Any]:
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    header_idx = next(
        (i for i, row in enumerate(rows) if row and row[0].strip() == "Date" and "SVENY02" in row),
        None,
    )
    if header_idx is None:
        raise ForwardCurveError("Fed zero-curve CSV missing Date/SVENY headers")
    header = rows[header_idx]
    zero_cols: dict[int, tuple[str, float]] = {}
    forward_cols: dict[int, tuple[str, float]] = {}
    for idx, name in enumerate(header):
        name = name.strip()
        if name.startswith("SVENY") and name[5:].isdigit():
            years = float(int(name[5:]))
            zero_cols[idx] = (_tenor_key(years), years)
        elif name.startswith("SVENF") and name[5:].isdigit():
            years = float(int(name[5:]))
            forward_cols[idx] = (_tenor_key(years), years)
    if not zero_cols:
        raise ForwardCurveError("Fed zero-curve CSV has no SVENY columns")

    latest: tuple[date, list[str]] | None = None
    for row in rows[header_idx + 1 :]:
        if not row:
            continue
        d = _date(row[0])
        if d is None:
            continue
        # Fed sometimes appends calendar dates with all NA; require 2Y/3Y/4Y actual values.
        def cell_for(mnemonic: str) -> float | None:
            try:
                idx = header.index(mnemonic)
            except ValueError:
                return None
            return _num(row[idx] if idx < len(row) else None)
        if any(cell_for(m) is None for m in ("SVENY02", "SVENY03", "SVENY04")):
            continue
        if latest is None or d > latest[0]:
            latest = (d, row)
    if latest is None:
        raise ForwardCurveError("Fed zero-curve CSV has no usable dated rows")

    as_of, row = latest
    zero: dict[str, float] = {}
    discounts: dict[str, float] = {}
    published_forwards: dict[str, float] = {}
    for idx, (tenor, years) in zero_cols.items():
        value = _num(row[idx] if idx < len(row) else None)
        if value is None:
            continue
        zero[tenor] = value
        discounts[tenor] = _continuous_discount(value, years)
    for idx, (tenor, _years) in forward_cols.items():
        value = _num(row[idx] if idx < len(row) else None)
        if value is not None:
            published_forwards[tenor] = value

    return _curve_block(
        country="US",
        as_of=as_of,
        zero_yields_pct=zero,
        discount_factors=discounts,
        forward_rates_pct=published_forwards,
        source_name="Federal Reserve staff nominal zero-coupon yield curve",
        source_url=FED_ZERO_PAGE,
        today=today,
        notes=(
            "Fed staff Svensson Treasury curve; SVENY zero yields are continuously compounded. "
            "Accepted as a close-enough proxy for USD swap/OIS forward-forward paper marks."
        ),
    )


def _parse_rba_f17_grid(text: str, *, expected_phrase: str) -> tuple[date, dict[str, float]]:
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    title_idx = next((i for i, row in enumerate(rows) if row and row[0].strip().lower() == "title"), None)
    series_idx = next((i for i, row in enumerate(rows) if row and row[0].strip().lower() == "series id"), None)
    if title_idx is None or series_idx is None:
        raise ForwardCurveError("RBA F17 metadata rows missing")
    titles = rows[title_idx]
    columns: dict[int, tuple[str, float]] = {}
    for idx, title in enumerate(titles[1:], start=1):
        label = title.strip().lower()
        if expected_phrase not in label:
            continue
        # e.g. "Zero-coupon discount factor – 2.25 yrs"
        tail = label.split("–")[-1].strip()
        number = tail.split()[0]
        years = _num(number)
        if years is None:
            continue
        columns[idx] = (_tenor_key(years), years)
    if not columns:
        raise ForwardCurveError(f"RBA F17 could not discover {expected_phrase} maturities")

    latest: tuple[date, dict[str, float]] | None = None
    for row in rows[series_idx + 1 :]:
        if not row:
            continue
        d = _date(row[0])
        if d is None:
            continue
        values: dict[str, float] = {}
        for idx, (tenor, _years) in columns.items():
            value = _num(row[idx] if idx < len(row) else None)
            if value is not None:
                values[tenor] = value
        if all(key in values for key in ("2Y", "3Y", "4Y")) and (latest is None or d > latest[0]):
            latest = (d, values)
    if latest is None:
        raise ForwardCurveError(f"RBA F17 {expected_phrase} file has no usable dated row")
    return latest


def parse_rba_f17(
    discount_text: str,
    *,
    today: date,
    yield_text: str | None = None,
    forward_text: str | None = None,
) -> dict[str, Any]:
    as_of, discounts = _parse_rba_f17_grid(discount_text, expected_phrase="zero-coupon discount factor")
    zeros: dict[str, float] = {}
    forwards: dict[str, float] = {}
    if yield_text:
        y_date, zeros = _parse_rba_f17_grid(yield_text, expected_phrase="zero-coupon yield")
        if y_date != as_of:
            # Keep one coherent curve vintage; direct discounts are canonical.
            zeros = {}
    if forward_text:
        f_date, forwards = _parse_rba_f17_grid(forward_text, expected_phrase="zero-coupon forward rate")
        if f_date != as_of:
            forwards = {}
    return _curve_block(
        country="AU",
        as_of=as_of,
        zero_yields_pct=zeros,
        discount_factors=discounts,
        forward_rates_pct=forwards,
        source_name="Reserve Bank of Australia F17 zero-coupon analytical series",
        source_url=RBA_F17_PAGE,
        today=today,
        notes=(
            "RBA-published government zero-coupon discount curve. Accepted as a close-enough "
            "proxy for AUD swap/OIS forward-forward paper marks."
        ),
    )


def parse_boc_zero_csv(text: str, *, today: date) -> dict[str, Any]:
    """Parse BoC zero-coupon curve download.

    The BoC publication contract defines each dated row as one curve with 120 values,
    ordered 0.25y, 0.50y, ... 30.00y. Use an explicit numeric header when present;
    otherwise use that official fixed quarter-year grid.
    """
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    latest: tuple[date, list[float]] | None = None
    for row in rows:
        if not row:
            continue
        d = _date(row[0])
        if d is None:
            continue
        values = [_num(cell) for cell in row[1:]]
        numeric = [value for value in values if value is not None]
        if len(numeric) < 16:
            continue
        if latest is None or d > latest[0]:
            latest = (d, numeric)
    if latest is None:
        raise ForwardCurveError("BoC zero-coupon CSV has no usable dated curve rows")

    as_of, values = latest
    if len(values) < 16:
        raise ForwardCurveError("BoC zero-coupon curve does not reach 4Y")
    # Official BoC page: columns 1..120 map 0.25y..30.00y and values are decimals.
    zero: dict[str, float] = {}
    discounts: dict[str, float] = {}
    for i, decimal_yield in enumerate(values[:120], start=1):
        years = 0.25 * i
        if not (-0.10 < decimal_yield < 0.30):
            raise ForwardCurveError(
                f"BoC zero-coupon value {decimal_yield} outside expected decimal-yield range"
            )
        tenor = _tenor_key(years)
        pct = decimal_yield * 100.0
        zero[tenor] = pct
        discounts[tenor] = math.exp(-decimal_yield * years)

    return _curve_block(
        country="CA",
        as_of=as_of,
        zero_yields_pct=zero,
        discount_factors=discounts,
        source_name="Bank of Canada Government of Canada zero-coupon yield curve",
        source_url=BOC_ZERO_PAGE,
        today=today,
        notes=(
            "BoC government zero-coupon curve; published yields are decimals and treated as "
            "continuously compounded. Accepted as a close-enough proxy for CORRA/OIS "
            "forward-forward paper marks."
        ),
    )


def forward_swap_proxy(
    curve: Mapping[str, Any],
    *,
    start_years: int,
    tenor_years: int,
    payment_frequency: int = 1,
) -> dict[str, Any]:
    if start_years < 0 or tenor_years <= 0:
        raise ForwardCurveError("forward swap start/tenor must be positive")
    if payment_frequency not in {1, 2, 4}:
        raise ForwardCurveError("payment_frequency must be 1, 2 or 4")
    dfs = curve.get("discount_factors") if isinstance(curve, Mapping) else None
    if not isinstance(dfs, Mapping):
        raise ForwardCurveError("curve missing discount_factors")

    def df(years: float) -> float:
        key = _tenor_key(years)
        row = dfs.get(key)
        value = row.get("discount_factor") if isinstance(row, Mapping) else None
        if value is None:
            raise ForwardCurveError(f"curve missing discount factor {key}")
        out = float(value)
        if not (0 < out <= 1.5):
            raise ForwardCurveError(f"implausible discount factor {key}={out}")
        return out

    end_years = start_years + tenor_years
    start_df = 1.0 if start_years == 0 else df(float(start_years))
    end_df = df(float(end_years))
    step = 1.0 / payment_frequency
    payments = int(round(tenor_years * payment_frequency))
    annuity = 0.0
    refs: list[str] = []
    for i in range(1, payments + 1):
        t = start_years + i * step
        annuity += step * df(t)
        refs.append(_tenor_key(t))
    if annuity <= 0:
        raise ForwardCurveError("forward swap annuity is non-positive")
    rate_pct = 100.0 * (start_df - end_df) / annuity
    return {
        "rate_pct": round(rate_pct, 8),
        "start_years": start_years,
        "tenor_years": tenor_years,
        "payment_frequency": payment_frequency,
        "as_of": curve.get("as_of"),
        "source_tenors": refs,
        "method": "(P_start - P_end) / sum(alpha_i * P_i)",
    }


def _common_forwards(curve: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for start, tenor in ((1, 1), (1, 2), (2, 1), (2, 2), (2, 3), (3, 2), (5, 5)):
        key = f"{start}y{tenor}y"
        try:
            out[key] = forward_swap_proxy(
                curve,
                start_years=start,
                tenor_years=tenor,
                payment_frequency=1,
            )
        except ForwardCurveError:
            continue
    return out


def collect_forward_curves(*, today: date, fetch_bytes: FetchBytes) -> dict[str, Any]:
    countries: dict[str, Any] = {}
    sources: dict[str, Any] = {}

    try:
        fed = fetch_bytes(FED_ZERO_CSV).decode("utf-8-sig", errors="replace")
        countries["US"] = parse_fed_zero_csv(fed, today=today)
        countries["US"]["common_forward_swaps"] = _common_forwards(countries["US"])
        sources["US"] = {"status": "ok", "url": FED_ZERO_CSV}
    except Exception as exc:
        countries["US"] = {"status": "unavailable", "error": str(exc)}
        sources["US"] = {"status": "unavailable", "url": FED_ZERO_CSV, "error": str(exc)}

    try:
        start = today - timedelta(days=60)
        qs = urllib.parse.urlencode(
            {
                "searchRange": "",
                "dFrom": start.isoformat(),
                "dTo": today.isoformat(),
                "submit": "Submit",
            }
        )
        try:
            raw = fetch_bytes(
                f"{BOC_ZERO_CSV}?{qs}",
                user_agent=BROWSER_UA,
                referer=BOC_ZERO_PAGE,
            ).decode("utf-8-sig", errors="replace")
            ca = parse_boc_zero_csv(raw, today=today)
        except Exception:
            # Same official form offers Retrieve all data. This is a bounded fallback
            # for hosts on which the date-range form path is rejected.
            all_qs = urllib.parse.urlencode({"searchRange": "all", "submit": "Submit"})
            raw = fetch_bytes(
                f"{BOC_ZERO_CSV}?{all_qs}",
                user_agent=BROWSER_UA,
                referer=BOC_ZERO_PAGE,
            ).decode("utf-8-sig", errors="replace")
            ca = parse_boc_zero_csv(raw, today=today)
        countries["CA"] = ca
        countries["CA"]["common_forward_swaps"] = _common_forwards(countries["CA"])
        sources["CA"] = {"status": "ok", "url": BOC_ZERO_PAGE}
    except Exception as exc:
        countries["CA"] = {"status": "unavailable", "error": str(exc)}
        sources["CA"] = {"status": "unavailable", "url": BOC_ZERO_PAGE, "error": str(exc)}

    try:
        discount = fetch_bytes(RBA_F17_DISCOUNT_CSV).decode("utf-8-sig", errors="replace")
        yields = fetch_bytes(RBA_F17_YIELD_CSV).decode("utf-8-sig", errors="replace")
        forwards = fetch_bytes(RBA_F17_FORWARD_CSV).decode("utf-8-sig", errors="replace")
        countries["AU"] = parse_rba_f17(
            discount,
            today=today,
            yield_text=yields,
            forward_text=forwards,
        )
        countries["AU"]["common_forward_swaps"] = _common_forwards(countries["AU"])
        sources["AU"] = {
            "status": "ok",
            "discount_url": RBA_F17_DISCOUNT_CSV,
            "yield_url": RBA_F17_YIELD_CSV,
            "forward_url": RBA_F17_FORWARD_CSV,
        }
    except Exception as exc:
        countries["AU"] = {"status": "unavailable", "error": str(exc)}
        sources["AU"] = {
            "status": "unavailable",
            "discount_url": RBA_F17_DISCOUNT_CSV,
            "error": str(exc),
        }

    statuses = [countries[c].get("status") for c in ("US", "CA", "AU")]
    if all(status in {"ok", "stale"} for status in statuses):
        status = "ok"
    elif any(status in {"ok", "stale"} for status in statuses):
        status = "partial"
    else:
        status = "unavailable"
    return {
        "status": status,
        "countries": countries,
        "sources": sources,
        "method": {
            "model_calls": 0,
            "credentials_required": [],
            "paper_mid_proxy": True,
            "note": (
                "Official government zero/forward curves are accepted as close-enough "
                "proxies for swap/OIS forward-forward marks in the paper competition. "
                "They are research/reference marks, not executable swap/OIS quotes."
            ),
        },
    }


def validate_forward_curves(payload: Mapping[str, Any]) -> None:
    if payload.get("method", {}).get("model_calls") != 0:
        raise ForwardCurveError("forward curve collector must make zero model calls")
    countries = payload.get("countries")
    if not isinstance(countries, Mapping) or set(countries) != {"US", "CA", "AU"}:
        raise ForwardCurveError("forward curves must contain US, CA and AU country blocks")
    for country, block in countries.items():
        if block.get("status") == "unavailable":
            if not block.get("error"):
                raise ForwardCurveError(f"{country} unavailable curve missing error provenance")
            continue
        if block.get("curve_type") != "government_zero_curve_proxy":
            raise ForwardCurveError(f"{country} forward-curve type invalid")
        dfs = block.get("discount_factors")
        if not isinstance(dfs, Mapping):
            raise ForwardCurveError(f"{country} curve missing discount_factors")
        for tenor in ("2Y", "3Y", "4Y"):
            row = dfs.get(tenor)
            if not isinstance(row, Mapping) or row.get("discount_factor") is None:
                raise ForwardCurveError(f"{country} curve missing {tenor} discount factor")
        fwd = forward_swap_proxy(block, start_years=2, tenor_years=2)
        if not (0 < float(fwd["rate_pct"]) < 25):
            raise ForwardCurveError(f"{country} 2y2y proxy implausible: {fwd}")
