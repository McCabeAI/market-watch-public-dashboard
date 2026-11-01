"""CME US Treasury note futures (TU/ZT, FV/ZF, TY/ZN): contract economics and CTD-aware DV01.

Price-quoted futures; P&L scales with point value, not STIR implied-rate sign.
DV01 uses supplied conversion factor and CTD inputs only (no invented duration).

Exchange references:
- https://www.cmegroup.com/education/courses/introduction-to-treasuries/understand-treasuries-contract-specifications
- https://www.cmegroup.com/markets/interest-rates/us-treasury/10-year-us-treasury-note.contractSpecs.html
- https://www.cmegroup.com/articles/2024/calculating-us-treasury-futures-conversion-factors.html
"""

from __future__ import annotations

import math
import re
from decimal import Decimal, ROUND_FLOOR
from typing import Any, Mapping

_CME_MONTH = {
    "F": 1,
    "G": 2,
    "H": 3,
    "J": 4,
    "K": 5,
    "M": 6,
    "N": 7,
    "Q": 8,
    "U": 9,
    "V": 10,
    "X": 11,
    "Z": 12,
}

_DELIVERY_MONTHS = frozenset({3, 6, 9, 12})

_PRODUCT_ALIASES = {
    "TU": "TU",
    "ZT": "TU",
    "FV": "FV",
    "ZF": "FV",
    "TY": "TY",
    "ZN": "TY",
}

_GLOBEX = {"TU": "ZT", "FV": "ZF", "TY": "ZN"}

_SPECS: dict[str, dict[str, Any]] = {
    "TU": {
        "product": "TU",
        "globex": "ZT",
        "name": "2-Year U.S. Treasury Note",
        "face_notional_usd": 200_000.0,
        "point_value_usd": 2_000.0,
        "tick_size_points": 0.125 / 32.0,
        "tick_value_usd": 7.8125,
        "thirty_second_point_value_usd": 62.50,
        "delivery_months": [3, 6, 9, 12],
        "deliverable_summary": (
            "Original maturity ≤ 5y3m; remaining maturity ≥ 1y9m from first day of "
            "delivery month and ≤ 2y from last day of delivery month."
        ),
        "last_trading_day_rule": "Last business day of the contract month.",
        "invoice": "Futures settlement × conversion factor + accrued interest.",
        "conversion_factor_yield": "6% (CME; rounded to 4 decimals per deliverable and month).",
        "source": (
            "CME Globex ZT / 2-Year U.S. Treasury Note futures; "
            "https://www.cmegroup.com/education/courses/introduction-to-treasuries/"
            "understand-treasuries-contract-specifications"
        ),
    },
    "FV": {
        "product": "FV",
        "globex": "ZF",
        "name": "5-Year U.S. Treasury Note",
        "face_notional_usd": 100_000.0,
        "point_value_usd": 1_000.0,
        "tick_size_points": 0.25 / 32.0,
        "tick_value_usd": 7.8125,
        "thirty_second_point_value_usd": 31.25,
        "delivery_months": [3, 6, 9, 12],
        "deliverable_summary": (
            "Original term ≤ 5y3m; remaining maturity ≥ 4y2m as of the first day "
            "of the delivery month."
        ),
        "last_trading_day_rule": "Last business day of the contract month.",
        "invoice": "Futures settlement × conversion factor + accrued interest.",
        "conversion_factor_yield": "6% (CME; rounded to 4 decimals per deliverable and month).",
        "source": (
            "CME 5-Year U.S. Treasury Note futures (ZF); "
            "https://www.cmegroup.com/education/courses/introduction-to-treasuries/"
            "understand-treasuries-contract-specifications"
        ),
    },
    "TY": {
        "product": "TY",
        "globex": "ZN",
        "name": "10-Year U.S. Treasury Note",
        "face_notional_usd": 100_000.0,
        "point_value_usd": 1_000.0,
        "tick_size_points": 0.5 / 32.0,
        "tick_value_usd": 15.625,
        "thirty_second_point_value_usd": 31.25,
        "delivery_months": [3, 6, 9, 12],
        "deliverable_summary": (
            "Remaining maturity at least 6.5 years but less than 8 years from the "
            "first day of the delivery month (current CME contract specs)."
        ),
        "last_trading_day_rule": (
            "Seven business days before the last business day of the contract month."
        ),
        "invoice": "Futures settlement × conversion factor + accrued interest.",
        "conversion_factor_yield": "6% (CME; rounded to 4 decimals per deliverable and month).",
        "source": (
            "CME 10-Year U.S. Treasury Note futures (ZN); "
            "https://www.cmegroup.com/markets/interest-rates/us-treasury/"
            "10-year-us-treasury-note.contractSpecs.html"
        ),
    },
}

