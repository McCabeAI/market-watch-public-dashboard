"""Independent-seat provenance. Parent-authored output is never a valid seat."""

from __future__ import annotations

from typing import Any

from scripts.trader_room.constants import (
    ADVOCATE_MODEL,
    AGGREGATOR_MODEL,
    AGGREGATORS,
    COMPOSER_PER_ADVOCATE,
    FORBIDDEN_EXECUTION_MARKERS,
    INDEPENDENT_EXECUTION,
    STANDING_ADVOCATES,
    SUBAGENT_MODEL,
)
from scripts.trader_room.errors import IndependentSeatRequired, ParentAuthoredSeatError
from scripts.trader_room.models import normalize_model

STANDING_GROK_ROLES = frozenset(
    {
        "advocate",
        "rebuttal",
        "conflict-aggregator",
        "final-aggregator",
    }
)
COMPOSER_ONLY_ROLE = "advocate-research"
INVALID_PRIOR_RUN_ID = "tr-20260917T231827Z-4ca9133b"
INVALID_PRIOR_REASON = (
    "Parent authored standing-seat briefs instead of launching the 14 independent "
    "grok-4.6 seats. This run is not a valid Trader Room result."
)


def execution_marker(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    raw = payload.get("execution")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    invocation = payload.get("invocation")
    if isinstance(invocation, dict):
        nested = invocation.get("execution")
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
    return None


def reject_forbidden_execution(payload: dict[str, Any], label: str) -> None:
    marker = execution_marker(payload)
    if marker and marker in FORBIDDEN_EXECUTION_MARKERS:
        raise ParentAuthoredSeatError(
            f"{label} is {marker}; parent-authored or simulated standing-seat "
            "output is not accepted"
        )
    invocation = payload.get("invocation") if isinstance(payload, dict) else None
    if isinstance(invocation, dict) and invocation.get("parent_authored") is True:
        raise ParentAuthoredSeatError(
            f"{label} invocation.parent_authored=true; parent must not author seat output"
        )
    if isinstance(payload, dict) and payload.get("parent_authored") is True:
        raise ParentAuthoredSeatError(f"{label} is parent-authored and is not accepted")


def _invocation(payload: dict[str, Any]) -> dict[str, Any]:
    invocation = payload.get("invocation")
    if invocation is None:
        return {}
    if not isinstance(invocation, dict):
        raise IndependentSeatRequired(f"{payload.get('agent') or 'payload'} invocation must be an object")
    return invocation


def require_independent_grok_seat(
    payload: dict[str, Any],
    *,
    role: str,
    expected_agent: str | None = None,
    allow_missing_invocation_id: bool = False,
) -> dict[str, Any]:
    """Fail loud unless this payload came from an independent grok-4.6 seat."""
    if not isinstance(payload, dict):
        raise IndependentSeatRequired(f"{role} output is missing; parent must not synthesize a substitute")
    reject_forbidden_execution(payload, expected_agent or role)
    if payload.get("execution") != INDEPENDENT_EXECUTION:
        raise IndependentSeatRequired(
            f"{expected_agent or role} missing execution={INDEPENDENT_EXECUTION}; "
            "parent must not ghostwrite or simulate a standing seat"
        )
    invocation = _invocation(payload)
    if not invocation:
        raise IndependentSeatRequired(
            f"{expected_agent or role} missing invocation evidence; refuse to invent a seat"
        )
    if invocation.get("independent") is not True:
        raise IndependentSeatRequired(f"{expected_agent or role} invocation is not marked independent")
    if invocation.get("parent_authored") is True:
        raise ParentAuthoredSeatError(f"{expected_agent or role} was parent-authored")
    recorded_role = invocation.get("role") or payload.get("seat_role")
    if recorded_role != role:
        raise IndependentSeatRequired(
            f"{expected_agent or role} invocation role {recorded_role!r} != {role!r}"
        )
    model = normalize_model(str(invocation.get("model") or payload.get("seat_model") or ""))
    required_model = AGGREGATOR_MODEL if role in {"conflict-aggregator", "final-aggregator"} else ADVOCATE_MODEL
    if model != required_model:
        raise IndependentSeatRequired(
            f"{expected_agent or role} must be exact {required_model}, got {model!r}"
        )
    if not allow_missing_invocation_id and not str(invocation.get("id") or "").strip():
        raise IndependentSeatRequired(
            f"{expected_agent or role} missing invocation id; launch evidence is required"
        )
    subagent_calls = int(payload.get("subagent_calls") or invocation.get("subagent_calls") or 0)
    if role in {"rebuttal", "conflict-aggregator", "final-aggregator"} and subagent_calls:
        raise IndependentSeatRequired(
            f"{expected_agent or role} may not make internal subagent calls"
        )
    if role == "advocate":
        if subagent_calls > COMPOSER_PER_ADVOCATE:
            raise IndependentSeatRequired(
                f"{expected_agent} used {subagent_calls} composer subagents; max {COMPOSER_PER_ADVOCATE}"
            )
        sub_model = payload.get("subagent_model") or invocation.get("subagent_model")
        if subagent_calls and normalize_model(str(sub_model or "")) != SUBAGENT_MODEL:
            raise IndependentSeatRequired(
                f"{expected_agent} internal subagents must be exact {SUBAGENT_MODEL}"
            )
    if expected_agent:
        agent = payload.get("agent")
        if role in {"advocate", "rebuttal"} and agent != expected_agent:
            raise IndependentSeatRequired(f"expected {expected_agent}, got {agent}")
        if role in AGGREGATORS and expected_agent != role:
            raise IndependentSeatRequired(f"expected aggregator {role}")
    return payload


def stamp_independent_invocation(
    payload: dict[str, Any],
    *,
    role: str,
    model: str,
    invocation_id: str,
    agent: str | None = None,
    subagent_calls: int = 0,
    subagent_model: str | None = None,
) -> dict[str, Any]:
    """Attach launch evidence to an already-returned seat payload.

    This must not create thesis/trade/conflict content. Missing payload fails.
    """
    if not isinstance(payload, dict):
        raise IndependentSeatRequired(
            f"refusing to stamp {role}{f'/{agent}' if agent else ''}: no seat output was returned"
        )
    reject_forbidden_execution(payload, agent or role)
    normalized = normalize_model(model)
    required = AGGREGATOR_MODEL if role in {"conflict-aggregator", "final-aggregator"} else ADVOCATE_MODEL
    if normalized != required:
        raise IndependentSeatRequired(f"{agent or role} launch model must be {required}, got {model!r}")
    if not str(invocation_id).strip():
        raise IndependentSeatRequired(f"{agent or role} launch produced no invocation id")
    if role not in STANDING_GROK_ROLES:
        raise IndependentSeatRequired(f"unknown standing role {role!r}")
    stamped = dict(payload)
    stamped["execution"] = INDEPENDENT_EXECUTION
    stamped["seat_model"] = normalized
    stamped["seat_role"] = role
    stamped["parent_authored"] = False
    invocation = dict(stamped.get("invocation") or {})
    invocation.update(
        {
            "id": str(invocation_id).strip(),
            "model": normalized,
            "frontmatter_model": "grok-4.6[]",
            "role": role,
            "independent": True,
            "parent_authored": False,
            "subagent_calls": int(subagent_calls),
            "subagent_model": subagent_model if subagent_calls else None,
        }
    )
    stamped["invocation"] = invocation
    stamped["subagent_calls"] = int(subagent_calls)
    stamped["subagent_model"] = subagent_model if subagent_calls else None
    return stamped


def require_complete_independent_roster(
    originals: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    missing = [agent for agent in STANDING_ADVOCATES if agent not in originals]
    if missing:
        raise IndependentSeatRequired(
            f"refusing to synthesize missing first-pass seats: {missing}"
        )
    extra = sorted(set(originals) - set(STANDING_ADVOCATES))
    if extra:
        raise IndependentSeatRequired(f"unexpected first-pass seats: {extra}")
    validated: dict[str, dict[str, Any]] = {}
    for agent in STANDING_ADVOCATES:
        validated[agent] = require_independent_grok_seat(
            originals[agent],
            role="advocate",
            expected_agent=agent,
        )
    return validated
