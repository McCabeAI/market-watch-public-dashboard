"""Persistent $100m paper books for the locked 14-seat roster."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

from scripts.funding.accounting import (
    FUNDING_REGIME_ZERO_BENCHMARK,
    apply_zero_return_sofr_migration,
    attach_financing_fields,
    competition_net_pnl,
)
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
from scripts.overnight.public_prose import public_alerts, sanitize_public_prose, sanitize_public_value
from scripts.overnight.freshness import assert_action_allowed
from scripts.risk_capital import (
    already_force_flattened_ids,
    attach_position_risk,
    book_risk_capital,
    partition_force_exit_positions,
    position_risk_capital,
)


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


def _projected_risk_capital(
    seat_book: dict[str, Any],
    action: dict[str, Any],
    market_state: dict[str, Any] | None = None,
) -> float | None:
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
        old_n = float(position["notional_usd"])
        new_n = old_n + _money(action.get("notional_usd"), "notional_usd")
        if position.get("legs") or position.get("valuation_method") == "instrument_dv01":
            from scripts.overnight.paper_marks import refresh_positions
            from scripts.rates.lifecycle import apply_book_resize

            if isinstance(market_state, dict):
                refresh_positions([projected], market_state)
            preview = apply_book_resize(
                projected,
                old_notional=old_n,
                new_notional=new_n,
                add_price=None if action.get("price") in (None, "") else float(action.get("price")),
                market_state=market_state,
            )
            # A mark that cannot be priced adds no risk. The booking path records pending_mark.
            if preview.get("pending_mark") or preview.get("zero_lot") or preview.get("size_rejected"):
                return current
            projected["notional_usd"] = new_n
        else:
            projected["notional_usd"] = new_n
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
        "paper_expression": deepcopy(source.get("paper_expression")) if isinstance(source.get("paper_expression"), dict) else source.get("paper_expression"),
    }
    try:
        _install_rates_economics(position, market_state)
    except SchemaError:
        return None
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

    Paper NAV may be described as earning SOFR, but the same principal is
    benchmarked at SOFR so those flows cancel in competition P&L. Deployed
    shocked-risk capital pays official SOFR; notional is never borrowed
    principal. A flat book, including no-trade-skeptic, has zero net financing.
    """
    apply_zero_return_sofr_migration(seat_book, paper_nav=STARTING_NAV_USD)
    seat_book.setdefault("funding_cost_usd", 0.0)
    seat_book.setdefault("cash_yield_usd", 0.0)
    seat_book.setdefault("benchmark_cost_usd", 0.0)
    _attach_observed_rate(seat_book, market_state)
    _attach_allocation_fields(seat_book)
    last_raw = seat_book.get("funding_last_accrual_at")
    if not last_raw:
        seat_book["funding_last_accrual_at"] = isoformat(when)
        seat_book["funding_regime"] = FUNDING_REGIME_ZERO_BENCHMARK
        return {"funding_cost_usd": 0.0, "cash_yield_usd": 0.0, "benchmark_cost_usd": 0.0}
    try:
        last = datetime.fromisoformat(str(last_raw))
    except ValueError as exc:
        raise SchemaError(f"invalid funding accrual timestamp {last_raw}") from exc
    if (when - last).total_seconds() <= 0:
        return {"funding_cost_usd": 0.0, "cash_yield_usd": 0.0, "benchmark_cost_usd": 0.0}

    history = extract_sofr_history(market_state or {}, seat_book.get("funding_context") or {})
    principal = float(seat_book.get("risk_capital_usd") or 0.0)
    try:
        funding_accrual = accrue_act_360(principal, start=last, end=when, history=history, market_state=market_state)
        cash_accrual = accrue_act_360(STARTING_NAV_USD, start=last, end=when, history=history, market_state=market_state)
    except FundingHistoryError as exc:
        seat_book.setdefault("alerts", []).append(f"funding_accrual_failed_closed: {exc}")
        seat_book["funding_accrual_status"] = "failed_closed"
        return {"funding_cost_usd": 0.0, "cash_yield_usd": 0.0, "benchmark_cost_usd": 0.0, "failed_closed": True}

    funding_increment = funding_accrual["amount"]
    cash_yield_increment = cash_accrual["amount"]
    benchmark_increment = cash_yield_increment
    seat_book["funding_cost_usd"] = round(float(seat_book.get("funding_cost_usd") or 0.0) + funding_increment, 2)
    seat_book["cash_yield_usd"] = round(float(seat_book.get("cash_yield_usd") or 0.0) + cash_yield_increment, 2)
    seat_book["benchmark_cost_usd"] = round(float(seat_book.get("benchmark_cost_usd") or 0.0) + benchmark_increment, 2)
    seat_book["cash_usd"] = round(
        float(seat_book.get("cash_usd", STARTING_NAV_USD))
        + cash_yield_increment
        - benchmark_increment
        - funding_increment,
        2,
    )

    seat_book["funding_last_accrual_at"] = isoformat(when)
    seat_book["funding_regime"] = FUNDING_REGIME_ZERO_BENCHMARK
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
                "benchmark_cost_base_usd": STARTING_NAV_USD,
                "funding_cost_usd": funding_increment,
                "cash_yield_usd": cash_yield_increment,
                "benchmark_cost_usd": benchmark_increment,
            }
        )
    return {
        "funding_cost_usd": funding_increment,
        "cash_yield_usd": cash_yield_increment,
        "benchmark_cost_usd": benchmark_increment,
    }

