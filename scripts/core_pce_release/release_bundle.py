"""Select one frozen CPI/PPI/BEA bundle for a target month."""

from __future__ import annotations

import json
import re
from pathlib import Path

from scripts.core_pce_release.history import shift_month
from scripts.core_pce_release.snapshot import REPO_ROOT

INDEX_PATH = REPO_ROOT / "data" / "core_pce_release" / "release_index.json"
_RELEASE_RE = re.compile(r"^\d{4}-\d{2}$")
_ISSUE_RE = re.compile(r"^\[run-(ppi|cpi)\] (\d{4}-\d{2})$")


def parse_release_month(text: str | None) -> str | None:
    if not text or _RELEASE_RE.match(text) is None:
        return None
    month = int(text[5:7])
    if month < 1 or month > 12:
        return None
    return text


def parse_issue_title(title: str | None) -> tuple[str, str] | None:
    """Return (cpi|ppi, YYYY-MM) for an exact manual-issue title."""
    if title is None:
        return None
    match = _ISSUE_RE.match(title)
    if match is None:
        return None
    release = parse_release_month(match.group(2))
    if release is None:
        return None
    return match.group(1), release


def anchor_period(release: str) -> str:
    return shift_month(release, -1)


def load_index() -> dict:
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def release_record(release: str) -> dict | None:
    if parse_release_month(release) is None:
        return None
    row = (load_index().get("releases") or {}).get(release)
    if not isinstance(row, dict):
        return None
    if row.get("anchor_period") != anchor_period(release):
        return None
    return row


def _repo_path(relative: str | None) -> Path | None:
    if not relative:
        return None
    return REPO_ROOT / relative


def resolve_release(release: str) -> dict | None:
    """Return absolute paths for one month, or None when the bundle is absent."""
    row = release_record(release)
    if row is None:
        return None
    snapshot_dir = _repo_path(row.get("snapshot_dir"))
    cpi_cache = _repo_path(row.get("cpi_cache"))
    registry = _repo_path(row.get("registry"))
    history = _repo_path(row.get("component_history"))
    if snapshot_dir is None or cpi_cache is None or registry is None or history is None:
        return None
    reference = _repo_path(row.get("reference"))
    return {
        "release": release,
        "anchor_period": row["anchor_period"],
        "snapshot_dir": snapshot_dir,
        "cpi_cache": cpi_cache,
        "ppi_points": _repo_path(row.get("ppi_points")),
        "registry": registry,
        "component_history": history,
        "reference": reference,
        "locked_regression": bool(row.get("locked_regression")),
        "record": row,
    }
