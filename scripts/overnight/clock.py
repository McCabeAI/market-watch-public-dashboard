"""America/New_York run identity and stage windows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from scripts.overnight.constants import LOCAL_CRON, OVERNIGHT_TZ, STAGE_SCHEDULE, STAGES
from scripts.overnight.errors import SchemaError

NY = ZoneInfo(OVERNIGHT_TZ)


def now_ny(when: datetime | None = None) -> datetime:
    if when is None:
        return datetime.now(tz=NY)
    if when.tzinfo is None:
        return when.replace(tzinfo=timezone.utc).astimezone(NY)
    return when.astimezone(NY)


def isoformat(when: datetime) -> str:
    return now_ny(when).isoformat()


def parse_iso(value: str) -> datetime:
    raw = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return now_ny(raw)


def overnight_run_id(when: datetime | None = None, *, dry_run: bool = False, suffix: str = "") -> str:
    ny = now_ny(when)
    base = f"overnight-{ny.strftime('%Y%m%d')}"
    if dry_run:
        base = f"{base}-dryrun"
    if suffix:
        base = f"{base}-{suffix}"
    return base


def session_date(when: datetime | None = None) -> str:
    return now_ny(when).date().isoformat()


def stage_window(stage: str, when: datetime | None = None) -> dict[str, Any]:
    if stage not in STAGE_SCHEDULE:
        raise SchemaError(f"unknown stage {stage}")
    spec = STAGE_SCHEDULE[stage]
    ny = now_ny(when)
    start = datetime.combine(ny.date(), spec["et_time"], tzinfo=NY)
    end = start + timedelta(minutes=int(spec["window_minutes"]))
    return {
        "stage": stage,
        "et_time": spec["et_time"].strftime("%H:%M"),
        "timezone": OVERNIGHT_TZ,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "window_minutes": spec["window_minutes"],
        "owner": spec["owner"],
        "summary": spec["summary"],
    }


def stage_for_time(when: datetime | None = None) -> str | None:
    ny = now_ny(when)
    for stage in STAGES:
        window = stage_window(stage, ny)
        start = parse_iso(window["window_start"])
        end = parse_iso(window["window_end"])
        if start <= ny < end:
            return stage
    return None


def schedule_catalog() -> list[dict[str, Any]]:
    return [
        stage_window(stage) | {"cron": LOCAL_CRON.get(stage)}
        for stage in STAGES
    ]
