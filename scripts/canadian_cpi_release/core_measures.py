"""Official-style CPI-trim and CPI-median forecasts (not 55-component reconstruction)."""

from __future__ import annotations

from typing import Any

from scripts.canadian_cpi_release.contract import add_months
from scripts.canadian_cpi_release.model import compute_moms

CORE_TRIM = "core_trim_index"
CORE_MEDIAN = "core_median_index"


def _core_rate(moms: dict[str, float], release: str) -> float | None:
    prior = sorted(p for p in moms if p < release)
    if len(prior) < 6:
        return None
    last6 = [moms[p] for p in prior[-6:]]
    last3 = last6[-3:]
    return 0.5 * (sum(last3) / 3.0 + sum(last6) / 6.0)


def forecast_core_measure(
    levels: dict[str, float],
    release: str,
    measure_id: str,
) -> dict[str, Any]:
    moms = compute_moms(levels)
    rate = _core_rate(moms, release)
    t1 = add_months(release, -1)
    t3 = add_months(release, -3)
    t12 = add_months(release, -12)
    if rate is None or t1 not in levels or t12 not in levels:
        return {
            "measure": measure_id,
            "status": "unavailable",
            "reason": "Fewer than six prior month-over-month observations.",
        }
    forecast_level = levels[t1] * (1.0 + rate / 100.0)
    yoy = 100.0 * (forecast_level / levels[t12] - 1.0)
    annualized_3m = None
    if t3 in levels and levels[t3] > 0:
        annualized_3m = 100.0 * ((forecast_level / levels[t3]) ** 4 - 1.0)
    return {
        "measure": measure_id,
        "status": "available",
        "mom_forecast": rate,
        "forecast_level": forecast_level,
        "previous_level": levels[t1],
        "base_level": levels[t12],
        "yoy_forecast": yoy,
        "annualized_3m": annualized_3m,
        "method": "mean3_mean6_blend",
        "note": "Not a 55-component CPI reconstruction.",
    }


def build_core_block(
    level_series: dict[str, dict[str, float]],
    release: str,
) -> dict[str, Any]:
    trim = forecast_core_measure(level_series.get(CORE_TRIM, {}), release, CORE_TRIM)
    median = forecast_core_measure(level_series.get(CORE_MEDIAN, {}), release, CORE_MEDIAN)
    return {
        "cpi_common": {
            "status": "unavailable",
            "reason": "CPI-common factor model is not identified in this engine.",
        },
        "cpi_trim": trim,
        "cpi_median": median,
        "reconstruction_note": (
            "Core trim and median are forecast from official index histories only; "
            "no research-proxy trim from CPI components."
        ),
    }
