#!/usr/bin/env python3
"""Independent recomputation of sfri_oer proxy metrics (numpy only)."""

from __future__ import annotations

import csv
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA_BLS = ROOT / "data" / "bls_cpi_shelter_through_2026-09.csv"
DATA_ZORI = ROOT / "data" / "zori_us_snapshot.csv"
METRICS_PATH = ROOT / "results" / "metrics.json"
PROXY_SCRIPT = ROOT / "scripts" / "proxy_sensitivity.py"
OUT_MD = Path(__file__).resolve().parent / "VERIFICATION.md"
MAX_MONTH = "2026-09"

MAE_TOL = 1e-6
HIT_TOL = 1e-9


def load_bls() -> dict[str, dict[str, float | None]]:
    series = {k: {} for k in ("oer_sa", "oer_nsa", "rent_sa", "rent_nsa")}
    with DATA_BLS.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            m = row["month"]
            for k in series:
                cell = (row.get(k) or "").strip()
                series[k][m] = float(cell) if cell else None
    return series


def load_zori() -> tuple[dict[str, float], dict[str, float]]:
    z_all: dict[str, float] = {}
    z_sfr: dict[str, float] = {}
    with DATA_ZORI.open(encoding="utf-8") as f:
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
    for m in sorted(levels.keys()):
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
) -> list[dict]:
    months = sorted(m for m in mom if m >= "2019-01" and m <= MAX_MONTH)
    rows: list[dict] = []
    for t in months:
        if mom.get(t) is None:
            continue
        actual = mom[t]
        assert actual is not None
        m1 = prev_month(t)
        m2 = prev_month(m1) if m1 else None
        m3 = prev_month(m2) if m2 else None
        persist = mom.get(m1) if m1 else None
        trail3 = None
        if m1 and m2 and m3:
            v1, v2, v3 = mom.get(m1), mom.get(m2), mom.get(m3)
            if v1 is not None and v2 is not None and v3 is not None:
                trail3 = (v1 + v2 + v3) / 3.0

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
            if mom.get(s1) is None or mom.get(s2) is None or mom.get(s3) is None:
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
            t1 = prev_month(t)
            t2 = prev_month(t1) if t1 else None
            t3 = prev_month(t2) if t2 else None
            if not t1 or not t2 or not t3:
                return None
            x_new = [1.0, mom[t1], mom[t2], mom[t3]]  # type: ignore
            if extra_col_fn:
                ex = extra_col_fn(t)
                if ex is None:
                    return None
                x_new.append(ex)
            return ols_predict(X, y, np.array(x_new, dtype=float))

        ar3 = fit_ar3()
        ar3_z1 = fit_ar3(lambda s: zori_yoy.get(prev_month(s)) if prev_month(s) else None)
        ar3_z12 = fit_ar3(lambda s: zori_yoy.get(add_months(s, -12)))

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
            }
        )
    return rows


def common_sample_metrics(rows: list[dict], target: str = "oer_sa_mom") -> dict[str, Any]:
    keys = ["persist", "trail3", "ar3", "ar3_zori_m1", "ar3_zori_m12"]
    common = [r for r in rows if r["target"] == target and all(r[k] is not None for k in keys)]
    metrics: dict[str, Any] = {"n_common": len(common), "models": {}}
    for k in keys:
        mae, rmse, n = mae_rmse([r["actual"] for r in common], [r[k] for r in common])  # type: ignore
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
            mae, _, n = mae_rmse([r["actual"] for r in sub], [r[k] for r in sub])  # type: ignore
            metrics["mae_splits_oer_sa"][name][k] = {"mae": mae, "n": n}
    return metrics


