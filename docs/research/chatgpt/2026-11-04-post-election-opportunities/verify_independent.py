#!/usr/bin/env python3
"""Independent verifier — recomputes from frozen_extract.json and JSON constants only."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

DIR = Path(__file__).resolve().parent
FROZEN = DIR / "frozen_extract.json"
CALC = DIR / "calc_results.json"
PORTFOLIO = DIR / "portfolio_scenarios.json"
MATH_NOTES = DIR / "math_notes.md"

PINNED = "612666a21e621e6bb437802cb48ace011f181b7b"
EXPECTED_PACKET_SHA = "d1a793edb498fd7c866b54038d6db9cc1139c91301f5b2c8fc20729d8933430f"
EXPECTED_SNAPSHOT_SHA = "f4dad4a2657be919f6b6e991761bc260ee93a5527a004b5c7f9f9af8f3041241"
EXPECTED_CUTOFF = "2026-11-04T05:35:22.541505-05:00"
EXPECTED_GENERATED_AT = "2026-11-04T10:52:31Z"
SNAPSHOT_GIT_PATH = (
    "data/overnight/runs/overnight-20261104/reviews/review-001/evidence_snapshot.json"
)
REVIEW_GIT_PATH = (
    "data/overnight/runs/overnight-20261104/reviews/review-001/review.json"
)

LEG_EXPIRIES = ("2027-03", "2027-06", "2027-09", "2027-12")
LEG_KEYS = ("H", "M", "U", "Z")
SOFR_RATE = 0.0395
DAY_COUNT = 360
DAYS_30 = 30
TOL_BP = 0.01
TOL_USD = 1.0


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def git_show(commit: str, relpath: str) -> bytes:
    proc = subprocess.run(
        ["git", "show", f"{commit}:{relpath}"],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise OSError(proc.stderr.decode() or f"git show failed for {relpath}")
    return proc.stdout


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def money(x: float) -> float:
    return round(x, 2)


def fail(checks: list[tuple[str, bool, str]], name: str, ok: bool, detail: str) -> None:
    checks.append((name, ok, detail))
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name}: {detail}")


def corra_2027_rates(frozen: dict) -> dict[str, float]:
    rows = frozen["futures_contracts"]["CORRA_3M"]
    out: dict[str, float] = {}
    for row in rows:
        exp = row.get("expiry")
        if exp in LEG_EXPIRIES:
            out[exp] = float(row["implied_rate"])
    if set(out) != set(LEG_EXPIRIES):
        raise ValueError(f"missing CORRA 2027 legs: {out}")
    return out


def main() -> int:
    checks: list[tuple[str, bool, str]] = []
    failures = 0

    frozen = load_json(FROZEN)
    calc = load_json(CALC)
    portfolio = load_json(PORTFOLIO)

    # --- 1 Provenance ---
    meta = frozen["meta"]
    ok_pin = meta.get("pinned_commit") == PINNED
    fail(
        checks,
        "1a_pinned_commit",
        ok_pin,
        f"frozen meta pinned_commit={meta.get('pinned_commit')} expected={PINNED}",
    )

    ok_cutoff = (
        meta.get("frozen_at") == EXPECTED_CUTOFF
        and meta.get("snapshot_as_of") == EXPECTED_CUTOFF
    )
    fail(
        checks,
        "1b_cutoff",
        ok_cutoff,
        f"frozen_at={meta.get('frozen_at')} snapshot_as_of={meta.get('snapshot_as_of')}",
    )

    ok_gen = meta.get("market_state_generated_at") == EXPECTED_GENERATED_AT
    fail(
        checks,
        "1c_market_state_generated_at",
        ok_gen,
        f"got={meta.get('market_state_generated_at')} expected={EXPECTED_GENERATED_AT}",
    )

    ok_packet = meta.get("packet_sha256") == EXPECTED_PACKET_SHA
    fail(
        checks,
        "1d_frozen_packet_sha256",
        ok_packet,
        f"got={meta.get('packet_sha256')} expected={EXPECTED_PACKET_SHA}",
    )

    try:
        review_raw = git_show(PINNED, REVIEW_GIT_PATH)
        review = json.loads(review_raw)
        rev_status = review.get("status")
        rev_packet = review.get("packet_sha256") or review.get("packet")
        ok_review = rev_status == "accepted" and rev_packet == EXPECTED_PACKET_SHA
        fail(
            checks,
            "1e_review_json",
            ok_review,
            f"status={rev_status} packet_sha256={rev_packet}",
        )
    except OSError as exc:
        fail(checks, "1e_review_json", False, str(exc))

    try:
        snap_raw = git_show(PINNED, SNAPSHOT_GIT_PATH)
        snap_sha = sha256_bytes(snap_raw)
        stored_snap_sha = meta.get("snapshot_file_sha256")
        ok_snap = snap_sha == EXPECTED_SNAPSHOT_SHA and (
            stored_snap_sha is None or snap_sha == stored_snap_sha
        )
        fail(
            checks,
            "1f_evidence_snapshot_rehash",
            ok_snap,
            f"git_blob_sha256={snap_sha} frozen_stored={stored_snap_sha}",
        )
    except OSError as exc:
        fail(checks, "1f_evidence_snapshot_rehash", False, str(exc))

    # --- 2 CORRA strip / book mark ---
    rates_by_exp = corra_2027_rates(frozen)
    h, m, u, z = (
        rates_by_exp["2027-03"],
        rates_by_exp["2027-06"],
        rates_by_exp["2027-09"],
        rates_by_exp["2027-12"],
    )
    mean = (h + m + u + z) / 4.0
    cash = float(frozen["benchmarks"]["CORRA"]["rate"])
    premium_bp = (mean - cash) * 100.0
    book_mark = float(frozen["chatgpt_position_economics"]["mark"])
    mark_gap_bp = (book_mark - mean) * 100.0
    paper_dv01 = float(calc["dv01_and_fx"]["paper_dv01_usd_per_bp_at_250m_notional"])
    mark_gap_pnl = -mark_gap_bp * paper_dv01  # receive vs higher stored mark
    stored_unreal = float(frozen["chatgpt_position_economics"]["unrealized_pnl_usd"])

    ok_rates = all(
        abs(x - y) < TOL_BP
        for x, y in zip((h, m, u, z), (2.97, 3.115, 3.225, 3.31))
    )
    fail(
        checks,
        "2a_corra_HMUZ",
        ok_rates,
        f"H/M/U/Z={h}/{m}/{u}/{z}",
    )
    ok_mean = abs(mean - 3.155) < TOL_BP
    fail(checks, "2b_corra_mean", ok_mean, f"mean={mean:.6f}")
    ok_prem = abs(premium_bp - 61.5) < TOL_BP
    fail(checks, "2c_premium_vs_2p54_bp", ok_prem, f"premium_bp={premium_bp:.4f}")
    ok_mgap = abs(mark_gap_bp - 0.5) < TOL_BP
    fail(checks, "2d_book_mark_gap_bp", ok_mgap, f"3.16-mean={mark_gap_bp:.4f}bp")
    ok_mpnl = abs(mark_gap_pnl - (-12500.0)) < TOL_USD
    fail(
        checks,
        "2e_mark_gap_paper_pnl_usd",
        ok_mpnl,
        f"computed={mark_gap_pnl:.2f} expected=-12500 (stored unrealized kept {stored_unreal:.0f})",
    )

    # --- 3 USDCAD / CRA sizing ---
    usdcad = float(frozen["fx"]["pairs"]["USDCAD"]["spot"])
    usd_per_cad = 1.0 / usdcad
    cra_bpv_usd = 25.0 * usd_per_cad
    lots = math.floor(25000.0 / (4.0 * cra_bpv_usd))
    achieved_4 = lots * 4.0 * cra_bpv_usd
    achieved_uz = lots * 2.0 * cra_bpv_usd
    sizing = calc["research_budgets_usd_per_bp"]["25000"]["expressions"][
        "receive_4leg_CORRA_2027_HMUZ"
    ]
    calc_lots = int(sizing["floored_lots_per_leg"])
    ok_fx = abs(usdcad - float(calc["dv01_and_fx"]["USDCAD_spot_CAD_per_USD"])) < 1e-9
    ok_lots = lots == 349 and lots == calc_lots
    fail(
        checks,
        "3_cra_lots_and_dv01",
        ok_fx and ok_lots,
        f"USDCAD={usdcad:.12f} lots={lots} dv01_4leg={achieved_4:.2f} dv01_UZ={achieved_uz:.2f}",
    )

    # --- 4 SR3 bpv ---
    sr3_bpv = float(calc["dv01_and_fx"]["SR3_usd_per_bp_per_lot_ASSUMPTION"])
    ok_sr3 = (
        abs(sr3_bpv - 25.0) < 1e-9
        and abs(200 * sr3_bpv - 5000.0) < 1e-6
        and abs(1000 * sr3_bpv - 25000.0) < 1e-6
    )
    fail(
        checks,
        "4_sr3_bpv_lot_scaling",
        ok_sr3,
        f"bpv/lot={sr3_bpv} 200lots={200*sr3_bpv} 1000lots={1000*sr3_bpv}",
    )

    # --- 5 Roll ---
    slides = calc["one_quarter_roll"]["CORRA_slide_bp_by_leg"]
    slide_h = float(slides["H"])
    slide_m = float(slides["M"])
    slide_u = float(slides["U"])
    slide_z = float(slides["Z"])
    pay_h_recv_z = slide_h - slide_z
    avg_slide = (22.0 + 14.5 + 11.0 + 8.5) / 4.0
    roll_pnl_paper = avg_slide * paper_dv01
    ok_roll = (
        abs(slide_h - (-22.0)) < TOL_BP
        and abs(slide_m - (-14.5)) < TOL_BP
        and abs(slide_u - (-11.0)) < TOL_BP
        and abs(slide_z - (-8.5)) < TOL_BP
        and abs(pay_h_recv_z - (-13.5)) < TOL_BP
        and abs(avg_slide - 14.0) < TOL_BP
        and abs(roll_pnl_paper - 350000.0) < TOL_USD
    )
    fail(
        checks,
        "5_one_quarter_roll_ASSUMPTION",
        ok_roll,
        f"slideH-Z={pay_h_recv_z:.4f}bp avg_slide={avg_slide:.4f}bp paper_usd={roll_pnl_paper:.2f}",
    )

    # --- 6 Financing ---
    exact_2p5m = 2_500_000 * SOFR_RATE * DAYS_30 / DAY_COUNT
    fin_conv = portfolio.get("financing_convention", {})
    r1_meta = portfolio["rivals"]["R1"]["meta"]
    r1_fin = float(r1_meta["financing_30d_usd"])
    r1_rc = float(r1_meta["risk_capital_usd"])
    r1_dv01 = float(r1_meta["parallel_dv01_usd_per_bp"])
    expected_r1_fin = money(r1_rc * SOFR_RATE * DAYS_30 / DAY_COUNT)
    ok_exact = abs(exact_2p5m - 8229.166666666666) < 1e-6
    ok_r1_fin = abs(r1_fin - expected_r1_fin) <= TOL_USD
    fail(
        checks,
        "6_financing",
        ok_exact and ok_r1_fin,
        f"2.5m*SOFR*30/360={exact_2p5m:.10f} portfolio_R1={r1_fin} "
        f"recomputed_from_risk_capital={expected_r1_fin} convention={fin_conv.get('day_count')}",
    )

    # --- 7 SIGN / matched book ---
    shock = 20.0
    recv_pnl = -achieved_4 * shock
    pay_pnl_matched_dv01 = achieved_4 * shock
    pay_pnl_25k = paper_dv01 * shock
    combined_matched = recv_pnl + pay_pnl_matched_dv01
    sk = calc["scenario_skeletons_usd_assumption_paths"]["scenarios"]["common_plus_20"]
    bug_pay = float(sk["futures_pay_4leg_sr3_matched_usd"])
    self_checks = portfolio.get("self_checks", [])
    matched_sc = next(
        (c for c in self_checks if c.get("name") == "matched_pay_receive_common_plus_20"),
        None,
    )
    integrator_ok = matched_sc is not None and matched_sc.get("pass") is True
    combined_from_integrator = None
    if matched_sc:
        detail = matched_sc.get("detail", "")
        if "combined=" in detail:
            try:
                combined_from_integrator = float(detail.split("combined=")[1].split()[0])
            except ValueError:
                combined_from_integrator = None
    recv_at_25k = -paper_dv01 * shock
    pay_at_25k = paper_dv01 * shock
    ok_sign = (
        abs(recv_at_25k - (-500000.0)) < TOL_USD
        and abs(pay_at_25k - 500000.0) < TOL_USD
        and abs(recv_at_25k + pay_at_25k) < TOL_USD
        and abs(combined_matched) < TOL_USD
        and bug_pay < 0
        and integrator_ok
        and (
            combined_from_integrator is None
            or abs(combined_from_integrator) <= TOL_USD
        )
    )
    fail(
        checks,
        "7_sign_and_matched_common_plus_20",
        ok_sign,
        f"recv@achieved_dv01={recv_pnl:.2f} pay@achieved={pay_pnl_matched_dv01:.2f} "
        f"combined={combined_matched:.2f} calc_bug_pay={bug_pay} integrator_pass={integrator_ok}",
    )

    # --- 8 Article gaps / no fused P&L ---
    gaps = frozen.get("article_context_gaps", {})
    y10 = gaps["versus_frozen_cash_yields"]["ust10_narrative_vs_US_10Y"]
    y2 = gaps["versus_frozen_cash_yields"]["ust2_narrative_vs_US_2Y"]
    y30 = gaps["versus_frozen_cash_yields"]["ust30_narrative_vs_US_30Y"]
    ok_gap_vals = (
        abs(float(y10["gap_bp_where_rate"]) - (-5.2)) < 0.05
        and abs(float(y2["gap_bp_where_rate"]) - (-3.7)) < 0.05
        and abs(float(y30["gap_bp_where_rate"]) - (-2.7)) < 0.05
        and y10.get("classification") == "UNSYNCHRONIZED"
    )
    wti = gaps["oil_percent_vs_frozen_compact"]["wti"]
    brent = gaps["oil_percent_vs_frozen_compact"]["brent"]
    wti_ratio = 88.0 / float(wti["frozen"]) - 1.0
    brent_ratio = 94.0 / float(brent["frozen"]) - 1.0
    ok_oil = abs(wti_ratio - float(wti["ratio_minus_one"])) < 1e-6 and abs(
        brent_ratio - float(brent["ratio_minus_one"])
    ) < 1e-6

    def scenario_uses_article_yields(obj: object) -> bool:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ("market_pnl_usd", "net_pnl_usd") and isinstance(v, (int, float)):
                    continue
                if isinstance(v, str) and any(
                    t in v for t in ("4.898", "4.573", "5.293", "quote_table")
                ):
                    if "ASSUMPTION" not in v and "UNSYNCHRONIZED" not in v:
                        return True
                if scenario_uses_article_yields(v):
                    return True
        elif isinstance(obj, list):
            return any(scenario_uses_article_yields(x) for x in obj)
        return False

    ok_no_fused = not scenario_uses_article_yields(portfolio.get("rivals", {}))
    # article_treasury_minus_5_ASSUMPTION is allowed
    fail(
        checks,
        "8_article_gaps_unsynchronized",
        ok_gap_vals and ok_oil and ok_no_fused,
        f"UST gaps bp={y10['gap_bp_where_rate']}/{y2['gap_bp_where_rate']}/{y30['gap_bp_where_rate']} "
        f"oil ratios ok={ok_oil} portfolio_fused={not ok_no_fused}",
    )

    # --- 9 Quote-table vs narrative ---
    qt = frozen["article_context"]["quote_table"]
    narr = frozen["article_context"]["narrative"]
    gap2 = float(qt["ust2"]) - float(narr["ust2"])
    gap30 = float(qt["ust30"]) - float(narr["ust30"])
    ok_qt = abs(gap2 - 0.004) < 0.0005 and abs(gap30 - (-0.003)) < 0.0005
    integrator_text = (DIR / "portfolio_integrator.md").read_text(encoding="utf-8")
    bad_label = "quote-table prints as frozen" in integrator_text.lower() or (
        "quote-table" in integrator_text
        and "frozen yield" in integrator_text.lower()
        and "not" not in integrator_text.lower().split("quote-table")[0][-40:]
    )
    ok_integrator = "Do **not** treat quote-table prints as" in integrator_text
    fail(
        checks,
        "9_quote_table_not_frozen_yield",
        ok_qt and ok_integrator and not bad_label,
        f"narrative2Y={narr['ust2']} quote2Y={qt['ust2']} delta={gap2:.4f}; integrator_warns={ok_integrator}",
    )

    # --- 10 Flat rival / no prospective 600k ---
    r0 = portfolio["rivals"]["R0"]
    r3 = portfolio["rivals"]["R3"]
    ok_flat = portfolio.get("proposed_rival_id") == "R0"
    for rival_id, rival in (("R0", r0), ("R3", r3)):
        for sname, srow in rival.get("scenarios", {}).items():
            if float(srow.get("market_pnl_usd", 0)) != 0.0:
                ok_flat = False
    ok_flat = ok_flat and float(stored_unreal) == 600000.0  # historical only in extract
    fail(
        checks,
        "10_flat_rival_no_prospective_unrealized",
        ok_flat,
        f"proposed={portfolio.get('proposed_rival_id')} R0/R3 market_pnl all 0; "
        f"stored unrealized={stored_unreal} not in scenario P&L",
    )

    # --- 11 Cross-check key portfolio scenario dollars (R1 common+20) ---
    r1_cp20 = float(
        portfolio["rivals"]["R1"]["scenarios"]["common_plus_20"]["market_pnl_usd"]
    )
    expected_r1 = money(-achieved_4 * 20.0)
    ok_r1 = abs(r1_cp20 - expected_r1) <= TOL_USD
    fail(
        checks,
        "11_r1_common_plus_20_market_pnl",
        ok_r1,
        f"portfolio={r1_cp20} recomputed={expected_r1}",
    )

    for _, ok, _ in checks:
        if not ok:
            failures += 1

    verdict = "PASS" if failures == 0 else "FAIL"
    print(f"\nVERDICT: {verdict} (failures={failures})")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