_DATED = re.compile(r"^(TU|ZT|FV|ZF|TY|ZN)[_-](20\d{2})-(\d{2})$")
_CODED = re.compile(r"^(TU|ZT|FV|ZF|TY|ZN)([FGHJKMNQUVXZ])(\d)$")

_DV01_LIMITS = (
    "CTD-aware approximation: ignores switch option, timing option, and end-of-month option."
)


def contract_spec(product: str) -> dict:
    """Static CME contract economics for TU, FV, or TY."""
    key = _PRODUCT_ALIASES.get(str(product or "").strip().upper())
    if key is None:
        raise KeyError(f"Unknown treasury futures product: {product!r}")
    row = dict(_SPECS[key])
    row["dv01_method_limits"] = _DV01_LIMITS
    row["quote"] = "price_par_100_points"
    row["venue"] = "CME Globex"
    row["currency"] = "USD"
    return row


def _instrument_id(product: str, year: int, month: int) -> str:
    return f"{product}_{year:04d}-{month:02d}"


def _expiry(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def parse_treasury_id(instrument: str) -> dict[str, Any] | None:
    if not instrument or not isinstance(instrument, str):
        return None
    raw = instrument.strip().upper().replace(" ", "")
    dated = _DATED.fullmatch(raw)
    if dated:
        alias = dated.group(1)
        product = _PRODUCT_ALIASES.get(alias)
        if product is None:
            return {"status": "unsupported", "reason": "unknown product", "instrument": raw}
        year = int(dated.group(2))
        month = int(dated.group(3))
        if month not in _DELIVERY_MONTHS:
            return {
                "status": "unsupported",
                "reason": "invalid delivery month",
                "product": product,
                "expiry": _expiry(year, month),
                "instrument": _instrument_id(product, year, month),
            }
        return {
            "status": "ok",
            "product": product,
            "globex": _GLOBEX[product],
            "alias": alias,
            "year": year,
            "month": month,
            "expiry": _expiry(year, month),
            "instrument": _instrument_id(product, year, month),
        }
    coded = _CODED.fullmatch(raw)
    if coded:
        alias = coded.group(1)
        product = _PRODUCT_ALIASES[alias]
        month = _CME_MONTH[coded.group(2)]
        year = 2020 + int(coded.group(3))
        base = {
            "product": product,
            "globex": _GLOBEX[product],
            "alias": alias,
            "year": year,
            "month": month,
            "expiry": _expiry(year, month),
            "instrument": _instrument_id(product, year, month),
            "coded": raw,
        }
        if month not in _DELIVERY_MONTHS:
            return {
                **base,
                "status": "unsupported",
                "reason": "invalid delivery month",
            }
        return {**base, "status": "ok"}
    return None


def _expression_type(expression: Any) -> str | None:
    if isinstance(expression, Mapping):
        t = expression.get("type")
        if isinstance(t, str):
            return t
    return None


def _treasury_block(market_state: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if not isinstance(market_state, Mapping):
        return None
    block = market_state.get("treasury_futures")
    return block if isinstance(block, Mapping) else None


def _contract_row(market_state: Mapping[str, Any] | None, instrument_id: str) -> Mapping[str, Any] | None:
    block = _treasury_block(market_state)
    if block is None:
        return None
    contracts = block.get("contracts")
    if not isinstance(contracts, Mapping):
        return None
    row = contracts.get(instrument_id)
    return row if isinstance(row, Mapping) else None


def _positive_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out <= 0 or math.isnan(out) or math.isinf(out):
        return None
    return out


def _has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _ctd_dv01_per_100(row: Mapping[str, Any]) -> tuple[float | None, list[str]]:
    """Return (ctd_dv01_per_100_face, missing dotted paths under the contract row)."""
    missing: list[str] = []
    direct = _positive_float(row.get("ctd_dv01_per_100_face"))
    if direct is not None:
        if not _has_text(row.get("ctd_source")):
            missing.append("ctd_source")
        if not _has_text(row.get("ctd_as_of")):
            missing.append("ctd_as_of")
        if missing:
            return None, missing
        return direct, []

    mod = _positive_float(row.get("ctd_modified_duration"))
    dirty = _positive_float(row.get("ctd_dirty_price_per_100"))
    if mod is None:
        missing.append("ctd_modified_duration")
    if dirty is None:
        missing.append("ctd_dirty_price_per_100")
    if not _has_text(row.get("ctd_source")):
        missing.append("ctd_source")
    if not _has_text(row.get("ctd_as_of")):
        missing.append("ctd_as_of")
    if mod is None or dirty is None:
        return None, missing
    return mod * dirty * 0.0001, missing


def _conversion_factor(row: Mapping[str, Any]) -> tuple[float | None, list[str]]:
    missing: list[str] = []
    cf = _positive_float(row.get("conversion_factor"))
    if cf is None:
        missing.append("conversion_factor")
    if not _has_text(row.get("conversion_factor_source")):
        missing.append("conversion_factor_source")
    if not _has_text(row.get("conversion_factor_as_of")):
        missing.append("conversion_factor_as_of")
    if cf is None:
        return None, missing
    if missing:
        return None, missing
    return cf, []


def futures_dv01_per_contract(
    product: str,
    *,
    conversion_factor: float,
    ctd_dv01_per_100: float,
) -> float:
    """CTD-aware contract DV01 (USD per 1bp parallel shift in CTD yield, via supplied inputs)."""
    spec = contract_spec(product)
    face = float(spec["face_notional_usd"])
    return ctd_dv01_per_100 * (face / 100.0) / conversion_factor


def _price_from_row(row: Mapping[str, Any] | None) -> tuple[float | None, str | None, str | None]:
    if row is None:
        return None, None, None
    price = row.get("futures_price")
    try:
        price_f = float(price)
    except (TypeError, ValueError):
        return None, None, None
    if math.isnan(price_f) or math.isinf(price_f):
        return None, None, None
    source = row.get("price_source") if _has_text(row.get("price_source")) else None
    as_of = row.get("price_as_of") if _has_text(row.get("price_as_of")) else None
    return price_f, source, as_of


def _prefix_missing(instrument_id: str, suffixes: list[str]) -> list[str]:
    return [f"treasury_futures.contracts.{instrument_id}.{s}" for s in suffixes]


def _contract_row_sourced(row: Mapping[str, Any]) -> bool:
    return _has_text(row.get("price_source")) or _has_text(row.get("source"))


def _canonical_product_root(instrument: str) -> tuple[str, str] | None:
    """Return (canonical product TU/FV/TY, root symbol as passed) for bare roots only."""
    if not instrument or not isinstance(instrument, str):
        return None
    raw = instrument.strip().upper().replace(" ", "")
    product = _PRODUCT_ALIASES.get(raw)
    if product is None:
        return None
    if parse_treasury_id(raw) is not None:
        return None
    return product, raw


def _sourced_dated_contracts(
    market_state: Mapping[str, Any] | None,
    product: str,
) -> list[tuple[str, dict[str, Any]]]:
    block = _treasury_block(market_state)
    if block is None:
        return []
    contracts = block.get("contracts")
    if not isinstance(contracts, Mapping):
        return []
    out: list[tuple[str, dict[str, Any]]] = []
    for contract_id, row in contracts.items():
        if not isinstance(row, Mapping):
            continue
        if not _contract_row_sourced(row):
            continue
        parsed = parse_treasury_id(str(contract_id))
        if parsed is None or parsed.get("status") != "ok":
            continue
        if str(parsed.get("product")) != product:
            continue
        out.append((str(parsed["instrument"]), parsed))
    return out


def resolve_treasury_instrument(
    instrument: str,
    market_state: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Resolve a treasury futures id to a dated contract using market_state when needed."""
    parsed = parse_treasury_id(instrument)
    if parsed is not None:
        if parsed.get("status") == "ok":
            return {
                "status": "ok",
                "parsed": parsed,
                "instrument_id": str(parsed["instrument"]),
                "resolved_from": None,
            }
        return {
            "status": "unsupported",
            "parsed": parsed,
            "instrument_id": parsed.get("instrument"),
            "reason": parsed.get("reason"),
            "resolved_from": None,
        }

    root_info = _canonical_product_root(instrument)
    if root_info is None:
        return {
            "status": "unsupported",
            "reason": f"Not a supported treasury futures instrument: {instrument!r}",
            "missing_inputs": [],
            "resolved_from": None,
        }

    product, root_symbol = root_info
    block = _treasury_block(market_state)
    missing_inputs: list[str] = [f"treasury_futures.contracts.{product}"]

    def _failure(reason: str, extra_missing: list[str] | None = None) -> dict[str, Any]:
        mi = list(missing_inputs)
        if extra_missing:
            mi.extend(extra_missing)
        return {
            "status": "missing_input",
            "bookable": False,
            "reason": reason,
            "missing_inputs": sorted(dict.fromkeys(mi)),
            "product": product,
            "resolved_from": root_symbol,
        }

    if block is None:
        return _failure(
            "Preflight requires a sourced dated treasury futures contract with an explicit expiry; "
            f"no contract rows for {product}."
        )

    front_map = block.get("front")
    if isinstance(front_map, Mapping) and product in front_map:
        front_key = f"treasury_futures.front.{product}"
        missing_inputs.append(front_key)
        front_id = str(front_map[product])
        front_parsed = parse_treasury_id(front_id)
        front_row = _contract_row(market_state, front_id)
        if (
            front_parsed is None
            or front_parsed.get("status") != "ok"
            or str(front_parsed.get("product")) != product
        ):
            return _failure(
                f"treasury_futures.front.{product} names {front_id!r}, which is not a valid "
                f"sourced {product} dated contract.",
                [front_key, f"treasury_futures.contracts.{front_id}"],
            )
        if front_row is None or not _contract_row_sourced(front_row):
            return _failure(
                f"treasury_futures.front.{product} names {front_id!r}, which has no price source.",
                [front_key, f"treasury_futures.contracts.{front_id}"],
            )
        resolved_id = str(front_parsed["instrument"])
        return {
            "status": "ok",
            "parsed": front_parsed,
            "instrument_id": resolved_id,
            "resolved_from": root_symbol,
        }

    sourced = _sourced_dated_contracts(market_state, product)
    front_flagged = [
        (cid, p)
        for cid, p in sourced
        if _row_front_flag(_contract_row(market_state, cid) or {})
    ]

    if len(front_flagged) == 1:
        cid, p = front_flagged[0]
        return {
            "status": "ok",
            "parsed": p,
            "instrument_id": cid,
            "resolved_from": root_symbol,
        }
    if len(front_flagged) > 1:
        ids = sorted(c for c, _ in front_flagged)
        return _failure(
            f"Ambiguous {product} expiry: multiple contracts marked front: {', '.join(ids)}."
        )

    if len(sourced) == 1:
        cid, p = sourced[0]
        return {
            "status": "ok",
            "parsed": p,
            "instrument_id": cid,
            "resolved_from": root_symbol,
        }
    if len(sourced) == 0:
        return _failure(
            "Preflight requires a sourced dated treasury futures contract with an explicit expiry; "
            f"no sourced contract rows for {product}."
        )

    ids = sorted(cid for cid, _ in sourced)
    return _failure(
        f"Ambiguous {product} expiry: multiple sourced contracts "
        f"({', '.join(ids)}); set treasury_futures.front or pass an explicit dated id."
    )


def _row_front_flag(row: Mapping[str, Any]) -> bool:
    return row.get("front") is True


def _assess_from_resolved(
    resolution: dict[str, Any],
    *,
    expr_type: str | None,
    market_state: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if resolution.get("status") == "missing_input":
        return {
            "family": "treasury_future",
            "instrument": resolution.get("resolved_from") or "",
            "expression_type": expr_type or "treasury_future",
            "product": resolution.get("product"),
            "expiry": None,
            "status": "missing_input",
            "bookable": False,
            "reason": resolution.get("reason"),
            "missing_inputs": resolution.get("missing_inputs") or [],
            "mark_status": "unavailable",
            "mark_source": None,
            "futures_price": None,
            "futures_dv01_per_contract": None,
            "dv01_method_limits": _DV01_LIMITS,
            "resolved_from": resolution.get("resolved_from"),
        }

    parsed = resolution["parsed"]
    instrument_id = str(resolution["instrument_id"])
    resolved_from = resolution.get("resolved_from")
    base: dict[str, Any] = {
        "family": "treasury_future",
        "instrument": instrument_id,
        "expression_type": expr_type or "treasury_future",
        "product": parsed.get("product"),
        "expiry": parsed.get("expiry"),
    }
    if resolved_from:
        base["resolved_from"] = resolved_from

    if resolution.get("status") == "unsupported" or parsed.get("status") == "unsupported":
        return {
            **base,
            "status": "unsupported",
            "bookable": False,
            "reason": resolution.get("reason") or parsed.get("reason"),
            "missing_inputs": [],
            "mark_status": "unavailable",
            "mark_source": None,
            "futures_dv01_per_contract": None,
            "dv01_method_limits": _DV01_LIMITS,
        }

    row = _contract_row(market_state, instrument_id)
    price, price_source, _price_as_of = _price_from_row(row)
    missing: list[str] = []

    if price is None:
        missing.append(f"treasury_futures.contracts.{instrument_id}.futures_price")
        mark_status = "unavailable"
        mark_source = None
    else:
        mark_status = "ok"
        mark_source = price_source

    cf_val: float | None = None
    ctd_per_100: float | None = None
    futures_dv01: float | None = None

    if row is not None:
        cf_val, cf_missing = _conversion_factor(row)
        if cf_missing:
            missing.extend(_prefix_missing(instrument_id, cf_missing))
        ctd_per_100, ctd_missing = _ctd_dv01_per_100(row)
        if ctd_missing:
            missing.extend(_prefix_missing(instrument_id, ctd_missing))
        if cf_val is not None and ctd_per_100 is not None:
            futures_dv01 = futures_dv01_per_contract(
                str(parsed["product"]),
                conversion_factor=cf_val,
                ctd_dv01_per_100=ctd_per_100,
            )
    else:
        missing.extend(
            [
                f"treasury_futures.contracts.{instrument_id}.conversion_factor",
                f"treasury_futures.contracts.{instrument_id}.conversion_factor_source",
                f"treasury_futures.contracts.{instrument_id}.conversion_factor_as_of",
                f"treasury_futures.contracts.{instrument_id}.ctd_dv01_per_100_face",
                f"treasury_futures.contracts.{instrument_id}.ctd_source",
                f"treasury_futures.contracts.{instrument_id}.ctd_as_of",
            ]
        )

    missing = sorted(dict.fromkeys(missing))
    bookable = price is not None and futures_dv01 is not None and not missing

    if bookable:
        status = "ok"
        reason = None
    else:
        status = "missing_input"
        reason = "missing required treasury futures price or CTD risk inputs"

    return {
        **base,
        "status": status,
        "bookable": bool(bookable),
        "reason": reason,
        "missing_inputs": missing,
        "mark_status": mark_status,
        "mark_source": mark_source,
        "futures_price": price,
        "futures_dv01_per_contract": futures_dv01,
        "dv01_method_limits": _DV01_LIMITS,
    }


def assess_treasury(
    instrument: str,
    expression: Any,
    market_state: Mapping[str, Any] | None,
    notional_usd: float | None = None,
) -> dict[str, Any] | None:
    del notional_usd
    expr_type = _expression_type(expression)
    if expr_type is not None and expr_type != "treasury_future":
        return None

    parsed = parse_treasury_id(instrument)
    if parsed is None and expr_type != "treasury_future":
        return None

    resolution = resolve_treasury_instrument(instrument, market_state)
    if resolution.get("status") == "unsupported" and parsed is None and expr_type is None:
        return None

    return _assess_from_resolved(resolution, expr_type=expr_type, market_state=market_state)


def _whole_contracts(notional_usd: float, face: float) -> int:
    if notional_usd <= 0 or face <= 0:
        return 0
    return int(Decimal(str(notional_usd / face)).to_integral_value(rounding=ROUND_FLOOR))


def build_treasury_position(
    instrument: str,
    *,
    side: str,
    notional_usd: float,
    market_state: Mapping[str, Any] | None,
) -> dict[str, Any]:
    resolution = resolve_treasury_instrument(instrument, market_state)
    if resolution.get("status") != "ok":
        reason = resolution.get("reason") or f"Cannot resolve treasury futures instrument {instrument!r}"
        raise ValueError(reason)

    parsed = resolution["parsed"]
    product = str(parsed["product"])
    spec = contract_spec(product)
    instrument_id = str(resolution["instrument_id"])
    row = _contract_row(market_state, instrument_id)
    price, _, _ = _price_from_row(row)
    if price is None:
        raise ValueError(f"Missing futures price for {instrument_id}")

    cf_val, cf_missing = _conversion_factor(row or {})
    ctd_per_100, ctd_missing = _ctd_dv01_per_100(row or {})
    if cf_missing or ctd_missing or cf_val is None or ctd_per_100 is None:
        parts = cf_missing + ctd_missing
        raise ValueError(
            f"Missing CTD/conversion-factor inputs for {instrument_id}: {', '.join(parts)}"
        )

    face = float(spec["face_notional_usd"])
    contracts = _whole_contracts(float(notional_usd), face)
    if contracts < 1:
        raise ValueError(
            f"Notional {notional_usd} USD below one {product} contract face {face} USD"
        )

    futures_dv01 = futures_dv01_per_contract(
        product,
        conversion_factor=cf_val,
        ctd_dv01_per_100=ctd_per_100,
    )
    side_norm = str(side).strip().lower()
    if side_norm not in {"long", "short"}:
        raise ValueError(f"side must be long or short, got {side!r}")

    row = row or {}
    return {
        "instrument": instrument_id,
        "product": product,
        "asset_class": "rates",
        "side": side_norm,
        "notional_usd": float(notional_usd),
        "contracts": contracts,
        "face_notional_usd": face,
        "point_value_usd": float(spec["point_value_usd"]),
        "tick_value_usd": float(spec["tick_value_usd"]),
        "tick_size_points": float(spec["tick_size_points"]),
        "valuation_method": "instrument_dv01",
        "price_unit": "futures_points",
        "canonical_risk": "ctd_cf_dv01",
        "isolated": False,
        "entry_price": price,
        "mark_price": price,
        "futures_dv01_per_contract": futures_dv01,
        "dv01_usd": contracts * futures_dv01,
        "conversion_factor": cf_val,
        "conversion_factor_source": row.get("conversion_factor_source"),
        "conversion_factor_as_of": row.get("conversion_factor_as_of"),
        "ctd_source": row.get("ctd_source"),
        "ctd_as_of": row.get("ctd_as_of"),
        "dv01_source_as_of": row.get("ctd_as_of"),
        "risk_status": "ok",
        "dv01_method_limits": _DV01_LIMITS,
    }


def refresh_treasury_risk(position: dict, market_state: Mapping[str, Any] | None) -> None:
    """Recompute CTD/conversion-factor DV01 from current market_state; does not touch price P&L fields."""
    instrument_id = str(position.get("instrument") or "")
    parsed = parse_treasury_id(instrument_id)
    root = _canonical_product_root(instrument_id)
    if parsed is None or parsed.get("status") != "ok" or root is not None:
        position["futures_dv01_per_contract"] = None
        position["dv01_usd"] = None
        position["risk_status"] = "unavailable"
        position["risk_unavailable_reason"] = (
            "Treasury futures risk requires a dated contract id with explicit expiry; "
            f"position instrument {instrument_id!r} is not dated."
        )
        return

    product = str(parsed["product"])
    row = _contract_row(market_state, instrument_id)
    if row is None:
        position["futures_dv01_per_contract"] = None
        position["dv01_usd"] = None
        position["risk_status"] = "unavailable"
        position["risk_unavailable_reason"] = (
            f"Missing treasury_futures.contracts.{instrument_id} for risk refresh."
        )
        return

    cf_val, cf_missing = _conversion_factor(row)
    ctd_per_100, ctd_missing = _ctd_dv01_per_100(row)
    if cf_missing or ctd_missing or cf_val is None or ctd_per_100 is None:
        position["futures_dv01_per_contract"] = None
        position["dv01_usd"] = None
        position["risk_status"] = "unavailable"
        missing = cf_missing + ctd_missing
        position["risk_unavailable_reason"] = (
            f"Missing CTD/conversion-factor inputs for {instrument_id}: {', '.join(missing)}"
        )
        return

    futures_dv01 = futures_dv01_per_contract(
        product,
        conversion_factor=cf_val,
        ctd_dv01_per_100=ctd_per_100,
    )
    try:
        contracts = int(position["contracts"])
    except (KeyError, TypeError, ValueError):
        contracts = 0

    position["futures_dv01_per_contract"] = futures_dv01
    position["dv01_usd"] = contracts * futures_dv01
    position["conversion_factor"] = cf_val
    position["conversion_factor_source"] = row.get("conversion_factor_source")
    position["conversion_factor_as_of"] = row.get("conversion_factor_as_of")
    position["ctd_source"] = row.get("ctd_source")
    position["ctd_as_of"] = row.get("ctd_as_of")
    cf_as_of = row.get("conversion_factor_as_of")
    ctd_as_of = row.get("ctd_as_of")
    if _has_text(cf_as_of) and _has_text(ctd_as_of) and cf_as_of != ctd_as_of:
        position["dv01_source_as_of"] = {
            "conversion_factor_as_of": cf_as_of,
            "ctd_as_of": ctd_as_of,
        }
    else:
        position["dv01_source_as_of"] = ctd_as_of if _has_text(ctd_as_of) else cf_as_of
    position["risk_status"] = "ok"
    position.pop("risk_unavailable_reason", None)


def _side_sign(side: str) -> float:
    return 1.0 if str(side).strip().lower() == "long" else -1.0


def treasury_pnl_usd(position: Mapping[str, Any], *, mark_price: float | None = None) -> float | None:
    try:
        entry = float(position["entry_price"])
        contracts = int(position["contracts"])
        point_value = float(position["point_value_usd"])
    except (KeyError, TypeError, ValueError):
        return None
    mark = entry if mark_price is None else float(mark_price)
    side = position.get("side", "long")
    return _side_sign(str(side)) * contracts * (mark - entry) * point_value


def treasury_shock_risk_usd(position: Mapping[str, Any]) -> float | None:
    try:
        contracts = int(position["contracts"])
        dv01 = float(position["futures_dv01_per_contract"])
    except (KeyError, TypeError, ValueError):
        return None
    if dv01 <= 0:
        return None
    return abs(contracts * dv01 * 100.0)


def roll_quote(
    market_state: Mapping[str, Any] | None,
    front_id: str,
    back_id: str,
) -> dict[str, Any]:
    front = parse_treasury_id(front_id)
    back = parse_treasury_id(back_id)
    if front is None or back is None:
        return {"status": "unsupported", "reason": "invalid contract id"}
    if front.get("status") != "ok" or back.get("status") != "ok":
        return {"status": "unsupported", "reason": "invalid contract id"}
    if front.get("product") != back.get("product"):
        return {"status": "unsupported", "reason": "roll requires the same product"}

    product = str(front["product"])
    spec = contract_spec(product)
    tick_size = float(spec["tick_size_points"])
    front_inst = str(front["instrument"])
    back_inst = str(back["instrument"])

    front_row = _contract_row(market_state, front_inst)
    back_row = _contract_row(market_state, back_inst)
    front_px, front_src, front_as_of = _price_from_row(front_row)
    back_px, back_src, back_as_of = _price_from_row(back_row)

    missing: list[str] = []
    if front_px is None:
        missing.append(f"treasury_futures.contracts.{front_inst}.futures_price")
    if back_px is None:
        missing.append(f"treasury_futures.contracts.{back_inst}.futures_price")
    if missing:
        return {
            "status": "missing_input",
            "missing_inputs": missing,
            "front_id": front_inst,
            "back_id": back_inst,
            "product": product,
        }

    assert front_px is not None and back_px is not None
    roll_points = back_px - front_px
    return {
        "status": "ok",
        "product": product,
        "front_id": front_inst,
        "back_id": back_inst,
        "front_price": front_px,
        "back_price": back_px,
        "front_price_source": front_src,
        "back_price_source": back_src,
        "front_price_as_of": front_as_of,
        "back_price_as_of": back_as_of,
        "roll_points": roll_points,
        "roll_ticks": roll_points / tick_size,
        "tick_size_points": tick_size,
    }
