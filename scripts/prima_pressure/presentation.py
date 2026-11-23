"""Read-only Country Detail presentation for Canada Prima-pressure history."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from datetime import date, datetime

from scripts.market_watch_launch.durability import load_remote_freeze, remote_freeze_verified
from scripts.overnight.store import sha256_json
from scripts.prima_pressure.contract import CHANNELS, DIRECTIONS, DISCLAIMER
from scripts.prima_pressure.expiry import assess_stored_shock_inputs

_PREVIEW_EXCLUSION_HUMAN: dict[str, str] = {
    "snapshot_hash_mismatch": (
        "A newer frozen overnight review did not pass verification (snapshot hash mismatch); "
        "this card shows the last accepted reading."
    ),
    "observed_at_mismatch": (
        "A newer frozen overnight review was misdated and was not shown; "
        "this card shows the last accepted reading."
    ),
    "unverified_frozen_review": (
        "A newer frozen overnight review did not pass verification; "
        "this card shows the last accepted reading."
    ),
    "missing_snapshot": (
        "A newer frozen overnight review is missing its evidence snapshot; "
        "this card shows the last accepted reading."
    ),
    "freeze_binding_mismatch": (
        "A newer frozen overnight review did not match trusted launch freeze attestation; "
        "this card shows the last accepted reading."
    ),
    "preview_not_newer": (
        "A newer frozen overnight review is not after the last accepted run and was not shown; "
        "this card shows the last accepted reading."
    ),
}

PRESENTATION_SCHEMA = "canada_prima_pressure_presentation_v1"
_SOURCE_KIND = "overnight_evidence_snapshot"
_REVIEW_ID_RE = re.compile(r"^review-[0-9]{3,}$")

_HISTORY_NOTE_NONE = (
    "History begins here: no stored Market Watch Prima observations have been recorded yet."
)
_HISTORY_NOTE_ONE = (
    "History begins here: one stored Market Watch observation is on file; "
    "not enough runs to show a direction transition."
)
_HISTORY_NOTE_TREND = (
    "Stored Market Watch Prima observations are listed in time order; "
    "transitions reflect consecutive stored runs only."
)


def _normalize_direction(raw: Any, reasons: list[str]) -> str:
    if raw in DIRECTIONS:
        return str(raw)
    if raw is None or raw == "":
        reasons.append("direction_missing")
    else:
        reasons.append("direction_invalid")
    return "UNAVAILABLE"


def _as_optional_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def project_block(block: dict[str, Any]) -> dict[str, Any]:
    """Normalize a compact canada_prima_pressure block for presentation."""
    reasons: list[str] = []
    direction = _normalize_direction(block.get("direction"), reasons)

    subs_raw = block.get("subcomponent_directions")
    subs = subs_raw if isinstance(subs_raw, dict) else {}
    subcomponent_directions: dict[str, str] = {}
    for channel in CHANNELS:
        value = subs.get(channel)
        subcomponent_directions[channel] = (
            str(value) if value in DIRECTIONS else "UNAVAILABLE"
        )

    staleness = block.get("staleness")
    staleness_text = str(staleness) if staleness is not None else None
    status = block.get("status")
    status_text = str(status) if status is not None else None

    stale = False
    if staleness_text and "stale" in staleness_text.lower():
        stale = True
    if status_text == "stale":
        stale = True

    drivers_raw = block.get("largest_drivers")
    largest_drivers: list[str] = []
    if isinstance(drivers_raw, list):
        for item in drivers_raw[:3]:
            if isinstance(item, str) and item.strip():
                largest_drivers.append(item.strip())

    block_reason = block.get("reason")
    if block_reason is not None and str(block_reason).strip():
        reasons.append(str(block_reason).strip())

    unique_reasons: list[str] = []
    for item in reasons:
        if item not in unique_reasons:
            unique_reasons.append(item)

    channel_evidence: dict[str, Any] | None = None
    ce_raw = block.get("channel_evidence")
    if isinstance(ce_raw, dict):
        normalized_ce: dict[str, Any] = {}
        for channel in CHANNELS:
            entry = ce_raw.get(channel)
            if isinstance(entry, dict):
                normalized_ce[channel] = entry
        if normalized_ce:
            channel_evidence = normalized_ce

    projected: dict[str, Any] = {
        "direction": direction,
        "subcomponent_directions": subcomponent_directions,
        "confidence": block.get("confidence") if block.get("confidence") is not None else None,
        "coverage": _as_optional_float(block.get("coverage")),
        "staleness": staleness_text,
        "status": status_text,
        "reason": "; ".join(unique_reasons) if unique_reasons else None,
        "mpr_status": block.get("mpr_status"),
        "conditioning_date": block.get("conditioning_date"),
        "change_since_last_mpr": block.get("change_since_last_mpr"),
        "disclaimer": str(block.get("disclaimer") or DISCLAIMER),
        "largest_drivers": largest_drivers,
        "stale": stale,
    }
    if channel_evidence is not None:
        projected["channel_evidence"] = channel_evidence
    shadow = block.get("shadow_sector_layer")
    if isinstance(shadow, dict):
        projected["shadow_sector_layer"] = shadow
    return projected


def _synthetic_unavailable_current() -> dict[str, Any]:
    return {
        "direction": "UNAVAILABLE",
        "subcomponent_directions": {ch: "UNAVAILABLE" for ch in CHANNELS},
        "confidence": None,
        "coverage": None,
        "staleness": None,
        "status": "unavailable",
        "reason": "no_persisted_prima_observation",
        "mpr_status": "unavailable",
        "conditioning_date": None,
        "change_since_last_mpr": None,
        "disclaimer": DISCLAIMER,
        "largest_drivers": [],
        "stale": False,
    }


def _presentation_shell(
    *,
    history_state: str,
    history_note: str,
    current: dict[str, Any],
    trend: list[dict[str, Any]],
    transitions: list[dict[str, Any]],
    limitations: list[str],
    current_read_model: str,
    current_acceptance: str,
) -> dict[str, Any]:
    return {
        "schema_version": PRESENTATION_SCHEMA,
        "feeds_inflation_score": False,
        "score_inputs_changed": False,
        "context_only": True,
        "country": "CA",
        "source": "accepted_overnight_evidence_snapshots",
        "current_read_model": current_read_model,
        "current_acceptance": current_acceptance,
        "history_state": history_state,
        "history_note": history_note,
        "limitations": limitations,
        "current": current,
        "trend": trend,
        "transitions": transitions,
    }


def _empty_presentation(limitations: list[str] | None = None) -> dict[str, Any]:
    lim = sorted(set(limitations or []))
    note = _HISTORY_NOTE_NONE
    if lim:
        note = note + " Limitations: " + "; ".join(lim) + "."
    current = _synthetic_unavailable_current()
    current["acceptance_state"] = "unavailable"
    current["preview"] = False
    return _presentation_shell(
        history_state="none",
        history_note=note,
        current=current,
        trend=[],
        transitions=[],
        limitations=lim,
        current_read_model="none",
        current_acceptance="unavailable",
    )


def _review_sort_key(review_id: str) -> int:
    return int(review_id.split("-", 1)[1])


def _trend_point(observation: dict[str, Any], projected: dict[str, Any]) -> dict[str, Any]:
    point: dict[str, Any] = {
        "observed_at": str(observation.get("observed_at") or ""),
        "source_id": str(observation.get("source_id") or ""),
        "run_id": str(observation.get("run_id") or ""),
        "review_id": str(observation.get("review_id") or ""),
        "source_kind": str(observation.get("source_kind") or _SOURCE_KIND),
        "direction": projected["direction"],
    }
    if projected.get("status"):
        point["status"] = projected["status"]
    if projected.get("staleness"):
        point["staleness"] = projected["staleness"]
    point["subcomponent_directions"] = dict(projected.get("subcomponent_directions") or {})
    if projected.get("largest_drivers"):
        point["largest_drivers"] = list(projected["largest_drivers"])
    ce = projected.get("channel_evidence")
    if isinstance(ce, dict) and ce:
        point["channel_evidence"] = ce
    if projected.get("futures_validity"):
        point["futures_validity"] = projected["futures_validity"]
    gap = projected.get("futures_history_gap")
    if isinstance(gap, dict):
        point["futures_history_gap"] = gap
    return point


def _as_of_from_observation(observation: dict[str, Any]) -> date | None:
    raw = str(observation.get("observed_at") or "")
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _history_gap_sentence(gap: dict[str, Any]) -> str:
    findings = gap.get("findings") if isinstance(gap.get("findings"), list) else []
    bits: list[str] = []
    for finding in findings:
        if not isinstance(finding, dict) or finding.get("valid"):
            continue
        symbol = finding.get("symbol") or "unknown contract"
        reason = finding.get("reason") or "invalid"
        final_trade = finding.get("final_trade_date") or "unknown"
        bits.append(f"{symbol} {reason} (final trade {final_trade})")
    detail = "; ".join(bits[:4]) if bits else "listed futures inputs failed the expiry check"
    source = gap.get("source_id") or "this run"
    return (
        f"History gap for {source}: stored Brent futures inputs were not active listed "
        f"maturities on this run ({detail}). The stored shock reading is not used. "
        "This is not a stable reading. No backfill was created."
    )


def apply_futures_history_guard(
    block: dict[str, Any],
    projected: dict[str, Any],
    observation: dict[str, Any],
) -> dict[str, Any]:
    """Drop contaminated oil from the presentation without rewriting the snapshot.

    Non-oil channels stay as stored. An invalid shock is unavailable, never stable,
    and the stored aggregate direction is not repeated.
    """
    as_of = _as_of_from_observation(observation)
    if as_of is None:
        projected = dict(projected)
        projected["futures_validity"] = "invalid"
        projected["direction"] = "UNAVAILABLE"
        subs = dict(projected.get("subcomponent_directions") or {})
        subs["shock_persistence"] = "UNAVAILABLE"
        projected["subcomponent_directions"] = subs
        projected["futures_history_gap"] = {
            "state": "invalid_futures_inputs",
            "reason": "missing_as_of",
            "source_id": observation.get("source_id"),
            "run_id": observation.get("run_id"),
            "review_id": observation.get("review_id"),
            "stored_direction_not_used": block.get("direction"),
            "findings": [],
        }
        return projected

    review = assess_stored_shock_inputs(block, as_of)
    if review["status"] == "no_futures_inputs":
        projected = dict(projected)
        projected["futures_validity"] = "no_futures_inputs"
        return projected
    if review["valid"]:
        projected = dict(projected)
        projected["futures_validity"] = "valid"
        return projected

    projected = dict(projected)
    projected["futures_validity"] = "invalid"
    projected["direction"] = "UNAVAILABLE"
    projected["status"] = "history_gap"
    subs = dict(projected.get("subcomponent_directions") or {})
    subs["shock_persistence"] = "UNAVAILABLE"
    projected["subcomponent_directions"] = subs
    drivers = [
        item
        for item in (projected.get("largest_drivers") or [])
        if isinstance(item, str) and not item.lower().startswith("brent")
    ]
    projected["largest_drivers"] = drivers
    evidence = dict(projected.get("channel_evidence") or {})
    original_shock: dict[str, Any] = {}
    if isinstance(block.get("channel_evidence"), dict):
        raw_shock = block["channel_evidence"].get("shock_persistence")
        if isinstance(raw_shock, dict):
            original_shock = raw_shock
    shock = dict(evidence.get("shock_persistence") or {})
    shock["direction"] = "UNAVAILABLE"
    shock["inputs"] = []
    shock["stored_inputs_rejected"] = True
    gap = {
        "state": "invalid_futures_inputs",
        "source_id": observation.get("source_id"),
        "run_id": observation.get("run_id"),
        "review_id": observation.get("review_id"),
        "as_of": as_of.isoformat(),
        "findings": review["findings"],
        "stored_direction_not_used": block.get("direction"),
        "stored_shock_direction_not_used": original_shock.get("direction"),
    }
    shock["note"] = _history_gap_sentence(gap)
    evidence["shock_persistence"] = shock
    projected["channel_evidence"] = evidence
    projected["futures_history_gap"] = gap
    reason = projected.get("reason")
    gap_reason = "invalid_futures_inputs"
    if reason:
        projected["reason"] = f"{reason}; {gap_reason}"
    else:
        projected["reason"] = gap_reason
    return projected


def _load_review_index(
    run_dir: Path, run_id: str, limitations: list[str]
) -> list[dict[str, Any]] | None:
    index_path = run_dir / "reviews" / "index.json"
    if not index_path.is_file():
        return None
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        limitations.append(f"invalid_review_index:{run_id}")
        return None
    if not isinstance(payload, dict):
        limitations.append(f"invalid_review_index:{run_id}")
        return None
    reviews = payload.get("reviews")
    if not isinstance(reviews, list):
        limitations.append(f"invalid_review_index:{run_id}")
        return None
    return reviews


def _choose_accepted_review_id(
    run_id: str,
    reviews: list[Any],
    limitations: list[str],
) -> tuple[str, dict[str, Any]] | None:
    accepted: list[tuple[int, str, dict[str, Any]]] = []
    for row in reviews:
        if not isinstance(row, dict):
            continue
        if row.get("status") != "accepted":
            continue
        review_id = row.get("review_id")
        if not isinstance(review_id, str):
            continue
        if not _REVIEW_ID_RE.match(review_id):
            limitations.append(f"malformed_review_id:{run_id}")
            continue
        accepted.append((_review_sort_key(review_id), review_id, row))
    if not accepted:
        return None
    _, review_id, row = max(accepted, key=lambda item: item[0])
    return review_id, row


def _observation_from_run(
    run_dir: Path,
    run_id: str,
    limitations: list[str],
) -> dict[str, Any] | None:
    reviews = _load_review_index(run_dir, run_id, limitations)
    if reviews is None:
        return None

    chosen = _choose_accepted_review_id(run_id, reviews, limitations)
    if chosen is None:
        return None
    review_id, review_row = chosen

    review_json_path = run_dir / "reviews" / review_id / "review.json"
    if review_json_path.is_file():
        try:
            review_meta = json.loads(review_json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            review_meta = None
        if isinstance(review_meta, dict):
            meta_status = review_meta.get("status")
            if isinstance(meta_status, str) and meta_status != "accepted":
                limitations.append(f"review_metadata_not_accepted:{run_id}/{review_id}")
                return None

    snapshot_path = run_dir / "reviews" / review_id / "evidence_snapshot.json"
    if not snapshot_path.is_file():
        limitations.append(f"missing_snapshot:{run_id}/{review_id}")
        return None

    try:
        raw_bytes = snapshot_path.read_bytes()
    except OSError:
        limitations.append(f"unreadable_snapshot:{run_id}/{review_id}")
        return None

    if b"canada_prima_pressure" not in raw_bytes:
        return None

    try:
        snapshot = json.loads(raw_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        limitations.append(f"unreadable_snapshot:{run_id}/{review_id}")
        return None

    if not isinstance(snapshot, dict):
        limitations.append(f"unreadable_snapshot:{run_id}/{review_id}")
        return None

    snap_run = snapshot.get("overnight_run_id")
    if snap_run is not None and snap_run != run_id:
        limitations.append(f"snapshot_run_mismatch:{run_id}/{review_id}")
        return None

    snap_review = snapshot.get("review_id")
    if snap_review is not None and snap_review != review_id:
        limitations.append(f"snapshot_review_mismatch:{run_id}/{review_id}")
        return None

    if "canada_prima_pressure" not in snapshot:
        return None
    block = snapshot.get("canada_prima_pressure")
    if block is None:
        return None

    if not isinstance(block, dict):
        block = {"direction": None, "reason": "prima_block_not_object"}

    observed_at: str | None = None
    as_of = snapshot.get("as_of")
    frozen_at = review_row.get("frozen_at")
    as_of_str = str(as_of).strip() if as_of is not None and str(as_of).strip() else None
    frozen_str = (
        str(frozen_at).strip() if frozen_at is not None and str(frozen_at).strip() else None
    )
    if as_of_str and frozen_str and as_of_str != frozen_str:
        limitations.append(f"observed_at_mismatch:{run_id}/{review_id}")
    if as_of_str:
        observed_at = as_of_str
    elif frozen_str:
        observed_at = frozen_str
    else:
        limitations.append(f"missing_observed_at:{run_id}/{review_id}")
        return None

    return {
        "observed_at": observed_at,
        "source_id": f"{run_id}/{review_id}",
        "source_kind": _SOURCE_KIND,
        "run_id": run_id,
        "review_id": review_id,
        "block": block,
    }


def _collect_observations(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    runs_root = root / "data" / "overnight" / "runs"
    if not runs_root.is_dir():
        return [], []

    limitations: list[str] = []
    observations: list[dict[str, Any]] = []

    for run_dir in sorted(runs_root.iterdir(), key=lambda p: p.name):
        if not run_dir.is_dir():
            continue
        run_id = run_dir.name
        observation = _observation_from_run(run_dir, run_id, limitations)
        if observation is not None:
            observations.append(observation)

    observations.sort(
        key=lambda row: (str(row.get("observed_at") or ""), str(row.get("source_id") or ""))
    )
    unique_limitations = sorted(set(limitations))
    return observations, unique_limitations


def _parse_instant(raw: Any) -> datetime | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _preview_exclusion_reason(code: str, *, has_accepted: bool) -> str:
    base = _PREVIEW_EXCLUSION_HUMAN.get(
        code,
        "A newer frozen overnight review was not shown; this card shows the last accepted reading.",
    )
    if has_accepted:
        return base
    return base.replace("the last accepted reading", "no accepted reading is on file")


def _attach_observation_identity(
    projected: dict[str, Any],
    observation: dict[str, Any],
    *,
    acceptance_state: str,
    preview: bool,
) -> dict[str, Any]:
    current = dict(projected)
    current.update(
        {
            "acceptance_state": acceptance_state,
            "observed_at": str(observation.get("observed_at") or ""),
            "source_id": str(observation.get("source_id") or ""),
            "run_id": str(observation.get("run_id") or ""),
            "review_id": str(observation.get("review_id") or ""),
            "preview": preview,
        }
    )
    return current


def _find_latest_frozen_candidate(
    root: Path,
    limitations: list[str],
) -> tuple[str, str, dict[str, Any], Path] | None:
    runs_root = root / "data" / "overnight" / "runs"
    if not runs_root.is_dir():
        return None
    best: tuple[datetime, str, str, dict[str, Any], Path] | None = None
    for run_dir in sorted(runs_root.iterdir(), key=lambda p: p.name):
        if not run_dir.is_dir():
            continue
        run_id = run_dir.name
        reviews = _load_review_index(run_dir, run_id, limitations)
        if not reviews:
            continue
        for row in reviews:
            if not isinstance(row, dict) or row.get("status") != "frozen":
                continue
            review_id = row.get("review_id")
            if not isinstance(review_id, str) or not _REVIEW_ID_RE.match(review_id):
                continue
            frozen_at = _parse_instant(row.get("frozen_at"))
            if frozen_at is None:
                continue
            candidate = (frozen_at, run_id, review_id, row, run_dir)
            if best is None or (frozen_at, run_id, review_id) > (best[0], best[1], best[2]):
                best = candidate
    if best is None:
        return None
    _, run_id, review_id, row, run_dir = best
    return run_id, review_id, row, run_dir


def _verify_launch_freeze_bindings(
    root: Path,
    run_id: str,
    review_id: str,
    packet_sha256: str,
) -> str | None:
    launches_root = root / "data" / "market_watch_launches"
    if not launches_root.is_dir():
        return None
    bound_dirs: list[Path] = []
    for launch_dir in launches_root.iterdir():
        if not launch_dir.is_dir():
            continue
        binding_path = launch_dir / "freeze_binding.json"
        if not binding_path.is_file():
            continue
        try:
            binding = json.loads(binding_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(binding, dict):
            continue
        if binding.get("overnight_run_id") != run_id or binding.get("review_id") != review_id:
            continue
        bound_dirs.append(launch_dir)
    if not bound_dirs:
        return None
    for launch_dir in bound_dirs:
        binding_path = launch_dir / "freeze_binding.json"
        try:
            binding = json.loads(binding_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if binding.get("packet_sha256") != packet_sha256:
            continue
        if not remote_freeze_verified(launch_dir):
            continue
        remote = load_remote_freeze(launch_dir)
        if not isinstance(remote, dict):
            continue
        if remote.get("packet_sha256") != packet_sha256:
            continue
        return None
    return "freeze_binding_mismatch"


def _verify_frozen_preview_candidate(
    root: Path,
    run_dir: Path,
    run_id: str,
    review_id: str,
    index_row: dict[str, Any],
    limitations: list[str],
) -> tuple[dict[str, Any] | None, str | None]:
    review_json_path = run_dir / "reviews" / review_id / "review.json"
    if not review_json_path.is_file():
        limitations.append(f"missing_review_json:{run_id}/{review_id}")
        return None, "unverified_frozen_review"
    try:
        review_meta = json.loads(review_json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        limitations.append(f"unreadable_review_json:{run_id}/{review_id}")
        return None, "unverified_frozen_review"
    if not isinstance(review_meta, dict):
        return None, "unverified_frozen_review"
    if review_meta.get("status") != "frozen":
        return None, "unverified_frozen_review"
    if review_meta.get("immutable") is not True:
        return None, "unverified_frozen_review"
    meta_review_id = review_meta.get("review_id")
    if meta_review_id is not None and meta_review_id != review_id:
        return None, "unverified_frozen_review"
    meta_run = review_meta.get("overnight_run_id")
    if meta_run is not None and meta_run != run_id:
        return None, "unverified_frozen_review"

    index_hash = index_row.get("packet_sha256")
    review_hash = review_meta.get("packet_sha256")
    if not isinstance(index_hash, str) or not index_hash.strip():
        return None, "unverified_frozen_review"
    if not isinstance(review_hash, str) or review_hash != index_hash:
        return None, "snapshot_hash_mismatch"

    snapshot_path = run_dir / "reviews" / review_id / "evidence_snapshot.json"
    if not snapshot_path.is_file():
        limitations.append(f"missing_snapshot:{run_id}/{review_id}")
        return None, "missing_snapshot"
    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        limitations.append(f"unreadable_snapshot:{run_id}/{review_id}")
        return None, "unverified_frozen_review"
    if not isinstance(snapshot, dict):
        return None, "unverified_frozen_review"
    if snapshot.get("type") != "OVERNIGHT_EVIDENCE_SNAPSHOT":
        return None, "unverified_frozen_review"
    if snapshot.get("overnight_run_id") != run_id:
        return None, "unverified_frozen_review"
    if snapshot.get("review_id") != review_id:
        return None, "unverified_frozen_review"
    block = snapshot.get("canada_prima_pressure")
    if not isinstance(block, dict):
        return None, "unverified_frozen_review"

    snap_hash = snapshot.get("packet_sha256")
    body_hash = sha256_json({k: v for k, v in snapshot.items() if k != "packet_sha256"})
    if not isinstance(snap_hash, str) or snap_hash != body_hash or snap_hash != index_hash:
        return None, "snapshot_hash_mismatch"

    as_of = snapshot.get("as_of")
    frozen_at = index_row.get("frozen_at")
    index_frozen = review_meta.get("frozen_at")
    as_of_str = str(as_of).strip() if as_of is not None and str(as_of).strip() else None
    frozen_str = (
        str(frozen_at).strip() if frozen_at is not None and str(frozen_at).strip() else None
    )
    review_frozen_str = (
        str(index_frozen).strip()
        if index_frozen is not None and str(index_frozen).strip()
        else None
    )
    if not as_of_str or not frozen_str or as_of_str != frozen_str:
        limitations.append(f"frozen_preview_misdated:{run_id}/{review_id}")
        return None, "observed_at_mismatch"
    if review_frozen_str and review_frozen_str != as_of_str:
        limitations.append(f"frozen_preview_misdated:{run_id}/{review_id}")
        return None, "observed_at_mismatch"

    if review_meta.get("starting_state_binding") != "canonical_file":
        return None, "unverified_frozen_review"
    if snapshot.get("starting_state_binding") != "canonical_file":
        return None, "unverified_frozen_review"

    for field in ("starting_trader_books_sha256", "starting_pm_books_sha256"):
        review_val = review_meta.get(field)
        snap_val = snapshot.get(field)
        if not isinstance(review_val, str) or not review_val.strip():
            return None, "unverified_frozen_review"
        if not isinstance(snap_val, str) or snap_val != review_val:
            return None, "unverified_frozen_review"

    binding_code = _verify_launch_freeze_bindings(root, run_id, review_id, index_hash)
    if binding_code:
        limitations.append(f"freeze_binding_mismatch:{run_id}/{review_id}")
        return None, binding_code

    return (
        {
            "observed_at": as_of_str,
            "source_id": f"{run_id}/{review_id}",
            "source_kind": _SOURCE_KIND,
            "run_id": run_id,
            "review_id": review_id,
            "block": block,
        },
        None,
    )


def build_presentation(root: Path) -> dict[str, Any]:
    """Build presentation from accepted overnight evidence snapshots (no proxy computation)."""
    runs_root = root / "data" / "overnight" / "runs"
    if not runs_root.is_dir():
        return _empty_presentation()

    observations, limitations = _collect_observations(root)

    trend: list[dict[str, Any]] = []
    projected_rows: list[dict[str, Any]] = []
    for observation in observations:
        block = observation.get("block")
        if not isinstance(block, dict):
            projected = _synthetic_unavailable_current()
            projected["reason"] = "observation_block_missing"
        else:
            projected = apply_futures_history_guard(block, project_block(block), observation)
        projected_rows.append(projected)
        trend.append(_trend_point(observation, projected))

    latest_accepted_at = (
        _parse_instant(observations[-1].get("observed_at")) if observations else None
    )
    frozen_candidate = _find_latest_frozen_candidate(root, limitations)
    preview_observation: dict[str, Any] | None = None
    preview_reject_code: str | None = None
    if frozen_candidate is not None:
        f_run_id, f_review_id, f_index_row, f_run_dir = frozen_candidate
        frozen_at = _parse_instant(f_index_row.get("frozen_at"))
        candidate_is_newer = latest_accepted_at is None or (
            frozen_at is not None and frozen_at > latest_accepted_at
        )
        if candidate_is_newer:
            verified_obs, reject_code = _verify_frozen_preview_candidate(
                root,
                f_run_dir,
                f_run_id,
                f_review_id,
                f_index_row,
                limitations,
            )
            if verified_obs is not None:
                preview_observation = verified_obs
            else:
                preview_reject_code = reject_code or "unverified_frozen_review"

    if preview_observation is not None:
        block = preview_observation.get("block")
        if isinstance(block, dict):
            projected = apply_futures_history_guard(
                block, project_block(block), preview_observation
            )
        else:
            projected = _synthetic_unavailable_current()
            projected["reason"] = "observation_block_missing"
        current = _attach_observation_identity(
            projected,
            preview_observation,
            acceptance_state="pending_trader_acceptance",
            preview=True,
        )
        current_read_model = "verified_frozen_stage_04_preview"
        current_acceptance = "pending_trader_acceptance"
    elif observations:
        current = _attach_observation_identity(
            projected_rows[-1],
            observations[-1],
            acceptance_state="accepted",
            preview=False,
        )
        current_read_model = "accepted_overnight_review"
        current_acceptance = "accepted"
        if preview_reject_code:
            current["preview_excluded"] = preview_reject_code
            current["preview_excluded_reason"] = _preview_exclusion_reason(
                preview_reject_code, has_accepted=True
            )
            limitations.append(f"preview_excluded:{preview_reject_code}")
    else:
        current = _synthetic_unavailable_current()
        current["acceptance_state"] = "unavailable"
        current["preview"] = False
        current_read_model = "none"
        current_acceptance = "unavailable"
        if preview_reject_code:
            current["preview_excluded"] = preview_reject_code
            current["preview_excluded_reason"] = _preview_exclusion_reason(
                preview_reject_code, has_accepted=False
            )
            limitations.append(f"preview_excluded:{preview_reject_code}")

    transitions: list[dict[str, Any]] = []
    for index in range(1, len(trend)):
        prev = trend[index - 1]
        curr = trend[index]
        transitions.append(
            {
                "from_observed_at": prev["observed_at"],
                "to_observed_at": curr["observed_at"],
                "from_direction": prev["direction"],
                "to_direction": curr["direction"],
                "label": f"{prev['direction']} → {curr['direction']}",
            }
        )

    if not observations:
        history_state = "none"
        history_note = _HISTORY_NOTE_NONE
    elif len(observations) == 1:
        history_state = "begins_here"
        history_note = _HISTORY_NOTE_ONE
    else:
        history_state = "trend"
        history_note = _HISTORY_NOTE_TREND

    limitations = sorted(set(limitations))
    if limitations:
        history_note = history_note + " Limitations: " + "; ".join(limitations) + "."

    return _presentation_shell(
        history_state=history_state,
        history_note=history_note,
        current=current,
        trend=trend,
        transitions=transitions,
        limitations=limitations,
        current_read_model=current_read_model,
        current_acceptance=current_acceptance,
    )
