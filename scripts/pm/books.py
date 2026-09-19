"""Four independent $1bn-gross PM books. Not trader seats.

$1bn is a gross-notional risk limit, not automatically borrowed capital.
Realized cash yield / funding uses official NY Fed SOFR ACT/360 only where a
position's funded-capital draw can be proven from canonical fields.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

from scripts.funding.basis import apply_basis_to_position, funded_draw_for_book
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
from scripts.overnight.books import position_pnl, realized_increment
from scripts.overnight.clock import isoformat, now_ny
from scripts.overnight.paper_marks import (
    PaperMarkError,
    find_position,
    hydrate_action_mids,
    refresh_positions,
)
from scripts.pm.constants import (
    ACTIONS,
    ASSET_CLASSES,
    DECISION_STATUSES,
    CASH_CAPITAL_USD,
    GROSS_NOTIONAL_LIMIT_USD,
    MANDATES,
    MARK_REQUIRED_ACTIONS,
    PM_IDS,
    SCHEMA_VERSION,
    SIDES,
)
from scripts.pm.curve_lock import assert_family_locked, locked_fields
from scripts.pm.errors import CapError, IndependenceError, MarkError, SchemaError


def _money(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SchemaError(f"{field} must be numeric") from exc
    if number != number:
        raise SchemaError(f"{field} is not a number")
    return number


def mandate(pm_id: str) -> dict[str, Any]:
    if pm_id not in MANDATES:
        raise SchemaError(f"unknown pm_id {pm_id}")
    return dict(MANDATES[pm_id])


def hedge_allowed(pm_id: str) -> bool:
    return bool(MANDATES[pm_id]["hedge_allowed"])


def awaiting_status(pm_id: str) -> str:
    return str(MANDATES[pm_id]["awaiting_status"])


def gross_utilization(book: dict[str, Any]) -> float:
    return round(sum(abs(float(p.get("notional_usd") or 0.0)) for p in book.get("positions") or []), 2)


def assert_cap(book: dict[str, Any]) -> float:
    used = gross_utilization(book)
    limit = float(book.get("gross_notional_limit_usd") or GROSS_NOTIONAL_LIMIT_USD)
    if used - limit > 1e-6:
        raise CapError(
            f"{book.get('pm_id')} gross notional {used} exceeds limit {limit}"
        )
    return used


def empty_pm_book(pm_id: str) -> dict[str, Any]:
    spec = mandate(pm_id)
    return {
        "pm_id": pm_id,
        "label": spec["label"],
        "mandate": spec["shorthand"],
        "style": spec["style"],
        "hedge_allowed": spec["hedge_allowed"],
        "gross_notional_limit_usd": GROSS_NOTIONAL_LIMIT_USD,
        "gross_utilization_usd": 0.0,
        "gross_remaining_usd": float(GROSS_NOTIONAL_LIMIT_USD),
        "cash_capital_usd": CASH_CAPITAL_USD,
        "funded_draw_usd": 0.0,
        "unused_cash_usd": float(CASH_CAPITAL_USD),
        "funding_cost_usd": 0.0,
        "cash_yield_usd": 0.0,
        "net_after_funding_pnl_usd": 0.0,
        "funding_rate_annual": None,
        "funding_percent_rate": None,
        "funding_effective_date": None,
        "funding_day_count": FUNDING_DAY_COUNT,
        "funding_convention": FUNDING_CONVENTION,
        "funding_source": FUNDING_SOURCE,
        "funding_last_accrual_at": None,
        "funding_basis_status": "none",
        "unresolved_funding_positions": [],
        "positions": [],
        "history": [],
        "realized_pnl_usd": 0.0,
        "unrealized_pnl_usd": 0.0,
        "total_pnl_usd": 0.0,
        "pnl_unavailable": False,
        "conviction": 0,
        "thesis": None,
        "invalidation": None,
        "alerts": [],
        "prior_action": None,
        "last_action": None,
        "decision_status": awaiting_status(pm_id),
        "review_status": "awaiting",
        "review_packet_id": None,
        "review_packet_sha256": None,
        "last_decision_packet_id": None,
        "last_decision_packet_sha256": None,
        "last_decision_at": None,
        "evidence_cutoff": None,
        "rationale": None,
        "synthesis": None,
    }


def empty_books(
    *,
    trader_room_run_id: str | None = None,
    overnight_run_id: str | None = None,
    when: datetime | None = None,
) -> dict[str, Any]:
    stamp = isoformat(now_ny(when))
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "PM_BOOKS",
        "gross_notional_limit_usd": GROSS_NOTIONAL_LIMIT_USD,
        "cash_capital_usd": CASH_CAPITAL_USD,
        "as_of": stamp,
        "overnight_run_id": overnight_run_id,
        "trader_room_run_id": trader_room_run_id,
        "evidence_cutoff": None,
        "pms": {pm_id: empty_pm_book(pm_id) for pm_id in PM_IDS},
    }


def mark_pm_book(book: dict[str, Any]) -> dict[str, Any]:
    unrealized = 0.0
    missing = False
    for position in book.get("positions") or []:
        pnl = position_pnl(position)
        position["unrealized_pnl_usd"] = pnl["unrealized_pnl_usd"]
        position["pnl_unavailable"] = pnl["pnl_unavailable"]
        if pnl["pnl_unavailable"]:
            missing = True
        else:
            unrealized += float(pnl["unrealized_pnl_usd"])
    book["unrealized_pnl_usd"] = round(unrealized, 2)
    book["pnl_unavailable"] = missing
    realized = round(float(book.get("realized_pnl_usd") or 0.0), 2)
    book["realized_pnl_usd"] = realized
    book["total_pnl_usd"] = None if missing else round(realized + unrealized, 2)
    used = assert_cap(book)
    book["gross_utilization_usd"] = used
    book["gross_remaining_usd"] = round(float(book["gross_notional_limit_usd"]) - used, 2)
    book.setdefault("cash_capital_usd", CASH_CAPITAL_USD)
    draws = funded_draw_for_book(book)
    book.update(draws)
    funding = round(float(book.get("funding_cost_usd") or 0.0), 2)
    cash_yield = round(float(book.get("cash_yield_usd") or 0.0), 2)
    book["funding_cost_usd"] = funding
    book["cash_yield_usd"] = cash_yield
    book["net_after_funding_pnl_usd"] = None if missing else round(realized + unrealized - funding + cash_yield, 2)
    return book


def refresh_pm_book(book: dict[str, Any], market_state: dict[str, Any] | None) -> dict[str, Any]:
    if market_state is not None:
        alerts = book.setdefault("alerts", [])
        refresh_positions(list(book.get("positions") or []), market_state, alerts=alerts)
    return mark_pm_book(book)


def _find_position(book: dict[str, Any], position_id: str) -> dict[str, Any]:
    for position in book.get("positions") or []:
        if position["position_id"] == position_id:
            return position
    raise SchemaError(f"unknown position_id {position_id} for {book.get('pm_id')}")


def _history_entry(action: dict[str, Any], *, when: datetime, run_id: str | None, result: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    row = {
        "at": isoformat(when),
        "run_id": run_id,
        "action": action.get("action"),
        "result": result,
        "instrument": action.get("instrument"),
        "notional_usd": action.get("notional_usd"),
        "price": action.get("price"),
        "position_id": action.get("position_id"),
        "note": action.get("note"),
        "paper_mid_source": action.get("paper_mid_source"),
        "paper_mid_as_of": action.get("paper_mid_as_of"),
        "paper_mid_kind": action.get("paper_mid_kind"),
        "locked_expression_family": action.get("locked_expression_family"),
        "realized_pnl_usd": action.get("realized_pnl_usd"),
    }
    if extra:
        row.update(extra)
    return row


def _require_notional(action: dict[str, Any]) -> float:
    notional = _money(action.get("notional_usd"), "notional_usd")
    if notional <= 0:
        raise SchemaError("notional_usd must be positive")
    return notional


def _require_mark(action: dict[str, Any], *, kind: str, pm_id: str) -> float:
    price = action.get("price")
    if price in (None, ""):
        raise MarkError(f"{pm_id} {kind} failed closed: missing deterministic paper mark")
    return _money(price, "price")


def _set_decision_fields(book: dict[str, Any], action: dict[str, Any], decision: dict[str, Any] | None) -> None:
    payload = decision or {}
    if action.get("conviction") is not None or payload.get("conviction") is not None:
        conviction = int(action.get("conviction", payload.get("conviction")))
        if not 0 <= conviction <= 100:
            raise SchemaError(f"{book['pm_id']} conviction must be 0-100")
        book["conviction"] = conviction
    if action.get("thesis") or payload.get("thesis"):
        book["thesis"] = action.get("thesis") or payload.get("thesis")
    if action.get("invalidation") or payload.get("invalidation"):
        book["invalidation"] = action.get("invalidation") or payload.get("invalidation")
    if payload.get("rationale"):
        book["rationale"] = payload["rationale"]
    if payload.get("synthesis"):
        book["synthesis"] = payload["synthesis"]
    if action.get("alerts"):
        book.setdefault("alerts", []).extend(list(action["alerts"]))
    if payload.get("alerts"):
        book.setdefault("alerts", []).extend(list(payload["alerts"]))


def _derive_status(book: dict[str, Any], *, kind: str, had_prior_decision: bool) -> str:
    if kind == "NO_TRADE":
        return "no_trade"
    if book.get("positions"):
        return "active"
    if kind == "HOLD" and had_prior_decision:
        return "hold"
    if kind == "HOLD" and not had_prior_decision:
        # Explicit first HOLD is still an explicit hold, not awaiting.
        return "hold"
    if kind in MARK_REQUIRED_ACTIONS:
        return "active" if book.get("positions") else "hold"
    return book.get("decision_status") or awaiting_status(book["pm_id"])


def accrue_pm_funding(
    book: dict[str, Any],
    *,
    when: datetime,
    run_id: str | None = None,
    market_state: dict[str, Any] | None = None,
    model_forecast: Any = None,
) -> dict[str, float]:
    """Accrue official SOFR on proven unused cash / funded draw only.

    model_forecast is ignored for realized accounting.
    """
    del model_forecast
    book.setdefault("funding_cost_usd", 0.0)
    book.setdefault("cash_yield_usd", 0.0)
    book.setdefault("cash_capital_usd", CASH_CAPITAL_USD)
    draws = funded_draw_for_book(book)
    book.update(draws)
    fields = observed_rate_fields(market_state)
    if fields["funding_rate_annual"] is not None:
        book["funding_rate_annual"] = fields["funding_rate_annual"]
        book["funding_percent_rate"] = fields["funding_percent_rate"]
        book["funding_effective_date"] = fields["funding_effective_date"]
    book["funding_day_count"] = FUNDING_DAY_COUNT
    book["funding_convention"] = FUNDING_CONVENTION
    book["funding_source"] = FUNDING_SOURCE
    last_raw = book.get("funding_last_accrual_at")
    if not last_raw:
        book["funding_last_accrual_at"] = isoformat(when)
        return {"funding_cost_usd": 0.0, "cash_yield_usd": 0.0}
    try:
        last = datetime.fromisoformat(str(last_raw))
    except ValueError as exc:
        raise SchemaError(f"invalid PM funding accrual timestamp {last_raw}") from exc
    if (when - last).total_seconds() <= 0:
        return {"funding_cost_usd": 0.0, "cash_yield_usd": 0.0}
    history = extract_sofr_history(market_state or {})
    try:
        cost = accrue_act_360(
            float(book.get("funded_draw_usd") or 0.0),
            start=last,
            end=when,
            history=history,
            market_state=market_state,
        )
        yield_ = accrue_act_360(
            float(book.get("unused_cash_usd") or 0.0),
            start=last,
            end=when,
            history=history,
            market_state=market_state,
        )
    except FundingHistoryError as exc:
        book.setdefault("alerts", []).append(f"funding_accrual_failed_closed: {exc}")
        book["funding_accrual_status"] = "failed_closed"
        return {"funding_cost_usd": 0.0, "cash_yield_usd": 0.0, "failed_closed": True}
    book["funding_cost_usd"] = round(float(book.get("funding_cost_usd") or 0.0) + cost["amount"], 2)
    book["cash_yield_usd"] = round(float(book.get("cash_yield_usd") or 0.0) + yield_["amount"], 2)
    book["funding_last_accrual_at"] = isoformat(when)
    book["funding_accrual_status"] = "applied"
    book["funding_rate_annual"] = yield_["funding_rate_annual"] or cost["funding_rate_annual"]
    book["funding_percent_rate"] = yield_["latest_percent_rate"] or cost["latest_percent_rate"]
    book["funding_effective_date"] = yield_["latest_effective_date"] or cost["latest_effective_date"]
    if cost["amount"] or yield_["amount"]:
        book.setdefault("history", []).append(
            {
                "at": isoformat(when),
                "run_id": run_id,
                "action": "FUNDING",
                "result": "applied",
                "funding_rate_annual": book["funding_rate_annual"],
                "funding_percent_rate": book["funding_percent_rate"],
                "funding_effective_date": book["funding_effective_date"],
                "funding_source": FUNDING_SOURCE,
                "funding_source_url": FUNDING_SOURCE_URL,
                "funding_day_count": FUNDING_DAY_COUNT,
                "funding_convention": FUNDING_CONVENTION,
                "accrual_days": max(cost["accrual_days"], yield_["accrual_days"]),
                "funding_base_usd": book.get("funded_draw_usd"),
                "cash_yield_base_usd": book.get("unused_cash_usd"),
                "funding_cost_usd": cost["amount"],
                "cash_yield_usd": yield_["amount"],
                "gross_utilization_usd": book.get("gross_utilization_usd"),
                "funded_draw_usd": book.get("funded_draw_usd"),
            }
        )
    return {"funding_cost_usd": cost["amount"], "cash_yield_usd": yield_["amount"]}


def apply_action(
    book: dict[str, Any],
    action: dict[str, Any],
    *,
    run_id: str | None,
    when: datetime | None = None,
    decision: dict[str, Any] | None = None,
    market_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stamp = now_ny(when)
    accrue_pm_funding(
        book,
        when=stamp,
        run_id=run_id,
        market_state=market_state,
        model_forecast=(decision or {}).get("funding_forecast") or action.get("funding_forecast"),
    )
    kind = action.get("action")
    if kind not in ACTIONS:
        raise SchemaError(f"unknown action {kind}")
    pm_id = book["pm_id"]
    if kind == "HEDGE" and not hedge_allowed(pm_id):
        raise SchemaError(f"{pm_id} mandate prohibits HEDGE; reduce or close instead")

    had_prior = bool(book.get("last_decision_at") or book.get("last_action"))
    if kind == "OPEN":
        _open_position(book, action, run_id=run_id, when=stamp)
    elif kind == "ADD":
        _resize(book, action, factor=1, run_id=run_id, when=stamp)
    elif kind == "REDUCE":
        _resize(book, action, factor=-1, run_id=run_id, when=stamp)
    elif kind == "CLOSE":
        _close(book, action, run_id=run_id, when=stamp)
    elif kind == "HEDGE":
        _hedge(book, action, run_id=run_id, when=stamp)
    elif kind in {"HOLD", "NO_TRADE"}:
        pass

    book["prior_action"] = book.get("last_action")
    book["last_action"] = kind
    _set_decision_fields(book, action, decision)
    book["decision_status"] = _derive_status(book, kind=kind, had_prior_decision=had_prior)
    book["history"].append(_history_entry(action, when=stamp, run_id=run_id, result="applied"))
    return mark_pm_book(book)


def _open_position(book: dict[str, Any], action: dict[str, Any], *, run_id: str | None, when: datetime) -> dict[str, Any]:
    notional = _require_notional(action)
    instrument = action.get("instrument")
    side = action.get("side")
    if not instrument:
        raise SchemaError("OPEN requires instrument")
    if side not in SIDES:
        raise SchemaError("OPEN requires side long|short")
    asset = action.get("asset_class") or "spot_fx"
    if asset not in ASSET_CLASSES:
        raise SchemaError(f"invalid asset_class {asset}")
    if asset == "options" and action.get("price") in (None, ""):
        raise MarkError(f"{book['pm_id']} options remain unavailable: insufficient marks")
    price = _require_mark(action, kind="OPEN", pm_id=book["pm_id"])
    lock = locked_fields(instrument, asset, action.get("paper_expression"))
    action["locked_expression_family"] = lock["locked_expression_family"]
    position = {
        "position_id": action.get("position_id") or f"pm-{book['pm_id']}-{uuid4().hex[:12]}",
        "instrument": instrument,
        "asset_class": asset,
        "side": side,
        "notional_usd": notional,
        "entry_price": price,
        "mark_price": action.get("mark_price", price),
        "entry_price_source": action.get("paper_mid_source"),
        "entry_price_as_of": action.get("paper_mid_as_of"),
        "mark_price_source": action.get("paper_mid_source"),
        "mark_price_as_of": action.get("paper_mid_as_of"),
        "paper_expression": deepcopy(action.get("paper_expression") or lock["paper_expression"]),
        "locked_expression_family": lock["locked_expression_family"],
        "opened_at": isoformat(when),
        "opened_run_id": run_id,
        "thesis": action.get("thesis"),
        "invalidation": action.get("invalidation"),
        "hedge_of": action.get("hedge_of"),
        "unrealized_pnl_usd": None,
        "pnl_unavailable": False,
    }
    action["position_id"] = position["position_id"]
    preview = deepcopy(book)
    preview["positions"] = list(preview.get("positions") or []) + [position]
    assert_cap(preview)
    apply_basis_to_position(position)
    book["positions"].append(position)
    return position


def _resize(book: dict[str, Any], action: dict[str, Any], *, factor: int, run_id: str | None, when: datetime) -> None:
    position = _find_position(book, action.get("position_id") or "")
    delta = _require_notional(action)
    assert_family_locked(
        position,
        instrument=action.get("instrument") or position.get("instrument"),
        asset_class=action.get("asset_class") or position.get("asset_class"),
        expression=action.get("paper_expression"),
    )
    if factor < 0:
        if delta > float(position["notional_usd"]) + 1e-9:
            raise SchemaError("REDUCE exceeds position notional")
        exit_price = _require_mark(action, kind="REDUCE", pm_id=book["pm_id"])
        realized = realized_increment(position, exit_price=exit_price, closed_notional=delta)
        position["notional_usd"] = round(float(position["notional_usd"]) - delta, 2)
        book["realized_pnl_usd"] = round(float(book["realized_pnl_usd"]) + realized, 2)
        action["realized_pnl_usd"] = realized
        if position["notional_usd"] <= 1e-9:
            book["positions"] = [p for p in book["positions"] if p["position_id"] != position["position_id"]]
    else:
        add_price = _require_mark(action, kind="ADD", pm_id=book["pm_id"])
        old_n = float(position["notional_usd"])
        if position.get("entry_price") not in (None, ""):
            position["entry_price"] = (float(position["entry_price"]) * old_n + add_price * delta) / (old_n + delta)
            position["mark_price"] = action.get("mark_price", add_price)
            position["entry_price_source"] = "weighted_average_paper_mid"
            position["entry_price_as_of"] = action.get("paper_mid_as_of")
            position["mark_price_source"] = action.get("paper_mid_source")
            position["mark_price_as_of"] = action.get("paper_mid_as_of")
        preview = deepcopy(book)
        preview_pos = next(p for p in preview["positions"] if p["position_id"] == position["position_id"])
        preview_pos["notional_usd"] = round(old_n + delta, 2)
        assert_cap(preview)
        position["notional_usd"] = round(old_n + delta, 2)
    action["run_id"] = run_id
    action["at"] = isoformat(when)
    action["locked_expression_family"] = position.get("locked_expression_family")


def _close(book: dict[str, Any], action: dict[str, Any], *, run_id: str | None, when: datetime) -> None:
    position = _find_position(book, action.get("position_id") or "")
    action["notional_usd"] = position["notional_usd"]
    action["instrument"] = position["instrument"]
    action.setdefault("asset_class", position.get("asset_class"))
    _resize(book, action, factor=-1, run_id=run_id, when=when)


def _hedge(book: dict[str, Any], action: dict[str, Any], *, run_id: str | None, when: datetime) -> None:
    target_id = action.get("hedge_of") or action.get("position_id")
    if not target_id:
        raise SchemaError("HEDGE requires hedge_of or position_id of the existing risk")
    target = _find_position(book, target_id)
    assert_family_locked(
        target,
        instrument=action.get("instrument") or target.get("instrument"),
        asset_class=action.get("asset_class") or target.get("asset_class"),
        expression=action.get("paper_expression") or target.get("paper_expression"),
    )
    hedge = dict(action)
    hedge["action"] = "OPEN"
    hedge["hedge_of"] = target["position_id"]
    hedge.setdefault("instrument", target["instrument"])
    hedge.setdefault("asset_class", target["asset_class"])
    hedge.setdefault("paper_expression", target.get("paper_expression"))
    if "side" not in hedge:
        hedge["side"] = "short" if target["side"] == "long" else "long"
    _open_position(book, hedge, run_id=run_id, when=when)
    action["position_id"] = hedge.get("position_id")
    action["locked_expression_family"] = hedge.get("locked_expression_family")


def _normalize_actions(decision: dict[str, Any]) -> list[dict[str, Any]]:
    actions = deepcopy(decision.get("actions") or [])
    if not isinstance(actions, list):
        raise SchemaError("decision actions must be a list")
    if not actions:
        explicit = str(decision.get("decision") or decision.get("stance") or "").upper()
        if explicit in {"NO_TRADE", "NO-TRADE", "NOTRADE"}:
            actions = [{"action": "NO_TRADE"}]
        else:
            actions = [{"action": "HOLD"}]
    return actions


def prepare_actions(
    book: dict[str, Any],
    decision: dict[str, Any],
    *,
    market_state: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    actions = _normalize_actions(decision)
    for action in actions:
        kind = action.get("action")
        if kind in {"ADD", "REDUCE", "CLOSE", "HEDGE"} and action.get("paper_expression"):
            target_id = str(action.get("position_id") or action.get("hedge_of") or "")
            pos = find_position(list(book.get("positions") or []), target_id, owner=book["pm_id"])
            assert_family_locked(
                pos,
                instrument=action.get("instrument") or pos.get("instrument"),
                asset_class=action.get("asset_class") or pos.get("asset_class"),
                expression=action.get("paper_expression"),
            )
    if market_state is None:
        expanding = [row for row in actions if row.get("action") in MARK_REQUIRED_ACTIONS]
        if expanding:
            raise MarkError(f"{book['pm_id']} failed closed: market state is required to hydrate marks")
        return actions
    try:
        hydrate_action_mids(
            actions,
            market_state,
            positions=list(book.get("positions") or []),
            owner=book["pm_id"],
        )
    except PaperMarkError as exc:
        raise MarkError(f"{book['pm_id']} failed closed: {exc}") from exc
    return actions


def apply_decision(
    books: dict[str, Any],
    decision: dict[str, Any],
    *,
    pm_id: str,
    market_state: dict[str, Any] | None,
    run_id: str | None,
    evidence_cutoff: str | None,
    review_packet_id: str | None,
    review_packet_sha256: str | None,
    when: datetime | None = None,
) -> dict[str, Any]:
    if pm_id not in PM_IDS:
        raise SchemaError(f"unknown pm_id {pm_id}")
    if decision.get("pm_id") not in (None, pm_id):
        raise IndependenceError(f"decision pm_id {decision.get('pm_id')} does not match {pm_id}")
    out = deepcopy(books)
    if set(out.get("pms") or {}) != set(PM_IDS):
        raise SchemaError("PM books must contain exactly chatgpt, swinger, pragmatist, grinder")
    book = out["pms"][pm_id]
    if market_state is not None:
        refresh_pm_book(book, market_state)
    actions = prepare_actions(book, decision, market_state=market_state)
    stamp = now_ny(when)
    for action in actions:
        apply_action(
            book,
            action,
            run_id=run_id,
            when=stamp,
            decision=decision,
            market_state=market_state,
        )
    book["last_decision_at"] = isoformat(stamp)
    book["last_decision_packet_id"] = review_packet_id
    book["last_decision_packet_sha256"] = review_packet_sha256
    book["review_packet_id"] = review_packet_id
    book["review_packet_sha256"] = review_packet_sha256
    book["review_status"] = "fresh"
    book["evidence_cutoff"] = evidence_cutoff
    out["as_of"] = isoformat(stamp)
    if evidence_cutoff:
        out["evidence_cutoff"] = evidence_cutoff
    if run_id:
        if str(run_id).startswith("overnight-"):
            out["overnight_run_id"] = run_id
        else:
            out["trader_room_run_id"] = out.get("trader_room_run_id") or run_id
    mark_pm_book(book)
    return out


def mark_stale_if_packet_changed(books: dict[str, Any], current_packets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    out = deepcopy(books)
    for pm_id, book in out["pms"].items():
        packet = current_packets.get(pm_id) or {}
        book["review_packet_id"] = packet.get("review_packet_id")
        book["review_packet_sha256"] = packet.get("review_packet_sha256")
        if not book.get("last_decision_at"):
            book["review_status"] = "awaiting"
            book["decision_status"] = awaiting_status(pm_id)
            continue
        if book.get("evidence_cutoff") != packet.get("evidence_cutoff"):
            book["review_status"] = "stale"
        else:
            book["review_status"] = "fresh"
    return out


def validate_books(books: dict[str, Any]) -> dict[str, Any]:
    if books.get("schema_version") != SCHEMA_VERSION:
        raise SchemaError("PM books schema_version mismatch")
    if books.get("type") != "PM_BOOKS":
        raise SchemaError("PM books type mismatch")
    if set(books.get("pms") or {}) != set(PM_IDS):
        raise SchemaError("PM books must contain exactly four PMs")
    if books.get("gross_notional_limit_usd") != GROSS_NOTIONAL_LIMIT_USD:
        raise SchemaError(f"gross_notional_limit_usd must be {GROSS_NOTIONAL_LIMIT_USD}")
    for pm_id, book in books["pms"].items():
        if book.get("pm_id") != pm_id:
            raise SchemaError(f"pm key/name mismatch for {pm_id}")
        if book.get("gross_notional_limit_usd") != GROSS_NOTIONAL_LIMIT_USD:
            raise SchemaError(f"{pm_id} gross limit drifted")
        if book.get("decision_status") not in DECISION_STATUSES:
            raise SchemaError(f"{pm_id} has unknown decision_status")
        mark_pm_book(book)
    return books


def public_pm_view(books: dict[str, Any]) -> dict[str, Any]:
    validate_books(books)
    rows = []
    for pm_id in PM_IDS:
        item = books["pms"][pm_id]
        rows.append(
            {
                "pm_id": pm_id,
                "label": item["label"],
                "mandate": item["mandate"],
                "decision_status": item["decision_status"],
                "review_status": item["review_status"],
                "last_action": item.get("last_action"),
                "gross_notional_limit_usd": item["gross_notional_limit_usd"],
                "gross_utilization_usd": item["gross_utilization_usd"],
                "gross_remaining_usd": item["gross_remaining_usd"],
                "cash_capital_usd": item.get("cash_capital_usd", CASH_CAPITAL_USD),
                "funded_draw_usd": item.get("funded_draw_usd", 0.0),
                "unused_cash_usd": item.get("unused_cash_usd", item.get("cash_capital_usd", CASH_CAPITAL_USD)),
                "funding_cost_usd": item.get("funding_cost_usd", 0.0),
                "cash_yield_usd": item.get("cash_yield_usd", 0.0),
                "net_after_funding_pnl_usd": item.get("net_after_funding_pnl_usd"),
                "funding_rate_annual": item.get("funding_rate_annual"),
                "funding_convention": item.get("funding_convention", FUNDING_CONVENTION),
                "funding_source": item.get("funding_source", FUNDING_SOURCE),
                "funding_basis_status": item.get("funding_basis_status"),
                "unresolved_funding_positions": item.get("unresolved_funding_positions") or [],
                "realized_pnl_usd": item["realized_pnl_usd"],
                "unrealized_pnl_usd": item["unrealized_pnl_usd"],
                "total_pnl_usd": item["total_pnl_usd"],
                "pnl_unavailable": item["pnl_unavailable"],
                "conviction": item["conviction"],
                "thesis": item.get("thesis"),
                "invalidation": item.get("invalidation"),
                "alerts": item.get("alerts") or [],
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
                        "mark_price_source": p.get("mark_price_source"),
                        "locked_expression_family": p.get("locked_expression_family"),
                        "funding_basis": p.get("funding_basis"),
                        "funding_basis_status": p.get("funding_basis_status"),
                        "funding_draw_usd": p.get("funding_draw_usd"),
                        "unrealized_pnl_usd": p.get("unrealized_pnl_usd"),
                        "hedge_of": p.get("hedge_of"),
                    }
                    for p in item["positions"]
                ],
            }
        )
    comparison = [
        {
            "pm_id": row["pm_id"],
            "label": row["label"],
            "total_pnl_usd": row["total_pnl_usd"],
            "realized_pnl_usd": row["realized_pnl_usd"],
            "unrealized_pnl_usd": row["unrealized_pnl_usd"],
            "gross_utilization_usd": row["gross_utilization_usd"],
            "funded_draw_usd": row["funded_draw_usd"],
            "unused_cash_usd": row["unused_cash_usd"],
            "net_after_funding_pnl_usd": row["net_after_funding_pnl_usd"],
            "decision_status": row["decision_status"],
            "review_status": row["review_status"],
        }
        for row in rows
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "PM_PUBLIC_BOOKS",
        "as_of": books.get("as_of"),
        "overnight_run_id": books.get("overnight_run_id"),
        "trader_room_run_id": books.get("trader_room_run_id"),
        "evidence_cutoff": books.get("evidence_cutoff"),
        "gross_notional_limit_usd": GROSS_NOTIONAL_LIMIT_USD,
        "cash_capital_usd": CASH_CAPITAL_USD,
        "funding_convention": FUNDING_CONVENTION,
        "funding_source": FUNDING_SOURCE,
        "pm_count": len(rows),
        "pms": rows,
        "comparison": comparison,
    }
