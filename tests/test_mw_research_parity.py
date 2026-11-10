"""The research renderer stays in lockstep with deploy-pages.yml, and the
workflow wiring keeps research and final publication separate.

The static base is one module. deploy-pages.yml invokes its CLIs, and those
CLIs match the research path functions on the repository inputs.
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

from scripts.market_watch_launch import research_static_base as base

REPO = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO / ".github" / "workflows"
DEPLOY = (WORKFLOWS / "deploy-pages.yml").read_text(encoding="utf-8")
LAUNCH_WF = (WORKFLOWS / "launch-market-watch.yml").read_text(encoding="utf-8")
RESEARCH_SRC = (REPO / "scripts" / "market_watch_launch" / "research_pages.py").read_text(encoding="utf-8")

# deploy-pages entrypoints the research edition deliberately does not run.
EXEMPT_ENTRYPOINTS = {
    "scripts/market_state.py": "research publishes a frozen market payload through public_snapshot; a missing payload is an explicit unavailable document and does not call market_state.py",
    "scripts/policy_state.py": "research uses the committed policy artifact; it does not refresh live policy data",
    "scripts/temperature_level.py": "diagnostic --print-levels; research recomputes scores from the staged histories instead",
    "scripts.market_watch_launch.pages_dispatch": "final-edition dispatch binding and dataset verification",
    "scripts.market_watch_launch.publication_release": "final-edition stamp and guard; research stamps through research_pages",
    "scripts.market_watch_launch.pages_recovery": "final-edition Stage 08 in-run reconciliation",
    "scripts.market_watch_launch.research_static_base": "shared static-base CLI; research calls the same functions in-process",
    "scripts.market_watch_launch.render_steps": "shared hard/optional render runner; research applies the same step policy in-process",
    "scripts.market_watch_launch.publication_checks": "shared final-edition integrity checks after the stamp",
    "scripts.market_watch_launch.publication_issues": "shared issues feed; never a publication veto",
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
    def test_workflow_has_no_inline_static_base_transforms(self):
        for needle in (
            "payload_v6",
            "patch_v7/last24",
            "patch_v9/news_rollup",
            "patch_v8/",
            "2c68341978db2ccc8efdd8f1af7bee4e105c89427f741bb10e7747cb98dde917",
            "v6 base already contains v7 patch",
            "rolling-news anchors changed",
            "temperature score patch already present",
        ):
            self.assertNotIn(needle, DEPLOY, needle)
        blocks = step_blocks(DEPLOY)
        self.assertIn(
            "python3 -m scripts.market_watch_launch.research_static_base base --root . --out _site/index.html",
            blocks["Rebuild static base"],
        )
        self.assertIn(
            "python3 -m scripts.market_watch_launch.research_static_base temperature-inputs --root . --html _site/index.html",
            blocks["Restore 1-100 temperature input scores"],
        )
        for retired in (
            "Rebuild v6 base",
            "Apply last-24-hours patch",
            "Apply rolling news rollup",
        ):
            self.assertNotIn(retired, blocks)

    def test_cli_output_matches_research_functions(self):
        env = dict(os.environ, PYTHONPATH=str(REPO))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "index.html"
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.market_watch_launch.research_static_base",
                    "base",
                    "--root",
                    str(REPO),
                    "--out",
                    str(out),
                ],
                cwd=REPO,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            expected = base.apply_news_rollup(REPO, base.apply_last24(REPO, base.rebuild_v6_base(REPO)))
            self.assertEqual(out.read_bytes(), expected.encode("utf-8"))

            proc = subprocess.run(
                [sys.executable, "scripts/apply_six_economy_dashboard.py", str(out)],
                cwd=REPO,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            six = out.read_text(encoding="utf-8")
            base.assert_six_economies(six)
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.market_watch_launch.research_static_base",
                    "temperature-inputs",
                    "--root",
                    str(REPO),
                    "--html",
                    str(out),
                ],
                cwd=REPO,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            self.assertEqual(out.read_bytes(), base.apply_temperature_inputs(REPO, six).encode("utf-8"))

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
            if exempt.startswith("scripts.market_watch_launch."):
                self.assertIn(exempt, DEPLOY, f"exemption {exempt} must appear in deploy-pages.yml")

    def test_static_steps_ported_are_the_ones_in_deploy_pages(self):
        blocks = step_blocks(DEPLOY)
        self.assertIn("Rebuild static base", blocks)
        self.assertIn("Restore 1-100 temperature input scores", blocks)
        self.assertIn("research_static_base base", blocks["Rebuild static base"])
        self.assertIn("research_static_base temperature-inputs", blocks["Restore 1-100 temperature input scores"])


class LaunchResearchWorkflowWiringTests(unittest.TestCase):
    def test_removed_coordinator_and_research_workflow(self):
        self.assertFalse((WORKFLOWS / "publish-research-pages.yml").is_file())
        self.assertFalse((REPO / "scripts/market_watch_launch/publication_coordinator.py").is_file())
        for wf_path in WORKFLOWS.glob("*.yml"):
            text = wf_path.read_text(encoding="utf-8")
            for forbidden in (
                "publication_coordinator",
                "final-wait",
                "research-check",
                "actions/workflows/deploy-pages.yml/runs",
            ):
                self.assertNotIn(forbidden, text, wf_path.name)

    def test_research_job_wiring(self):
        research = job_block(LAUNCH_WF, "research")
        self.assertIn("needs: [guard, orchestrate]", research)
        self.assertIn("github.ref == 'refs/heads/main'", research)
        self.assertIn("needs.guard.outputs.provider == 'acp'", research)
        self.assertIn("needs.guard.outputs.mode == 'live'", research)
        self.assertIn("group: pages-production", research)
        self.assertIn("cancel-in-progress: false", research)
        order = step_order(research)
        expected = [
            "Checkout main",
            "Set up Python",
            "Install market-state dependencies",
            "Select this launch's verified Stage 04 freeze",
            "Build and validate research edition",
            "Upload Pages artifact",
            "Configure Pages",
            "Recheck eligibility and publication order on fresh main",
            "Deploy to GitHub Pages",
            "Verify public page serves this research edition",
            "Commit research publication receipt",
            "Fail when the public read-back did not verify",
        ]
        self.assertEqual(order, expected)
        guard_i = order.index("Recheck eligibility and publication order on fresh main")
        deploy_i = order.index("Deploy to GitHub Pages")
        self.assertEqual(guard_i + 1, deploy_i)
        self.assertIn("steps.guard.outputs.deploy == 'true'", research)
        verify = research[research.index("- name: Verify public page serves this research edition") :]
        self.assertIn("continue-on-error: true", verify.split("- name: Commit", 1)[0])
        self.assertNotIn("--allow-superseded", verify)
        receipt = research[research.index("- name: Commit research publication receipt") :]
        self.assertIn('receipt="data/market_watch_launches/${LAUNCH_ID}/research_pages.json"', receipt)
        self.assertIn('git add -- "$receipt"', receipt)
        self.assertNotIn("git add -A", receipt)
        self.assertNotIn("git add data", receipt)

    def test_handoff_job_and_orchestrate_no_longer_handoff(self):
        handoff = job_block(LAUNCH_WF, "handoff")
        self.assertIn("needs: [guard, orchestrate, research]", handoff)
        self.assertIn("--name 05_acp_handoff", handoff)
        orchestrate = job_block(LAUNCH_WF, "orchestrate")
        self.assertNotIn("05_acp_handoff", orchestrate)

    def test_launch_workflow_has_no_polling_or_cross_workflow_hops(self):
        lowered = LAUNCH_WF.lower()
        self.assertNotIn("actions: read", LAUNCH_WF)
        self.assertNotIn("schedule:", LAUNCH_WF)
        self.assertNotIn("sleep 15", LAUNCH_WF)
        self.assertNotIn("workflow_run:", LAUNCH_WF)
        for forbidden in ("cursor", "06_acceptance", "07_finalize", "08_pages", "gh workflow run", "deploy-pages.yml"):
            self.assertNotIn(forbidden, lowered)
        for provider_secret in (
            "cursor_api_key",
            "openai_api_key",
            "anthropic_api_key",
            "secrets.github_token",
        ):
            self.assertNotIn(provider_secret, lowered)
        # The only repository secret in this workflow is the BEA GDP data-source
        # key, and only on the launch CLI step that runs ingestion.
        allowed = "secrets.bea_api_key"
        self.assertEqual(lowered.count("secrets."), 1)
        self.assertEqual(lowered.count(allowed), 1)
        orchestrate = job_block(LAUNCH_WF, "orchestrate")
        launch_step = orchestrate.split("- name: Run launch CLI", 1)[1].split("- name:", 1)[0]
        self.assertIn("BEA_API_KEY: ${{ secrets.BEA_API_KEY }}", launch_step)
        self.assertEqual(launch_step.lower().count("secrets."), 1)
        for job in ("guard", "research", "handoff", "unit-tests"):
            self.assertNotIn("secrets.", job_block(LAUNCH_WF, job).lower())

    def test_launch_concurrency_routes_only_real_launches(self):
        conc = re.search(r"^concurrency:\n(.*?)^jobs:", LAUNCH_WF, flags=re.M | re.S).group(1)
        self.assertIn("market-watch-manual-launch", conc)
        self.assertIn("[launch-market-watch]", conc)
        self.assertIn("market-watch-launch-other", conc)


class FinalWorkflowWiringTests(unittest.TestCase):
    def test_final_publication_hard_gates_remain(self):
        for needle in (
            "REQUIRE_DATASET=(--require-dataset)",
            "assert_published_trader_room(packet, selected)",
            "validate_public_packet(packet)",
            "validate_snapshot(packet)",
            "validate_score_sources.py",
            'cmp data/temperature_scores.json',
            "node --check patch_v12/market-data.js",
            "pages_dispatch bind-checkout",
            "pages_dispatch verify-public",
            "publication_checks final --site-dir _site --root .",
            "publication_issues publish --site-dir _site --root .",
            "publication_release stamp-final --site-dir _site",
            "publication_release guard --site-dir _site",
            'MW_RENDER_DIAGNOSTICS=${RUNNER_TEMP}/render-diagnostics.jsonl',
            "cancel-in-progress: ${{ github.event_name != 'workflow_dispatch' }}",
            "group: ${{ github.event_name == 'workflow_dispatch' && 'pages-production'",
        ):
            self.assertIn(needle, DEPLOY, needle)
        for removed in (
            "${{ runner.temp }}/render-diagnostics",
            "stale Michigan 47.8",
            "stale petrol sentence remains",
            "official_release_cache.json version must be 1",
            "missing accepted public news context for Pages HTML assertion",
            "scoreboard still labeled Live",
        ):
            self.assertNotIn(removed, DEPLOY, removed)

    def test_stamp_and_guard_order_in_final_build(self):
        build = job_block(DEPLOY, "build")
        order = step_order(build)
        self.assertLess(order.index("Apply dashboard repair"), order.index("Stamp final publication edition"))
        self.assertLess(order.index("Stamp final publication edition"), order.index("Check final publication integrity"))
        self.assertLess(order.index("Check final publication integrity"), order.index("Publish issues feed"))
        self.assertLess(order.index("Publish issues feed"), order.index("Configure Pages"))
        self.assertLess(order.index("Configure Pages"), order.index("Refuse to publish over a newer edition"))
        self.assertLess(order.index("Refuse to publish over a newer edition"), order.index("Upload Pages artifact"))
        guard = build[build.index("- name: Refuse to publish over a newer edition") :]
        self.assertIn("if: github.event_name == 'workflow_dispatch'", guard.split("- name:", 2)[1])

    def test_final_deploy_rechecks_order_without_coordinator(self):
        deploy = job_block(DEPLOY, "deploy")
        order = step_order(deploy)
        names = (
            "Checkout publication verifier",
            "Checkout fresh main for publication order",
            "Download publication release",
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
        self.assertNotIn("actions: read", deploy)
        self.assertNotIn("publication_coordinator", deploy)
        self.assertNotIn("Wait for in-flight research deploy", deploy)
        self.assertIn("--root _publication_main", deploy)
        self.assertIn("needs.build.outputs.pages_base_url", deploy)
        build = job_block(DEPLOY, "build")
        self.assertIn("pages_base_url: ${{ steps.pages.outputs.base_url }}", build)
        self.assertIn("if: github.event_name != 'pull_request'", deploy)

    def test_reconcile_job_records_stage_08_in_run(self):
        reconcile = job_block(DEPLOY, "reconcile")
        self.assertIn("needs: [build, deploy]", reconcile)
        for cond in (
            "github.event_name == 'workflow_dispatch'",
            "github.ref == 'refs/heads/main'",
            "github.event.inputs.launch_id != ''",
            "needs.deploy.result == 'success'",
        ):
            self.assertIn(cond, reconcile)
        self.assertIn("contents: write", reconcile)
        self.assertNotIn("concurrency:", reconcile)
        self.assertIn("pages_recovery in-run-evidence", reconcile)
        self.assertIn("reconcile_published_pages.sh", reconcile)

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
        for name in ("launch-continuation.yml", "reconcile-published-pages.yml", "deploy-pages.yml"):
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
            "tests.test_mw_launch_milestones",
            "tests.test_mw_two_trigger_contract",
            "tests.test_mw_research_pages",
            "tests.test_mw_research_headlines",
            "tests.test_mw_pages_in_run_reconcile",
            "tests.test_mw_research_parity",
        ):
            self.assertIn(module, LAUNCH_WF)
        unit = job_block(LAUNCH_WF, "unit-tests")
        self.assertIn("fetch-depth: 0", unit)


if __name__ == "__main__":
    unittest.main()
