"""Shared contract for the manual Market Watch launch DAG.

Launch identity is separate from the legacy overnight ``schedule_id``
``market-watch-weekday-0205``. That constant stays a backward-compatible
field on trusted scheduled-output validation. It is not an active clock.

Stage handlers return a receipt dict. The graph advances only when the
prior stage status is ``succeeded`` and the reread artifact hash matches
``output_sha256``. A process exit code is not a stage result.
"""

from __future__ import annotations

import re
from typing import Any

LAUNCHER_ID = "manual-market-watch-launch-v1"
LEGACY_SCHEDULE_ID = "market-watch-weekday-0205"
ISSUE_TITLE_PREFIX = "[launch-market-watch]"
ISSUE_TITLE_RE = re.compile(r"^\[launch-market-watch\] (\d{4}-\d{2}-\d{2})( rerun)?$")
LAUNCH_ID_RE = re.compile(r"^mwl-(\d{8})T(\d{6})Z-([0-9a-f]{8})$")

STAGES: tuple[str, ...] = (
    "00_authenticate",
    "01_ingest",
    "02_acquire",
    "03_quality_gate",
    "04_freeze",
    "05_acp_handoff",
    "06_acceptance",
    "07_finalize",
    "08_pages",
)

STAGE_STATUSES: tuple[str, ...] = ("pending", "running", "succeeded", "blocked", "failed")
TERMINAL_LAUNCH_STATUSES: tuple[str, ...] = ("succeeded", "blocked", "failed")
LIVE_LAUNCH_STATUSES: tuple[str, ...] = ("pending", "running")

COUNTRIES: tuple[str, ...] = ("US", "CA", "AU", "NZ", "EA", "JP")
MODES: tuple[str, ...] = ("fixture", "live")
PROVIDERS: tuple[str, ...] = ("stub", "acp")

# Scored-series statuses that are real release checks. A job that merely ran
# must not mark an older period as checked.
VERIFIED_OBSERVATION_STATUSES: frozenset[str] = frozenset(
    {
        "checked_unchanged",
        "new_observation",
        "revision_applied",
        "revision_pending",
    }
)
BLOCKING_SERIES_STATUSES: frozenset[str] = frozenset(
    {
        "due_missing",
        "source_failed",
        "incomplete_country",
    }
)
OPTIONAL_GAP_STATUSES: frozenset[str] = frozenset(
    {
        "license_gap",
        "not_applicable",
        "calendar_unparsed",
    }
)

AWAITING_ACP = "awaiting_acp_one_shot_authority"
BOT_ORIGIN_FORBIDDEN = "bot_origin_forbidden"
CONCURRENCY_BLOCK = "concurrency_one_live_launch"


def empty_stage(name: str) -> dict[str, Any]:
    if name not in STAGES:
        raise ValueError(f"unknown launch stage {name}")
    return {
        "stage": name,
        "status": "pending",
        "input_sha256": None,
        "output_sha256": None,
        "started_at": None,
        "finished_at": None,
        "reason": None,
        "source_run_url": None,
        "artifact": None,
        "details": {},
    }


def empty_launch(
    *,
    launch_id: str,
    session_date: str,
    created_at: str,
    request: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "type": "MARKET_WATCH_LAUNCH",
        "launcher_id": LAUNCHER_ID,
        "launch_id": launch_id,
        "session_date": session_date,
        "timezone": "America/New_York",
        "created_at": created_at,
        "status": "pending",
        "duplicate_of": None,
        "prior_launch_id": request.get("prior_launch_id"),
        "rerun": bool(request.get("rerun")),
        "overnight_run_id": None,
        "review_id": None,
        "base_packet_sha256": None,
        "starting_trader_books_sha256": None,
        "starting_pm_books_sha256": None,
        "freeze_commit_sha": None,
        "request": request,
        "stages": {name: empty_stage(name) for name in STAGES},
    }


def stage_receipt(
    stage: str,
    *,
    status: str,
    input_sha256: str | None,
    output_sha256: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    reason: str | None = None,
    source_run_url: str | None = None,
    artifact: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if stage not in STAGES:
        raise ValueError(f"unknown launch stage {stage}")
    if status not in STAGE_STATUSES:
        raise ValueError(f"invalid stage status {status}")
    return {
        "stage": stage,
        "status": status,
        "input_sha256": input_sha256,
        "output_sha256": output_sha256,
        "started_at": started_at,
        "finished_at": finished_at,
        "reason": reason,
        "source_run_url": source_run_url,
        "artifact": artifact,
        "details": details or {},
    }
