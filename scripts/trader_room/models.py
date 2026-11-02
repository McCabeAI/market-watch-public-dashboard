"""Mechanical model-routing validation against the repository catalog."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.trader_room.agent_config import get_profile, load_config, normalize_model as _normalize_model
from scripts.trader_room.constants import (
    ADVOCATE_MODEL,
    AGGREGATOR_MODEL,
    AGENT_FRONTMATTER_MODEL,
    ALLOWED_SUBAGENT_MODELS,
    REGISTRY_PATH,
    SUBAGENT_MODEL,
)
from scripts.trader_room.errors import ModelPolicyError


def load_registry(path: Path | None = None) -> dict[str, Any]:
    cfg = load_config(path)
    profile = get_profile(config=cfg)
    roles = profile["roles"]
    pm_model = roles["pm_principal"]
    advocate = roles["trader"]
    subagent = roles["advocate_subagent"]

    cursor_variants = (
        "high",
        "high-fast",
        "low",
        "low-fast",
        "medium",
        "medium-fast",
        "xhigh",
        "xhigh-fast",
    )
    pm_forbidden = (pm_model, "inherit") + tuple(
        f"cursor-{pm_model}-{variant}" for variant in cursor_variants
    )

    data: dict[str, Any] = {
        "schema_version": 2,
        "active_profile": cfg["active_profile"],
        "advocate_model": advocate,
        "aggregator_model": roles.get("advocate", advocate),
        "agent_frontmatter_model": f"{advocate}[]",
        "subagent_models": [subagent],
        "pm_principal_model": pm_model,
        "pm_agent_frontmatter_model": f"{pm_model}[]",
        "automated_pm_agent_ids": list(cfg["roster"]["automated_pms"]),
        "pm_allowed_subagent_models": list(profile["pm_subagent_models"]),
        "pm_principal_launch_mechanism": "cursor_custom_agent",
        "pm_forbidden_task_principal_models": list(pm_forbidden),
        "forbidden_models": list(cfg.get("forbidden_models") or []),
    }

    if data["advocate_model"] != ADVOCATE_MODEL:
        raise ModelPolicyError(
            f"registry advocate_model {data.get('advocate_model')!r} != {ADVOCATE_MODEL}"
        )
    if data["aggregator_model"] != AGGREGATOR_MODEL:
        raise ModelPolicyError(
            f"registry aggregator_model {data.get('aggregator_model')!r} != {AGGREGATOR_MODEL}"
        )
    if data.get("agent_frontmatter_model") != AGENT_FRONTMATTER_MODEL:
        raise ModelPolicyError(
            f"registry frontmatter {data.get('agent_frontmatter_model')!r} != {AGENT_FRONTMATTER_MODEL}"
        )
    if tuple(data.get("subagent_models") or ()) != ALLOWED_SUBAGENT_MODELS:
        raise ModelPolicyError(
            f"registry subagent_models {data.get('subagent_models')!r} != {list(ALLOWED_SUBAGENT_MODELS)}"
        )
    return data


def normalize_model(model: str | None) -> str:
    try:
        return _normalize_model(model)
    except Exception as exc:
        if isinstance(exc, ModelPolicyError):
            raise
        raise ModelPolicyError(str(exc)) from exc


def assert_advocate_model(model: str | None) -> str:
    normalized = normalize_model(model)
    if normalized != ADVOCATE_MODEL:
        raise ModelPolicyError(
            f"advocate/aggregator model must be exact {ADVOCATE_MODEL}, got {model!r}"
        )
    return normalized


def assert_aggregator_model(model: str | None) -> str:
    return assert_advocate_model(model)


def assert_subagent_model(model: str | None) -> str:
    normalized = normalize_model(model)
    if normalized != SUBAGENT_MODEL:
        raise ModelPolicyError(
            f"internal advocate subagent model must be exact {SUBAGENT_MODEL}, got {model!r}"
        )
    return normalized


def assert_allowed_role_model(role: str, model: str | None) -> str:
    if role in {"advocate", "conflict-aggregator", "final-aggregator", "rebuttal"}:
        return assert_advocate_model(model)
    if role == "subagent":
        return assert_subagent_model(model)
    raise ModelPolicyError(f"unknown model role {role!r}")


def trader_room_hook_policy() -> str:
    """Machine-readable policy line consumed by the Cursor subagent hook."""
    return (
        'TRADER_ROOM_MODEL_POLICY={"version":1,'
        f'"advocate_model":"{ADVOCATE_MODEL}",'
        f'"aggregator_model":"{AGGREGATOR_MODEL}",'
        f'"subagent_models":["{SUBAGENT_MODEL}"]}}'
    )
