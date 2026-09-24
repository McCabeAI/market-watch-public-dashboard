"""Overnight automated-PM decision validation/apply. This repo never invokes models."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from scripts.overnight.errors import EvidenceBoundaryError
from scripts.trading.apply import apply_pm_decision_with_memory
from scripts.trading.store import TradingStore
from scripts.pm.constants import ALLOWED_SUBAGENT_MODELS, AUTOMATED_PM_IDS, MAX_SUBAGENTS_PER_PM
from scripts.pm.errors import IndependenceError, SchemaError
from scripts.pm.models import PM_PRINCIPAL_MODEL
from scripts.pm.grinder import synthetic_grinder_hurdle, validate_grinder_hurdle
from scripts.pm.portfolio import synthetic_portfolio_construction, validate_portfolio_construction


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


def validate_pm_decisions(
    block: Any,
    *,
    overnight_run_id: str,
    packet_sha256: str,
    evidence_cutoff: str,
    packet: dict[str, Any] | None = None,
    memory_hashes: dict[str, str] | None = None,
    required: bool = True,
) -> dict[str, Any]:
    if block is None or not isinstance(block, dict):
        if required:
            raise SchemaError(
                "scheduled output must include current-cycle decisions for exactly "
                "swinger, pragmatist, and grinder"
            )
        if block is None:
            return {}
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
        for forbidden_key in ("tools_used", "web_search", "web_fetch", "fetched_new_evidence"):
            if decision.get(forbidden_key):
                raise EvidenceBoundaryError(
                    f"{pm_id} recorded forbidden post-freeze acquisition: {forbidden_key}"
                )
        validate_pm_execution(decision.get("execution") or decision, pm_id=pm_id)
        principal = (decision.get("execution") or {}).get("principal_model") or decision.get(
            "principal_model"
        )
        if principal != PM_PRINCIPAL_MODEL:
            raise SchemaError(
                f"{pm_id} overnight automated principal_model must be exact {PM_PRINCIPAL_MODEL}"
            )
        validate_portfolio_construction(decision, pm_id=pm_id, required=True, packet=packet)
        validate_grinder_hurdle(decision, pm_id=pm_id, required=True, packet=packet)
        expanding = [
            row
            for row in decision["actions"]
            if isinstance(row, dict) and row.get("action") in {"OPEN", "ADD", "HEDGE"}
        ]
        if expanding and memory_hashes:
            frozen_hash = memory_hashes.get(pm_id)
            supplied_hash = decision.get("memory_context_sha256")
            if not supplied_hash:
                raise EvidenceBoundaryError(f"{pm_id} learning_gate: missing_memory_context_sha256")
            if frozen_hash and supplied_hash != frozen_hash:
                raise EvidenceBoundaryError(
                    f"{pm_id} referenced a memory snapshot that is not this PM/run freeze"
                )
    return block


def apply_automated_pm_decisions(
    books: dict[str, Any],
    pm_decisions: dict[str, Any],
    *,
    market_state: dict[str, Any] | None,
    run_id: str,
    evidence_cutoff: str,
    review_id: str | None = None,
    packets: dict[str, dict[str, Any]] | None = None,
    trading_store: TradingStore | None = None,
    memory_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Apply each automated PM independently. No PM sees another's current decision."""
    prior = deepcopy(books)
    result = deepcopy(books)
    trading = trading_store or TradingStore()
    for pm_id in AUTOMATED_PM_IDS:
        packet = (packets or {}).get(pm_id) or {}
        decision = pm_decisions[pm_id]
        expected_memory = (
            (memory_hashes or {}).get(pm_id)
            or packet.get("memory_context_sha256")
            or decision.get("memory_context_sha256")
        )
        isolated = deepcopy(prior)
        merged = apply_pm_decision_with_memory(
            isolated,
            decision,
            pm_id=pm_id,
            store=trading,
            market_state=market_state,
            run_id=run_id,
            evidence_cutoff=evidence_cutoff,
            review_packet_id=packet.get("review_packet_id"),
            review_packet_sha256=packet.get("review_packet_sha256"),
            expected_memory_sha256=expected_memory,
            evidence_hash=packet.get("review_packet_sha256"),
            review_id=review_id,
            review_packet=packet or None,
        )
        result["pms"][pm_id] = deepcopy(merged["pms"][pm_id])
    return result


def dry_run_pm_decisions(
    *,
    overnight_run_id: str,
    packet_sha256: str,
    evidence_cutoff: str,
    memory_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Deterministic HOLD block for overnight dry-runs (zero model spend)."""
    block: dict[str, Any] = {}
    for pm_id in AUTOMATED_PM_IDS:
        row: dict[str, Any] = {
            "pm_id": pm_id,
            "overnight_run_id": overnight_run_id,
            "packet_sha256": packet_sha256,
            "evidence_cutoff": evidence_cutoff,
            "principal_model": PM_PRINCIPAL_MODEL,
            "subagent_count": 0,
            "subagent_models": [],
            "actions": [{"action": "HOLD"}],
            "thesis": "Dry-run hold; no live model invocation.",
            "invalidation": None,
            "conviction": 0,
        }
        if memory_hashes and pm_id in memory_hashes:
            row["memory_context_sha256"] = memory_hashes[pm_id]
        if pm_id == "pragmatist":
            row["portfolio_construction"] = synthetic_portfolio_construction()
        if pm_id == "grinder":
            row["deployment_hurdle"] = synthetic_grinder_hurdle()
        block[pm_id] = row
    return block


def apply_required_overnight_pm_decisions(
    pm_store,
    pm_decisions: dict[str, Any],
    *,
    run_id: str,
    evidence_cutoff: str,
    market_state: dict[str, Any] | None,
    packets: dict[str, dict[str, Any]],
    trading_store: TradingStore,
    memory_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    from scripts.pm.books import validate_books

    books = validate_books(pm_store.read_books())
    books = apply_automated_pm_decisions(
        books,
        pm_decisions,
        market_state=market_state,
        run_id=run_id,
        evidence_cutoff=evidence_cutoff,
        packets=packets,
        trading_store=trading_store,
        memory_hashes=memory_hashes,
    )
    books["last_successful_automated_pm_run_id"] = run_id
    pm_store.write_books(books)
    return books
