"""Authentic ECB close-only case curation for Chart Guy qualification."""

from __future__ import annotations

import copy
from datetime import date
from typing import Any, Mapping

try:
    from scripts.fx_technical.indicators import pair_indicators
except ImportError:  # pragma: no cover
    pair_indicators = None  # type: ignore[misc, assignment]


SETUP_CLASSES = (
    "trend_continuation",
    "breakout",
    "failed_breakout",
    "range",
    "disagreement",
    "no_trade",
)


def _sorted_series(series: Mapping[date, float]) -> list[tuple[date, float]]:
    return sorted(series.items(), key=lambda x: x[0])


def _prefix_dict(sorted_rows: list[tuple[date, float]], end_index: int) -> dict[date, float]:
    return dict(sorted_rows[: end_index + 1])


def _stack_agrees(ind: dict, trend: str) -> bool:
    close = ind.get("close")
    s20 = ind.get("sma_20")
    s50 = ind.get("sma_50")
    if close is None or s20 is None or s50 is None:
        return False
    if trend == "up":
        return close >= s20 >= s50
    if trend == "down":
        return close <= s20 <= s50
    return False


def _disagreement(ind: dict) -> tuple[bool, str | None]:
    trend = ind.get("trend")
    hist = ind.get("macd_histogram")
    rsi = ind.get("rsi_14")
    if trend == "up" and hist is not None and hist < 0:
        return True, "trend_up_macd_negative"
    if trend == "down" and hist is not None and hist > 0:
        return True, "trend_down_macd_positive"
    if trend == "up" and rsi is not None and rsi >= 70:
        return True, "rsi_elevated_in_uptrend"
    return False, None


def _classify_setup(ind: dict) -> tuple[str | None, str | None]:
    """Return (setup_class, conflict) if this observation is a curation candidate."""
    trend = ind.get("trend")
    vol = ind.get("vol_regime")

    if ind.get("failed_breakout_up_20") or ind.get("failed_breakout_down_20"):
        return "failed_breakout", None

    if ind.get("breakout_up_20") or ind.get("breakout_down_20"):
        return "breakout", None

    is_dis, conflict = _disagreement(ind)
    if is_dis:
        return "disagreement", conflict

    if trend in ("up", "down") and _stack_agrees(ind, trend):
        return "trend_continuation", None

    if trend == "range" and vol in ("compressed", "expanded"):
        return "range", None

    fresh_breakout = ind.get("breakout_up_20") or ind.get("breakout_down_20")
    if vol == "expanded" and trend in (None, "range") and not fresh_breakout:
        return "no_trade", "expanded_vol_no_structure"

    return None, None


def _is_candidate(ind: dict) -> bool:
    setup_class, _ = _classify_setup(ind)
    return setup_class is not None


def _forward_path(
    sorted_rows: list[tuple[date, float]], index: int, decision_close: float
) -> dict:
    out: dict[str, Any] = {
        "5D": None,
        "20D": None,
        "ret_5d_forward": None,
        "ret_20d_forward": None,
    }
    n = len(sorted_rows)

    def ret_at(offset: int) -> tuple[float | None, float | None]:
        j = index + offset
        if j >= n:
            return None, None
        px = sorted_rows[j][1]
        if decision_close == 0:
            return px, None
        pct = (px - decision_close) / decision_close * 100.0
        return px, pct

    c5, r5 = ret_at(5)
    c20, r20 = ret_at(20)
    out["5D"] = c5
    out["20D"] = c20
    out["ret_5d_forward"] = r5
    out["ret_20d_forward"] = r20
    return out


def _diversity_select(candidates: list[dict], max_cases: int) -> list[dict]:
    """Pick candidates across setup classes and pairs.

    Within a class, the least-used pair wins, then the earlier decision date.
    That stops the first pair in iteration order from filling the whole bank.
    """
    by_class: dict[str, list[dict]] = {c: [] for c in SETUP_CLASSES}
    for cand in candidates:
        cls = cand["setup_class"]
        if cls in by_class:
            by_class[cls].append(cand)

    selected: list[dict] = []
    seen_ids: set[str] = set()
    pair_counts: dict[str, int] = {}
    while len(selected) < max_cases:
        added = False
        for cls in SETUP_CLASSES:
            bucket = by_class[cls]
            pick_index = None
            best_key = None
            for index, item in enumerate(bucket):
                if item["case_id"] in seen_ids:
                    continue
                key = (pair_counts.get(item["pair"], 0), item["decision_date"], item["pair"])
                if best_key is None or key < best_key:
                    best_key = key
                    pick_index = index
            if pick_index is None:
                continue
            item = bucket.pop(pick_index)
            selected.append(item)
            seen_ids.add(item["case_id"])
            pair_counts[item["pair"]] = pair_counts.get(item["pair"], 0) + 1
            added = True
            if len(selected) >= max_cases:
                break
        if not added:
            break
    return selected


