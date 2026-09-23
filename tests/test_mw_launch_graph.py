"""Unit tests for the manual Market Watch launch graph."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.market_watch_launch.contract import CONCURRENCY_BLOCK, LAUNCH_ID_RE, STAGES
from scripts.market_watch_launch.graph import run_launch
from scripts.market_watch_launch.identity import default_session_date
from scripts.market_watch_launch.state import LaunchStateStore
from scripts.overnight.store import sha256_json

NY = ZoneInfo("America/New_York")
FIXED_WHEN = datetime(2026, 9, 23, 10, 30, 0, tzinfo=NY)


def _success_receipt(stage: str, launch: dict, ctx: dict, extra: dict | None = None) -> dict:
    from scripts.market_watch_launch.contract import stage_receipt

    details = {"stage": stage, "launch_id": launch["launch_id"]}
    if extra:
        details.update(extra)
    prev_idx = STAGES.index(stage)
    input_sha = None
    if prev_idx > 0:
        prev = STAGES[prev_idx - 1]
        input_sha = launch["stages"][prev].get("output_sha256")
    return stage_receipt(
        stage,
        status="succeeded",
        input_sha256=input_sha,
        output_sha256=sha256_json(details),
        details=details,
    )


class MarketWatchLaunchGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state_root = Path(self.tmp.name)
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        self.calls: list[str] = []

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _handlers(self, **overrides):
        def make(stage: str):
            def _handler(launch, ctx):
                self.calls.append(stage)
                if overrides.get(stage):
                    return overrides[stage](launch, ctx)
                return _success_receipt(stage, launch, ctx)

            return _handler

        handlers = {"00_authenticate": make("00_authenticate")}
        for stage in STAGES:
            if stage == "00_authenticate":
                continue
            handlers[stage] = make(stage)
        handlers.update({k: v for k, v in overrides.items() if callable(v)})
        return handlers

    def _request(self, **kwargs) -> dict:
        base = {
            "session_date": "2026-09-23",
            "rerun": False,
            "mode": "fixture",
            "provider": "stub",
            "source": "workflow_dispatch",
            "actor_type": "User",
            "actor": "kevin",
        }
        base.update(kwargs)
        return base

    def test_launch_id_format_and_ny_session_date(self) -> None:
        when = datetime(2026, 9, 23, 23, 45, 0, tzinfo=NY)
        result = run_launch(
            self._request(session_date=None),
            root=self.root,
            state_root=self.state_root,
            handlers=self._handlers(),
            when=when,
        )
        self.assertRegex(result["launch_id"], LAUNCH_ID_RE.pattern)
        self.assertEqual(result["session_date"], default_session_date(when))
        self.assertEqual(result["session_date"], "2026-09-23")

    def test_duplicate_same_session_returns_same_launch_without_rerunning_handlers(self) -> None:
        handlers = self._handlers()
        req = self._request()
        first = run_launch(req, root=self.root, state_root=self.state_root, handlers=handlers, when=FIXED_WHEN)
        self.assertFalse(first["returned_existing"])
        self.assertEqual(first["status"], "succeeded")
        call_count_after_first = len(self.calls)
        second = run_launch(req, root=self.root, state_root=self.state_root, handlers=handlers, when=FIXED_WHEN)
        self.assertTrue(second["returned_existing"])
        self.assertEqual(second["launch_id"], first["launch_id"])
        self.assertEqual(len(self.calls), call_count_after_first)

    def test_explicit_rerun_allocates_new_launch_id(self) -> None:
        handlers = self._handlers()
        req = self._request()
        first = run_launch(req, root=self.root, state_root=self.state_root, handlers=handlers, when=FIXED_WHEN)
        second = run_launch(
            self._request(rerun=True),
            root=self.root,
            state_root=self.state_root,
            handlers=handlers,
            when=FIXED_WHEN,
        )
        self.assertNotEqual(second["launch_id"], first["launch_id"])
        self.assertEqual(second["launch"]["prior_launch_id"], first["launch_id"])
        self.assertTrue(second["launch"]["rerun"])

    def test_second_launch_while_one_live_is_blocked(self) -> None:
        seen: dict[str, int] = {"01": 0}

        def slow_ingest(launch, ctx):
            seen["01"] += 1
            if seen["01"] == 1:
                from scripts.market_watch_launch.contract import stage_receipt

                return stage_receipt(
                    "01_ingest",
                    status="running",
                    input_sha256=launch["stages"]["00_authenticate"]["output_sha256"],
                    details={"partial": True},
                )
            return _success_receipt("01_ingest", launch, ctx)

        handlers = self._handlers()
        handlers["01_ingest"] = slow_ingest
        first = run_launch(
            self._request(session_date="2026-09-24"),
            root=self.root,
            state_root=self.state_root,
            handlers=handlers,
            when=FIXED_WHEN,
        )
        self.assertEqual(first["status"], "running")
        store = LaunchStateStore(self.state_root)
        self.assertIsNotNone(store.live_launch())

        second = run_launch(
            self._request(session_date="2026-09-25", rerun=False),
            root=self.root,
            state_root=self.state_root,
            handlers=handlers,
            when=FIXED_WHEN,
        )
        self.assertEqual(second["status"], "blocked")
        self.assertEqual(second["launch"]["stages"]["00_authenticate"]["reason"], CONCURRENCY_BLOCK)

    def test_crash_resume_retries_failed_stage_without_rerunning_auth(self) -> None:
        attempts = {"01": 0}

        def flaky_ingest(launch, ctx):
            attempts["01"] += 1
            if attempts["01"] == 1:
                raise RuntimeError("simulated crash")
            return _success_receipt("01_ingest", launch, ctx)

        handlers = self._handlers()
        handlers["01_ingest"] = flaky_ingest
        req = self._request()
        first = run_launch(req, root=self.root, state_root=self.state_root, handlers=handlers, when=FIXED_WHEN)
        self.assertEqual(first["status"], "failed")
        self.assertEqual(first["launch"]["stages"]["00_authenticate"]["status"], "succeeded")
        self.assertEqual(attempts["01"], 1)
        auth_calls = self.calls.count("00_authenticate")

        second = run_launch(req, root=self.root, state_root=self.state_root, handlers=handlers, when=FIXED_WHEN)
        self.assertTrue(second["returned_existing"])
        self.assertEqual(second["launch_id"], first["launch_id"])
        self.assertEqual(second["status"], "succeeded")
        self.assertEqual(self.calls.count("00_authenticate"), auth_calls)
        self.assertEqual(attempts["01"], 2)

    def test_hash_drift_on_resume_fails_without_next_stage(self) -> None:
        handlers = self._handlers()
        req = self._request()
        first = run_launch(req, root=self.root, state_root=self.state_root, handlers=handlers, when=FIXED_WHEN)
        self.assertEqual(first["status"], "succeeded")
        store = LaunchStateStore(self.state_root)
        store.mutate_artifact_bytes(first["launch_id"], "00_authenticate", '{"tampered": true}\n')
        self.calls.clear()

        second = run_launch(req, root=self.root, state_root=self.state_root, handlers=handlers, when=FIXED_WHEN)
        self.assertEqual(second["status"], "failed")
        self.assertEqual(second["launch"]["stages"]["00_authenticate"]["reason"], "hash_drift")
        self.assertEqual(self.calls, [])

    def test_bot_actor_stops_at_authenticate(self) -> None:
        handlers = self._handlers()
        handlers.pop("00_authenticate", None)
        result = run_launch(
            self._request(source="github_issue", actor_type="Bot"),
            root=self.root,
            state_root=self.state_root,
            handlers=handlers,
            when=FIXED_WHEN,
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(self.calls, [])
        self.assertEqual(result["launch"]["stages"]["01_ingest"]["status"], "pending")

    def test_blocked_quality_gate_does_not_invoke_later_stages(self) -> None:
        from scripts.market_watch_launch.contract import stage_receipt

        def blocked_gate(launch, ctx):
            self.calls.append("03_quality_gate")
            return stage_receipt(
                "03_quality_gate",
                status="blocked",
                input_sha256=launch["stages"]["02_acquire"]["output_sha256"],
                reason="data_blocked",
                details={"report": "missing US CPI"},
            )

        handlers = self._handlers()
        handlers["03_quality_gate"] = blocked_gate
        result = run_launch(
            self._request(),
            root=self.root,
            state_root=self.state_root,
            handlers=handlers,
            when=FIXED_WHEN,
        )
        self.assertEqual(result["status"], "blocked")
        self.assertIn("03_quality_gate", self.calls)
        self.assertNotIn("04_freeze", self.calls)
        self.assertEqual(result["launch"]["stages"]["04_freeze"]["status"], "pending")

        self.calls.clear()
        again = run_launch(
            self._request(),
            root=self.root,
            state_root=self.state_root,
            handlers=handlers,
            when=FIXED_WHEN,
        )
        self.assertTrue(again["returned_existing"])
        self.assertEqual(self.calls, [])


class IssueBodyTests(unittest.TestCase):
    def test_parse_raw_and_fenced_json(self) -> None:
        from scripts.market_watch_launch.identity import parse_issue_body

        raw = parse_issue_body('{"mode":"live","provider":"acp","rerun":false}')
        self.assertEqual(raw["mode"], "live")
        self.assertFalse(raw["rerun"])
        fenced = parse_issue_body('Please launch.\n```json\n{"mode": "fixture", "provider": "stub", "rerun": true}\n```\n')
        self.assertEqual(fenced["provider"], "stub")
        self.assertTrue(fenced["rerun"])
        self.assertEqual(parse_issue_body("not json"), {})


if __name__ == "__main__":
    unittest.main()
