"""Workflow wiring and Nov 24 recovery facts for the Pages artifact waiter.

The wait decision itself is tested by the JavaScript action suite. This module
does not call GitHub or deploy.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ACTION = REPO / ".github" / "actions" / "wait-for-pages-artifact"
LAUNCH_ID = "mwl-20261124T100050Z-f1607c19"
FREEZE_COMMIT = "0bcdb7cc9172d309983f14035e979833aeb0cc6a"
PACKET_SHA = "6a780ad835844268a3333fe2729dddab24fec781bcdfd93772ec0c227df7f625"
RUN_HEAD = "8cc4f533dfcaa31191e9e53f09317bd2197a9773"
ATTEMPT1_ID = 14910118264
ATTEMPT2_ID = 14916005309
PRIOR_NAME = "github-pages-research-45370439017-1"
NEW_NAME = "github-pages-research-45370439017-2"


class Nov24RecoveryPlanTests(unittest.TestCase):
    def test_committed_freeze_matches_the_recovery_note(self) -> None:
        launch = json.loads((REPO / "data/market_watch_launches" / LAUNCH_ID / "launch.json").read_text(encoding="utf-8"))
        attestation = json.loads(
            (REPO / "data/market_watch_launches" / LAUNCH_ID / "remote_freeze.json").read_text(encoding="utf-8")
        )
        note = (REPO / "docs/operations/nov24_research_pages_artifact_recovery.md").read_text(encoding="utf-8")
        self.assertEqual(launch["status"], "running")
        self.assertEqual(launch["session_date"], "2026-11-24")
        self.assertEqual(launch["base_packet_sha256"], PACKET_SHA)
        self.assertEqual(launch["review_id"], "review-001")
        self.assertFalse(launch["request"]["rerun"])
        for stage in ("00_authenticate", "01_ingest", "02_acquire", "03_quality_gate", "04_freeze"):
            self.assertEqual(launch["stages"][stage]["status"], "succeeded", stage)
        self.assertEqual(launch["stages"]["04_freeze"]["details"]["packet_sha256"], PACKET_SHA)
        self.assertEqual(launch["stages"]["05_acp_handoff"]["status"], "pending")
        self.assertEqual(attestation["commit_sha"], FREEZE_COMMIT)
        self.assertEqual(attestation["packet_sha256"], PACKET_SHA)
        self.assertFalse((REPO / "data/market_watch_launches" / LAUNCH_ID / "research_pages.json").exists())
        for fact in (
            LAUNCH_ID,
            FREEZE_COMMIT,
            PACKET_SHA,
            RUN_HEAD,
            str(ATTEMPT1_ID),
            str(ATTEMPT2_ID),
            PRIOR_NAME,
            NEW_NAME,
            "gh issue create \\\n",
            '--title "[launch-market-watch] 2026-11-24"',
            '--body ""',
            "Do not re-run failed jobs",
            "Do not `workflow_dispatch` `launch-market-watch.yml`",
            "Do not reopen issue 370",
            "Do not `workflow_dispatch` `deploy-pages.yml`",
            "session_not_today",
            "live_provider_dispatched: false",
            "wait-for-pages-artifact",
        ):
            self.assertIn(fact, note, fact)

    def test_resume_through_freeze_does_not_call_handlers_again(self) -> None:
        import tempfile
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from scripts.market_watch_launch.graph import run_launch

        calls: list[str] = []
        when = datetime(2026, 11, 24, 10, 0, tzinfo=ZoneInfo("America/New_York"))
        request = {
            "session_date": "2026-11-24",
            "rerun": False,
            "mode": "fixture",
            "provider": "stub",
            "source": "workflow_dispatch",
            "actor_type": "User",
            "actor": "kevin",
        }

        def handlers() -> dict:
            from scripts.market_watch_launch.contract import STAGES, stage_receipt
            from scripts.overnight.store import sha256_json

            def make(stage: str):
                def _handler(launch: dict, _ctx: dict) -> dict:
                    calls.append(stage)
                    details = {"stage": stage, "launch_id": launch["launch_id"]}
                    prev_idx = STAGES.index(stage)
                    input_sha = None
                    if prev_idx > 0:
                        input_sha = launch["stages"][STAGES[prev_idx - 1]].get("output_sha256")
                    return stage_receipt(
                        stage,
                        status="succeeded",
                        input_sha256=input_sha,
                        output_sha256=sha256_json(details),
                        details=details,
                    )

                return _handler

            return {stage: make(stage) for stage in STAGES}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = run_launch(request, root=root, state_root=root, handlers=handlers(), when=when, through="04_freeze")
            self.assertEqual(first["status"], "running")
            self.assertEqual(
                calls,
                ["00_authenticate", "01_ingest", "02_acquire", "03_quality_gate", "04_freeze"],
            )
            self.assertEqual(first["launch"]["stages"]["05_acp_handoff"]["status"], "pending")
            calls.clear()
            second = run_launch(request, root=root, state_root=root, handlers=handlers(), when=when, through="04_freeze")
            self.assertTrue(second["returned_existing"])
            self.assertEqual(second["launch_id"], first["launch_id"])
            self.assertEqual(calls, [])
            self.assertEqual(
                second["launch"]["stages"]["04_freeze"]["details"]["launch_id"],
                first["launch_id"],
            )


class WorkflowWiringTests(unittest.TestCase):
    def test_both_publication_paths_wait_before_one_deploy(self) -> None:
        from tests.test_mw_research_parity import job_block, step_order

        launch = (REPO / ".github/workflows/launch-market-watch.yml").read_text(encoding="utf-8")
        deploy = (REPO / ".github/workflows/deploy-pages.yml").read_text(encoding="utf-8")
        manifest = (ACTION / "action.yml").read_text(encoding="utf-8")
        entry = (ACTION / "src/main.js").read_text(encoding="utf-8")
        self.assertIn("using: node20", manifest)
        self.assertIn("main: dist/index.js", manifest)
        self.assertIn("client.listArtifacts()", entry)
        self.assertNotIn("findBy", entry)
        self.assertNotIn("ACTIONS_RUNTIME_TOKEN", entry)
        self.assertTrue((ACTION / "dist/index.js").is_file())
        research = job_block(launch, "research")
        research_order = step_order(research)
        guard = research_order.index("Recheck eligibility and publication order on fresh main")
        wait = research_order.index("Wait for exact Pages artifact visibility")
        deploy_i = research_order.index("Deploy to GitHub Pages")
        self.assertEqual(guard + 1, wait)
        self.assertEqual(wait + 1, deploy_i)
        self.assertEqual(research.count("actions/deploy-pages@v4"), 1)
        self.assertEqual(research.count("uses: ./.github/actions/wait-for-pages-artifact"), 1)
        self.assertIn("steps.visibility.outcome == 'success'", research)
        self.assertIn("steps.pages-artifact.outputs.artifact_id", research)
        self.assertNotIn("actions: read", research)
        self.assertNotIn("ACTIONS_RUNTIME_TOKEN", research)
        self.assertNotIn("pages_artifact_visibility", research)
        self.assertIn("id: pages-artifact", research)

        final = job_block(deploy, "deploy")
        final_order = step_order(final)
        recheck = final_order.index("Recheck publication order before deploy")
        final_wait = final_order.index("Wait for exact Pages artifact visibility")
        final_deploy = final_order.index("Deploy to GitHub Pages")
        self.assertEqual(recheck + 1, final_wait)
        self.assertEqual(final_wait + 1, final_deploy)
        self.assertEqual(final.count("actions/deploy-pages@v4"), 1)
        self.assertEqual(final.count("uses: ./.github/actions/wait-for-pages-artifact"), 1)
        self.assertIn("steps.visibility.outcome == 'success'", final)
        self.assertIn("needs.build.outputs.pages_artifact_id", final)
        self.assertNotIn("actions: read", final)
        self.assertNotIn("ACTIONS_RUNTIME_TOKEN", final)
        self.assertIn("pages_artifact_id:", job_block(deploy, "build"))
        self.assertIn("node --test .github/actions/wait-for-pages-artifact/src/wait.test.js", launch)


if __name__ == "__main__":
    unittest.main()
