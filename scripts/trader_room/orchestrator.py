"""On-demand Trader Room entrypoint: prepare, freeze, debate, persist."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from scripts.trader_room.artifacts import persist_launch_kit, persist_run, retrieve, run_dir, write_json
from scripts.trader_room.budget import BudgetLedger
from scripts.trader_room.conflict import rebuttal_assignments
from scripts.trader_room.constants import (
    DEFAULT_ESSENTIAL_FAMILIES,
    ROOT,
    STANDING_ADVOCATES,
)
from scripts.trader_room.dispatch import MailboxStore
from scripts.trader_room.errors import ParentDispatchRequired, SchemaError, TraderRoomError
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
    return frozen, preflight


def _prepare_if_live(runner: ModelRunner, phase: str, **kwargs: Any) -> None:
    prepare = getattr(runner, "prepare_round", None)
    if prepare is None:
        return
    prepare(phase, **kwargs)


def run_debate(
    packet: dict[str, Any],
    preflight: dict[str, Any],
    *,
    runner: ModelRunner,
    root: Path = ROOT,
    artifact_root: Path | None = None,
    live: bool = False,
) -> dict[str, Any]:
    budget = BudgetLedger()
    budget.assert_baseline_room()
    _prepare_if_live(runner, "round1", packet=packet)
    originals: dict[str, dict[str, Any]] = {}
    for agent in STANDING_ADVOCATES:
        contribution = runner.run_advocate(agent, packet, budget)
        originals[agent] = validate_contribution(contribution, packet=packet, expected_agent=agent)
    if set(originals) != set(STANDING_ADVOCATES):
        raise SchemaError("round 1 did not return the complete 14-advocate roster")

    dest = artifact_root or root
    if live:
        base = run_dir(dest, packet["run_id"])
        for agent, contribution in originals.items():
            write_json(base / "submissions" / f"{agent}.json", contribution)

    _prepare_if_live(runner, "conflict", packet=packet, originals=originals)
    conflict_map = runner.run_conflict_aggregator(originals, packet, budget)
    conflict_map = validate_conflict_map(conflict_map, originals)
    assignments = rebuttal_assignments(conflict_map)
    if live:
        write_json(run_dir(dest, packet["run_id"]) / "conflict_map.json", conflict_map)

    _prepare_if_live(
        runner, "rebuttal", packet=packet, originals=originals, assignments=assignments
    )
    rebuttals: dict[str, dict[str, Any]] = {}
    for agent, assignment in assignments.items():
        rebuttal = runner.run_rebuttal(agent, packet, originals[agent], assignment, budget)
        rebuttals[agent] = validate_rebuttal(
            rebuttal,
            packet=packet,
            expected_agent=agent,
            allowed_opponents=set(assignment["opponents"]),
        )
    if live:
        for agent, item in rebuttals.items():
            write_json(run_dir(dest, packet["run_id"]) / "rebuttals" / f"{agent}.json", item)

    _prepare_if_live(
        runner,
        "final",
        packet=packet,
        originals=originals,
        conflict_map=conflict_map,
        rebuttals=rebuttals,
    )
    handoff = runner.run_final_aggregator(packet, originals, conflict_map, rebuttals, budget)
    launch_plan = build_launch_plan(packet)
    index = persist_run(
        root=artifact_root or root,
        packet=packet,
        preflight=preflight,
        originals=originals,
        conflict_map=conflict_map,
        rebuttals=rebuttals,
        handoff=handoff,
        budget=budget.snapshot(),
        launch_plan=launch_plan,
        live=live,
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
    dispatcher=None,
    resume_run_id: str | None = None,
) -> dict[str, Any]:
    dest = artifact_root or root
    if live:
        runner: ModelRunner = LiveRunner(dispatcher=dispatcher)
    else:
        if resume_run_id:
            raise TraderRoomError("resume is only valid for live Cursor-native runs")
        runner = DryRunRunner(composer_calls_per_advocate=composer_calls_per_advocate)
    if resume_run_id:
        packet = retrieve(dest, resume_run_id, "evidence_packet")
        preflight = retrieve(dest, resume_run_id, "preflight")
    else:
        packet, preflight = prepare_evidence(
            topic=topic,
            synthetic=synthetic,
            fixture=fixture,
            market_state_path=market_state_path,
            root=root,
        )
        if live:
            persist_launch_kit(
                root=dest,
                packet=packet,
                preflight=preflight,
                launch_plan=build_launch_plan(packet),
            )
    if live and dispatcher is None:
        runner.bind(MailboxStore(dest, packet["run_id"]))  # type: ignore[attr-defined]
    try:
        return run_debate(
            packet,
            preflight,
            runner=runner,
            root=root,
            artifact_root=dest,
            live=live,
        )
    except ParentDispatchRequired as exc:
        write_json(dest / "trader-room" / "runs" / packet["run_id"] / "dispatch" / "pending.json", exc.as_dict())
        raise
