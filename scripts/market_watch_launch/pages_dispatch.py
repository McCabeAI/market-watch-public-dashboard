"""Confirm a deploy-pages workflow_dispatch run exists.

``gh workflow run`` returns 0 when GitHub accepts the request (HTTP 204). That
response has no run id and is not a deployment. Callers must observe an Actions
run on the expected main SHA before stage 08 may say the dispatch was confirmed,
and must still leave publication false until a successful deploy is reconciled.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from scripts.market_watch_launch.pages import (
    PAGES_RUN_NOT_OBSERVED,
    launch_awaiting_pages_publication,
    load_launch_record,
)
from scripts.pm.constants import AUTOMATED_PM_IDS

TRADER_SEAT_COUNT = 14
LAUNCH_ID_IN_TITLE = re.compile(r"mwl-\d{8}T\d{6}Z-[0-9a-f]{8}")
DISPATCH_NOT_CONFIRMED = "pages_dispatch_not_confirmed"
DISPATCH_AMBIGUOUS = "pages_dispatch_ambiguous"
_RUN_LIST_JSON = (
    "databaseId,headSha,status,conclusion,event,url,displayTitle,headBranch,name"
)


def dispatch_command(
    *,
    workflow: str,
    ref: str,
    launch_id: str,
    review_id: str,
    packet_sha256: str,
) -> list[str]:
    return [
        "gh",
        "workflow",
        "run",
        workflow,
        "--ref",
        ref,
        "-f",
        f"launch_id={launch_id}",
        "-f",
        f"review_id={review_id}",
        "-f",
        f"packet_sha256={packet_sha256}",
    ]


def _run_id(row: dict[str, Any]) -> str:
    return str(row.get("databaseId") or row.get("id") or "")


def _title_launch_id(row: dict[str, Any]) -> str | None:
    title = " ".join(
        str(row.get(key) or "")
        for key in ("displayTitle", "name", "workflowName")
    )
    match = LAUNCH_ID_IN_TITLE.search(title)
    return match.group(0) if match else None


def match_new_run(
    before_ids: set[str],
    runs: list[dict[str, Any]],
    *,
    expected_sha: str,
    launch_id: str,
) -> dict[str, Any] | None:
    """Return the single new main workflow_dispatch run for this launch.

    None means no matching run yet. A dict with ``ambiguous`` True means more
    than one new run could be this dispatch and the caller must fail closed.
    """
    expected = expected_sha.lower()
    matches: list[dict[str, Any]] = []
    for row in runs:
        if not isinstance(row, dict):
            continue
        run_id = _run_id(row)
        if not run_id.isdigit() or run_id in before_ids:
            continue
        if str(row.get("event") or "") != "workflow_dispatch":
            continue
        if str(row.get("headBranch") or "") != "main":
            continue
        head_sha = str(row.get("headSha") or "").lower()
        if head_sha != expected:
            continue
        titled = _title_launch_id(row)
        if titled is not None and titled != launch_id:
            continue
        matches.append(row)
    if not matches:
        return None
    if len(matches) > 1:
        return {"ambiguous": True}
    return matches[0]


def confirm_pages_dispatch(
    *,
    plan: dict[str, Any],
    launch: dict[str, Any],
    expected_sha: str,
    list_runs: Callable[[], list[dict[str, Any]]],
    request_dispatch: Callable[[], int],
    sleep: Callable[[float], None] | None = None,
    attempts: int = 8,
    interval_seconds: float = 3.0,
) -> dict[str, Any]:
    """Request dispatch, then require one new run pinned to ``expected_sha``."""
    workflow = str(plan.get("workflow") or "deploy-pages.yml")
    ref = str(plan.get("ref") or "main")
    launch_id = str(launch.get("launch_id") or plan.get("launch_id") or "")
    if workflow != "deploy-pages.yml" or ref != "main" or not launch_id:
        return {"dispatched": False, "dispatch_confirmed": False, "reason": DISPATCH_NOT_CONFIRMED}
    if len(expected_sha) != 40:
        return {"dispatched": False, "dispatch_confirmed": False, "reason": DISPATCH_NOT_CONFIRMED}
    try:
        before = {_run_id(row) for row in list_runs() if isinstance(row, dict)}
    except (OSError, ValueError, json.JSONDecodeError):
        # Without a snapshot, an older run on this SHA could be mistaken for the
        # request that was just accepted. Do not dispatch.
        return {"dispatched": False, "dispatch_confirmed": False, "reason": DISPATCH_NOT_CONFIRMED}
    before.discard("")
    if request_dispatch() != 0:
        return {"dispatched": False, "dispatch_confirmed": False, "reason": DISPATCH_NOT_CONFIRMED}
    pause = sleep or time.sleep
    tries = max(1, attempts)
    for attempt in range(tries):
        try:
            rows = list_runs()
        except (OSError, ValueError, json.JSONDecodeError):
            rows = []
        matched = match_new_run(before, rows, expected_sha=expected_sha, launch_id=launch_id)
        if matched and matched.get("ambiguous"):
            return {"dispatched": False, "dispatch_confirmed": False, "reason": DISPATCH_AMBIGUOUS}
        if matched:
            run_id = _run_id(matched)
            run_url = str(matched.get("url") or matched.get("html_url") or "")
            return {
                "dispatched": True,
                "dispatch_confirmed": True,
                "reason": "pages_dispatch_observed",
                "workflow": workflow,
                "event": "workflow_dispatch",
                "ref": "main",
                "run_id": run_id,
                "run_url": run_url,
                "head_sha": str(matched.get("headSha") or expected_sha).lower(),
                "launch_id": launch_id,
                "status": matched.get("status"),
                "conclusion": matched.get("conclusion"),
            }
        if attempt + 1 < tries:
            pause(interval_seconds)
    return {"dispatched": False, "dispatch_confirmed": False, "reason": PAGES_RUN_NOT_OBSERVED}


def _git_head(repo_root: Path) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip().lower() if proc.returncode == 0 else ""


def _gh_json(args: list[str], *, cwd: Path) -> Any:
    proc = subprocess.run(args, cwd=cwd, check=False, capture_output=True, text=True)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise OSError(proc.stderr.strip() or "gh command failed")
    return json.loads(proc.stdout)


def confirm_pages_run(
    *,
    plan: dict[str, Any],
    launch: dict[str, Any],
    repo_root: Path,
) -> dict[str, Any]:
    """Production dispatcher used by continuation when MW_ENABLE_PAGES_DISPATCH=1."""
    workflow = str(plan.get("workflow") or "deploy-pages.yml")
    ref = str(plan.get("ref") or "main")
    launch_id = str(launch.get("launch_id") or "")
    review_id = str(plan.get("review_id") or launch.get("review_id") or "")
    packet = str(launch.get("base_packet_sha256") or "")
    expected_sha = _git_head(repo_root)
    command = dispatch_command(
        workflow=workflow,
        ref=ref,
        launch_id=launch_id,
        review_id=review_id,
        packet_sha256=packet,
    )

    def list_runs() -> list[dict[str, Any]]:
        payload = _gh_json(
            [
                "gh",
                "run",
                "list",
                "--workflow",
                workflow,
                "--event",
                "workflow_dispatch",
                "--branch",
                ref,
                "--limit",
                "20",
                "--json",
                _RUN_LIST_JSON,
            ],
            cwd=repo_root,
        )
        if not isinstance(payload, list):
            raise ValueError("gh run list did not return a list")
        return [row for row in payload if isinstance(row, dict)]

    def request_dispatch() -> int:
        proc = subprocess.run(command, cwd=repo_root, check=False, capture_output=True, text=True)
        return proc.returncode

    attempts = int(os.environ.get("MW_PAGES_DISPATCH_ATTEMPTS", "8") or "8")
    interval = float(os.environ.get("MW_PAGES_DISPATCH_INTERVAL_SECONDS", "3") or "3")
    return confirm_pages_dispatch(
        plan=plan,
        launch=launch,
        expected_sha=expected_sha,
        list_runs=list_runs,
        request_dispatch=request_dispatch,
        attempts=attempts,
        interval_seconds=interval,
    )


def assert_dispatch_binding(
    launch: dict[str, Any],
    *,
    launch_id: str,
    review_id: str,
    packet_sha256: str,
) -> None:
    """Fail closed unless this checkout is the authorized finalized launch."""
    if not launch_awaiting_pages_publication(launch):
        raise SystemExit("checkout is not a finalized launch awaiting Pages")
    if launch.get("launch_id") != launch_id:
        raise SystemExit("workflow_dispatch launch_id does not match checkout")
    if launch.get("review_id") != review_id:
        raise SystemExit("workflow_dispatch review_id does not match checkout")
    if launch.get("base_packet_sha256") != packet_sha256:
        raise SystemExit("workflow_dispatch packet SHA does not match checkout")


def bind_checkout(
    root: Path,
    *,
    launch_id: str,
    review_id: str,
    packet_sha256: str,
) -> str:
    latest_path = root / "data" / "overnight" / "latest.json"
    try:
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"deployed checkout has no overnight dataset: {exc}") from exc
    dataset_run_id = str((latest or {}).get("overnight_run_id") or "")
    if not dataset_run_id:
        raise SystemExit("deployed checkout has no overnight_run_id")
    if launch_id:
        launch = load_launch_record(launch_id=launch_id, state_root=root)
        if launch is None:
            raise SystemExit("workflow_dispatch launch_id is not on this checkout")
        assert_dispatch_binding(
            launch,
            launch_id=launch_id,
            review_id=review_id,
            packet_sha256=packet_sha256,
        )
        launch_run = str(launch.get("overnight_run_id") or "")
        if launch_run and launch_run != dataset_run_id:
            raise SystemExit("launch overnight_run_id does not match data/overnight/latest.json")
    return dataset_run_id


def assert_public_dataset(
    *,
    html: str,
    trader: dict[str, Any],
    pm: dict[str, Any],
    overnight_run_id: str,
) -> None:
    """The live page must serve this deploy's trader roster and the 3 PM books."""
    if "Trader Book" not in html:
        raise SystemExit("public page is missing Trader Book")
    seats = trader.get("seats")
    if not isinstance(seats, list) or len(seats) != TRADER_SEAT_COUNT:
        raise SystemExit("public trader-books.json does not list 14 trader seats")
    published = (
        ((trader.get("publication") or {}) if isinstance(trader.get("publication"), dict) else {}).get(
            "overnight_run_id"
        )
        or trader.get("books_run_id")
        or trader.get("overnight_run_id")
    )
    if published != overnight_run_id:
        raise SystemExit("public trader dataset does not match the deployed overnight run")
    rows = pm.get("pms")
    if not isinstance(rows, list):
        raise SystemExit("public pm-books.json has no PM roster")
    found = {row.get("pm_id") for row in rows if isinstance(row, dict)}
    missing = [pm_id for pm_id in AUTOMATED_PM_IDS if pm_id not in found]
    if missing:
        raise SystemExit("public pm-books.json is missing automated PM books")


