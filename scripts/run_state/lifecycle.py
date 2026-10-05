"""Checkpoint store for resumable run lifecycle (in-memory)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from scripts.run_state.schema import sha256_json

CHECKPOINTS = (
    "series_plan",
    "admission",
    "attempts",
    "observations",
    "scores",
    "gate",
    "freeze",
    "candidate_bundle",
    "publication",
    "deploy_ack",
)

_CHECKPOINT_SET = frozenset(CHECKPOINTS)


class CheckpointStore:
    def __init__(self) -> None:
        self._checkpoints: Dict[str, Dict[str, Any]] = {}

    def _record_view(self, name: str, stored: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": name,
            "input_sha256": stored["input_sha256"],
            "output": stored["output"],
            "generation": stored["generation"],
            "output_sha256": sha256_json(stored["output"]),
        }

    def commit(
        self,
        name: str,
        *,
        input_sha256: str,
        output: dict,
        expected_generation: int,
    ) -> dict:
        if name not in _CHECKPOINT_SET:
            raise KeyError(name)

        stored = self._checkpoints.get(name)
        if stored is not None:
            if expected_generation != stored["generation"]:
                raise RuntimeError("cas_conflict")
            if input_sha256 == stored["input_sha256"]:
                return self._record_view(name, stored)
            raise RuntimeError("cas_conflict")

        if expected_generation != 0:
            raise RuntimeError("cas_conflict")

        envelope_ms = output.get("timeout_envelope_ms")
        self._checkpoints[name] = {
            "input_sha256": input_sha256,
            "output": dict(output),
            "generation": 0,
            "timeout_envelope_ms": envelope_ms,
        }
        return self._record_view(name, self._checkpoints[name])

    def read(self, name: str) -> dict | None:
        stored = self._checkpoints.get(name)
        if stored is None:
            return None
        return self._record_view(name, stored)

    def resume(self, name: str, *, input_sha256: str) -> dict | None:
        stored = self._checkpoints.get(name)
        if stored is None:
            return None
        if stored["input_sha256"] != input_sha256:
            return None
        return self._record_view(name, stored)
