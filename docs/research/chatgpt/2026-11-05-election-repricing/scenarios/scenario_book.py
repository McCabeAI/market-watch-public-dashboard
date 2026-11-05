#!/usr/bin/env python3
"""Scenario and sizing calculator for ChatGPT CORRA receive (frozen snapshot only)."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
SNAPSHOT_PATH = (
    REPO
    / "data/overnight/runs/overnight-20261105/reviews/review-001/evidence_snapshot.json"
)
BOOK_PATH = REPO / "data/pm/books/latest.json"
OUT_JSON = Path(__file__).resolve().parent / "scenario_results.json"
OUT_MD = Path(__file__).resolve().parent / "scenario_results.md"

EXPECTED_PACKET_SHA256 = (
    "0bc766c948f4f88f81ea6e28bc00ad0a67e09ee5605b23b47cb69b039f415b10"
)

CORRA_CODES = ("CRAH27", "CRAM27", "CRAU27", "CRAZ27")
SR3_CODES = ("SR3H7", "SR3M7", "SR3U7", "SR3Z7")
AONIA_LATER_EXPIRIES = (
    "2027-11",
    "2027-12",
    "2028-01",
    "2028-02",
    "2028-03",
    "2028-04",
)

SCENARIO_CORRA = {
    "A": {"assumption": True, "legs": [2.75, 2.75, 2.75, 2.75]},
    "B": {"assumption": True, "legs": [3.00, 3.20, 3.35, 3.50]},
    "C": {"assumption": True, "legs": [2.85, 2.95, 3.00, 3.05]},
}

SCENARIO_SOFR = {
    "A": {"assumption": True, "legs": [4.20, 4.20, 4.20, 4.20]},
    "B": {"assumption": True, "legs": [4.45, 4.60, 4.70, 4.75]},
    "C": {"assumption": True, "legs": None},  # equals futures
}

AONIA_LATER_ASSUMPTIONS = {
    "A": {"assumption": True, "average": 4.225, "source": "rates_memo stated -5bp/month continuation"},
    "B": {
        "assumption": True,
        "gap_bp_vs_futures": -34.333,
        "source": "rates_memo later-bucket gap under scenario B",
    },
    "C": {
        "assumption": True,
        "gap_bp_vs_futures": -24.333,
        "source": "rates_memo later-bucket gap under scenario C",
    },
}


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def canonical_packet_hash(data: dict) -> str:
    payload = {k: v for k, v in data.items() if k != "packet_sha256"}
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def raw_file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def implied_from_contract(c: dict) -> float:
    if "implied_rate" in c and c["implied_rate"] is not None:
        return float(c["implied_rate"])
    return 100.0 - float(c["price"])


def contract_by_code(curve: dict, code: str) -> dict:
    for c in curve["contracts"]:
        if c.get("code") == code:
            return c
    raise KeyError(code)


def contracts_by_expiry(curve: dict, expiries: tuple[str, ...]) -> list[dict]:
    by_exp = {c["expiry"]: c for c in curve["contracts"]}
    return [by_exp[e] for e in expiries]


def avg(values: list[float]) -> float:
    return sum(values) / len(values)


def receive_mtm_usd(usd_per_bp: float, from_rate: float, to_rate: float) -> float:
    """Receive gains when average yield falls (from_rate > to_rate)."""
    return usd_per_bp * (from_rate - to_rate) * 100.0


def gap_bp(from_rate: float, to_rate: float) -> float:
    return (from_rate - to_rate) * 100.0


def run_unit_tests(usd_per_bp: float) -> dict:
    tests: dict[str, bool | str] = {}

    payer_gain = 20 * 1000 * 25.0
    receive_loss = -payer_gain
    tests["payer_plus_20bp_1000_contracts"] = payer_gain == 500_000.0
    tests["receive_same_dv01_opposite"] = receive_loss == -500_000.0

    recv_small = receive_mtm_usd(usd_per_bp, 3.160, 3.155)
    tests["receive_3160_to_3155"] = abs(recv_small - 12_500.0) < 1e-6

    tests["book_usd_per_bp"] = usd_per_bp == 25_000.0
    tests["sr3_equivalent_contracts"] = (
        "Book DV01 25000 USD/bp equals 1000 SR3-equivalent contracts "
        "(USD 25/bp each), i.e. 250 contracts per leg on an equal four-leg strip."
    )

    all_pass = all(v is True for k, v in tests.items() if k != "sr3_equivalent_contracts")
    tests["all_pass"] = all_pass
    return tests


def verify_snapshot(data: dict, path: Path) -> dict:
    stored = data.get("packet_sha256")
    canonical = canonical_packet_hash(data)
    raw = raw_file_sha256(path)
    if stored != EXPECTED_PACKET_SHA256:
        print(f"packet_sha256 mismatch: {stored}", file=sys.stderr)
        sys.exit(1)
    if canonical != EXPECTED_PACKET_SHA256:
        print(f"canonical hash mismatch: {canonical}", file=sys.stderr)
        sys.exit(1)
    return {
        "expected_packet_sha256": EXPECTED_PACKET_SHA256,
        "stored_packet_sha256": stored,
        "canonical_sha256_excluding_packet_sha256": canonical,
        "raw_file_sha256": raw,
        "raw_file_matches_packet_sha256": raw == stored,
        "note": "Raw file bytes include packet_sha256; mismatch is expected.",
    }


def read_chatgpt_position(book: dict) -> dict:
    pm = book["pms"]["chatgpt"]
    pos = None
    for p in pm["positions"]:
        if p["position_id"] == "pm-chatgpt-595561a1b90f":
            pos = p
            break
    if pos is None:
        print("position not found", file=sys.stderr)
        sys.exit(1)
    return pm, pos


def assert_book_pnl(pos: dict) -> None:
    notional = float(pos["notional_usd"])
    entry = float(pos["entry_price"])
    mark = float(pos["mark_price"])
    stored = float(pos["unrealized_pnl_usd"])
    pnl = notional * (entry - mark) / 100.0
    if abs(pnl - stored) > 0.01:
        print(f"P&L identity failed: {pnl} vs {stored}", file=sys.stderr)
        sys.exit(1)
    usd_per_bp = notional * 0.0001
    dv01_check = usd_per_bp * (entry - mark) * 100.0
    if abs(dv01_check - stored) > 0.01:
        print(f"DV01 P&L identity failed: {dv01_check}", file=sys.stderr)
        sys.exit(1)


def build_corra_strip(curves: dict) -> dict:
    corra = curves["CORRA"]
    legs = {}
    rates = []
    for code in CORRA_CODES:
        c = contract_by_code(corra, code)
        rate = implied_from_contract(c)
        legs[code] = {
            "expiry": c["expiry"],
            "price": c["price"],
            "implied_rate": rate,
            "from_100_minus_price": 100.0 - float(c["price"]),
        }
        rates.append(rate)
    snap_avg = avg(rates)
    fixing = float(corra["benchmark"]["rate"])
    return {
        "codes": list(CORRA_CODES),
        "legs": legs,
        "snapshot_average": snap_avg,
        "corra_fixing": fixing,
        "corra_fixing_as_of": corra["benchmark"]["as_of"],
        "gap_average_vs_fixing_bp": gap_bp(snap_avg, fixing),
        "informational_only_not_mispricing": True,
    }


def scenario_corra(snap_avg: float, usd_per_bp: float, leg_snap: list[float]) -> dict:
    out = {}
    for name, spec in SCENARIO_CORRA.items():
        legs = spec["legs"]
        scen_avg = avg(legs)
        g = gap_bp(snap_avg, scen_avg)
        mtm = receive_mtm_usd(usd_per_bp, snap_avg, scen_avg)
        per_leg = []
        for i, code in enumerate(CORRA_CODES):
            per_leg.append(
                {
                    "code": code,
                    "snapshot_rate": leg_snap[i],
                    "assumption_rate": legs[i],
                    "gap_bp_snapshot_minus_assumption": gap_bp(leg_snap[i], legs[i]),
                }
            )
        out[name] = {
            "assumption": spec["assumption"],
            "scenario_average": scen_avg,
            "gap_bp_snapshot_minus_scenario": g,
            "receive_mtm_usd": mtm,
            "per_leg": per_leg,
        }
    return out


def stresses(usd_per_bp: float) -> dict:
    return {
        "from": "snapshot_strip_average",
        "parallel_plus_20bp_receive_mtm_usd": -usd_per_bp * 20,
        "parallel_minus_20bp_receive_mtm_usd": usd_per_bp * 20,
        "parallel_plus_100bp_receive_mtm_usd": -usd_per_bp * 100,
        "plus_100bp_note": "Book risk-capital shock, not expected loss",
    }


def alternative_uz_half(
    snap_avg: float, usd_per_bp: float, cra_u: float, cra_z: float
) -> dict:
    half_dv01 = usd_per_bp / 2
    per_leg = usd_per_bp / 4
    uz_avg = avg([cra_u, cra_z])
    scen_a_avg = 2.75
    four_leg_gap = gap_bp(snap_avg, scen_a_avg)
    uz_vs_275_gap = gap_bp(uz_avg, scen_a_avg)
    # Price the U/Z average, not the four-leg average, on the half DV01.
    mtm_a = receive_mtm_usd(half_dv01, uz_avg, scen_a_avg)
    wrong_four_leg_gap_on_half_dv01 = receive_mtm_usd(half_dv01, snap_avg, scen_a_avg)
    if abs(mtm_a - half_dv01 * uz_vs_275_gap) > 0.01:
        raise SystemExit("U/Z MTM does not equal half DV01 times the U/Z gap")
    if abs(mtm_a - wrong_four_leg_gap_on_half_dv01) < 0.01 and abs(uz_avg - snap_avg) > 1e-9:
        raise SystemExit("U/Z MTM collapsed to the four-leg gap on half DV01")
    return {
        "rejected": True,
        "label": "ACP387 U/Z-only trap",
        "per_leg_dv01_usd": per_leg,
        "total_dv01_usd": half_dv01,
        "unchanged_expression": "CRAU27 and CRAZ27 only; per-leg DV01 unchanged at 6250",
        "uz_snapshot_average": uz_avg,
        "scenario_A_average": scen_a_avg,
        "four_leg_gap_bp_vs_2_75": four_leg_gap,
        "uz_average_gap_bp_vs_2_75_larger": uz_vs_275_gap,
        "under_A_mtm_usd_half_dv01": mtm_a,
        "under_A_mtm_usd_full_dv01_for_comparison": receive_mtm_usd(
            usd_per_bp, snap_avg, scen_a_avg
        ),
        "parallel_plus_20bp_loss_usd": -half_dv01 * 20,
        "trap_note": (
            "Lower stress loss reflects half DV01, not a better expression; "
            f"U/Z average gap vs 2.75 ({uz_vs_275_gap:.3f} bp) exceeds four-leg "
            f"scenario-A gap ({four_leg_gap:.3f} bp) while dollar MTM under A "
            f"({mtm_a:.2f}) is smaller than full strip ({receive_mtm_usd(usd_per_bp, snap_avg, scen_a_avg):.2f})."
        ),
    }


def alternative_double_add(
    scenarios: dict, usd_per_bp: float, stresses_dict: dict
) -> dict:
    double = usd_per_bp * 2
    return {
        "rejected_add": True,
        "doubled_usd_per_bp": double,
        "under_A_mtm_usd": scenarios["A"]["receive_mtm_usd"] * 2,
        "under_B_mtm_usd": scenarios["B"]["receive_mtm_usd"] * 2,
        "parallel_plus_20bp_loss_usd": stresses_dict["parallel_plus_20bp_receive_mtm_usd"] * 2,
        "note": (
            "Unknown scenario probabilities mean doubled B loss is not compensated "
            "by a known probability weight."
        ),
    }


def alternative_sofr(curves: dict, usd_per_bp: float) -> dict:
    sofr = curves["SOFR"]
    rates = [implied_from_contract(contract_by_code(sofr, c)) for c in SR3_CODES]
    snap_avg = avg(rates)
    legs_detail = {
        code: implied_from_contract(contract_by_code(sofr, code))
        for code in SR3_CODES
    }
    out = {
        "rejected": True,
        "not_held": True,
        "standalone_only": True,
        "matched_dv01_usd_per_bp": usd_per_bp,
        "snapshot_legs": legs_detail,
        "snapshot_average": snap_avg,
        "scenarios": {},
    }
    for name, spec in SCENARIO_SOFR.items():
        if name == "C":
            legs = rates
        else:
            legs = spec["legs"]
        scen_avg = avg(legs)
        mtm = receive_mtm_usd(usd_per_bp, snap_avg, scen_avg)
        out["scenarios"][name] = {
            "assumption": spec["assumption"],
            "scenario_average": scen_avg,
            "gap_bp_snapshot_minus_scenario": gap_bp(snap_avg, scen_avg),
            "receive_mtm_usd": mtm,
        }
    return out


def alternative_aonia_pay(curves: dict) -> dict:
    aonia = curves["AONIA"]
    month_contracts = contracts_by_expiry(aonia, AONIA_LATER_EXPIRIES)
    futures_rates = [implied_from_contract(c) for c in month_contracts]
    futures_avg = avg(futures_rates)
    aud_per_bp_target = 25_000.0
    dv01_per_lot = 24.66
    n_months = len(AONIA_LATER_EXPIRIES)
    lots_exact = aud_per_bp_target / (n_months * dv01_per_lot)
    lots_int = round(lots_exact)
    int_dv01 = lots_int * n_months * dv01_per_lot

    def pay_mtm(from_r: float, to_r: float) -> float:
        return -aud_per_bp_target * (from_r - to_r) * 100.0

    scenario_rows = {}
    for name, spec in AONIA_LATER_ASSUMPTIONS.items():
        if "average" in spec:
            scen_avg = spec["average"]
        else:
            scen_avg = futures_avg - spec["gap_bp_vs_futures"] / 100.0
        scenario_rows[name] = {
            "assumption": spec["assumption"],
            "scenario_average": scen_avg,
            "futures_average": futures_avg,
            "gap_bp_futures_minus_scenario": gap_bp(futures_avg, scen_avg),
            "pay_mtm_aud_repricing": pay_mtm(futures_avg, scen_avg),
            "source": spec["source"],
        }

    return {
        "rejected": True,
        "side": "pay",
        "currency": "AUD",
        "not_added_to_corra_book": True,
        "expiries": list(AONIA_LATER_EXPIRIES),
        "futures_by_month": {
            c["expiry"]: implied_from_contract(c) for c in month_contracts
        },
        "futures_bucket_average": futures_avg,
        "dv01_per_lot_aud_per_bp": dv01_per_lot,
        "lots_exact_for_25000_aud_per_bp": lots_exact,
        "lots_rounded_integer": lots_int,
        "integer_bucket_dv01_aud_per_bp": int_dv01,
        "parallel_stress_from_futures_average_aud": {
            "pay_plus_20bp_parallel_mtm_aud": aud_per_bp_target * 20,
            "pay_minus_20bp_parallel_mtm_aud": -aud_per_bp_target * 20,
        },
        "scenarios_later_bucket": scenario_rows,
        "memo_note": (
            "Scenario sign flips for this bucket were argued in the rates memo; "
            "this script does not convert them into an expected value."
        ),
        "no_fx_conversion_to_usd": True,
    }


def funding_block(pm: dict, pos: dict) -> dict:
    history = pm.get("history") or []
    accruals = [h for h in history if h.get("action") == "FUNDING"]
    reproduced = 0.0
    lines = []
    for h in accruals:
        base = float(h["funding_base_usd"])
        rate = float(h["funding_rate_annual"])
        days = int(h["accrual_days"])
        dc = int(h["funding_day_count"])
        piece = base * rate * days / dc
        reproduced += piece
        lines.append({"accrual_days": days, "computed": piece, "stored": h["funding_cost_usd"]})

    stored_total = float(pm["funding_cost_usd"])
    match = abs(reproduced - stored_total) < 0.05
    return {
        "funding_cost_usd": stored_total,
        "funding_rate_annual": float(pm["funding_rate_annual"]),
        "funding_draw_usd": float(pos["funding_draw_usd"]),
        "pm_funded_draw_usd": float(pm.get("funded_draw_usd", pos["funding_draw_usd"])),
        "funding_formula": (
            "sum over FUNDING history: funding_base_usd * funding_rate_annual * "
            "accrual_days / funding_day_count (ACT/360 per entry)"
            if match
            else "unidentified"
        ),
        "recomputed_sum_usd": reproduced,
        "history_accrual_pieces": lines,
        "opened_at": pos["opened_at"],
        "last_decision_at": pm["last_decision_at"],
        "scenario_mtm_excludes_funding": True,
    }


def instrument_disclosure(curves: dict) -> dict:
    return {
        "CRA": curves["CORRA"].get("instrument"),
        "CRA_dv01": (
            "CAD 25 per 0.01 per CAD 1,000,000 face (90/360); book uses USD "
            "notional convention per stored P&L identity, not CAD face rescaling."
        ),
        "SR3": "USD 25 per 0.01 per USD 1,000,000",
        "AONIA_IB": (
            "A$24.66 per 0.01 per lot, notional A$3,000,000, 30/365"
        ),
        "cad_aud_not_converted_to_usd": True,
    }


def write_markdown(result: dict) -> None:
    sc = result["scenarios_corra"]
    st = result["stresses"]
    alt_uz = result["alternatives"]["uz_half_dv01"]
    alt_sofr = result["alternatives"]["rejected_sofr_receive"]
    alt_aon = result["alternatives"]["rejected_aonia_pay"]

    lines = [
        "# Scenario results — ChatGPT CORRA receive",
        "",
        f"Snapshot average **{result['snapshot_strip']['snapshot_average']:.5f}** "
        f"(packet `{result['hash_verification']['stored_packet_sha256'][:12]}…`).",
        "",
        "## Existing position (USD MTM, futures-only)",
        "",
        "| Case | Scenario avg | Gap (bp) | Receive MTM USD |",
        "| --- | ---: | ---: | ---: |",
    ]
    for key in ("A", "B", "C"):
        row = sc[key]
        lines.append(
            f"| {key} | {row['scenario_average']:.4f} | "
            f"{row['gap_bp_snapshot_minus_scenario']:.3f} | "
            f"{row['receive_mtm_usd']:,.2f} |"
        )
    lines.extend(
        [
            f"| Stress +20 bp parallel | — | +20 | "
            f"{st['parallel_plus_20bp_receive_mtm_usd']:,.2f} |",
            f"| Stress −20 bp parallel | — | −20 | "
            f"{st['parallel_minus_20bp_receive_mtm_usd']:,.2f} |",
            "",
            "## U/Z half-DV01 trap (rejected)",
            "",
            alt_uz["trap_note"],
            "",
            "## Rejected SOFR and AONIA",
            "",
            (
                f"A standalone equal-weight **receive** on SR3H7–SR3Z7 (not held) "
                f"would show scenario-A MTM **{alt_sofr['scenarios']['A']['receive_mtm_usd']:,.0f} USD** "
                f"and scenario-C MTM **{alt_sofr['scenarios']['C']['receive_mtm_usd']:,.0f} USD** "
                f"on matched 25k USD/bp; the research owner rejected adding SOFR."
            ),
            "",
            (
                f"A **pay** on AONIA Nov-2027–Apr-2028 (illustrative "
                f"{alt_aon['lots_exact_for_25000_aud_per_bp']:.2f} lots/month for 25k AUD/bp) "
                f"has bucket futures average **{alt_aon['futures_bucket_average']:.5f}**; "
                f"±20 bp parallel pay MTM is "
                f"**{alt_aon['parallel_stress_from_futures_average_aud']['pay_plus_20bp_parallel_mtm_aud']:,.0f}** / "
                f"**{alt_aon['parallel_stress_from_futures_average_aud']['pay_minus_20bp_parallel_mtm_aud']:,.0f} AUD**. "
                f"{alt_aon['memo_note']} Not combined with the CORRA book."
            ),
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    snapshot = load_json(SNAPSHOT_PATH)
    hash_info = verify_snapshot(snapshot, SNAPSHOT_PATH)
    book = load_json(BOOK_PATH)
    pm, pos = read_chatgpt_position(book)

    notional = float(pos["notional_usd"])
    usd_per_bp = notional * 0.0001
    assert_book_pnl(pos)

    unit_tests = run_unit_tests(usd_per_bp)
    if not unit_tests["all_pass"]:
        print("Unit tests failed:", unit_tests, file=sys.stderr)
        sys.exit(1)

    market_data = snapshot["families"]["market_state"]["data"]
    curves = market_data["tradable_rate_curves"]["curves"]
    strip = build_corra_strip(curves)
    snap_avg = strip["snapshot_average"]
    leg_rates = [strip["legs"][c]["implied_rate"] for c in CORRA_CODES]

    mark = float(pos["mark_price"])
    vintage_bp = gap_bp(mark, snap_avg)
    vintage_mtm = usd_per_bp * vintage_bp

    scenarios = scenario_corra(snap_avg, usd_per_bp, leg_rates)
    stress = stresses(usd_per_bp)

    result = {
        "type": "SCENARIO_BOOK_2026_11_05",
        "hash_verification": hash_info,
        "unit_tests": unit_tests,
        "book_identity": {
            "position_id": pos["position_id"],
            "side": pos["side"],
            "side_meaning": "long = receive (yield down = gain)",
            "notional_usd": notional,
            "entry_price": float(pos["entry_price"]),
            "mark_price": mark,
            "mark_price_note": "prior book mark; forward scenarios use snapshot average",
            "stored_unrealized_pnl_usd": float(pos["unrealized_pnl_usd"]),
            "pnl_formula": "notional_usd * (entry_price - mark_price) / 100.0",
            "usd_per_bp_strip_average": usd_per_bp,
            "dv01_pnl_identity": "usd_per_bp * (entry_price - mark_price) * 100",
            "receive_loses_when_average_yield_rises": True,
        },
        "snapshot_strip": {
            **strip,
            "vintage_book_mark_minus_snapshot_average_bp": vintage_bp,
            "hypothetical_incremental_mtm_usd": vintage_mtm,
            "vintage_mtm_label": "NOT canonical P&L",
        },
        "scenarios_corra": scenarios,
        "stresses": stress,
        "alternatives": {
            "uz_half_dv01": alternative_uz_half(
                snap_avg,
                usd_per_bp,
                strip["legs"]["CRAU27"]["implied_rate"],
                strip["legs"]["CRAZ27"]["implied_rate"],
            ),
            "rejected_double_add": alternative_double_add(scenarios, usd_per_bp, stress),
            "rejected_sofr_receive": alternative_sofr(curves, usd_per_bp),
            "rejected_aonia_pay": alternative_aonia_pay(curves),
        },
        "financing": funding_block(pm, pos),
        "instrument_disclosure": instrument_disclosure(curves),
        "sign_notes": (
            "The existing position is a receive; yield up is a loss; the +20 bp "
            "payer gain of 500000 USD is the opposite sign of this book."
        ),
    }

    OUT_JSON.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    write_markdown(result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
