"""Whole-lot open, add, reduce, and close accounting.

Descriptive notional is the requested face. Executable quantity is an integer
lot count. A request that closes or adds less than one lot is not a fill.
A partial reduce keeps ``floor(old_lots * remaining_notional / old_notional)``
and realizes P&L only on the lots actually removed. Hedge legs each use that
rule, so their closed counts need not share one fraction.
"""

from __future__ import annotations

from typing import Any, Mapping

from scripts.rates.contract_economics import (
    current_fx_quote,
    dv01_per_contract,
    parse_contract_id,
    whole_lots,
)
from scripts.rates.structures import leg_pnl_for_contracts, recompute_leg_dv01

SUB_LOT_POLICY = "sub_lot_request_is_not_a_fill"
REMAINING_POLICY = "floor_remaining_lots"


def split_lots(old_lots: int, old_notional: float, new_notional: float) -> tuple[int, int, bool]:
    """Return (remaining_lots, closed_lots, zero_lot)."""
    old_lots = int(old_lots)
    if old_lots < 0:
        old_lots = 0
    if new_notional <= 1e-9 or old_notional <= 1e-9:
        return 0, old_lots, False
    if new_notional >= old_notional - 1e-9:
        return old_lots, 0, False
    closed_raw = old_lots * (old_notional - new_notional) / old_notional
    if closed_raw < 1.0:
        return old_lots, 0, True
    remaining = min(old_lots, whole_lots(old_lots * new_notional / old_notional))
    return remaining, old_lots - remaining, False


def added_lots_from_face(added_notional: float, *, face_usd_per_lot: float) -> tuple[int, float, bool]:
    """Floor the descriptive add to whole lots. Below one lot is not a fill."""
    if face_usd_per_lot <= 0 or added_notional <= 0:
        return 0, 0.0, True
    raw = added_notional / face_usd_per_lot
    lots = whole_lots(raw)
    return lots, raw, lots < 1


def outright_face_usd(position: Mapping[str, Any], fx_usd_per_unit: float) -> float | None:
    parsed = parse_contract_id(position.get("instrument") if isinstance(position.get("instrument"), str) else None)
    if parsed is None or fx_usd_per_unit <= 0:
        return None
    return parsed.spec.face_notional * fx_usd_per_unit


def _current_fx_rate(position: Mapping[str, Any], market_state: Mapping[str, Any] | None) -> float | None:
    parsed = parse_contract_id(position.get("instrument") if isinstance(position.get("instrument"), str) else None)
    currency = position.get("contract_currency") or (parsed.spec.currency if parsed else None)
    if currency in (None, "USD"):
        return 1.0
    if market_state is not None:
        quote = current_fx_quote(str(currency), market_state)
        if quote.get("status") == "ok" and quote.get("usd_per_unit") is not None:
            return float(quote["usd_per_unit"])
        return None
    if position.get("mark_fx_status") in (None, "ok") and position.get("mark_fx_usd_per_unit") not in (None, ""):
        return float(position["mark_fx_usd_per_unit"])
    return None


def contract_pnl_for_lots(position: Mapping[str, Any], lots: int, *, mark: float | None = None) -> float | None:
    parsed = parse_contract_id(position.get("instrument") if isinstance(position.get("instrument"), str) else None)
    if parsed is None:
        return None
    if lots < 0:
        return None
    if lots == 0:
        return 0.0
    entry = position.get("entry_price")
    px = position.get("mark_price") if mark is None else mark
    if entry in (None, "") or px in (None, ""):
        return None
    if parsed.spec.currency == "USD":
        fx = 1.0
    else:
        if position.get("mark_fx_status") not in (None, "ok") or position.get("mark_fx_usd_per_unit") in (None, ""):
            return None
        fx = float(position["mark_fx_usd_per_unit"])
    local = dv01_per_contract(parsed.spec, year=parsed.year, month=parsed.month)
    if local is None:
        return None
    bp = (float(px) - float(entry)) * parsed.spec.bp_per_price_unit
    sign = 1.0 if position.get("side") == "long" else -1.0
    return -sign * int(lots) * local * bp * fx


