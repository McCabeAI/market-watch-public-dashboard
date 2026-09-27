"""Detect psychology events from one identity's own accepted cycle and append them.

The detector reads ledger, journal, learning, and consequence facts. It writes only
psychology_events.json and psychology_state.json.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from scripts.overnight.clock import isoformat, now_ny
from scripts.overnight.constants import MAX_DRAWDOWN_USD, STARTING_NAV_USD
from scripts.pm.constants import CASH_CAPITAL_USD
from scripts.pm.constants import MAX_DRAWDOWN_USD as PM_MAX_DRAWDOWN_USD
from scripts.trading.constants import (
    EXPANDING_ACTIONS,
    MATERIAL_DRAWDOWN_FRACTION,
    PSYCH_DEAD_BAND_FRACTION,
    PSYCH_UNIT_FRACTION,
)
from scripts.trading.psychology import (
    empty_events_doc,
    fold_cycle,
    seed_state,
    state_digest,
)
from scripts.trading.psychology_profiles import is_not_applicable
from scripts.trading.store import TradingStore

_STANDING_RANK = {"good_standing": 0, "watch": 1, "probation": 2}


def _scale(owner_type: str) -> tuple[float, float, float]:
    max_dd = MAX_DRAWDOWN_USD if owner_type == "trader" else PM_MAX_DRAWDOWN_USD
    material = MATERIAL_DRAWDOWN_FRACTION * max_dd
    starting = STARTING_NAV_USD if owner_type == "trader" else CASH_CAPITAL_USD
    return PSYCH_UNIT_FRACTION * material, PSYCH_DEAD_BAND_FRACTION * material, float(starting)


def _magnitude(delta: float, unit: float, dead: float) -> float:
    if abs(delta) < dead or unit <= 0:
        return 0.0
    return min(1.0, abs(delta) / unit)


def revenge_family(instrument: str | None, asset_class: str | None = None, expression: Any = None) -> str:
    try:
        from scripts.pm.curve_lock import expression_family

        family = expression_family(instrument, asset_class, expression if isinstance(expression, dict) else None)
    except Exception:
        family = "other"
    if family in {"sofr", "corra", "aonia", "bond", "options"}:
        return str(family)
    token = str(instrument or "").upper().replace(" ", "")
    return token or str(family or "other")


def _event(kind: str, magnitude: float, subject: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    row = {"kind": kind, "magnitude": magnitude, "subject": subject or {}, "source": extra.get("source") or {"layer": "L1"}}
    for key in ("scale", "soften", "provenance", "mismatch"):
        if key in extra:
            row[key] = extra[key]
    return row


def _close_event(trade: dict[str, Any]) -> dict[str, Any] | None:
    for event in reversed(trade.get("events") or []):
        if isinstance(event, dict) and event.get("kind") == "CLOSE":
            return event
    return None


def _open_run(trade: dict[str, Any]) -> str | None:
    for event in trade.get("events") or []:
        if isinstance(event, dict) and event.get("kind") in {"OPEN", "HEDGE"}:
            return event.get("run_id")
    return trade.get("opened_run_id")


def detect_cycle_events(
    *,
    owner_type: str,
    owner_id: str,
    state: dict[str, Any],
    consequence: dict[str, Any] | None,
    prior: dict[str, Any] | None,
    decision: dict[str, Any] | None,
    blocked: list[dict[str, Any]] | None,
    trades: list[dict[str, Any]],
    reflections: list[dict[str, Any]],
    learning_state: dict[str, Any] | None,
    capital_standing: str | None,
    market_fresh: bool,
    run_id: str | None,
    positions: list[dict[str, Any]] | None,
    journal_events: list[dict[str, Any]] | None = None,
    postmortems: list[dict[str, Any]] | None = None,
    alerts: list[Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return event specs plus annotations. No writes."""
    unit, dead, starting = _scale(owner_type)
    events: list[dict[str, Any]] = []
    consequence = consequence or {}
    prior = prior or {}
    decision = decision or {}
    learning_state = learning_state or {}
    annotations: dict[str, Any] = {
        "learning_status": learning_state.get("learning_status"),
        "standing": capital_standing,
        "repeated_counts": {},
    }

    session = consequence.get("session_pnl_change_usd")
    if isinstance(session, (int, float)):
        mag = _magnitude(float(session), unit, dead)
        if mag and float(session) > 0:
            events.append(_event("session_gain", mag, {"session_pnl_change_usd": session}))
        elif mag and float(session) < 0:
            events.append(_event("session_loss", mag, {"session_pnl_change_usd": session}))

    rank_change = consequence.get("rank_change")
    if isinstance(rank_change, int):
        if rank_change >= 4:
            events.append(_event("rank_shock", 1.0, {"rank_change": rank_change}))
        elif rank_change in {2, 3}:
            events.append(_event("rank_drop_minor", 1.0, {"rank_change": rank_change}))
        elif rank_change <= -3:
            events.append(_event("rank_gain_major", 1.0, {"rank_change": rank_change}))

    high_water = consequence.get("high_water_nav_usd")
    drawdown = consequence.get("drawdown_usd")
    prior_hw = prior.get("last_high_water_nav_usd")
    prior_hw = float(prior_hw) if isinstance(prior_hw, (int, float)) else starting
    prior_dd = prior.get("last_drawdown_usd")
    prior_dd = float(prior_dd) if isinstance(prior_dd, (int, float)) else 0.0
    if isinstance(high_water, (int, float)) and isinstance(drawdown, (int, float)):
        if float(high_water) > starting and prior_dd < unit <= float(drawdown):
            events.append(_event("giveback", _magnitude(float(drawdown), unit, dead) or 1.0, {"drawdown_usd": drawdown}))
        rose = float(high_water) - prior_hw
        if rose >= unit and float(high_water) > starting:
            events.append(_event("new_high", _magnitude(rose, unit, dead) or 1.0, {"high_water_delta_usd": rose}))

    expression_trades = set()
    for reflection in reflections:
        if run_id and reflection.get("run_id") not in (None, run_id):
            continue
        if reflection.get("chase_or_revenge") == "yes":
            events.append(_event("self_report_admission_chase_or_revenge", 1.0, {"reflection_id": reflection.get("reflection_id")}, source={"layer": "self_report"}))
        if reflection.get("overconfidence_risk") == "yes":
            events.append(_event("self_report_admission_overconfidence", 1.0, {"reflection_id": reflection.get("reflection_id")}, source={"layer": "self_report"}))
        if reflection.get("pressure_effect") == "distorting":
            events.append(_event("self_report_admission_pressure_distorting", 1.0, {"reflection_id": reflection.get("reflection_id")}, source={"layer": "self_report"}))
        attribution = reflection.get("attribution") or []
        causal = reflection.get("causal") if isinstance(reflection.get("causal"), dict) else {}
        if "expression" in attribution or causal.get("decision_quality_attribution") == "expression":
            for trade_id in reflection.get("trade_ids") or []:
                expression_trades.add(trade_id)

    check = decision.get("psychology_check") if isinstance(decision.get("psychology_check"), dict) else {}
    answers = check.get("answers") if isinstance(check.get("answers"), dict) else {}
    rank_answers = answers.get("rank_distortion_risk") if isinstance(answers.get("rank_distortion_risk"), dict) else {}
    if rank_answers.get("pressure_read") == "distorting":
        events.append(_event("self_report_admission_pressure_distorting", 1.0, {"source": "psychology_check"}, source={"layer": "self_report"}))

    dispositions = {
        str(row.get("lesson_id")): row
        for row in (learning_state.get("retrieved_lessons") or [])
        if isinstance(row, dict) and row.get("disposition")
    }
    alert_rows = list(decision.get("alerts") or []) + list(alerts or [])
    forced_flat = any("max drawdown breached" in str(alert).lower() for alert in alert_rows)
    for trade in trades:
        if trade.get("status") != "closed" or trade.get("closed_run_id") != run_id:
            continue
        close = _close_event(trade) or {}
        realized = float(trade.get("realized_pnl_usd") or 0.0)
        category = close.get("exit_reason_category") or trade.get("exit_reason_category")
        family = revenge_family(trade.get("instrument"), trade.get("asset_class"), trade.get("paper_expression"))
        subject = {
            "trade_id": trade.get("trade_id"),
            "family": family,
            "side": trade.get("side"),
            "notional_usd": trade.get("initial_notional_usd"),
            "realized_pnl_usd": realized,
        }
        risk_cut = category == "risk_cut" or forced_flat
        mag = _magnitude(realized, unit, dead)
        if risk_cut and (mag or forced_flat):
            events.append(_event("stop_or_risk_cut_close", mag or 1.0, subject))
        elif mag and realized > 0:
            events.append(_event("trade_win_close", mag, subject))
        elif mag and realized < 0:
            soften = trade.get("trade_id") in expression_trades
            events.append(_event("trade_loss_close", mag, subject, soften=soften))
        open_run = _open_run(trade)
        opening = [
            row for row in (learning_state.get("retrieved_lessons") or [])
            if isinstance(row, dict) and row.get("run_id") == open_run and row.get("disposition")
        ]
        if mag or realized >= 0:
            if any(row.get("disposition") in {"OVERRIDE", "DOES_NOT_APPLY"} for row in opening) and realized < -dead:
                events.append(_event("override_failed", mag, subject, source={"layer": "L3"}))
            if any(row.get("disposition") == "APPLIES" for row in opening) and realized >= 0:
                events.append(_event("correction_success", max(0.5, mag), subject, source={"layer": "L3"}))
            if any(row.get("disposition") == "OVERRIDE" for row in opening) and realized > dead:
                events.append(_event("override_vindicated", min(0.5, mag), subject, source={"layer": "L3"}))

    actions = [row for row in (decision.get("actions") or []) if isinstance(row, dict)]
    executed = {row.get("action") for row in actions}
    open_positions = positions or []
    flat_actions = bool(executed) and executed <= {"HOLD", "NO_TRADE"}
    no_positions = not open_positions
    prior_flat = int((state.get("streaks") or {}).get("flat_cycles") or 0)
    flat_cycles = prior_flat + 1 if flat_actions and no_positions else 0
    annotations["flat_cycles"] = flat_cycles
    if flat_cycles >= 3 and market_fresh and flat_actions and no_positions:
        events.append(_event("flat_with_market", 1.0, {"flat_cycles": flat_cycles}))

    blocked_n = 0
    for row in blocked or []:
        action = row.get("action") if isinstance(row.get("action"), dict) else row
        if isinstance(action, dict) and action.get("action") in EXPANDING_ACTIONS:
            blocked_n += 1
    for _index in range(min(2, blocked_n)):
        events.append(_event("blocked_expansion", 1.0, {"index": _index}))

    previous_status = state.get("last_learning_status")
    status = learning_state.get("learning_status")
    if status == "learning_default" and previous_status != "learning_default":
        events.append(_event("learning_default_entered", 1.0, {"learning_status": status}, source={"layer": "L3"}))
    elif previous_status == "learning_default" and status and status != "learning_default":
        events.append(_event("learning_default_cleared", 1.0, {"learning_status": status}, source={"layer": "L3"}))

    previous_counts = dict(state.get("last_repeated_error_counts") or {})
    new_counts = {}
    escalations = 0
    for row in learning_state.get("repeated_error_escalations") or []:
        if not isinstance(row, dict) or not row.get("lesson_id"):
            continue
        lesson_id = str(row.get("lesson_id"))
        count = int(row.get("count") or 0)
        new_counts[lesson_id] = count
        if count > int(previous_counts.get(lesson_id) or 0) and escalations < 2:
            escalations += 1
            events.append(_event("lesson_contradicted_after_retrieval", 1.0, {"lesson_id": lesson_id, "count": count}, source={"layer": "L3"}))
    annotations["repeated_counts"] = new_counts

    active_tags = [tag for tag in ((state.get("tags") or {}).get("revenge") or []) if int(tag.get("ttl") or 0) > 0]
    win_streak = int((state.get("streaks") or {}).get("session_win") or 0)
    trailing = [float(value) for value in (state.get("trailing_open_risk_capital_usd") or [])]
    observed_risk: list[float] = []
    for action in actions:
        if action.get("action") not in {"OPEN", "ADD"}:
            continue
        family = revenge_family(action.get("instrument"), action.get("asset_class"), action.get("paper_expression"))
        notional = float(action.get("notional_usd") or 0.0)
        matched = [tag for tag in active_tags if tag.get("family") == family]
        if matched:
            lost = max(float(tag.get("loss_notional_usd") or 0.0) for tag in matched)
            scale = 1.5 if lost and notional > lost else 1.0
            events.append(_event("reentry_same_family_after_loss", 1.0, {"family": family}, scale=scale))
        risk = _action_risk_capital(action)
        if risk is not None:
            observed_risk.append(float(risk))
            mean = sum(trailing) / len(trailing) if trailing else 0.0
            if win_streak >= 2 and mean and float(risk) > 1.5 * mean:
                events.append(_event("size_escalation_after_streak", 1.0, {"risk_capital_usd": risk}))
    annotations["open_risk"] = (trailing + observed_risk)[-4:]

    previous_standing = state.get("last_capital_owner_standing")
    if capital_standing and previous_standing and capital_standing in _STANDING_RANK and previous_standing in _STANDING_RANK:
        if _STANDING_RANK[capital_standing] > _STANDING_RANK[previous_standing]:
            events.append(_event("allocator_standing_worsened", 1.0, {"standing_from": previous_standing, "standing_to": capital_standing}))
        elif capital_standing == "good_standing" and previous_standing != "good_standing":
            events.append(_event("allocator_standing_restored", 1.0, {"standing_from": previous_standing, "standing_to": capital_standing}))
    flags = set(consequence.get("pressure_flags") or [])
    if owner_type == "pm" and ({"behind_leading_pm", "best_trader_ahead"} & flags):
        events.append(_event("competitive_flag_active", 1.0, {}))

    painful = []
    for position in open_positions:
        unrealized = position.get("unrealized_pnl_usd")
        if isinstance(unrealized, (int, float)) and float(unrealized) <= -unit:
            painful.append(str(position.get("position_id") or ""))
    reduced = {str(action.get("position_id")) for action in actions if action.get("action") == "REDUCE"}
    hold_counts = dict((state.get("tags") or {}).get("hold_through_pain") or {})
    updated_counts = {}
    for position_id in painful:
        if position_id in reduced:
            continue
        count = int(hold_counts.get(position_id) or 0) + 1
        updated_counts[position_id] = count
        if 3 <= count <= 5:
            events.append(_event("hold_through_pain", 1.0, {"position_id": position_id}))
    annotations["hold_through_pain"] = updated_counts
    events.extend(
        _verdict_events(
            trades=trades,
            run_id=run_id,
            unit=unit,
            journal_events=journal_events or [],
            postmortems=postmortems or [],
            reflections=reflections,
            decision=decision,
            state=state,
            actions=actions,
        )
    )
    return events, annotations


