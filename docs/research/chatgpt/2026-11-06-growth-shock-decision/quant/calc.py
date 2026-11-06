#!/usr/bin/env python3
"""Quant calc for 2026-11-06 growth-shock decision packet. Stdlib only."""
from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
RESEARCH_ROOT = SCRIPT_DIR.parent
SOURCE_MAP_PATH = RESEARCH_ROOT / "source" / "source_map.json"
BOOK_JUDGMENT_PATH = RESEARCH_ROOT / "book" / "judgment.json"
FX_JUDGMENT_PATH = RESEARCH_ROOT / "fx" / "judgment.json"
RATES_JUDGMENT_PATH = RESEARCH_ROOT / "rates" / "judgment.json"
INPUTS_PATH = SCRIPT_DIR / "inputs.json"
RESULTS_PATH = SCRIPT_DIR / "results.json"

YARDSTICK_IDS = (
    "CA_2Y",
    "US_2Y",
    "US_10Y",
    "EURUSD",
    "AUDJPY",
    "AUDNZD",
    "AUDUSD",
    "USDJPY",
    "NASDAQ",
    "WTI",
    "BRENT",
)


def _must_float(x: Any, path: str) -> float:
    if x is None:
        raise ValueError(f"Missing required numeric field: {path}")
    return float(x)


def _maybe_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    return float(x)


def _write_json(path: Path, obj: Any, *, sort_keys: bool = True) -> None:
    path.write_text(json.dumps(obj, sort_keys=sort_keys, indent=2) + "\n", encoding="utf-8")


def _usd_float_pair(value: float) -> Dict[str, Any]:
    return {
        "unrounded": value,
        "nearest_dollar": int(round(value)),
        "loss_usd_positive": max(0.0, -value),
    }


def _bp_pair(exact_bp: float) -> Dict[str, Any]:
    return {"exact_bp": exact_bp, "display_bp_2dp": round(exact_bp, 2)}


def _vol_display(change: float, is_bp: bool) -> Dict[str, Any]:
    if is_bp:
        return {"full": change, "display_bp_2dp": round(change, 2)}
    return {"full": change, "display_percent_2dp_of_100_ln": round(change, 2)}


