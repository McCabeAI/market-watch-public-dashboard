"""Pragmatist portfolio-construction contract.

Opportunistic mandate is unchanged. Before final actions the PM must inspect
its existing book and independent markable Trader Room opportunities, name the
main adverse scenario, and explain whether candidates complement, diversify,
offset, or duplicate beta. Flat and one-position outcomes remain valid.
"""

from __future__ import annotations

from typing import Any

from scripts.overnight.paper_marks import PaperMarkError, resolve_paper_mid
from scripts.pm.errors import SchemaError

PRAGMATIST_PM_ID = "pragmatist"
PORTFOLIO_CONSTRUCTION_FIELDS = (
    "existing_book_summary",
    "independent_handoff_opportunities",
    "adverse_scenario",
    "candidate_interactions",
    "chosen_actions_rationale",
    "rejected_complements",
)
INTERACTION_KINDS = ("complement", "diversify", "offset", "duplicate_beta", "unrelated")
EXPANDING_HANDOFF_ACTIONS = frozenset({"OPEN", "ADD", "HEDGE"})
MIN_INDEPENDENT_REVIEW = 2


def _non_empty_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaError(f"{field} must be a non-empty string")
    return value.strip()


def _instrument_key(value: Any) -> str:
    return str(value or "").strip().casefold()


def _row_instrument(item: dict[str, Any]) -> str:
    return str(item.get("instrument") or item.get("opportunity") or "").strip()


def _opportunity_row(item: Any, *, field: str) -> None:
    if not isinstance(item, dict):
        raise SchemaError(f"{field} entries must be objects")
    _non_empty_text(item.get("instrument") or item.get("opportunity"), f"{field}.instrument")
    _non_empty_text(item.get("rationale") or item.get("why_independent"), f"{field}.rationale")
    markable = item.get("markable")
    if markable not in (True, False, None):
        raise SchemaError(f"{field}.markable must be a boolean when supplied")


def _interaction_row(item: Any, *, field: str) -> None:
    if not isinstance(item, dict):
        raise SchemaError(f"{field} entries must be objects")
    _non_empty_text(item.get("instrument") or item.get("candidate"), f"{field}.instrument")
    kind = item.get("interaction")
    if kind not in INTERACTION_KINDS:
        raise SchemaError(f"{field}.interaction must be one of {list(INTERACTION_KINDS)}")
    _non_empty_text(item.get("rationale"), f"{field}.rationale")


def _rejected_row(item: Any, *, field: str) -> None:
    if not isinstance(item, dict):
        raise SchemaError(f"{field} entries must be objects")
    _non_empty_text(item.get("instrument") or item.get("candidate"), f"{field}.instrument")
    _non_empty_text(item.get("reason") or item.get("rationale"), f"{field}.reason")


def synthetic_portfolio_construction(
    *,
    existing_book: str = "Current book is empty / unchanged.",
    adverse: str = "The main adverse path is a reversal of the current book’s primary factor.",
    opportunities: list[dict[str, Any]] | None = None,
    rejected: list[dict[str, Any]] | None = None,
    interactions: list[dict[str, Any]] | None = None,
    rationale: str = "Hold the current opportunistic book; complementary candidates do not improve the portfolio.",
) -> dict[str, Any]:
    """Deterministic valid section for tests and dry-run fixtures."""
    opps = opportunities if opportunities is not None else []
    inter = interactions if interactions is not None else [
        {
            "instrument": row.get("instrument") or "handoff candidate",
            "interaction": "duplicate_beta",
            "rationale": "Does not improve the current opportunistic portfolio versus the adverse path.",
        }
        for row in opps
    ]
    rej = rejected if rejected is not None else [
        {
            "instrument": row.get("instrument") or "handoff candidate",
            "reason": "Does not improve the portfolio after the adverse-scenario check.",
        }
        for row in opps
    ]
    return {
        "existing_book_summary": existing_book,
        "independent_handoff_opportunities": opps,
        "adverse_scenario": adverse,
        "candidate_interactions": inter,
        "chosen_actions_rationale": rationale,
        "rejected_complements": rej,
    }


