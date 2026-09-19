"""Apply trusted book actions, then persist ledger / journal / memory."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from scripts.overnight.books import apply_review, validate_books
from scripts.overnight.clock import now_ny
from scripts.overnight.constants import STANDING_SEATS
from scripts.pm.books import apply_decision as apply_pm_book_decision
from scripts.trading.gate import (
    action_rationale,
    assert_expansion_rationale,
    assert_learning_gate,
    rationale_status_for,
)
from scripts.trading.journal import record_event
from scripts.trading.ledger import find_trade_by_position, observe_open_mark, record_lifecycle_event
from scripts.trading.memory import apply_reflections, build_memory_context, create_postmortem_due
from scripts.trading.store import TradingStore


def _run_ids(run_id: str | None) -> tuple[str | None, str | None]:
    if not run_id:
        return None, None
    if str(run_id).startswith("overnight-"):
        return run_id, None
    if str(run_id).startswith("tr-"):
        return None, run_id
    return None, None


def _catalysts(action: dict[str, Any], decision: dict[str, Any]) -> list[str]:
    raw = action.get("catalysts") or decision.get("catalysts") or []
    if isinstance(raw, str):
        raw = [raw]
    return [str(item).strip() for item in raw if str(item).strip()]


def _priced(action: dict[str, Any], decision: dict[str, Any]) -> str | None:
    for key in ("priced_or_disagreed", "market_assumption_disagreed_with", "what_is_priced"):
        value = action.get(key) or decision.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    context = action.get("context_build") or decision.get("context_build")
    if isinstance(context, dict):
        value = context.get("market_assumption_disagreed_with")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _sync_history_row(
    store: TradingStore,
    *,
    owner_type: str,
    owner_id: str,
    row: dict[str, Any],
    decision: dict[str, Any],
    prior_positions: dict[str, dict[str, Any]],
    updated_positions: dict[str, dict[str, Any]],
    when: datetime,
    run_id: str | None,
    evidence_cutoff: str | None,
    evidence_hash: str | None,
    evidence_packet_id: str | None,
    review_packet_id: str | None,
    review_packet_sha256: str | None,
    journal_event_id: str | None,
) -> list[str]:
    kind = row.get("action")
    if kind not in {"OPEN", "ADD", "REDUCE", "HEDGE", "CLOSE"}:
        return []
    if row.get("result") != "applied":
        return []
    overnight_run_id, trader_room_run_id = _run_ids(run_id)
    position_id = row.get("position_id")
    if kind == "HEDGE":
        position_id = row.get("position_id") or row.get("hedge_of")
    if not position_id:
        if kind == "OPEN":
            created = [pid for pid in updated_positions if pid not in prior_positions]
            position_id = created[0] if len(created) == 1 else None
        elif kind in {"ADD", "REDUCE", "CLOSE"}:
            changed = [
                pid
                for pid, pos in prior_positions.items()
                if pid not in updated_positions
                or float(pos.get("notional_usd") or 0) != float(updated_positions.get(pid, {}).get("notional_usd") or 0)
            ]
            position_id = changed[0] if len(changed) == 1 else None
    if not position_id:
        return []

    matching_action = None
    for action in decision.get("actions") or []:
        if not isinstance(action, dict):
            continue
        if action.get("action") == kind and (
            action.get("position_id") in (None, position_id)
            or action.get("hedge_of") == position_id
            or action.get("instrument") == row.get("instrument")
        ):
            matching_action = action
            break
    action = matching_action or {}
    rationale = action_rationale(action, decision)
    status = rationale_status_for(action if action else {"action": kind}, decision)
    current = updated_positions.get(position_id)
    prior = prior_positions.get(position_id)
    current_notional = None if current is None else current.get("notional_usd")
    if kind == "CLOSE":
        current_notional = 0.0
    notional_change = row.get("notional_usd")
    if notional_change is None and prior is not None and current is not None:
        notional_change = abs(float(current.get("notional_usd") or 0) - float(prior.get("notional_usd") or 0))
    elif notional_change is None and prior is not None and current is None:
        notional_change = prior.get("notional_usd")
    mark = row.get("price")
    if mark in (None, "") and current is not None:
        mark = current.get("entry_price") if kind in {"OPEN", "HEDGE", "ADD"} else current.get("mark_price")
    if mark in (None, "") and prior is not None:
        mark = prior.get("mark_price") or prior.get("entry_price")

    linked: list[str] = []
    if kind == "HEDGE":
        hedge_target = action.get("hedge_of") or row.get("hedge_of")
        new_pos = current or updated_positions.get(row.get("position_id") or "")
        new_id = (new_pos or {}).get("position_id") or row.get("position_id")
        if new_id:
            hedge_trade = record_lifecycle_event(
                store,
                owner_type=owner_type,
                owner_id=owner_id,
                kind="HEDGE",
                position_id=new_id,
                when=when,
                run_id=run_id,
                instrument=row.get("instrument") or (new_pos or {}).get("instrument"),
                asset_class=(new_pos or {}).get("asset_class") or action.get("asset_class"),
                side=(new_pos or {}).get("side") or action.get("side"),
                mark=mark,
                mark_source=row.get("paper_mid_source") or (new_pos or {}).get("entry_price_source"),
                mark_as_of=row.get("paper_mid_as_of") or (new_pos or {}).get("entry_price_as_of"),
                notional_change_usd=notional_change or (new_pos or {}).get("notional_usd"),
                current_notional_usd=(new_pos or {}).get("notional_usd"),
                rationale=rationale,
                rationale_status=status,
                thesis=action.get("thesis") or decision.get("thesis"),
                invalidation=action.get("invalidation") or decision.get("invalidation"),
                conviction=action.get("conviction", decision.get("conviction")),
                priced_or_disagreed=_priced(action, decision),
                catalysts=_catalysts(action, decision),
                paper_expression=(new_pos or {}).get("paper_expression") or action.get("paper_expression"),
                locked_expression_family=(new_pos or {}).get("locked_expression_family")
                or row.get("locked_expression_family"),
                hedge_of_position_id=hedge_target,
                evidence_cutoff=evidence_cutoff,
                evidence_hash=evidence_hash,
                evidence_packet_id=evidence_packet_id,
                source_decision_id=decision.get("decision_id"),
                source_journal_event_id=journal_event_id,
                review_packet_id=review_packet_id,
                review_packet_sha256=review_packet_sha256,
                overnight_run_id=overnight_run_id,
                trader_room_run_id=trader_room_run_id,
            )
            linked.append(hedge_trade["trade_id"])
        if hedge_target:
            original = find_trade_by_position(
                store, owner_type=owner_type, owner_id=owner_id, position_id=hedge_target
            )
            if original:
                record_lifecycle_event(
                    store,
                    owner_type=owner_type,
                    owner_id=owner_id,
                    kind="HEDGE",
                    position_id=hedge_target,
                    when=when,
                    run_id=run_id,
                    rationale=rationale,
                    rationale_status=status,
                    hedge_of_position_id=new_id,
                    source_journal_event_id=journal_event_id,
                    overnight_run_id=overnight_run_id,
                    trader_room_run_id=trader_room_run_id,
                )
                linked.append(original["trade_id"])
        return linked

    trade = record_lifecycle_event(
        store,
        owner_type=owner_type,
        owner_id=owner_id,
        kind=kind,
        position_id=position_id,
        when=when,
        run_id=run_id,
        instrument=row.get("instrument") or action.get("instrument") or (prior or current or {}).get("instrument"),
        asset_class=action.get("asset_class") or (prior or current or {}).get("asset_class"),
        side=action.get("side") or (prior or current or {}).get("side"),
        mark=mark,
        mark_source=row.get("paper_mid_source") or (current or prior or {}).get("entry_price_source"),
        mark_as_of=row.get("paper_mid_as_of") or (current or prior or {}).get("entry_price_as_of"),
        notional_change_usd=notional_change,
        current_notional_usd=current_notional,
        realized_increment_usd=row.get("realized_pnl_usd") or action.get("realized_pnl_usd"),
        rationale=rationale,
        rationale_status=status,
        thesis=action.get("thesis") or decision.get("thesis"),
        invalidation=action.get("invalidation") or decision.get("invalidation"),
        conviction=action.get("conviction", decision.get("conviction")),
        priced_or_disagreed=_priced(action, decision),
        catalysts=_catalysts(action, decision),
        exit_reason_category=action.get("exit_reason_category") or decision.get("exit_reason_category"),
        paper_expression=action.get("paper_expression") or (current or prior or {}).get("paper_expression"),
        locked_expression_family=row.get("locked_expression_family")
        or (current or prior or {}).get("locked_expression_family"),
        evidence_cutoff=evidence_cutoff,
        evidence_hash=evidence_hash,
        evidence_packet_id=evidence_packet_id,
        source_decision_id=decision.get("decision_id"),
        source_journal_event_id=journal_event_id,
        review_packet_id=review_packet_id,
        review_packet_sha256=review_packet_sha256,
        overnight_run_id=overnight_run_id,
        trader_room_run_id=trader_room_run_id,
    )
    if kind == "CLOSE":
        create_postmortem_due(store, trade, run_id=run_id, when=when)
    return [trade["trade_id"]]


def _observe_marks(store: TradingStore, owner_type: str, owner_id: str, positions: list[dict[str, Any]]) -> None:
    for position in positions:
        trade = find_trade_by_position(
            store, owner_type=owner_type, owner_id=owner_id, position_id=position.get("position_id") or ""
        )
        if trade:
            observe_open_mark(store, trade, unrealized_pnl_usd=position.get("unrealized_pnl_usd"))


def _prepare_identity(
    store: TradingStore,
    decision: dict[str, Any],
    *,
    owner_type: str,
    owner_id: str,
    run_id: str | None,
    expected_memory_sha256: str | None,
    when: datetime | None,
) -> None:
    apply_reflections(store, decision, owner_type=owner_type, owner_id=owner_id, run_id=run_id, when=when)
    assert_expansion_rationale(decision, owner_id=owner_id)
    assert_learning_gate(
        store,
        owner_type=owner_type,
        owner_id=owner_id,
        decision=decision,
        run_id=run_id,
        expected_memory_sha256=expected_memory_sha256,
    )


def apply_trader_review_with_memory(
    books: dict[str, Any],
    reviews: dict[str, Any],
    *,
    families: dict[str, Any],
    run_id: str,
    evidence_cutoff: str,
    store: TradingStore,
    memory_hashes: dict[str, str] | None = None,
    evidence_hash: str | None = None,
    when: datetime | None = None,
    market_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    store.ensure_initialized()
    stamp = now_ny(when)
    hashes = memory_hashes or {}
    prepared = deepcopy(reviews)
    for seat in STANDING_SEATS:
        payload = prepared[seat]
        _prepare_identity(
            store,
            payload,
            owner_type="trader",
            owner_id=seat,
            run_id=run_id,
            expected_memory_sha256=hashes.get(seat) or payload.get("memory_context_sha256"),
            when=stamp,
        )
    hist_lens = {seat: len(books["seats"][seat].get("history") or []) for seat in STANDING_SEATS}
    prior_positions = {
        seat: {p["position_id"]: deepcopy(p) for p in books["seats"][seat].get("positions") or []}
        for seat in STANDING_SEATS
    }
    updated = apply_review(
        books,
        prepared,
        families=families,
        run_id=run_id,
        evidence_cutoff=evidence_cutoff,
        when=stamp,
        market_state=market_state,
    )
    overnight_run_id, trader_room_run_id = _run_ids(run_id)
    for seat in STANDING_SEATS:
        decision = prepared[seat]
        seat_book = updated["seats"][seat]
        new_hist = (seat_book.get("history") or [])[hist_lens[seat] :]
        current_positions = {p["position_id"]: p for p in seat_book.get("positions") or []}
        linked: list[str] = []
        linked_positions: list[str] = []
        missing_exit = False
        for row in new_hist:
            if row.get("action") in {"REDUCE", "CLOSE"} and rationale_status_for(
                next(
                    (
                        action
                        for action in decision.get("actions") or []
                        if isinstance(action, dict) and action.get("action") == row.get("action")
                    ),
                    {"action": row.get("action")},
                ),
                decision,
            ) == "missing_required":
                missing_exit = True
            linked.extend(
                _sync_history_row(
                    store,
                    owner_type="trader",
                    owner_id=seat,
                    row=row,
                    decision=decision,
                    prior_positions=prior_positions[seat],
                    updated_positions=current_positions,
                    when=stamp,
                    run_id=run_id,
                    evidence_cutoff=evidence_cutoff,
                    evidence_hash=evidence_hash,
                    evidence_packet_id=None,
                    review_packet_id=None,
                    review_packet_sha256=None,
                    journal_event_id=None,
                )
            )
            if row.get("position_id"):
                linked_positions.append(row["position_id"])
        if missing_exit:
            seat_book.setdefault("alerts", []).append(
                "rationale_status=missing_required; postmortem_due flagged for missing exit rationale"
            )
        event = record_event(
            store,
            owner_type="trader",
            owner_id=seat,
            kind="OVERNIGHT_DECISION",
            when=stamp,
            run_id=run_id,
            actions=decision.get("actions"),
            rationale=decision.get("rationale") or decision.get("thesis"),
            thesis=decision.get("thesis"),
            invalidation=decision.get("invalidation"),
            conviction=decision.get("conviction"),
            linked_trade_ids=sorted(set(linked)),
            linked_position_ids=sorted(set(linked_positions)),
            memory_context_sha256=decision.get("memory_context_sha256") or hashes.get(seat),
            evidence_cutoff=evidence_cutoff,
            evidence_hash=evidence_hash,
            overnight_run_id=overnight_run_id,
            trader_room_run_id=trader_room_run_id,
        )
        _observe_marks(store, "trader", seat, list(seat_book.get("positions") or []))
        build_memory_context(store, "trader", seat, when=stamp)
        decision["journal_event_id"] = event["event_id"]
    validate_books(updated)
    return updated


def apply_pm_decision_with_memory(
    books: dict[str, Any],
    decision: dict[str, Any],
    *,
    pm_id: str,
    store: TradingStore,
    market_state: dict[str, Any] | None,
    run_id: str | None,
    evidence_cutoff: str | None,
    review_packet_id: str | None,
    review_packet_sha256: str | None,
    expected_memory_sha256: str | None = None,
    evidence_hash: str | None = None,
    when: datetime | None = None,
) -> dict[str, Any]:
    store.ensure_initialized()
    stamp = now_ny(when)
    _prepare_identity(
        store,
        decision,
        owner_type="pm",
        owner_id=pm_id,
        run_id=run_id,
        expected_memory_sha256=expected_memory_sha256 or decision.get("memory_context_sha256"),
        when=stamp,
    )
    prior = {p["position_id"]: deepcopy(p) for p in books["pms"][pm_id].get("positions") or []}
    hist_len = len(books["pms"][pm_id].get("history") or [])
    updated = apply_pm_book_decision(
        books,
        decision,
        pm_id=pm_id,
        market_state=market_state,
        run_id=run_id,
        evidence_cutoff=evidence_cutoff,
        review_packet_id=review_packet_id,
        review_packet_sha256=review_packet_sha256,
        when=stamp,
    )
    book = updated["pms"][pm_id]
    current = {p["position_id"]: p for p in book.get("positions") or []}
    linked: list[str] = []
    linked_positions: list[str] = []
    missing_exit = False
    overnight_run_id, trader_room_run_id = _run_ids(run_id)
    for row in (book.get("history") or [])[hist_len:]:
        if row.get("action") in {"REDUCE", "CLOSE"} and rationale_status_for(
            next(
                (
                    action
                    for action in decision.get("actions") or []
                    if isinstance(action, dict) and action.get("action") == row.get("action")
                ),
                {"action": row.get("action")},
            ),
            decision,
        ) == "missing_required":
            missing_exit = True
        linked.extend(
            _sync_history_row(
                store,
                owner_type="pm",
                owner_id=pm_id,
                row=row,
                decision=decision,
                prior_positions=prior,
                updated_positions=current,
                when=stamp,
                run_id=run_id,
                evidence_cutoff=evidence_cutoff,
                evidence_hash=evidence_hash,
                evidence_packet_id=review_packet_id,
                review_packet_id=review_packet_id,
                review_packet_sha256=review_packet_sha256,
                journal_event_id=None,
            )
        )
        if row.get("position_id"):
            linked_positions.append(row["position_id"])
    if missing_exit:
        book.setdefault("alerts", []).append(
            "rationale_status=missing_required; postmortem_due flagged for missing exit rationale"
        )
    record_event(
        store,
        owner_type="pm",
        owner_id=pm_id,
        kind="PM_DECISION",
        when=stamp,
        run_id=run_id,
        actions=decision.get("actions"),
        rationale=decision.get("rationale") or decision.get("thesis"),
        thesis=decision.get("thesis"),
        invalidation=decision.get("invalidation"),
        conviction=decision.get("conviction"),
        linked_trade_ids=sorted(set(linked)),
        linked_position_ids=sorted(set(linked_positions)),
        memory_context_sha256=decision.get("memory_context_sha256") or expected_memory_sha256,
        evidence_cutoff=evidence_cutoff,
        evidence_hash=evidence_hash or review_packet_sha256,
        overnight_run_id=overnight_run_id,
        trader_room_run_id=trader_room_run_id,
        review_packet_id=review_packet_id,
    )
    _observe_marks(store, "pm", pm_id, list(book.get("positions") or []))
    build_memory_context(store, "pm", pm_id, when=stamp)
    return updated


def journal_trader_room_pitch(
    store: TradingStore,
    contribution: dict[str, Any],
    *,
    run_id: str,
    evidence_cutoff: str | None,
    evidence_hash: str | None,
    memory_context_sha256: str | None,
    source_ref: str | None,
    when: datetime | None = None,
) -> dict[str, Any]:
    agent = contribution.get("agent")
    trade = contribution.get("trade") or {}
    return record_event(
        store,
        owner_type="trader",
        owner_id=agent,
        kind="TRADER_ROOM_PROPOSAL",
        when=when,
        run_id=run_id,
        actions=[] if not trade else [{"action": "PROPOSE", **{k: trade.get(k) for k in ("instrument", "direction", "asset_class")}}],
        rationale=contribution.get("stance_summary") or (trade.get("thesis") if isinstance(trade, dict) else None),
        thesis=(trade.get("thesis") if isinstance(trade, dict) else None) or contribution.get("stance_summary"),
        invalidation=(trade.get("invalidation") if isinstance(trade, dict) else None),
        conviction=contribution.get("confidence"),
        memory_context_sha256=memory_context_sha256,
        evidence_cutoff=evidence_cutoff,
        evidence_hash=evidence_hash,
        trader_room_run_id=run_id,
        source_ref=source_ref,
        extra={
            "trade": trade or None,
            "conflict_synopsis": contribution.get("conflict_synopsis"),
        },
    )


def journal_trader_room_rebuttal(
    store: TradingStore,
    rebuttal: dict[str, Any],
    *,
    run_id: str,
    evidence_cutoff: str | None,
    evidence_hash: str | None,
    memory_context_sha256: str | None,
    source_ref: str | None,
    when: datetime | None = None,
) -> dict[str, Any]:
    agent = rebuttal.get("agent")
    return record_event(
        store,
        owner_type="trader",
        owner_id=agent,
        kind="TRADER_ROOM_REBUTTAL",
        when=when,
        run_id=run_id,
        actions=[{"action": "REBUT", "trade_change": rebuttal.get("trade_change")}],
        rationale="; ".join(rebuttal.get("defense") or []) or None,
        memory_context_sha256=memory_context_sha256,
        evidence_cutoff=evidence_cutoff,
        evidence_hash=evidence_hash,
        trader_room_run_id=run_id,
        source_ref=source_ref,
        extra={
            "opponents": rebuttal.get("opponents"),
            "trade_change": rebuttal.get("trade_change"),
            "revised_trade": rebuttal.get("revised_trade"),
            "holes_in_opposing_case": rebuttal.get("holes_in_opposing_case"),
        },
    )
