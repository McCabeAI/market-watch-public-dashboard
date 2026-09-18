"""Neutral Markdown arbiter packet for Git-retrievable ChatGPT handoff."""

from __future__ import annotations

import json
from typing import Any

from scripts.trader_room.constants import HANDOFF_MARKER, STANDING_ADVOCATES


def _json_block(payload: Any) -> str:
    return "```json\n" + json.dumps(payload, indent=2, sort_keys=True) + "\n```"


def render_pm_handoff_markdown(
    *,
    packet: dict[str, Any],
    originals: dict[str, dict[str, Any]],
    conflict_map: dict[str, Any],
    rebuttals: dict[str, dict[str, Any]],
    handoff: dict[str, Any],
) -> str:
    rows = []
    for agent in STANDING_ADVOCATES:
        item = originals[agent]
        trade = item.get("trade") or {}
        comparison = item.get("expression_comparison") or {}
        rows.append(
            "| `{agent}` | {instrument} | {direction} | {chosen} | {thesis} |".format(
                agent=agent,
                instrument=trade.get("instrument") or "no-trade",
                direction=trade.get("direction") or "n/a",
                chosen=comparison.get("chosen_expression") or "unchanged_remit",
                thesis=(trade.get("thesis") or item.get("stance_summary") or "").replace("|", "/"),
            )
        )
    gaps = packet.get("known_gaps") or []
    lines = [
        f"# Trader Room PM handoff `{packet['run_id']}`",
        "",
        f"- Evidence cutoff: `{packet['as_of']}`",
        f"- Packet SHA-256: `{packet.get('packet_sha256')}`",
        f"- Durable channel: git `trader-room/runs/{packet['run_id']}/`",
        "- Aggregators are neutral organizers. No winner, vote, ranking, or house view.",
        "",
        "## Source coverage and gaps",
        "",
        _json_block(packet.get("family_status") or {}),
        "",
        "Known gaps:",
        *([f"- {gap}" for gap in gaps] if gaps else ["- None recorded."]),
        "",
        "## Compact Round 1 table",
        "",
        "| Agent | Instrument | Direction | Chosen expression | Thesis |",
        "| --- | --- | --- | --- | --- |",
        *rows,
        "",
        "## Full Round 1 contributions",
        "",
    ]
    for agent in STANDING_ADVOCATES:
        lines.extend([f"### `{agent}`", "", _json_block(originals[agent]), ""])
    lines.extend(["## Conflict map", "", _json_block(conflict_map), ""])
    if rebuttals:
        lines.extend(["## Round 2 rebuttals", ""])
        for agent, rebuttal in rebuttals.items():
            lines.extend([f"### `{agent}`", "", _json_block(rebuttal), ""])
    else:
        lines.extend(["## Round 2 rebuttals", "", "No meaningful conflict routing; Round 2 skipped.", ""])
    lines.extend(
        [
            "## Unresolved factual questions",
            "",
            _json_block(handoff.get("unresolved_questions_and_gaps") or []),
            "",
            "## Structured PM handoff JSON",
            "",
            _json_block({k: v for k, v in handoff.items() if k != "artifact_index"} | {"artifact_index": handoff.get("artifact_index")}),
            "",
            HANDOFF_MARKER,
            "",
        ]
    )
    return "\n".join(lines) + "\n"
