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
    "benchmark": "b2_ex_energy_forecast",
    "admitted": False,
    "evaluation_points": 0,
    "baseline_mae": None,
    "augmented_mae": None,
    "mae_improvement": None,
    "residual_beta": None,
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


def _ols_intercept_and_slope(y: list[float], x: list[float]) -> tuple[float, float]:
    """OLS intercept and slope for y ~ alpha + beta * x using centered normal equations."""
    if len(y) != len(x) or not x:
        return 0.0, 0.0
    n = len(x)
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    sxx = sum((xi - mean_x) ** 2 for xi in x)
    if sxx < _VAR_EPS:
        return mean_y, 0.0
    sxy = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    beta = sxy / sxx
    alpha = mean_y - beta * mean_x
    return alpha, beta


def _gate_result(
    *,
    admitted: bool,
    evaluation_points: int,
    baseline_mae: float | None,
    augmented_mae: float | None,
    mae_improvement: float | None,
    residual_beta: float | None,
    decision: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "predictor": "ippi_ex_energy_mom_lag1",
        "component": "cpi_nsa_ex_energy",
        "benchmark": "b2_ex_energy_forecast",
        "admitted": admitted,
        "evaluation_points": evaluation_points,
        "baseline_mae": baseline_mae,
        "augmented_mae": augmented_mae,
        "mae_improvement": mae_improvement,
        "residual_beta": residual_beta,
        "decision": decision,
        "reason": reason,
    }


def evaluate_ippi_gate(rows: list[dict]) -> dict[str, Any]:
    """Pseudo-OOS gate for IPPI ex-energy lag vs ex-energy component MoM (shadow by default)."""
    if not rows:
        return dict(_DEFAULT_GATE)

    parsed: list[tuple[float, float, float]] = []
    saw_ippi_or_component = False
    for row in rows:
        y = _safe_float(row.get("component_mom"))
        x = _safe_float(row.get("ippi_ex_energy_mom_lag1"))
        b2 = _safe_float(row.get("b2_ex_energy_forecast"))
        if y is not None or x is not None:
            saw_ippi_or_component = True
        if y is None or x is None or b2 is None:
            continue
        parsed.append((y, x, b2))

    min_rows = _MIN_TRAIN + _MIN_EVAL
    if len(parsed) < min_rows:
        if saw_ippi_or_component and not parsed:
            reason = (
                "missing_point_in_time_b2_ex_energy_forecast: "
                "aligned rows lack point-in-time b2_ex_energy_forecast"
            )
        elif saw_ippi_or_component:
            reason = (
                f"insufficient_history: need {min_rows} usable rows with "
                f"point-in-time b2_ex_energy_forecast, have {len(parsed)}"
            )
        else:
            reason = (
                f"insufficient_history: need {min_rows} aligned rows, have {len(parsed)}"
            )
        return _gate_result(
            admitted=False,
            evaluation_points=max(0, len(parsed) - _MIN_TRAIN),
            baseline_mae=None,
            augmented_mae=None,
            mae_improvement=None,
            residual_beta=None,
            decision="shadow_only",
            reason=reason,
        )

    baseline_errors: list[float] = []
    augmented_errors: list[float] = []
    last_beta: float | None = None

    for t in range(_MIN_TRAIN, len(parsed)):
        train = parsed[:t]
        y_t, x_t, b2_t = parsed[t]
        residuals = [p[0] - p[2] for p in train]
        xs = [p[1] for p in train]
        alpha, beta = _ols_intercept_and_slope(residuals, xs)
        last_beta = beta
        baseline_errors.append(abs(y_t - b2_t))
        aug_forecast = b2_t + alpha + beta * x_t
        augmented_errors.append(abs(y_t - aug_forecast))

    eval_n = len(baseline_errors)
    baseline_mae = sum(baseline_errors) / eval_n
    augmented_mae = sum(augmented_errors) / eval_n
    improvement = baseline_mae - augmented_mae

    admitted = eval_n >= _MIN_EVAL and improvement >= _MAE_IMPROVEMENT_PP
    if admitted:
        return _gate_result(
            admitted=True,
            evaluation_points=eval_n,
            baseline_mae=baseline_mae,
            augmented_mae=augmented_mae,
            mae_improvement=improvement,
            residual_beta=last_beta,
            decision="admitted",
            reason=(
                f"pseudo_oos_mae_improvement versus b2_ex_energy_forecast "
                f"{improvement:.4f} pp >= {_MAE_IMPROVEMENT_PP} on {eval_n} evaluation points"
            ),
        )

    reason = (
        f"pseudo_oos_mae_improvement versus b2_ex_energy_forecast "
        f"{improvement:.4f} pp < {_MAE_IMPROVEMENT_PP} on {eval_n} evaluation points"
        if eval_n >= _MIN_EVAL
        else f"insufficient_evaluation_points: {eval_n} < {_MIN_EVAL}"
    )
    return _gate_result(
        admitted=False,
        evaluation_points=eval_n,
        baseline_mae=baseline_mae,
        augmented_mae=augmented_mae,
        mae_improvement=improvement,
        residual_beta=last_beta,
        decision="shadow_only",
        reason=reason,
    )


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
