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

# Legacy vintages and spot still mature after one full standard-shock unit.
# Instrument-correct STIR review uses a much smaller delivered move so a 100bp
# shock is not required before a trader re-underwrites. These bands are review
# clocks, not targets, stops, or a preferred strategy.
MATERIAL_WINNER_RISK_MULTIPLE = 1.0
MATERIAL_WINNER_MIN_USD = 100_000.0
STIR_REVIEW_MOVE_BP = {"tactical": 5.0, "swing": 10.0, "structural": 20.0}
STIR_REVIEW_MOVE_BP_UNSPECIFIED = 10.0
STIR_REVIEW_NOISE_FLOOR_BP = 5.0
# After that winner exists, giving back this much of MFE re-opens the review.
GIVEBACK_RETAINED_FRACTION = 0.70
# A deeper giveback can open a causal reflection. It still does not write a lesson.
MAJOR_GIVEBACK_RETAINED_FRACTION = 0.50
MAJOR_GIVEBACK_MIN_USD = 100_000.0
# A residual at or above this share of the pre-action notional is still a kept position.
# A smaller residual can still require review when its scaled P&L remains a material winner.
MEANINGFUL_RESIDUAL_FRACTION = 0.25

HARVEST_QUESTION = (
    "If flat today, would you initiate this exact trade at this exact size and level?"
)
ORDER_POLICY = "review_only"
REASON_MIN_CHARS = 40

ENTRY_ACTIONS = frozenset({"OPEN", "HEDGE"})
DERISK_ACTIONS = frozenset({"REDUCE", "CLOSE"})
CONTINUATION_ACTIONS = frozenset({"HOLD", "NO_TRADE"})
REEXPANSION_ACTIONS = frozenset({"ADD", "HEDGE"})


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


def _intent_context(trade: dict[str, Any], position: dict[str, Any] | None, entry: float | None, mark: float | None) -> dict[str, Any]:
    expected = _text((position or {}).get("expected_mark_direction")) or _text((trade or {}).get("expected_mark_direction"))
    if expected not in {"lower", "higher"} or entry is None or mark is None:
        versus = "unknown"
    elif mark == entry:
        versus = "flat"
    elif expected == "lower":
        versus = "with_intent" if mark < entry else "against_intent"
    else:
        versus = "with_intent" if mark > entry else "against_intent"
    return {"expected_mark_direction": expected, "move_versus_entry_intent": versus}


def _expected_move_bp(trade: dict[str, Any], position: dict[str, Any] | None, lifecycle: dict[str, Any] | None) -> float | None:
    for source in (lifecycle or {}, trade or {}, position or {}):
        if not isinstance(source, dict):
            continue
        raw = source.get("expected_move_bp")
        if raw in (None, ""):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def _instrument_dv01_per_bp(position: dict[str, Any] | None) -> float | None:
    position = position or {}
    if position.get("valuation_method") != "instrument_dv01" and not position.get("legs"):
        return None
    if position.get("legs"):
        dv01s = [abs(float(leg["dv01_usd"])) for leg in position["legs"] if leg.get("dv01_usd") is not None]
        if not dv01s:
            return None
        kind = (position.get("paper_expression") or {}).get("type") if isinstance(position.get("paper_expression"), dict) else None
        kind = kind or position.get("structure_label")
        if kind == "butterfly":
            for leg in position["legs"]:
                if leg.get("role") == "wing1" and leg.get("dv01_usd") is not None:
                    return abs(float(leg["dv01_usd"]))
        return max(dv01s)
    contracts = position.get("contracts")
    local = None
    contract = position.get("contract") if isinstance(position.get("contract"), dict) else {}
    local = contract.get("dv01_per_contract_local")
    fx = 1.0 if position.get("contract_currency") in (None, "USD") else position.get("mark_fx_usd_per_unit")
    if contracts in (None, "") or local in (None, "") or fx in (None, ""):
        return None
    try:
        return abs(float(contracts) * float(local) * float(fx))
    except (TypeError, ValueError):
        return None


