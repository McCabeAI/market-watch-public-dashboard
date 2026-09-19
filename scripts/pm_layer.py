"""Four independent $1bn paper PM books above the 14-seat Trader Room."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from scripts.overnight.books import position_pnl, realized_increment
from scripts.overnight.clock import isoformat, now_ny
from scripts.overnight.errors import SchemaError
from scripts.overnight.paper_marks import PaperMarkError, resolve_paper_mid

SCHEMA_VERSION = 1
MAX_GROSS_NOTIONAL_USD = 1_000_000_000
PM_IDS = ("chatgpt-pm", "swinger-pm", "pragmatist-pm", "grinder-pm")
MODEL_PM_IDS = ("swinger-pm", "pragmatist-pm", "grinder-pm")
PM_BOOKS_RELPATH = Path("data/pm/books/latest.json")
PM_SPECS = {
    "chatgpt-pm": {
        "label": "ChatGPT PM",
        "objective": "Independent synthesis of all available evidence and trader arguments. No forced style and no requirement to trade.",
        "hedging_allowed": True,
    },
    "swinger-pm": {
        "label": "The Swinger",
        "objective": "Maximize expected absolute P&L. Prefer concentration and high risk utilization when conviction exists. Do not hedge; reduce or close if the thesis weakens.",
        "hedging_allowed": False,
    },
    "pragmatist-pm": {
        "label": "The Pragmatist",
        "objective": "Pursue home-run asymmetry when available while compounding singles and doubles through cleaner tactical, carry and relative-value opportunities.",
        "hedging_allowed": True,
    },
    "grinder-pm": {
        "label": "The Grinder",
        "objective": "Minimize drawdowns and negative days. Prefer small repeatable edges, quick profit realization and substantial unused capacity over large directional swings.",
        "hedging_allowed": True,
    },
}
ACTIONS = {"OPEN", "ADD", "HOLD", "REDUCE", "HEDGE", "CLOSE"}
ASSET_CLASSES = {"spot_fx", "rates", "curve", "rates_rv", "options"}
SIDES = {"long", "short"}


def _num(value: Any, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise SchemaError(f"{field} must be numeric") from exc
    if out != out:
        raise SchemaError(f"{field} may not be NaN")
    return out


def _position(book: Mapping[str, Any], position_id: str) -> dict[str, Any]:
    for row in book.get("positions") or []:
        if row.get("position_id") == position_id:
            return row
    raise SchemaError(f"unknown PM position_id {position_id}")


def _gross(book: Mapping[str, Any]) -> float:
    return round(sum(float(p.get("notional_usd") or 0.0) for p in book.get("positions") or []), 2)


def _recalc(book: dict[str, Any]) -> dict[str, Any]:
    unrealized = 0.0
    missing = False
    for pos in book.get("positions") or []:
        pnl = position_pnl(pos)
        pos["unrealized_pnl_usd"] = pnl["unrealized_pnl_usd"]
        pos["pnl_unavailable"] = pnl["pnl_unavailable"]
        if pnl["pnl_unavailable"]:
            missing = True
        else:
            unrealized += float(pnl["unrealized_pnl_usd"])
    book["gross_notional_usd"] = _gross(book)
    book["unrealized_pnl_usd"] = round(unrealized, 2)
    book["total_pnl_usd"] = None if missing else round(float(book.get("realized_pnl_usd") or 0.0) + unrealized, 2)
    book["pnl_unavailable"] = missing
    if book["gross_notional_usd"] > MAX_GROSS_NOTIONAL_USD + 1e-6:
        raise SchemaError(
            f"{book['pm_id']} gross notional {book['gross_notional_usd']:.2f} exceeds $1bn limit"
        )
    return book


def empty_pm(pm_id: str) -> dict[str, Any]:
    if pm_id not in PM_SPECS:
        raise SchemaError(f"unknown PM {pm_id}")
    spec = PM_SPECS[pm_id]
    return {
        "pm_id": pm_id,
        "label": spec["label"],
        "objective": spec["objective"],
        "hedging_allowed": spec["hedging_allowed"],
        "max_gross_notional_usd": MAX_GROSS_NOTIONAL_USD,
        "positions": [],
        "history": [],
        "realized_pnl_usd": 0.0,
        "unrealized_pnl_usd": 0.0,
        "total_pnl_usd": 0.0,
        "gross_notional_usd": 0.0,
        "pnl_unavailable": False,
        "conviction": 0,
        "thesis": None,
        "invalidation": None,
        "last_action": "HOLD",
        "evidence_cutoff": None,
        "last_review_id": None,
        "alerts": [],
    }


def empty_pm_books(*, when: datetime | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "PM_BOOKS",
        "as_of": isoformat(now_ny(when)),
        "max_gross_notional_usd_per_pm": MAX_GROSS_NOTIONAL_USD,
        "review_status": "missing",
        "last_successful_review_id": None,
        "pms": {pm_id: empty_pm(pm_id) for pm_id in PM_IDS},
    }


def validate_pm_books(books: dict[str, Any]) -> dict[str, Any]:
    if books.get("schema_version") != SCHEMA_VERSION or books.get("type") != "PM_BOOKS":
        raise SchemaError("PM books schema/type mismatch")
    if set(books.get("pms") or {}) != set(PM_IDS):
        raise SchemaError("PM books must contain exactly the four PMs")
    if books.get("max_gross_notional_usd_per_pm") != MAX_GROSS_NOTIONAL_USD:
        raise SchemaError("PM gross-notional limit drifted")
    for pm_id in PM_IDS:
        book = books["pms"][pm_id]
        if book.get("pm_id") != pm_id:
            raise SchemaError(f"PM id mismatch for {pm_id}")
        spec = PM_SPECS[pm_id]
        if book.get("label") != spec["label"] or book.get("objective") != spec["objective"]:
            raise SchemaError(f"PM mandate drifted for {pm_id}")
        if bool(book.get("hedging_allowed")) != bool(spec["hedging_allowed"]):
            raise SchemaError(f"PM hedge rule drifted for {pm_id}")
        _recalc(book)
    return books


def refresh_pm_marks(books: dict[str, Any], market_state: Mapping[str, Any]) -> dict[str, Any]:
    for pm_id in PM_IDS:
        book = books["pms"][pm_id]
        for pos in book.get("positions") or []:
            try:
                mark = resolve_paper_mid(
                    market_state,
                    str(pos.get("instrument") or ""),
                    asset_class=pos.get("asset_class"),
                    expression=pos.get("paper_expression"),
                )
            except PaperMarkError as exc:
                pos["mark_price"] = None
                pos["mark_price_source"] = None
                pos["mark_price_as_of"] = None
                book.setdefault("alerts", []).append(
                    f"Paper mark unavailable for {pos.get('instrument')}: {exc}"
                )
                continue
            pos["mark_price"] = mark["value"]
            pos["mark_price_source"] = mark["source"]
            pos["mark_price_as_of"] = mark.get("as_of")
        _recalc(book)
    return books


def _mid(
    market_state: Mapping[str, Any],
    *,
    instrument: str,
    asset_class: str,
    expression: Mapping[str, Any] | None,
) -> dict[str, Any]:
    try:
        return resolve_paper_mid(
            market_state,
            instrument,
            asset_class=asset_class,
            expression=expression,
        )
    except PaperMarkError as exc:
        raise SchemaError(f"cannot paper-execute {instrument}: {exc}") from exc


def _history(book: dict[str, Any], action: str, review_id: str, when: datetime, **extra: Any) -> None:
    book["history"].append(
        {
            "at": isoformat(when),
            "review_id": review_id,
            "action": action,
            **extra,
        }
    )


def apply_pm_decision(
    books: dict[str, Any],
    *,
    pm_id: str,
    decision: Mapping[str, Any],
    market_state: Mapping[str, Any],
    review_id: str,
    evidence_cutoff: str,
    when: datetime | None = None,
) -> dict[str, Any]:
    validate_pm_books(books)
    if pm_id not in PM_IDS:
        raise SchemaError(f"unknown PM {pm_id}")
    if decision.get("pm_id") not in (None, pm_id):
        raise SchemaError(f"PM decision id mismatch for {pm_id}")
    stamp = now_ny(when)
    out = deepcopy(books)
    refresh_pm_marks(out, market_state)
    book = out["pms"][pm_id]
    actions = list(decision.get("actions") or [{"action": "HOLD"}])
    if not actions:
        actions = [{"action": "HOLD"}]

    for raw in actions:
        action = dict(raw)
        kind = str(action.get("action") or "").upper()
        if kind not in ACTIONS:
            raise SchemaError(f"{pm_id} invalid action {kind}")
        if kind == "HEDGE" and not PM_SPECS[pm_id]["hedging_allowed"]:
            raise SchemaError("The Swinger may not HEDGE; REDUCE or CLOSE instead")

        if kind == "HOLD":
            _history(book, kind, review_id, stamp, result="applied")
        elif kind == "OPEN":
            instrument = str(action.get("instrument") or "")
            side = str(action.get("side") or "")
            asset_class = str(action.get("asset_class") or "")
            notional = _num(action.get("notional_usd"), "notional_usd")
            if not instrument or side not in SIDES or asset_class not in ASSET_CLASSES or notional <= 0:
                raise SchemaError("PM OPEN requires instrument, side, asset_class and positive notional_usd")
            expression = deepcopy(action.get("paper_expression"))
            mark = _mid(
                market_state,
                instrument=instrument,
                asset_class=asset_class,
                expression=expression,
            )
            pos = {
                "position_id": str(action.get("position_id") or f"pmpos-{uuid4().hex[:12]}"),
                "instrument": instrument,
                "asset_class": asset_class,
                "side": side,
                "notional_usd": notional,
                "entry_price": mark["value"],
                "mark_price": mark["value"],
                "entry_price_source": mark["source"],
                "entry_price_as_of": mark.get("as_of"),
                "mark_price_source": mark["source"],
                "mark_price_as_of": mark.get("as_of"),
                "paper_expression": expression,
                "opened_at": isoformat(stamp),
                "opened_review_id": review_id,
                "thesis": action.get("thesis") or decision.get("thesis"),
                "invalidation": action.get("invalidation") or decision.get("invalidation"),
                "hedge_of": action.get("hedge_of"),
                "unrealized_pnl_usd": 0.0,
                "pnl_unavailable": False,
            }
            book["positions"].append(pos)
            _recalc(book)
            _history(
                book,
                kind,
                review_id,
                stamp,
                result="applied",
                position_id=pos["position_id"],
                instrument=instrument,
                notional_usd=notional,
                price=mark["value"],
                paper_mid_source=mark["source"],
                paper_mid_as_of=mark.get("as_of"),
            )
        elif kind in {"ADD", "REDUCE", "CLOSE"}:
            pos = _position(book, str(action.get("position_id") or ""))
            # Curve/expression family is locked at OPEN.
            mark = _mid(
                market_state,
                instrument=str(pos["instrument"]),
                asset_class=str(pos["asset_class"]),
                expression=pos.get("paper_expression"),
            )
            old_notional = float(pos["notional_usd"])
            delta = old_notional if kind == "CLOSE" else _num(action.get("notional_usd"), "notional_usd")
            if delta <= 0:
                raise SchemaError(f"{kind} requires positive notional_usd")
            if kind in {"REDUCE", "CLOSE"} and delta > old_notional + 1e-9:
                raise SchemaError(f"{kind} exceeds position notional")
            if kind == "ADD":
                new_notional = old_notional + delta
                pos["entry_price"] = (
                    float(pos["entry_price"]) * old_notional + float(mark["value"]) * delta
                ) / new_notional
                pos["notional_usd"] = round(new_notional, 2)
                pos["entry_price_source"] = "weighted_average_paper_mid"
                pos["entry_price_as_of"] = mark.get("as_of")
                pos["mark_price"] = mark["value"]
                pos["mark_price_source"] = mark["source"]
                pos["mark_price_as_of"] = mark.get("as_of")
                realized = 0.0
            else:
                realized = realized_increment(
                    pos,
                    exit_price=float(mark["value"]),
                    closed_notional=delta,
                )
                book["realized_pnl_usd"] = round(
                    float(book.get("realized_pnl_usd") or 0.0) + realized, 2
                )
                pos["notional_usd"] = round(old_notional - delta, 2)
                if pos["notional_usd"] <= 1e-9:
                    book["positions"] = [
                        p for p in book["positions"] if p["position_id"] != pos["position_id"]
                    ]
            _recalc(book)
            _history(
                book,
                kind,
                review_id,
                stamp,
                result="applied",
                position_id=pos["position_id"],
                instrument=pos["instrument"],
                notional_usd=delta,
                price=mark["value"],
                realized_pnl_usd=realized,
                paper_mid_source=mark["source"],
                paper_mid_as_of=mark.get("as_of"),
            )
        elif kind == "HEDGE":
            target = _position(book, str(action.get("hedge_of") or action.get("position_id") or ""))
            hedge = {
                **action,
                "action": "OPEN",
                "instrument": action.get("instrument") or target["instrument"],
                "asset_class": action.get("asset_class") or target["asset_class"],
                "side": action.get("side") or ("short" if target["side"] == "long" else "long"),
                "paper_expression": (
                    deepcopy(action["paper_expression"])
                    if action.get("paper_expression") is not None
                    else deepcopy(target.get("paper_expression"))
                ),
                "hedge_of": target["position_id"],
            }
            nested = {"pm_id": pm_id, "actions": [hedge]}
            out = apply_pm_decision(
                out,
                pm_id=pm_id,
                decision=nested,
                market_state=market_state,
                review_id=review_id,
                evidence_cutoff=evidence_cutoff,
                when=stamp,
            )
            book = out["pms"][pm_id]
            _history(
                book,
                "HEDGE",
                review_id,
                stamp,
                result="applied",
                hedge_of=target["position_id"],
                instrument=hedge["instrument"],
                notional_usd=hedge.get("notional_usd"),
            )

        if _gross(book) > MAX_GROSS_NOTIONAL_USD + 1e-6:
            raise SchemaError(f"{pm_id} would exceed the $1bn gross-notional ceiling")

    if decision.get("conviction") is not None:
        conviction = int(decision["conviction"])
        if not 0 <= conviction <= 100:
            raise SchemaError("PM conviction must be 0-100")
        book["conviction"] = conviction
    if "thesis" in decision:
        book["thesis"] = decision.get("thesis")
    if "invalidation" in decision:
        book["invalidation"] = decision.get("invalidation")
    book["last_action"] = str(actions[-1].get("action") or "HOLD").upper()
    book["evidence_cutoff"] = evidence_cutoff
    book["last_review_id"] = review_id
    if decision.get("alerts"):
        book["alerts"].extend([str(x) for x in decision.get("alerts") or []])
    _recalc(book)
    out["as_of"] = isoformat(stamp)
    out["last_successful_review_id"] = review_id
    out["review_status"] = "fresh"
    return out


def apply_pm_decisions(
    books: dict[str, Any],
    *,
    decisions: Mapping[str, Any],
    market_state: Mapping[str, Any],
    review_id: str,
    evidence_cutoff: str,
    when: datetime | None = None,
    require_all: bool = True,
) -> dict[str, Any]:
    if require_all and set(decisions) != set(PM_IDS):
        raise SchemaError(f"PM review must contain all four PMs; got {sorted(decisions)}")
    out = deepcopy(books)
    for pm_id in PM_IDS:
        if pm_id not in decisions:
            continue
        out = apply_pm_decision(
            out,
            pm_id=pm_id,
            decision=decisions[pm_id],
            market_state=market_state,
            review_id=review_id,
            evidence_cutoff=evidence_cutoff,
            when=when,
        )
    return validate_pm_books(out)


def public_pm_view(books: dict[str, Any]) -> dict[str, Any]:
    validate_pm_books(books)
    rows = []
    for pm_id in PM_IDS:
        book = books["pms"][pm_id]
        rows.append(
            {
                "pm_id": pm_id,
                "label": book["label"],
                "objective": book["objective"],
                "hedging_allowed": book["hedging_allowed"],
                "max_gross_notional_usd": MAX_GROSS_NOTIONAL_USD,
                "gross_notional_usd": book["gross_notional_usd"],
                "utilization_pct": round(100.0 * book["gross_notional_usd"] / MAX_GROSS_NOTIONAL_USD, 2),
                "realized_pnl_usd": book["realized_pnl_usd"],
                "unrealized_pnl_usd": book["unrealized_pnl_usd"],
                "total_pnl_usd": book["total_pnl_usd"],
                "pnl_unavailable": book["pnl_unavailable"],
                "conviction": book["conviction"],
                "thesis": book.get("thesis"),
                "invalidation": book.get("invalidation"),
                "last_action": book.get("last_action"),
                "last_review_id": book.get("last_review_id"),
                "evidence_cutoff": book.get("evidence_cutoff"),
                "alerts": book.get("alerts") or [],
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
                        "unrealized_pnl_usd": p.get("unrealized_pnl_usd"),
                        "hedge_of": p.get("hedge_of"),
                    }
                    for p in book.get("positions") or []
                ],
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "PM_BOOKS_PUBLIC",
        "as_of": books.get("as_of"),
        "review_status": books.get("review_status"),
        "last_successful_review_id": books.get("last_successful_review_id"),
        "max_gross_notional_usd_per_pm": MAX_GROSS_NOTIONAL_USD,
        "pm_count": len(rows),
        "pms": rows,
    }
