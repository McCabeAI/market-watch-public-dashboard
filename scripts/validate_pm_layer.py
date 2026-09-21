#!/usr/bin/env python3
"""Validate PM custom agents, launch plan, and model registry alignment."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.pm.constants import AUTOMATED_PM_IDS, MAX_SUBAGENTS_PER_PM
from scripts.pm.launch import build_pm_launch_plan
from scripts.pm.models import (
    PM_AGENT_FRONTMATTER_MODEL,
    PM_PRINCIPAL_MODEL,
    assert_pm_launch_mechanism,
    pm_hook_policy,
)
from scripts.trader_room.constants import REGISTRY_PATH
from scripts.validate_trader_room import assert_agent_file

ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / ".cursor" / "agents"
COMMAND = ROOT / ".cursor" / "commands" / "portfolio-managers.md"


def main() -> None:
    assert COMMAND.is_file(), "missing .cursor/commands/portfolio-managers.md"
    command = COMMAND.read_text(encoding="utf-8")
    assert "cursor_custom_agent" in command or "custom agent" in command.lower()
    assert "Do not" in command and "Task" in command
    assert "grok-4.6[]" in command
    assert "portfolio_construction" in command
    assert "packet/handoff" in command
    assert pm_hook_policy() in command

    for pm_id in AUTOMATED_PM_IDS:
        path = AGENT_DIR / f"{pm_id}.md"
        assert path.is_file(), f"missing PM agent {path}"
        assert_agent_file(pm_id, path)
        body = path.read_text(encoding="utf-8")
        assert "composer-2.5" in body
        assert "PM_LAYER_V1" in body
        if pm_id == "swinger":
            assert "HEDGE is prohibited" in body or "HEDGE prohibited" in body
        if pm_id == "pragmatist":
            assert "portfolio_construction" in body
            assert "independent markable" in body
            assert "packet/handoff" in body

    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert registry.get("pm_principal_model") == PM_PRINCIPAL_MODEL
    assert registry.get("pm_agent_frontmatter_model") == PM_AGENT_FRONTMATTER_MODEL
    assert tuple(registry.get("automated_pm_agent_ids") or ()) == AUTOMATED_PM_IDS
    forbidden = set(registry.get("pm_forbidden_task_principal_models") or [])
    assert "grok-4.6" in forbidden
    assert "cursor-grok-4.6-high-fast" in forbidden

    plan = build_pm_launch_plan(
        run_id="tr-test",
        evidence_cutoff="2026-09-19T00:00:00Z",
        evidence_packet_sha256="abc",
    )
    assert plan["launch_mechanism"] == "cursor_custom_agent"
    assert set(plan["agents"]) == set(AUTOMATED_PM_IDS)
    for pm_id in AUTOMATED_PM_IDS:
        agent = plan["agents"][pm_id]
        assert agent["frontmatter_model"] == PM_AGENT_FRONTMATTER_MODEL
        assert agent["max_subagents"] == MAX_SUBAGENTS_PER_PM
        assert_pm_launch_mechanism(agent["launch_mechanism"])

    hook = (ROOT / ".cursor" / "hooks" / "enforce-subagent-models.sh").read_text(encoding="utf-8")
    assert "PM_MODEL_POLICY" in hook
    assert "cursor-grok-4.6-*" in hook

    print(
        "PM layer validated: grok-4.6[] custom agents for swinger/pragmatist/grinder, "
        "cursor_custom_agent launch plan, and PM publication structural gate."
    )


if __name__ == "__main__":
    main()
