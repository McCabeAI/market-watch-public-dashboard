"""Mutual exclusion between research and final GitHub Pages deploys via Actions API state.

Research deploy jobs stay outside the ``pages-production`` concurrency group so
they cannot replace a pending final deploy. Ordering uses API snapshots instead:
the research job claims before deploy (skip if production is active or recent);
the final deploy job waits for in-flight research deploy steps, then enforces a
research session-date floor before deploying.

Assumes: the API never reports a step completed before it truly is;
``actions/deploy-pages`` step completion means the Pages deployment reached a
terminal state; runner/API clock skew is below ``CLOCK_SKEW_SECONDS``; Pages
serves the most recently created successful deployment.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

DEPLOY_PAGES_WORKFLOW = "deploy-pages.yml"
RESEARCH_WORKFLOW = "publish-research-pages.yml"
RESEARCH_DEPLOY_JOB = "Deploy research edition"
RESEARCH_DEPLOY_STEP = "Deploy to GitHub Pages"
CLOCK_SKEW_SECONDS = 120
FINAL_WAIT_TIMEOUT_SECONDS = 1500
FINAL_WAIT_INTERVAL_SECONDS = 15
RESEARCH_LOOKBACK_HOURS = 48
ACTIVE_STATUSES = ("queued", "in_progress", "waiting", "requested", "pending")
NY = ZoneInfo("America/New_York")

_SESSION_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class CoordinatorError(RuntimeError):
    def __init__(self, reason: str, detail: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def parse_api_time(value: Any) -> datetime | None:
    if value is None or not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def production_runs(runs: Any) -> list[dict[str, Any]]:
    if not isinstance(runs, list):
        raise CoordinatorError("runs_unreadable")
    out: list[dict[str, Any]] = []
    for item in runs:
        if not isinstance(item, dict):
            continue
        if item.get("event") == "workflow_dispatch" and item.get("head_branch") == "main":
            out.append(item)
    return out


def _run_effective_time(run: dict[str, Any]) -> tuple[datetime | None, bool]:
    """Return (max(created, started), any_field_present_but_unreadable)."""
    created_raw = run.get("created_at")
    started_raw = run.get("run_started_at")
    created = parse_api_time(created_raw)
    started = parse_api_time(started_raw)
    unreadable = False
    if created_raw and created is None:
        unreadable = True
    if started_raw and started is None:
        unreadable = True
    times = [t for t in (created, started) if t is not None]
    if not times:
        return None, unreadable
    return max(times), unreadable


def research_deploy_decision(deploy_pages_runs: Any, *, since: datetime) -> dict[str, Any]:
    if since.tzinfo is None:
        raise CoordinatorError("invalid_since", "since must be timezone-aware")
    since_utc = since.astimezone(timezone.utc)
    skew_bound = since_utc - timedelta(seconds=CLOCK_SKEW_SECONDS)
    runs = production_runs(deploy_pages_runs)
    blocking: list[dict[str, Any]] = []
    reason = "allowed"

    for run in runs:
        status = run.get("status")
        base = {
            "id": run.get("id"),
            "status": status,
            "created_at": run.get("created_at"),
            "run_started_at": run.get("run_started_at"),
            "html_url": run.get("html_url"),
        }
        if status != "completed":
            blocking.append({**base, "why": "production_deploy_active"})
            if reason == "allowed":
                reason = "production_deploy_active"
            continue
        effective, unreadable = _run_effective_time(run)
        if unreadable or effective is None:
            blocking.append({**base, "why": "production_run_time_unreadable"})
            if reason == "allowed":
                reason = "production_run_time_unreadable"
            continue
        if effective is not None and effective >= skew_bound:
            blocking.append({**base, "why": "production_deploy_since_research_start"})
            if reason == "allowed":
                reason = "production_deploy_since_research_start"

    allowed = not blocking
    if allowed:
        reason = "allowed"
    elif any(entry["why"] == "production_deploy_active" for entry in blocking):
        reason = "production_deploy_active"
    elif any(entry["why"] == "production_run_time_unreadable" for entry in blocking):
        reason = "production_run_time_unreadable"
    else:
        reason = "production_deploy_since_research_start"
    return {
        "allowed": allowed,
        "reason": reason,
        "blocking": blocking,
        "since": since_utc.isoformat().replace("+00:00", "Z"),
    }


def _deploy_step(job: dict[str, Any]) -> dict[str, Any] | None:
    steps = job.get("steps")
    if not isinstance(steps, list):
        return None
    for step in steps:
        if isinstance(step, dict) and step.get("name") == RESEARCH_DEPLOY_STEP:
            return step
    return None


def inflight_research_deploys(snapshot: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocking: list[dict[str, Any]] = []
    for entry in snapshot:
        run = entry.get("run") or {}
        jobs = entry.get("jobs")
        if not isinstance(jobs, list):
            continue
        run_id = run.get("id")
        html_url = run.get("html_url")
        for job in jobs:
            if not isinstance(job, dict) or job.get("name") != RESEARCH_DEPLOY_JOB:
                continue
            job_status = job.get("status")
            if job_status == "completed":
                continue
            step = _deploy_step(job)
            step_status = step.get("status") if step else None
            if step is None or step_status != "completed":
                blocking.append(
                    {
                        "run_id": run_id,
                        "run_attempt": job.get("run_attempt"),
                        "job_id": job.get("id"),
                        "job_status": job_status,
                        "step_status": step_status,
                        "html_url": html_url,
                    }
                )
    return blocking


def research_deploy_floor(snapshot: list[dict[str, Any]]) -> str | None:
    best: str | None = None
    for entry in snapshot:
        run = entry.get("run") or {}
        jobs = entry.get("jobs")
        if not isinstance(jobs, list):
            continue
        for job in jobs:
            if not isinstance(job, dict) or job.get("name") != RESEARCH_DEPLOY_JOB:
                continue
            step = _deploy_step(job)
            if not step or step.get("conclusion") != "success":
                continue
            completed = parse_api_time(step.get("completed_at"))
            if completed is None:
                completed = parse_api_time(run.get("updated_at"))
                if completed is None:
                    raise CoordinatorError("research_deploy_time_unreadable")
            ny_date = completed.astimezone(NY).date().isoformat()
            if best is None or ny_date > best:
                best = ny_date
    return best


def final_order_decision(candidate_release: dict[str, Any], *, floor_date: str | None) -> dict[str, Any]:
    session_date = candidate_release.get("session_date")
    if not isinstance(session_date, str) or not _SESSION_DATE_RE.fullmatch(session_date):
        return {
            "allowed": False,
            "reason": "release_session_missing",
            "session_date": session_date,
            "research_floor": floor_date,
        }
    if floor_date and session_date < floor_date:
        return {
            "allowed": False,
            "reason": "research_edition_deployed_for_newer_session",
            "session_date": session_date,
            "research_floor": floor_date,
        }
    return {
        "allowed": True,
        "reason": "allowed",
        "session_date": session_date,
        "research_floor": floor_date,
    }


def gh_api(
    path: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    attempts: int = 4,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    cmd = ["gh", "api", "-H", "Accept: application/vnd.github+json", path]
    delays = (2, 4, 8)
    last_stderr = ""
    for attempt in range(attempts):
        proc = runner(cmd, capture_output=True, text=True, check=False)
        last_stderr = proc.stderr or ""
        if proc.returncode == 0:
            try:
                return json.loads(proc.stdout)
            except json.JSONDecodeError:
                pass
        if attempt < attempts - 1:
            sleep(delays[min(attempt, len(delays) - 1)])
    tail = last_stderr[-300:] if last_stderr else ""
    raise CoordinatorError("github_api_unavailable", f"{path} {tail}".strip())


def _workflow_runs_from_payload(payload: Any) -> list[dict[str, Any]]:
    runs = payload.get("workflow_runs") if isinstance(payload, dict) else None
    if not isinstance(runs, list):
        raise CoordinatorError("runs_unreadable")
    return [item for item in runs if isinstance(item, dict)]


def _prefer_run_copy(existing: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    if existing.get("status") != "completed" and new.get("status") == "completed":
        return existing
    if new.get("status") != "completed" and existing.get("status") == "completed":
        return new
    return new


def _dedupe_workflow_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[Any, dict[str, Any]] = {}
    for run in runs:
        run_id = run.get("id")
        if run_id is None:
            continue
        prior = merged.get(run_id)
        merged[run_id] = _prefer_run_copy(prior, run) if prior is not None else run
    return list(merged.values())


def _run_times_for_lookback(run: dict[str, Any]) -> list[datetime]:
    return [
        parsed
        for parsed in (
            parse_api_time(run.get("updated_at")),
            parse_api_time(run.get("created_at")),
            parse_api_time(run.get("run_started_at")),
        )
        if parsed is not None
    ]


def _research_run_needs_jobs(run: dict[str, Any], now: datetime) -> bool:
    if run.get("status") != "completed":
        return True
    times = _run_times_for_lookback(run)
    if not times:
        return False
    cutoff = now - timedelta(hours=RESEARCH_LOOKBACK_HOURS)
    return max(times) >= cutoff


def fetch_deploy_pages_runs(repo: str, *, api: Callable[[str], Any] = gh_api) -> list[Any]:
    base = (
        f"repos/{repo}/actions/workflows/{DEPLOY_PAGES_WORKFLOW}/runs"
        "?branch=main&event=workflow_dispatch&per_page=50"
    )
    collected: list[dict[str, Any]] = []
    for path in (base, *(f"{base}&status={status}" for status in ACTIVE_STATUSES)):
        collected.extend(_workflow_runs_from_payload(api(path)))
    return _dedupe_workflow_runs(collected)


def fetch_research_snapshot(
    repo: str,
    *,
    now: datetime,
    api: Callable[[str], Any] = gh_api,
) -> list[dict[str, Any]]:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    base = f"repos/{repo}/actions/workflows/{RESEARCH_WORKFLOW}/runs?per_page=30"
    collected: list[dict[str, Any]] = []
    for path in (base, *(f"{base}&status={status}" for status in ACTIVE_STATUSES)):
        collected.extend(_workflow_runs_from_payload(api(path)))
    runs = _dedupe_workflow_runs(collected)
    snapshot: list[dict[str, Any]] = []
    for run in runs:
        run_id = run.get("id")
        if run_id is None:
            continue
        if not _research_run_needs_jobs(run, now):
            continue
        jobs_payload = api(f"repos/{repo}/actions/runs/{run_id}/jobs?filter=latest&per_page=100")
        jobs = jobs_payload.get("jobs") if isinstance(jobs_payload, dict) else None
        if not isinstance(jobs, list):
            raise CoordinatorError("jobs_unreadable")
        snapshot.append({"run": run, "jobs": jobs})
    return snapshot


def wait_for_research_quiescence(
    fetch: Callable[[], list[dict[str, Any]]],
    *,
    timeout: int = FINAL_WAIT_TIMEOUT_SECONDS,
    interval: int = FINAL_WAIT_INTERVAL_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = lambda msg: print(msg, file=sys.stderr),
) -> list[dict[str, Any]]:
    start = clock()
    while True:
        snap = fetch()
        inflight = inflight_research_deploys(snap)
        if not inflight:
            return snap
        if clock() - start >= timeout:
            raise CoordinatorError(
                "research_deploy_still_in_flight",
                json.dumps(inflight, sort_keys=True),
            )
        log(f"waiting for {len(inflight)} in-flight research deploy(s)")
        sleep(interval)


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _write_github_output(key: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"{key}={value}\n")


def _parse_since(value: str) -> datetime:
    parsed = parse_api_time(value)
    if parsed is None:
        raise CoordinatorError("invalid_since", value)
    return parsed


def _cmd_research_check(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="research-check")
    parser.add_argument("--since", required=True)
    parser.add_argument("--repo")
    parser.add_argument("--runs-json")
    args = parser.parse_args(argv)
    try:
        since = _parse_since(args.since)
        if args.runs_json:
            loaded = json.loads(Path(args.runs_json).read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and "workflow_runs" in loaded:
                runs = loaded["workflow_runs"]
            else:
                runs = loaded
        elif args.repo:
            runs = fetch_deploy_pages_runs(args.repo)
        else:
            raise CoordinatorError("invalid_args", "need --repo or --runs-json")
        decision = research_deploy_decision(runs, since=since)
        print(_canonical_json(decision), end="")
        _write_github_output("deploy", "true" if decision["allowed"] else "false")
        return 0
    except CoordinatorError as exc:
        print(_canonical_json({"error": exc.reason, "detail": exc.detail}), end="")
        return 1


def _cmd_final_wait(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="final-wait")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--timeout", type=int, default=FINAL_WAIT_TIMEOUT_SECONDS)
    parser.add_argument("--interval", type=int, default=FINAL_WAIT_INTERVAL_SECONDS)
    args = parser.parse_args(argv)
    try:
        release = json.loads(Path(args.release).read_text(encoding="utf-8"))
        snap = wait_for_research_quiescence(
            lambda: fetch_research_snapshot(args.repo, now=datetime.now(timezone.utc)),
            timeout=args.timeout,
            interval=args.interval,
        )
        floor = research_deploy_floor(snap)
        decision = final_order_decision(release, floor_date=floor)
        payload = {**decision, "inflight": [], "research_floor": floor}
        print(_canonical_json(payload), end="")
        return 0 if decision["allowed"] else 1
    except CoordinatorError as exc:
        print(_canonical_json({"error": exc.reason, "detail": exc.detail}), end="")
        return 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: publication_coordinator research-check|final-wait ...", file=sys.stderr)
        return 2
    command = argv[0]
    rest = argv[1:]
    if command == "research-check":
        return _cmd_research_check(rest)
    if command == "final-wait":
        return _cmd_final_wait(rest)
    print(f"unknown command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
