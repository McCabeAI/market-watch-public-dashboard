"""ACP freeze window helpers and post-freeze delta writer."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
FREEZE_CUTOFF = (1, 50)  # 01:50 America/New_York
FREEZE_CUTOFF_LABEL = "01:50 America/New_York"
TRUSTED_PACKET_STATEMENT = (
    "These macro points were not in the trusted trader packet frozen at 01:50 America/New_York."
)

ROOT = Path(__file__).resolve().parents[2]
POST_FREEZE_DIR = ROOT / "data/macro_ingestion/post_freeze"

_FORBIDDEN_PATH_RE = re.compile(r"reviews/|evidence_snapshot", re.IGNORECASE)


class PostFreezePathError(ValueError):
    pass


def session_date_ny(when: datetime) -> date:
    if when.tzinfo is None:
        when = when.replace(tzinfo=NY)
    return when.astimezone(NY).date()


def cutoff_class(when: datetime) -> str:
    if when.tzinfo is None:
        when = when.replace(tzinfo=NY)
    local = when.astimezone(NY)
    hour, minute = FREEZE_CUTOFF
    if local.hour < hour or (local.hour == hour and local.minute < minute):
        return "pre_freeze"
    return "post_freeze"


def assert_allowed_output_path(path: Path | str) -> None:
    text = str(path)
    if _FORBIDDEN_PATH_RE.search(text):
        raise PostFreezePathError(f"Refusing forbidden output path: {text}")


def _stamp_compact(when: datetime) -> str:
    if when.tzinfo is None:
        when = when.replace(tzinfo=NY)
    local = when.astimezone(NY)
    return local.strftime("%Y%m%dT%H%M%S")


def post_freeze_filename(session: date, when: datetime) -> str:
    return f"{session.isoformat()}-{_stamp_compact(when)}.json"


def write_post_freeze_delta(
    *,
    when: datetime,
    changed_series: list[dict[str, Any]],
    run_id: str | None = None,
    base_dir: Path = POST_FREEZE_DIR,
) -> Path:
    """Create a new immutable post-freeze file; never overwrite an existing stamp."""
    if cutoff_class(when) != "post_freeze":
        raise ValueError("post-freeze writer called before freeze cutoff")

    session = session_date_ny(when)
    name = post_freeze_filename(session, when)
    path = base_dir / name
    assert_allowed_output_path(path)

    if path.exists():
        # Immutability: append a disambiguating suffix rather than overwrite.
        suffix = 1
        while True:
            alt = base_dir / name.replace(".json", f"-{suffix}.json")
            assert_allowed_output_path(alt)
            if not alt.exists():
                path = alt
                break
            suffix += 1

    base_dir.mkdir(parents=True, exist_ok=True)
    doc = {
        "session_date": session.isoformat(),
        "observed_at": when.astimezone(NY).isoformat(),
        "freeze_cutoff": FREEZE_CUTOFF_LABEL,
        "run_id": run_id,
        "cutoff_class": "post_freeze",
        "trusted_packet_statement": TRUSTED_PACKET_STATEMENT,
        "changed_series": changed_series,
    }
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return path
