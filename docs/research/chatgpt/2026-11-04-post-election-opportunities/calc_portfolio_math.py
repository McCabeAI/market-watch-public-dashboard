#!/usr/bin/env python3
"""Portfolio math from frozen_extract.json (stdlib only)."""

from __future__ import annotations

import argparse
import json
import math
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, List, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUTS = SCRIPT_DIR / "frozen_extract.json"
DEFAULT_OUTPUT = SCRIPT_DIR / "calc_results.json"

LEGS_2027 = ("2027-03", "2027-06", "2027-09", "2027-12")
LEG_KEYS = ("H", "M", "U", "Z")
FUNDING_RATE = 0.0395
FUNDING_DAY_COUNT = 360

# ASSUMPTION from prior research commit 250bf6f4 unless snapshot states otherwise.
SR3_USD_PER_BP = 25.0
CRA_CAD_PER_BP = 25.0
CRA_FACE_CAD = 1_000_000
IB_AUD_PER_BP = 24.66  # prior research convention


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def money(x: float) -> float:
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def mean(values: List[float]) -> float:
    return sum(values) / len(values)


def bp_diff(a: float, b: float) -> float:
    return (a - b) * 100.0


def floor_toward_zero(x: float) -> int:
    if x >= 0:
        return int(math.floor(x))
    return int(math.ceil(x))


def contracts_by_expiry(rows: List[dict]) -> Dict[str, dict]:
    return {r["expiry"]: r for r in rows if r.get("expiry")}


def contracts_by_code(rows: List[dict]) -> Dict[str, dict]:
    return {r["code"]: r for r in rows if r.get("code")}


def find_expiry(rows: List[dict], expiry: str) -> dict:
    m = contracts_by_expiry(rows)
    if expiry not in m:
        raise KeyError(f"Missing expiry {expiry}")
    return m[expiry]


def fx_spot(frozen: dict, pair: str) -> float:
    return frozen["fx"]["pairs"][pair]["spot"]


def dv01_block(frozen: dict) -> dict:
    usdcad = fx_spot(frozen, "USDCAD")
    audusd = fx_spot(frozen, "AUDUSD")
    usd_per_cad = 1.0 / usdcad
    usd_per_aud = audusd
    ib_unrounded = 3_000_000 * 0.0001 * 30 / 365
    return {
        "USDCAD_spot_CAD_per_USD": usdcad,
        "AUDUSD_spot": audusd,
        "usd_per_cad": usd_per_cad,
        "usd_per_aud": usd_per_aud,
        "CRA_usd_per_bp_per_lot_ASSUMPTION": CRA_CAD_PER_BP * usd_per_cad,
        "SR3_usd_per_bp_per_lot_ASSUMPTION": SR3_USD_PER_BP,
        "IB_aud_per_bp_prior_research_ASSUMPTION": IB_AUD_PER_BP,
        "IB_usd_per_bp_prior_research_ASSUMPTION": IB_AUD_PER_BP * usd_per_aud,
        "IB_unrounded_3m_face_30_365_formula": ib_unrounded,
        "paper_dv01_usd_per_bp_at_250m_notional": 250_000_000 * 0.0001,
    }


