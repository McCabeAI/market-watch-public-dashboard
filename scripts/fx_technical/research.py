from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from scripts.fx_technical.indicators import SOURCE_NAME, SCHEMA_VERSION, pair_indicators

_FUTURES_ROLL_KEYS = frozenset({"GOLD", "WTI", "BRENT", "COPPER"})
_DEFAULT_CROSS_NOTE = (
    "Daily source observation; publication and market close times differ."
)
_ROLL_APPEND = " Continuous futures history can include roll discontinuities."

_SOURCE_NOTE = (
    "ECB reference rates are information/reference fixings, not executable prices. "
    "Indicators use same-fixing closes only."
)


def unavailable_technical_research(reason: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "FX_TECHNICAL_RESEARCH",
        "status": "unavailable",
        "vetoes_unrelated_trades": False,
        "reason": reason,
        "as_of": None,
        "clock": None,
        "horizons": {"primary": ["5D", "20D"], "context": ["1D", "10D"]},
        "source": {
            "name": SOURCE_NAME,
            "fx_source": "ecb_euro_reference_crosses",
            "observation_date": None,
            "note": _SOURCE_NOTE,
        },
        "method": _method_block(),
        "market_status": {
            "pairs_computed": 0,
            "pairs_ok": 0,
            "pairs_stale": 0,
            "pairs_insufficient": 0,
            "pairs_unavailable": 0,
            "trend_counts": {
                "up": 0,
                "down": 0,
                "range": 0,
                "insufficient": 0,
            },
            "volatility_regimes": {
                "compressed": 0,
                "neutral": 0,
                "expanded": 0,
                "insufficient": 0,
            },
            "disagreement_count": 0,
        },
        "setups": [],
        "context": {
            "status": "unavailable",
            "reason": "no rates or cross-asset observations were supplied",
            "supportive": [],
            "examined_not_supportive": [],
        },
        "pairs": {},
        "pair_count": 0,
    }


def _method_block() -> dict:
    return {
        "price": "close_only",
        "session": "ecb_fixing_observation",
        "sma": [20, 50, 200],
        "rsi": {"period": 14, "method": "wilder"},
        "macd": {"fast": 12, "slow": 26, "signal": 9, "seed": "sma"},
        "bollinger": {"period": 20, "stdev": 2, "stdev_kind": "population"},
        "realized_vol": "close_to_close_log_pstdev_annualized_252",
        "range": "closing_price_min_max",
        "swing": "close_fractal_k2_confirmed",
        "lookahead": False,
        "excluded": [
            "ohlc",
            "atr",
            "candlestick",
            "intraday",
            "synthetic_candles",
            "model_probabilities",
        ],
    }


def _family_status(pair_rows: dict[str, dict]) -> str:
    if not pair_rows:
        return "unavailable"
    statuses = [r["status"] for r in pair_rows.values()]
    if all(s == "unavailable" for s in statuses):
        return "unavailable"
    if all(s == "ok" for s in statuses):
        return "ok"
    if any(s == "ok" for s in statuses):
        return "partial"
    if any(s == "stale" for s in statuses):
        return "stale"
    return "partial"


def _is_disagreement(row: dict) -> tuple[bool, str | None]:
    trend = row.get("trend")
    macd_hist = row.get("macd_histogram")
    rsi = row.get("rsi_14")
    if trend == "up" and macd_hist is not None and macd_hist < 0 and rsi is not None and rsi < 50:
        return True, "uptrend with negative MACD histogram and RSI below 50"
    if trend == "down" and macd_hist is not None and macd_hist > 0 and rsi is not None and rsi > 50:
        return True, "downtrend with positive MACD histogram and RSI above 50"
    if trend == "up" and rsi is not None and rsi >= 70:
        return (
            True,
            "uptrend with elevated RSI; an elevated RSI is not by itself a bearish signal",
        )
    if trend == "down" and rsi is not None and rsi <= 30:
        return (
            True,
            "downtrend with depressed RSI; a depressed RSI is not by itself a bullish signal",
        )
    return False, None