def stir_review_move_bp(trade: dict[str, Any], position: dict[str, Any] | None) -> float | None:
    """Bp of instrument DV01 that matures a review. None keeps the legacy shock unit."""
    if _instrument_dv01_per_bp(position) is None:
        return None
    lifecycle = active_lifecycle(trade)
    framing = None if lifecycle is None else lifecycle.get("framing")
    bp = STIR_REVIEW_MOVE_BP.get(framing, STIR_REVIEW_MOVE_BP_UNSPECIFIED)
    expected = _expected_move_bp(trade, position, lifecycle)
    if expected is not None:
        # A stored opportunity can pull the review earlier. It cannot demand
        # the full 100bp risk shock, and it cannot drop through the noise floor.
        bp = min(bp, max(STIR_REVIEW_NOISE_FLOOR_BP, 0.5 * expected))
    return bp


def material_winner_threshold_usd(trade: dict[str, Any], position: dict[str, Any] | None) -> float | None:
    """Review threshold in dollars. STIR uses a small delivered move, not the 100bp shock."""
    review_bp = stir_review_move_bp(trade, position or {})
    dv01 = _instrument_dv01_per_bp(position)
    if review_bp is not None and dv01 is not None:
        return round(max(MATERIAL_WINNER_MIN_USD, dv01 * review_bp), 2)
    notional = _risk_notional(trade, position)
    asset = (position or {}).get("asset_class") or (trade or {}).get("asset_class")
    capital = None
    probe = dict(position or {})
    if asset:
        probe["asset_class"] = asset
    if notional is not None:
        probe["notional_usd"] = notional
    if probe.get("legs"):
        current = _money((position or {}).get("notional_usd"))
        base = position_risk_capital(position or {})
        if base is not None and current and notional is not None and current > 0:
            capital = base * (notional / current)
        elif base is not None and notional is None:
            capital = base
    elif notional is not None and asset:
        capital = position_risk_capital(probe)
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
        "review_move_bp": stir_review_move_bp(trade, position),
        "risk_context": "instrument_dv01_small_move" if stir_review_move_bp(trade, position) else "legacy_or_spot",
        **_intent_context(trade, position, entry, current_mark),
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


def _positive_notional(action: dict[str, Any]) -> float | None:
    raw = action.get("notional_usd")
    if raw in (None, ""):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value


def _actions_for_position(
    actions: list[dict[str, Any]],
    position_id: str,
    open_ids: list[str],
) -> list[dict[str, Any]]:
    sole = len(open_ids) == 1
    matched: list[dict[str, Any]] = []
    for action in actions:
        if not isinstance(action, dict) or action.get("action") not in {"ADD", "REDUCE", "CLOSE"}:
            continue
        pid = action.get("position_id")
        if str(pid or "") == str(position_id) or (sole and pid in (None, "", "__first__")):
            matched.append(action)
    return matched


def residual_notional(pre_notional_usd: float, actions: list[dict[str, Any]]) -> dict[str, Any]:
    """Net the decision's size changes. An unsized REDUCE does not count as a harvest.

    Actions apply in order, so a later ADD restores exposure that an earlier REDUCE removed.
    """
    net = max(float(pre_notional_usd or 0.0), 0.0)
    reduced = 0.0
    added = 0.0
    for action in actions:
        kind = action.get("action")
        if kind == "CLOSE":
            reduced += max(net, 0.0)
            net = 0.0
        elif kind == "REDUCE":
            cut = _positive_notional(action)
            if cut is None:
                continue
            applied = min(cut, max(net, 0.0))
            net = round(max(0.0, net - applied), 2)
            reduced += applied
        elif kind == "ADD":
            add = _positive_notional(action) or 0.0
            net = round(net + add, 2)
            added += add
    pre = round(max(float(pre_notional_usd or 0.0), 0.0), 2)
    residual = round(max(net, 0.0), 2)
    fraction = None if pre <= 0 else round(residual / pre, 4)
    return {
        "pre_notional_usd": pre,
        "residual_notional_usd": residual,
        "residual_fraction": fraction,
        "reduced_usd": round(reduced, 2),
        "added_usd": round(added, 2),
    }