def strip_identity(frozen: dict) -> dict:
    corra = frozen["futures_contracts"]["CORRA_3M"]
    sofr = frozen["futures_contracts"]["SOFR_3M"]
    corra_rates = [find_expiry(corra, e)["implied_rate"] for e in LEGS_2027]
    sofr_rates = [find_expiry(sofr, e)["implied_rate"] for e in LEGS_2027]
    corra_mean = mean(corra_rates)
    sofr_mean = mean(sofr_rates)
    cash_corra = frozen["benchmarks"]["CORRA"]["rate"]
    cash_sofr = frozen["benchmarks"]["SOFR"]["rate"]
    dec_mar_corra = bp_diff(
        find_expiry(corra, "2027-12")["implied_rate"],
        find_expiry(corra, "2027-03")["implied_rate"],
    )
    dec_mar_sofr = bp_diff(
        find_expiry(sofr, "2027-12")["implied_rate"],
        find_expiry(sofr, "2027-03")["implied_rate"],
    )
    book = frozen["chatgpt_position_economics"]
    mark = book["mark"]
    gap_bp = (mark - corra_mean) * 100.0
    paper_dv01 = book["notional_usd"] * 0.0001
    return {
        "corra_2027_rates": dict(zip(LEGS_2027, corra_rates)),
        "corra_equal_weight_mean": corra_mean,
        "corra_mean_vs_cash_2p54_bp": (corra_mean - 2.54) * 100.0,
        "corra_mean_vs_frozen_cash_bp": bp_diff(corra_mean, cash_corra),
        "sofr_2027_rates": dict(zip(LEGS_2027, sofr_rates)),
        "sofr_equal_weight_mean": sofr_mean,
        "sofr_minus_corra_bp_by_expiry": {
            e: bp_diff(find_expiry(sofr, e)["implied_rate"], find_expiry(corra, e)["implied_rate"])
            for e in LEGS_2027
        },
        "corra_H_to_Z_bp": bp_diff(corra_rates[3], corra_rates[0]),
        "sofr_H_to_Z_bp": bp_diff(sofr_rates[3], sofr_rates[0]),
        "december_minus_march_corra_bp": dec_mar_corra,
        "december_minus_march_sofr_bp": dec_mar_sofr,
        "cash_fixings": {"CORRA": cash_corra, "SOFR": cash_sofr},
        "book_mark": mark,
        "book_mark_vs_strip_mean_bp": gap_bp,
        "book_mark_vs_strip_mean_paper_usd_at_book_dv01": money(-gap_bp * paper_dv01),
        "note_book_mark_is_prior_decision_not_replaced": True,
    }


def size_cra_equal_lots(target_parallel_dv01: float, cra_dv01: float) -> dict:
    unrounded = target_parallel_dv01 / (4.0 * cra_dv01)
    lots = floor_toward_zero(unrounded)
    achieved = lots * 4.0 * cra_dv01
    return {
        "target_parallel_dv01_usd_per_bp": target_parallel_dv01,
        "unrounded_lots_per_leg": unrounded,
        "floored_lots_per_leg": lots,
        "achieved_parallel_dv01_usd_per_bp": achieved,
        "residual_shortfall_usd_per_bp": target_parallel_dv01 - achieved,
    }


def size_flattener(target_leg_dv01: float, cra_dv01: float) -> dict:
    unrounded = target_leg_dv01 / cra_dv01
    lots = floor_toward_zero(unrounded)
    achieved = lots * cra_dv01
    return {
        "structure": "pay_CRAH27_receive_CRAZ27_equal_local_dv01",
        "unrounded_lots_per_leg": unrounded,
        "floored_lots_per_leg": lots,
        "achieved_leg_usd_dv01": achieved,
    }


def one_quarter_roll(frozen: dict) -> dict:
    corra = frozen["futures_contracts"]["CORRA_3M"]
    sofr = frozen["futures_contracts"]["SOFR_3M"]
    corra_by_code = contracts_by_code(corra)
    sofr_by_code = contracts_by_code(sofr)
    mapping_corra = {"H": "CRAZ26", "M": "CRAH27", "U": "CRAM27", "Z": "CRAU27"}
    mapping_sofr = {"H": "SR3Z6", "M": "SR3H7", "U": "SR3M7", "Z": "SR3U7"}
    old_corra = {
        k: find_expiry(corra, e)["implied_rate"] for k, e in zip(LEG_KEYS, LEGS_2027)
    }
    old_sofr = {k: find_expiry(sofr, e)["implied_rate"] for k, e in zip(LEG_KEYS, LEGS_2027)}
    new_corra = {k: corra_by_code[mapping_corra[k]]["implied_rate"] for k in LEG_KEYS}
    new_sofr = {k: sofr_by_code[mapping_sofr[k]]["implied_rate"] for k in LEG_KEYS}
    slide_corra = {k: bp_diff(new_corra[k], old_corra[k]) for k in LEG_KEYS}
    slide_sofr = {k: bp_diff(new_sofr[k], old_sofr[k]) for k in LEG_KEYS}
    flattener_bp_per_leg_dv01 = slide_corra["H"] - slide_corra["Z"]
    return {
        "assumption": "unchanged_tenor_roll: each leg rate replaced by prior-quarter contract mapping",
        "CORRA_mapping": mapping_corra,
        "SOFR_mapping": mapping_sofr,
        "CORRA_slide_bp_by_leg": slide_corra,
        "SOFR_slide_bp_by_leg": slide_sofr,
        "pay_H_receive_Z_pnl_bp_per_leg_dv01_dH_minus_dZ": flattener_bp_per_leg_dv01,
        "spread_widen_Z_minus_H_bp": slide_corra["Z"] - slide_corra["H"],
        "not_guaranteed_accrual": True,
    }


