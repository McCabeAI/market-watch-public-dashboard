"""Read-only Country Detail presentation for Canada Prima-pressure history."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.prima_pressure.contract import CHANNELS, DIRECTIONS, DISCLAIMER

HISTORY_REL = Path("data/prima_pressure/canada_history.json")
PRESENTATION_SCHEMA = "canada_prima_pressure_presentation_v1"
HISTORY_SCHEMA = "canada_prima_pressure_history_v1"

_HISTORY_NOTE_NONE = (
    "History begins here: no stored Market Watch Prima observations have been recorded yet."
)
_HISTORY_NOTE_ONE = (
    "History begins here: one stored Market Watch observation is on file; "
    "not enough runs to show a direction transition."
)


def _history_path(root: Path) -> Path:
    return root / HISTORY_REL


def _empty_history() -> dict[str, Any]:
    return {
        "schema_version": HISTORY_SCHEMA,
        "country": "CA",
        "note": (
            "Append-only index of compact canada_prima_pressure blocks copied from Market Watch "
            "evidence freezes. Rows are written only when a freeze persists a block. "
            "This file does not backfill dates that were not stored."
        ),
        "observations": [],
    }


def _load_history(root: Path) -> tuple[dict[str, Any] | None, str | None]:
    path = _history_path(root)
    if not path.is_file():
        return None, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return None, f"invalid_history_json: {exc}"
    if not isinstance(payload, dict):
        return None, "invalid_history_shape: root must be an object"
    if payload.get("schema_version") != HISTORY_SCHEMA:
        return None, f"invalid_history_schema: {payload.get('schema_version')}"
    observations = payload.get("observations")
    if not isinstance(observations, list):
        return None, "invalid_history_observations: expected a list"
    return payload, None


def _sorted_observations(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [row for row in observations if isinstance(row, dict)]
    return sorted(
        rows,
        key=lambda row: (str(row.get("observed_at") or ""), str(row.get("source_id") or "")),
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

    return {
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
) -> dict[str, Any]:
    return {
        "schema_version": PRESENTATION_SCHEMA,
        "feeds_inflation_score": False,
        "score_inputs_changed": False,
        "context_only": True,
        "country": "CA",
        "history_state": history_state,
        "history_note": history_note,
        "current": current,
        "trend": trend,
        "transitions": transitions,
    }


def _trend_point(observation: dict[str, Any], projected: dict[str, Any]) -> dict[str, Any]:
    point: dict[str, Any] = {
        "observed_at": str(observation.get("observed_at") or ""),
        "source_id": str(observation.get("source_id") or ""),
        "direction": projected["direction"],
    }
    if projected.get("status"):
        point["status"] = projected["status"]
    if projected.get("staleness"):
        point["staleness"] = projected["staleness"]
    return point


def build_presentation(root: Path) -> dict[str, Any]:
    """Build presentation from persisted history only (no proxy computation)."""
    payload, error = _load_history(root)
    if error:
        current = _synthetic_unavailable_current()
        current["reason"] = error
        return _presentation_shell(
            history_state="unavailable",
            history_note=_HISTORY_NOTE_NONE,
            current=current,
            trend=[],
            transitions=[],
        )

    observations = _sorted_observations((payload or _empty_history()).get("observations") or [])
    if not observations:
        return _presentation_shell(
            history_state="none",
            history_note=_HISTORY_NOTE_NONE,
            current=_synthetic_unavailable_current(),
            trend=[],
            transitions=[],
        )

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
        history_note = (
            "Stored Market Watch Prima observations are listed in time order; "
            "transitions reflect consecutive stored runs only."
        )

    return _presentation_shell(
        history_state=history_state,
        history_note=history_note,
        current=current,
        trend=trend,
        transitions=transitions,
    )


def record_observation(
    state_root: Path,
    block: dict,
    *,
    observed_at: str,
    source_id: str,
    source_kind: str,
) -> dict[str, Any]:
    """Append one frozen compact block to the history file (idempotent on source_id)."""
    path = state_root / HISTORY_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != HISTORY_SCHEMA:
            payload = _empty_history()
    else:
        payload = _empty_history()

    observations = payload.get("observations")
    if not isinstance(observations, list):
        observations = []
        payload["observations"] = observations

    for row in observations:
        if isinstance(row, dict) and str(row.get("source_id") or "") == source_id:
            return payload

    observations.append(
        {
            "observed_at": observed_at,
            "source_id": source_id,
            "source_kind": source_kind,
            "block": block,
        }
    )
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload
