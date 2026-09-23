from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.country_registry import history_files, temperature_countries

ROOT = Path(__file__).resolve().parents[1]
CALIBRATION_PATH = ROOT / "data" / "temperature_calibration.json"
HISTORY_DIR = ROOT / "data" / "temperature_history"
STATE_PATH = ROOT / "data" / "temperature_scores.json"
PATHS_PATH = HISTORY_DIR / "score_paths.json"

COUNTRY_CODES = temperature_countries()
HISTORY_FILES = history_files()
DIMENSIONS = ("Inflation", "Labor", "Activity", "Consumer")

QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")
MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def load_calibration(path: Path = CALIBRATION_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_history(history_dir: Path = HISTORY_DIR) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for code in COUNTRY_CODES:
        path = history_dir / HISTORY_FILES[code]
        out[code] = json.loads(path.read_text(encoding="utf-8"))
    return out


def clip_score(value: float, lo: float = 1.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def display_score(score: float | None) -> str:
    if score is None:
        return "n/a"
    rounded = round(score, 1)
    if abs(rounded - round(rounded)) < 1e-9:
        return str(int(round(rounded)))
    return f"{rounded:.1f}"


def temperature_class(score: float | None) -> str | None:
    if score is None:
        return None
    if score <= 20:
        return "cold"
    if score <= 40:
        return "cool"
    if score <= 60:
        return "neutral"
    if score <= 80:
        return "warm"
    return "hot"


def parse_period(period: str) -> tuple[str, int, int]:
    m = QUARTER_RE.match(period)
    if m:
        year, q = int(m.group(1)), int(m.group(2))
        end_month = q * 3
        return ("Q", year, end_month)
    m = MONTH_RE.match(period)
    if m:
        return ("M", int(m.group(1)), int(m.group(2)))
    raise ValueError(f"invalid reference_period: {period}")


def period_sort_key(period: str) -> tuple[int, int]:
    kind, year, num = parse_period(period)
    if kind == "Q":
        return (year, num)
    return (year, num)


def period_leq(period: str, cutoff: str) -> bool:
    return period_sort_key(period) <= period_sort_key(cutoff)


def month_before(period: str) -> str | None:
    kind, year, num = parse_period(period)
    if kind == "Q":
        q = num // 3
        if q == 1:
            return f"{year - 1}-Q4"
        return f"{year}-Q{q - 1}"
    if num == 1:
        return f"{year - 1}-12"
    return f"{year}-{num - 1:02d}"


def consecutive_tail(values_by_period: dict[str, float], end_period: str, want: int) -> list[tuple[str, float]]:
    """Longest available trailing window ending at end_period (same cadence, stepping back)."""
    if end_period not in values_by_period:
        return []
    chain: list[tuple[str, float]] = [(end_period, values_by_period[end_period])]
    cursor = end_period
    while len(chain) < want:
        prev = month_before(cursor)
        if prev is None or prev not in values_by_period:
            break
        chain.append((prev, values_by_period[prev]))
        cursor = prev
    chain.reverse()
    return chain


def qoq_pct_to_saar(q: float) -> float:
    return ((1.0 + q / 100.0) ** 4 - 1.0) * 100.0


def apply_scoring_transform(name: str, window: list[float], spec: dict[str, Any]) -> float | None:
    if not window:
        return None
    if name == "identity":
        return window[-1]
    if name == "trailing_mean_n2":
        return sum(window) / len(window)
    if name == "trailing_mean_n3":
        return sum(window) / len(window)
    if name == "mean_qoq_to_saar_n2":
        saars = [qoq_pct_to_saar(v) for v in window]
        return sum(saars) / len(saars)
    if name == "mom_mean_n3":
        return sum(window) / len(window)
    if name == "qoq_to_saar":
        q = window[-1]
        return qoq_pct_to_saar(q)
    if name == "mom_sa_compound_annualized_n3":
        n = len(window)
        prod = 1.0
        for m in window:
            prod *= 1.0 + m / 100.0
        periods_per_year = int(spec.get("periods_per_year", 12))
        return (prod ** (periods_per_year / n) - 1.0) * 100.0
    raise ValueError(f"unknown scoring_transform: {name}")


def component_level(x: float, spec: dict[str, Any], cal: dict[str, Any]) -> float:
    hot = int(spec["hot_direction"])
    anchor = float(spec["anchor"])
    scale = float(spec["scale_per_unit"])
    lo = float(cal.get("score_min", 1.0))
    hi = float(cal.get("score_max", 100.0))
    return clip_score(50.0 + hot * (x - anchor) * scale, lo, hi)


def _component_spec(cal: dict[str, Any], country: str, dimension: str, component: str) -> dict[str, Any]:
    key = f"{country}.{dimension}.{component}"
    spec = cal["components"][key]
    return spec


def _history_component(history: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    return history["components"][spec["history_key"]]


def _observations_for_spec(
    history: dict[str, Any], spec: dict[str, Any], cutoff: str
) -> list[dict[str, Any]]:
    comp = _history_component(history, spec)
    src_tf = spec["source_transformation"]
    rows: list[dict[str, Any]] = []
    for obs in comp.get("observations", []):
        if obs.get("transformation") != src_tf:
            continue
        if not period_leq(obs["reference_period"], cutoff):
            continue
        if "series_ids" in spec:
            if obs.get("series_id") not in spec["series_ids"]:
                continue
        elif spec.get("series_id"):
            if obs.get("series_id") != spec["series_id"]:
                continue
        rows.append(obs)
    return rows


def _collapse_equal_mean(rows: list[dict[str, Any]], series_ids: list[str]) -> dict[str, float]:
    by_period: dict[str, dict[str, float]] = {}
    for obs in rows:
        sid = obs.get("series_id")
        if sid not in series_ids:
            continue
        by_period.setdefault(obs["reference_period"], {})[sid] = float(obs["value"])
    out: dict[str, float] = {}
    for period, parts in by_period.items():
        if all(sid in parts for sid in series_ids):
            out[period] = sum(parts[sid] for sid in series_ids) / len(series_ids)
    return out


def raw_values_by_period(
    history: dict[str, Any], spec: dict[str, Any], cutoff: str
) -> dict[str, float]:
    rows = _observations_for_spec(history, spec, cutoff)
    if spec.get("collapse") == "equal_mean_same_period":
        series_ids = list(spec["series_ids"])
        return _collapse_equal_mean(rows, series_ids)
    out: dict[str, float] = {}
    for obs in rows:
        out[obs["reference_period"]] = float(obs["value"])
    return out


def _transform_name(spec: dict[str, Any], role: str) -> str:
    key = f"{role}_scoring_transform"
    if key in spec:
        return str(spec[key])
    return str(spec["scoring_transform"])


def _n_periods_for_transform(tf: str, spec: dict[str, Any]) -> int:
    if tf in ("trailing_mean_n2", "mean_qoq_to_saar_n2"):
        return 2
    if tf in ("trailing_mean_n3", "mom_mean_n3", "mom_sa_compound_annualized_n3"):
        return int(spec.get("n_periods", 3))
    if tf == "identity":
        return 1
    if tf == "qoq_to_saar":
        return 1
    return int(spec.get("n_periods", 3))


def transform_at_period(
    values_by_period: dict[str, float],
    period: str,
    spec: dict[str, Any],
    role: str = "level",
) -> float | None:
    if period not in values_by_period:
        return None
    tf = _transform_name(spec, role)
    if tf == "identity":
        return values_by_period[period]
    n = _n_periods_for_transform(tf, spec)
    window_vals = [v for _, v in consecutive_tail(values_by_period, period, n)]
    if not window_vals:
        return None
    return apply_scoring_transform(tf, window_vals, spec)


@dataclass
class ComponentResult:
    observed: bool
    as_of: str | None
    transform_value: float | None
    level: float | None
    impulse: float | None
    short_window: bool = False
    weight: float = 0.0


def score_component(
    history: dict[str, Any],
    spec: dict[str, Any],
    cal: dict[str, Any],
    cutoff: str,
    weight: float,
) -> ComponentResult:
    if spec.get("observed") is False:
        return ComponentResult(False, None, None, None, None, weight=weight)

    values = raw_values_by_period(history, spec, cutoff)
    if not values:
        return ComponentResult(False, None, None, None, None, weight=weight)

    periods = sorted(values.keys(), key=period_sort_key)
    latest = periods[-1]
    level_tf = _transform_name(spec, "level")
    x_latest = transform_at_period(values, latest, spec, role="level")
    if x_latest is None:
        return ComponentResult(False, None, None, None, None, weight=weight)

    level_latest = component_level(x_latest, spec, cal)
    n_level = _n_periods_for_transform(level_tf, spec)
    tail = consecutive_tail(values, latest, n_level)
    short_window = len(tail) < n_level and level_tf != "identity"

    impulse: float | None = None
    if len(periods) >= 2:
        prev = periods[-2]
        x_imp_latest = transform_at_period(values, latest, spec, role="impulse")
        x_imp_prev = transform_at_period(values, prev, spec, role="impulse")
        if x_imp_latest is not None and x_imp_prev is not None:
            impulse = component_level(x_imp_latest, spec, cal) - component_level(
                x_imp_prev, spec, cal
            )

    return ComponentResult(
        True,
        latest,
        x_latest,
        level_latest,
        impulse,
        short_window=short_window,
        weight=weight,
    )


def aggregate_dimension(
    components: dict[str, float],
    results: dict[str, ComponentResult],
    cal: dict[str, Any],
) -> dict[str, Any]:
    num = 0.0
    cov = 0.0
    impulse_num = 0.0
    impulse_cov = 0.0
    for name, weight in components.items():
        res = results[name]
        if not res.observed or res.level is None:
            continue
        num += weight * res.level
        cov += weight
        if res.impulse is not None:
            impulse_num += weight * res.impulse
            impulse_cov += weight

    level = num / cov if cov > 0 else None
    impulse = impulse_num / impulse_cov if impulse_cov > 0 else None

    warming = float(cal["impulse_warming_threshold"])
    cooling = float(cal["impulse_cooling_threshold"])
    if impulse is None:
        direction = "static"
    elif impulse >= warming:
        direction = "warming"
    elif impulse <= cooling:
        direction = "cooling"
    else:
        direction = "static"

    return {
        "level": level,
        "impulse": impulse,
        "direction": direction,
        "coverage": cov,
        "temperature_class": temperature_class(level),
    }


def scoring_cutoff(cal: dict[str, Any], histories: dict[str, dict[str, Any]]) -> str:
    """Latest month the LEVEL engine may see.

    The calibration ``as_of`` stays the structural anchor. A later verified
    observation extends the scoring window; it does not move that anchor.
    """
    structural = str(cal.get("as_of") or "2026-09")[:7]
    best_key = period_sort_key(structural)
    best = structural
    for history in histories.values():
        for comp in (history.get("components") or {}).values():
            for obs in comp.get("observations") or []:
                period = obs.get("reference_period")
                if not isinstance(period, str):
                    continue
                try:
                    key = period_sort_key(period)
                except ValueError:
                    continue
                if key > best_key:
                    best_key = key
                    _kind, year, month = parse_period(period)
                    best = f"{year}-{month:02d}"
    return best


def compute_state(
    cal: dict[str, Any] | None = None,
    histories: dict[str, dict[str, Any]] | None = None,
    cutoff: str | None = None,
) -> dict[str, Any]:
    cal = cal or load_calibration()
    histories = histories or load_history()
    cutoff = cutoff or scoring_cutoff(cal, histories)

    countries: dict[str, Any] = {}
    for country in COUNTRY_CODES:
        history = histories[country]
        countries[country] = {}
        for dimension in DIMENSIONS:
            weights = cal["weights"][country][dimension]
            comp_results: dict[str, ComponentResult] = {}
            component_state: dict[str, Any] = {}
            for comp_name, weight in weights.items():
                spec = _component_spec(cal, country, dimension, comp_name)
                res = score_component(history, spec, cal, cutoff, float(weight))
                comp_results[comp_name] = res
                component_state[comp_name] = {
                    "observed": res.observed,
                    "as_of": res.as_of,
                    "transform_value": _r(res.transform_value, 4),
                    "level": _r(res.level),
                    "impulse": _r(res.impulse),
                    "weight": float(weight),
                    "coverage_contribution": float(weight) if res.observed and res.level is not None else 0.0,
                    "short_window": res.short_window,
                }
            agg = aggregate_dimension(weights, comp_results, cal)
            countries[country][dimension] = {
                **agg,
                "level": _r(agg["level"]),
                "impulse": _r(agg["impulse"]),
                "coverage": _r(agg["coverage"], 4),
                "as_of": cutoff,
                "components": weights,
                "component_state": component_state,
            }

    return {"cutoff": cutoff, "countries": countries}


def all_levels(state: dict[str, Any]) -> dict[str, dict[str, float | None]]:
    countries = state.get("countries") or state
    if "countries" in state and "cutoff" in state:
        countries = state["countries"]
    return {
        country: {
            dim: countries[country][dim].get("level")
            for dim in DIMENSIONS
        }
        for country in COUNTRY_CODES
    }


def all_impulses(state: dict[str, Any]) -> dict[str, dict[str, float | None]]:
    countries = state.get("countries") or state
    if "countries" in state and "cutoff" in state:
        countries = state["countries"]
    return {
        country: {
            dim: countries[country][dim].get("impulse")
            for dim in DIMENSIONS
        }
        for country in COUNTRY_CODES
    }


def build_lineage(cal: dict[str, Any]) -> str:
    return (
        "V1 structural LEVEL: score 50 = policy/trend anchor from "
        f"{cal.get('methodology', 'TEMPERATURE_LEVEL_CALIBRATION_V1')}; "
        "not the 2026-09-17 cumulative-impulse reindex. "
        "LEVEL = coverage-weighted anchored components; IMPULSE = latest print vs prior print."
    )


def _r(x: float | None, nd: int = 2) -> float | None:
    if x is None:
        return None
    return round(float(x), nd)


def build_score_state(
    cal: dict[str, Any],
    computed: dict[str, Any],
    events_by_dimension: dict[str, dict[str, list[dict[str, Any]]]] | None = None,
) -> dict[str, Any]:
    events_by_dimension = events_by_dimension or {}
    countries_out: dict[str, Any] = {}
    for country in COUNTRY_CODES:
        countries_out[country] = {}
        for dimension in DIMENSIONS:
            dim = computed["countries"][country][dimension]
            entry = {
                "level": dim["level"],
                "impulse": dim["impulse"],
                "direction": dim["direction"],
                "coverage": dim["coverage"],
                "temperature_class": dim["temperature_class"],
                "as_of": dim["as_of"],
                "components": dim["components"],
                "component_state": dim["component_state"],
                "lineage": build_lineage(cal),
            }
            ev = events_by_dimension.get(country, {}).get(dimension)
            if ev:
                entry["events"] = ev
            countries_out[country][dimension] = entry

    return {
        "version": 3,
        "methodology": cal["methodology"],
        "calibration": "data/temperature_calibration.json",
        "as_of": cal["as_of"],
        "last_refresh_date": cal["as_of"],
        "baseline_score": float(cal["neutral_score"]),
        "baseline_meaning": "structural_policy_neutral_not_reindex_date",
        "countries": countries_out,
    }


def validate_state(state: dict[str, Any]) -> None:
    if state.get("version") != 3:
        raise ValueError("temperature_scores.json must be version 3")
    if set(state.get("countries", {})) != set(COUNTRY_CODES):
        raise ValueError(f"countries must be {'/'.join(COUNTRY_CODES)}")
    for country in COUNTRY_CODES:
        dims = state["countries"][country]
        if set(dims) != set(DIMENSIONS):
            raise ValueError(f"{country} missing dimensions")
        for dimension in DIMENSIONS:
            spec = dims[dimension]
            for field in (
                "level",
                "impulse",
                "direction",
                "coverage",
                "temperature_class",
                "as_of",
                "components",
                "component_state",
                "lineage",
            ):
                if field not in spec:
                    raise ValueError(f"missing {country} {dimension} field {field}")
            weights = spec["components"]
            if abs(sum(float(w) for w in weights.values()) - 1.0) > 1e-9:
                raise ValueError(f"{country} {dimension} weights must sum to 1")
            level = spec["level"]
            if level is not None and not 1.0 <= float(level) <= 100.0:
                raise ValueError(f"{country} {dimension} level out of range")


def load_state(path: Path = STATE_PATH) -> dict[str, Any]:
    state = json.loads(path.read_text(encoding="utf-8"))
    validate_state(state)
    return state


def iter_path_cutoffs(start: str = "2025-09", end: str = "2026-09") -> list[str]:
    y, m = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    out: list[str] = []
    while (y, m) <= (ey, em):
        out.append(f"{y}-{m:02d}")
        if m == 12:
            y += 1
            m = 1
        else:
            m += 1
    return out


def build_paths(
    cal: dict[str, Any],
    histories: dict[str, dict[str, Any]],
    start: str = "2025-09",
    end: str = "2026-09",
) -> dict[str, Any]:
    cutoffs = iter_path_cutoffs(start, end)
    paths: dict[str, Any] = {c: {d: [] for d in DIMENSIONS} for c in COUNTRY_CODES}
    prev_levels: dict[str, dict[str, float | None]] = {
        c: {d: None for d in DIMENSIONS} for c in COUNTRY_CODES
    }

    for cutoff in cutoffs:
        computed = compute_state(cal, histories, cutoff=cutoff)
        for country in COUNTRY_CODES:
            for dimension in DIMENSIONS:
                dim = computed["countries"][country][dimension]
                paths[country][dimension].append(
                    {
                        "period": cutoff,
                        "level": dim["level"],
                        "impulse": dim["impulse"],
                        "direction": dim["direction"],
                        "coverage": dim["coverage"],
                    }
                )
                prev_levels[country][dimension] = dim["level"]

    pathology = scan_pathologies(paths, cal, histories)
    return {
        "version": 1,
        "methodology": cal["methodology"],
        "calibration": "data/temperature_calibration.json",
        "window": {"start": start, "end": end},
        "pathology": pathology,
        "paths": paths,
    }


def scan_pathologies(
    paths: dict[str, Any],
    cal: dict[str, Any],
    histories: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    max_jump = float(cal["pathology_checks"]["max_abs_month_jump_without_input_jump"])
    max_boundary = int(cal["pathology_checks"]["max_consecutive_boundary_months"])
    findings: list[dict[str, Any]] = []

    for country in COUNTRY_CODES:
        for dimension in DIMENSIONS:
            series = paths[country][dimension]
            for i in range(1, len(series)):
                prev = series[i - 1]["level"]
                cur = series[i]["level"]
                if prev is None or cur is None:
                    continue
                jump = abs(cur - prev)
                if jump > max_jump:
                    findings.append(
                        {
                            "kind": "large_level_jump",
                            "country": country,
                            "dimension": dimension,
                            "from_period": series[i - 1]["period"],
                            "to_period": series[i]["period"],
                            "delta": round(cur - prev, 3),
                            "note": "Inspect component releases; may be legitimate data.",
                        }
                    )

            boundary_run = 0
            boundary_val: float | None = None
            for point in series:
                lvl = point["level"]
                if lvl is not None and (lvl <= 1.01 or lvl >= 99.99):
                    if boundary_val is None or abs(lvl - boundary_val) < 0.05:
                        boundary_run += 1
                        boundary_val = lvl
                    else:
                        boundary_run = 1
                        boundary_val = lvl
                    if boundary_run > max_boundary:
                        findings.append(
                            {
                                "kind": "boundary_compression",
                                "country": country,
                                "dimension": dimension,
                                "period": point["period"],
                                "level": lvl,
                                "consecutive_months": boundary_run,
                            }
                        )
                else:
                    boundary_run = 0
                    boundary_val = None

    return {"max_abs_jump_threshold": max_jump, "findings": findings}


def write_state(path: Path = STATE_PATH) -> dict[str, Any]:
    cal = load_calibration()
    computed = compute_state(cal)
    state = build_score_state(cal, computed)
    validate_state(state)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return state


def write_paths(path: Path = PATHS_PATH) -> dict[str, Any]:
    cal = load_calibration()
    histories = load_history()
    doc = build_paths(cal, histories)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def print_levels_table(state: dict[str, Any]) -> None:
    levels = all_levels(state)
    print("Current LEVEL (1-100):")
    header = f"{'':6}" + "".join(f"{d:>12}" for d in DIMENSIONS)
    print(header)
    for country in COUNTRY_CODES:
        row = f"{country:6}"
        for dim in DIMENSIONS:
            val = levels[country][dim]
            row += f"{display_score(val):>12}"
        print(row)


def main() -> None:
    parser = argparse.ArgumentParser(description="Temperature LEVEL + IMPULSE engine (V1)")
    parser.add_argument("--write-state", action="store_true")
    parser.add_argument("--write-paths", action="store_true")
    parser.add_argument("--print-levels", action="store_true")
    args = parser.parse_args()

    state: dict[str, Any] | None = None
    if args.write_state:
        state = write_state()
    if args.write_paths:
        write_paths()
    if args.print_levels:
        state = state or load_state()
        print_levels_table(state)


if __name__ == "__main__":
    main()
