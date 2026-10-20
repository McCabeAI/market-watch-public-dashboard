"""Maturity-specific NYMEX oil curve collection (not continuous BZ=F / CL=F)."""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from scripts.prima_pressure.contract import (
    GALLONS_PER_BARREL,
    GASOLINE_CRACK_FORMULA,
    HEAT_CRACK_FORMULA,
    OIL_CONTRACTS,
    REFINERY_CONTRACTS,
    STABLE_USD,
    TARGET_MATURITY_MONTHS,
    YAHOO_CHART_URL,
    add_months,
    contract_symbol,
    iso_date,
    period_key,
)

Opener = Callable[..., bytes]


def _validate_yahoo_chart_meta(meta: dict[str, Any], requested_symbol: str) -> None:
    if requested_symbol.endswith("=F") or "=F" in requested_symbol:
        raise ValueError(f"continuous symbol not allowed: {requested_symbol}")
    returned = meta.get("symbol")
    if returned is not None and returned != requested_symbol:
        raise ValueError(
            f"chart meta.symbol {returned!r} does not match requested {requested_symbol!r}"
        )
    if returned is not None and (returned.endswith("=F") or "=F" in returned):
        raise ValueError(f"continuous chart symbol rejected: {returned!r}")
    instrument = meta.get("instrumentType")
    if instrument is not None and instrument != "FUTURE":
        raise ValueError(f"instrumentType {instrument!r} is not FUTURE")


def parse_yahoo_chart(
    blob: bytes, *, as_of: date, requested_symbol: str
) -> list[tuple[date, float]]:
    """Completed daily closes with UTC session dates strictly before as_of."""
    payload = json.loads(blob)
    chart = payload.get("chart") or {}
    if chart.get("error"):
        err = chart["error"]
        desc = err.get("description") or err.get("code") or str(err)
        raise ValueError(f"Yahoo chart error: {desc}")
    results = chart.get("result")
    if not results:
        raise ValueError("Yahoo chart Not Found")
    result = results[0]
    if result is None:
        raise ValueError("Yahoo chart Not Found")
    meta = result.get("meta") or {}
    _validate_yahoo_chart_meta(meta, requested_symbol)
    closes = result["indicators"]["quote"][0]["close"]
    out: list[tuple[date, float]] = []
    for ts, v in zip(result["timestamp"], closes):
        if v is None:
            continue
        d = datetime.fromtimestamp(ts, timezone.utc).date()
        if d >= as_of:
            continue
        if not math.isfinite(v) or v <= 0:
            continue
        out.append((d, float(v)))
    out.sort(key=lambda row: row[0])
    return out


def contract_history(
    root: str,
    year: int,
    month: int,
    as_of: date,
    opener: Opener,
) -> tuple[list[tuple[date, float]], str | None]:
    symbol = contract_symbol(root, year, month)
    url = YAHOO_CHART_URL.format(symbol=symbol)
    try:
        blob = opener(url)
        return parse_yahoo_chart(blob, as_of=as_of, requested_symbol=symbol), None
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"


def _stop_on_fetch_error(message: str) -> bool:
    text = message.lower()
    return any(token in text for token in ("429", "403", "timeout", "timed out"))


def select_front_month(
    as_of: date, root: str, opener: Opener
) -> tuple[tuple[int, int] | None, list[str]]:
    if as_of.day >= 18:
        y, m = add_months(as_of.year, as_of.month, 1)
    else:
        y, m = as_of.year, as_of.month
    errors: list[str] = []
    for _ in range(8):
        history, err = contract_history(root, y, m, as_of, opener)
        if err:
            errors.append(err)
            if _stop_on_fetch_error(err):
                break
        elif history:
            last_date, _ = history[-1]
            if last_date < as_of and (as_of - last_date).days <= 10:
                return (y, m), errors
        y, m = add_months(y, m, 1)
    return None, errors


def _latest_on_or_before(history: list[tuple[date, float]], cutoff: date) -> tuple[date, float] | None:
    chosen: tuple[date, float] | None = None
    for d, p in history:
        if d <= cutoff:
            chosen = (d, p)
    return chosen


