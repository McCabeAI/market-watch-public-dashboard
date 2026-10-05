"""Evidence item normalization and discovery reconciliation."""

from __future__ import annotations

from typing import Any, Dict, List

from scripts.run_state.schema import (
    SCHEMA_EVIDENCE_ITEM,
    ContractError,
    sha256_json,
    validate_evidence_item,
)


def normalize_evidence_item(raw: dict) -> dict:
    doc: Dict[str, Any] = dict(raw)
    if not doc.get("schema_version"):
        doc["schema_version"] = SCHEMA_EVIDENCE_ITEM
    prov = doc.get("provenance")
    if not isinstance(prov, dict):
        prov = {}
    if not doc.get("evidence_id"):
        identity = {
            "source_name": prov.get("source_name") or "",
            "headline": doc.get("headline") or doc.get("title") or "",
            "timestamp": doc.get("timestamp") or "",
        }
        doc["evidence_id"] = "ev_" + sha256_json(identity)[:20]
    return validate_evidence_item(doc)


def reconcile_evidence(items: list[dict]) -> dict:
    if not items:
        return {
            "discovered": 0,
            "accepted": 0,
            "rendered": 0,
            "excluded": 0,
            "items": [],
        }
    normalized = [normalize_evidence_item(item) for item in items]
    discovered = len(normalized)
    accepted = sum(1 for item in normalized if item["disposition"] in ("accepted", "rendered"))
    excluded = sum(1 for item in normalized if item["disposition"] == "excluded")
    rendered = sum(1 for item in normalized if item["disposition"] == "rendered")
    if accepted + excluded != discovered or rendered > accepted:
        raise ValueError("count_mismatch")
    return {
        "discovered": discovered,
        "accepted": accepted,
        "rendered": rendered,
        "excluded": excluded,
        "items": normalized,
    }


__all__ = ["normalize_evidence_item", "reconcile_evidence", "ContractError"]
