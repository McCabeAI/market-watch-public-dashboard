"""Build validated stub scheduled output for manual launch mock provider runs."""

from __future__ import annotations

from typing import Any

from scripts.market_watch_launch.contract import LAUNCHER_ID
from scripts.overnight.constants import SCHEMA_VERSION
from scripts.overnight.scheduled_output import AGENT_PACKET_TYPE, SCHEDULE_ID
from scripts.overnight.store import OvernightStore, sha256_json
from scripts.trader_room import agent_config
from scripts.pm.automated import dry_run_pm_decisions
from scripts.pm.grinder import synthetic_grinder_hurdle
from scripts.pm.portfolio import synthetic_portfolio_construction


def _research_supplement(base_packet: dict[str, Any]) -> dict[str, Any]:
    from scripts.macro_ingestion.au_labor_handoff import (
        leading_block_from_frozen,
        merge_research_supplement,
    )

    stub = {
        "summary": "Stub provider: no live model research after trusted freeze.",
        "news": [],
        "central_bank_research": [],
        "sources": [],
    }
    merged = merge_research_supplement(stub, leading_block_from_frozen(base_packet))
    from scripts.prima_pressure.handoff import block_from_frozen, merge_prima_research

    return merge_prima_research(merged, block_from_frozen(base_packet))


def _frozen_cross_assets(packet: dict[str, Any]) -> dict[str, Any]:
    from scripts.cross_asset_data import frozen_cross_assets_from_evidence

    return frozen_cross_assets_from_evidence(packet)


def _skeptic_funding_view() -> dict[str, Any]:
    return {
        "current_sofr": "Frozen official NY Fed SOFR fixing in funding_context.",
        "sr3_forward_view": "Frozen SR3 contracts are the relevant forward-funding path.",
        "forward_funding_assessment": "about_the_same",
        "implication": "Remain at the zero official-SOFR benchmark unless a packet-supported trade beats SOFR charged on shocked-risk capital. Flat cash is not alpha.",
    }


def _hold_decision(
    seat: str,
    run_id: str,
    packet_hash: str,
    cutoff: str,
) -> dict[str, Any]:
    thesis = (
        "Voluntary stub HOLD for manual launch mock; not a data-quality substitute."
    )
    row: dict[str, Any] = {
        "seat": seat,
        "overnight_run_id": run_id,
        "packet_sha256": packet_hash,
        "evidence_cutoff": cutoff,
        "conviction": 25,
        "thesis": thesis,
        "invalidation": None,
        "required_pitch": None,
        "risk_put_on": None,
        "expression_memo": {
            "rates_candidate": None,
            "spot_candidate": None,
            "options_candidate": None,
            "selected": "none",
            "rationale": "Voluntary stub HOLD; retain existing risk.",
        },
        "actions": [
            {
                "action": "HOLD",
                "expression_memo": {
                    "rates_candidate": None,
                    "spot_candidate": None,
                    "options_candidate": None,
                    "selected": "none",
                    "rationale": "Voluntary stub HOLD; retain existing risk.",
                },
            }
        ],
        "alerts": [],
    }
    if seat == "no-trade-skeptic":
        row["funding_view"] = _skeptic_funding_view()
    return row


def _pm_block(
    run_id: str,
    packet_hash: str,
    cutoff: str,
    memory_hashes: dict[str, str] | None,
    principal_model: str,
) -> dict[str, Any]:
    block = dry_run_pm_decisions(
        overnight_run_id=run_id,
        packet_sha256=packet_hash,
        evidence_cutoff=cutoff,
        memory_hashes=memory_hashes,
        principal_model=principal_model,
    )
    for pm_id, row in block.items():
        row["thesis"] = "Voluntary stub HOLD for manual launch mock; not a data-quality substitute."
        row["conviction"] = 20
        if pm_id == "pragmatist":
            row["portfolio_construction"] = synthetic_portfolio_construction(
                existing_book="Pragmatist book is flat in this manual-launch fixture.",
                rationale="Voluntary stub HOLD; no independent markable complementary trade.",
            )
        if pm_id == "grinder":
            row["deployment_hurdle"] = synthetic_grinder_hurdle()
    return block


def build_stub_output(
    store: OvernightStore,
    *,
    launch: dict[str, Any],
    base_packet: dict[str, Any],
) -> dict[str, Any]:
    run_id = base_packet["overnight_run_id"]
    review_id = base_packet["review_id"]
    base_hash = base_packet["packet_sha256"]
    cutoff = base_packet["as_of"]
    memory_hashes = (base_packet.get("seat_memory") or {}).get("hashes") or {}
    pm_memory = (base_packet.get("pm_memory") or {}).get("hashes") or {}

    pin = agent_config.assert_acceptable_pin(agent_config.pin_from_artifact(base_packet, kind="daily"))
    trader_ids = agent_config.pin_trader_ids(pin)
    budget = pin["budget"]
    if agent_config.legacy_equivalent(pin):
        allowed_subagent_models = ["composer-2.5", "grok-4.6"]
    else:
        roles = pin["roles"]
        allowed_subagent_models = sorted(
            {
                roles["trader"],
                roles["pm_principal"],
                roles["synthesis"],
                roles["learning_examiner"],
            }
        )

    agent_packet: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "type": AGENT_PACKET_TYPE,
        "overnight_run_id": run_id,
        "review_id": review_id,
        "base_packet_sha256": base_hash,
        "base_evidence_cutoff": base_packet["as_of"],
        "evidence_cutoff": cutoff,
        "competition": base_packet.get("competition"),
        "research_supplement": _research_supplement(base_packet),
        "cross_assets": _frozen_cross_assets(base_packet),
        "trade_permissions": base_packet.get("trade_permissions"),
    }
    agent_packet["packet_sha256"] = sha256_json(agent_packet)
    packet_hash = agent_packet["packet_sha256"]

    return {
        "schema_version": SCHEMA_VERSION,
        "type": "OVERNIGHT_SCHEDULED_OUTPUT",
        "schedule_id": SCHEDULE_ID,
        "overnight_run_id": run_id,
        "review_id": review_id,
        "base_packet_sha256": base_hash,
        "launch_id": launch["launch_id"],
        "launcher_id": LAUNCHER_ID,
        "provider": "stub",
        "agent_packet": agent_packet,
        "decisions": {
            seat: _hold_decision(seat, run_id, packet_hash, cutoff) for seat in trader_ids
        },
        "pm_decisions": _pm_block(
            run_id,
            packet_hash,
            cutoff,
            pm_memory or memory_hashes,
            pin["roles"]["pm_principal"],
        ),
        "execution": {
            "parent_model": pin["roles"]["parent"],
            "allowed_subagent_models": allowed_subagent_models,
            "total_model_cap": budget["total_calls"],
            "grok_cap": budget["grok_family_calls"],
            "composer_cap": budget["composer_calls"],
            "declared_total_model_calls": budget["total_calls"],
            "declared_grok_calls": budget["grok_family_calls"],
            "declared_composer_calls": budget["composer_calls"],
            "other_models_calls": 0,
            "auto_used": False,
        },
    }