def _scaled_harvest(
    trade: dict[str, Any],
    position: dict[str, Any],
    residual: dict[str, Any],
    *,
    as_of: datetime | None,
) -> dict[str, Any]:
    """Harvest view of the size the decision would leave, not the size it started with."""
    pre = float(residual["pre_notional_usd"] or 0.0)
    net = float(residual["residual_notional_usd"] or 0.0)
    if pre <= 0 or net <= 0:
        return {"review_required": False, "review_triggers": [], "mechanical_order": False, "order_policy": ORDER_POLICY}
    scale = net / pre
    scaled_trade = deepcopy(trade)
    for key in ("mfe_usd", "mae_usd"):
        if scaled_trade.get(key) not in (None, ""):
            scaled_trade[key] = round(float(scaled_trade[key]) * scale, 2)
    scaled_trade["peak_notional_usd"] = net
    scaled_trade["initial_notional_usd"] = net
    scaled_trade["current_notional_usd"] = net
    scaled_trade["realized_pnl_usd"] = 0.0
    scaled_position = deepcopy(position)
    scaled_position["notional_usd"] = net
    if position.get("unrealized_pnl_usd") not in (None, ""):
        scaled_position["unrealized_pnl_usd"] = round(float(position["unrealized_pnl_usd"]) * scale, 2)
    return harvest_metrics(scaled_trade, scaled_position, as_of=as_of)


def residual_needs_justification(
    metrics: dict[str, Any],
    residual: dict[str, Any],
    scaled: dict[str, Any],
) -> bool:
    """True when the post-action size is still a kept triggered winner.

    A flat close, or a cut that leaves only a non-meaningful stub whose scaled
    P&L is no longer a material winner, does not need a remaining-edge answer.
    """
    if not metrics.get("review_required"):
        return False
    net = float(residual.get("residual_notional_usd") or 0.0)
    if net <= 0:
        return False
    pre = float(residual.get("pre_notional_usd") or 0.0)
    fraction = 1.0 if pre <= 0 else net / pre
    if fraction + 1e-12 >= MEANINGFUL_RESIDUAL_FRACTION:
        return True
    return bool(set(scaled.get("review_triggers") or []) & {"material_winner", "giveback"})


def review_metrics_for_residual(
    metrics: dict[str, Any],
    scaled: dict[str, Any],
    residual: dict[str, Any],
) -> dict[str, Any]:
    pre = float(residual.get("pre_notional_usd") or 0.0)
    net = float(residual.get("residual_notional_usd") or 0.0)
    fraction = 1.0 if pre <= 0 else net / pre
    if fraction + 1e-12 >= MEANINGFUL_RESIDUAL_FRACTION:
        triggers = list(metrics.get("review_triggers") or [])
    else:
        triggers = [name for name in (scaled.get("review_triggers") or []) if name in {"material_winner", "giveback"}]
        for clock in ("horizon_expired", "catalyst"):
            if clock in (metrics.get("review_triggers") or []) and triggers and clock not in triggers:
                triggers.append(clock)
    reviewed = dict(metrics)
    reviewed["review_required"] = True
    reviewed["review_triggers"] = triggers
    reviewed["full_size_hold_requires_reunderwrite"] = "horizon_expired" in triggers
    reviewed["residual_notional_usd"] = round(net, 2)
    reviewed["residual_fraction"] = round(fraction, 4)
    reviewed["mechanical_order"] = False
    reviewed["order_policy"] = ORDER_POLICY
    return reviewed


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
    fraction = metrics.get("residual_fraction")
    kept = "full size" if fraction is None or float(fraction) >= 0.999 else "the post-action residual"
    if not isinstance(review, dict):
        return (
            f"{label} harvest_review: {triggers} requires an explicit review before keeping {kept}. "
            f"{HARVEST_QUESTION} REDUCE and CLOSE still execute without this review. "
            "A cut does not authorize the residual. This is not a take-profit order."
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
            f"{label} harvest_review: keeping {kept} requires remaining_edge true and "
            f"would_initiate_flat yes. Thesis validity alone is not remaining edge. "
            "REDUCE and CLOSE remain executable without that answer."
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
                f"Keeping {kept} requires a fresh re-underwrite from current conditions ({exc}). "
                "A tactical trade does not become structural by silence."
            )
    return None


