"""Causal learning, structured lessons, retrieval, and learning default.

Extends the existing Git-backed identity memory. It does not create a second store.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from scripts.overnight.clock import isoformat, now_ny
from scripts.trading.constants import (
    CAUSAL_FIELDS,
    DECISION_QUALITY_ATTRIBUTION,
    ESTABLISHED_REINFORCEMENT_THRESHOLD,
    LESSON_CONSIDERATION_DISPOSITIONS,
    LESSON_MATURITY,
    LESSON_OPS,
    LEARNING_STATUSES,
    MATERIAL_LESSON_SCORE,
    NO_NEW_LESSON_MARKERS,
    PLATITUDE_PATTERNS,
    SETUP_FINGERPRINT_LIST_CAP,
)
from scripts.trading.errors import SchemaError
from scripts.trading.store import TradingStore, assert_identity


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def is_platitude(value: str) -> bool:
    text = _norm(value)
    if len(text) < 24:
        return True
    for pattern in PLATITUDE_PATTERNS:
        if pattern.search(text):
            return True
    stripped = re.sub(r"[$€£]?\d[\d,]*(?:\.\d+)?%?", " ", text)
    stripped = re.sub(
        r"\b(pnl|p&l|profit|loss|rank|nav|drawdown|usd|bps|percent|timing was bad|disciplined)\b",
        " ",
        stripped,
    )
    words = [word for word in re.findall(r"[a-z]{3,}", stripped) if word not in {"the", "and", "was", "were", "for", "with"}]
    return len(words) < 4


def substantive_text(value: Any, *, label: str) -> str:
    text = _text(value)
    if not text or is_platitude(text):
        raise SchemaError(f"{label} must be a substantive causal statement, not a P&L summary or platitude")
    return text


def causal_block(payload: dict[str, Any]) -> dict[str, str]:
    raw = payload.get("causal")
    if not isinstance(raw, dict):
        raise SchemaError("learning submission requires a causal object")
    out: dict[str, str] = {}
    for field in CAUSAL_FIELDS:
        out[field] = substantive_text(raw.get(field), label=f"causal.{field}")
    attribution = raw.get("decision_quality_attribution")
    if attribution not in DECISION_QUALITY_ATTRIBUTION:
        raise SchemaError(
            "causal.decision_quality_attribution must be one of "
            + ", ".join(DECISION_QUALITY_ATTRIBUTION)
        )
    out["decision_quality_attribution"] = attribution
    return out


def substantive_no_new_lesson(value: Any) -> str:
    text = substantive_text(value, label="no_new_lesson")
    lowered = _norm(text)
    if not any(marker in lowered for marker in NO_NEW_LESSON_MARKERS):
        raise SchemaError(
            "NO_NEW_LESSON must explain ordinary bounded variance or why the prior process remains sound"
        )
    return text


def empty_scope() -> dict[str, Any]:
    return {
        "instruments": [],
        "instrument_family": None,
        "asset_class": None,
        "countries": [],
        "currencies": [],
        "setup_type": None,
        "market_drivers": [],
        "catalyst_type": None,
        "failure_mode": None,
        "decision_dimension": None,
    }


def _string_list(value: Any, *, cap: int = SETUP_FINGERPRINT_LIST_CAP) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = _text(item)
        if text and text not in out:
            out.append(text)
        if len(out) >= cap:
            break
    return out


def normalize_scope(value: Any) -> dict[str, Any]:
    scope = empty_scope()
    if not isinstance(value, dict):
        return scope
    scope["instruments"] = _string_list(value.get("instruments"))
    scope["instrument_family"] = _text(value.get("instrument_family"))
    scope["asset_class"] = _text(value.get("asset_class"))
    scope["countries"] = _string_list(value.get("countries"))
    scope["currencies"] = _string_list(value.get("currencies"))
    scope["setup_type"] = _text(value.get("setup_type"))
    scope["market_drivers"] = _string_list(value.get("market_drivers"))
    scope["catalyst_type"] = _text(value.get("catalyst_type"))
    scope["failure_mode"] = _text(value.get("failure_mode"))
    dimension = _text(value.get("decision_dimension"))
    if dimension in DECISION_QUALITY_ATTRIBUTION:
        scope["decision_dimension"] = dimension
    return scope


def migrate_lesson(row: dict[str, Any]) -> dict[str, Any]:
    """Safe in-place shape for legacy active lessons. Sparse scope stays usable."""
    lesson = dict(row)
    lesson.setdefault("trade_ids", list(row.get("trade_ids") or []))
    lesson.setdefault("postmortem_ids", list(row.get("postmortem_ids") or []))
    lesson.setdefault("reflection_ids", list(row.get("reflection_ids") or []))
    lesson["status"] = row.get("status") if row.get("status") in {"active", "retired"} else "active"
    lesson["reinforcement_count"] = int(row.get("reinforcement_count") or 1)
    lesson["contradiction_count"] = int(row.get("contradiction_count") or 0)
    lesson["text"] = _text(row.get("text")) or ""
    lesson["future_rule"] = _text(row.get("future_rule")) or lesson["text"]
    lesson["maturity"] = row.get("maturity") if row.get("maturity") in LESSON_MATURITY else "candidate"
    if lesson["maturity"] == "candidate" and lesson["reinforcement_count"] >= ESTABLISHED_REINFORCEMENT_THRESHOLD:
        lesson["maturity"] = "established"
    lesson["scope"] = normalize_scope(row.get("scope"))
    history = row.get("history") if isinstance(row.get("history"), list) else []
    lesson["history"] = [item for item in history if isinstance(item, dict)]
    lesson.setdefault("created_at", row.get("created_at"))
    lesson.setdefault("updated_at", row.get("updated_at"))
    lesson.setdefault("source_run_id", row.get("source_run_id"))
    return lesson


def migrate_lessons_doc(doc: dict[str, Any]) -> dict[str, Any]:
    rows = [migrate_lesson(row) for row in (doc.get("lessons") or []) if isinstance(row, dict)]
    return {**doc, "lessons": rows}


def empty_learning_state() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "type": "LEARNING_COMPLIANCE",
        "learning_status": "compliant",
        "learning_default_age_runs": 0,
        "learning_default_count": 0,
        "competition_eligible": True,
        "retrieved_lessons": [],
        "repeated_error_escalations": [],
    }


def read_learning_state(store: TradingStore, owner_type: str, owner_id: str) -> dict[str, Any]:
    state = store.read_learning_state(owner_type, owner_id)
    base = empty_learning_state()
    if not isinstance(state, dict):
        return base
    base.update({k: v for k, v in state.items() if k in base or k in {"schema_version", "type"}})
    if base.get("learning_status") not in LEARNING_STATUSES:
        base["learning_status"] = "compliant"
    base["learning_default_age_runs"] = int(base.get("learning_default_age_runs") or 0)
    base["learning_default_count"] = int(base.get("learning_default_count") or 0)
    base["competition_eligible"] = bool(base.get("competition_eligible", True))
    base["retrieved_lessons"] = [row for row in (base.get("retrieved_lessons") or []) if isinstance(row, dict)]
    base["repeated_error_escalations"] = [
        row for row in (base.get("repeated_error_escalations") or []) if isinstance(row, dict)
    ]
    return base


def write_learning_state(store: TradingStore, owner_type: str, owner_id: str, state: dict[str, Any]) -> None:
    store.write_learning_state(owner_type, owner_id, state)


def settle_learning_compliance(
    store: TradingStore,
    owner_type: str,
    owner_id: str,
    *,
    prior_debt_remains: bool,
    same_run_debt: bool = False,
) -> dict[str, Any]:
    """Unresolved prior-run debt becomes learning default. Clearing it restores eligibility."""
    assert_identity(owner_type, owner_id)
    state = read_learning_state(store, owner_type, owner_id)
    if prior_debt_remains:
        if state.get("learning_status") != "learning_default":
            state["learning_default_count"] = int(state.get("learning_default_count") or 0) + 1
            state["learning_default_age_runs"] = 1
        else:
            state["learning_default_age_runs"] = int(state.get("learning_default_age_runs") or 0) + 1
        state["learning_status"] = "learning_default"
        state["competition_eligible"] = False
    else:
        state["learning_status"] = "due" if same_run_debt else "compliant"
        state["learning_default_age_runs"] = 0
        state["competition_eligible"] = True
    write_learning_state(store, owner_type, owner_id, state)
    return state


def compliance_view(store: TradingStore, owner_type: str, owner_id: str) -> dict[str, Any]:
    state = read_learning_state(store, owner_type, owner_id)
    return {
        "learning_status": state["learning_status"],
        "learning_default_age_runs": state["learning_default_age_runs"],
        "learning_default_count": state["learning_default_count"],
        "competition_eligible": state["competition_eligible"],
        "repeated_error_escalations": [
            {
                "lesson_id": row.get("lesson_id"),
                "failure_mode": row.get("failure_mode"),
                "count": int(row.get("count") or 0),
            }
            for row in state.get("repeated_error_escalations") or []
        ],
    }


def lesson_public_fields(row: dict[str, Any]) -> dict[str, Any]:
    lesson = migrate_lesson(row)
    return {
        "lesson_id": lesson.get("lesson_id"),
        "text": lesson.get("text"),
        "future_rule": lesson.get("future_rule"),
        "maturity": lesson.get("maturity"),
        "trade_ids": lesson.get("trade_ids") or [],
        "postmortem_ids": lesson.get("postmortem_ids") or [],
        "reflection_ids": lesson.get("reflection_ids") or [],
        "reinforcement_count": lesson.get("reinforcement_count"),
        "contradiction_count": lesson.get("contradiction_count"),
        "scope": lesson.get("scope"),
        "status": lesson.get("status"),
        "source_run_id": lesson.get("source_run_id"),
    }


def _currencies_from_instrument(instrument: str | None) -> list[str]:
    if not instrument:
        return []
    letters = re.findall(r"[A-Z]{3}", instrument.upper())
    return letters[:4]


def setup_fingerprint(action: dict[str, Any]) -> dict[str, Any]:
    raw = action.get("setup_fingerprint")
    if raw is None:
        return normalize_scope({})
    if not isinstance(raw, dict):
        raise SchemaError("setup_fingerprint must be an object")
    scope = normalize_scope(raw)
    extra = [key for key in raw if key not in empty_scope()]
    if extra:
        raise SchemaError(f"setup_fingerprint has unsupported fields: {sorted(extra)[:4]}")
    return scope


def _overlap_count(left: list[str], right: list[str]) -> int:
    right_norm = {_norm(item) for item in right}
    return sum(1 for item in left if _norm(item) in right_norm)


def lesson_match_score(lesson: dict[str, Any], trusted: dict[str, Any], fingerprint: dict[str, Any]) -> int:
    scope = normalize_scope(lesson.get("scope"))
    score = 0
    instrument = _text(trusted.get("instrument"))
    if instrument and _norm(instrument) in {_norm(item) for item in scope["instruments"]}:
        score += 3
    asset = _text(trusted.get("asset_class"))
    if asset and scope["asset_class"] and _norm(asset) == _norm(scope["asset_class"]):
        score += 2
    family = _text(fingerprint.get("instrument_family"))
    if family and scope["instrument_family"] and _norm(family) == _norm(scope["instrument_family"]):
        score += 2
    setup = _text(fingerprint.get("setup_type"))
    if setup and scope["setup_type"] and _norm(setup) == _norm(scope["setup_type"]):
        score += 2
    catalyst = _text(fingerprint.get("catalyst_type"))
    if catalyst and scope["catalyst_type"] and _norm(catalyst) == _norm(scope["catalyst_type"]):
        score += 2
    score += min(2, _overlap_count(scope["market_drivers"], fingerprint.get("market_drivers") or []))
    failure = _text(fingerprint.get("failure_mode"))
    if failure and scope["failure_mode"] and _norm(failure) == _norm(scope["failure_mode"]):
        score += 2
    dimension = _text(fingerprint.get("decision_dimension"))
    if dimension and scope["decision_dimension"] and dimension == scope["decision_dimension"]:
        score += 1
    if _overlap_count(scope["currencies"], _currencies_from_instrument(instrument) or fingerprint.get("currencies") or []):
        score += 1
    return score


def materially_matching_lessons(action: dict[str, Any], lessons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fingerprint = setup_fingerprint(action) if isinstance(action.get("setup_fingerprint"), dict) else normalize_scope({})
    trusted = {
        "instrument": action.get("instrument"),
        "asset_class": action.get("asset_class"),
        "side": action.get("side"),
    }
    matched = []
    for lesson in lessons:
        if lesson.get("status") not in (None, "active"):
            continue
        score = lesson_match_score(lesson, trusted, fingerprint)
        if score >= MATERIAL_LESSON_SCORE:
            matched.append({**lesson_public_fields(lesson), "match_score": score})
    matched.sort(key=lambda row: (-int(row["match_score"]), str(row.get("lesson_id"))))
    return matched


def _considerations(decision: dict[str, Any], action: dict[str, Any]) -> list[dict[str, Any]]:
    rows = action.get("lesson_considerations")
    if not isinstance(rows, list):
        rows = decision.get("lesson_considerations")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def lesson_consideration_reason(
    action: dict[str, Any],
    decision: dict[str, Any],
    lessons: list[dict[str, Any]],
    *,
    owner_id: str,
) -> str | None:
    if not isinstance(action.get("setup_fingerprint"), dict) and lessons:
        active_scoped = [row for row in lessons if _scope_populated(row.get("scope"))]
        if active_scoped:
            return f"{owner_id} learning_gate: missing_setup_fingerprint"
    matched = materially_matching_lessons(action, lessons)
    if not matched:
        return None
    provided = {row.get("lesson_id"): row for row in _considerations(decision, action)}
    for lesson in matched:
        row = provided.get(lesson.get("lesson_id"))
        if row is None:
            return f"{owner_id} learning_gate: lesson_not_addressed {lesson.get('lesson_id')}"
        if row.get("disposition") not in LESSON_CONSIDERATION_DISPOSITIONS:
            return f"{owner_id} learning_gate: invalid_lesson_disposition {lesson.get('lesson_id')}"
        try:
            substantive_text(row.get("rationale"), label="lesson_consideration.rationale")
        except SchemaError:
            return f"{owner_id} learning_gate: insubstantive_lesson_rationale {lesson.get('lesson_id')}"
    return None


def _scope_populated(scope: Any) -> bool:
    scope = normalize_scope(scope)
    return any(
        (
            scope["instruments"],
            scope["instrument_family"],
            scope["asset_class"],
            scope["countries"],
            scope["currencies"],
            scope["setup_type"],
            scope["market_drivers"],
            scope["catalyst_type"],
            scope["failure_mode"],
            scope["decision_dimension"],
        )
    )


def record_retrieved_lessons(
    store: TradingStore,
    owner_type: str,
    owner_id: str,
    *,
    lesson_ids: list[str],
    run_id: str | None,
    when: datetime | None = None,
) -> None:
    if not lesson_ids:
        return
    state = read_learning_state(store, owner_type, owner_id)
    stamp = isoformat(now_ny(when))
    known = {(row.get("lesson_id"), row.get("run_id")) for row in state["retrieved_lessons"]}
    for lesson_id in lesson_ids:
        if (lesson_id, run_id) in known:
            continue
        state["retrieved_lessons"].append({"lesson_id": lesson_id, "run_id": run_id, "at": stamp})
    state["retrieved_lessons"] = state["retrieved_lessons"][-40:]
    write_learning_state(store, owner_type, owner_id, state)


def note_repeated_error(
    store: TradingStore,
    owner_type: str,
    owner_id: str,
    *,
    lesson_id: str | None,
    failure_mode: str | None,
    run_id: str | None,
) -> None:
    if not lesson_id and not failure_mode:
        return
    state = read_learning_state(store, owner_type, owner_id)
    retrieved = {row.get("lesson_id") for row in state.get("retrieved_lessons") or []}
    if lesson_id and lesson_id not in retrieved and not failure_mode:
        return
    if lesson_id and lesson_id not in retrieved:
        return
    key_mode = failure_mode or lesson_id
    for row in state["repeated_error_escalations"]:
        if row.get("lesson_id") == lesson_id and row.get("failure_mode") == key_mode:
            row["count"] = int(row.get("count") or 1) + 1
            row["last_run_id"] = run_id
            write_learning_state(store, owner_type, owner_id, state)
            return
    state["repeated_error_escalations"].append(
        {
            "lesson_id": lesson_id,
            "failure_mode": key_mode,
            "count": 2,
            "last_run_id": run_id,
        }
    )
    write_learning_state(store, owner_type, owner_id, state)


def apply_structured_lesson_fields(lesson: dict[str, Any], update: dict[str, Any], *, stamp: str, run_id: str | None, op: str) -> None:
    if op not in LESSON_OPS:
        raise SchemaError(f"memory update op must be one of {LESSON_OPS}")
    if update.get("future_rule"):
        lesson["future_rule"] = _text(update.get("future_rule"))
    if isinstance(update.get("scope"), dict):
        lesson["scope"] = normalize_scope(update.get("scope"))
    history = lesson.setdefault("history", [])
    history.append({"op": op, "at": stamp, "run_id": run_id, "text": _text(update.get("text"))})
    if op == "reinforce":
        lesson["reinforcement_count"] = int(lesson.get("reinforcement_count") or 0) + 1
        if int(lesson["reinforcement_count"]) >= ESTABLISHED_REINFORCEMENT_THRESHOLD:
            lesson["maturity"] = "established"
    elif op == "contradict":
        lesson["contradiction_count"] = int(lesson.get("contradiction_count") or 0) + 1
    elif op == "refine":
        if _text(update.get("text")):
            lesson["text"] = _text(update.get("text"))
    elif op == "add":
        lesson["maturity"] = "candidate"
        lesson["contradiction_count"] = int(lesson.get("contradiction_count") or 0)


def journal_learning_triggers(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Triggers only from fields already present on the journal. No invented causes."""
    triggers: list[dict[str, Any]] = []
    for trade in trades:
        if trade.get("status") != "closed":
            continue
        close = None
        for event in reversed(trade.get("events") or []):
            if isinstance(event, dict) and event.get("kind") == "CLOSE":
                close = event
                break
        if not close:
            continue
        trade_id = trade.get("trade_id")
        category = close.get("exit_reason_category")
        if category == "thesis_invalidated":
            triggers.append({"id": "thesis_invalidated", "trade_id": trade_id})
        elif category == "risk_cut":
            triggers.append({"id": "stop_or_forced_exit", "trade_id": trade_id})
        if close.get("close_path") == "diverged_from_thesis":
            triggers.append({"id": "close_reason_diverges", "trade_id": trade_id})
        if close.get("expression_vs_thesis") == "right_thesis_wrong_expression":
            triggers.append({"id": "right_thesis_wrong_expression", "trade_id": trade_id})
        if close.get("reaction_vs_expectation") == "materially_different":
            triggers.append({"id": "catalyst_or_reaction_diverged", "trade_id": trade_id})
    return triggers


