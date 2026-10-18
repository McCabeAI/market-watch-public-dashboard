"""Canadian seasonal/momentum ridge and baseline forecasts."""

from __future__ import annotations

import calendar
from typing import Sequence

import numpy as np

from scripts.canadian_cpi_release.contract import (
    MIN_OBS_BASELINE,
    MIN_OBS_BRIDGE,
    RIDGE_PENALTY,
    RIDGE_STABILITY,
    SEASONAL_COLUMNS,
    TRAIN_WINDOW,
    add_months,
)


def month_number(period: str) -> int:
    return int(period[5:7])


def compute_moms(levels: dict[str, float]) -> dict[str, float]:
    """Month-over-month percent for strictly adjacent YYYY-MM periods."""
    periods = sorted(levels.keys())
    moms: dict[str, float] = {}
    for i in range(1, len(periods)):
        prev_p, p = periods[i - 1], periods[i]
        if add_months(prev_p, 1) != p:
            continue
        prev_v, v = levels[prev_p], levels[p]
        if prev_v == 0:
            continue
        moms[p] = 100.0 * (v / prev_v - 1.0)
    return moms


def _season5_mean(moms: dict[str, float], target: str) -> float | None:
    tgt_m = month_number(target)
    same = [moms[p] for p in sorted(moms) if month_number(p) == tgt_m and p < target]
    if same:
        return float(np.mean(same[-5:]))
    recent = [moms[p] for p in sorted(moms) if p < target]
    if len(recent) >= 3:
        return float(np.mean(recent[-3:]))
    if recent:
        return float(np.mean(recent))
    return None


def baseline_carry_mean3_season5(
    moms: dict[str, float], target: str
) -> tuple[float | None, float | None, float | None]:
    """Baselines from moms strictly before ``target``."""
    prior = sorted(p for p in moms if p < target)
    if not prior:
        return None, None, None
    carry = moms[prior[-1]]
    mean3 = float(np.mean([moms[p] for p in prior[-3:]])) if prior else None
    season5 = _season5_mean(moms, target)
    return carry, mean3, season5


def _build_design_row(
    period: str,
    moms: dict[str, float],
    extra: dict[str, float | None],
    extra_names: Sequence[str],
) -> list[float] | None:
    m = month_number(period)
    row: list[float] = [0.0] * 12
    row[m - 1] = 1.0
    prev = add_months(period, -1)
    if prev not in moms:
        return None
    lag1 = moms[prev]
    prev3 = [add_months(period, -k) for k in (1, 2, 3)]
    if not all(p in moms for p in prev3):
        return None
    mean3 = float(np.mean([moms[p] for p in prev3]))
    row.extend([lag1, mean3])
    for name in extra_names:
        val = extra.get(name)
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return None
        row.append(float(val))
    return row


def ridge_mom_forecast(
    moms: dict[str, float],
    target: str,
    *,
    extra_by_period: dict[str, dict[str, float | None]] | None = None,
    extra_names: Sequence[str] = (),
    min_obs: int = MIN_OBS_BASELINE,
) -> float | None:
    """Rolling ridge on moms strictly before ``target``; predict mom at ``target``."""
    extra_by_period = extra_by_period or {}
    train_periods = sorted(p for p in moms if p < target)
    rows_y: list[tuple[list[float], float]] = []
    for p in train_periods:
        ex = extra_by_period.get(p, {})
        row = _build_design_row(p, moms, ex, extra_names)
        if row is None:
            continue
        if p not in moms:
            continue
        rows_y.append((row, moms[p]))
    if len(rows_y) > TRAIN_WINDOW:
        rows_y = rows_y[-TRAIN_WINDOW:]
    if len(rows_y) < min_obs:
        return None
    x_train = np.array([r for r, _ in rows_y], dtype=float)
    y_train = np.array([y for _, y in rows_y], dtype=float)
    ex_t = extra_by_period.get(target, {})
    target_row = _build_design_row(target, moms, ex_t, extra_names)
    if target_row is None:
        return None
    x_target = np.array(target_row, dtype=float)
    scale = np.std(x_train, axis=0, ddof=0)
    scale[scale < 1e-9] = 1.0
    x_train_s = x_train / scale
    x_target_s = x_target / scale
    n_cols = x_train_s.shape[1]
    penalty = np.eye(n_cols, dtype=float) * RIDGE_PENALTY
    penalty[:SEASONAL_COLUMNS, :SEASONAL_COLUMNS] = 0.0
    penalty += np.eye(n_cols, dtype=float) * RIDGE_STABILITY
    xtx = x_train_s.T @ x_train_s + penalty
    xty = x_train_s.T @ y_train
    try:
        coef = np.linalg.solve(xtx, xty)
    except np.linalg.LinAlgError:
        return None
    return float(x_target_s @ coef)


def forecast_model_a(moms: dict[str, float], target: str) -> tuple[float, str]:
    """Model A with season5 fallback when ridge unavailable."""
    ridge = ridge_mom_forecast(moms, target, min_obs=MIN_OBS_BASELINE)
    if ridge is not None:
        return ridge, "modeled"
    _, _, season5 = baseline_carry_mean3_season5(moms, target)
    if season5 is not None:
        return season5, "fallback_baseline"
    carry, mean3, _ = baseline_carry_mean3_season5(moms, target)
    if mean3 is not None:
        return mean3, "fallback_baseline"
    if carry is not None:
        return carry, "fallback_baseline"
    return 0.0, "fallback_baseline"


def forecast_bridge(
    moms: dict[str, float],
    target: str,
    extra_by_period: dict[str, dict[str, float | None]],
    extra_names: Sequence[str],
) -> tuple[float | None, str]:
    """Direct bridge ridge; None forecast means fall back to model A at caller."""
    ridge = ridge_mom_forecast(
        moms,
        target,
        extra_by_period=extra_by_period,
        extra_names=extra_names,
        min_obs=MIN_OBS_BRIDGE,
    )
    if ridge is not None:
        return ridge, "observed_bridge"
    return None, "fallback_baseline"
