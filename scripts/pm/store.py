"""Git-auditable JSON persistence for the four-PM layer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.overnight.store import read_json, sha256_json, write_json
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
        latest = write_json(self.packet_path(pm_id, "latest.json"), payload)
        packet_id = payload.get("review_packet_id")
        if packet_id:
            write_json(self.packet_path(pm_id, f"{packet_id}.json"), payload)
        return latest
