from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.pm.launch import build_pm_launch_plan
from scripts.pm.models import (
    FORBIDDEN_PM_TASK_PRINCIPAL_MODELS,
    PM_AGENT_FRONTMATTER_MODEL,
    PM_PRINCIPAL_MODEL,
    assert_pm_launch_mechanism,
    assert_pm_principal_model,
    pm_hook_policy,
)
from scripts.trader_room.constants import REGISTRY_PATH
from scripts.trader_room.models import load_registry

ROOT = Path(__file__).resolve().parents[1]


class PMLaunchPlanTests(unittest.TestCase):
    def test_launch_plan_uses_custom_agents_not_task_slugs(self) -> None:
        plan = build_pm_launch_plan(
            run_id="tr-20260919T214000Z-ondemand",
            evidence_cutoff="2026-09-19T21:40:00Z",
            evidence_packet_sha256="f8424b8a",
        )
        self.assertEqual(plan["requested_principal"], PM_PRINCIPAL_MODEL)
        self.assertEqual(plan["launch_mechanism"], "cursor_custom_agent")
        for pm_id in ("swinger", "pragmatist", "grinder"):
            agent = plan["agents"][pm_id]
            self.assertEqual(agent["custom_agent"], pm_id)
            self.assertEqual(agent["frontmatter_model"], PM_AGENT_FRONTMATTER_MODEL)
            forbidden = agent["forbidden_principal_launch"]["task_model_parameter"]
            self.assertIn("grok-4.6", forbidden)
            self.assertIn("cursor-grok-4.6-high-fast", forbidden)

    def test_registry_documents_pm_routing(self) -> None:
        registry = load_registry()
        on_disk = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(registry["advocate_model"], PM_PRINCIPAL_MODEL)
        self.assertEqual(on_disk["pm_principal_model"], PM_PRINCIPAL_MODEL)
        self.assertEqual(on_disk["pm_agent_frontmatter_model"], PM_AGENT_FRONTMATTER_MODEL)
        self.assertEqual(on_disk["pm_principal_launch_mechanism"], "cursor_custom_agent")

    def test_pm_agent_frontmatter_matches_trader_room(self) -> None:
        for pm_id in ("swinger", "pragmatist", "grinder"):
            text = (ROOT / ".cursor" / "agents" / f"{pm_id}.md").read_text(encoding="utf-8")
            self.assertIn("model: grok-4.6[]", text)
            assert_pm_principal_model("grok-4.6[]")

    def test_task_runtime_slug_rejected_under_pm_policy(self) -> None:
        hook = ROOT / ".cursor" / "hooks" / "enforce-subagent-models.sh"
        policy = pm_hook_policy()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write(policy + "\n")
            transcript = handle.name
        try:
            for slug in ("cursor-grok-4.6-high-fast", "cursor-grok-4.6-high"):
                proc = subprocess.run(
                    ["sh", str(hook), json.dumps({"subagent_model": slug, "transcript_path": transcript})],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(proc.returncode, 0, slug)
            ok = subprocess.run(
                ["sh", str(hook), json.dumps({"subagent_model": "grok-4.6", "transcript_path": transcript})],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(ok.returncode, 0, ok.stdout)
        finally:
            Path(transcript).unlink(missing_ok=True)

    def test_forbidden_task_models_include_inherit_and_grok_slug(self) -> None:
        self.assertIn("inherit", FORBIDDEN_PM_TASK_PRINCIPAL_MODELS)
        self.assertIn("grok-4.6", FORBIDDEN_PM_TASK_PRINCIPAL_MODELS)

    def test_launch_mechanism_guard(self) -> None:
        assert_pm_launch_mechanism("cursor_custom_agent")
        with self.assertRaises(Exception):
            assert_pm_launch_mechanism("task_model_grok-4.6")


if __name__ == "__main__":
    unittest.main()