def _join_page(page_url: str, name: str) -> str:
    if not page_url.startswith("https://"):
        raise SystemExit("deployment page_url is not https")
    return page_url.rstrip("/") + "/" + name


def fetch_public_text(
    url: str,
    *,
    attempts: int = 6,
    interval_seconds: float = 10.0,
    sleep: Callable[[float], None] | None = None,
    opener: Callable[[str], str] | None = None,
) -> str:
    pause = sleep or time.sleep
    fetch = opener or _urlopen_text
    tries = max(1, attempts)
    for attempt in range(tries):
        try:
            body = fetch(url)
        except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            body = ""
        if body:
            return body
        if attempt + 1 < tries:
            pause(interval_seconds)
    raise SystemExit(f"public page was not reachable: {url}")


def _urlopen_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "market-watch-pages-verify"})
    with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
        status = getattr(response, "status", 200)
        if status != 200:
            raise OSError(f"HTTP {status}")
        return response.read().decode("utf-8")


def verify_public_dataset(
    *,
    page_url: str,
    overnight_run_id: str,
    attempts: int = 6,
    interval_seconds: float = 10.0,
    sleep: Callable[[float], None] | None = None,
    opener: Callable[[str], str] | None = None,
) -> None:
    html = fetch_public_text(
        _join_page(page_url, ""),
        attempts=attempts,
        interval_seconds=interval_seconds,
        sleep=sleep,
        opener=opener,
    )
    trader_text = fetch_public_text(
        _join_page(page_url, "trader-books.json"),
        attempts=attempts,
        interval_seconds=interval_seconds,
        sleep=sleep,
        opener=opener,
    )
    pm_text = fetch_public_text(
        _join_page(page_url, "pm-books.json"),
        attempts=attempts,
        interval_seconds=interval_seconds,
        sleep=sleep,
        opener=opener,
    )
    try:
        trader = json.loads(trader_text)
        pm = json.loads(pm_text)
    except json.JSONDecodeError as exc:
        raise SystemExit("public dataset JSON is invalid") from exc
    if not isinstance(trader, dict) or not isinstance(pm, dict):
        raise SystemExit("public dataset JSON is invalid")
    assert_public_dataset(html=html, trader=trader, pm=pm, overnight_run_id=overnight_run_id)