def position_pnl(position: dict[str, Any]) -> dict[str, Any]:
    """Paper P&L. Supported contracts and stored legs use instrument DV01.

    Unstamped historical rows stay on the legacy duration-one vintage.
    """
    from scripts.rates.valuation import value_position

    return value_position(position)


def realized_increment(position: dict[str, Any], *, exit_price: float, closed_notional: float) -> float:
    from scripts.rates.valuation import value_position

    if position.get("legs"):
        valued = value_position(position, exit_price=exit_price, closed_notional=closed_notional)
        if valued.get("pnl_unavailable") or valued.get("unrealized_pnl_usd") is None:
            raise SchemaError(valued.get("pnl_note") or "cannot realize structure P&L without leg marks, DV01, and FX")
        return float(valued["unrealized_pnl_usd"])
    if position.get("entry_price") in (None, ""):
        raise SchemaError("cannot realize P&L without an entry_price")
    valued = value_position(position, exit_price=exit_price, closed_notional=closed_notional)
    if valued.get("pnl_unavailable") or valued.get("unrealized_pnl_usd") is None:
        raise SchemaError(valued.get("pnl_note") or "cannot realize P&L")
    if valued.get("valuation_method") != "instrument_dv01" and _money(position["entry_price"], "entry_price") == 0:
        raise SchemaError("cannot realize P&L with a zero entry_price")
    return float(valued["unrealized_pnl_usd"])


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
        "benchmark_cost_usd": 0.0,
        "net_financing_pnl_usd": 0.0,
        "funding_rate_annual": None,
        "funding_percent_rate": None,
        "funding_effective_date": None,
        "funding_day_count": FUNDING_DAY_COUNT,
        "funding_convention": FUNDING_CONVENTION,
        "funding_source": FUNDING_SOURCE,
        "funding_regime": FUNDING_REGIME_ZERO_BENCHMARK,
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


PENDING_FORCE_FLATTEN_REASON = (
    "max drawdown breached but one or more positions lack a deterministic exit mark; "
    "expansion is blocked pending forced flatten"
)


