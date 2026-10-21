"""Profit-harvest review for open trader and PM positions.

Thresholds decide when a decision must re-underwrite a full-size hold. They
never create take-profit orders, stops, or book actions. An intact thesis is
not remaining forward edge.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from typing import Any

from scripts.overnight.clock import isoformat, now_ny, parse_iso
from scripts.risk_capital import position_risk_capital
from scripts.trading.errors import HarvestReviewError, SchemaError

LIFECYCLE_FRAMINGS = ("tactical", "swing", "structural")
# Review clocks, not exit orders. A missing explicit horizon uses the framing default.
DEFAULT_HORIZON_DAYS = {"tactical": 10, "swing": 45, "structural": 120}
MIN_HORIZON_DAYS = 1
MAX_HORIZON_DAYS = 366

# One standard-shock unit is a delivered move, not the first green print.
# The dollar floor keeps a tiny-risk line from flapping on noise.
MATERIAL_WINNER_RISK_MULTIPLE = 1.0
MATERIAL_WINNER_MIN_USD = 100_000.0
# After that winner exists, giving back this much of MFE re-opens the review.
GIVEBACK_RETAINED_FRACTION = 0.70
# A deeper giveback can open a causal reflection. It still does not write a lesson.
MAJOR_GIVEBACK_RETAINED_FRACTION = 0.50
MAJOR_GIVEBACK_MIN_USD = 100_000.0

HARVEST_QUESTION = (
    "If flat today, would you initiate this exact trade at this exact size and level?"
)
ORDER_POLICY = "review_only"
REASON_MIN_CHARS = 40

CONTINUATION_ACTIONS = frozenset({"HOLD", "NO_TRADE"})
DERISK_SIZE_ACTIONS = frozenset({"REDUCE", "CLOSE"})
ENTRY_ACTIONS = frozenset({"OPEN", "HEDGE"})


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _money(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _price(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fraction(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 4)


def normalize_lifecycle(payload: Any, *, label: str = "lifecycle") -> dict[str, Any]:
    """Validate entry or re-underwrite lifecycle. Does not invent a horizon for legacy trades."""
    if not isinstance(payload, dict):
        raise SchemaError(
            f"{label} requires framing, realization_logic, and catalyst_logic"
        )
    framing = payload.get("framing")
    if framing not in LIFECYCLE_FRAMINGS:
        raise SchemaError(f"{label}.framing must be tactical, swing, or structural")
    raw_days = payload.get("horizon_days")
    if raw_days in (None, ""):
        horizon_days = DEFAULT_HORIZON_DAYS[framing]
    else:
        try:
            horizon_days = int(raw_days)
        except (TypeError, ValueError) as exc:
            raise SchemaError(f"{label}.horizon_days must be an integer") from exc
        if horizon_days < MIN_HORIZON_DAYS or horizon_days > MAX_HORIZON_DAYS:
            raise SchemaError(
                f"{label}.horizon_days must be {MIN_HORIZON_DAYS}..{MAX_HORIZON_DAYS}"
            )
    realization = _text(payload.get("realization_logic"))
    catalyst = _text(payload.get("catalyst_logic"))
    if not realization or len(realization) < 12:
        raise SchemaError(f"{label}.realization_logic must describe how the trade is expected to pay")
    if not catalyst or len(catalyst) < 12:
        raise SchemaError(f"{label}.catalyst_logic must describe what realizes or exhausts the edge")
    catalyst_by = _text(payload.get("catalyst_by"))
    if catalyst_by:
        try:
            date.fromisoformat(catalyst_by[:10])
        except ValueError as exc:
            raise SchemaError(f"{label}.catalyst_by must be an ISO date") from exc
        catalyst_by = catalyst_by[:10]
    return {
        "framing": framing,
        "horizon_days": horizon_days,
        "realization_logic": realization,
        "catalyst_logic": catalyst,
        "catalyst_by": catalyst_by,
    }


def assert_expansion_lifecycle(action: dict[str, Any], *, owner_id: str) -> None:
    """New OPEN/HEDGE decisions must carry lifecycle. Legacy records without it stay readable."""
    if action.get("action") not in ENTRY_ACTIONS:
        return
    try:
        normalize_lifecycle(action.get("lifecycle"), label=f"{owner_id} {action.get('action')} lifecycle")
    except SchemaError as exc:
        raise SchemaError(
            f"{owner_id} {action.get('action')} requires lifecycle "
            f"(tactical|swing|structural, realization_logic, catalyst_logic): {exc}"
        ) from exc


def _parse_when(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return parse_iso(str(value))
    except (TypeError, ValueError):
        return None


def _elapsed_seconds(start: Any, end: datetime | None) -> int | None:
    opened = _parse_when(start)
    if opened is None or end is None:
        return None
    elapsed = (end - opened).total_seconds()
    if elapsed < 0:
        return None
    return int(elapsed)


def active_lifecycle(trade: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(trade, dict):
        return None
    lifecycle = trade.get("lifecycle")
    if isinstance(lifecycle, dict) and lifecycle.get("framing") in LIFECYCLE_FRAMINGS:
        return lifecycle
    return None


def _risk_notional(trade: dict[str, Any], position: dict[str, Any] | None) -> float | None:
    for source in (
        (trade or {}).get("peak_notional_usd"),
        (trade or {}).get("initial_notional_usd"),
        (position or {}).get("notional_usd"),
        (trade or {}).get("current_notional_usd"),
    ):
        money = _money(source)
        if money:
            return abs(money)
    return None


def material_winner_threshold_usd(trade: dict[str, Any], position: dict[str, Any] | None) -> float | None:
    """Review threshold in dollars. None when risk capital cannot be measured and no floor applies."""
    notional = _risk_notional(trade, position)
    asset = (position or {}).get("asset_class") or (trade or {}).get("asset_class")
    capital = None
    if notional is not None and asset:
        capital = position_risk_capital({"asset_class": asset, "notional_usd": notional})
    if capital is None:
        return MATERIAL_WINNER_MIN_USD
    return round(max(MATERIAL_WINNER_MIN_USD, MATERIAL_WINNER_RISK_MULTIPLE * float(capital)), 2)


def harvest_metrics(
    trade: dict[str, Any] | None,
    position: dict[str, Any] | None = None,
    *,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Deterministic harvest view. Missing legacy fields stay null and do not raise."""
    trade = trade or {}
    position = position or {}
    stamp = now_ny(as_of)
    entry = _price(position.get("entry_price"))
    if entry is None:
        entry = _price(trade.get("entry_mark"))
    current_mark = _price(position.get("mark_price"))
    if current_mark is None:
        current_mark = _price(trade.get("last_mark"))
    unrealized = _money(position.get("unrealized_pnl_usd"))
    if unrealized is None:
        unrealized = _money(trade.get("last_unrealized_pnl_usd"))
    realized = _money(trade.get("realized_pnl_usd"))
    if realized is None:
        realized = 0.0
    total = None if unrealized is None else round(realized + unrealized, 2)
    recorded_mfe = _money(trade.get("mfe_usd"))
    recorded_mae = _money(trade.get("mae_usd"))
    if recorded_mfe is not None and total is not None:
        reference_peak = round(max(recorded_mfe, total), 2)
    elif recorded_mfe is not None:
        reference_peak = recorded_mfe
    elif total is not None and total > 0:
        reference_peak = total
    else:
        reference_peak = None
    if reference_peak is not None and reference_peak > 0 and total is not None:
        retained = _fraction(total / reference_peak)
        giveback = round(max(0.0, reference_peak - total), 2)
    else:
        retained = None
        giveback = None
    lifecycle = active_lifecycle(trade)
    opened_at = (lifecycle or {}).get("anchored_at") or trade.get("opened_at") or position.get("opened_at")
    # Holding time is still measured from the original open. The horizon clock
    # restarts at the latest re-underwrite.
    holding_seconds = _elapsed_seconds(trade.get("opened_at") or position.get("opened_at"), stamp)
    horizon_anchor = (lifecycle or {}).get("anchored_at") or trade.get("opened_at") or position.get("opened_at")
    horizon_elapsed = _elapsed_seconds(horizon_anchor, stamp)
    horizon_days = None if lifecycle is None else lifecycle.get("horizon_days")
    if lifecycle is None or not horizon_days or horizon_elapsed is None:
        horizon_status = "unspecified" if lifecycle is None else "unknown"
        elapsed_fraction = None
    else:
        elapsed_days = horizon_elapsed / 86400.0
        elapsed_fraction = _fraction(elapsed_days / float(horizon_days))
        horizon_status = "expired" if elapsed_days > float(horizon_days) else "within"
    threshold = material_winner_threshold_usd(trade, position or {"asset_class": trade.get("asset_class")})
    triggers: list[str] = []
    if reference_peak is not None and threshold is not None and reference_peak >= threshold:
        triggers.append("material_winner")
    if horizon_status == "expired":
        triggers.append("horizon_expired")
    catalyst_by = (lifecycle or {}).get("catalyst_by")
    if catalyst_by:
        try:
            if stamp.date() > date.fromisoformat(str(catalyst_by)[:10]):
                triggers.append("catalyst")
        except ValueError:
            pass
    if (
        "material_winner" in triggers
        and retained is not None
        and retained <= GIVEBACK_RETAINED_FRACTION
        and (giveback or 0) >= MATERIAL_WINNER_MIN_USD
    ):
        triggers.append("giveback")
    return {
        "trade_id": trade.get("trade_id"),
        "position_id": position.get("position_id") or trade.get("position_id"),
        "instrument": position.get("instrument") or trade.get("instrument"),
        "side": position.get("side") or trade.get("side"),
        "asset_class": position.get("asset_class") or trade.get("asset_class"),
        "entry_mark": entry,
        "current_mark": current_mark,
        "current_notional_usd": _money(position.get("notional_usd") if position else None)
        or _money(trade.get("current_notional_usd")),
        "unrealized_pnl_usd": unrealized,
        "realized_pnl_usd": realized,
        "total_pnl_usd": total,
        "mfe_usd": reference_peak if reference_peak is not None else recorded_mfe,
        "recorded_mfe_usd": recorded_mfe,
        "mae_usd": recorded_mae,
        "retained_mfe_fraction": retained,
        "giveback_usd": giveback,
        "holding_seconds": holding_seconds,
        "framing": None if lifecycle is None else lifecycle.get("framing"),
        "intended_horizon_days": horizon_days,
        "horizon_elapsed_fraction": elapsed_fraction,
        "horizon_status": horizon_status,
        "realization_logic": None if lifecycle is None else lifecycle.get("realization_logic"),
        "catalyst_logic": None if lifecycle is None else lifecycle.get("catalyst_logic"),
        "catalyst_by": catalyst_by,
        "review_threshold_usd": threshold,
        "review_required": bool(triggers),
        "review_triggers": triggers,
        "full_size_hold_requires_reunderwrite": "horizon_expired" in triggers,
        "question": HARVEST_QUESTION,
        "order_policy": ORDER_POLICY,
        "mechanical_order": False,
    }


