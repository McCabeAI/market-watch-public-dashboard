"""Conflict detection and one-pass rebuttal routing. No ranking."""

from __future__ import annotations

import re
from typing import Any

from scripts.trader_room.constants import G10, OPPOSITE_REGIME
from scripts.trader_room.schema import validate_conflict_map

PAIR_RE = re.compile(r"(" + "|".join(G10) + ")(" + "|".join(G10) + ")")


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


def detect_conflicts(originals: dict[str, dict[str, Any]]) -> dict[str, Any]:
    run_id = next(iter(originals.values()))["run_id"]
    conflicts: list[dict[str, Any]] = []

    by_instrument: dict[str, dict[int, list[str]]] = {}
    by_currency: dict[str, dict[int, list[str]]] = {}
    for name, item in originals.items():
        trade = item.get("trade")
        if not trade:
            continue
        sign = direction_sign(str(trade["direction"]))
        if sign:
            by_instrument.setdefault(_trade_key(trade), {}).setdefault(sign, []).append(name)
        for ccy, exposure in currency_exposure(trade).items():
            by_currency.setdefault(ccy, {}).setdefault(exposure, []).append(name)

    for instrument, sides in sorted(by_instrument.items()):
        longs = sides.get(1, [])
        shorts = sides.get(-1, [])
        if longs and shorts:
            agents = longs + shorts
            conflicts.append(
                {
                    "id": f"opp-dir:{instrument}",
                    "kind": "opposite_direction",
                    "agents": agents,
                    "opposing_trades": {name: originals[name]["trade"] for name in agents},
                    "description": (
                        f"{', '.join(longs)} are long {instrument} while "
                        f"{', '.join(shorts)} are short"
                    ),
                }
            )

    covered_pairs = {
        frozenset((a, b))
        for conflict in conflicts
        if conflict["kind"] == "opposite_direction"
        for a in conflict["agents"]
        for b in conflict["agents"]
        if a != b
    }
    for ccy, sides in sorted(by_currency.items()):
        plus = sides.get(1, [])
        minus = sides.get(-1, [])
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
                    "opposing_trades": {name: originals[name].get("trade") for name in agents},
                    "description": (
                        f"{', '.join(plus)} are long {ccy} while {', '.join(minus)} are short {ccy}"
                    ),
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
        involved = agents + others
        conflicts.append(
            {
                "id": f"regime:{key}:{value}-vs-{opposite}",
                "kind": "incompatible_regime",
                "agents": involved,
                "opposing_trades": {name: originals[name].get("trade") for name in involved},
                "description": (
                    f"{', '.join(agents)} assume {key}={value} while "
                    f"{', '.join(others)} assume {key}={opposite}"
                ),
            }
        )

    traders = [name for name, item in originals.items() if item.get("trade") is not None]
    skeptics = [name for name, item in originals.items() if item.get("trade") is None]
    if traders and skeptics:
        opposing = {name: originals[name].get("trade") for name in traders + skeptics}
        conflicts.append(
            {
                "id": "trade-vs-no-trade",
                "kind": "trade_vs_no_trade",
                "agents": skeptics + traders,
                "opposing_trades": opposing,
                "description": (
                    f"{', '.join(skeptics)} submit no-trade against "
                    f"{len(traders)} actionable proposals"
                ),
            }
        )

    payload = {
        "type": "TRADER_ROOM_CONFLICT_MAP",
        "run_id": run_id,
        "conflicts": conflicts,
        "ranking": None,
        "house_view": None,
    }
    # Explicit nulls are not ranking keys present as selectors; strip them after documenting absence.
    payload.pop("ranking")
    payload.pop("house_view")
    return validate_conflict_map(payload, originals)


def rebuttal_assignments(conflict_map: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Each conflicted advocate gets exactly one rebuttal bundle."""
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
