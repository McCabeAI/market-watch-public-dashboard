"""Persistent $100m paper books for the locked 14-seat roster."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

from scripts.funding.sofr import (
    FUNDING_CONVENTION,
    FUNDING_DAY_COUNT,
    FUNDING_SOURCE,
    FUNDING_SOURCE_URL,
    FundingHistoryError,
    accrue_act_360,
    extract_sofr_history,
    observed_rate_fields,
)
from scripts.overnight.clock import isoformat, now_ny
from scripts.overnight.constants import (
    ACTIONS,
    ASSET_CLASSES,
    EXPANDING_ACTIONS,
    SCHEMA_VERSION,
    SIDES,
    STANDING_SEATS,
    STARTING_NAV_USD,
    RISK_CAPITAL_LIMIT_USD,
    MAX_DRAWDOWN_USD,
)
from scripts.overnight.errors import FreshnessError, SchemaError
from scripts.overnight.expression import expression_rule, remit, selected_asset_class, validate_expression_memo
from scripts.overnight.freshness import assert_action_allowed
from scripts.risk_capital import attach_position_risk, book_risk_capital, position_risk_capital


def _money(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SchemaError(f"{field} must be numeric") from exc
    if not number == number:  # NaN
        raise SchemaError(f"{field} is not a number")
    return number


def _side_sign(side: str) -> int:
    if side not in SIDES:
        raise SchemaError(f"side must be long or short, got {side}")
    return 1 if side == "long" else -1


ALLOCATION_LIMIT_USD = RISK_CAPITAL_LIMIT_USD


def allocation_limit_usd() -> float:
    """Compatibility alias: the enforced allocation is shocked risk capital, not notional."""
    return RISK_CAPITAL_LIMIT_USD


def risk_capital_limit_usd() -> float:
    return RISK_CAPITAL_LIMIT_USD


def deployed_notional(seat_book: dict[str, Any]) -> float:
    return round(
        sum(float(position.get("notional_usd") or 0.0) for position in seat_book.get("positions") or []),
        2,
    )


def _attach_allocation_fields(seat_book: dict[str, Any]) -> None:
    metrics = book_risk_capital(seat_book)
    for position in seat_book.get("positions") or []:
        attach_position_risk(position)
    used = float(metrics["risk_capital_usd"])
    limit = risk_capital_limit_usd()
    seat_book.update(metrics)
    seat_book["risk_capital_limit_usd"] = limit
    seat_book["risk_capital_remaining_usd"] = round(max(0.0, limit - used), 2)
    # Legacy allocation fields now mirror the enforced risk-capital budget.
    seat_book["allocation_limit_usd"] = limit
    seat_book["allocation_used_usd"] = used
    seat_book["allocation_remaining_usd"] = seat_book["risk_capital_remaining_usd"]
    seat_book["deployed_notional_usd"] = deployed_notional(seat_book)


def projected_deployed_notional(seat_book: dict[str, Any], action: dict[str, Any]) -> float:
    current = deployed_notional(seat_book)
    kind = action.get("action")
    if kind in {"OPEN", "ADD", "HEDGE"}:
        notional = action.get("notional_usd")
        if notional in (None, ""):
            return current
        return round(current + _money(notional, "notional_usd"), 2)
    return current


def _projected_risk_capital(seat_book: dict[str, Any], action: dict[str, Any]) -> float | None:
    metrics = book_risk_capital(seat_book)
    if metrics["risk_capital_unavailable_positions"]:
        return None
    current = float(metrics["risk_capital_usd"])
    kind = action.get("action")
    if kind not in {"OPEN", "ADD", "HEDGE"}:
        return current

    if kind == "ADD":
        position = _find_position(seat_book, action.get("position_id") or "")
        prior = position_risk_capital(position)
        projected = deepcopy(position)
        projected["notional_usd"] = float(position["notional_usd"]) + _money(action.get("notional_usd"), "notional_usd")
        if action.get("price") not in (None, ""):
            projected["mark_price"] = action.get("mark_price", action.get("price"))
        new = position_risk_capital(projected)
        return None if prior is None or new is None else round(current - prior + new, 2)

    source = action
    if kind == "HEDGE":
        target_id = action.get("hedge_of") or action.get("position_id")
        target = _find_position(seat_book, target_id or "")
        source = dict(target)
        source.update({k: v for k, v in action.items() if v not in (None, "")})
        source["notional_usd"] = action.get("notional_usd")
        source.setdefault("asset_class", target.get("asset_class"))
        source.setdefault("side", target.get("side"))
    position = {
        "instrument": source.get("instrument"),
        "asset_class": source.get("asset_class") or "spot_fx",
        "side": source.get("side") or "long",
        "notional_usd": source.get("notional_usd"),
        "entry_price": source.get("price"),
        "mark_price": source.get("mark_price", source.get("price")),
    }
    added = position_risk_capital(position)
    return None if added is None else round(current + added, 2)


def assert_allocation(seat_book: dict[str, Any], *, extra_notional: float = 0) -> None:
    del extra_notional
    metrics = book_risk_capital(seat_book)
    if metrics["risk_capital_unavailable_positions"]:
        raise SchemaError("seat risk capital unavailable")
    if float(metrics["risk_capital_usd"]) - risk_capital_limit_usd() > 1e-6:
        raise SchemaError("seat shocked-risk capital cap exceeded")


def _attach_observed_rate(target: dict[str, Any], market_state: dict[str, Any] | None = None) -> None:
    fields = observed_rate_fields(market_state)
    if fields["funding_rate_annual"] is None and target.get("funding_rate_annual") == 0.05:
        fields["funding_rate_annual"] = None
        fields["funding_percent_rate"] = None
    if target.get("funding_rate_annual") == 0.05:
        target["funding_rate_annual"] = fields["funding_rate_annual"]
    elif fields["funding_rate_annual"] is not None:
        target["funding_rate_annual"] = fields["funding_rate_annual"]
    target["funding_day_count"] = FUNDING_DAY_COUNT
    target["funding_convention"] = FUNDING_CONVENTION
    target["funding_source"] = FUNDING_SOURCE
    target["funding_source_url"] = FUNDING_SOURCE_URL
    if fields["funding_percent_rate"] is not None:
        target["funding_percent_rate"] = fields["funding_percent_rate"]
        target["funding_effective_date"] = fields["funding_effective_date"]


def accrue_funding(
    seat_book: dict[str, Any],
    *,
    when: datetime,
    run_id: str | None = None,
    market_state: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Accrue official NY Fed SOFR ACT/360 on shocked risk capital.

    Every seat earns the common cash hurdle on its starting paper NAV. Risk-taking
    books additionally pay SOFR on current 1%-shock risk capital; notional itself
    is never treated as borrowed principal. The no-trade skeptic has zero risk
    capital while flat and therefore pays no financing charge.
    """
    seat_book.setdefault("funding_cost_usd", 0.0)
    seat_book.setdefault("cash_yield_usd", 0.0)
    _attach_observed_rate(seat_book, market_state)
    _attach_allocation_fields(seat_book)
    last_raw = seat_book.get("funding_last_accrual_at")
    if not last_raw:
        seat_book["funding_last_accrual_at"] = isoformat(when)
        seat_book["funding_regime"] = "sofr_risk_capital_1pct"
        return {"funding_cost_usd": 0.0, "cash_yield_usd": 0.0}
    try:
        last = datetime.fromisoformat(str(last_raw))
    except ValueError as exc:
        raise SchemaError(f"invalid funding accrual timestamp {last_raw}") from exc
    if (when - last).total_seconds() <= 0:
        return {"funding_cost_usd": 0.0, "cash_yield_usd": 0.0}

    history = extract_sofr_history(market_state or {}, seat_book.get("funding_context") or {})
    principal = 0.0 if seat_book["seat"] == "no-trade-skeptic" else float(seat_book.get("risk_capital_usd") or 0.0)
    try:
        funding_accrual = accrue_act_360(principal, start=last, end=when, history=history, market_state=market_state)
        cash_accrual = accrue_act_360(STARTING_NAV_USD, start=last, end=when, history=history, market_state=market_state)
    except FundingHistoryError as exc:
        seat_book.setdefault("alerts", []).append(f"funding_accrual_failed_closed: {exc}")
        seat_book["funding_accrual_status"] = "failed_closed"
        return {"funding_cost_usd": 0.0, "cash_yield_usd": 0.0, "failed_closed": True}

    funding_increment = funding_accrual["amount"]
    cash_yield_increment = cash_accrual["amount"]
    seat_book["funding_cost_usd"] = round(float(seat_book.get("funding_cost_usd") or 0.0) + funding_increment, 2)
    seat_book["cash_yield_usd"] = round(float(seat_book.get("cash_yield_usd") or 0.0) + cash_yield_increment, 2)
    seat_book["cash_usd"] = round(
        float(seat_book.get("cash_usd", STARTING_NAV_USD)) + cash_yield_increment - funding_increment,
        2,
    )

    seat_book["funding_last_accrual_at"] = isoformat(when)
    seat_book["funding_regime"] = "sofr_risk_capital_1pct"
    seat_book["funding_accrual_status"] = "applied"
    seat_book["funding_rate_annual"] = cash_accrual["funding_rate_annual"] or funding_accrual["funding_rate_annual"]
    seat_book["funding_percent_rate"] = cash_accrual["latest_percent_rate"] or funding_accrual["latest_percent_rate"]
    seat_book["funding_effective_date"] = cash_accrual["latest_effective_date"] or funding_accrual["latest_effective_date"]
    seat_book["funding_day_count"] = FUNDING_DAY_COUNT
    seat_book["funding_convention"] = FUNDING_CONVENTION
    seat_book["funding_source"] = FUNDING_SOURCE
    if funding_increment or cash_yield_increment:
        seat_book.setdefault("history", []).append(
            {
                "at": isoformat(when),
                "overnight_run_id": run_id,
                "action": "FUNDING",
                "result": "applied",
                "funding_rate_annual": seat_book["funding_rate_annual"],
                "funding_percent_rate": seat_book["funding_percent_rate"],
                "funding_effective_date": seat_book["funding_effective_date"],
                "funding_source": FUNDING_SOURCE,
                "funding_source_url": FUNDING_SOURCE_URL,
                "funding_day_count": FUNDING_DAY_COUNT,
                "funding_convention": FUNDING_CONVENTION,
                "accrual_days": max(funding_accrual["accrual_days"], cash_accrual["accrual_days"]),
                "funding_base_usd": principal,
                "risk_capital_usd": principal,
                "cash_yield_base_usd": STARTING_NAV_USD,
                "funding_cost_usd": funding_increment,
                "cash_yield_usd": cash_yield_increment,
            }
        )
    return {"funding_cost_usd": funding_increment, "cash_yield_usd": cash_yield_increment}

