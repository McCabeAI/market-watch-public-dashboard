"""Whole-lot open, add, reduce, and close accounting.

Descriptive notional is the requested face. Executable quantity is an integer
lot count. A request that closes or adds less than one lot is not a fill.
A partial reduce keeps ``floor(old_lots * remaining_notional / old_notional)``
and realizes P&L only on the lots actually removed.

A multi-leg structure is one package. Per-leg floors are only a candidate.
The candidate is booked when every active role, side, and curve remains
(unless the request closes the whole structure), every active leg changes
together, and the change in signed USD DV01 — for the package and for each
curve — stays within one contract of the largest leg plus the structure's
existing unrounded residual. A proportional request that cannot meet that
gate is ``size_rejected`` and does not change any leg.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, ROUND_FLOOR
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
PACKAGE_RESIZE_POLICY = "atomic_package_one_contract_residual"


def _money(value: float) -> Decimal:
    return Decimal(str(value))


def split_lots(old_lots: int, old_notional: float, new_notional: float) -> tuple[int, int, bool]:
    """Return (remaining_lots, closed_lots, zero_lot)."""
    old_lots = int(old_lots)
    if old_lots < 0:
        old_lots = 0
    if new_notional <= 1e-9 or old_notional <= 1e-9:
        return 0, old_lots, False
    if new_notional >= old_notional - 1e-9:
        return old_lots, 0, False
    old_n = _money(old_notional)
    new_n = _money(new_notional)
    closed_raw = Decimal(old_lots) * (old_n - new_n) / old_n
    if closed_raw < 1:
        return old_lots, 0, True
    raw_remaining = Decimal(old_lots) * new_n / old_n
    remaining = int(raw_remaining.to_integral_value(rounding=ROUND_FLOOR))
    remaining = min(old_lots, max(0, remaining))
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


def _candidate_resize_rows(legs: list[Mapping[str, Any]], old_notional: float, new_notional: float) -> list[dict[str, Any]]:
    per_leg: list[dict[str, Any]] = []
    for leg in legs:
        old = int(leg.get("contracts") or 0)
        remaining, closed, zero = split_lots(old, old_notional, new_notional)
        unrounded = _unrounded_remaining(old, old_notional, new_notional)
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
    return per_leg


def plan_structure_resize(
    legs: list[Mapping[str, Any]],
    old_notional: float,
    new_notional: float,
    *,
    suggest: bool = True,
) -> dict[str, Any]:
    """Candidate whole-lot reduce, accepted only as one package. Does not mutate.

    Each leg is floored on its own. A 13-lot leg halved keeps 6 and closes 7.
    The fill is zero only when every leg would close less than one lot.
    A candidate that would drop or skip a leg is ``size_rejected``.
    """
    per_leg = _candidate_resize_rows(legs, old_notional, new_notional)
    any_closed = any(int(row["closed_lots"]) > 0 for row in per_leg)
    zero_lot = new_notional > 1e-9 and not any_closed and all(
        row["remaining_lots"] == row["old_lots"] for row in per_leg
    )
    plan = {"per_leg": per_leg, "zero_lot": zero_lot, "any_closed": any_closed, "size_rejected": False}
    if zero_lot:
        return plan
    return _finish_package_plan(legs, plan, old_notional, new_notional, reducing=True, suggest=suggest)


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


def plan_structure_add(
    legs: list[Mapping[str, Any]],
    old_notional: float,
    new_notional: float,
    *,
    suggest: bool = True,
) -> dict[str, Any]:
    """Add by flooring each leg's scaled total. Booked only as one package."""
    if old_notional <= 0:
        return {"per_leg": [], "zero_lot": True, "any_added": False, "size_rejected": False, "any_closed": False}
    ratio = _money(new_notional) / _money(old_notional)
    per_leg = []
    any_added = False
    for leg in legs:
        old = int(leg.get("contracts") or 0)
        scaled_raw = Decimal(old) * ratio
        scaled = int(scaled_raw.to_integral_value(rounding=ROUND_FLOOR))
        if scaled < old:
            scaled = old
        added = scaled - old
        raw_added = float(scaled_raw - Decimal(old))
        unrounded = float(scaled_raw)
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
    plan = {"per_leg": per_leg, "zero_lot": not any_added, "any_added": any_added, "any_closed": False, "size_rejected": False}
    if plan["zero_lot"]:
        return plan
    return _finish_package_plan(legs, plan, old_notional, new_notional, reducing=False, suggest=suggest)


