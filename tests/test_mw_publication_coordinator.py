from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from scripts.market_watch_launch import publication_coordinator as coord


def _run(**fields: object) -> dict:
    base = {
        "event": "workflow_dispatch",
        "head_branch": "main",
        "status": "completed",
        "created_at": "2026-10-27T12:00:00Z",
        "run_started_at": "2026-10-27T12:00:00Z",
        "html_url": "https://example/run",
    }
    base.update(fields)
    return base


class ParseApiTimeTests(unittest.TestCase):
    def test_zulu(self):
        dt = coord.parse_api_time("2026-10-27T12:00:00Z")
        self.assertEqual(dt, datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc))

    def test_offset(self):
        dt = coord.parse_api_time("2026-10-27T08:00:00-04:00")
        self.assertEqual(dt, datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc))

    def test_naive_invalid(self):
        self.assertIsNone(coord.parse_api_time("2026-10-27T12:00:00"))
        self.assertIsNone(coord.parse_api_time("not-a-date"))


class ProductionRunsTests(unittest.TestCase):
    def test_filters(self):
        runs = [
            _run(id=1),
            _run(id=2, event="push"),
            _run(id=3, head_branch="dev"),
        ]
        self.assertEqual(len(coord.production_runs(runs)), 1)

    def test_non_list(self):
        with self.assertRaises(coord.CoordinatorError) as ctx:
            coord.production_runs({})
        self.assertEqual(ctx.exception.reason, "runs_unreadable")


class ResearchDeployDecisionTests(unittest.TestCase):
    def setUp(self):
        self.since = datetime(2026, 10, 27, 13, 0, tzinfo=timezone.utc)

    def test_allowed_empty(self):
        d = coord.research_deploy_decision([], since=self.since)
        self.assertTrue(d["allowed"])
        self.assertEqual(d["reason"], "allowed")

    def test_active_blocks(self):
        d = coord.research_deploy_decision([_run(id=9, status="in_progress")], since=self.since)
        self.assertFalse(d["allowed"])
        self.assertEqual(d["reason"], "production_deploy_active")

    def test_run_started_at_rerun_blocks(self):
        old = "2026-10-20T10:00:00Z"
        new_start = "2026-10-27T12:59:00Z"
        d = coord.research_deploy_decision(
            [_run(id=1, status="in_progress", created_at=old, run_started_at=new_start)],
            since=self.since,
        )
        self.assertFalse(d["allowed"])

    def test_skew_boundary_blocks_at_120(self):
        t = (self.since - timedelta(seconds=120)).strftime("%Y-%m-%dT%H:%M:%SZ")
        d = coord.research_deploy_decision([_run(created_at=t, run_started_at=t)], since=self.since)
        self.assertFalse(d["allowed"])
        self.assertEqual(d["reason"], "production_deploy_since_research_start")

    def test_skew_boundary_allows_at_121(self):
        t = (self.since - timedelta(seconds=121)).strftime("%Y-%m-%dT%H:%M:%SZ")
        d = coord.research_deploy_decision([_run(created_at=t, run_started_at=t)], since=self.since)
        self.assertTrue(d["allowed"])

    def test_unreadable_time(self):
        d = coord.research_deploy_decision([_run(created_at="bad")], since=self.since)
        self.assertFalse(d["allowed"])
        self.assertEqual(d["reason"], "production_run_time_unreadable")

    def test_completed_run_without_timestamps_blocks(self):
        d = coord.research_deploy_decision(
            [_run(status="completed", created_at=None, run_started_at=None)],
            since=self.since,
        )
        self.assertFalse(d["allowed"])
        self.assertEqual(d["reason"], "production_run_time_unreadable")
        self.assertEqual(d["blocking"][0]["why"], "production_run_time_unreadable")

    def test_active_wins_reason(self):
        runs = [
            _run(id=1, status="queued"),
            _run(id=2, created_at=self.since.strftime("%Y-%m-%dT%H:%M:%SZ")),
        ]
        d = coord.research_deploy_decision(runs, since=self.since)
        self.assertEqual(d["reason"], "production_deploy_active")
        self.assertEqual(len(d["blocking"]), 2)

    def test_non_list_raises(self):
        with self.assertRaises(coord.CoordinatorError):
            coord.research_deploy_decision("x", since=self.since)


