"""Allocator mandate pressure for automated PMs (context only)."""

from __future__ import annotations

from typing import Any

from scripts.pm.constants import AUTOMATED_PM_IDS, CASH_CAPITAL_USD, MAX_DRAWDOWN_USD
from scripts.trading.constants import MATERIAL_DRAWDOWN_FRACTION
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


def _spx_total_return(market_state: dict[str, Any] | None) -> float | None:
    if not market_state:
        return None
    for path in (
        ("equities", "spx", "total_return_ytd"),
        ("equities", "SPX", "total_return_ytd"),
        ("spx_total_return_ytd"),
    ):
        if len(path) == 1:
            value = market_state.get(path[0])
        else:
            node = market_state
            for key in path:
                if not isinstance(node, dict):
                    node = None
                    break
                node = node.get(key)
            value = node
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def build_capital_owner(
    store: TradingStore,
    pm_id: str,
    *,
    consequence: dict[str, Any] | None,
    market_state: dict[str, Any] | None = None,
    pm_book: dict[str, Any] | None = None,
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
        if drawdown >= threshold and not compensated:
            standing = "watch"
            pressure_flags.append("uncompensated_drawdown")
            notes.append(
                "I love risk. I'm starting to think you just suck at taking it."
            )
        elif drawdown >= threshold and compensated:
            notes.append("Drawdown is real, but outsized gains have compensated the pain.")
        elif drawdown >= threshold:
            notes.append("Large drawdown without enough offsetting upside yet.")

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
        zero_alpha = near_zero
        persistent = near_zero and flat_history >= 2
        if persistent:
            standing = "watch"
            pressure_flags.append("persistent_zero_alpha")
            notes.append("Repeated flat SOFR-hurdle books suggest you need to beat cash, not hide in it.")
        elif near_zero and flat_history == 0:
            notes.append("Flat versus SOFR is zero alpha; first snapshot, no persistence claim yet.")
        return {
            "standing": standing,
            "mandate": "grinder",
            "hurdle": "SOFR",
            "zero_alpha": zero_alpha,
            "persistent_zero_alpha": persistent,
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


def record_grinder_flat_snapshot(store: TradingStore, pm_id: str, consequence: dict[str, Any]) -> None:
    if pm_id != "grinder" or consequence.get("status") != "ok":
        return
    net = float(consequence.get("net_after_funding_pnl_usd") or 0.0)
    max_dd = float(consequence.get("max_drawdown_usd") or MAX_DRAWDOWN_USD)
    threshold = MATERIAL_DRAWDOWN_FRACTION * max_dd
    near_zero = abs(net) < max(50_000.0, threshold * 0.02)
    state = store.read_consequence_state("pm", pm_id)
    count = int(state.get("grinder_flat_snapshots") or 0)
    state["grinder_flat_snapshots"] = count + 1 if near_zero else 0
    store.write_consequence_state("pm", pm_id, state)
