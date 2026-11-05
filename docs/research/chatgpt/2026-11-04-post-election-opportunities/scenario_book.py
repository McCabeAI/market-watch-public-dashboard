#!/usr/bin/env python3
"""Portfolio rival scenario P&L (stdlib). Recomputes from pinned constants; calc_results.json cross-check only."""

from __future__ import annotations

import json
import math
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CALC_RESULTS = SCRIPT_DIR / "calc_results.json"
OUTPUT = SCRIPT_DIR / "portfolio_scenarios.json"

# --- Verified constants (source: calc_results.json fields cited in comments) ---
# strip_and_book.corra_2027_rates, corra_equal_weight_mean, cash_fixings
CORRA_HMUZ = {"H": 2.97, "M": 3.115, "U": 3.225, "Z": 3.31}
CORRA_MEAN = 3.155  # calc_results strip_and_book.corra_equal_weight_mean
CORRA_CASH = 2.54
PREMIUM_BP = 61.5

# dv01_and_fx
USDCAD = 1.3975310850702212  # calc_results dv01_and_fx.USDCAD_spot_CAD_per_USD
CRA_USD_PER_BP_LOT = 17.88868975228829  # CRA_usd_per_bp_per_lot_ASSUMPTION
SR3_USD_PER_BP_LOT = 25.0  # SR3_usd_per_bp_per_lot_ASSUMPTION
PAPER_DV01_250M = 25000.0  # paper_dv01_usd_per_bp_at_250m_notional

LOTS_4LEG = 349  # research_budgets 25000 receive_4leg floored_lots_per_leg
SR3_LOTS_MATCHED_25K = 250  # pay_4leg_SR3_matched_dv01 at 25000/bp

# one_quarter_roll.CORRA_slide_bp_by_leg / SOFR_slide_bp_by_leg
ROLL_CORRA_BP = {"H": -22.0, "M": -14.5, "U": -11.0, "Z": -8.5}
ROLL_SOFR_BP = {"H": -20.5, "M": -13.0, "U": -4.0, "Z": 2.0}

SOFR_RATE = 0.0395
DAY_COUNT = 360
DAYS_30 = 30

LEG_KEYS = ("H", "M", "U", "Z")


def money(x: float) -> float:
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def parallel_dv01_4leg(lots_per_leg: int) -> float:
    return lots_per_leg * 4 * CRA_USD_PER_BP_LOT


def parallel_dv01_uz(lots_per_leg: int) -> float:
    return lots_per_leg * 2 * CRA_USD_PER_BP_LOT


def risk_capital_from_dv01(parallel_dv01_usd_per_bp: float) -> float:
    """Book: 1% of notional ≈ 100 × USD/bp parallel DV01 at 250m mapping."""
    return parallel_dv01_usd_per_bp * 100.0


def financing_30d(risk_capital: float) -> float:
    return money(risk_capital * SOFR_RATE * DAYS_30 / DAY_COUNT)


def pnl_receive_cra(
    lots_by_leg: dict[str, int], ca_shock_bp: dict[str, float]
) -> float:
    total = 0.0
    for k in LEG_KEYS:
        lots = lots_by_leg.get(k, 0)
        if lots:
            total += -lots * CRA_USD_PER_BP_LOT * ca_shock_bp[k]
    return money(total)


def pnl_pay_sr3(
    lots_per_leg: int, us_shock_bp: dict[str, float]
) -> float:
    """Pay leg gains when rates rise: +DV01 * shock_bp."""
    total = 0.0
    for k in LEG_KEYS:
        total += lots_per_leg * SR3_USD_PER_BP_LOT * us_shock_bp[k]
    return money(total)


def pnl_pay_h_receive_z(leg_dv01: float, ca_shock_bp: dict[str, float]) -> float:
    """Pay H / receive Z on equal leg DV01: (shock_H - shock_Z) * leg_dv01."""
    return money(leg_dv01 * (ca_shock_bp["H"] - ca_shock_bp["Z"]))


def avg_shock(shocks: dict[str, float]) -> float:
    return sum(shocks[k] for k in LEG_KEYS) / 4.0


def paper_strip_pnl(parallel_dv01: float, ca_shock_bp: dict[str, float]) -> float:
    return money(-parallel_dv01 * avg_shock(ca_shock_bp))


def fx_pnl_long_cadnok(notional_usd_equiv: float, cadnok_move_fraction: float) -> float:
    return money(notional_usd_equiv * cadnok_move_fraction)


