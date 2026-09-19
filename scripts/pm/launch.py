"""Deterministic automated-PM launch plan (custom agents, not Task model slugs)."""

from __future__ import annotations

from typing import Any

from scripts.pm.constants import ALLOWED_SUBAGENT_MODELS, AUTOMATED_PM_IDS, MAX_SUBAGENTS_PER_PM
from scripts.pm.models import (
    FORBIDDEN_PM_TASK_PRINCIPAL_MODELS,
    PM_AGENT_FRONTMATTER_MODEL,
    PM_PRINCIPAL_MODEL,
    assert_pm_launch_mechanism,
    pm_hook_policy,
)


def build_pm_launch_plan(
    *,
    run_id: str,
    evidence_cutoff: str,
    evidence_packet_sha256: str,
    trader_room_run_id: str | None = None,
) -> dict[str, Any]:
    """Launch plan consumed by scheduled/manual PM orchestration."""
    assert_pm_launch_mechanism("cursor_custom_agent")
    agents: dict[str, Any] = {}
    for pm_id in AUTOMATED_PM_IDS:
        agents[pm_id] = {
            "pm_id": pm_id,
            "launch_mechanism": "cursor_custom_agent",
            "custom_agent": pm_id,
            "custom_agent_path": f".cursor/agents/{pm_id}.md",
            "model": PM_PRINCIPAL_MODEL,
            "frontmatter_model": PM_AGENT_FRONTMATTER_MODEL,
            "max_subagents": MAX_SUBAGENTS_PER_PM,
            "allowed_subagent_models": list(ALLOWED_SUBAGENT_MODELS),
            "forbidden_principal_launch": {
                "task_model_parameter": list(FORBIDDEN_PM_TASK_PRINCIPAL_MODELS),
                "reason": (
                    "Task/subagent_type with model grok-4.6 or inherit emits cursor-grok-4.6-* "
                    "runtime slugs rejected by enforce-subagent-models.sh"
                ),
            },
        }
    return {
        "schema_version": 1,
        "type": "AUTOMATED_PM_LAUNCH",
        "run_id": run_id,
        "trader_room_run_id": trader_room_run_id or run_id,
        "evidence_cutoff": evidence_cutoff,
        "evidence_packet_sha256": evidence_packet_sha256,
        "requested_principal": PM_PRINCIPAL_MODEL,
        "launch_mechanism": "cursor_custom_agent",
        "independence": "each PM reads only its own packet + memory; no mutual current-cycle visibility",
        "chatgpt": "ingest-only; do not launch ChatGPT as a Cursor PM principal",
        "hook_policy_line": pm_hook_policy(),
        "agents": agents,
    }