def _rate_delta_fraction(asset_class: str | None, delta: float) -> float:
    """Convert a stored rates mark change into decimal-rate units.

    Outright yields are stored in percentage points (e.g. 4.76%), so 1bp is
    a 0.01 mark change and delta/100 converts percentage points to decimal.
    Curve and rates-RV marks are stored directly in basis points, so 1bp is
    a 1.00 mark change and delta/10_000 converts basis points to decimal.
    """
    if asset_class == "rates":
        return delta / 100.0
    if asset_class in {"curve", "rates_rv"}:
        return delta / 10_000.0
    raise SchemaError(f"unsupported rates asset_class {asset_class!r}")


def position_pnl(position: dict[str, Any]) -> dict[str, Any]:
    entry = position.get("entry_price")
    mark = position.get("mark_price")
    notional = _money(position.get("notional_usd"), "notional_usd")
    if entry in (None, "") or mark in (None, ""):
        return {
            "unrealized_pnl_usd": None,
            "pnl_unavailable": True,
            "pnl_note": "mark or entry missing; P&L not invented",
        }
    entry_px = _money(entry, "entry_price")
    mark_px = _money(mark, "mark_price")
    if entry_px == 0:
        return {
            "unrealized_pnl_usd": None,
            "pnl_unavailable": True,
            "pnl_note": "entry_price is zero; P&L not invented",
        }
    sign = _side_sign(position["side"])
    asset = position.get("asset_class")
    if asset in {"rates", "curve", "rates_rv"}:
        # Simplified duration-1 paper P&L, inverted because higher yields/spreads
        # lower the value of a long-duration / long-spread position.
        raw = -sign * _rate_delta_fraction(asset, mark_px - entry_px) * notional
    else:
        raw = sign * (mark_px - entry_px) / entry_px * notional
    return {
        "unrealized_pnl_usd": round(raw, 2),
        "pnl_unavailable": False,
        "pnl_note": None,
    }


