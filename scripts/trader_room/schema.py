"""Deterministic trade, remit, conflict, and handoff validators."""

from __future__ import annotations

import re
from typing import Any

from scripts.trader_room.constants import (
    ADVOCATE_REMITS,
    COMPARISON_AGENTS,
    FORBIDDEN_RANKING_KEYS,
    HANDOFF_MARKER,
    NO_TRADE_AGENT,
    NULLABLE_LEVEL_FIELDS,
    REQUIRED_TRADE_FIELDS,
    STANDING_ADVOCATES,
    TRADE_REQUIRED_AGENTS,
)
from scripts.trader_room.errors import DataBoundaryError, SchemaError
from scripts.trader_room.evidence import assert_same_frozen_packet
from scripts.trader_room.mandate import compact_comparison, seat_class, validate_expression_comparison

LEVEL_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
FORBIDDEN_ACQUISITION = (
    "web_search",
    "web_fetch",
    "browse",
    "search_results",
    "new_evidence",
    "fresh_sources",
    "http_get",
)


def packet_ref_ids(packet: dict[str, Any]) -> set[str]:
    ids = {str(item.get("id")) for item in packet.get("source_index") or [] if item.get("id")}
    for key in ("temperature_gauges", "central_bank_research", "news_and_research"):
        for item in packet.get(key) or []:
            if item.get("id"):
                ids.add(str(item["id"]))
    if packet.get("market_state"):
        ids.add("market_state")
    if packet.get("research_method"):
        ids.add("research_method")
    return ids


def _require_keys(payload: dict[str, Any], keys: tuple[str, ...], label: str) -> None:
    missing = [k for k in keys if k not in payload]
    if missing:
        raise SchemaError(f"{label} missing required fields: {missing}")