def _classify_pair(row: dict) -> list[dict]:
    if row["status"] not in ("ok", "stale") or row.get("close") is None:
        return []

    pair = row["pair"] or ""
    trend = row.get("trend")
    close = row["close"]
    sma20 = row.get("sma_20")
    sma50 = row.get("sma_50")
    macd_hist = row.get("macd_histogram")
    b_up = row.get("breakout_up_20")
    b_down = row.get("breakout_down_20")
    f_up = row.get("failed_breakout_up_20")
    f_down = row.get("failed_breakout_down_20")
    vol = row.get("vol_regime")
    ret_20 = row.get("ret_20d") or 0

    is_dag, dag_conflict = _is_disagreement(row)
    fresh_breakout = b_up or b_down

    chosen: dict | None = None

    if is_dag:
        chosen = {
            "pair": pair,
            "class": "disagreement",
            "side": None,
            "horizon_primary": "5D",
            "score": 4,
            "ret_20": ret_20,
            "conflict": dag_conflict,
            "read": f"{pair} shows mixed close-only signals across trend, momentum, and oscillators.",
        }
    elif fresh_breakout:
        side = "long_base" if b_up else "short_base"
        chosen = {
            "pair": pair,
            "class": "breakout",
            "side": side,
            "horizon_primary": "5D",
            "score": 5,
            "ret_20": ret_20,
            "conflict": None,
            "read": f"{pair} closed beyond the prior 20-observation range on the latest fixing.",
        }
    elif f_up or f_down:
        chosen = {
            "pair": pair,
            "class": "failed_breakout",
            "side": None,
            "horizon_primary": "5D",
            "score": 5,
            "ret_20": ret_20,
            "conflict": None,
            "read": (
                f"{pair} reversed back inside a range after an earlier range break "
                "within five observations."
            ),
        }
    else:
        options: list[dict] = []
        tc_ok = False
        if (
            trend in ("up", "down")
            and sma20 is not None
            and sma50 is not None
            and macd_hist is not None
        ):
            if trend == "up" and close > sma20 > sma50 and macd_hist > 0:
                tc_ok = True
            if trend == "down" and close < sma20 < sma50 and macd_hist < 0:
                tc_ok = True
        if tc_ok:
            side = "long_base" if trend == "up" else "short_base"
            options.append(
                {
                    "pair": pair,
                    "class": "trend_continuation",
                    "side": side,
                    "horizon_primary": "20D",
                    "score": 3,
                    "ret_20": ret_20,
                    "conflict": None,
                    "read": (
                        f"{pair} close structure aligns with the prevailing swing-defined "
                        "trend and moving-average stack."
                    ),
                }
            )
        if trend == "range":
            options.append(
                {
                    "pair": pair,
                    "class": "range",
                    "side": None,
                    "horizon_primary": "20D",
                    "score": 2,
                    "ret_20": ret_20,
                    "conflict": None,
                    "read": f"{pair} swing structure is range-bound without a fresh range break.",
                }
            )
        if vol == "expanded" and trend in (None, "range"):
            options.append(
                {
                    "pair": pair,
                    "class": "no_trade",
                    "side": None,
                    "horizon_primary": "5D",
                    "score": 4,
                    "ret_20": ret_20,
                    "conflict": None,
                    "read": (
                        f"{pair} realized volatility is expanded versus its longer horizon "
                        "while trend structure is unclear."
                    ),
                }
            )
        if options:
            chosen = max(options, key=lambda c: c["score"])

    if chosen is None:
        return []

    return [
        {
            "pair": chosen["pair"],
            "class": chosen["class"],
            "side": chosen["side"],
            "horizon_primary": chosen["horizon_primary"],
            "as_of": row.get("observation_date"),
            "close": close,
            "status": row["status"],
            "conflict": chosen["conflict"],
            "read": chosen["read"],
            "trade_recommendation": None,
            "_score": chosen["score"],
            "_ret_20": chosen["ret_20"],
        }
    ]


def _sort_key(setup: dict) -> tuple:
    return (-setup["_score"], -abs(setup.get("_ret_20") or 0), setup["pair"])


def _select_setups(all_candidates: list[dict]) -> list[dict]:
    conflict_classes = {"disagreement", "no_trade"}
    conflict = [c for c in all_candidates if c["class"] in conflict_classes]
    primary_pool = [c for c in all_candidates if c["class"] not in conflict_classes]
    primary_pool.sort(key=_sort_key)
    conflict.sort(key=_sort_key)

    selected = primary_pool[:8]
    selected_pairs = {s["pair"] for s in selected}
    extra = [d for d in conflict if d["pair"] not in selected_pairs][:2]
    selected.extend(extra)
    selected.sort(key=_sort_key)
    if len(selected) > 10:
        selected = selected[:10]

    for s in selected:
        s.pop("_score", None)
        s.pop("_ret_20", None)
    return selected


def _prepare_cross_series(
    series: Mapping[date, float], as_of: date
) -> dict[date, float]:
    raw = [(d, c) for d, c in series.items() if d <= as_of and c > 0]
    raw.sort(key=lambda x: x[0])
    by_date: dict[date, float] = {}
    for d, c in raw:
        by_date[d] = c
    return by_date


