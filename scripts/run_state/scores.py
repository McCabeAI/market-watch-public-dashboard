"""Bind temperature component levels to observation versions."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional

from scripts.run_state.schema import sha256_json
from scripts.temperature_level import component_level


class ScoreConflict(ValueError):
    """Two score bindings disagree for the same observation."""


def _default_score_fn(value: float, spec: Mapping[str, Any], cal: Mapping[str, Any]) -> float:
    return component_level(value, dict(spec), dict(cal))


def _usable_for_score(obs: Mapping[str, Any]) -> bool:
    if obs.get("score") is False:
        return False
    if obs.get("use_for_score") is False:
        return False
    return True


def bind_scores(*, observations: List[dict], score_fn: Optional[Callable[..., float]] = None) -> dict:
    scorer = score_fn or _default_score_fn
    levels_by_observation: Dict[str, tuple[str, float]] = {}
    components: List[Dict[str, Any]] = []

    for obs in observations:
        if not _usable_for_score(obs):
            continue
        observation_id = obs.get("observation_id")
        series_id = obs.get("series_id")
        if not isinstance(observation_id, str) or not isinstance(series_id, str):
            raise ValueError("scoring observation requires observation_id and series_id")
        value = obs.get("value")
        spec = obs.get("component_spec")
        cal = obs.get("calibration")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError("scoring observation requires numeric value")
        if not isinstance(spec, dict) or not isinstance(cal, dict):
            raise ValueError("scoring observation requires component_spec and calibration dicts")
        level = float(scorer(float(value), spec, cal))
        prior = levels_by_observation.get(observation_id)
        if prior is not None and prior[1] != level:
            raise ScoreConflict(f"conflicting levels for observation {observation_id}")
        levels_by_observation[observation_id] = (series_id, level)
        components.append(
            {
                "series_id": series_id,
                "observation_id": observation_id,
                "level": level,
            }
        )

    components.sort(key=lambda row: (row["series_id"], row["observation_id"]))
    return {
        "schema": "score-binding/1",
        "components": components,
        "score_state_sha256": sha256_json(components),
    }