def _non_empty_text(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SchemaError(f"{field} must be a non-empty string")


def _list_of_text(value: Any, field: str) -> None:
    if not isinstance(value, list) or not value or any(not isinstance(x, str) or not x.strip() for x in value):
        raise SchemaError(f"{field} must be a non-empty list of strings")


def validate_trade(
    trade: dict[str, Any] | None,
    *,
    agent: str,
    packet: dict[str, Any],
) -> None:
    if trade is None:
        if agent != NO_TRADE_AGENT:
            raise SchemaError(f"{agent} must submit one actionable trade; trade is null")
        return
    if not isinstance(trade, dict):
        raise SchemaError(f"{agent} trade must be an object or null")
    _require_keys(trade, REQUIRED_TRADE_FIELDS, f"{agent} trade")
    for field in ("instrument", "direction", "thesis", "mispricing", "horizon"):
        _non_empty_text(trade[field], f"{agent}.trade.{field}")
    for field in ("why_now", "evidence_refs", "catalysts", "principal_risks"):
        _list_of_text(trade[field], f"{agent}.trade.{field}")
    confidence = trade["confidence"]
    if not isinstance(confidence, int) or not 0 <= confidence <= 100:
        raise SchemaError(f"{agent} trade.confidence must be int 0-100")
    allowed = packet_ref_ids(packet)
    unknown = [ref for ref in trade["evidence_refs"] if ref not in allowed]
    if unknown:
        raise DataBoundaryError(f"{agent} evidence_refs not in frozen packet: {unknown}")
    for field in NULLABLE_LEVEL_FIELDS:
        value = trade[field]
        if value is None:
            continue
        if field == "structure":
            _non_empty_text(value, f"{agent}.trade.structure")
            continue
        if not isinstance(value, str) or not value.strip():
            raise SchemaError(f"{agent}.trade.{field} must be null or a sourced string")
        if LEVEL_RE.search(value) and not trade["evidence_refs"]:
            raise SchemaError(f"{agent}.trade.{field} has a level but no evidence_refs")
    invented = trade.get("invented_levels")
    if invented:
        raise SchemaError(f"{agent} must use explicit nulls rather than invented levels")


def assert_data_only_boundary(payload: dict[str, Any], packet: dict[str, Any], label: str) -> None:
    blob = str(payload)
    for key in FORBIDDEN_ACQUISITION:
        if key in payload:
            raise DataBoundaryError(f"{label} used forbidden acquisition field {key}")
        if f'"{key}"' in blob and key in payload.get("tools_used", []):
            raise DataBoundaryError(f"{label} recorded forbidden tool {key}")
    if payload.get("packet_sha256") and payload["packet_sha256"] != packet.get("packet_sha256"):
        raise DataBoundaryError(f"{label} packet hash mismatch")
    supplied = payload.get("evidence_packet")
    if supplied is not None:
        assert_same_frozen_packet(packet, supplied)


def validate_contribution(
    contribution: dict[str, Any],
    *,
    packet: dict[str, Any],
    expected_agent: str | None = None,
) -> dict[str, Any]:
    _require_keys(
        contribution,
        ("type", "run_id", "round", "agent", "archetype", "stance_summary", "trade", "confidence", "remit"),
        "contribution",
    )
    if contribution["type"] != "TRADER_ROOM_CONTRIBUTION":
        raise SchemaError(f"contribution type must be TRADER_ROOM_CONTRIBUTION, got {contribution['type']}")
    if contribution["round"] != 1:
        raise SchemaError("initial contribution round must be 1")
    agent = contribution["agent"]
    if agent not in STANDING_ADVOCATES:
        raise SchemaError(f"unknown advocate {agent}")
    if expected_agent and agent != expected_agent:
        raise SchemaError(f"expected {expected_agent}, got {agent}")
    if contribution["run_id"] != packet["run_id"]:
        raise SchemaError("contribution run_id does not match frozen packet")
    if contribution["remit"] != ADVOCATE_REMITS[agent]:
        raise SchemaError(f"{agent} remit does not match standing remit")
    if not isinstance(contribution["confidence"], int) or not 0 <= contribution["confidence"] <= 100:
        raise SchemaError(f"{agent} confidence must be int 0-100")
    validate_trade(contribution["trade"], agent=agent, packet=packet)
    if agent in TRADE_REQUIRED_AGENTS and contribution["trade"] is None:
        raise SchemaError(f"{agent} must end with one cogent actionable trade")
    validate_expression_comparison(contribution, agent=agent)
    assert_data_only_boundary(contribution, packet, agent)
    return contribution


def validate_rebuttal(
    rebuttal: dict[str, Any],
    *,
    packet: dict[str, Any],
    expected_agent: str,
    allowed_opponents: set[str],
) -> dict[str, Any]:
    _require_keys(
        rebuttal,
        (
            "type",
            "run_id",
            "round",
            "agent",
            "opponents",
            "own_original_ref",
            "holes_in_opposing_case",
            "trade_change",
            "revised_trade",
            "attack",
            "defense",
        ),
        "rebuttal",
    )
    if rebuttal["type"] != "TRADER_ROOM_REBUTTAL":
        raise SchemaError("rebuttal type must be TRADER_ROOM_REBUTTAL")
    if rebuttal["round"] != 2:
        raise SchemaError("rebuttal round must be 2")
    if rebuttal["agent"] != expected_agent:
        raise SchemaError(f"rebuttal agent {rebuttal['agent']} != {expected_agent}")
    if rebuttal["run_id"] != packet["run_id"]:
        raise SchemaError("rebuttal run_id mismatch")
    if rebuttal["trade_change"] not in {"unchanged", "amended", "withdrawn"}:
        raise SchemaError("trade_change must be unchanged | amended | withdrawn")
    if not rebuttal.get("holes_in_opposing_case"):
        raise SchemaError(f"{expected_agent} must explicitly shoot holes in the opposing case")
    extra = set(rebuttal.get("opponents") or ()) - allowed_opponents
    if extra:
        raise SchemaError(f"{expected_agent} rebuttal opponents not in conflict routing: {sorted(extra)}")
    if rebuttal.get("subagent_calls"):
        raise SchemaError("rebuttal pass may not make additional subagent calls")
    if rebuttal["trade_change"] == "withdrawn":
        if expected_agent != NO_TRADE_AGENT and rebuttal["revised_trade"] is not None:
            raise SchemaError("withdrawn trade must be null")
    elif rebuttal["revised_trade"] is not None:
        validate_trade(rebuttal["revised_trade"], agent=expected_agent, packet=packet)
    assert_data_only_boundary(rebuttal, packet, f"{expected_agent} rebuttal")
    return rebuttal


def _assert_no_ranking(payload: dict[str, Any], label: str) -> None:
    for key in FORBIDDEN_RANKING_KEYS:
        if key in payload:
            raise SchemaError(f"{label} must not include {key}")


def validate_conflict_map(conflict_map: dict[str, Any], originals: dict[str, dict[str, Any]]) -> dict[str, Any]:
    _require_keys(conflict_map, ("type", "run_id", "conflicts"), "conflict map")
    if conflict_map["type"] != "TRADER_ROOM_CONFLICT_MAP":
        raise SchemaError("conflict map type must be TRADER_ROOM_CONFLICT_MAP")
    _assert_no_ranking(conflict_map, "conflict aggregator")
    seen_ids: set[str] = set()
    for conflict in conflict_map["conflicts"]:
        _require_keys(conflict, ("id", "kind", "agents", "opposing_trades", "description"), "conflict")
        if conflict["id"] in seen_ids:
            raise SchemaError(f"duplicate conflict id {conflict['id']}")
        seen_ids.add(conflict["id"])
        agents = conflict["agents"]
        if len(agents) < 2:
            raise SchemaError(f"conflict {conflict['id']} needs at least two agents")
        unknown = [a for a in agents if a not in originals]
        if unknown:
            raise SchemaError(f"conflict {conflict['id']} unknown agents {unknown}")
        _assert_no_ranking(conflict, f"conflict {conflict['id']}")
    return conflict_map


def validate_pm_handoff(
    handoff: dict[str, Any],
    *,
    packet: dict[str, Any],
    originals: dict[str, dict[str, Any]],
    conflict_map: dict[str, Any],
    rebuttals: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    required = (
        "type",
        "run_id",
        "evidence_cutoff",
        "proposed_trades",
        "agreement_clusters",
        "conflicts",
        "strongest_evidence_by_side",
        "rebuttals",
        "amendments_and_withdrawals",
        "shared_assumptions",
        "unresolved_questions_and_gaps",
        "expression_comparisons",
        "artifact_index",
        "status",
    )
    _require_keys(handoff, required, "PM handoff")
    if handoff["type"] != "TRADER_ROOM_PM_HANDOFF":
        raise SchemaError("handoff type must be TRADER_ROOM_PM_HANDOFF")
    if handoff["run_id"] != packet["run_id"]:
        raise SchemaError("handoff run_id mismatch")
    if handoff["evidence_cutoff"] != packet["as_of"]:
        raise SchemaError("handoff evidence_cutoff must equal packet as_of")
    if handoff["status"] != HANDOFF_MARKER:
        raise SchemaError(f"handoff status must be exactly {HANDOFF_MARKER}")
    _assert_no_ranking(handoff, "final aggregator")
    proposed_agents = {item["agent"] for item in handoff["proposed_trades"]}
    if proposed_agents != set(originals):
        raise SchemaError("PM handoff must preserve every original proposed trade")
    detail_fields = ("thesis", "evidence_refs", "expression", "catalysts", "invalidation")
    for item in handoff["proposed_trades"]:
        missing = [field for field in detail_fields if field not in item]
        if missing:
            raise SchemaError(f"PM handoff proposed trade for {item.get('agent')} missing {missing}")
        if "winner" in item or "rank" in item:
            raise SchemaError("PM handoff proposed_trades must not rank or pick a winner")
    if set(handoff["rebuttals"]) != set(rebuttals):
        raise SchemaError("PM handoff must preserve every rebuttal")
    comparisons = handoff["expression_comparisons"]
    if set(comparisons) != set(originals):
        raise SchemaError("PM handoff must preserve every seat's expression comparison")
    for agent, original in originals.items():
        if agent in COMPARISON_AGENTS and not original.get("expression_comparison"):
            raise SchemaError(f"PM handoff lost {agent} expression comparison")
        if seat_class(agent) != "vol_specialist" and comparisons.get(agent) is None:
            raise SchemaError(f"PM handoff missing expression comparison for {agent}")
    index = handoff["artifact_index"]
    for agent in originals:
        if agent not in (index.get("submissions") or {}):
            raise SchemaError(f"artifact index missing submission for {agent}")
    for agent in rebuttals:
        if agent not in (index.get("rebuttals") or {}):
            raise SchemaError(f"artifact index missing rebuttal for {agent}")
    if "evidence_packet" not in index or "conflict_map" not in index:
        raise SchemaError("artifact index missing evidence_packet or conflict_map")
    if len(handoff["conflicts"]) != len(conflict_map["conflicts"]):
        raise SchemaError("PM handoff conflict count does not match conflict map")
    return handoff


def proposed_trade_row(name: str, item: dict[str, Any]) -> dict[str, Any]:
    trade = item.get("trade")
    comparison = item.get("expression_comparison")
    return {
        "agent": name,
        "trade": trade,
        "ref": f"submissions/{name}.json",
        "thesis": (trade or {}).get("thesis") or item.get("stance_summary"),
        "evidence_refs": list((trade or {}).get("evidence_refs") or []),
        "expression": (trade or {}).get("structure")
        or (trade or {}).get("instrument")
        or "no-trade",
        "catalysts": list((trade or {}).get("catalysts") or []),
        "invalidation": None if trade is None else trade.get("invalidation"),
        "expression_comparison": compact_comparison(comparison),
    }
