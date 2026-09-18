"""Persistent $100m paper books for the locked 14-seat roster."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

from scripts.overnight.clock import isoformat, now_ny
from scripts.overnight.constants import (
    ACTIONS,
    ASSET_CLASSES,
    EXPANDING_ACTIONS,
    SCHEMA_VERSION,
    SIDES,
    STANDING_SEATS,
    STARTING_NAV_USD,
)
from scripts.overnight.errors import FreshnessError, SchemaError
from scripts.overnight.expression import expression_rule, remit, selected_asset_class, validate_expression_memo
from scripts.overnight.freshness import assert_action_allowed


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
        # Simplified paper P&L: 1.00 yield point on 100 notional ≈ 1.00 notional,
        # inverted because higher yield lowers the long-duration mark.
        raw = -sign * (mark_px - entry_px) / 100.0 * notional
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
        return round(-sign * (exit_price - entry_px) / 100.0 * closed_notional, 2)
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


def mark_to_market(seat_book: dict[str, Any]) -> dict[str, Any]:
    unrealized = 0.0
    missing = False
    for position in seat_book["positions"]:
        pnl = position_pnl(position)
        position["unrealized_pnl_usd"] = pnl["unrealized_pnl_usd"]
        position["pnl_unavailable"] = pnl["pnl_unavailable"]
        if pnl["pnl_unavailable"]:
            missing = True
        else:
            unrealized += float(pnl["unrealized_pnl_usd"])
    seat_book["unrealized_pnl_usd"] = round(unrealized, 2)
    seat_book["pnl_unavailable"] = missing
    seat_book["nav_usd"] = round(
        float(seat_book["starting_nav_usd"]) + float(seat_book["realized_pnl_usd"]) + unrealized,
        2,
    )
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
    }
    if extra:
        row.update(extra)
    return row


def apply_action(
    seat_book: dict[str, Any],
    action: dict[str, Any],
    *,
    families: dict[str, Any],
    run_id: str,
    when: datetime | None = None,
) -> dict[str, Any]:
    stamp = now_ny(when)
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
            return mark_to_market(seat_book)
        raise

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
    return mark_to_market(seat_book)


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
        "opened_at": isoformat(when),
        "opened_run_id": run_id,
        "thesis": action.get("thesis"),
        "invalidation": action.get("invalidation"),
        "hedge_of": action.get("hedge_of"),
        "unrealized_pnl_usd": None,
        "pnl_unavailable": action.get("price") in (None, ""),
    }
    seat_book["positions"].append(position)
    seat_book["cash_usd"] = round(float(seat_book["cash_usd"]) - notional, 2)
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
        seat_book["cash_usd"] = round(float(seat_book["cash_usd"]) + delta + realized, 2)
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
        position["notional_usd"] = round(old_n + delta, 2)
        seat_book["cash_usd"] = round(float(seat_book["cash_usd"]) - delta, 2)
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
) -> dict[str, Any]:
    if set(reviews) != set(STANDING_SEATS):
        raise SchemaError(f"review must include every standing seat; missing/extra {set(reviews) ^ set(STANDING_SEATS)}")
    out = deepcopy(books)
    out["overnight_run_id"] = run_id
    out["evidence_cutoff"] = evidence_cutoff
    out["as_of"] = isoformat(now_ny(when))
    for seat in STANDING_SEATS:
        payload = reviews[seat]
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
            apply_action(seat_book, action, families=families, run_id=run_id, when=when)
        if payload.get("alerts"):
            seat_book["alerts"].extend(list(payload["alerts"]))
        mark_to_market(seat_book)
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
                "pnl_unavailable": item["pnl_unavailable"],
                "conviction": item["conviction"],
                "thesis": item.get("thesis"),
                "invalidation": item.get("invalidation"),
                "last_action": item.get("last_action"),
                "prior_action": item.get("prior_action"),
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
                        "unrealized_pnl_usd": p.get("unrealized_pnl_usd"),
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
    return {
        "schema_version": SCHEMA_VERSION,
        "overnight_run_id": books.get("overnight_run_id"),
        "as_of": books.get("as_of"),
        "evidence_cutoff": books.get("evidence_cutoff"),
        "review_status": books.get("review_status"),
        "last_successful_review_run_id": books.get("last_successful_review_run_id"),
        "starting_nav_usd": STARTING_NAV_USD,
        "seat_count": len(seats),
        "seats": seats,
        "overnight_changes": changes,
    }
