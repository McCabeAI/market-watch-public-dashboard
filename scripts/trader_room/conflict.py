"""Deterministic Trader Room conflict detection and rebuttal routing. No ranking."""

from __future__ import annotations

import re
from typing import Any

from scripts.trader_room.constants import G10, OPPOSITE_REGIME
from scripts.trader_room.schema import validate_conflict_map

PAIR_RE = re.compile(r"(" + "|".join(G10) + ")(" + "|".join(G10) + ")")

VIEW_FIELDS = {
    "usd_view": ("USD", "higher", "lower"),
    "cad_view": ("CAD", "higher", "lower"),
    "aud_view": ("AUD", "higher", "lower"),
    "nzd_view": ("NZD", "higher", "lower"),
}
RATE_FIELDS = {
    "USD": "us_rates_view",
    "CAD": "ca_rates_view",
    "AUD": "au_rates_view",
    "NZD": "nz_rates_view",
}


def parse_pair(instrument: str) -> tuple[str, str] | None:
    match = PAIR_RE.search(instrument.replace("/", "").upper())
    if not match:
        return None
    base, quote = match.group(1), match.group(2)
    if base == quote:
        return None
    return base, quote


def direction_sign(direction: str) -> int | None:
    text = direction.strip().lower()
    if text.startswith("long") or text in {"buy", "overweight"}:
        return 1
    if text.startswith("short") or text in {"sell", "underweight"}:
        return -1
    return None


def currency_exposure(trade: dict[str, Any] | None) -> dict[str, int]:
    if not trade:
        return {}
    pair = parse_pair(str(trade.get("instrument") or ""))
    sign = direction_sign(str(trade.get("direction") or ""))
    if not pair or sign is None:
        return {}
    base, quote = pair
    return {base: sign, quote: -sign}


def _assumptions(contribution: dict[str, Any]) -> dict[str, str]:
    raw = contribution.get("macro_assumptions") or {}
    if contribution.get("trade") and isinstance(contribution["trade"].get("macro_assumptions"), dict):
        raw = {**raw, **contribution["trade"]["macro_assumptions"]}
    return {str(k): str(v) for k, v in raw.items()}


def _trade_key(trade: dict[str, Any]) -> str:
    return str(trade["instrument"]).replace("/", "").upper()


def _trade_map(originals: dict[str, dict[str, Any]], agents: list[str]) -> dict[str, Any]:
    return {name: originals[name].get("trade") for name in agents}


def _synopsis_map(originals: dict[str, dict[str, Any]], agents: list[str]) -> dict[str, Any]:
    return {name: originals[name].get("conflict_synopsis") for name in agents}


