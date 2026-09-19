"""On-demand Trader Room entrypoint: prepare, freeze, debate, persist."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from scripts.trader_room.artifacts import persist_run
from scripts.trader_room.budget import BudgetLedger
from scripts.trader_room.conflict import detect_conflicts, rebuttal_assignments
from scripts.trader_room.constants import (
    DEFAULT_ESSENTIAL_FAMILIES,
    ROOT,
    STANDING_ADVOCATES,
)
from scripts.trader_room.errors import LiveRunBlocked, SchemaError
from scripts.trader_room.handoff import build_pm_handoff
from scripts.trader_room.evidence import (
    assemble_packet,
    assess_families,
    freeze_packet,
    load_synthetic_packet,
    validate_preflight,
)
from scripts.trader_room.models import load_registry, trader_room_hook_policy
from scripts.trader_room.runners import DryRunRunner, LiveRunner, ModelRunner, build_launch_plan
from scripts.trader_room.schema import (
    validate_conflict_map,
    validate_contribution,
    validate_pm_handoff,
    validate_rebuttal,
)

DEFAULT_FIXTURE = ROOT / "trader-room" / "fixtures" / "minimal_evidence.json"


def prepare_evidence(
    *,
    topic: str,
    synthetic: bool = False,
    fixture: Path | None = None,
    market_state_path: Path | None = None,
    root: Path = ROOT,
    artifact_root: Path | None = None,
    essential_families: tuple[str, ...] = DEFAULT_ESSENTIAL_FAMILIES,
) -> tuple[dict[str, Any], dict[str, Any]]:
    load_registry()
    if synthetic:
        raw = load_synthetic_packet(fixture or DEFAULT_FIXTURE, topic=topic)
        raw["run_id"] = f"tr-dryrun-{uuid4().hex[:12]}"
    else:
        raw = assemble_packet(topic=topic, root=root, market_state_path=market_state_path)
    statuses = raw.get("family_status") or assess_families(raw)
    preflight = validate_preflight(raw, statuses, essential_families=essential_families)
    frozen, digest = freeze_packet({k: v for k, v in raw.items() if k != "packet_sha256"})
    preflight["packet_sha256"] = digest
    preflight["run_id"] = frozen["run_id"]
    preflight["evidence_cutoff"] = frozen["as_of"]
    preflight["hook_policy"] = trader_room_hook_policy()
    from scripts.trading.snapshot import snapshot_trader_room
    from scripts.trading.store import TradingStore

    persist_root = Path(artifact_root or root)
    trading = TradingStore(root=persist_root, state_root=persist_root)
    memory_index = snapshot_trader_room(
        trading,
        run_dir=persist_root / "trader-room" / "runs" / frozen["run_id"],
        run_id=frozen["run_id"],
        common_evidence_sha256=digest,
    )
    preflight["seat_memory"] = {
        "isolation": "own_sidecar_only",
        "common_evidence_sha256": digest,
        "hashes": memory_index.get("hashes") or {},
        "paths": memory_index.get("paths") or {},
    }
    return frozen, preflight


def run_debate(
    packet: dict[str, Any],
    preflight: dict[str, Any],
    *,
    runner: ModelRunner,
    root: Path = ROOT,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    budget = BudgetLedger()
    budget.assert_baseline_room()
    originals: dict[str, dict[str, Any]] = {}
    for agent in STANDING_ADVOCATES:
        contribution = runner.run_advocate(agent, packet, budget)
        originals[agent] = validate_contribution(contribution, packet=packet, expected_agent=agent)
    if set(originals) != set(STANDING_ADVOCATES):
        raise SchemaError("round 1 did not return the complete 14-advocate roster")

    conflict_map = validate_conflict_map(detect_conflicts(originals), originals)
    assignments = rebuttal_assignments(conflict_map)

    rebuttals: dict[str, dict[str, Any]] = {}
    for agent, assignment in assignments.items():
        rebuttal = runner.run_rebuttal(agent, packet, originals[agent], assignment, budget)
        rebuttals[agent] = validate_rebuttal(
            rebuttal,
            packet=packet,
            expected_agent=agent,
            allowed_opponents=set(assignment["opponents"]),
        )

    handoff = build_pm_handoff(
        packet=packet,
        originals=originals,
        conflict_map=conflict_map,
        rebuttals=rebuttals,
    )
    launch_plan = build_launch_plan(packet, memory_index=preflight.get("seat_memory"))
    persist_root = artifact_root or root
    index = persist_run(
        root=persist_root,
        packet=packet,
        preflight=preflight,
        originals=originals,
        conflict_map=conflict_map,
        rebuttals=rebuttals,
        handoff=handoff,
        budget=budget.snapshot(),
        launch_plan=launch_plan,
    )
    from scripts.trading.apply import journal_trader_room_pitch, journal_trader_room_rebuttal
    from scripts.trading.store import TradingStore

    trading = TradingStore(root=persist_root, state_root=persist_root)
    hashes = (preflight.get("seat_memory") or {}).get("hashes") or {}
    for agent, contribution in originals.items():
        journal_trader_room_pitch(
            trading,
            contribution,
            run_id=packet["run_id"],
            evidence_cutoff=packet.get("as_of"),
            evidence_hash=packet.get("packet_sha256"),
            memory_context_sha256=hashes.get(agent),
            source_ref=f"trader-room/runs/{packet['run_id']}/submissions/{agent}.json",
        )
    for agent, rebuttal in rebuttals.items():
        journal_trader_room_rebuttal(
            trading,
            rebuttal,
            run_id=packet["run_id"],
            evidence_cutoff=packet.get("as_of"),
            evidence_hash=packet.get("packet_sha256"),
            memory_context_sha256=hashes.get(agent),
            source_ref=f"trader-room/runs/{packet['run_id']}/rebuttals/{agent}.json",
        )
    handoff["artifact_index"] = index
    validate_pm_handoff(
        handoff,
        packet=packet,
        originals=originals,
        conflict_map=conflict_map,
        rebuttals=rebuttals,
    )
    return {
        "run_id": packet["run_id"],
        "evidence_cutoff": packet["as_of"],
        "packet_sha256": packet["packet_sha256"],
        "preflight": preflight,
        "originals": originals,
        "conflict_map": conflict_map,
        "rebuttals": rebuttals,
        "handoff": handoff,
        "budget": budget.snapshot(),
        "launch_plan": launch_plan,
        "artifact_index": index,
    }


def go(
    *,
    topic: str,
    live: bool = False,
    synthetic: bool = True,
    fixture: Path | None = None,
    market_state_path: Path | None = None,
    root: Path = ROOT,
    artifact_root: Path | None = None,
    composer_calls_per_advocate: int = 0,
) -> dict[str, Any]:
    if live:
        runner: ModelRunner = LiveRunner()
    else:
        runner = DryRunRunner(composer_calls_per_advocate=composer_calls_per_advocate)
    packet, preflight = prepare_evidence(
        topic=topic,
        synthetic=synthetic,
        fixture=fixture,
        market_state_path=market_state_path,
        root=root,
        artifact_root=artifact_root,
    )
    if live:
        raise LiveRunBlocked("live debate dispatch is gated after evidence freeze")
    return run_debate(packet, preflight, runner=runner, root=root, artifact_root=artifact_root)
