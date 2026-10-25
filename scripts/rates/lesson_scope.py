"""Evidence-grounded lesson scopes.

Scope fields are copied from the linked trade ledger: instrument, asset class,
stored paper-expression type, and the curve family already recorded on that
expression. Lesson text, future rule, and history are not rewritten. Retrieval
history is not invented.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from scripts.trading.learning import empty_scope, normalize_scope

_CURVE = {
    "SOFR": {"currency": "USD", "country": "US", "family": "sofr"},
    "CORRA": {"currency": "CAD", "country": "CA", "family": "corra"},
    "AONIA": {"currency": "AUD", "country": "AU", "family": "aonia"},
    "SR3": {"currency": "USD", "country": "US", "family": "sofr"},
    "CRA": {"currency": "CAD", "country": "CA", "family": "corra"},
    "IB": {"currency": "AUD", "country": "AU", "family": "aonia"},
}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _scope_populated(scope: Mapping[str, Any] | None) -> bool:
    normalized = normalize_scope(scope)
    return any(
        (
            normalized["instruments"],
            normalized["instrument_family"],
            normalized["asset_class"],
            normalized["countries"],
            normalized["currencies"],
            normalized["setup_type"],
            normalized["market_drivers"],
            normalized["catalyst_type"],
            normalized["failure_mode"],
            normalized["decision_dimension"],
        )
    )


def scope_from_trade(trade: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    scope = empty_scope()
    fields: list[str] = []
    instruments: list[str] = []
    instrument = _text(trade.get("instrument"))
    if instrument:
        instruments.append(instrument)
        fields.append("instrument")
    expression = trade.get("paper_expression") if isinstance(trade.get("paper_expression"), Mapping) else {}
    curve_id = _text(expression.get("curve_id"))
    curve_key = curve_id.upper() if curve_id else None
    meta = _CURVE.get(curve_key or "")
    if curve_key:
        fields.append("paper_expression.curve_id")
        scope["instrument_family"] = meta["family"] if meta else curve_key.lower()
    for expiry in expression.get("expiries") or []:
        expiry_text = _text(expiry)
        if curve_key and expiry_text:
            alias = f"{curve_key}_{expiry_text}"
            if alias not in instruments:
                instruments.append(alias)
            fields.append("paper_expression.expiries")
    kind = _text(expression.get("type"))
    if kind:
        scope["setup_type"] = kind
        fields.append("paper_expression.type")
    asset = _text(trade.get("asset_class"))
    if asset:
        scope["asset_class"] = asset
        fields.append("asset_class")
    if meta:
        scope["currencies"] = [meta["currency"]]
        scope["countries"] = [meta["country"]]
        fields.append("paper_expression.curve_id.currency")
        fields.append("paper_expression.curve_id.country")
    elif instrument:
        prefix = instrument.split("_", 1)[0].upper()
        inferred = _CURVE.get(prefix)
        compact = instrument.replace("_", "").upper()
        if inferred:
            scope["instrument_family"] = scope["instrument_family"] or inferred["family"]
            scope["currencies"] = [inferred["currency"]]
            scope["countries"] = [inferred["country"]]
            fields.append("instrument.prefix")
        elif re.fullmatch(r"[A-Z]{6}", compact):
            scope["currencies"] = [compact[:3], compact[3:]]
            fields.append("instrument.fx_pair")
    scope["instruments"] = instruments
    evidence = {
        "method": "ledger_identity_fields",
        "trade_id": trade.get("trade_id"),
        "fields": sorted(set(fields)),
        "retrievals_backfilled": False,
        "text_modified": False,
        "history_modified": False,
    }
    if not fields:
        evidence["status"] = "insufficient_evidence"
    else:
        evidence["status"] = "scoped_from_trade"
    return normalize_scope(scope), evidence


def backfill_lesson(lesson: Mapping[str, Any], trades_by_id: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Return a lesson copy. Existing non-empty scope, text, and history stay."""
    out = dict(lesson)
    if _scope_populated(out.get("scope") if isinstance(out.get("scope"), Mapping) else None):
        out["scope_evidence"] = {
            "method": "preexisting_scope",
            "status": "left_unchanged",
            "retrievals_backfilled": False,
            "text_modified": False,
            "history_modified": False,
        }
        return out
    trade_ids = [str(item) for item in (out.get("trade_ids") or []) if item]
    chosen = None
    for trade_id in trade_ids:
        trade = trades_by_id.get(trade_id)
        if isinstance(trade, Mapping):
            chosen = trade
            break
    if chosen is None:
        out["scope"] = normalize_scope(out.get("scope"))
        out["scope_evidence"] = {
            "method": "ledger_identity_fields",
            "status": "insufficient_evidence",
            "trade_ids": trade_ids,
            "retrievals_backfilled": False,
            "text_modified": False,
            "history_modified": False,
        }
        return out
    scope, evidence = scope_from_trade(chosen)
    out["scope"] = scope
    out["scope_evidence"] = evidence
    return out