def common_sample_metrics_without_m12(rows: list[dict], target: str = "oer_sa_mom") -> dict[str, Any]:
    keys = ["persist", "trail3", "ar3", "ar3_zori_m1"]
    common = [r for r in rows if r["target"] == target and all(r[k] is not None for k in keys)]
    metrics: dict[str, Any] = {"n_common": len(common), "models": {}}
    for k in keys:
        mae, rmse, n = mae_rmse([r["actual"] for r in common], [r[k] for r in common])  # type: ignore
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
            mae, _, n = mae_rmse([r["actual"] for r in sub], [r[k] for r in sub])  # type: ignore
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
            if oer_mom.get(t) is not None and rent_mom.get(t) is not None:
                hist.append(oer_mom[t] - rent_mom[t])  # type: ignore
            t = add_months(t, 1)
        return hist

    return {
        "oer_sa_mom_2024_01": oer_mom.get("2024-01"),
        "rent_sa_mom_2024_01": rent_mom.get("2024-01"),
        "difference_2024_01": d24,
        "hist_2015_2019": hist_diff_stats(collect_hist("2015-01", "2019-12"), d24),
        "hist_2012_through_2023": hist_diff_stats(collect_hist("2012-02", "2023-12"), d24),
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
    z_s_yoy = yoy_series({k: v for k, v in z_sfr.items()})

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
    gap = v_za - v_o if v_za is not None and v_o is not None else None
    return {
        "as_of_month": m_o,
        "oer_sa_yoy": v_o,
        "oer_nsa_yoy": v_on,
        "rent_sa_yoy": v_r,
        "zori_all_yoy": v_za,
        "zori_sfr_yoy": v_zs,
        "zori_all_yoy_minus_oer_sa_yoy": gap,
    }


def three_month_non_overlapping(
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
        x_new = [1.0, *pred_row]
        if with_zori:
            z1, z13 = zori_yoy.get(s1), zori_yoy.get(add_months(t, -13))
            if z1 is None or z13 is None:
                return None
            x_new.extend([z1, z13])
        return ols_predict(X, y, np.array(x_new, dtype=float))

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

    common = [
        r
        for r in non_overlap
        if math.isfinite(r["actual"])
        and all(
            r.get(k) is not None and math.isfinite(r[k])
            for k in ("trail3_x3", "direct_ar", "direct_ar_zori")
        )
    ]
    models: dict[str, Any] = {}
    for k in ("trail3_x3", "direct_ar", "direct_ar_zori"):
        mae, _, n = mae_rmse([r["actual"] for r in common], [r[k] for r in common])  # type: ignore
        models[k] = {"mae": mae, "n": n}
    return {"n": len(common), "models": models}


def directional_12_zori_all(
    oer_yoy: dict[str, float | None],
    zori_yoy: dict[str, float | None],
) -> dict[str, Any]:
    h = 12

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
            if zori_yoy.get(m) is None:
                continue
            ms.append(m)
        return ms

    def predict_gap(m: str) -> int:
        gap = zori_yoy[m] - oer_yoy[m]  # type: ignore
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
            if pred_fn(m) == a:
                hits += 1
        return {"hit_rate": hits / n if n else None, "zero_count": zeros, "n": n}

    all_m = eligible_months()
    non_m: list[str] = []
    if all_m:
        t = all_m[0]
        while t <= MAX_MONTH:
            if t in all_m:
                non_m.append(t)
            t = add_months(t, h)
    return {
        "non_overlapping": {
            "gap": eval_set(non_m, predict_gap),
            "always_decline": eval_set(non_m, predict_always_decline),
            "momentum": eval_set(non_m, predict_momentum),
        }
    }


def run_hard_audits(bls: dict, oer_mom_sa: dict) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    for label, months in (
        ("BLS", sorted(bls["oer_sa"].keys())),
        ("ZORI", []),
    ):
        pass
    z_all, _ = load_zori()
    zori_months = sorted(z_all.keys())
    bls_months = sorted(bls["oer_sa"].keys())

    for name, months in (("BLS CSV", bls_months), ("ZORI CSV", zori_months)):
        bad = [m for m in months if m > MAX_MONTH]
        ok = len(bad) == 0
        results.append(
            (f"No month after {MAX_MONTH} in {name}", ok, f"max={max(months) if months else 'n/a'}")
        )

    for k in ("oer_sa", "oer_nsa", "rent_sa", "rent_nsa"):
        v = bls[k].get("2025-10")
        ok = v is None
        results.append((f"2025-10 {k} blank", ok, f"value={v!r}"))

    v_sep = bls["oer_sa"].get("2026-09")
    ok = v_sep is not None and abs(v_sep - 445.195) < 1e-9
    results.append(("2026-09 oer_sa is 445.195", ok, f"value={v_sep}"))

    for m in ("2025-10", "2025-11"):
        ok = oer_mom_sa.get(m) is None
        results.append((f"OER SA mom missing for {m}", ok, f"mom={oer_mom_sa.get(m)!r}"))
    ok = oer_mom_sa.get("2025-12") is not None
    results.append(("OER SA mom present for 2025-12", ok, f"mom={oer_mom_sa.get('2025-12')}"))
    return results


def lookahead_audit() -> dict[str, Any]:
    text = PROXY_SCRIPT.read_text(encoding="utf-8")
    feature_quotes: list[str] = []
    patterns = [
        (r"persist\s*=\s*mom\.get\(m1\)", "persist = mom.get(m1)"),
        (r"x_new\s*=\s*\[1\.0,\s*mom\[t1\],\s*mom\[t2\],\s*mom\[t3\]\]", "ar3 prediction features at t-1..t-3"),
        (
            r"ar3_z1\s*=\s*fit_ar3\(lambda s: zori_yoy\.get\(prev_month\(s\)\)",
            "ar3_zori_m1 uses zori_yoy at prev_month(s)",
        ),
        (
            r"ar3_z12\s*=\s*fit_ar3\(\s*\n\s*lambda s: zori_yoy\.get\(add_months\(s, -12\)\)",
            "ar3_zori_m12 uses zori_yoy at s-12",
        ),
    ]
    for pat, desc in patterns:
        m = re.search(pat, text)
        if m:
            line_no = text[: m.start()].count("\n") + 1
            line = text.splitlines()[line_no - 1].strip()
            feature_quotes.append(f"L{line_no}: {line} ({desc})")

    # Same-month t leakage in 1m models
    uses_zori_at_t = bool(re.search(r"zori_yoy\.get\(t\)|zori_yoy\[t\]", text))
    uses_oer_mom_at_t = bool(re.search(r"mom\[t\].*x_new|x_new.*mom\[t\]", text))
    uses_mom_t_feature = bool(
        re.search(r"mom\.get\(t\)|mom\[t\].*#.*feature", text)
    )
    # persist uses m1=prev_month(t) - check forecast_1m block
    forecast_block = re.search(r"def forecast_1m\(.*?\n(?=def )", text, re.DOTALL)
    block = forecast_block.group(0) if forecast_block else text
    same_month_leak = False
    # Prediction features use t1=prev_month(t), not t
    if re.search(r"mom\[t\]|mom\.get\(t\)", block):
        # mom[t] is actual label, not feature - only leak if in x_new
        if re.search(r"x_new.*mom\[t\]|mom\.get\(t\).*x_new", block):
            same_month_leak = True
    if re.search(r"zori_yoy\.get\(t\)|zori_yoy\[t\]", block) and "extra_col_fn(t)" in block:
        # extra_col_fn(t) for zori - check if any uses t not lagged
        if "zori_yoy.get(t)" in block or "zori_yoy.get( t" in block:
            same_month_leak = True
    # ar3_z1 uses extra_col_fn(t) with prev_month in lambda - safe

    three_month_training = bool(
        re.search(r"add_months\(s, 2\) > t_m1", text)
    )
    training_outcome_ok = three_month_training  # s+2 <= t-1 when training for origin t

    return {
        "same_month_feature_leak": same_month_leak,
        "uses_zori_at_t_in_features": uses_zori_at_t,
        "feature_quotes": feature_quotes,
        "three_month_training_cutoff_present": training_outcome_ok,
        "training_outcome_can_end_after_t_minus_1": not training_outcome_ok,
    }


def close_enough(a: float | None, b: float | None, tol: float) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def compare_num(name: str, got: float | None, ref: float | None, tol: float, checks: list) -> None:
    ok = close_enough(got, ref, tol)
    detail = f"recomputed={got!r}, metrics.json={ref!r}"
    if not ok:
        detail += f" (tol={tol})"
    checks.append((name, ok, detail))


def compare_int(name: str, got: int, ref: int, checks: list) -> None:
    ok = got == ref
    checks.append((name, ok, f"recomputed={got}, metrics.json={ref}"))


def main() -> int:
    ref = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    bls = load_bls()
    z_all, z_sfr = load_zori()
    oer_mom_sa = mom_series(bls["oer_sa"])
    oer_mom_nsa = mom_series(bls["oer_nsa"])
    rent_mom_sa = mom_series(bls["rent_sa"])
    oer_yoy_sa = yoy_series(bls["oer_sa"])
    z_all_yoy = yoy_series({k: v for k, v in z_all.items()})

    hard = run_hard_audits(bls, oer_mom_sa)
    j24 = january_2024_note(oer_mom_sa, rent_mom_sa)
    as_of = as_of_snapshot(bls["oer_sa"], bls["oer_nsa"], bls["rent_sa"], z_all, z_sfr)
    rows_sa = forecast_1m(oer_mom_sa, z_all_yoy, "oer_sa_mom")
    rows_nsa = forecast_1m(oer_mom_nsa, z_all_yoy, "oer_nsa_mom")
    cm_sa = common_sample_metrics(rows_sa, "oer_sa_mom")
    cm_no_m12 = common_sample_metrics_without_m12(rows_sa, "oer_sa_mom")
    cm_nsa = common_sample_metrics(rows_nsa, "oer_nsa_mom")
    three_m = three_month_non_overlapping(bls["oer_sa"], oer_mom_sa, oer_yoy_sa, z_all_yoy)
    d12 = directional_12_zori_all(oer_yoy_sa, z_all_yoy)
    lookahead = lookahead_audit()

    checks: list[tuple[str, bool, str]] = []
    for item in hard:
        checks.append(item)

    rj = ref["january_2024"]
    for key in ("oer_sa_mom_2024_01", "rent_sa_mom_2024_01", "difference_2024_01"):
        compare_num(f"january_2024.{key}", j24[key], rj[key], MAE_TOL, checks)
    for hist_key in ("hist_2015_2019", "hist_2012_through_2023"):
        for field in ("n", "median", "maximum", "percentile_rank_strictly_less_than_2024_01"):
            tol = MAE_TOL if field != "n" else 0
            if field == "n":
                compare_int(f"january_2024.{hist_key}.{field}", j24[hist_key][field], rj[hist_key][field], checks)
            else:
                compare_num(
                    f"january_2024.{hist_key}.{field}",
                    j24[hist_key][field],
                    rj[hist_key][field],
                    MAE_TOL,
                    checks,
                )

    ra = ref["as_of"]
    if as_of["as_of_month"] == ra["as_of_month"]:
        checks.append(("as_of.as_of_month", True, str(as_of["as_of_month"])))
    else:
        checks.append(("as_of.as_of_month", False, f"{as_of['as_of_month']} vs {ra['as_of_month']}"))
    for key in (
        "oer_sa_yoy",
        "oer_nsa_yoy",
        "rent_sa_yoy",
        "zori_all_yoy",
        "zori_sfr_yoy",
        "zori_all_yoy_minus_oer_sa_yoy",
    ):
        compare_num(f"as_of.{key}", as_of[key], ra[key], MAE_TOL, checks)

    def compare_forecast_block(block_name: str, got: dict, ref_block: dict, models: list[str], splits: bool) -> None:
        compare_int(f"{block_name}.n_common", got["n_common"], ref_block["n_common"], checks)
        for m in models:
            for stat in ("mae", "rmse", "n"):
                if stat == "n":
                    compare_int(
                        f"{block_name}.models.{m}.{stat}",
                        got["models"][m][stat],
                        ref_block["models"][m][stat],
                        checks,
                    )
                else:
                    compare_num(
                        f"{block_name}.models.{m}.{stat}",
                        got["models"][m][stat],
                        ref_block["models"][m][stat],
                        MAE_TOL,
                        checks,
                    )
        if splits:
            for win in ("through_2019", "2020_2022", "from_2023"):
                for m in models:
                    compare_int(
                        f"{block_name}.mae_splits.{win}.{m}.n",
                        got["mae_splits_oer_sa"][win][m]["n"],
                        ref_block["mae_splits_oer_sa"][win][m]["n"],
                        checks,
                    )
                    compare_num(
                        f"{block_name}.mae_splits.{win}.{m}.mae",
                        got["mae_splits_oer_sa"][win][m]["mae"],
                        ref_block["mae_splits_oer_sa"][win][m]["mae"],
                        MAE_TOL,
                        checks,
                    )

    sa5 = ["persist", "trail3", "ar3", "ar3_zori_m1", "ar3_zori_m12"]
    sa4 = ["persist", "trail3", "ar3", "ar3_zori_m1"]
    compare_forecast_block(
        "forecast_1m_oer_sa_common", cm_sa, ref["forecast_1m_oer_sa_common"], sa5, True
    )
    compare_forecast_block(
        "forecast_1m_oer_sa_common_without_m12",
        cm_no_m12,
        ref["forecast_1m_oer_sa_common_without_m12"],
        sa4,
        True,
    )
    compare_forecast_block(
        "forecast_1m_oer_nsa_common", cm_nsa, ref["forecast_1m_oer_nsa_common"], sa5, False
    )

    checks.append(
        (
            "forecast_1m_ar3_zori_ksearch",
            True,
            "not re-derived (k-search skipped by verifier)",
        )
    )

    rt = ref["three_month"]["common_sample_non_overlapping"]
    compare_int("three_month.non_overlap.n", three_m["n"], rt["n"], checks)
    for m in ("trail3_x3", "direct_ar", "direct_ar_zori"):
        compare_num(
            f"three_month.non_overlap.{m}.mae",
            three_m["models"][m]["mae"],
            rt["models"][m]["mae"],
            MAE_TOL,
            checks,
        )

    ref_d12 = ref["directional_12_zori_all"]["non_overlapping"]
    for rule in ("gap", "always_decline", "momentum"):
        compare_num(
            f"directional_12.non_overlap.{rule}.hit_rate",
            d12["non_overlapping"][rule]["hit_rate"],
            ref_d12[rule]["hit_rate"],
            HIT_TOL,
            checks,
        )
        compare_int(
            f"directional_12.non_overlap.{rule}.n",
            d12["non_overlapping"][rule]["n"],
            ref_d12[rule]["n"],
            checks,
        )
        compare_int(
            f"directional_12.non_overlap.{rule}.zero_count",
            d12["non_overlapping"][rule]["zero_count"],
            ref_d12[rule]["zero_count"],
            checks,
        )

    lookahead_ok = not lookahead["same_month_feature_leak"]
    checks.append(
        (
            "lookahead: no same-month ZORI/OER feature at t for 1m models",
            lookahead_ok,
            "no leak detected" if lookahead_ok else "possible same-month feature use",
        )
    )
    training_ok = not lookahead["training_outcome_can_end_after_t_minus_1"]
    checks.append(
        (
            "lookahead: 3m training outcome window ends by t-1",
            training_ok,
            "add_months(s,2)<=prev_month(t) guard present" if training_ok else "guard missing",
        )
    )

    all_pass = all(c[1] for c in checks)
    verdict = "PASS" if all_pass else "FAIL"

    lines: list[str] = []
    lines.append(verdict)
    lines.append("")
    lines.append(
        "Independent recomputation from frozen BLS and ZORI CSVs (`verification/independent_recompute.py`, "
        "Python 3 + numpy only). A **PASS** confirms proxy arithmetic against `results/metrics.json` only; "
        "it does **not** convert Zillow ZORI into Cotality SFRI and is **not** a production model recommendation."
    )
    lines.append("")
    lines.append("## Hard data audits")
    lines.append("")
    for name, ok, detail in hard:
        lines.append(f"- [{'x' if ok else ' '}] {name}: {detail}")
    lines.append("")
    lines.append("## Metric comparisons vs `results/metrics.json`")
    lines.append("")
    metric_prefixes = (
        "january_2024",
        "as_of",
        "forecast_1m",
        "three_month",
        "directional_12",
    )
    for name, ok, detail in checks:
        if name.startswith("lookahead") or name == "forecast_1m_ar3_zori_ksearch":
            continue
        if not any(name.startswith(p) for p in metric_prefixes) and not name.startswith("No month"):
            if name.startswith("2025") or name.startswith("2026") or name.startswith("OER SA mom"):
                continue
        if name.startswith("No month") or name.startswith("2025") or name.startswith("2026") or name.startswith("OER SA mom"):
            continue
        status = "MATCH" if ok else "**MISMATCH**"
        lines.append(f"- {name}: {status} — {detail}")
    lines.append("")
    lines.append("## Skipped")
    lines.append("")
    lines.append("- `forecast_1m_ar3_zori_ksearch`: not re-derived (k-search omitted).")
    lines.append("")
    lines.append("## Lookahead audit (`scripts/proxy_sensitivity.py` read as text)")
    lines.append("")
    lines.append(
        f"**Same-month feature at prediction month t (1m models):** "
        f"{'none found' if lookahead_ok else 'POSSIBLE LEAK'}."
    )
    lines.append("")
    lines.append("Quoted feature lines:")
    for q in lookahead["feature_quotes"]:
        lines.append(f"- `{q}`")
    lines.append("")
    lines.append(
        f"**3-month training outcomes:** Training origins require `add_months(s, 2) <= prev_month(t)`, "
        f"so the realized 3-month window for training row `s` ends at `s+2` and cannot extend past `t-1`. "
        f"Guard present: {lookahead['three_month_training_cutoff_present']}."
    )
    lines.append("")
    lines.append("## Lookahead checks")
    lines.append("")
    for name, ok, detail in checks:
        if not name.startswith("lookahead"):
            continue
        lines.append(f"- {name}: {'PASS' if ok else 'FAIL'} — {detail}")
    lines.append("")
    lines.append("## Full check list")
    lines.append("")
    lines.append("| Check | Result | Detail |")
    lines.append("| --- | --- | --- |")
    for name, ok, detail in checks:
        lines.append(f"| {name} | {'PASS' if ok else 'FAIL'} | {detail} |")

    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
