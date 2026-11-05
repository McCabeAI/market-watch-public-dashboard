#!/usr/bin/env python3
"""Frozen snapshot quant: EURUSD vol, CORRA sensitivities, carry — no external data."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
from datetime import date
from pathlib import Path
from statistics import mean
from typing import Any

REPO = Path(__file__).resolve().parents[5]
SNAPSHOT = REPO / "data/overnight/runs/overnight-20261105/reviews/review-001/evidence_snapshot.json"
AGENT_PACKET = SNAPSHOT.parent / "agent_evidence_packet.json"
TRADER_REVIEW = SNAPSHOT.parent / "trader_review.json"
BOOK = REPO / "data/pm/books/latest.json"
OUT = Path(__file__).resolve().parent

EXPECTED_RAW_SHA = "13a1b1ca0fb89f4030f427f4106199ab8087894e478db8e980e1cc1d050f2744"
EXPECTED_CANON_SHA = "0bc766c948f4f88f81ea6e28bc00ad0a67e09ee5605b23b47cb69b039f415b10"
EXPECTED_GIT_BLOB = "16a74cdf5149e3fa8a9211fa2559b9ba9fc8f2ad"
EXPECTED_AGENT_PACKET_SHA = "633501f729ca9917b211edbfb809dce6dd89edb762b14c669582e2a2ca5fee5a"

CORRA_EXPIRIES = ["2027-03", "2027-06", "2027-09", "2027-12"]
HORIZONS_YARD = [5, 10, 21, 42, 63]
EXCURSION_H = [5, 21, 63]
ADV_BPS = [10, 15, 20, 25, 30, 36.375, 50, 100]
NOTIONALS_CORRA = [(250_000_000, 25_000), (125_000_000, 12_500), (62_500_000, 6_250)]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_sha256(path: Path) -> str:
    with path.open() as f:
        obj = json.load(f)
    obj.pop("packet_sha256", None)
    blob = json.dumps(obj, indent=2, sort_keys=True) + "\n"
    return hashlib.sha256(blob.encode()).hexdigest()


def git_blob(path: Path) -> str | None:
    rel = path.relative_to(REPO).as_posix()
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", f"HEAD:{rel}"],
            cwd=REPO,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return out
    except subprocess.CalledProcessError:
        return None


def sample_std(values: list[float]) -> tuple[float, int]:
    n = len(values)
    if n < 2:
        return float("nan"), n
    m = mean(values)
    var = sum((x - m) ** 2 for x in values) / (n - 1)
    return math.sqrt(var), n


def get_series_by_id(series_list: list[dict], sid: str) -> dict | None:
    for s in series_list:
        if s.get("id") == sid:
            return s
    return None


def history_closes(series: dict) -> list[tuple[str, float]]:
    h = series.get("history") or []
    return [(row[0], float(row[1])) for row in h]


def resolve_eurusd_history(data: dict) -> tuple[str, list[tuple[str, float]]]:
    """EURUSD stored closes: fx.pairs has stats only; 126-point history in opportunities.series."""
    fx_pairs = set(data["fx"]["pairs"].keys())
    if "EURUSD" not in fx_pairs:
        raise ValueError("EURUSD missing from fx.pairs")
    series_list = data["opportunities"]["series"]
    eu = get_series_by_id(series_list, "EURUSD")
    if not eu or not eu.get("history"):
        raise ValueError("EURUSD history not found")
    path = "families.market_state.data.opportunities.series[id=EURUSD].history"
    return path, history_closes(eu)


def yardstick_row(daily_sigma: float, h: int) -> dict[str, Any]:
    sigma_h = daily_sigma * math.sqrt(h)
    approx_pct = 100.0 * (math.exp(sigma_h) - 1.0)
    return {
        "horizon_observations": h,
        "sigma_h_log": sigma_h,
        "approx_simple_percent": approx_pct,
        "label": "YARDSTICK",
    }


def overlapping_horizon_sums(log_rets: list[tuple[str, float]], h: int) -> list[tuple[str, float]]:
    """Sum of h consecutive daily log returns ending at each date (overlapping)."""
    if len(log_rets) < h:
        return []
    vals = [r for _, r in log_rets]
    dates = [d for d, _ in log_rets]
    out: list[tuple[str, float]] = []
    for i in range(h - 1, len(vals)):
        s = sum(vals[i - h + 1 : i + 1])
        out.append((dates[i], s))
    return out


def simple_pct_change(last: float, prior: float) -> float:
    return 100.0 * (last / prior - 1.0)


def usd_per_fx_simple_pct(pair: str, s0: float, s1: float) -> float:
    """Simple % change in USD per unit foreign currency; invert USDXXX."""
    if pair.startswith("USD") and pair not in ("USD",):
        return 100.0 * (s0 / s1 - 1.0)
    return 100.0 * (s1 / s0 - 1.0)


def corra_strip(data: dict) -> dict[str, Any]:
    corra = data["tradable_rate_curves"]["curves"]["CORRA"]
    contracts = {c["expiry"]: c for c in corra["contracts"]}
    legs = []
    for exp in CORRA_EXPIRIES:
        c = contracts[exp]
        legs.append(
            {
                "expiry": exp,
                "implied_rate": c["implied_rate"],
                "price": c["price"],
                "code": c["code"],
                "source": c.get("source"),
                "open_interest": c.get("open_interest"),
                "change_from_overnight_bps": c.get("change_from_overnight_bps"),
            }
        )
    avg = mean(x["implied_rate"] for x in legs)
    strip_hist = any(
        isinstance(c.get("history"), list) and len(c.get("history", [])) > 1
        for c in corra["contracts"]
    )
    return {
        "curve_path": "families.market_state.data.tradable_rate_curves.curves.CORRA",
        "mark_convention": corra.get("mark_convention"),
        "product_code": corra.get("product_code"),
        "legs": legs,
        "equal_weight_average_implied_rate": avg,
        "strip_history_status": "PRESENT" if strip_hist else "ABSENT",
    }


def ca2y_proxy_sigma(series_list: list[dict]) -> dict[str, Any] | None:
    s = get_series_by_id(series_list, "CA_2Y")
    if not s:
        return None
    hist = history_closes(s)
    changes: list[float] = []
    dates: list[str] = []
    for i in range(1, len(hist)):
        changes.append(hist[i][1] - hist[i - 1][1])
        dates.append(hist[i][0])
    def win(n: int) -> tuple[float, int]:
        tail = changes[-n:] if len(changes) >= n else changes
        return sample_std(tail)
    s20, n20 = win(20)
    s60, n60 = win(60)
    return {
        "label": "SOVEREIGN_PROXY_NOT_STRIP",
        "series_id": "CA_2Y",
        "last_date": hist[-1][0],
        "last_level_bp": hist[-1][1],
        "daily_change_bp_sample_std_20": s20,
        "n_changes_20": n20,
        "daily_change_bp_sample_std_60": s60,
        "n_changes_60": n60,
    }


def receive_pnl_usd(bp_move: float, dv01_per_bp: float) -> float:
    """Receive: yield up (positive bp) -> loss."""
    return -bp_move * dv01_per_bp


def extract_leads(trader_review_path: Path) -> list[dict[str, str]]:
    if not trader_review_path.is_file():
        return []
    with trader_review_path.open() as f:
        tr = json.load(f)
    leads: list[dict[str, str]] = []
    keywords = ("eurusd", "eur/usd", "corra", "canada", "canadian", "boc")

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if k.lower() in ("psychology", "conviction", "emotion", "stress"):
                    continue
                if isinstance(v, str) and len(v) > 20:
                    low = v.lower()
                    if any(kw in low for kw in keywords):
                        if "eur" in low or "corra" in low or "canada" in low:
                            leads.append({"label": "leads_not_votes", "text": v[:500]})
                else:
                    walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(tr)
    seen: set[str] = set()
    uniq: list[dict[str, str]] = []
    for item in leads:
        if item["text"] not in seen:
            seen.add(item["text"])
            uniq.append(item)
    return uniq[:12]


def main() -> None:
    raw_sha = sha256_file(SNAPSHOT)
    canon_sha = canonical_sha256(SNAPSHOT)
    git_blob_sha = git_blob(SNAPSHOT)
    agent_sha = sha256_file(AGENT_PACKET) if AGENT_PACKET.is_file() else None
    agent_canon_sha = canonical_sha256(AGENT_PACKET) if AGENT_PACKET.is_file() else None

    with SNAPSHOT.open() as f:
        snap = json.load(f)

    ms = snap["families"]["market_state"]
    data = ms["data"]
    clocks = {
        "snapshot_as_of": snap.get("as_of"),
        "market_state_as_of": ms.get("as_of"),
        "market_state_generated_at": data.get("generated_at"),
        "macro_hard_as_of": snap.get("families", {}).get("macro_hard", {}).get("as_of"),
    }

    hash_checks = {
        "evidence_snapshot_raw_sha256": {
            "computed": raw_sha,
            "expected": EXPECTED_RAW_SHA,
            "match": raw_sha == EXPECTED_RAW_SHA,
        },
        "evidence_snapshot_canonical_sha256": {
            "computed": canon_sha,
            "expected": EXPECTED_CANON_SHA,
            "match": canon_sha == EXPECTED_CANON_SHA,
        },
        "git_blob_head": {
            "computed": git_blob_sha,
            "expected": EXPECTED_GIT_BLOB,
            "match": git_blob_sha == EXPECTED_GIT_BLOB,
        },
        "agent_evidence_packet_sha256": {
            "computed": agent_sha,
            "expected": EXPECTED_AGENT_PACKET_SHA,
            "match": agent_sha == EXPECTED_AGENT_PACKET_SHA if agent_sha else False,
        },
        "agent_evidence_packet_canonical_sha256": {
            "computed": agent_canon_sha,
            "expected": EXPECTED_AGENT_PACKET_SHA,
            "match": agent_canon_sha == EXPECTED_AGENT_PACKET_SHA if agent_canon_sha else False,
        },
    }

    hist_path, eur_hist = resolve_eurusd_history(data)
    if len(eur_hist) != 126:
        raise ValueError(f"EURUSD history length {len(eur_hist)}, expected 126")

    dates = [d for d, _ in eur_hist]
    closes = [c for _, c in eur_hist]
    last_date, last_close = eur_hist[-1]
    prior_close = eur_hist[-2][1]

    log_rets: list[tuple[str, float]] = []
    for i in range(1, len(closes)):
        lr = math.log(closes[i] / closes[i - 1])
        log_rets.append((dates[i], lr))

    ret_vals = [r for _, r in log_rets]
    sigma20, n20 = sample_std(ret_vals[-20:])
    sigma60, n60 = sample_std(ret_vals[-60:])
    sigma_full, n_full = sample_std(ret_vals)

    def annualize(daily: float) -> float:
        return daily * math.sqrt(252)

    yardsticks = {
        "daily_sigma_20": {
            "value": sigma20,
            "n_returns": n20,
            "annualized_convention_sqrt252": annualize(sigma20),
            "label_annualized": "convention on stored observations; not claim of 252 trading days in file",
        },
        "daily_sigma_60": {
            "value": sigma60,
            "n_returns": n60,
            "annualized_convention_sqrt252": annualize(sigma60),
        },
        "daily_sigma_full_sample": {"value": sigma_full, "n_returns": n_full},
        "horizon_yardsticks_sigma20": {str(h): yardstick_row(sigma20, h) for h in HORIZONS_YARD},
        "horizon_yardsticks_sigma60": {str(h): yardstick_row(sigma60, h) for h in HORIZONS_YARD},
    }

    excursions: dict[str, Any] = {}
    for h in EXCURSION_H:
        sums = overlapping_horizon_sums(log_rets, h)
        if not sums:
            excursions[str(h)] = {"label": "overlapping_descriptive", "status": "window_short"}
            continue
        log_vals = [s for _, s in sums]
        pct_vals = [(math.exp(s) - 1.0) * 100.0 for s in log_vals]
        min_i = min(range(len(log_vals)), key=lambda i: log_vals[i])
        max_i = max(range(len(log_vals)), key=lambda i: log_vals[i])
        excursions[str(h)] = {
            "label": "overlapping_descriptive_not_independent",
            "min_sum_log": log_vals[min_i],
            "min_end_date": sums[min_i][0],
            "max_sum_log": log_vals[max_i],
            "max_end_date": sums[max_i][0],
            "worst_simple_percent": pct_vals[min_i],
            "best_simple_percent": pct_vals[max_i],
        }

    max_daily = max(log_rets, key=lambda x: abs(x[1]))
    weak_rank = 100.0 * sum(1 for c in closes if c <= last_close) / len(closes)
    fx_eu = data["fx"]["pairs"]["EURUSD"]

    def ret_over_obs(end_idx: int, n_obs: int) -> dict[str, Any]:
        start_idx = end_idx - n_obs
        if start_idx < 0:
            return {"status": "window_short"}
        s0 = closes[start_idx]
        s1 = closes[end_idx]
        return {
            "start_date": dates[start_idx],
            "end_date": dates[end_idx],
            "simple_percent": simple_pct_change(s1, s0),
        }

    end_idx = len(closes) - 1
    move_facts = {
        "simple_1d_2026_11_04": {
            "prior_date": dates[end_idx - 1],
            "simple_percent": simple_pct_change(last_close, prior_close),
        },
        "simple_5_observations": ret_over_obs(end_idx, 5),
        "simple_63_observations": ret_over_obs(end_idx, 63),
    }

    cross_pairs = {
        "EUR": "EURUSD",
        "GBP": "GBPUSD",
        "SEK": "USDSEK",
        "CHF": "USDCHF",
        "AUD": "AUDUSD",
        "CAD": "USDCAD",
        "NZD": "NZDUSD",
        "NOK": "USDNOK",
        "JPY": "USDJPY",
    }
    series_list = data["opportunities"]["series"]
    cross: dict[str, Any] = {}
    for ccy, pair in cross_pairs.items():
        s = get_series_by_id(series_list, pair)
        if not s:
            cross[ccy] = {"status": "missing"}
            continue
        h = history_closes(s)
        p0, p1 = h[-2][1], h[-1][1]
        cross[ccy] = {
            "pair": pair,
            "simple_percent_usd_per_fx": usd_per_fx_simple_pct(pair, p0, p1),
        }
    nine = [cross[c]["simple_percent_usd_per_fx"] for c in cross_pairs if "simple_percent_usd_per_fx" in cross[c]]
    ew_nine = mean(nine)
    europe = ["GBP", "SEK", "CHF"]
    ew_europe = mean([cross[c]["simple_percent_usd_per_fx"] for c in europe])
    cross_section = {
        "last_step_only": cross,
        "equal_weight_nine_mean_simple_percent": ew_nine,
        "eur_minus_ew_nine": cross["EUR"]["simple_percent_usd_per_fx"] - ew_nine,
        "equal_weight_europe_three_mean": ew_europe,
        "eur_minus_europe_three": cross["EUR"]["simple_percent_usd_per_fx"] - ew_europe,
        "note": "decomposition_not_correlation",
    }

    strip = corra_strip(data)
    ca2y = ca2y_proxy_sigma(series_list)

    with BOOK.open() as f:
        book_all = json.load(f)
    chatgpt = book_all["pms"]["chatgpt"]
    pos = chatgpt["positions"][0]
    entry = float(pos["entry_price"])
    mark = float(pos["mark_price"])
    notional = float(pos["notional_usd"])
    unrealized = (entry - mark) * 100.0 * 25_000.0
    realized = float(chatgpt.get("realized_pnl_usd", 0))
    snapshot_mark = strip["equal_weight_average_implied_rate"]
    snapshot_vs_book = (mark - snapshot_mark) * 100.0 * 25_000.0

    dv01_table: dict[str, Any] = {}
    for bp in ADV_BPS:
        row = {}
        for notional_usd, dv01 in NOTIONALS_CORRA:
            key = f"usd_{int(notional_usd)}_dv01_{dv01}"
            row[key] = receive_pnl_usd(bp, dv01)
        dv01_table[str(bp)] = row

    sign_checks = {
        "receive_plus_20bp_on_250m": receive_pnl_usd(20, 25_000),
        "receive_minus_20bp_on_250m": receive_pnl_usd(-20, 25_000),
        "receive_0.5bp_yield_decline_3.160_to_3.155_on_250m": receive_pnl_usd(-0.5, 25_000),
    }

    usdcad = float(data["fx"]["pairs"]["USDCAD"]["spot"])
    usd_per_bp_per_lot = 25.0 / usdcad
    lots_for_25k = 25_000.0 / usd_per_bp_per_lot

    funding_days = [21, 42, 63, 90]
    funding = {
        d: 0.0395 * 2_500_000.0 * d / 360.0 for d in funding_days
    }

    us2 = get_series_by_id(series_list, "US_2Y")
    ea2 = get_series_by_id(series_list, "EA_2Y")
    us_hist = {d: v for d, v in history_closes(us2)}
    ea_hist = {d: v for d, v in history_closes(ea2)}

    def y2(date_s: str) -> dict[str, float]:
        return {
            "US_2Y_bp": us_hist.get(date_s),
            "EA_2Y_bp": ea_hist.get(date_s),
            "gap_us_minus_ea_bp": (
                us_hist[date_s] - ea_hist[date_s]
                if date_s in us_hist and date_s in ea_hist
                else None
            ),
        }

    gap_4nov = y2("2026-11-04")
    gap_4nov_decimal = gap_4nov["gap_us_minus_ea_bp"] / 10000.0 if gap_4nov["gap_us_minus_ea_bp"] is not None else None

    sofr_bm = data["policy_paths"]["countries"]["US"]["benchmark"]
    estr_bm = data["policy_paths"]["countries"]["EA"]["benchmark"]
    sofr_hist = {r["effective_date"]: r["percent_rate"] for r in sofr_bm.get("history", [])}
    sofr_fix = {"date": sofr_bm.get("as_of"), "rate_percent": sofr_bm.get("rate")}
    estr_fix = {"date": estr_bm.get("as_of"), "rate_percent": estr_bm.get("rate")}
    sofr_minus_estr_pp = sofr_fix["rate_percent"] - estr_fix["rate_percent"]
    sofr_minus_estr_decimal = sofr_minus_estr_pp / 100.0

    carry_notionals = [25_000_000, 50_000_000, 100_000_000]
    carry_horizons = [21, 42, 63]
    carry_drag: dict[str, Any] = {"label": "INDICATIVE_BENCHMARK_NOT_FORWARD", "executable_forward_points": "ABSENT", "broker_spread": "UNKNOWN"}
    for label, gap_dec in [("gap_2y_us_minus_ea_2026_11_04", gap_4nov_decimal), ("gap_sofr_minus_estr_fixings", sofr_minus_estr_decimal)]:
        if gap_dec is None:
            continue
        carry_drag[label] = {}
        for n in carry_notionals:
            carry_drag[label][str(n)] = {
                str(d): n * gap_dec * (d / 360.0) for d in carry_horizons
            }

    s0 = last_close
    spot_examples: dict[str, Any] = {"N_usd": 50_000_000, "S0": s0, "formula": "N * (S1/S0 - 1)"}
    for s1 in [1.11, 1.14, 1.15, 1.16]:
        spot_examples[f"S1_{s1}"] = 50_000_000 * (s1 / s0 - 1.0)
    for pct in [-0.01, -0.015, -0.02, 0.01, 0.015, 0.02]:
        s1 = s0 * (1.0 + pct)
        spot_examples[f"pct_{pct:+.4f}"] = 50_000_000 * (s1 / s0 - 1.0)
    for n in [25_000_000, 100_000_000]:
        for pct in [-0.01, -0.02]:
            s1 = s0 * (1.0 + pct)
            spot_examples[f"N{n}_pct_{pct:+.2f}"] = n * (s1 / s0 - 1.0)

    brent = get_series_by_id(series_list, "BRENT")
    wti = get_series_by_id(series_list, "WTI")
    oil_dq: dict[str, Any] = {
        "vol_computation": "excluded_futures_roll_contamination",
        "note": "stored oil series is futures path; no oil vol computed",
    }
    for name, s in [("BRENT", brent), ("WTI", wti)]:
        h = history_closes(s)
        oil_dq[name] = {"history_end_date": h[-1][0], "last_5_closes": h[-5:]}

    cpp = snap.get("canada_prima_pressure") or data.get("canada_prima_pressure")
    prima_input = None
    if cpp:
        for ch in cpp.get("channel_evidence", {}).values():
            for inp in ch.get("inputs", []):
                if inp.get("neutral_midpoint") == 2.75:
                    prima_input = {
                        "label": "PROXY_NEUTRAL_INPUT",
                        "neutral_midpoint": 2.75,
                        "as_of": inp.get("as_of"),
                        "corra_rate": inp.get("corra_rate"),
                        "gap": inp.get("gap"),
                    }
                    break

    real_s = get_series_by_id(series_list, "US_REAL10")
    be_s = get_series_by_id(series_list, "US_BE10")
    nominal_mismatch = {
        "US_real_10y_last": real_s["history"][-1] if real_s else None,
        "US_breakeven_10y_last": be_s["history"][-1] if be_s else None,
        "note": "do not combine into same-day real-yield split",
    }

    dec2026_stale = False
    if cpp:
        for ch in cpp.get("channel_evidence", {}).values():
            for inp in ch.get("inputs", []):
                if inp.get("contract_month") == "2026-12":
                    od = inp.get("observation_date", "")
                    if od and od <= "2026-10-30":
                        dec2026_stale = True
                        oil_dq["brent_dec2026_leg"] = {"observation_date": od, "flag": "STALE"}

    # CSV series
    csv_path = OUT / "series_eurusd.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "close"])
        for d, c in eur_hist:
            w.writerow([d, c])

    inputs = {
        "hash_checks": hash_checks,
        "clocks": clocks,
        "eurusd_history_path": hist_path,
        "eurusd_fx_pairs_stats_path": "families.market_state.data.fx.pairs.EURUSD",
        "last_date": last_date,
        "last_close": last_close,
        "prior_close": prior_close,
        "fx_pairs_eurusd_pctile_1y": fx_eu.get("pctile_1y"),
        "fx_pairs_eurusd_pctile_5y": fx_eu.get("pctile_5y"),
        "weak_inclusive_rank_last_close": weak_rank,
        "leads_not_votes": extract_leads(TRADER_REVIEW),
        "corra_strip": strip,
        "ca2y_proxy": ca2y,
        "book_identity_chatgpt": {
            "label": "book identity",
            "entry_implied_rate": entry,
            "mark_implied_rate": mark,
            "notional_usd": notional,
            "unrealized_usd_identity": unrealized,
            "realized_usd_stored": realized,
            "realized_half_identity_formula": "(entry-mark_closeout)*100*25000",
            "snapshot_vs_book_mark_usd_remark": snapshot_vs_book,
            "funding_cost_usd_stored": chatgpt.get("funding_cost_usd"),
        },
        "sofr_estr": {
            "US_2Y_2026_11_03": y2("2026-11-03"),
            "US_2Y_2026_11_04": gap_4nov,
            "SOFR_fixing": sofr_fix,
            "SOFR_2026_11_03_from_history": sofr_hist.get("2026-11-03"),
            "ESTR_fixing": estr_fix,
        },
        "prima_neutral": prima_input,
        "oil_data_quality": oil_dq,
        "nominal_real_breakeven_dates": nominal_mismatch,
        "dec2026_brent_leg_stale_flag": dec2026_stale,
    }

    volatility = {
        "eurusd": {
            "history_path": hist_path,
            "n_closes": len(closes),
            "n_daily_log_returns": len(log_rets),
            "max_abs_daily_log_return": {"date": max_daily[0], "value": max_daily[1]},
            "sample_std_daily_log_return": {
                "last_20": {"sigma": sigma20, "n": n20},
                "last_60": {"sigma": sigma60, "n": n60},
                "full_sample": {"sigma": sigma_full, "n": n_full},
            },
            "annualized_sqrt252_from_20": annualize(sigma20),
            "annualized_sqrt252_from_60": annualize(sigma60),
            "yardsticks": yardsticks,
            "empirical_excursions_overlapping": excursions,
            "weak_inclusive_rank_percent": weak_rank,
            "pctile_1y_from_fx_pairs": fx_eu.get("pctile_1y"),
            "pctile_5y_from_fx_pairs": fx_eu.get("pctile_5y"),
            "move_facts": move_facts,
            "cross_section_last_step": cross_section,
        }
    }

    sensitivities = {
        "corra_receive_dv01_pnl_usd_by_adverse_bp": dv01_table,
        "sign_checks": sign_checks,
        "book_pnl_identities": inputs["book_identity_chatgpt"],
        "funding_accrual_examples_usd": funding,
        "cad_lot_illustration": {
            "label": "ILLUSTRATION",
            "USDCAD": usdcad,
            "usd_per_bp_per_cad_1mm_lot": usd_per_bp_per_lot,
            "lots_to_match_usd_25000_per_bp": lots_for_25k,
        },
        "long_eurusd_carry_sensitivities": carry_drag,
        "spot_pnl_identity_examples": spot_examples,
    }

    ledger_lines = [
        "# Assumption ledger",
        "",
        "No external data were retrieved; all series from pinned evidence_snapshot.json, book at data/pm/books/latest.json (pms.chatgpt only), optional trader_review.json opinion strings.",
        "",
        "## Clocks (not conflated)",
        f"- snapshot as_of: {clocks['snapshot_as_of']}",
        f"- market_state as_of / generated_at: {clocks['market_state_as_of']} / {clocks['market_state_generated_at']}",
        f"- macro_hard as_of: {clocks['macro_hard_as_of']}",
        "",
        "## EURUSD",
        f"- Series: `{hist_path}` (126 closes); stats `{inputs['eurusd_fx_pairs_stats_path']}`",
        f"- Last: {last_date} close {last_close}; formula daily log return ln(p_t/p_{{t-1}}); sample std N-1 on last 20/60/full returns",
        f"- Horizon yardsticks: sigma_h = daily_sigma_* * sqrt(h); approx % = 100*(exp(sigma_h)-1); label YARDSTICK",
        f"- Excursions: overlapping sums in stored sample; label overlapping_descriptive",
        f"- Weak rank: 100*count(closes<=last)/126 = {weak_rank:.6f}",
        "",
        "## CORRA strip",
        f"- Snapshot legs 2027 H/M/U/Z; strip_history_status={strip['strip_history_status']}",
        "- DV01 P&L: receive, yield up = loss; label book identity / illustration",
        "",
        "## Carry (long EURUSD)",
        "- Financing drag N*gap*(days/360); gap from 2y sovereign (2026-11-04) and SOFR−ESTR; label INDICATIVE_BENCHMARK_NOT_FORWARD",
        "- Executable forward points: ABSENT",
        "",
        "## Oil",
        "- Vol excluded (futures roll-contamination); Dec 2026 Brent leg STALE if observation on/before 2026-10-30",
        "",
        "## Real / breakeven",
        "- US real 10y vs breakeven end dates differ; do not same-day combine",
    ]

    OUT.joinpath("inputs.json").write_text(json.dumps(inputs, indent=2, sort_keys=True) + "\n")
    OUT.joinpath("volatility.json").write_text(json.dumps(volatility, indent=2, sort_keys=True) + "\n")
    OUT.joinpath("sensitivities.json").write_text(json.dumps(sensitivities, indent=2, sort_keys=True) + "\n")
    OUT.joinpath("assumption_ledger.md").write_text("\n".join(ledger_lines) + "\n")

    print("Wrote quant outputs to", OUT)
    print("EURUSD sigma20", sigma20, "sigma60", sigma60)
    print("Hash raw match", hash_checks["evidence_snapshot_raw_sha256"]["match"])
    print("Agent packet match", hash_checks["agent_evidence_packet_sha256"]["match"])


if __name__ == "__main__":
    main()