def _force_drawdown_flatten(
    seat_book: dict[str, Any],
    *,
    when: datetime | None = None,
    run_id: str | None = None,
) -> bool:
    positions = list(seat_book.get("positions") or [])
    if not positions:
        seat_book["risk_stopped"] = True
        seat_book["risk_stop_pending"] = False
        return True

    already = already_force_flattened_ids(seat_book)
    markable, blocked = partition_force_exit_positions(positions)
    markable = [position for position in markable if str(position.get("position_id") or "") not in already]

    realized = 0.0
    flattened_ids: list[str] = []
    if markable:
        for position in markable:
            realized += realized_increment(
                position,
                exit_price=float(position["mark_price"]),
                closed_notional=float(position["notional_usd"]),
            )
            if position.get("position_id"):
                flattened_ids.append(str(position["position_id"]))
        realized = round(realized, 2)
        seat_book["realized_pnl_usd"] = round(float(seat_book.get("realized_pnl_usd") or 0.0) + realized, 2)
        seat_book["cash_usd"] = round(float(seat_book.get("cash_usd", STARTING_NAV_USD)) + realized, 2)
        remaining_ids = {id(position) for position in blocked}
        seat_book["positions"] = [position for position in positions if id(position) in remaining_ids]

    seat_book["risk_stopped"] = True
    pending = bool(seat_book.get("positions"))
    seat_book["risk_stop_pending"] = pending
    stamp = isoformat(now_ny(when))
    if flattened_ids or not seat_book.get("risk_stop_at"):
        seat_book["risk_stop_at"] = stamp
    seat_book["prior_action"] = seat_book.get("last_action")
    seat_book["last_action"] = "RISK_STOP"
    history = seat_book.setdefault("history", [])
    result = "pending_forced_flatten" if pending else "forced_flat"
    if flattened_ids or (
        pending
        and not any(row.get("action") == "RISK_STOP" and row.get("result") == "pending_forced_flatten" for row in history)
    ):
        history.append(
            {
                "at": stamp,
                "overnight_run_id": run_id,
                "action": "RISK_STOP",
                "result": result,
                "realized_pnl_usd": round(realized, 2),
                "flattened_position_ids": flattened_ids,
                "drawdown_usd": seat_book.get("drawdown_usd"),
                "max_drawdown_usd": seat_book.get("max_drawdown_usd", MAX_DRAWDOWN_USD),
            }
        )
    alerts = seat_book.setdefault("alerts", [])
    if pending:
        if PENDING_FORCE_FLATTEN_REASON not in alerts:
            alerts.append(PENDING_FORCE_FLATTEN_REASON)
    else:
        msg = (
            "RISK_STOP: book forcibly flattened after drawdown reached "
            f"{float(seat_book.get('drawdown_usd') or 0.0):,.2f}"
        )
        if msg not in alerts:
            alerts.append(msg)
    return not pending


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
        if pnl.get("valuation_method") and not position.get("valuation_method"):
            position["valuation_method"] = pnl["valuation_method"]
        if pnl.get("isolated"):
            position["isolated"] = True
            position["corrected_valuation_status"] = pnl.get("corrected_valuation_status")
            if pnl.get("isolation_reason"):
                position["isolation_reason"] = pnl["isolation_reason"]
            if pnl.get("structure_label"):
                position["structure_label"] = pnl["structure_label"]
        attach_position_risk(position)
        if pnl["pnl_unavailable"]:
            missing = True
        else:
            unrealized += float(pnl["unrealized_pnl_usd"])
    seat_book["unrealized_pnl_usd"] = round(unrealized, 2)
    seat_book["pnl_unavailable"] = missing
    gross = round(float(seat_book.get("realized_pnl_usd") or 0.0) + unrealized, 2)
    apply_zero_return_sofr_migration(seat_book, paper_nav=float(seat_book.get("starting_nav_usd") or STARTING_NAV_USD))
    attach_financing_fields(seat_book, gross=None if missing else gross, missing=missing)
    seat_book["gross_pnl_usd"] = None if missing else gross
    _attach_observed_rate(seat_book)
    cash_yield = round(float(seat_book.get("cash_yield_usd") or 0.0), 2)
    benchmark = round(float(seat_book.get("benchmark_cost_usd") or 0.0), 2)
    funding = round(float(seat_book.get("funding_cost_usd") or 0.0), 2)
    seat_book["cash_usd"] = round(
        float(seat_book["starting_nav_usd"])
        + float(seat_book.get("realized_pnl_usd") or 0.0)
        - funding
        + cash_yield
        - benchmark,
        2,
    )
    known_net = competition_net_pnl(
        gross,
        funding_cost_usd=funding,
        cash_yield_usd=cash_yield,
        benchmark_cost_usd=benchmark,
    )
    seat_book["nav_usd"] = round(float(seat_book["starting_nav_usd"]) + known_net, 2)
    _attach_allocation_fields(seat_book)

    seat_book.setdefault("max_drawdown_usd", MAX_DRAWDOWN_USD)
    seat_book.setdefault("high_water_nav_usd", float(seat_book["starting_nav_usd"]))
    seat_book.setdefault("risk_stopped", False)
    seat_book.setdefault("risk_stop_pending", False)
    if not missing:
        high_water = max(float(seat_book["high_water_nav_usd"]), float(seat_book["nav_usd"]))
        seat_book["high_water_nav_usd"] = round(high_water, 2)
    seat_book["drawdown_usd"] = round(
        max(0.0, float(seat_book["high_water_nav_usd"]) - float(seat_book["nav_usd"])),
        2,
    )
    if seat_book.get("risk_stopped") and not seat_book.get("positions"):
        seat_book["risk_stop_pending"] = False

    pending_open = bool(seat_book.get("risk_stop_pending") and seat_book.get("positions"))
    drawdown_breach = float(seat_book["drawdown_usd"]) >= float(seat_book["max_drawdown_usd"])
    needs_stop = drawdown_breach and (seat_book.get("positions") or not seat_book.get("risk_stopped"))
    if enforce_stop and (pending_open or needs_stop):
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
    for key in (
        "fill_status",
        "size_reject_reason",
        "minimum_executable_increment_usd",
        "minimum_executable_fraction",
        "minimum_executable_notional_usd",
        "package_policy",
        "zero_lot_policy",
    ):
        if action.get(key) not in (None, ""):
            row[key] = action[key]
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
    memo_for_gate = memo if isinstance(memo, dict) else {}
    selected = memo_for_gate.get("selected")
    selected_candidate = {
        "rates": memo_for_gate.get("rates_candidate"),
        "spot": memo_for_gate.get("spot_candidate"),
        "options": memo_for_gate.get("options_candidate"),
    }.get(selected)
    selected_candidate = selected_candidate if isinstance(selected_candidate, dict) else {}
    if kind in {"OPEN", "ADD", "HEDGE"}:
        from scripts.overnight.mark_admission import (
            action_exposure,
            entry_rejection,
            seat_valuation_block,
            unresolved_research_position_ids,
        )
        from scripts.overnight.paper_marks import resolve_paper_mid

        gate_instrument, gate_asset_class, gate_expression = action_exposure(
            action,
            seat_book.get("positions"),
            selected_candidate=selected_candidate,
        )
        rejection = entry_rejection(
            gate_instrument,
            asset_class=gate_asset_class if isinstance(gate_asset_class, str) else None,
            expression=gate_expression if isinstance(gate_expression, dict) else None,
            action=kind,
        )
        if rejection:
            return _block_expansion(
                seat_book,
                action,
                when=stamp,
                run_id=run_id,
                result="blocked_admission",
                reason=f"{rejection['reason']}: {rejection['message']}",
            )
        unresolved = unresolved_research_position_ids(
            seat_book.get("positions"),
            market_state=market_state,
            resolve_mark=resolve_paper_mid,
        )
        seat_block = seat_valuation_block(seat_book.get("positions"), unresolved)
        if seat_block:
            return _block_expansion(
                seat_book,
                action,
                when=stamp,
                run_id=run_id,
                result="blocked_admission",
                reason=f"{seat_block['reason']}: {seat_block['message']}",
            )
    try:
        blocked = assert_action_allowed(
            kind,
            families,
            seat=seat,
            instrument=action.get("instrument") or selected_candidate.get("instrument"),
            asset_class=action.get("asset_class") or selected_candidate.get("asset_class"),
            expression=_expression_for_freshness_gate(seat_book, action, selected_candidate),
        )
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
        projected = _projected_risk_capital(seat_book, action, market_state)
        if projected is None:
            return _block_expansion(
                seat_book,
                action,
                when=stamp,
                run_id=run_id,
                result="blocked_risk_capital",
                reason=f"{seat} {kind} blocked: standard-shock risk capital cannot be computed from deterministic marks",
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
        _open_position(seat_book, action, memo=memo, run_id=run_id, when=stamp, market_state=market_state)
    elif kind == "ADD":
        _resize(seat_book, action, factor=1, run_id=run_id, when=stamp, market_state=market_state)
    elif kind == "REDUCE":
        _resize(seat_book, action, factor=-1, run_id=run_id, when=stamp, market_state=market_state)
    elif kind == "CLOSE":
        _close(seat_book, action, run_id=run_id, when=stamp, market_state=market_state)
    elif kind == "HEDGE":
        _hedge(seat_book, action, memo=memo, run_id=run_id, when=stamp, market_state=market_state)
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
        _history_entry(
            action,
            when=stamp,
            run_id=run_id,
            result=(
                "pending_mark"
                if action.get("pending_mark")
                else action.get("fill_status")
                if action.get("fill_status") in {"zero_lot", "size_rejected"}
                else "applied"
            ),
            extra={"blocked_families": blocked},
        )
    )
    return mark_to_market(seat_book, when=stamp, run_id=run_id)


