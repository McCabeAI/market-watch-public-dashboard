"""Learning and rationale gates. De-risk/HOLD never fail closed on memory."""

from __future__ import annotations

from typing import Any

from scripts.trading.constants import DERISK_ACTIONS, EXPANDING_ACTIONS
from scripts.trading.errors import LearningGateError, RationaleError
from scripts.trading.learning import lesson_consideration_reason
from scripts.trading.memory import active_lessons, outstanding_due, outstanding_reflections_due
from scripts.trading.store import TradingStore, assert_identity


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def decision_actions(decision: dict[str, Any]) -> list[dict[str, Any]]:
    actions = decision.get("actions") or []
    if not isinstance(actions, list):
        return []
    return [row for row in actions if isinstance(row, dict)]


def expanding_actions(decision: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in decision_actions(decision) if row.get("action") in EXPANDING_ACTIONS]


def is_derisk_only(decision: dict[str, Any]) -> bool:
    actions = decision_actions(decision)
    if not actions:
        return True
    return all(row.get("action") in DERISK_ACTIONS for row in actions)


def action_rationale(action: dict[str, Any], decision: dict[str, Any] | None = None) -> str | None:
    for key in ("rationale", "entry_rationale", "exit_rationale", "thesis", "note"):
        text = _text(action.get(key))
        if text:
            return text
    memo = action.get("expression_memo")
    if isinstance(memo, dict):
        text = _text(memo.get("rationale"))
        if text:
            return text
    payload = decision or {}
    for key in ("rationale", "thesis"):
        text = _text(payload.get(key))
        if text:
            return text
    memo = payload.get("expression_memo")
    if isinstance(memo, dict):
        text = _text(memo.get("rationale"))
        if text:
            return text
    return None


def rationale_status_for(action: dict[str, Any], decision: dict[str, Any] | None = None) -> str:
    kind = action.get("action")
    present = action_rationale(action, decision) is not None
    if kind in EXPANDING_ACTIONS:
        return "present" if present else "missing_required"
    if kind in {"REDUCE", "CLOSE"}:
        return "present" if present else "missing_required"
    return "present" if present else "not_required"


def expansion_rationale_reason(action: dict[str, Any], decision: dict[str, Any] | None, *, owner_id: str) -> str | None:
    if action.get("action") not in EXPANDING_ACTIONS:
        return None
    if action_rationale(action, decision):
        return None
    return f"{owner_id} {action.get('action')} failed closed: missing required expansion rationale"


