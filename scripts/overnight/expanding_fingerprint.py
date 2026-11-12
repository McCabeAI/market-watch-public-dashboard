"""Preflight setup_fingerprint checks before scheduled-output book simulation."""

from __future__ import annotations

from typing import Any

from scripts.overnight.store import OvernightStore
from scripts.trading.constants import DERISK_ACTIONS, EXPANDING_ACTIONS
from scripts.trading.errors import LearningGateError
from scripts.trading.learning import _scope_populated, empty_scope, setup_fingerprint
from scripts.trading.memory import active_lessons
from scripts.trading.store import TradingStore

SETUP_FINGERPRINT_FIELDS: tuple[str, ...] = tuple(empty_scope().keys())

_DERISK = frozenset(DERISK_ACTIONS)
_EXPANDING = frozenset(EXPANDING_ACTIONS)


def _scoped_active_lessons(lessons: list[dict[str, Any]]) -> bool:
    return any(_scope_populated(row.get("scope")) for row in lessons)


def _decision_actions(decision: dict[str, Any]) -> list[dict[str, Any]]:
    rows = decision.get("actions") or []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _check_owner_decision(
    *,
    owner_id: str,
    owner_type: str,
    decision: dict[str, Any],
    trading: TradingStore,
) -> None:
    lessons = active_lessons(trading, owner_type, owner_id)
    scoped_lessons = _scoped_active_lessons(lessons)
    allowed = False
    blocked: tuple[str, Any] | None = None

    for action in _decision_actions(decision):
        kind = action.get("action")
        if kind in _DERISK:
            allowed = True
            continue
        if kind not in _EXPANDING:
            continue
        if isinstance(action.get("setup_fingerprint"), dict):
            # A dict is not "missing", but an empty object is not strategy metadata.
            # Do not fill fields. Scoped lessons still require a populated scope.
            normalized = setup_fingerprint(action)
            if scoped_lessons and not _scope_populated(normalized):
                if blocked is None:
                    blocked = (str(kind), action.get("instrument"))
                continue
            allowed = True
            continue
        if scoped_lessons:
            if blocked is None:
                blocked = (str(kind), action.get("instrument"))
        else:
            allowed = True

    if blocked and not allowed:
        kind, instrument = blocked
        instr = instrument if instrument not in (None, "") else "none"
        raise LearningGateError(
            f"{owner_id} learning_gate: missing_setup_fingerprint "
            f"action={kind} instrument={instr} required_field=setup_fingerprint"
        )


def preflight_expanding_fingerprints(store: OvernightStore, payload: dict[str, Any]) -> None:
    trading = TradingStore(root=store.root, state_root=store.state_root)
    decisions = payload.get("decisions")
    if isinstance(decisions, dict):
        for owner_id, decision in decisions.items():
            if isinstance(decision, dict):
                _check_owner_decision(
                    owner_id=str(owner_id),
                    owner_type="trader",
                    decision=decision,
                    trading=trading,
                )
    pm_decisions = payload.get("pm_decisions")
    if isinstance(pm_decisions, dict):
        for owner_id, decision in pm_decisions.items():
            if isinstance(decision, dict):
                _check_owner_decision(
                    owner_id=str(owner_id),
                    owner_type="pm",
                    decision=decision,
                    trading=trading,
                )
