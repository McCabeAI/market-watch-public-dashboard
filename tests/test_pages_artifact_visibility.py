"""Exact Pages artifact visibility before deploy-pages.

The results list is injected. These tests do not call GitHub or deploy.
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import unittest
import urllib.error
from pathlib import Path

from scripts.market_watch_launch.pages_artifact_visibility import (
    LIST_PATH,
    MAX_ATTEMPTS,
    PermanentMetadata,
    RetryableMetadata,
    artifact_rows,
    backend_ids_from_runtime_token,
    delay_before_next,
    format_result,
    interpret_listing,
    list_via_results,
    run_wait,
    wait_until_visible,
)

REPO = Path(__file__).resolve().parents[1]
LAUNCH_ID = "mwl-20261124T100050Z-f1607c19"
FREEZE_COMMIT = "0bcdb7cc9172d309983f14035e979833aeb0cc6a"
PACKET_SHA = "6a780ad835844268a3333fe2729dddab24fec781bcdfd93772ec0c227df7f625"
RUN_HEAD = "8cc4f533dfcaa31191e9e53f09317bd2197a9773"
ATTEMPT1_ID = 14910118264
ATTEMPT2_ID = 14916005309
PRIOR_NAME = "github-pages-research-45370439017-1"
NEW_NAME = "github-pages-research-45370439017-2"


def _jwt(scope: str) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps({"scp": scope}).encode()).decode().rstrip("=")
    return f"{header}.{payload}.sig"


class _Response:
    def __init__(self, status: int, body: bytes):
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> bool:
        return False


class InterpretListingTests(unittest.TestCase):
    def test_delayed_visibility_does_not_accept_an_empty_list(self) -> None:
        first = interpret_listing([], name=NEW_NAME, artifact_id=ATTEMPT2_ID)
        self.assertEqual(first.status, "not_visible")
        self.assertTrue(first.retryable)
        later = interpret_listing(
            [{"name": NEW_NAME, "id": ATTEMPT2_ID}],
            name=NEW_NAME,
            artifact_id=ATTEMPT2_ID,
        )
        self.assertEqual(later.status, "visible")
        self.assertEqual(later.artifact_id, ATTEMPT2_ID)

    def test_prior_attempt_artifact_is_not_the_new_name(self) -> None:
        result = interpret_listing(
            [{"name": PRIOR_NAME, "id": ATTEMPT1_ID}],
            name=NEW_NAME,
            artifact_id=ATTEMPT2_ID,
        )
        self.assertEqual(result.status, "not_visible")
        self.assertTrue(result.retryable)
        self.assertEqual(result.seen, ((PRIOR_NAME, ATTEMPT1_ID),))

    def test_name_equality_is_exact(self) -> None:
        rows = [
            {"name": "github-pages-1", "id": 10},
            {"name": "github-pages-10", "id": 11},
            {"name": "github-pages", "id": 12},
        ]
        for name, artifact_id in (("github-pages-1", 10), ("github-pages-10", 11), ("github-pages", 12)):
            result = interpret_listing(rows, name=name, artifact_id=artifact_id)
            self.assertEqual(result.status, "visible", name)
            self.assertEqual(result.artifact_id, artifact_id)
        missing = interpret_listing(rows, name="github-pages-2", artifact_id=99)
        self.assertEqual(missing.status, "not_visible")

    def test_same_name_with_a_different_id_is_not_retryable(self) -> None:
        result = interpret_listing(
            [{"name": NEW_NAME, "id": ATTEMPT1_ID}],
            name=NEW_NAME,
            artifact_id=ATTEMPT2_ID,
        )
        self.assertEqual(result.status, "id_mismatch")
        self.assertFalse(result.retryable)
        self.assertEqual(result.artifact_id, ATTEMPT1_ID)

    def test_duplicate_exact_name_is_ambiguous(self) -> None:
        result = interpret_listing(
            [{"name": NEW_NAME, "id": ATTEMPT2_ID}, {"name": NEW_NAME, "id": ATTEMPT2_ID + 1}],
            name=NEW_NAME,
            artifact_id=ATTEMPT2_ID,
        )
        self.assertEqual(result.status, "ambiguous")
        self.assertFalse(result.retryable)


class WaitLoopTests(unittest.TestCase):
    def test_delayed_visibility_waits_then_succeeds_without_deploying(self) -> None:
        listings = [
            [],
            [{"name": PRIOR_NAME, "id": ATTEMPT1_ID}],
            [{"name": PRIOR_NAME, "id": ATTEMPT1_ID}, {"name": NEW_NAME, "id": ATTEMPT2_ID}],
        ]
        calls: list[int] = []
        sleeps: list[float] = []

        def list_once() -> list[dict]:
            calls.append(1)
            return listings.pop(0)

        result = wait_until_visible(
            name=NEW_NAME,
            artifact_id=ATTEMPT2_ID,
            list_once=list_once,
            sleep=sleeps.append,
            attempts=8,
        )
        self.assertEqual(result.status, "visible")
        self.assertEqual(result.attempts, 3)
        self.assertEqual(result.artifact_id, ATTEMPT2_ID)
        self.assertEqual(sleeps, [delay_before_next(0), delay_before_next(1)])
        self.assertEqual(listings, [])
        self.assertNotIn("deployments", format_result(result))

    def test_timeout_keeps_the_prior_artifact_and_stops(self) -> None:
        sleeps: list[float] = []

        def list_once() -> list[dict]:
            return [{"name": PRIOR_NAME, "id": ATTEMPT1_ID}]

        result = wait_until_visible(
            name=NEW_NAME,
            artifact_id=ATTEMPT2_ID,
            list_once=list_once,
            sleep=sleeps.append,
            attempts=3,
        )
        self.assertEqual(result.status, "not_visible")
        self.assertEqual(result.attempts, 3)
        self.assertEqual(result.seen, ((PRIOR_NAME, ATTEMPT1_ID),))
        self.assertEqual(len(sleeps), 2)
        self.assertEqual(sleeps[0], 2)
        self.assertEqual(sleeps[1], 4)

    def test_transient_metadata_error_then_success(self) -> None:
        state = {"calls": 0}
        sleeps: list[float] = []

        def list_once() -> list[dict]:
            state["calls"] += 1
            if state["calls"] == 1:
                raise RetryableMetadata("results list HTTP 503")
            return [{"name": NEW_NAME, "id": ATTEMPT2_ID}]

        result = wait_until_visible(
            name=NEW_NAME,
            artifact_id=ATTEMPT2_ID,
            list_once=list_once,
            sleep=sleeps.append,
            attempts=4,
        )
        self.assertEqual(result.status, "visible")
        self.assertEqual(result.attempts, 2)
        self.assertEqual(sleeps, [2])

    def test_unauthorized_metadata_stops_immediately(self) -> None:
        calls = {"n": 0}
        sleeps: list[float] = []

        def list_once() -> list[dict]:
            calls["n"] += 1
            raise PermanentMetadata("results list unauthorized HTTP 403")

        result = wait_until_visible(
            name=NEW_NAME,
            artifact_id=ATTEMPT2_ID,
            list_once=list_once,
            sleep=sleeps.append,
        )
        self.assertEqual(result.status, "metadata_error")
        self.assertFalse(result.retryable)
        self.assertEqual(calls["n"], 1)
        self.assertEqual(sleeps, [])

    def test_id_mismatch_does_not_poll_again(self) -> None:
        calls = {"n": 0}

        def list_once() -> list[dict]:
            calls["n"] += 1
            return [{"name": NEW_NAME, "id": ATTEMPT1_ID}]

        result = wait_until_visible(
            name=NEW_NAME,
            artifact_id=ATTEMPT2_ID,
            list_once=list_once,
            sleep=lambda _seconds: self.fail("slept"),
        )
        self.assertEqual(result.status, "id_mismatch")
        self.assertEqual(calls["n"], 1)

    def test_successful_first_listing_does_not_sleep(self) -> None:
        result = wait_until_visible(
            name="github-pages-1",
            artifact_id=42,
            list_once=lambda: [{"name": "github-pages-1", "id": 42}],
            sleep=lambda _seconds: self.fail("slept"),
        )
        self.assertEqual(result.status, "visible")
        self.assertEqual(result.attempts, 1)

    def test_attempt_bound_is_closed(self) -> None:
        with self.assertRaises(PermanentMetadata):
            wait_until_visible(
                name=NEW_NAME,
                artifact_id=ATTEMPT2_ID,
                list_once=lambda: [],
                sleep=lambda _seconds: None,
                attempts=MAX_ATTEMPTS + 1,
            )
        self.assertEqual(delay_before_next(0), 2)
        self.assertEqual(delay_before_next(3), 16)
        self.assertEqual(delay_before_next(6), 16)


class ResultsListTests(unittest.TestCase):
    def test_unfiltered_list_uses_the_runtime_token_and_exact_row(self) -> None:
        token = _jwt("Actions.Results:run-backend:job-backend")
        captured: list[urllib.request.Request] = []

        def opener(request: urllib.request.Request, timeout: float) -> _Response:
            self.assertEqual(timeout, 15)
            captured.append(request)
            body = {
                "artifacts": [
                    {"name": PRIOR_NAME, "databaseId": str(ATTEMPT1_ID), "size": "1"},
                    {"name": NEW_NAME, "databaseId": str(ATTEMPT2_ID), "size": "2"},
                ]
            }
            return _Response(200, json.dumps(body).encode())

        sleeps: list[float] = []
        code = run_wait(
            ["wait"],
            opener=opener,
            sleep=sleeps.append,
            env={
                "PAGES_ARTIFACT_NAME": NEW_NAME,
                "PAGES_ARTIFACT_ID": str(ATTEMPT2_ID),
                "ACTIONS_RUNTIME_TOKEN": token,
                "ACTIONS_RESULTS_URL": "https://results.example.test/api",
            },
        )
        self.assertEqual(code, 0)
        self.assertEqual(sleeps, [])
        self.assertEqual(len(captured), 1)
        request = captured[0]
        self.assertTrue(request.full_url.endswith(LIST_PATH))
        self.assertNotIn("deployments", request.full_url)
        self.assertNotIn(token, request.full_url)
        self.assertTrue(request.get_header("Authorization").startswith("Bearer "))
        payload = json.loads(request.data.decode())
        self.assertEqual(
            payload,
            {
                "workflowRunBackendId": "run-backend",
                "workflowJobRunBackendId": "job-backend",
            },
        )
        self.assertNotIn("nameFilter", payload)
        self.assertNotIn("idFilter", payload)

    def test_http_503_is_retried_and_403_is_not(self) -> None:
        token = _jwt("Actions.Example Actions.Results:run-backend:job-backend")
        calls = {"n": 0}

        def opener(request: urllib.request.Request, timeout: float) -> _Response:
            del request, timeout
            calls["n"] += 1
            if calls["n"] == 1:
                raise urllib.error.HTTPError(
                    "https://results.example.test" + LIST_PATH,
                    503,
                    "unavailable",
                    hdrs=None,
                    fp=io.BytesIO(b""),
                )
            body = {"artifacts": [{"name": NEW_NAME, "databaseId": ATTEMPT2_ID}]}
            return _Response(200, json.dumps(body).encode())

        sleeps: list[float] = []
        code = run_wait(
            ["wait"],
            opener=opener,
            sleep=sleeps.append,
            env={
                "PAGES_ARTIFACT_NAME": NEW_NAME,
                "PAGES_ARTIFACT_ID": str(ATTEMPT2_ID),
                "ACTIONS_RUNTIME_TOKEN": token,
                "ACTIONS_RESULTS_URL": "https://results.example.test/twirp/ignored",
            },
        )
        self.assertEqual(code, 0)
        self.assertEqual(calls["n"], 2)
        self.assertEqual(sleeps, [2])

        def forbidden(request: urllib.request.Request, timeout: float) -> _Response:
            del request, timeout
            raise urllib.error.HTTPError(
                "https://results.example.test" + LIST_PATH,
                403,
                "forbidden",
                hdrs=None,
                fp=io.BytesIO(b""),
            )

        code = run_wait(
            ["wait"],
            opener=forbidden,
            sleep=lambda _seconds: self.fail("slept"),
            env={
                "PAGES_ARTIFACT_NAME": NEW_NAME,
                "PAGES_ARTIFACT_ID": str(ATTEMPT2_ID),
                "ACTIONS_RUNTIME_TOKEN": token,
                "ACTIONS_RESULTS_URL": "https://results.example.test",
            },
        )
        self.assertEqual(code, 4)

    def test_timeout_exit_is_not_a_deploy(self) -> None:
        token = _jwt("Actions.Results:run-backend:job-backend")
        urls: list[str] = []

        def opener(request: urllib.request.Request, timeout: float) -> _Response:
            del timeout
            urls.append(request.full_url)
            return _Response(200, json.dumps({"artifacts": [{"name": PRIOR_NAME, "databaseId": str(ATTEMPT1_ID)}]}).encode())

        code = run_wait(
            ["wait"],
            opener=opener,
            sleep=lambda _seconds: None,
            env={
                "PAGES_ARTIFACT_NAME": NEW_NAME,
                "PAGES_ARTIFACT_ID": str(ATTEMPT2_ID),
                "ACTIONS_RUNTIME_TOKEN": token,
                "ACTIONS_RESULTS_URL": "https://results.example.test",
            },
        )
        self.assertEqual(code, 2)
        self.assertEqual(len(urls), MAX_ATTEMPTS)
        self.assertTrue(all(url.endswith(LIST_PATH) for url in urls))

    def test_missing_id_and_bad_token_do_not_call_the_service(self) -> None:
        def opener(*_args: object, **_kwargs: object) -> _Response:
            raise AssertionError("listed")

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = run_wait(
                ["wait"],
                opener=opener,
                env={
                    "PAGES_ARTIFACT_NAME": NEW_NAME,
                    "PAGES_ARTIFACT_ID": "",
                    "ACTIONS_RUNTIME_TOKEN": _jwt("Actions.Results:run-backend:job-backend"),
                    "ACTIONS_RESULTS_URL": "https://results.example.test",
                },
            )
        self.assertEqual(code, 4)
        self.assertIn("artifact id must be a positive integer", stderr.getvalue())
        with self.assertRaises(PermanentMetadata):
            backend_ids_from_runtime_token("not-a-jwt")
        rows = artifact_rows({"artifacts": [{"name": "github-pages-2", "id": "7"}]})
        self.assertEqual(rows, [{"name": "github-pages-2", "id": 7}])


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
            'gh issue create \\\n',
            '--title "[launch-market-watch] 2026-11-24"',
            '--body ""',
            "Do not re-run failed jobs",
            "Do not `workflow_dispatch` `launch-market-watch.yml`",
            "Do not reopen issue 370",
            "Do not `workflow_dispatch` `deploy-pages.yml`",
            "session_not_today",
            "live_provider_dispatched: false",
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
        research = job_block(launch, "research")
        research_order = step_order(research)
        guard = research_order.index("Recheck eligibility and publication order on fresh main")
        wait = research_order.index("Wait for exact Pages artifact visibility")
        deploy_i = research_order.index("Deploy to GitHub Pages")
        self.assertEqual(guard + 1, wait)
        self.assertEqual(wait + 1, deploy_i)
        self.assertEqual(research.count("actions/deploy-pages@v4"), 1)
        self.assertIn("steps.visibility.outcome == 'success'", research)
        self.assertIn("pages_artifact_visibility wait", research)
        self.assertNotIn("actions: read", research)
        self.assertIn("id: pages-artifact", research)

        final = job_block(deploy, "deploy")
        final_order = step_order(final)
        recheck = final_order.index("Recheck publication order before deploy")
        final_wait = final_order.index("Wait for exact Pages artifact visibility")
        final_deploy = final_order.index("Deploy to GitHub Pages")
        self.assertEqual(recheck + 1, final_wait)
        self.assertEqual(final_wait + 1, final_deploy)
        self.assertEqual(final.count("actions/deploy-pages@v4"), 1)
        self.assertIn("steps.visibility.outcome == 'success'", final)
        self.assertIn("needs.build.outputs.pages_artifact_id", final)
        self.assertNotIn("actions: read", final)
        self.assertIn("pages_artifact_id:", job_block(deploy, "build"))


if __name__ == "__main__":
    unittest.main()
