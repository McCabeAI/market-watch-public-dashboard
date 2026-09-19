#!/usr/bin/env python3
"""Apply final Trader Room paper-capital decisions through the book engine."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.overnight.books import apply_review, validate_books
from scripts.overnight.clock import now_ny
from scripts.overnight.constants import STANDING_SEATS, STARTING_NAV_USD
from scripts.overnight.expression import expression_rule
from scripts.overnight.store import OvernightStore, write_json
from scripts.trader_room.constants import ADVOCATE_REMITS, ROOT, STANDING_ADVOCATES


def _lookup_mark(packet: dict[str, Any], instrument: str, asset_class: str | None) -> dict[str, Any] | None:
    marks = packet.get("executable_marks") or {}
    families = []
    if asset_class == "spot_fx":
        families = ["spot_fx"]
    elif asset_class in {"rates", "curve"}:
        families = ["rates"]
    elif asset_class == "rates_rv":
        families = ["rates_rv"]
    else:
        families = ["spot_fx", "rates", "rates_rv"]
    for family in families:
        row = (marks.get(family) or {}).get(instrument)
        if row:
            return {"family": family, **row}
    return None


def validate_paper_capital(item: dict[str, Any], *, packet: dict[str, Any], seat: str) -> dict[str, Any]:
    paper = item.get("paper_capital")
    if not isinstance(paper, dict):
        return {
            "seat": seat,
            "risk_put_on": False,
            "action": "HOLD",
            "notional_usd": None,
            "execution_blocked": "paper_capital object missing from seat output",
            "source": "validator_default_hold",
        }
    blocked = paper.get("execution_blocked")
    if blocked:
        return {
            "seat": seat,
            "risk_put_on": False,
            "action": "HOLD",
            "notional_usd": None,
            "execution_blocked": str(blocked),
            "funding_hurdle_rationale": paper.get("funding_hurdle_rationale"),
            "source": "seat_execution_blocked",
        }
    risk = paper.get("risk_put_on")
    if risk is False:
        return {
            "seat": seat,
            "risk_put_on": False,
            "action": "HOLD",
            "notional_usd": None,
            "execution_blocked": None,
            "funding_hurdle_rationale": paper.get("funding_hurdle_rationale"),
            "source": "seat_hold",
        }
    if risk is not True:
        return {
            "seat": seat,
            "risk_put_on": False,
            "action": "HOLD",
            "notional_usd": None,
            "execution_blocked": f"risk_put_on must be true or false, got {risk!r}",
            "source": "validator_default_hold",
        }

    action = paper.get("action")
    if action != "OPEN":
        return {
            "seat": seat,
            "risk_put_on": False,
            "action": "HOLD",
            "notional_usd": None,
            "execution_blocked": f"risk_put_on true requires OPEN, got {action!r}",
            "source": "validator_default_hold",
        }
    try:
        notional = float(paper.get("notional_usd"))
    except (TypeError, ValueError):
        return {
            "seat": seat,
            "risk_put_on": False,
            "action": "HOLD",
            "notional_usd": None,
            "execution_blocked": "notional_usd missing or non-numeric",
            "source": "validator_default_hold",
        }
    if not 1 <= notional <= STARTING_NAV_USD:
        return {
            "seat": seat,
            "risk_put_on": False,
            "action": "HOLD",
            "notional_usd": None,
            "execution_blocked": f"notional_usd {notional} outside 1..{STARTING_NAV_USD}",
            "source": "validator_default_hold",
        }
    instrument = paper.get("instrument")
    side = paper.get("side")
    asset_class = paper.get("asset_class")
    if side not in {"long", "short"}:
        return {
            "seat": seat,
            "risk_put_on": False,
            "action": "HOLD",
            "notional_usd": None,
            "execution_blocked": f"side must be long|short, got {side!r}",
            "source": "validator_default_hold",
        }
    mark = _lookup_mark(packet, str(instrument), str(asset_class) if asset_class else None)
    if mark is None:
        return {
            "seat": seat,
            "risk_put_on": False,
            "action": "HOLD",
            "notional_usd": None,
            "execution_blocked": (
                f"instrument {instrument!r} asset_class {asset_class!r} cannot be represented "
                "and marked safely from frozen market_state executable_marks"
            ),
            "source": "validator_default_hold",
        }
    price = paper.get("price", paper.get("mark_price"))
    try:
        price_f = float(price)
        mark_f = float(mark["price"])
    except (TypeError, ValueError):
        return {
            "seat": seat,
            "risk_put_on": False,
            "action": "HOLD",
            "notional_usd": None,
            "execution_blocked": "paper price is not numeric",
            "source": "validator_default_hold",
        }
    if abs(price_f - mark_f) > 1e-9:
        return {
            "seat": seat,
            "risk_put_on": False,
            "action": "HOLD",
            "notional_usd": None,
            "execution_blocked": (
                f"paper price {price_f} does not match frozen market_state mark {mark_f} "
                f"at {mark['path']}"
            ),
            "source": "validator_default_hold",
        }
    return {
        "seat": seat,
        "risk_put_on": True,
        "action": "OPEN",
        "notional_usd": notional,
        "instrument": instrument,
        "side": side,
        "asset_class": asset_class or mark["family"],
        "price": mark_f,
        "mark_price": mark_f,
        "price_path": mark["path"],
        "execution_blocked": None,
        "funding_hurdle_rationale": paper.get("funding_hurdle_rationale"),
        "source": "seat_open",
    }


def _memo_from_item(item: dict[str, Any], seat: str, decision: dict[str, Any]) -> dict[str, Any]:
    trade = item.get("trade") or {}
    comparison = trade.get("expression_comparison") or {}
    if decision["action"] == "HOLD":
        if expression_rule(seat) == "spot_only":
            return {
                "rates_candidate": None,
                "spot_candidate": None,
                "options_candidate": None,
                "selected": "none",
                "rationale": decision.get("execution_blocked") or "Seat elected HOLD; no incremental spot risk.",
            }
        return {
            "rates_candidate": None,
            "spot_candidate": None,
            "options_candidate": None,
            "selected": "none",
            "rationale": decision.get("execution_blocked") or "Seat elected HOLD; no incremental rates or spot risk.",
        }
    selected = comparison.get("selected") or (
        "spot" if decision["asset_class"] == "spot_fx" else "rates"
    )
    rates_text = comparison.get("rates_candidate")
    spot_text = comparison.get("spot_candidate")
    rates_candidate = None
    if isinstance(rates_text, str) and rates_text.strip():
        rates_candidate = {
            "instrument": str(trade.get("instrument") or decision["instrument"]),
            "asset_class": decision["asset_class"] if decision["asset_class"] != "spot_fx" else "rates",
            "rationale": rates_text,
        }
    spot_candidate = None
    if isinstance(spot_text, str) and spot_text.strip():
        spot_candidate = {
            "instrument": str(trade.get("instrument") or decision["instrument"]),
            "asset_class": "spot_fx",
            "rationale": spot_text,
        }
    if expression_rule(seat) == "spot_only":
        return {
            "rates_candidate": None,
            "spot_candidate": {
                "instrument": decision["instrument"],
                "asset_class": "spot_fx",
                "rationale": spot_text or "Dedicated spot seat OPEN from frozen marks.",
            },
            "options_candidate": None,
            "selected": "spot",
            "rationale": comparison.get("rationale") or "Dedicated spot seat OPEN.",
        }
    if selected == "spot":
        return {
            "rates_candidate": rates_candidate,
            "spot_candidate": {
                "instrument": decision["instrument"],
                "asset_class": "spot_fx",
                "rationale": spot_text or "Spot selected from frozen packet.",
            },
            "options_candidate": None,
            "selected": "spot",
            "rationale": comparison.get("rationale") or "Spot selected after rates-first comparison.",
        }
    return {
        "rates_candidate": {
            "instrument": decision["instrument"],
            "asset_class": decision["asset_class"],
            "rationale": rates_text or "Rates expression selected from frozen packet.",
        },
        "spot_candidate": spot_candidate,
        "options_candidate": None,
        "selected": "rates",
        "rationale": comparison.get("rationale") or "Rates selected after rates-first comparison.",
    }


def families_from_packet(packet: dict[str, Any]) -> dict[str, Any]:
    market = packet.get("market_state") or {}
    # A newly generated snapshot is an obtained market-state family even when
    # an official source inside it is stale/unavailable (commonly NZ yields).
    market_status = "fresh"
    if market.get("status") in {"unavailable", "missing"} or not market:
        market_status = "unavailable"
    news = packet.get("news_and_research") or []
    cb = packet.get("central_bank_research") or []
    gauges = packet.get("temperature_gauges") or []
    return {
        "macro_hard": {
            "status": "fresh" if gauges else "missing",
            "as_of": packet.get("as_of"),
            "notes": [],
        },
        "news": {
            "status": "fresh" if (news or cb) else "missing",
            "as_of": packet.get("as_of"),
            "notes": [],
        },
        "central_bank_research": {
            "status": "fresh" if cb else "missing",
            "as_of": packet.get("as_of"),
            "notes": [],
        },
        "market_state": {
            "status": market_status,
            "as_of": market.get("generated_at") or packet.get("as_of"),
            "notes": list(market.get("stale_sources") or []) + list(market.get("unavailable_sources") or []),
        },
    }


def final_items(run_dir: Path) -> dict[str, dict[str, Any]]:
    originals: dict[str, dict[str, Any]] = {}
    for seat in STANDING_ADVOCATES:
        originals[seat] = json.loads((run_dir / "submissions" / f"{seat}.json").read_text(encoding="utf-8"))
    rebuttal_dir = run_dir / "rebuttals"
    if rebuttal_dir.is_dir():
        for path in rebuttal_dir.glob("*.json"):
            seat = path.stem
            item = json.loads(path.read_text(encoding="utf-8"))
            change = item.get("trade_change")
            if change == "withdrawn":
                originals[seat] = dict(originals[seat])
                originals[seat]["trade"] = None
                if isinstance(item.get("paper_capital"), dict):
                    originals[seat]["paper_capital"] = item["paper_capital"]
                else:
                    originals[seat]["paper_capital"] = {
                        "risk_put_on": False,
                        "action": "HOLD",
                        "notional_usd": None,
                        "execution_blocked": "trade withdrawn in rebuttal",
                    }
            elif change == "amended":
                originals[seat] = dict(originals[seat])
                if item.get("revised_trade") is not None:
                    originals[seat]["trade"] = item["revised_trade"]
                if isinstance(item.get("paper_capital"), dict):
                    originals[seat]["paper_capital"] = item["paper_capital"]
    return originals


def build_reviews(finals: dict[str, dict[str, Any]], packet: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    reviews: dict[str, Any] = {}
    decisions: dict[str, Any] = {}
    for seat in STANDING_SEATS:
        item = finals[seat]
        decision = validate_paper_capital(item, packet=packet, seat=seat)
        decisions[seat] = decision
        trade = item.get("trade") or {}
        memo = _memo_from_item(item, seat, decision)
        review: dict[str, Any] = {
            "seat": seat,
            "conviction": item.get("confidence", trade.get("confidence", 0)),
            "thesis": trade.get("thesis") or item.get("stance_summary"),
            "invalidation": trade.get("invalidation"),
            "required_pitch": trade or None,
            "risk_put_on": (
                {
                    "instrument": decision.get("instrument"),
                    "notional_usd": decision.get("notional_usd"),
                    "note": decision.get("funding_hurdle_rationale"),
                }
                if decision["risk_put_on"]
                else None
            ),
            "expression_memo": memo,
            "alerts": [decision["execution_blocked"]] if decision.get("execution_blocked") else [],
            "actions": [],
        }
        if decision["action"] == "OPEN":
            review["actions"] = [
                {
                    "action": "OPEN",
                    "instrument": decision["instrument"],
                    "side": decision["side"],
                    "notional_usd": decision["notional_usd"],
                    "price": decision["price"],
                    "mark_price": decision["mark_price"],
                    "asset_class": decision["asset_class"],
                    "expression_memo": memo,
                    "note": decision.get("price_path"),
                }
            ]
        else:
            review["actions"] = [{"action": "HOLD", "expression_memo": memo}]
        reviews[seat] = review
    return reviews, decisions


def apply_run(*, run_dir: Path, root: Path = ROOT, when: datetime | None = None) -> dict[str, Any]:
    packet = json.loads((run_dir / "evidence_packet.json").read_text(encoding="utf-8"))
    finals = final_items(run_dir)
    reviews, decisions = build_reviews(finals, packet)
    store = OvernightStore(root=root)
    books = validate_books(store.read_books())
    families = families_from_packet(packet)
    stamp = now_ny(when)
    updated = apply_review(
        books,
        reviews,
        families=families,
        run_id=packet["run_id"],
        evidence_cutoff=packet["as_of"],
        when=stamp,
    )
    updated["review_status"] = "fresh"
    updated["last_successful_review_run_id"] = packet["run_id"]
    updated["overnight_run_id"] = packet["run_id"]
    store.write_books(updated)
    write_json(run_dir / "paper_capital_decisions.json", decisions)
    write_json(run_dir / "paper_reviews.json", reviews)
    write_json(run_dir / "books_after.json", updated)
    return {
        "run_id": packet["run_id"],
        "books_path": "data/overnight/books/latest.json",
        "risk_put_on": sorted(seat for seat, row in decisions.items() if row["risk_put_on"]),
        "holds": sorted(seat for seat, row in decisions.items() if not row["risk_put_on"]),
        "execution_blocked": {
            seat: row["execution_blocked"]
            for seat, row in decisions.items()
            if row.get("execution_blocked")
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True, type=Path)
    ap.add_argument("--root", type=Path, default=ROOT)
    args = ap.parse_args()
    result = apply_run(run_dir=args.run_dir, root=args.root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
