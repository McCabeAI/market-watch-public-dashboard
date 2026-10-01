"""Locked current-graph call contract for Market Watch launches.

The current graph is 20 calls by design:

1 parent + 1 synthesis + 14 traders + 3 automated PMs + 1 learning examiner.

That is 18 grok-family calls and 2 composer calls. A 19-call ceiling is the
pre-examiner graph and is not a valid launch cap.
"""

from __future__ import annotations

import json
from typing import Any

# name, count, family
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


def _family_total(family: str) -> int:
    return sum(count for _name, count, node_family in CURRENT_GRAPH_NODES if node_family == family)


def current_graph() -> dict[str, Any]:
    grok = _family_total("grok")
    composer = _family_total("composer")
    total = grok + composer
    if (total, grok, composer) != (TOTAL_CALLS, GROK_FAMILY_CALLS, COMPOSER_CALLS):
        raise CallGraphError(
            f"current graph drifted to {total}/{grok}/{composer}; "
            f"locked contract is {TOTAL_CALLS}/{GROK_FAMILY_CALLS}/{COMPOSER_CALLS}"
        )
    return {
        "version": 1,
        "total_calls": total,
        "grok_family_calls": grok,
        "composer_calls": composer,
        "nodes": {name: count for name, count, _family in CURRENT_GRAPH_NODES},
    }


def current_graph_marker() -> str:
    graph = current_graph()
    nodes = graph["nodes"]
    payload = {
        "version": 1,
        "total_calls": graph["total_calls"],
        "grok_family_calls": graph["grok_family_calls"],
        "composer_calls": graph["composer_calls"],
        "parent": nodes["parent"],
        "synthesis": nodes["synthesis"],
        "traders": nodes["traders"],
        "automated_pms": nodes["automated_pms"],
        "learning_examiner": nodes["learning_examiner"],
    }
    return "MW_CURRENT_GRAPH=" + json.dumps(payload, separators=(",", ":"), sort_keys=True)


def assert_launch_budget(budget: dict[str, Any]) -> dict[str, Any]:
    """Reject a stale 19-call ceiling and any other unauthorized cap."""
    graph = current_graph()
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
    return graph
