"""Live source status. Component fetches stay closed until series ids are verified."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.core_pce_release.snapshot import REPO_ROOT

REGISTRY_PATH = REPO_ROOT / "data" / "core_pce_release" / "series_registry.json"


def load_registry(path: Path | None = None) -> dict:
    return json.loads((path or REGISTRY_PATH).read_text(encoding="utf-8"))


def live_fetch_status(registry: dict | None = None) -> dict:
    document = registry if registry is not None else load_registry()
    verified = document.get("verified") or []
    component_ids = [row["series_id"] for row in verified if row.get("maps_to_pce_line") is not None]
    ready = document.get("live_component_fetch") == "READY" and len(component_ids) > 0
    return {
        "status": "READY" if ready else "NOT READY",
        "blocker": None if ready else document.get("blocker"),
        "verified_context_series": [row["series_id"] for row in verified if row.get("role") == "cpi_context_only"],
        "pce_component_series_ids": len(component_ids),
    }