def realized_increment(position: dict[str, Any], *, exit_price: float, closed_notional: float) -> float:
    if position.get("entry_price") in (None, ""):
        raise SchemaError("cannot realize P&L without an entry_price")
    entry_px = _money(position["entry_price"], "entry_price")
    if entry_px == 0:
        raise SchemaError("cannot realize P&L with a zero entry_price")
    sign = _side_sign(position["side"])
    asset = position.get("asset_class")
    if asset in {"rates", "curve", "rates_rv"}:
        return round(-sign * _rate_delta_fraction(asset, exit_price - entry_px) * closed_notional, 2)
    return round(sign * (exit_price - entry_px) / entry_px * closed_notional, 2)


def empty_seat(seat: str) -> dict[str, Any]:
    return {
        "seat": seat,
        "remit": remit(seat),
        "expression_rule": expression_rule(seat),
        "starting_nav_usd": STARTING_NAV_USD,
        "cash_usd": STARTING_NAV_USD,
        "nav_usd": STARTING_NAV_USD,
        "positions": [],
        "history": [],
        "realized_pnl_usd": 0.0,
        "unrealized_pnl_usd": 0.0,
        "gross_pnl_usd": 0.0,
        "funding_cost_usd": 0.0,
        "cash_yield_usd": 0.0,
        "funding_rate_annual": None,
        "funding_percent_rate": None,
        "funding_effective_date": None,
        "funding_day_count": FUNDING_DAY_COUNT,
        "funding_convention": FUNDING_CONVENTION,
        "funding_source": FUNDING_SOURCE,
        "funding_regime": "sofr_risk_capital_1pct",
        "funding_last_accrual_at": None,
        "risk_capital_usd": 0.0,
        "risk_capital_limit_usd": RISK_CAPITAL_LIMIT_USD,
        "risk_capital_remaining_usd": RISK_CAPITAL_LIMIT_USD,
        "risk_capital_status": "ok",
        "risk_capital_unavailable_positions": [],
        "max_drawdown_usd": MAX_DRAWDOWN_USD,
        "high_water_nav_usd": STARTING_NAV_USD,
        "drawdown_usd": 0.0,
        "risk_stopped": False,
        "risk_stop_pending": False,
        "risk_stop_at": None,
        "net_pnl_usd": 0.0,
        "pnl_unavailable": False,
        "conviction": 0,
        "thesis": None,
        "invalidation": None,
        "alerts": [],
        "prior_action": None,
        "last_action": "HOLD",
        "required_pitch": None,
        "risk_put_on": None,
        "evidence_cutoff": None,
        "blocked_opens": [],
        "allocation_limit_usd": RISK_CAPITAL_LIMIT_USD,
        "allocation_used_usd": 0.0,
        "deployed_notional_usd": 0.0,
        "allocation_remaining_usd": RISK_CAPITAL_LIMIT_USD,
    }


def empty_books(*, overnight_run_id: str | None = None, when: datetime | None = None) -> dict[str, Any]:
    stamp = isoformat(now_ny(when))
    return {
        "schema_version": SCHEMA_VERSION,
        "starting_nav_usd": STARTING_NAV_USD,
        "as_of": stamp,
        "overnight_run_id": overnight_run_id,
        "evidence_cutoff": None,
        "review_status": "missing",
        "last_successful_review_run_id": None,
        "seats": {seat: empty_seat(seat) for seat in STANDING_SEATS},
    }