def aonia_proxies(frozen: dict) -> dict:
    aonia = frozen["futures_contracts"]["AONIA_1M"]
    q1_months = ("2027-03", "2027-04", "2027-05")
    q3_months = ("2027-09", "2027-10", "2027-11")
    q1 = mean([find_expiry(aonia, m)["implied_rate"] for m in q1_months])
    q3 = mean([find_expiry(aonia, m)["implied_rate"] for m in q3_months])
    return {
        "Mar_May_2027_average_label_proxy": {
            "months": list(q1_months),
            "rate": q1,
        },
        "Sep_Nov_2027_average_label_proxy": {
            "months": list(q3_months),
            "rate": q3,
        },
        "proxy_note": "Simple average of listed monthly contracts; not compounded IMM quarter.",
    }


def cross_market_spreads(frozen: dict) -> dict:
    rates = frozen["cash_yields"]
    pairs = [("CA", "US"), ("AU", "US"), ("EA", "US"), ("JP", "US")]
    out = {}
    for foreign, us in pairs:
        row = {}
        for tenor in ("2Y", "10Y"):
            f = rates[foreign]["tenors"][tenor]["value"]
            u = rates[us]["tenors"][tenor]["value"]
            f_as = rates[foreign]["tenors"][tenor]["as_of"]
            u_as = rates[us]["tenors"][tenor]["as_of"]
            spread_bp = None if f is None or u is None else (f - u) * 100.0
            stale = None
            if foreign == "AU" and f_as == "2026-10-28" and u_as == "2026-11-03":
                stale = "stale_mismatched_AU_2026-10-28_vs_US_2026-11-03"
            row[tenor] = {
                "spread_bp_foreign_minus_us": spread_bp,
                "foreign_as_of": f_as,
                "us_as_of": u_as,
                "stale_mismatch_flag": stale,
            }
        out[f"{foreign}-{us}"] = row
    return out


def matched_futures_spreads(frozen: dict) -> dict:
    corra = frozen["futures_contracts"]["CORRA_3M"]
    sofr = frozen["futures_contracts"]["SOFR_3M"]
    out = {}
    for e in LEGS_2027:
        c = find_expiry(corra, e)["implied_rate"]
        s = find_expiry(sofr, e)["implied_rate"]
        out[e] = {"SR3_minus_CRA_bp": bp_diff(s, c)}
    return out


def fx_pnl_usd(pair: str, spot: float, spot_move_fraction: float, notional_usd: float) -> float:
    """USD P&L for 1 unit of foreign CCY notional expressed in USD terms (spot quote conventions)."""
    if pair == "USDJPY":
        # long USDJPY gains when USD strengthens vs JPY
        return money(notional_usd * spot_move_fraction)
    if pair in ("AUDUSD", "NZDUSD"):
        return money(notional_usd * spot_move_fraction)
    if pair == "USDCAD":
        # USDCAD up => USD stronger; long USDCAD P&L ~ notional * move
        return money(notional_usd * spot_move_fraction)
    if pair == "AUDNZD":
        return money(notional_usd * spot_move_fraction)
    if pair in ("AUDCAD", "NZDCAD"):
        return money(notional_usd * spot_move_fraction)
    if pair in ("AUDJPY", "NZDJPY"):
        return money(notional_usd * spot_move_fraction)
    raise KeyError(pair)