def _snap(run_id: int, job_status: str, step: dict | None, **run_fields: object) -> dict:
    job = {
        "name": coord.RESEARCH_DEPLOY_JOB,
        "status": job_status,
        "id": run_id * 10,
        "html_url": f"https://example/job/{run_id}",
        "run_attempt": 1,
        "steps": [step] if step else [],
    }
    run = {"id": run_id, "html_url": f"https://example/run/{run_id}", **run_fields}
    return {"run": run, "jobs": [job]}


class InflightResearchDeploysTests(unittest.TestCase):
    def test_queued_job(self):
        inflight = coord.inflight_research_deploys([_snap(1, "queued", None)])
        self.assertEqual(len(inflight), 1)

    def test_in_progress_step_queued(self):
        step = {"name": coord.RESEARCH_DEPLOY_STEP, "status": "queued"}
        self.assertEqual(len(coord.inflight_research_deploys([_snap(1, "in_progress", step)])), 1)

    def test_completed_step_not_inflight(self):
        step = {"name": coord.RESEARCH_DEPLOY_STEP, "status": "completed", "conclusion": "success"}
        self.assertEqual(coord.inflight_research_deploys([_snap(1, "in_progress", step)]), [])

    def test_missing_steps(self):
        snap = {"run": {"id": 1}, "jobs": [{"name": coord.RESEARCH_DEPLOY_JOB, "status": "in_progress"}]}
        self.assertEqual(len(coord.inflight_research_deploys([snap])), 1)

    def test_other_job_ignored(self):
        snap = {"run": {"id": 1}, "jobs": [{"name": "Build research edition", "status": "in_progress"}]}
        self.assertEqual(coord.inflight_research_deploys([snap]), [])

    def test_completed_job_ignored(self):
        step = {"name": coord.RESEARCH_DEPLOY_STEP, "status": "in_progress"}
        self.assertEqual(coord.inflight_research_deploys([_snap(1, "completed", step)]), [])


class ResearchDeployFloorTests(unittest.TestCase):
    def test_success_ny_date(self):
        step = {
            "name": coord.RESEARCH_DEPLOY_STEP,
            "status": "completed",
            "conclusion": "success",
            "completed_at": "2026-10-28T03:30:00Z",
        }
        self.assertEqual(coord.research_deploy_floor([_snap(1, "completed", step)]), "2026-10-27")

    def test_failure_ignored(self):
        step = {
            "name": coord.RESEARCH_DEPLOY_STEP,
            "status": "completed",
            "conclusion": "failure",
            "completed_at": "2026-10-28T03:30:00Z",
        }
        self.assertIsNone(coord.research_deploy_floor([_snap(1, "completed", step)]))

    def test_fallback_updated_at(self):
        step = {
            "name": coord.RESEARCH_DEPLOY_STEP,
            "status": "completed",
            "conclusion": "success",
            "completed_at": "not-iso",
        }
        snap = _snap(1, "completed", step, updated_at="2026-10-28T04:00:00Z")
        self.assertEqual(coord.research_deploy_floor([snap]), "2026-10-28")

    def test_unreadable_raises(self):
        step = {
            "name": coord.RESEARCH_DEPLOY_STEP,
            "status": "completed",
            "conclusion": "success",
            "completed_at": "bad",
        }
        snap = _snap(1, "completed", step, updated_at="bad")
        with self.assertRaises(coord.CoordinatorError) as ctx:
            coord.research_deploy_floor([snap])
        self.assertEqual(ctx.exception.reason, "research_deploy_time_unreadable")


class FinalOrderDecisionTests(unittest.TestCase):
    def test_allowed(self):
        d = coord.final_order_decision({"session_date": "2026-10-27"}, floor_date="2026-10-27")
        self.assertTrue(d["allowed"])

    def test_missing_session(self):
        d = coord.final_order_decision({}, floor_date=None)
        self.assertEqual(d["reason"], "release_session_missing")

    def test_floor_refuse(self):
        d = coord.final_order_decision({"session_date": "2026-10-26"}, floor_date="2026-10-27")
        self.assertFalse(d["allowed"])
        self.assertEqual(d["reason"], "research_edition_deployed_for_newer_session")


