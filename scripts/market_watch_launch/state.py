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

    def index_rows(self) -> list[dict[str, Any]]:
        index = self._read_index()
        return list(index.get("launches") or [])

    def _sync_index_row(self, launch: dict[str, Any]) -> None:
        from scripts.market_watch_launch.milestones import (
            holds_data_collection_lock,
            launch_phase,
            research_publication,
        )

        index = self._read_index()
        launch_id = launch["launch_id"]
        launch_dir = self.launch_dir(launch_id)
        research_verified = research_publication(launch_dir, launch) is not None
        row = {
            "launch_id": launch_id,
            "session_date": launch["session_date"],
            "status": launch["status"],
            "rerun": bool(launch.get("rerun")),
            "created_at": launch["created_at"],
            "phase": launch_phase(launch, research_verified=research_verified),
        }
        launches = index.get("launches") or []
        replaced = False
        for i, existing in enumerate(launches):
            if existing.get("launch_id") == launch_id:
                launches[i] = row
                replaced = True
                break
        if not replaced:
            launches.append(row)
        index["launches"] = launches
        live_id = None
        for entry in launches:
            lid = entry.get("launch_id")
            if not lid:
                continue
            if lid == launch_id:
                candidate = launch
            else:
                if entry.get("status") not in LIVE_LAUNCH_STATUSES:
                    continue
                try:
                    candidate = self.load_launch(str(lid))
                except FileNotFoundError:
                    continue
            if holds_data_collection_lock(
                candidate,
                launch_dir=self.launch_dir(str(lid)),
                today=None,
            ):
                live_id = lid
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

    def data_collection_holder(self, today: str | None) -> dict[str, Any] | None:
        from scripts.market_watch_launch.milestones import holds_data_collection_lock

        for row in self.index_rows():
            lid = row.get("launch_id")
            if not lid or row.get("status") not in LIVE_LAUNCH_STATUSES:
                continue
            try:
                launch = self.load_launch(str(lid))
            except FileNotFoundError:
                continue
            if holds_data_collection_lock(
                launch,
                launch_dir=self.launch_dir(str(lid)),
                today=today,
            ):
                return launch
        return None

    def live_launch(self) -> dict[str, Any] | None:
        return self.data_collection_holder(None)

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
