#!/usr/bin/env python3
"""ZORI proxy sensitivity vs OER from frozen CSVs. Not Cotality SFRI."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"
MAX_MONTH = "2026-09"
LABEL = "ZORI proxy, not Cotality SFRI"


def load_bls() -> dict[str, dict[str, float | None]]:
    path = DATA_DIR / "bls_cpi_shelter_through_2026-09.csv"
    series = {k: {} for k in ("oer_sa", "oer_nsa", "rent_sa", "rent_nsa")}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            m = row["month"]
            for k in series:
                cell = (row.get(k) or "").strip()
                series[k][m] = float(cell) if cell else None
    return series


def load_zori() -> tuple[dict[str, float], dict[str, float]]:
    path = DATA_DIR / "zori_us_snapshot.csv"
    z_all: dict[str, float] = {}
    z_sfr: dict[str, float] = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            m = row["month"]
            a = (row.get("zori_all") or "").strip()
            s = (row.get("zori_sfr") or "").strip()
            if a:
                z_all[m] = float(a)
            if s:
                z_sfr[m] = float(s)
    return z_all, z_sfr


def prev_month(m: str) -> str | None:
    y, mo = map(int, m.split("-"))
    if mo == 1:
        return f"{y - 1}-12"
    return f"{y}-{mo - 1:02d}"


def add_months(m: str, n: int) -> str:
    y, mo = map(int, m.split("-"))
    mo += n
    while mo > 12:
        mo -= 12
        y += 1
    while mo < 1:
        mo += 12
        y -= 1
    return f"{y}-{mo:02d}"


def mom_series(levels: dict[str, float | None]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    months = sorted(levels.keys())
    for m in months:
        pm = prev_month(m)
        if pm is None:
            out[m] = None
            continue
        lt, ltm = levels.get(m), levels.get(pm)
        if lt is None or ltm is None or lt <= 0 or ltm <= 0:
            out[m] = None
        else:
            out[m] = 100.0 * (lt / ltm - 1.0)
    return out


def yoy_series(levels: dict[str, float | None]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for m in sorted(levels.keys()):
        ym12 = add_months(m, -12)
        lt, l12 = levels.get(m), levels.get(ym12)
        if lt is None or l12 is None or lt <= 0 or l12 <= 0:
            out[m] = None
        else:
            out[m] = 100.0 * (lt / l12 - 1.0)
    return out


def diff_series(yoy: dict[str, float | None]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for m in sorted(yoy.keys()):
        pm = prev_month(m)
        if pm is None:
            out[m] = None
            continue
        a, b = yoy.get(m), yoy.get(pm)
        if a is None or b is None:
            out[m] = None
        else:
            out[m] = a - b
    return out


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2:
        return None
    x = np.array(xs, dtype=float)
    y = np.array(ys, dtype=float)
    if np.std(x) == 0 or np.std(y) == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def lag_correlations(
    proxy_yoy: dict[str, float | None],
    oer_yoy: dict[str, float | None],
    proxy_name: str,
    max_lag: int = 24,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    proxy_dy = diff_series(proxy_yoy)
    oer_dy = diff_series(oer_yoy)
    months = sorted(set(oer_yoy) & set(proxy_yoy))
    months = [m for m in months if m <= MAX_MONTH]
    for transform, p_series, o_series in (
        ("level_yoy", proxy_yoy, oer_yoy),
        ("diff_yoy", proxy_dy, oer_dy),
    ):
        for lag in range(max_lag + 1):
            xs, ys = [], []
            for m in months:
                mt = add_months(m, -lag)
                pv = p_series.get(mt)
                ov = o_series.get(m)
                if pv is not None and ov is not None:
                    xs.append(pv)
                    ys.append(ov)
            c = pearson(xs, ys)
            rows.append(
                {
                    "proxy": proxy_name,
                    "transform": transform,
                    "lag": lag,
                    "n": len(xs),
                    "correlation": c,
                }
            )
    return rows


def best_lag(rows: list[dict], proxy: str, transform: str) -> tuple[int, float | None]:
    sub = [r for r in rows if r["proxy"] == proxy and r["transform"] == transform]
    best = max(
        sub,
        key=lambda r: (r["correlation"] if r["correlation"] is not None else -2.0),
    )
    return int(best["lag"]), best["correlation"]


def ols_predict(X: np.ndarray, y: np.ndarray, x_new: np.ndarray) -> float | None:
    if len(y) < 1:
        return None
    try:
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        return float(x_new @ beta)
    except Exception:
        return None


def mae_rmse(actual: list[float], pred: list[float]) -> tuple[float | None, float | None, int]:
    n = len(actual)
    if n == 0:
        return None, None, 0
    err = [abs(a - p) for a, p in zip(actual, pred)]
    sq = [(a - p) ** 2 for a, p in zip(actual, pred)]
    return sum(err) / n, math.sqrt(sum(sq) / n), n


def forecast_1m(
    mom: dict[str, float | None],
    zori_yoy: dict[str, float | None],
    target_key: str,
) -> tuple[list[dict], dict[str, Any]]:
    months = sorted(m for m in mom if m >= "2019-01" and m <= MAX_MONTH)
    rows: list[dict] = []
    for t in months:
        if mom.get(t) is None:
            continue
        actual = mom[t]
        assert actual is not None

        m1, m2, m3 = prev_month(t), None, None
        if m1:
            m2 = prev_month(m1)
        if m2:
            m3 = prev_month(m2)

        persist = mom.get(m1) if m1 else None

        trail3 = None
        if m1 and m2 and m3:
            v1, v2, v3 = mom.get(m1), mom.get(m2), mom.get(m3)
            if v1 is not None and v2 is not None and v3 is not None:
                trail3 = (v1 + v2 + v3) / 3.0

        # training for AR models: all s < t with mom(s-1..s-3)
        train_moms: list[tuple[str, float]] = []
        for s in sorted(mom.keys()):
            if s >= t:
                break
            if mom.get(s) is None:
                continue
            s1 = prev_month(s)
            s2 = prev_month(s1) if s1 else None
            s3 = prev_month(s2) if s2 else None
            if not s1 or not s2 or not s3:
                continue
            if (
                mom.get(s1) is None
                or mom.get(s2) is None
                or mom.get(s3) is None
            ):
                continue
            train_moms.append((s, mom[s]))  # type: ignore

        def fit_ar3(extra_col_fn=None) -> float | None:
            if len(train_moms) < 36:
                return None
            X_list, y_list = [], []
            for s, yval in train_moms:
                s1 = prev_month(s)
                s2 = prev_month(s1)
                s3 = prev_month(s2)
                row = [1.0, mom[s1], mom[s2], mom[s3]]  # type: ignore
                if extra_col_fn:
                    ex = extra_col_fn(s)
                    if ex is None:
                        continue
                    row.append(ex)
                X_list.append(row)
                y_list.append(yval)
            if len(y_list) < 36:
                return None
            X = np.array(X_list)
            y = np.array(y_list)
            t1, t2, t3 = prev_month(t), prev_month(prev_month(t)), prev_month(prev_month(prev_month(t)))
            x_new = [1.0, mom[t1], mom[t2], mom[t3]]  # type: ignore
            if extra_col_fn:
                ex = extra_col_fn(t)
                if ex is None:
                    return None
                x_new.append(ex)
            return ols_predict(X, y, np.array(x_new, dtype=float))

        ar3 = fit_ar3()
        ar3_z1 = fit_ar3(lambda s: zori_yoy.get(prev_month(s)) if prev_month(s) else None)
        ar3_z12 = fit_ar3(
            lambda s: zori_yoy.get(add_months(s, -12))
        )

        # k-search
        best_k, best_rmse, k_pred = None, float("inf"), None
        for k in range(1, 25):
            preds_train, acts_train = [], []

            def col_k(s: str) -> float | None:
                return zori_yoy.get(add_months(s, -k))

            if len(train_moms) < 36:
                continue
            X_list, y_list = [], []
            for s, yval in train_moms:
                s1, s2, s3 = prev_month(s), prev_month(prev_month(s)), prev_month(
                    prev_month(prev_month(s))
                )
                zk = col_k(s)
                if (
                    mom.get(s1) is None
                    or mom.get(s2) is None
                    or mom.get(s3) is None
                    or zk is None
                ):
                    continue
                X_list.append([1.0, mom[s1], mom[s2], mom[s3], zk])  # type: ignore
                y_list.append(yval)
            if len(y_list) < 36:
                continue
            X = np.array(X_list)
            y = np.array(y_list)
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
            resid = y - X @ beta
            rmse = float(np.sqrt(np.mean(resid**2)))
            if rmse < best_rmse or (rmse == best_rmse and (best_k is None or k < best_k)):
                best_rmse = rmse
                best_k = k
                t1, t2, t3 = (
                    prev_month(t),
                    prev_month(prev_month(t)),
                    prev_month(prev_month(prev_month(t))),
                )
                zk_t = col_k(t)
                if (
                    mom.get(t1) is not None
                    and mom.get(t2) is not None
                    and mom.get(t3) is not None
                    and zk_t is not None
                ):
                    x_new = np.array(
                        [1.0, mom[t1], mom[t2], mom[t3], zk_t], dtype=float  # type: ignore
                    )
                    k_pred = float(x_new @ beta)

        rows.append(
            {
                "target": target_key,
                "month": t,
                "actual": actual,
                "persist": persist,
                "trail3": trail3,
                "ar3": ar3,
                "ar3_zori_m1": ar3_z1,
                "ar3_zori_m12": ar3_z12,
                "ar3_zori_ksearch": k_pred,
                "k_selected": best_k,
            }
        )

    return rows, {}


def common_sample_metrics(rows: list[dict], target: str = "oer_sa_mom") -> dict[str, Any]:
    keys = ["persist", "trail3", "ar3", "ar3_zori_m1", "ar3_zori_m12"]
    common = [
        r
        for r in rows
        if r["target"] == target
        and all(r[k] is not None for k in keys)
    ]
    metrics: dict[str, Any] = {"n_common": len(common), "models": {}}
    for k in keys:
        mae, rmse, n = mae_rmse(
            [r["actual"] for r in common], [r[k] for r in common]  # type: ignore
        )
        metrics["models"][k] = {"mae": mae, "rmse": rmse, "n": n}

    # directional vs trail3
    hits, zeros, considered = 0, 0, 0
    for r in common:
        trail = r["trail3"]
        for model in ("ar3", "ar3_zori_m1", "ar3_zori_m12", "ar3_zori_ksearch"):
            pass
    # only for models in common sample (ksearch may differ)
    dir_models = ["ar3", "ar3_zori_m1", "ar3_zori_m12"]
    dir_acc: dict[str, Any] = {}
    for model in dir_models:
        h, z, c = 0, 0, 0
        for r in common:
            ta, tr = r["actual"] - r["trail3"], r[model] - r["trail3"]  # type: ignore
            if ta == 0 or tr == 0:
                z += 1
                continue
            c += 1
            if (ta > 0) == (tr > 0):
                h += 1
        dir_acc[model] = {
            "directional_accuracy": h / c if c else None,
            "zero_count": z,
            "n_considered": c,
        }
    metrics["directional_vs_trail3"] = dir_acc

    # period splits on MAE for oer_sa
    splits = {
        "through_2019": lambda m: m <= "2019-12",
        "2020_2022": lambda m: "2020-01" <= m <= "2022-12",
        "from_2023": lambda m: m >= "2023-01",
    }
    metrics["mae_splits_oer_sa"] = {}
    for name, pred in splits.items():
        sub = [r for r in common if pred(r["month"])]
        metrics["mae_splits_oer_sa"][name] = {}
        for k in keys:
            mae, _, n = mae_rmse(
                [r["actual"] for r in sub], [r[k] for r in sub]  # type: ignore
            )
            metrics["mae_splits_oer_sa"][name][k] = {"mae": mae, "n": n}

    return metrics


def common_sample_metrics_without_m12(
    rows: list[dict], target: str = "oer_sa_mom"
) -> dict[str, Any]:
    keys = ["persist", "trail3", "ar3", "ar3_zori_m1"]
    common = [
        r
        for r in rows
        if r["target"] == target
        and all(r[k] is not None for k in keys)
    ]
    metrics: dict[str, Any] = {"n_common": len(common), "models": {}}
    for k in keys:
        mae, rmse, n = mae_rmse(
            [r["actual"] for r in common], [r[k] for r in common]  # type: ignore
        )
        metrics["models"][k] = {"mae": mae, "rmse": rmse, "n": n}

    splits = {
        "through_2019": lambda m: m <= "2019-12",
        "2020_2022": lambda m: "2020-01" <= m <= "2022-12",
        "from_2023": lambda m: m >= "2023-01",
    }
    metrics["mae_splits_oer_sa"] = {}
    for name, pred in splits.items():
        sub = [r for r in common if pred(r["month"])]
        metrics["mae_splits_oer_sa"][name] = {}
        for k in keys:
            mae, _, n = mae_rmse(
                [r["actual"] for r in sub], [r[k] for r in sub]  # type: ignore
            )
            metrics["mae_splits_oer_sa"][name][k] = {"mae": mae, "n": n}

    return metrics


def hist_diff_stats(hist: list[float], d24: float | None) -> dict[str, Any]:
    hist_sorted = sorted(hist)
    n = len(hist)
    median: float | None = None
    if n:
        if n % 2 == 1:
            median = hist_sorted[n // 2]
        else:
            median = (hist_sorted[n // 2 - 1] + hist_sorted[n // 2]) / 2.0
    maximum = max(hist) if hist else None
    pct = None
    if d24 is not None and n:
        pct = sum(1 for x in hist if x < d24) / n
    return {
        "n": n,
        "median": median,
        "maximum": maximum,
        "percentile_rank_strictly_less_than_2024_01": pct,
    }


def three_month_exercise(
    oer_sa: dict[str, float | None],
    mom: dict[str, float | None],
    oer_yoy: dict[str, float | None],
    zori_yoy: dict[str, float | None],
) -> dict[str, Any]:
    def actual_3m(t: str) -> float | None:
        tm1 = prev_month(t)
        tp1, tp2, tpp2 = t, add_months(t, 1), add_months(t, 2)
        if tm1 is None:
            return None
        for m in (tm1, tp1, tp2, tpp2):
            if oer_sa.get(m) is None:
                return None
        l0, l3 = oer_sa.get(tm1), oer_sa.get(tpp2)
        if l0 is None or l3 is None or l0 <= 0:
            return None
        return 100.0 * (l3 / l0 - 1.0)

    def trail3_x3(t: str) -> float | None:
        m1 = prev_month(t)
        if not m1:
            return None
        m2, m3 = prev_month(m1), prev_month(prev_month(m1))
        if not m2 or not m3:
            return None
        v = [mom.get(m1), mom.get(m2), mom.get(m3)]
        if any(x is None for x in v):
            return None
        return 3.0 * sum(v) / 3.0  # type: ignore

    def fit_direct(t: str, with_zori: bool) -> float | None:
        t_m1 = prev_month(t)
        if t_m1 is None:
            return None
        train: list[tuple[str, float]] = []
        for s in sorted(oer_sa.keys()):
            if s >= t:
                break
            if add_months(s, 2) > t_m1:
                continue
            y = actual_3m(s)
            if y is None:
                continue
            s1 = prev_month(s)
            if not s1:
                continue
            s2, s3 = prev_month(s1), prev_month(prev_month(s1))
            if not s2 or not s3:
                continue
            row_base = [mom.get(s1), mom.get(s2), mom.get(s3), oer_yoy.get(s1)]
            if any(x is None for x in row_base):
                continue
            if with_zori:
                if zori_yoy.get(s1) is None or zori_yoy.get(add_months(s, -13)) is None:
                    continue
            train.append((s, y))
        if len(train) < 36:
            return None
        X_list, y_list = [], []
        for s, yval in train:
            s1 = prev_month(s)
            s2, s3 = prev_month(s1), prev_month(prev_month(s1))
            row = [1.0, mom[s1], mom[s2], mom[s3], oer_yoy[s1]]  # type: ignore
            if with_zori:
                z1, z13 = zori_yoy.get(s1), zori_yoy.get(add_months(s, -13))
                row.extend([z1, z13])  # type: ignore
            X_list.append(row)
            y_list.append(yval)
        if len(y_list) < 36:
            return None
        X = np.array(X_list)
        y = np.array(y_list)
        s1 = prev_month(t)
        s2, s3 = prev_month(s1), prev_month(prev_month(s1))
        if not s1 or not s2 or not s3:
            return None
        pred_row = [mom.get(s1), mom.get(s2), mom.get(s3), oer_yoy.get(s1)]
        if any(x is None for x in pred_row):
            return None
        x_new = [1.0, pred_row[0], pred_row[1], pred_row[2], pred_row[3]]
        if with_zori:
            z1, z13 = zori_yoy.get(s1), zori_yoy.get(add_months(t, -13))
            if z1 is None or z13 is None:
                return None
            x_new.extend([z1, z13])
        return ols_predict(X, y, np.array(x_new, dtype=float))

    overlapping: list[dict] = []
    for t in sorted(oer_sa.keys()):
        if t < "2019-01" or t > MAX_MONTH:
            continue
        act = actual_3m(t)
        if act is None:
            continue
        overlapping.append(
            {
                "month": t,
                "actual": act,
                "trail3_x3": trail3_x3(t),
                "direct_ar": fit_direct(t, False),
                "direct_ar_zori": fit_direct(t, True),
            }
        )

    def mae_for(key: str, subset: list[dict]) -> dict:
        pairs = [
            (r["actual"], r[key])
            for r in subset
            if r.get(key) is not None
            and math.isfinite(r[key])
            and math.isfinite(r["actual"])
        ]
        if not pairs:
            return {"mae": None, "n": 0}
        mae, _, n = mae_rmse([a for a, _ in pairs], [p for _, p in pairs])
        return {"mae": mae, "n": n}

    overlap_mae = {
        "trail3_x3": mae_for("trail3_x3", overlapping),
        "direct_ar": mae_for("direct_ar", overlapping),
        "direct_ar_zori": mae_for("direct_ar_zori", overlapping),
    }

    non_overlap: list[dict] = []
    t = "2019-01"
    while t <= MAX_MONTH:
        act = actual_3m(t)
        if act is not None:
            non_overlap.append(
                {
                    "month": t,
                    "actual": act,
                    "trail3_x3": trail3_x3(t),
                    "direct_ar": fit_direct(t, False),
                    "direct_ar_zori": fit_direct(t, True),
                }
            )
        y, mo = int(t[:4]), int(t[5:7])
        mo += 3
        while mo > 12:
            mo -= 12
            y += 1
        t = f"{y}-{mo:02d}"

    non_overlap_mae = {
        "trail3_x3": mae_for("trail3_x3", non_overlap),
        "direct_ar": mae_for("direct_ar", non_overlap),
        "direct_ar_zori": mae_for("direct_ar_zori", non_overlap),
    }

    def common_sample_mae(subset: list[dict]) -> dict[str, Any]:
        common = [
            r
            for r in subset
            if math.isfinite(r["actual"])
            and all(
                r.get(k) is not None and math.isfinite(r[k])
                for k in ("trail3_x3", "direct_ar", "direct_ar_zori")
            )
        ]
        models: dict[str, Any] = {}
        for k in ("trail3_x3", "direct_ar", "direct_ar_zori"):
            mae, _, n = mae_rmse(
                [r["actual"] for r in common], [r[k] for r in common]  # type: ignore
            )
            models[k] = {"mae": mae, "n": n}
        return {"n": len(common), "models": models}

    return {
        "common_sample_overlapping": common_sample_mae(overlapping),
        "common_sample_non_overlapping": common_sample_mae(non_overlap),
        "unequal_n_overlapping_descriptive_mae": overlap_mae,
        "unequal_n_non_overlapping_descriptive_mae": non_overlap_mae,
    }


def directional_yoy(
    oer_yoy: dict[str, float | None],
    zori_yoy: dict[str, float | None],
    h: int,
    proxy: str,
    zori_key: dict[str, float | None],
) -> dict[str, Any]:
    def eligible_months() -> list[str]:
        ms = []
        for m in sorted(oer_yoy.keys()):
            if m < "2016-09" or m > MAX_MONTH:
                continue
            th = add_months(m, h)
            if th > MAX_MONTH:
                continue
            if oer_yoy.get(m) is None or oer_yoy.get(th) is None:
                continue
            if oer_yoy.get(add_months(m, -3)) is None:
                continue
            if zori_key.get(m) is None:
                continue
            ms.append(m)
        return ms

    def predict_gap(m: str) -> int:
        gap = zori_key[m] - oer_yoy[m]  # type: ignore
        return -1 if gap < 0 else 1

    def predict_always_decline(_: str) -> int:
        return -1

    def predict_momentum(m: str) -> int:
        d = oer_yoy[m] - oer_yoy[add_months(m, -3)]  # type: ignore
        return -1 if d < 0 else 1

    def actual_sign(m: str) -> int:
        d = oer_yoy[add_months(m, h)] - oer_yoy[m]  # type: ignore
        if d == 0:
            return 0
        return 1 if d > 0 else -1

    def eval_set(months: list[str], pred_fn) -> dict[str, Any]:
        hits, zeros, n = 0, 0, 0
        for m in months:
            a = actual_sign(m)
            if a == 0:
                zeros += 1
                continue
            n += 1
            p = pred_fn(m)
            if p == a:
                hits += 1
        return {
            "hit_rate": hits / n if n else None,
            "zero_count": zeros,
            "n": n,
        }

    all_m = eligible_months()
    overlapping = {
        "gap": eval_set(all_m, predict_gap),
        "always_decline": eval_set(all_m, predict_always_decline),
        "momentum": eval_set(all_m, predict_momentum),
    }

    non_m: list[str] = []
    if all_m:
        t = all_m[0]
        while t <= MAX_MONTH:
            if t in all_m:
                non_m.append(t)
            t = add_months(t, h)
    non_overlapping = {
        "gap": eval_set(non_m, predict_gap),
        "always_decline": eval_set(non_m, predict_always_decline),
        "momentum": eval_set(non_m, predict_momentum),
    }

    return {
        "horizon_months": h,
        "proxy": proxy,
        "descriptive_overlapping": overlapping,
        "non_overlapping": non_overlapping,
    }


def january_2024_note(
    oer_mom: dict[str, float | None],
    rent_mom: dict[str, float | None],
) -> dict[str, Any]:
    d24 = None
    if oer_mom.get("2024-01") is not None and rent_mom.get("2024-01") is not None:
        d24 = oer_mom["2024-01"] - rent_mom["2024-01"]  # type: ignore

    def collect_hist(start: str, end: str) -> list[float]:
        hist: list[float] = []
        t = start
        while t <= end:
            if (
                oer_mom.get(t) is not None
                and rent_mom.get(t) is not None
            ):
                hist.append(oer_mom[t] - rent_mom[t])  # type: ignore
            t = add_months(t, 1)
        return hist

    hist_2015_2019 = collect_hist("2015-01", "2019-12")
    hist_2012_through_2023 = collect_hist("2012-02", "2023-12")

    return {
        "oer_sa_mom_2024_01": oer_mom.get("2024-01"),
        "rent_sa_mom_2024_01": rent_mom.get("2024-01"),
        "difference_2024_01": d24,
        "hist_2015_2019": hist_diff_stats(hist_2015_2019, d24),
        "hist_2012_through_2023": hist_diff_stats(hist_2012_through_2023, d24),
    }


def as_of_snapshot(
    oer_sa: dict[str, float | None],
    oer_nsa: dict[str, float | None],
    rent_sa: dict[str, float | None],
    z_all: dict[str, float],
    z_sfr: dict[str, float],
) -> dict[str, Any]:
    oer_yoy_sa = yoy_series(oer_sa)
    oer_yoy_nsa = yoy_series(oer_nsa)
    rent_yoy = yoy_series(rent_sa)
    z_a_yoy = yoy_series({k: v for k, v in z_all.items()})
    z_s_yoy = yoy_series({k: v for k, v in z_sfr.items()}) if z_sfr else {}

    def last_yoy(ser: dict[str, float | None]) -> tuple[str | None, float | None]:
        for m in reversed(sorted(ser.keys())):
            if m <= MAX_MONTH and ser.get(m) is not None:
                return m, ser[m]
        return None, None

    m_o, v_o = last_yoy(oer_yoy_sa)
    _, v_on = last_yoy(oer_yoy_nsa)
    _, v_r = last_yoy(rent_yoy)
    _, v_za = last_yoy(z_a_yoy)
    _, v_zs = last_yoy(z_s_yoy)
    gap = None
    if v_za is not None and v_o is not None:
        gap = v_za - v_o
    return {
        "as_of_month": m_o,
        "oer_sa_yoy": v_o,
        "oer_nsa_yoy": v_on,
        "rent_sa_yoy": v_r,
        "zori_all_yoy": v_za,
        "zori_sfr_yoy": v_zs,
        "zori_all_yoy_minus_oer_sa_yoy": gap,
    }


def write_svg(
    path: Path,
    oer_yoy: dict[str, float | None],
    zori_yoy: dict[str, float | None],
) -> None:
    months = sorted(
        m for m in set(oer_yoy) & set(zori_yoy) if m <= MAX_MONTH and m >= "2015-01"
    )
    pts_o = [(m, oer_yoy[m]) for m in months if oer_yoy.get(m) is not None]
    pts_z = [(m, zori_yoy[m]) for m in months if zori_yoy.get(m) is not None]
    if not pts_o or not pts_z:
        path.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
        return

    def xpos(i: int, n: int) -> float:
        return 60 + (520 * i / max(n - 1, 1))

    all_vals = [v for _, v in pts_o] + [v for _, v in pts_z]
    ymin, ymax = min(all_vals), max(all_vals)
    pad = (ymax - ymin) * 0.05 or 1.0
    ymin -= pad
    ymax += pad

    def ypos(v: float) -> float:
        return 320 - 260 * (v - ymin) / (ymax - ymin)

    n = len(pts_o)
    lines_o = " ".join(
        f"{xpos(i,n):.1f},{ypos(v):.1f}" for i, (_, v) in enumerate(pts_o)
    )
    # align zori to same month index by month string
    month_to_i = {m: i for i, m in enumerate([m for m, _ in pts_o])}
    pts_z_aligned = [
        (month_to_i[m], v) for m, v in pts_z if m in month_to_i
    ]
    lines_z = " ".join(
        f"{xpos(i,n):.1f},{ypos(v):.1f}" for i, v in pts_z_aligned
    )

    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="640" height="400" viewBox="0 0 640 400">
  <rect width="100%" height="100%" fill="#fafafa"/>
  <text x="320" y="28" text-anchor="middle" font-family="sans-serif" font-size="14" font-weight="bold">Proxy only: Zillow ZORI is not Cotality SFRI</text>
  <text x="320" y="48" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#444">Revised Zillow snapshot through 2026-09; OER from BLS SA shelter CPI</text>
  <polyline fill="none" stroke="#1f77b4" stroke-width="2" points="{lines_o}"/>
  <polyline fill="none" stroke="#ff7f0e" stroke-width="2" points="{lines_z}"/>
  <text x="80" y="360" font-family="sans-serif" font-size="11" fill="#1f77b4">oer_sa yoy</text>
  <text x="200" y="360" font-family="sans-serif" font-size="11" fill="#ff7f0e">zori_all yoy</text>
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def rnd3(x: float | None) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    return f"{x:.3f}"


def rnd1pct(x: float | None) -> str:
    if x is None:
        return "n/a"
    return f"{100.0 * x:.1f}"


def _split_mae_table(
    splits: dict[str, Any], model_keys: list[str], split_names: list[str]
) -> str:
    header = "| Window | n | " + " | ".join(model_keys) + " |"
    sep = "| --- | ---: | " + " | ".join(["---:"] * len(model_keys)) + " |"
    lines = [header, sep]
    for sname in split_names:
        block = splits[sname]
        n_ref = block[model_keys[0]]["n"]
        if n_ref == 0 and "ar3_zori_m12" in model_keys:
            lines.append(
                f"| {sname} | 0 | "
                + " | ".join(["—"] * len(model_keys))
                + " |"
            )
            continue
        cells = [rnd3(block[k]["mae"]) for k in model_keys]
        lines.append(f"| {sname} | {n_ref} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _nsa_beat_statement(cm_nsa: dict[str, Any]) -> str:
    m1 = cm_nsa["models"]["ar3_zori_m1"]["mae"]
    t3 = cm_nsa["models"]["trail3"]["mae"]
    a3 = cm_nsa["models"]["ar3"]["mae"]
    if m1 is None or t3 is None or a3 is None:
        return "NSA common-sample MAEs are incomplete; no beat statement."
    beats_trail3 = m1 < t3
    beats_ar3 = m1 < a3
    if beats_trail3 and beats_ar3:
        return (
            f"On NSA (`oer_nsa_mom`), `ar3_zori_m1` MAE ({rnd3(m1)} pp) is lower than "
            f"both `trail3` ({rnd3(t3)} pp) and `ar3` ({rnd3(a3)} pp)."
        )
    if beats_trail3 and not beats_ar3:
        return (
            f"On NSA, `ar3_zori_m1` ({rnd3(m1)} pp) beats `trail3` ({rnd3(t3)} pp) but not "
            f"`ar3` ({rnd3(a3)} pp)."
        )
    if not beats_trail3 and beats_ar3:
        return (
            f"On NSA, `ar3_zori_m1` ({rnd3(m1)} pp) beats `ar3` ({rnd3(a3)} pp) but not "
            f"`trail3` ({rnd3(t3)} pp)."
        )
    return (
        f"On NSA, `ar3_zori_m1` ({rnd3(m1)} pp) does **not** beat `trail3` ({rnd3(t3)} pp) "
        f"or `ar3` ({rnd3(a3)} pp) on common-sample MAE."
    )


def write_proxy_analysis(metrics: dict[str, Any], lag_rows: list[dict]) -> None:
    m = metrics
    bl = m["best_lags"]
    cm = m["forecast_1m_oer_sa_common"]
    cm_no_m12 = m["forecast_1m_oer_sa_common_without_m12"]
    cm_nsa = m["forecast_1m_oer_nsa_common"]
    tm = m["three_month"]
    ks = m["forecast_1m_ar3_zori_ksearch_oer_sa"]
    j24 = m["january_2024"]

    sa_models_full = [
        "persist",
        "trail3",
        "ar3",
        "ar3_zori_m1",
        "ar3_zori_m12",
    ]
    sa_models_no_m12 = ["persist", "trail3", "ar3", "ar3_zori_m1"]
    split_names = ["through_2019", "2020_2022", "from_2023"]

    split_full = _split_mae_table(
        cm["mae_splits_oer_sa"], sa_models_full, split_names
    )
    split_no_m12 = _split_mae_table(
        cm_no_m12["mae_splits_oer_sa"], sa_models_no_m12, split_names
    )

    through19_n = cm["mae_splits_oer_sa"]["through_2019"]["persist"]["n"]
    split_full_note = ""
    if through19_n == 0:
        split_full_note = (
            "\n\nFor the **full** five-model common sample, the through_2019 window has "
            "**n = 0**: `ar3_zori_m12` needs 36 training rows with ZORI lag-12, so no month "
            "through 2019 qualifies in the intersected sample. That emptiness is a sample "
            "definition, not evidence that models tied.\n"
        )

    nsa_models = sa_models_full
    nsa_table_rows = "\n".join(
        f"| {k} | {rnd3(cm_nsa['models'][k]['mae'])} | {rnd3(cm_nsa['models'][k]['rmse'])} |"
        for k in nsa_models
    )

    cs_non = tm["common_sample_non_overlapping"]
    t3m = cs_non["models"]

    text = f"""# Proxy sensitivity ({LABEL})

