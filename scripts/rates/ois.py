"""USD SOFR OIS paper economics (OTC).

Convention documented for integrators; no live curve fetch in this module.

USD SOFR OIS with tenors at or beyond 1Y uses annual-annual fixed/float payments,
ACT/360 on both legs, spot start T+2. The par fixed rate in percent is

    S = 100 × (DF_start − DF_end) / Σ(accrual_i × DF_pay_i)

where DF_start is the discount factor at the swap start and DF_end at the final
payment. For spot-start structures only, DF_start = 1.0 may be used as a
*definitional* anchor (``definitional_spot_discount_factor``); it is not an
observed market quote.

DV01 in USD: ``notional_usd × annuity × 0.0001`` with
``annuity = Σ(accrual_i × DF_pay_i)``. Receive fixed (long) profits when the
par rate falls.

Do not use Treasury or government ``official_curves`` as SOFR OIS inputs.
"""

from __future__ import annotations

from typing import Any, Mapping

from scripts.rates.structures import StructureError

OIS_TYPE = "usd_sofr_ois"
FAMILY = "usd_sofr_ois"
_SUPPORTED = frozenset({(0, 2), (1, 1)})
_BAD_CURVE_KINDS = frozenset({"treasury", "government", "official", "proxy"})
_QUOTE_TYPES = frozenset({"observed_par", "derived_from_discount_factors"})


def instrument_id(*, start_years: float, tenor_years: float) -> str:
    start = int(start_years)
    tenor = int(tenor_years)
    if (start, tenor) == (0, 2):
        return "USD_SOFR_OIS_2Y"
    if (start, tenor) == (1, 1):
        return "USD_SOFR_OIS_1Y1Y"
    raise StructureError(
        f"unsupported USD SOFR OIS start_years={start_years} tenor_years={tenor_years}; "
        "supported: spot 2Y and 1Y1Y forward"
    )


