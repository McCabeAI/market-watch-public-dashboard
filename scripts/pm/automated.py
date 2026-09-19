"""Optional future automated-PM decision ingestion. This repo never invokes models."""

from __future__ import annotations

from typing import Any

from scripts.trading.apply import apply_pm_decision_with_memory
from scripts.trading.store import TradingStore
from scripts.pm.constants import ALLOWED_SUBAGENT_MODELS, AUTOMATED_PM_IDS, MAX_SUBAGENTS_PER_PM
from scripts.pm.errors import IndependenceError, SchemaError


def validate_pm_execution(execution: dict[str, Any] | None, *, pm_id: str) -> dict[str, Any]:
    payload = execution or {}
    if not isinstance(payload, dict):
        raise SchemaError(f"{pm_id} execution must be an object")
    principal = payload.get("principal_model")
    if principal not in ALLOWED_SUBAGENT_MODELS:
        raise SchemaError(f"{pm_id} principal_model must be grok-4.6 or composer-2.5")
    raw_count = payload.get("subagent_count", 0)
    try:
        count = int(raw_count)
    except (TypeError, ValueError) as exc:
        raise SchemaError(f"{pm_id} subagent_count must be an integer") from exc
    if count < 0 or count > MAX_SUBAGENTS_PER_PM:
        raise SchemaError(f"{pm_id} subagent_count must be 0..{MAX_SUBAGENTS_PER_PM}")
    models = payload.get("subagent_models", [])
    if models is None:
        models = []
    if not isinstance(models, list):
        raise SchemaError(f"{pm_id} subagent_models must be a list")
    if len(models) != count:
        raise SchemaError(f"{pm_id} subagent_models length must equal subagent_count")
    unsupported = [model for model in models if model not in ALLOWED_SUBAGENT_MODELS]
    if unsupported:
        raise SchemaError(f"{pm_id} unsupported subagent model(s): {unsupported}")
    return payload


def validate_pm_decisions(block: Any, *, overnight_run_id: str, packet_sha256: str, evidence_cutoff: str) -> dict[str, Any]:
    if block is None:
        return {}
    if not isinstance(block, dict):
        raise SchemaError("pm_decisions must be an object when supplied")
    if set(block) != set(AUTOMATED_PM_IDS):
        raise SchemaError(
            "pm_decisions must contain exactly swinger, pragmatist, and grinder; "
            f"got {sorted(block)}"
        )
    for pm_id in AUTOMATED_PM_IDS:
        decision = block[pm_id]
        if not isinstance(decision, dict):
            raise SchemaError(f"{pm_id} automated decision must be an object")
        if decision.get("pm_id") not in (None, pm_id):
            raise IndependenceError(f"{pm_id} decision pm_id mismatch")
        if decision.get("overnight_run_id") not in (None, overnight_run_id):
            raise SchemaError(f"{pm_id} overnight_run_id mismatch")
        if decision.get("packet_sha256") not in (None, packet_sha256):
            raise SchemaError(f"{pm_id} packet_sha256 mismatch")
        if decision.get("evidence_cutoff") not in (None, evidence_cutoff):
            raise SchemaError(f"{pm_id} evidence_cutoff mismatch")
        if not isinstance(decision.get("actions"), list) or not decision["actions"]:
            raise SchemaError(f"{pm_id} must return at least one structured action")
        validate_pm_execution(decision.get("execution") or decision, pm_id=pm_id)
    return block


def apply_automated_pm_decisions(
    books: dict[str, Any],
    pm_decisions: dict[str, Any],
    *,
    market_state: dict[str, Any] | None,
    run_id: str,
    evidence_cutoff: str,
    packets: dict[str, dict[str, Any]] | None = None,
    trading_store: TradingStore | None = None,
) -> dict[str, Any]:
    """Apply each automated PM independently. No PM sees another's current decision."""
    updated = books
    trading = trading_store or TradingStore()
    for pm_id in AUTOMATED_PM_IDS:
        packet = (packets or {}).get(pm_id) or {}
        decision = pm_decisions[pm_id]
        updated = apply_pm_decision_with_memory(
            updated,
            decision,
            pm_id=pm_id,
            store=trading,
            market_state=market_state,
            run_id=run_id,
            evidence_cutoff=evidence_cutoff,
            review_packet_id=packet.get("review_packet_id"),
            review_packet_sha256=packet.get("review_packet_sha256"),
            expected_memory_sha256=packet.get("memory_context_sha256") or decision.get("memory_context_sha256"),
            evidence_hash=packet.get("review_packet_sha256"),
        )
    return updated
