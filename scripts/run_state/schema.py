"""Canonical run-state document validators and JSON hashing."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Dict, List, Mapping, Optional, Union

SCHEMA_SERIES_DEFINITION = "series-definition/1"
SCHEMA_RELEASE_EXPECTATION = "release-expectation/1"
SCHEMA_ACQUISITION_ATTEMPT = "acquisition-attempt/1"
SCHEMA_SCHEDULER_EVENT = "scheduler-event/1"
SCHEMA_OBSERVATION_VERSION = "observation-version/1"
SCHEMA_SERIES_RUN_STATE = "series-run-state/1"
SCHEMA_EVIDENCE_ITEM = "evidence-item/1"
SCHEMA_RUN_MANIFEST = "run-manifest/1"
SCHEMA_QUALITY_POLICY = "quality-policy/1"


class ContractError(ValueError):
    """Raised when a document violates the frozen run-state contract."""


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_json(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def _require_str(doc: Mapping[str, Any], key: str, label: str) -> str:
    if key not in doc:
        raise ContractError(f"{label}: missing required field {key!r}")
    val = doc[key]
    if not isinstance(val, str):
        raise ContractError(f"{label}: {key!r} must be a string")
    if val == "" and key in ("publisher", "provider"):
        raise ContractError(f"{label}: {key!r} must be non-empty")
    return val


def _require_enum(doc: Mapping[str, Any], key: str, allowed: frozenset, label: str) -> str:
    if key not in doc:
        raise ContractError(f"{label}: missing required field {key!r}")
    val = doc[key]
    if val not in allowed:
        raise ContractError(f"{label}: unknown {key!r} value {val!r}")
    return val


def definition_id_from_body(body: Mapping[str, Any]) -> str:
    payload = {k: v for k, v in body.items() if k != "definition_id"}
    return "sd_" + sha256_json(payload)[:20]


def expectation_id_from_body(body: Mapping[str, Any]) -> str:
    payload = {k: v for k, v in body.items() if k != "expectation_id"}
    return "re_" + sha256_json(payload)[:20]


def validate_series_definition(doc: Mapping[str, Any]) -> Dict[str, Any]:
    label = "SeriesDefinition"
    out = dict(doc)
    sv = _require_str(out, "schema_version", label)
    if sv != SCHEMA_SERIES_DEFINITION:
        raise ContractError(f"{label}: schema_version must be {SCHEMA_SERIES_DEFINITION!r}")
    _require_str(out, "definition_id", label)
    _require_str(out, "publisher", label)
    _require_str(out, "provider", label)
    _require_enum(out, "calendar_status", frozenset({"known", "unknown"}), label)
    if not isinstance(out.get("trade_critical"), bool):
        raise ContractError(f"{label}: trade_critical must be bool")
    weight = out.get("weight")
    if not isinstance(weight, (int, float)) or isinstance(weight, bool):
        raise ContractError(f"{label}: weight must be a number")
    _require_str(out, "role", label)
    _require_str(out, "units", label)
    _require_str(out, "transform", label)
    _require_str(out, "policy_version", label)
    if out["policy_version"] != SCHEMA_QUALITY_POLICY:
        raise ContractError(f"{label}: policy_version must be {SCHEMA_QUALITY_POLICY!r}")
    _require_str(out, "series_id", label)
    _require_str(out, "country", label)
    _require_str(out, "source_authority", label)
    fallbacks = out.get("fallback_series_ids")
    if not isinstance(fallbacks, list):
        raise ContractError(f"{label}: fallback_series_ids must be a list")
    for item in fallbacks:
        if not isinstance(item, str):
            raise ContractError(f"{label}: fallback_series_ids entries must be strings")
    if "id" in out and not isinstance(out["id"], str):
        raise ContractError(f"{label}: id must be a string when present")
    expected_def_id = definition_id_from_body(out)
    if out["definition_id"] != expected_def_id:
        raise ContractError(f"{label}: definition_id does not match canonical hash")
    return out


def validate_release_expectation(doc: Mapping[str, Any]) -> Dict[str, Any]:
    label = "ReleaseExpectation"
    out = dict(doc)
    sv = _require_str(out, "schema_version", label)
    if sv != SCHEMA_RELEASE_EXPECTATION:
        raise ContractError(f"{label}: schema_version must be {SCHEMA_RELEASE_EXPECTATION!r}")
    _require_str(out, "expectation_id", label)
    _require_str(out, "run_id", label)
    _require_str(out, "series_id", label)
    cal = _require_enum(out, "calendar_status", frozenset({"known", "unknown"}), label)
    flag = out.get("scheduled_release_occurred_by_cutoff", "__missing__")
    if cal == "unknown":
        if flag is not None:
            raise ContractError(
                f"{label}: unknown calendar requires scheduled_release_occurred_by_cutoff null"
            )
    else:
        if not isinstance(flag, bool):
            raise ContractError(
                f"{label}: known calendar requires scheduled_release_occurred_by_cutoff bool"
            )
    if not isinstance(out.get("expectation_satisfied_by_verified_evidence"), bool):
        raise ContractError(f"{label}: expectation_satisfied_by_verified_evidence must be bool")
    _require_str(out, "cutoff_at", label)
    era = out.get("expected_release_at")
    if era is not None and not isinstance(era, str):
        raise ContractError(f"{label}: expected_release_at must be string or null")
    period = out.get("expected_period")
    if period is not None and not isinstance(period, str):
        raise ContractError(f"{label}: expected_period must be string or null")
    sat_id = out.get("satisfaction_observation_id")
    if sat_id is not None and not isinstance(sat_id, str):
        raise ContractError(f"{label}: satisfaction_observation_id must be string or null")
    expected_eid = expectation_id_from_body(out)
    if out["expectation_id"] != expected_eid:
        raise ContractError(f"{label}: expectation_id does not match canonical hash")
    return out


_ACQUISITION_RESULTS = frozenset(
    {
        "success",
        "timeout",
        "http_404",
        "http_429",
        "http_5xx",
        "schema_drift",
        "transport_error",
        "license_gap",
        "empty_parse",
    }
)


def validate_acquisition_attempt(doc: Mapping[str, Any]) -> Dict[str, Any]:
    label = "AcquisitionAttempt"
    out = dict(doc)
    sv = _require_str(out, "schema_version", label)
    if sv != SCHEMA_ACQUISITION_ATTEMPT:
        raise ContractError(f"{label}: schema_version must be {SCHEMA_ACQUISITION_ATTEMPT!r}")
    kind = out.get("kind")
    if kind in ("skipped_admission", "skipped_retry"):
        raise ContractError(f"{label}: kind {kind!r} is not an acquisition attempt")
    _require_enum(out, "kind", frozenset({"primary", "retry"}), label)
    result = out.get("result")
    if result == "budget_deferred":
        raise ContractError(f"{label}: budget_deferred is not a valid attempt result")
    _require_enum(out, "result", _ACQUISITION_RESULTS, label)
    for clock in ("queued_at", "started_at", "ended_at", "deadline_at"):
        if clock not in out or not isinstance(out[clock], str) or out[clock] == "":
            raise ContractError(f"{label}: missing or invalid {clock!r}")
    elapsed = out.get("elapsed_ms")
    if not isinstance(elapsed, int) or isinstance(elapsed, bool) or elapsed < 0:
        raise ContractError(f"{label}: elapsed_ms must be int >= 0")
    ordinal = out.get("ordinal")
    if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 1:
        raise ContractError(f"{label}: ordinal must be int >= 1")
    return out


def validate_scheduler_event(doc: Mapping[str, Any]) -> Dict[str, Any]:
    label = "SchedulerEvent"
    out = dict(doc)
    sv = _require_str(out, "schema_version", label)
    if sv != SCHEMA_SCHEDULER_EVENT:
        raise ContractError(f"{label}: schema_version must be {SCHEMA_SCHEDULER_EVENT!r}")
    kind = _require_enum(out, "kind", frozenset({"skipped_admission", "skipped_retry"}), label)
    if kind == "skipped_retry":
        rid = out.get("related_attempt_id")
        if not isinstance(rid, str) or rid == "":
            raise ContractError(f"{label}: skipped_retry requires related_attempt_id")
    if kind == "skipped_admission" and "started_at" in out:
        raise ContractError(f"{label}: skipped_admission must not include started_at")
    return out


def validate_observation_version(doc: Mapping[str, Any]) -> Dict[str, Any]:
    label = "ObservationVersion"
    out = dict(doc)
    sv = _require_str(out, "schema_version", label)
    if sv != SCHEMA_OBSERVATION_VERSION:
        raise ContractError(f"{label}: schema_version must be {SCHEMA_OBSERVATION_VERSION!r}")
    _require_enum(
        out,
        "revision_status",
        frozenset({"flash", "preliminary", "final", "revised", "unspecified"}),
        label,
    )
    unc = _require_enum(
        out,
        "publication_time_uncertainty",
        frozenset({"exact", "date_only", "unknown"}),
        label,
    )
    pub = out.get("publication_time")
    if unc == "unknown":
        if pub is not None:
            raise ContractError(f"{label}: unknown uncertainty requires publication_time null")
    elif unc == "exact":
        if not isinstance(pub, str) or pub == "":
            raise ContractError(f"{label}: exact uncertainty requires publication_time")
    elif unc == "date_only":
        if not isinstance(pub, str) or pub == "":
            raise ContractError(f"{label}: date_only uncertainty requires publication_time")
        if "T" in pub:
            raise ContractError(f"{label}: date_only publication_time must not contain time component")
    value = out.get("value")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ContractError(f"{label}: value must be int or float")
    if not math.isfinite(float(value)):
        raise ContractError(f"{label}: value must be finite")
    _require_str(out, "units", label)
    _require_str(out, "transformation", label)
    return out


_CARRY_FORWARD_REASONS = frozenset(
    {
        "old_but_current",
        "old_after_failed_check",
        "overdue_unverified",
        "unknown_calendar",
    }
)


def validate_series_run_state(doc: Mapping[str, Any]) -> Dict[str, Any]:
    label = "SeriesRunState"
    out = dict(doc)
    sv = _require_str(out, "schema_version", label)
    if sv != SCHEMA_SERIES_RUN_STATE:
        raise ContractError(f"{label}: schema_version must be {SCHEMA_SERIES_RUN_STATE!r}")
    run_id = _require_str(out, "run_id", label)
    series_id = _require_str(out, "series_id", label)
    state_id = _require_str(out, "state_id", label)
    if state_id != f"{run_id}:{series_id}":
        raise ContractError(f"{label}: state_id must equal run_id:series_id")
    reason = out.get("carry_forward_reason")
    if reason is not None and reason not in _CARRY_FORWARD_REASONS:
        raise ContractError(f"{label}: unknown carry_forward_reason {reason!r}")
    for list_key in ("attempt_ids", "scheduler_event_ids"):
        lst = out.get(list_key)
        if not isinstance(lst, list):
            raise ContractError(f"{label}: {list_key} must be a list")
        for item in lst:
            if not isinstance(item, str):
                raise ContractError(f"{label}: {list_key} entries must be strings")
    _require_str(out, "policy_version", label)
    _require_str(out, "state_sha256", label)
    return out


def validate_evidence_item(doc: Mapping[str, Any]) -> Dict[str, Any]:
    label = "EvidenceItem"
    out = dict(doc)
    sv = _require_str(out, "schema_version", label)
    if sv != SCHEMA_EVIDENCE_ITEM:
        raise ContractError(f"{label}: schema_version must be {SCHEMA_EVIDENCE_ITEM!r}")
    prov = out.get("provenance")
    if not isinstance(prov, dict):
        raise ContractError(f"{label}: provenance must be a dict")
    for pk in ("source_name", "acquired_at", "method"):
        val = prov.get(pk)
        if not isinstance(val, str) or val == "":
            raise ContractError(f"{label}: provenance.{pk} must be a non-empty string")
    if "url" in out and out["url"] is not None and not isinstance(out["url"], str):
        raise ContractError(f"{label}: url must be string or null when present")
    _require_enum(
        out,
        "timestamp_uncertainty",
        frozenset({"exact", "date_only", "unknown"}),
        label,
    )
    disp = _require_enum(out, "disposition", frozenset({"accepted", "rendered", "excluded"}), label)
    if disp == "excluded":
        er = out.get("exclusion_reason")
        if not isinstance(er, str) or er == "":
            raise ContractError(f"{label}: excluded disposition requires non-empty exclusion_reason")
    return out


def validate_run_manifest(doc: Mapping[str, Any]) -> Dict[str, Any]:
    label = "RunManifest"
    out = dict(doc)
    sv = _require_str(out, "schema_version", label)
    if sv != SCHEMA_RUN_MANIFEST:
        raise ContractError(f"{label}: schema_version must be {SCHEMA_RUN_MANIFEST!r}")
    mode = out.get("publication_mode")
    if mode != "offline":
        raise ContractError(f"{label}: publication_mode must be offline")
    cutoff = _require_str(out, "cutoff_at", label)
    freeze = _require_str(out, "freeze_cutoff", label)
    _require_str(out, "policy_version", label)
    _require_str(out, "score_state_sha256", label)
    coverage = out.get("coverage")
    if not isinstance(coverage, dict):
        raise ContractError(f"{label}: coverage must be a dict")
    for ck in ("due", "satisfied", "attempted_failed", "never_attempted", "unknown_calendar"):
        val = coverage.get(ck)
        if not isinstance(val, int) or isinstance(val, bool) or val < 0:
            raise ContractError(f"{label}: coverage.{ck} must be int >= 0")
    budget = out.get("budget")
    if not isinstance(budget, dict):
        raise ContractError(f"{label}: budget must be a dict")
    for bk in ("protected_slots", "consumed_slots", "remaining_slots"):
        if bk not in budget:
            raise ContractError(f"{label}: budget missing {bk!r}")
    gate = out.get("gate_bound_to")
    if not isinstance(gate, dict):
        raise ContractError(f"{label}: gate_bound_to must be a dict")
    if gate.get("cutoff_at") != cutoff:
        raise ContractError(f"{label}: gate_bound_to.cutoff_at must equal cutoff_at")
    if gate.get("freeze_cutoff") != freeze:
        raise ContractError(f"{label}: gate_bound_to.freeze_cutoff must equal freeze_cutoff")
    state_ids = out.get("state_ids")
    if not isinstance(state_ids, list):
        raise ContractError(f"{label}: state_ids must be a list")
    for sid in state_ids:
        if not isinstance(sid, str):
            raise ContractError(f"{label}: state_ids entries must be strings")
    return out


def validate_quality_policy(doc: Mapping[str, Any]) -> Dict[str, Any]:
    label = "QualityPolicy"
    out = dict(doc)
    sv = _require_str(out, "schema_version", label)
    if sv != SCHEMA_QUALITY_POLICY:
        raise ContractError(f"{label}: schema_version must be {SCHEMA_QUALITY_POLICY!r}")
    return out
