"""Shared FX technical block for the freeze and the on-demand packet.

The block is computed once from in-memory closes before the freeze. After that,
readers copy it. They do not fetch, and a missing block does not veto unrelated
trades.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import date
from typing import Any


def technical_research_for_snapshot(
    *,
    fx_series: Mapping[str, Any] | None,
    as_of: date,
    clock: date | None = None,
    cross_asset_series: Mapping[str, Mapping[date, float]] | None = None,
    cross_asset_meta: Mapping[str, Mapping[str, Any]] | None = None,
    rate_series: Mapping[str, Mapping[date, float]] | None = None,
) -> dict[str, Any]:
    """Build the research block. Failures become an explicit unavailable block."""
    from scripts.fx_technical.research import (
        build_technical_research,
        unavailable_technical_research,
    )

    try:
        clean: dict[str, Mapping[date, float]] = {}
        for pair, series in (fx_series or {}).items():
            if isinstance(series, Mapping) and series:
                clean[str(pair)] = series
        if not clean:
            return unavailable_technical_research("FX closes unavailable for technical research")
        block = build_technical_research(
            clean,
            as_of=as_of,
            clock=clock,
            cross_asset_series=cross_asset_series,
            cross_asset_meta=cross_asset_meta,
            rate_series=rate_series,
        )
    except Exception as exc:
        block = unavailable_technical_research(f"technical research failed closed: {exc}")
    block["vetoes_unrelated_trades"] = False
    return block


def fx_technical_from_market_state(market_state: Mapping[str, Any] | None) -> dict[str, Any]:
    """Copy the frozen block. Do not recompute and do not fetch."""
    from scripts.fx_technical.research import unavailable_technical_research

    block: dict[str, Any] | None = None
    if isinstance(market_state, Mapping):
        raw = market_state.get("fx_technical")
        if isinstance(raw, dict) and raw.get("type") == "FX_TECHNICAL_RESEARCH":
            block = copy.deepcopy(raw)
    if block is None:
        block = unavailable_technical_research("technical feed absent from frozen market state")
    block["vetoes_unrelated_trades"] = False
    return block


def ensure_fx_technical(packet: dict[str, Any]) -> dict[str, Any]:
    """Put one shared block on an on-demand packet.

    The market-state copy wins when both exist, so every seat reads the feed
    that was frozen with the snapshot.
    """
    market = packet.get("market_state")
    market_block = None
    if isinstance(market, dict):
        raw = market.get("fx_technical")
        if isinstance(raw, dict) and raw.get("type") == "FX_TECHNICAL_RESEARCH":
            market_block = raw
    if market_block is not None:
        packet["fx_technical"] = fx_technical_from_market_state(market)
        return packet
    existing = packet.get("fx_technical")
    if isinstance(existing, dict) and existing.get("type") == "FX_TECHNICAL_RESEARCH":
        copied = copy.deepcopy(existing)
        copied["vetoes_unrelated_trades"] = False
        packet["fx_technical"] = copied
        return packet
    packet["fx_technical"] = fx_technical_from_market_state(None)
    return packet