def structure_pnl_for_closed_lots(legs: list[Mapping[str, Any]], closed_by_role: Mapping[str, int]) -> float | None:
    total = 0.0
    for leg in legs:
        role = str(leg.get("role") or "")
        closed = int(closed_by_role.get(role, 0))
        pnl = leg_pnl_for_contracts(leg, closed)
        if pnl is None:
            return None
        total += pnl
    return total


def _unrounded_remaining(old_lots: int, old_notional: float, new_notional: float) -> float:
    if new_notional <= 1e-9 or old_notional <= 1e-9:
        return 0.0
    return old_lots * new_notional / old_notional


def plan_structure_resize(legs: list[Mapping[str, Any]], old_notional: float, new_notional: float) -> dict[str, Any]:
    """Per-leg remaining and closed lots. Does not mutate.

    Each leg is floored on its own. A 13-lot leg halved keeps 6 and closes 7.
    The fill is zero only when every leg would close less than one lot.
    """
    per_leg: list[dict[str, Any]] = []
    any_closed = False
    for leg in legs:
        old = int(leg.get("contracts") or 0)
        remaining, closed, zero = split_lots(old, old_notional, new_notional)
        unrounded = _unrounded_remaining(old, old_notional, new_notional)
        if closed:
            any_closed = True
        per_leg.append(
            {
                "role": leg.get("role"),
                "old_lots": old,
                "remaining_lots": remaining,
                "closed_lots": closed,
                "zero_lot": zero,
                "unrounded_remaining": unrounded,
                "residual_contracts": unrounded - remaining,
            }
        )
    zero_lot = new_notional > 1e-9 and not any_closed and all(
        row["remaining_lots"] == row["old_lots"] for row in per_leg
    )
    return {"per_leg": per_leg, "zero_lot": zero_lot, "any_closed": any_closed}


def apply_structure_remaining(legs: list[dict[str, Any]], plan: Mapping[str, Any], *, average_entries: bool) -> None:
    by_role = {str(row["role"]): row for row in plan["per_leg"]}
    for leg in legs:
        row = by_role.get(str(leg.get("role")))
        if row is None:
            continue
        old = int(row["old_lots"])
        new_lots = int(row["remaining_lots"])
        if average_entries and new_lots > old and leg.get("entry_rate") is not None and leg.get("mark_rate") is not None and old > 0:
            added = new_lots - old
            leg["entry_rate"] = (float(leg["entry_rate"]) * old + float(leg["mark_rate"]) * added) / new_lots
        leg["contracts"] = new_lots
        leg["lots_closed_last"] = int(row["closed_lots"])
        leg["lots_added_last"] = int(row.get("added_lots") or 0)
        if "unrounded_remaining" in row:
            leg["contracts_unrounded"] = row["unrounded_remaining"]
        if "residual_contracts" in row:
            leg["residual_contracts"] = row["residual_contracts"]
        leg["rounding_policy"] = REMAINING_POLICY
        recompute_leg_dv01(leg)


def plan_structure_add(legs: list[Mapping[str, Any]], old_notional: float, new_notional: float) -> dict[str, Any]:
    """Add by flooring each leg's scaled total. Added lots can differ by leg."""
    if old_notional <= 0:
        return {"per_leg": [], "zero_lot": True, "any_added": False}
    ratio = new_notional / old_notional
    per_leg = []
    any_added = False
    for leg in legs:
        old = int(leg.get("contracts") or 0)
        scaled = whole_lots(old * ratio)
        added = max(0, scaled - old)
        raw_added = old * ratio - old
        unrounded = old * ratio
        zero = added < 1
        if added:
            any_added = True
        per_leg.append(
            {
                "role": leg.get("role"),
                "old_lots": old,
                "remaining_lots": old if zero else scaled,
                "closed_lots": 0,
                "added_lots": 0 if zero else added,
                "added_unrounded": raw_added,
                "unrounded_remaining": old if zero else unrounded,
                "residual_contracts": 0.0 if zero else unrounded - scaled,
                "zero_lot": zero,
            }
        )
    return {"per_leg": per_leg, "zero_lot": not any_added, "any_added": any_added, "any_closed": False}


