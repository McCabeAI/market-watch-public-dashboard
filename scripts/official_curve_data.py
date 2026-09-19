"""Official zero/forward government curves for paper rates expressions.

Purpose: provide deterministic research/reference curve mids for the paper books.
These are official government-curve proxies, not executable OIS/swap quotes.

Sources:
- US: Federal Reserve staff nominal Treasury Svensson curve.
- Canada: Bank of Canada Government of Canada zero-coupon curve download.
- Australia: RBA F17 zero-coupon discount factors / forwards / yields.

No model calls. No credentials.
"""

from __future__ import annotations

import csv
import io
import math
import urllib.parse
import zipfile
from datetime import date, datetime, timedelta
from typing import Any, Callable, Mapping

FetchBytes = Callable[..., bytes]

FED_NOMINAL_CURVE_URL = "https://www.federalreserve.gov/data/yield-curve-tables/feds200628.csv"
FED_NOMINAL_CURVE_PAGE = "https://www.federalreserve.gov/data/nominal-yield-curve.htm"

BOC_ZERO_CURVE_PAGE = "https://www.bankofcanada.ca/rates/interest-rates/bond-yield-curves/"
BOC_ZERO_CURVE_ENDPOINT = "https://www.bankofcanada.ca/stats/results/csv"


def boc_zero_curve_url(today: date) -> str:
    # The official page publishes with roughly a two-week lag. A 60-day window
    # is ample while avoiding the multi-decade "all data" download.
    d_from = today - timedelta(days=60)
    return BOC_ZERO_CURVE_ENDPOINT + "?" + urllib.parse.urlencode(
        {
            "lookupPage": "lookup_yield_curve.php",
            "startRange": "1986-01-01",
            "searchRange": "",
            "dFrom": d_from.isoformat(),
            "dTo": today.isoformat(),
        }
    )

RBA_F17_PAGE = "https://www.rba.gov.au/statistics/tables/"
RBA_F17_DISCOUNT_URL = "https://www.rba.gov.au/statistics/tables/csv/f17-discount-factors.csv"
RBA_F17_FORWARD_URL = "https://www.rba.gov.au/statistics/tables/csv/f17-forward-rates.csv"
RBA_F17_YIELDS_URL = "https://www.rba.gov.au/statistics/tables/csv/f17-yields.csv"


def _num(value: Any) -> float | None:
    if value is None:
        return None
    s = str(value).strip().replace(",", "")
    if not s or s.lower() in {"na", "n/a", "..", "-", "—"}:
        return None
    try:
        out = float(s)
    except ValueError:
        return None
    return out if math.isfinite(out) else None


def _date(value: Any) -> date | None:
    s = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _maturity_label(years: float) -> str:
    rounded = round(float(years), 8)
    if abs(rounded - round(rounded)) < 1e-8:
        return f"{int(round(rounded))}Y"
    text = f"{rounded:.8f}".rstrip("0").rstrip(".")
    return f"{text}Y"


def _curve_row(value: float, *, as_of: str, maturity_years: float, source: str) -> dict[str, Any]:
    return {
        "value": round(float(value), 10),
        "as_of": as_of,
        "maturity_years": round(float(maturity_years), 8),
        "source": source,
    }


def parse_fed_nominal_curve_csv(text: str) -> dict[str, Any]:
    """Latest Fed Svensson nominal curve.

    SVENYxx is continuously-compounded zero yield in percent.
    SVENFxx is continuously-compounded instantaneous forward in percent.
    """
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    header_i = next((i for i, row in enumerate(rows) if row and row[0].strip() == "Date"), None)
    if header_i is None:
        raise ValueError("Fed nominal curve CSV missing Date header")
    header = [cell.strip() for cell in rows[header_i]]
    data_rows: list[tuple[date, list[str]]] = []
    for row in rows[header_i + 1 :]:
        if not row:
            continue
        d = _date(row[0])
        if d is not None:
            data_rows.append((d, row))
    if not data_rows:
        raise ValueError("Fed nominal curve CSV contains no dated observations")
    d, latest = max(data_rows, key=lambda item: item[0])
    lookup = {name: latest[i] if i < len(latest) else "" for i, name in enumerate(header)}

    zero: dict[str, Any] = {}
    discount: dict[str, Any] = {}
    forward: dict[str, Any] = {}
    for years in range(1, 31):
        z = _num(lookup.get(f"SVENY{years:02d}"))
        if z is not None:
            label = _maturity_label(years)
            zero[label] = _curve_row(z, as_of=d.isoformat(), maturity_years=years, source="FED_SVENSSON_ZERO")
            df = math.exp(-(z / 100.0) * years)
            discount[label] = _curve_row(df, as_of=d.isoformat(), maturity_years=years, source="FED_SVENSSON_DERIVED_DF")
        fwd = _num(lookup.get(f"SVENF{years:02d}"))
        if fwd is not None:
            label = _maturity_label(years)
            forward[label] = _curve_row(fwd, as_of=d.isoformat(), maturity_years=years, source="FED_SVENSSON_INSTANT_FWD")
    if not all(k in discount for k in ("2Y", "3Y", "4Y")):
        raise ValueError("Fed nominal curve lacks 2Y/3Y/4Y zero points")
    return {
        "status": "ok",
        "as_of": d.isoformat(),
        "curve_type": "government_zero_curve_proxy",
        "zero_yields": zero,
        "discount_factors": discount,
        "forward_rates": forward,
        "compounding": "Fed zero yields are continuously compounded; discount factors use exp(-z*t)",
        "source_url": FED_NOMINAL_CURVE_URL,
        "source_page": FED_NOMINAL_CURVE_PAGE,
    }