def _action_risk_capital(action: dict[str, Any]) -> float | None:
    from scripts.risk_capital import position_risk_capital

    measured = position_risk_capital(action)
    if measured is not None:
        return float(measured)
    explicit = action.get("risk_capital_usd")
    if isinstance(explicit, (int, float)):
        return float(explicit)
    return None


def _opening_override_checks(trade: dict[str, Any], journal_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trade_id = trade.get("trade_id")
    checks: list[dict[str, Any]] = []
    for event in journal_events:
        if trade_id and trade_id not in (event.get("linked_trade_ids") or []):
            continue
        kinds = {row.get("action") for row in (event.get("actions") or []) if isinstance(row, dict)}
        if not kinds & {"OPEN", "ADD", "HEDGE"}:
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        psychology = payload.get("psychology") if isinstance(payload.get("psychology"), dict) else {}
        check = psychology.get("check") if isinstance(psychology.get("check"), dict) else None
        if check and check.get("proceed_despite_flags") is True:
            checks.append(check)
    return checks


def _linked_reflections(trade: dict[str, Any], reflections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trade_id = trade.get("trade_id")
    linked = []
    for reflection in reflections:
        if not isinstance(reflection, dict):
            continue
        if trade_id and trade_id in (reflection.get("trade_ids") or []):
            linked.append(reflection)
    return linked


def _postmortem_attributions(trade: dict[str, Any], postmortems: list[dict[str, Any]]) -> set[str]:
    trade_id = trade.get("trade_id")
    found: set[str] = set()
    for row in postmortems:
        if not isinstance(row, dict) or row.get("trade_id") != trade_id:
            continue
        causal = row.get("causal") if isinstance(row.get("causal"), dict) else {}
        attribution = causal.get("decision_quality_attribution")
        if attribution:
            found.add(str(attribution))
    return found


def _self_report_reads(reflections: list[dict[str, Any]], checks: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    effects: set[str] = set()
    reads: set[str] = set()
    for reflection in reflections:
        effect = reflection.get("pressure_effect")
        if effect:
            effects.add(str(effect))
    for check in checks:
        answers = check.get("answers") if isinstance(check.get("answers"), dict) else {}
        rank = answers.get("rank_distortion_risk") if isinstance(answers.get("rank_distortion_risk"), dict) else {}
        if rank.get("pressure_read"):
            reads.add(str(rank["pressure_read"]))
    return effects, reads


def _verdict_name(
    *,
    realized: float,
    unit: float,
    attributions: set[str],
    reflections: list[dict[str, Any]],
    exit_category: str | None,
) -> str:
    chase = any(row.get("chase_or_revenge") == "yes" for row in reflections)
    distorted_evidence = bool(attributions & {"sizing", "timing", "entry"}) or chase or exit_category == "risk_cut"
    if realized <= -unit and distorted_evidence:
        return "distorted"
    luck = any(row.get("skill_vs_luck") == "luck" for row in reflections)
    non_luck = any(row.get("skill_vs_luck") not in (None, "luck") for row in reflections)
    if realized >= unit and non_luck and not luck:
        return "sharpened"
    return "inconclusive"


def _mismatch(verdict: str, effects: set[str], reads: set[str]) -> bool:
    reported = set(effects) | set(reads)
    if verdict == "distorted" and reported & {"sharpening", "neither", "none"}:
        return True
    if verdict == "sharpened" and "distorting" in reported:
        return True
    return False


def _verdict_events(
    *,
    trades: list[dict[str, Any]],
    run_id: str | None,
    unit: float,
    journal_events: list[dict[str, Any]],
    postmortems: list[dict[str, Any]],
    reflections: list[dict[str, Any]],
    decision: dict[str, Any],
    state: dict[str, Any],
    actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for trade in trades:
        if trade.get("status") != "closed" or trade.get("closed_run_id") != run_id:
            continue
        checks = _opening_override_checks(trade, journal_events)
        if not checks:
            continue
        linked = _linked_reflections(trade, reflections)
        close = _close_event(trade) or {}
        category = close.get("exit_reason_category") or trade.get("exit_reason_category")
        realized = float(trade.get("realized_pnl_usd") or 0.0)
        verdict = _verdict_name(
            realized=realized,
            unit=unit,
            attributions=_postmortem_attributions(trade, postmortems),
            reflections=linked,
            exit_category=str(category) if category else None,
        )
        effects, reads = _self_report_reads(linked, checks)
        current_effects, current_reads = _self_report_reads(linked, [decision.get("psychology_check")] if isinstance(decision.get("psychology_check"), dict) else [])
        effects |= current_effects
        reads |= current_reads
        kind = {"distorted": "verdict_distorted", "sharpened": "verdict_sharpened"}.get(verdict, "verdict_inconclusive")
        found.append(
            _event(
                kind,
                1.0,
                {
                    "trade_id": trade.get("trade_id"),
                    "verdict": verdict,
                    "pressure_effect": sorted(effects),
                    "pressure_read": sorted(reads),
                    "realized_pnl_usd": realized,
                },
                source={"layer": "verdict"},
                mismatch=_mismatch(verdict, effects, reads),
            )
        )
    if found:
        return found
    active = {row.get("id") for row in (state.get("flags") or []) if isinstance(row, dict)}
    derisk = any(action.get("action") in {"REDUCE", "CLOSE"} for action in actions)
    if "capitulation_risk" in active and derisk:
        check = decision.get("psychology_check") if isinstance(decision.get("psychology_check"), dict) else {}
        answers = check.get("answers") if isinstance(check.get("answers"), dict) else {}
        row = answers.get("capitulation_risk") if isinstance(answers.get("capitulation_risk"), dict) else {}
        reason = row.get("derisk_reason")
        if reason in (None, "pnl_pain"):
            found.append(
                _event(
                    "verdict_inconclusive",
                    1.0,
                    {"verdict": "inconclusive", "reason": "capitulation_derisk", "derisk_reason": reason},
                    source={"layer": "verdict"},
                )
            )
    return found


def _cycle_key(run_id: str | None, review_id: str | None) -> tuple[str | None, str | None]:
    return (run_id, review_id)


def observe_psychology_cycle(
    store: TradingStore,
    owner_type: str,
    owner_id: str,
    *,
    run_id: str | None,
    review_id: str | None = None,
    review_packet_id: str | None = None,
    consequence_bundle: dict[str, Any] | None = None,
    decision: dict[str, Any] | None = None,
    blocked: list[dict[str, Any]] | None = None,
    market_fresh: bool = False,
    capital_standing: str | None = None,
    positions: list[dict[str, Any]] | None = None,
    alerts: list[Any] | None = None,
    when: datetime | None = None,
) -> dict[str, Any]:
    """Append one cycle if this run/review has not already been applied."""
    if is_not_applicable(owner_id):
        return store.read_psychology_state(owner_type, owner_id)
    state = store.read_psychology_state(owner_type, owner_id)
    if not state.get("applicable", True):
        return state
    review_key = review_id or review_packet_id
    doc = store.read_psychology_events(owner_type, owner_id)
    for row in doc.get("events") or []:
        if _cycle_key(row.get("run_id"), row.get("review_id")) == _cycle_key(run_id, review_key):
            return state
    from scripts.trading.learning import read_learning_state

    bundle = consequence_bundle or {}
    events, annotations = detect_cycle_events(
        owner_type=owner_type,
        owner_id=owner_id,
        state=state,
        consequence=bundle.get("consequence"),
        prior=bundle.get("prior"),
        decision=decision,
        blocked=blocked,
        trades=store.trades_for(owner_type, owner_id),
        reflections=list(store.read_reflections(owner_type, owner_id).get("items") or []),
        learning_state=read_learning_state(store, owner_type, owner_id),
        capital_standing=capital_standing,
        market_fresh=market_fresh,
        run_id=run_id,
        positions=positions,
        journal_events=list(store.read_journal(owner_type, owner_id).get("events") or []),
        postmortems=list(store.read_postmortems(owner_type, owner_id).get("items") or []),
        alerts=alerts,
    )
    new_state, records = fold_cycle(
        state,
        events,
        run_id=run_id,
        review_id=review_key,
        flat_cycles=annotations.get("flat_cycles"),
        annotations=annotations,
    )
    stamp = isoformat(now_ny(when))
    for record in records:
        record["event_id"] = f"pse-{record['seq']:06d}"
        record["at"] = stamp
        record["owner_id"] = owner_id
    doc.setdefault("events", []).extend(records)
    store.write_psychology_events(owner_type, owner_id, doc)
    new_state["state_sha256"] = state_digest(new_state)
    store.write_psychology_state(owner_type, owner_id, new_state)
    return new_state
