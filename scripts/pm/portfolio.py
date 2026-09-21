"""Pragmatist portfolio-construction contract.

Opportunistic mandate is unchanged. Before final actions the PM must inspect
its existing book and independent markable Trader Room opportunities, name the
main adverse scenario, and explain whether candidates complement, diversify,
offset, or duplicate beta. Flat and one-position outcomes remain valid.
"""

from __future__ import annotations

from typing import Any

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


def _non_empty_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaError(f"{field} must be a non-empty string")
    return value.strip()


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


def validate_portfolio_construction(
    decision: dict[str, Any] | None,
    *,
    pm_id: str,
    required: bool = True,
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
    return section