All tables and figures use frozen CSVs from `build_inputs.py`. This is **not** a Cotality SFRI validation.

## Lag correlations (descriptive)

Highest **level** year-on-year correlation for `zori_all` vs `oer_sa`: lag **{bl['zori_all_level_lag']}**, r = {rnd3(bl['zori_all_level_corr'])} (n = {bl['zori_all_level_n']}).

Highest **first-difference of yoy** correlation: lag **{bl['zori_all_diff_lag']}**, r = {rnd3(bl['zori_all_diff_corr'])}.

For `zori_sfr` level yoy: best lag **{bl['zori_sfr_level_lag']}**, r = {rnd3(bl['zori_sfr_level_corr'])}.

Overlapping year-on-year correlations are **not** evidence of a one-month CPI print edge.

## One-month OER SA month-on-month (rolling origin)

Information set: OER and ZORI through **t−1** only (latest revised vintages — **not** a real-time publication test).

### Common sample (all five models finite)

n = {cm['n_common']}:

| Model | MAE (pp) | RMSE (pp) |
| --- | --- | --- |
| persist | {rnd3(cm['models']['persist']['mae'])} | {rnd3(cm['models']['persist']['rmse'])} |
| trail3 | {rnd3(cm['models']['trail3']['mae'])} | {rnd3(cm['models']['trail3']['rmse'])} |
| ar3 | {rnd3(cm['models']['ar3']['mae'])} | {rnd3(cm['models']['ar3']['rmse'])} |
| ar3_zori_m1 | {rnd3(cm['models']['ar3_zori_m1']['mae'])} | {rnd3(cm['models']['ar3_zori_m1']['rmse'])} |
| ar3_zori_m12 | {rnd3(cm['models']['ar3_zori_m12']['mae'])} | {rnd3(cm['models']['ar3_zori_m12']['rmse'])} |

