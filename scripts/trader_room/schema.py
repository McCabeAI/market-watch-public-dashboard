"""Deterministic trade, remit, conflict, and handoff validators."""

from __future__ import annotations

import re
from typing import Any

from scripts.funding.view import FundingViewError, assert_no_trade_funding_view
from scripts.trader_room.constants import (
    ADVOCATE_REMITS,
    ASSET_CLASSES,
    EXPRESSION_SELECTIONS,
    FORBIDDEN_RANKING_KEYS,
    HANDOFF_MARKER,
    NO_TRADE_AGENT,
    NULLABLE_LEVEL_FIELDS,
    RATES_FIRST_SEATS,
    SPOT_ONLY_SEATS,
    REQUIRED_TRADE_FIELDS,
    STANDING_ADVOCATES,
    TRADE_REQUIRED_AGENTS,
    VOL_SPECIALIST_SEAT,
)
from scripts.trader_room.errors import DataBoundaryError, SchemaError
from scripts.trader_room.evidence import assert_same_frozen_packet

LEVEL_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
SYNOPSIS_DIRECTION_VALUES = {"higher", "lower", "neutral", "not_relevant"}
SYNOPSIS_RISK_VALUES = {"risk_on", "risk_off", "neutral", "not_relevant"}
SYNOPSIS_CARRY_VALUES = {"supports_trade", "opposes_trade", "neutral", "not_relevant"}
SYNOPSIS_FIELDS = (
    "seat",
    "primary_trade",
    "core_view",
    "usd_view",
    "cad_view",
    "aud_view",
    "nzd_view",
    "us_rates_view",
    "ca_rates_view",
    "au_rates_view",
    "nz_rates_view",
    "risk_view",
    "carry_view",
    "time_horizon",
    "key_catalyst",
    "key_invalidation",
    "confidence",
    "conflict_tags",
)

CONTEXT_BUILD_FIELDS = (
    "causal_mechanism",
    "path_to_current_price",
    "known_vs_new_information",
    "market_implied_assumption",
    "market_assumption_disagreed_with",
    "price_decomposition",
    "historical_reference",
    "independent_checks",
    "flow_and_positioning_check",
    "policy_path_check",
)
HISTORICAL_REFERENCE_FIELDS = ("distribution", "analogs", "regime_differences")
POLICY_PATH_STATUSES = {"available", "not_applicable"}

PAPER_BOOK_ACTIONS = frozenset({"OPEN", "ADD", "HOLD", "REDUCE", "HEDGE", "CLOSE"})


def _validate_paper_action_row(row: Any, *, label: str) -> None:
    if not isinstance(row, dict):
        raise SchemaError(f"{label} paper_actions entries must be objects")
    kind = row.get("action")
    if kind not in PAPER_BOOK_ACTIONS:
        raise SchemaError(f"{label} paper_actions action must be one of {sorted(PAPER_BOOK_ACTIONS)}")
    asset_class = row.get("asset_class")
    if kind == "OPEN" and asset_class in {"rates", "curve", "rates_rv"}:
        expected = row.get("expected_mark_direction")
        if expected not in {"lower", "higher"}:
            raise SchemaError(
                f"{label} rates OPEN requires expected_mark_direction lower|higher"
            )
        required_side = "long" if expected == "lower" else "short"
        if row.get("side") != required_side:
            raise SchemaError(
                f"{label} rates OPEN side mismatch: expected_mark_direction={expected} "
                f"requires side={required_side} under the trusted P&L convention"
            )


def _validate_primary_trade_action_alignment(
    trade: dict[str, Any] | None,
    actions: Any,
    *,
    label: str,
) -> None:
    if not isinstance(trade, dict) or trade.get("asset_class") not in {"rates", "curve", "rates_rv"}:
        return
    if not isinstance(actions, list):
        return
    instrument = trade.get("instrument")
    for row in actions:
        if (
            isinstance(row, dict)
            and row.get("action") == "OPEN"
            and row.get("instrument") == instrument
            and row.get("asset_class") in {"rates", "curve", "rates_rv"}
        ):
            if trade.get("direction") != row.get("side"):
                raise SchemaError(
                    f"{label} primary rates trade direction must match the canonical paper-book side "
                    f"when both refer to {instrument}: trade.direction={trade.get('direction')} "
                    f"paper side={row.get('side')}"
                )