def _change_block(
    history: list[tuple[date, float]],
    last_date: date,
    last_price: float,
    *,
    mode: str,
) -> dict[str, Any] | None:
    prior: tuple[date, float] | None = None
    if mode == "1d":
        for d, p in reversed(history):
            if d < last_date:
                prior = (d, p)
                break
    elif mode == "1w":
        prior = _latest_on_or_before(history, last_date - timedelta(days=7))
    elif mode == "1m":
        prior = _latest_on_or_before(history, last_date - timedelta(days=30))
    else:
        return None
    if prior is None:
        return None
    prior_date, prior_price = prior
    abs_chg = last_price - prior_price
    return {
        "abs": abs_chg,
        "pct": abs_chg / prior_price if prior_price else None,
        "prior_date": iso_date(prior_date),
    }


def _build_point(
    *,
    maturity_months: int,
    year: int,
    month: int,
    root: str,
    as_of: date,
    opener: Opener,
    unit: str,
) -> dict[str, Any] | None:
    symbol = contract_symbol(root, year, month)
    history, err = contract_history(root, year, month, as_of, opener)
    if err or not history:
        return None
    obs_date, price = history[-1]
    age_days = (as_of - obs_date).days
    url = YAHOO_CHART_URL.format(symbol=symbol)
    return {
        "maturity_months": maturity_months,
        "contract_month": period_key(year, month),
        "symbol": symbol,
        "price": price,
        "unit": unit,
        "observation_date": iso_date(obs_date),
        "source_url": url,
        "source_kind": "specific_listed_contract",
        "staleness": "ok" if age_days <= 5 else "stale",
        "age_days": age_days,
        "changes": {
            "1d": _change_block(history, obs_date, price, mode="1d"),
            "1w": _change_block(history, obs_date, price, mode="1w"),
            "1m": _change_block(history, obs_date, price, mode="1m"),
        },
    }


def build_curve(curve_id: str, as_of: date, opener: Opener) -> dict[str, Any]:
    meta = OIL_CONTRACTS.get(curve_id)
    if meta is None:
        return {
            "curve_id": curve_id,
            "as_of": iso_date(as_of),
            "status": "unavailable",
            "continuous_front_not_used": True,
            "error": f"unknown curve id: {curve_id}",
        }
    root = meta["yahoo_root"]
    unit = meta["unit"]
    front, fetch_errors = select_front_month(as_of, root, opener)
    base: dict[str, Any] = {
        "curve_id": curve_id,
        "as_of": iso_date(as_of),
        "instrument": meta["instrument"],
        "exchange": meta.get("exchange"),
        "unit": unit,
        "role": meta.get("role"),
        "note": meta.get("note"),
        "continuous_front_not_used": True,
        "points": [],
        "missing_maturities": [],
    }
    if front is None:
        if fetch_errors:
            unique = list(dict.fromkeys(fetch_errors))
            error = "; ".join(unique[:3])
        else:
            error = "no listed front contract with a completed bar within 10 days before as_of"
        base.update(
            status="unavailable",
            error=error,
            missing_maturities=list(TARGET_MATURITY_MONTHS),
            slopes_usd={"12m_minus_front": None, "24m_minus_front": None},
            forward_path_summary={"shape": "unavailable"},
        )
        return base

    fy, fm = front
    base["front_contract_month"] = period_key(fy, fm)
    points: list[dict[str, Any]] = []
    missing: list[int] = []
    for maturity in TARGET_MATURITY_MONTHS:
        cy, cm = add_months(fy, fm, maturity)
        point = _build_point(
            maturity_months=maturity,
            year=cy,
            month=cm,
            root=root,
            as_of=as_of,
            opener=opener,
            unit=unit,
        )
        if point is None:
            missing.append(maturity)
        else:
            points.append(point)

    base["points"] = points
    base["missing_maturities"] = missing

    by_mat = {p["maturity_months"]: p for p in points}
    front_pt = by_mat.get(0)
    p12 = by_mat.get(12)
    p24 = by_mat.get(24)
    slopes = {
        "12m_minus_front": None,
        "24m_minus_front": None,
    }
    if front_pt and p12:
        slopes["12m_minus_front"] = p12["price"] - front_pt["price"]
    if front_pt and p24:
        slopes["24m_minus_front"] = p24["price"] - front_pt["price"]
    base["slopes_usd"] = slopes

    shape = "unavailable"
    if front_pt and p12:
        diff = p12["price"] - front_pt["price"]
        if diff <= -STABLE_USD:
            shape = "backwardation"
        elif diff >= STABLE_USD:
            shape = "contango"
        else:
            shape = "flat"
    base["forward_path_summary"] = {"shape": shape}

    if len(points) == len(TARGET_MATURITY_MONTHS):
        base["status"] = "ok"
    elif points:
        base["status"] = "partial"
    else:
        base["status"] = "unavailable"
        base["error"] = "no maturity points available for listed contracts"
    return base


