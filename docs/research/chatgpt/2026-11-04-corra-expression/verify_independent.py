#!/usr/bin/env python3
"""Independent recompute from frozen_inputs.json vs calc_results.json (Composer V)."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[3]
FROZEN = SCRIPT_DIR / "frozen_inputs.json"
CALC_RESULTS = SCRIPT_DIR / "calc_results.json"
PINNED_COMMIT = "612666a21e621e6bb437802cb48ace011f181b7b"
SNAPSHOT_GIT_PATH = (
    "data/overnight/runs/overnight-20261104/reviews/review-001/evidence_snapshot.json"
)

LEGS_2027 = ("2027-03", "2027-06", "2027-09", "2027-12")
LEG_KEYS = ("H", "M", "U", "Z")
TOL_RATE = 1e-9
TOL_BP = 1e-6
TOL_USD = 0.02


@dataclass
class Check:
    name: str
    passed: bool
    expected: Any
    computed: Any
    note: str = ""


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


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


def close(a: float, b: float, tol: float = TOL_RATE) -> bool:
    return abs(a - b) <= tol


def find_corra_3m(data: dict, expiry: str) -> dict:
    for row in data["corra_3m"]:
        if row["expiry"] == expiry:
            return row
    raise KeyError(expiry)


def find_sofr_3m(data: dict, expiry: str) -> dict:
    for row in data["sofr_3m"]:
        if row["expiry"] == expiry:
            return row
    raise KeyError(expiry)


def find_aonia_1m(data: dict, expiry: str) -> dict:
    for row in data["aonia_1m"]:
        if row["expiry"] == expiry:
            return row
    raise KeyError(expiry)


def rate_by_code_corra(data: dict, code: str) -> float:
    for row in data["corra_3m"]:
        if row["code"] == code:
            return row["implied_rate"]
    raise KeyError(code)


def rate_by_code_sofr(data: dict, code: str) -> float:
    for row in data["sofr_3m"]:
        if row["code"] == code:
            return row["implied_rate"]
    raise KeyError(code)


def compare_float(name: str, computed: float, expected: float, tol: float = TOL_RATE) -> Check:
    return Check(
        name=name,
        passed=close(computed, expected, tol),
        expected=expected,
        computed=computed,
    )


def compare_usd(name: str, computed: float, expected: float) -> Check:
    return compare_float(name, computed, expected, TOL_USD)


def load_snapshot_market_state() -> Optional[dict]:
    try:
        out = subprocess.run(
            ["git", "show", f"{PINNED_COMMIT}:{SNAPSHOT_GIT_PATH}"],
            capture_output=True,
            text=True,
            check=True,
            cwd=REPO_ROOT,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    snap = json.loads(out.stdout)
    return snap["families"]["market_state"]["data"]


def verify_frozen_vs_snapshot(frozen: dict, checks: List[Check]) -> None:
    ms = load_snapshot_market_state()
    if ms is None:
        checks.append(
            Check(
                "snapshot_pin_available",
                False,
                "git show snapshot",
                None,
                note="Could not read pinned evidence_snapshot.json",
            )
        )
        return

    pairs = ms["fx"]["pairs"]
    countries = ms["policy_paths"]["countries"]
    fields = [
        ("USDCAD spot", frozen["fx"]["USDCAD"]["spot"], pairs["USDCAD"]["spot"]),
        ("AUDUSD spot", frozen["fx"]["AUDUSD"]["spot"], pairs["AUDUSD"]["spot"]),
        (
            "CORRA cash",
            frozen["benchmarks"]["CORRA"]["rate"],
            countries["CA"]["benchmark"]["rate"],
        ),
        (
            "SOFR cash",
            frozen["benchmarks"]["SOFR"]["rate"],
            countries["US"]["benchmark"]["rate"],
        ),
        (
            "AONIA cash",
            frozen["benchmarks"]["AONIA"]["rate"],
            countries["AU"]["benchmark"]["rate"],
        ),
    ]
    for label, fv, sv in fields:
        checks.append(compare_float(f"snapshot_match_{label}", fv, sv))

    for expiry in LEGS_2027:
        fc = find_corra_3m(frozen, expiry)["implied_rate"]
        sc = next(
            r["implied_rate"]
            for r in countries["CA"]["contracts_3m"]
            if r["expiry"] == expiry
        )
        checks.append(compare_float(f"snapshot_match_CRA_{expiry}", fc, sc))
        fs = find_sofr_3m(frozen, expiry)["implied_rate"]
        ss = next(
            r["implied_rate"]
            for r in countries["US"]["contracts_3m"]
            if r["expiry"] == expiry
        )
        checks.append(compare_float(f"snapshot_match_SR3_{expiry}", fs, ss))


def recompute_all(frozen: dict, calc: dict) -> Tuple[List[Check], dict]:
    checks: List[Check] = []
    s1 = calc["section_1_identity"]
    s3 = calc["section_3_fx_and_dv01"]
    s4 = calc["section_4_equal_lot_cra_receive_sizing"]
    s5 = calc["section_5_expression_B_flattener"]["primary_leg_dv01_25000"]
    s7 = calc["section_7_one_quarter_roll"]
    s8 = calc["section_8_scenarios_usd"]

    corra_rates = [find_corra_3m(frozen, e)["implied_rate"] for e in LEGS_2027]
    sofr_rates = [find_sofr_3m(frozen, e)["implied_rate"] for e in LEGS_2027]
    corra_mean = mean(corra_rates)
    sofr_mean = mean(sofr_rates)
    checks.append(compare_float("corra_equal_weight_mean", corra_mean, s1["corra_equal_weight_mean"]))
    checks.append(compare_float("sofr_equal_weight_mean", sofr_mean, s1["sofr_equal_weight_mean"]))
    checks.append(
        compare_float("corra_H_to_Z_bp", bp_diff(corra_rates[3], corra_rates[0]), s1["corra_H_to_Z_bp"], TOL_BP)
    )
    checks.append(
        compare_float("sofr_H_to_Z_bp", bp_diff(sofr_rates[3], sofr_rates[0]), s1["sofr_H_to_Z_bp"], TOL_BP)
    )

    for i, exp in enumerate(LEGS_2027):
        spread = bp_diff(sofr_rates[i], corra_rates[i])
        checks.append(
            compare_float(
                f"us_minus_ca_spread_{exp}",
                spread,
                s1["us_minus_ca_spread_bp_by_expiry"][exp],
                TOL_BP,
            )
        )

    steep = bp_diff(corra_rates[3], corra_rates[0]) - bp_diff(sofr_rates[3], sofr_rates[0])
    checks.append(
        compare_float(
            "ca_minus_us_H_to_Z_steepener_diff_bp",
            steep,
            s1["ca_minus_us_H_to_Z_steepener_diff_bp"],
            TOL_BP,
        )
    )

    corra_cash = frozen["benchmarks"]["CORRA"]["rate"]
    sofr_cash = frozen["benchmarks"]["SOFR"]["rate"]
    aonia_cash = frozen["benchmarks"]["AONIA"]["rate"]
    for exp, r in zip(LEGS_2027, corra_rates):
        checks.append(
            compare_float(
                f"corra_premium_{exp}",
                premium_bp(r, corra_cash),
                s1["premium_vs_own_cash_bp"]["CORRA_by_leg"][exp],
                TOL_BP,
            )
        )
    for exp, r in zip(LEGS_2027, sofr_rates):
        checks.append(
            compare_float(
                f"sofr_premium_{exp}",
                premium_bp(r, sofr_cash),
                s1["premium_vs_own_cash_bp"]["SOFR_by_leg"][exp],
                TOL_BP,
            )
        )

    aonia_q = {
        "Mar_Apr_May": mean(
            [
                find_aonia_1m(frozen, "2027-03")["implied_rate"],
                find_aonia_1m(frozen, "2027-04")["implied_rate"],
                find_aonia_1m(frozen, "2027-05")["implied_rate"],
            ]
        ),
        "Jun_Jul_Aug": mean(
            [
                find_aonia_1m(frozen, "2027-06")["implied_rate"],
                find_aonia_1m(frozen, "2027-07")["implied_rate"],
                find_aonia_1m(frozen, "2027-08")["implied_rate"],
            ]
        ),
        "Sep_Oct_Nov": mean(
            [
                find_aonia_1m(frozen, "2027-09")["implied_rate"],
                find_aonia_1m(frozen, "2027-10")["implied_rate"],
                find_aonia_1m(frozen, "2027-11")["implied_rate"],
            ]
        ),
        "Dec27_Jan28_Feb28": mean(
            [
                find_aonia_1m(frozen, "2027-12")["implied_rate"],
                find_aonia_1m(frozen, "2028-01")["implied_rate"],
                find_aonia_1m(frozen, "2028-02")["implied_rate"],
            ]
        ),
    }
    ref = s1["aonia_labeled_quarterly_proxy_rates"]
    for k, v in aonia_q.items():
        checks.append(compare_float(f"aonia_quarter_{k}", v, ref[k]))

    usdcad = frozen["fx"]["USDCAD"]["spot"]
    audusd = frozen["fx"]["AUDUSD"]["spot"]
    usd_per_cad = 1.0 / usdcad
    cra_dv01_usd = 25.0 * usd_per_cad
    ib_dv01_usd = 24.66 * audusd
    checks.append(compare_float("usd_per_cad", usd_per_cad, s3["usd_per_cad"]))
    checks.append(compare_float("CRA_dv01_usd", cra_dv01_usd, s3["CRA_dv01_usd_per_contract"]))
    checks.append(compare_float("SR3_dv01_usd", 25.0, s3["SR3_dv01_usd_per_contract"]))
    checks.append(
        compare_float(
            "IB_dv01_usd_published_24_66",
            ib_dv01_usd,
            s3["IB_dv01_usd_per_contract_published_basis"],
        )
    )
    unrounded_ib = 3_000_000 * 0.0001 * 30 / 365
    checks.append(
        compare_float(
            "IB_unrounded_not_for_valuation",
            unrounded_ib,
            s3["IB_unrounded_3m_face_30_365_not_for_valuation"],
        )
    )

    target = 25_000.0
    lots_cra = floor_toward_zero(target / (4.0 * cra_dv01_usd))
    achieved = lots_cra * 4.0 * cra_dv01_usd
    checks.append(compare_float("equal_lot_floored", lots_cra, s4["floored_lots_per_leg"], tol=0))
    checks.append(
        compare_usd("equal_lot_achieved_parallel_dv01", achieved, s4["achieved_parallel_dv01_usd_per_bp"])
    )

    lots_flat = floor_toward_zero(target / cra_dv01_usd)
    achieved_flat = lots_flat * cra_dv01_usd
    checks.append(compare_float("flattener_floored_lots", lots_flat, s5["floored_lots_per_leg"], tol=0))
    checks.append(compare_usd("flattener_achieved_leg_dv01", achieved_flat, s5["achieved_leg_usd_dv01"]))

    corra_old = {k: find_corra_3m(frozen, e)["implied_rate"] for k, e in zip(LEG_KEYS, LEGS_2027)}
    sofr_old = {k: find_sofr_3m(frozen, e)["implied_rate"] for k, e in zip(LEG_KEYS, LEGS_2027)}
    corra_new = {
        "H": rate_by_code_corra(frozen, "CRAZ26"),
        "M": rate_by_code_corra(frozen, "CRAH27"),
        "U": rate_by_code_corra(frozen, "CRAM27"),
        "Z": rate_by_code_corra(frozen, "CRAU27"),
    }
    sofr_new = {
        "H": rate_by_code_sofr(frozen, "SR3Z6"),
        "M": rate_by_code_sofr(frozen, "SR3H7"),
        "U": rate_by_code_sofr(frozen, "SR3M7"),
        "Z": rate_by_code_sofr(frozen, "SR3U7"),
    }
    corra_slide = {k: bp_diff(corra_new[k], corra_old[k]) for k in LEG_KEYS}
    sofr_slide = {k: bp_diff(sofr_new[k], sofr_old[k]) for k in LEG_KEYS}

    for k in LEG_KEYS:
        checks.append(
            compare_float(
                f"corra_slide_{k}",
                corra_slide[k],
                s7["CORRA"]["slide_bp_by_leg"][k],
                TOL_BP,
            )
        )
        checks.append(
            compare_float(
                f"sofr_slide_{k}",
                sofr_slide[k],
                s7["SOFR"]["slide_bp_by_leg"][k],
                TOL_BP,
            )
        )

    md_sofr_rounded = {"H": -21.0, "M": -13.0, "U": -4.0, "Z": -2.0}
    md_avg = -10.0
    json_avg = mean(list(sofr_slide.values()))
    table_matches_json = all(
        abs(sofr_slide[k] - md_sofr_rounded[k]) < 0.51 for k in LEG_KEYS
    ) and abs(json_avg - md_avg) < 0.51
    checks.append(
        Check(
            "composer_a_markdown_sofr_slide_table_matches_json",
            table_matches_json,
            "rounded table −21/−13/−4/−2 avg −10",
            f"exact legs {sofr_slide} avg {json_avg}",
        )
    )

    dH = corra_slide["H"]
    dZ = corra_slide["Z"]
    economic_bp_per_dv01 = dH - dZ
    section7_field = s7["flattener_pnl_bp_per_leg_dv01"]
    calc_formula_field = -(dH) + dZ
    roll_flattener_usd = s8["S_roll_1q"]["c_primary_flattener_usd"]
    economic_usd = money_cents(achieved_flat * economic_bp_per_dv01)
    checks.append(
        Check(
            "flattener_roll_economic_sign_negative",
            economic_bp_per_dv01 < 0 and roll_flattener_usd < 0,
            "negative bp and USD on roll",
            f"bp={economic_bp_per_dv01} usd={roll_flattener_usd}",
        )
    )
    checks.append(
        Check(
            "section7_flattener_field_matches_economic_sign",
            (economic_bp_per_dv01 > 0) == (section7_field > 0),
            "same sign as legDV01*(dH-dZ)",
            f"section7={section7_field} economic={economic_bp_per_dv01}",
            note="section7 uses -(dH)+dZ; economic uses dH-dZ",
        )
    )
    checks.append(compare_usd("roll_flattener_usd_vs_recompute", economic_usd, roll_flattener_usd))

    sr3_lots = floor_toward_zero(target / (4.0 * 25.0))
    pnl_ca = sum(-lots_cra * cra_dv01_usd * corra_slide[k] for k in LEG_KEYS)
    pnl_us = sum(sr3_lots * 25.0 * sofr_slide[k] for k in LEG_KEYS)
    cross_net = money_cents(pnl_ca + pnl_us)
    checks.append(compare_usd("cross_strip_roll_net_usd", cross_net, s7["cross_strip_receive_CA_roll_plus_pay_US_roll"]["net_usd_matched_books"]))

    pe = frozen["paper_engine_observed_on_book"]
    paper_unreal = pe["notional_usd"] * (pe["entry_mark"] - pe["book_mark"]) / 100.0
    checks.append(compare_usd("paper_unrealized_250m", paper_unreal, 600_000.0))

    scenario_expectations = {
        "S_parallel_selloff_25": ("a_paper_long_receive_usd", -625_000.0),
        "S_bull_flatten": ("a_paper_long_receive_usd", 125_000.0),
        "S_bear_steepen": ("a_paper_long_receive_usd", -156_250.0),
        "S_deescalation": ("a_paper_long_receive_usd", 750_000.0),
    }
    for scen, (field, exp) in scenario_expectations.items():
        checks.append(
            compare_usd(
                f"scenario_{scen}",
                s8[scen][field],
                exp,
            )
        )

    ca_only_d = s8["S_canada_only_25"]["d_ca_strip_vs_sofr_strip_usd"]
    ca_only_b = s8["S_canada_only_25"]["b_floored_equal_cra_receive_usd"]
    us_small = sum(sr3_lots * 25.0 * 5.0 for _ in LEG_KEYS)
    approx_d = money_cents(ca_only_b + us_small)
    checks.append(
        Check(
            "canada_only_cross_approx_ca_loss_minus_us_pay",
            abs(ca_only_d - approx_d) <= TOL_USD,
            approx_d,
            ca_only_d,
        )
    )

    journal_avg = mean(
        [
            frozen["paper_engine_observed_on_book"]["nov3_journal_mids_not_this_snapshot"]["2027-03"],
            frozen["paper_engine_observed_on_book"]["nov3_journal_mids_not_this_snapshot"]["2027-06"],
            frozen["paper_engine_observed_on_book"]["nov3_journal_mids_not_this_snapshot"]["2027-09"],
            frozen["paper_engine_observed_on_book"]["nov3_journal_mids_not_this_snapshot"]["2027-12"],
        ]
    )
    journal_vs_snapshot_bp = (journal_avg - corra_mean) * 100.0
    checks.append(
        Check(
            "composer_B_journal_1bp_above_snapshot",
            abs(journal_vs_snapshot_bp - 1.0) < 0.25,
            1.0,
            journal_vs_snapshot_bp,
            note="B text claims 1 bp; recomputed 3.16 vs 3.155",
        )
    )

    b_premia = [43.0, 57.5, 68.5, 77.0]
    for i, (exp, p) in enumerate(zip(LEGS_2027, b_premia)):
        checks.append(
            compare_float(
                f"composer_B_premium_{exp}",
                premium_bp(corra_rates[i], corra_cash),
                p,
                TOL_BP,
            )
        )
    avg_prem = mean([premium_bp(r, corra_cash) for r in corra_rates])
    checks.append(compare_float("composer_B_avg_premium_61_5", avg_prem, 61.5, TOL_BP))
    checks.append(compare_float("composer_B_HZ_slope_34bp", bp_diff(corra_rates[3], corra_rates[0]), 34.0, TOL_BP))

    verify_frozen_vs_snapshot(frozen, checks)

    summary = {
        "pass_count": sum(1 for c in checks if c.passed),
        "fail_count": sum(1 for c in checks if not c.passed),
        "checks": [
            {
                "name": c.name,
                "status": "PASS" if c.passed else "FAIL",
                "expected": c.expected,
                "computed": c.computed,
                "note": c.note,
            }
            for c in checks
        ],
    }
    return checks, summary


def format_notes(checks: List[Check], summary: dict) -> str:
    lines = [
        "# Independent verifier notes (Composer V)",
        "",
        f"Sources: `{FROZEN.name}`, `{CALC_RESULTS.name}`; snapshot confirm via git `{PINNED_COMMIT}` `{SNAPSHOT_GIT_PATH}`.",
        "",
        f"**Run result:** {summary['pass_count']} PASS, {summary['fail_count']} FAIL",
        "",
        "## Checks",
        "",
    ]
    for c in checks:
        status = "PASS" if c.passed else "FAIL"
        exp = c.expected
        comp = c.computed
        extra = f" — {c.note}" if c.note else ""
        lines.append(f"- **{c.name}:** {status} (expected {exp!r}, got {comp!r}){extra}")

    lines.extend(
        [
            "",
            "## Flattener roll sign (item 5)",
            "",
            "- Economic: pay H / receive Z, `PnL = legDV01 × (dH − dZ)` with dH≈−22 bp, dZ≈−8.5 bp → **−13.5 bp per leg DV01 (loss)**.",
            "- `calc_results` `section_8` `S_roll_1q` `c_primary_flattener_usd` is **negative** → matches economic sign.",
            "- `section_7` `flattener_pnl_bp_per_leg_dv01` **+13.5** uses `−(slide_H)+slide_Z`; **opposite sign** to `dH−dZ` (magnitude only).",
            "",
            "## Composer A markdown SOFR slides (item 6)",
            "",
            "- Table **−21 / −13 / −4 / −2**, avg **−10** is rounded; JSON exact slides are **−20.5 / −13 / −4 / +2**, avg **≈ −8.875**.",
            "",
            "## Composer B arithmetic (item 9)",
            "",
            "- Journal **3.16%** vs snapshot mean **3.155%** → **+0.5 bp**, not **+1 bp** as stated.",
            "- Stated premia **+43/+57.5/+68.5/+77**, avg **+61.5**, H→Z **+34 bp** match frozen inputs.",
            "",
            "No trade recommendation.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    frozen = load_json(FROZEN)
    calc = load_json(CALC_RESULTS)
    checks, summary = recompute_all(frozen, calc)
    notes = format_notes(checks, summary)
    notes_path = SCRIPT_DIR / "verifier_notes.md"
    notes_path.write_text(notes, encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if summary["fail_count"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