def _position_pre_notional(position: dict[str, Any], metrics: dict[str, Any]) -> float:
    pre = _money(position.get("notional_usd"))
    if pre is None:
        pre = _money(metrics.get("current_notional_usd")) or 0.0
    return float(pre)


def _obligation_due(trade: dict[str, Any]) -> bool:
    obligation = trade.get("harvest_obligation")
    return isinstance(obligation, dict) and obligation.get("status") == "due"


def _targets_position(action: dict[str, Any], position_id: str, *, sole: bool) -> bool:
    pid = action.get("position_id")
    hedge = action.get("hedge_of")
    if str(pid or "") == str(position_id) or str(hedge or "") == str(position_id):
        return True
    if sole and pid in (None, "", "__first__") and action.get("action") in DERISK_ACTIONS | REEXPANSION_ACTIONS:
        return True
    return False


def _book_level_continuation(action: dict[str, Any]) -> bool:
    return action.get("action") in CONTINUATION_ACTIONS and action.get("position_id") in (None, "", "__first__")


def continuation_rejection(actions: list[dict[str, Any]], blocked: list[dict[str, Any]]) -> str | None:
    """Reject a decision only when nothing left is an executable de-risk.

    A REDUCE or CLOSE keeps the decision applicable. The unjustified hold or add
    is split off later and is not a reason to discard the cut.
    """
    if not blocked:
        return None
    if any(isinstance(action, dict) and action.get("action") in DERISK_ACTIONS for action in actions):
        return None
    return str(blocked[0].get("reason") or "harvest_review required")