def _product_price(
    root: str,
    year: int,
    month: int,
    as_of: date,
    opener: Opener,
) -> dict[str, Any] | None:
    symbol = contract_symbol(root, year, month)
    history, err = contract_history(root, year, month, as_of, opener)
    if err or not history:
        return None
    obs_date, price = history[-1]
    return {
        "symbol": symbol,
        "price": price,
        "observation_date": iso_date(obs_date),
        "source_url": YAHOO_CHART_URL.format(symbol=symbol),
    }


def build_refinery_margin(as_of: date, wti_curve: dict[str, Any], opener: Opener) -> dict[str, Any]:
    out: dict[str, Any] = {
        "as_of": iso_date(as_of),
        "status": "unavailable",
        "note": (
            "Same-month listed-contract crack spread using NYMEX RB and HO versus the WTI "
            "front listed contract. Not a proprietary refinery margin index."
        ),
        "gasoline_crack_formula": GASOLINE_CRACK_FORMULA,
        "heating_oil_crack_formula": HEAT_CRACK_FORMULA,
        "gallons_per_barrel": GALLONS_PER_BARREL,
    }
    wti_front = next(
        (p for p in wti_curve.get("points") or [] if p.get("maturity_months") == 0),
        None,
    )
    if wti_front is None:
        out["reason"] = "wti_front_listed_contract_unavailable"
        return out

    contract_month = wti_front["contract_month"]
    year = int(contract_month[:4])
    month = int(contract_month[5:7])
    out["wti_front"] = {
        "contract_month": contract_month,
        "symbol": wti_front["symbol"],
        "price_usd_per_bbl": wti_front["price"],
        "observation_date": wti_front["observation_date"],
    }

    rbob = _product_price(REFINERY_CONTRACTS["rbob"]["yahoo_root"], year, month, as_of, opener)
    ho = _product_price(REFINERY_CONTRACTS["heating_oil"]["yahoo_root"], year, month, as_of, opener)

    if rbob:
        out["rbob"] = {**rbob, "unit": REFINERY_CONTRACTS["rbob"]["unit"]}
        out["gasoline_crack_usd_per_bbl"] = rbob["price"] * GALLONS_PER_BARREL - wti_front["price"]
        out["gasoline_crack_status"] = "ok"
    else:
        out["gasoline_crack_status"] = "unavailable"

    if ho:
        out["heating_oil"] = {**ho, "unit": REFINERY_CONTRACTS["heating_oil"]["unit"]}
        out["heating_oil_crack_usd_per_bbl"] = ho["price"] * GALLONS_PER_BARREL - wti_front["price"]
        out["heating_oil_crack_status"] = "ok"
    else:
        out["heating_oil_crack_status"] = "unavailable"

    if rbob and ho:
        out["status"] = "ok"
    elif rbob or ho:
        out["status"] = "partial"
    else:
        out["reason"] = "rbob_and_heating_oil_unavailable"
    return out