### MAE by window (same five-model common sample)

MAE (pp) by model; n is the count of months in that window where all five models are finite.

{split_full}
{split_full_note}
### Secondary common sample (drops `ar3_zori_m12`)

`forecast_1m_oer_sa_common_without_m12` — persist, trail3, ar3, and ar3_zori_m1 only (n = {cm_no_m12['n_common']}). This intersection allows a pre-2020 comparison.

{split_no_m12}

### `ar3_zori_ksearch` (separate sample)

Lag k is chosen by in-sample training RMSE each origin; this is **not** the five-model common sample. Separate sample n = {ks['n']}, MAE = {rnd3(ks['mae'])} pp, RMSE = {rnd3(ks['rmse'])} pp.

### Robustness: OER NSA month-on-month

Common sample n = {cm_nsa['n_common']} (all five models finite on `oer_nsa_mom`):

| Model | MAE (pp) | RMSE (pp) |
| --- | --- | --- |
{nsa_table_rows}

{_nsa_beat_statement(cm_nsa)}

## Three-month cumulative OER SA change

**Common-sample horse race (non-overlapping origins, step 3 months):** months where `trail3_x3`, `direct_ar`, and `direct_ar_zori` are all finite. n = {cs_non['n']}; MAE (pp): trail3×3 {rnd3(t3m['trail3_x3']['mae'])}, direct_ar {rnd3(t3m['direct_ar']['mae'])}, direct_ar_zori {rnd3(t3m['direct_ar_zori']['mae'])}.

