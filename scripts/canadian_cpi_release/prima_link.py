"""Medium-term Prima-pressure context for CPI nowcast reports (not a B2 input)."""

from __future__ import annotations

import copy
from typing import Any

_VAR_EPS = 1e-18
_MIN_TRAIN = 24
_MIN_EVAL = 24
_MAE_IMPROVEMENT_PP = 0.02

_DEFAULT_GATE = {
    "predictor": "ippi_ex_energy_mom_lag1",
    "component": "cpi_nsa_ex_energy",
    "admitted": False,
    "evaluation_points": 0,
    "baseline_mae": None,
    "augmented_mae": None,
    "mae_improvement": None,
    "decision": "shadow_only",
    "reason": "no_aligned_ippi_history_in_cpi_fixture",
}

_DEFAULT_BLOCK = {"direction": "UNAVAILABLE", "status": "not_supplied"}

_NOTE = (
    "The Prima-pressure proxy is not an input to the B2 next-print nowcast. "
    "NRCan gasoline and furnace-oil bridges are unchanged."
)


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ols_slope(y_resid: list[float], x: list[float]) -> float:
    if len(y_resid) != len(x) or not x:
        return 0.0
    n = len(x)
    mean_x = sum(x) / n
    var_x = sum((xi - mean_x) ** 2 for xi in x) / n
    if var_x < _VAR_EPS:
        return 0.0
    num = sum(yi * xi for yi, xi in zip(y_resid, x))
    den = sum(xi * xi for xi in x)
    if abs(den) < _VAR_EPS:
        return 0.0
    return num / den


def evaluate_ippi_gate(rows: list[dict]) -> dict[str, Any]:
    """Pseudo-OOS gate for IPPI ex-energy lag vs ex-energy component MoM (shadow by default)."""
    predictor = "ippi_ex_energy_mom_lag1"
    component = "cpi_nsa_ex_energy"

    parsed: list[tuple[float, float]] = []
    for row in rows:
        y = _safe_float(row.get("component_mom"))
        x = _safe_float(row.get("ippi_ex_energy_mom_lag1"))
        if y is None or x is None:
            continue
        parsed.append((y, x))

    if len(parsed) < _MIN_TRAIN + _MIN_EVAL:
        return {
            "predictor": predictor,
            "component": component,
            "admitted": False,
            "evaluation_points": max(0, len(parsed) - _MIN_TRAIN),
            "baseline_mae": None,
            "augmented_mae": None,
            "mae_improvement": None,
            "decision": "shadow_only",
            "reason": (
                f"insufficient_history: need {_MIN_TRAIN + _MIN_EVAL} aligned rows, "
                f"have {len(parsed)}"
            ),
        }

    baseline_errors: list[float] = []
    augmented_errors: list[float] = []

    for t in range(_MIN_TRAIN, len(parsed)):
        train = parsed[:t]
        y_t, x_t = parsed[t]
        ys = [p[0] for p in train]
        xs = [p[1] for p in train]
        mean_prior = sum(ys) / len(ys)
        y_resid = [y - mean_prior for y in ys]
        beta = _ols_slope(y_resid, xs)
        baseline_errors.append(abs(y_t - mean_prior))
        aug_forecast = mean_prior + beta * x_t
        augmented_errors.append(abs(y_t - aug_forecast))

    eval_n = len(baseline_errors)
    baseline_mae = sum(baseline_errors) / eval_n
    augmented_mae = sum(augmented_errors) / eval_n
    improvement = baseline_mae - augmented_mae

    admitted = eval_n >= _MIN_EVAL and improvement >= _MAE_IMPROVEMENT_PP
    if admitted:
        return {
            "predictor": predictor,
            "component": component,
            "admitted": True,
            "evaluation_points": eval_n,
            "baseline_mae": baseline_mae,
            "augmented_mae": augmented_mae,
            "mae_improvement": improvement,
            "decision": "admitted",
            "reason": (
                f"pseudo_oos_mae_improvement {improvement:.4f} pp "
                f">= {_MAE_IMPROVEMENT_PP} on {eval_n} evaluation points"
            ),
        }

    reason = (
        f"pseudo_oos_mae_improvement {improvement:.4f} pp "
        f"< {_MAE_IMPROVEMENT_PP} on {eval_n} evaluation points"
        if eval_n >= _MIN_EVAL
        else f"insufficient_evaluation_points: {eval_n} < {_MIN_EVAL}"
    )
    return {
        "predictor": predictor,
        "component": component,
        "admitted": False,
        "evaluation_points": eval_n,
        "baseline_mae": baseline_mae,
        "augmented_mae": augmented_mae,
        "mae_improvement": improvement,
        "decision": "shadow_only",
        "reason": reason,
    }


def attach_medium_term_prima(
    payload: dict[str, Any],
    block: dict | None,
    gate: dict | None = None,
) -> dict[str, Any]:
    """Attach medium-term Prima context without altering headline or B2 forecast fields."""
    out = copy.deepcopy(payload)
    gate_out = dict(gate) if gate is not None else dict(_DEFAULT_GATE)
    block_out = dict(block) if block is not None else dict(_DEFAULT_BLOCK)

    if gate_out.get("admitted"):
        activation_held = "gate_passed_but_not_wired_into_b2"
    else:
        activation_held = "shadow_only"

    out["medium_term_prima_pressure"] = {
        "role": "medium_term_context_not_a_b2_input",
        "forecast_active": False,
        "activation_held": activation_held,
        "gate": gate_out,
        "block": block_out,
        "note": _NOTE,
    }
    return out
