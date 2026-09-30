"""Persist the latest attention snapshot used to judge reprint freshness.

The file stores one record per observation id: the latest value and the
fields that decide an unchanged reprint. History is not written. Importing
this module does not touch ``data/``.
"""

from __future__ import annotations

import json
from pathlib import Path

SNAPSHOT_VERSION = 1
SNAPSHOT_FIELDS = (
    "value",
    "reference_period",
    "transformation",
    "revision_status",
    "vintage",
)


def _record(source: dict) -> dict:
    return {field: source.get(field) for field in SNAPSHOT_FIELDS}


def _observations_from_evaluate(snapshot: dict) -> dict[str, dict]:
    records: dict[str, dict] = {}
    for member in snapshot.get("members") or []:
        observation_id = member.get("observation_id")
        if not observation_id:
            raise ValueError("evaluate result member is missing observation_id")
        records[str(observation_id)] = _record(member)
    return records


def _observations_from_file_shape(snapshot: dict) -> dict[str, dict]:
    raw = snapshot.get("observations")
    if not isinstance(raw, dict):
        raise ValueError("attention snapshot observations must be an object")
    records: dict[str, dict] = {}
    for observation_id, payload in raw.items():
        if not isinstance(payload, dict):
            raise ValueError(f"attention snapshot record {observation_id} must be an object")
        records[str(observation_id)] = _record(payload)
    return records


def snapshot_observations(snapshot: dict) -> dict[str, dict]:
    """Normalize an evaluate result or a snapshot document to id -> record."""
    if not isinstance(snapshot, dict):
        raise TypeError("snapshot must be a dict")
    if "members" in snapshot:
        return _observations_from_evaluate(snapshot)
    if "observations" in snapshot:
        return _observations_from_file_shape(snapshot)
    if snapshot and all(isinstance(value, dict) for value in snapshot.values()):
        return {str(observation_id): _record(payload) for observation_id, payload in snapshot.items()}
    raise ValueError("snapshot must be an evaluate result or a versioned attention snapshot")


def load_snapshot(path: Path) -> dict:
    """Load a versioned attention snapshot.

    Returns ``{"version": 1, "observations": {observation_id: record}}``.
    The observations map is the ``prior`` accepted by ``evaluate_observations``.
    """
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("version") != SNAPSHOT_VERSION:
        raise ValueError("unrecognized attention snapshot")
    if not isinstance(document.get("observations"), dict):
        raise ValueError("attention snapshot is missing observations")
    return {
        "version": SNAPSHOT_VERSION,
        "observations": _observations_from_file_shape(document),
    }


def save_snapshot(path: Path, snapshot: dict) -> None:
    """Write ``{"version": 1, "observations": {...}}`` for the latest values.

    ``snapshot`` is an ``evaluate_observations`` result, or an already
    normalized snapshot document. Each observation id is stored once.
    """
    payload = {
        "version": SNAPSHOT_VERSION,
        "observations": snapshot_observations(snapshot),
    }
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    destination.write_text(text, encoding="utf-8")
