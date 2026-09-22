"""Git-auditable JSON persistence for the four-PM layer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.overnight.store import read_json, sha256_json, write_json
from scripts.pm.errors import SchemaError
from scripts.pm.constants import (
    BOOKS_RELPATH,
    DECISIONS_DIRNAME,
    INBOX_RELPATH,
    PACKETS_DIRNAME,
    PUBLIC_RELPATH,
    REQUESTS_RELPATH,
    ROOT,
    STATE_DIRNAME,
)


class PMStore:
    def __init__(self, root: Path | None = None, *, state_root: Path | None = None):
        self.root = Path(root or ROOT)
        self.state_root = Path(state_root or self.root)

    def state_dir(self) -> Path:
        return self.state_root / STATE_DIRNAME

    def books_path(self) -> Path:
        return self.state_root / BOOKS_RELPATH

    def public_path(self) -> Path:
        return self.state_root / PUBLIC_RELPATH

    def requests_path(self) -> Path:
        return self.state_root / REQUESTS_RELPATH

    def inbox_path(self) -> Path:
        return self.state_root / INBOX_RELPATH

    def packets_dir(self) -> Path:
        return self.state_root / PACKETS_DIRNAME

    def packet_path(self, pm_id: str, name: str = "latest.json") -> Path:
        return self.packets_dir() / pm_id / name

    def decisions_dir(self) -> Path:
        return self.state_root / DECISIONS_DIRNAME

    def read_json(self, path: Path) -> Any:
        return read_json(path)

    def write_json(self, path: Path, payload: Any) -> Path:
        return write_json(path, payload)

    def sha256_json(self, payload: Any) -> str:
        return sha256_json(payload)

    def read_books(self) -> dict[str, Any]:
        return read_json(self.books_path())

    def write_books(self, books: dict[str, Any]) -> Path:
        return write_json(self.books_path(), books)

    def read_requests(self) -> dict[str, Any]:
        return read_json(self.requests_path())

    def write_requests(self, payload: dict[str, Any]) -> Path:
        return write_json(self.requests_path(), payload)

    def write_public(self, payload: dict[str, Any]) -> Path:
        return write_json(self.public_path(), payload)

    def write_packet(self, pm_id: str, payload: dict[str, Any]) -> Path:
        packet_id = payload.get("review_packet_id")
        if packet_id:
            named_path = self.packet_path(pm_id, f"{packet_id}.json")
            if named_path.is_file():
                existing = read_json(named_path)
                old_review_id = existing.get("review_id")
                new_review_id = payload.get("review_id")
                if (
                    isinstance(old_review_id, str)
                    and old_review_id
                    and isinstance(new_review_id, str)
                    and new_review_id
                    and old_review_id != new_review_id
                ):
                    raise SchemaError(
                        f"refusing to overwrite PM packet {packet_id} for {pm_id}: "
                        f"existing review_id={old_review_id!r}, new review_id={new_review_id!r}"
                    )
            write_json(named_path, payload)
        return write_json(self.packet_path(pm_id, "latest.json"), payload)
