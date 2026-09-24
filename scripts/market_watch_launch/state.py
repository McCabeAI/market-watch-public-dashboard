"""Durable JSON store for manual Market Watch launches."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.market_watch_launch.contract import LIVE_LAUNCH_STATUSES, STAGES
from scripts.overnight.store import sha256_json, write_json

SCHEMA_VERSION = 1
STORE_RELPATH = Path("data") / "market_watch_launches"


def _dump_compact(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


class LaunchStateStore:
    def __init__(self, state_root: Path) -> None:
        self.state_root = Path(state_root)
        self.base_dir = self.state_root / STORE_RELPATH

    def index_path(self) -> Path:
        return self.base_dir / "index.json"

    def launch_dir(self, launch_id: str) -> Path:
        return self.base_dir / launch_id

    def launch_path(self, launch_id: str) -> Path:
        return self.launch_dir(launch_id) / "launch.json"

    def artifact_path(self, launch_id: str, stage: str) -> Path:
        return self.launch_dir(launch_id) / "artifacts" / f"{stage}.json"

    def _read_index(self) -> dict[str, Any]:
        path = self.index_path()
        if not path.is_file():
            return {"schema_version": SCHEMA_VERSION, "launches": [], "live_launch_id": None}
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("index.json must be an object")
        payload.setdefault("schema_version", SCHEMA_VERSION)
        payload.setdefault("launches", [])
        payload.setdefault("live_launch_id", None)
        return payload

    def _write_index(self, index: dict[str, Any]) -> None:
        index["schema_version"] = SCHEMA_VERSION
        write_json(self.index_path(), index)

    def _sync_index_row(self, launch: dict[str, Any]) -> None:
        index = self._read_index()
        row = {
            "launch_id": launch["launch_id"],
            "session_date": launch["session_date"],
            "status": launch["status"],
            "rerun": bool(launch.get("rerun")),
            "created_at": launch["created_at"],
        }
        launches = index.get("launches") or []
        replaced = False
        for i, existing in enumerate(launches):
            if existing.get("launch_id") == launch["launch_id"]:
                launches[i] = row
                replaced = True
                break
        if not replaced:
            launches.append(row)
        index["launches"] = launches
        live_id = None
        for entry in launches:
            if entry.get("status") in LIVE_LAUNCH_STATUSES:
                live_id = entry.get("launch_id")
                break
        index["live_launch_id"] = live_id
        self._write_index(index)

    def save_launch(self, launch: dict[str, Any]) -> None:
        write_json(self.launch_path(launch["launch_id"]), launch)
        self._sync_index_row(launch)

    def load_launch(self, launch_id: str) -> dict[str, Any]:
        path = self.launch_path(launch_id)
        if not path.is_file():
            raise FileNotFoundError(f"unknown launch_id {launch_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list_launches_for_session(self, session_date: str) -> list[dict[str, Any]]:
        index = self._read_index()
        rows = [
            row
            for row in (index.get("launches") or [])
            if row.get("session_date") == session_date
        ]
        rows.sort(key=lambda r: r.get("created_at") or "")
        return rows

    def current_launch_for_session(self, session_date: str) -> dict[str, Any] | None:
        rows = self.list_launches_for_session(session_date)
        if not rows:
            return None
        latest_id = rows[-1]["launch_id"]
        return self.load_launch(latest_id)

    def live_launch(self) -> dict[str, Any] | None:
        index = self._read_index()
        live_id = index.get("live_launch_id")
        if not live_id:
            return None
        try:
            launch = self.load_launch(live_id)
        except FileNotFoundError:
            return None
        if launch.get("status") not in LIVE_LAUNCH_STATUSES:
            return None
        return launch

    def write_artifact(self, launch_id: str, stage: str, body: dict[str, Any]) -> str:
        if stage not in STAGES:
            raise ValueError(f"unknown stage {stage}")
        path = self.artifact_path(launch_id, stage)
        write_json(path, body)
        return sha256_json(body)

    def read_artifact(self, launch_id: str, stage: str) -> dict[str, Any]:
        path = self.artifact_path(launch_id, stage)
        if not path.is_file():
            raise FileNotFoundError(f"missing artifact for {launch_id} stage {stage}")
        return json.loads(path.read_text(encoding="utf-8"))

    def reread_artifact(self, launch_id: str, stage: str) -> tuple[dict[str, Any], str]:
        body = self.read_artifact(launch_id, stage)
        digest = sha256_json(body)
        return body, digest

    def mutate_artifact_bytes(self, launch_id: str, stage: str, text: str) -> None:
        """Test helper: overwrite artifact file without updating launch hashes."""
        path = self.artifact_path(launch_id, stage)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