def _prepare_rate_series(series: Mapping[date, float], as_of: date) -> dict[date, float]:
    by_date: dict[date, float] = {}
    for d, value in series.items():
        if d > as_of or isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        number = float(value)
        if not math.isfinite(number):
            continue
        by_date[d] = number
    return by_date


def _rates_context(
    rate_series: Mapping[str, Mapping[date, float]] | None, as_of: date
) -> dict | None:
    note = "Sovereign yield closes and ECB fixing observations are not synchronous."
    if not rate_series or "US10Y" not in rate_series:
        return None
    us10 = _prepare_rate_series(rate_series["US10Y"], as_of)
    dates_sorted = sorted(us10.keys())
    # 20 sessions back needs 21 observations. No forward fill.
    if len(dates_sorted) < 21:
        return {
            "instrument": "US10Y",
            "status": "insufficient_sample",
            "change_20_obs_bp": None,
            "publication_lag_note": note,
        }
    change_bp = (us10[dates_sorted[-1]] - us10[dates_sorted[-21]]) * 100.0
    return {
        "instrument": "US10Y",
        "status": "ok",
        "change_20_obs_bp": round(change_bp, 4),
        "observation_date": dates_sorted[-1].isoformat(),
        "publication_lag_note": note,
    }


def _fx_anchor_pair(pairs: Mapping[str, Mapping[date, float]]) -> str | None:
    if "EURUSD" in pairs:
        return "EURUSD"
    usd_quotes = sorted(p for p in pairs if p.endswith("USD"))
    return usd_quotes[0] if usd_quotes else None


def _paired_log_returns(
    fx: dict[date, float], other: dict[date, float]
) -> tuple[list[float], list[float]]:
    common = sorted(set(fx.keys()) & set(other.keys()))
    x_rets: list[float] = []
    y_rets: list[float] = []
    for i in range(1, len(common)):
        d0, d1 = common[i - 1], common[i]
        if fx[d1] > 0 and fx[d0] > 0 and other[d1] > 0 and other[d0] > 0:
            x_rets.append(math.log(fx[d1] / fx[d0]))
            y_rets.append(math.log(other[d1] / other[d0]))
    return x_rets, y_rets


def _pearson(x: Sequence[float], y: Sequence[float]) -> float | None:
    if len(x) != len(y) or len(x) < 2:
        return None
    mx = statistics.fmean(x)
    my = statistics.fmean(y)
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y)) / len(x)
    sx = statistics.pstdev(x)
    sy = statistics.pstdev(y)
    if sx == 0 or sy == 0:
        return None
    return cov / (sx * sy)


def _cross_asset_context(
    pairs: Mapping[str, Mapping[date, float]],
    cross_asset_series: Mapping[str, Mapping[date, float]] | None,
    cross_asset_meta: Mapping[str, Mapping] | None,
    as_of: date,
) -> dict:
    if not cross_asset_series:
        return {}
    meta = cross_asset_meta or {}
    anchor = _fx_anchor_pair(pairs)
    fx_series = _prepare_cross_series(pairs[anchor], as_of) if anchor else {}

    supportive: list[dict] = []
    examined: list[dict] = []

    for key in sorted(cross_asset_series.keys()):
        m = meta.get(key, {})
        st = m.get("status")
        if st not in ("ok", "stale"):
            examined.append(
                {
                    "key": key,
                    "reason": "cross-asset source status not ok or stale",
                }
            )
            if len(examined) >= 5:
                continue
            continue
        series = _prepare_cross_series(cross_asset_series[key], as_of)
        if len(series) < 20:
            examined.append(
                {
                    "key": key,
                    "reason": "insufficient positive closes on or before as_of",
                }
            )
            if len(examined) >= 5:
                continue
            continue
        dates_sorted = sorted(series.keys())
        d_now = dates_sorted[-1]
        d_then = dates_sorted[-20]
        pct_chg = 100.0 * (series[d_now] / series[d_then] - 1.0)
        note = m.get("note") or _DEFAULT_CROSS_NOTE
        if key in _FUTURES_ROLL_KEYS and "roll" not in note.lower():
            note = note.rstrip() + "." + _ROLL_APPEND

        entry = {
            "key": key,
            "label": m.get("label", key),
            "status": st,
            "note": note,
            "as_of": m.get("as_of", d_now.isoformat()),
            "source": m.get("source"),
            "change_20_obs_pct": round(pct_chg, 4),
        }

        corr = None
        if anchor and fx_series:
            x_rets, y_rets = _paired_log_returns(fx_series, series)
            if len(x_rets) >= 20:
                corr = _pearson(x_rets, y_rets)
                entry["correlation_with_anchor"] = (
                    round(corr, 4) if corr is not None else None
                )

        if corr is not None and abs(corr) >= 0.25:
            if len(supportive) < 5:
                supportive.append(entry)
        else:
            if len(examined) < 5:
                reason = (
                    "aligned observations do not support a stable context link"
                    if corr is not None
                    else "insufficient overlapping log-return sample"
                )
                examined.append({**entry, "reason": reason})

    return {"supportive": supportive, "examined_not_supportive": examined}


