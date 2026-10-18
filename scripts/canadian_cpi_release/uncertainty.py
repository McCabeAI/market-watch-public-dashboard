"""Empirical pseudo-OOS residual bands from B2 backtest errors."""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from scripts.canadian_cpi_release.contract import ERROR_QUANTILES


def uncertainty_from_errors(
    errors: Sequence[float],
    headline_b2: float | None,
) -> dict[str, Any]:
    """error = actual - forecast; bands = headline_B2 + quantile(error)."""
    arr = np.array(list(errors), dtype=float)
    n = len(arr)
    if n == 0:
        return {
            "reliability": "no_sample",
            "n_errors": 0,
            "quantiles": {},
            "bands": {},
            "label": (
                "Empirical pseudo-OOS residual band, latest index vintage; "
                "not a calibrated probability; not component-extreme sum."
            ),
        }
    q_vals = np.quantile(arr, ERROR_QUANTILES)
    quantiles = {str(q): float(v) for q, v in zip(ERROR_QUANTILES, q_vals)}
    bands = {}
    if headline_b2 is not None:
        bands = {str(q): float(headline_b2 + v) for q, v in zip(ERROR_QUANTILES, q_vals)}
    reliability = "short_sample" if n < 24 else "ok"
    return {
        "reliability": reliability,
        "n_errors": n,
        "error_quantiles": quantiles,
        "bands": bands,
        "label": (
            "Empirical pseudo-OOS residual band, latest index vintage; "
            "not a calibrated probability; not the sum of component extremes."
        ),
    }