class GhApiTests(unittest.TestCase):
    def test_retries_then_success(self):
        calls = []

        def runner(cmd, **kwargs):
            calls.append(cmd)
            if len(calls) < 3:
                return subprocess.CompletedProcess(cmd, 1, "", "err")
            return subprocess.CompletedProcess(cmd, 0, '{"ok": true}', "")

        sleeps: list[float] = []

        out = coord.gh_api("repos/x", runner=runner, sleep=sleeps.append)
        self.assertEqual(out, {"ok": True})
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [2, 4])

    def test_always_fails(self):
        def runner(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, "", "fail")

        with self.assertRaises(coord.CoordinatorError) as ctx:
            coord.gh_api("repos/x", runner=runner, sleep=lambda _: None, attempts=2)
        self.assertEqual(ctx.exception.reason, "github_api_unavailable")

    def test_no_token_in_argv(self):
        token = "ghp_super_secret_token_value"
        with mock.patch.dict(os.environ, {"GH_TOKEN": token}):

            def runner(cmd, **kwargs):
                self.assertNotIn(token, cmd)
                self.assertEqual(cmd[:3], ["gh", "api", "-H"])
                return subprocess.CompletedProcess(cmd, 0, "{}", "")

            coord.gh_api("repos/x", runner=runner)