def _expression_for_freshness_gate(
    seat_book: dict[str, Any],
    action: dict[str, Any],
    selected_candidate: dict[str, Any],
) -> Any:
    """Paper expression the freshness gate must evaluate.

    Trader Room actions carry the expression on ``paper_expression``. ADD and
    CLOSE follow the open position. A HEDGE with no instrument of its own
    follows the target position. The selected candidate is only a fallback
    when the action and its target omit the expression.
    """
    kind = action.get("action")
    expression = action.get("paper_expression")
    if kind in {"ADD", "REDUCE", "CLOSE"}:
        try:
            position = _find_position(seat_book, str(action.get("position_id") or ""))
        except SchemaError:
            position = None
        if isinstance(position, dict) and position.get("paper_expression") is not None:
            expression = position.get("paper_expression")
    elif kind == "HEDGE" and not action.get("instrument"):
        target_id = action.get("hedge_of") or action.get("position_id")
        try:
            target = _find_position(seat_book, str(target_id or ""))
        except SchemaError:
            target = None
        if expression is None and isinstance(target, dict):
            expression = target.get("paper_expression")
    if expression is None and isinstance(selected_candidate, dict):
        candidate_expression = selected_candidate.get("paper_expression")
        if candidate_expression is not None:
            expression = candidate_expression
    return expression


