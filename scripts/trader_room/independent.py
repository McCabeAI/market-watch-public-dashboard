"""Persist a complete independently launched live Trader Room run.

The parent must supply already-returned grok-4.6 seat outputs. This module
validates provenance and writes the Git-durable artifact surface. It will not
author a missing first-pass, conflict, rebuttal, or final-aggregator payload.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.trader_room.artifacts import persist_run
from scripts.trader_room.budget import BudgetLedger
from scripts.trader_room.constants import (
    ADVOCATE_MODEL,
    AGGREGATOR_MODEL,
    ROOT,
    STANDING_ADVOCATES,
    SUBAGENT_MODEL,
)
from scripts.trader_room.errors import IndependentSeatRequired
from scripts.trader_room.provenance import (
    require_complete_independent_roster,
    require_independent_grok_seat,
)
from scripts.trader_room.runners import build_launch_plan
from scripts.trader_room.schema import (
    validate_conflict_map,
    validate_contribution,
    validate_pm_handoff,
    validate_rebuttal,
)


def _charge_independent(budget: BudgetLedger, originals: dict[str, dict[str, Any]], rebuttals: dict[str, dict[str, Any]]) -> None:
    budget.assert_baseline_room()
    for agent in STANDING_ADVOCATES:
        budget.charge("advocate", ADVOCATE_MODEL, agent, f"round1:{agent}")
        calls = int(originals[agent].get("subagent_calls") or 0)
        for idx in range(calls):
            budget.charge("subagent", SUBAGENT_MODEL, agent, f"round1:{agent}:subagent:{idx+1}")
    budget.charge("conflict-aggregator", AGGREGATOR_MODEL, "conflict-aggregator", "conflict-map")
    for agent in rebuttals:
        budget.charge("rebuttal", ADVOCATE_MODEL, agent, f"rebuttal:{agent}")
    budget.charge("final-aggregator", AGGREGATOR_MODEL, "final-aggregator", "pm-handoff")


def persist_independent_run(
    *,
    packet: dict[str, Any],
    preflight: dict[str, Any],
    originals: dict[str, dict[str, Any]],
    conflict_map: dict[str, Any],
    rebuttals: dict[str, dict[str, Any]],
    handoff: dict[str, Any],
    root: Path = ROOT,
    artifact_root: Path | None = None,
    invocation_ledger: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if any(item is None for item in (originals, conflict_map, rebuttals, handoff)):
        raise IndependentSeatRequired(
            "refusing to persist an incomplete live run; missing conflict/rebuttal/handoff "
            "must not be parent-synthesized"
        )
    validated = require_complete_independent_roster(originals)
    for agent, contribution in list(validated.items()):
        validated[agent] = validate_contribution(contribution, packet=packet, expected_agent=agent)
        require_independent_grok_seat(validated[agent], role="advocate", expected_agent=agent)

    require_independent_grok_seat(conflict_map, role="conflict-aggregator", expected_agent="conflict-aggregator")
    conflict_map = validate_conflict_map(conflict_map, validated)

    resolved_rebuttals: dict[str, dict[str, Any]] = {}
    if not isinstance(rebuttals, dict):
        raise IndependentSeatRequired("rebuttals must be a mapping of independent grok-4.6 seat outputs")
    for agent, payload in rebuttals.items():
        require_independent_grok_seat(payload, role="rebuttal", expected_agent=agent)
        opponents = set(payload.get("opponents") or ())
        resolved_rebuttals[agent] = validate_rebuttal(
            payload,
            packet=packet,
            expected_agent=agent,
            allowed_opponents=opponents,
        )

    require_independent_grok_seat(handoff, role="final-aggregator", expected_agent="final-aggregator")
    handoff = dict(handoff)
    handoff["live"] = True
    handoff["execution"] = "independent_grok_seat"
    budget = BudgetLedger()
    _charge_independent(budget, validated, resolved_rebuttals)
    launch_plan = build_launch_plan(packet)
    index = persist_run(
        root=artifact_root or root,
        packet=packet,
        preflight=preflight,
        originals=validated,
        conflict_map=conflict_map,
        rebuttals=resolved_rebuttals,
        handoff=handoff,
        budget=budget.snapshot(),
        launch_plan=launch_plan,
        invocation_ledger=invocation_ledger
        or {
            "valid": True,
            "execution": "independent_grok_seat",
            "invocations": budget.snapshot()["invocations"],
        },
        valid=True,
    )
    handoff["artifact_index"] = index
    validate_pm_handoff(
        handoff,
        packet=packet,
        originals=validated,
        conflict_map=conflict_map,
        rebuttals=resolved_rebuttals,
    )
    return {
        "run_id": packet["run_id"],
        "evidence_cutoff": packet["as_of"],
        "packet_sha256": packet["packet_sha256"],
        "preflight": preflight,
        "originals": validated,
        "conflict_map": conflict_map,
        "rebuttals": resolved_rebuttals,
        "handoff": handoff,
        "budget": budget.snapshot(),
        "launch_plan": launch_plan,
        "artifact_index": index,
        "valid": True,
    }