Common-sample overlapping (every qualifying month): n = {tm['common_sample_overlapping']['n']}; MAEs trail3×3 {rnd3(tm['common_sample_overlapping']['models']['trail3_x3']['mae'])}, direct_ar {rnd3(tm['common_sample_overlapping']['models']['direct_ar']['mae'])}, direct_ar_zori {rnd3(tm['common_sample_overlapping']['models']['direct_ar_zori']['mae'])}.

**Unequal_n_descriptive** (each model scored on its own finite months — not a horse race): non-overlapping trail3×3 MAE {rnd3(tm['unequal_n_non_overlapping_descriptive_mae']['trail3_x3']['mae'])} (n={tm['unequal_n_non_overlapping_descriptive_mae']['trail3_x3']['n']}); direct_ar {rnd3(tm['unequal_n_non_overlapping_descriptive_mae']['direct_ar']['mae'])} (n={tm['unequal_n_non_overlapping_descriptive_mae']['direct_ar']['n']}); direct_ar_zori {rnd3(tm['unequal_n_non_overlapping_descriptive_mae']['direct_ar_zori']['mae'])} (n={tm['unequal_n_non_overlapping_descriptive_mae']['direct_ar_zori']['n']}).

## Directional OER SA yoy (6- and 12-month)

Non-overlapping 12-month (`zori_all` gap rule): hit rate {rnd1pct(m['directional_12_zori_all']['non_overlapping']['gap']['hit_rate'])}% (n={m['directional_12_zori_all']['non_overlapping']['gap']['n']}, zero_count={m['directional_12_zori_all']['non_overlapping']['gap']['zero_count']}).