def _write_github_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT", "").strip()
    line = f"{name}={value}\n"
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line)
    else:
        print(line, end="")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Confirm and verify Market Watch Pages dispatch.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("bind-checkout")
    sub.add_parser("verify-public")
    args = parser.parse_args(argv)
    try:
        if args.command == "bind-checkout":
            dataset = bind_checkout(
                Path.cwd(),
                launch_id=os.environ.get("MW_LAUNCH_ID", "").strip(),
                review_id=os.environ.get("MW_REVIEW_ID", "").strip(),
                packet_sha256=os.environ.get("MW_PACKET_SHA256", "").strip(),
            )
            _write_github_output("dataset_run_id", dataset)
            return 0
        page_url = os.environ.get("PAGE_URL", "").strip()
        dataset = os.environ.get("DATASET_RUN_ID", "").strip()
        if not page_url or not dataset:
            raise SystemExit("deployment page_url or dataset run id is missing")
        attempts = int(os.environ.get("MW_PUBLIC_VERIFY_ATTEMPTS", "6") or "6")
        interval = float(os.environ.get("MW_PUBLIC_VERIFY_INTERVAL_SECONDS", "10") or "10")
        verify_public_dataset(
            page_url=page_url,
            overnight_run_id=dataset,
            attempts=attempts,
            interval_seconds=interval,
        )
        print(json.dumps({"verified": True, "overnight_run_id": dataset}))
        return 0
    except SystemExit as exc:
        message = exc.code
        if isinstance(message, str) and message:
            print(message, file=__import__("sys").stderr)
            return 1
        if message in (None, 0):
            return 0
        if isinstance(message, int):
            return message
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