def _sample_std(values: Sequence[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    var = sum((x - mean) ** 2 for x in values) / (n - 1)
    return math.sqrt(var)


def _rolling_sum_extrema(changes: Sequence[float], window: int) -> Dict[str, Any]:
    n = len(changes)
    if n < window:
        return {
            "window": window,
            "insufficient_changes": True,
            "min_sum": None,
            "max_sum": None,
        }
    sums: List[Tuple[int, int, float]] = []
    cur = sum(changes[:window])
    sums.append((0, window - 1, cur))
    for i in range(1, n - window + 1):
        cur = cur - changes[i - 1] + changes[i + window - 1]
        sums.append((i, i + window - 1, cur))
    min_t = min(sums, key=lambda t: t[2])
    max_t = max(sums, key=lambda t: t[2])
    return {
        "window": window,
        "insufficient_changes": False,
        "min_sum": {
            "start_index": min_t[0],
            "end_index": min_t[1],
            "value": min_t[2],
        },
        "max_sum": {
            "start_index": max_t[0],
            "end_index": max_t[1],
            "value": max_t[2],
        },
        "label": "descriptive_not_a_stop",
    }


def _series_changes(series: Dict[str, Any]) -> Tuple[List[float], str, bool]:
    unit = series.get("unit")
    hist = series.get("history") or []
    if len(hist) < 2:
        raise ValueError(f"Series {series.get('id')}: history too short")
    changes: List[float] = []
    if unit == "bp":
        for i in range(1, len(hist)):
            changes.append(float(hist[i][1]) - float(hist[i - 1][1]))
        return changes, "daily_difference_bp", True
    # price / spot / index / etc.
    for i in range(1, len(hist)):
        p0, p1 = float(hist[i - 1][1]), float(hist[i][1])
        if p0 <= 0 or p1 <= 0:
            raise ValueError(f"Series {series.get('id')}: non-positive level in history")
        lr = math.log(p1 / p0)
        changes.append(100.0 * lr)
    return changes, "hundred_times_log_return", False


def _build_yardstick(series: Dict[str, Any]) -> Dict[str, Any]:
    sid = series["id"]
    hist = series.get("history") or []
    len_history = len(hist)
    unit = series.get("unit")
    changes, change_rule, is_bp = _series_changes(series)
    n_changes = len(changes)
    expected_changes = len_history - 1
    length_flag = n_changes == expected_changes
    # Last 20 observations = 19 one-day changes (intervals between those obs).
    short_changes = changes[-19:] if n_changes >= 19 else changes
    std_short = _sample_std(short_changes)
    std_all = _sample_std(changes)

    def _pack_chg(c: float) -> Dict[str, Any]:
        d = _vol_display(c, is_bp)
        return {"unrounded": c, **d}

    changes_packed = [_pack_chg(c) for c in changes]

    out: Dict[str, Any] = {
        "id": sid,
        "len_history": len_history,
        "stored_n_field": series.get("n_field"),
        "unit": unit,
        "change_rule": change_rule,
        "changes": changes_packed,
        "num_changes": n_changes,
        "len_history_matches_changes_plus_one": length_flag,
        "std_sample": {
            "last_20_observations_19_changes": {
                "n_changes": len(short_changes),
                "std_unrounded": std_short,
                "std_display_rounded": round(std_short, 2),
            },
            "all_changes": {
                "n_changes": n_changes,
                "std_unrounded": std_all,
                "std_display_rounded": round(std_all, 2),
            },
        },
        "horizon_scale": {
            "std_source": "all_changes",
            "n_trading_day_deltas_in_std": n_changes,
            "note": "std_for_sqrt_h_is_full_sample_all_changes_not_short_window_not_70_calendar_financing_days",
            "h40_trading_days": {
                "std_times_sqrt_h_unrounded": std_all * math.sqrt(40),
                "label": "convention_not_a_probability",
            },
            "h60_trading_days": {
                "std_times_sqrt_h_unrounded": std_all * math.sqrt(60),
                "label": "convention_not_a_probability",
            },
        },
        "rolling_cumulative_change": {
            "window_40": _rolling_sum_extrema(changes, 40),
            "window_60": _rolling_sum_extrema(changes, 60),
        },
    }
    if sid in ("EURUSD", "AUDJPY", "AUDNZD"):
        levels = [float(h[1]) for h in hist]
        dates = [h[0] for h in hist]
        imin = min(range(len(levels)), key=lambda i: levels[i])
        imax = max(range(len(levels)), key=lambda i: levels[i])
        out["history_level_extremes"] = {
            "min": {"date": dates[imin], "level": levels[imin]},
            "max": {"date": dates[imax], "level": levels[imax]},
        }
    if sid in ("WTI", "BRENT"):
        note = series.get("note")
        if note:
            out["roll_caveat_from_series_note"] = note
    return out


def _corra_dv01_total_usd(notional: float) -> float:
    return 10000.0 * (notional / 1.0e8)


def _sr3_dv01_total_usd(notional: float) -> float:
    return 25.0 * (notional / 1.0e6)


def _move_bp_implied(new: float, ref: float) -> float:
    return (new - ref) * 100.0


def _pnl_corra_receive(notional: float, ref: float, level: float) -> float:
    move_bp = _move_bp_implied(level, ref)
    return -move_bp * _corra_dv01_total_usd(notional)


def _pnl_sr3(side: str, notional: float, ref: float, level: float) -> float:
    move_bp = _move_bp_implied(level, ref)
    dv01 = _sr3_dv01_total_usd(notional)
    if side == "receive":
        return -move_bp * dv01
    if side == "pay":
        return move_bp * dv01
    return 0.0


def _pnl_eur_long(notional: float, ref: float, level: float) -> float:
    return notional * (level / ref - 1.0)


def _pnl_short_cross(notional: float, ref: float, level: float) -> float:
    return -notional * (level / ref - 1.0)


def _direction_ok(hurts: str, ref: float, adverse: float) -> bool:
    if hurts == "implied_rate_rises":
        return adverse > ref
    if hurts == "implied_rate_falls":
        return adverse < ref
    if hurts == "spot_falls":
        return adverse < ref
    if hurts == "cross_rises":
        return adverse > ref
    return True


def _get_levels_to_price(cand: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    keys = ("target_low", "target_high", "planned_exit_level", "adverse_level", "gap_stress_level")
    out: Dict[str, Any] = {}
    skipped: List[str] = []
    for k in keys:
        v = cand.get(k)
        if v is None or v == 0:
            skipped.append(k)
            continue
        out[k] = float(v)
    return out, skipped


def _pricing_worker(cand: Dict[str, Any]) -> Callable[..., float]:
    inst = str(cand.get("instrument") or "")
    hurts = str(cand.get("hurts_when") or "")
    expr = str(cand.get("expression") or "")
    side = str(cand.get("side") or "")
    if inst.startswith("CORRA") or "corra" in cand.get("candidate_id", ""):
        return lambda n, ref, lev: _pnl_corra_receive(n, ref, lev)
    if inst == "SR3H7" or "sofr" in cand.get("candidate_id", ""):
        if "receive" in expr or side == "long_price":
            return lambda n, ref, lev: _pnl_sr3("receive", n, ref, lev)
        if "pay" in expr or side == "short_price":
            return lambda n, ref, lev: _pnl_sr3("pay", n, ref, lev)
        return lambda n, ref, lev: 0.0
    if inst == "EURUSD":
        return lambda n, ref, lev: _pnl_eur_long(n, ref, lev)
    if expr == "short_reference_cross":
        return lambda n, ref, lev: _pnl_short_cross(n, ref, lev)
    raise ValueError(f"Cannot infer pricing for candidate_id={cand.get('candidate_id')}")


def _adverse_loss_per_usd_notional(
    cand: Dict[str, Any], ref: float, adverse: float, price_fn: Callable[..., float]
) -> float:
    """Positive loss magnitude per USD 1 of notional at adverse (when adverse hurts)."""
    pnl = price_fn(1.0, ref, adverse)
    return max(0.0, -pnl)


def _analyst_proposed_notional(cand: Dict[str, Any]) -> Tuple[float, str]:
    act = str(cand.get("action") or "")
    prop = cand.get("proposed_notional_usd")
    if isinstance(prop, (int, float)):
        return float(prop), "proposed_notional_usd"
    closed = {"CLOSE", "EXIT", "WAIT", "NO_TRADE", "DECLINE"}
    lb = _maybe_float(cand.get("loss_budget_usd")) or 0.0
    if act in closed and lb == 0.0:
        return 0.0, "zero_flat_no_budget"
    cat = cand.get("compare_at_notional_usd")
    if isinstance(cat, (int, float)):
        return float(cat), "compare_at_notional_usd"
    raise ValueError(
        f"candidate {cand.get('candidate_id')}: missing proposed/compare notional rule"
    )


def main() -> None:
    source_map = json.loads(SOURCE_MAP_PATH.read_text(encoding="utf-8"))
    book_j = json.loads(BOOK_JUDGMENT_PATH.read_text(encoding="utf-8"))
    fx_j = json.loads(FX_JUDGMENT_PATH.read_text(encoding="utf-8"))
    rates_j = json.loads(RATES_JUDGMENT_PATH.read_text(encoding="utf-8"))

    bindings = source_map["bindings"]
    agent_packet_sha256 = bindings["agent_packet_fields"]["packet_sha256"]
    embedded_packet_sha256_in_snapshot = bindings["embedded_packet_sha256_in_snapshot"]
    series_by_id = {s["id"]: s for s in source_map.get("series", [])}
    tc = source_map["tradable_curves"]
    corra_blk = tc["CORRA"]
    sofr_blk = tc["SOFR"]

    def _contract_rate(code: str) -> Dict[str, Any]:
        for c in corra_blk["contracts"]:
            if c.get("code") == code:
                return c
        raise ValueError(f"CORRA contract {code} not found")

    cra_h = _contract_rate("CRAH27")
    sr3_h7 = None
    for c in sofr_blk["contracts"]:
        if c.get("code") == "SR3H7":
            sr3_h7 = c
            break
    if sr3_h7 is None:
        raise ValueError("SR3H7 not found in SOFR contracts")

    funding = tc.get("funding_context_sofr")
    if funding is None:
        raise ValueError("funding_context_sofr not found under tradable_curves")

    book_pms = source_map["book"]["pms_chatgpt"]
    funding_sofr_pct = float(funding["percent_rate"])
    funding_sofr_date = str(funding.get("effective_date") or funding.get("observation_date"))

    # Identity checks
    entry = 3.4
    book_mark_corra = 3.10875
    entry_to_mark_bp = (entry - book_mark_corra) * 100.0
    identity_stored = entry_to_mark_bp * 10000.0
    identity_checks = {
        "CRAH27_from_tradable_curves": {
            "price": cra_h["price"],
            "implied_rate_percent": cra_h["implied_rate"],
            "price_equals_100_minus_implied_ok": cra_h.get("price_equals_100_minus_implied_rate_ok"),
            "expected_price_97_115_implied_2_885_ok": (
                abs(float(cra_h["price"]) - 97.115) < 1e-9
                and abs(float(cra_h["implied_rate"]) - 2.885) < 1e-9
            ),
        },
        "SR3H7_from_tradable_curves": {
            "price": sr3_h7["price"],
            "implied_rate_percent": sr3_h7["implied_rate"],
            "price_equals_100_minus_implied_ok": sr3_h7.get("price_equals_100_minus_implied_rate_ok"),
            "expected_price_95_76_implied_4_24_ok": (
                abs(float(sr3_h7["price"]) - 95.76) < 1e-9
                and abs(float(sr3_h7["implied_rate"]) - 4.24) < 1e-9
            ),
        },
        "corra_book_identity_parallel_average": {
            "entry_implied_percent": entry,
            "book_mark_implied_percent": book_mark_corra,
            "bp_entry_minus_book_mark": entry_to_mark_bp,
            "usd_per_bp_per_100m_notional": 10000.0,
            "unrealized_usd_identity_check": identity_stored,
            "matches_stored_book_unrealized_291250": abs(identity_stored - 291250.0) < 1e-6,
            "label": "book_identity_parallel_average_equal_weight_strip_not_single_contract",
        },
        "funding_context_sofr_matches_candidate_card": {
            "percent_rate": funding_sofr_pct,
            "observation_date": funding_sofr_date,
            "expected_3_94_on_2026_11_04": funding_sofr_pct == 3.94 and funding_sofr_date == "2026-11-04",
        },
    }

    codes_4 = ("CRAH27", "CRAM27", "CRAU27", "CRAZ27")
    rates_4 = [float(_contract_rate(c)["implied_rate"]) for c in codes_4]
    avg_4 = sum(rates_4) / 4.0
    gap_bp_unrounded = (avg_4 - book_mark_corra) * 100.0
    nc_corra_pnl = (book_mark_corra - avg_4) * 100.0 * 10000.0

    eurusd_series = series_by_id["EURUSD"]
    spot_last = float(eurusd_series["last_value"])
    eur_entry = 1.1267
    nc_eur_pnl = 5_000_000.0 * (spot_last / eur_entry - 1.0)
    combined_gross = nc_corra_pnl + nc_eur_pnl
    claim_prompt = 38418.0
    noncanonical_mark = {
        "label": "noncanonical_not_stored_unrealized",
        "corra_four_contracts_mean_implied_percent": {
            "contracts": codes_4,
            "implied_rates_percent": rates_4,
            "arithmetic_mean": avg_4,
            "book_mark_percent": book_mark_corra,
            "gap_bp_unrounded": gap_bp_unrounded,
            "nearest_dollar_pnl_at_100m_book_parallel": int(round(nc_corra_pnl)),
            "pnl_usd_unrounded": nc_corra_pnl,
            "formula": "(book_mark - average)*100*10000",
        },
        "eur_long_spot_vs_entry": {
            "entry": eur_entry,
            "frozen_spot_from_EURUSD_series_last": spot_last,
            "notional_usd": 5_000_000.0,
            "pnl_usd_unrounded": nc_eur_pnl,
            "nearest_dollar": int(round(nc_eur_pnl)),
            "stored_book_unrealized_usd": 0.0,
        },
        "combined_gross_before_financing": {
            "unrounded": combined_gross,
            "nearest_dollar": int(round(combined_gross)),
            "claim_prompt_usd_38418": claim_prompt,
            "nearest_dollar_agreement_with_claim": int(round(combined_gross)) == int(round(claim_prompt)),
        },
    }

    stock_charge = {
        "stock_charge_already_on_book": {
            "funding_cost_usd": book_pms["funding_cost_usd"],
            "funding_percent_rate": book_pms["funding_percent_rate"],
            "funding_convention": book_pms["funding_convention"],
            "funded_draw_usd": book_pms["funded_draw_usd"],
            "source": "source_map.book.pms_chatgpt",
        }
    }

    carry_spec = book_j["eur_carry_sensitivity"]
    us2y = series_by_id["US_2Y"]
    ea2y = series_by_id["EA_2Y"]
    us2y_pct = float(us2y["last_value"]) / 100.0
    ea2y_pct = float(ea2y["last_value"]) / 100.0
    card_us = float(carry_spec["usd_rate_percent"])
    card_eu = float(carry_spec["eur_rate_percent"])
    notional_carry = float(carry_spec["notional_usd"])
    days_carry = float(carry_spec["days"])
    basis_carry = float(carry_spec["day_count_basis"])
    line_series = notional_carry * (us2y_pct - ea2y_pct) / 100.0 * (days_carry / basis_carry)
    line_card = notional_carry * (card_us - card_eu) / 100.0 * (days_carry / basis_carry)
    rate_disagree = (abs(card_us - us2y_pct) > 1e-9) or (abs(card_eu - ea2y_pct) > 1e-9)
    eur_carry_block = {
        "note_not_forward_not_spot_forecast": carry_spec.get("note"),
        "series_based": {
            "US_2Y_last_bp": us2y["last_value"],
            "US_2Y_last_as_of": us2y.get("last_date"),
            "US_2Y_as_percent_from_bp": us2y_pct,
            "EA_2Y_last_bp": ea2y["last_value"],
            "EA_2Y_last_as_of": ea2y.get("last_date"),
            "EA_2Y_as_percent_from_bp": ea2y_pct,
            "cost_sensitivity_usd_unrounded": line_series,
            "nearest_cent": round(line_series, 2),
        },
        "card_percent_from_judgment_object": {
            "usd_rate_percent": card_us,
            "eur_rate_percent": card_eu,
            "cost_sensitivity_usd_unrounded": line_card,
            "nearest_cent": round(line_card, 2),
        },
        "card_disagrees_with_series_last_bp": rate_disagree,
        "formula_applied": "notional * ((usd_rate_percent - eur_rate_percent)/100) * days/basis; series line uses bp_last/100 as percent",
    }

    all_candidates: List[Tuple[Dict[str, Any], str]] = []
    for c in book_j["candidates"]:
        all_candidates.append((deepcopy(c), "book"))
    for c in fx_j["candidates"]:
        all_candidates.append((deepcopy(c), "fx"))
    for c in rates_j["candidates"]:
        all_candidates.append((deepcopy(c), "rates"))

    priced: List[Dict[str, Any]] = []
    direction_flags: List[bool] = []

    for cand, src in all_candidates:
        cid = cand["candidate_id"]
        cand["judgment_source"] = src
        ref = _must_float(cand.get("reference_level"), f"{cid}.reference_level")
        hurts = str(cand.get("hurts_when") or "")
        price_fn = _pricing_worker(cand)
        levels, skipped = _get_levels_to_price(cand)
        cand["levels_used_forward_pnl"] = levels
        cand["levels_skipped_zero_or_null"] = skipped

        adverse = levels.get("adverse_level")
        direction_ok = True
        if cid == "sofr_h7_flat":
            direction_ok = True
        elif adverse is not None:
            direction_ok = _direction_ok(hurts, ref, float(adverse))
        direction_flags.append(direction_ok)
        cand["adverse_direction_ok"] = direction_ok

        an_prop, an_rule = _analyst_proposed_notional(cand)
        cand["analyst_proposed_notional_usd"] = {"value": an_prop, "rule": an_rule}

        loss_budget = _maybe_float(cand.get("loss_budget_usd"))
        if loss_budget is None:
            loss_budget = 0.0

        adv_loss_per_1 = 0.0
        if adverse is not None:
            adv_loss_per_1 = _adverse_loss_per_usd_notional(cand, ref, float(adverse), price_fn)

        budget_impl = 0.0
        if loss_budget > 0 and adv_loss_per_1 > 0:
            budget_impl = loss_budget / adv_loss_per_1
        elif act_flat := str(cand.get("action") or "") in ("CLOSE", "EXIT", "WAIT", "NO_TRADE", "DECLINE"):
            if loss_budget == 0:
                budget_impl = 0.0

        rounded_1000 = round(budget_impl / 1000.0) * 1000.0 if budget_impl > 0 else 0.0
        cand["budget_implied_notional_usd"] = {
            "unrounded": budget_impl,
            "rounded_to_1000_usd_labeled_rounded": rounded_1000,
        }

        # PnL grids
        level_pnls: Dict[str, Any] = {}
        for lk, lv in levels.items():
            for label, notional in (
                ("analyst_proposed_notional_usd", an_prop),
                ("budget_implied_notional_usd", budget_impl),
            ):
                pv = price_fn(notional, ref, lv)
                level_pnls.setdefault(lk, {})[label] = _usd_float_pair(pv)

        cand["forward_pnl_by_level_and_notional"] = level_pnls

        # Budget exceeded
        bud_exc = False
        overrun = None
        if loss_budget > 0 and adverse is not None and an_prop > 0:
            pnl_adv = price_fn(an_prop, ref, float(adverse))
            loss_mag = max(0.0, -pnl_adv)
            if loss_mag > loss_budget + 1e-9:
                bud_exc = True
                overrun = loss_mag - loss_budget
        cand["budget_exceeded_by_proposed_notional"] = {
            "flag": bud_exc,
            "overrun_usd": overrun,
        }

        # Illustrative opportunity (not a loss) for zero-notional closes
        opp_block = None
        act = str(cand.get("action") or "")
        if an_prop == 0 and cid in ("corra_close", "eur_exit", "sofr_h7_flat"):
            inc_corr = 100_000_000.0 if "corra" in cid else None
            inc_eur = 5_000_000.0 if cid == "eur_exit" else None
            if cid == "corra_close":
                tg_hi = levels.get("target_high")
                tg_lo = levels.get("target_low")
                n0 = inc_corr
                if tg_hi is not None:
                    opp_block = {
                        "label": "opportunity_not_a_loss",
                        "notional_usd": n0,
                        "forgone_pnl_at_targets_from_reference": {
                            "target_high": _usd_float_pair(price_fn(n0, ref, float(tg_hi))),
                            "target_low": _usd_float_pair(price_fn(n0, ref, float(tg_lo))),
                        },
                    }
            elif cid == "eur_exit":
                n0 = inc_eur
                if n0:
                    tg_hi = levels.get("target_high")
                    tg_lo = levels.get("target_low")
                    opp_block = {
                        "label": "opportunity_not_a_loss",
                        "notional_usd": n0,
                        "forgone_pnl_at_targets_from_reference": {
                            "target_high": _usd_float_pair(price_fn(n0, ref, float(tg_hi)))
                            if tg_hi is not None
                            else None,
                            "target_low": _usd_float_pair(price_fn(n0, ref, float(tg_lo)))
                            if tg_lo is not None
                            else None,
                        },
                    }
            elif cid == "sofr_h7_flat":
                opp_block = {
                    "label": "opportunity_not_a_loss",
                    "note": "flat SR3 at zero notional; no directional give-up computed",
                }
        cand["illustrative"] = opp_block

        priced.append(cand)

    # Portfolio helpers
    def _find(cid: str) -> Dict[str, Any]:
        for p in priced:
            if p["candidate_id"] == cid:
                return p
        raise ValueError(f"Missing candidate {cid}")

    corra_pref = _find("corra_cut_50m")
    eur_pref = _find("eur_hold_5m")
    sofr_pref = _find("sofr_h7_flat")

    n_corra_prop = float(corra_pref["proposed_notional_usd"])
    n_eur_prop = float(eur_pref["proposed_notional_usd"])
    n_sofr = 0.0

    n_corra_budget = corra_pref["budget_implied_notional_usd"]["unrounded"]
    n_eur_budget = eur_pref["budget_implied_notional_usd"]["unrounded"]

    ref_c = float(corra_pref["reference_level"])
    ref_e = float(eur_pref["reference_level"])
    adv_c = float(corra_pref["levels_used_forward_pnl"]["adverse_level"])
    adv_e = float(eur_pref["levels_used_forward_pnl"]["adverse_level"])
    gap_c = float(corra_pref["levels_used_forward_pnl"]["gap_stress_level"])
    gap_e = float(eur_pref["levels_used_forward_pnl"]["gap_stress_level"])
    tg_e_hi = float(eur_pref["levels_used_forward_pnl"]["target_high"])
    tg_e_lo = float(eur_pref["levels_used_forward_pnl"]["target_low"])
    tg_c_hi = float(corra_pref["levels_used_forward_pnl"]["target_high"])
    tg_c_lo = float(corra_pref["levels_used_forward_pnl"]["target_low"])

    pc = lambda n, lev: _pnl_corra_receive(n, ref_c, lev)
    pe = lambda n, lev: _pnl_eur_long(n, ref_e, lev)

    rate_pct = float(corra_pref["financing_rate_percent"])
    days_fin = float(corra_pref["financing_horizon_days"])
    dc = float(corra_pref["financing_day_count"])

    def _fin_cost(draw: float) -> Dict[str, Any]:
        raw = draw * (rate_pct / 100.0) * (days_fin / dc)
        return {"draw_usd": draw, "cost_usd_unrounded": raw, "nearest_cent": round(raw, 2)}

    pref_draws = [
        ("corra_cut_50m", float(corra_pref["financing_draw_usd"])),
        ("eur_hold_5m", float(eur_pref["financing_draw_usd"])),
        ("sofr_h7_flat", float(sofr_pref["financing_draw_usd"])),
    ]
    pref_lines = [_fin_cost(d) for _, d in pref_draws]
    pref_total = sum(x["cost_usd_unrounded"] for x in pref_lines)

    sq_lines = [
        _fin_cost(1_000_000.0),
        _fin_cost(50_000.0),
    ]
    sq_total = sum(x["cost_usd_unrounded"] for x in sq_lines)

    scen_rows: Dict[str, Any] = {}

    def _sum2(fn_c: Callable[[], float], fn_e: Callable[[], float]) -> Dict[str, Any]:
        d = fn_c()
        f = fn_e()
        net = d + f
        return {
            "corra": _usd_float_pair(d),
            "eurusd": _usd_float_pair(f),
            "sofr_flat": _usd_float_pair(0.0),
            "combined_directional_pnl_usd": _usd_float_pair(net),
            "label": "not_an_expected_value",
        }

    scen_rows["domestic_reacceleration"] = {
        "corra_to_adverse_eur_unchanged_at_reference": _sum2(
            lambda: pc(n_corra_prop, adv_c), lambda: pe(n_eur_prop, ref_e)
        ),
        "financing_cost_separate_positive": {
            "unrounded": pref_total,
            "nearest_cent": round(pref_total, 2),
            "label": "never_an_edge",
        },
        "net_directional_plus_financing_not_ev": {
            "unrounded": None,
            "note": "financing_not_mixed_into_directional",
        },
    }
    scen_rows["dollar_demand_and_oil"] = {
        "corra_unchanged_eur_to_adverse": _sum2(
            lambda: pc(n_corra_prop, ref_c), lambda: pe(n_eur_prop, adv_e)
        ),
        "financing_cost_separate_positive": {
            "unrounded": pref_total,
            "nearest_cent": round(pref_total, 2),
            "label": "never_an_edge",
        },
    }
    scen_rows["both_adverse_no_correlation_assumed"] = {
        "both_legs_adverse": _sum2(lambda: pc(n_corra_prop, adv_c), lambda: pe(n_eur_prop, adv_e)),
        "financing_cost_separate_positive": {
            "unrounded": pref_total,
            "nearest_cent": round(pref_total, 2),
            "label": "never_an_edge",
        },
        "note": "not_a_hedge_test",
    }
    scen_rows["gap_stress_both"] = {
        "both_gap_stress_levels": _sum2(
            lambda: pc(n_corra_prop, gap_c), lambda: pe(n_eur_prop, gap_e)
        ),
        "financing_cost_separate_positive": {
            "unrounded": pref_total,
            "nearest_cent": round(pref_total, 2),
            "label": "never_an_edge",
        },
    }

    pnl_c_hi = pc(n_corra_prop, tg_c_hi)
    pnl_c_lo = pc(n_corra_prop, tg_c_lo)
    dist_hi = abs(tg_c_hi - ref_c)
    dist_lo = abs(tg_c_lo - ref_c)
    nearer = "target_high" if dist_hi < dist_lo else "target_low"
    farther = "target_low" if nearer == "target_high" else "target_high"

    pnl_e_hi = pe(n_eur_prop, tg_e_hi)
    pnl_e_lo = pe(n_eur_prop, tg_e_lo)
    dist_e_hi = abs(tg_e_hi - ref_e)
    dist_e_lo = abs(tg_e_lo - ref_e)
    eur_near = "target_high" if dist_e_hi < dist_e_lo else "target_low"

    scen_rows["target_near_and_target_far"] = {
        "corra_receive_at_proposed_notional": {
            "target_high_pnl": _usd_float_pair(pnl_c_hi),
            "target_low_pnl": _usd_float_pair(pnl_c_lo),
            "nearer_favorable_receive_smaller_move_bp": nearer,
            "farther_favorable_receive_larger_move_bp": farther,
            "note": "no_average",
        },
        "eur_long_at_proposed_notional": {
            "target_high_pnl": _usd_float_pair(pnl_e_hi),
            "target_low_pnl": _usd_float_pair(pnl_e_lo),
            "nearer_to_reference_usd_per_eur": eur_near,
            "note": "no_average",
        },
        "financing_cost_separate_positive": {
            "unrounded": pref_total,
            "nearest_cent": round(pref_total, 2),
            "label": "never_an_edge",
        },
    }

    # Status quo: CORRA 100m + EUR 5m both adverse
    scen_rows["status_quo_incumbent_both_adverse_comparison"] = {
        "corra_notional_usd": 100_000_000.0,
        "eur_notional_usd": 5_000_000.0,
        "label": "not_preferred_incumbent_sizes",
        "both_legs_adverse": _sum2(lambda: pc(100_000_000.0, adv_c), lambda: pe(5_000_000.0, adv_e)),
        "financing_cost_status_quo_not_preferred": {
            "unrounded": sq_total,
            "nearest_cent": round(sq_total, 2),
            "label": "comparison_only_never_an_edge",
        },
    }

    # Duplicate scenarios at budget-implied CORRA / EUR sizes
    scen_rows["domestic_reacceleration_budget_implied_notionals_second_column"] = {
        "corra_to_adverse_eur_unchanged_at_reference": _sum2(
            lambda: pc(n_corra_budget, adv_c), lambda: pe(n_eur_budget, ref_e)
        ),
        "financing_cost_same_draw_rule_as_preferred_rows": {
            "unrounded": pref_total,
            "nearest_cent": round(pref_total, 2),
            "note": "draw_schedule_unchanged_second_column_is_notional_only",
        },
    }
    scen_rows["dollar_demand_and_oil_budget_implied_notionals_second_column"] = {
        "corra_unchanged_eur_to_adverse": _sum2(
            lambda: pc(n_corra_budget, ref_c), lambda: pe(n_eur_budget, adv_e)
        ),
    }
    scen_rows["both_adverse_budget_implied_notionals_second_column"] = {
        "both_legs_adverse": _sum2(
            lambda: pc(n_corra_budget, adv_c), lambda: pe(n_eur_budget, adv_e)
        ),
        "note": "not_a_hedge_test",
    }

    financing_block = {
        **stock_charge,
        "prospective_preferred_set": {
            "financing_rate_percent": rate_pct,
            "financing_horizon_days": days_fin,
            "day_count": int(dc),
            "lines": {name: _fin_cost(dr) for name, dr in pref_draws},
            "sum_cost_usd_unrounded": pref_total,
            "sum_cost_nearest_cent": round(pref_total, 2),
            "label": "preferred_true_candidates_only",
        },
        "status_quo_financing_comparison_not_preferred": {
            "assumption": "CORRA_draw_1000000_plus_EUR_draw_50000",
            "lines": {"corra_incumbent_draw": sq_lines[0], "eur_incumbent_draw": sq_lines[1]},
            "sum_cost_usd_unrounded": sq_total,
            "sum_cost_nearest_cent": round(sq_total, 2),
            "label": "not_preferred",
        },
    }

    # Declined illustrations
    audj = _find("audjpy_short")
    audn = _find("audnzd_short")
    sr3r = _find("sofr_h7_receive")
    sr3p = _find("sofr_h7_pay")

    def _ill_short(c: Dict[str, Any], n: float) -> Dict[str, Any]:
        ref = float(c["reference_level"])
        adv = float(c["levels_used_forward_pnl"]["adverse_level"])
        return _usd_float_pair(_pnl_short_cross(n, ref, adv))

    declined_block = {
        "fx_aud_shorts_compare_at_5m_adverse": {
            "audjpy": _ill_short(audj, 5_000_000.0),
            "audnzd": _ill_short(audn, 5_000_000.0),
            "sized_notional_zero_loss_budget_zero": True,
        },
        "sr3h7_declined_at_compare_10m_and_budget_implied": {
            "receive_adverse": {
                "compare_at_10m": _usd_float_pair(
                    _pnl_sr3("receive", 10_000_000.0, float(sr3r["reference_level"]), float(sr3r["levels_used_forward_pnl"]["adverse_level"]))
                ),
                "budget_implied_notional_unrounded": sr3r["budget_implied_notional_usd"]["unrounded"],
                "at_budget_implied_notional": _usd_float_pair(
                    _pnl_sr3(
                        "receive",
                        float(sr3r["budget_implied_notional_usd"]["unrounded"]),
                        float(sr3r["reference_level"]),
                        float(sr3r["levels_used_forward_pnl"]["adverse_level"]),
                    )
                ),
            },
            "pay_adverse": {
                "compare_at_10m": _usd_float_pair(
                    _pnl_sr3("pay", 10_000_000.0, float(sr3p["reference_level"]), float(sr3p["levels_used_forward_pnl"]["adverse_level"]))
                ),
                "budget_implied_notional_unrounded": sr3p["budget_implied_notional_usd"]["unrounded"],
                "at_budget_implied_notional": _usd_float_pair(
                    _pnl_sr3(
                        "pay",
                        float(sr3p["budget_implied_notional_usd"]["unrounded"]),
                        float(sr3p["reference_level"]),
                        float(sr3p["levels_used_forward_pnl"]["adverse_level"]),
                    )
                ),
            },
        },
        "notes": [
            "positive_or_negative_correlation_is_not_a_veto",
            "different_notionals_are_not_proof_of_diversification",
        ],
    }

    yard_out = {sid: _build_yardstick(series_by_id[sid]) for sid in sorted(YARDSTICK_IDS)}

    limitations = [
        "no_corra_strip_history_proxy_only",
        "proxy_labels_on_candidates",
        "no_meeting_prices_no_SR1_pricing",
        "no_currency_forwards_executed",
        "futures_rolls_distort_oil_screens_per_series_note",
        "stored_n_field_252_not_the_126_point_sample",
    ]

    all_direction_ok = all(direction_flags)

    results = {
        "bindings_echo": {
            "embedded_packet_sha256_in_snapshot": embedded_packet_sha256_in_snapshot,
            "agent_packet_sha256": agent_packet_sha256,
        },
        "identity_checks": identity_checks,
        "noncanonical_mark": noncanonical_mark,
        "financing": financing_block,
        "eur_carry_sensitivity": eur_carry_block,
        "candidates": priced,
        "yardsticks": yard_out,
        "portfolio": {
            "preferred_set_candidate_ids": ["corra_cut_50m", "eur_hold_5m", "sofr_h7_flat"],
            "all_adverse_direction_checks_passed": all_direction_ok,
            "notional_columns": {
                "proposed_corra_usd": n_corra_prop,
                "proposed_eur_usd": n_eur_prop,
                "proposed_sofr_usd": n_sofr,
                "budget_implied_corra_usd_unrounded": n_corra_budget,
                "budget_implied_eur_usd_unrounded": n_eur_budget,
            },
            "scenarios": scen_rows,
            "declined_illustrations": declined_block,
        },
        "limitations": limitations,
    }

    inputs_snapshot = {
        "paths": {
            "source_map": str(SOURCE_MAP_PATH.relative_to(RESEARCH_ROOT)),
            "book_judgment": str(BOOK_JUDGMENT_PATH.relative_to(RESEARCH_ROOT)),
            "fx_judgment": str(FX_JUDGMENT_PATH.relative_to(RESEARCH_ROOT)),
            "rates_judgment": str(RATES_JUDGMENT_PATH.relative_to(RESEARCH_ROOT)),
        },
        "bindings_echo": {
            "embedded_packet_sha256_in_snapshot": embedded_packet_sha256_in_snapshot,
            "agent_packet_sha256": agent_packet_sha256,
        },
        "identities_used": {
            "corra_book": "dv01_usd_per_bp = 10000 * notional/1e8",
            "sr3": "dv01_usd_per_bp = 25 * notional/1e6",
        },
        "carry_series_last": {
            "US_2Y": {"bp": us2y["last_value"], "as_of": us2y.get("last_date")},
            "EA_2Y": {"bp": ea2y["last_value"], "as_of": ea2y.get("last_date")},
        },
        "noncanonical_inputs": {
            "corra_contracts_mean": avg_4,
            "eurusd_spot_last": spot_last,
        },
        "financing_rate_percent_used": rate_pct,
        "financing_horizon_days": days_fin,
        "sofr_funding_context": {
            "percent_rate": funding_sofr_pct,
            "effective_date": funding_sofr_date,
        },
    }
    _write_json(INPUTS_PATH, inputs_snapshot, sort_keys=False)
    ordered_results = {
        "bindings_echo": results["bindings_echo"],
        "identity_checks": results["identity_checks"],
        "noncanonical_mark": results["noncanonical_mark"],
        "financing": results["financing"],
        "eur_carry_sensitivity": results["eur_carry_sensitivity"],
        "candidates": results["candidates"],
        "yardsticks": results["yardsticks"],
        "portfolio": results["portfolio"],
        "limitations": results["limitations"],
    }
    _write_json(RESULTS_PATH, ordered_results, sort_keys=False)

    # Second run idempotency: re-read and rewrite same structure
    results2 = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    _write_json(RESULTS_PATH, results2, sort_keys=False)


if __name__ == "__main__":
    main()
