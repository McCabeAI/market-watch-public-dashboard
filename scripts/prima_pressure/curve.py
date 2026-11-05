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
from scripts.prima_pressure.expiry import (
    ExpiryError,
    active_front_contract,
    contract_is_active,
    final_trade_date,
    rule_for_root,
)

# Quote freshness is the age of the last completed bar strictly before as_of.
# It is not an activity test. Ten calendar days is the existing freshness gate;
# five calendar days marks a usable quote stale. Neither window revives a
# contract whose final trade date is already behind as_of.
QUOTE_FRESHNESS_MAX_AGE_DAYS = 10
QUOTE_STALE_AFTER_DAYS = 5

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


def quote_is_fresh(
    observation_date: date,
    as_of: date,
    *,
    max_age_days: int = QUOTE_FRESHNESS_MAX_AGE_DAYS,
) -> bool:
    """True when a completed bar is strictly before as_of and inside the freshness window.

    A true result does not make an expired contract active.
    """
    if observation_date >= as_of:
        return False
    return (as_of - observation_date).days <= max_age_days


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _front_failure(
    *,
    reason: str,
    error: str,
    front: dict[str, Any] | None = None,
    quote_age_days: int | None = None,
    quote_observation_date: date | None = None,
    fetch_errors: list[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": False,
        "failure_reason": reason,
        "error": error,
        "quote_age_days": quote_age_days,
        "quote_observation_date": _iso(quote_observation_date),
        "quote_fresh": False,
        "freshness_max_age_days": QUOTE_FRESHNESS_MAX_AGE_DAYS,
        "fetch_errors": list(fetch_errors or []),
    }
    if front is not None:
        payload.update(
            {
                "root": front.get("root"),
                "year": front.get("year"),
                "month": front.get("month"),
                "contract_month": front.get("contract_month"),
                "symbol": front.get("symbol"),
                "final_trade_date": _iso(front.get("final_trade_date")),
                "active_as_of": front.get("active_as_of"),
                "expiry_rule_id": front.get("expiry_rule_id"),
                "expiry_source": front.get("expiry_source"),
                "rejected_expired": list(front.get("rejected_expired") or []),
                "roll_reason": front.get("roll_reason"),
                "prior_contract": front.get("prior_contract"),
            }
        )
    return payload


def select_active_front(as_of: date, root: str, opener: Opener) -> dict[str, Any]:
    """Select the calendar-active front only if its quote is separately fresh.

    Expired contracts are never fetched and never selected. A missing or stale
    quote on the active front fails the curve; the next maturity is not used
    in its place.
    """
    try:
        front = active_front_contract(as_of, root)
    except ExpiryError as exc:
        return _front_failure(reason=exc.reason, error=str(exc))

    history, err = contract_history(root, front["year"], front["month"], as_of, opener)
    if err:
        if _stop_on_fetch_error(err):
            return _front_failure(
                reason="quote_fetch_error",
                error=err,
                front=front,
                fetch_errors=[err],
            )
        return _front_failure(
            reason="missing_active_front",
            error=err,
            front=front,
            fetch_errors=[err],
        )
    if not history:
        return _front_failure(
            reason="missing_active_front",
            error=f"no completed bar for active front {front['symbol']} before {as_of.isoformat()}",
            front=front,
        )

    obs_date, _price = history[-1]
    age_days = (as_of - obs_date).days
    if not quote_is_fresh(obs_date, as_of):
        return _front_failure(
            reason="stale_active_quote",
            error=(
                f"stale_active_quote: {front['symbol']} last bar {obs_date.isoformat()} "
                f"is {age_days} calendar days before {as_of.isoformat()}; "
                f"freshness max is {QUOTE_FRESHNESS_MAX_AGE_DAYS} calendar days; "
                f"contract remains active until {front['final_trade_date'].isoformat()}"
            ),
            front=front,
            quote_age_days=age_days,
            quote_observation_date=obs_date,
        )

    return {
        "ok": True,
        "failure_reason": None,
        "error": None,
        "root": root,
        "year": front["year"],
        "month": front["month"],
        "contract_month": front["contract_month"],
        "symbol": front["symbol"],
        "final_trade_date": front["final_trade_date"],
        "active_as_of": True,
        "expiry_rule_id": front["expiry_rule_id"],
        "expiry_source": front["expiry_source"],
        "business_day_source": front.get("business_day_source"),
        "roll_reason": front["roll_reason"],
        "prior_contract": front.get("prior_contract"),
        "rejected_expired": list(front.get("rejected_expired") or []),
        "quote_observation_date": obs_date,
        "quote_age_days": age_days,
        "quote_fresh": True,
        "freshness_max_age_days": QUOTE_FRESHNESS_MAX_AGE_DAYS,
        "history": history,
        "fetch_errors": [],
    }


def select_front_month(
    as_of: date, root: str, opener: Opener
) -> tuple[tuple[int, int] | None, list[str]]:
    """Compatibility wrapper. Selection is expiry-first; bars do not extend activity."""
    selected = select_active_front(as_of, root, opener)
    errors = list(selected.get("fetch_errors") or [])
    if not selected.get("ok"):
        if selected.get("error"):
            errors.append(str(selected["error"]))
        return None, errors
    return (int(selected["year"]), int(selected["month"])), errors


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


def _expiry_fields(root: str, year: int, month: int, as_of: date) -> dict[str, Any]:
    last = final_trade_date(root, year, month)
    rule = rule_for_root(root)
    return {
        "final_trade_date": iso_date(last),
        "active_as_of": as_of <= last,
        "expiry_rule_id": rule["expiry_rule_id"],
        "expiry_source": rule["expiry_source"],
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
    history: list[tuple[date, float]] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """One listed maturity. Expired, missing, and stale contracts are not filled."""
    symbol = contract_symbol(root, year, month)
    try:
        expiry = _expiry_fields(root, year, month, as_of)
    except ExpiryError as exc:
        return None, exc.reason
    if not expiry["active_as_of"]:
        return None, "expired_contract"
    if not contract_is_active(root, year, month, as_of):
        return None, "expired_contract"
    err = None
    if history is None:
        history, err = contract_history(root, year, month, as_of, opener)
    if err or not history:
        return None, "missing_maturity_contract" if maturity_months else "missing_active_front"
    obs_date, price = history[-1]
    age_days = (as_of - obs_date).days
    fresh = quote_is_fresh(obs_date, as_of)
    if not fresh:
        return None, "stale_active_quote"
    url = YAHOO_CHART_URL.format(symbol=symbol)
    point = {
        "maturity_months": maturity_months,
        "contract_month": period_key(year, month),
        "symbol": symbol,
        "price": price,
        "unit": unit,
        "observation_date": iso_date(obs_date),
        "source_url": url,
        "source_kind": "specific_listed_contract",
        "staleness": "ok" if age_days <= QUOTE_STALE_AFTER_DAYS else "stale",
        "age_days": age_days,
        "quote_fresh": True,
        "freshness_max_age_days": QUOTE_FRESHNESS_MAX_AGE_DAYS,
        "changes": {
            "1d": _change_block(history, obs_date, price, mode="1d"),
            "1w": _change_block(history, obs_date, price, mode="1w"),
            "1m": _change_block(history, obs_date, price, mode="1m"),
        },
        **expiry,
    }
    return point, None


def _public_selection(selected: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe front selection record. Quote history is not repeated here."""
    prior = selected.get("prior_contract")
    final = selected.get("final_trade_date")
    obs = selected.get("quote_observation_date")
    if isinstance(final, date):
        final = final.isoformat()
    if isinstance(obs, date):
        obs = obs.isoformat()
    return {
        "ok": bool(selected.get("ok")),
        "failure_reason": selected.get("failure_reason"),
        "contract_month": selected.get("contract_month"),
        "symbol": selected.get("symbol"),
        "final_trade_date": final,
        "active_as_of": selected.get("active_as_of"),
        "expiry_rule_id": selected.get("expiry_rule_id"),
        "expiry_source": selected.get("expiry_source"),
        "roll_reason": selected.get("roll_reason"),
        "prior_contract": prior,
        "rejected_expired": list(selected.get("rejected_expired") or []),
        "quote_observation_date": obs,
        "quote_age_days": selected.get("quote_age_days"),
        "quote_fresh": selected.get("quote_fresh"),
        "freshness_max_age_days": selected.get("freshness_max_age_days", QUOTE_FRESHNESS_MAX_AGE_DAYS),
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
    selected = select_active_front(as_of, root, opener)
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
        "quote_freshness_max_age_days": QUOTE_FRESHNESS_MAX_AGE_DAYS,
    }
    if not selected.get("ok"):
        error = selected.get("error") or selected.get("failure_reason") or "active front unavailable"
        base.update(
            status="unavailable",
            error=error,
            selection_failure=selected.get("failure_reason"),
            front_selection=_public_selection(selected),
            missing_maturities=list(TARGET_MATURITY_MONTHS),
            slopes_usd={"12m_minus_front": None, "24m_minus_front": None},
            forward_path_summary={"shape": "unavailable"},
        )
        return base

    fy, fm = int(selected["year"]), int(selected["month"])
    base["front_contract_month"] = period_key(fy, fm)
    base["front_symbol"] = selected["symbol"]
    base["front_final_trade_date"] = iso_date(selected["final_trade_date"])
    base["front_active_as_of"] = True
    base["front_selection"] = _public_selection(selected)
    points: list[dict[str, Any]] = []
    missing: list[int] = []
    missing_reasons: dict[str, str] = {}
    for maturity in TARGET_MATURITY_MONTHS:
        cy, cm = add_months(fy, fm, maturity)
        reused = selected.get("history") if maturity == 0 else None
        point, reason = _build_point(
            maturity_months=maturity,
            year=cy,
            month=cm,
            root=root,
            as_of=as_of,
            opener=opener,
            unit=unit,
            history=reused,
        )
        if point is None:
            missing.append(maturity)
            missing_reasons[str(maturity)] = reason or "missing_maturity_contract"
        else:
            point["selection"] = "active_front_plus_maturity"
            point["front_contract_month"] = period_key(fy, fm)
            points.append(point)

    base["points"] = points
    base["missing_maturities"] = missing
    base["missing_maturity_reasons"] = missing_reasons

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
) -> tuple[dict[str, Any] | None, str | None]:
    """Same-month product leg. An expired contract is not priced off its last bar."""
    symbol = contract_symbol(root, year, month)
    try:
        expiry = _expiry_fields(root, year, month, as_of)
    except ExpiryError as exc:
        return None, exc.reason
    if not expiry["active_as_of"]:
        return None, "expired_contract"
    history, err = contract_history(root, year, month, as_of, opener)
    if err or not history:
        return None, "missing_active_contract"
    obs_date, price = history[-1]
    age_days = (as_of - obs_date).days
    if not quote_is_fresh(obs_date, as_of):
        return None, "stale_active_quote"
    return {
        "symbol": symbol,
        "price": price,
        "observation_date": iso_date(obs_date),
        "source_url": YAHOO_CHART_URL.format(symbol=symbol),
        "quote_fresh": True,
        "age_days": age_days,
        "staleness": "ok" if age_days <= QUOTE_STALE_AFTER_DAYS else "stale",
        **expiry,
    }, None


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
    try:
        wti_active = contract_is_active("CL", year, month, as_of)
        wti_last = final_trade_date("CL", year, month)
    except ExpiryError as exc:
        out["reason"] = exc.reason
        return out
    if not wti_active:
        out["reason"] = "expired_contract"
        out["wti_front"] = {
            "contract_month": contract_month,
            "symbol": wti_front.get("symbol"),
            "final_trade_date": iso_date(wti_last),
            "active_as_of": False,
        }
        out["gasoline_crack_status"] = "unavailable"
        out["heating_oil_crack_status"] = "unavailable"
        return out

    out["wti_front"] = {
        "contract_month": contract_month,
        "symbol": wti_front["symbol"],
        "price_usd_per_bbl": wti_front["price"],
        "observation_date": wti_front["observation_date"],
        "final_trade_date": iso_date(wti_last),
        "active_as_of": True,
    }

    rbob, rbob_reason = _product_price(
        REFINERY_CONTRACTS["rbob"]["yahoo_root"], year, month, as_of, opener
    )
    ho, ho_reason = _product_price(
        REFINERY_CONTRACTS["heating_oil"]["yahoo_root"], year, month, as_of, opener
    )

    if rbob:
        out["rbob"] = {**rbob, "unit": REFINERY_CONTRACTS["rbob"]["unit"]}
        out["gasoline_crack_usd_per_bbl"] = rbob["price"] * GALLONS_PER_BARREL - wti_front["price"]
        out["gasoline_crack_status"] = "ok"
    else:
        out["gasoline_crack_status"] = "unavailable"
        out["gasoline_crack_reason"] = rbob_reason or "missing_active_contract"

    if ho:
        out["heating_oil"] = {**ho, "unit": REFINERY_CONTRACTS["heating_oil"]["unit"]}
        out["heating_oil_crack_usd_per_bbl"] = ho["price"] * GALLONS_PER_BARREL - wti_front["price"]
        out["heating_oil_crack_status"] = "ok"
    else:
        out["heating_oil_crack_status"] = "unavailable"
        out["heating_oil_crack_reason"] = ho_reason or "missing_active_contract"

    if rbob and ho:
        out["status"] = "ok"
    elif rbob or ho:
        out["status"] = "partial"
    else:
        out["reason"] = rbob_reason or ho_reason or "rbob_and_heating_oil_unavailable"
    return out
