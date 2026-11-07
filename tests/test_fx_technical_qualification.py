"""Unit tests for Chart Guy case curation and blind qualification scoring."""

from __future__ import annotations

import copy
import math
import unittest
from datetime import date, timedelta
from typing import Mapping
from unittest.mock import patch

from scripts.fx_technical.cases import (
    assert_no_lookahead,
    blind_view,
    curate_cases,
)
from scripts.fx_technical.qualification import score_response, summarize_qualification

INDICATORS_AVAILABLE = True
try:
    from scripts.fx_technical.indicators import pair_indicators as _real_pair_indicators
except ImportError:
    INDICATORS_AVAILABLE = False
    _real_pair_indicators = None


def _business_days(start: date, count: int) -> list[date]:
    out: list[date] = []
    d = start
    while len(out) < count:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _synthetic_uptrend_series(n: int = 260, base: float = 1.10) -> dict[date, float]:
    """Deterministic sine-on-trend closes for unit fixtures only (not ECB history)."""
    days = _business_days(date(2018, 1, 1), n)
    series: dict[date, float] = {}
    for i, d in enumerate(days):
        drift = 0.00015 * i
        wave = 0.002 * math.sin(i / 8.0)
        series[d] = base + drift + wave
    return series


def _base_case(
    *,
    setup_class: str = "trend_continuation",
    trend: str = "up",
    rsi: float = 55.0,
    histogram: float = 0.0001,
    decision_close: float = 1.12,
    conflict: str | None = None,
) -> dict:
    return {
        "case_id": "EURUSD-2019-06-15",
        "provenance": "synthetic_unit_fixture",
        "synthetic": True,
        "pair": "EURUSD",
        "decision_date": date(2019, 6, 15),
        "decision_close": decision_close,
        "indicators": {
            "close": decision_close,
            "sma_20": decision_close - 0.002,
            "sma_50": decision_close - 0.004,
            "sma_200": decision_close - 0.01,
            "rsi_14": rsi,
            "macd_histogram": histogram,
            "trend": trend,
            "breakout_up_20": False,
            "breakout_down_20": False,
            "failed_breakout_up_20": False,
            "failed_breakout_down_20": False,
            "vol_regime": "normal",
            "status": "ok",
            "observation_date": date(2019, 6, 15),
        },
        "subsequent_path": {
            "5D": 1.125,
            "20D": 1.14,
            "ret_5d_forward": 0.45,
            "ret_20d_forward": 1.79,
        },
        "setup_class": setup_class,
        "conflict": conflict,
        "split": "study",
    }


def _response_trade_with_trend(case: dict) -> dict:
    dc = case["decision_close"]
    return {
        "case_id": case["case_id"],
        "decision": "TRADE",
        "pair": case["pair"],
        "direction": "long_base",
        "horizon": "5D",
        "entry": dc,
        "invalidation": dc - 0.01,
        "target": dc + 0.025,
        "indicator_read": {
            "trend": "up",
            "rsi_not_automatically_reversal": True,
            "macd_agrees_with_trend": True,
            "conflict": None,
        },
        "uses_ohlc_atr_candles": False,
        "cites_post_cutoff": False,
        "rationale": "Close above rising averages; MACD histogram agrees with uptrend.",
    }


