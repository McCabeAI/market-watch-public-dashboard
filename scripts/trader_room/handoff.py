"""Deterministic Trader Room PM handoff.

The final stage is bookkeeping, not analysis: preserve validated trades, conflicts,
rebuttals, evidence references, and artifact paths for ChatGPT arbitration without
spending another model call or re-reading the frozen evidence packet.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.trader_room.artifacts import write_json
from scripts.trader_room.conflict import rebuttal_assignments
from scripts.trader_room.constants import HANDOFF_MARKER, STANDING_ADVOCATES
from scripts.trader_room.schema import (
    validate_conflict_map,
    validate_contribution,
    validate_pm_handoff,
    validate_rebuttal,
)


def agreement_clusters(originals: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[str]] = {}
    for agent in STANDING_ADVOCATES:
        item = originals[agent]
        trade = item.get("trade")
        if not trade:
            key = "NO_TRADE"
        else:
            key = f"{trade.get('instrument')} | {trade.get('direction')}"
        groups.setdefault(key, []).append(agent)
    return [
        {"expression": expression, "agents": agents}
        for expression, agents in groups.items()
        if len(agents) > 1 or expression == "NO_TRADE"
    ]


def _rebuttal_point(item: dict[str, Any]) -> str | None:
    for key in ("strongest_opposing_claim", "strongest_opponent_point"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in ("holes_in_opposing_case", "attack"):
        values = item.get(key)
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str) and value.strip():
                    return value.strip()
        elif isinstance(values, str) and values.strip():
            return values.strip()
    return None


def artifact_index_for_run(
    *,
    root: Path,
    run_id: str,
    packet: dict[str, Any],
    originals: dict[str, dict[str, Any]],
    rebuttals: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    base = root / "trader-room" / "runs" / run_id
    return {
        "run_id": run_id,
        "evidence_cutoff": packet["as_of"],
        "packet_sha256": packet["packet_sha256"],
        "evidence_packet": str((base / "evidence_packet.json").relative_to(root)),
        "conflict_map": str((base / "conflict_map.json").relative_to(root)),
        "pm_handoff": str((base / "pm_handoff.json").relative_to(root)),
        "submissions": {
            agent: str((base / "submissions" / f"{agent}.json").relative_to(root))
            for agent in originals
        },
        "rebuttals": {
            agent: str((base / "rebuttals" / f"{agent}.json").relative_to(root))
            for agent in rebuttals
        },
    }


def build_pm_handoff(
    *,
    packet: dict[str, Any],
    originals: dict[str, dict[str, Any]],
    conflict_map: dict[str, Any],
    rebuttals: dict[str, dict[str, Any]],
    artifact_index: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_id = packet["run_id"]
    conflicts = list(conflict_map.get("conflicts") or [])
    handoff = {
        "type": "TRADER_ROOM_PM_HANDOFF",
        "run_id": run_id,
        "evidence_cutoff": packet["as_of"],
        "packet_sha256": packet["packet_sha256"],
        "proposed_trades": [
            {
                "agent": agent,
                "ref": f"trader-room/runs/{run_id}/submissions/{agent}.json",
                "trade": originals[agent].get("trade"),
            }
            for agent in STANDING_ADVOCATES
        ],
        "agreement_clusters": agreement_clusters(originals),
        "conflicts": [
            {
                "id": item["id"],
                "kind": item["kind"],
                "agents": item["agents"],
                "description": item["description"],
            }
            for item in conflicts
        ],
        "strongest_evidence_by_side": {
            conflict["id"]: {
                agent: list((originals[agent].get("trade") or {}).get("evidence_refs") or [])
                for agent in conflict["agents"]
                if agent in originals
            }
            for conflict in conflicts
        },
        "rebuttals": {
            agent: {
                "ref": f"trader-room/runs/{run_id}/rebuttals/{agent}.json",
                "trade_change": item["trade_change"],
                "strongest_opponent_point": _rebuttal_point(item),
            }
            for agent, item in rebuttals.items()
        },
        "amendments_and_withdrawals": [
            {
                "agent": agent,
                "trade_change": item["trade_change"],
                "revised_trade": item.get("revised_trade") if item["trade_change"] == "amended" else None,
            }
            for agent, item in rebuttals.items()
        ],
        "shared_assumptions": [
            "All 14 seats used the identical frozen evidence packet and cutoff.",
            "No advocate, rebuttal, or final handoff acquired new evidence after freeze.",
        ],
        "unresolved_questions_and_gaps": list(packet.get("known_gaps") or []),
        "artifact_index": artifact_index or {},
        "status": HANDOFF_MARKER,
    }
    for key in ("theoretical_tensions", "context_tensions", "challenges"):
        if conflict_map.get(key) is not None:
            handoff[key] = conflict_map[key]
    return handoff


def finalize_run_dir(*, root: Path, run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    root = root.resolve()
    packet = json.loads((run_dir / "evidence_packet.json").read_text(encoding="utf-8"))
    run_id = packet["run_id"]
    if run_dir.name != run_id:
        raise ValueError(f"run directory {run_dir.name} does not match packet run_id {run_id}")

    originals: dict[str, dict[str, Any]] = {}
    for agent in STANDING_ADVOCATES:
        path = run_dir / "submissions" / f"{agent}.json"
        contribution = json.loads(path.read_text(encoding="utf-8"))
        originals[agent] = validate_contribution(
            contribution,
            packet=packet,
            expected_agent=agent,
        )

    conflict_map = json.loads((run_dir / "conflict_map.json").read_text(encoding="utf-8"))
    validate_conflict_map(conflict_map, originals)

    assignments = rebuttal_assignments(conflict_map)

    rebuttals: dict[str, dict[str, Any]] = {}
    rebuttal_dir = run_dir / "rebuttals"
    if rebuttal_dir.is_dir():
        for path in sorted(rebuttal_dir.glob("*.json")):
            agent = path.stem
            item = json.loads(path.read_text(encoding="utf-8"))
            assignment = assignments.get(agent)
            allowed = set((assignment or {}).get("opponents") or [])
            rebuttals[agent] = validate_rebuttal(
                item,
                packet=packet,
                expected_agent=agent,
                allowed_opponents=allowed,
            )

    if set(rebuttals) != set(assignments):
        missing = sorted(set(assignments) - set(rebuttals))
        extra = sorted(set(rebuttals) - set(assignments))
        raise ValueError(f"rebuttal set incomplete or unexpected; missing={missing} extra={extra}")

    index = artifact_index_for_run(
        root=root,
        run_id=run_id,
        packet=packet,
        originals=originals,
        rebuttals=rebuttals,
    )
    handoff = build_pm_handoff(
        packet=packet,
        originals=originals,
        conflict_map=conflict_map,
        rebuttals=rebuttals,
        artifact_index=index,
    )
    validate_pm_handoff(
        handoff,
        packet=packet,
        originals=originals,
        conflict_map=conflict_map,
        rebuttals=rebuttals,
    )
    write_json(run_dir / "pm_handoff.json", handoff)
    write_json(run_dir / "artifact_index.json", index)
    receipt_path = run_dir / "receipt.json"
    receipt = (
        json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt_path.is_file()
        else {}
    )
    receipt.update(
        {
            "run_id": run_id,
            "evidence_cutoff": packet["as_of"],
            "packet_sha256": packet["packet_sha256"],
            "artifact_root": str(run_dir.relative_to(root)),
            "status": HANDOFF_MARKER,
            "final_handoff_method": "deterministic_pm_handoff_v1",
            "final_handoff_model_calls": 0,
        }
    )
    write_json(receipt_path, receipt)
    return handoff