def fx_pnl_long_nzdusd(notional_usd: float, move_fraction: float) -> float:
    return money(notional_usd * move_fraction)


SCENARIOS: dict[str, dict] = {
    "common_plus_20": {
        "label": "Common +20bp CRA and SR3",
        "CA": {k: 20.0 for k in LEG_KEYS},
        "US": {k: 20.0 for k in LEG_KEYS},
    },
    "common_minus_20": {
        "label": "Common -20bp CRA and SR3",
        "CA": {k: -20.0 for k in LEG_KEYS},
        "US": {k: -20.0 for k in LEG_KEYS},
    },
    "canada_plus_25_us_plus_5": {
        "label": "Canada +25bp, US +5bp (domestic inflation / oil pass-through sketch)",
        "CA": {k: 25.0 for k in LEG_KEYS},
        "US": {k: 5.0 for k in LEG_KEYS},
    },
    "canada_minus_15_us_minus_10": {
        "label": "Canada -15bp, US -10bp (small de-escalation in rates)",
        "CA": {k: -15.0 for k in LEG_KEYS},
        "US": {k: -10.0 for k in LEG_KEYS},
    },
    "article_treasury_minus_5_ASSUMPTION": {
        "label": "ASSUMPTION: article Treasury move (~4-5bp) repeated in CRA/SR3",
        "CA": {k: -5.0 for k in LEG_KEYS},
        "US": {k: -5.0 for k in LEG_KEYS},
    },
    "renewed_conflict": {
        "label": "Renewed conflict: Canada +20, US +10; FX if held",
        "CA": {k: 20.0 for k in LEG_KEYS},
        "US": {k: 10.0 for k in LEG_KEYS},
        "fx_cadnok_frac": -0.015,
        "fx_audusd_frac": -0.015,
    },
    "us_fiscal_disappointment_long_end": {
        "label": "US fiscal disappointment hits long end; no TY — STIR ~0 by construction",
        "CA": {k: 0.0 for k in LEG_KEYS},
        "US": {k: 0.0 for k in LEG_KEYS},
    },
    "global_inflation_repricing": {
        "label": "Global inflation repricing: Canada +15, US +15",
        "CA": {k: 15.0 for k in LEG_KEYS},
        "US": {k: 15.0 for k in LEG_KEYS},
    },
    "canada_domestic_surprise": {
        "label": "Canada domestic surprise: Canada +20, US 0",
        "CA": {k: 20.0 for k in LEG_KEYS},
        "US": {k: 0.0 for k in LEG_KEYS},
    },
    "one_quarter_unchanged_curve_roll_ASSUMPTION": {
        "label": "One-quarter unchanged-curve roll (assumption, not accrual)",
        "CA": dict(ROLL_CORRA_BP),
        "US": dict(ROLL_SOFR_BP),
    },
    "bull_flatten_corra_ASSUMPTION": {
        "label": "Bull flatten CORRA: H+10 M0 U-10 Z-20 (assumption)",
        "CA": {"H": 10.0, "M": 0.0, "U": -10.0, "Z": -20.0},
        "US": {k: 0.0 for k in LEG_KEYS},
    },
    "bear_steepen_corra_ASSUMPTION": {
        "label": "Bear steepen CORRA: H-5 Z+15 (assumption)",
        "CA": {"H": -5.0, "M": 0.0, "U": 0.0, "Z": 15.0},
        "US": {k: 0.0 for k in LEG_KEYS},
    },
}


def rival_r0_flat() -> dict:
    return {
        "id": "R0",
        "name": "Flat after closing residual; no FX",
        "positions": [],
        "parallel_dv01_usd_per_bp": 0.0,
        "risk_capital_usd": 0.0,
        "financing_30d_usd": 0.0,
        "fx_legs": [],
    }


def rival_r1_retain() -> dict:
    lots = {k: LOTS_4LEG for k in LEG_KEYS}
    pdv01 = parallel_dv01_4leg(LOTS_4LEG)
    rc = risk_capital_from_dv01(pdv01)
    return {
        "id": "R1",
        "name": "Retain 250m equal-weight CORRA receive (349 lots × 4)",
        "positions": ["receive_CRA_2027_HMUZ_349_each"],
        "lots_by_leg": lots,
        "parallel_dv01_usd_per_bp": money(pdv01),
        "risk_capital_usd": money(rc),
        "financing_30d_usd": financing_30d(rc),
        "sr3_pay_overlay": None,
        "fx_legs": [],
    }


