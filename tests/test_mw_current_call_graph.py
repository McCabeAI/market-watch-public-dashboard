"""The live Market Watch launch contract is the 20-call current graph."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from scripts.market_watch_launch.acp_handshake import build_delegation_request
from scripts.market_watch_launch.call_graph import (
    CallGraphError,
    assert_launch_budget,
    current_graph,
    current_graph_marker,
)
from scripts.overnight.constants import ROOT
from scripts.overnight.errors import SchemaError
from scripts.overnight.scheduled_output import validate_execution

LAUNCH_TEXTS = (
    ROOT / ".cursor" / "commands" / "overnight-scheduled.md",
    ROOT / ".cursor" / "commands" / "manual-market-watch-review.md",
    ROOT / "docs" / "ACP_ONE_SHOT_AUTHORITY.md",
    ROOT / "docs" / "OVERNIGHT_PIPELINE_V1.md",
)

STALE_CEILINGS = (
    '"total_model_cap":19',
    '"total_model_cap": 19',
    "at most 19 total",
    "Approved graph (19",
    "Total: 19 invocations",
    "approved graph uses 19",
    "19 / 18 / 1",
)


def _budget_hook():
    path = ROOT / ".cursor" / "hooks" / "enforce-overnight-budget.py"
    spec = importlib.util.spec_from_file_location("mw_overnight_budget_hook", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CurrentGraphContractTests(unittest.TestCase):
    def test_nodes_are_twenty_calls_with_eighteen_grok_and_two_composer(self) -> None:
        graph = current_graph()
        nodes = graph["nodes"]
        self.assertEqual(
            nodes,
            {
                "parent": 1,
                "synthesis": 1,
                "traders": 14,
                "automated_pms": 3,
                "learning_examiner": 1,
            },
        )
        self.assertEqual(sum(nodes.values()), 20)
        self.assertEqual(nodes["parent"] + nodes["traders"] + nodes["automated_pms"], 18)
        self.assertEqual(nodes["synthesis"] + nodes["learning_examiner"], 2)
        self.assertEqual(
            (graph["total_calls"], graph["grok_family_calls"], graph["composer_calls"]),
            (20, 18, 2),
        )
        self.assertIn("learning_examiner", nodes)

    def test_delegation_budget_carries_the_current_graph_and_rejects_nineteen(self) -> None:
        request = build_delegation_request(
            {
                "launch_id": "mwl-test",
                "session_date": "2026-10-02",
                "review_id": "review-001",
                "request": {},
            }
        )
        budget = request["budget"]
        self.assertEqual(
            (budget["total_model_cap"], budget["grok_cap"], budget["composer_cap"]),
            (20, 18, 2),
        )
        self.assertEqual(budget["current_graph"], current_graph())
        self.assertEqual(budget["launch_command"], ".cursor/commands/manual-market-watch-review.md")
        stale = dict(budget)
        stale["total_model_cap"] = 19
        with self.assertRaises(CallGraphError):
            assert_launch_budget(stale)

    def test_launch_text_states_twenty_and_has_no_stale_nineteen_ceiling(self) -> None:
        marker = current_graph_marker()
        self.assertIn('"total_calls":20', marker)
        self.assertIn('"learning_examiner":1', marker)
        for path in LAUNCH_TEXTS:
            text = path.read_text(encoding="utf-8")
            for stale in STALE_CEILINGS:
                self.assertNotIn(stale, text, f"{path} still contains stale ceiling {stale!r}")
        for command in LAUNCH_TEXTS[:2]:
            self.assertIn(marker, command.read_text(encoding="utf-8"))
        authority = (ROOT / "docs" / "ACP_ONE_SHOT_AUTHORITY.md").read_text(encoding="utf-8")
        self.assertIn("1 parent + 1 synthesis + 14 traders + 3 automated PMs + 1 learning examiner", authority)
        self.assertIn('"learning_examiner": 1', authority)

    def test_validator_and_budget_hook_reject_a_nineteen_ceiling_and_excess_calls(self) -> None:
        execution = {
            "parent_model": "grok-4.6",
            "allowed_subagent_models": ["composer-2.5", "grok-4.6"],
            "total_model_cap": 19,
            "grok_cap": 18,
            "composer_cap": 2,
            "declared_total_model_calls": 19,
            "declared_grok_calls": 18,
            "declared_composer_calls": 1,
            "other_models_calls": 0,
            "auto_used": False,
        }
        with self.assertRaises(SchemaError) as stale_cap:
            validate_execution(execution)
        self.assertIn("approved Market Watch contract", str(stale_cap.exception))

        excess = dict(execution)
        excess["total_model_cap"] = 20
        excess["declared_total_model_calls"] = 21
        excess["declared_grok_calls"] = 19
        excess["declared_composer_calls"] = 2
        with self.assertRaises(SchemaError) as over_cap:
            validate_execution(excess)
        self.assertIn("exceed the run budget", str(over_cap.exception))

        hook = _budget_hook()
        required = hook.POLICIES["overnight"]["required"]
        self.assertEqual(
            (required["total_model_cap"], required["grok_cap"], required["composer_cap"]),
            (20, 18, 2),
        )
        bad_policy = dict(required)
        bad_policy["total_model_cap"] = 19
        with self.assertRaises(SystemExit):
            hook.validate_policy("overnight", bad_policy, hook.POLICIES["overnight"])

    def test_acceptance_workflow_does_not_push_apply_commit_onto_the_pr_head(self) -> None:
        workflow = Path(ROOT / ".github" / "workflows" / "overnight-scheduled-output.yml").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("github.event.pull_request.head.ref", workflow)
        apply_at = workflow.index("Commit canonical acceptance state on main")
        merge_at = workflow.index("merge_accepted_output.sh")
        self.assertLess(merge_at, apply_at)
        self.assertIn("HEAD_REF: main", workflow)


if __name__ == "__main__":
    unittest.main()
