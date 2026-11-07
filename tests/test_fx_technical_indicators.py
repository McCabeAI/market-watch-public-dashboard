from __future__ import annotations

import json
import math
import statistics
import unittest
from datetime import date, timedelta

from scripts.fx_technical.indicators import pair_indicators
from scripts.fx_technical.research import (
    build_technical_research,
    unavailable_technical_research,
)

FORBIDDEN_KEYS = frozenset(
    {"open", "high", "low", "atr", "ohlc", "candle", "candlestick"}
)


def _dated_series(closes: list[float], start: date | None = None) -> dict[date, float]:
    if start is None:
        start = date(2020, 1, 1)
    out: dict[date, float] = {}
    d = start
    for c in closes:
        out[d] = c
        d += timedelta(days=1)
    return out


def _ref_ema_full(values: list[float], period: int) -> list[float | None]:
    n = len(values)
    out: list[float | None] = [None] * n
    if n < period:
        return out
    k = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, n):
        prev = (values[i] - prev) * k + prev
        out[i] = prev
    return out


def _ref_rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(c, 0.0) for c in changes]
    losses = [max(-c, 0.0) for c in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(changes)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else None
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def _ref_macd(closes: list[float]) -> tuple[float | None, float | None, float | None]:
    if len(closes) < 34:
        return None, None, None
    ema12 = _ref_ema_full(closes, 12)
    ema26 = _ref_ema_full(closes, 26)
    macd_line = [
        (a - b if a is not None and b is not None else None) for a, b in zip(ema12, ema26)
    ]
    macd_vals = [m for m in macd_line if m is not None]
    if len(macd_vals) < 9:
        return None, None, None
    k = 2.0 / 10.0
    signal_seed = sum(macd_vals[:9]) / 9
    signal_line: list[float | None] = [None] * len(macd_line)
    first_idx = next(i for i, m in enumerate(macd_line) if m is not None)
    sig_start = first_idx + 8
    signal_line[sig_start] = signal_seed
    prev = signal_seed
    for i in range(sig_start + 1, len(macd_line)):
        m = macd_line[i]
        if m is None:
            continue
        prev = (m - prev) * k + prev
        signal_line[i] = prev
    last = len(closes) - 1
    m, s = macd_line[last], signal_line[last]
    if m is None or s is None:
        return None, None, None
    return m, s, m - s


def _ref_bollinger(closes: list[float], period: int = 20) -> dict[str, float | None]:
    if len(closes) < period:
        return {"mid": None, "upper": None, "lower": None}
    window = closes[-period:]
    mid = sum(window) / period
    std = statistics.pstdev(window)
    return {"mid": mid, "upper": mid + 2 * std, "lower": mid - 2 * std}


class TestFxTechnicalIndicators(unittest.TestCase):
    def test_sma_hand_benchmark(self):
        s20 = _dated_series([1.0] * 20)
        r = pair_indicators(s20, as_of=date(2020, 1, 20))
        self.assertEqual(r["sma_20"], 1.0)

        s_mix = _dated_series([1.0] * 19 + [1.1])
        r2 = pair_indicators(s_mix, as_of=date(2020, 1, 20))
        self.assertEqual(r2["sma_20"], round((19 + 1.1) / 20, 6))

    def test_reference_rsi_macd_bollinger(self):
        closes = [100.0 + i * 0.1 for i in range(60)]
        start = date(2020, 1, 1)
        series = _dated_series(closes, start=start)
        as_of = start + timedelta(days=len(closes) - 1)
        prod = pair_indicators(series, as_of=as_of)

        rsi_ref = _ref_rsi(closes)
        macd_ref, sig_ref, hist_ref = _ref_macd(closes)
        bb_ref = _ref_bollinger(closes)

        self.assertIsNotNone(rsi_ref)
        self.assertLess(abs(prod["rsi_14"] - round(rsi_ref, 2)), 0.01)

        self.assertIsNotNone(macd_ref)
        self.assertLess(abs(prod["macd"] - round(macd_ref, 6)), 5e-7)
        self.assertLess(abs(prod["macd_signal"] - round(sig_ref, 6)), 5e-7)
        self.assertLess(abs(prod["macd_histogram"] - round(hist_ref, 6)), 5e-7)

        self.assertEqual(prod["bollinger_mid"], round(bb_ref["mid"], 6))

    def test_anti_lookahead(self):
        closes = [1.0 + i * 0.01 for i in range(80)]
        full = _dated_series(closes)
        cut = _dated_series(closes[:50])
        as_of = date(2020, 1, 1) + timedelta(days=49)
        a = pair_indicators(full, as_of=as_of)
        b = pair_indicators(cut, as_of=as_of)
        keys = [
            "close",
            "sma_20",
            "sma_50",
            "rsi_14",
            "macd",
            "trend",
            "breakout_up_20",
            "breakout_down_20",
            "failed_breakout_up_20",
            "failed_breakout_down_20",
        ]
        for k in keys:
            self.assertEqual(a[k], b[k], msg=k)

    def test_insufficient_sample(self):
        series = _dated_series([1.0 + i * 0.01 for i in range(10)])
        r = pair_indicators(series, as_of=date(2020, 1, 10))
        self.assertEqual(r["status"], "insufficient_sample")
        self.assertIsNone(r["sma_20"])
        self.assertIsNone(r["rsi_14"])
        self.assertIsNone(r["macd"])
        self.assertIsNone(r["bollinger_mid"])
        self.assertIn("sma_20", r["null_reasons"])

    def test_stale_and_unavailable_age(self):
        series = _dated_series([1.05] * 25)
        last = date(2020, 1, 25)
        r_stale = pair_indicators(series, as_of=last, clock=last + timedelta(days=10))
        self.assertEqual(r_stale["status"], "stale")
        self.assertIsNotNone(r_stale["close"])

        r_dead = pair_indicators(series, as_of=last, clock=last + timedelta(days=30))
        self.assertEqual(r_dead["status"], "unavailable")
        self.assertIsNone(r_dead["close"])
        self.assertEqual(r_dead["null_reasons"].get("series"), "stale_beyond_mark")

    def test_no_forbidden_keys(self):
        series = _dated_series([1.0 + i * 0.02 for i in range(40)])
        r = pair_indicators(series, as_of=date(2020, 1, 1) + timedelta(days=39))
        blob = json.dumps(r).lower()
        for key in FORBIDDEN_KEYS:
            self.assertNotIn(f'"{key}"', blob)

    def test_build_technical_research(self):
        p1 = _dated_series([1.1 + i * 0.001 for i in range(60)], start=date(2024, 1, 1))
        p2 = _dated_series([0.9 + i * 0.002 for i in range(60)], start=date(2024, 1, 1))
        rep = build_technical_research(
            {"EURUSD": p1, "GBPUSD": p2},
            as_of=date(2024, 3, 1),
        )
        self.assertFalse(rep["vetoes_unrelated_trades"])
        self.assertLessEqual(len(rep["setups"]), 10)
        for setup in rep["setups"]:
            self.assertIsNone(setup["trade_recommendation"])
        build_technical_research(
            {"EURUSD": p1},
            as_of=date(2024, 3, 1),
            cross_asset_series=None,
            cross_asset_meta=None,
        )

    def test_unavailable_technical_research(self):
        rep = unavailable_technical_research("feed down")
        self.assertEqual(rep["status"], "unavailable")
        self.assertFalse(rep["vetoes_unrelated_trades"])
        self.assertEqual(rep["setups"], [])
        self.assertEqual(rep["pairs"], {})

    def test_failed_breakout_fixture(self):
        closes = [1.0] * 20 + [1.05, 1.0]
        series = _dated_series(closes)
        as_of = date(2020, 1, 22)
        r = pair_indicators(series, as_of=as_of)
        self.assertTrue(r["failed_breakout_up_20"])
        self.assertFalse(r["breakout_up_20"])

    def test_breakout_fixture(self):
        closes = [1.0] * 21 + [1.05]
        series = _dated_series(closes)
        r = pair_indicators(series, as_of=date(2020, 1, 22))
        self.assertTrue(r["breakout_up_20"])


if __name__ == "__main__":
    unittest.main()