def refresh_outright_fx(position: dict[str, Any], market_state: Mapping[str, Any] | None) -> bool:
    """Write the current frozen FX onto a single stamped future. Entry FX stays put."""
    if position.get("legs") or position.get("valuation_method") != "instrument_dv01":
        return True
    parsed = parse_contract_id(position.get("instrument") if isinstance(position.get("instrument"), str) else None)
    currency = position.get("contract_currency") or (parsed.spec.currency if parsed else "USD")
    quote = current_fx_quote(str(currency), market_state)
    position["mark_fx_pair"] = quote.get("pair")
    position["mark_fx_as_of"] = quote.get("as_of")
    position["mark_fx_source"] = quote.get("source")
    if quote.get("status") != "ok" or quote.get("usd_per_unit") is None:
        position["mark_fx_usd_per_unit"] = None
        position["mark_fx_status"] = quote.get("status") or "unavailable"
        position["mark_price"] = None
        position["mark_price_source"] = None
        position["mark_price_as_of"] = None
        position["mark_status"] = "unavailable"
        position["mark_unavailable_reason"] = f"{currency} FX fixing {quote.get('status') or 'unavailable'}"
        position["pnl_unavailable"] = True
        return False
    position["mark_fx_usd_per_unit"] = quote["usd_per_unit"]
    position["mark_fx_status"] = "ok"
    if position.get("mark_price") not in (None, ""):
        position["mark_status"] = "ok"
        position.pop("mark_unavailable_reason", None)
    return True


def marks_block_fill(position: Mapping[str, Any]) -> bool:
    """True when a real fill would have to invent a rate or a current FX."""
    if position.get("legs"):
        if position.get("mark_status") == "unavailable" or position.get("mark_price") in (None, ""):
            return True
        for leg in position.get("legs") or []:
            if not isinstance(leg, Mapping):
                return True
            if leg.get("mark_status") == "unavailable" or leg.get("mark_rate") is None:
                return True
            if leg.get("currency") not in (None, "USD") and (
                leg.get("mark_fx_usd_per_unit") in (None, "") or leg.get("mark_fx_status") not in (None, "ok")
            ):
                return True
        return False
    if position.get("valuation_method") == "instrument_dv01":
        if position.get("mark_status") == "unavailable" or position.get("mark_price") in (None, ""):
            return True
        if position.get("contract_currency") not in (None, "USD") and (
            position.get("mark_fx_usd_per_unit") in (None, "") or position.get("mark_fx_status") not in (None, "ok")
        ):
            return True
    return False


def _pending(lots_added: int = 0) -> dict[str, Any]:
    return {
        "legacy": False,
        "zero_lot": False,
        "pending_mark": True,
        "realized_pnl_usd": None,
        "lots_closed": 0,
        "lots_added": lots_added,
    }


def _zero_lot(*, remaining_lots: int | None = None) -> dict[str, Any]:
    row = {
        "legacy": False,
        "zero_lot": True,
        "pending_mark": False,
        "realized_pnl_usd": 0.0,
        "lots_closed": 0,
        "lots_added": 0,
    }
    if remaining_lots is not None:
        row["remaining_lots"] = remaining_lots
    return row


