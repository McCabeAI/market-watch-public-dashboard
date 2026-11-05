#!/usr/bin/env python3
"""Validate PM custom agents, launch plan, and model registry alignment."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.pm.constants import AUTOMATED_PM_IDS, MAX_SUBAGENTS_PER_PM
from scripts.pm.launch import build_pm_launch_plan
from scripts.pm.models import (
    PM_AGENT_FRONTMATTER_MODEL,
    PM_PRINCIPAL_MODEL,
    assert_pm_launch_mechanism,
    pm_hook_policy,
)
from scripts.trader_room.agent_config import check_agents, get_profile
from scripts.trader_room.models import load_registry
from scripts.validate_trader_room import _hook_allowed_models, assert_agent_file

ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / ".cursor" / "agents"
COMMAND = ROOT / ".cursor" / "commands" / "portfolio-managers.md"


def main() -> None:
    assert COMMAND.is_file(), "missing .cursor/commands/portfolio-managers.md"
    command = COMMAND.read_text(encoding="utf-8")
    assert "cursor_custom_agent" in command or "custom agent" in command.lower()
    assert "Do not" in command and "Task" in command
    assert PM_AGENT_FRONTMATTER_MODEL in command
    assert "grok-4.6[]" not in command
    assert "portfolio_construction" in command
    assert "full frozen market" in command
    assert "challenge set" in command
    assert "opportunity_scan" in command
    assert "force_deployment" in command
    assert pm_hook_policy() in command

    for pm_id in AUTOMATED_PM_IDS:
        path = AGENT_DIR / f"{pm_id}.md"
        assert path.is_file(), f"missing PM agent {path}"
        assert_agent_file(pm_id, path)
        body = path.read_text(encoding="utf-8")
        assert "composer-2.5" in body
        assert "PM_LAYER_V1" in body
        assert "full frozen market" in body
        assert "opportunity_scan" in body
        assert "challenge set" in body
        if pm_id == "swinger":
            assert "HEDGE is prohibited" in body or "HEDGE prohibited" in body
        if pm_id == "pragmatist":
            assert "portfolio_construction" in body
            assert "independent markable" in body
        if pm_id == "grinder":
            assert "force_deployment" in body
            assert "near-zero" in body

    registry = load_registry()
    assert registry.get("pm_principal_model") == PM_PRINCIPAL_MODEL
    assert registry.get("pm_agent_frontmatter_model") == PM_AGENT_FRONTMATTER_MODEL
    assert tuple(registry.get("automated_pm_agent_ids") or ()) == AUTOMATED_PM_IDS
    forbidden = set(registry.get("pm_forbidden_task_principal_models") or [])
    assert PM_PRINCIPAL_MODEL in forbidden
    assert f"cursor-{PM_PRINCIPAL_MODEL}-high-fast" in forbidden

    agent_errors = check_agents(ROOT)
    assert not agent_errors, "agent frontmatter drift:\n" + "\n".join(agent_errors)

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

    hook_path = ROOT / ".cursor" / "hooks" / "enforce-subagent-models.sh"
    hook = hook_path.read_text(encoding="utf-8")
    assert "PM_MODEL_POLICY" in hook
    assert "hook-models" in hook
    assert "scripts/trader_room/agent_config.py" in hook
    profile = get_profile()
    assert _hook_allowed_models("pm") == profile["pm_subagent_models"]

    policy = pm_hook_policy()
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(policy + "\n")
        transcript = handle.name
    try:
        proc = subprocess.run(
            [
                "sh",
                str(hook_path),
                json.dumps({"subagent_model": "cursor-grok-4.6-high-fast", "transcript_path": transcript}),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode != 0
        combined = proc.stdout + proc.stderr
        assert ".cursor/agents" in combined or "custom agent" in combined.lower()
    finally:
        Path(transcript).unlink(missing_ok=True)

    print(
        f"PM layer validated: {PM_AGENT_FRONTMATTER_MODEL} custom agents for swinger/pragmatist/grinder, "
        "cursor_custom_agent launch plan, and PM publication structural gate."
    )


if __name__ == "__main__":
    main()
