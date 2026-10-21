"""Immutable snapshot and run archives.

Identical snapshot and raw bytes are idempotent (the directory is left
untouched). Different bytes raise ArchiveConflict and do not modify the
existing files. Forecast publication is refused at or after the release
time with generated_after_freeze.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.au_cpi_release import ARCHIVE_MANIFEST_SCHEMA, BACKTEST_ARCHIVE_MANIFEST_SCHEMA
from scripts.au_cpi_release.calendar import REPO_ROOT, parse_timestamp
from scripts.au_cpi_release.contract import Snapshot
from scripts.au_cpi_release.sources.acquire import snapshot_canonical_bytes, snapshot_sha256

class ArchiveConflict(Exception):
    """An archive directory already exists with different bytes."""


class GeneratedAfterFreeze(Exception):
    """Publication was attempted at or after the release time."""

    code = "generated_after_freeze"

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__("generated_after_freeze" if not detail else f"generated_after_freeze: {detail}")


def assert_before_freeze(generated_at: datetime, release_time: datetime) -> None:
    """Refuse publication when generated_at >= release_time."""
    if generated_at.tzinfo is None or release_time.tzinfo is None:
        raise ValueError("generated_at and release_time must be timezone-aware")
    if generated_at >= release_time:
        raise GeneratedAfterFreeze(f"{generated_at.isoformat()} >= {release_time.isoformat()}")


def compact_token(value: str) -> str:
    return value.replace(":", "").replace("+", "p").replace("/", "-")


def snapshot_archive_dir(out: Path, as_of: str, snapshot: Snapshot) -> Path:
    digest = snapshot_sha256(snapshot)[:12]
    return Path(out) / "snapshots" / f"asof-{compact_token(as_of)}-{digest}"


def run_archive_dir(out: Path, release: str, as_of: str, snapshot: Snapshot, *, suffix: str = "") -> Path:
    digest = snapshot_sha256(snapshot)[:12]
    extra = f"-{suffix}" if suffix else ""
    return Path(out) / "runs" / f"{release}-asof-{compact_token(as_of)}-{digest}{extra}"


def backtest_archive_dir(out: Path, release: str | None, as_of: str, snapshot: Snapshot) -> Path:
    digest = snapshot_sha256(snapshot)[:12]
    release_token = release if release else "all"
    return Path(out) / "backtests" / f"{release_token}-asof-{compact_token(as_of)}-{digest}"


def tool_git_commit() -> str | None:
    try:
        output = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
        return None
    commit = output.strip()
    return commit or None


def tool_git_dirty() -> bool | None:
    try:
        output = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
        return None
    return bool(output.strip())


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _file_hashes(files: dict[str, bytes]) -> dict[str, dict[str, Any]]:
    listed: dict[str, dict[str, Any]] = {}
    for name in sorted(files):
        body = files[name]
        listed[name] = {"bytes": len(body), "sha256": _sha256(body)}
    return listed


def _manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return (json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def _content_matches(directory: Path, files: dict[str, bytes]) -> bool:
    for name, body in files.items():
        path = directory / name
        if not path.is_file() or path.read_bytes() != body:
            return False
    return True


def publish_tree(directory: Path, files: dict[str, bytes], manifest: dict[str, Any]) -> dict[str, Any]:
    """Write snapshot/raw/manifest. Identical files leave the directory unchanged."""
    directory = Path(directory)
    if "manifest.json" in files:
        raise ValueError("manifest.json is written by publish_tree")
    if directory.exists():
        if any(directory.iterdir()):
            if not _content_matches(directory, files):
                raise ArchiveConflict(f"archive exists at {directory} with different bytes")
            manifest_path = directory / "manifest.json"
            if manifest_path.is_file():
                return json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_path.write_bytes(_manifest_bytes(manifest))
            return manifest
        directory.rmdir()

    parent = directory.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = parent / f".{directory.name}.partial-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        for name, body in files.items():
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
            _fsync_file(target)
        manifest_path = staging / "manifest.json"
        manifest_path.write_bytes(_manifest_bytes(manifest))
        _fsync_file(manifest_path)
        if directory.exists():
            if _content_matches(directory, files):
                shutil.rmtree(staging)
                existing = directory / "manifest.json"
                if existing.is_file():
                    return json.loads(existing.read_text(encoding="utf-8"))
                return manifest
            shutil.rmtree(staging)
            raise ArchiveConflict(f"archive exists at {directory} with different bytes")
        os.rename(staging, directory)
    except ArchiveConflict:
        raise
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return manifest


def _base_manifest(
    snapshot: Snapshot,
    files: dict[str, bytes],
    *,
    as_of: str | None,
    release: str | None,
    release_time: str | None,
    generated_at: str,
) -> dict[str, Any]:
    return {
        "as_of": as_of,
        "files": _file_hashes(files),
        "files_note": "sha256 and bytes of every archived file except manifest.json, whose contents include this listing",
        "generated_at": generated_at,
        "release": release,
        "release_time": release_time,
        "retrieved_at": snapshot.retrieved_at,
        "schema_version": ARCHIVE_MANIFEST_SCHEMA,
        "snapshot_sha256": snapshot_sha256(snapshot),
        "source_urls": [
            {
                "bytes": rec.get("bytes"),
                "dataflow": rec.get("dataflow"),
                "http_status": rec.get("http_status"),
                "sha256": rec.get("sha256"),
                "source_id": rec.get("source_id"),
                "url": rec.get("url"),
            }
            for rec in snapshot.source_records
        ],
        "tool_git_commit": tool_git_commit(),
        "tool_git_dirty": tool_git_dirty(),
    }


def archive_files(snapshot: Snapshot, raw_files: dict[str, bytes]) -> dict[str, bytes]:
    files = {"snapshot.json": snapshot_canonical_bytes(snapshot)}
    for relative, body in raw_files.items():
        if relative == "manifest.json" or relative == "snapshot.json":
            raise ValueError(f"raw file name collides with archive control file: {relative}")
        files[str(relative)] = body
    return files


def write_snapshot_archive(
    directory: Path,
    snapshot: Snapshot,
    raw_files: dict[str, bytes],
    *,
    as_of: str,
    release: str | None,
    release_time: str | None,
    generated_at: str,
) -> dict[str, Any]:
    """Write ``<directory>`` with snapshot.json, raw bytes, and manifest.json."""
    files = archive_files(snapshot, raw_files)
    manifest = _base_manifest(
        snapshot,
        files,
        as_of=as_of,
        release=release,
        release_time=release_time,
        generated_at=generated_at,
    )
    return publish_tree(directory, files, manifest)


def write_reference_run_archive(
    directory: Path,
    snapshot: Snapshot,
    *,
    snapshot_path: str,
    as_of: str,
    release: str,
    release_time: str,
    generated_at: datetime,
    extra_files: dict[str, bytes],
) -> dict[str, Any]:
    """Slim run archive: nowcast outputs plus manifest with external snapshot reference."""
    assert_before_freeze(generated_at, parse_timestamp(release_time, date_only="start"))
    files = dict(extra_files)
    if "manifest.json" in files:
        raise ValueError("manifest.json is written by publish_tree")
    manifest = _base_manifest(
        snapshot,
        files,
        as_of=as_of,
        release=release,
        release_time=release_time,
        generated_at=generated_at.isoformat(),
    )
    manifest["snapshot_path"] = snapshot_path
    manifest["snapshot_sha256"] = snapshot_sha256(snapshot)
    return publish_tree(directory, files, manifest)


def write_run_archive(
    directory: Path,
    snapshot: Snapshot,
    raw_files: dict[str, bytes],
    *,
    as_of: str,
    release: str,
    release_time: str,
    generated_at: datetime,
    extra_files: dict[str, bytes] | None = None,
) -> dict[str, Any]:
    """Publish a run directory. Refuses when generated_at >= release_time, before any write."""
    assert_before_freeze(generated_at, parse_timestamp(release_time, date_only="start"))
    files = archive_files(snapshot, raw_files)
    for name, body in (extra_files or {}).items():
        if name in files or name == "manifest.json":
            raise ValueError(f"extra file collides: {name}")
        files[name] = body
    manifest = _base_manifest(
        snapshot,
        files,
        as_of=as_of,
        release=release,
        release_time=release_time,
        generated_at=generated_at.isoformat(),
    )
    return publish_tree(directory, files, manifest)


def write_backtest_archive(
    directory: Path,
    snapshot: Snapshot,
    *,
    as_of: str,
    release: str | None,
    generated_at: str,
    backtest_json: bytes,
    backtest_txt: bytes,
) -> dict[str, Any]:
    """Publish a backtest directory with backtest.json, backtest.txt, and manifest.json."""
    files = {
        "backtest.json": backtest_json,
        "backtest.txt": backtest_txt,
    }
    manifest: dict[str, Any] = {
        "as_of": as_of,
        "files": _file_hashes(files),
        "files_note": "sha256 and bytes of every archived file except manifest.json, whose contents include this listing",
        "generated_at": generated_at,
        "release": release,
        "schema_version": BACKTEST_ARCHIVE_MANIFEST_SCHEMA,
        "snapshot_sha256": snapshot_sha256(snapshot),
        "tool_git_commit": tool_git_commit(),
        "tool_git_dirty": tool_git_dirty(),
    }
    return publish_tree(directory, files, manifest)
