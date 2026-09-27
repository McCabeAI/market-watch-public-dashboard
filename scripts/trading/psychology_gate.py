"""Mandatory psychology self-checks. They never block de-risking."""

from __future__ import annotations

from typing import Any

from scripts.trading.constants import EXPANDING_ACTIONS, PM_IDS
from scripts.trading.errors import SchemaError
from scripts.trading.learning import _considerations, substantive_text
from scripts.trading.psychology import REQUIRED_CHECK_QUESTIONS
from scripts.trading.psychology_events import revenge_family

_ENUMS = {
    "size_vs_trailing_average": {"smaller", "same", "larger"},
    "invalidation_explicit": {"yes", "no"},
    "would_take_if_flat_and_unscarred": {"yes", "no", "unsure"},
    "size_vs_prior_loss": {"smaller", "same", "larger", "not_applicable"},
    "catalyst_or_mispricing_identified": {"yes", "no"},
    "would_pitch_if_rank_hidden": {"yes", "no", "unsure"},
    "invalidation_touched": {"yes", "no", "partially"},
    "decision_same_if_rank_hidden": {"yes", "no", "unsure"},
    "pressure_read": {"sharpening", "distorting", "neither"},
    "thesis_still_valid": {"yes", "no", "unsure"},
    "derisk_reason": {"thesis", "risk_limit", "pnl_pain", "mandate", "other"},
}
_TEXT_FIELDS = {
    "what_would_make_me_wrong_now",
    "what_changed_in_evidence",
    "why_now",
    "new_information_since_entry",
    "thesis_unchanged_because",
}


def _flags(context: dict[str, Any] | None) -> list[dict[str, Any]]:
    psychology = (context or {}).get("psychology") or {}
    if not psychology.get("applicable", True):
        return []
    return [row for row in (psychology.get("active_flags") or []) if isinstance(row, dict)]


def _override_disposition(decision: dict[str, Any], action: dict[str, Any]) -> bool:
    return any(
        isinstance(row, dict) and row.get("disposition") == "OVERRIDE" for row in _considerations(decision, action)
    )


def _relevant_flags(action: dict[str, Any], flags: list[dict[str, Any]], decision: dict[str, Any]) -> list[dict[str, Any]]:
    kind = action.get("action")
    if kind not in EXPANDING_ACTIONS:
        return []
    family = revenge_family(action.get("instrument"), action.get("asset_class"), action.get("paper_expression"))
    matched = []
    for flag in flags:
        if flag.get("check") != "required":
            continue
        actions = set(flag.get("relevant_actions") or [])
        override = flag.get("id") == "stubbornness_risk" and _override_disposition(decision, action)
        if kind not in actions and not override:
            continue
        if flag.get("id") == "revenge_risk" and flag.get("scope") == "family":
            families = set(flag.get("families") or [])
            if family not in families:
                continue
        matched.append(flag)
    return matched


def _pressure_satisfies_rank(decision: dict[str, Any]) -> bool:
    from scripts.trading.gate import _pressure_assessment_valid

    return _pressure_assessment_valid(decision.get("pressure_assessment"))


def _adverse(flag_id: str, answers: dict[str, Any], action: dict[str, Any]) -> bool:
    if flag_id == "revenge_risk":
        return answers.get("would_take_if_flat_and_unscarred") == "no" or answers.get("size_vs_prior_loss") == "larger"
    if flag_id == "chase_risk":
        return answers.get("catalyst_or_mispricing_identified") == "no"
    if flag_id == "stubbornness_risk":
        return action.get("action") == "ADD" and answers.get("invalidation_touched") == "yes"
    if flag_id == "rank_distortion_risk":
        return answers.get("decision_same_if_rank_hidden") == "no"
    return False


def validate_psychology_check(check: Any, questions: dict[str, tuple[str, ...]]) -> dict[str, Any]:
    if not isinstance(check, dict):
        raise SchemaError("psychology_check must be an object")
    answers = check.get("answers")
    if not isinstance(answers, dict):
        raise SchemaError("psychology_check.answers must be an object")
    cleaned_answers: dict[str, dict[str, Any]] = {}
    for flag_id, fields in questions.items():
        row = answers.get(flag_id)
        if not isinstance(row, dict):
            raise SchemaError(f"psychology_check missing answers for {flag_id}")
        cleaned: dict[str, Any] = {}
        for field in fields:
            value = row.get(field)
            if field in _TEXT_FIELDS:
                cleaned[field] = substantive_text(value, label=f"psychology_check.{flag_id}.{field}")
            elif field in _ENUMS:
                if value not in _ENUMS[field]:
                    raise SchemaError(f"psychology_check.{flag_id}.{field} is invalid")
                cleaned[field] = value
            else:
                raise SchemaError(f"unknown psychology_check field {field}")
        cleaned_answers[flag_id] = cleaned
    if check.get("proceed_despite_flags") not in (True, False):
        raise SchemaError("psychology_check.proceed_despite_flags must be boolean")
    acknowledged = check.get("flags_acknowledged")
    if not isinstance(acknowledged, list) or any(not isinstance(item, str) for item in acknowledged):
        raise SchemaError("psychology_check.flags_acknowledged must be a list of flag ids")
    return {
        "state_sha256": check.get("state_sha256"),
        "flags_acknowledged": acknowledged,
        "answers": cleaned_answers,
        "proceed_despite_flags": check.get("proceed_despite_flags"),
        "override_rationale": check.get("override_rationale"),
    }