def apply_book_resize(
    position: dict[str, Any],
    *,
    old_notional: float,
    new_notional: float,
    add_price: float | None = None,
    market_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Mutate lot counts. Realized P&L covers only lots removed on this action.

    Returns legacy=True when the position is not a stamped future or structure.
    """
    reducing = new_notional < old_notional - 1e-9
    if position.get("legs"):
        if reducing:
            plan = plan_structure_resize(position["legs"], old_notional, new_notional)
            if plan["zero_lot"]:
                return _zero_lot()
            if marks_block_fill(position):
                return _pending()
            closed_map = {str(row["role"]): int(row["closed_lots"]) for row in plan["per_leg"]}
            realized = structure_pnl_for_closed_lots(position["legs"], closed_map)
            if realized is None:
                return _pending()
            apply_structure_remaining(position["legs"], plan, average_entries=False)
        else:
            plan = plan_structure_add(position["legs"], old_notional, new_notional)
            if plan["zero_lot"]:
                return _zero_lot()
            if marks_block_fill(position):
                return _pending()
            apply_structure_remaining(position["legs"], plan, average_entries=True)
            realized = 0.0
            closed_map = {}
        dv01s = [abs(float(leg.get("dv01_usd") or 0.0)) for leg in position["legs"] if leg.get("dv01_usd") is not None]
        position["spread_dv01_usd"] = round(max(dv01s) if dv01s else 0.0, 8)
        position["residual_dv01_usd"] = _structure_residual_dv01(position["legs"], plan)
        lots_closed = sum(int(row.get("closed_lots") or 0) for row in plan["per_leg"])
        lots_added = sum(int(row.get("added_lots") or 0) for row in plan["per_leg"])
        return {
            "legacy": False,
            "zero_lot": False,
            "pending_mark": False,
            "realized_pnl_usd": round(float(realized or 0.0), 2),
            "lots_closed": lots_closed,
            "lots_added": lots_added,
            "per_leg": plan["per_leg"],
            "closed_map": closed_map if reducing else {},
        }

    if position.get("valuation_method") == "instrument_dv01" and position.get("contracts") is not None:
        old_lots = int(position["contracts"])
        if reducing:
            remaining, closed, zero = split_lots(old_lots, old_notional, new_notional)
            if zero:
                return _zero_lot(remaining_lots=old_lots)
            if marks_block_fill(position):
                return _pending()
            realized = contract_pnl_for_lots(position, closed)
            if realized is None:
                return _pending()
            position["contracts"] = remaining
            position["_closed_lots"] = closed
            _stamp_outright_residual(position, _unrounded_remaining(old_lots, old_notional, new_notional))
            return {
                "legacy": False,
                "zero_lot": False,
                "pending_mark": False,
                "realized_pnl_usd": round(realized, 2),
                "lots_closed": closed,
                "lots_added": 0,
                "remaining_lots": remaining,
            }
        fx = _current_fx_rate(position, market_state)
        face = outright_face_usd(position, float(fx or 0.0))
        if fx is None or face is None:
            return _pending()
        added, raw_added, zero = added_lots_from_face(new_notional - old_notional, face_usd_per_lot=face)
        if zero:
            return _zero_lot(remaining_lots=old_lots)
        if marks_block_fill(position):
            return _pending()
        price = add_price if add_price is not None else position.get("mark_price")
        if price in (None, ""):
            return _pending()
        if position.get("entry_price") not in (None, "") and old_lots > 0:
            position["entry_price"] = (float(position["entry_price"]) * old_lots + float(price) * added) / (old_lots + added)
            position["entry_price_source"] = "weighted_average_of_actual_lots"
        position["mark_price"] = price
        position["contracts"] = old_lots + added
        _stamp_outright_residual(position, old_lots + raw_added)
        return {
            "legacy": False,
            "zero_lot": False,
            "pending_mark": False,
            "realized_pnl_usd": 0.0,
            "lots_closed": 0,
            "lots_added": added,
            "remaining_lots": old_lots + added,
        }
    return {"legacy": True}


def _stamp_outright_residual(position: dict[str, Any], unrounded: float) -> None:
    contracts = int(position.get("contracts") or 0)
    position["contracts_unrounded"] = unrounded
    position["residual_contracts"] = unrounded - contracts
    position["rounding_policy"] = REMAINING_POLICY
    position["sub_lot_policy"] = SUB_LOT_POLICY


def _structure_residual_dv01(legs: list[Mapping[str, Any]], plan: Mapping[str, Any]) -> float:
    """USD DV01 of the fractional lots that were not booked."""
    by_role = {str(row.get("role")): row for row in plan.get("per_leg") or []}
    residual = 0.0
    for leg in legs:
        row = by_role.get(str(leg.get("role")))
        if row is None or leg.get("dv01_per_contract_local") is None or leg.get("mark_fx_usd_per_unit") in (None, ""):
            continue
        per = float(leg["dv01_per_contract_local"]) * float(leg["mark_fx_usd_per_unit"])
        residual += float(row.get("residual_contracts") or 0.0) * per
    return round(residual, 6)


def outright_lot_pnl_lots(position: Mapping[str, Any], closed_notional: float | None) -> int | None:
    """Lots that a reduce realizes. None means use the full open quantity."""
    contracts = position.get("contracts")
    if contracts is None:
        return None
    explicit = position.get("_closed_lots")
    if explicit is not None:
        return int(explicit)
    if closed_notional is None:
        return int(contracts)
    notional = float(position.get("notional_usd") or 0.0)
    _remaining, closed, zero = split_lots(int(contracts), notional, notional - float(closed_notional))
    if zero:
        return 0
    return closed