def fx_sensitivities(frozen: dict) -> dict:
    pairs = (
        "USDJPY",
        "AUDUSD",
        "NZDUSD",
        "AUDNZD",
        "USDCAD",
        "AUDCAD",
        "NZDCAD",
        "AUDJPY",
        "NZDJPY",
    )
    out = {}
    for pair in pairs:
        spot = fx_spot(frozen, pair)
        units = {
            "risk_capital_1pct_notional_usd_2_500_000": 250_000_000,
            "notional_usd_10_000_000": 10_000_000,
        }
        out[pair] = {
            "spot": spot,
            "usd_pnl_per_1pct_spot_move": {
                name: fx_pnl_usd(pair, spot, 0.01, notional) for name, notional in units.items()
            },
        }
    return out


def financing_cost(risk_capital: float, days: int) -> float:
    return money(risk_capital * FUNDING_RATE * days / FUNDING_DAY_COUNT)


def pnl_receive_corra_lots(
    lots: int, cra_dv01: float, ca_shock: Dict[str, float]
) -> float:
    total = 0.0
    for k in LEG_KEYS:
        total += -lots * cra_dv01 * ca_shock[k]
    return money(total)


def pnl_pay_sofr_lots(lots: int, sr3_dv01: float, us_shock: Dict[str, float]) -> float:
    total = 0.0
    for k in LEG_KEYS:
        total += -lots * sr3_dv01 * us_shock[k]
    return money(total)


def pnl_flattener(leg_dv01: float, ca: Dict[str, float]) -> float:
    return money(leg_dv01 * (ca["H"] - ca["Z"]))


def build_shocks(roll: dict) -> Dict[str, dict]:
    z = {k: 0.0 for k in LEG_KEYS}
    roll_ca = roll["CORRA_slide_bp_by_leg"]
    roll_us = roll["SOFR_slide_bp_by_leg"]
    return {
        "parallel_canada_plus_25_us_unchanged": {"CA": {k: 25.0 for k in LEG_KEYS}, "US": dict(z)},
        "parallel_canada_minus_25": {"CA": {k: -25.0 for k in LEG_KEYS}, "US": dict(z)},
        "common_plus_20": {"CA": {k: 20.0 for k in LEG_KEYS}, "US": {k: 20.0 for k in LEG_KEYS}},
        "common_minus_20": {"CA": {k: -20.0 for k in LEG_KEYS}, "US": {k: -20.0 for k in LEG_KEYS}},
        "canada_plus_25_us_plus_5": {"CA": {k: 25.0 for k in LEG_KEYS}, "US": {k: 5.0 for k in LEG_KEYS}},
        "canada_minus_30_us_minus_15": {
            "CA": {k: -30.0 for k in LEG_KEYS},
            "US": {k: -15.0 for k in LEG_KEYS},
        },
        "bull_flatten_corra_ASSUMPTION": {
            "CA": {"H": 10.0, "M": 0.0, "U": -10.0, "Z": -20.0},
            "US": dict(z),
        },
        "bear_steepen_corra_ASSUMPTION": {
            "CA": {"H": -5.0, "M": 0.0, "U": 0.0, "Z": 15.0},
            "US": dict(z),
        },
        "deescalation_sketch_ASSUMPTION": {
            "CA": {k: -15.0 for k in LEG_KEYS},
            "US": {k: -10.0 for k in LEG_KEYS},
            "fx": {"AUDUSD": 0.01, "AUDNZD": 0.005},
        },
        "escalation_sketch_ASSUMPTION": {
            "CA": {k: 20.0 for k in LEG_KEYS},
            "US": {k: 10.0 for k in LEG_KEYS},
            "fx": {"AUDUSD": -0.015, "AUDNZD": -0.008},
        },
        "one_quarter_roll_mapping": {"CA": dict(roll_ca), "US": dict(roll_us)},
    }