def standing_floor_for_learning_default(standing: str, *, learning_status: str) -> str:
    if learning_status != "learning_default":
        return standing
    if standing == "not_applicable":
        return standing
    if standing in {"good_standing", "watch"}:
        return "probation"
    return standing


EXAMINER_ROLE = "learning_quality_examiner"
EXAMINER_MODEL = "composer-2.5"
EXAMINER_FORBIDDEN_KEYS = {
    "actions",
    "thesis",
    "invalidation",
    "instrument",
    "side",
    "notional_usd",
    "lesson",
    "memory_update",
    "memory_updates",
    "postmortems",
    "performance_reflections",
    "books",
    "nav_usd",
    "trade",
    "expression_memo",
}


def validate_learning_quality_review(review: Any) -> dict[str, Any]:
    """Examiner output may grade causal adequacy only."""
    if not isinstance(review, dict):
        raise SchemaError("learning_quality_review must be an object")
    if review.get("role") != EXAMINER_ROLE:
        raise SchemaError("learning_quality_review role must be learning_quality_examiner")
    if review.get("model") != EXAMINER_MODEL:
        raise SchemaError("learning quality examiner must be composer-2.5")
    if int(review.get("call_count", -1)) != 1:
        raise SchemaError("learning quality review is exactly one call")
    forbidden = [key for key in review if key in EXAMINER_FORBIDDEN_KEYS]
    if forbidden:
        raise SchemaError("learning quality review cannot author trading decisions or lessons")
    assessments = review.get("assessments")
    if not isinstance(assessments, list):
        raise SchemaError("learning_quality_review.assessments must be a list")
    cleaned = []
    for row in assessments:
        if not isinstance(row, dict):
            raise SchemaError("learning assessment must be an object")
        extra = [key for key in row if key in EXAMINER_FORBIDDEN_KEYS]
        if extra:
            raise SchemaError("learning assessment cannot author a trade or lesson")
        if row.get("adequate") not in (True, False):
            raise SchemaError("learning assessment adequate must be boolean")
        reasons = row.get("reasons") or []
        if not isinstance(reasons, list) or any(not isinstance(item, str) for item in reasons):
            raise SchemaError("learning assessment reasons must be strings")
        cleaned.append(
            {
                "owner_type": row.get("owner_type"),
                "owner_id": row.get("owner_id"),
                "submission_kind": row.get("submission_kind"),
                "submission_ref": row.get("submission_ref"),
                "adequate": row.get("adequate"),
                "reasons": reasons,
            }
        )
    return {**review, "assessments": cleaned}