def _pressure_assessment_valid(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    required = {
        "judgment_effect": ("sharpening", "distorting", "neither"),
        "junior_vs_self": ("variance", "style", "information", "not_behind", "not_applicable"),
        "chase_temptation": ("yes", "no", "not_applicable"),
        "protecting_gains": ("yes", "no", "not_applicable"),
        "heater_risk": ("yes", "no", "not_applicable"),
        "allocator_vs_noise": ("mandate_failure", "short_horizon_noise", "not_applicable"),
    }
    for key, allowed in required.items():
        if payload.get(key) not in allowed:
            return False
    return True


def requires_pressure_assessment(decision: dict[str, Any]) -> bool:
    memory = decision.get("_memory_context") or {}
    consequence = memory.get("consequence") or {}
    capital_owner = memory.get("capital_owner") or {}
    flags = consequence.get("pressure_flags") or []
    competitive = any(
        flag in flags
        for flag in ("behind_leading_pm", "best_trader_ahead", "competitive_pressure")
    )
    standing = capital_owner.get("standing")
    if not competitive and standing not in ("watch", "probation"):
        return False
    if competitive and consequence.get("status") == "ok":
        spread = consequence.get("spread_to_leader_pm_usd")
        best_gap = consequence.get("gap_to_best_trader_usd")
        own_pnl = float(consequence.get("net_after_funding_pnl_usd") or 0.0)
        if spread == 0 and (best_gap in (None, 0)) and own_pnl == 0.0:
            return False
    return True


def pressure_gate_reason(decision: dict[str, Any], *, owner_id: str) -> str | None:
    if not requires_pressure_assessment(decision):
        return None
    if _pressure_assessment_valid(decision.get("pressure_assessment")):
        return None
    return f"{owner_id} learning_gate: missing_pressure_assessment"


def learning_gate_reason(
    store: TradingStore,
    *,
    owner_type: str,
    owner_id: str,
    decision: dict[str, Any],
    run_id: str | None,
    expected_memory_sha256: str | None,
) -> str | None:
    """Return a deterministic expansion-block reason, or None if expansion may proceed."""
    assert_identity(owner_type, owner_id)
    supplied = _text(decision.get("memory_context_sha256"))
    if not supplied:
        return f"{owner_id} learning_gate: missing_memory_context_sha256"
    if not expected_memory_sha256:
        return f"{owner_id} learning_gate: stale_memory_context"
    if supplied != expected_memory_sha256:
        return f"{owner_id} learning_gate: stale_memory_context"
    due = outstanding_due(store, owner_type, owner_id, exclude_run_id=run_id)
    if due:
        trade_ids = [row.get("trade_id") for row in due]
        return f"{owner_id} learning_gate: postmortems_due {trade_ids}"
    reflections = outstanding_reflections_due(store, owner_type, owner_id, exclude_run_id=run_id)
    if reflections:
        ids = [row.get("reflection_due_id") for row in reflections]
        return f"{owner_id} learning_gate: reflections_due {ids}"
    pressure_reason = pressure_gate_reason(decision, owner_id=owner_id)
    if pressure_reason:
        return pressure_reason
    lessons = active_lessons(store, owner_type, owner_id)
    for action in expanding_actions(decision):
        reason = lesson_consideration_reason(action, decision, lessons, owner_id=owner_id)
        if reason:
            return reason
    return None


def evaluate_decision_actions(
    store: TradingStore,
    *,
    owner_type: str,
    owner_id: str,
    decision: dict[str, Any],
    run_id: str | None,
    expected_memory_sha256: str | None,
    trader_books: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split a decision into executable actions and explicitly blocked expansions.

    HOLD / NO_TRADE / REDUCE / CLOSE always remain in the executable set.
    OPEN / ADD / HEDGE fail closed independently when rationale or memory
    obligations are not met. Same-run postmortems are excluded so a CLOSE
    in this decision cannot retroactively block a already-valid sibling action.
    """
    allowed: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    memory_reason = None
    if expanding_actions(decision):
        if decision.get("_memory_context") is None and expected_memory_sha256:
            from scripts.trading.memory import build_memory_context

            decision["_memory_context"] = build_memory_context(
                store,
                owner_type,
                owner_id,
                exclude_run_id=run_id,
                trader_books=trader_books,
            )
        memory_reason = learning_gate_reason(
            store,
            owner_type=owner_type,
            owner_id=owner_id,
            decision=decision,
            run_id=run_id,
            expected_memory_sha256=expected_memory_sha256,
        )
    for action in decision_actions(decision):
        kind = action.get("action")
        if kind in EXPANDING_ACTIONS:
            rationale_reason = expansion_rationale_reason(action, decision, owner_id=owner_id)
            if rationale_reason:
                blocked.append({"action": action, "reason": rationale_reason, "result": "blocked"})
                continue
            if memory_reason:
                blocked.append({"action": action, "reason": memory_reason, "result": "blocked"})
                continue
        allowed.append(action)
    return allowed, blocked


def raise_if_unexecutable(blocked: list[dict[str, Any]], allowed: list[dict[str, Any]]) -> None:
    """Pure invalid expansion fails closed. Mixed decisions keep executable de-risk."""
    if not blocked or allowed:
        return
    reason = str(blocked[0].get("reason") or "expansion blocked")
    if "missing required expansion rationale" in reason:
        raise RationaleError(reason)
    raise LearningGateError(reason)


def assert_expansion_rationale(decision: dict[str, Any], *, owner_id: str) -> None:
    for action in expanding_actions(decision):
        reason = expansion_rationale_reason(action, decision, owner_id=owner_id)
        if reason:
            raise RationaleError(reason)


def assert_learning_gate(
    store: TradingStore,
    *,
    owner_type: str,
    owner_id: str,
    decision: dict[str, Any],
    run_id: str | None,
    expected_memory_sha256: str | None,
) -> None:
    assert_identity(owner_type, owner_id)
    if is_derisk_only(decision):
        return
    reason = learning_gate_reason(
        store,
        owner_type=owner_type,
        owner_id=owner_id,
        decision=decision,
        run_id=run_id,
        expected_memory_sha256=expected_memory_sha256,
    )
    if reason:
        raise LearningGateError(reason)