def scenario_skeleton(
    name: str,
    shock: dict,
    paper_dv01: float,
    cra_lots: int,
    cra_dv01: float,
    sr3_lots: int,
    sr3_dv01: float,
    flattener_leg_dv01: float,
    uz_lots: int,
    frozen: dict,
) -> dict:
    ca = shock["CA"]
    us = shock.get("US", {k: 0.0 for k in LEG_KEYS})
    avg_ca = mean([ca[k] for k in LEG_KEYS])
    fx_block = shock.get("fx") or {}
    fx_pnl = 0.0
    for pair, move in fx_block.items():
        fx_pnl += fx_pnl_usd(pair, fx_spot(frozen, pair), move, 250_000_000)
    return {
        "assumption_path_not_forecast": True,
        "paper_receive_4leg_usd": money(-paper_dv01 * avg_ca),
        "futures_receive_4leg_cra_usd": pnl_receive_corra_lots(cra_lots, cra_dv01, ca),
        "futures_pay_4leg_sr3_matched_usd": pnl_pay_sofr_lots(sr3_lots, sr3_dv01, us),
        "combined_receive_cra_pay_sr3_usd": money(
            pnl_receive_corra_lots(cra_lots, cra_dv01, ca)
            + pnl_pay_sofr_lots(sr3_lots, sr3_dv01, us)
        ),
        "pay_H_receive_Z_flattener_usd": pnl_flattener(flattener_leg_dv01, ca),
        "uz_only_same_lots_as_strip_usd": pnl_receive_corra_lots(
            uz_lots, cra_dv01, {"H": 0.0, "M": 0.0, "U": ca["U"], "Z": ca["Z"]}
        ),
        "deescalation_escalation_fx_usd_if_present": money(fx_pnl) if fx_block else None,
    }


def expression_sensitivities(
    frozen: dict, budget: float, cra_dv01: float, sr3_dv01: float, ib_dv01: float
) -> dict:
    cra = size_cra_equal_lots(budget, cra_dv01)
    sr3 = size_cra_equal_lots(budget, sr3_dv01)
    cra_uz = size_cra_equal_lots(budget / 2.0, cra_dv01)
    fl = size_flattener(budget, cra_dv01)
    aonia = frozen["futures_contracts"]["AONIA_1M"]
    mar = find_expiry(aonia, "2027-03")
    mar_lots = floor_toward_zero(budget / ib_dv01)
    proxies = aonia_proxies(frozen)
    q1 = proxies["Mar_May_2027_average_label_proxy"]["rate"]
    q3 = proxies["Sep_Nov_2027_average_label_proxy"]["rate"]
    aonia_cash = frozen["benchmarks"]["AONIA"]["rate"]
    return {
        "budget_usd_per_bp": budget,
        "receive_4leg_CORRA_2027_HMUZ": cra,
        "receive_CRAU27_CRAZ27_only_equal_risk_per_leg": {
            "per_leg_target_dv01": budget / 2.0,
            **size_flattener(budget / 2.0, cra_dv01),
        },
        "pay_CRAH27_receive_CRAZ27_dv01_neutral": fl,
        "pay_4leg_SR3_matched_dv01": sr3,
        "pay_SR3Z7_outright": {
            "unrounded_lots": budget / sr3_dv01,
            "floored_lots": floor_toward_zero(budget / sr3_dv01),
            "achieved_leg_dv01_usd": floor_toward_zero(budget / sr3_dv01) * sr3_dv01,
        },
        "AONIA_receive_MarMay_avg_vs_SepNov_avg_label_proxy": {
            "Mar_May_months": proxies["Mar_May_2027_average_label_proxy"]["months"],
            "Sep_Nov_months": proxies["Sep_Nov_2027_average_label_proxy"]["months"],
            "Mar_May_avg_rate": q1,
            "Sep_Nov_avg_rate": q3,
            "avg_minus_avg_bp": bp_diff(q3, q1),
            "premium_vs_cash_bp_by_window": {
                "Mar_May": bp_diff(q1, aonia_cash),
                "Sep_Nov": bp_diff(q3, aonia_cash),
            },
            "Mar_2027_contract_only_sizing": {
                "floored_lots": mar_lots,
                "achieved_leg_dv01_usd": mar_lots * ib_dv01,
                "open_interest": mar.get("open_interest"),
                "volume": mar.get("volume"),
            },
        },
        "halved_parallel_dv01_keep_UZ_same_lots_as_4leg": {
            "lots_per_leg_from_4leg_sizing": cra["floored_lots_per_leg"],
            "parallel_dv01_usd": 2 * cra["floored_lots_per_leg"] * cra_dv01,
            "half_of_4leg_parallel_dv01": budget / 2.0,
            "parallel_dv01_dollars": money(2 * cra["floored_lots_per_leg"] * cra_dv01),
        },
        "TONA_bpv": {
            "status": "conditional_null_no_JPY_bpv_in_snapshot",
            "hypothesis_from_prior_research": None,
        },
    }


