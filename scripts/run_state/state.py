"""Assemble canonical SeriesRunState documents."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from scripts.run_state.schema import (
    SCHEMA_SERIES_RUN_STATE,
    ContractError,
    expectation_id_from_body,
    sha256_json,
    validate_release_expectation,
    validate_series_run_state,
)


def _derive_carry_forward_reason(
    expectation: Mapping[str, Any],
    *,
    attempt_ids: List[str],
    selected_observation_id: Optional[str],
    prior_observation_id: Optional[str],
) -> Optional[str]:
    if expectation.get("calendar_status") == "unknown":
        return "unknown_calendar"
    occurred = expectation.get("scheduled_release_occurred_by_cutoff")
    satisfied = expectation.get("expectation_satisfied_by_verified_evidence")
    if occurred is True and satisfied is True:
        return None
    if occurred is True and not satisfied:
        return "overdue_unverified"
    if occurred is False and attempt_ids and selected_observation_id is None and prior_observation_id:
        return "old_after_failed_check"
    if occurred is False and (selected_observation_id or prior_observation_id):
        return "old_but_current"
    if occurred is False and not selected_observation_id and not prior_observation_id:
        return None
    return None


def assemble_series_run_state(
    *,
    run_id: str,
    series_id: str,
    definition_id: str,
    expectation: Mapping[str, Any],
    attempt_ids: List[str],
    scheduler_event_ids: List[str],
    selected_observation_id: Optional[str],
    prior_observation_id: Optional[str],
    policy_version: str = "quality-policy/1",
    trade_critical: bool = False,
    country: Optional[str] = None,
    score_input_observation_id: Optional[str] = None,
    role: Optional[str] = None,
    weight: Optional[float] = None,
) -> Dict[str, Any]:
    validate_release_expectation(expectation)
    derived_score_input = selected_observation_id if selected_observation_id else prior_observation_id
    if score_input_observation_id is not None and score_input_observation_id != derived_score_input:
        raise ContractError(
            "score_input_observation_id must equal selected_observation_id or prior_observation_id"
        )
    score_input = derived_score_input

    carry = _derive_carry_forward_reason(
        expectation,
        attempt_ids=attempt_ids,
        selected_observation_id=selected_observation_id,
        prior_observation_id=prior_observation_id,
    )

    exp_id = expectation.get("expectation_id")
    if not isinstance(exp_id, str) or exp_id == "":
        exp_id = expectation_id_from_body(dict(expectation))

    state_id = f"{run_id}:{series_id}"
    body: Dict[str, Any] = {
        "schema_version": SCHEMA_SERIES_RUN_STATE,
        "run_id": run_id,
        "series_id": series_id,
        "state_id": state_id,
        "definition_id": definition_id,
        "expectation_id": exp_id,
        "attempt_ids": list(attempt_ids),
        "scheduler_event_ids": list(scheduler_event_ids),
        "selected_observation_id": selected_observation_id,
        "prior_observation_id": prior_observation_id,
        "score_input_observation_id": score_input,
        "carry_forward_reason": carry,
        "policy_version": policy_version,
        "trade_critical": trade_critical,
    }
    if country is not None:
        body["country"] = country
    if role is not None:
        body["role"] = role
    if weight is not None:
        body["weight"] = weight

    body["state_sha256"] = sha256_json({k: v for k, v in body.items() if k != "state_sha256"})
    return validate_series_run_state(body)