def _lot_map(per_leg: list[Mapping[str, Any]]) -> str:
    return ", ".join(f"{row.get('role')} {int(row['old_lots'])}→{int(row['remaining_lots'])}" for row in per_leg)


def _legs_by_role(legs: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(leg.get("role") or ""): leg for leg in legs}


def _active_rows(per_leg: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [row for row in per_leg if int(row.get("old_lots") or 0) > 0]


def _usd_per_contract(leg: Mapping[str, Any]) -> float | None:
    local = leg.get("dv01_per_contract_local")
    if local is None:
        return None
    currency = leg.get("currency")
    fx = leg.get("mark_fx_usd_per_unit")
    if currency in (None, "USD"):
        if fx in (None, ""):
            return abs(float(local))
        if leg.get("mark_fx_status") not in (None, "ok"):
            return None
        return abs(float(local) * float(fx))
    if fx in (None, "") or leg.get("mark_fx_status") not in (None, "ok"):
        return None
    return abs(float(local) * float(fx))


def _signed_dv01(leg: Mapping[str, Any], contracts: int, per_usd: float) -> float:
    sign = 1.0 if leg.get("side") == "long" else -1.0
    return sign * int(contracts) * per_usd


def _assess_package(
    legs: list[Mapping[str, Any]],
    plan: Mapping[str, Any],
    old_notional: float,
    new_notional: float,
) -> dict[str, Any]:
    """Accept a candidate only when the package shape survives whole-lot rounding."""
    per_leg = list(plan.get("per_leg") or [])
    active = _active_rows(per_leg)
    by_role = _legs_by_role(legs)
    full_close_request = new_notional <= 1e-9 or old_notional <= 1e-9
    all_flat = bool(active) and all(int(row["remaining_lots"]) <= 0 for row in active)
    if all_flat and full_close_request:
        return {"size_rejected": False, "package_policy": PACKAGE_RESIZE_POLICY}
    if all_flat:
        return {
            "size_rejected": True,
            "package_policy": PACKAGE_RESIZE_POLICY,
            "reason": (
                f"partial resize floors every leg to zero ({_lot_map(per_leg)}); "
                "a full close is the executable unwind"
            ),
        }
    dropped = [str(row["role"]) for row in active if int(row["remaining_lots"]) <= 0]
    if dropped:
        kept = [str(row["role"]) for row in active if int(row["remaining_lots"]) > 0]
        return {
            "size_rejected": True,
            "package_policy": PACKAGE_RESIZE_POLICY,
            "reason": (
                f"package resize would remove {dropped} and leave {kept}; "
                f"refusing a one-sided structure ({_lot_map(per_leg)})"
            ),
        }
    changed = [str(row["role"]) for row in active if int(row["remaining_lots"]) != int(row["old_lots"])]
    unchanged = [str(row["role"]) for row in active if int(row["remaining_lots"]) == int(row["old_lots"])]
    if changed and unchanged:
        return {
            "size_rejected": True,
            "package_policy": PACKAGE_RESIZE_POLICY,
            "reason": (
                f"package resize changes {changed} and leaves {unchanged} unchanged; "
                f"refusing a one-sided structure ({_lot_map(per_leg)})"
            ),
        }

    def _labels(remaining: bool, field: str) -> set[Any]:
        found: set[Any] = set()
        for row in active:
            lots = int(row["remaining_lots"] if remaining else row["old_lots"])
            if lots <= 0:
                continue
            leg = by_role.get(str(row.get("role")))
            if leg is not None and leg.get(field) not in (None, ""):
                found.add(leg.get(field))
        return found

    for field, kind in (("side", "side"), ("curve_id", "curve")):
        before = _labels(False, field)
        after = _labels(True, field)
        if before != after:
            return {
                "size_rejected": True,
                "package_policy": PACKAGE_RESIZE_POLICY,
                "reason": (
                    f"package resize drops {kind} {sorted(before - after)!s}; "
                    f"refusing a structure that no longer matches its definition ({_lot_map(per_leg)})"
                ),
            }

    ratio = 0.0 if old_notional <= 1e-9 else new_notional / old_notional
    pers: list[float] = []
    existing_residual = 0.0
    missing_fx = False
    for row in active:
        leg = by_role.get(str(row.get("role")))
        if leg is None:
            missing_fx = True
            continue
        per = _usd_per_contract(leg)
        if per is None:
            missing_fx = True
            continue
        pers.append(per)
        existing_residual += abs(float(leg.get("residual_contracts") or 0.0)) * per
    if missing_fx or not pers:
        return {"size_rejected": False, "needs_fx": True, "package_policy": PACKAGE_RESIZE_POLICY}

    tolerance = max(pers) + existing_residual
    groups: dict[str, list[tuple[Mapping[str, Any], Mapping[str, Any], float]]] = {"package": []}
    for row in active:
        leg = by_role[str(row.get("role"))]
        per = _usd_per_contract(leg)
        assert per is not None
        groups["package"].append((row, leg, per))
        curve = str(leg.get("curve_id") or leg.get("currency") or "package")
        groups.setdefault(curve, []).append((row, leg, per))
    for name, members in groups.items():
        pre = sum(_signed_dv01(leg, int(row["old_lots"]), per) for row, leg, per in members)
        post = sum(_signed_dv01(leg, int(row["remaining_lots"]), per) for row, leg, per in members)
        delta = abs(post - pre * ratio)
        if delta > tolerance + 1e-4:
            label = "package" if name == "package" else f"curve {name}"
            return {
                "size_rejected": True,
                "package_policy": PACKAGE_RESIZE_POLICY,
                "reason": (
                    f"{label} signed USD DV01 moves by {delta:.2f} versus the scaled package, "
                    f"outside the one-contract tolerance {tolerance:.2f} ({_lot_map(per_leg)})"
                ),
            }
    return {"size_rejected": False, "package_policy": PACKAGE_RESIZE_POLICY, "dv01_tolerance_usd": round(tolerance, 6)}


def _minimum_executable(
    legs: list[Mapping[str, Any]],
    old_notional: float,
    *,
    reducing: bool,
) -> dict[str, Any]:
    """Smallest notional step that passes the same package gate. Does not mutate."""
    active = [leg for leg in legs if int(leg.get("contracts") or 0) > 0]
    if not active or old_notional <= 0:
        return {}
    candidates: list[float] = []
    seen: set[float] = set()
    old_n = _money(old_notional)
    for leg in active:
        old = int(leg.get("contracts") or 0)
        steps = range(0, old) if reducing else range(1, old + 1)
        for step in steps:
            if reducing:
                new_n = float((old_n * Decimal(step) / Decimal(old)).quantize(Decimal("0.01")))
                if new_n >= float(old_notional) - 0.01:
                    continue
            else:
                new_n = float((old_n * Decimal(old + step) / Decimal(old)).quantize(Decimal("0.01")))
                if new_n <= float(old_notional) + 0.01:
                    continue
            key = round(new_n, 2)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(new_n)
    candidates.sort(reverse=reducing)
    for new_n in candidates:
        if reducing:
            plan = plan_structure_resize(legs, old_notional, new_n, suggest=False)
        else:
            plan = plan_structure_add(legs, old_notional, new_n, suggest=False)
        if plan.get("zero_lot") or plan.get("size_rejected"):
            continue
        increment = round(abs(new_n - float(old_notional)), 2)
        return {
            "minimum_executable_increment_usd": increment,
            "minimum_executable_fraction": round(increment / float(old_notional), 8),
            "minimum_executable_notional_usd": increment,
        }
    return {}


def _finish_package_plan(
    legs: list[Mapping[str, Any]],
    plan: dict[str, Any],
    old_notional: float,
    new_notional: float,
    *,
    reducing: bool,
    suggest: bool,
) -> dict[str, Any]:
    verdict = _assess_package(legs, plan, old_notional, new_notional)
    plan.update(verdict)
    if plan.get("size_rejected") and suggest:
        plan.update(_minimum_executable(legs, old_notional, reducing=reducing))
    return plan


def stamp_structure_nofill(action: dict[str, Any], block: Mapping[str, Any]) -> None:
    """Record a structure no-fill on the action. Does not touch the position."""
    action["fill_status"] = block["fill_status"]
    action["lots_closed"] = 0
    action["lots_added"] = 0
    action["realized_pnl_usd"] = 0.0
    action["pending_mark"] = False
    if block["fill_status"] == "zero_lot":
        action["zero_lot_policy"] = SUB_LOT_POLICY
    if block["fill_status"] == "size_rejected":
        action["size_reject_reason"] = block.get("reason")
        action["package_policy"] = block.get("package_policy") or PACKAGE_RESIZE_POLICY
        for key in (
            "minimum_executable_increment_usd",
            "minimum_executable_fraction",
            "minimum_executable_notional_usd",
        ):
            if block.get(key) is not None:
                action[key] = block[key]


def structure_resize_block(
    position: Mapping[str, Any],
    *,
    old_notional: float,
    new_notional: float,
    market_state: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """No-fill decision for a structure, or None when the live path should execute.

    The probe is a copy. A rejected size or a sub-lot request does not refresh
    or resize the caller's position.
    """
    if not position.get("legs"):
        return None
    probe = deepcopy(position)
    if isinstance(market_state, Mapping):
        from scripts.overnight.paper_marks import refresh_positions

        refresh_positions([probe], market_state)
    reducing = new_notional < old_notional - 1e-9
    if reducing:
        plan = plan_structure_resize(probe["legs"], old_notional, new_notional)
    else:
        plan = plan_structure_add(probe["legs"], old_notional, new_notional)
    if plan.get("zero_lot"):
        return {"fill_status": "zero_lot", "realized_pnl_usd": 0.0, "reason": SUB_LOT_POLICY}
    if plan.get("size_rejected"):
        return {
            "fill_status": "size_rejected",
            "realized_pnl_usd": 0.0,
            "reason": plan.get("reason"),
            "minimum_executable_increment_usd": plan.get("minimum_executable_increment_usd"),
            "minimum_executable_fraction": plan.get("minimum_executable_fraction"),
            "minimum_executable_notional_usd": plan.get("minimum_executable_notional_usd"),
            "package_policy": plan.get("package_policy") or PACKAGE_RESIZE_POLICY,
        }
    return None


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


def _size_rejected(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "legacy": False,
        "zero_lot": False,
        "pending_mark": False,
        "size_rejected": True,
        "realized_pnl_usd": 0.0,
        "lots_closed": 0,
        "lots_added": 0,
        "reason": plan.get("reason"),
        "minimum_executable_increment_usd": plan.get("minimum_executable_increment_usd"),
        "minimum_executable_fraction": plan.get("minimum_executable_fraction"),
        "minimum_executable_notional_usd": plan.get("minimum_executable_notional_usd"),
        "package_policy": plan.get("package_policy") or PACKAGE_RESIZE_POLICY,
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
            if plan.get("size_rejected"):
                return _size_rejected(plan)
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
            if plan.get("size_rejected"):
                return _size_rejected(plan)
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