def _direct_instrument_conflicts(originals: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    by_instrument: dict[str, dict[int, list[str]]] = {}
    for name, item in originals.items():
        trade = item.get("trade")
        if not trade:
            continue
        sign = direction_sign(str(trade.get("direction") or ""))
        if sign:
            by_instrument.setdefault(_trade_key(trade), {}).setdefault(sign, []).append(name)

    conflicts: list[dict[str, Any]] = []
    for instrument, sides in sorted(by_instrument.items()):
        longs = sorted(sides.get(1, []))
        shorts = sorted(sides.get(-1, []))
        if longs and shorts:
            agents = longs + shorts
            conflicts.append(
                {
                    "id": f"opp-dir:{instrument}",
                    "kind": "opposite_direction",
                    "agents": agents,
                    "opposing_trades": _trade_map(originals, agents),
                    "synopses": _synopsis_map(originals, agents),
                    "description": f"{', '.join(longs)} are long {instrument} while {', '.join(shorts)} are short",
                }
            )
    return conflicts


def _synopsis_conflicts(originals: dict[str, dict[str, Any]]) -> dict[str, Any]:
    run_id = next(iter(originals.values()))["run_id"]
    conflicts = _direct_instrument_conflicts(originals)

    covered_pairs = {
        frozenset((a, b))
        for conflict in conflicts
        for a in conflict["agents"]
        for b in conflict["agents"]
        if a != b
    }

    for field, (label, positive, negative) in VIEW_FIELDS.items():
        plus = sorted(
            name for name, item in originals.items()
            if (item.get("conflict_synopsis") or {}).get(field) == positive
        )
        minus = sorted(
            name for name, item in originals.items()
            if (item.get("conflict_synopsis") or {}).get(field) == negative
        )
        if not plus or not minus:
            continue
        pair_set = {frozenset((a, b)) for a in plus for b in minus}
        if pair_set <= covered_pairs:
            continue
        agents = plus + minus
        conflicts.append(
            {
                "id": f"opp-view:{label}",
                "kind": "opposite_currency_view",
                "agents": agents,
                "opposing_trades": _trade_map(originals, agents),
                "synopses": _synopsis_map(originals, agents),
                "description": f"{', '.join(plus)} expect {label} higher while {', '.join(minus)} expect {label} lower",
            }
        )
        covered_pairs |= pair_set

    theoretical: list[dict[str, Any]] = []
    for ccy, view_field in ((v[0], k) for k, v in VIEW_FIELDS.items()):
        rate_field = RATE_FIELDS[ccy]
        currency_up = sorted(
            n for n, item in originals.items()
            if (item.get("conflict_synopsis") or {}).get(view_field) == "higher"
        )
        currency_down = sorted(
            n for n, item in originals.items()
            if (item.get("conflict_synopsis") or {}).get(view_field) == "lower"
        )
        rates_up = sorted(
            n for n, item in originals.items()
            if (item.get("conflict_synopsis") or {}).get(rate_field) == "higher"
        )
        rates_down = sorted(
            n for n, item in originals.items()
            if (item.get("conflict_synopsis") or {}).get(rate_field) == "lower"
        )
        for suffix, a, b, description in (
            (
                "ccy-up-rates-down",
                currency_up,
                rates_down,
                f"{ccy} higher views coexist with {ccy} rates-lower views; that is a theoretical policy/FX tension, not an automatic contradiction.",
            ),
            (
                "ccy-down-rates-up",
                currency_down,
                rates_up,
                f"{ccy} lower views coexist with {ccy} rates-higher views; that is a theoretical policy/FX tension, not an automatic contradiction.",
            ),
        ):
            agents = sorted(set(a + b))
            if a and b and len(agents) >= 2:
                theoretical.append(
                    {
                        "id": f"theory:{ccy}:{suffix}",
                        "kind": "currency_rates_tension",
                        "agents": agents,
                        "currency_camp": a,
                        "rates_camp": b,
                        "synopses": _synopsis_map(originals, agents),
                        "description": description,
                    }
                )

    context_tensions: list[dict[str, Any]] = []
    for field, left, right, label in (
        ("risk_view", "risk_on", "risk_off", "risk regime"),
        ("carry_view", "supports_trade", "opposes_trade", "carry"),
    ):
        a = sorted(
            n for n, item in originals.items()
            if (item.get("conflict_synopsis") or {}).get(field) == left
        )
        b = sorted(
            n for n, item in originals.items()
            if (item.get("conflict_synopsis") or {}).get(field) == right
        )
        if a and b:
            context_tensions.append(
                {
                    "id": f"context:{field}",
                    "kind": "context_tension",
                    "agents": sorted(set(a + b)),
                    "side_a": a,
                    "side_b": b,
                    "description": f"Opposing {label} assumptions: {left} versus {right}.",
                }
            )

    traders = sorted(name for name, item in originals.items() if item.get("trade") is not None)
    skeptics = sorted(name for name, item in originals.items() if item.get("trade") is None)
    challenges = []
    if traders and skeptics:
        challenges.append(
            {
                "id": "trade-vs-no-trade",
                "kind": "skeptic_challenge",
                "agents": skeptics,
                "targets": traders,
                "description": f"{', '.join(skeptics)} challenge whether any of the {len(traders)} actionable pitches clears the hurdle.",
            }
        )

    payload = {
        "type": "TRADER_ROOM_CONFLICT_MAP",
        "run_id": run_id,
        "method": "deterministic_conflict_synopsis_v1",
        "conflicts": conflicts,
        "theoretical_tensions": theoretical,
        "context_tensions": context_tensions,
        "challenges": challenges,
    }
    return validate_conflict_map(payload, originals)


def _legacy_conflicts(originals: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Fallback for old/synthetic fixtures that predate conflict_synopsis."""
    run_id = next(iter(originals.values()))["run_id"]
    conflicts = _direct_instrument_conflicts(originals)

    by_currency: dict[str, dict[int, list[str]]] = {}
    for name, item in originals.items():
        for ccy, exposure in currency_exposure(item.get("trade")).items():
            by_currency.setdefault(ccy, {}).setdefault(exposure, []).append(name)

    covered_pairs = {
        frozenset((a, b))
        for conflict in conflicts
        for a in conflict["agents"]
        for b in conflict["agents"]
        if a != b
    }
    for ccy, sides in sorted(by_currency.items()):
        plus = sorted(sides.get(1, []))
        minus = sorted(sides.get(-1, []))
        if plus and minus:
            pair_set = {frozenset((a, b)) for a in plus for b in minus}
            if pair_set <= covered_pairs:
                continue
            agents = plus + minus
            conflicts.append(
                {
                    "id": f"opp-ccy:{ccy}",
                    "kind": "opposite_currency_exposure",
                    "agents": agents,
                    "opposing_trades": _trade_map(originals, agents),
                    "description": f"{', '.join(plus)} are long {ccy} while {', '.join(minus)} are short {ccy}",
                }
            )

    camps: dict[tuple[str, str], list[str]] = {}
    for name, item in originals.items():
        for key, value in _assumptions(item).items():
            camps.setdefault((key, value), []).append(name)
    seen_regimes: set[tuple[str, str, str]] = set()
    for (key, value), agents in camps.items():
        opposite = OPPOSITE_REGIME.get((key, value))
        if not opposite:
            continue
        others = camps.get((key, opposite), [])
        if not others:
            continue
        regime_key = tuple(sorted((value, opposite)))
        dedupe = (key, regime_key[0], regime_key[1])
        if dedupe in seen_regimes:
            continue
        seen_regimes.add(dedupe)
        involved = sorted(set(agents + others))
        conflicts.append(
            {
                "id": f"regime:{key}:{value}-vs-{opposite}",
                "kind": "incompatible_regime",
                "agents": involved,
                "opposing_trades": _trade_map(originals, involved),
                "description": f"{', '.join(agents)} assume {key}={value} while {', '.join(others)} assume {key}={opposite}",
            }
        )

    return validate_conflict_map(
        {"type": "TRADER_ROOM_CONFLICT_MAP", "run_id": run_id, "method": "legacy_v0", "conflicts": conflicts},
        originals,
    )


def detect_conflicts(originals: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if originals and all(isinstance(item.get("conflict_synopsis"), dict) for item in originals.values()):
        return _synopsis_conflicts(originals)
    return _legacy_conflicts(originals)


def rebuttal_assignments(conflict_map: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Each directly conflicted advocate gets exactly one rebuttal bundle."""
    assignments: dict[str, dict[str, Any]] = {}
    for conflict in conflict_map["conflicts"]:
        agents = list(conflict["agents"])
        for agent in agents:
            opponents = [other for other in agents if other != agent]
            bundle = assignments.setdefault(
                agent,
                {"agent": agent, "conflict_ids": [], "opponents": [], "opposing_trades": []},
            )
            if conflict["id"] not in bundle["conflict_ids"]:
                bundle["conflict_ids"].append(conflict["id"])
            for opponent in opponents:
                if opponent not in bundle["opponents"]:
                    bundle["opponents"].append(opponent)
                    bundle["opposing_trades"].append(
                        {
                            "agent": opponent,
                            "conflict_id": conflict["id"],
                            "trade": conflict["opposing_trades"].get(opponent),
                        }
                    )
    if len(assignments) > 14:
        raise ValueError("rebuttal assignments exceeded 14 advocates")
    return assignments