def enforce_harvest_hold(
    decision: dict[str, Any],
    trades: list[dict[str, Any]],
    positions: list[dict[str, Any]] | None,
    *,
    as_of: datetime | None = None,
    owner_id: str,
) -> dict[str, Any]:
    """Split harvest review from de-risk. Never blocks REDUCE or CLOSE.

    Returns accepted continuation reviews, continuation/add actions to block,
    and the residual obligations those cuts would leave. Does not emit an order.
    A missing review raises only through ``continuation_rejection`` when the
    decision has no de-risk leg.
    """
    actions = [row for row in (decision.get("actions") or []) if isinstance(row, dict)]
    open_positions = _open_positions(positions)
    rows = [
        (
            harvest_metrics(_match_trade(trades, position), position, as_of=as_of),
            _match_trade(trades, position),
            position,
        )
        for position in open_positions
    ]
    open_ids = [str(position.get("position_id")) for position in open_positions if position.get("position_id")]
    sole = len(open_ids) == 1
    pending: dict[str, dict[str, Any]] = {}
    derisk_plans: dict[str, dict[str, Any]] = {}
    for metrics, trade, position in rows:
        position_id = str(position.get("position_id") or "")
        if not position_id:
            continue
        pre = _position_pre_notional(position, metrics)
        matched = _actions_for_position(actions, position_id, open_ids)
        derisk_actions = [action for action in matched if action.get("action") in DERISK_ACTIONS]
        plan = residual_notional(pre, derisk_actions)
        scaled = _scaled_harvest(trade, position, plan, as_of=as_of)
        due = _obligation_due(trade)
        fraction = 1.0 if pre <= 0 else float(plan.get("residual_notional_usd") or 0.0) / pre if pre else 0.0
        needs = residual_needs_justification(metrics, plan, scaled) or (
            due and float(plan.get("residual_notional_usd") or 0.0) > 0 and fraction + 1e-12 >= MEANINGFUL_RESIDUAL_FRACTION
        )
        derisk_plans[position_id] = {"metrics": metrics, "trade": trade, "position": position, "plan": plan, "pre": pre}
        if needs:
            pending[position_id] = review_metrics_for_residual(metrics, scaled, plan)
    triggered_count = len(pending)
    blocked: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    authorized: set[str] = set()

    def _authorize(position_id: str, reviewed: dict[str, Any], review: dict[str, Any]) -> None:
        authorized.add(position_id)
        accepted.append(
            {
                "metrics_position_id": position_id,
                "review": review,
                "triggers": list(reviewed.get("review_triggers") or []),
                "residual_notional_usd": reviewed.get("residual_notional_usd"),
            }
        )

    for action in actions:
        kind = action.get("action")
        if kind in DERISK_ACTIONS:
            continue
        if kind in CONTINUATION_ACTIONS:
            targets = open_ids if _book_level_continuation(action) else [
                pid for pid in pending if _targets_position(action, pid, sole=sole)
            ]
            unmet: list[str] = []
            ready: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
            for position_id in targets:
                reviewed = pending.get(position_id)
                if not reviewed:
                    continue
                review = matching_review(decision, reviewed, triggered_count=triggered_count)
                reason = justification_reason(reviewed, review)
                if reason:
                    unmet.append(f"{owner_id} {reason}")
                elif isinstance(review, dict):
                    ready.append((position_id, reviewed, review))
            if unmet:
                blocked.append({"action": action, "reason": unmet[0], "result": "blocked"})
            else:
                for position_id, reviewed, review in ready:
                    _authorize(position_id, reviewed, review)
            continue
        if kind not in REEXPANSION_ACTIONS:
            continue
        for position_id, bundle in derisk_plans.items():
            if not _targets_position(action, position_id, sole=sole):
                continue
            restored = residual_notional(bundle["pre"], [*(
                action_row
                for action_row in _actions_for_position(actions, position_id, open_ids)
                if action_row.get("action") in DERISK_ACTIONS
            ), action])
            restored_scaled = _scaled_harvest(bundle["trade"], bundle["position"], restored, as_of=as_of)
            reviewed = pending.get(position_id)
            if reviewed is None and residual_needs_justification(bundle["metrics"], restored, restored_scaled):
                reviewed = review_metrics_for_residual(bundle["metrics"], restored_scaled, restored)
            if reviewed is None:
                continue
            # Judge the add against the size it would actually create on top of the cut.
            reviewed = dict(reviewed)
            reviewed["residual_notional_usd"] = restored.get("residual_notional_usd")
            reviewed["residual_fraction"] = restored.get("residual_fraction")
            reason = justification_reason(reviewed, matching_review(decision, reviewed, triggered_count=max(triggered_count, 1)))
            if reason:
                blocked.append({"action": action, "reason": f"{owner_id} {reason}", "result": "blocked"})
            else:
                review = matching_review(decision, reviewed, triggered_count=max(triggered_count, 1))
                if isinstance(review, dict):
                    _authorize(position_id, reviewed, review)
            break
    obligations = []
    for position_id, reviewed in pending.items():
        if position_id in authorized:
            continue
        obligations.append(
            {
                "position_id": position_id,
                "trade_id": reviewed.get("trade_id"),
                "residual_notional_usd": reviewed.get("residual_notional_usd"),
                "triggers": list(reviewed.get("review_triggers") or []),
                "status": "due",
            }
        )
    return {"accepted": accepted, "blocked": blocked, "obligations": obligations}