Non-overlapping 12-month with `zori_sfr` (if present): hit rate {rnd1pct(m['directional_12_zori_sfr']['non_overlapping']['gap']['hit_rate'])}% (n={m['directional_12_zori_sfr']['non_overlapping']['gap']['n']}).

Non-overlapping 6-month gap hit rate: {rnd1pct(m['directional_6']['non_overlapping']['gap']['hit_rate'])}% (n={m['directional_6']['non_overlapping']['gap']['n']}).

## January 2024 methodology note (BLS SA)

2024-01 `oer_sa` mom = {rnd3(j24['oer_sa_mom_2024_01'])}; `rent_sa` mom = {rnd3(j24['rent_sa_mom_2024_01'])}; difference (OER − rent) = {rnd3(j24['difference_2024_01'])}.

The BLS rent/OER notice described the originally published January 2024 seasonally adjusted changes as about **0.6 percent** for OER and **0.4 percent** for rent ([BLS notice](https://www.bls.gov/cpi/notices/2024/rent-oer-information.htm)). The frozen current vintage here is the recomputed **0.511** and **0.352**. The gap is **seasonal-factor revision**, so a latest-vintage SA backtest is not the real-time print.

**Hist sample A — every month 2015-01 through 2019-12** with both OER SA mom and rent SA mom (n = {j24['hist_2015_2019']['n']}): median gap = {rnd3(j24['hist_2015_2019']['median'])}, max = {rnd3(j24['hist_2015_2019']['maximum'])}, share of gaps strictly below 2024-01 = {rnd3(j24['hist_2015_2019']['percentile_rank_strictly_less_than_2024_01'])}.

**Hist sample B — pre-break comparison, 2012-02 through 2023-12** (2024-01 excluded; n = {j24['hist_2012_through_2023']['n']}): median = {rnd3(j24['hist_2012_through_2023']['median'])}, max = {rnd3(j24['hist_2012_through_2023']['maximum'])}, share strictly below 2024-01 = {rnd3(j24['hist_2012_through_2023']['percentile_rank_strictly_less_than_2024_01'])}.

## As-of snapshot (through {m['as_of']['as_of_month']})

Not a forecast of October 2026 CPI and not an SFRI reading.

| Series | YoY % |
| --- | --- |
| oer_sa | {rnd3(m['as_of']['oer_sa_yoy'])} |
| oer_nsa | {rnd3(m['as_of']['oer_nsa_yoy'])} |
| rent_sa | {rnd3(m['as_of']['rent_sa_yoy'])} |
| zori_all | {rnd3(m['as_of']['zori_all_yoy'])} |
| zori_sfr | {rnd3(m['as_of']['zori_sfr_yoy'])} |
| zori_all − oer_sa | {rnd3(m['as_of']['zori_all_yoy_minus_oer_sa_yoy'])} |

See `results/yoy_comparison.svg` for level yoy paths.
"""
    (ROOT / "PROXY_ANALYSIS.md").write_text(text, encoding="utf-8")


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    bls = load_bls()
    z_all, z_sfr = load_zori()

    oer_mom_sa = mom_series(bls["oer_sa"])
    oer_mom_nsa = mom_series(bls["oer_nsa"])
    rent_mom_sa = mom_series(bls["rent_sa"])
    oer_yoy_sa = yoy_series(bls["oer_sa"])
    z_all_yoy = yoy_series({k: v for k, v in z_all.items()})
    z_sfr_yoy = yoy_series({k: v for k, v in z_sfr.items()}) if z_sfr else {}

    lag_rows = lag_correlations(z_all_yoy, oer_yoy_sa, "zori_all")
    if z_sfr:
        lag_rows.extend(lag_correlations(z_sfr_yoy, oer_yoy_sa, "zori_sfr"))

    with (RESULTS_DIR / "lag_correlations.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=["proxy", "transform", "lag", "n", "correlation"]
        )
        w.writeheader()
        for r in lag_rows:
            w.writerow(r)

    rows_sa, _ = forecast_1m(oer_mom_sa, z_all_yoy, "oer_sa_mom")
    rows_nsa, _ = forecast_1m(oer_mom_nsa, z_all_yoy, "oer_nsa_mom")
    all_rows = rows_sa + rows_nsa

    with (RESULTS_DIR / "forecast_errors_1m.csv").open("w", newline="", encoding="utf-8") as f:
        fields = [
            "target",
            "month",
            "actual",
            "persist",
            "trail3",
            "ar3",
            "ar3_zori_m1",
            "ar3_zori_m12",
            "ar3_zori_ksearch",
            "k_selected",
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in all_rows:
            w.writerow(r)

    cm_sa = common_sample_metrics(rows_sa, "oer_sa_mom")
    cm_sa_no_m12 = common_sample_metrics_without_m12(rows_sa, "oer_sa_mom")
    cm_nsa = common_sample_metrics(rows_nsa, "oer_nsa_mom")

    ksearch_rows = [
        r
        for r in rows_sa
        if r.get("ar3_zori_ksearch") is not None
        and math.isfinite(r["ar3_zori_ksearch"])
    ]
    ksearch_mae, ksearch_rmse, ksearch_n = mae_rmse(
        [r["actual"] for r in ksearch_rows],
        [r["ar3_zori_ksearch"] for r in ksearch_rows],  # type: ignore
    )
    metrics_ksearch = {
        "n": ksearch_n,
        "mae": ksearch_mae,
        "rmse": ksearch_rmse,
    }

    three_m = three_month_exercise(bls["oer_sa"], oer_mom_sa, oer_yoy_sa, z_all_yoy)
    d6 = directional_yoy(oer_yoy_sa, z_all_yoy, 6, "zori_all", z_all_yoy)
    d12_all = directional_yoy(oer_yoy_sa, z_all_yoy, 12, "zori_all", z_all_yoy)
    d12_sfr = (
        directional_yoy(oer_yoy_sa, z_sfr_yoy, 12, "zori_sfr", z_sfr_yoy)
        if z_sfr
        else {
            "non_overlapping": {"gap": {"hit_rate": None, "n": 0, "zero_count": 0}},
            "descriptive_overlapping": {},
        }
    )

    j24 = january_2024_note(oer_mom_sa, rent_mom_sa)
    as_of = as_of_snapshot(
        bls["oer_sa"], bls["oer_nsa"], bls["rent_sa"], z_all, z_sfr
    )

    zl, zlc = best_lag(lag_rows, "zori_all", "level_yoy")
    zd, zdc = best_lag(lag_rows, "zori_all", "diff_yoy")
    zsl, zslc = best_lag(lag_rows, "zori_sfr", "level_yoy") if z_sfr else (None, None)
    znl = [r for r in lag_rows if r["proxy"] == "zori_all" and r["transform"] == "level_yoy" and r["lag"] == zl]
    znd = [r for r in lag_rows if r["proxy"] == "zori_all" and r["transform"] == "diff_yoy" and r["lag"] == zd]

    metrics: dict[str, Any] = {
        "label": LABEL,
        "direct_sfri_test": "blocked",
        "best_lags": {
            "zori_all_level_lag": zl,
            "zori_all_level_corr": zlc,
            "zori_all_level_n": znl[0]["n"] if znl else 0,
            "zori_all_diff_lag": zd,
            "zori_all_diff_corr": zdc,
            "zori_sfr_level_lag": zsl,
            "zori_sfr_level_corr": zslc,
        },
        "forecast_1m_oer_sa_common": cm_sa,
        "forecast_1m_oer_sa_common_without_m12": cm_sa_no_m12,
        "forecast_1m_oer_nsa_common": cm_nsa,
        "forecast_1m_ar3_zori_ksearch_oer_sa": metrics_ksearch,
        "three_month": three_m,
        "directional_6": d6,
        "directional_12_zori_all": d12_all,
        "directional_12_zori_sfr": d12_sfr,
        "january_2024": j24,
        "as_of": as_of,
    }

    def _sanitize(obj: object) -> object:
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
        if isinstance(obj, dict):
            return {k: _sanitize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_sanitize(v) for v in obj]
        return obj

    metrics = _sanitize(metrics)
    with (RESULTS_DIR / "metrics.json").open("w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
        f.write("\n")

    write_svg(RESULTS_DIR / "yoy_comparison.svg", oer_yoy_sa, z_all_yoy)
    write_proxy_analysis(metrics, lag_rows)

    print(f"Wrote results under {RESULTS_DIR}")


if __name__ == "__main__":
    main()