def _force_drawdown_flatten(
    seat_book: dict[str, Any],
    *,
    when: datetime | None = None,
    run_id: str | None = None,
) -> bool:
    positions = list(seat_book.get("positions") or [])
    if not positions:
        seat_book["risk_stopped"] = True
        return True
    if any(position.get("mark_price") in (None, "") for position in positions):
        seat_book["risk_stopped"] = True
        seat_book["risk_stop_pending"] = True
        reason = "max drawdown breached but one or more positions lack a deterministic exit mark; expansion is blocked pending forced flatten"
        if reason not in seat_book.setdefault("alerts", []):
            seat_book["alerts"].append(reason)
        return False

    realized = 0.0
    for position in positions:
        realized += realized_increment(
            position,
            exit_price=float(position["mark_price"]),
            closed_notional=float(position["notional_usd"]),
        )
    seat_book["realized_pnl_usd"] = round(float(seat_book.get("realized_pnl_usd") or 0.0) + realized, 2)
    seat_book["cash_usd"] = round(float(seat_book.get("cash_usd", STARTING_NAV_USD)) + realized, 2)
    seat_book["positions"] = []
    seat_book["risk_stopped"] = True
    seat_book["risk_stop_pending"] = False
    seat_book["risk_stop_at"] = isoformat(now_ny(when))
    seat_book["prior_action"] = seat_book.get("last_action")
    seat_book["last_action"] = "RISK_STOP"
    seat_book.setdefault("history", []).append(
        {
            "at": seat_book["risk_stop_at"],
            "overnight_run_id": run_id,
            "action": "RISK_STOP",
            "result": "forced_flat",
            "realized_pnl_usd": round(realized, 2),
            "drawdown_usd": seat_book.get("drawdown_usd"),
            "max_drawdown_usd": seat_book.get("max_drawdown_usd", MAX_DRAWDOWN_USD),
        }
    )
    seat_book.setdefault("alerts", []).append(
        f"RISK_STOP: book forcibly flattened after drawdown reached {float(seat_book.get('drawdown_usd') or 0.0):,.2f}"
    )
    return True


def mark_to_market(
    seat_book: dict[str, Any],
    *,
    when: datetime | None = None,
    run_id: str | None = None,
    enforce_stop: bool = True,
) -> dict[str, Any]:
    unrealized = 0.0
    missing = False
    for position in seat_book["positions"]:
        pnl = position_pnl(position)
        position["unrealized_pnl_usd"] = pnl["unrealized_pnl_usd"]
        position["pnl_unavailable"] = pnl["pnl_unavailable"]
        attach_position_risk(position)
        if pnl["pnl_unavailable"]:
            missing = True
        else:
            unrealized += float(pnl["unrealized_pnl_usd"])
    seat_book["unrealized_pnl_usd"] = round(unrealized, 2)
    seat_book["pnl_unavailable"] = missing
    gross = round(float(seat_book.get("realized_pnl_usd") or 0.0) + unrealized, 2)
    funding = round(float(seat_book.get("funding_cost_usd") or 0.0), 2)
    cash_yield = round(float(seat_book.get("cash_yield_usd") or 0.0), 2)
    seat_book["gross_pnl_usd"] = None if missing else gross
    seat_book["funding_cost_usd"] = funding
    seat_book["cash_yield_usd"] = cash_yield
    _attach_observed_rate(seat_book)
    seat_book["net_pnl_usd"] = None if missing else round(gross - funding + cash_yield, 2)
    seat_book["nav_usd"] = round(float(seat_book["starting_nav_usd"]) + gross - funding + cash_yield, 2)
    _attach_allocation_fields(seat_book)

    seat_book.setdefault("max_drawdown_usd", MAX_DRAWDOWN_USD)
    seat_book.setdefault("high_water_nav_usd", float(seat_book["starting_nav_usd"]))
    seat_book.setdefault("risk_stopped", False)
    seat_book.setdefault("risk_stop_pending", False)
    high_water = max(float(seat_book["high_water_nav_usd"]), float(seat_book["nav_usd"]))
    seat_book["high_water_nav_usd"] = round(high_water, 2)
    seat_book["drawdown_usd"] = round(max(0.0, high_water - float(seat_book["nav_usd"])), 2)

    if (
        enforce_stop
        and not missing
        and float(seat_book["drawdown_usd"]) >= float(seat_book["max_drawdown_usd"])
        and seat_book.get("positions")
    ):
        _force_drawdown_flatten(seat_book, when=when, run_id=run_id)
        return mark_to_market(seat_book, when=when, run_id=run_id, enforce_stop=False)
    return seat_book

def _find_position(seat_book: dict[str, Any], position_id: str) -> dict[str, Any]:
    for position in seat_book["positions"]:
        if position["position_id"] == position_id:
            return position
    raise SchemaError(f"unknown position_id {position_id}")


