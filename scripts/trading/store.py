"""Git-backed file layout for the 18-identity trading memory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.overnight.clock import isoformat, now_ny
from scripts.overnight.constants import ROOT
from scripts.overnight.store import read_json, sha256_json, write_json
from scripts.trading.constants import (
    ALL_IDENTITIES,
    OWNER_TYPES,
    PM_IDS,
    SCHEMA_VERSION,
    STANDING_TRADERS,
    STATE_DIRNAME,
)
from scripts.trading.errors import SchemaError


def identity_key(owner_type: str, owner_id: str) -> str:
    return f"{owner_type}/{owner_id}"


def assert_identity(owner_type: str, owner_id: str) -> tuple[str, str]:
    if owner_type not in OWNER_TYPES:
        raise SchemaError(f"owner_type must be trader|pm, got {owner_type}")
    if owner_type == "trader" and owner_id not in STANDING_TRADERS:
        raise SchemaError(f"unknown trader identity {owner_id}")
    if owner_type == "pm" and owner_id not in PM_IDS:
        raise SchemaError(f"unknown pm identity {owner_id}")
    return owner_type, owner_id


def empty_identity_index(owner_type: str, owner_id: str) -> dict[str, Any]:
    return {
        "owner_type": owner_type,
        "owner_id": owner_id,
        "trade_ids": [],
        "open_trade_ids": [],
        "closed_trade_ids": [],
    }


def empty_index(*, when=None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "TRADING_LEDGER_INDEX",
        "updated_at": isoformat(now_ny(when)),
        "identities": [empty_identity_index(owner_type, owner_id) for owner_type, owner_id in ALL_IDENTITIES],
        "trade_ids": [],
    }


def empty_journal() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "TRADING_DECISION_JOURNAL",
        "events": [],
    }


def empty_lessons() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "TRADING_LESSONS",
        "lessons": [],
    }


def empty_postmortems() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "TRADING_POSTMORTEMS",
        "items": [],
    }


def empty_postmortems_due() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "TRADING_POSTMORTEMS_DUE",
        "items": [],
    }


class TradingStore:
    """Read/write data/trading without inventing canonical facts."""

    def __init__(self, root: Path | None = None, *, state_root: Path | None = None):
        self.root = Path(root or ROOT)
        self.state_root = Path(state_root or self.root)

    def state_dir(self) -> Path:
        return self.state_root / STATE_DIRNAME

    def index_path(self) -> Path:
        return self.state_dir() / "index.json"

    def trades_dir(self) -> Path:
        return self.state_dir() / "trades"

    def trade_path(self, trade_id: str) -> Path:
        return self.trades_dir() / f"{trade_id}.json"

    def identity_dir(self, owner_type: str, owner_id: str) -> Path:
        assert_identity(owner_type, owner_id)
        return self.state_dir() / owner_type / owner_id

    def journal_path(self, owner_type: str, owner_id: str) -> Path:
        return self.identity_dir(owner_type, owner_id) / "journal.json"

    def lessons_path(self, owner_type: str, owner_id: str) -> Path:
        return self.identity_dir(owner_type, owner_id) / "lessons.json"

    def postmortems_path(self, owner_type: str, owner_id: str) -> Path:
        return self.identity_dir(owner_type, owner_id) / "postmortems.json"

    def postmortems_due_path(self, owner_type: str, owner_id: str) -> Path:
        return self.identity_dir(owner_type, owner_id) / "postmortems_due.json"

    def context_path(self, owner_type: str, owner_id: str) -> Path:
        return self.identity_dir(owner_type, owner_id) / "context.json"

    def write_json(self, path: Path, payload: Any) -> Path:
        return write_json(path, payload)

    def read_json(self, path: Path) -> Any:
        return read_json(path)

    def sha256_json(self, payload: Any) -> str:
        return sha256_json(payload)

    def ensure_initialized(self, *, when=None) -> dict[str, Any]:
        index = self.read_index() if self.index_path().is_file() else empty_index(when=when)
        known = {(row["owner_type"], row["owner_id"]) for row in index.get("identities") or []}
        for owner_type, owner_id in ALL_IDENTITIES:
            if (owner_type, owner_id) not in known:
                index.setdefault("identities", []).append(empty_identity_index(owner_type, owner_id))
            self._ensure_identity_files(owner_type, owner_id)
        self.write_index(index)
        return index

    def _ensure_identity_files(self, owner_type: str, owner_id: str) -> None:
        if not self.journal_path(owner_type, owner_id).is_file():
            self.write_json(self.journal_path(owner_type, owner_id), empty_journal())
        if not self.lessons_path(owner_type, owner_id).is_file():
            self.write_json(self.lessons_path(owner_type, owner_id), empty_lessons())
        if not self.postmortems_path(owner_type, owner_id).is_file():
            self.write_json(self.postmortems_path(owner_type, owner_id), empty_postmortems())
        if not self.postmortems_due_path(owner_type, owner_id).is_file():
            self.write_json(self.postmortems_due_path(owner_type, owner_id), empty_postmortems_due())

    def read_index(self) -> dict[str, Any]:
        return read_json(self.index_path())

    def write_index(self, index: dict[str, Any]) -> Path:
        index["schema_version"] = SCHEMA_VERSION
        index["updated_at"] = isoformat(now_ny())
        return write_json(self.index_path(), index)

    def identity_row(self, owner_type: str, owner_id: str) -> dict[str, Any]:
        assert_identity(owner_type, owner_id)
        index = self.ensure_initialized()
        for row in index["identities"]:
            if row["owner_type"] == owner_type and row["owner_id"] == owner_id:
                return row
        raise SchemaError(f"missing identity row for {identity_key(owner_type, owner_id)}")

    def list_trade_ids(self, owner_type: str | None = None, owner_id: str | None = None) -> list[str]:
        if owner_type and owner_id:
            return list(self.identity_row(owner_type, owner_id).get("trade_ids") or [])
        index = self.ensure_initialized()
        return list(index.get("trade_ids") or [])

    def has_trade(self, trade_id: str) -> bool:
        return self.trade_path(trade_id).is_file()

    def read_trade(self, trade_id: str) -> dict[str, Any]:
        return read_json(self.trade_path(trade_id))

    def write_trade(self, trade: dict[str, Any]) -> Path:
        trade_id = trade.get("trade_id")
        if not isinstance(trade_id, str) or not trade_id:
            raise SchemaError("trade_id is required")
        path = write_json(self.trade_path(trade_id), trade)
        self._index_trade(trade)
        return path

    def _index_trade(self, trade: dict[str, Any]) -> None:
        index = self.ensure_initialized()
        trade_id = trade["trade_id"]
        if trade_id not in index["trade_ids"]:
            index["trade_ids"].append(trade_id)
        for row in index["identities"]:
            if row["owner_type"] != trade["owner_type"] or row["owner_id"] != trade["owner_id"]:
                continue
            if trade_id not in row["trade_ids"]:
                row["trade_ids"].append(trade_id)
            if trade.get("status") == "open":
                if trade_id not in row["open_trade_ids"]:
                    row["open_trade_ids"].append(trade_id)
                if trade_id in row["closed_trade_ids"]:
                    row["closed_trade_ids"].remove(trade_id)
            else:
                if trade_id in row["open_trade_ids"]:
                    row["open_trade_ids"].remove(trade_id)
                if trade_id not in row["closed_trade_ids"]:
                    row["closed_trade_ids"].append(trade_id)
            break
        self.write_index(index)

    def read_journal(self, owner_type: str, owner_id: str) -> dict[str, Any]:
        self.ensure_initialized()
        return read_json(self.journal_path(owner_type, owner_id))

    def write_journal(self, owner_type: str, owner_id: str, journal: dict[str, Any]) -> Path:
        return write_json(self.journal_path(owner_type, owner_id), journal)

    def read_lessons(self, owner_type: str, owner_id: str) -> dict[str, Any]:
        self.ensure_initialized()
        return read_json(self.lessons_path(owner_type, owner_id))

    def write_lessons(self, owner_type: str, owner_id: str, payload: dict[str, Any]) -> Path:
        return write_json(self.lessons_path(owner_type, owner_id), payload)

    def read_postmortems(self, owner_type: str, owner_id: str) -> dict[str, Any]:
        self.ensure_initialized()
        return read_json(self.postmortems_path(owner_type, owner_id))

    def write_postmortems(self, owner_type: str, owner_id: str, payload: dict[str, Any]) -> Path:
        return write_json(self.postmortems_path(owner_type, owner_id), payload)

    def read_postmortems_due(self, owner_type: str, owner_id: str) -> dict[str, Any]:
        self.ensure_initialized()
        return read_json(self.postmortems_due_path(owner_type, owner_id))

    def write_postmortems_due(self, owner_type: str, owner_id: str, payload: dict[str, Any]) -> Path:
        return write_json(self.postmortems_due_path(owner_type, owner_id), payload)

    def write_context(self, owner_type: str, owner_id: str, context: dict[str, Any]) -> Path:
        return write_json(self.context_path(owner_type, owner_id), context)

    def read_context(self, owner_type: str, owner_id: str) -> dict[str, Any] | None:
        path = self.context_path(owner_type, owner_id)
        if not path.is_file():
            return None
        return read_json(path)

    def trades_for(self, owner_type: str, owner_id: str) -> list[dict[str, Any]]:
        return [self.read_trade(trade_id) for trade_id in self.list_trade_ids(owner_type, owner_id)]