def _append_handoff_trade(
    rows: list[dict[str, Any]],
    *,
    instrument: Any,
    asset_class: Any = None,
    source: str,
) -> None:
    text = str(instrument or "").strip()
    if not text:
        return
    rows.append(
        {
            "instrument": text,
            "asset_class": asset_class if isinstance(asset_class, str) and asset_class.strip() else None,
            "source": source,
        }
    )


def _market_state_from_packet(packet: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(packet, dict):
        return None
    for candidate in (
        packet.get("market_state"),
        (packet.get("evidence") or {}).get("market_state") if isinstance(packet.get("evidence"), dict) else None,
        ((packet.get("agent_packet") or {}).get("market_state") if isinstance(packet.get("agent_packet"), dict) else None),
    ):
        if isinstance(candidate, dict) and candidate:
            return candidate
    return None


def packet_handoff_trades(packet: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Named Trader Room / overnight handoff trades visible in a frozen PM packet."""
    if not isinstance(packet, dict):
        return []
    rows: list[dict[str, Any]] = []

    trader_room = packet.get("trader_room")
    if isinstance(trader_room, dict):
        for item in trader_room.get("trades") or []:
            if not isinstance(item, dict):
                continue
            trade = item.get("trade")
            if isinstance(trade, dict):
                _append_handoff_trade(
                    rows,
                    instrument=trade.get("instrument"),
                    asset_class=trade.get("asset_class"),
                    source="trader_room",
                )

    overnight = packet.get("overnight_review")
    if isinstance(overnight, dict):
        for decision in overnight.get("decisions") or []:
            if not isinstance(decision, dict):
                continue
            for action in decision.get("actions") or []:
                if not isinstance(action, dict):
                    continue
                if action.get("action") not in EXPANDING_HANDOFF_ACTIONS and not action.get("instrument"):
                    continue
                if action.get("action") not in EXPANDING_HANDOFF_ACTIONS:
                    continue
                _append_handoff_trade(
                    rows,
                    instrument=action.get("instrument"),
                    asset_class=action.get("asset_class"),
                    source="overnight_review",
                )

    for item in packet.get("proposed_trades") or []:
        if not isinstance(item, dict):
            continue
        trade = item.get("trade")
        if isinstance(trade, dict):
            _append_handoff_trade(
                rows,
                instrument=trade.get("instrument"),
                asset_class=trade.get("asset_class"),
                source="proposed_trades",
            )

    decisions = packet.get("decisions")
    if isinstance(decisions, dict):
        for decision in decisions.values():
            if not isinstance(decision, dict):
                continue
            for action in decision.get("actions") or []:
                if not isinstance(action, dict) or action.get("action") not in EXPANDING_HANDOFF_ACTIONS:
                    continue
                _append_handoff_trade(
                    rows,
                    instrument=action.get("instrument"),
                    asset_class=action.get("asset_class"),
                    source="decisions",
                )
    return rows


def _is_markable(row: dict[str, Any], market_state: dict[str, Any] | None) -> bool:
    if not market_state:
        return False
    try:
        resolve_paper_mid(
            market_state,
            row["instrument"],
            asset_class=row.get("asset_class"),
        )
    except (PaperMarkError, SchemaError, TypeError, ValueError):
        return False
    return True


def independent_markable_handoff_opportunities(
    packet: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Unique packet instruments that trusted code can mark from frozen market state."""
    market_state = _market_state_from_packet(packet)
    seen: dict[str, dict[str, Any]] = {}
    for row in packet_handoff_trades(packet):
        key = _instrument_key(row["instrument"])
        if not key or key in seen:
            continue
        if _is_markable(row, market_state):
            seen[key] = row
    return list(seen.values())


def required_independent_opportunity_count(packet: dict[str, Any] | None) -> int:
    markable = independent_markable_handoff_opportunities(packet)
    if not markable:
        return 0
    return min(MIN_INDEPENDENT_REVIEW, len(markable))


def _assert_packet_opportunity_coverage(
    opportunities: list[Any],
    *,
    packet: dict[str, Any],
) -> None:
    handoff_rows = packet_handoff_trades(packet)
    handoff_keys = {_instrument_key(row["instrument"]) for row in handoff_rows if _instrument_key(row["instrument"])}
    markable = independent_markable_handoff_opportunities(packet)
    markable_keys = {_instrument_key(row["instrument"]) for row in markable}
    required = required_independent_opportunity_count(packet)

    listed_keys: list[str] = []
    for idx, row in enumerate(opportunities):
        if not isinstance(row, dict):
            continue
        key = _instrument_key(_row_instrument(row))
        field = f"pragmatist.portfolio_construction.independent_handoff_opportunities[{idx}]"
        if key not in handoff_keys:
            raise SchemaError(
                f"{field} instrument {_row_instrument(row)!r} is not traceable to the "
                "frozen PM packet/handoff"
            )
        listed_keys.append(key)

    covered = set(listed_keys) & markable_keys
    if len(covered) < required:
        available = [row["instrument"] for row in markable]
        raise SchemaError(
            "pragmatist.portfolio_construction.independent_handoff_opportunities must "
            f"enumerate/evaluate independent markable Trader Room alternatives from the "
            f"frozen packet (required {required}, covered {len(covered)}; "
            f"markable={available})"
        )


def validate_portfolio_construction(
    decision: dict[str, Any] | None,
    *,
    pm_id: str,
    required: bool = True,
    packet: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if pm_id != PRAGMATIST_PM_ID:
        return None
    payload = decision or {}
    section = payload.get("portfolio_construction")
    if section is None:
        if not required:
            return None
        raise SchemaError(
            "pragmatist must include portfolio_construction before final actions: "
            "existing book, independent handoff opportunities, adverse scenario, "
            "candidate interaction, and reasons for adding or rejecting complements"
        )
    if not isinstance(section, dict):
        raise SchemaError("pragmatist.portfolio_construction must be an object")
    missing = [key for key in PORTFOLIO_CONSTRUCTION_FIELDS if key not in section]
    if missing:
        raise SchemaError(f"pragmatist.portfolio_construction missing required fields: {missing}")
    _non_empty_text(section.get("existing_book_summary"), "pragmatist.portfolio_construction.existing_book_summary")
    _non_empty_text(section.get("adverse_scenario"), "pragmatist.portfolio_construction.adverse_scenario")
    _non_empty_text(
        section.get("chosen_actions_rationale"),
        "pragmatist.portfolio_construction.chosen_actions_rationale",
    )
    opportunities = section.get("independent_handoff_opportunities")
    if not isinstance(opportunities, list):
        raise SchemaError("pragmatist.portfolio_construction.independent_handoff_opportunities must be a list")
    for idx, row in enumerate(opportunities):
        _opportunity_row(row, field=f"pragmatist.portfolio_construction.independent_handoff_opportunities[{idx}]")
    interactions = section.get("candidate_interactions")
    if not isinstance(interactions, list):
        raise SchemaError("pragmatist.portfolio_construction.candidate_interactions must be a list")
    for idx, row in enumerate(interactions):
        _interaction_row(row, field=f"pragmatist.portfolio_construction.candidate_interactions[{idx}]")
    rejected = section.get("rejected_complements")
    if not isinstance(rejected, list):
        raise SchemaError("pragmatist.portfolio_construction.rejected_complements must be a list")
    for idx, row in enumerate(rejected):
        _rejected_row(row, field=f"pragmatist.portfolio_construction.rejected_complements[{idx}]")
    if opportunities and not rejected and not interactions:
        raise SchemaError(
            "pragmatist.portfolio_construction must evaluate independent handoff opportunities "
            "as complement/diversify/offset/duplicate_beta or explain rejected complements"
        )
    if packet is not None:
        _assert_packet_opportunity_coverage(opportunities, packet=packet)
    return section
