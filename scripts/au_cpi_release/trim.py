"""Rank-and-trim reconstruction of the monthly trimmed mean, plus the quarterly legacy check.

Expenditure classes are the leaf codes under All groups CPI (INDEX 10001) in
CL_CPI_INDEX. The primary variant uses seasonally adjusted class month-to-month
changes where a TSEST 20 index exists and the original change otherwise, with
price-updated weights contribution(t-1) / all-groups index(t-1). Two further
variants are reported and are not searched beyond that. G5 passes only on the
primary variant.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any

from scripts.au_cpi_release import TRIM_REPORT_SCHEMA
from scripts.au_cpi_release.contract import (
    Observation,
    Snapshot,
    previous_month,
)
from scripts.au_cpi_release.sources.acquire import resolve_source_path

PRIMARY_VARIANT = "sa_where_available_else_original__weight_t_minus_1"
VARIANT_ORIGINAL = "original_only__weight_t_minus_1"
VARIANT_WEIGHT_LAG2 = "sa_where_available_else_original__weight_t_minus_2"

CLASS_RULE = (
    "Expenditure classes are the leaf codes of codelist CL_CPI_INDEX (from the "
    "archived ABS,CPI,2.0.0 structure message) that descend from 10001 (All groups CPI) "
    "and have no children. In this codelist those leaves are the depth-3 expenditure "
    "classes. Groups, subgroups, special aggregates, analytical series (9999xx), "
    "tradables and goods/services components are excluded because they are not leaves "
    "under 10001."
)


def _round_1dp(value: float) -> float:
    from decimal import Decimal, ROUND_HALF_UP

    return float(Decimal(f"{value:.10f}").quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def expenditure_class_ids(structure: dict[str, Any]) -> tuple[list[str], dict[str, int]]:
    """Return leaf class ids under 10001 and a depth histogram of those leaves."""
    codelists = (structure.get("data") or {}).get("codelists") or []
    index_cl = next((item for item in codelists if item.get("id") == "CL_CPI_INDEX"), None)
    if index_cl is None:
        raise ValueError("codelist_missing:CL_CPI_INDEX")
    codes = index_cl.get("codes") or []
    if not codes or not any(code.get("parent") for code in codes):
        raise ValueError("codelist_missing_parent_links")
    children: dict[str, list[str]] = defaultdict(list)
    by_id: dict[str, dict[str, Any]] = {}
    for code in codes:
        by_id[str(code["id"])] = code
        parent = code.get("parent")
        if parent:
            children[str(parent)].append(str(code["id"]))
    if "10001" not in by_id:
        raise ValueError("codelist_missing:10001")
    leaves: list[str] = []
    stack = ["10001"]
    while stack:
        node = stack.pop()
        kids = children.get(node) or []
        if node != "10001" and not kids:
            leaves.append(node)
        else:
            stack.extend(kids)

    def depth(code_id: str) -> int:
        seen: set[str] = set()
        steps = 0
        current = code_id
        while current in by_id and by_id[current].get("parent") and current not in seen:
            seen.add(current)
            current = str(by_id[current]["parent"])
            steps += 1
        return steps

    def order(code_id: str) -> int:
        for annotation in by_id[code_id].get("annotations") or []:
            if annotation.get("type") == "ORDER":
                try:
                    return int(annotation.get("text") or 0)
                except (TypeError, ValueError):
                    return 0
        return 0

    leaves.sort(key=order)
    depths = {code_id: depth(code_id) for code_id in leaves}
    histogram: dict[str, int] = defaultdict(int)
    for value in depths.values():
        histogram[str(value)] += 1
    return leaves, dict(histogram)


def trimmed_weighted_mean(changes: list[float], weights: list[float], *, trim: float = 0.15) -> float:
    """Weighted mean of the central (1-2*trim) of the weight distribution.

    Items are sorted by change. A class that straddles a trim boundary keeps
    only the weight that falls inside the window.
    """
    if len(changes) != len(weights) or not changes:
        raise ValueError("trim inputs must be non-empty and aligned")
    total = sum(weights)
    if total <= 0:
        raise ValueError("non-positive weight")
    lower = trim * total
    upper = (1.0 - trim) * total
    cumulative = 0.0
    kept_weight = 0.0
    kept_sum = 0.0
    for change, weight in sorted(zip(changes, weights), key=lambda item: item[0]):
        start = cumulative
        end = cumulative + weight
        keep = max(0.0, min(end, upper) - max(start, lower))
        kept_sum += keep * change
        kept_weight += keep
        cumulative = end
    if kept_weight <= 0:
        raise ValueError("empty trim window")
    return kept_sum / kept_weight


def _series_map(snapshot: Snapshot, vintage: str) -> dict[tuple[str, str], float]:
    out: dict[tuple[str, str], float] = {}
    for obs in snapshot.observations:
        if obs.vintage != vintage:
            continue
        out[(obs.canonical_id, obs.period)] = obs.value
    return out


def _mom(level_now: float | None, level_prev: float | None) -> float | None:
    if level_now is None or level_prev is None or level_prev == 0:
        return None
    return (level_now / level_prev - 1.0) * 100.0


def _reconstruct_month(
    *,
    classes: list[str],
    levels: dict[tuple[str, str], float],
    month: str,
    use_sa: bool,
    weight_lag: int,
) -> dict[str, Any] | None:
    weight_period = month
    for _ in range(weight_lag):
        weight_period = previous_month(weight_period)
    previous = previous_month(month)
    all_index = levels.get(("headline_nsa_index", weight_period))
    if all_index is None or all_index == 0:
        return None
    changes: list[float] = []
    raw_weights: list[float] = []
    sa_used = 0
    original_used = 0
    missing = 0
    contribution_sum = 0.0
    contribution_count = 0
    for class_id in classes:
        contribution = levels.get((f"cpi.m.4.{class_id}.10.50", weight_period))
        if contribution is None or contribution <= 0:
            missing += 1
            continue
        change = None
        if use_sa:
            change = _mom(
                levels.get((f"cpi.m.1.{class_id}.20.50", month)),
                levels.get((f"cpi.m.1.{class_id}.20.50", previous)),
            )
            if change is not None:
                sa_used += 1
        if change is None:
            change = _mom(
                levels.get((f"cpi.m.1.{class_id}.10.50", month)),
                levels.get((f"cpi.m.1.{class_id}.10.50", previous)),
            )
            if change is None:
                missing += 1
                continue
            original_used += 1
        changes.append(change)
        raw_weights.append(contribution / all_index)
        contribution_sum += contribution
        contribution_count += 1
    if not changes:
        return None
    reconstructed = trimmed_weighted_mean(changes, raw_weights)
    published = levels.get(("trimmed_mean_monthly_sa_mom", month))
    unrounded = _mom(
        levels.get(("trimmed_mean_monthly_sa_index", month)),
        levels.get(("trimmed_mean_monthly_sa_index", previous)),
    )
    rounded_match = None
    if published is not None:
        rounded_match = _round_1dp(reconstructed) == _round_1dp(published)
    return {
        "period": month,
        "reconstructed_mom": reconstructed,
        "reconstructed_mom_1dp": _round_1dp(reconstructed),
        "published_mom_1dp": published,
        "unrounded_mom_from_index": unrounded,
        "abs_error_vs_unrounded_pp": None if unrounded is None else abs(reconstructed - unrounded),
        "rounded_match": rounded_match,
        "class_count": len(changes),
        "sa_class_count": sa_used,
        "original_class_count": original_used,
        "missing_class_count": missing,
        "weight_sum_before_normalisation": sum(raw_weights),
        "leaf_contribution_sum": contribution_sum,
        "all_groups_index_at_weight_period": all_index,
        "contribution_gap_vs_all_groups_index": contribution_sum - all_index,
    }


def _summarise_variant(variant_id: str, description: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [row for row in rows if row.get("abs_error_vs_unrounded_pp") is not None and row.get("rounded_match") is not None]
    errors = [float(row["abs_error_vs_unrounded_pp"]) for row in usable]
    matches = [row for row in usable if row["rounded_match"]]
    n = len(usable)
    rate = (len(matches) / n) if n else 0.0
    max_abs = max(errors) if errors else None
    mean_abs = fmean(errors) if errors else None
    reasons: list[str] = []
    if n < 12:
        reasons.append(f"months_covered {n} < 12")
    if n == 0 or rate < 0.90:
        reasons.append(f"rounded_match_rate {rate} < 0.90")
    if max_abs is None or max_abs > 0.05:
        reasons.append(f"max_abs_error_unrounded_pp {max_abs} > 0.05")
    class_counts = [int(row["class_count"]) for row in rows]
    gaps = [abs(float(row["contribution_gap_vs_all_groups_index"])) for row in rows]
    mismatches = [row["period"] for row in usable if not row["rounded_match"]]
    return {
        "variant_id": variant_id,
        "description": description,
        "months_covered": n,
        "months": [row["period"] for row in usable],
        "class_count_min": min(class_counts) if class_counts else 0,
        "class_count_max": max(class_counts) if class_counts else 0,
        "class_count_mean": fmean(class_counts) if class_counts else 0.0,
        "mean_abs_error_unrounded_pp": mean_abs,
        "max_abs_error_unrounded_pp": max_abs,
        "rounded_match_count": len(matches),
        "rounded_match_rate": rate,
        "rounded_mismatches": mismatches,
        "g5_pass": not reasons,
        "g5_reasons": reasons,
        "mean_abs_contribution_gap_vs_all_groups_index": fmean(gaps) if gaps else None,
        "rows": rows,
    }


def _variant_rows(
    classes: list[str],
    levels: dict[tuple[str, str], float],
    *,
    use_sa: bool,
    weight_lag: int,
) -> list[dict[str, Any]]:
    months = sorted({period for (canonical, period) in levels if canonical == "trimmed_mean_monthly_sa_mom"})
    rows: list[dict[str, Any]] = []
    for month in months:
        row = _reconstruct_month(
            classes=classes,
            levels=levels,
            month=month,
            use_sa=use_sa,
            weight_lag=weight_lag,
        )
        if row is not None:
            rows.append(row)
    return rows


def _pair_diff(left: dict[str, float], right: dict[str, float]) -> dict[str, Any]:
    overlap = sorted(set(left) & set(right))
    diffs = []
    matches = 0
    for period in overlap:
        diff = abs(left[period] - right[period])
        rounded_match = _round_1dp(left[period]) == _round_1dp(right[period])
        if rounded_match:
            matches += 1
        diffs.append({"period": period, "left": left[period], "right": right[period], "abs_diff": diff, "rounded_match": rounded_match})
    n = len(overlap)
    max_abs = max((item["abs_diff"] for item in diffs), default=None)
    mean_abs = fmean([item["abs_diff"] for item in diffs]) if diffs else None
    rate = (matches / n) if n else 0.0
    if n == 0:
        verdict = "blocked"
        reasons = ["no_overlap"]
    elif n >= 12 and rate == 1.0 and max_abs is not None and max_abs <= 0.05:
        verdict = "equivalent"
        reasons = []
    else:
        verdict = "not_equivalent"
        reasons = []
        if n < 12:
            reasons.append(f"overlap {n} < 12")
        if rate != 1.0:
            reasons.append(f"rounded_match_rate {rate} != 1")
        if max_abs is None or max_abs > 0.05:
            reasons.append(f"max_abs_diff {max_abs} > 0.05")
    worst = sorted(diffs, key=lambda item: item["abs_diff"], reverse=True)[:8]
    return {
        "n_overlap": n,
        "n_rounded_match": matches,
        "rounded_match_rate": rate,
        "mean_abs_diff_pp": mean_abs,
        "max_abs_diff_pp": max_abs,
        "verdict": verdict,
        "reasons": reasons,
        "worst_periods": worst,
        "rule": "equivalent only if n>=12, every overlap matches at 1 decimal, and max abs diff <= 0.05 pp",
    }


def _values(snapshot: Snapshot, canonical_id: str, vintage: str | None = None) -> dict[str, float]:
    out: dict[str, float] = {}
    for obs in snapshot.observations:
        if obs.canonical_id != canonical_id:
            continue
        if vintage is not None and obs.vintage != vintage:
            continue
        out[obs.period] = obs.value
    return out


def quarterly_legacy_equivalence(snapshot: Snapshot) -> dict[str, Any]:
    cpi_q = _values(snapshot, "trimmed_mean_quarterly_legacy_qoq", "abs_api")
    rba = _values(snapshot, "rba_g1_GCPIOCPMTMQP")
    appendix = _values(snapshot, "appendix_1a_trimmed_mean_qoq")
    cpi_vs_rba = _pair_diff(cpi_q, rba)
    if appendix:
        cpi_vs_appendix = _pair_diff(cpi_q, appendix)
        appendix_status = "obtained"
    else:
        cpi_vs_appendix = {"verdict": "not_obtained", "n_overlap": 0, "reasons": ["appendix_1a_not_in_snapshot"]}
        appendix_status = "not_obtained"
    if cpi_vs_rba["verdict"] == "equivalent" and cpi_vs_appendix.get("verdict") == "equivalent":
        verdict = "equivalent"
    elif cpi_vs_rba["verdict"] == "equivalent" and appendix_status != "obtained":
        verdict = "equivalent_vs_rba_appendix_not_obtained"
    elif cpi_vs_rba["verdict"] == "equivalent":
        verdict = "equivalent_vs_rba_appendix_not_equivalent"
    elif cpi_vs_rba["verdict"] == "blocked":
        verdict = "blocked"
    else:
        verdict = "not_equivalent"
    return {
        "cpi_q_vs_rba_g1_GCPIOCPMTMQP": cpi_vs_rba,
        "cpi_q_vs_appendix_1a": cpi_vs_appendix,
        "appendix_1a_status": appendix_status,
        "verdict": verdict,
        "note": (
            "Compared published QoQ percent changes (CPI_Q MEASURE 2 INDEX 999902, "
            "RBA G1 series GCPIOCPMTMQP, and Appendix 1a when the June 2026 workbook "
            "was parsed). This is not a claim that the monthly trimmed mean equals "
            "the quarterly legacy trimmed mean."
        ),
    }


def load_structure(snapshot: Snapshot, snapshot_dir: Path) -> dict[str, Any]:
    record = next((rec for rec in snapshot.source_records if rec.get("source_id") == "abs_cpi_structure"), None)
    if record is None:
        raise ValueError("structure source record missing")
    path = resolve_source_path(snapshot_dir, record)
    return json.loads(path.read_text(encoding="utf-8"))


def verify_trim(snapshot: Snapshot, snapshot_dir: Path) -> dict[str, Any]:
    structure = load_structure(snapshot, snapshot_dir)
    classes, depth_hist = expenditure_class_ids(structure)
    levels = _series_map(snapshot, "abs_api")
    sa_leaves = 0
    sample_period = "2026-08"
    for class_id in classes:
        if (f"cpi.m.1.{class_id}.20.50", sample_period) in levels:
            sa_leaves += 1
    primary_rows = _variant_rows(classes, levels, use_sa=True, weight_lag=1)
    original_rows = _variant_rows(classes, levels, use_sa=False, weight_lag=1)
    lag2_rows = _variant_rows(classes, levels, use_sa=True, weight_lag=2)
    variants = [
        _summarise_variant(
            PRIMARY_VARIANT,
            "SA class MoM where a TSEST 20 index exists for both months, else original MoM; "
            "price-updated weight = MEASURE 4 contribution at t-1 divided by the all-groups "
            "original index at t-1, then normalised over classes with both a weight and a change. "
            "15% of weight trimmed from each tail with partial boundary weights.",
            primary_rows,
        ),
        _summarise_variant(
            VARIANT_ORIGINAL,
            "Original (TSEST 10) class MoM for every class; same t-1 contribution weights.",
            original_rows,
        ),
        _summarise_variant(
            VARIANT_WEIGHT_LAG2,
            "Same SA-else-original price changes; weights from contribution(t-2) / all-groups index(t-2).",
            lag2_rows,
        ),
    ]
    primary = variants[0]
    claim = "reconstruction" if primary["g5_pass"] else "proxy"
    contribution_periods = sorted(
        {
            period
            for (canonical, period) in levels
            if canonical.startswith("cpi.m.4.") and canonical.endswith(".10.50")
        }
    )
    published_mom_periods = sorted(
        period for (canonical, period) in levels if canonical == "trimmed_mean_monthly_sa_mom"
    )
    coverage_note = (
        "Class MEASURE 4 contributions in this snapshot"
        + (f" start at {contribution_periods[0]}." if contribution_periods else " are absent.")
        + " A t-1 weight therefore cannot be formed before the following month. "
        + f"Published monthly trimmed-mean MoM periods: {published_mom_periods[0] if published_mom_periods else 'none'}"
        + (f"..{published_mom_periods[-1]} ({len(published_mom_periods)})." if published_mom_periods else ".")
        + " Months without a contribution weight are omitted rather than filled in."
    )
    return {
        "schema_version": TRIM_REPORT_SCHEMA,
        "class_identification": {
            "rule": CLASS_RULE,
            "codelist": "CL_CPI_INDEX",
            "root": "10001",
            "class_count": len(classes),
            "depth_histogram": depth_hist,
            "class_ids": classes,
            "leaves_with_sa_index_at_2026-08": sa_leaves,
        },
        "abs_error_definition": "absolute difference in percentage points versus the unrounded MoM implied by INDEX 999902 levels",
        "rounded_match_definition": "reconstruction rounded half-up to 1 decimal equals published MEASURE 2 (also at 1 decimal)",
        "primary_variant": PRIMARY_VARIANT,
        "variants": variants,
        "g5_verdict": "pass" if primary["g5_pass"] else "fail",
        "g5_claim": claim,
        "coverage_note": coverage_note,
        "g5_rule": "pass only if the primary variant's rounded MoM matches on >=90% of >=12 months and max abs error versus the unrounded index MoM is <= 0.05 pp",
        "quarterly_legacy_equivalence": quarterly_legacy_equivalence(snapshot),
    }


def write_trim_report(snapshot: Snapshot, snapshot_dir: Path, out: Path) -> Path:
    report = verify_trim(snapshot, snapshot_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "trim_verification.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