class TestScoreResponse(unittest.TestCase):
    def test_uptrend_trade_with_trend_passes(self) -> None:
        case = _base_case()
        result = score_response(case, _response_trade_with_trend(case))
        self.assertTrue(result["passed"])
        self.assertEqual(result["score"], 1.0)
        self.assertEqual(result["failures"], [])

    def test_rsi_elevated_fade_fails(self) -> None:
        case = _base_case(rsi=74.0, trend="up", histogram=-0.0001)
        resp = _response_trade_with_trend(case)
        resp["direction"] = "short_base"
        resp["invalidation"] = case["decision_close"] + 0.01
        resp["target"] = case["decision_close"] - 0.02
        resp["indicator_read"]["rsi_not_automatically_reversal"] = False
        resp["indicator_read"]["macd_agrees_with_trend"] = False
        result = score_response(case, resp)
        self.assertFalse(result["passed"])
        self.assertIn("rsi_extreme_faded_trend", result["failures"])

    def test_disagreement_forced_trade_fails(self) -> None:
        case = _base_case(
            setup_class="disagreement",
            conflict="trend_up_macd_negative",
            histogram=-0.0002,
        )
        resp = _response_trade_with_trend(case)
        result = score_response(case, resp)
        self.assertFalse(result["passed"])
        self.assertIn("forced_trade_on_conflict", result["failures"])

    def test_disagreement_no_trade_passes(self) -> None:
        case = _base_case(
            setup_class="disagreement",
            conflict="trend_up_macd_negative",
            histogram=-0.0002,
        )
        resp = {
            "case_id": case["case_id"],
            "decision": "NO_TRADE",
            "pair": case["pair"],
            "direction": None,
            "horizon": None,
            "entry": None,
            "invalidation": None,
            "target": None,
            "indicator_read": {
                "trend": "up",
                "rsi_not_automatically_reversal": True,
                "macd_agrees_with_trend": False,
                "conflict": case["conflict"],
            },
            "uses_ohlc_atr_candles": False,
            "cites_post_cutoff": False,
            "rationale": "Trend and MACD disagree; standing aside per playbook.",
        }
        result = score_response(case, resp)
        self.assertTrue(result["passed"])

    def test_reward_not_above_risk_fails(self) -> None:
        case = _base_case()
        resp = _response_trade_with_trend(case)
        dc = case["decision_close"]
        resp["invalidation"] = dc - 0.02
        resp["target"] = dc + 0.005
        result = score_response(case, resp)
        self.assertFalse(result["passed"])
        self.assertIn("reward_not_above_risk", result["failures"])


class TestBlindViewAndLookahead(unittest.TestCase):
    def test_blind_view_strips_forward(self) -> None:
        case = _base_case()
        blind = blind_view(case)
        self.assertNotIn("subsequent_path", blind)
        self.assertEqual(blind["indicators"], case["indicators"])
        for label in ("setup_class", "split", "synthetic", "provenance", "conflict"):
            self.assertNotIn(label, blind)

    @unittest.skipUnless(INDICATORS_AVAILABLE, "indicators module not present")
    def test_assert_no_lookahead_passes_on_real_prefix(self) -> None:
        series = _synthetic_uptrend_series(280)
        curated = curate_cases(
            {"EURUSD": series},
            min_cases=1,
            max_cases=5,
            synthetic=True,
            provenance="synthetic_unit_fixture",
        )
        if not curated["cases"]:
            self.skipTest("synthetic series produced no candidates")
        case = curated["cases"][0]
        assert_no_lookahead(case, series)

    @unittest.skipUnless(INDICATORS_AVAILABLE, "indicators module not present")
    def test_assert_no_lookahead_fails_on_tamper(self) -> None:
        series = _synthetic_uptrend_series(280)
        curated = curate_cases(
            {"EURUSD": series},
            min_cases=1,
            max_cases=5,
            synthetic=True,
            provenance="synthetic_unit_fixture",
        )
        if not curated["cases"]:
            self.skipTest("synthetic series produced no candidates")
        case = copy.deepcopy(curated["cases"][0])
        case["indicators"]["trend"] = "down"
        with self.assertRaises(ValueError):
            assert_no_lookahead(case, series)


