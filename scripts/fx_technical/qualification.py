"""Blind qualification scoring for Chart Guy FX technical responses."""

from __future__ import annotations

import math
import re
from typing import Any

EXCLUDED_RATIONALE_WORDS = ("doji", "hammer", "engulfing", "atr", "candlestick")

SETUP_NO_TRADE_CLASSES = frozenset({"disagreement", "no_trade"})
FAILURE_BUCKETS = 8


def _trend_label(trend: Any) -> str:
    if trend is None:
        return "insufficient"
    if trend in ("up", "down", "range"):
        return trend
    return "insufficient"


def _macd_agrees_expected(trend: Any, histogram: Any) -> bool | None:
    if histogram is None or trend not in ("up", "down"):
        return None
    if trend == "up":
        return histogram > 0
    return histogram < 0


def _numbers_in_text(text: str) -> list[float]:
    pattern = re.compile(r"(?<![\w.])(-?\d+\.?\d*)(?![\w.])")
    out: list[float] = []
    for m in pattern.finditer(text):
        try:
            out.append(float(m.group(1)))
        except ValueError:
            continue
    return out


def _significant_match(a: float, b: float, min_sig: int = 4) -> bool:
    if a == b:
        return True
    if a == 0 or b == 0:
        return abs(a - b) < 1e-12
    # Match if rounded to min_sig significant figures they agree
    def sig_round(x: float, n: int) -> float:
        if x == 0:
            return 0.0
        exp = math.floor(math.log10(abs(x)))
        scale = 10 ** (n - 1 - exp)
        return round(x * scale) / scale

    return sig_round(a, min_sig) == sig_round(b, min_sig)


def score_response(case: dict, response: dict) -> dict:
    """Score a blind qualification response against a case (may include holdout path)."""
    failures: list[str] = []
    case_id = case.get("case_id")
    indicators = case.get("indicators") or {}
    setup_class = case.get("setup_class")
    decision_close = case.get("decision_close")
    trend = indicators.get("trend")
    rsi_14 = indicators.get("rsi_14")
    histogram = indicators.get("macd_histogram")

    if response.get("case_id") != case_id:
        failures.append("case_id_mismatch")
    if response.get("pair") != case.get("pair"):
        failures.append("pair_mismatch")
    if response.get("cites_post_cutoff") is not False:
        failures.append("cites_post_cutoff")
    if response.get("uses_ohlc_atr_candles") is not False:
        failures.append("uses_ohlc_atr_candles")

    rationale = response.get("rationale") or ""
    sub_path = case.get("subsequent_path")
    if sub_path:
        for num in _numbers_in_text(rationale):
            for key in ("5D", "20D"):
                fwd = sub_path.get(key)
                if fwd is not None and _significant_match(num, float(fwd)):
                    failures.append("rationale_leaks_forward_close")
                    break
            if "rationale_leaks_forward_close" in failures:
                break

    indicator_read = response.get("indicator_read") or {}
    read_trend = indicator_read.get("trend")
    if read_trend != _trend_label(trend):
        failures.append("indicator_trend")

    expected_macd = _macd_agrees_expected(trend, histogram)
    stated_macd = indicator_read.get("macd_agrees_with_trend")
    if stated_macd != expected_macd:
        failures.append("indicator_macd")

    rationale_lower = rationale.lower()
    if any(word in rationale_lower for word in EXCLUDED_RATIONALE_WORDS):
        failures.append("excluded_technique")

    decision = response.get("decision")
    direction = response.get("direction")
    if (
        rsi_14 is not None
        and trend in ("up", "down")
        and ((rsi_14 >= 70 and trend == "up") or (rsi_14 <= 30 and trend == "down"))
    ):
        if decision == "TRADE":
            fades = (trend == "up" and direction == "short_base") or (
                trend == "down" and direction == "long_base"
            )
            if fades or not indicator_read.get("rsi_not_automatically_reversal"):
                failures.append("rsi_extreme_faded_trend")

    if setup_class in SETUP_NO_TRADE_CLASSES and decision != "NO_TRADE":
        failures.append("forced_trade_on_conflict")

    conflict = case.get("conflict") or indicators.get("conflict")
    macd_agrees = _macd_agrees_expected(trend, histogram) is True
    clean_actionable = (
        setup_class in ("trend_continuation", "breakout")
        and trend in ("up", "down")
        and macd_agrees
        and not conflict
    )
    if clean_actionable and decision != "TRADE":
        failures.append("missed_actionable_setup")

    if decision == "NO_TRADE":
        for field in ("horizon", "direction", "entry", "invalidation", "target"):
            if response.get(field) is not None:
                failures.append(f"no_trade_field_{field}_set")
    elif decision == "TRADE":
        horizon = response.get("horizon")
        if horizon not in ("5D", "20D"):
            failures.append("bad_horizon")

        if setup_class in ("trend_continuation", "breakout") and trend in ("up", "down"):
            if trend == "up" and direction != "long_base":
                failures.append("direction_opposes_trend")
            elif trend == "down" and direction != "short_base":
                failures.append("direction_opposes_trend")

        entry = response.get("entry")
        if decision_close is not None and entry is not None:
            ref = float(decision_close)
            if ref == 0:
                if entry != ref:
                    failures.append("entry_not_at_close")
            elif abs(float(entry) - ref) / abs(ref) > 0.005:
                failures.append("entry_not_at_close")
        elif entry is None:
            failures.append("entry_not_at_close")

        invalidation = response.get("invalidation")
        target = response.get("target")
        if entry is not None and invalidation is not None:
            if direction == "long_base" and float(invalidation) >= float(entry):
                failures.append("invalidation_side")
            if direction == "short_base" and float(invalidation) <= float(entry):
                failures.append("invalidation_side")
            if abs(float(entry) - float(invalidation)) <= 0:
                failures.append("invalidation_side")

        if entry is not None and target is not None:
            if direction == "long_base" and float(target) <= float(entry):
                failures.append("reward_not_above_risk")
            if direction == "short_base" and float(target) >= float(entry):
                failures.append("reward_not_above_risk")

        if entry is not None and invalidation is not None and target is not None:
            reward = abs(float(target) - float(entry))
            risk = abs(float(entry) - float(invalidation))
            if reward <= risk:
                failures.append("reward_not_above_risk")
    else:
        failures.append("bad_decision")

    passed = len(failures) == 0
    score = 1.0 if passed else 0.0
    return {
        "case_id": case_id,
        "setup_class": setup_class,
        "decision": decision,
        "passed": passed,
        "score": score,
        "failures": failures,
    }


def summarize_qualification(results: list[dict]) -> dict:
    """Summarize scorer results and apply the qualification gate."""
    n = len(results)
    passed_n = sum(1 for r in results if r.get("passed"))
    failed_ids = [r["case_id"] for r in results if not r.get("passed")]
    pass_rate = (passed_n / n) if n else 0.0

    conflict_failures = [
        r["case_id"]
        for r in results
        if r.get("setup_class") in SETUP_NO_TRADE_CLASSES and not r.get("passed")
    ]

    passed_trades = [
        r["case_id"]
        for r in results
        if r.get("passed") and r.get("decision") == "TRADE"
    ]
    gate = "pass"
    if n < 8 or pass_rate < 0.75 or conflict_failures or len(passed_trades) < 3:
        gate = "fail"

    return {
        "n": n,
        "passed": passed_n,
        "failed": n - passed_n,
        "pass_rate": pass_rate,
        "failed_ids": failed_ids,
        "gate": gate,
        "conflict_case_failures": conflict_failures,
        "passed_trade_ids": passed_trades,
    }