def _assign_splits(cases: list[dict], holdout_count: int) -> tuple[list[dict], str | None]:
    """Sort by decision_date, pair; assign study/holdout."""
    note = None
    ordered = sorted(cases, key=lambda c: (c["decision_date"], c["pair"]))
    n = len(ordered)
    if n < holdout_count + 5:
        h = max(1, n // 5)
        note = (
            f"Fewer than {holdout_count + 5} cases ({n}); "
            f"placed last {h} in holdout instead of {holdout_count}."
        )
        holdout_n = h
    else:
        holdout_n = holdout_count

    # Latest case of each conflict class is held out when it exists, then the
    # remaining slots are the latest other cases. Study material stays earlier.
    required = ("disagreement", "no_trade", "failed_breakout")
    holdout_ids: list[str] = []
    for cls in required:
        members = [c for c in ordered if c.get("setup_class") == cls]
        if members:
            holdout_ids.append(members[-1]["case_id"])
    for case in reversed(ordered):
        if len(holdout_ids) >= holdout_n:
            break
        if case["case_id"] not in holdout_ids:
            holdout_ids.append(case["case_id"])
    holdout_set = set(holdout_ids[:holdout_n])
    for case in ordered:
        case["split"] = "holdout" if case["case_id"] in holdout_set else "study"
    return ordered, note


def curate_cases(
    pairs: Mapping[str, Mapping[date, float]],
    *,
    min_cases: int = 25,
    max_cases: int = 40,
    holdout_count: int = 8,
    provenance: str = "ecb_euro_reference_crosses",
    synthetic: bool = False,
) -> dict:
    """Walk ECB close series and build authentic qualification cases without lookahead."""
    if pair_indicators is None:
        raise ImportError("scripts.fx_technical.indicators.pair_indicators is not available")

    candidates: list[dict] = []
    min_prefix = 200
    forward_need = 20

    for pair, series in pairs.items():
        sorted_rows = _sorted_series(series)
        if len(sorted_rows) < min_prefix + forward_need + 1:
            continue
        last_taken_index = -15
        for index in range(min_prefix - 1, len(sorted_rows) - forward_need):
            if index - last_taken_index < 15:
                continue
            obs_date = sorted_rows[index][0]
            prefix = _prefix_dict(sorted_rows, index)
            ind = pair_indicators(prefix, as_of=obs_date)
            if not _is_candidate(ind):
                continue
            setup_class, conflict = _classify_setup(ind)
            if setup_class is None:
                continue
            decision_close = ind.get("close")
            if decision_close is None:
                continue
            sub_path = _forward_path(sorted_rows, index, float(decision_close))
            case_id = f"{pair}-{obs_date.isoformat()}"
            candidates.append(
                {
                    "case_id": case_id,
                    "provenance": provenance,
                    "synthetic": synthetic,
                    "pair": pair,
                    "decision_date": obs_date,
                    "decision_close": decision_close,
                    "indicators": ind,
                    "subsequent_path": sub_path,
                    "setup_class": setup_class,
                    "conflict": conflict,
                }
            )
            last_taken_index = index

    selected = _diversity_select(candidates, max_cases)
    selected, split_note = _assign_splits(selected, holdout_count)

    status = "ok"
    coverage_note = None
    if len(selected) < min_cases:
        status = "incomplete_coverage"
        coverage_note = (
            f"Supplied ECB observations supported {len(candidates)} candidate episodes "
            f"and {len(selected)} after diversity selection; target minimum was {min_cases}."
        )
    if split_note:
        coverage_note = f"{coverage_note or ''} {split_note}".strip()

    return {
        "status": status,
        "cases": selected,
        "candidate_count": len(candidates),
        "coverage_note": coverage_note,
    }


_EXAM_LABELS = ("setup_class", "split", "synthetic", "provenance", "conflict")


def blind_view(case: dict) -> dict:
    """Deep copy of a case with the answer key and exam labels removed.

    The examinee sees the decision-date indicators. Subsequent closes, the
    curator class, the holdout split, and the conflict label stay in the
    answer key only.
    """
    out = copy.deepcopy(case)
    out.pop("subsequent_path", None)
    for key in list(out.keys()):
        if key in _EXAM_LABELS or "forward" in key.lower():
            out.pop(key, None)
    sp = out.get("indicators") or {}
    cleaned = {k: v for k, v in sp.items() if "forward" not in k.lower()}
    out["indicators"] = cleaned
    return out


def assert_no_lookahead(case: dict, series: Mapping[date, float]) -> None:
    """Recompute indicators on prefix only; raise ValueError on mismatch."""
    if pair_indicators is None:
        raise ImportError("scripts.fx_technical.indicators.pair_indicators is not available")

    decision_date = case["decision_date"]
    prefix = {d: v for d, v in series.items() if d <= decision_date}
    fresh = pair_indicators(prefix, as_of=decision_date)
    stored = case.get("indicators") or {}
    check_keys = (
        "close",
        "rsi_14",
        "trend",
        "breakout_up_20",
        "breakout_down_20",
    )
    for key in check_keys:
        if fresh.get(key) != stored.get(key):
            raise ValueError(
                f"Lookahead or indicator drift on {key}: "
                f"stored={stored.get(key)!r} recomputed={fresh.get(key)!r}"
            )
