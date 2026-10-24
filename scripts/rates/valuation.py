"""Rates P&L and shocked-risk valuation.

Stored positions that already have a position id and no explicit
``valuation_method`` stay on the legacy duration-one vintage so historical
ledgers are not silently restated. New single-contract bookings stamp
``instrument_dv01``. A strip average is never valued as one contract or as a
curve spread. Sovereign holdings without a verified DV01 stay on the legacy
number for the original ledger and are marked unavailable in the corrected view.
"""

from __future__ import annotations

from typing import Any, Mapping

from scripts.overnight.errors import SchemaError
from scripts.rates.contract_economics import (
    contracts_from_face_usd,
    dv01_per_contract,
    fx_usd_per_unit,
    is_sovereign_instrument,
    parse_contract_id,
)
from scripts.rates.structures import (
    STRIP_TYPE,
    STRUCTURE_TYPES,
    leg_pnl_usd,
    structure_pnl_usd,
)

LEGACY_METHOD = "legacy_duration_one"
INSTRUMENT_METHOD = "instrument_dv01"
UNAVAILABLE = "unavailable"

STANDARD_SHOCK_BP = 100.0
SPOT_SHOCK_FRACTION = 0.01


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:
        return None
    return out


def _expression(position: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = position.get("paper_expression")
    return raw if isinstance(raw, Mapping) else {}


def is_strip(position: Mapping[str, Any]) -> bool:
    return _expression(position).get("type") == STRIP_TYPE and not position.get("legs")


def valuation_mode(position: Mapping[str, Any]) -> str:
    if position.get("legs"):
        return INSTRUMENT_METHOD
    if is_strip(position):
        return LEGACY_METHOD
    method = position.get("valuation_method")
    if method == LEGACY_METHOD:
        return LEGACY_METHOD
    if method == INSTRUMENT_METHOD:
        return INSTRUMENT_METHOD
    if method == UNAVAILABLE:
        return UNAVAILABLE
    # Historical rows keep the vintage that produced the stored ledger.
    if position.get("position_id") or position.get("opened_at"):
        return LEGACY_METHOD
    if parse_contract_id(position.get("instrument") if isinstance(position.get("instrument"), str) else None):
        return INSTRUMENT_METHOD
    return LEGACY_METHOD


def _side_sign(side: Any) -> int:
    if side not in {"long", "short"}:
        raise SchemaError(f"side must be long or short, got {side}")
    return 1 if side == "long" else -1


def legacy_rate_pnl(position: Mapping[str, Any], *, exit_price: float | None = None, closed_notional: float | None = None) -> dict[str, Any]:
    entry = position.get("entry_price")
    mark = exit_price if exit_price is not None else position.get("mark_price")
    notional = closed_notional if closed_notional is not None else position.get("notional_usd")
    notional_f = _number(notional)
    if notional_f is None:
        raise SchemaError("notional_usd must be numeric")
    if entry in (None, "") or mark in (None, ""):
        return {
            "unrealized_pnl_usd": None,
            "pnl_unavailable": True,
            "pnl_note": "mark or entry missing; P&L not invented",
            "valuation_method": LEGACY_METHOD,
        }
    entry_f = _number(entry)
    mark_f = _number(mark)
    if entry_f is None or mark_f is None:
        raise SchemaError("entry_price and mark_price must be numeric")
    if entry_f == 0 and position.get("asset_class") not in {"rates", "curve", "rates_rv"}:
        return {
            "unrealized_pnl_usd": None,
            "pnl_unavailable": True,
            "pnl_note": "entry_price is zero; P&L not invented",
            "valuation_method": LEGACY_METHOD,
        }
    sign = _side_sign(position.get("side"))
    asset = position.get("asset_class")
    if asset == "rates":
        raw = -sign * (mark_f - entry_f) / 100.0 * notional_f
    elif asset in {"curve", "rates_rv"}:
        raw = -sign * (mark_f - entry_f) / 10_000.0 * notional_f
    else:
        if entry_f == 0:
            return {
                "unrealized_pnl_usd": None,
                "pnl_unavailable": True,
                "pnl_note": "entry_price is zero; P&L not invented",
                "valuation_method": LEGACY_METHOD,
            }
        raw = sign * (mark_f - entry_f) / entry_f * notional_f
    return {
        "unrealized_pnl_usd": round(raw, 2),
        "pnl_unavailable": False,
        "pnl_note": None,
        "valuation_method": LEGACY_METHOD,
    }


def _contract_pnl(position: Mapping[str, Any], *, exit_price: float | None, closed_notional: float | None) -> dict[str, Any]:
    parsed = parse_contract_id(position.get("instrument") if isinstance(position.get("instrument"), str) else None)
    if parsed is None:
        return {
            "unrealized_pnl_usd": None,
            "pnl_unavailable": True,
            "pnl_note": "no verified contract economics for this instrument",
            "valuation_method": UNAVAILABLE,
            "isolated": True,
        }
    entry = _number(position.get("entry_price"))
    mark = _number(exit_price if exit_price is not None else position.get("mark_price"))
    notional = _number(closed_notional if closed_notional is not None else position.get("notional_usd"))
    if entry is None or mark is None or notional is None:
        return {
            "unrealized_pnl_usd": None,
            "pnl_unavailable": True,
            "pnl_note": "mark, entry, or notional missing; contract P&L not invented",
            "valuation_method": INSTRUMENT_METHOD,
            "isolated": True,
            "contract": parsed.as_dict(),
        }
    fx, pair = fx_usd_per_unit(parsed.spec.currency, position=position)
    local = dv01_per_contract(parsed.spec, year=parsed.year, month=parsed.month)
    if fx is None or local is None:
        return {
            "unrealized_pnl_usd": None,
            "pnl_unavailable": True,
            "pnl_note": f"{parsed.spec.currency} USD conversion or DV01 unavailable; P&L not invented",
            "valuation_method": UNAVAILABLE,
            "isolated": True,
            "contract": parsed.as_dict(),
            "fx_pair": pair,
        }
    contracts = position.get("contracts")
    contracts_f = _number(contracts)
    if contracts_f is None:
        contracts_f = contracts_from_face_usd(parsed.spec, abs(notional), fx)
    if contracts_f is None:
        return {
            "unrealized_pnl_usd": None,
            "pnl_unavailable": True,
            "pnl_note": "contract quantity unavailable",
            "valuation_method": UNAVAILABLE,
            "isolated": True,
            "contract": parsed.as_dict(),
        }
    bp = (mark - entry) * parsed.spec.bp_per_price_unit
    sign = _side_sign(position.get("side"))
    raw = -sign * contracts_f * local * bp * fx
    economics = parsed.as_dict()
    economics.update(
        {
            "contracts": contracts_f,
            "fx_usd_per_unit": fx,
            "fx_pair": pair,
            "dv01_usd": local * contracts_f * fx,
        }
    )
    return {
        "unrealized_pnl_usd": round(raw, 2),
        "pnl_unavailable": False,
        "pnl_note": None,
        "valuation_method": INSTRUMENT_METHOD,
        "isolated": False,
        "contract": economics,
        "currency": parsed.spec.currency,
        "price_unit": "implied_rate_percent",
    }


def _annotate_legacy(position: Mapping[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    instrument = position.get("instrument") if isinstance(position.get("instrument"), str) else None
    if is_strip(position):
        result["corrected_valuation_status"] = UNAVAILABLE
        result["isolated"] = True
        result["structure_label"] = STRIP_TYPE
        result["isolation_reason"] = (
            "futures_strip_average is a strip average, not a curve spread and not a single contract; "
            "leg quantities were not stored, so corrected DV01 is unavailable"
        )
    elif is_sovereign_instrument(instrument):
        result["corrected_valuation_status"] = UNAVAILABLE
        result["isolated"] = True
        result["isolation_reason"] = (
            "sovereign holding has no verified modified duration or DV01; "
            "corrected P&L is unavailable and the legacy number is not a contract valuation"
        )
    else:
        result["corrected_valuation_status"] = "legacy_vintage"
        result["isolated"] = False
    return result


def value_position(position: Mapping[str, Any], *, exit_price: float | None = None, closed_notional: float | None = None) -> dict[str, Any]:
    mode = valuation_mode(position)
    if position.get("legs"):
        fraction = 1.0
        notional = _number(position.get("notional_usd"))
        closed = _number(closed_notional)
        if closed is not None and notional not in (None, 0):
            fraction = closed / notional
        total = structure_pnl_usd(list(position.get("legs") or []))
        if total is None:
            return {
                "unrealized_pnl_usd": None,
                "pnl_unavailable": True,
                "pnl_note": "one or more structure legs is missing a rate, DV01, or FX; P&L not invented",
                "valuation_method": UNAVAILABLE,
                "isolated": True,
                "structure_label": _expression(position).get("type") or position.get("structure_label"),
            }
        return {
            "unrealized_pnl_usd": round(total * fraction, 2),
            "pnl_unavailable": False,
            "pnl_note": None,
            "valuation_method": INSTRUMENT_METHOD,
            "isolated": False,
            "structure_label": _expression(position).get("type") or position.get("structure_label"),
            "currency": "USD",
        }
    if mode == INSTRUMENT_METHOD:
        return _contract_pnl(position, exit_price=exit_price, closed_notional=closed_notional)
    if mode == UNAVAILABLE:
        return {
            "unrealized_pnl_usd": None,
            "pnl_unavailable": True,
            "pnl_note": position.get("isolation_reason") or "valuation unavailable; P&L not invented",
            "valuation_method": UNAVAILABLE,
            "isolated": True,
        }
    asset = position.get("asset_class")
    if asset in {"rates", "curve", "rates_rv", "spot_fx", None} or asset == "spot_fx":
        try:
            result = legacy_rate_pnl(position, exit_price=exit_price, closed_notional=closed_notional)
        except SchemaError:
            raise
        if asset in {"rates", "curve", "rates_rv"} or is_strip(position) or is_sovereign_instrument(
            position.get("instrument") if isinstance(position.get("instrument"), str) else None
        ):
            return _annotate_legacy(position, result)
        result["isolated"] = False
        result["corrected_valuation_status"] = "not_rates"
        return result
    return {
        "unrealized_pnl_usd": None,
        "pnl_unavailable": True,
        "pnl_note": f"unsupported asset_class {asset!r}",
        "valuation_method": UNAVAILABLE,
        "isolated": True,
    }


def shock_risk_usd(position: Mapping[str, Any]) -> float | None:
    """Absolute P&L from the standard shock, in USD.

    Spot remains a 1% price move. Supported contracts and DV01-balanced
    structures use a 100bp adverse move in the canonical mark. Legacy vintages
    keep the duration-one 100bp identity. Options still require an explicit
    shocked MTM. Missing FX or DV01 returns None.
    """
    notional = _number(position.get("notional_usd"))
    asset = str(position.get("asset_class") or "")
    if position.get("legs"):
        dv01 = _number(position.get("spread_dv01_usd"))
        if dv01 is None:
            sample = structure_pnl_usd(list(position.get("legs") or []))
            # Reconstruct spread DV01 from a 1bp canonical move when stored.
            roles = {leg.get("role"): leg for leg in position.get("legs") or []}
            kind = _expression(position).get("type") or position.get("structure_label")
            if kind == "butterfly":
                dv01 = abs(float(roles["wing1"]["dv01_usd"])) if "wing1" in roles else None
            elif kind == "outright_rv":
                dv01 = abs(float(roles["receive"]["dv01_usd"])) if "receive" in roles else None
            elif kind == "curve_rv":
                dv01 = abs(float(roles["long_calendar_near"]["dv01_usd"])) if "long_calendar_near" in roles else None
            elif roles:
                first = next(iter(roles.values()))
                dv01 = abs(float(first.get("dv01_usd") or 0.0))
            if sample is None and dv01 is None:
                return None
        if dv01 is None:
            return None
        return round(abs(dv01) * STANDARD_SHOCK_BP, 2)
    mode = valuation_mode(position)
    if mode == INSTRUMENT_METHOD:
        parsed = parse_contract_id(position.get("instrument") if isinstance(position.get("instrument"), str) else None)
        if parsed is None:
            return None
        if notional is None:
            return None
        fx, _pair = fx_usd_per_unit(parsed.spec.currency, position=position)
        local = dv01_per_contract(parsed.spec, year=parsed.year, month=parsed.month)
        if fx is None or local is None:
            return None
        contracts = _number(position.get("contracts"))
        if contracts is None:
            contracts = contracts_from_face_usd(parsed.spec, abs(notional), fx)
        if contracts is None:
            return None
        return round(abs(contracts * local * fx * STANDARD_SHOCK_BP), 2)
    if mode == UNAVAILABLE:
        return None
    if notional is None:
        return None
    notional = abs(notional)
    if notional == 0:
        return 0.0
    if asset == "spot_fx" or (not asset and position.get("side") and not parse_contract_id(str(position.get("instrument") or ""))):
        if asset == "spot_fx":
            return round(notional * SPOT_SHOCK_FRACTION, 2)
    if asset == "spot_fx":
        return round(notional * SPOT_SHOCK_FRACTION, 2)
    if asset == "rates" or (mode == LEGACY_METHOD and asset == "rates"):
        return round(notional * 1.0 / 100.0, 2)
    if asset in {"curve", "rates_rv"}:
        return round(notional * STANDARD_SHOCK_BP / 10_000.0, 2)
    if asset == "options":
        explicit = _number(position.get("shock_1pct_pnl_usd"))
        return None if explicit is None else round(abs(explicit), 2)
    if asset == "" and mode == LEGACY_METHOD:
        return None
    return None


def stamp_open_valuation(position: dict[str, Any], market_state: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Attach the valuation vintage for a newly opened position. Does not invent FX."""
    expression = _expression(position)
    kind = expression.get("type")
    if kind == STRIP_TYPE:
        position["valuation_method"] = LEGACY_METHOD
        position["structure_label"] = STRIP_TYPE
        position["corrected_valuation_status"] = UNAVAILABLE
        position["isolated"] = True
        position["isolation_reason"] = (
            "futures_strip_average is a strip average, not a curve spread and not a single contract; "
            "corrected DV01 is unavailable until leg quantities are stored"
        )
        return position
    if kind in STRUCTURE_TYPES and position.get("legs"):
        position["valuation_method"] = INSTRUMENT_METHOD
        position["structure_label"] = kind
        position["isolated"] = False
        position["corrected_valuation_status"] = "instrument_dv01"
        return position
    instrument = position.get("instrument") if isinstance(position.get("instrument"), str) else None
    parsed = parse_contract_id(instrument)
    if parsed is not None and kind not in STRUCTURE_TYPES:
        fx, pair = fx_usd_per_unit(parsed.spec.currency, market_state, position)
        local = dv01_per_contract(parsed.spec, year=parsed.year, month=parsed.month)
        if fx is None or local is None:
            position["valuation_method"] = UNAVAILABLE
            position["isolated"] = True
            position["corrected_valuation_status"] = UNAVAILABLE
            position["isolation_reason"] = (
                f"{parsed.spec.currency} USD conversion or month DV01 is unavailable for {parsed.alias}; "
                "position isolated rather than valued with a generic duration"
            )
            position["contract"] = parsed.as_dict()
            return position
        notional = _number(position.get("notional_usd")) or 0.0
        contracts = contracts_from_face_usd(parsed.spec, abs(notional), fx)
        position["valuation_method"] = INSTRUMENT_METHOD
        position["isolated"] = False
        position["corrected_valuation_status"] = "instrument_dv01"
        position["contract_currency"] = parsed.spec.currency
        position["fx_usd_per_unit"] = fx
        position["fx_pair"] = pair
        position["contracts"] = contracts
        position["contract"] = parsed.as_dict()
        position["structure_label"] = "outright_future"
        return position
    if is_sovereign_instrument(instrument) or position.get("asset_class") in {"rates", "curve", "rates_rv"}:
        if is_sovereign_instrument(instrument) or (
            position.get("asset_class") in {"rates", "curve", "rates_rv"} and parsed is None and kind not in STRUCTURE_TYPES
        ):
            # Generic curve/RV labels and sovereigns have no verified DV01.
            if is_sovereign_instrument(instrument):
                position["valuation_method"] = LEGACY_METHOD
                position["corrected_valuation_status"] = UNAVAILABLE
                position["isolated"] = True
                position["isolation_reason"] = (
                    "sovereign holding has no verified modified duration or DV01; "
                    "legacy ledger P&L is retained and corrected P&L is unavailable"
                )
                return position
    position.setdefault("valuation_method", LEGACY_METHOD)
    position.setdefault("isolated", False)
    return position
