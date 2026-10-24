"""Audited restatement that does not write the ledger.

``restate_positions`` returns the legacy vintage and a corrected view. Callers
that want a migration must copy the report themselves. This module never
assigns into the source position.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from scripts.rates.contract_economics import fx_usd_per_unit, is_sovereign_instrument, parse_contract_id
from scripts.rates.structures import STRIP_TYPE
from scripts.rates.valuation import (
    INSTRUMENT_METHOD,
    LEGACY_METHOD,
    UNAVAILABLE,
    legacy_rate_pnl,
    value_position,
)


def _expression(position: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = position.get("paper_expression")
    return raw if isinstance(raw, Mapping) else {}


def corrected_view(position: Mapping[str, Any], *, market_state: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Corrected economics for one position. The input mapping is not mutated."""
    probe = deepcopy(dict(position))
    expression = _expression(probe)
    instrument = probe.get("instrument") if isinstance(probe.get("instrument"), str) else None
    if probe.get("legs"):
        valued = value_position(probe)
        valued["corrected_valuation_status"] = INSTRUMENT_METHOD if not valued.get("pnl_unavailable") else UNAVAILABLE
        return valued
    if expression.get("type") == STRIP_TYPE:
        return {
            "unrealized_pnl_usd": None,
            "pnl_unavailable": True,
            "valuation_method": UNAVAILABLE,
            "corrected_valuation_status": UNAVAILABLE,
            "isolated": True,
            "structure_label": STRIP_TYPE,
            "isolation_reason": (
                "strip average was booked as one synthetic mark; leg quantities were not stored, "
                "so it is not restated as a single contract or as a curve spread"
            ),
        }
    if is_sovereign_instrument(instrument):
        return {
            "unrealized_pnl_usd": None,
            "pnl_unavailable": True,
            "valuation_method": UNAVAILABLE,
            "corrected_valuation_status": UNAVAILABLE,
            "isolated": True,
            "isolation_reason": "sovereign holding has no verified DV01 or modified duration",
        }
    parsed = parse_contract_id(instrument)
    if parsed is None:
        if probe.get("asset_class") in {"rates", "curve", "rates_rv"}:
            return {
                "unrealized_pnl_usd": None,
                "pnl_unavailable": True,
                "valuation_method": UNAVAILABLE,
                "corrected_valuation_status": UNAVAILABLE,
                "isolated": True,
                "isolation_reason": "rates position has no verified contract economics",
            }
        return {
            "unrealized_pnl_usd": None,
            "pnl_unavailable": False,
            "valuation_method": "unchanged_non_rates",
            "corrected_valuation_status": "not_rates",
            "isolated": False,
        }
    fx, pair = fx_usd_per_unit(parsed.spec.currency, market_state, probe)
    if fx is None:
        return {
            "unrealized_pnl_usd": None,
            "pnl_unavailable": True,
            "valuation_method": UNAVAILABLE,
            "corrected_valuation_status": UNAVAILABLE,
            "isolated": True,
            "fx_pair": pair,
            "isolation_reason": f"{parsed.spec.currency} FX observation missing; USD P&L not invented",
            "contract": parsed.as_dict(),
        }
    probe["valuation_method"] = INSTRUMENT_METHOD
    probe["fx_usd_per_unit"] = fx
    probe["fx_pair"] = pair
    probe["contract_currency"] = parsed.spec.currency
    # Drop identity so the corrected formula is allowed to run.
    probe.pop("position_id", None)
    probe.pop("opened_at", None)
    valued = value_position(probe)
    valued["corrected_valuation_status"] = INSTRUMENT_METHOD if not valued.get("pnl_unavailable") else UNAVAILABLE
    valued["isolated"] = bool(valued.get("pnl_unavailable"))
    return valued


def restate_positions(
    positions: list[Mapping[str, Any]] | None,
    *,
    market_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    rows = []
    for position in positions or []:
        if not isinstance(position, Mapping):
            continue
        legacy = None
        legacy_error = None
        try:
            if position.get("asset_class") in {"rates", "curve", "rates_rv", "spot_fx"} or position.get("entry_price") not in (None, ""):
                legacy = legacy_rate_pnl(position)
        except Exception as exc:  # ledger rows can be incomplete; the report records that
            legacy_error = str(exc)
        corrected = corrected_view(position, market_state=market_state)
        rows.append(
            {
                "position_id": position.get("position_id"),
                "instrument": position.get("instrument"),
                "asset_class": position.get("asset_class"),
                "legacy": legacy,
                "legacy_error": legacy_error,
                "corrected": corrected,
                "ledger_mutated": False,
            }
        )
    return {
        "ledger_mutated": False,
        "overwrites_source": False,
        "rows": rows,
        "note": (
            "Corrected rows are a parallel vintage. Original decisions, marks, and "
            "realized ledgers are not modified by this report."
        ),
    }


def restate_books(books: Mapping[str, Any], *, market_state: Mapping[str, Any] | None = None) -> dict[str, Any]:
    seats = {}
    source = books.get("seats") if isinstance(books.get("seats"), Mapping) else None
    if source is None and isinstance(books.get("pms"), Mapping):
        source = books.get("pms")
    for seat, book in (source or {}).items():
        if not isinstance(book, Mapping):
            continue
        seats[str(seat)] = restate_positions(list(book.get("positions") or []), market_state=market_state)
    return {
        "ledger_mutated": False,
        "seats": seats,
        "note": "Replay is deterministic and read-only. Apply it only under a separate reviewed migration.",
    }
