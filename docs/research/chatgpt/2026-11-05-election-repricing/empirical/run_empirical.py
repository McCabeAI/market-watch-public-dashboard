#!/usr/bin/env python3
"""Empirical spread–FX correlation study. Design loaded from spec.json only."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SPEC_PATH = ROOT / "spec.json"


def _dump(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def sha256_json(payload: Any) -> str:
    return hashlib.sha256(_dump(payload).encode()).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_spec() -> dict:
    with SPEC_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def pearson_r(xs: list[float], ys: list[float]) -> tuple[float | None, int]:
    n = len(xs)
    if n != len(ys) or n < 2:
        return None, n
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mx) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - my) ** 2 for y in ys))
    if den_x == 0 or den_y == 0:
        return None, n
    return num / (den_x * den_y), n


def stat_block(
    xs: list[float],
    ys: list[float],
    dates_x: list[str],
    *,
    inconclusive_threshold: int | None = None,
) -> dict:
    r, n = pearson_r(xs, ys)
    out: dict[str, Any] = {"N": n}
    if inconclusive_threshold is not None and n < inconclusive_threshold:
        out["label"] = "inconclusive"
    if r is None:
        out["pearson_r"] = None
        out["R2"] = None
        out["sign"] = None
    else:
        out["pearson_r"] = round(r, 4)
        out["R2"] = round(r * r, 4)
        out["sign"] = "+" if r > 0 else ("-" if r < 0 else "0")
    if dates_x:
        out["date_start"] = dates_x[0]
        out["date_end"] = dates_x[-1]
    return out


def holdout_signs(
    xs: list[float],
    ys: list[float],
    t_indices: list[int],
    split_idx: int,
    *,
    min_holdout: int,
) -> dict:
    x_in, y_in, x_out, y_out = [], [], [], []
    for x, y, i in zip(xs, ys, t_indices):
        if i < split_idx:
            x_in.append(x)
            y_in.append(y)
        else:
            x_out.append(x)
            y_out.append(y)
    r_in, n_in = pearson_r(x_in, y_in)
    r_out, n_out = pearson_r(x_out, y_out)

    def _sign(r: float | None) -> str | None:
        if r is None:
            return None
        if r > 0:
            return "+"
        if r < 0:
            return "-"
        return "0"

    ho: dict[str, Any] = {
        "split_aligned_index": split_idx,
        "N_in_sample": n_in,
        "N_holdout": n_out,
        "sign_in_sample": _sign(r_in),
        "sign_holdout": _sign(r_out),
    }
    if n_out < min_holdout:
        ho["holdout_label"] = "inconclusive"
        ho["signs_match"] = None
    else:
        ho["holdout_label"] = "ok"
        si, so = ho["sign_in_sample"], ho["sign_holdout"]
        ho["signs_match"] = si == so if si is not None and so is not None else None
    if r_in is not None:
        ho["r_in_sample"] = round(r_in, 4)
    if r_out is not None:
        ho["r_holdout"] = round(r_out, 4)
    return ho


def history_to_map(history: list[list[Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in history:
        if len(row) < 2:
            continue
        d, v = row[0], row[1]
        if v is None:
            continue
        out[str(d)] = float(v)
    return out


def align_panel(
    base_map: dict[str, float],
    quote_map: dict[str, float],
    spot_map: dict[str, float],
) -> tuple[list[str], list[float], list[float]]:
    dates = sorted(set(base_map) & set(quote_map) & set(spot_map))
    spreads = [base_map[d] - quote_map[d] for d in dates]
    spots = [spot_map[d] for d in dates]
    return dates, spreads, spots


def calendar_gaps(dates: list[str]) -> dict[str, float | int | None]:
    if len(dates) < 2:
        return {"min_gap_days": None, "median_gap_days": None, "max_gap_days": None}
    gaps = []
    for a, b in zip(dates[:-1], dates[1:]):
        da = datetime.strptime(a, "%Y-%m-%d")
        db = datetime.strptime(b, "%Y-%m-%d")
        gaps.append((db - da).days)
    gaps.sort()
    mid = len(gaps) // 2
    if len(gaps) % 2:
        med = float(gaps[mid])
    else:
        med = (gaps[mid - 1] + gaps[mid]) / 2.0
    return {
        "min_gap_days": gaps[0],
        "median_gap_days": med,
        "max_gap_days": gaps[-1],
    }


def log_return_forward(spots: list[float], i: int, h: int) -> float | None:
    if i + h >= len(spots):
        return None
    s0, s1 = spots[i], spots[i + h]
    if s0 <= 0 or s1 <= 0:
        return None
    return 100.0 * math.log(s1 / s0)


def log_return_one_step(spots: list[float], i: int) -> float | None:
    if i < 1:
        return None
    return log_return_forward(spots, i - 1, 1)


def run_pair(
    pair: dict,
    series_by_id: dict[str, dict],
    spec: dict,
) -> dict[str, Any]:
    by = series_by_id[pair["base_yield_id"]]
    qy = series_by_id[pair["quote_yield_id"]]
    sp = series_by_id[pair["spot_id"]]
    base_map = history_to_map(by["history"])
    quote_map = history_to_map(qy["history"])
    spot_map = history_to_map(sp["history"])
    dates, spreads, spots = align_panel(base_map, quote_map, spot_map)
    n = len(dates)
    split_idx = int(n * spec["holdout"]["in_sample_fraction"])
    if split_idx < 1:
        split_idx = 1
    if split_idx >= n:
        split_idx = max(1, n - 1)

    gaps = calendar_gaps(dates)
    panel = {
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "usable_N_levels": n,
        **gaps,
    }

    delta_spread: list[float | None] = [None] * n
    for i in range(1, n):
        delta_spread[i] = spreads[i] - spreads[i - 1]

    min_ho = spec["holdout"]["inconclusive_if_holdout_N_lt"]
    horizons = spec["horizons_aligned_steps"]
    inconclusive_n = 20

    result: dict[str, Any] = {"pair": pair["name"], "panel": panel, "S1": {}, "S2": {}, "S3": {}, "B1": {}}

    xs2, ys2, ds2, is2 = [], [], [], []
    for i in range(1, n):
        ret = log_return_one_step(spots, i)
        dlt = delta_spread[i]
        if ret is None or dlt is None:
            continue
        xs2.append(dlt)
        ys2.append(ret)
        ds2.append(dates[i])
        is2.append(i)
    s2_full = stat_block(xs2, ys2, ds2)
    s2_full["holdout"] = holdout_signs(xs2, ys2, is2, split_idx, min_holdout=min_ho)
    result["S2"] = s2_full

    for h in horizons:
        xs1, ys1, ds1, is1 = [], [], [], []
        for i in range(n):
            fw = log_return_forward(spots, i, h)
            if fw is None:
                continue
            xs1.append(spreads[i])
            ys1.append(fw)
            ds1.append(dates[i])
            is1.append(i)
        s1_h = stat_block(xs1, ys1, ds1)
        s1_h["holdout"] = holdout_signs(xs1, ys1, is1, split_idx, min_holdout=min_ho)
        if h > 1:
            xs1_no, ys1_no, ds1_no = [], [], []
            for i in range(0, n, h):
                fw = log_return_forward(spots, i, h)
                if fw is None:
                    continue
                xs1_no.append(spreads[i])
                ys1_no.append(fw)
                ds1_no.append(dates[i])
            s1_h["non_overlapping"] = stat_block(
                xs1_no, ys1_no, ds1_no, inconclusive_threshold=inconclusive_n
            )
        result["S1"][f"h{h}"] = s1_h

        xs3, ys3, ds3, is3 = [], [], [], []
        for i in range(1, n):
            dlt = delta_spread[i]
            fw = log_return_forward(spots, i, h)
            if dlt is None or fw is None:
                continue
            xs3.append(dlt)
            ys3.append(fw)
            ds3.append(dates[i])
            is3.append(i)
        s3_h = stat_block(xs3, ys3, ds3)
        s3_h["holdout"] = holdout_signs(xs3, ys3, is3, split_idx, min_holdout=min_ho)
        if h > 1:
            xs3_no, ys3_no, ds3_no = [], [], []
            for i in range(1, n, h):
                dlt = delta_spread[i]
                fw = log_return_forward(spots, i, h)
                if dlt is None or fw is None:
                    continue
                xs3_no.append(dlt)
                ys3_no.append(fw)
                ds3_no.append(dates[i])
            s3_h["non_overlapping"] = stat_block(
                xs3_no, ys3_no, ds3_no, inconclusive_threshold=inconclusive_n
            )
        result["S3"][f"h{h}"] = s3_h

        xb, yb, db, ib = [], [], [], []
        for i in range(1, n):
            lag = log_return_one_step(spots, i)
            fw = log_return_forward(spots, i, h)
            if lag is None or fw is None:
                continue
            xb.append(lag)
            yb.append(fw)
            db.append(dates[i])
            ib.append(i)
        b1_h = stat_block(xb, yb, db)
        b1_h["holdout"] = holdout_signs(xb, yb, ib, split_idx, min_holdout=min_ho)
        b1_h["compare_to_S1_R2"] = {
            "S1_R2": result["S1"][f"h{h}"].get("R2"),
            "B1_R2": b1_h.get("R2"),
            "S1_beats_momentum_in_sample": None,
        }
        xs1_in = [x for x, idx in zip(xs1, is1) if idx < split_idx]
        ys1_in = [y for y, idx in zip(ys1, is1) if idx < split_idx]
        xb_in = [x for x, idx in zip(xb, ib) if idx < split_idx]
        yb_in = [y for y, idx in zip(yb, ib) if idx < split_idx]
        r1_in, _ = pearson_r(xs1_in, ys1_in)
        rb_in, _ = pearson_r(xb_in, yb_in)
        if r1_in is not None and rb_in is not None:
            b1_h["compare_to_S1_R2"]["S1_beats_momentum_in_sample"] = (r1_in * r1_in) > (
                rb_in * rb_in
            )
        result["B1"][f"h{h}"] = b1_h

    return result


def nz_coverage(series_by_id: dict[str, dict]) -> dict:
    nz = series_by_id.get("NZ_2Y")
    if not nz:
        return {"id": "NZ_2Y", "present": False}
    hist = nz.get("history") or []
    dates = [str(row[0]) for row in hist if row]
    return {
        "id": "NZ_2Y",
        "stored_history_length": len(hist),
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "dates": dates,
        "excluded": "All NZ pairs excluded; history too short for closed design.",
    }


def main() -> int:
    spec = load_spec()
    input_path = Path(spec["input"]["path"])
    expected = spec["input"]["expected_content_sha256"]
    deviations: list[dict] = []

    if not input_path.is_file():
        print(f"ABORT: missing input {input_path}", file=sys.stderr)
        return 1

    file_hash = sha256_file(input_path)
    with input_path.open(encoding="utf-8") as f:
        snapshot = json.load(f)
    content = {k: v for k, v in snapshot.items() if k != "packet_sha256"}
    content_hash = sha256_json(content)

    if file_hash != expected:
        if content_hash != expected:
            print(
                f"ABORT: file sha256 {file_hash} != {expected}; content sha256 {content_hash}",
                file=sys.stderr,
            )
            out = {
                "status": "aborted",
                "reason": "input_integrity_failed",
                "file_sha256": file_hash,
                "content_sha256": content_hash,
                "expected_sha256": expected,
            }
            (ROOT / "results.json").write_text(_dump(out), encoding="utf-8")
            return 1
        deviations.append(
            {
                "type": "file_sha256_mismatch",
                "expected_sha256_in_spec": expected,
                "actual_file_sha256": file_hash,
                "content_sha256_matches_spec": content_hash,
                "note": "Spec pin matches packet content digest (json excluding packet_sha256), not raw file bytes.",
            }
        )

    node = snapshot
    for key in spec["input"]["series_path"]:
        node = node[key]
    series_list = node
    series_by_id = {s["id"]: s for s in series_list if s.get("id")}

    nz = nz_coverage(series_by_id)
    print("NZ_2Y coverage:", json.dumps(nz, indent=2))

    pair_results = []
    for pair in spec["pairs"]:
        missing = [
            k
            for k in (
                pair["base_yield_id"],
                pair["quote_yield_id"],
                pair["spot_id"],
            )
            if k not in series_by_id
        ]
        if missing:
            deviations.append(
                {
                    "type": "missing_series",
                    "pair": pair["name"],
                    "missing_ids": missing,
                }
            )
            continue
        pair_results.append(run_pair(pair, series_by_id, spec))

    results = {
        "status": "ok",
        "integrity": {
            "file_sha256": file_hash,
            "content_sha256": content_hash,
            "expected_content_sha256": expected,
            "embedded_packet_sha256": snapshot.get("packet_sha256"),
        },
        "deviations": deviations,
        "nz_2y": nz,
        "excluded_notes": spec["excluded_coverage_only"],
        "pairs": pair_results,
        "spec_file": str(SPEC_PATH),
    }

    out_json = ROOT / "results.json"
    out_json.write_text(_dump(results), encoding="utf-8")

    cov_path = ROOT / "coverage.csv"
    with cov_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "pair",
                "first_date",
                "last_date",
                "usable_N",
                "min_gap_days",
                "median_gap_days",
                "max_gap_days",
                "base_yield_id",
                "quote_yield_id",
                "spot_id",
            ]
        )
        for pr in pair_results:
            p = pr["panel"]
            pair_spec = next(p for p in spec["pairs"] if p["name"] == pr["pair"])
            w.writerow(
                [
                    pr["pair"],
                    p["first_date"],
                    p["last_date"],
                    p["usable_N_levels"],
                    p["min_gap_days"],
                    p["median_gap_days"],
                    p["max_gap_days"],
                    pair_spec["base_yield_id"],
                    pair_spec["quote_yield_id"],
                    pair_spec["spot_id"],
                ]
            )
        w.writerow([])
        w.writerow(
            [
                "NZ_2Y",
                "stored_len",
                nz.get("stored_history_length"),
                "first",
                nz.get("first_date"),
                "last",
                nz.get("last_date"),
            ]
        )
        w.writerow(["excluded", "NOK/SEK/GBP crosses", "no 2Y yield history"])
        w.writerow(["excluded", "NZ pairs", "NZ_2Y history too short"])

    print(f"Wrote {out_json} and {cov_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