def inadequate_submission_refs(review: dict[str, Any] | None) -> set[tuple[str, str, str]]:
    if not review:
        return set()
    refs = set()
    for row in review.get("assessments") or []:
        if row.get("adequate") is False:
            refs.add((str(row.get("owner_type")), str(row.get("owner_id")), str(row.get("submission_ref"))))
    return refs


def drop_inadequate_learning_submissions(decision: dict[str, Any], *, owner_type: str, owner_id: str, blocked_refs: set[tuple[str, str, str]]) -> dict[str, Any]:
    """Remove examiner-rejected learning payloads. Trading actions stay untouched."""
    if not blocked_refs:
        return decision
    out = dict(decision)

    def _keep(kind: str, rows: Any) -> list[Any]:
        kept = []
        for row in rows or []:
            if not isinstance(row, dict):
                kept.append(row)
                continue
            ref = str(row.get("trade_id") or row.get("reflection_due_id") or row.get("submission_ref") or "")
            if (owner_type, owner_id, ref) in blocked_refs:
                continue
            kept.append(row)
        return kept

    if "postmortems" in out:
        out["postmortems"] = _keep("postmortem", out.get("postmortems"))
    if "performance_reflections" in out:
        out["performance_reflections"] = _keep("performance_reflection", out.get("performance_reflections"))
    return out