def _require_block(market_state: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(market_state, Mapping):
        if market_state is not None:
            pass
        if isinstance(market_state, Mapping) and market_state.get("official_curves"):
            raise StructureError(
                "government official curve is not a SOFR OIS quote; missing usd_sofr_ois"
            )
        raise StructureError("usd_sofr_ois block absent")
    block = market_state.get("usd_sofr_ois")
    if not isinstance(block, Mapping):
        if market_state.get("official_curves"):
            raise StructureError(
                "government official curve is not a SOFR OIS quote; missing usd_sofr_ois"
            )
        raise StructureError("usd_sofr_ois block absent")
    kind = str(block.get("curve_kind") or "").lower()
    if kind in _BAD_CURVE_KINDS or kind != "sofr_ois":
        raise StructureError(
            f"usd_sofr_ois.curve_kind must be sofr_ois, got {block.get('curve_kind')!r}"
        )
    if str(block.get("status") or "") != "ok":
        raise StructureError("usd_sofr_ois.status must be ok")
    if not str(block.get("source") or "").strip():
        raise StructureError("usd_sofr_ois.source is required")
    if not str(block.get("as_of") or "").strip():
        raise StructureError("usd_sofr_ois.as_of is required")
    return block


def _require_field(row: Mapping[str, Any], block_id: str, field: str) -> Any:
    if field not in row or row.get(field) in (None, ""):
        raise StructureError(f"usd_sofr_ois.instruments.{block_id}.{field}")
    return row[field]


def _instrument_row(block: Mapping[str, Any], inst_id: str) -> Mapping[str, Any]:
    instruments = block.get("instruments")
    if not isinstance(instruments, Mapping):
        raise StructureError(f"usd_sofr_ois.instruments.{inst_id}")
    row = instruments.get(inst_id)
    if not isinstance(row, Mapping):
        raise StructureError(f"usd_sofr_ois.instruments.{inst_id}")
    return row


def build_ois(
    expression: Mapping[str, Any],
    *,
    side: str = "long",
    notional_usd: float,
    market_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    kind = str(expression.get("type") or "")
    if kind != OIS_TYPE:
        raise StructureError(f"expected expression type {OIS_TYPE!r}, got {kind!r}")
    if side not in {"long", "short"}:
        raise StructureError("structure side must be long or short")
    try:
        start_years = float(expression.get("start_years"))
        tenor_years = float(expression.get("tenor_years"))
    except (TypeError, ValueError) as exc:
        raise StructureError("usd_sofr_ois requires numeric start_years and tenor_years") from exc

    if (int(start_years), int(tenor_years)) not in _SUPPORTED:
        instrument_id(start_years=start_years, tenor_years=tenor_years)

    inst_id = instrument_id(start_years=start_years, tenor_years=tenor_years)
    explicit = expression.get("instrument")
    if explicit not in (None, "") and str(explicit) != inst_id:
        raise StructureError(f"refusing silent substitution: expression instrument {explicit!r} != {inst_id}")

    if float(notional_usd) <= 0:
        raise StructureError("notional_usd must be positive")

    block = _require_block(market_state)
    row = _instrument_row(block, inst_id)

    row_kind = str(_require_field(row, inst_id, "curve_kind")).lower()
    if row_kind != "sofr_ois":
        raise StructureError(f"usd_sofr_ois.instruments.{inst_id}.curve_kind must be sofr_ois")

    if str(_require_field(row, inst_id, "status")) != "ok":
        raise StructureError(f"usd_sofr_ois.instruments.{inst_id}.status must be ok")

    par = float(_require_field(row, inst_id, "par_rate_percent"))
    annuity = float(_require_field(row, inst_id, "annuity"))
    if annuity <= 0:
        raise StructureError(f"usd_sofr_ois.instruments.{inst_id}.annuity must be positive")

    quote_type = str(_require_field(row, inst_id, "quote_type"))
    if quote_type not in _QUOTE_TYPES:
        raise StructureError(f"usd_sofr_ois.instruments.{inst_id}.quote_type")

    source = str(_require_field(row, inst_id, "source"))
    as_of = str(_require_field(row, inst_id, "as_of"))

    if quote_type == "observed_par":
        mark_source = source
    else:
        mark_source = source if source.startswith("derived:usd_sofr_ois") else f"derived:usd_sofr_ois:{source}"

    dv01_usd = float(notional_usd) * annuity * 0.0001

    return {
        "valuation_method": "instrument_dv01",
        "family": FAMILY,
        "instrument": inst_id,
        "side": side,
        "notional_usd": float(notional_usd),
        "entry_rate": par,
        "mark_rate": par,
        "annuity": annuity,
        "dv01_usd": dv01_usd,
        "quote_type": quote_type,
        "mark_source": mark_source,
        "as_of": as_of,
        "contracts": None,
        "price_unit": "implied_rate_percent",
        "isolated": False,
        "structure_label": OIS_TYPE,
        "expression": dict(expression),
        "start_years": start_years,
        "tenor_years": tenor_years,
        "day_count": block.get("day_count") or "ACT/360",
    }


def ois_pnl_usd(position: Mapping[str, Any], *, mark_rate: float | None = None) -> float | None:
    dv01 = position.get("dv01_usd")
    entry = position.get("entry_rate")
    mark = mark_rate if mark_rate is not None else position.get("mark_rate")
    side = position.get("side")
    if dv01 in (None, "") or entry in (None, "") or mark in (None, ""):
        return None
    if side not in {"long", "short"}:
        return None
    try:
        dv01_f = float(dv01)
        entry_f = float(entry)
        mark_f = float(mark)
    except (TypeError, ValueError):
        return None
    sign = 1.0 if side == "long" else -1.0
    return -sign * dv01_f * (mark_f - entry_f) * 100.0


def par_from_sofr_ois_discount_factors(
    payments: list[dict],
    *,
    start_discount_factor: float,
    start_is_definitional: bool,
    start_years: float = 0,
    allow_definitional_only_for_spot: bool = True,
) -> dict[str, Any]:
    if allow_definitional_only_for_spot and start_is_definitional and float(start_years) != 0.0:
        raise ValueError(
            "definitional spot discount factor (DF_start=1) is only allowed for spot start (start_years=0)"
        )
    if not payments:
        raise ValueError("payments must be non-empty")
    annuity = 0.0
    sources: list[str] = []
    df_end: float | None = None
    for pay in payments:
        mat = pay.get("maturity_years")
        accrual = pay.get("accrual_act_360")
        df = pay.get("discount_factor")
        source = pay.get("source")
        if mat in (None, "") or accrual in (None, "") or df in (None, ""):
            raise ValueError(f"payment at maturity_years={mat!r} missing numeric accrual or discount_factor")
        src_l = str(source or "").lower()
        if "official_curves" in src_l or "treasury" in src_l:
            raise ValueError(f"payment at maturity_years={mat} refuses Treasury or official_curves source")
        try:
            acc_f = float(accrual)
            df_f = float(df)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"payment at maturity_years={mat!r} missing numeric accrual or discount_factor") from exc
        if acc_f <= 0 or df_f <= 0:
            raise ValueError(f"payment at maturity_years={mat} accrual and discount_factor must be positive")
        annuity += acc_f * df_f
        df_end = df_f
        sources.append(str(source or "unknown"))

    try:
        df_start = float(start_discount_factor)
    except (TypeError, ValueError) as exc:
        raise ValueError("start_discount_factor must be numeric") from exc
    if df_end is None:
        raise ValueError("payments must include a terminal discount factor")
    if annuity <= 0:
        raise ValueError("annuity must be positive")

    par_percent = 100.0 * (df_start - df_end) / annuity
    joined = "derived:usd_sofr_ois[" + ",".join(sources) + "]"
    return {
        "par_rate_percent": par_percent,
        "annuity": annuity,
        "quote_type": "derived_from_discount_factors",
        "source": joined,
        "definitional_spot_discount_factor": bool(start_is_definitional),
    }


def _ois_verdict_base(expression: Mapping[str, Any]) -> dict[str, Any]:
    try:
        inst = instrument_id(
            start_years=float(expression.get("start_years", 0)),
            tenor_years=float(expression.get("tenor_years", 0)),
        )
    except StructureError:
        inst = str(expression.get("instrument") or OIS_TYPE)
    return {
        "family": FAMILY,
        "instrument": inst,
        "expression_type": OIS_TYPE,
        "missing_inputs": [],
    }


def _classify_ois_error(exc: StructureError) -> tuple[str, list[str]]:
    msg = str(exc)
    missing: list[str] = []
    if msg.startswith("usd_sofr_ois."):
        missing.append(msg.split()[0] if " " in msg else msg)
        for token in msg.split():
            if token.startswith("usd_sofr_ois."):
                missing.append(token.rstrip("."))
        missing = list(dict.fromkeys(missing))
    if "refusing silent substitution" in msg:
        return "unsupported", missing
    if "unsupported USD SOFR OIS" in msg:
        return "unsupported", missing
    if "curve_kind must be sofr_ois" in msg and "instruments" not in msg:
        return "unsupported", missing
    if "government official curve is not a SOFR OIS quote" in msg or "block absent" in msg:
        if not missing:
            missing.append("usd_sofr_ois")
        return "missing_input", missing
    if missing:
        return "missing_input", missing
    if "unsupported" in msg.lower():
        return "unsupported", missing
    return "missing_input", missing


def assess_ois(
    expression: Mapping[str, Any],
    *,
    side: str = "long",
    notional_usd: float,
    market_state: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    if str(expression.get("type") or "") != OIS_TYPE:
        return None
    base = _ois_verdict_base(expression)
    try:
        built = build_ois(expression, side=side, notional_usd=notional_usd, market_state=market_state)
    except StructureError as exc:
        status, missing = _classify_ois_error(exc)
        mark_status = "missing" if status == "missing_input" else "unavailable"
        if status == "unsupported":
            mark_status = "not_applicable"
        return {
            **base,
            "status": status,
            "bookable": False,
            "reason": str(exc),
            "missing_inputs": missing or (["usd_sofr_ois"] if status == "missing_input" else []),
            "mark_status": mark_status,
            "mark_source": None,
        }
    return {
        **base,
        "status": "executable",
        "bookable": True,
        "reason": "USD SOFR OIS marked from usd_sofr_ois instrument row",
        "missing_inputs": [],
        "mark_status": "ok",
        "mark_source": built.get("mark_source"),
        "instrument": built.get("instrument"),
    }
