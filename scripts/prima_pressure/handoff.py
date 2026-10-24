"""Bridge Canada Prima-pressure proxy blocks into Market Watch and overnight freeze."""

from __future__ import annotations

import datetime
from typing import Any

from scripts.prima_pressure import contract
from scripts.prima_pressure.proxy import compact_block, compute_prima_proxy


def unavailable_block(reason: str) -> dict[str, Any]:
    return {
        "title": "Canada Prima-pressure proxy",
        "direction": "UNAVAILABLE",
        "strength": None,
        "confidence": "low",
        "coverage": 0.0,
        "subcomponent_directions": {
            ch: "UNAVAILABLE" for ch in contract.CHANNELS
        },
        "front_shock_classification": "unavailable",
        "largest_drivers": [],
        "mpr_status": "unavailable",
        "conditioning_date": "2026-07-09",
        "change_since_last_mpr": "unavailable",
        "disclaimer": contract.DISCLAIMER,
        "staleness": "not computed",
        "status": "unavailable",
        "reason": reason,
        "channel_evidence": {},
    }


def prima_block_for_snapshot(
    as_of: datetime.date,
    *,
    include_cross_assets: bool,
) -> dict[str, Any]:
    if not include_cross_assets:
        return unavailable_block("cross_asset_collection_disabled")
    try:
        from scripts.prima_pressure.bundle import build_observation_bundle

        bundle = build_observation_bundle(as_of, allow_network=True)
        proxy = compute_prima_proxy(bundle)
        return compact_block(proxy)
    except Exception as exc:
        return unavailable_block(f"{type(exc).__name__}: {exc}")


def block_from_market_state(market_state: dict | None) -> dict[str, Any]:
    if isinstance(market_state, dict):
        block = market_state.get("canada_prima_pressure")
        if isinstance(block, dict):
            return block
    return unavailable_block("not_in_market_state")


def block_from_frozen(packet: dict | None) -> dict[str, Any]:
    if isinstance(packet, dict):
        direct = packet.get("canada_prima_pressure")
        if isinstance(direct, dict):
            return direct
        families = packet.get("families") if isinstance(packet.get("families"), dict) else {}
        market_family = families.get("market_state") if isinstance(families.get("market_state"), dict) else {}
        data = market_family.get("data")
        if isinstance(data, dict):
            nested = data.get("canada_prima_pressure")
            if isinstance(nested, dict):
                return nested
    return unavailable_block("not_in_frozen_evidence")


def _label_channel(channel: str) -> str:
    return channel.replace("_", " ")


def render_prima_research_text(block: dict[str, Any]) -> str:
    direction = block.get("direction") or "UNAVAILABLE"
    subs = block.get("subcomponent_directions") or {}
    sub_parts = [
        f"{_label_channel(ch)} {subs.get(ch, 'UNAVAILABLE')}" for ch in contract.CHANNELS
    ]
    coverage = block.get("coverage")
    drivers = block.get("largest_drivers") or []
    driver_text = ", ".join(str(d) for d in drivers) if drivers else "none highlighted"
    conditioning = block.get("conditioning_date") or "unknown"
    change = block.get("change_since_last_mpr") or "unavailable"
    disclaimer = block.get("disclaimer") or contract.DISCLAIMER
    return (
        f"The Canada Prima-pressure proxy reads {direction} with "
        f"channel directions ({'; '.join(sub_parts)}), coverage {coverage}, "
        f"largest drivers {driver_text}, MPR conditioning date {conditioning}, "
        f"and change since the last MPR: {change}. "
        f"{disclaimer}"
    )


def merge_prima_research(supplement: dict[str, Any], block: dict[str, Any]) -> dict[str, Any]:
    out = dict(supplement)
    out["canada_prima_pressure"] = block
    direction = block.get("direction")
    if direction in ("RISING", "STABLE", "FALLING"):
        headline = f"Canada Prima-pressure proxy {direction}"
        item = {
            "headline": headline,
            "title": headline,
            "summary": render_prima_research_text(block),
        }
        central = list(out.get("central_bank_research") or [])
        central.append(item)
        out["central_bank_research"] = central
    return out