class WaitForQuiescenceTests(unittest.TestCase):
    def test_quiet_after_three_polls(self):
        snaps = [
            [_snap(1, "in_progress", {"name": coord.RESEARCH_DEPLOY_STEP, "status": "in_progress"})],
            [_snap(1, "in_progress", {"name": coord.RESEARCH_DEPLOY_STEP, "status": "in_progress"})],
            [_snap(1, "completed", {"name": coord.RESEARCH_DEPLOY_STEP, "status": "completed", "conclusion": "success"})],
        ]
        idx = 0
        sleeps: list[float] = []

        def fetch():
            nonlocal idx
            s = snaps[min(idx, len(snaps) - 1)]
            idx += 1
            return s

        t = 0.0

        def clock():
            return t

        def sleep(sec):
            nonlocal t
            sleeps.append(sec)
            t += sec

        out = coord.wait_for_research_quiescence(
            fetch, clock=clock, sleep=sleep, interval=5, timeout=100, log=lambda _: None
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(sleeps, [5, 5])

    def test_timeout(self):
        def fetch():
            return [_snap(1, "queued", None)]

        tick = 0.0

        def clock():
            return tick

        def sleep(_sec):
            nonlocal tick
            tick = 11.0

        with self.assertRaises(coord.CoordinatorError) as ctx:
            coord.wait_for_research_quiescence(
                fetch,
                clock=clock,
                sleep=sleep,
                timeout=10,
                interval=1,
                log=lambda _: None,
            )
        self.assertEqual(ctx.exception.reason, "research_deploy_still_in_flight")

    def test_fetch_error_propagates(self):
        def fetch():
            raise coord.CoordinatorError("runs_unreadable")

        with self.assertRaises(coord.CoordinatorError):
            coord.wait_for_research_quiescence(fetch, sleep=lambda _: None, timeout=10)


class CliTests(unittest.TestCase):
    def test_research_check_writes_output(self):
        runs = {"workflow_runs": []}
        with tempfile.TemporaryDirectory() as tmp:
            runs_path = os.path.join(tmp, "runs.json")
            out_path = os.path.join(tmp, "out")
            with open(runs_path, "w", encoding="utf-8") as handle:
                json.dump(runs, handle)
            with open(out_path, "w", encoding="utf-8") as handle:
                handle.write("")
            with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": out_path}):
                code = coord.main(
                    [
                        "research-check",
                        "--since",
                        "2026-10-27T13:00:00Z",
                        "--runs-json",
                        runs_path,
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn("deploy=true", open(out_path, encoding="utf-8").read())

        with tempfile.TemporaryDirectory() as tmp:
            runs_path = os.path.join(tmp, "runs.json")
            out_path = os.path.join(tmp, "out")
            with open(runs_path, "w", encoding="utf-8") as handle:
                json.dump({"workflow_runs": [_run(status="queued")]}, handle)
            with open(out_path, "w", encoding="utf-8") as handle:
                handle.write("")
            with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": out_path}):
                code = coord.main(
                    [
                        "research-check",
                        "--since",
                        "2026-10-27T13:00:00Z",
                        "--runs-json",
                        runs_path,
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn("deploy=false", open(out_path, encoding="utf-8").read())

    def test_bad_since(self):
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            code = coord.main(["research-check", "--since", "nope", "--runs-json", "/dev/null"])
        self.assertEqual(code, 1)

    @mock.patch("scripts.market_watch_launch.publication_coordinator.wait_for_research_quiescence")
    def test_final_wait_allowed(self, wait_mock):
        release = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump({"session_date": "2026-10-27"}, release)
        release.close()
        wait_mock.return_value = []
        code = coord.main(["final-wait", "--repo", "o/r", "--release", release.name, "--timeout", "1"])
        self.assertEqual(code, 0)
        os.unlink(release.name)

    @mock.patch("scripts.market_watch_launch.publication_coordinator.wait_for_research_quiescence")
    def test_final_wait_refused(self, wait_mock):
        release = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump({"session_date": "2026-10-26"}, release)
        release.close()
        step = {
            "name": coord.RESEARCH_DEPLOY_STEP,
            "status": "completed",
            "conclusion": "success",
            "completed_at": "2026-10-28T12:00:00Z",
        }
        wait_mock.return_value = [_snap(1, "completed", step)]
        code = coord.main(["final-wait", "--repo", "o/r", "--release", release.name, "--timeout", "1"])
        self.assertEqual(code, 1)
        os.unlink(release.name)

    @mock.patch("scripts.market_watch_launch.publication_coordinator.wait_for_research_quiescence")
    def test_final_wait_timeout(self, wait_mock):
        release = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump({"session_date": "2026-10-27"}, release)
        release.close()
        wait_mock.side_effect = coord.CoordinatorError("research_deploy_still_in_flight", "[]")
        code = coord.main(["final-wait", "--repo", "o/r", "--release", release.name])
        self.assertEqual(code, 1)
        os.unlink(release.name)


class QueueScenarioTests(unittest.TestCase):
    def test_overlapping_arrivals_r_blocked_when_visible(self):
        since = datetime(2026, 10, 27, 13, 0, tzinfo=timezone.utc)
        f_created = (since - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        runs = [_run(id=100, status="in_progress", created_at=f_created, run_started_at=f_created)]
        d = coord.research_deploy_decision(runs, since=since)
        self.assertFalse(d["allowed"])

    def test_research_running_while_final_queued(self):
        since = datetime(2026, 10, 27, 13, 0, tzinfo=timezone.utc)
        runs = [_run(id=1, status="queued")]
        self.assertFalse(coord.research_deploy_decision(runs, since=since)["allowed"])

    def test_final_waits_on_in_progress_research(self):
        step = {"name": coord.RESEARCH_DEPLOY_STEP, "status": "in_progress"}
        self.assertTrue(coord.inflight_research_deploys([_snap(1, "in_progress", step)]))

    def test_older_rerun_blocks(self):
        since = datetime(2026, 10, 27, 13, 0, tzinfo=timezone.utc)
        runs = [
            _run(
                id=1,
                status="in_progress",
                created_at="2026-10-01T00:00:00Z",
                run_started_at="2026-10-27T12:59:30Z",
            )
        ]
        self.assertFalse(coord.research_deploy_decision(runs, since=since)["allowed"])

    def test_floor_refuses_stale_refresh(self):
        d = coord.final_order_decision({"session_date": "2026-10-26"}, floor_date="2026-10-27")
        self.assertFalse(d["allowed"])
        d2 = coord.final_order_decision({"session_date": "2026-10-27"}, floor_date="2026-10-27")
        self.assertTrue(d2["allowed"])

    def test_r_allowed_after_old_final_completed_before_since(self):
        since = datetime(2026, 10, 27, 13, 0, tzinfo=timezone.utc)
        old = "2026-10-20T10:00:00Z"
        d = coord.research_deploy_decision([_run(created_at=old, run_started_at=old)], since=since)
        self.assertTrue(d["allowed"])


BASE = datetime(2026, 10, 27, 13, 0, tzinfo=timezone.utc)
SESSION_FINAL = "2026-10-27"
SESSION_REFRESH = "2026-10-26"
D_F = 45
R_CLAIM = 40
R_GUARD = 10
R_CHECKOUT = 5
R_DEPLOY_START = 41
R_JOB_DONE = 30  # after deploy step


def _iso_at(offset_sec: int) -> str:
    return (BASE + timedelta(seconds=offset_sec)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _since_dt() -> datetime:
    return BASE


def _production_view(t_f: int, view: int, f_run_end: int) -> list[dict]:
    if t_f > view:
        return []
    status = "in_progress" if view < f_run_end else "completed"
    return [
        _run(
            id=900,
            status=status,
            created_at=_iso_at(t_f),
            run_started_at=_iso_at(t_f),
        )
    ]


def _research_snapshot(view: int, r_outcome: str, d_r: int) -> list[dict]:
    if view < 0:
        return []
    deploy_end = R_DEPLOY_START + d_r
    job_done = deploy_end + R_JOB_DONE
    if r_outcome == "skip_guard":
        if view < R_GUARD:
            job_status = "in_progress"
            step = None
        else:
            job_status = "completed"
            step = {"name": coord.RESEARCH_DEPLOY_STEP, "status": "completed", "conclusion": "skipped"}
    elif r_outcome == "skip_claim":
        if view < R_CLAIM:
            job_status = "in_progress"
            step = None
        else:
            job_status = "completed"
            step = {"name": coord.RESEARCH_DEPLOY_STEP, "status": "completed", "conclusion": "skipped"}
    elif r_outcome == "deploy":
        if view < R_DEPLOY_START:
            job_status = "in_progress"
            step = None
        elif view < deploy_end:
            job_status = "in_progress"
            step = {"name": coord.RESEARCH_DEPLOY_STEP, "status": "in_progress"}
        elif view < job_done:
            job_status = "in_progress"
            step = {
                "name": coord.RESEARCH_DEPLOY_STEP,
                "status": "completed",
                "conclusion": "success",
                "completed_at": _iso_at(deploy_end),
            }
        else:
            job_status = "completed"
            step = {
                "name": coord.RESEARCH_DEPLOY_STEP,
                "status": "completed",
                "conclusion": "success",
                "completed_at": _iso_at(deploy_end),
            }
    else:
        return []
    return [_snap(1, job_status, step, updated_at=_iso_at(view))]


def _simulate(
    *,
    f_kind: str,
    t_f: int,
    lag: int,
    d_r: int,
    b: int,
    cdn_lag: int,
    wait_for_research: bool = True,
) -> dict:
    f_session = SESSION_FINAL if f_kind == "final" else SESSION_REFRESH
    f_run_end = t_f + b + D_F
    r_skip_guard = f_kind == "final" and (t_f - 1) <= R_CHECKOUT
    view_claim = R_CLAIM - lag
    claim_prod = _production_view(t_f, view_claim, f_run_end)
    claim_decision = coord.research_deploy_decision(claim_prod, since=_since_dt())
    if r_skip_guard:
        r_outcome = "skip_guard"
    elif not claim_decision["allowed"]:
        r_outcome = "skip_claim"
    else:
        r_outcome = "deploy"
    r_deploy_end = R_DEPLOY_START + d_r if r_outcome == "deploy" else None
    r_receipt_at = (R_DEPLOY_START + d_r + 60) if r_outcome == "deploy" else None
    r_public_at = (R_DEPLOY_START + d_r + cdn_lag) if r_outcome == "deploy" else None

    f_ready = t_f + b
    poll = f_ready
    f_waited = False
    timed_out = False
    while poll - f_ready <= coord.FINAL_WAIT_TIMEOUT_SECONDS:
        view = poll - lag
        snap = _research_snapshot(view, r_outcome, d_r)
        inflight = coord.inflight_research_deploys(snap) if wait_for_research else []
        if not inflight:
            break
        f_waited = True
        poll += coord.FINAL_WAIT_INTERVAL_SECONDS
    else:
        timed_out = True
    t_dec = poll
    snap_dec = _research_snapshot(t_dec - lag, r_outcome, d_r)
    floor = coord.research_deploy_floor(snap_dec)
    order = coord.final_order_decision({"session_date": f_session}, floor_date=floor)
    guard_refuse = False
    if not order["allowed"]:
        guard_refuse = True
    elif f_kind == "refresh_older" and r_receipt_at is not None and t_dec >= r_receipt_at:
        guard_refuse = True
    f_deployed = not timed_out and not guard_refuse
    f_deploy_start = t_dec if f_deployed else None
    f_deploy_end = t_dec + D_F if f_deployed else None

    completions: list[tuple[str, int]] = []
    if r_outcome == "deploy":
        completions.append(("research", R_DEPLOY_START + d_r))
    if f_deployed:
        completions.append(("final", f_deploy_end))
    served = max(completions, key=lambda item: item[1])[0] if completions else None

    return {
        "r_outcome": r_outcome,
        "r_deploy_end": r_deploy_end,
        "f_deployed": f_deployed,
        "f_deploy_start": f_deploy_start,
        "f_deploy_end": f_deploy_end,
        "f_waited": f_waited,
        "f_refused": guard_refuse or timed_out,
        "f_refused_floor_or_guard": guard_refuse,
        "timed_out": timed_out,
        "served": served,
        "t_dec": t_dec,
        "f_ready": f_ready,
        "r_public_at": r_public_at,
    }


class FetcherTests(unittest.TestCase):
    def test_deploy_pages_unions_status_queries_and_dedupes(self):
        old_completed = _run(
            id=77,
            status="completed",
            created_at="2026-10-01T00:00:00Z",
            run_started_at="2026-10-01T00:00:00Z",
        )
        active = _run(
            id=77,
            status="in_progress",
            created_at="2026-10-01T00:00:00Z",
            run_started_at="2026-10-27T12:00:00Z",
        )
        paths: list[str] = []

        def api(path: str):
            paths.append(path)
            if "status=in_progress" in path:
                return {"workflow_runs": [active]}
            if "status=" in path:
                return {"workflow_runs": []}
            return {"workflow_runs": [old_completed]}

        runs = coord.fetch_deploy_pages_runs("o/r", api=api)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "in_progress")
        self.assertEqual(len(paths), 1 + len(coord.ACTIVE_STATUSES))

    def test_deploy_pages_unreadable_payload(self):
        def api(_path: str):
            return {"workflow_runs": "nope"}

        with self.assertRaises(coord.CoordinatorError) as ctx:
            coord.fetch_deploy_pages_runs("o/r", api=api)
        self.assertEqual(ctx.exception.reason, "runs_unreadable")

    def test_research_snapshot_lists_all_status_paths_and_skips_old_jobs(self):
        now = datetime(2026, 10, 27, 13, 0, tzinfo=timezone.utc)
        old = {
            "id": 1,
            "status": "completed",
            "created_at": "2026-10-01T00:00:00Z",
            "updated_at": "2026-10-01T01:00:00Z",
        }
        fresh = {
            "id": 2,
            "status": "completed",
            "created_at": "2026-10-26T12:00:00Z",
            "updated_at": "2026-10-26T13:00:00Z",
        }
        active = {"id": 3, "status": "in_progress", "created_at": "2026-10-27T12:00:00Z"}
        paths: list[str] = []

        def api(path: str):
            paths.append(path)
            if "/jobs?" in path:
                return {"jobs": [{"name": coord.RESEARCH_DEPLOY_JOB, "status": "queued", "steps": []}]}
            if "status=in_progress" in path:
                return {"workflow_runs": [active]}
            if "status=" in path:
                return {"workflow_runs": []}
            return {"workflow_runs": [old, fresh]}

        snap = coord.fetch_research_snapshot("o/r", now=now, api=api)
        self.assertEqual(len(snap), 2)
        job_paths = [p for p in paths if "/jobs?" in p]
        self.assertEqual(len(job_paths), 2)
        self.assertTrue(any("runs/2/" in p for p in job_paths))
        self.assertTrue(any("runs/3/" in p for p in job_paths))
        list_paths = [p for p in paths if "/workflows/" in p and "/jobs?" not in p]
        self.assertEqual(len(list_paths), 1 + len(coord.ACTIVE_STATUSES))

    def test_research_jobs_unreadable_raises(self):
        now = datetime(2026, 10, 27, 13, 0, tzinfo=timezone.utc)

        def api(path: str):
            if "/jobs?" in path:
                return {"jobs": None}
            return {"workflow_runs": [{"id": 9, "status": "in_progress", "created_at": "2026-10-27T12:00:00Z"}]}

        with self.assertRaises(coord.CoordinatorError) as ctx:
            coord.fetch_research_snapshot("o/r", now=now, api=api)
        self.assertEqual(ctx.exception.reason, "jobs_unreadable")


class InterleavingModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.counters = {
            "r_deploy": 0,
            "r_skip_guard": 0,
            "r_skip_claim": 0,
            "f_waited": 0,
            "f_refused_refresh": 0,
        }
        cls.model_runtime = 0.0
        import time as time_mod

        start = time_mod.perf_counter()
        for f_kind in ("final", "refresh_older"):
            for t_f in range(-900, 901, 10):
                for lag in (0, 5, 30, 90):
                    for d_r in (20, 60, 240):
                        for b in (180, 300):
                            for cdn_lag in (0, 600):
                                outcome = _simulate(
                                    f_kind=f_kind,
                                    t_f=t_f,
                                    lag=lag,
                                    d_r=d_r,
                                    b=b,
                                    cdn_lag=cdn_lag,
                                )
                                cls._assert_invariants(f_kind, outcome, t_f, lag, d_r, b, cdn_lag)
                                if outcome["r_outcome"] == "deploy":
                                    cls.counters["r_deploy"] += 1
                                if outcome["r_outcome"] == "skip_guard":
                                    cls.counters["r_skip_guard"] += 1
                                if outcome["r_outcome"] == "skip_claim":
                                    cls.counters["r_skip_claim"] += 1
                                if outcome["f_waited"]:
                                    cls.counters["f_waited"] += 1
                                if f_kind == "refresh_older" and outcome["f_refused_floor_or_guard"]:
                                    cls.counters["f_refused_refresh"] += 1
        cls.model_runtime = time_mod.perf_counter() - start

    @staticmethod
    def _assert_invariants(f_kind, outcome, t_f, lag, d_r, b, cdn_lag):
        bound = b + d_r + 2 * coord.FINAL_WAIT_INTERVAL_SECONDS + 60
        if not outcome["timed_out"]:
            assert outcome["t_dec"] - outcome["f_ready"] <= bound, (f_kind, t_f, lag, d_r, b, cdn_lag)
        if f_kind == "final" and outcome["f_deployed"]:
            assert outcome["served"] == "final", (f_kind, t_f, lag, d_r, b)
            if outcome["r_deploy_end"] is not None:
                assert outcome["r_deploy_end"] <= outcome["f_deploy_start"], (f_kind, t_f, lag, d_r, b)
        if f_kind == "refresh_older" and outcome["r_outcome"] == "deploy":
            assert outcome["served"] == "research", (f_kind, t_f, lag, d_r, b, outcome)
        view_claim = R_CLAIM - lag
        f_run_end = t_f + b + D_F
        if t_f <= view_claim < f_run_end:
            assert outcome["r_outcome"] != "skip_claim" or not coord.research_deploy_decision(
                _production_view(t_f, view_claim, f_run_end), since=_since_dt()
            )["allowed"]

    def test_grid_counters_nontrivial(self):
        self.assertGreater(self.counters["r_deploy"], 0)
        self.assertGreater(self.counters["r_skip_guard"], 0)
        self.assertGreater(self.counters["r_skip_claim"], 0)
        self.assertGreater(self.counters["f_waited"], 0)
        self.assertGreater(self.counters["f_refused_refresh"], 0)
        self.assertLess(self.model_runtime, 15.0, f"model took {self.model_runtime:.2f}s")

    def test_negative_control_without_wait_finds_violation(self):
        violations = 0
        for t_f in range(-900, 901, 10):
            for lag in (0, 5, 30, 90):
                for d_r in (20, 60, 240):
                    for b in (180, 300):
                        for cdn_lag in (0, 600):
                            good = _simulate(
                                f_kind="final",
                                t_f=t_f,
                                lag=lag,
                                d_r=d_r,
                                b=b,
                                cdn_lag=cdn_lag,
                                wait_for_research=True,
                            )
                            bad = _simulate(
                                f_kind="final",
                                t_f=t_f,
                                lag=lag,
                                d_r=d_r,
                                b=b,
                                cdn_lag=cdn_lag,
                                wait_for_research=False,
                            )
                            if good["f_deployed"] and good["r_deploy_end"] is not None:
                                if bad["f_deployed"] and bad["r_deploy_end"] > bad["f_deploy_start"]:
                                    violations += 1
        self.assertGreater(violations, 0)


if __name__ == "__main__":
    unittest.main()
