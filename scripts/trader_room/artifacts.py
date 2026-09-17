"""Immutable run-artifact persistence and retrieval."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.trader_room.errors import ArtifactError

ARTIFACT_FILES = {
    "evidence_packet": "evidence_packet.json",
    "preflight": "preflight.json",
    "conflict_map": "conflict_map.json",
    "pm_handoff": "pm_handoff.json",
    "budget": "budget.json",
    "launch_plan": "launch_plan.json",
    "artifact_index": "artifact_index.json",
    "receipt": "receipt.json",
}


def run_dir(root: Path, run_id: str) -> Path:
    return root / "trader-room" / "runs" / run_id


def write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def persist_run(
    *,
    root: Path,
    packet: dict[str, Any],
    preflight: dict[str, Any],
    originals: dict[str, dict[str, Any]],
    conflict_map: dict[str, Any],
    rebuttals: dict[str, dict[str, Any]],
    handoff: dict[str, Any],
    budget: dict[str, Any],
    launch_plan: dict[str, Any],
) -> dict[str, Any]:
    run_id = packet["run_id"]
    base = run_dir(root, run_id)
    try:
        write_json(base / ARTIFACT_FILES["evidence_packet"], packet)
        (base / "evidence_packet.sha256").write_text(packet["packet_sha256"] + "\n", encoding="utf-8")
        write_json(base / ARTIFACT_FILES["preflight"], preflight)
        write_json(base / ARTIFACT_FILES["conflict_map"], conflict_map)
        write_json(base / ARTIFACT_FILES["budget"], budget)
        write_json(base / ARTIFACT_FILES["launch_plan"], launch_plan)
        for agent, contribution in originals.items():
            write_json(base / "submissions" / f"{agent}.json", contribution)
        for agent, rebuttal in rebuttals.items():
            write_json(base / "rebuttals" / f"{agent}.json", rebuttal)
        index = {
            "run_id": run_id,
            "evidence_cutoff": packet["as_of"],
            "packet_sha256": packet["packet_sha256"],
            "evidence_packet": str((base / ARTIFACT_FILES["evidence_packet"]).relative_to(root)),
            "conflict_map": str((base / ARTIFACT_FILES["conflict_map"]).relative_to(root)),
            "pm_handoff": str((base / ARTIFACT_FILES["pm_handoff"]).relative_to(root)),
            "submissions": {
                agent: str((base / "submissions" / f"{agent}.json").relative_to(root))
                for agent in originals
            },
            "rebuttals": {
                agent: str((base / "rebuttals" / f"{agent}.json").relative_to(root))
                for agent in rebuttals
            },
        }
        handoff = dict(handoff)
        handoff["artifact_index"] = index
        write_json(base / ARTIFACT_FILES["pm_handoff"], handoff)
        write_json(base / ARTIFACT_FILES["artifact_index"], index)
        receipt = {
            "run_id": run_id,
            "evidence_cutoff": packet["as_of"],
            "artifact_root": str(base.relative_to(root)),
            "status": handoff["status"],
            "live": False,
        }
        write_json(base / ARTIFACT_FILES["receipt"], receipt)
    except OSError as exc:
        raise ArtifactError(f"failed to persist run {run_id}: {exc}") from exc
    return index


def retrieve(root: Path, run_id: str, kind: str, agent: str | None = None) -> dict[str, Any]:
    base = run_dir(root, run_id)
    if kind == "submission":
        if not agent:
            raise ArtifactError("submission retrieval requires agent")
        path = base / "submissions" / f"{agent}.json"
    elif kind == "rebuttal":
        if not agent:
            raise ArtifactError("rebuttal retrieval requires agent")
        path = base / "rebuttals" / f"{agent}.json"
    elif kind in ARTIFACT_FILES:
        path = base / ARTIFACT_FILES[kind]
    else:
        raise ArtifactError(f"unknown artifact kind {kind}")
    if not path.is_file():
        raise ArtifactError(f"artifact not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
