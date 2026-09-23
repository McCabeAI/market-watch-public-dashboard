"""Health ledger: latest snapshot plus append-only events."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
HEALTH_DIR = ROOT / "data/macro_ingestion/health"
LATEST_PATH = HEALTH_DIR / "latest.json"
EVENTS_PATH = HEALTH_DIR / "events.jsonl"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ledger_row(
    *,
    series_id: str,
    status: str,
    checked_at: str,
    observation_vintage: str | None,
    calibration_as_of: str,
    cutoff_class: str,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = {
        "series_id": series_id,
        "status": status,
        "checked_at": checked_at,
        "observation_vintage": observation_vintage,
        "calibration_as_of": calibration_as_of,
        "cutoff_class": cutoff_class,
        "error": error,
    }
    if extra:
        row.update(extra)
    return row


def write_ledger(
    rows: list[dict[str, Any]],
    *,
    health_dir: Path = HEALTH_DIR,
    run_id: str | None = None,
) -> Path:
    health_dir.mkdir(parents=True, exist_ok=True)
    latest = {
        "updated_at": _utc_now_iso(),
        "run_id": run_id,
        "rows": rows,
    }
    latest_path = health_dir / "latest.json"
    latest_path.write_text(json.dumps(latest, indent=2) + "\n", encoding="utf-8")

    events_path = health_dir / "events.jsonl"
    with events_path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    return latest_path


def load_latest(health_dir: Path = HEALTH_DIR) -> dict[str, Any]:
    path = health_dir / "latest.json"
    if not path.exists():
        return {"rows": []}
    return json.loads(path.read_text(encoding="utf-8"))
