#!/usr/bin/env python3
"""Recompute FX and energy facts from the frozen 2026-11-05 evidence snapshot.

Reads only:
  data/overnight/runs/overnight-20261105/reviews/review-001/evidence_snapshot.json
  data/trading/pm/chatgpt/research/hypotheses/hyp-chatgpt-cadnok-energy-reversal-20261104.json
  data/pm/books/latest.json  (pms.chatgpt only)

Writes fx_facts.json beside this script. No network. No other seats' memory.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
OUT_DIR = Path(__file__).resolve().parent
SNAPSHOT = (
    REPO
    / "data/overnight/runs/overnight-20261105/reviews/review-001/evidence_snapshot.json"
)
HYPOTHESIS = (
    REPO
    / "data/trading/pm/chatgpt/research/hypotheses/hyp-chatgpt-cadnok-energy-reversal-20261104.json"
)
BOOK = REPO / "data/pm/books/latest.json"

INSTRUCTED_SHA256 = "0bc766c948f4f88f81ea6e28bc00ad0a67e09ee5605b23b47cb69b039f415b10"
FREEZE_AS_OF = "2026-11-05T04:53:53.458055-05:00"
MARKET_STATE_AS_OF = "2026-11-05T10:17:36Z"

# Liquid G10 USD pairs plus the crosses named in the review brief.
TABLE_IDS = [
    "WTI",
    "BRENT",
    "EURUSD",
    "GBPUSD",
    "AUDUSD",
    "NZDUSD",
    "USDJPY",
    "USDCHF",
    "USDCAD",
    "USDNOK",
    "USDSEK",
    "CADNOK",
    "EURNOK",
    "EURCAD",
    "AUDCAD",
    "EURJPY",
    "NOKSEK",
    "AUDNZD",
]

CONTEXT_IDS = [
    "SP500",
    "VIX",
    "NASDAQ",
    "DOW",
    "RUSSELL",
    "GOLD",
    "BROAD_USD",
    "COPPER",
    "HY_OAS",
    "US_2Y",
    "US_5Y",
    "US_10Y",
    "US_30Y",
    "US_BE10",
    "US_REAL10",
    "EA_2Y",
    "EA_10Y",
    "JP_2Y",
    "JP_10Y",
    "CA_2Y",
    "CA_10Y",
    "AU_2Y",
    "AU_10Y",
    "NZ_2Y",
    "NZ_10Y",
]

# USD quote direction. base/quote follows market convention in the pair id.
USD_LEGS = {
    "EURUSD": ("EUR", "USD"),
    "GBPUSD": ("GBP", "USD"),
    "AUDUSD": ("AUD", "USD"),
    "NZDUSD": ("NZD", "USD"),
    "USDJPY": ("USD", "JPY"),
    "USDCHF": ("USD", "CHF"),
    "USDCAD": ("USD", "CAD"),
    "USDNOK": ("USD", "NOK"),
    "USDSEK": ("USD", "SEK"),
}

# (left, op, right) on log returns. op is "plus" or "minus".
CROSS_SPEC = {
    "CADNOK": ("USDNOK", "minus", "USDCAD"),  # USDNOK / USDCAD
    "EURNOK": ("EURUSD", "plus", "USDNOK"),
    "EURCAD": ("EURUSD", "plus", "USDCAD"),
    "AUDCAD": ("AUDUSD", "plus", "USDCAD"),
    "EURJPY": ("EURUSD", "plus", "USDJPY"),
    "NOKSEK": ("USDSEK", "minus", "USDNOK"),  # USDSEK / USDNOK
    "AUDNZD": ("AUDUSD", "minus", "NZDUSD"),  # AUDUSD / NZDUSD
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_dump(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def rnum(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def pct(new: float, old: float) -> float:
    return (new / old - 1.0) * 100.0


def logpct(new: float, old: float) -> float:
    return math.log(new / old) * 100.0


def parse_date(text: str) -> datetime:
    return datetime.fromisoformat(text)


def business_gap_missing(prev: str, last: str) -> bool:
    """True when the last step skips a weekday. Weekends alone are not missing."""
    a = parse_date(prev).date()
    b = parse_date(last).date()
    day = a + timedelta(days=1)
    while day < b:
        if day.weekday() < 5:
            return True
        day += timedelta(days=1)
    return False


def on_or_before(history: list, last_date: str, days: int) -> dict | None:
    target = (parse_date(last_date) - timedelta(days=days)).date().isoformat()
    cand = [row for row in history if row[0] <= target]
    if not cand:
        return None
    anchor_date, anchor_value = cand[-1]
    last_value = history[-1][1]
    return {
        "target_date": target,
        "anchor_date": anchor_date,
        "anchor_value": rnum(anchor_value, 8),
        "calendar_days_anchor_to_last": (parse_date(last_date) - parse_date(anchor_date)).days,
        "days_target_before_anchor": (parse_date(target) - parse_date(anchor_date)).days,
        "simple_pct": rnum(pct(last_value, anchor_value), 6),
        "log_pct": rnum(logpct(last_value, anchor_value), 6),
        "level_change": rnum(last_value - anchor_value, 6),
    }


def obs_back(history: list, steps: int) -> dict | None:
    if len(history) < steps + 1:
        return None
    anchor_date, anchor_value = history[-(steps + 1)]
    last_date, last_value = history[-1]
    return {
        "steps": steps,
        "start_date": anchor_date,
        "end_date": last_date,
        "start_value": rnum(anchor_value, 8),
        "end_value": rnum(last_value, 8),
        "simple_pct": rnum(pct(last_value, anchor_value), 6),
        "log_pct": rnum(logpct(last_value, anchor_value), 6),
        "level_change": rnum(last_value - anchor_value, 6),
        "sign": "positive" if last_value > anchor_value else "negative" if last_value < anchor_value else "flat",
    }


def rank_block(values: list[float], score: float) -> dict:
    n = len(values)
    below = sum(v < score for v in values)
    equal = sum(v == score for v in values)
    at_or_below = below + equal
    return {
        "n": n,
        "count_below": below,
        "count_equal": equal,
        "count_at_or_below": at_or_below,
        "weak_inclusive_pct": rnum(100.0 * at_or_below / n, 6),
        "strict_below_pct": rnum(100.0 * below / n, 6),
        "midrank_pct": rnum(100.0 * (below + 0.5 * equal) / n, 6),
        "min": rnum(min(values), 8),
        "median": rnum(statistics.median(values), 8),
        "max": rnum(max(values), 8),
        "range_position": rnum((score - min(values)) / (max(values) - min(values)), 6)
        if max(values) != min(values)
        else None,
    }


def stored_z(values: list[float], score: float) -> dict:
    """Z of score versus the other stored points, and versus the full stored sample."""
    prior = values[:-1]
    mu_p = statistics.fmean(prior)
    sd_p = statistics.stdev(prior)
    mu_a = statistics.fmean(values)
    sd_a = statistics.pstdev(values)
    return {
        "z_versus_prior_points_sample_stdev": rnum((score - mu_p) / sd_p, 6),
        "z_versus_full_sample_population_stdev": rnum((score - mu_a) / sd_a, 6),
        "prior_mean": rnum(mu_p, 8),
        "prior_sample_stdev": rnum(sd_p, 8),
    }


def daily_log_returns(history: list) -> list[float]:
    out = []
    for (d0, v0), (d1, v1) in zip(history, history[1:]):
        out.append(logpct(v1, v0))
    return out


def realized_vol(history: list, window: int = 20) -> dict | None:
    rets = daily_log_returns(history)
    if len(rets) < window:
        return None
    sample = rets[-window:]
    # sample stdev of daily log percent, then the usual sqrt(252) annualization.
    daily = statistics.stdev(sample)
    last = rets[-1]
    return {
        "window_observations": window,
        "daily_log_pct_stdev": rnum(daily, 6),
        "annualized_pct_sqrt252": rnum(daily * math.sqrt(252), 6),
        "annualization": "sample stdev of daily log percent times sqrt(252); convention, not a snapshot field",
        "last_log_pct": rnum(last, 6),
        "last_move_z_versus_window": rnum(last / daily, 6) if daily else None,
    }


def move_z_in_stored_returns(history: list) -> dict | None:
    rets = daily_log_returns(history)
    if len(rets) < 3:
        return None
    last = rets[-1]
    prior = rets[:-1]
    sd = statistics.stdev(prior)
    return {
        "n_stored_log_returns": len(rets),
        "last_log_pct": rnum(last, 6),
        "z_versus_prior_stored_log_returns": rnum((last - statistics.fmean(prior)) / sd, 6),
    }


def value_on(history: list, date: str) -> float | None:
    for d, v in history:
        if d == date:
            return v
    return None


def step_between(history: list, start: str, end: str) -> dict | None:
    a = value_on(history, start)
    b = value_on(history, end)
    if a is None or b is None:
        return {
            "start_date": start,
            "end_date": end,
            "available": False,
            "reason": "one or both dates are absent; not treated as a zero move",
        }
    return {
        "start_date": start,
        "end_date": end,
        "available": True,
        "start_value": rnum(a, 8),
        "end_value": rnum(b, 8),
        "simple_pct": rnum(pct(b, a), 6),
        "log_pct": rnum(logpct(b, a), 6),
        "level_change": rnum(b - a, 6),
    }


def series_record(s: dict, fx_pair: dict | None) -> dict:
    history = s["history"]
    dates = [row[0] for row in history]
    values = [row[1] for row in history]
    if dates != sorted(dates):
        raise SystemExit(f"{s['id']} history is not sorted")
    if len(dates) != len(set(dates)):
        raise SystemExit(f"{s['id']} history has duplicate dates")
    last_date, last_value = history[-1]
    prev_date, prev_value = history[-2]
    last_step = {
        "start_date": prev_date,
        "end_date": last_date,
        "start_value": rnum(prev_value, 8),
        "end_value": rnum(last_value, 8),
        "simple_pct": rnum(pct(last_value, prev_value), 6),
        "log_pct": rnum(logpct(last_value, prev_value), 6),
        "level_change": rnum(last_value - prev_value, 6),
        "missing_weekday_between": business_gap_missing(prev_date, last_date),
    }
    full_rank = rank_block(values, last_value)
    prior_values = values[:-1]
    prior_rank_of_previous_close = rank_block(prior_values, prev_value)
    full_z = stored_z(values, last_value)
    snap_pct = s.get("percentile")
    snap_z = s.get("z")
    weak = full_rank["weak_inclusive_pct"]
    rec = {
        "id": s["id"],
        "label": s.get("label"),
        "unit": s.get("unit"),
        "category": s.get("category"),
        "status": s.get("status"),
        "note": s.get("note"),
        "series_as_of": s.get("as_of"),
        "n_field": s.get("n"),
        "history_len": len(history),
        "n_field_equals_history_len": s.get("n") == len(history),
        "first_date": dates[0],
        "last_date": last_date,
        "previous_date": prev_date,
        "last_value": rnum(last_value, 8),
        "previous_value": rnum(prev_value, 8),
        "has_2026_11_04": "2026-11-04" in dates,
        "last_step": last_step,
        "from_5_stored_observations_back": obs_back(history, 5),
        "from_21_stored_observations": obs_back(history, 21),
        "from_63_stored_observations": obs_back(history, 63),
        "calendar_30d_on_or_before": on_or_before(history, last_date, 30),
        "calendar_91d_on_or_before": on_or_before(history, last_date, 91),
        "from_first_stored": {
            "start_date": dates[0],
            "end_date": last_date,
            "start_value": rnum(values[0], 8),
            "simple_pct": rnum(pct(last_value, values[0]), 6),
            "log_pct": rnum(logpct(last_value, values[0]), 6),
            "level_change": rnum(last_value - values[0], 6),
        },
        "path_points": {
            date: step_between(history, date, date) and rnum(value_on(history, date), 8)
            for date in ("2026-10-30", "2026-11-02", "2026-11-03", "2026-11-04")
        },
        "path_changes": {
            "2026-10-30_to_2026-11-02": step_between(history, "2026-10-30", "2026-11-02"),
            "2026-11-02_to_2026-11-03": step_between(history, "2026-11-02", "2026-11-03"),
            "2026-11-03_to_2026-11-04": step_between(history, "2026-11-03", "2026-11-04"),
            "2026-10-30_to_2026-11-03": step_between(history, "2026-10-30", "2026-11-03"),
            "2026-10-30_to_2026-11-04": step_between(history, "2026-10-30", "2026-11-04"),
        },
        "stored_history_rank_of_last": full_rank,
        "stored_history_z": full_z,
        "rank_of_previous_close_within_history_through_previous": prior_rank_of_previous_close,
        "snapshot_series_percentile": None if snap_pct is None else rnum(snap_pct, 6),
        "snapshot_series_z": None if snap_z is None else rnum(snap_z, 6),
        "snapshot_percentile_matches_stored_weak_inclusive": (
            None
            if snap_pct is None
            else abs(snap_pct - weak) < 0.05
        ),
        "snapshot_z_matches_stored_prior_z": (
            None
            if snap_z is None
            else abs(snap_z - full_z["z_versus_prior_points_sample_stdev"]) < 0.05
        ),
        "snapshot_moves": s.get("moves"),
        "stored_return_z": move_z_in_stored_returns(history),
        "recomputed_rv_20obs": realized_vol(history, 20),
    }
    # Drop the awkward path_points construction if a date is missing: keep nulls.
    rec["path_levels"] = {
        date: None if value_on(history, date) is None else rnum(value_on(history, date), 8)
        for date in ("2026-10-30", "2026-11-02", "2026-11-03", "2026-11-04")
    }
    del rec["path_points"]
    if fx_pair is not None:
        ret_1d = fx_pair.get("ret_1d")
        ret_5d = fx_pair.get("ret_5d")
        ret_1m = fx_pair.get("ret_1m")
        ret_3m = fx_pair.get("ret_3m")
        rec["snapshot_fx_pair"] = {
            "source": "families.market_state.data.fx.pairs; not recomputed from the 126-row history",
            "as_of": fx_pair.get("as_of"),
            "spot": rnum(fx_pair.get("spot"), 8),
            "pctile_1y": rnum(fx_pair.get("pctile_1y"), 6),
            "pctile_5y": rnum(fx_pair.get("pctile_5y"), 6),
            "z_1y": rnum(fx_pair.get("z_1y"), 6),
            "z_5y": rnum(fx_pair.get("z_5y"), 6),
            "ret_1d": rnum(ret_1d, 6),
            "ret_5d": rnum(ret_5d, 6),
            "ret_1m": rnum(ret_1m, 6),
            "ret_3m": rnum(ret_3m, 6),
            "rv_20d": rnum(fx_pair.get("rv_20d"), 6),
            "rv_60d": rnum(fx_pair.get("rv_60d"), 6),
            "scale_note": "pctile_1y and pctile_5y are already on a 0-100 scale. A reading of 0.357 is the 0.357th percentile, not the 35.7th.",
        }
        rec["snapshot_return_matches_recomputed_simple"] = {
            "ret_1d_minus_last_step": None
            if ret_1d is None
            else rnum(ret_1d - last_step["simple_pct"], 8),
            "ret_5d_minus_5obs": None
            if ret_5d is None or rec["from_5_stored_observations_back"] is None
            else rnum(ret_5d - rec["from_5_stored_observations_back"]["simple_pct"], 8),
            "ret_1m_minus_21obs": None
            if ret_1m is None or rec["from_21_stored_observations"] is None
            else rnum(ret_1m - rec["from_21_stored_observations"]["simple_pct"], 8),
            "ret_3m_minus_63obs": None
            if ret_3m is None or rec["from_63_stored_observations"] is None
            else rnum(ret_3m - rec["from_63_stored_observations"]["simple_pct"], 8),
        }
    if s["id"] in USD_LEGS:
        base, quote = USD_LEGS[s["id"]]
        # Value of the non-USD currency in USD terms.
        if quote == "USD":
            ccy = base
            vs = last_step["simple_pct"]
            log_vs = last_step["log_pct"]
        else:
            ccy = quote
            vs = rnum(pct(prev_value, last_value), 6)  # old/new - 1
            log_vs = rnum(logpct(prev_value, last_value), 6)
        rec["non_usd_vs_usd_last_step"] = {
            "currency": ccy,
            "simple_pct": vs,
            "log_pct": log_vs,
            "definition": "Percent change in USD per one unit of the non-USD currency on the last stored step.",
        }
    return rec


def leg_decomposition(by_id: dict) -> dict:
    out = {}
    for cross, (left, op, right) in CROSS_SPEC.items():
        ch = by_id[cross]["last_step"]
        lh = by_id[left]["last_step"]
        rh = by_id[right]["last_step"]
        implied = lh["log_pct"] + rh["log_pct"] if op == "plus" else lh["log_pct"] - rh["log_pct"]
        sign = "+" if op == "plus" else "-"
        diff = ch["log_pct"] - implied
        if abs(diff) > 1e-4:
            raise SystemExit(f"{cross} log decomposition residual {diff}")
        out[cross] = {
            "formula": f"log({cross}) = log({left}) {sign} log({right})",
            "cross_log_pct": ch["log_pct"],
            "cross_simple_pct": ch["simple_pct"],
            "implied_log_pct_from_usd_legs": rnum(implied, 6),
            "difference_log_pct": rnum(diff, 6),
            "left_leg": {"id": left, "log_pct": lh["log_pct"], "simple_pct": lh["simple_pct"]},
            "right_leg": {"id": right, "log_pct": rh["log_pct"], "simple_pct": rh["simple_pct"]},
        }
    return out


def ccy_panel(by_id: dict) -> list:
    rows = []
    for pid, (base, quote) in USD_LEGS.items():
        rec = by_id[pid]
        if not rec["has_2026_11_04"] or rec["last_date"] != "2026-11-04":
            rows.append({"pair": pid, "available_on_2026_11_04": False})
            continue
        vs = rec["non_usd_vs_usd_last_step"]
        rows.append(
            {
                "pair": pid,
                "available_on_2026_11_04": True,
                "currency": vs["currency"],
                "vs_usd_simple_pct": vs["simple_pct"],
                "vs_usd_log_pct": vs["log_pct"],
                "pair_simple_pct": rec["last_step"]["simple_pct"],
            }
        )
    rows.sort(key=lambda row: -(row.get("vs_usd_simple_pct") or -999))
    return rows


def yield_gap(by_id: dict, left: str, right: str, date: str) -> dict:
    lv = by_id[left]["path_levels"].get(date)
    rv = by_id[right]["path_levels"].get(date)
    if lv is None or rv is None:
        return {
            "date": date,
            "available": False,
            "left": left,
            "right": right,
            "reason": "missing print; not treated as zero",
        }
    return {
        "date": date,
        "available": True,
        "left": left,
        "right": right,
        "left_bp": lv,
        "right_bp": rv,
        "left_minus_right_bp": rnum(lv - rv, 4),
        "note": "Sovereign yield gap in basis points. Not a forward point, not FX financing.",
    }


def scan_forward_keys(obj: object, path: str = "", found: list | None = None) -> list:
    if found is None:
        found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = f"{path}.{key}" if path else str(key)
            if any(token in str(key).lower() for token in ("forward", "points", "fwd")):
                found.append(child)
            if path.count(".") < 3:
                scan_forward_keys(value, child, found)
    elif isinstance(obj, list) and obj and path.count(".") < 2:
        scan_forward_keys(obj[0], path + "[]", found)
    return found


def curve_facts(data: dict) -> dict:
    official = data["official_curves"]["countries"]
    tradable = data["tradable_rate_curves"]["curves"]
    policy = data["policy_paths"]["countries"]
    estr = tradable["ESTR"]
    ea_policy = policy["EA"]
    return {
        "official_countries": sorted(official.keys()),
        "tradable_curve_ids": sorted(tradable.keys()),
        "policy_countries": sorted(policy.keys()),
        "nok_in_official": "NO" in official or "NOK" in official,
        "nok_in_tradable": any("NOK" in k or k == "NOWA" for k in tradable),
        "nok_in_policy": "NO" in policy or "NOK" in policy,
        "nz_in_official": "NZ" in official,
        "nz_in_tradable": any(k.startswith("NZ") or "BKBM" in k for k in tradable),
        "nz_in_policy": "NZ" in policy,
        "tradable_status": {name: curve.get("status") for name, curve in tradable.items()},
        "estr": {
            "status": estr.get("status"),
            "error": estr.get("error"),
            "n_contracts": len(estr.get("contracts") or []),
        },
        "ea_policy": {
            "status": ea_policy.get("status"),
            "terminal": ea_policy.get("terminal"),
            "n_contracts_3m": len(ea_policy.get("contracts_3m") or []),
            "errors": ea_policy.get("errors"),
        },
        "ea_official_bond_curves": {
            name: {"status": curve.get("status"), "as_of": curve.get("as_of"), "n_zero_yields": len(curve.get("zero_yields") or [])}
            for name, curve in official["EA"]["curves"].items()
        },
        "other_official_as_of": {
            code: official[code].get("as_of")
            for code in ("AU", "CA", "JP", "US")
        },
    }


def news_facts(news: dict) -> dict:
    items = []
    for item in news.get("items") or []:
        summary = item.get("summary") or ""
        items.append(
            {
                "id": item.get("id"),
                "published_at": item.get("published_at"),
                "source_name": item.get("source_name"),
                "primary_category": item.get("primary_category"),
                "headline": item.get("headline"),
                "summary": summary,
                "headline_only": summary.startswith("Headline-only"),
                "role": "narrative_not_a_mark",
            }
        )
    return {
        "as_of": news.get("as_of"),
        "status": news.get("status"),
        "n_items": len(items),
        "items": items,
    }


def prior_hypothesis(payload: dict) -> dict:
    return {
        "role": "prior_to_challenge_not_a_finding",
        "hypothesis_id": payload.get("hypothesis_id"),
        "current_revision_id": payload.get("current_revision_id"),
        "title": payload.get("title"),
        "status": payload.get("status"),
        "stated_at": (payload.get("forecast") or {}).get("stated_at"),
        "forecast_expectation": (payload.get("forecast") or {}).get("expectation"),
        "horizon": (payload.get("forecast") or {}).get("horizon"),
        "claim": payload.get("claim"),
        "calculations": payload.get("calculations"),
        "competing_explanations": payload.get("competing_explanations"),
        "falsifiers": payload.get("falsifiers"),
        "instruction": "November 4 closes precede stated_at 2026-11-04T22:07:17 ET. They are newly admitted context. They are not forecast success.",
    }


def book_facts(book: dict) -> dict:
    cg = book["pms"]["chatgpt"]
    positions = []
    for pos in cg.get("positions") or []:
        positions.append(
            {
                "position_id": pos.get("position_id"),
                "instrument": pos.get("instrument"),
                "side": pos.get("side"),
                "asset_class": pos.get("asset_class"),
                "notional_usd": pos.get("notional_usd"),
                "paper_expression": pos.get("paper_expression"),
            }
        )
    return {
        "source": "data/pm/books/latest.json pms.chatgpt only",
        "book_as_of": book.get("as_of"),
        "evidence_cutoff": cg.get("evidence_cutoff"),
        "pm_id": cg.get("pm_id"),
        "decision_status": cg.get("decision_status"),
        "last_action": cg.get("last_action"),
        "positions": positions,
        "any_fx_position": any((p.get("asset_class") == "fx") for p in positions),
        "note": "Existing book is a rates position. This packet is not an instruction to hedge it with FX.",
    }


def main() -> None:
    raw = SNAPSHOT.read_bytes()
    file_sha = sha256_bytes(raw)
    snapshot = json.loads(raw)
    body = {k: v for k, v in snapshot.items() if k != "packet_sha256"}
    canon_sha = sha256_bytes(canonical_dump(body).encode("utf-8"))
    full_canon_sha = sha256_bytes(canonical_dump(snapshot).encode("utf-8"))
    if snapshot.get("as_of") != FREEZE_AS_OF:
        raise SystemExit(f"unexpected snapshot as_of {snapshot.get('as_of')}")
    ms = snapshot["families"]["market_state"]
    data = ms["data"]
    if ms.get("as_of") != MARKET_STATE_AS_OF or data.get("generated_at") != MARKET_STATE_AS_OF:
        raise SystemExit(
            f"unexpected market_state clocks as_of={ms.get('as_of')} generated_at={data.get('generated_at')}"
        )
    if canon_sha != INSTRUCTED_SHA256:
        raise SystemExit("canonical packet hash does not match the instructed freeze id")

    series = {s["id"]: s for s in data["opportunities"]["series"]}
    pairs = data["fx"]["pairs"]
    missing = [i for i in TABLE_IDS + CONTEXT_IDS if i not in series]
    if missing:
        raise SystemExit(f"missing series {missing}")

    table = []
    context = []
    by_id = {}
    for sid in TABLE_IDS:
        rec = series_record(series[sid], pairs.get(sid))
        table.append(rec)
        by_id[sid] = rec
    for sid in CONTEXT_IDS:
        rec = series_record(series[sid], pairs.get(sid))
        context.append(rec)
        by_id[sid] = rec

    carry = data["opportunities"]["carry"]
    relationships = []
    for rel in data["opportunities"]["relationships"]:
        relationships.append(
            {
                "id": rel.get("id"),
                "label": rel.get("label"),
                "status": rel.get("status"),
                "as_of": rel.get("as_of"),
                "n": rel.get("n"),
                "reason": rel.get("reason"),
                "role": "research_prompt_not_a_causal_model_and_not_a_vote",
            }
        )

    candidate_ids = [
        "EURUSD",
        "CADNOK",
        "EURNOK",
        "USDNOK",
        "EURJPY",
        "USDJPY",
        "AUDUSD",
        "AUDNZD",
        "EURCAD",
        "GBPUSD",
        "NZDUSD",
    ]
    financing = {}
    carry_by_pair = {row["pair"]: row for row in carry}
    for sid in candidate_ids:
        row = carry_by_pair.get(sid)
        financing[sid] = {
            "forward_points_present": False,
            "carry_row_present": row is not None,
            "carry_row": row,
            "financing_status": "UNKNOWN",
            "reason": "No forward points or FX funding spread are in the snapshot. A carry row, when present, is a 2y sovereign yield differential divided by FX vol and is explicitly not forward carry.",
        }

    oil = {
        "wti": by_id["WTI"],
        "brent": by_id["BRENT"],
        "futures_roll_note": by_id["WTI"]["note"],
        "interpretation_constraint": "Percentile and z inside the stored 126 closes are recomputed here. The snapshot percentile and z fields do not match those ranks. n_field is 252 while len(history) is 126, so the snapshot level percentile is not a function of the stored rows alone. Both clocks are preserved. The mismatch is not repaired.",
    }

    facts = {
        "type": "FX_FACTS_2026_11_05",
        "methodology": {
            "history_row": "[date, value]",
            "returns": "Recomputed from opportunities.series history. Simple percent is 100*(new/old-1). Log percent is 100*ln(new/old). Snapshot ret_* fields are compared and not used as the cited move.",
            "five_observations_back": "history[-6] to history[-1], which is five stored steps. Requires at least six rows.",
            "one_month_and_three_month": "Reported only with the actual start date. obs_21 and obs_63 count stored observations, not calendar days. A separate calendar anchor uses the last stored print on or before last_date minus 30 or 91 calendar days. No forward fill.",
            "stored_percentile": "weak_inclusive_pct = 100 * (count of stored values <= last) / len(history). strict_below_pct uses <. midrank_pct gives ties half weight. This is the rank inside the stored rows only.",
            "snapshot_fx_percentiles": "fx.pairs pctile_1y and pctile_5y are copied, not recomputed. The stored history is 126 rows and cannot support a 1y or 5y percentile. Scale is 0-100.",
            "yields": "Series unit is basis points. 458 means 4.58 percent. Cited yield changes are level_change in bp.",
            "financing": "UNKNOWN unless a forward-points or funding-spread field exists. opportunities.carry is recorded and is not financing.",
            "news": "Headlines are narrative. They are not marks.",
            "relationships": "opportunities.relationships are research prompts. Betas are omitted so they are not reused as a model.",
        },
        "freeze": {
            "snapshot_path": str(SNAPSHOT.relative_to(REPO)),
            "file_bytes": len(raw),
            "file_bytes_sha256": file_sha,
            "instructed_sha256": INSTRUCTED_SHA256,
            "file_bytes_sha256_equals_instructed": file_sha == INSTRUCTED_SHA256,
            "canonical_packet_sha256_excluding_packet_sha256_field": canon_sha,
            "canonical_packet_sha256_equals_instructed": canon_sha == INSTRUCTED_SHA256,
            "canonical_full_object_sha256": full_canon_sha,
            "canonical_full_object_equals_file_bytes": full_canon_sha == file_sha,
            "stored_packet_sha256_field": snapshot.get("packet_sha256"),
            "hash_definition": "Instructed digest equals sha256 of json.dumps(object without packet_sha256, indent=2, sort_keys=True) plus a trailing newline. Raw file bytes are the canonical dump of the full object, including the packet_sha256 field, so the file-byte digest differs. The difference is recorded and not repaired.",
            "snapshot_as_of": snapshot.get("as_of"),
            "collect_as_of": snapshot.get("collect_as_of"),
            "market_state_as_of": ms.get("as_of"),
            "market_state_generated_at": data.get("generated_at"),
            "market_state_status": ms.get("status"),
            "fx_source_observation": data["fx"].get("source_observation"),
            "clock_note": "Freeze as_of is 2026-11-05T04:53:53.458055-05:00. market_state as_of and generated_at are 2026-11-05T10:17:36Z. Not every field was known at the earlier timestamp.",
        },
        "opportunities_method": data["opportunities"].get("method"),
        "table": table,
        "context_series": context,
        "currency_vs_usd_on_last_step": ccy_panel(by_id),
        "cross_log_decomposition_last_step": leg_decomposition(by_id),
        "oil": {
            "wti_last_date": oil["wti"]["last_date"],
            "brent_last_date": oil["brent"]["last_date"],
            "futures_roll_note": oil["futures_roll_note"],
            "interpretation_constraint": oil["interpretation_constraint"],
            "wti_stored_rank": oil["wti"]["stored_history_rank_of_last"],
            "brent_stored_rank": oil["brent"]["stored_history_rank_of_last"],
            "wti_snapshot_percentile": oil["wti"]["snapshot_series_percentile"],
            "brent_snapshot_percentile": oil["brent"]["snapshot_series_percentile"],
            "wti_snapshot_z": oil["wti"]["snapshot_series_z"],
            "brent_snapshot_z": oil["brent"]["snapshot_series_z"],
            "wti_snapshot_percentile_matches": oil["wti"]["snapshot_percentile_matches_stored_weak_inclusive"],
            "brent_snapshot_percentile_matches": oil["brent"]["snapshot_percentile_matches_stored_weak_inclusive"],
            "wti_rank_of_2026_11_03_within_history_through_that_date": oil["wti"][
                "rank_of_previous_close_within_history_through_previous"
            ],
            "brent_rank_of_2026_11_03_within_history_through_that_date": oil["brent"][
                "rank_of_previous_close_within_history_through_previous"
            ],
            "wti_63obs_sign": oil["wti"]["from_63_stored_observations"]["sign"],
            "brent_63obs_sign": oil["brent"]["from_63_stored_observations"]["sign"],
            "wti_calendar_91d_sign": (
                "positive"
                if oil["wti"]["calendar_91d_on_or_before"]["simple_pct"] > 0
                else "negative"
            ),
            "brent_calendar_91d_sign": (
                "positive"
                if oil["brent"]["calendar_91d_on_or_before"]["simple_pct"] > 0
                else "negative"
            ),
            "wti_full_window_sign": "positive" if oil["wti"]["from_first_stored"]["simple_pct"] > 0 else "negative",
            "brent_full_window_sign": "positive" if oil["brent"]["from_first_stored"]["simple_pct"] > 0 else "negative",
        },
        "yield_gaps_not_financing": {
            "us_minus_ea_2y": {
                "2026-11-03": yield_gap(by_id, "US_2Y", "EA_2Y", "2026-11-03"),
                "2026-11-04": yield_gap(by_id, "US_2Y", "EA_2Y", "2026-11-04"),
            },
            "us_minus_ca_2y": {
                "2026-11-03": yield_gap(by_id, "US_2Y", "CA_2Y", "2026-11-03"),
                "2026-11-04": yield_gap(by_id, "US_2Y", "CA_2Y", "2026-11-04"),
            },
            "us_10y_minus_breakeven_change_2026_11_04": {
                "us_10y_level_change_bp": by_id["US_10Y"]["path_changes"]["2026-11-03_to_2026-11-04"]["level_change"],
                "us_be10_level_change_bp": by_id["US_BE10"]["path_changes"]["2026-11-03_to_2026-11-04"]["level_change"],
                "nominal_minus_breakeven_bp": rnum(
                    by_id["US_10Y"]["path_changes"]["2026-11-03_to_2026-11-04"]["level_change"]
                    - by_id["US_BE10"]["path_changes"]["2026-11-03_to_2026-11-04"]["level_change"],
                    4,
                ),
                "note": "Arithmetic difference of two stored changes. Not a US_REAL10 print. US_REAL10 has no 2026-11-04 row.",
            },
        },
        "curves": curve_facts(data),
        "nz_yield_series": {
            "NZ_2Y_history_len": by_id["NZ_2Y"]["history_len"],
            "NZ_2Y_as_of": by_id["NZ_2Y"]["series_as_of"],
            "NZ_10Y_history_len": by_id["NZ_10Y"]["history_len"],
            "note": "Short sovereign series are not an NZ futures curve.",
        },
        "nok_rate_series_ids": [sid for sid in series if sid.startswith("NO") or "NOK" in sid and sid not in pairs],
        "financing": {
            "keyword_paths_under_market_state": scan_forward_keys(data),
            "keyword_path_classification": "Paths containing 'forward' are government-curve forward rates, a macro look-ahead flag, or similar. None is an FX forward-points or FX funding field. fx.pairs has no points field.",
            "fx_pair_field_names": sorted(next(iter(pairs.values())).keys()),
            "carry_rows": carry,
            "by_expression": financing,
            "status": "UNKNOWN",
            "statement": "FX forward points are absent. Financing is UNKNOWN for every FX expression reviewed. The carry screen is not a funding spread.",
        },
        "relationship_prompts": relationships,
        "news": news_facts(snapshot["families"]["news"]),
        "prior_hypothesis": prior_hypothesis(json.loads(HYPOTHESIS.read_bytes())),
        "chatgpt_book": book_facts(json.loads(BOOK.read_bytes())),
        "missing_nov4_marks": [
            {
                "id": sid,
                "last_date": by_id[sid]["last_date"],
            }
            for sid in ("SP500", "VIX", "BROAD_USD", "US_REAL10", "HY_OAS", "CA_2Y", "CA_10Y", "AU_2Y", "AU_10Y")
            if not by_id[sid]["has_2026_11_04"]
        ],
    }
    # NOK rate series: FX ids contain NOK. Filter to non-spot categories.
    facts["nok_rate_series_ids"] = [
        sid
        for sid, s in series.items()
        if "NOK" in sid and s.get("category") != "FX" or sid.startswith("NO_")
    ]

    out = OUT_DIR / "fx_facts.json"
    out.write_text(json.dumps(facts, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    print(f"file_sha {file_sha}")
    print(f"canon_sha {canon_sha} match {canon_sha == INSTRUCTED_SHA256}")
    print(f"file_match_instructed {file_sha == INSTRUCTED_SHA256}")


if __name__ == "__main__":
    main()
