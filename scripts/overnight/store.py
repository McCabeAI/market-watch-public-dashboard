"""Git-auditable JSON persistence for overnight state.

Supabase is intentionally not required. The existing market-watch-dev writer
is not credentialed for unattended production (`SUPABASE_DB_URL` may be
absent). This filesystem/git path is the shipped durable store.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from scripts.overnight.constants import BOOKS_RELPATH, LATEST_POINTER, ROOT, RUNS_DIRNAME, STATE_DIRNAME
from scripts.overnight.errors import SchemaError

REVIEW_ID_RE = re.compile(r"^review-[0-9]{3,}$")
REVIEW_SCOPED_ARTIFACTS = frozenset(
    {
        "evidence_snapshot.json",
        "agent_evidence_packet.json",
        "scheduled_output.json",
        "trader_review.json",
    }
)
ACCEPTED_REVIEW_ARTIFACTS = frozenset(
    {
        "agent_evidence_packet.json",
        "scheduled_output.json",
        "trader_review.json",
    }
)


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

    def reviews_dir(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "reviews"

    def reviews_index_path(self, run_id: str) -> Path:
        return self.reviews_dir(run_id) / "index.json"

    def review_dir(self, run_id: str, review_id: str) -> Path:
        if not REVIEW_ID_RE.match(review_id):
            raise SchemaError(f"malformed review_id {review_id!r}")
        return self.reviews_dir(run_id) / review_id

    def read_review_index(self, run_id: str) -> dict[str, Any] | None:
        path = self.reviews_index_path(run_id)
        if not path.is_file():
            return None
        payload = read_json(path)
        if not isinstance(payload, dict):
            raise SchemaError(f"review index for {run_id} must be an object")
        return payload

    def review_rows(self, run_id: str) -> list[dict[str, Any]]:
        index = self.read_review_index(run_id) or {}
        rows = index.get("reviews") or []
        return [row for row in rows if isinstance(row, dict) and isinstance(row.get("review_id"), str)]

    def latest_review_id(self, run_id: str, *, statuses: set[str] | None = None) -> str | None:
        chosen = None
        for row in self.review_rows(run_id):
            if statuses is not None and row.get("status") not in statuses:
                continue
            chosen = row["review_id"]
        return chosen

    def books_path(self) -> Path:
        return self.state_root / BOOKS_RELPATH

    def latest_path(self) -> Path:
        return self.state_root / LATEST_POINTER

    def _resolve_review_artifact(self, run_id: str, name: str) -> Path | None:
        rows = self.review_rows(run_id)
        if name in ACCEPTED_REVIEW_ARTIFACTS:
            for row in reversed(rows):
                if row.get("status") != "accepted":
                    continue
                path = self.review_dir(run_id, row["review_id"]) / name
                if path.is_file():
                    return path
        for row in reversed(rows):
            path = self.review_dir(run_id, row["review_id"]) / name
            if path.is_file():
                return path
        legacy = self.run_dir(run_id) / name
        if legacy.is_file():
            return legacy
        return None

    def artifact_path(self, run_id: str, name: str, *, review_id: str | None = None) -> Path:
        if review_id:
            return self.review_dir(run_id, review_id) / name
        if name in REVIEW_SCOPED_ARTIFACTS:
            resolved = self._resolve_review_artifact(run_id, name)
            if resolved is not None:
                return resolved
        return self.run_dir(run_id) / name

    def write_artifact(self, run_id: str, name: str, payload: Any, *, review_id: str | None = None) -> Path:
        if name in REVIEW_SCOPED_ARTIFACTS and review_id is None:
            review_id = self.latest_review_id(
                run_id, statuses={"allocating", "freezing", "frozen", "accepting"}
            )
        return write_json(self.artifact_path(run_id, name, review_id=review_id), payload)

    def read_artifact(self, run_id: str, name: str, *, review_id: str | None = None) -> Any:
        return read_json(self.artifact_path(run_id, name, review_id=review_id))

    def has_artifact(self, run_id: str, name: str, *, review_id: str | None = None) -> bool:
        return self.artifact_path(run_id, name, review_id=review_id).is_file()

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
