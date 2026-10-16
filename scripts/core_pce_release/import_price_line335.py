"""BEA line 335 import/PPI NNLS calendar-SA nowcast (pre-specified backtest)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from scripts.core_pce_release.history import shift_month
from scripts.core_pce_release.import_price_fixture import _DEFAULT_BUNDLE_DIR

MODEL_ID = "line335_nnls_calendar_sa_v1"
MIN_TRAIN = 60
NEG_TOL = 1e-10
PANEL_START = "2007-02"
PANEL_END_LABEL = "2026-08"
TARGET_PERIOD = "2026-09"
TRAINING_END = "2026-08"


def _default_history_path() -> Path:
    return _DEFAULT_BUNDLE_DIR / "line335_history.json"


def _mom_ratio(index_t: float, index_prev: float) -> float:
    return (index_t / index_prev - 1.0) * 100.0


def _parse_index_map(raw: dict[str, str]) -> dict[str, float]:
    return {period: float(value) for period, value in raw.items()}


def _period_range(start: str, end: str) -> list[str]:
    periods: list[str] = []
    current = start
    while current <= end:
        periods.append(current)
        current = shift_month(current, 1)
    return periods


def _build_panel(history: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    bea = _parse_index_map(history["bea_indexes"])
    preds = history["predictors"]
    import_idx = _parse_index_map(preds["import_air_passenger_fares"]["indexes"])
    ppi_idx = _parse_index_map(preds["ppi_international_scheduled_passenger"]["indexes"])

    rows: list[dict[str, Any]] = []
    for period in _period_range(PANEL_START, TARGET_PERIOD):
        prior = shift_month(period, -1)
        if prior not in bea or period not in bea:
            bea_mom: float | None = None
        else:
            bea_mom = _mom_ratio(bea[period], bea[prior])
        if prior not in import_idx or period not in import_idx:
            continue
        if prior not in ppi_idx or period not in ppi_idx:
            continue
        import_mom = _mom_ratio(import_idx[period], import_idx[prior])
        ppi_mom = _mom_ratio(ppi_idx[period], ppi_idx[prior])
        month = int(period.split("-")[1])
        labeled = period <= PANEL_END_LABEL and bea_mom is not None
        rows.append(
            {
                "period": period,
                "calendar_month": month,
                "bea_mom": bea_mom,
                "import_nsa_mom": import_mom,
                "ppi_nsa_mom": ppi_mom,
                "labeled": labeled,
            }
        )
    meta = {
        "panel_start": PANEL_START,
        "panel_end_label": PANEL_END_LABEL,
        "target_period": TARGET_PERIOD,
        "model_id": MODEL_ID,
    }
    return rows, meta


def _seasonal_factors(training: list[dict[str, Any]]) -> dict[str, dict[int, float]]:
    buckets: dict[str, dict[int, list[float]]] = {
        "import": {m: [] for m in range(1, 13)},
        "ppi": {m: [] for m in range(1, 13)},
    }
    for row in training:
        m = row["calendar_month"]
        buckets["import"][m].append(row["import_nsa_mom"])
        buckets["ppi"][m].append(row["ppi_nsa_mom"])
    out: dict[str, dict[int, float]] = {"import": {}, "ppi": {}}
    for leg in ("import", "ppi"):
        for m in range(1, 13):
            vals = buckets[leg][m]
            out[leg][m] = sum(vals) / len(vals) if len(vals) >= 3 else 0.0
    return out


def _sa_row(row: dict[str, Any], factors: dict[str, dict[int, float]]) -> tuple[float, float]:
    m = row["calendar_month"]
    import_sa = row["import_nsa_mom"] - factors["import"][m]
    ppi_sa = row["ppi_nsa_mom"] - factors["ppi"][m]
    return import_sa, ppi_sa


def _solve_linear(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    mat = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = col
        for r in range(col + 1, n):
            if abs(mat[r][col]) > abs(mat[pivot][col]):
                pivot = r
        if abs(mat[pivot][col]) < 1e-15:
            raise ValueError("singular")
        mat[col], mat[pivot] = mat[pivot], mat[col]
        div = mat[col][col]
        for r in range(col + 1, n):
            if abs(mat[r][col]) < 1e-15:
                continue
            factor = mat[r][col] / div
            for c in range(col, n + 1):
                mat[r][c] -= factor * mat[col][c]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        s = mat[i][n]
        for j in range(i + 1, n):
            s -= mat[i][j] * x[j]
        x[i] = s / mat[i][i]
    return x


def _ols(design: list[list[float]], y: list[float]) -> list[float]:
    k = len(design[0])
    n = len(y)
    xtx = [[0.0] * k for _ in range(k)]
    xty = [0.0] * k
    for i in range(n):
        row = design[i]
        for a in range(k):
            xty[a] += row[a] * y[i]
            for b in range(k):
                xtx[a][b] += row[a] * row[b]
    return _solve_linear(xtx, xty)


def _fit_constrained(
    training: list[dict[str, Any]],
    factors: dict[str, dict[int, float]],
) -> tuple[float, float, float, str]:
    y = [row["bea_mom"] for row in training]
    import_sa = []
    ppi_sa = []
    for row in training:
        i_sa, p_sa = _sa_row(row, factors)
        import_sa.append(i_sa)
        ppi_sa.append(p_sa)

    design = [[1.0, import_sa[i], ppi_sa[i]] for i in range(len(y))]
    b0, b1, b2 = _ols(design, y)

    if b1 >= -NEG_TOL and b2 >= -NEG_TOL:
        return b0, max(0.0, b1), max(0.0, b2), "both"
    if b1 < -NEG_TOL and b2 < -NEG_TOL:
        return sum(y) / len(y), 0.0, 0.0, "intercept"
    if b1 < -NEG_TOL:
        coeffs = _ols([[1.0, ppi_sa[i]] for i in range(len(y))], y)
        return coeffs[0], 0.0, max(0.0, coeffs[1]), "ppi_only"
    coeffs = _ols([[1.0, import_sa[i]] for i in range(len(y))], y)
    return coeffs[0], max(0.0, coeffs[1]), 0.0, "import_only"


def _predict(
    row: dict[str, Any],
    factors: dict[str, dict[int, float]],
    b0: float,
    b1: float,
    b2: float,
) -> float:
    import_sa, ppi_sa = _sa_row(row, factors)
    return b0 + b1 * import_sa + b2 * ppi_sa


def _labeled_rows(panel: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in panel if row["labeled"]]


def _filter_history_before(history: dict[str, Any], period: str) -> dict[str, Any]:
    bea = {k: v for k, v in history["bea_indexes"].items() if k < period}
    out = json.loads(json.dumps(history))
    out["bea_indexes"] = bea
    return out


def load_line335_history(path: Path | None = None) -> dict[str, Any]:
    p = Path(path) if path is not None else _default_history_path()
    return json.loads(p.read_text(encoding="utf-8"))


def walk_forward(history: dict[str, Any]) -> dict[str, Any]:
    panel, _ = _build_panel(history)
    labeled = _labeled_rows(panel)
    records: list[dict[str, Any]] = []
    errs_model: list[float] = []
    errs_carry: list[float] = []
    errs_three: list[float] = []

    for i in range(MIN_TRAIN, len(labeled)):
        train = labeled[:i]
        test = labeled[i]
        factors = _seasonal_factors(train)
        b0, b1, b2, mode = _fit_constrained(train, factors)
        pred = _predict(test, factors, b0, b1, b2)
        actual = test["bea_mom"]
        carry = labeled[i - 1]["bea_mom"]
        prev3 = [labeled[i - k]["bea_mom"] for k in range(1, 4)]
        three = sum(prev3) / 3.0
        e_model = pred - actual
        e_carry = carry - actual
        e_three = three - actual
        errs_model.append(e_model)
        errs_carry.append(e_carry)
        errs_three.append(e_three)
        records.append(
            {
                "period": test["period"],
                "actual": actual,
                "prediction": pred,
                "carry": carry,
                "three_month": three,
                "error_model": e_model,
                "error_carry": e_carry,
                "error_three_month": e_three,
                "mode": mode,
                "coefficients": [b0, b1, b2],
            }
        )

    def _mae(errs: list[float]) -> float:
        return sum(abs(e) for e in errs) / len(errs) if errs else float("nan")

    def _bias(errs: list[float]) -> float:
        return sum(errs) / len(errs) if errs else float("nan")

    mae_model = _mae(errs_model)
    mae_carry = _mae(errs_carry)
    mae_three = _mae(errs_three)
    bias_model = _bias(errs_model)
    n = len(records)
    mid = n // 2

    def _half_metrics(start: int, end: int) -> dict[str, float]:
        em = errs_model[start:end]
        ec = errs_carry[start:end]
        et = errs_three[start:end]
        return {
            "mae_model": _mae(em),
            "mae_carry": _mae(ec),
            "mae_three_month": _mae(et),
            "bias_model": _bias(em),
            "n": float(end - start),
        }

    halves = {
        "first": _half_metrics(0, mid),
        "second": _half_metrics(mid, n),
    }

    min_base = min(mae_carry, mae_three)
    gate = (
        n >= 60
        and mae_model < mae_carry
        and mae_model < mae_three
        and mae_model <= 0.90 * min_base
        and (min_base - mae_model) >= 0.10
        and abs(bias_model) < 0.50
        and halves["first"]["mae_model"] < halves["first"]["mae_carry"]
        and halves["first"]["mae_model"] < halves["first"]["mae_three_month"]
        and halves["second"]["mae_model"] < halves["second"]["mae_carry"]
        and halves["second"]["mae_model"] < halves["second"]["mae_three_month"]
    )

    if labeled:
        final_train = labeled
        final_factors = _seasonal_factors(final_train)
        fb0, fb1, fb2, fmode = _fit_constrained(final_train, final_factors)
        gate = gate and (fb1 > 0.0 or fb2 > 0.0) and fmode != "intercept"

    window = {
        "start": records[0]["period"] if records else None,
        "end": records[-1]["period"] if records else None,
        "min_train_months": MIN_TRAIN,
    }

    return {
        "model_id": MODEL_ID,
        "records": records,
        "n": n,
        "window": window,
        "mae": {
            "model": mae_model,
            "carry": mae_carry,
            "three_month": mae_three,
        },
        "bias": {"model": bias_model},
        "halves": halves,
        "gate_passed": gate,
    }


def predict_month(history: dict[str, Any], period: str) -> dict[str, Any]:
    hist = _filter_history_before(history, period)
    panel, _ = _build_panel(hist)
    labeled = _labeled_rows(panel)
    target = next((row for row in panel if row["period"] == period), None)
    if target is None:
        raise ValueError(f"period {period} not in panel")

    if target["labeled"]:
        idx = labeled.index(target)
        if idx < MIN_TRAIN:
            raise ValueError(f"period {period} before minimum training window")
        train = labeled[:idx]
    else:
        train = labeled

    factors = _seasonal_factors(train)
    b0, b1, b2, mode = _fit_constrained(train, factors)
    pred = _predict(target, factors, b0, b1, b2)
    return {
        "period": period,
        "prediction": pred,
        "mode": mode,
        "coefficients": [b0, b1, b2],
        "seasonal_factors": factors,
        "training_end": train[-1]["period"] if train else None,
        "labeled": target["labeled"],
        "actual": target.get("bea_mom"),
    }


def _estimate_json_safe(estimate: dict[str, Any]) -> dict[str, Any]:
    out = dict(estimate)
    out["model_mom"] = format(estimate["model_mom"], "f")
    return out


def september_2026_estimate(history: dict[str, Any] | None = None) -> dict[str, Any]:
    hist = history if history is not None else load_line335_history()
    oos = walk_forward(hist)
    pred = predict_month(hist, TARGET_PERIOD)
    yhat = pred["prediction"]
    return {
        "model_id": MODEL_ID,
        "label": "model_estimated_not_bea_official",
        "training_end": TRAINING_END,
        "period": TARGET_PERIOD,
        "model_mom": Decimal(repr(yhat)),
        "mode": pred["mode"],
        "coefficients": pred["coefficients"],
        "seasonal_factors": pred["seasonal_factors"],
        "gate": oos["gate_passed"],
        "gate_passed": oos["gate_passed"],
        "oos": {
            "n": oos["n"],
            "window": oos["window"],
            "mae": oos["mae"],
            "bias": oos["bias"],
            "halves": oos["halves"],
        },
    }