def build_technical_research(
    pairs: Mapping[str, Mapping[date, float]],
    *,
    as_of: date,
    clock: date | None = None,
    source: Mapping | None = None,
    cross_asset_series: Mapping | None = None,
    cross_asset_meta: Mapping | None = None,
    rate_series: Mapping | None = None,
) -> dict:
    if clock is None:
        clock = as_of

    pair_rows: dict[str, dict] = {}
    for name in sorted(pairs.keys()):
        row = pair_indicators(pairs[name], as_of=as_of, clock=clock, pair=name)
        pair_rows[name] = row

    obs_dates = [
        date.fromisoformat(r["observation_date"])
        for r in pair_rows.values()
        if r.get("observation_date")
    ]
    max_obs = max(obs_dates).isoformat() if obs_dates else None

    market_status = {
        "pairs_computed": len(pair_rows),
        "pairs_ok": sum(1 for r in pair_rows.values() if r["status"] == "ok"),
        "pairs_stale": sum(1 for r in pair_rows.values() if r["status"] == "stale"),
        "pairs_insufficient": sum(
            1 for r in pair_rows.values() if r["status"] == "insufficient_sample"
        ),
        "pairs_unavailable": sum(
            1 for r in pair_rows.values() if r["status"] == "unavailable"
        ),
        "trend_counts": {"up": 0, "down": 0, "range": 0, "insufficient": 0},
        "volatility_regimes": {
            "compressed": 0,
            "neutral": 0,
            "expanded": 0,
            "insufficient": 0,
        },
        "disagreement_count": 0,
    }

    for r in pair_rows.values():
        tr = r.get("trend")
        if tr in ("up", "down", "range"):
            market_status["trend_counts"][tr] += 1
        else:
            market_status["trend_counts"]["insufficient"] += 1
        vr = r.get("vol_regime")
        if vr in ("compressed", "neutral", "expanded"):
            market_status["volatility_regimes"][vr] += 1
        else:
            market_status["volatility_regimes"]["insufficient"] += 1
        is_dag, _ = _is_disagreement(r)
        if is_dag:
            market_status["disagreement_count"] += 1

    all_candidates: list[dict] = []
    for r in pair_rows.values():
        all_candidates.extend(_classify_pair(r))
    setups = _select_setups(all_candidates)

    rates_ctx = _rates_context(rate_series, as_of)
    cross_ctx = _cross_asset_context(
        pairs, cross_asset_series, cross_asset_meta, as_of
    )

    if rates_ctx is None and not cross_ctx:
        context = {
            "status": "unavailable",
            "reason": "no rates or cross-asset observations were supplied",
            "supportive": [],
            "examined_not_supportive": [],
        }
    else:
        context: dict[str, Any] = {
            "status": "ok",
            "supportive": cross_ctx.get("supportive", []),
            "examined_not_supportive": cross_ctx.get("examined_not_supportive", []),
        }
        if rates_ctx:
            context["rates"] = rates_ctx
        if not context["supportive"] and not context.get("rates"):
            if cross_ctx:
                context["status"] = "partial"
            else:
                context["status"] = "unavailable"
                context["reason"] = (
                    "no rates or cross-asset observations were supplied"
                )

    source_block = {
        "name": SOURCE_NAME,
        "fx_source": "ecb_euro_reference_crosses",
        "observation_date": max_obs,
        "note": _SOURCE_NOTE,
    }
    if source:
        source_block.update({k: v for k, v in source.items() if k not in source_block})

    return {
        "schema_version": SCHEMA_VERSION,
        "type": "FX_TECHNICAL_RESEARCH",
        "status": _family_status(pair_rows),
        "vetoes_unrelated_trades": False,
        "as_of": as_of.isoformat(),
        "clock": clock.isoformat(),
        "horizons": {"primary": ["5D", "20D"], "context": ["1D", "10D"]},
        "source": source_block,
        "method": _method_block(),
        "market_status": market_status,
        "setups": setups,
        "context": context,
        "pairs": pair_rows,
        "pair_count": len(pairs),
    }
