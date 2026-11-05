#!/usr/bin/env python3
"""Parent-specified scenario pricing from quant inputs/volatility/sensitivities only."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from statistics import median

QUANT = Path(__file__).resolve().parent


def load(name: str) -> dict:
    return json.loads((QUANT / name).read_text())


def spot_pnl(n: float, s0: float, s1: float) -> float:
    return n * (s1 / s0 - 1.0)


def carry_drag(n: float, gap_bp: float, days: int) -> float:
    return n * (gap_bp / 10000.0) * (days / 360.0)


def receive_pnl_bp(anchor: float, scenario: float, dv01_per_bp: float) -> float:
    """Receive: rate down vs anchor -> gain. Rates in percent."""
    bp = (anchor - scenario) * 100.0
    return bp * dv01_per_bp


def adverse_receive_pnl(adverse_bp: float, dv01_per_bp: float) -> float:
    return -adverse_bp * dv01_per_bp


def main() -> None:
    inputs = load("inputs.json")
    vol = load("volatility.json")
    sens = load("sensitivities.json")

    s0 = inputs["last_close"]
    anchor_date = inputs["last_date"]
    usdcad = sens["cad_lot_illustration"]["USDCAD"]
    usd_per_bp_lot = sens["cad_lot_illustration"]["usd_per_bp_per_cad_1mm_lot"]

    csv_rows = list(csv.DictReader((QUANT / "series_eurusd.csv").open()))
    closes = [float(r["close"]) for r in csv_rows]
    csv_min = min(closes)
    csv_median = median(closes)

    near = s0 * (s0 / 1.1179)
    far = 1.14715
    exit_px = 1.1179
    stress = 1.113
    price_checks = {
        "near_from_prior_ratio": near,
        "far_stored_median": far,
        "far_confirmed_from_csv_median": abs(csv_median - far) < 1e-9,
        "exit_prior_close": exit_px,
        "stress_level": stress,
        "stress_is_stored_csv_minimum": abs(csv_min - stress) < 1e-9,
        "csv_min_close": csv_min,
        "csv_median_close": csv_median,
    }

    scenario_prices = {
        "near": near,
        "far": far,
        "exit": exit_px,
        "stress": stress,
    }

    gap_2y_bp = inputs["sofr_estr"]["US_2Y_2026_11_04"]["gap_us_minus_ea_bp"]
    sofr = inputs["sofr_estr"]["SOFR_fixing"]["rate_percent"]
    estr = inputs["sofr_estr"]["ESTR_fixing"]["rate_percent"]
    gap_sofr_estr_bp = (sofr - estr) * 100.0

    declined_n = [5_000_000, 10_000_000]
    eurusd_adopted = {
        "action": "REJECT",
        "notional_usd": 0,
        "anchor_spot": s0,
        "anchor_date": anchor_date,
        "label": "adopted",
    }
    eurusd_declined: dict = {
        "label": "declined_not_adopted",
        "notionals_usd": declined_n,
        "spot_pnl_by_price": {},
        "carry_drag_usd": {},
    }
    for n in declined_n:
        eurusd_declined["spot_pnl_by_price"][str(n)] = {
            k: spot_pnl(n, s0, p) for k, p in scenario_prices.items()
        }
        eurusd_declined["carry_drag_usd"][str(n)] = {}
        for days in [56, 84]:
            eurusd_declined["carry_drag_usd"][str(n)][str(days)] = {
                f"gap_{gap_2y_bp}bp": carry_drag(n, gap_2y_bp, days),
                f"gap_{gap_sofr_estr_bp}bp_sofr_minus_estr": carry_drag(
                    n, gap_sofr_estr_bp, days
                ),
            }

    ys = vol["eurusd"]["yardsticks"]
    sigma20 = ys["daily_sigma_20"]["value"]
    sigma60 = ys["daily_sigma_60"]["value"]
    yard_sigma20 = {
        h: ys["horizon_yardsticks_sigma20"][h]["approx_simple_percent"]
        for h in ["10", "21", "42", "63"]
    }
    exc = vol["eurusd"]["empirical_excursions_overlapping"]
    context_moves = {
        "eur_oct30_to_nov3_simple_percent": 100.0 * (1.1179 / 1.1172 - 1.0),
        "wti_oct30_to_nov3_simple_percent": 100.0
        * (96.08999633789062 / 104.12000274658203 - 1.0),
        "note": "WTI levels parent-specified; not from quant vol series",
    }

    eurusd_block = {
        "adopted": eurusd_adopted,
        "declined_illustration": eurusd_declined,
        "price_level_checks": price_checks,
        "volatility_context": {
            "daily_log_sigma_20": sigma20,
            "daily_log_sigma_60": sigma60,
            "yardstick_simple_percent_sigma20_h": yard_sigma20,
            "label_yardstick": "YARDSTICK not probability",
            "overlapping_excursions_simple_percent": {
                "21": {
                    "worst": exc["21"]["worst_simple_percent"],
                    "best": exc["21"]["best_simple_percent"],
                },
                "63": {
                    "worst": exc["63"]["worst_simple_percent"],
                    "best": exc["63"]["best_simple_percent"],
                },
            },
        },
        "context_simple_moves": context_moves,
        "carry_gaps_bp": {
            "us_minus_ea_2y_2026_11_04": gap_2y_bp,
            "sofr_minus_estr": gap_sofr_estr_bp,
        },
    }

    anchor_strip = inputs["corra_strip"]["equal_weight_average_implied_rate"]
    central_legs = [2.90, 2.98, 3.05, 3.10]
    central_avg = sum(central_legs) / 4.0
    floor, ceiling = 2.80, 3.20
    gap_central_bp = (anchor_strip - central_avg) * 100.0

    sizes = [
        {"label": "adopted", "notional_usd": 100_000_000, "dv01_usd_per_bp": 10_000},
        {
            "label": "not_adopted_full_size",
            "notional_usd": 250_000_000,
            "dv01_usd_per_bp": 25_000,
        },
    ]

    def pnl_scenarios(dv01: float) -> dict:
        return {
            "tradable_target_strip_3.03375_minus_8bp_vs_anchor": receive_pnl_bp(
                anchor_strip, 3.03375, dv01
            ),
            "exit_strip_3.26375_plus_15bp_vs_anchor": receive_pnl_bp(
                anchor_strip, 3.26375, dv01
            ),
            "noise_marker_3.19375_plus_8bp_vs_anchor": receive_pnl_bp(
                anchor_strip, 3.19375, dv01
            ),
            "central_shape_avg_3.0075": receive_pnl_bp(anchor_strip, central_avg, dv01),
            "adverse_20bp": adverse_receive_pnl(20, dv01),
            "adverse_25bp": adverse_receive_pnl(25, dv01),
            "adverse_30bp": adverse_receive_pnl(30, dv01),
        }

    funding_rate = 0.0395
    funding = {}
    for sz in sizes:
        draw = 1_000_000 if sz["notional_usd"] == 100_000_000 else 2_500_000
        funding[sz["label"]] = {
            d: funding_rate * draw * d / 360.0 for d in [56, 84]
        }

    daily_sigma20_bp = inputs["ca2y_proxy"]["daily_change_bp_sample_std_20"]
    proxy_yard = {
        "label": "SOVEREIGN_PROXY_YARDSTICK",
        "daily_bp_sigma_20_obs": daily_sigma20_bp,
        "horizon_bp": {
            str(h): daily_sigma20_bp * math.sqrt(h) for h in [21, 42, 63]
        },
    }
    exit_adverse_bp = 15.0
    yard_21 = proxy_yard["horizon_bp"]["21"]
    inside_21 = exit_adverse_bp <= yard_21

    sign = sens["sign_checks"]

    corra_block = {
        "adopted": {
            "action": "RESIZE",
            "side": "receive",
            "notional_usd": 100_000_000,
            "dv01_usd_per_bp": 10_000,
            "anchor_strip_average": anchor_strip,
        },
        "comparison_not_adopted_full_size": {
            "notional_usd": 250_000_000,
            "dv01_usd_per_bp": 25_000,
            "label": "not_adopted_full_size",
        },
        "central_shape": {
            "leg_rates_percent": central_legs,
            "average": central_avg,
            "average_must_equal": 3.0075,
            "average_matches": abs(central_avg - 3.0075) < 1e-12,
            "gap_bp_anchor_minus_central": gap_central_bp,
        },
        "anchor_distance_bp": {
            "to_floor_2.80": (anchor_strip - floor) * 100.0,
            "to_ceiling_3.20": (ceiling - anchor_strip) * 100.0,
        },
        "scenario_pnl_usd": {sz["label"]: pnl_scenarios(sz["dv01_usd_per_bp"]) for sz in sizes},
        "funding_cost_usd": funding,
        "sovereign_proxy_yardstick": proxy_yard,
        "exit_plus_15bp_inside_21obs_proxy_yardstick": {
            "adverse_bp": exit_adverse_bp,
            "yardstick_21_obs_bp": yard_21,
            "inside": inside_21,
        },
        "lot_illustration": {
            "label": "ILLUSTRATION",
            "USDCAD": usdcad,
            "usd_per_bp_per_cad_1mm_lot": usd_per_bp_lot,
            "lots_per_contract_strip_four_legs": {
                "dv01_10000": (10_000 / 4) / usd_per_bp_lot,
                "dv01_25000": (25_000 / 4) / usd_per_bp_lot,
            },
            "formula": "lots = (dv01/4)/usd_per_bp",
        },
        "sign_checks_receive": sign,
        "strip_history_status": inputs["corra_strip"]["strip_history_status"],
    }

    plan = {
        "source_files": ["inputs.json", "volatility.json", "sensitivities.json", "series_eurusd.csv"],
        "note": "Parent-specified scenarios; not investment recommendation",
        "EURUSD": eurusd_block,
        "CORRA": corra_block,
    }

    out = QUANT / "decision_plan.json"
    out.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    print("Wrote", out)


if __name__ == "__main__":
    main()