def _require_notional(action: dict[str, Any]) -> float:
    notional = _money(action.get("notional_usd"), "notional_usd")
    if notional <= 0:
        raise SchemaError("notional_usd must be positive")
    return notional


def _install_rates_economics(
    position: dict[str, Any],
    market_state: dict[str, Any] | None,
    *,
    side: str | None = None,
) -> None:
    """Build the same legs, lots, FX vintage, and DV01 the booking path will keep."""
    from scripts.overnight.paper_marks import PaperMarkError, hydrate_structure_rates
    from scripts.rates.structures import STRUCTURE_TYPES, StructureError, build_structure
    from scripts.rates.valuation import stamp_open_valuation

    expression = position.get("paper_expression") if isinstance(position.get("paper_expression"), dict) else None
    if expression and expression.get("type") in STRUCTURE_TYPES:
        try:
            built = build_structure(
                expression,
                side=str(side or position.get("side") or "long"),
                notional_usd=float(position.get("notional_usd") or 0.0),
                market_state=market_state,
            )
        except (StructureError, SchemaError, PaperMarkError) as exc:
            raise SchemaError(str(exc)) from exc
        position["legs"] = built["legs"]
        position["spread_dv01_usd"] = built["spread_dv01_usd"]
        position["structure_label"] = built["type"]
        position["mark_definition"] = built["mark_definition"]
        position["residual_dv01_usd"] = round(
            sum(float(leg.get("residual_contracts") or 0.0) * float(leg.get("dv01_per_contract_local") or 0.0) * float(leg.get("mark_fx_usd_per_unit") or 0.0) for leg in built["legs"]),
            6,
        )
        try:
            hydrate_structure_rates(position, market_state)
        except PaperMarkError as exc:
            raise SchemaError(str(exc)) from exc
    stamp_open_valuation(position, market_state)


