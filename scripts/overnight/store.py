"""Git-auditable JSON persistence for overnight state.

Supabase is intentionally not required. The existing market-watch-dev writer
is not credentialed for unattended production (`SUPABASE_DB_URL` may be
absent). This filesystem/git path is the shipped durable store.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.overnight.constants import BOOKS_RELPATH, LATEST_POINTER, ROOT, RUNS_DIRNAME, STATE_DIRNAME
from scripts.overnight.errors import SchemaError


def _dump(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(_dump(payload), encoding="utf-8")
    tmp.replace(path)
    return path


def read_json(path: Path) -> Any:
    if not path.is_file():
        raise SchemaError(f"missing JSON file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SchemaError(f"invalid JSON in {path}: {exc}") from exc


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_json(payload: Any) -> str:
    return sha256_text(_dump(payload))


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


class OvernightStore:
    """Read/write the overnight ledger, books, and stage artifacts."""

    def __init__(self, root: Path | None = None, *, state_root: Path | None = None):
        self.root = Path(root or ROOT)
        self.state_root = Path(state_root or self.root)

    def state_dir(self) -> Path:
        return self.state_root / STATE_DIRNAME

    def runs_dir(self) -> Path:
        return self.state_root / RUNS_DIRNAME

    def run_dir(self, run_id: str) -> Path:
        return self.runs_dir() / run_id

    def books_path(self) -> Path:
        return self.state_root / BOOKS_RELPATH

    def latest_path(self) -> Path:
        return self.state_root / LATEST_POINTER

    def artifact_path(self, run_id: str, name: str) -> Path:
        return self.run_dir(run_id) / name

    def write_artifact(self, run_id: str, name: str, payload: Any) -> Path:
        return write_json(self.artifact_path(run_id, name), payload)

    def read_artifact(self, run_id: str, name: str) -> Any:
        return read_json(self.artifact_path(run_id, name))

    def has_artifact(self, run_id: str, name: str) -> bool:
        return self.artifact_path(run_id, name).is_file()

    def write_books(self, payload: Any) -> Path:
        return write_json(self.books_path(), payload)

    def read_books(self) -> dict[str, Any]:
        return read_json(self.books_path())

    def write_latest(self, payload: Any) -> Path:
        return write_json(self.latest_path(), payload)

    def read_latest(self) -> dict[str, Any] | None:
        if not self.latest_path().is_file():
            return None
        return read_json(self.latest_path())
