"""Read-only Country Detail presentation for Canada Prima-pressure history."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from scripts.prima_pressure.contract import CHANNELS, DIRECTIONS, DISCLAIMER

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
) -> dict[str, Any]:
    return {
        "schema_version": PRESENTATION_SCHEMA,
        "feeds_inflation_score": False,
        "score_inputs_changed": False,
        "context_only": True,
        "country": "CA",
        "source": "accepted_overnight_evidence_snapshots",
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
    return _presentation_shell(
        history_state="none",
        history_note=note,
        current=_synthetic_unavailable_current(),
        trend=[],
        transitions=[],
        limitations=lim,
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
    return point


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


def build_presentation(root: Path) -> dict[str, Any]:
    """Build presentation from accepted overnight evidence snapshots (no proxy computation)."""
    runs_root = root / "data" / "overnight" / "runs"
    if not runs_root.is_dir():
        return _empty_presentation()

    observations, limitations = _collect_observations(root)

    if not observations:
        return _empty_presentation(limitations)

    trend: list[dict[str, Any]] = []
    projected_rows: list[dict[str, Any]] = []
    for observation in observations:
        block = observation.get("block")
        if not isinstance(block, dict):
            projected = _synthetic_unavailable_current()
            projected["reason"] = "observation_block_missing"
        else:
            projected = project_block(block)
        projected_rows.append(projected)
        trend.append(_trend_point(observation, projected))

    current = projected_rows[-1]
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

    if len(observations) == 1:
        history_state = "begins_here"
        history_note = _HISTORY_NOTE_ONE
    else:
        history_state = "trend"
        history_note = _HISTORY_NOTE_TREND

    if limitations:
        history_note = history_note + " Limitations: " + "; ".join(limitations) + "."

    return _presentation_shell(
        history_state=history_state,
        history_note=history_note,
        current=current,
        trend=trend,
        transitions=transitions,
        limitations=limitations,
    )