def _unpack_boc_curve_bytes(data: bytes) -> str:
    if not data:
        raise ValueError("BoC zero curve response empty")
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not names:
                raise ValueError("BoC zero curve ZIP contained no CSV")
            return zf.read(names[0]).decode("utf-8-sig", errors="replace")
    text = data.decode("utf-8-sig", errors="replace")
    if "<html" in text[:1000].lower():
        raise ValueError("BoC zero curve endpoint returned HTML instead of curve data")
    return text


def parse_boc_zero_curve_bytes(data: bytes) -> dict[str, Any]:
    """Parse the BoC 0.25Y..30Y zero-coupon curve download.

    The published values are decimals (0.0500 = 5%). The parser is deliberately
    header-agnostic because the historical download has changed formatting.
    """
    text = _unpack_boc_curve_bytes(data)
    rows = list(csv.reader(io.StringIO(text)))
    candidates: list[tuple[date, list[float | None]]] = []
    for row in rows:
        if not row:
            continue
        d = _date(row[0])
        if d is None:
            continue
        vals = [_num(cell) for cell in row[1:]]
        if len(vals) < 100:
            continue
        candidates.append((d, vals[:120]))
    if not candidates:
        raise ValueError("BoC zero curve download contains no 120-point dated curves")
    d, vals = max(candidates, key=lambda item: item[0])
    zero: dict[str, Any] = {}
    discount: dict[str, Any] = {}
    for idx, raw in enumerate(vals, start=1):
        if raw is None:
            continue
        years = idx * 0.25
        # BoC page states decimals, e.g. 0.0500 = 5%. Keep packet yield units in percent.
        y_decimal = float(raw)
        y_percent = y_decimal * 100.0
        label = _maturity_label(years)
        zero[label] = _curve_row(y_percent, as_of=d.isoformat(), maturity_years=years, source="BOC_ZERO_CURVE")
        # Government of Canada bond convention is semi-annual. This is a paper
        # proxy discount factor, explicitly not an OIS discount curve.
        df = (1.0 + y_decimal / 2.0) ** (-2.0 * years)
        discount[label] = _curve_row(df, as_of=d.isoformat(), maturity_years=years, source="BOC_ZERO_DERIVED_DF")
    if not all(k in discount for k in ("2Y", "3Y", "4Y")):
        raise ValueError("BoC zero curve lacks 2Y/3Y/4Y points")
    return {
        "status": "ok",
        "as_of": d.isoformat(),
        "curve_type": "government_zero_curve_proxy",
        "zero_yields": zero,
        "discount_factors": discount,
        "forward_rates": {},
        "compounding": "BoC published zero yields converted to semi-annual government-bond proxy discount factors",
        "source_url": BOC_ZERO_CURVE_PAGE,
        "source_page": BOC_ZERO_CURVE_PAGE,
    }


def _parse_rba_f17_csv(text: str, *, kind: str) -> dict[str, Any]:
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    title_i = next((i for i, row in enumerate(rows) if row and row[0].strip() == "Title"), None)
    if title_i is None:
        raise ValueError(f"RBA F17 {kind} missing Title row")
    titles = rows[title_i]
    maturities: list[float | None] = [None]
    for title in titles[1:]:
        m = None
        import re
        hit = re.search(r"[-–]\s*([0-9]+(?:\.[0-9]+)?)\s*yrs?\b", title, re.I)
        if hit:
            m = float(hit.group(1))
        maturities.append(m)
    dated: list[tuple[date, list[str]]] = []
    for row in rows[title_i + 1 :]:
        if not row:
            continue
        d = _date(row[0])
        if d is not None:
            dated.append((d, row))
    if not dated:
        raise ValueError(f"RBA F17 {kind} contains no dated rows")
    d, latest = max(dated, key=lambda item: item[0])
    out: dict[str, Any] = {}
    for i in range(1, min(len(latest), len(maturities))):
        years = maturities[i]
        value = _num(latest[i])
        if years is None or value is None:
            continue
        label = _maturity_label(years)
        out[label] = _curve_row(
            value,
            as_of=d.isoformat(),
            maturity_years=years,
            source=f"RBA_F17_{kind.upper()}",
        )
    return {"as_of": d.isoformat(), "values": out}


