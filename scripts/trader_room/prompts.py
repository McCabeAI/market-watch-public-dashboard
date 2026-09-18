"""Prompt builders for Cursor-native parent-agent Trader Room seats."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.trader_room.constants import (
    ADVOCATE_MODEL,
    ADVOCATE_REMITS,
    AGENT_FRONTMATTER_MODEL,
    AGGREGATOR_MODEL,
    COMPOSER_PER_ADVOCATE,
    HANDOFF_MARKER,
    NO_TRADE_AGENT,
    REQUIRED_TRADE_FIELDS,
    ROOT,
    STANDING_ADVOCATES,
    SUBAGENT_MODEL,
)
from scripts.trader_room.models import trader_room_hook_policy
from scripts.trader_room.schema import packet_ref_ids

AGENT_DIR = ROOT / ".cursor" / "agents"


def load_agent_file(name: str) -> str:
    path = AGENT_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")


def allowed_evidence_refs(packet: dict[str, Any]) -> list[str]:
    return sorted(packet_ref_ids(packet))


def _shared_header(packet: dict[str, Any], *, packet_path: str) -> str:
    refs = "\n".join(f"- `{ref}`" for ref in allowed_evidence_refs(packet))
    return f"""{trader_room_hook_policy()}

You are a Market Watch Trader Room seat. The parent orchestrator is grok-4.6.
Exact seat model: `{ADVOCATE_MODEL}` (frontmatter `{AGENT_FRONTMATTER_MODEL}`).

FROZEN EVIDENCE PACKET
- run_id: {packet["run_id"]}
- as_of / evidence cutoff: {packet["as_of"]}
- topic: {packet.get("topic")}
- packet_sha256: {packet["packet_sha256"]}
- packet path: {packet_path}

Read that packet file. It is the only lawful evidence. Do not use web, search,
browse, fetch, or any other new-evidence tool. Do not invent levels, carry,
positioning, policy pricing, or sources. Unsupported levels must be JSON null.

Allowed evidence_refs (must be a subset of this list):
{refs}
"""


def advocate_prompt(agent: str, packet: dict[str, Any], *, packet_path: str) -> str:
    remit = ADVOCATE_REMITS[agent]
    trade_rule = (
        "You may submit `trade: null` as an explicit NO TRADE, and you must state "
        "the conditions required to become actionable."
        if agent == NO_TRADE_AGENT
        else "You must end with one cogent actionable trade inside this remit. `trade` may not be null."
    )
    fields = ", ".join(REQUIRED_TRADE_FIELDS)
    return f"""{_shared_header(packet, packet_path=packet_path)}
STANDING SEAT
- agent: {agent}
- remit: {remit}
- Apply docs/TRADER_RESEARCH_METHOD.md from the packet `research_method` BEFORE your archetypal bias.

Seat file (follow this remit exactly):
{load_agent_file(agent)}

ROUND 1 RULES
- Return only one JSON object, type `TRADER_ROOM_CONTRIBUTION`. No extra prose.
- Required fields: type, run_id, round=1, agent, archetype, remit, stance_summary, trade, confidence, packet_sha256.
- remit must be exactly: {remit}
- run_id must be {packet["run_id"]}
- packet_sha256 must be {packet["packet_sha256"]}
- {trade_rule}
- If trade is an object it must include: {fields}
- evidence_refs must point into the frozen packet.
- You may make at most {COMPOSER_PER_ADVOCATE} internal subagent calls, model `{SUBAGENT_MODEL}` only, on this same frozen packet. Record `subagent_calls` (int) and `subagent_model` (`{SUBAGENT_MODEL}` or null).
- Do not look at other advocates. Do not rank or choose a winner.
"""


def conflict_prompt(
    packet: dict[str, Any],
    originals: dict[str, dict[str, Any]],
    *,
    packet_path: str,
    originals_dir: str,
) -> str:
    roster = ", ".join(STANDING_ADVOCATES)
    return f"""{_shared_header(packet, packet_path=packet_path)}
You are `conflict-aggregator` on exact model `{AGGREGATOR_MODEL}`.
{load_agent_file("conflict-aggregator")}

ROUND 1 ORIGINALS
- roster: {roster}
- directory: {originals_dir}
- Read every `submissions/<agent>.json` / original object. Do not invent missing seats.

Return only one JSON object, type `TRADER_ROOM_CONFLICT_MAP`, with:
- run_id: {packet["run_id"]}
- conflicts: list of {{id, kind, agents, opposing_trades, description}}
- kinds allowed: opposite_direction, opposite_currency_exposure, incompatible_regime, trade_vs_no_trade
- Identify substantive conflicts only. Do not rank, vote, choose a winner, or emit a house view.
- No subagents. No new evidence.
"""


def rebuttal_prompt(
    agent: str,
    packet: dict[str, Any],
    original: dict[str, Any],
    assignment: dict[str, Any],
    *,
    packet_path: str,
) -> str:
    opponents = ", ".join(assignment["opponents"])
    return f"""{_shared_header(packet, packet_path=packet_path)}
STANDING SEAT REBUTTAL
- agent: {agent}
- remit: {ADVOCATE_REMITS[agent]}
- Exact model `{ADVOCATE_MODEL}`. No subagents. No new evidence.

Seat file:
{load_agent_file(agent)}

YOUR ORIGINAL
{original}

OPPOSING ORIGINALS YOU MUST ATTACK
{assignment}

RULES
- Return only one JSON object, type `TRADER_ROOM_REBUTTAL`.
- run_id: {packet["run_id"]}; round: 2; opponents: {opponents}
- own_original_ref: submissions/{agent}.json
- Must include holes_in_opposing_case, attack, defense, trade_change (unchanged|amended|withdrawn), revised_trade.
- Explicitly shoot holes in the opposing case.
- subagent_calls must be 0.
- packet_sha256 must be {packet["packet_sha256"]}
"""


def final_prompt(
    packet: dict[str, Any],
    *,
    packet_path: str,
    originals_dir: str,
    conflict_path: str,
    rebuttals_dir: str,
) -> str:
    return f"""{_shared_header(packet, packet_path=packet_path)}
You are `final-aggregator` on exact model `{AGGREGATOR_MODEL}`.
{load_agent_file("final-aggregator")}

INPUTS
- originals: {originals_dir}
- conflict map: {conflict_path}
- rebuttals: {rebuttals_dir}

Return only one JSON object, type `TRADER_ROOM_PM_HANDOFF`, including:
proposed_trades (every original), agreement_clusters, conflicts,
strongest_evidence_by_side, rebuttals, amendments_and_withdrawals,
shared_assumptions, unresolved_questions_and_gaps, artifact_index (may be {{}}),
status exactly `{HANDOFF_MARKER}`,
run_id {packet["run_id"]}, evidence_cutoff {packet["as_of"]}, packet_sha256 {packet["packet_sha256"]}.

Do not select a winner, house view, ranking, or approved trade. No subagents. No new evidence.
"""