def profit_giveback_triggers(
    trades: list[dict[str, Any]],
    positions: list[dict[str, Any]] | None,
    *,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    """Major open-trade givebacks that should get a causal look, not an automatic lesson."""
    by_id = {str(row.get("position_id")): row for row in positions or [] if row.get("position_id")}
    found: list[dict[str, Any]] = []
    for trade in trades:
        if trade.get("status") != "open":
            continue
        position = by_id.get(str(trade.get("position_id")))
        metrics = harvest_metrics(trade, position, as_of=as_of)
        retained = metrics.get("retained_mfe_fraction")
        giveback = metrics.get("giveback_usd")
        peak = metrics.get("mfe_usd")
        threshold = metrics.get("review_threshold_usd")
        if retained is None or giveback is None or peak is None or threshold is None:
            continue
        if peak < threshold:
            continue
        if retained > MAJOR_GIVEBACK_RETAINED_FRACTION or giveback < MAJOR_GIVEBACK_MIN_USD:
            continue
        found.append(
            {
                "id": "profit_giveback",
                "trade_id": trade.get("trade_id"),
                "position_id": metrics.get("position_id"),
                "retained_mfe_fraction": retained,
                "giveback_usd": giveback,
                "mfe_usd": peak,
            }
        )
    return found


def _open_positions(positions: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    rows = []
    for position in positions or []:
        if not isinstance(position, dict):
            continue
        if _money(position.get("notional_usd")) == 0:
            continue
        rows.append(position)
    return rows


def _match_trade(trades: list[dict[str, Any]], position: dict[str, Any]) -> dict[str, Any]:
    pid = position.get("position_id")
    for trade in trades:
        if trade.get("status") != "open":
            continue
        if trade.get("position_id") == pid:
            return trade
    return {
        "position_id": pid,
        "trade_id": None,
        "instrument": position.get("instrument"),
        "side": position.get("side"),
        "asset_class": position.get("asset_class"),
        "entry_mark": position.get("entry_price"),
        "opened_at": position.get("opened_at"),
        "current_notional_usd": position.get("notional_usd"),
        "peak_notional_usd": position.get("notional_usd"),
        "initial_notional_usd": position.get("notional_usd"),
        "realized_pnl_usd": 0.0,
        "mfe_usd": position.get("mfe_usd"),
        "mae_usd": position.get("mae_usd"),
        "status": "open",
        "lifecycle": position.get("lifecycle") if isinstance(position.get("lifecycle"), dict) else None,
    }


def position_harvests(
    trades: list[dict[str, Any]],
    positions: list[dict[str, Any]] | None,
    *,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    return [
        harvest_metrics(_match_trade(trades, position), position, as_of=as_of)
        for position in _open_positions(positions)
    ]


def kept_full_size_ids(actions: list[dict[str, Any]], open_ids: list[str]) -> list[str]:
    """Positions a decision leaves at their current size.

    REDUCE and CLOSE harvest. HOLD, NO_TRADE, and silence keep full current size.
    """
    covered: set[str] = set()
    known = list(open_ids)
    for action in actions:
        if not isinstance(action, dict) or action.get("action") not in DERISK_SIZE_ACTIONS:
            continue
        pid = action.get("position_id")
        if pid in known:
            covered.add(str(pid))
        elif pid in (None, "", "__first__") and len(known) == 1:
            covered.add(known[0])
    return [pid for pid in known if pid not in covered]


def _review_rows(decision: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    many = decision.get("harvest_reviews")
    if isinstance(many, list):
        rows.extend(row for row in many if isinstance(row, dict))
    single = decision.get("harvest_review")
    if isinstance(single, dict):
        rows.append(single)
    for action in decision.get("actions") or []:
        if isinstance(action, dict) and isinstance(action.get("harvest_review"), dict):
            rows.append(action["harvest_review"])
    return rows


def matching_review(decision: dict[str, Any], metrics: dict[str, Any], *, triggered_count: int) -> dict[str, Any] | None:
    rows = _review_rows(decision)
    specific = [
        row
        for row in rows
        if row.get("position_id") == metrics.get("position_id") or (
            metrics.get("trade_id") and row.get("trade_id") == metrics.get("trade_id")
        )
    ]
    if specific:
        return specific[-1]
    blanks = [row for row in rows if not row.get("position_id") and not row.get("trade_id")]
    if triggered_count == 1 and blanks:
        return blanks[-1]
    return None


def justification_reason(metrics: dict[str, Any], review: dict[str, Any] | None) -> str | None:
    """None when a full-size hold has answered the harvest question.

    Thesis validity is recorded and is not sufficient.
    """
    if not metrics.get("review_required"):
        return None
    label = metrics.get("position_id") or metrics.get("trade_id") or metrics.get("instrument") or "position"
    triggers = ", ".join(metrics.get("review_triggers") or [])
    if not isinstance(review, dict):
        return (
            f"{label} harvest_review: {triggers} requires an explicit review before HOLD full size. "
            f"{HARVEST_QUESTION} Otherwise REDUCE or CLOSE. "
            "This is a review trigger, not a take-profit order."
        )
    if not isinstance(review.get("thesis_still_valid"), bool):
        return f"{label} harvest_review: thesis_still_valid must be true or false, separate from remaining edge"
    if not isinstance(review.get("remaining_edge"), bool):
        return f"{label} harvest_review: remaining_edge must be true or false, separate from thesis validity"
    answer = review.get("would_initiate_flat")
    if answer not in {"yes", "no"}:
        return f"{label} harvest_review: would_initiate_flat must be yes or no. {HARVEST_QUESTION}"
    if review.get("remaining_edge") is not True or answer != "yes":
        return (
            f"{label} harvest_review: full-size HOLD requires remaining_edge true and "
            f"would_initiate_flat yes. Thesis validity alone is not remaining edge. "
            "REDUCE or CLOSE remains available."
        )
    reason = _text(review.get("remaining_edge_reason"))
    if not reason or len(reason) < REASON_MIN_CHARS:
        return (
            f"{label} harvest_review: remaining_edge_reason must explain the forward edge "
            "from the current level and size"
        )
    if metrics.get("full_size_hold_requires_reunderwrite"):
        try:
            normalize_lifecycle(review.get("reunderwrite"), label=f"{label} reunderwrite")
        except SchemaError as exc:
            return (
                f"{label} harvest_review: the intended horizon has expired. "
                f"HOLD full size requires a fresh re-underwrite from current conditions ({exc}). "
                "A tactical trade does not become structural by silence."
            )
    return None


def enforce_harvest_hold(
    decision: dict[str, Any],
    trades: list[dict[str, Any]],
    positions: list[dict[str, Any]] | None,
    *,
    as_of: datetime | None = None,
    owner_id: str,
) -> list[dict[str, Any]]:
    """Raise when a triggered position is kept at full size without a re-underwrite.

    Returns the accepted reviews. Does not emit an order.
    """
    actions = [row for row in (decision.get("actions") or []) if isinstance(row, dict)]
    metrics_rows = position_harvests(trades, positions, as_of=as_of)
    open_ids = [str(row["position_id"]) for row in metrics_rows if row.get("position_id")]
    kept = set(kept_full_size_ids(actions, open_ids))
    triggered = [row for row in metrics_rows if row.get("review_required") and str(row.get("position_id")) in kept]
    accepted: list[dict[str, Any]] = []
    problems: list[str] = []
    for metrics in triggered:
        review = matching_review(decision, metrics, triggered_count=len(triggered))
        reason = justification_reason(metrics, review)
        if reason:
            problems.append(f"{owner_id} {reason}")
            continue
        accepted.append({"metrics_position_id": metrics.get("position_id"), "review": review, "triggers": list(metrics.get("review_triggers") or [])})
    if problems:
        raise HarvestReviewError(problems[0])
    return accepted


def replay_mark_path(
    trade: dict[str, Any],
    marks: list[dict[str, Any]],
    *,
    entry_price: float,
    notional_usd: float,
    asset_class: str,
    side: str,
) -> list[dict[str, Any]]:
    """Walk a historical mark path with a running MFE. Later peaks are not visible early."""
    from scripts.overnight.books import position_pnl

    running_mfe: float | None = None
    running_mae: float | None = None
    out: list[dict[str, Any]] = []
    for point in marks:
        snapshot = deepcopy(trade)
        position = {
            "position_id": trade.get("position_id"),
            "instrument": trade.get("instrument") or point.get("instrument"),
            "asset_class": asset_class,
            "side": side,
            "notional_usd": point.get("notional_usd", notional_usd),
            "entry_price": entry_price,
            "mark_price": point.get("mark"),
            "opened_at": trade.get("opened_at"),
        }
        unrealized = point.get("unrealized_pnl_usd")
        if unrealized is None and point.get("mark") not in (None, ""):
            unrealized = position_pnl(position)["unrealized_pnl_usd"]
        position["unrealized_pnl_usd"] = unrealized
        if unrealized is not None:
            running_mfe = float(unrealized) if running_mfe is None else max(running_mfe, float(unrealized))
            running_mae = float(unrealized) if running_mae is None else min(running_mae, float(unrealized))
        snapshot["mfe_usd"] = None if running_mfe is None else round(running_mfe, 2)
        snapshot["mae_usd"] = None if running_mae is None else round(running_mae, 2)
        snapshot["realized_pnl_usd"] = point.get("realized_pnl_usd") or 0.0
        as_of = _parse_when(point.get("as_of"))
        metrics = harvest_metrics(snapshot, position, as_of=as_of)
        metrics["as_of"] = point.get("as_of")
        out.append(metrics)
    return out


def persist_accepted_harvest(
    store: Any,
    decision: dict[str, Any],
    *,
    owner_type: str,
    owner_id: str,
    when: datetime | None,
    run_id: str | None,
) -> None:
    """Store an accepted re-underwrite on the ledger. Does not change entry price or P&L."""
    accepted = decision.get("_harvest_accepted") or []
    if not accepted:
        return
    from scripts.trading.ledger import find_trade_by_position

    stamp = isoformat(now_ny(when))
    for item in accepted:
        review = item.get("review") or {}
        position_id = review.get("position_id") or item.get("metrics_position_id")
        trade_id = review.get("trade_id")
        trade = None
        if position_id:
            trade = find_trade_by_position(
                store, owner_type=owner_type, owner_id=owner_id, position_id=str(position_id)
            )
        if trade is None and trade_id and store.has_trade(trade_id):
            trade = store.read_trade(trade_id)
        if not trade or trade.get("owner_id") != owner_id:
            continue
        updated = deepcopy(trade)
        record = {
            "at": stamp,
            "run_id": run_id,
            "position_id": updated.get("position_id"),
            "trade_id": updated.get("trade_id"),
            "triggers": list(item.get("triggers") or []),
            "thesis_still_valid": review.get("thesis_still_valid"),
            "remaining_edge": review.get("remaining_edge"),
            "would_initiate_flat": review.get("would_initiate_flat"),
            "remaining_edge_reason": _text(review.get("remaining_edge_reason")),
            "order_policy": ORDER_POLICY,
            "mechanical_order": False,
        }
        reunderwrite = review.get("reunderwrite")
        if isinstance(reunderwrite, dict) and "horizon_expired" in (item.get("triggers") or []):
            fresh = normalize_lifecycle(reunderwrite, label="reunderwrite")
            fresh["anchored_at"] = stamp
            fresh["source"] = "reunderwrite"
            prior = updated.get("lifecycle")
            if isinstance(prior, dict) and not updated.get("entry_lifecycle"):
                updated["entry_lifecycle"] = prior
            updated.setdefault("lifecycle_reunderwrites", []).append(fresh)
            updated["lifecycle"] = fresh
            record["reunderwrite"] = fresh
        updated.setdefault("harvest_reviews", []).append(record)
        store.write_trade(updated)
