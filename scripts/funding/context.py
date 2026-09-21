"""Compact deterministic funding_context projection from Market State."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from scripts.funding.sofr import (
    FUNDING_CONVENTION,
    FUNDING_DAY_COUNT,
    FUNDING_SOURCE,
    FUNDING_SOURCE_URL,
    extract_sofr_history,
    latest_official_sofr,
)

_NY = ZoneInfo("America/New_York")


def _as_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not hasattr(value, "hour"):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        if "T" in text:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(_NY).date()
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))


def _sr3_contracts(market_state: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(market_state, dict):
        return []
    tradable = market_state.get("tradable_rate_curves") or {}
    curves = tradable.get("curves") if isinstance(tradable, dict) else {}
    sofr = (curves or {}).get("SOFR") if isinstance(curves, dict) else {}
    rows = (sofr or {}).get("contracts") if isinstance(sofr, dict) else None
    if not isinstance(rows, list) or not rows:
        policy = market_state.get("policy_paths") or {}
        us = ((policy.get("countries") or {}) if isinstance(policy, dict) else {}).get("US") or {}
        rows = us.get("contracts_3m") if isinstance(us, dict) else None
    out: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        expiry = row.get("expiry")
        implied = row.get("implied_rate")
        if expiry in (None, "") or implied in (None, ""):
            continue
        out.append(
            {
                "expiry": str(expiry),
                "code": row.get("code"),
                "implied_rate": implied,
                "price": row.get("price"),
                "change_from_overnight_bps": row.get("change_from_overnight_bps"),
            }
        )
    out.sort(key=lambda item: item["expiry"])
    return out


def _horizon_summary(contracts: list[dict[str, Any]], *, as_of: date, months: int) -> dict[str, Any] | None:
    """Use an exact SR3 expiry-month match only. No interpolation."""
    target = _add_months(as_of, months).strftime("%Y-%m")
    for row in contracts:
        if str(row.get("expiry")) == target:
            return {
                "horizon_months": months,
                "expiry": row["expiry"],
                "code": row.get("code"),
                "implied_rate": row.get("implied_rate"),
                "method": "exact_sr3_expiry_month",
            }
    return None


def build_funding_context(*payloads: Any, as_of: str | None = None) -> dict[str, Any]:
    """Deterministic spot/forward SOFR context for trader and PM packets."""
    market: dict[str, Any] = {}
    for payload in payloads:
        if isinstance(payload, dict):
            if "policy_paths" in payload or "tradable_rate_curves" in payload or "funding_context" in payload:
                market = payload
                break
            families = payload.get("families")
            if isinstance(families, dict):
                block = families.get("market_state") or {}
                data = block.get("data") if isinstance(block, dict) else None
                if isinstance(data, dict):
                    market = data
                    break
    history = extract_sofr_history(*[p for p in payloads if p is not None], market)
    latest = latest_official_sofr({"sofr_history": history, "source": FUNDING_SOURCE})
    observation = None
    if latest is not None:
        observation = _as_date(latest.get("effective_date"))
    if observation is None:
        observation = _as_date(as_of or market.get("generated_at") or market.get("as_of"))
    contracts = _sr3_contracts(market)
    summaries = {"1m": None, "3m": None, "6m": None, "12m": None}
    if observation is not None:
        summaries = {
            "1m": _horizon_summary(contracts, as_of=observation, months=1),
            "3m": _horizon_summary(contracts, as_of=observation, months=3),
            "6m": _horizon_summary(contracts, as_of=observation, months=6),
            "12m": _horizon_summary(contracts, as_of=observation, months=12),
        }
    status = "ok" if latest is not None else "missing"
    return {
        "status": status,
        "authority": "Official NY Fed SOFR is the realized funding-rate authority. SR3 is forward context only.",
        "sofr": None
        if latest is None
        else {
            "name": "SOFR",
            "rate": latest["percent_rate"],
            "percent_rate": latest["percent_rate"],
            "observation_date": latest["effective_date"],
            "effective_date": latest["effective_date"],
            "source": FUNDING_SOURCE,
            "source_url": FUNDING_SOURCE_URL,
            "day_count": FUNDING_DAY_COUNT,
            "convention": FUNDING_CONVENTION,
            "history": history,
        },
        "sr3": {
            "instrument": "CME Three-Month SOFR futures",
            "product_code": "SR3",
            "contracts": contracts,
        },
        "forward_summaries": summaries,
        "notes": [
            "Forward summaries are exact SR3 expiry-month matches only; unsupported horizons stay null.",
            "Realized accounting never uses SR3 or a model funding forecast.",
        ],
    }


def competition_contract(funding_context: dict[str, Any] | None = None) -> dict[str, Any]:
    latest = None
    if isinstance(funding_context, dict):
        latest = funding_context.get("sofr")
    rate = None if not isinstance(latest, dict) else latest.get("rate")
    observed = None if rate is None else round(float(rate) / 100.0, 8)
    return {
        "objective": "Finish with the highest cumulative net paper P&L across the 14 standing seats.",
        "metric": "net_pnl_after_funding",
        "funding_rate_annual": observed,
        "funding_day_count": FUNDING_DAY_COUNT,
        "funding_convention": FUNDING_CONVENTION,
        "funding_source": FUNDING_SOURCE,
        "funding_source_url": FUNDING_SOURCE_URL,
        "funding_observation_date": None if not isinstance(latest, dict) else latest.get("observation_date"),
        "funding_basis": (
            "Official NY Fed SOFR ACT/360 is the zero-return competition benchmark, not free alpha. "
            "Every seat has $100m paper NAV that may be described as earning SOFR, but that capital "
            "is equally funded/benchmarked at SOFR so those flows cancel. Deployed shocked-risk "
            "capital pays the same official SOFR on trusted standard-shock risk capital: the absolute "
            "MTM loss from a 1% adverse spot move, a 100bp (1 percentage point) adverse outright "
            "rate move, or a 100bp adverse curve/RV spread move under the trusted duration-1 P&L "
            "convention. Equal risk capital receives equal financing treatment across asset classes. "
            "Notional is descriptive, not the funding base. A completely flat book — including "
            "no-trade-skeptic — therefore has zero net financing/competition P&L from SOFR cash or "
            "funding economics. Positive financing/carry alpha requires an explicit markable "
            "strategy that earns above SOFR or funds below SOFR. Weekends and holidays carry the "
            "last applicable published fixing until the next fixing. If official fixing history "
            "cannot be established, new funding accrual fails closed and prior canonical balances "
            "are preserved."
        ),
        "flat_book_pnl": (
            "A flat seat has zero net financing/competition P&L: paper NAV earning SOFR is "
            "benchmarked at SOFR, so those flows cancel, and shocked-risk financing is zero."
        ),
        "risk_limits": {
            "paper_nav_usd": 100_000_000,
            "risk_capital_limit_usd": 10_000_000,
            "max_drawdown_usd": 5_000_000,
            "risk_capital_method": "mtm_standard_1pct_move",
        },
        "no_trade_allowed": True,
        "instruction": (
            "Do not optimize for gross notional or fill available capacity. Size risk from plausible "
            "adverse paths and historical excursions while staying inside the trusted risk-capital "
            "and drawdown limits. Flat cash at SOFR is the zero benchmark, not a source of alpha. "
            "The no-trade-skeptic must include a structured funding_view on every new risk or "
            "NO_TRADE thesis: the frozen official SOFR fixing, the relevant SR3 forward-curve view, "
            "its own assessment of whether realized funding will print higher, lower, or about the "
            "same as the curve, and the implication for remaining at the zero SOFR benchmark versus "
            "paying SOFR on shocked-risk capital."
        ),
    }
