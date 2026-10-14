"""Idempotent observation ledger. Conflicts are kept, not overwritten."""

from __future__ import annotations

import json


def observation_key(observation: dict) -> tuple:
    role = observation.get("role") or "rate"
    return (
        role,
        observation.get("line"),
        str(observation.get("period") or ""),
        observation.get("series_id"),
        observation.get("source_family"),
    )


def _fingerprint(observation: dict) -> tuple:
    return (
        observation.get("mom_percent"),
        observation.get("index_level"),
        observation.get("prior_index_level"),
        observation.get("seasonal_status"),
        observation.get("source_family"),
        json.dumps(observation.get("legs"), sort_keys=True, default=str) if observation.get("legs") else None,
    )


def merge_observations(ledger: dict, incoming: list[dict]) -> dict:
    changed: list[dict] = []
    conflicts: list[dict] = []
    duplicates = 0
    for observation in incoming:
        key = observation_key(observation)
        current = ledger.get(key)
        if current is None:
            stored = dict(observation)
            ledger[key] = stored
            changed.append(stored)
            continue
        if _fingerprint(current) == _fingerprint(observation):
            duplicates += 1
            continue
        rejected = dict(observation)
        rejected["has_conflict"] = True
        current["has_conflict"] = True
        conflict_key = ("conflict",) + key + _fingerprint(observation)
        conflicts.append(
            {
                "line": observation.get("line"),
                "period": observation.get("period"),
                "series_id": observation.get("series_id"),
                "kept_mom_percent": current.get("mom_percent"),
                "rejected_mom_percent": observation.get("mom_percent"),
            }
        )
        if conflict_key not in ledger:
            ledger[conflict_key] = rejected
            changed.append(rejected)
    return {"changed": changed, "conflicts": conflicts, "ignored_duplicates": duplicates}


def export_observations(ledger: dict) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for observation in ledger.values():
        if not isinstance(observation, dict):
            continue
        encoded = json.dumps(observation, sort_keys=True, default=str)
        if encoded in seen:
            continue
        seen.add(encoded)
        rows.append(observation)
    return rows


def series_ids_for_period(ledger: dict, period: str) -> set[str]:
    found: set[str] = set()
    for observation in export_observations(ledger):
        if str(observation.get("period") or "") != period:
            continue
        if observation.get("series_id"):
            found.add(str(observation["series_id"]))
        for series_id in observation.get("series_ids") or []:
            found.add(str(series_id))
    return found
