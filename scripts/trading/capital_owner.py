"""Allocator mandate pressure for automated PMs (context only)."""

from __future__ import annotations

from typing import Any

from scripts.pm.constants import AUTOMATED_PM_IDS, CASH_CAPITAL_USD, MAX_DRAWDOWN_USD
from scripts.trading.constants import MATERIAL_DRAWDOWN_FRACTION, SWINGER_ESCALATION_EPISODES
from scripts.trading.store import TradingStore


def _stress_regime(market_state: dict[str, Any] | None) -> str:
    if not market_state:
        return "unknown"
    for key in ("stress_regime", "regime_stress", "risk_regime"):
        value = market_state.get(key)
        if isinstance(value, str) and value.strip():
            lowered = value.strip().lower()
            if lowered in {"stress", "stressed", "crisis", "risk_off"}:
                return "stress"
            if lowered in {"normal", "calm", "risk_on"}:
                return "normal"
    overlay = market_state.get("macro_overlay") or market_state.get("overlay")
    if isinstance(overlay, dict):
        flag = overlay.get("stress") or overlay.get("stress_regime")
        if isinstance(flag, bool):
            return "stress" if flag else "normal"
        if isinstance(flag, str) and flag.strip().lower() in {"stress", "stressed", "true"}:
            return "stress"
    evidence = market_state.get("evidence") or {}
    if isinstance(evidence, dict):
        for block in evidence.values():
            if isinstance(block, dict) and block.get("stress_regime") is True:
                return "stress"
    return "unknown"


def _float_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _spx_from_series(rows: Any) -> float | None:
    if isinstance(rows, dict):
        rows = rows.get("series") or rows.get("rows") or []
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = str(row.get("id") or row.get("symbol") or row.get("name") or "").upper()
        if label not in {"SP500", "SPX", "GSPC", "SPXT"}:
            continue
        for key in ("total_return_ytd", "total_return", "total_return_pct"):
            number = _float_or_none(row.get(key))
            if number is not None:
                return number
    return None


def _spx_total_return(market_state: dict[str, Any] | None) -> float | None:
    if not market_state:
        return None
    for path in (
        ("equities", "spx", "total_return_ytd"),
        ("equities", "SPX", "total_return_ytd"),
        ("spx_total_return_ytd",),
        ("cross_assets", "SP500", "total_return_ytd"),
        ("opportunities", "SP500", "total_return_ytd"),
    ):
        node: Any = market_state
        for key in path:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(key)
        number = _float_or_none(node)
        if number is not None:
            return number
    for key in ("opportunities", "cross_assets", "equities"):
        found = _spx_from_series(market_state.get(key))
        if found is not None:
            return found
    return None


def opportunity_status_from_packet(packet: dict[str, Any] | None) -> str:
    """Trusted frozen handoff opportunities. Unknown when no packet was supplied."""
    if not isinstance(packet, dict):
        return "unknown"
    from scripts.pm.portfolio import independent_markable_handoff_opportunities

    rows = independent_markable_handoff_opportunities(packet)
    return "present" if rows else "none"