def rival_r2_uz() -> dict:
    lots = {"H": 0, "M": 0, "U": LOTS_4LEG, "Z": LOTS_4LEG}
    pdv01 = parallel_dv01_uz(LOTS_4LEG)
    rc = risk_capital_from_dv01(pdv01)
    return {
        "id": "R2",
        "name": "Prior reshape: receive U and Z only, 349 lots each",
        "positions": ["receive_CRAU27_CRAZ27_349_each"],
        "lots_by_leg": lots,
        "parallel_dv01_usd_per_bp": money(pdv01),
        "risk_capital_usd": money(rc),
        "financing_30d_usd": financing_30d(rc),
        "sr3_pay_overlay": None,
        "fx_legs": [],
    }


def rival_r3_playbook() -> dict:
    return {
        "id": "R3",
        "name": "Close; conditionals + at most one FX — zero current risk",
        "positions": [],
        "parallel_dv01_usd_per_bp": 0.0,
        "risk_capital_usd": 0.0,
        "financing_30d_usd": 0.0,
        "fx_legs": [],
        "conditionals_off_book": True,
    }


def rival_r4_considered() -> dict:
    """Smallest promoted idea considered: none — rates/FX both fail from-flat."""
    return {
        "id": "R4",
        "name": "Considered hold-now alternative (rejected)",
        "positions": [],
        "parallel_dv01_usd_per_bp": 0.0,
        "risk_capital_usd": 0.0,
        "financing_30d_usd": 0.0,
        "fx_legs": [],
        "note": "No leg clears READY; promoting CORRA conditional without marks would duplicate R3 with risk.",
    }


def evaluate_rival(rival: dict, scenario_key: str, sc: dict) -> dict:
    ca = sc["CA"]
    us = sc.get("US", {k: 0.0 for k in LEG_KEYS})
    fin = rival["financing_30d_usd"]

    if rival["parallel_dv01_usd_per_bp"] == 0:
        return {
            "market_pnl_usd": 0.0,
            "financing_30d_usd": 0.0,
            "net_pnl_usd": 0.0,
            "components": {},
        }

    lots_by_leg = rival.get("lots_by_leg") or {k: LOTS_4LEG for k in LEG_KEYS}
    cra_pnl = pnl_receive_cra(lots_by_leg, ca)
    sr3_pnl = 0.0
    if rival.get("sr3_pay_overlay"):
        sr3_pnl = pnl_pay_sr3(SR3_LOTS_MATCHED_25K, us)

    fx_pnl = 0.0
    if sc.get("fx_cadnok_frac") and any(
        leg.get("pair") == "CADNOK" for leg in rival.get("fx_legs", [])
    ):
        fx_pnl += fx_pnl_long_cadnok(40_000_000, sc["fx_cadnok_frac"])
    if sc.get("fx_audusd_frac") and any(
        leg.get("pair") == "AUDUSD" for leg in rival.get("fx_legs", [])
    ):
        fx_pnl += fx_pnl_long_nzdusd(30_000_000, sc["fx_audusd_frac"])

    market = money(cra_pnl + sr3_pnl + fx_pnl)
    return {
        "market_pnl_usd": market,
        "financing_30d_usd": fin,
        "net_pnl_usd": money(market - fin),
        "components": {
            "cra_receive_usd": cra_pnl,
            "sr3_pay_usd": sr3_pnl,
            "fx_usd": fx_pnl,
        },
    }


