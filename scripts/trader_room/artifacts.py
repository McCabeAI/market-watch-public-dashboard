"""Immutable run-artifact persistence and retrieval.

Sanitized analysis artifacts are written to the Git-approved
`trader-room/runs/<run_id>/` surface so ChatGPT can retrieve them.
Unsanitized provider-local packets may use `trader-room/runs/.local/`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.trader_room.constants import ROOT
from scripts.trader_room.errors import ArtifactError
from scripts.trader_room.handoff_markdown import render_pm_handoff_markdown

ARTIFACT_FILES = {
    "evidence_packet": "evidence_packet.json",
    "preflight": "preflight.json",
    "conflict_map": "conflict_map.json",
    "pm_handoff": "pm_handoff.json",
    "pm_handoff_markdown": "pm_handoff.md",
    "budget": "budget.json",
    "launch_plan": "launch_plan.json",
    "artifact_index": "artifact_index.json",
    "receipt": "receipt.json",
}
PRIVATE_KEYS = {
    "private_methodology_available",
    "paid_source_text",
    "licensed_excerpt",
    "raw_paid_evidence",
    "raw_evidence_text",
    "paywalled_text",
}
LOCAL_RUNS_DIRNAME = ".local"
INDEX_NAME = "INDEX.json"
LATEST_NAME = "latest.json"


def run_dir(root: Path, run_id: str, *, local: bool = False) -> Path:
    base = root / "trader-room" / "runs"
    if local:
        return base / LOCAL_RUNS_DIRNAME / run_id
    return base / run_id


def write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _strip_private(payload: Any) -> Any:
    if isinstance(payload, dict):
        cleaned: dict[str, Any] = {}
        for key, value in payload.items():
            if key in PRIVATE_KEYS:
                continue
            cleaned[key] = _strip_private(value)
        return cleaned
    if isinstance(payload, list):
        return [_strip_private(item) for item in payload]
    return payload


def sanitize_packet(packet: dict[str, Any]) -> dict[str, Any]:
    """Drop private/licensed/raw paid evidence; keep public analysis inputs."""
    clean = _strip_private(json.loads(json.dumps(packet)))
    method = clean.get("research_method")
    if isinstance(method, dict) and method.get("text"):
        method["text"] = None
        method["text_ref"] = method.get("document") or "docs/TRADER_RESEARCH_METHOD.md"
        method["sanitized"] = True
    clean["private_methodology_available"] = []
    clean["sanitized"] = True
    return clean


def _catalog_paths(root: Path) -> tuple[Path, Path]:
    runs = root / "trader-room" / "runs"
    return runs / INDEX_NAME, runs / LATEST_NAME


def update_run_catalog(root: Path, entry: dict[str, Any]) -> None:
    index_path, latest_path = _catalog_paths(root)
    catalog = {"durable_channel": "git", "latest_run_id": None, "runs": []}
    if index_path.is_file():
        catalog = json.loads(index_path.read_text(encoding="utf-8"))
    runs = [item for item in catalog.get("runs") or [] if item.get("run_id") != entry["run_id"]]
    runs.insert(0, entry)
    catalog = {
        "durable_channel": "git",
        "latest_run_id": entry["run_id"],
        "retrieve_command": (
            "PYTHONPATH=. python scripts/trader_room_go.py retrieve "
            f"--run-id {entry['run_id']} --kind pm_handoff"
        ),
        "runs": runs,
    }
    write_json(index_path, catalog)
    write_json(
        latest_path,
        {
            "run_id": entry["run_id"],
            "path": entry["artifact_root"],
            "evidence_cutoff": entry.get("evidence_cutoff"),
            "retrieve_command": catalog["retrieve_command"],
            "durable_channel": "git",
        },
    )


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
    update_catalog: bool | None = None,
    local: bool = False,
) -> dict[str, Any]:
    run_id = packet["run_id"]
    base = run_dir(root, run_id, local=local)
    sanitized_packet = sanitize_packet(packet)
    if update_catalog is None:
        update_catalog = (not local) and root.resolve() == ROOT.resolve()
    try:
        write_json(base / ARTIFACT_FILES["evidence_packet"], sanitized_packet)
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
            "durable_channel": "local" if local else "git",
            "sanitized": True,
            "evidence_packet": str((base / ARTIFACT_FILES["evidence_packet"]).relative_to(root)),
            "conflict_map": str((base / ARTIFACT_FILES["conflict_map"]).relative_to(root)),
            "pm_handoff": str((base / ARTIFACT_FILES["pm_handoff"]).relative_to(root)),
            "pm_handoff_markdown": str((base / ARTIFACT_FILES["pm_handoff_markdown"]).relative_to(root)),
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
        markdown = render_pm_handoff_markdown(
            packet=sanitized_packet,
            originals=originals,
            conflict_map=conflict_map,
            rebuttals=rebuttals,
            handoff=handoff,
        )
        (base / ARTIFACT_FILES["pm_handoff_markdown"]).write_text(markdown, encoding="utf-8")
        write_json(base / ARTIFACT_FILES["artifact_index"], index)
        receipt = {
            "run_id": run_id,
            "evidence_cutoff": packet["as_of"],
            "artifact_root": str(base.relative_to(root)),
            "status": handoff["status"],
            "live": bool(handoff.get("live") or packet.get("live")),
            "sanitized": True,
            "durable_channel": index["durable_channel"],
            "retrieve_command": (
                "PYTHONPATH=. python scripts/trader_room_go.py retrieve "
                f"--run-id {run_id} --kind pm_handoff"
            ),
        }
        write_json(base / ARTIFACT_FILES["receipt"], receipt)
        if update_catalog:
            update_run_catalog(
                root,
                {
                    "run_id": run_id,
                    "evidence_cutoff": packet["as_of"],
                    "packet_sha256": packet["packet_sha256"],
                    "artifact_root": str(base.relative_to(root)),
                    "sanitized": True,
                    "durable_channel": "git",
                    "status": handoff["status"],
                },
            )
    except OSError as exc:
        raise ArtifactError(f"failed to persist run {run_id}: {exc}") from exc
    return index


def retrieve(root: Path, run_id: str, kind: str, agent: str | None = None) -> dict[str, Any]:
    candidates = [run_dir(root, run_id), run_dir(root, run_id, local=True)]
    last_missing: Path | None = None
    for base in candidates:
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
        if path.is_file():
            if path.suffix == ".md":
                return {"path": str(path.relative_to(root)), "markdown": path.read_text(encoding="utf-8")}
            return json.loads(path.read_text(encoding="utf-8"))
        last_missing = path
    raise ArtifactError(f"artifact not found: {last_missing}")
