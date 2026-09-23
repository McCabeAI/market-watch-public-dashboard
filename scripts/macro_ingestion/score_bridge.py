"""Recompute temperature LEVEL scores after verified macro observations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.temperature_level import (
    CALIBRATION_PATH,
    STATE_PATH,
    build_score_state,
    compute_state,
    load_calibration,
    write_state,
)

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class ScoreRecomputeResult:
    ok: bool
    score_recompute: str | None = None
    state: dict[str, Any] | None = None


def recompute_scores_after_observation(
    *,
    persist_scores: bool = False,
    persist_history: bool = False,
    calibration_path: Path = CALIBRATION_PATH,
) -> ScoreRecomputeResult:
    """
    Recompute public score state from committed history + calibration.

    Context rows never affect weights. Calibration bytes are never modified here.
    History persistence is opt-in for integrators; default False for shared platform runs.
    """
    if persist_history:
        return ScoreRecomputeResult(
            ok=False,
            score_recompute="blocked_history_persist_disabled_on_platform",
        )

    cal_before = calibration_path.read_bytes()
    cal = load_calibration(calibration_path)
    computed = compute_state(cal)
    state = build_score_state(cal, computed)

    if persist_scores:
        cal_after = calibration_path.read_bytes()
        if cal_after != cal_before:
            return ScoreRecomputeResult(
                ok=False,
                score_recompute="blocked_calibration_lock",
            )
        write_state(STATE_PATH)
        return ScoreRecomputeResult(ok=True, state=state)

    return ScoreRecomputeResult(ok=True, state=state)
