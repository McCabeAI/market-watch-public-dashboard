"""Grinder deployment-hurdle contract.

Grinder may stay flat, but missing data is never a global veto. Before a
decision it must evaluate the best frozen, markable handoff candidates against
the SOFR funding hurdle and identify only candidate-specific missing data that
would materially change the edge/risk assessment.
"""

from __future__ import annotations

from typing import Any

from scripts.pm.errors import SchemaError
from scripts.pm.portfolio import (
    independent_markable_handoff_opportunities,
    packet_handoff_trades,
)

GRINDER_PM_ID = "grinder"
GRINDER_HURDLE_FIELD = "deployment_hurdle"
HURDLE_RESULTS = ("clears", "does_not_clear", "not_evaluable")
MIN_CANDIDATE_REVIEW = 2


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaError(f"{field} must be a non-empty string")
    return value.strip()


def _instrument_key(value: Any) -> str:
    return str(value or "").strip().casefold()


def synthetic_grinder_hurdle() -> dict[str, Any]:
    return {
        "benchmark": "Official NY Fed SOFR ACT/360 is the zero-alpha benchmark.",
        "candidate_assessments": [],
        "chosen_action_rationale": (
            "Deterministic dry-run: no live investment decision is being made."
        ),
    }


def _validate_gap_rows(value: Any, *, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise SchemaError(f"{field} must be a list")
    for idx, row in enumerate(value):
        if not isinstance(row, dict):
            raise SchemaError(f"{field}[{idx}] must be an object")
        _text(row.get("field"), f"{field}[{idx}].field")
        _text(row.get("relevance"), f"{field}[{idx}].relevance")


def _validate_candidate(row: Any, *, field: str) -> None:
    if not isinstance(row, dict):
        raise SchemaError(f"{field} entries must be objects")
    _text(row.get("instrument"), f"{field}.instrument")
    result = row.get("hurdle_result")
    if result not in HURDLE_RESULTS:
        raise SchemaError(f"{field}.hurdle_result must be one of {list(HURDLE_RESULTS)}")
    markable = row.get("markable")
    if markable not in (True, False):
        raise SchemaError(f"{field}.markable must be boolean")
    _text(row.get("rationale"), f"{field}.rationale")
    _validate_gap_rows(row.get("material_missing_data"), field=f"{field}.material_missing_data")
    ignored = row.get("ignored_unrelated_gaps", [])
    if not isinstance(ignored, list) or any(not isinstance(x, str) or not x.strip() for x in ignored):
        raise SchemaError(f"{field}.ignored_unrelated_gaps must be a list of non-empty strings")
    if result == "not_evaluable" and not row.get("material_missing_data"):
        raise SchemaError(
            f"{field} marked not_evaluable must name candidate-specific material_missing_data"
        )


def _assert_packet_coverage(candidates: list[Any], *, packet: dict[str, Any]) -> None:
    handoff_keys = {
        _instrument_key(row.get("instrument"))
        for row in packet_handoff_trades(packet)
        if _instrument_key(row.get("instrument"))
    }
    markable = independent_markable_handoff_opportunities(packet)
    markable_keys = {_instrument_key(row.get("instrument")) for row in markable}
    required = min(MIN_CANDIDATE_REVIEW, len(markable))

    covered: set[str] = set()
    for idx, row in enumerate(candidates):
        if not isinstance(row, dict):
            continue
        instrument = row.get("instrument")
        key = _instrument_key(instrument)
        if key not in handoff_keys:
            raise SchemaError(
                f"grinder.deployment_hurdle.candidate_assessments[{idx}] instrument "
                f"{instrument!r} is not traceable to the frozen PM packet/handoff"
            )
        if row.get("markable") and key in markable_keys:
            covered.add(key)

    if len(covered) < required:
        available = [row.get("instrument") for row in markable]
        raise SchemaError(
            "grinder.deployment_hurdle.candidate_assessments must evaluate the best "
            f"independent markable frozen handoff opportunities (required {required}, "
            f"covered {len(covered)}; markable={available})"
        )


def validate_grinder_hurdle(
    decision: dict[str, Any] | None,
    *,
    pm_id: str,
    required: bool = True,
    packet: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if pm_id != GRINDER_PM_ID:
        return None
    payload = decision or {}
    section = payload.get(GRINDER_HURDLE_FIELD)
    if section is None:
        if not required:
            return None
        raise SchemaError(
            "grinder must include deployment_hurdle: SOFR benchmark, candidate-by-candidate "
            "hurdle assessments, candidate-specific missing-data relevance, and chosen-action rationale"
        )
    if not isinstance(section, dict):
        raise SchemaError("grinder.deployment_hurdle must be an object")

    _text(section.get("benchmark"), "grinder.deployment_hurdle.benchmark")
    _text(
        section.get("chosen_action_rationale"),
        "grinder.deployment_hurdle.chosen_action_rationale",
    )
    candidates = section.get("candidate_assessments")
    if not isinstance(candidates, list):
        raise SchemaError("grinder.deployment_hurdle.candidate_assessments must be a list")
    for idx, row in enumerate(candidates):
        _validate_candidate(
            row,
            field=f"grinder.deployment_hurdle.candidate_assessments[{idx}]",
        )
    actions = payload.get("actions") or []
    is_no_trade = any(
        isinstance(row, dict) and row.get("action") == "NO_TRADE"
        for row in actions
    )
    if packet is not None and is_no_trade:
        _assert_packet_coverage(candidates, packet=packet)
    return section
