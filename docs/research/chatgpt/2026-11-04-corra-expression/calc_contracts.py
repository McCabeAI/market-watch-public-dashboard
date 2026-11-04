#!/usr/bin/env python3
"""Standalone contract math from frozen_inputs.json only (Composer A)."""

from __future__ import annotations

import argparse
import json
import math
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUTS = SCRIPT_DIR / "frozen_inputs.json"
DEFAULT_OUTPUT = SCRIPT_DIR / "calc_results.json"

LEGS_2027 = ("2027-03", "2027-06", "2027-09", "2027-12")
LEG_KEYS = ("H", "M", "U", "Z")


def load_inputs(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def find_corra_3m(data: dict, expiry: str) -> dict:
    for row in data["corra_3m"]:
        if row["expiry"] == expiry:
            return row
    raise KeyError(f"CORRA 3m expiry {expiry}")


def find_sofr_3m(data: dict, expiry: str) -> dict:
    for row in data["sofr_3m"]:
        if row["expiry"] == expiry:
            return row
    raise KeyError(f"SOFR 3m expiry {expiry}")


def find_aonia_1m(data: dict, expiry: str) -> dict:
    for row in data["aonia_1m"]:
        if row["expiry"] == expiry:
            return row
    raise KeyError(f"AONIA 1m expiry {expiry}")


def find_corra_1m(data: dict, expiry: str) -> dict:
    for row in data["corra_1m"]:
        if row["expiry"] == expiry:
            return row
    raise KeyError(f"CORRA 1m expiry {expiry}")


def mean(values: List[float]) -> float:
    return sum(values) / len(values)


def bp_diff(rate_high: float, rate_low: float) -> float:
    return (rate_high - rate_low) * 100.0


def premium_bp(implied_pct: float, cash_pct: float) -> float:
    return (implied_pct - cash_pct) * 100.0


def floor_toward_zero(x: float) -> int:
    if x >= 0:
        return int(math.floor(x))
    return int(math.ceil(x))


def money_cents(x: float) -> float:
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def fx_block(data: dict) -> dict:
    usdcad = data["fx"]["USDCAD"]["spot"]
    audusd = data["fx"]["AUDUSD"]["spot"]
    usd_per_cad = 1.0 / usdcad
    usd_per_aud = audusd
    expected_corra_fx = data["analytics_fx_check"]["CORRA_fx_usd_per_unit_row"]
    ib_unrounded_bpv = 3_000_000 * 0.0001 * 30 / 365
    cra_dv01_usd = 25.0 * usd_per_cad
    sr3_dv01_usd = 25.0
    ib_dv01_usd = 24.66 * usd_per_aud
    return {
        "USDCAD_spot": usdcad,
        "AUDUSD_spot": audusd,
        "usd_per_cad": usd_per_cad,
        "usd_per_aud": usd_per_aud,
        "usd_per_cad_matches_analytics_row": abs(usd_per_cad - expected_corra_fx) < 1e-15,
        "analytics_expected_usd_per_cad": expected_corra_fx,
        "CRA_dv01_usd_per_contract": cra_dv01_usd,
        "SR3_dv01_usd_per_contract": sr3_dv01_usd,
        "IB_dv01_usd_per_contract_published_basis": ib_dv01_usd,
        "IB_unrounded_3m_face_30_365_not_for_valuation": ib_unrounded_bpv,
    }


def identity_checks(data: dict, fx: dict) -> dict:
    corra_rates = [find_corra_3m(data, e)["implied_rate"] for e in LEGS_2027]
    sofr_rates = [find_sofr_3m(data, e)["implied_rate"] for e in LEGS_2027]
    corra_mean = mean(corra_rates)
    sofr_mean = mean(sofr_rates)
    corra_hz_bp = bp_diff(corra_rates[3], corra_rates[0])
    sofr_hz_bp = bp_diff(sofr_rates[3], sofr_rates[0])
    spreads_bp = [bp_diff(sofr_rates[i], corra_rates[i]) for i in range(4)]
    steepener_diff_bp = corra_hz_bp - sofr_hz_bp

    corra_cash = data["benchmarks"]["CORRA"]["rate"]
    sofr_cash = data["benchmarks"]["SOFR"]["rate"]
    aonia_cash = data["benchmarks"]["AONIA"]["rate"]

    aonia_q1 = mean(
        [
            find_aonia_1m(data, "2027-03")["implied_rate"],
            find_aonia_1m(data, "2027-04")["implied_rate"],
            find_aonia_1m(data, "2027-05")["implied_rate"],
        ]
    )
    aonia_q2 = mean(
        [
            find_aonia_1m(data, "2027-06")["implied_rate"],
            find_aonia_1m(data, "2027-07")["implied_rate"],
            find_aonia_1m(data, "2027-08")["implied_rate"],
        ]
    )
    aonia_q3 = mean(
        [
            find_aonia_1m(data, "2027-09")["implied_rate"],
            find_aonia_1m(data, "2027-10")["implied_rate"],
            find_aonia_1m(data, "2027-11")["implied_rate"],
        ]
    )
    aonia_q4_proxy = mean(
        [
            find_aonia_1m(data, "2027-12")["implied_rate"],
            find_aonia_1m(data, "2028-01")["implied_rate"],
            find_aonia_1m(data, "2028-02")["implied_rate"],
        ]
    )
    aonia_contract_months = {
        "2027-03": find_aonia_1m(data, "2027-03")["implied_rate"],
        "2027-06": find_aonia_1m(data, "2027-06")["implied_rate"],
        "2027-09": find_aonia_1m(data, "2027-09")["implied_rate"],
        "2027-12": find_aonia_1m(data, "2027-12")["implied_rate"],
    }

    corra_premium_bp = [premium_bp(r, corra_cash) for r in corra_rates]
    sofr_premium_bp = [premium_bp(r, sofr_cash) for r in sofr_rates]
    aonia_premiums = {
        "Q1_labeled_proxy": premium_bp(aonia_q1, aonia_cash),
        "Q2_labeled_proxy": premium_bp(aonia_q2, aonia_cash),
        "Q3_labeled_proxy": premium_bp(aonia_q3, aonia_cash),
        "Q4_Dec_window_proxy": premium_bp(aonia_q4_proxy, aonia_cash),
        **{k: premium_bp(v, aonia_cash) for k, v in aonia_contract_months.items()},
    }

    corra_1m_path = {}
    for exp in ("2026-11", "2026-12", "2027-01", "2027-02"):
        r = find_corra_1m(data, exp)["implied_rate"]
        corra_1m_path[exp] = {"rate": r, "premium_vs_cash_bp": premium_bp(r, corra_cash)}

    journal = data["paper_engine_observed_on_book"]["nov3_journal_mids_not_this_snapshot"]
    journal_mids = [journal["2027-03"], journal["2027-06"], journal["2027-09"], journal["2027-12"]]
    journal_avg = mean(journal_mids)
    journal_avg_claimed = journal["average_claimed"]
    snap_change_bp = [bp_diff(corra_rates[i], journal_mids[i]) for i in range(4)]

    failures = []
    if abs(journal_avg - 3.16) > 1e-9:
        failures.append("journal_average_recompute")
    if abs(journal_avg - journal_avg_claimed) > 1e-9:
        failures.append("journal_average_vs_claimed")

    return {
        "corra_2027_rates": dict(zip(LEGS_2027, corra_rates)),
        "corra_equal_weight_mean": corra_mean,
        "corra_H_to_Z_bp": corra_hz_bp,
        "sofr_2027_rates": dict(zip(LEGS_2027, sofr_rates)),
        "sofr_equal_weight_mean": sofr_mean,
        "sofr_H_to_Z_bp": sofr_hz_bp,
        "us_minus_ca_spread_bp_by_expiry": dict(zip(LEGS_2027, spreads_bp)),
        "ca_minus_us_H_to_Z_steepener_diff_bp": steepener_diff_bp,
        "cash_fixings": {"CORRA": corra_cash, "SOFR": sofr_cash, "AONIA": aonia_cash},
        "aonia_labeled_quarterly_proxy_rates": {
            "Mar_Apr_May": aonia_q1,
            "Jun_Jul_Aug": aonia_q2,
            "Sep_Oct_Nov": aonia_q3,
            "Dec27_Jan28_Feb28": aonia_q4_proxy,
            "note": "Simple average of listed months; not a compounded IMM quarter.",
        },
        "aonia_single_contract_month_rates_2027": aonia_contract_months,
        "premium_vs_own_cash_bp": {
            "CORRA_by_leg": dict(zip(LEGS_2027, corra_premium_bp)),
            "SOFR_by_leg": dict(zip(LEGS_2027, sofr_premium_bp)),
            "AONIA": aonia_premiums,
        },
        "corra_1m_nov2026_feb2027_vs_cash": corra_1m_path,
        "nov3_journal_mids": dict(zip(LEGS_2027, journal_mids)),
        "nov3_journal_average_recomputed": journal_avg,
        "nov3_journal_average_claimed": journal_avg_claimed,
        "nov4_snapshot_bp_change_vs_journal_by_leg": dict(zip(LEGS_2027, snap_change_bp)),
        "identity_check_failures": failures,
    }


def paper_engine(data: dict) -> dict:
    pe = data["paper_engine_observed_on_book"]
    notional = pe["notional_usd"]
    entry = pe["entry_mark"]
    book = pe["book_mark"]
    unrealized_calc = notional * (entry - book) / 100.0
    half_notional = notional / 2.0
    half_realized_calc = half_notional * (entry - book) / 100.0
    paper_dv01 = notional * 0.0001
    risk_capital = pe["risk_capital_usd"]
    rate = pe["funding_percent_rate"] / 100.0
    dc = pe["funding_day_count"]

    def forward_funding(days: int) -> float:
        return risk_capital * rate * days / dc

    return {
        "unrealized_formula": "notional_usd * (entry_mark - book_mark) / 100",
        "unrealized_inputs": {"notional_usd": notional, "entry_mark": entry, "book_mark": book},
        "unrealized_recomputed_usd": unrealized_calc,
        "unrealized_stored_usd": pe["unrealized_pnl_usd"],
        "unrealized_match": abs(unrealized_calc - pe["unrealized_pnl_usd"]) < 0.01,
        "half_notional_realized_formula": "(notional_usd/2) * (entry_mark - book_mark) / 100",
        "half_notional_realized_recomputed_usd": half_realized_calc,
        "realized_stored_usd": pe["realized_pnl_usd"],
        "half_realized_match": abs(half_realized_calc - pe["realized_pnl_usd"]) < 0.01,
        "paper_dv01_usd_per_bp_average": paper_dv01,
        "risk_capital_100bp_usd": risk_capital,
        "stored_funding_cost_usd_unchanged": pe["funding_cost_usd"],
        "stored_net_after_funding_usd_unchanged": pe["net_after_funding_pnl_usd"],
        "forward_paper_funding_on_risk_capital_act360": {
            "risk_capital_usd": risk_capital,
            "rate_pct": pe["funding_percent_rate"],
            "days_91_usd": money_cents(forward_funding(91)),
            "days_182_usd": money_cents(forward_funding(182)),
        },
    }


def size_equal_lot_cra_receive(target_parallel_dv01_usd: float, fx: dict) -> dict:
    dv01_per_lot = fx["CRA_dv01_usd_per_contract"]
    unrounded_lots = target_parallel_dv01_usd / (4.0 * dv01_per_lot)
    lots = floor_toward_zero(unrounded_lots)
    achieved = lots * 4.0 * dv01_per_lot
    shortfall = target_parallel_dv01_usd - achieved
    face_cad_per_leg = lots * 1_000_000
    face_usd_per_leg = face_cad_per_leg * fx["usd_per_cad"]
    return {
        "target_parallel_dv01_usd_per_bp": target_parallel_dv01_usd,
        "unrounded_lots_per_leg": unrounded_lots,
        "floored_lots_per_leg": lots,
        "achieved_parallel_dv01_usd_per_bp": achieved,
        "residual_shortfall_usd_per_bp": shortfall,
        "face_cad_per_leg": face_cad_per_leg,
        "face_usd_per_leg": face_usd_per_leg,
        "gross_face_cad_four_legs": face_cad_per_leg * 4,
        "gross_face_usd_four_legs": face_usd_per_leg * 4,
        "paper_notional_mismatch_note": (
            "Paper 250m USD is duration-one risk notional (~one year of 90/360 risk), "
            "approximately 250m USD face per leg, not 250m total gross face."
        ),
    }


def size_expression_b(target_leg_dv01_usd: float, fx: dict) -> dict:
    dv01_per_lot = fx["CRA_dv01_usd_per_contract"]
    unrounded = target_leg_dv01_usd / dv01_per_lot
    lots = floor_toward_zero(unrounded)
    achieved = lots * dv01_per_lot
    return {
        "structure": "pay_CRAH27_receive_CRAZ27_equal_local_dv01",
        "target_leg_usd_dv01": target_leg_dv01_usd,
        "unrounded_lots_per_leg": unrounded,
        "floored_lots_per_leg": lots,
        "achieved_leg_usd_dv01": achieved,
        "pnl_formula": "achieved_leg_usd_dv01 * (dH_bp - dZ_bp)",
        "verify_1bp_flatten_dH0_dZ_neg1_usd": money_cents(achieved * (0 - (-1))),
        "verify_1bp_parallel_dH1_dZ1_usd": money_cents(achieved * (1 - 1)),
    }


def roll_one_quarter(data: dict) -> dict:
    corra_old = {k: find_corra_3m(data, e)["implied_rate"] for k, e in zip(LEG_KEYS, LEGS_2027)}
    sofr_old = {k: find_sofr_3m(data, e)["implied_rate"] for k, e in zip(LEG_KEYS, LEGS_2027)}
    corra_slide_from = {"H": "CRAZ26", "M": "CRAH27", "U": "CRAM27", "Z": "CRAU27"}
    sofr_slide_from = {"H": "SR3Z6", "M": "SR3H7", "U": "SR3M7", "Z": "SR3U7"}

    def rate_by_code_corra(code: str) -> float:
        for row in data["corra_3m"]:
            if row["code"] == code:
                return row["implied_rate"]
        raise KeyError(code)

    def rate_by_code_sofr(code: str) -> float:
        for row in data["sofr_3m"]:
            if row["code"] == code:
                return row["implied_rate"]
        raise KeyError(code)

    corra_new = {
        "H": rate_by_code_corra("CRAZ26"),
        "M": rate_by_code_corra("CRAH27"),
        "U": rate_by_code_corra("CRAM27"),
        "Z": rate_by_code_corra("CRAU27"),
    }
    sofr_new = {
        "H": rate_by_code_sofr("SR3Z6"),
        "M": rate_by_code_sofr("SR3H7"),
        "U": rate_by_code_sofr("SR3M7"),
        "Z": rate_by_code_sofr("SR3U7"),
    }

    def slide_block(old: dict, new: dict) -> dict:
        bp = {k: bp_diff(new[k], old[k]) for k in LEG_KEYS}
        return {
            "old_rates": old,
            "slide_source_rates": new,
            "slide_bp_by_leg": bp,
            "equal_weight_average_slide_bp": mean(list(bp.values())),
        }

    corra_roll = slide_block(corra_old, corra_new)
    sofr_roll = slide_block(sofr_old, sofr_new)

    h_slide_ca = corra_roll["slide_bp_by_leg"]["H"]
    z_slide_ca = corra_roll["slide_bp_by_leg"]["Z"]
    flattener_bp_dv01 = -(h_slide_ca) + z_slide_ca

    # Matched parallel DV01 books (25k USD/bp) with floored equal-lot sizing from section 6.
    cra_dv01_usd = 25.0 * (1.0 / data["fx"]["USDCAD"]["spot"])
    target_dv01 = 25_000.0
    cra_lots_roll = floor_toward_zero(target_dv01 / (4.0 * cra_dv01_usd))
    sr3_lots_roll = floor_toward_zero(target_dv01 / (4.0 * 25.0))
    pnl_ca_roll = sum(
        -cra_lots_roll * cra_dv01_usd * corra_roll["slide_bp_by_leg"][k] for k in LEG_KEYS
    )
    pnl_us_roll = sum(
        sr3_lots_roll * 25.0 * sofr_roll["slide_bp_by_leg"][k] for k in LEG_KEYS
    )
    cross_net_usd = money_cents(pnl_ca_roll + pnl_us_roll)
    cross_bp_per_matched_dv01 = cross_net_usd / target_dv01

    return {
        "assumption": "unchanged_tenor_roll_not_forecast",
        "CORRA_mapping": corra_slide_from,
        "SOFR_mapping": sofr_slide_from,
        "CORRA": corra_roll,
        "SOFR": sofr_roll,
        "flattener_pnl_bp_per_leg_dv01": flattener_bp_dv01,
        "cross_strip_receive_CA_roll_plus_pay_US_roll": {
            "CRA_floored_lots_per_leg": cra_lots_roll,
            "SR3_floored_lots_per_leg": sr3_lots_roll,
            "net_usd_matched_books": cross_net_usd,
            "bp_per_matched_dv01_usd_25000": cross_bp_per_matched_dv01,
            "usd_at_25000_per_bp": money_cents(cross_bp_per_matched_dv01 * target_dv01),
        },
    }


def build_shocks(roll: dict) -> Dict[str, dict]:
    ca0 = {k: 0.0 for k in LEG_KEYS}
    us0 = {k: 0.0 for k in LEG_KEYS}
    au0 = {"Dec": 0.0, "Jan": 0.0, "Feb": 0.0}
    roll_ca = roll["CORRA"]["slide_bp_by_leg"]
    roll_us = roll["SOFR"]["slide_bp_by_leg"]

    return {
        "S_parallel_selloff_25": {
            "CA": {k: 25.0 for k in LEG_KEYS},
            "US": {k: 25.0 for k in LEG_KEYS},
            "AONIA_dec_window": {k: 25.0 for k in au0},
        },
        "S_parallel_rally_25": {
            "CA": {k: -25.0 for k in LEG_KEYS},
            "US": {k: -25.0 for k in LEG_KEYS},
            "AONIA_dec_window": {k: -25.0 for k in au0},
        },
        "S_bull_flatten": {
            "CA": {"H": 10.0, "M": 0.0, "U": -10.0, "Z": -20.0},
            "US": dict(us0),
            "AONIA_dec_window": dict(au0),
        },
        "S_bear_steepen": {
            "CA": {"H": -10.0, "M": 5.0, "U": 10.0, "Z": 20.0},
            "US": dict(us0),
            "AONIA_dec_window": dict(au0),
        },
        "S_common_selloff_20": {
            "CA": {k: 20.0 for k in LEG_KEYS},
            "US": {k: 20.0 for k in LEG_KEYS},
            "AONIA_dec_window": {k: 20.0 for k in au0},
        },
        "S_canada_only_25": {
            "CA": {k: 25.0 for k in LEG_KEYS},
            "US": {k: 5.0 for k in LEG_KEYS},
            "AONIA_dec_window": {k: 5.0 for k in au0},
        },
        "S_deescalation": {
            "CA": {k: -30.0 for k in LEG_KEYS},
            "US": {k: -15.0 for k in LEG_KEYS},
            "AONIA_dec_window": {k: -15.0 for k in au0},
        },
        "S_roll_1q": {
            "CA": dict(roll_ca),
            "US": dict(roll_us),
            "AONIA_dec_window": dict(au0),
        },
    }


def pnl_paper_long_receive(avg_ca_bp: float) -> float:
    return money_cents(-25_000.0 * avg_ca_bp)


def pnl_real_cra_receive(lots: int, dv01_per_lot: float, ca_shock: dict) -> float:
    total = 0.0
    for k in LEG_KEYS:
        total += -lots * dv01_per_lot * ca_shock[k]
    return money_cents(total)


def pnl_flattener(achieved_leg_dv01: float, ca_shock: dict) -> float:
    return money_cents(achieved_leg_dv01 * (ca_shock["H"] - ca_shock["Z"]))


def pnl_ca_strip_vs_sofr_strip(
    cra_lots: int,
    cra_dv01: float,
    sr3_lots: int,
    sr3_dv01: float,
    ca_shock: dict,
    us_shock: dict,
) -> float:
    pnl = 0.0
    for k in LEG_KEYS:
        pnl += -cra_lots * cra_dv01 * ca_shock[k]
        pnl += sr3_lots * sr3_dv01 * us_shock[k]
    return money_cents(pnl)


def pnl_cra_z_vs_aonia_window(
    cra_z_lots: int,
    cra_dv01: float,
    aonia_lots: Dict[str, int],
    ib_dv01: float,
    ca_shock_z: float,
    aonia_shock: dict,
) -> float:
    pnl = -cra_z_lots * cra_dv01 * ca_shock_z
    month_keys = ("2027-12", "2028-01", "2028-02")
    shock_keys = ("Dec", "Jan", "Feb")
    for m, sk in zip(month_keys, shock_keys):
        pnl += aonia_lots[m] * ib_dv01 * aonia_shock[sk]
    return money_cents(pnl)


def expression_c_sizing(data: dict, fx: dict) -> dict:
    target = 25_000.0
    cra_dv01 = fx["CRA_dv01_usd_per_contract"]
    sr3_dv01 = fx["SR3_dv01_usd_per_contract"]
    ib_dv01 = fx["IB_dv01_usd_per_contract_published_basis"]

    cra_unrounded = target / (4.0 * cra_dv01)
    cra_lots = floor_toward_zero(cra_unrounded)
    sr3_unrounded = target / (4.0 * sr3_dv01)
    sr3_lots = floor_toward_zero(sr3_unrounded)

    cra_z_lots = floor_toward_zero(target / cra_dv01)
    sr3_z_lots = floor_toward_zero(target / sr3_dv01)

    third_target = target / 3.0
    aonia_months = ("2027-12", "2028-01", "2028-02")
    aonia_legs = {}
    for exp in aonia_months:
        row = find_aonia_1m(data, exp)
        unrounded = third_target / ib_dv01
        lots = floor_toward_zero(unrounded)
        aonia_legs[exp] = {
            "target_leg_usd_dv01_one_third": third_target,
            "unrounded_lots": unrounded,
            "floored_lots": lots,
            "achieved_leg_usd_dv01": lots * ib_dv01,
            "open_interest": row.get("open_interest"),
            "volume": row.get("volume"),
        }

    mar_row = find_aonia_1m(data, "2027-03")
    mar_lots = floor_toward_zero(target / ib_dv01)

    return {
        "four_leg_receive_CORRA_pay_SOFR_parallel_dv01_25000": {
            "CRA_unrounded_lots_per_leg": cra_unrounded,
            "CRA_floored_lots_per_leg": cra_lots,
            "CRA_achieved_book_parallel_dv01_usd": cra_lots * 4 * cra_dv01,
            "SR3_unrounded_lots_per_leg": sr3_unrounded,
            "SR3_floored_lots_per_leg": sr3_lots,
            "SR3_achieved_book_parallel_dv01_usd": sr3_lots * 4 * sr3_dv01,
        },
        "single_quarter_CRAZ27_receive_vs_SR3Z7_pay": {
            "CRA_unrounded_lots": target / cra_dv01,
            "CRA_floored_lots": cra_z_lots,
            "CRA_achieved_leg_dv01_usd": cra_z_lots * cra_dv01,
            "SR3_unrounded_lots": target / sr3_dv01,
            "SR3_floored_lots": sr3_z_lots,
            "SR3_achieved_leg_dv01_usd": sr3_z_lots * sr3_dv01,
        },
        "AONIA_pay_Dec_window_proxy_three_months": {
            "months": aonia_legs,
            "executable_evidence": "markable_from_inputs; OI/volume null on some months means not evidenced as executable",
        },
        "AONIA_pay_March_2027_only_contrast_25000_dv01": {
            "unrounded_lots": target / ib_dv01,
            "floored_lots": mar_lots,
            "achieved_leg_usd_dv01": mar_lots * ib_dv01,
            "open_interest": mar_row.get("open_interest"),
            "volume": mar_row.get("volume"),
        },
    }


def factor_line(lots: int, dv01_per_lot: float) -> dict:
    per_leg = {}
    for k in LEG_KEYS:
        per_leg[k] = money_cents(-lots * dv01_per_lot * 1.0)
    parallel = money_cents(sum(per_leg.values()))
    return {"plus_1bp_single_leg_usd": per_leg, "plus_1bp_parallel_all_legs_usd": parallel}


def run_all(inputs_path: Path) -> dict:
    data = load_inputs(inputs_path)
    fx = fx_block(data)
    ident = identity_checks(data, fx)
    paper = paper_engine(data)
    sizing_a = size_equal_lot_cra_receive(25_000.0, fx)
    expr_b_primary = size_expression_b(25_000.0, fx)
    expr_b_half = size_expression_b(12_500.0, fx)
    expr_c = expression_c_sizing(data, fx)
    roll = roll_one_quarter(data)
    shocks = build_shocks(roll)

    cra_lots = sizing_a["floored_lots_per_leg"]
    cra_dv01 = fx["CRA_dv01_usd_per_contract"]
    sr3_lots = expr_c["four_leg_receive_CORRA_pay_SOFR_parallel_dv01_25000"]["SR3_floored_lots_per_leg"]
    sr3_dv01 = fx["SR3_dv01_usd_per_contract"]
    flattener_dv01 = expr_b_primary["achieved_leg_usd_dv01"]
    cra_z_lots = expr_c["single_quarter_CRAZ27_receive_vs_SR3Z7_pay"]["CRA_floored_lots"]
    aonia_lots = {
        exp: expr_c["AONIA_pay_Dec_window_proxy_three_months"]["months"][exp]["floored_lots"]
        for exp in ("2027-12", "2028-01", "2028-02")
    }
    ib_dv01 = fx["IB_dv01_usd_per_contract_published_basis"]

    scenario_rows = {}
    ff = paper["forward_paper_funding_on_risk_capital_act360"]
    for name, shock in shocks.items():
        ca = shock["CA"]
        us = shock["US"]
        au = shock["AONIA_dec_window"]
        avg_ca = mean([ca[k] for k in LEG_KEYS])
        scenario_rows[name] = {
            "a_paper_long_receive_usd": pnl_paper_long_receive(avg_ca),
            "b_floored_equal_cra_receive_usd": pnl_real_cra_receive(cra_lots, cra_dv01, ca),
            "c_primary_flattener_usd": pnl_flattener(flattener_dv01, ca),
            "d_ca_strip_vs_sofr_strip_usd": pnl_ca_strip_vs_sofr_strip(
                expr_c["four_leg_receive_CORRA_pay_SOFR_parallel_dv01_25000"]["CRA_floored_lots_per_leg"],
                cra_dv01,
                sr3_lots,
                sr3_dv01,
                ca,
                us,
            ),
            "e_CRAZ27_vs_aonia_dec_window_usd": pnl_cra_z_vs_aonia_window(
                cra_z_lots,
                cra_dv01,
                aonia_lots,
                ib_dv01,
                ca["Z"],
                au,
            ),
            "paper_forward_funding_91d_usd_separate_line": ff["days_91_usd"],
            "paper_forward_funding_182d_usd_separate_line": ff["days_182_usd"],
            "ca_avg_bp_for_paper": avg_ca,
        }

    return {
        "inputs_path": str(inputs_path),
        "pinned_commit": data["identity"]["pinned_commit"],
        "section_1_identity": ident,
        "section_2_paper_engine": paper,
        "section_3_fx_and_dv01": fx,
        "section_4_equal_lot_cra_receive_sizing": sizing_a,
        "section_5_expression_B_flattener": {
            "primary_leg_dv01_25000": expr_b_primary,
            "half_gross_leg_dv01_12500": expr_b_half,
        },
        "section_6_expression_C": expr_c,
        "section_7_one_quarter_roll": roll,
        "section_8_scenarios_usd": scenario_rows,
        "section_9_factor_line_floored_equal_receive": factor_line(cra_lots, cra_dv01),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Composer A contract math from frozen inputs.")
    parser.add_argument(
        "frozen_inputs",
        nargs="?",
        default=str(DEFAULT_INPUTS),
        help="Path to frozen_inputs.json",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="Path for calc_results.json",
    )
    args = parser.parse_args()
    results = run_all(Path(args.frozen_inputs))
    out_path = Path(args.output)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, sort_keys=False)
        f.write("\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