class TestCurateCases(unittest.TestCase):
    def test_holdout_split_and_playbook_isolation(self) -> None:
        series = _synthetic_uptrend_series(450)
        if INDICATORS_AVAILABLE:
            out = curate_cases(
                {"EURUSD": series},
                min_cases=25,
                max_cases=40,
                holdout_count=8,
                synthetic=True,
                provenance="synthetic_unit_fixture",
            )
        else:
            with patch(
                "scripts.fx_technical.cases.pair_indicators",
                side_effect=lambda s, as_of=None, clock=None: {
                    "close": list(s.values())[-1],
                    "sma_20": list(s.values())[-1] - 0.001,
                    "sma_50": list(s.values())[-1] - 0.002,
                    "sma_200": list(s.values())[-1] - 0.005,
                    "rsi_14": 55.0,
                    "macd_histogram": 0.0001,
                    "trend": "up",
                    "breakout_up_20": False,
                    "breakout_down_20": False,
                    "failed_breakout_up_20": False,
                    "failed_breakout_down_20": False,
                    "rv_20": 0.05,
                    "rv_60": 0.05,
                    "vol_regime": "normal",
                    "ret_5d": 0.1,
                    "ret_20d": 0.2,
                    "status": "ok",
                    "observation_date": as_of,
                    "null_reasons": {},
                },
            ):
                out = curate_cases(
                    {"EURUSD": series},
                    min_cases=25,
                    max_cases=40,
                    holdout_count=8,
                    synthetic=True,
                    provenance="synthetic_unit_fixture",
                )

        holdouts = [c for c in out["cases"] if c.get("split") == "holdout"]
        self.assertGreaterEqual(len(holdouts), 1)
        if out["status"] == "incomplete_coverage" or len(out["cases"]) < 25:
            self.assertIn(out["status"], ("incomplete_coverage", "ok"))

        playbook_path = (
            "/agent/repos/market-watch-public-dashboard/docs/fx_technical/CHART_GUY_PLAYBOOK.md"
        )
        with open(playbook_path, encoding="utf-8") as fh:
            playbook_text = fh.read()
        for case in out["cases"]:
            if case.get("split") == "holdout":
                self.assertNotIn(case["case_id"], playbook_text)

    def test_synthetic_flag_on_fixture(self) -> None:
        series = _synthetic_uptrend_series(280)
        if not INDICATORS_AVAILABLE:
            mock_ind = patch(
                "scripts.fx_technical.cases.pair_indicators",
                side_effect=lambda s, as_of=None, clock=None: {
                    "close": list(s.values())[-1],
                    "sma_20": list(s.values())[-1] * 0.999,
                    "sma_50": list(s.values())[-1] * 0.998,
                    "sma_200": list(s.values())[-1] * 0.99,
                    "rsi_14": 55.0,
                    "macd_histogram": 0.0001,
                    "trend": "up",
                    "breakout_up_20": False,
                    "breakout_down_20": False,
                    "failed_breakout_up_20": False,
                    "failed_breakout_down_20": False,
                    "vol_regime": "normal",
                    "status": "ok",
                    "observation_date": as_of,
                    "null_reasons": {},
                },
            )
            ctx = mock_ind
        else:
            from contextlib import nullcontext

            ctx = nullcontext()

        with ctx:
            out = curate_cases(
                {"EURUSD": series},
                min_cases=1,
                max_cases=10,
                synthetic=True,
                provenance="synthetic_unit_fixture",
            )
        for case in out["cases"]:
            self.assertTrue(case["synthetic"])
            self.assertEqual(case["provenance"], "synthetic_unit_fixture")


class TestSummarizeQualification(unittest.TestCase):
    def test_gate_respects_conflict_cases(self) -> None:
        case = _base_case(setup_class="disagreement", histogram=-0.0001)
        good = score_response(
            case,
            {
                "case_id": case["case_id"],
                "decision": "NO_TRADE",
                "pair": "EURUSD",
                "direction": None,
                "horizon": None,
                "entry": None,
                "invalidation": None,
                "target": None,
                "indicator_read": {
                    "trend": "up",
                    "rsi_not_automatically_reversal": True,
                    "macd_agrees_with_trend": False,
                    "conflict": "trend_up_macd_negative",
                },
                "uses_ohlc_atr_candles": False,
                "cites_post_cutoff": False,
                "rationale": "Conflict; no trade.",
            },
        )
        good["setup_class"] = "disagreement"
        summary = summarize_qualification([good])
        self.assertEqual(summary["gate"], "fail")  # n < 8


if __name__ == "__main__":
    unittest.main()
