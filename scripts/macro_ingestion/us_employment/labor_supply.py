"""Dated labor-supply regime snapshots. No high-frequency immigration interpolation."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT_PATH = ROOT / "data/macro_ingestion/us_labor_supply_snapshots.json"


def load_snapshots(path: Path = SNAPSHOT_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def current_breakeven_snapshot(
    *,
    on: date | None = None,
    path: Path = SNAPSHOT_PATH,
) -> dict[str, Any] | None:
    """Return the publication snapshot whose validity window contains `on`.

    A snapshot applies as a regime for later payroll months until it expires.
    It is not copied onto months before it was published, and it is not
    restated as a monthly path.
    """
    document = load_snapshots(path)
    today = on or date.today()
    chosen: dict[str, Any] | None = None
    for snapshot in document.get("snapshots") or []:
        published = date.fromisoformat(str(snapshot["publication_date"]))
        expires = date.fromisoformat(str(snapshot["expires_after"]))
        if published <= today <= expires and (chosen is None or published > date.fromisoformat(str(chosen["publication_date"]))):
            chosen = snapshot
    return chosen


def fetch_breakeven_snapshot(spec: dict[str, Any], *, on: date | None = None) -> dict[str, Any]:
    path = SNAPSHOT_PATH
    if not path.is_file():
        return {"ok": False, "status": "source_failed", "error": "breakeven_snapshot_missing"}
    body = path.read_bytes()
    snapshot = current_breakeven_snapshot(on=on, path=path)
    if snapshot is None:
        return {
            "ok": False,
            "status": "source_failed",
            "error": "breakeven_snapshot_not_in_force",
            "body": body,
            "raw_sha256": hashlib.sha256(body).hexdigest(),
        }
    try:
        value = float(snapshot["value_thousands_per_month"])
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "status": "source_failed", "error": "breakeven_snapshot_value_missing", "body": body}
    return {
        "ok": True,
        "points": [
            {
                "period": str(snapshot["period"]),
                "value": value,
                "transformation": str(spec.get("transform") or "thousands_per_month"),
                "revision_status": "final",
                "source_url": snapshot.get("source_url"),
                "release_date": snapshot.get("publication_date"),
                "vintage": str(snapshot.get("publication_date")),
                "derivation": {
                    "publisher": snapshot.get("publisher"),
                    "value_kind": snapshot.get("value_kind"),
                    "statement": snapshot.get("statement"),
                    "expires_after": snapshot.get("expires_after"),
                    "update_cadence": "on_publication",
                    "interpolation": "none",
                    "citations": snapshot.get("citations") or [],
                },
            }
        ],
        "vintage": str(snapshot.get("publication_date")),
        "raw_sha256": hashlib.sha256(body).hexdigest(),
        "body": body,
    }