def _validate_paper_actions_list(value: Any, *, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise SchemaError(f"{label} paper_actions must be a list")
    if not value:
        raise SchemaError(f"{label} paper_actions must contain at least one final book action")
    for row in value:
        _validate_paper_action_row(row, label=label)


def _validate_paper_capital(value: Any, *, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise SchemaError(f"{label} paper_capital must be an object")
    kind = value.get("decision") or value.get("action")
    if kind is None:
        raise SchemaError(f"{label} paper_capital requires decision or action")
    if kind == "NO_TRADE":
        kind = "HOLD"
    if kind not in PAPER_BOOK_ACTIONS:
        raise SchemaError(f"{label} paper_capital decision/action invalid: {kind!r}")
    if kind == "HOLD":
        return
    if value.get("notional_usd") is not None:
        try:
            float(value["notional_usd"])
        except (TypeError, ValueError) as exc:
            raise SchemaError(f"{label} paper_capital.notional_usd must be numeric") from exc


FORBIDDEN_ACQUISITION = (
    "web_search",
    "web_fetch",
    "browse",
    "search_results",
    "new_evidence",
    "fresh_sources",
    "http_get",
)


def packet_ref_ids(packet: dict[str, Any]) -> set[str]:
    ids = {str(item.get("id")) for item in packet.get("source_index") or [] if item.get("id")}
    for key in ("temperature_gauges", "central_bank_research", "news_and_research"):
        for item in packet.get(key) or []:
            if item.get("id"):
                ids.add(str(item["id"]))
    if packet.get("market_state"):
        ids.add("market_state")
    if packet.get("research_method"):
        ids.add("research_method")
    return ids


def _require_keys(payload: dict[str, Any], keys: tuple[str, ...], label: str) -> None:
    missing = [k for k in keys if k not in payload]
    if missing:
        raise SchemaError(f"{label} missing required fields: {missing}")


def _non_empty_text(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SchemaError(f"{field} must be a non-empty string")


def _list_of_text(value: Any, field: str) -> None:
    if not isinstance(value, list) or not value or any(not isinstance(x, str) or not x.strip() for x in value):
        raise SchemaError(f"{field} must be a non-empty list of strings")


def validate_conflict_synopsis(
    synopsis: dict[str, Any],
    *,
    agent: str,
    confidence: int,
) -> None:
    if not isinstance(synopsis, dict):
        raise SchemaError(f"{agent}.conflict_synopsis must be an object")
    _require_keys(synopsis, SYNOPSIS_FIELDS, f"{agent}.conflict_synopsis")
    if synopsis["seat"] != agent:
        raise SchemaError(f"{agent}.conflict_synopsis.seat mismatch")
    if synopsis["confidence"] != confidence:
        raise SchemaError(f"{agent}.conflict_synopsis.confidence must match contribution confidence")
    for field in ("primary_trade", "core_view", "time_horizon", "key_catalyst", "key_invalidation"):
        _non_empty_text(synopsis[field], f"{agent}.conflict_synopsis.{field}")
    for field in (
        "usd_view", "cad_view", "aud_view", "nzd_view",
        "us_rates_view", "ca_rates_view", "au_rates_view", "nz_rates_view",
    ):
        if synopsis[field] not in SYNOPSIS_DIRECTION_VALUES:
            raise SchemaError(f"{agent}.conflict_synopsis.{field} has invalid value {synopsis[field]!r}")
    if synopsis["risk_view"] not in SYNOPSIS_RISK_VALUES:
        raise SchemaError(f"{agent}.conflict_synopsis.risk_view invalid")
    if synopsis["carry_view"] not in SYNOPSIS_CARRY_VALUES:
        raise SchemaError(f"{agent}.conflict_synopsis.carry_view invalid")
    _list_of_text(synopsis["conflict_tags"], f"{agent}.conflict_synopsis.conflict_tags")


def validate_context_build(context: dict[str, Any], *, agent: str, trade: dict[str, Any], packet: dict[str, Any]) -> None:
    if not isinstance(context, dict):
        raise SchemaError(f"{agent}.trade.context_build must be an object")
    _require_keys(context, CONTEXT_BUILD_FIELDS, f"{agent}.trade.context_build")
    for field in (
        "causal_mechanism",
        "path_to_current_price",
        "known_vs_new_information",
        "market_implied_assumption",
        "market_assumption_disagreed_with",
        "price_decomposition",
        "flow_and_positioning_check",
    ):
        _non_empty_text(context[field], f"{agent}.trade.context_build.{field}")

    checks = context["independent_checks"]
    if not isinstance(checks, list) or len(checks) < 2 or any(not isinstance(x, str) or not x.strip() for x in checks):
        raise SchemaError(f"{agent}.trade.context_build.independent_checks must contain at least two non-empty checks")

    history = context["historical_reference"]
    if not isinstance(history, dict):
        raise SchemaError(f"{agent}.trade.context_build.historical_reference must be an object")
    _require_keys(history, HISTORICAL_REFERENCE_FIELDS, f"{agent}.trade.context_build.historical_reference")
    _non_empty_text(history["distribution"], f"{agent}.trade.context_build.historical_reference.distribution")
    _non_empty_text(history["regime_differences"], f"{agent}.trade.context_build.historical_reference.regime_differences")
    analogs = history["analogs"]
    if not isinstance(analogs, list) or not analogs or any(not isinstance(x, str) or not x.strip() for x in analogs):
        raise SchemaError(
            f"{agent}.trade.context_build.historical_reference.analogs must contain at least one comparable episode "
            "or an explicit statement that no credible analog exists"
        )

    policy = context["policy_path_check"]
    if not isinstance(policy, dict):
        raise SchemaError(f"{agent}.trade.context_build.policy_path_check must be an object")
    _require_keys(policy, ("status", "relevant_countries", "pricing_summary", "rationale"), f"{agent}.trade.context_build.policy_path_check")
    if policy["status"] not in POLICY_PATH_STATUSES:
        raise SchemaError(f"{agent}.trade.context_build.policy_path_check.status invalid")
    _non_empty_text(policy["pricing_summary"], f"{agent}.trade.context_build.policy_path_check.pricing_summary")
    _non_empty_text(policy["rationale"], f"{agent}.trade.context_build.policy_path_check.rationale")
    countries = policy["relevant_countries"]
    if not isinstance(countries, list) or any(c not in {"US", "CA", "AU", "NZ", "EA", "UK", "JP"} for c in countries):
        raise SchemaError(f"{agent}.trade.context_build.policy_path_check.relevant_countries invalid")

    rates_trade = trade.get("asset_class") in {"rates", "curve", "rates_rv"}
    short_policy_tenor = bool(re.search(r"(?:^|[_\s-])2Y\b|\b2s", str(trade.get("instrument") or ""), re.I))
    if rates_trade and short_policy_tenor and any(c in {"US", "CA", "AU"} for c in countries):
        if policy["status"] != "available":
            raise SchemaError(
                f"{agent} short-end rates trade requires available US/CA/AU policy-path pricing; "
                "a sovereign yield percentile is not a substitute"
            )
        market_paths = ((packet.get("market_state") or {}).get("policy_paths") or {}).get("countries") or {}
        missing = [c for c in countries if c in {"US", "CA", "AU"} and (market_paths.get(c) or {}).get("status") != "ok"]
        if missing:
            raise SchemaError(f"{agent} policy_path_check says available but packet lacks live paths for {missing}")


def _validate_expression_comparison(trade: dict[str, Any], *, agent: str) -> None:
    asset_class = trade["asset_class"]
    if asset_class not in ASSET_CLASSES:
        raise SchemaError(f"{agent}.trade.asset_class invalid: {asset_class!r}")

    comparison = trade["expression_comparison"]
    if not isinstance(comparison, dict):
        raise SchemaError(f"{agent}.trade.expression_comparison must be an object")
    _require_keys(
        comparison,
        ("rates_candidate", "spot_candidate", "selected", "rationale"),
        f"{agent}.trade.expression_comparison",
    )
    selected = comparison["selected"]
    if selected not in EXPRESSION_SELECTIONS:
        raise SchemaError(f"{agent}.trade.expression_comparison.selected invalid: {selected!r}")
    _non_empty_text(comparison["rationale"], f"{agent}.trade.expression_comparison.rationale")

    selected_asset_ok = {
        "rates": asset_class in {"rates", "curve", "rates_rv"},
        "spot": asset_class == "spot_fx",
        "options": asset_class == "options",
    }
    if not selected_asset_ok[selected]:
        raise SchemaError(
            f"{agent}.trade.asset_class {asset_class!r} does not match selected expression {selected!r}"
        )

    if agent in SPOT_ONLY_SEATS:
        if selected != "spot":
            raise SchemaError(f"{agent} is a dedicated spot-FX seat and must select spot")
        _non_empty_text(comparison["spot_candidate"], f"{agent}.trade.expression_comparison.spot_candidate")
        return

    if agent == VOL_SPECIALIST_SEAT:
        if selected != "options":
            raise SchemaError(f"{agent} is the dedicated vol/options seat and must select options")
        return

    if agent in RATES_FIRST_SEATS:
        _non_empty_text(comparison["rates_candidate"], f"{agent}.trade.expression_comparison.rates_candidate")
        _non_empty_text(comparison["spot_candidate"], f"{agent}.trade.expression_comparison.spot_candidate")


def validate_trade(
    trade: dict[str, Any] | None,
    *,
    agent: str,
    packet: dict[str, Any],
) -> None:
    if trade is None:
        if agent != NO_TRADE_AGENT:
            raise SchemaError(f"{agent} must submit one actionable trade; trade is null")
        return
    if not isinstance(trade, dict):
        raise SchemaError(f"{agent} trade must be an object or null")
    _require_keys(trade, REQUIRED_TRADE_FIELDS, f"{agent} trade")
    _validate_expression_comparison(trade, agent=agent)
    validate_context_build(trade["context_build"], agent=agent, trade=trade, packet=packet)
    for field in ("instrument", "direction", "thesis", "mispricing", "horizon"):
        _non_empty_text(trade[field], f"{agent}.trade.{field}")
    for field in ("why_now", "evidence_refs", "catalysts", "principal_risks"):
        _list_of_text(trade[field], f"{agent}.trade.{field}")
    confidence = trade["confidence"]
    if not isinstance(confidence, int) or not 0 <= confidence <= 100:
        raise SchemaError(f"{agent} trade.confidence must be int 0-100")
    allowed = packet_ref_ids(packet)
    unknown = [ref for ref in trade["evidence_refs"] if ref not in allowed]
    if unknown:
        raise DataBoundaryError(f"{agent} evidence_refs not in frozen packet: {unknown}")
    for field in NULLABLE_LEVEL_FIELDS:
        value = trade[field]
        if value is None:
            continue
        if field == "structure":
            _non_empty_text(value, f"{agent}.trade.structure")
            continue
        if not isinstance(value, str) or not value.strip():
            raise SchemaError(f"{agent}.trade.{field} must be null or a sourced string")
        if LEVEL_RE.search(value) and not trade["evidence_refs"]:
            raise SchemaError(f"{agent}.trade.{field} has a level but no evidence_refs")
    invented = trade.get("invented_levels")
    if invented:
        raise SchemaError(f"{agent} must use explicit nulls rather than invented levels")


def assert_data_only_boundary(payload: dict[str, Any], packet: dict[str, Any], label: str) -> None:
    blob = str(payload)
    for key in FORBIDDEN_ACQUISITION:
        if key in payload:
            raise DataBoundaryError(f"{label} used forbidden acquisition field {key}")
        if f'"{key}"' in blob and key in payload.get("tools_used", []):
            raise DataBoundaryError(f"{label} recorded forbidden tool {key}")
    if payload.get("packet_sha256") and payload["packet_sha256"] != packet.get("packet_sha256"):
        raise DataBoundaryError(f"{label} packet hash mismatch")
    supplied = payload.get("evidence_packet")
    if supplied is not None:
        assert_same_frozen_packet(packet, supplied)


def validate_contribution(
    contribution: dict[str, Any],
    *,
    packet: dict[str, Any],
    expected_agent: str | None = None,
) -> dict[str, Any]:
    _require_keys(
        contribution,
        ("type", "run_id", "round", "agent", "archetype", "stance_summary", "trade", "confidence", "remit", "conflict_synopsis"),
        "contribution",
    )
    if contribution["type"] != "TRADER_ROOM_CONTRIBUTION":
        raise SchemaError(f"contribution type must be TRADER_ROOM_CONTRIBUTION, got {contribution['type']}")
    if contribution["round"] != 1:
        raise SchemaError("initial contribution round must be 1")
    agent = contribution["agent"]
    if agent not in STANDING_ADVOCATES:
        raise SchemaError(f"unknown advocate {agent}")
    if expected_agent and agent != expected_agent:
        raise SchemaError(f"expected {expected_agent}, got {agent}")
    if contribution["run_id"] != packet["run_id"]:
        raise SchemaError("contribution run_id does not match frozen packet")
    if contribution["remit"] != ADVOCATE_REMITS[agent]:
        raise SchemaError(f"{agent} remit does not match standing remit")
    if not isinstance(contribution["confidence"], int) or not 0 <= contribution["confidence"] <= 100:
        raise SchemaError(f"{agent} confidence must be int 0-100")
    validate_conflict_synopsis(
        contribution["conflict_synopsis"],
        agent=agent,
        confidence=contribution["confidence"],
    )
    validate_trade(contribution["trade"], agent=agent, packet=packet)
    if agent in TRADE_REQUIRED_AGENTS and contribution["trade"] is None:
        raise SchemaError(f"{agent} must end with one cogent actionable trade")
    if agent == NO_TRADE_AGENT:
        try:
            assert_no_trade_funding_view(contribution, packet=packet)
        except FundingViewError as exc:
            raise SchemaError(str(exc)) from exc
    _validate_paper_actions_list(contribution.get("paper_actions"), label=agent)
    _validate_primary_trade_action_alignment(
        contribution.get("trade"),
        contribution.get("paper_actions"),
        label=agent,
    )
    _validate_paper_capital(contribution.get("paper_capital"), label=agent)
    if contribution.get("paper_actions") is None and contribution.get("paper_capital") is None:
        raise SchemaError(
            f"{agent} must declare an explicit paper_actions list or legacy paper_capital decision"
        )
    assert_data_only_boundary(contribution, packet, agent)
    return contribution


def validate_rebuttal(
    rebuttal: dict[str, Any],
    *,
    packet: dict[str, Any],
    expected_agent: str,
    allowed_opponents: set[str],
) -> dict[str, Any]:
    _require_keys(
        rebuttal,
        (
            "type",
            "run_id",
            "round",
            "agent",
            "opponents",
            "own_original_ref",
            "holes_in_opposing_case",
            "trade_change",
            "revised_trade",
            "attack",
            "defense",
        ),
        "rebuttal",
    )
    if rebuttal["type"] != "TRADER_ROOM_REBUTTAL":
        raise SchemaError("rebuttal type must be TRADER_ROOM_REBUTTAL")
    if rebuttal["round"] != 2:
        raise SchemaError("rebuttal round must be 2")
    if rebuttal["agent"] != expected_agent:
        raise SchemaError(f"rebuttal agent {rebuttal['agent']} != {expected_agent}")
    if rebuttal["run_id"] != packet["run_id"]:
        raise SchemaError("rebuttal run_id mismatch")
    if rebuttal["trade_change"] not in {"unchanged", "amended", "withdrawn"}:
        raise SchemaError("trade_change must be unchanged | amended | withdrawn")
    if not rebuttal.get("holes_in_opposing_case"):
        raise SchemaError(f"{expected_agent} must explicitly shoot holes in the opposing case")
    extra = set(rebuttal.get("opponents") or ()) - allowed_opponents
    if extra:
        raise SchemaError(f"{expected_agent} rebuttal opponents not in conflict routing: {sorted(extra)}")
    if rebuttal.get("subagent_calls"):
        raise SchemaError("rebuttal pass may not make additional subagent calls")
    if rebuttal["trade_change"] == "withdrawn":
        if expected_agent != NO_TRADE_AGENT and rebuttal["revised_trade"] is not None:
            raise SchemaError("withdrawn trade must be null")
    elif rebuttal["revised_trade"] is not None:
        validate_trade(rebuttal["revised_trade"], agent=expected_agent, packet=packet)
    if expected_agent == NO_TRADE_AGENT and rebuttal.get("trade_change") in {"amended", "withdrawn"}:
        try:
            assert_no_trade_funding_view({**rebuttal, "agent": expected_agent, "thesis": " ".join(rebuttal.get("defense") or [])}, packet=packet)
        except FundingViewError as exc:
            raise SchemaError(str(exc)) from exc
    _validate_paper_actions_list(rebuttal.get("paper_actions"), label=f"{expected_agent} rebuttal")
    _validate_primary_trade_action_alignment(
        rebuttal.get("revised_trade"),
        rebuttal.get("paper_actions"),
        label=f"{expected_agent} rebuttal",
    )
    _validate_paper_capital(rebuttal.get("paper_capital"), label=f"{expected_agent} rebuttal")
    if rebuttal["trade_change"] in {"amended", "withdrawn"}:
        if rebuttal.get("paper_actions") is None and rebuttal.get("paper_capital") is None:
            raise SchemaError(
                f"{expected_agent} {rebuttal['trade_change']} rebuttal must declare the final paper book action set"
            )
        final_actions = list(rebuttal.get("paper_actions") or [])
        if rebuttal.get("paper_capital"):
            legacy_kind = rebuttal["paper_capital"].get("decision") or rebuttal["paper_capital"].get("action")
            if legacy_kind == "NO_TRADE":
                legacy_kind = "HOLD"
            final_actions.append({"action": legacy_kind})
        if rebuttal["trade_change"] == "withdrawn":
            expanding = [
                row.get("action")
                for row in final_actions
                if row.get("action") in {"OPEN", "ADD", "HEDGE"}
            ]
            if expanding:
                raise SchemaError(
                    f"{expected_agent} withdrawn rebuttal cannot leave expanding paper actions: {expanding}"
                )
    assert_data_only_boundary(rebuttal, packet, f"{expected_agent} rebuttal")
    return rebuttal


def _assert_no_ranking(payload: dict[str, Any], label: str) -> None:
    for key in FORBIDDEN_RANKING_KEYS:
        if key in payload:
            raise SchemaError(f"{label} must not include {key}")


def validate_conflict_map(conflict_map: dict[str, Any], originals: dict[str, dict[str, Any]]) -> dict[str, Any]:
    _require_keys(conflict_map, ("type", "run_id", "conflicts"), "conflict map")
    if conflict_map["type"] != "TRADER_ROOM_CONFLICT_MAP":
        raise SchemaError("conflict map type must be TRADER_ROOM_CONFLICT_MAP")
    _assert_no_ranking(conflict_map, "conflict aggregator")
    seen_ids: set[str] = set()
    for conflict in conflict_map["conflicts"]:
        _require_keys(conflict, ("id", "kind", "agents", "opposing_trades", "description"), "conflict")
        if conflict["id"] in seen_ids:
            raise SchemaError(f"duplicate conflict id {conflict['id']}")
        seen_ids.add(conflict["id"])
        agents = conflict["agents"]
        if len(agents) < 2:
            raise SchemaError(f"conflict {conflict['id']} needs at least two agents")
        unknown = [a for a in agents if a not in originals]
        if unknown:
            raise SchemaError(f"conflict {conflict['id']} unknown agents {unknown}")
        _assert_no_ranking(conflict, f"conflict {conflict['id']}")
    return conflict_map


def validate_pm_handoff(
    handoff: dict[str, Any],
    *,
    packet: dict[str, Any],
    originals: dict[str, dict[str, Any]],
    conflict_map: dict[str, Any],
    rebuttals: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    required = (
        "type",
        "run_id",
        "evidence_cutoff",
        "proposed_trades",
        "agreement_clusters",
        "conflicts",
        "strongest_evidence_by_side",
        "rebuttals",
        "amendments_and_withdrawals",
        "shared_assumptions",
        "unresolved_questions_and_gaps",
        "artifact_index",
        "status",
    )
    _require_keys(handoff, required, "PM handoff")
    if handoff["type"] != "TRADER_ROOM_PM_HANDOFF":
        raise SchemaError("handoff type must be TRADER_ROOM_PM_HANDOFF")
    if handoff["run_id"] != packet["run_id"]:
        raise SchemaError("handoff run_id mismatch")
    if handoff["evidence_cutoff"] != packet["as_of"]:
        raise SchemaError("handoff evidence_cutoff must equal packet as_of")
    if handoff["status"] != HANDOFF_MARKER:
        raise SchemaError(f"handoff status must be exactly {HANDOFF_MARKER}")
    _assert_no_ranking(handoff, "final aggregator")
    proposed_agents = {item["agent"] for item in handoff["proposed_trades"]}
    if proposed_agents != set(originals):
        raise SchemaError("PM handoff must preserve every original proposed trade")
    if set(handoff["rebuttals"]) != set(rebuttals):
        raise SchemaError("PM handoff must preserve every rebuttal")
    index = handoff["artifact_index"]
    for agent in originals:
        if agent not in (index.get("submissions") or {}):
            raise SchemaError(f"artifact index missing submission for {agent}")
    for agent in rebuttals:
        if agent not in (index.get("rebuttals") or {}):
            raise SchemaError(f"artifact index missing rebuttal for {agent}")
    if "evidence_packet" not in index or "conflict_map" not in index:
        raise SchemaError("artifact index missing evidence_packet or conflict_map")
    if len(handoff["conflicts"]) != len(conflict_map["conflicts"]):
        raise SchemaError("PM handoff conflict count does not match conflict map")
    return handoff