def _open_position(
    seat_book: dict[str, Any],
    action: dict[str, Any],
    *,
    memo: dict[str, Any],
    run_id: str,
    when: datetime,
    market_state: dict[str, Any] | None = None,
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
        "expected_mark_direction": action.get("expected_mark_direction"),
    }
    _install_rates_economics(position, market_state, side=str(side))
    if position.get("valuation_method") == "unavailable":
        raise SchemaError(position.get("isolation_reason") or "instrument economics unavailable")
    action["position_id"] = position["position_id"]
    seat_book["positions"].append(position)
    return position


def _refresh_live_marks(position: dict[str, Any], market_state: dict[str, Any] | None) -> None:
    stamped = position.get("legs") or position.get("valuation_method") == "instrument_dv01"
    if not stamped:
        return
    from scripts.overnight.paper_marks import clear_unresolved_mark, refresh_positions

    if not isinstance(market_state, dict):
        if position.get("legs") or position.get("contract_currency") not in (None, "USD"):
            clear_unresolved_mark(position, reason="market state missing; current marks invalidated")
        return
    refresh_positions([position], market_state)


def _instrument_position(position: dict[str, Any]) -> bool:
    return bool(position.get("legs") or (position.get("valuation_method") == "instrument_dv01" and position.get("contracts") is not None))