def assert_harvest_continuation(
    decision: dict[str, Any],
    trades: list[dict[str, Any]],
    positions: list[dict[str, Any]] | None,
    *,
    as_of: datetime | None = None,
    owner_id: str,
) -> dict[str, Any]:
    """Raise when a continuation decision has no executable de-risk leg."""
    plan = enforce_harvest_hold(decision, trades, positions, as_of=as_of, owner_id=owner_id)
    actions = [row for row in (decision.get("actions") or []) if isinstance(row, dict)]
    reason = continuation_rejection(actions, plan["blocked"])
    if reason:
        raise HarvestReviewError(reason)
    return plan


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
        # A continuation review answers the residual. Clearing happens in
        # sync_harvest_obligations so a pure reduce cannot consume this review.
        store.write_trade(updated)


def sync_harvest_obligations(
    store: Any,
    decision: dict[str, Any],
    *,
    owner_type: str,
    owner_id: str,
    positions_before: list[dict[str, Any]],
    allowed_actions: list[dict[str, Any]],
    when: datetime | None,
    run_id: str | None,
    as_of: datetime | None = None,
) -> None:
    """Record the residual that executed de-risk actually left.

    Blocked adds are not in ``allowed_actions``, so the obligation uses the
    post-cut size. An accepted continuation review clears it. REDUCE and CLOSE
    never require the review in order to run.
    """
    from scripts.trading.ledger import find_trade_by_position

    stamp = isoformat(now_ny(when))
    moment = as_of or when
    open_positions = _open_positions(positions_before)
    open_ids = [str(position.get("position_id")) for position in open_positions if position.get("position_id")]
    authorized = {
        str(item.get("metrics_position_id"))
        for item in (decision.get("_harvest_accepted") or [])
        if item.get("metrics_position_id")
    }
    for position in open_positions:
        position_id = str(position.get("position_id") or "")
        if not position_id:
            continue
        trade = find_trade_by_position(
            store, owner_type=owner_type, owner_id=owner_id, position_id=position_id
        )
        if not trade or trade.get("owner_id") != owner_id:
            continue
        metrics = harvest_metrics(trade, position, as_of=moment)
        pre = _position_pre_notional(position, metrics)
        executed = [
            action
            for action in allowed_actions
            if isinstance(action, dict)
            and action.get("action") in DERISK_ACTIONS | REEXPANSION_ACTIONS
            and _targets_position(action, position_id, sole=len(open_ids) == 1)
        ]
        plan = residual_notional(pre, executed)
        scaled = _scaled_harvest(trade, position, plan, as_of=moment)
        net = float(plan.get("residual_notional_usd") or 0.0)
        meaningful = net > 0 and residual_needs_justification(metrics, plan, scaled)
        updated = deepcopy(trade)
        if position_id in authorized or not meaningful:
            if isinstance(updated.get("harvest_obligation"), dict):
                updated["harvest_obligation"] = {
                    **updated["harvest_obligation"],
                    "status": "satisfied" if position_id in authorized else "retired",
                    "residual_notional_usd": plan.get("residual_notional_usd"),
                    "updated_at": stamp,
                    "run_id": run_id,
                    "mechanical_order": False,
                }
                store.write_trade(updated)
            continue
        reviewed = review_metrics_for_residual(metrics, scaled, plan)
        updated["harvest_obligation"] = {
            "status": "due",
            "position_id": position_id,
            "trade_id": trade.get("trade_id"),
            "residual_notional_usd": plan.get("residual_notional_usd"),
            "triggers": list(reviewed.get("review_triggers") or []),
            "updated_at": stamp,
            "run_id": run_id,
            "question": HARVEST_QUESTION,
            "order_policy": ORDER_POLICY,
            "mechanical_order": False,
        }
        store.write_trade(updated)
