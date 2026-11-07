from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

SCHEMA_VERSION = 1
SOURCE_NAME = "ecb_euro_reference_crosses"

_PRICE_DP = 6
_PCT_DP = 4
_RSI_DP = 2

INDICATOR_KEYS = (
    "close",
    "sma_20",
    "sma_50",
    "sma_200",
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_histogram",
    "bollinger_mid",
    "bollinger_upper",
    "bollinger_lower",
    "bollinger_bandwidth",
    "bollinger_percent_b",
    "rv_5",
    "rv_10",
    "rv_20",
    "rv_60",
    "ret_1d",
    "ret_5d",
    "ret_10d",
    "ret_20d",
    "sma20_slope_5",
    "close_range_high_20",
    "close_range_low_20",
    "close_range_high_60",
    "close_range_low_60",
    "range_position_20",
)


def _prepare_series(
    series: Mapping[date, float], as_of: date
) -> list[tuple[date, float]]:
    raw = [(d, c) for d, c in series.items() if d <= as_of and c > 0]
    raw.sort(key=lambda x: x[0])
    by_date: dict[date, float] = {}
    for d, c in raw:
        by_date[d] = c
    return sorted(by_date.items())


def _round_price(v: float | None) -> float | None:
    return None if v is None else round(v, _PRICE_DP)


def _round_pct(v: float | None) -> float | None:
    return None if v is None else round(v, _PCT_DP)


def _round_rsi(v: float | None) -> float | None:
    return None if v is None else round(v, _RSI_DP)


def _sma(values: Sequence[float], n: int) -> float | None:
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def _ema_full(values: Sequence[float], period: int) -> list[float | None]:
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


def _rsi_wilder(closes: Sequence[float], period: int = 14) -> float | None:
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
        if avg_gain > 0:
            return 100.0
        return None
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def _macd_components(closes: Sequence[float]) -> tuple[float | None, float | None, float | None]:
    if len(closes) < 34:
        return None, None, None
    ema12 = _ema_full(closes, 12)
    ema26 = _ema_full(closes, 26)
    macd_line: list[float | None] = []
    for e12, e26 in zip(ema12, ema26):
        if e12 is None or e26 is None:
            macd_line.append(None)
        else:
            macd_line.append(e12 - e26)
    macd_vals = [m for m in macd_line if m is not None]
    if len(macd_vals) < 9:
        return None, None, None
    k = 2.0 / 10.0
    signal_seed = sum(macd_vals[:9]) / 9
    signal_line: list[float | None] = [None] * len(macd_line)
    first_macd_idx = next(i for i, m in enumerate(macd_line) if m is not None)
    sig_start = first_macd_idx + 8
    if sig_start >= len(macd_line):
        return None, None, None
    signal_line[sig_start] = signal_seed
    prev = signal_seed
    for i in range(sig_start + 1, len(macd_line)):
        m = macd_line[i]
        if m is None:
            continue
        prev = (m - prev) * k + prev
        signal_line[i] = prev
    last = len(closes) - 1
    m = macd_line[last]
    s = signal_line[last]
    if m is None or s is None:
        return None, None, None
    return m, s, m - s


def _bollinger(closes: Sequence[float], period: int = 20, mult: float = 2.0) -> dict[str, float | None]:
    if len(closes) < period:
        return {
            "mid": None,
            "upper": None,
            "lower": None,
            "bandwidth": None,
            "percent_b": None,
        }
    window = closes[-period:]
    mid = sum(window) / period
    if len(window) < 2:
        std = 0.0
    else:
        std = statistics.pstdev(window)
    upper = mid + mult * std
    lower = mid - mult * std
    close = closes[-1]
    bandwidth = (upper - lower) / mid if mid else None
    percent_b = (close - lower) / (upper - lower) if upper != lower else None
    return {
        "mid": mid,
        "upper": upper,
        "lower": lower,
        "bandwidth": bandwidth,
        "percent_b": percent_b,
    }