def self_checks() -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []

    # Matched pay + receive flat on common parallel (exact DV01 match, not floored lots)
    recv = pnl_receive_cra({k: LOTS_4LEG for k in LEG_KEYS}, {k: 20.0 for k in LEG_KEYS})
    cra_parallel = parallel_dv01_4leg(LOTS_4LEG)
    sr3_lots_exact = cra_parallel / (4.0 * SR3_USD_PER_BP_LOT)
    pay = sum(
        sr3_lots_exact * SR3_USD_PER_BP_LOT * 20.0 for _ in LEG_KEYS
    )
    pay = money(pay)
    combined = recv + pay
    ok_flat = abs(combined) <= 1.0
    checks.append(
        (
            "matched_pay_receive_common_plus_20",
            ok_flat,
            f"combined={combined} (recv={recv}, pay={pay})",
        )
    )

    expected_fin = money(2_500_000 * SOFR_RATE * DAYS_30 / DAY_COUNT)
    fin_25k = financing_30d(risk_capital_from_dv01(PAPER_DV01_250M))
    ok_fin = abs(fin_25k - expected_fin) < 0.02
    checks.append(
        (
            "financing_30d_25000_dv01",
            ok_fin,
            f"got={fin_25k} expected={expected_fin}",
        )
    )

    # Document calc_results sign bug on common_plus_20
    try:
        with CALC_RESULTS.open(encoding="utf-8") as f:
            calc = json.load(f)
        sk = calc["scenario_skeletons_usd_assumption_paths"]["scenarios"]["common_plus_20"]
        bug_pay = sk["futures_pay_4leg_sr3_matched_usd"]
        checks.append(
            (
                "calc_results_sr3_pay_sign_bug_present",
                bug_pay < 0,
                f"calc common_plus_20 sr3_pay={bug_pay} (should be +500000 with correct pay sign)",
            )
        )
    except OSError:
        checks.append(("calc_results_readable", False, "missing calc_results.json"))

    return checks


def load_calc_crosscheck() -> dict | None:
    try:
        with CALC_RESULTS.open(encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return None


def main() -> int:
    rivals = [
        rival_r0_flat(),
        rival_r1_retain(),
        rival_r2_uz(),
        rival_r3_playbook(),
        rival_r4_considered(),
    ]
    proposed = "R0"

    results = {
        "written": "2026-11-05",
        "evidence_cycle": "2026-11-04",
        "proposed_rival_id": proposed,
        "constants_source": "calc_results.json (verified fields; SR3 pay sign corrected in this script)",
        "sign_correction": {
            "receive_pnl": "-DV01 * shock_bp",
            "pay_pnl": "+DV01 * shock_bp",
            "calc_portfolio_math_bug": "pnl_pay_sofr_lots uses -lots*dv01*shock (same as receive)",
        },
        "financing_convention": {
            "rate": SOFR_RATE,
            "day_count": f"ACT/{DAY_COUNT}",
            "risk_capital": "100 * parallel_dv01_usd_per_bp (1% of 250m mapping)",
        },
        "rivals": {},
        "self_checks": [],
    }

    for rival in rivals:
        rid = rival["id"]
        row = {
            "meta": {k: v for k, v in rival.items() if k not in ("lots_by_leg",)},
            "scenarios": {},
        }
        for skey, sc in SCENARIOS.items():
            row["scenarios"][skey] = {
                "label": sc["label"],
                **evaluate_rival(rival, skey, sc),
            }
        results["rivals"][rid] = row

    # Corrected reference: R1 common+20 for audit trail
    r1_cra = pnl_receive_cra({k: LOTS_4LEG for k in LEG_KEYS}, {k: 20.0 for k in LEG_KEYS})
    r1_sr3_correct = pnl_pay_sr3(SR3_LOTS_MATCHED_25K, {k: 20.0 for k in LEG_KEYS})
    results["audit_r1_common_plus_20"] = {
        "cra_receive_usd": r1_cra,
        "sr3_pay_overlay_correct_usd": r1_sr3_correct,
        "overlay_net_usd": money(r1_cra + r1_sr3_correct),
        "calc_results_combined_wrong_usd": -999452.22,
    }

    checks = self_checks()
    all_pass = True
    for name, ok, detail in checks:
        results["self_checks"].append({"name": name, "pass": ok, "detail": detail})
        if not ok and name not in ("calc_results_sr3_pay_sign_bug_present",):
            all_pass = False
        if name == "matched_pay_receive_common_plus_20" and not ok:
            all_pass = False
        if name == "financing_30d_25000_dv01" and not ok:
            all_pass = False

    calc = load_calc_crosscheck()
    if calc:
        rederived = calc["strip_and_book"]["corra_equal_weight_mean"]
        results["crosscheck_strip_mean"] = {
            "calc_results": rederived,
            "constants_used": CORRA_MEAN,
            "match": abs(rederived - CORRA_MEAN) < 1e-9,
        }

    with OUTPUT.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, sort_keys=False)
        f.write("\n")

    print("Self-checks:")
    for name, ok, detail in checks:
        status = "PASS" if ok else "FAIL"
        if name == "calc_results_sr3_pay_sign_bug_present":
            status = "PASS" if ok else "NOTE"
        print(f"  {status}: {name} — {detail}")

    overall = "PASS" if all_pass else "FAIL"
    print(overall)
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
