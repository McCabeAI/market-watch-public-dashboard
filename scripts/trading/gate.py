"""Learning and rationale gates. De-risk/HOLD never fail closed on memory."""

from __future__ import annotations

from typing import Any

from scripts.trading.constants import DERISK_ACTIONS, EXPANDING_ACTIONS
from scripts.trading.errors import LearningGateError, RationaleError
from scripts.trading.memory import outstanding_due
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
    return None


def evaluate_decision_actions(
    store: TradingStore,
    *,
    owner_type: str,
    owner_id: str,
    decision: dict[str, Any],
    run_id: str | None,
    expected_memory_sha256: str | None,
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