def parse_rba_f17(
    discount_text: str,
    forward_text: str,
    yields_text: str,
) -> dict[str, Any]:
    discount = _parse_rba_f17_csv(discount_text, kind="discount")
    forward = _parse_rba_f17_csv(forward_text, kind="forward")
    yields = _parse_rba_f17_csv(yields_text, kind="yield")
    dates = {discount["as_of"], forward["as_of"], yields["as_of"]}
    if len(dates) != 1:
        raise ValueError(f"RBA F17 components have mixed latest dates: {sorted(dates)}")
    d = discount["as_of"]
    if not all(k in discount["values"] for k in ("2Y", "3Y", "4Y")):
        raise ValueError("RBA F17 discount curve lacks 2Y/3Y/4Y points")
    return {
        "status": "ok",
        "as_of": d,
        "curve_type": "government_zero_curve_proxy",
        "zero_yields": yields["values"],
        "discount_factors": discount["values"],
        "forward_rates": forward["values"],
        "compounding": "RBA F17 published analytical discount factors/zero yields/forward rates",
        "source_url": RBA_F17_DISCOUNT_URL,
        "source_page": RBA_F17_PAGE,
        "component_urls": {
            "discount_factors": RBA_F17_DISCOUNT_URL,
            "forward_rates": RBA_F17_FORWARD_URL,
            "zero_yields": RBA_F17_YIELDS_URL,
        },
    }


def collect_official_curves(*, today: date, fetch_bytes: FetchBytes) -> dict[str, Any]:
    countries: dict[str, Any] = {}
    errors: dict[str, str] = {}

    try:
        fed = fetch_bytes(FED_NOMINAL_CURVE_URL).decode("utf-8-sig", errors="replace")
        countries["US"] = parse_fed_nominal_curve_csv(fed)
    except Exception as exc:
        countries["US"] = {"status": "unavailable", "error": str(exc)}
        errors["US"] = str(exc)

    try:
        # Current BoC page exposes the generic CSV endpoint as a GET form. The
        # legacy lookupPage/startRange parameters remain in the URL because the
        # endpoint historically requires dataset context; Referer identifies the
        # authoritative page if the endpoint ignores the legacy fields.
        boc_url = boc_zero_curve_url(today)
        boc = fetch_bytes(
            boc_url,
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            ),
            referer=BOC_ZERO_CURVE_PAGE,
        )
        countries["CA"] = parse_boc_zero_curve_bytes(boc)
        countries["CA"]["source_url"] = boc_url
    except Exception as exc:
        countries["CA"] = {"status": "unavailable", "error": str(exc)}
        errors["CA"] = str(exc)

    try:
        d = fetch_bytes(RBA_F17_DISCOUNT_URL).decode("utf-8-sig", errors="replace")
        f = fetch_bytes(RBA_F17_FORWARD_URL).decode("utf-8-sig", errors="replace")
        y = fetch_bytes(RBA_F17_YIELDS_URL).decode("utf-8-sig", errors="replace")
        countries["AU"] = parse_rba_f17(d, f, y)
    except Exception as exc:
        countries["AU"] = {"status": "unavailable", "error": str(exc)}
        errors["AU"] = str(exc)

    status = "ok" if all((countries.get(c) or {}).get("status") == "ok" for c in ("US", "CA", "AU")) else "partial"
    return {
        "status": status,
        "countries": countries,
        "errors": errors,
        "method": {
            "model_calls": 0,
            "credentials_required": [],
            "purpose": "official government zero/forward curve proxy for deterministic paper fwd-fwd and curve marks",
            "ois_equivalence": "proxy_only",
            "note": (
                "For the paper competition, official government zero/forward curves are accepted as a close-enough "
                "proxy for swap/OIS curve expressions. They are research/reference mids, not executable quotes."
            ),
        },
    }


def validate_official_curves(payload: Mapping[str, Any]) -> None:
    if payload.get("method", {}).get("model_calls") != 0:
        raise ValueError("official curve collector must use zero model calls")
    if payload.get("status") == "unavailable":
        return
    countries = payload.get("countries")
    if not isinstance(countries, Mapping) or set(countries) != {"US", "CA", "AU"}:
        raise ValueError("official curves must contain exactly US, CA and AU")
    for country in ("US", "CA", "AU"):
        block = countries[country]
        if block.get("status") != "ok":
            raise ValueError(f"{country} official curve unavailable: {block.get('error')}")
        dfs = block.get("discount_factors")
        if not isinstance(dfs, Mapping):
            raise ValueError(f"{country} official curve missing discount_factors")
        for tenor in ("2Y", "3Y", "4Y"):
            row = dfs.get(tenor)
            if not isinstance(row, Mapping):
                raise ValueError(f"{country} official curve missing {tenor} discount factor")
            value = _num(row.get("value"))
            if value is None or not (0.0 < value < 1.5):
                raise ValueError(f"{country} {tenor} discount factor implausible: {value}")
            if not row.get("as_of"):
                raise ValueError(f"{country} {tenor} discount factor missing as_of")
