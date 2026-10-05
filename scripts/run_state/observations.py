"""Append-only ObservationVersion store (observation-version/1)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from scripts.run_state.schema import (
    SCHEMA_OBSERVATION_VERSION,
    ContractError,
    sha256_json,
    validate_observation_version,
)

_REVISION_PREFERENCE = (
    "final",
    "revised",
    "preliminary",
    "flash",
    "unspecified",
)

_Identity = Tuple[str, str, str, str]


class ObservationConflict(ContractError):
    """Same observation identity with incompatible body."""


def _require_identity_field(doc: Dict[str, Any], key: str) -> str:
    val = doc.get(key)
    if not isinstance(val, str) or val == "":
        raise ContractError(f"ObservationVersion: missing or invalid {key!r}")
    return val


def observation_id_from_body(doc: Dict[str, Any]) -> str:
    payload = {
        "period": doc["period"],
        "raw_sha256": doc["raw_sha256"],
        "series_id": doc["series_id"],
        "transformation": doc["transformation"],
        "value": doc["value"],
    }
    return "ov_" + sha256_json(payload)[:20]


def _identity(doc: Dict[str, Any]) -> _Identity:
    return (
        _require_identity_field(doc, "series_id"),
        _require_identity_field(doc, "period"),
        _require_identity_field(doc, "transformation"),
        _require_identity_field(doc, "raw_sha256"),
    )


def _prepare_for_validation(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(doc)
    _require_identity_field(out, "series_id")
    _require_identity_field(out, "period")
    _require_identity_field(out, "transformation")
    _require_identity_field(out, "raw_sha256")

    if "schema_version" not in out:
        out["schema_version"] = SCHEMA_OBSERVATION_VERSION

    pub = out.get("publication_time")
    if pub is None:
        out["publication_time"] = None
        out["publication_time_uncertainty"] = "unknown"
    elif "publication_time_uncertainty" not in out:
        if isinstance(pub, str) and "T" in pub:
            out["publication_time_uncertainty"] = "exact"
        elif isinstance(pub, str):
            out["publication_time_uncertainty"] = "date_only"
        else:
            raise ContractError("ObservationVersion: publication_time must be string or null")

    validated = validate_observation_version(out)
    expected_id = observation_id_from_body(validated)
    supplied = validated.get("observation_id")
    if supplied is not None:
        if not isinstance(supplied, str) or supplied == "":
            raise ContractError("ObservationVersion: observation_id must be a non-empty string")
        if supplied != expected_id:
            raise ContractError("ObservationVersion: observation_id does not match canonical hash")
    else:
        validated["observation_id"] = expected_id

    return validated


class ObservationStore:
    def __init__(self) -> None:
        self._by_id: Dict[str, Dict[str, Any]] = {}
        self._by_identity: Dict[_Identity, str] = {}
        self._insertion_order: List[str] = []

    def append(self, doc: dict) -> dict:
        prepared = _prepare_for_validation(doc)
        ident = _identity(prepared)
        obs_id = prepared["observation_id"]

        existing_id = self._by_identity.get(ident)
        if existing_id is not None:
            stored = self._by_id[existing_id]
            for field in ("value", "units", "revision_status"):
                if prepared[field] != stored[field]:
                    raise ObservationConflict(
                        f"ObservationVersion: identity {ident!r} conflicts on {field!r}"
                    )
            return deepcopy(stored)

        stored = deepcopy(prepared)
        self._by_id[obs_id] = stored
        self._by_identity[ident] = obs_id
        self._insertion_order.append(obs_id)
        return deepcopy(stored)

    def get(self, observation_id: str) -> dict | None:
        row = self._by_id.get(observation_id)
        if row is None:
            return None
        return deepcopy(row)

    def reject_transform_mismatch(
        self,
        doc: dict,
        *,
        expected_units: str,
        expected_transformation: str,
    ) -> None:
        units = doc.get("units")
        transformation = doc.get("transformation")
        if units != expected_units:
            raise ContractError(
                f"ObservationVersion: units {units!r} does not match expected {expected_units!r}"
            )
        if transformation != expected_transformation:
            raise ContractError(
                "ObservationVersion: transformation "
                f"{transformation!r} does not match expected {expected_transformation!r}"
            )

    def versions_for(self, series_id: str, period: str) -> list[dict]:
        out: List[dict] = []
        for obs_id in self._insertion_order:
            row = self._by_id[obs_id]
            if row["series_id"] == series_id and row["period"] == period:
                out.append(deepcopy(row))
        return out

    def select_preferred(self, series_id: str, period: str) -> dict | None:
        versions = self.versions_for(series_id, period)
        if not versions:
            return None
        rank = {status: i for i, status in enumerate(_REVISION_PREFERENCE)}
        best = versions[0]
        best_rank = rank.get(best["revision_status"], len(_REVISION_PREFERENCE))
        for row in versions[1:]:
            r = rank.get(row["revision_status"], len(_REVISION_PREFERENCE))
            if r < best_rank:
                best = row
                best_rank = r
        return deepcopy(best)
