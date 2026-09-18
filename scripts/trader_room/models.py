"""Mechanical model-routing validation against the repository catalog."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
    registry_path = path or REGISTRY_PATH
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    if data.get("advocate_model") != ADVOCATE_MODEL:
        raise ModelPolicyError(
            f"registry advocate_model {data.get('advocate_model')!r} != {ADVOCATE_MODEL}"
        )
    if data.get("aggregator_model") != AGGREGATOR_MODEL:
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


# Cursor inherit on a grok-4.6 parent reports these provider slugs. They are
# the same standing grok-4.6 seat, not a different model family. Fast variants stay
# distinct and are not aliased.
GROK_INHERIT_ALIASES = {
    "cursor-grok-4.6-high": ADVOCATE_MODEL,
    "cursor-grok-4.6-medium": ADVOCATE_MODEL,
    "cursor-grok-4.6-low": ADVOCATE_MODEL,
    "cursor-grok-4.6-xhigh": ADVOCATE_MODEL,
}


def normalize_model(model: str | None) -> str:
    if not model:
        raise ModelPolicyError("missing model id")
    value = model.strip()
    if value.endswith("[]"):
        value = value[:-2]
    return GROK_INHERIT_ALIASES.get(value, value)


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
        f'"rebuttal_model":"{ADVOCATE_MODEL}",'
        f'"subagent_models":["{SUBAGENT_MODEL}"],'
        '"composer_max_per_advocate":2,'
        '"composer_allowed_role":"advocate-research"}'
    )