def build_capital_owner(
    store: TradingStore,
    pm_id: str,
    *,
    consequence: dict[str, Any] | None,
    market_state: dict[str, Any] | None = None,
    pm_book: dict[str, Any] | None = None,
    review_packet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if pm_id not in AUTOMATED_PM_IDS:
        return {"standing": "not_applicable", "mandate": "synthesis"}
    if consequence is None or consequence.get("status") != "ok":
        return {"standing": "not_applicable", "mandate": pm_id, "status": "unavailable"}
    max_dd = float((pm_book or {}).get("max_drawdown_usd") or MAX_DRAWDOWN_USD)
    threshold = MATERIAL_DRAWDOWN_FRACTION * max_dd
    net = float(consequence.get("net_after_funding_pnl_usd") or 0.0)
    drawdown = float(consequence.get("drawdown_usd") or 0.0)
    high_water = float(consequence.get("high_water_nav_usd") or CASH_CAPITAL_USD)
    starting = float((pm_book or {}).get("cash_capital_usd") or CASH_CAPITAL_USD)
    prior = store.read_consequence_state("pm", pm_id)
    notes: list[str] = []
    standing = "good_standing"
    pressure_flags: list[str] = []

    if pm_id == "swinger":
        compensated = net >= threshold or high_water > starting + threshold
        episodes = int(prior.get("swinger_uncompensated_episodes") or 0)
        uncompensated = drawdown >= threshold and not compensated
        if uncompensated and episodes >= SWINGER_ESCALATION_EPISODES:
            standing = "watch"
            pressure_flags.append("repeated_uncompensated_drawdown")
            notes.append("I love risk. I'm starting to think you just suck at taking it.")
        elif uncompensated:
            notes.append(
                "A single large drawdown is inside the swinger mandate. "
                "Allocator escalation requires repeated uncompensated pain without an outsized payoff."
            )
        elif drawdown >= threshold and compensated:
            notes.append("Drawdown is real, but outsized gains have compensated the pain.")

    elif pm_id == "pragmatist":
        annual_low = 20_000_000
        annual_high = 60_000_000
        notes.append(
            f"Mandate band is roughly 2–6% on ${CASH_CAPITAL_USD / 1_000_000:.0f}bn paper NAV "
            f"(${annual_low / 1_000_000:.0f}mm–${annual_high / 1_000_000:.0f}mm annual objective)."
        )
        spx = _spx_total_return(market_state)
        if spx is None:
            spx_context = {"status": "unavailable"}
        else:
            spx_context = {
                "status": "ok",
                "spx_total_return_ytd": spx,
                "opportunity_cost_context_pct": round(spx - 4.0, 4),
            }
            notes.append(
                f"Normal-regime context: S&P 500 total return {spx:.2f}% minus 4pp is "
                f"{spx - 4:.2f}% — pressure context, not a lever instruction."
            )
        stress = _stress_regime(market_state)
        if stress == "stress":
            notes.append("Stress regime: capital preservation matters more; equity-relative context is not the target.")
        elif stress == "normal":
            notes.append("Normal regime: dependable FICC return remains the primary objective.")
        else:
            notes.append("Stress regime unknown: evaluation cannot switch regimes from frozen inputs alone.")
        # Pace versus the annual band needs elapsed time. A flat or young book is not a shortfall.
        return {
            "standing": standing,
            "mandate": "pragmatist",
            "annual_objective_pct_low": 2.0,
            "annual_objective_pct_high": 6.0,
            "annual_objective_usd_low": annual_low,
            "annual_objective_usd_high": annual_high,
            "spx_context": spx_context if pm_id == "pragmatist" else None,
            "stress_regime": stress,
            "notes": notes,
            "pressure_flags": pressure_flags,
            "force_deployment": False,
        }

    elif pm_id == "grinder":
        near_zero = abs(net) < max(50_000.0, threshold * 0.02)
        flat_history = int(prior.get("grinder_flat_snapshots") or 0)
        opportunities = opportunity_status_from_packet(review_packet)
        zero_alpha = near_zero
        missed = near_zero and flat_history >= 2 and opportunities == "present"
        if missed:
            standing = "watch"
            pressure_flags.append("missed_opportunity_zero_alpha")
            notes.append(
                "Repeated flat SOFR-hurdle results while frozen markable opportunities were available. "
                "Selectivity is still allowed; deployment is not forced."
            )
        elif near_zero and opportunities == "none":
            notes.append(
                "Flat versus SOFR is zero alpha, but the frozen packet has no markable opportunity. Sitting out is legitimate."
            )
        elif near_zero and opportunities == "unknown":
            notes.append(
                "Flat versus SOFR is zero alpha. Opportunity availability is unknown in the frozen packet, so no missed-opportunity claim is made."
            )
        elif near_zero:
            notes.append("Flat versus SOFR is zero alpha. No persistence claim yet.")
        return {
            "standing": standing,
            "mandate": "grinder",
            "hurdle": "SOFR",
            "zero_alpha": zero_alpha,
            "persistent_zero_alpha": missed,
            "credible_opportunities": opportunities,
            "force_deployment": False,
            "notes": notes,
            "pressure_flags": pressure_flags,
        }

    return {
        "standing": standing,
        "mandate": pm_id,
        "notes": notes,
        "pressure_flags": pressure_flags,
        "force_deployment": False,
    }