def _log_returns(closes: Sequence[float]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(closes)):
        if closes[i] > 0 and closes[i - 1] > 0:
            out.append(math.log(closes[i] / closes[i - 1]))
    return out


def _rv(closes: Sequence[float], n: int) -> float | None:
    logrets = _log_returns(closes)
    if len(logrets) < n:
        return None
    return statistics.pstdev(logrets[-n:]) * math.sqrt(252.0) * 100.0


def _momentum_pct(closes: Sequence[float], n: int) -> float | None:
    if len(closes) <= n:
        return None
    old = closes[-1 - n]
    if old == 0:
        return None
    return 100.0 * (closes[-1] / old - 1.0)


def _sma20_slope_5(closes: Sequence[float]) -> float | None:
    sma_now = _sma(closes, 20)
    if len(closes) <= 5:
        return None
    sma_then = _sma(closes[:-5], 20)
    if sma_now is None or sma_then is None or sma_then == 0:
        return None
    return 100.0 * (sma_now / sma_then - 1.0)


def _breakout_flags(closes: Sequence[float]) -> tuple[bool, bool]:
    if len(closes) < 21:
        return False, False
    window = closes[-21:-1]
    prior_high = max(window)
    prior_low = min(window)
    last = closes[-1]
    prev = closes[-2]
    up = last > prior_high and prev <= prior_high
    down = last < prior_low and prev >= prior_low
    return up, down


def _failed_breakout_flags(closes: Sequence[float]) -> tuple[bool, bool]:
    n = len(closes)
    if n < 22:
        return False, False
    failed_up = False
    failed_down = False
    last = closes[-1]
    for k in range(1, 6):
        t = n - 1 - k
        if t < 20:
            continue
        window = closes[t - 20 : t]
        prior_high = max(window)
        prior_low = min(window)
        bar_close = closes[t]
        if bar_close > prior_high and last <= prior_high:
            failed_up = True
        if bar_close < prior_low and last >= prior_low:
            failed_down = True
    return failed_up, failed_down


