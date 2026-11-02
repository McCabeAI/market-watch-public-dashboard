"""Locked current-graph call contract for Market Watch launches (derived from pin)."""

from __future__ import annotations

import json
from typing import Any

from scripts.trader_room import agent_config

# Legacy importers may still reference node tuples for the 14-seat production graph.
CURRENT_GRAPH_NODES: tuple[tuple[str, int, str], ...] = (
    ("parent", 1, "grok"),
    ("synthesis", 1, "composer"),
    ("traders", 14, "grok"),
    ("automated_pms", 3, "grok"),
    ("learning_examiner", 1, "composer"),
)

TOTAL_CALLS = 20
GROK_FAMILY_CALLS = 18
COMPOSER_CALLS = 2


class CallGraphError(ValueError):
    """Raised when a launch budget disagrees with the locked current graph."""


def _head_daily_pin() -> dict[str, Any]:
    return agent_config.assert_acceptable_pin(agent_config.build_pin("daily"))


def current_graph(pin: dict[str, Any] | None = None) -> dict[str, Any]:
    resolved = pin or _head_daily_pin()
    budget = resolved["budget"]
    return {
        "version": 1,
        "total_calls": int(budget["total_calls"]),
        "grok_family_calls": int(budget["grok_family_calls"]),
        "composer_calls": int(budget["composer_calls"]),
        "nodes": dict(budget["nodes"]),
    }


def current_graph_marker(pin: dict[str, Any] | None = None) -> str:
    resolved = pin or _head_daily_pin()
    return agent_config.current_graph_marker_for(resolved)


def assert_launch_budget(budget: dict[str, Any], pin: dict[str, Any] | None = None) -> dict[str, Any]:
    """Reject a stale 19-call ceiling and any other unauthorized cap."""
    resolved = pin or _head_daily_pin()
    graph = current_graph(resolved)
    total = int(budget.get("total_model_cap", -1))
    grok = int(budget.get("grok_cap", -1))
    composer = int(budget.get("composer_cap", -1))
    if (total, grok, composer) != (
        graph["total_calls"],
        graph["grok_family_calls"],
        graph["composer_calls"],
    ):
        raise CallGraphError(
            "launch budget must be "
            f"{graph['total_calls']}/{graph['grok_family_calls']}/{graph['composer_calls']}; "
            f"got {total}/{grok}/{composer}"
        )
    declared = budget.get("current_graph")
    if declared is not None and declared != graph:
        raise CallGraphError("launch current_graph does not match the locked contract")
    parent_model = budget.get("parent_model")
    if parent_model is not None and parent_model != resolved["roles"]["parent"]:
        raise CallGraphError("launch parent_model does not match the pinned roster")
    return graph