def run_all(frozen: dict) -> dict:
    dv01 = dv01_block(frozen)
    cra_dv01 = dv01["CRA_usd_per_bp_per_lot_ASSUMPTION"]
    sr3_dv01 = dv01["SR3_usd_per_bp_per_lot_ASSUMPTION"]
    ib_dv01 = dv01["IB_usd_per_bp_prior_research_ASSUMPTION"]
    ident = strip_identity(frozen)
    roll = one_quarter_roll(frozen)
    shocks = build_shocks(roll)

    budgets = {}
    for b in (10_000.0, 25_000.0):
        cra_size = size_cra_equal_lots(b, cra_dv01)
        sr3_size = size_cra_equal_lots(b, sr3_dv01)
        fl = size_flattener(b, cra_dv01)
        risk_cap = b  # 100bp shock on paper DV01 == budget when 1% of notional mapping holds
        budgets[str(int(b))] = {
            "expressions": expression_sensitivities(frozen, b, cra_dv01, sr3_dv01, ib_dv01),
            "financing_act360_evidence_book_convention": {
                "risk_capital_usd": risk_cap,
                "rate_annual": FUNDING_RATE,
                "days_30_usd": financing_cost(risk_cap, 30),
                "days_90_usd": financing_cost(risk_cap, 90),
                "label": "SOFR on 100bp shock loss risk capital; not exchange margin",
            },
            "fx_financing_same_risk_capital_1pct_unit": {
                "risk_capital_usd": 2_500_000,
                "days_30_usd": financing_cost(2_500_000, 30),
                "days_90_usd": financing_cost(2_500_000, 90),
            },
        }

    paper_dv01_25k = 25_000.0
    cra_25 = size_cra_equal_lots(paper_dv01_25k, cra_dv01)
    sr3_25 = size_cra_equal_lots(paper_dv01_25k, sr3_dv01)
    fl_25 = size_flattener(paper_dv01_25k, cra_dv01)
    cra_lots = cra_25["floored_lots_per_leg"]
    sr3_lots = sr3_25["floored_lots_per_leg"]

    scenarios = {
        name: scenario_skeleton(
            name,
            shock,
            paper_dv01_25k,
            cra_lots,
            cra_dv01,
            sr3_lots,
            sr3_dv01,
            fl_25["achieved_leg_usd_dv01"],
            cra_lots,
            frozen,
        )
        for name, shock in shocks.items()
    }

    prior_strip_mean = 3.1550000000000002  # prior calc_results section_1 re-derive check
    rederived = ident["corra_equal_weight_mean"]
    return {
        "inputs": str(DEFAULT_INPUTS),
        "pinned_commit": frozen["meta"]["pinned_commit"],
        "dv01_and_fx": dv01,
        "strip_and_book": ident,
        "prior_research_strip_mean_250bf6f": prior_strip_mean,
        "prior_vs_rederived_strip_mean_delta_bp": (rederived - prior_strip_mean) * 100.0,
        "one_quarter_roll": roll,
        "cross_market_cash_spreads_bp": cross_market_spreads(frozen),
        "matched_futures_SR3_minus_CRA_bp": matched_futures_spreads(frozen),
        "fx_spot_sensitivities_1pct_move": fx_sensitivities(frozen),
        "research_budgets_usd_per_bp": budgets,
        "scenario_skeletons_usd_assumption_paths": {
            "note": "Assumption paths for integrator; not forecasts.",
            "structures": [
                "paper_4leg_receive_25000_per_bp",
                "uz_only_same_lots_halved_parallel_dv01",
                "dv01_matched_sr3_pay_overlay",
            ],
            "scenarios": scenarios,
        },
        "article_context_gaps_from_extract": frozen.get("article_context_gaps"),
        "chatgpt_book_pnl_identity": frozen.get("chatgpt_position_economics"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("frozen_extract", nargs="?", default=str(DEFAULT_INPUTS))
    parser.add_argument("-o", "--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    frozen = load(Path(args.frozen_extract))
    results = run_all(frozen)
    out = Path(args.output)
    with out.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, sort_keys=False)
        f.write("\n")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