def _swings(
    dates: Sequence[date], closes: Sequence[float], k: int = 2
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    n = len(closes)
    last_idx = n - 1
    highs: list[dict[str, Any]] = []
    lows: list[dict[str, Any]] = []
    for i in range(k, n - k):
        if i + k > last_idx:
            continue
        c = closes[i]
        if all(c > closes[i + d] for d in (-2, -1, 1, 2) if 0 <= i + d < n):
            highs.append(
                {
                    "price": c,
                    "observation_date": dates[i].isoformat(),
                    "confirmed_on": dates[i + k].isoformat(),
                }
            )
        if all(c < closes[i + d] for d in (-2, -1, 1, 2) if 0 <= i + d < n):
            lows.append(
                {
                    "price": c,
                    "observation_date": dates[i].isoformat(),
                    "confirmed_on": dates[i + k].isoformat(),
                }
            )
    return highs[-4:], lows[-4:]


def _trend_from_swings(
    highs: Sequence[dict[str, Any]], lows: Sequence[dict[str, Any]]
) -> str | None:
    if len(highs) < 2 or len(lows) < 2:
        return None
    h1, h2 = highs[-2], highs[-1]
    l1, l2 = lows[-2], lows[-1]
    hh = h2["price"] > h1["price"]
    hl = l2["price"] > l1["price"]
    lh = h2["price"] < h1["price"]
    ll = l2["price"] < l1["price"]
    if hh and hl:
        return "up"
    if lh and ll:
        return "down"
    return "range"


def _vol_regime(rv20: float | None, rv60: float | None) -> str | None:
    if rv20 is None or rv60 is None:
        return None
    if rv20 < 0.75 * rv60:
        return "compressed"
    if rv20 > 1.25 * rv60:
        return "expanded"
    return "neutral"


def _null_numeric_shell(null_reasons: dict[str, str]) -> dict[str, Any]:
    base: dict[str, Any] = {
        "close": None,
        "sma_20": None,
        "sma_50": None,
        "sma_200": None,
        "rsi_14": None,
        "macd": None,
        "macd_signal": None,
        "macd_histogram": None,
        "bollinger_mid": None,
        "bollinger_upper": None,
        "bollinger_lower": None,
        "bollinger_bandwidth": None,
        "bollinger_percent_b": None,
        "rv_5": None,
        "rv_10": None,
        "rv_20": None,
        "rv_60": None,
        "vol_regime": None,
        "ret_1d": None,
        "ret_5d": None,
        "ret_10d": None,
        "ret_20d": None,
        "sma20_slope_5": None,
        "close_range_high_20": None,
        "close_range_low_20": None,
        "close_range_high_60": None,
        "close_range_low_60": None,
        "range_position_20": None,
        "breakout_up_20": False,
        "breakout_down_20": False,
        "failed_breakout_up_20": False,
        "failed_breakout_down_20": False,
        "trend": None,
        "swing_highs": [],
        "swing_lows": [],
        "null_reasons": null_reasons,
    }
    return base


def pair_indicators(
    series: Mapping[date, float],
    *,
    as_of: date,
    clock: date | None = None,
    pair: str | None = None,
) -> dict:
    if clock is None:
        clock = as_of
    items = _prepare_series(series, as_of)
    sample_count = len(items)
    null_reasons: dict[str, str] = {}

    if not items:
        return {
            "schema_version": SCHEMA_VERSION,
            "pair": pair,
            "source": SOURCE_NAME,
            "observation_date": None,
            "sample_count": 0,
            "age_days": None,
            "status": "unavailable",
            "null_reasons": {"series": "empty_series"},
            **_null_numeric_shell({"series": "empty_series"}),
        }

    obs_date = items[-1][0]
    age_days = (clock - obs_date).days

    if age_days < 0:
        status = "unavailable"
        null_reasons["series"] = "observation_after_clock"
        return {
            "schema_version": SCHEMA_VERSION,
            "pair": pair,
            "source": SOURCE_NAME,
            "observation_date": obs_date.isoformat(),
            "sample_count": sample_count,
            "age_days": age_days,
            "status": status,
            **_null_numeric_shell(null_reasons),
        }

    if age_days > 21:
        status = "unavailable"
        null_reasons["series"] = "stale_beyond_mark"
        return {
            "schema_version": SCHEMA_VERSION,
            "pair": pair,
            "source": SOURCE_NAME,
            "observation_date": obs_date.isoformat(),
            "sample_count": sample_count,
            "age_days": age_days,
            "status": status,
            **_null_numeric_shell(null_reasons),
        }

    if age_days > 4:
        status = "stale"
    elif sample_count < 20:
        status = "insufficient_sample"
    else:
        status = "ok"

    dates = [d for d, _ in items]
    closes = [c for _, c in items]
    close = closes[-1]

    sma_20 = _sma(closes, 20)
    sma_50 = _sma(closes, 50)
    sma_200 = _sma(closes, 200)
    if sma_20 is None:
        null_reasons.setdefault("sma_20", "insufficient_sample")
    if sma_50 is None:
        null_reasons.setdefault("sma_50", "insufficient_sample")
    if sma_200 is None:
        null_reasons.setdefault("sma_200", "insufficient_sample")

    rsi = _rsi_wilder(closes, 14)
    if rsi is None:
        null_reasons.setdefault("rsi_14", "insufficient_sample")

    macd, macd_sig, macd_hist = _macd_components(closes)
    if macd is None:
        null_reasons.setdefault("macd", "insufficient_sample")

    bb = _bollinger(closes)
    if bb["mid"] is None:
        null_reasons.setdefault("bollinger", "insufficient_sample")

    rv5 = _rv(closes, 5)
    rv10 = _rv(closes, 10)
    rv20 = _rv(closes, 20)
    rv60 = _rv(closes, 60)
    for key, val in (("rv_5", rv5), ("rv_10", rv10), ("rv_20", rv20), ("rv_60", rv60)):
        if val is None:
            null_reasons.setdefault(key, "insufficient_sample")

    vol_regime = _vol_regime(rv20, rv60)
    if vol_regime is None:
        null_reasons.setdefault("vol_regime", "insufficient_sample")

    ret_1d = _momentum_pct(closes, 1)
    ret_5d = _momentum_pct(closes, 5)
    ret_10d = _momentum_pct(closes, 10)
    ret_20d = _momentum_pct(closes, 20)

    slope = _sma20_slope_5(closes)
    if slope is None:
        null_reasons.setdefault("sma20_slope_5", "insufficient_sample")

    cr_h20 = max(closes[-20:]) if len(closes) >= 20 else None
    cr_l20 = min(closes[-20:]) if len(closes) >= 20 else None
    cr_h60 = max(closes[-60:]) if len(closes) >= 60 else None
    cr_l60 = min(closes[-60:]) if len(closes) >= 60 else None
    range_pos = None
    if cr_h20 is not None and cr_l20 is not None and cr_h20 != cr_l20:
        range_pos = (close - cr_l20) / (cr_h20 - cr_l20)
    if cr_h20 is None:
        null_reasons.setdefault("close_range_20", "insufficient_sample")

    breakout_up, breakout_down = _breakout_flags(closes)
    failed_up, failed_down = _failed_breakout_flags(closes)

    all_highs, all_lows = _swings(dates, closes, k=2)
    confirmed_highs = [h for h in all_highs]
    confirmed_lows = [l for l in all_lows]
    trend = _trend_from_swings(confirmed_highs, confirmed_lows)
    if trend is None:
        null_reasons.setdefault("trend", "insufficient_sample")

    return {
        "schema_version": SCHEMA_VERSION,
        "pair": pair,
        "source": SOURCE_NAME,
        "observation_date": obs_date.isoformat(),
        "sample_count": sample_count,
        "age_days": age_days,
        "status": status,
        "close": _round_price(close),
        "sma_20": _round_price(sma_20),
        "sma_50": _round_price(sma_50),
        "sma_200": _round_price(sma_200),
        "rsi_14": _round_rsi(rsi),
        "macd": _round_price(macd),
        "macd_signal": _round_price(macd_sig),
        "macd_histogram": _round_price(macd_hist),
        "bollinger_mid": _round_price(bb["mid"]),
        "bollinger_upper": _round_price(bb["upper"]),
        "bollinger_lower": _round_price(bb["lower"]),
        "bollinger_bandwidth": _round_pct(bb["bandwidth"]),
        "bollinger_percent_b": _round_pct(bb["percent_b"]),
        "rv_5": _round_pct(rv5),
        "rv_10": _round_pct(rv10),
        "rv_20": _round_pct(rv20),
        "rv_60": _round_pct(rv60),
        "vol_regime": vol_regime,
        "ret_1d": _round_pct(ret_1d),
        "ret_5d": _round_pct(ret_5d),
        "ret_10d": _round_pct(ret_10d),
        "ret_20d": _round_pct(ret_20d),
        "sma20_slope_5": _round_pct(slope),
        "close_range_high_20": _round_price(cr_h20),
        "close_range_low_20": _round_price(cr_l20),
        "close_range_high_60": _round_price(cr_h60),
        "close_range_low_60": _round_price(cr_l60),
        "range_position_20": _round_pct(range_pos),
        "breakout_up_20": breakout_up,
        "breakout_down_20": breakout_down,
        "failed_breakout_up_20": failed_up,
        "failed_breakout_down_20": failed_down,
        "trend": trend,
        "swing_highs": [
            {
                "price": _round_price(h["price"]),
                "observation_date": h["observation_date"],
                "confirmed_on": h["confirmed_on"],
            }
            for h in confirmed_highs
        ],
        "swing_lows": [
            {
                "price": _round_price(l["price"]),
                "observation_date": l["observation_date"],
                "confirmed_on": l["confirmed_on"],
            }
            for l in confirmed_lows
        ],
        "null_reasons": null_reasons,
    }
