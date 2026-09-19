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


def assert_expansion_rationale(decision: dict[str, Any], *, owner_id: str) -> None:
    for action in expanding_actions(decision):
        if action_rationale(action, decision):
            continue
        raise RationaleError(
            f"{owner_id} {action.get('action')} failed closed: missing required expansion rationale"
        )


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
    supplied = _text(decision.get("memory_context_sha256"))
    if not supplied:
        raise LearningGateError(f"{owner_id} learning_gate: missing_memory_context_sha256")
    if not expected_memory_sha256:
        raise LearningGateError(f"{owner_id} learning_gate: stale_memory_context")
    if supplied != expected_memory_sha256:
        raise LearningGateError(f"{owner_id} learning_gate: stale_memory_context")
    due = outstanding_due(store, owner_type, owner_id, exclude_run_id=run_id)
    if due:
        trade_ids = [row.get("trade_id") for row in due]
        raise LearningGateError(f"{owner_id} learning_gate: postmortems_due {trade_ids}")