def _history_entry(action: dict[str, Any], *, when: datetime, run_id: str, result: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    row = {
        "at": isoformat(when),
        "overnight_run_id": run_id,
        "action": action["action"],
        "result": result,
        "instrument": action.get("instrument"),
        "notional_usd": action.get("notional_usd"),
        "price": action.get("price"),
        "position_id": action.get("position_id"),
        "note": action.get("note"),
        "paper_mid_source": action.get("paper_mid_source"),
        "paper_mid_as_of": action.get("paper_mid_as_of"),
        "paper_mid_kind": action.get("paper_mid_kind"),
        "realized_pnl_usd": action.get("realized_pnl_usd"),
    }
    if extra:
        row.update(extra)
    return row


def _block_expansion(
    seat_book: dict[str, Any],
    action: dict[str, Any],
    *,
    when: datetime,
    run_id: str,
    result: str,
    reason: str,
) -> dict[str, Any]:
    kind = action.get("action")
    seat_book["blocked_opens"].append(
        {
            "action": kind,
            "instrument": action.get("instrument"),
            "reason": reason,
            "at": isoformat(when),
            "overnight_run_id": run_id,
        }
    )
    seat_book["history"].append(_history_entry(action, when=when, run_id=run_id, result=result))
    seat_book["alerts"].append(reason)
    seat_book["prior_action"] = seat_book.get("last_action")
    seat_book["last_action"] = kind
    return mark_to_market(seat_book, when=when, run_id=run_id)


def apply_action(
    seat_book: dict[str, Any],
    action: dict[str, Any],
    *,
    families: dict[str, Any],
    run_id: str,
    when: datetime | None = None,
    market_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stamp = now_ny(when)
    accrue_funding(seat_book, when=stamp, run_id=run_id, market_state=market_state)
    kind = action.get("action")
    if kind not in ACTIONS:
        raise SchemaError(f"unknown action {kind}")
    seat = seat_book["seat"]
    memo = validate_expression_memo(action.get("expression_memo"), seat=seat, action=kind)
    blocked: list[str] = []
    try:
        blocked = assert_action_allowed(kind, families, seat=seat)
    except FreshnessError as exc:
        if kind in EXPANDING_ACTIONS:
            seat_book["blocked_opens"].append(
                {
                    "action": kind,
                    "instrument": action.get("instrument"),
                    "reason": str(exc),
                    "at": isoformat(stamp),
                    "overnight_run_id": run_id,
                }
            )
            seat_book["history"].append(_history_entry(action, when=stamp, run_id=run_id, result="blocked_freshness"))
            seat_book["alerts"].append(str(exc))
            seat_book["prior_action"] = seat_book.get("last_action")
            seat_book["last_action"] = kind
            return mark_to_market(seat_book, when=stamp, run_id=run_id)
        raise

    if kind in {"OPEN", "ADD", "HEDGE"}:
        if seat_book.get("risk_stopped"):
            return _block_expansion(
                seat_book,
                action,
                when=stamp,
                run_id=run_id,
                result="blocked_risk_stop",
                reason=f"{seat} is RISK_STOPPED after breaching the hard drawdown limit",
            )
        if action.get("_paper_mark_error"):
            return _block_expansion(
                seat_book,
                action,
                when=stamp,
                run_id=run_id,
                result="blocked_mark",
                reason=str(action["_paper_mark_error"]),
            )
        projected = _projected_risk_capital(seat_book, action)
        if projected is None:
            return _block_expansion(
                seat_book,
                action,
                when=stamp,
                run_id=run_id,
                result="blocked_risk_capital",
                reason=f"{seat} {kind} blocked: 1% shocked risk capital cannot be computed from deterministic marks",
            )
        if projected - risk_capital_limit_usd() > 1e-6:
            reason = (
                f"{seat} {kind} blocked: projected shocked risk capital {projected:,.2f} exceeds "
                f"{risk_capital_limit_usd():,.0f} seat risk-capital cap"
            )
            return _block_expansion(
                seat_book,
                action,
                when=stamp,
                run_id=run_id,
                result="blocked_risk_capital",
                reason=reason,
            )

    if kind == "OPEN":
        _open_position(seat_book, action, memo=memo, run_id=run_id, when=stamp)
    elif kind == "ADD":
        _resize(seat_book, action, factor=1, run_id=run_id, when=stamp)
    elif kind == "REDUCE":
        _resize(seat_book, action, factor=-1, run_id=run_id, when=stamp)
    elif kind == "CLOSE":
        _close(seat_book, action, run_id=run_id, when=stamp)
    elif kind == "HEDGE":
        _hedge(seat_book, action, memo=memo, run_id=run_id, when=stamp)
    elif kind == "HOLD":
        pass

    seat_book["prior_action"] = seat_book.get("last_action")
    seat_book["last_action"] = kind
    if action.get("conviction") is not None:
        conviction = int(action["conviction"])
        if not 0 <= conviction <= 100:
            raise SchemaError(f"{seat} conviction must be 0-100")
        seat_book["conviction"] = conviction
    if action.get("thesis"):
        seat_book["thesis"] = action["thesis"]
    if action.get("invalidation"):
        seat_book["invalidation"] = action["invalidation"]
    if action.get("alerts"):
        seat_book["alerts"].extend(list(action["alerts"]))
    seat_book["required_pitch"] = action.get("required_pitch")
    seat_book["risk_put_on"] = action.get("risk_put_on") if "risk_put_on" in action else action.get("risk")
    seat_book["evidence_cutoff"] = action.get("evidence_cutoff") or seat_book.get("evidence_cutoff")
    seat_book["history"].append(
        _history_entry(action, when=stamp, run_id=run_id, result="applied", extra={"blocked_families": blocked})
    )
    return mark_to_market(seat_book, when=stamp, run_id=run_id)


def _require_notional(action: dict[str, Any]) -> float:
    notional = _money(action.get("notional_usd"), "notional_usd")
    if notional <= 0:
        raise SchemaError("notional_usd must be positive")
    return notional


def _open_position(
    seat_book: dict[str, Any],
    action: dict[str, Any],
    *,
    memo: dict[str, Any],
    run_id: str,
    when: datetime,
) -> dict[str, Any]:
    notional = _require_notional(action)
    instrument = action.get("instrument")
    side = action.get("side")
    if not instrument:
        raise SchemaError("OPEN requires instrument")
    if side not in SIDES:
        raise SchemaError("OPEN requires side long|short")
    asset = action.get("asset_class") or selected_asset_class(memo) or "spot_fx"
    if asset not in ASSET_CLASSES:
        raise SchemaError(f"invalid asset_class {asset}")
    if expression_rule(seat_book["seat"]) == "spot_only" and asset != "spot_fx":
        raise SchemaError(f"{seat_book['seat']} may only OPEN spot_fx")
    position = {
        "position_id": action.get("position_id") or f"pos-{uuid4().hex[:12]}",
        "instrument": instrument,
        "asset_class": asset,
        "side": side,
        "notional_usd": notional,
        "entry_price": action.get("price"),
        "mark_price": action.get("mark_price", action.get("price")),
        "entry_price_source": action.get("paper_mid_source"),
        "entry_price_as_of": action.get("paper_mid_as_of"),
        "mark_price_source": action.get("paper_mid_source"),
        "mark_price_as_of": action.get("paper_mid_as_of"),
        "paper_expression": deepcopy(action.get("paper_expression")),
        "opened_at": isoformat(when),
        "opened_run_id": run_id,
        "thesis": action.get("thesis"),
        "invalidation": action.get("invalidation"),
        "hedge_of": action.get("hedge_of"),
        "unrealized_pnl_usd": None,
        "pnl_unavailable": action.get("price") in (None, ""),
    }
    action["position_id"] = position["position_id"]
    seat_book["positions"].append(position)
    return position


def _resize(seat_book: dict[str, Any], action: dict[str, Any], *, factor: int, run_id: str, when: datetime) -> None:
    position = _find_position(seat_book, action.get("position_id") or "")
    delta = _require_notional(action)
    if factor < 0:
        if delta > float(position["notional_usd"]) + 1e-9:
            raise SchemaError("REDUCE exceeds position notional")
        exit_price = action.get("price", position.get("mark_price"))
        if exit_price in (None, ""):
            realized = 0.0
            seat_book["alerts"].append(f"{position['position_id']} reduced without a price; realized P&L left at 0")
        else:
            realized = realized_increment(position, exit_price=float(exit_price), closed_notional=delta)
        position["notional_usd"] = round(float(position["notional_usd"]) - delta, 2)
        seat_book["realized_pnl_usd"] = round(float(seat_book["realized_pnl_usd"]) + realized, 2)
        seat_book["cash_usd"] = round(float(seat_book["cash_usd"]) + realized, 2)
        action["realized_pnl_usd"] = realized
        if position["notional_usd"] <= 1e-9:
            seat_book["positions"] = [p for p in seat_book["positions"] if p["position_id"] != position["position_id"]]
    else:
        # ADD: weighted-average entry when a new price is supplied
        add_price = action.get("price")
        old_n = float(position["notional_usd"])
        if add_price not in (None, "") and position.get("entry_price") not in (None, ""):
            position["entry_price"] = (float(position["entry_price"]) * old_n + float(add_price) * delta) / (old_n + delta)
            position["mark_price"] = action.get("mark_price", add_price)
            position["entry_price_source"] = "weighted_average_paper_mid"
            position["entry_price_as_of"] = action.get("paper_mid_as_of")
            position["mark_price_source"] = action.get("paper_mid_source")
            position["mark_price_as_of"] = action.get("paper_mid_as_of")
        position["notional_usd"] = round(old_n + delta, 2)
    action["overnight_run_id"] = run_id
    action["at"] = isoformat(when)


def _close(seat_book: dict[str, Any], action: dict[str, Any], *, run_id: str, when: datetime) -> None:
    position = _find_position(seat_book, action.get("position_id") or "")
    action["notional_usd"] = position["notional_usd"]
    action["instrument"] = position["instrument"]
    _resize(seat_book, action, factor=-1, run_id=run_id, when=when)


def _hedge(
    seat_book: dict[str, Any],
    action: dict[str, Any],
    *,
    memo: dict[str, Any],
    run_id: str,
    when: datetime,
) -> None:
    target_id = action.get("hedge_of") or action.get("position_id")
    if not target_id:
        raise SchemaError("HEDGE requires hedge_of or position_id of the existing risk")
    target = _find_position(seat_book, target_id)
    hedge = dict(action)
    hedge["action"] = "OPEN"
    hedge["hedge_of"] = target["position_id"]
    hedge.setdefault("instrument", target["instrument"])
    hedge.setdefault("asset_class", target["asset_class"])
    if "side" not in hedge:
        hedge["side"] = "short" if target["side"] == "long" else "long"
    _open_position(seat_book, hedge, memo=memo, run_id=run_id, when=when)
    action["position_id"] = hedge.get("position_id")


def apply_review(
    books: dict[str, Any],
    reviews: dict[str, Any],
    *,
    families: dict[str, Any],
    run_id: str,
    evidence_cutoff: str,
    when: datetime | None = None,
    market_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if set(reviews) != set(STANDING_SEATS):
        raise SchemaError(f"review must include every standing seat; missing/extra {set(reviews) ^ set(STANDING_SEATS)}")
    out = deepcopy(books)
    prepared_reviews = deepcopy(reviews)
    if market_state is not None:
        from scripts.overnight.paper_marks import hydrate_review_mids, refresh_book_marks

        refresh_book_marks(out, market_state)
        prepared_reviews = hydrate_review_mids(out, prepared_reviews, market_state)
    out["overnight_run_id"] = run_id
    out["evidence_cutoff"] = evidence_cutoff
    out["as_of"] = isoformat(now_ny(when))
    for seat in STANDING_SEATS:
        payload = prepared_reviews[seat]
        if payload.get("seat") not in (None, seat):
            raise SchemaError(f"review seat mismatch for {seat}")
        actions = payload.get("actions") or []
        if not actions:
            actions = [{"action": "HOLD", "expression_memo": payload.get("expression_memo") or _hold_memo(seat)}]
        seat_book = out["seats"][seat]
        for action in actions:
            action.setdefault("expression_memo", payload.get("expression_memo") or _hold_memo(seat))
            action.setdefault("thesis", payload.get("thesis"))
            action.setdefault("invalidation", payload.get("invalidation"))
            action.setdefault("conviction", payload.get("conviction", seat_book.get("conviction")))
            action.setdefault("required_pitch", payload.get("required_pitch"))
            action.setdefault("risk_put_on", payload.get("risk_put_on"))
            action.setdefault("evidence_cutoff", evidence_cutoff)
            apply_action(
                seat_book,
                action,
                families=families,
                run_id=run_id,
                when=when,
                market_state=market_state,
            )
        if payload.get("alerts"):
            seat_book["alerts"].extend(list(payload["alerts"]))
        mark_to_market(seat_book, when=when, run_id=run_id)
    return out


def _hold_memo(seat: str) -> dict[str, Any]:
    if expression_rule(seat) == "spot_only":
        return {
            "rates_candidate": None,
            "spot_candidate": None,
            "options_candidate": None,
            "selected": "none",
            "rationale": "No incremental spot risk; holding the current book.",
        }
    return {
        "rates_candidate": None,
        "spot_candidate": None,
        "options_candidate": None,
        "selected": "none",
        "rationale": "No incremental rates or spot risk; holding the current book.",
    }


def validate_books(books: dict[str, Any]) -> dict[str, Any]:
    if books.get("schema_version") != SCHEMA_VERSION:
        raise SchemaError("books schema_version mismatch")
    if set(books.get("seats") or {}) != set(STANDING_SEATS):
        raise SchemaError("books must contain every locked seat")
    if books.get("starting_nav_usd") != STARTING_NAV_USD:
        raise SchemaError(f"starting_nav_usd must be {STARTING_NAV_USD}")
    for seat, item in books["seats"].items():
        if item.get("seat") != seat:
            raise SchemaError(f"seat key/name mismatch for {seat}")
        if item.get("expression_rule") != expression_rule(seat):
            raise SchemaError(f"{seat} expression_rule drifted")
        if item.get("remit") != remit(seat):
            raise SchemaError(f"{seat} remit drifted from the standing roster")
        item.setdefault("funding_cost_usd", 0.0)
        item.setdefault("cash_yield_usd", 0.0)
        item.setdefault("funding_last_accrual_at", None)
        item.setdefault("funding_regime", "legacy_pending_sofr" if item.get("funding_last_accrual_at") else "sofr_risk_capital_1pct")
        item.setdefault("risk_capital_limit_usd", RISK_CAPITAL_LIMIT_USD)
        item.setdefault("max_drawdown_usd", MAX_DRAWDOWN_USD)
        item.setdefault("high_water_nav_usd", float(item.get("starting_nav_usd") or STARTING_NAV_USD))
        item.setdefault("drawdown_usd", 0.0)
        item.setdefault("risk_stopped", False)
        item.setdefault("risk_stop_pending", False)
        if item.get("funding_rate_annual") == 0.05:
            item["funding_rate_annual"] = None
        _attach_observed_rate(item)
        mark_to_market(item)
    return books


def public_books_view(books: dict[str, Any]) -> dict[str, Any]:
    """Dashboard-safe projection: no secrets, no private research."""
    validate_books(books)
    seats = []
    changes = []
    for seat in STANDING_SEATS:
        item = books["seats"][seat]
        seats.append(
            {
                "seat": seat,
                "remit": item["remit"],
                "expression_rule": item["expression_rule"],
                "nav_usd": item["nav_usd"],
                "realized_pnl_usd": item["realized_pnl_usd"],
                "unrealized_pnl_usd": item["unrealized_pnl_usd"],
                "gross_pnl_usd": item.get("gross_pnl_usd"),
                "funding_cost_usd": item.get("funding_cost_usd", 0.0),
                "cash_yield_usd": item.get("cash_yield_usd", 0.0),
                "funding_rate_annual": item.get("funding_rate_annual"),
                "funding_percent_rate": item.get("funding_percent_rate"),
                "funding_effective_date": item.get("funding_effective_date"),
                "funding_day_count": item.get("funding_day_count", FUNDING_DAY_COUNT),
                "funding_convention": item.get("funding_convention", FUNDING_CONVENTION),
                "funding_source": item.get("funding_source", FUNDING_SOURCE),
                "net_pnl_usd": item.get("net_pnl_usd"),
                "pnl_unavailable": item["pnl_unavailable"],
                "conviction": item["conviction"],
                "thesis": item.get("thesis"),
                "invalidation": item.get("invalidation"),
                "last_action": item.get("last_action"),
                "prior_action": item.get("prior_action"),
                "alerts": item.get("alerts") or [],
                "allocation_limit_usd": item.get("allocation_limit_usd", allocation_limit_usd()),
                "allocation_used_usd": item.get("allocation_used_usd"),
                "allocation_remaining_usd": item.get("allocation_remaining_usd"),
                "deployed_notional_usd": item.get("deployed_notional_usd", deployed_notional(item)),
                "risk_capital_usd": item.get("risk_capital_usd"),
                "risk_capital_limit_usd": item.get("risk_capital_limit_usd", RISK_CAPITAL_LIMIT_USD),
                "risk_capital_remaining_usd": item.get("risk_capital_remaining_usd"),
                "risk_capital_method": item.get("risk_capital_method"),
                "max_drawdown_usd": item.get("max_drawdown_usd", MAX_DRAWDOWN_USD),
                "high_water_nav_usd": item.get("high_water_nav_usd"),
                "drawdown_usd": item.get("drawdown_usd"),
                "risk_stopped": item.get("risk_stopped", False),
                "risk_stop_pending": item.get("risk_stop_pending", False),
                "positions": [
                    {
                        "position_id": p["position_id"],
                        "instrument": p["instrument"],
                        "asset_class": p["asset_class"],
                        "side": p["side"],
                        "notional_usd": p["notional_usd"],
                        "entry_price": p.get("entry_price"),
                        "mark_price": p.get("mark_price"),
                        "entry_price_source": p.get("entry_price_source"),
                        "entry_price_as_of": p.get("entry_price_as_of"),
                        "mark_price_source": p.get("mark_price_source"),
                        "mark_price_as_of": p.get("mark_price_as_of"),
                        "paper_expression": p.get("paper_expression"),
                        "opened_at": p.get("opened_at"),
                        "opened_run_id": p.get("opened_run_id"),
                        "thesis": p.get("thesis"),
                        "invalidation": p.get("invalidation"),
                        "unrealized_pnl_usd": p.get("unrealized_pnl_usd"),
                        "risk_capital_usd": p.get("risk_capital_usd"),
                        "risk_capital_method": p.get("risk_capital_method"),
                        "hedge_of": p.get("hedge_of"),
                    }
                    for p in item["positions"]
                ],
                "required_pitch": item.get("required_pitch"),
                "risk_put_on": item.get("risk_put_on"),
            }
        )
        for row in item.get("history") or []:
            if row.get("result") == "applied" and row.get("action") in {"OPEN", "ADD", "REDUCE", "HEDGE", "CLOSE"}:
                changes.append({"seat": seat, **{k: row.get(k) for k in ("action", "instrument", "notional_usd", "at", "result")}})
    ranked = sorted(
        (row for row in seats if not row["pnl_unavailable"] and row["net_pnl_usd"] is not None),
        key=lambda row: (-float(row["net_pnl_usd"]), row["seat"]),
    )
    prior_score: float | None = None
    prior_rank = 0
    for idx, row in enumerate(ranked, start=1):
        score = float(row["net_pnl_usd"])
        rank = prior_rank if prior_score is not None and score == prior_score else idx
        row["competition_rank"] = rank
        prior_score = score
        prior_rank = rank
    for row in seats:
        row.setdefault("competition_rank", None)
    leaderboard = [
        {
            "rank": row["competition_rank"],
            "seat": row["seat"],
            "net_pnl_usd": row["net_pnl_usd"],
            "gross_pnl_usd": row["gross_pnl_usd"],
            "funding_cost_usd": row["funding_cost_usd"],
            "cash_yield_usd": row["cash_yield_usd"],
            "pnl_unavailable": row["pnl_unavailable"],
        }
        for row in sorted(
            seats,
            key=lambda row: (
                row["competition_rank"] is None,
                row["competition_rank"] if row["competition_rank"] is not None else 10_000,
                row["seat"],
            ),
        )
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "overnight_run_id": books.get("overnight_run_id"),
        "as_of": books.get("as_of"),
        "evidence_cutoff": books.get("evidence_cutoff"),
        "review_status": books.get("review_status"),
        "last_successful_review_run_id": books.get("last_successful_review_run_id"),
        "starting_nav_usd": STARTING_NAV_USD,
        "funding_rate_annual": next(
            (row.get("funding_rate_annual") for row in seats if row.get("funding_rate_annual") is not None),
            None,
        ),
        "funding_day_count": FUNDING_DAY_COUNT,
        "funding_convention": FUNDING_CONVENTION,
        "funding_source": FUNDING_SOURCE,
        "competition_metric": "net_pnl_after_funding",
        "seat_count": len(seats),
        "leaderboard": leaderboard,
        "seats": seats,
        "overnight_changes": changes,
    }