def _resize(
    seat_book: dict[str, Any],
    action: dict[str, Any],
    *,
    factor: int,
    run_id: str,
    when: datetime,
    market_state: dict[str, Any] | None = None,
) -> None:
    position = _find_position(seat_book, action.get("position_id") or "")
    delta = _require_notional(action)
    old_n = float(position["notional_usd"])
    if factor < 0 and delta > old_n + 1e-9:
        raise SchemaError("REDUCE exceeds position notional")
    new_n = round(old_n - delta, 2) if factor < 0 else round(old_n + delta, 2)
    from scripts.rates.lifecycle import stamp_structure_nofill, structure_resize_block

    blocked = structure_resize_block(position, old_notional=old_n, new_notional=new_n, market_state=market_state)
    if blocked:
        stamp_structure_nofill(action, blocked)
        if blocked["fill_status"] == "size_rejected":
            seat_book["alerts"].append(
                f"{position['position_id']} resize rejected: {blocked.get('reason')}"
            )
        else:
            seat_book["alerts"].append(
                f"{position['position_id']} resize was below one lot on every leg; contracts were left unchanged"
            )
        return
    _refresh_live_marks(position, market_state)
    from scripts.overnight.paper_marks import marks_are_current

    if _instrument_position(position) and not marks_are_current(position):
        action["pending_mark"] = True
        action["fill_status"] = "pending_mark"
        action["realized_pnl_usd"] = None
        action["lots_closed"] = 0
        action["lots_added"] = 0
        position["exit_status"] = "pending_mark"
        position["pnl_unavailable"] = True
        seat_book["alerts"].append(
            f"{position['position_id']} {action.get('action') or 'resize'} left pending: current marks or FX are unavailable; no fill or P&L was invented"
        )
        return
    if factor < 0:
        old_n = float(position["notional_usd"])
        new_n = round(old_n - delta, 2)
        if _instrument_position(position):
            from scripts.rates.lifecycle import apply_book_resize

            result = apply_book_resize(position, old_notional=old_n, new_notional=new_n, market_state=market_state)
            if result.get("pending_mark"):
                action["pending_mark"] = True
                action["fill_status"] = "pending_mark"
                action["realized_pnl_usd"] = None
                position["exit_status"] = "pending_mark"
                seat_book["alerts"].append(
                    f"{position['position_id']} REDUCE/CLOSE left pending: current marks or FX are unavailable; no fill or P&L was invented"
                )
                return
            if result.get("zero_lot"):
                action["fill_status"] = "zero_lot"
                action["lots_closed"] = 0
                action["realized_pnl_usd"] = 0.0
                action["zero_lot_policy"] = "sub_lot_request_is_not_a_fill"
                seat_book["alerts"].append(
                    f"{position['position_id']} REDUCE did not close a whole lot; contracts and P&L were left unchanged"
                )
                return
            realized = float(result["realized_pnl_usd"])
            action["lots_closed"] = result.get("lots_closed")
            action["fill_status"] = "executed"
            position["notional_usd"] = new_n
            position.pop("_closed_lots", None)
        else:
            exit_price = action.get("price", position.get("mark_price"))
            if exit_price in (None, ""):
                realized = 0.0
                seat_book["alerts"].append(f"{position['position_id']} reduced without a price; realized P&L left at 0")
            else:
                realized = realized_increment(position, exit_price=float(exit_price), closed_notional=delta)
            position["notional_usd"] = new_n
            action["fill_status"] = "executed"
        seat_book["realized_pnl_usd"] = round(float(seat_book["realized_pnl_usd"]) + realized, 2)
        seat_book["cash_usd"] = round(float(seat_book["cash_usd"]) + realized, 2)
        action["realized_pnl_usd"] = realized
        if position["notional_usd"] <= 1e-9 or (
            _instrument_position(position) and int(position.get("contracts") or 0) == 0 and not position.get("legs")
        ) or (position.get("legs") and all(int(leg.get("contracts") or 0) == 0 for leg in position["legs"])):
            seat_book["positions"] = [p for p in seat_book["positions"] if p["position_id"] != position["position_id"]]
    else:
        add_price = action.get("price", position.get("mark_price"))
        old_n = float(position["notional_usd"])
        new_n = round(old_n + delta, 2)
        if _instrument_position(position):
            from scripts.rates.lifecycle import apply_book_resize

            result = apply_book_resize(
                position,
                old_notional=old_n,
                new_notional=new_n,
                add_price=None if add_price in (None, "") else float(add_price),
                market_state=market_state,
            )
            if result.get("zero_lot"):
                action["fill_status"] = "zero_lot"
                action["lots_added"] = 0
                action["realized_pnl_usd"] = 0.0
                action["zero_lot_policy"] = "sub_lot_request_is_not_a_fill"
                seat_book["alerts"].append(
                    f"{position['position_id']} ADD was below one lot; contracts were left unchanged"
                )
                return
            if result.get("pending_mark"):
                action["pending_mark"] = True
                action["fill_status"] = "pending_mark"
                return
            position["notional_usd"] = new_n
            action["lots_added"] = result.get("lots_added")
            action["fill_status"] = "executed"
            if add_price not in (None, ""):
                position["mark_price"] = add_price
                position["entry_price_source"] = "weighted_average_of_actual_lots"
        elif add_price not in (None, "") and position.get("entry_price") not in (None, ""):
            position["entry_price"] = (float(position["entry_price"]) * old_n + float(add_price) * delta) / new_n
            position["mark_price"] = action.get("mark_price", add_price)
            position["entry_price_source"] = "weighted_average_paper_mid"
            position["entry_price_as_of"] = action.get("paper_mid_as_of")
            position["mark_price_source"] = action.get("paper_mid_source")
            position["mark_price_as_of"] = action.get("paper_mid_as_of")
            position["notional_usd"] = new_n
            action["fill_status"] = "executed"
        else:
            position["notional_usd"] = new_n
            action["fill_status"] = "executed"
    action["overnight_run_id"] = run_id
    action["at"] = isoformat(when)


def _close(
    seat_book: dict[str, Any],
    action: dict[str, Any],
    *,
    run_id: str,
    when: datetime,
    market_state: dict[str, Any] | None = None,
) -> None:
    position = _find_position(seat_book, action.get("position_id") or "")
    action["notional_usd"] = position["notional_usd"]
    action["instrument"] = position["instrument"]
    _resize(seat_book, action, factor=-1, run_id=run_id, when=when, market_state=market_state)