def psychology_action_reason(action: dict[str, Any], decision: dict[str, Any], *, owner_id: str) -> str | None:
    """Block reason for one expanding action, or None."""
    if action.get("action") not in EXPANDING_ACTIONS:
        return None
    context = decision.get("_memory_context") or {}
    psychology = context.get("psychology") or {}
    if not psychology or psychology.get("applicable") is False:
        return None
    needed = _relevant_flags(action, _flags(context), decision)
    if owner_id in PM_IDS and _pressure_satisfies_rank(decision):
        needed = [flag for flag in needed if flag.get("id") != "rank_distortion_risk"]
    if not needed:
        return None
    expected_hash = psychology.get("state_sha256")
    check = decision.get("psychology_check")
    if not isinstance(check, dict):
        return f"{owner_id} psychology_gate: missing_psychology_check {needed[0].get('id')}"
    if check.get("state_sha256") != expected_hash:
        return f"{owner_id} psychology_gate: stale_psychology_state"
    questions = {}
    for flag in needed:
        flag_id = str(flag.get("id"))
        if flag_id not in REQUIRED_CHECK_QUESTIONS:
            continue
        questions[flag_id] = REQUIRED_CHECK_QUESTIONS[flag_id]
    try:
        cleaned = validate_psychology_check(check, questions)
    except SchemaError as exc:
        return f"{owner_id} psychology_gate: missing_psychology_check {exc}"
    acknowledged = set(cleaned["flags_acknowledged"])
    adverse = False
    for flag in needed:
        flag_id = str(flag.get("id"))
        if flag_id not in acknowledged:
            return f"{owner_id} psychology_gate: missing_psychology_check {flag_id}"
        row = cleaned["answers"].get(flag_id) or {}
        if _adverse(flag_id, row, action):
            adverse = True
    if cleaned["proceed_despite_flags"] is False:
        return f"{owner_id} psychology_gate: check_declines_but_expands"
    if adverse:
        try:
            substantive_text(cleaned.get("override_rationale"), label="psychology_check.override_rationale")
        except SchemaError:
            return f"{owner_id} psychology_gate: adverse_check_without_override_rationale"
    return None


def _stored_check(decision: dict[str, Any], context: dict[str, Any]) -> dict[str, Any] | None:
    """Persist only a check that validates. Invalid checks are not journaled as if accepted."""
    check = decision.get("psychology_check")
    if not isinstance(check, dict):
        return None
    answers = check.get("answers") if isinstance(check.get("answers"), dict) else {}
    questions = {
        flag_id: REQUIRED_CHECK_QUESTIONS[flag_id]
        for flag_id in answers
        if flag_id in REQUIRED_CHECK_QUESTIONS
    }
    for flag in _flags(context):
        flag_id = str(flag.get("id") or "")
        if flag.get("check") == "required" and flag_id in REQUIRED_CHECK_QUESTIONS:
            questions[flag_id] = REQUIRED_CHECK_QUESTIONS[flag_id]
    if not questions:
        return None
    try:
        return validate_psychology_check(check, questions)
    except SchemaError:
        return None


def psychology_journal_payload(decision: dict[str, Any], blocked: list[dict[str, Any]]) -> dict[str, Any]:
    context = decision.get("_memory_context") or {}
    psychology = context.get("psychology") or {}
    flags = [flag.get("id") for flag in _flags(context)]
    check = _stored_check(decision, context)
    expanding_blocked = any(
        isinstance(row.get("action"), dict) and row["action"].get("action") in EXPANDING_ACTIONS and "psychology_gate" in str(row.get("reason"))
        for row in blocked
    )
    if check and not expanding_blocked:
        status = "provided"
    elif expanding_blocked:
        status = "missing_required_blocked"
    elif any(flag.get("check") == "optional" for flag in _flags(context)) and not check:
        actions = {row.get("action") for row in (decision.get("actions") or []) if isinstance(row, dict)}
        status = "missing_optional" if actions & {"REDUCE", "CLOSE", "HOLD"} else "not_required"
    else:
        status = "not_required"
    pressure = decision.get("pressure_assessment") if isinstance(decision.get("pressure_assessment"), dict) else None
    return {
        "state_sha256": psychology.get("state_sha256"),
        "active_flags": flags,
        "check": check,
        "check_status": status,
        "pressure_assessment": pressure,
    }
