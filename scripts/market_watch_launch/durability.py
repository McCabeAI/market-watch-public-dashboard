"""Record and verify remote freeze attestations (no git push)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REMOTE_FREEZE_FILENAME = "remote_freeze.json"
BINDING_FILENAME = "freeze_binding.json"


def _non_empty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def record_remote_freeze(
    launch_dir: Path,
    *,
    commit_sha: str,
    packet_sha256: str,
    trader_books_sha256: str,
    pm_books_sha256: str,
    score_state_sha256: str,
) -> Path:
    launch_dir = Path(launch_dir)
    launch_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "commit_sha": commit_sha,
        "packet_sha256": packet_sha256,
        "trader_books_sha256": trader_books_sha256,
        "pm_books_sha256": pm_books_sha256,
        "score_state_sha256": score_state_sha256,
    }
    path = launch_dir / REMOTE_FREEZE_FILENAME
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_remote_freeze(launch_dir: Path) -> dict[str, Any] | None:
    path = Path(launch_dir) / REMOTE_FREEZE_FILENAME
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def remote_freeze_verified(launch_dir: Path) -> bool:
    row = load_remote_freeze(launch_dir)
    if row is None:
        return False
    fields = (
        "commit_sha",
        "packet_sha256",
        "trader_books_sha256",
        "pm_books_sha256",
        "score_state_sha256",
    )
    if not all(_non_empty_str(row.get(name)) for name in fields):
        return False
    binding_path = Path(launch_dir) / BINDING_FILENAME
    if binding_path.is_file():
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
        if binding.get("packet_sha256") != row.get("packet_sha256"):
            return False
    return True