def _hedge(
    seat_book: dict[str, Any],
    action: dict[str, Any],
    *,
    memo: dict[str, Any],
    run_id: str,
    when: datetime,
    market_state: dict[str, Any] | None = None,
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
    _open_position(seat_book, hedge, memo=memo, run_id=run_id, when=when, market_state=market_state)
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
        for seat_book in out["seats"].values():
            mark_to_market(seat_book, when=when, run_id=run_id)
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

    def public_position(p: dict[str, Any]) -> dict[str, Any]:
        row = {
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
            "mark_status": p.get("mark_status"),
            "mark_unavailable_reason": p.get("mark_unavailable_reason"),
            "pnl_unavailable": p.get("pnl_unavailable"),
            "mark_fx_status": p.get("mark_fx_status"),
            "mark_fx_usd_per_unit": p.get("mark_fx_usd_per_unit"),
            "paper_expression": sanitize_public_value(p.get("paper_expression"), max_chars=500),
            "opened_at": p.get("opened_at"),
            "opened_run_id": p.get("opened_run_id"),
            "thesis": sanitize_public_prose(p.get("thesis"), max_chars=500, fallback=""),
            "invalidation": sanitize_public_prose(p.get("invalidation"), max_chars=400, fallback=""),
            "unrealized_pnl_usd": p.get("unrealized_pnl_usd"),
            "valuation_method": p.get("valuation_method"),
            "isolated": bool(p.get("isolated")),
            "structure_label": p.get("structure_label"),
            "risk_capital_usd": p.get("risk_capital_usd"),
            "risk_capital_method": p.get("risk_capital_method"),
            "hedge_of": p.get("hedge_of"),
        }
        legs = p.get("legs")
        if isinstance(legs, list):
            row["legs"] = [
                {
                    "instrument": leg.get("instrument"),
                    "mark_status": leg.get("mark_status"),
                    "mark_rate": leg.get("mark_rate"),
                    "mark_price": leg.get("mark_price"),
                    "currency": leg.get("currency"),
                    "mark_fx_status": leg.get("mark_fx_status"),
                    "mark_fx_usd_per_unit": leg.get("mark_fx_usd_per_unit"),
                }
                for leg in legs
                if isinstance(leg, dict)
            ]
        return row

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
                "benchmark_cost_usd": item.get("benchmark_cost_usd", 0.0),
                "net_financing_pnl_usd": item.get("net_financing_pnl_usd"),
                "funding_rate_annual": item.get("funding_rate_annual"),
                "funding_percent_rate": item.get("funding_percent_rate"),
                "funding_effective_date": item.get("funding_effective_date"),
                "funding_day_count": item.get("funding_day_count", FUNDING_DAY_COUNT),
                "funding_convention": item.get("funding_convention", FUNDING_CONVENTION),
                "funding_source": item.get("funding_source", FUNDING_SOURCE),
                "funding_accrual_status": item.get("funding_accrual_status"),
                "unresolved_funding_positions": item.get("unresolved_funding_positions") or [],
                "net_pnl_usd": item.get("net_pnl_usd"),
                "pnl_unavailable": item["pnl_unavailable"],
                "conviction": item["conviction"],
                "thesis": sanitize_public_prose(item.get("thesis"), max_chars=700, fallback=""),
                "invalidation": sanitize_public_prose(item.get("invalidation"), max_chars=500, fallback=""),
                "last_action": item.get("last_action"),
                "prior_action": item.get("prior_action"),
                "alerts": public_alerts(item.get("alerts")),
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
                "positions": [public_position(p) for p in item["positions"]],
                "required_pitch": sanitize_public_value(item.get("required_pitch"), max_chars=700),
                "risk_put_on": sanitize_public_value(item.get("risk_put_on"), max_chars=700),
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
            "benchmark_cost_usd": row.get("benchmark_cost_usd", 0.0),
            "net_financing_pnl_usd": row.get("net_financing_pnl_usd"),
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
