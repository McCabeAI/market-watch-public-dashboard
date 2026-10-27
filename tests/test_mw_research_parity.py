"""The research renderer stays in lockstep with deploy-pages.yml, and the
workflow wiring keeps research and final publication separate.

The static-base checks execute the actual deploy-pages heredocs and the
``research_static_base`` port on the same repository inputs and require
byte-identical output.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from scripts.market_watch_launch import publication_coordinator as coordinator
from scripts.market_watch_launch import research_static_base as base

REPO = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO / ".github" / "workflows"
DEPLOY = (WORKFLOWS / "deploy-pages.yml").read_text(encoding="utf-8")
RESEARCH_WF = (WORKFLOWS / "publish-research-pages.yml").read_text(encoding="utf-8")
LAUNCH_WF = (WORKFLOWS / "launch-market-watch.yml").read_text(encoding="utf-8")
RESEARCH_SRC = (REPO / "scripts" / "market_watch_launch" / "research_pages.py").read_text(encoding="utf-8")

# deploy-pages entrypoints the research edition deliberately does not run.
EXEMPT_ENTRYPOINTS = {
    "scripts/market_state.py": "research serves the frozen packet's market_state through cross_asset_data.public_snapshot",
    "scripts/policy_state.py": "research uses the committed policy artifact; it does not refresh live policy data",
    "scripts/temperature_level.py": "diagnostic --print-levels; research recomputes scores from the staged histories instead",
    "scripts.market_watch_launch.pages_dispatch": "final-edition dispatch binding and dataset verification",
    "scripts.market_watch_launch.publication_release": "final-edition stamp and guard; research stamps through research_pages",
    "scripts.market_watch_launch.publication_coordinator": "production publication ordering; the research workflow calls it directly, not the renderer",
}


def step_blocks(workflow: str) -> dict[str, str]:
    """Map step name to its dedented ``run: |`` script."""
    lines = workflow.splitlines()
    blocks: dict[str, str] = {}
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)- name: (.+)$", line)
        if not match:
            continue
        indent = len(match.group(1))
        name = match.group(2).strip()
        for cursor in range(index + 1, len(lines)):
            current = lines[cursor]
            if re.match(rf"^\s{{0,{indent}}}- ", current) or (current.strip() and len(current) - len(current.lstrip()) <= indent):
                break
            run = re.match(r"^(\s*)run: \|\s*$", current)
            if run:
                key_indent = len(run.group(1))
                body = []
                for inner in lines[cursor + 1 :]:
                    if inner.strip() and len(inner) - len(inner.lstrip()) <= key_indent:
                        break
                    body.append(inner)
                blocks[name] = textwrap.dedent("\n".join(body)) + "\n"
                break
    return blocks


def job_block(workflow: str, job: str) -> str:
    match = re.search(rf"^  {re.escape(job)}:\n(.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)", workflow, flags=re.M | re.S)
    if not match:
        raise AssertionError(f"job {job} missing")
    return match.group(1)


def step_order(block: str) -> list[str]:
    return [name.strip() for name in re.findall(r"^\s*- name: (.+)$", block, flags=re.M)]


class StaticBaseParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.work = Path(cls._tmp.name) / "work"
        cls.scratch = Path(cls._tmp.name) / "scratch"
        cls.bin = Path(cls._tmp.name) / "bin"
        for path in (cls.work, cls.scratch, cls.bin):
            path.mkdir()
        for name in ("payload_v6", "patch_v7", "patch_v8", "patch_v9", "scripts", "data"):
            (cls.work / name).symlink_to(REPO / name)
        (cls.bin / "python").symlink_to(sys.executable)
        cls.blocks = step_blocks(DEPLOY)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_step(self, name: str) -> None:
        script = self.blocks[name].replace("/tmp/", f"{self.scratch}/")
        env = dict(os.environ, PATH=f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}", PYTHONPATH=str(REPO))
        proc = subprocess.run(["bash", "-c", script], cwd=self.work, env=env, capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, f"{name}: {proc.stderr[-2000:]}")

    def site_html(self) -> str:
        return (self.work / "_site" / "index.html").read_text()

    def test_workflow_static_base_steps_match_research_port(self):
        self.run_step("Rebuild v6 base")
        v6 = base.rebuild_v6_base(REPO)
        self.assertEqual((self.scratch / "v6.html").read_bytes(), v6.encode("utf-8"))

        self.run_step("Apply last-24-hours patch")
        last24 = base.apply_last24(REPO, v6)
        self.assertEqual(self.site_html(), last24)

        self.run_step("Apply rolling news rollup")
        rolled = base.apply_news_rollup(REPO, last24)
        self.assertEqual(self.site_html(), rolled)

        self.run_step("Extend dashboard to six economies")
        six = self.site_html()
        base.assert_six_economies(six)

        self.run_step("Restore 1-100 temperature input scores")
        self.assertEqual(self.site_html(), base.apply_temperature_inputs(REPO, six))

    def test_port_rejects_changed_anchors(self):
        v6 = base.rebuild_v6_base(REPO)
        with self.assertRaises(base.StaticBaseError):
            base.apply_last24(REPO, v6.replace(base.TOP_DRIVERS_ANCHOR, ""))
        with self.assertRaises(base.StaticBaseError):
            base.apply_temperature_inputs(REPO, v6.replace('<div class="cdetail nz">', ""))


class EntrypointCoverageTests(unittest.TestCase):
    def test_every_deploy_pages_renderer_runs_in_research_or_is_exempt(self):
        entrypoints = set(re.findall(r"python3? (?:-m )?(scripts[/.][A-Za-z0-9_/.]+?)(?:\s|$)", DEPLOY))
        self.assertGreater(len(entrypoints), 15)
        for entry in sorted(entrypoints):
            with self.subTest(entry=entry):
                if entry in EXEMPT_ENTRYPOINTS:
                    continue
                self.assertIn(f'"{entry}"', RESEARCH_SRC, f"{entry} runs in deploy-pages but not in the research renderer")
        for exempt in EXEMPT_ENTRYPOINTS:
            self.assertIn(exempt, entrypoints, f"stale exemption {exempt}")

    def test_static_steps_ported_are_the_ones_in_deploy_pages(self):
        blocks = step_blocks(DEPLOY)
        for name in (
            "Rebuild v6 base",
            "Apply last-24-hours patch",
            "Apply rolling news rollup",
            "Restore 1-100 temperature input scores",
        ):
            self.assertIn(name, blocks)


class ResearchWorkflowWiringTests(unittest.TestCase):
    def test_trigger_is_launch_completion_only(self):
        triggers = re.search(r"^on:\n(.*?)^permissions:", RESEARCH_WF, flags=re.M | re.S).group(1)
        active = "\n".join(line for line in triggers.splitlines() if not line.strip().startswith("#"))
        self.assertIn("workflow_run:", active)
        self.assertIn('workflows: ["Launch Market Watch"]', active)
        for forbidden in ("workflow_dispatch", "schedule", "push:", "pull_request", "issues:", "repository_dispatch"):
            self.assertNotIn(forbidden, active)
        research_job = job_block(RESEARCH_WF, "research")
        self.assertIn("github.event.workflow_run.head_branch == 'main'", research_job)

    def test_research_deploy_is_outside_production_group_and_yields(self):
        self.assertNotIn("pages-production", RESEARCH_WF)
        deploy = job_block(RESEARCH_WF, "deploy")
        self.assertNotIn("concurrency:", deploy)
        wf_conc = re.search(r"^concurrency:\n(.*?)^jobs:", RESEARCH_WF, flags=re.M | re.S).group(1)
        self.assertIn("group: market-watch-research-pages", wf_conc)
        self.assertIn("cancel-in-progress: false", wf_conc)
        order = step_order(deploy)
        self.assertEqual(order[0], "Record deploy job start")
        self.assertLess(order.index("Record deploy job start"), order.index("Checkout fresh main"))
        guard_i = order.index("Recheck eligibility and publication order on fresh main")
        yield_i = order.index("Yield to production Pages deploys")
        deploy_i = order.index("Deploy to GitHub Pages")
        self.assertLess(guard_i, yield_i)
        self.assertEqual(yield_i + 1, deploy_i)
        self.assertIn("steps.guard.outputs.deploy == 'true'", deploy)
        self.assertIn("steps.claim.outputs.deploy == 'true'", deploy)
        self.assertIn("actions: read", deploy)
        self.assertIn("timeout-minutes: 12", deploy)
        self.assertIn("timeout: 300000", deploy)
        self.assertIn(f"name: {coordinator.RESEARCH_DEPLOY_JOB}", RESEARCH_WF)
        self.assertIn(coordinator.RESEARCH_DEPLOY_STEP, deploy)
        self.assertIn("ref: main", deploy)
        self.assertIn("--allow-superseded", deploy)

    def test_build_refuses_while_final_deploy_active(self):
        research = job_block(RESEARCH_WF, "research")
        order = step_order(research)
        self.assertLess(order.index("Refuse while a final Pages deploy is queued or running"), order.index("Build and validate research edition"))
        self.assertIn("research_pages gate", research)
        self.assertIn("--channel production", research)

    def test_record_job_commits_only_the_receipt(self):
        record = job_block(RESEARCH_WF, "record")
        self.assertIn("contents: write", record)
        self.assertIn('receipt="data/market_watch_launches/${LAUNCH_ID}/research_pages.json"', record)
        self.assertIn('git add -- "$receipt"', record)
        self.assertIn("unexpected", record)
        self.assertNotIn("git add -A", record)
        self.assertNotIn("git add data", record)
        for other_job in ("research", "deploy"):
            self.assertNotIn("contents: write", job_block(RESEARCH_WF, other_job))

    def test_research_workflow_has_no_model_or_launch_authority(self):
        lowered = RESEARCH_WF.lower()
        for forbidden in ("secrets.", "cursor", "acp_", "05_acp_handoff", "market_watch_launch.cli", "launch.json", "08_pages", "reconcile"):
            self.assertNotIn(forbidden, lowered)


class FinalWorkflowWiringTests(unittest.TestCase):
    def test_final_publication_contract_is_unchanged(self):
        for needle in (
            "REQUIRE_DATASET=(--require-dataset)",
            'assert packet.get("seat_count") == 14',
            "validate_public_packet(packet)",
            "pages_dispatch bind-checkout",
            "pages_dispatch verify-public",
            "cancel-in-progress: true",
            "group: ${{ github.event_name == 'workflow_dispatch' && 'pages-production'",
        ):
            self.assertIn(needle, DEPLOY)

    def test_stamp_and_guard_order_in_final_build(self):
        build = job_block(DEPLOY, "build")
        order = step_order(build)
        self.assertLess(order.index("Apply dashboard repair"), order.index("Stamp final publication edition"))
        self.assertLess(order.index("Stamp final publication edition"), order.index("Configure Pages"))
        self.assertLess(order.index("Configure Pages"), order.index("Refuse to publish over a newer edition"))
        self.assertLess(order.index("Refuse to publish over a newer edition"), order.index("Upload Pages artifact"))
        guard = build[build.index("- name: Refuse to publish over a newer edition") :]
        self.assertIn("if: github.event_name == 'workflow_dispatch'", guard.split("- name:", 2)[1])

    def test_final_deploy_waits_for_research_then_rechecks_order(self):
        deploy = job_block(DEPLOY, "deploy")
        order = step_order(deploy)
        names = (
            "Checkout publication coordinator",
            "Checkout fresh main for publication order",
            "Download publication release",
            "Wait for in-flight research deploy",
            "Recheck publication order before deploy",
        )
        indices = [order.index(n) for n in names]
        for left, right in zip(indices, indices[1:]):
            self.assertLess(left, right)
        recheck_i = order.index("Recheck publication order before deploy")
        self.assertEqual(recheck_i + 1, order.index("Deploy to GitHub Pages"))
        for name in names:
            block = deploy[deploy.index(f"- name: {name}") :]
            self.assertIn("if: github.event_name == 'workflow_dispatch'", block.split("- name:", 2)[1])
        self.assertIn("actions: read", deploy)
        self.assertIn("--root _publication_main", deploy)
        self.assertIn("needs.build.outputs.pages_base_url", deploy)
        build = job_block(DEPLOY, "build")
        self.assertIn("pages_base_url: ${{ steps.pages.outputs.base_url }}", build)
        self.assertTrue((WORKFLOWS / coordinator.DEPLOY_PAGES_WORKFLOW).is_file())
        self.assertTrue((WORKFLOWS / coordinator.RESEARCH_WORKFLOW).is_file())

    def test_release_readback_does_not_gate_stage08(self):
        deploy = job_block(DEPLOY, "deploy")
        report = deploy[deploy.index("- name: Report public publication edition") :]
        self.assertIn("continue-on-error: true", report)
        verify = deploy[
            deploy.index("- name: Verify public page serves this dataset") : deploy.index(
                "- name: Report public publication edition"
            )
        ]
        self.assertNotIn("continue-on-error", verify)

    def test_launch_and_recovery_workflows_do_not_depend_on_research(self):
        for name in ("launch-market-watch.yml", "launch-continuation.yml", "reconcile-published-pages.yml", "deploy-pages.yml"):
            text = (WORKFLOWS / name).read_text(encoding="utf-8")
            self.assertNotIn("Publish Market Watch Research Edition", text, name)
            self.assertNotIn("publish-research-pages", text, name)
            self.assertNotIn("market_watch_launch.research_pages", text, name)
            self.assertNotIn("research_pages.json", text, name)
        reconcile = (WORKFLOWS / "reconcile-published-pages.yml").read_text(encoding="utf-8")
        self.assertIn('workflows: ["Deploy Market Watch Dashboard"]', reconcile)

    def test_new_tests_run_in_launch_unit_suite(self):
        for module in (
            "tests.test_mw_publication_release",
            "tests.test_mw_publication_coordinator",
            "tests.test_mw_research_pages",
            "tests.test_mw_research_parity",
        ):
            self.assertIn(module, LAUNCH_WF)
        unit = job_block(LAUNCH_WF, "unit-tests")
        self.assertIn("fetch-depth: 0", unit)


if __name__ == "__main__":
    unittest.main()
