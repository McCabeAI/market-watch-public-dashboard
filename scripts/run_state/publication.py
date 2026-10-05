"""Offline publication from an approved candidate bundle (no fetch, no rescore)."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Mapping, Union

from scripts.run_state.schema import validate_evidence_item

PathLike = Union[str, Path]

_FORBIDDEN_BUNDLE_KEYS = frozenset({"opener", "fetch", "rescore"})


def _parse_aware_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            return None
        return value
    if isinstance(value, str) and value:
        text = value.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            return None
        return dt
    return None


def publish_offline(bundle: dict, manifest: dict, *, output_dir: str | Path) -> dict:
    if manifest.get("publication_mode") != "offline":
        raise ValueError("publication_mode must be offline for publish_offline")

    for key in _FORBIDDEN_BUNDLE_KEYS:
        if key in bundle:
            raise ValueError(f"bundle must not contain {key!r}")

    if bundle.get("score_state_sha256") != manifest.get("score_state_sha256"):
        raise ValueError("score_mismatch")

    for field in ("cutoff_at", "freeze_cutoff"):
        if bundle.get(field) != manifest.get(field):
            raise ValueError("cutoff_mismatch")

    cutoff_at = _parse_aware_datetime(bundle["cutoff_at"])
    if cutoff_at is None:
        raise ValueError("cutoff_mismatch")

    evidence_items = bundle.get("evidence_items")
    if not isinstance(evidence_items, list):
        raise ValueError("evidence_items must be a list")
    for item in evidence_items:
        if not isinstance(item, dict):
            raise ValueError("evidence_items entries must be dicts")
        validate_evidence_item(item)
        ts = item.get("timestamp")
        if ts is not None:
            item_dt = _parse_aware_datetime(ts)
            if item_dt is not None:
                if item_dt > cutoff_at:
                    raise ValueError("post_cutoff")
            elif isinstance(ts, str) and ts:
                unc = item.get("timestamp_uncertainty")
                if unc == "date_only" and "T" not in ts:
                    try:
                        item_date = date.fromisoformat(ts)
                    except ValueError:
                        raise ValueError("post_cutoff")
                    if item_date > cutoff_at.date():
                        raise ValueError("post_cutoff")
                else:
                    raise ValueError("post_cutoff")

    public_body: Dict[str, Any] = {
        "run_id": bundle["run_id"],
        "score_state_sha256": bundle["score_state_sha256"],
        "state_ids": bundle["state_ids"],
        "policy_version": bundle["policy_version"],
        "cutoff_at": bundle["cutoff_at"],
        "public_caveat": bundle["public_caveat"],
        "evidence_items": evidence_items,
        "temperature_scores": bundle["temperature_scores"],
    }

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    public_path = out_path / "public.json"
    text = json.dumps(public_body, sort_keys=True, indent=2, ensure_ascii=False)
    public_path.write_text(text, encoding="utf-8")

    artifact_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    public_packet_id = "pp_" + artifact_sha256[:20]

    return {
        "public_packet_id": public_packet_id,
        "artifact_sha256": artifact_sha256,
        "files": ["public.json"],
        "launch_id": bundle["run_id"],
    }


def acknowledge_deploy(
    *,
    launch_id: str,
    artifact_sha256: str,
    receipt: dict,
    store: dict,
) -> dict:
    if "launch_id" not in receipt or "artifact_sha256" not in receipt:
        raise ValueError("receipt must include launch_id and artifact_sha256")
    if receipt["launch_id"] != launch_id:
        raise ValueError("launch_mismatch")
    if receipt["artifact_sha256"] != artifact_sha256:
        raise ValueError("artifact_mismatch")

    key = f"{launch_id}:{artifact_sha256}"
    if key in store:
        existing = dict(store[key])
        existing["idempotent"] = True
        return existing

    record = dict(receipt)
    record["acknowledged"] = True
    record["idempotent"] = False
    store[key] = record
    return dict(record)
