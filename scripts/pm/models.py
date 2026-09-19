"""PM principal/subagent model routing (exact grok-4.6 / composer-2.5 only)."""

from __future__ import annotations

import json

from scripts.pm.constants import ALLOWED_SUBAGENT_MODELS, AUTOMATED_PM_IDS, MAX_SUBAGENTS_PER_PM
from scripts.trader_room.constants import AGENT_FRONTMATTER_MODEL
from scripts.trader_room.errors import ModelPolicyError
from scripts.trader_room.models import assert_advocate_model, normalize_model

PM_PRINCIPAL_MODEL = "grok-4.6"
PM_AGENT_FRONTMATTER_MODEL = AGENT_FRONTMATTER_MODEL

FORBIDDEN_PM_TASK_PRINCIPAL_MODELS = (
    "grok-4.6",
    "inherit",
    "cursor-grok-4.6-high",
    "cursor-grok-4.6-high-fast",
    "cursor-grok-4.6-low",
    "cursor-grok-4.6-low-fast",
    "cursor-grok-4.6-medium",
    "cursor-grok-4.6-medium-fast",
    "cursor-grok-4.6-xhigh",
    "cursor-grok-4.6-xhigh-fast",
)


def assert_pm_principal_model(model: str | None) -> str:
    normalized = normalize_model(model)
    if normalized != PM_PRINCIPAL_MODEL:
        raise ModelPolicyError(
            f"automated PM principal must be exact {PM_PRINCIPAL_MODEL}, got {model!r}"
        )
    return normalized


def assert_pm_subagent_model(model: str | None) -> str:
    normalized = normalize_model(model)
    if normalized not in ALLOWED_SUBAGENT_MODELS:
        raise ModelPolicyError(
            f"PM subagent model must be one of {list(ALLOWED_SUBAGENT_MODELS)}, got {model!r}"
        )
    return normalized


def assert_pm_launch_mechanism(mechanism: str | None) -> str:
    value = (mechanism or "").strip()
    if value != "cursor_custom_agent":
        raise ModelPolicyError(
            "automated PM principals must launch via cursor_custom_agent "
            f"(.cursor/agents/<pm_id>.md with frontmatter {PM_AGENT_FRONTMATTER_MODEL!r}), "
            f"not {mechanism!r}"
        )
    return value


def pm_hook_policy() -> str:
    return (
        'PM_MODEL_POLICY={"version":1,'
        f'"principal_model":"{PM_PRINCIPAL_MODEL}",'
        f'"principal_launch":"cursor_custom_agent",'
        f'"subagent_models":{json.dumps(list(ALLOWED_SUBAGENT_MODELS))},'
        f'"max_subagents_per_pm":{MAX_SUBAGENTS_PER_PM}}}'
    )


def pm_agent_ids() -> tuple[str, ...]:
    return AUTOMATED_PM_IDS
