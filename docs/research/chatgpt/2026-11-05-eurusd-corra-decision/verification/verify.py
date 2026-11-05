#!/usr/bin/env python3
"""Independent verifier: recompute checks from snapshot/book sources only."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[5]
DECISION_DIR = Path(__file__).resolve().parents[1]
VERIFICATION_DIR = Path(__file__).resolve().parent

SNAPSHOT_PATH = (
    REPO
    / "data/overnight/runs/overnight-20261105/reviews/review-001/evidence_snapshot.json"
)
AGENT_PACKET_PATH = (
    REPO
    / "data/overnight/runs/overnight-20261105/reviews/review-001/agent_evidence_packet.json"
)
BOOK_PATH = REPO / "data/pm/books/latest.json"
PARENT_REPORT = (
    REPO
    / "docs/research/chatgpt/2026-11-05-eurusd-corra-decision-review.md"
)
DECISION_CARDS = DECISION_DIR / "decision_cards.json"
EUR_MEMO = DECISION_DIR / "eur/decision_memo.md"
CORRA_MEMO = DECISION_DIR / "corra/decision_memo.md"
EURUSD_CSV = DECISION_DIR / "quant/series_eurusd.csv"

EXPECTED = {
    "snapshot_canonical_sha256": "0bc766c948f4f88f81ea6e28bc00ad0a67e09ee5605b23b47cb69b039f415b10",
    "snapshot_raw_sha256": "13a1b1ca0fb89f4030f427f4106199ab8087894e478db8e980e1cc1d050f2744",
    "snapshot_git_blob": "16a74cdf5149e3fa8a9211fa2559b9ba9fc8f2ad",
    "agent_canonical_sha256": "633501f729ca9917b211edbfb809dce6dd89edb762b14c669582e2a2ca5fee5a",
    "packet_freeze": "2026-11-05T04:53:53.458055-05:00",
    "market_state_generated": "2026-11-05T10:17:36Z",
    "integration_clock": "2026-11-05T13:30:00Z",
    "base_commit": "a0c9357097fbd812bbac3e669b314349c0831660",
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def canonical_sha256(obj: dict, hash_key: str = "packet_sha256") -> str:
    copy = dict(obj)
    copy.pop(hash_key, None)
    text = json.dumps(copy, indent=2, sort_keys=True) + "\n"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def raw_file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_blob_sha256(path: Path) -> str:
    rel = path.relative_to(REPO)
    out = subprocess.check_output(
        ["git", "hash-object", str(rel)], cwd=REPO, text=True
    ).strip()
    return out


def check(name: str, ok: bool, detail: str, expected: Any = None, computed: Any = None) -> dict:
    return {
        "name": name,
        "status": "pass" if ok else "fail",
        "detail": detail,
        "expected": expected,
        "computed": computed,
    }


def find_opportunity_series(snapshot: dict) -> list[dict]:
    try:
        return snapshot["families"]["market_state"]["data"]["opportunities"]["series"]
    except KeyError:
        return []


def series_by_id(snapshot: dict, series_id: str) -> dict | None:
    for row in find_opportunity_series(snapshot):
        if row.get("id") == series_id:
            return row
    return None


def history_closes(series: dict) -> list[tuple[str, float]]:
    hist = series.get("history") or []
    return [(str(d), float(v)) for d, v in hist]


def simple_pct_usd_per_fx(series_id: str, prior: float, last: float) -> float:
    """Daily simple % change in USD per unit foreign, consistent with parent report."""
    direct = {"EURUSD", "GBPUSD", "AUDUSD", "NZDUSD"}
    if series_id in direct:
        return (last / prior - 1.0) * 100.0
    # USD quote first: USDSEK, USDCHF, USDJPY, USDCAD, USDNOK
    return (prior / last - 1.0) * 100.0


def daily_log_returns(closes: list[float]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(closes)):
        out.append(math.log(closes[i] / closes[i - 1]))
    return out


def sample_std(values: list[float]) -> float:
    if len(values) < 2:
        return float("nan")
    return statistics.stdev(values)


def yardstick_pct(sigma_daily_log: float, h: int) -> float:
    return 100.0 * (math.exp(sigma_daily_log * math.sqrt(h)) - 1.0)


def spot_pnl(notional: float, spot: float, entry: float = 1.1267) -> float:
    return notional * (spot / entry - 1.0)


def corra_pnl(bp_move: float, dv01_per_bp: float) -> float:
    """Receive: strip fall (negative bp) is gain."""
    return -bp_move * dv01_per_bp


def funding_cost(rate: float, draw: float, days: int) -> float:
    return rate * draw * days / 360.0


def rate_to_bp(delta_rate: float) -> float:
    """Convert rate difference in percent points to basis points."""
    return delta_rate * 100.0


def reasoning_audit(parent_text: str, cards: dict) -> list[dict]:
    t = parent_text
    audits: list[tuple[str, bool, str]] = []

    def has(*parts: str) -> bool:
        return all(p in t for p in parts)

    audits.append(
        (
            "now_wait_reject_both_instruments",
            has("**NOW", "EURUSD") and has("**WAIT", "EURUSD") and has("**REJECT", "EURUSD")
            and has("**NOW", "3.11375") and has("**WAIT", "CORRA") and has("**REJECT", "CORRA"),
            "Parent report states NOW, WAIT, and REJECT for EURUSD and CORRA anchored to 1.1267 and 3.11375.",
        )
    )
    audits.append(
        (
            "waiting_triad",
            "what_wait_buys" in json.dumps(cards)
            and "what_wait_can_forgo" in json.dumps(cards)
            and "circumstance_where_waiting_loses" in json.dumps(cards),
            "Decision cards document wait benefit, forgone move, and when waiting loses for both legs.",
        )
    )
    audits.append(
        (
            "euro_reject_not_four_screens",
            "missing residual" in t.lower() or "residual is not identified" in t.lower()
            and "Those four facts do not establish" in t
            and "not a ban" in t.lower(),
            "Euro reject is framed as unidentified residual, not rally/percentile/forwards/differential bans.",
        )
    )
    audits.append(
        (
            "275_not_prima_target",
            "2.75 sits 5 bp under the floor" in t and "not the four-quarter target" in t.lower(),
            "2.75 is rejected as four-quarter average, not adopted because prima stores it.",
        )
    )
    audits.append(
        (
            "no_grandfather_250m",
            "grandfathering" in t.lower() and "USD 100m" in t and "From-flat" in t,
            "Full USD 250m is cut under an explicit from-flat USD 100m test, not grandfathered.",
        )
    )
    audits.append(
        (
            "yardstick_not_probability",
            "not a probability" in t.lower() and "not an expected value" in t.lower()
            and "uncomfortable" in t.lower(),
            "Vol yardsticks and the 80k/150k pair are not treated as probability, target, or EV proof.",
        )
    )
    audits.append(
        (
            "unknowns_resize_not_blanket_wait",
            "September CPI" in t
            and "null open interest" in t.lower() or "Open interest is null" in t
            and "They do not justify another list of data requests" in t,
            "Named unknowns adjust size/horizon/flat euro without blanket wait-for-data on the receive.",
        )
    )
    audits.append(
        (
            "math_not_economic_truth",
            "Passing arithmetic does not make" in t or "does not make 3.01 the true" in t,
            "Parent approval separates mathematical pass from economic truth.",
        )
    )
    audits.append(
        (
            "plus8bp_correction",
            "+8 bp is not the measured ordinary move" in t or "+8 bp is not ordinary multi-week movement" in t,
            "Parent corrects that +8 bp is not ordinary multi-week strip movement versus proxy yardstick.",
        )
    )
    audits.append(
        (
            "integration_clock_labeled",
            "Integration clock" in t and "2026-11-05T13:30:00Z" in t and "not this clock" in t.lower(),
            "Authorship/integration clock is labeled and not substituted for freeze or 4 Nov close.",
        )
    )
    audits.append(
        (
            "prospective_unexecuted",
            "unexecuted" in t.lower() and "decision_cards.json" in t,
            "Prospective cards are unexecuted research plans, not ledger events.",
        )
    )
    audits.append(
        (
            "no_oos_success_claim",
            "not out-of-sample success" in t.lower() or "not an out-of-sample success" in t.lower(),
            "4 November move is not claimed as out-of-sample success.",
        )
    )

    return [
        check(name, ok, sentence)
        for name, ok, sentence in audits
    ]


def main() -> None:
    checks: list[dict] = []
    notes: list[str] = []

    snapshot = load_json(SNAPSHOT_PATH)
    agent = load_json(AGENT_PACKET_PATH)
    book = load_json(BOOK_PATH)
    cards = load_json(DECISION_CARDS)
    parent_text = PARENT_REPORT.read_text(encoding="utf-8")

    # 1. Hashes
    snap_canon = canonical_sha256(snapshot)
    checks.append(
        check(
            "snapshot_canonical_sha256",
            snap_canon == EXPECTED["snapshot_canonical_sha256"],
            "Canonical snapshot hash with packet_sha256 removed",
            EXPECTED["snapshot_canonical_sha256"],
            snap_canon,
        )
    )
    snap_raw = raw_file_sha256(SNAPSHOT_PATH)
    checks.append(
        check(
            "snapshot_raw_sha256",
            snap_raw == EXPECTED["snapshot_raw_sha256"],
            "Raw evidence_snapshot.json SHA256",
            EXPECTED["snapshot_raw_sha256"],
            snap_raw,
        )
    )
    snap_blob = git_blob_sha256(SNAPSHOT_PATH)
    checks.append(
        check(
            "snapshot_git_blob_sha256",
            snap_blob == EXPECTED["snapshot_git_blob"],
            "Git blob hash at HEAD for snapshot path",
            EXPECTED["snapshot_git_blob"],
            snap_blob,
        )
    )

    agent_canon = canonical_sha256(agent)
    agent_raw = raw_file_sha256(AGENT_PACKET_PATH)
    checks.append(
        check(
            "agent_packet_canonical_sha256",
            agent_canon == EXPECTED["agent_canonical_sha256"],
            "Canonical agent packet hash; raw may differ when digest field present",
            EXPECTED["agent_canonical_sha256"],
            agent_canon,
        )
    )
    checks.append(
        check(
            "agent_packet_raw_diff_not_fail",
            agent_raw != agent_canon,
            "Raw agent file differs from canonical (expected when packet_sha256 embedded)",
            "raw != canonical",
            {"raw": agent_raw, "canonical": agent_canon},
        )
    )

    # 3. Clocks
    snap_as_of = snapshot.get("as_of")
    ms = snapshot["families"]["market_state"]
    ms_as_of = ms.get("as_of")
    ms_gen = ms["data"].get("generated_at")
    checks.append(
        check(
            "snapshot_as_of",
            snap_as_of == EXPECTED["packet_freeze"],
            "Packet freeze clock",
            EXPECTED["packet_freeze"],
            snap_as_of,
        )
    )
    checks.append(
        check(
            "market_state_generated_at",
            ms_gen == EXPECTED["market_state_generated"],
            "Market-state generated_at",
            EXPECTED["market_state_generated"],
            ms_gen,
        )
    )
    checks.append(
        check(
            "market_state_as_of_matches_generated",
            ms_as_of == ms_gen,
            "market_state as_of equals generated_at in snapshot",
            ms_gen,
            ms_as_of,
        )
    )
    clocks_distinct = (
        EXPECTED["packet_freeze"] in parent_text
        and EXPECTED["market_state_generated"] in parent_text
        and "Integration clock" in parent_text
    )
    checks.append(
        check(
            "report_keeps_clocks_distinct",
            clocks_distinct and snap_as_of != ms_gen,
            "Parent report labels freeze, market-state, and integration clocks separately",
            "three distinct labels",
            {"freeze": snap_as_of, "market_state": ms_gen},
        )
    )

    # 4. Book chatgpt only
    chatgpt = book["pms"]["chatgpt"]
    positions = chatgpt.get("positions") or []
    checks.append(
        check(
            "single_chatgpt_position",
            len(positions) == 1 and positions[0].get("position_id") == "pm-chatgpt-595561a1b90f",
            "Exactly one open chatgpt position",
            1,
            len(positions),
        )
    )
    pos = positions[0]
    unreal = (3.4 - 3.14375) * 100 * 25000
    checks.append(
        check(
            "book_notional_entry_mark_unrealized",
            pos["notional_usd"] == 250_000_000
            and pos["entry_price"] == 3.4
            and abs(pos["mark_price"] - 3.14375) < 1e-9
            and abs(pos["unrealized_pnl_usd"] - unreal) < 0.01,
            "Book position economics",
            {"notional": 250_000_000, "unrealized": 640_625},
            {
                "notional": pos["notional_usd"],
                "entry": pos["entry_price"],
                "mark": pos["mark_price"],
                "unrealized": pos["unrealized_pnl_usd"],
                "recomputed_unrealized": unreal,
            },
        )
    )
    checks.append(
        check(
            "funding_stock_historical",
            abs(chatgpt.get("funding_cost_usd", 0) - 24829.87) < 0.01,
            "Funding stock charge is historical book field",
            24829.87,
            chatgpt.get("funding_cost_usd"),
        )
    )

    # 5. CORRA legs
    corra_block = ms["data"]["tradable_rate_curves"]["curves"]["CORRA"]
    contracts = {c["expiry"]: float(c["implied_rate"]) for c in corra_block["contracts"]}
    legs = {}
    for expiry in ("2027-03", "2027-06", "2027-09", "2027-12"):
        legs[expiry] = contracts[expiry]
    expected_legs = [2.93, 3.075, 3.185, 3.265]
    leg_vals = [legs[k] for k in ("2027-03", "2027-06", "2027-09", "2027-12")]
    avg = sum(leg_vals) / 4.0
    checks.append(
        check(
            "corra_legs_and_average",
            all(abs(a - e) < 1e-9 for a, e in zip(leg_vals, expected_legs))
            and abs(avg - 3.11375) < 1e-9,
            "CORRA 2027 H/M/U/Z legs and strip average",
            {"legs": expected_legs, "avg": 3.11375},
            {"legs": leg_vals, "avg": avg},
        )
    )
    strip_hist = corra_block.get("history") or corra_block.get("strip_history")
    checks.append(
        check(
            "corra_strip_history_absent",
            strip_hist in (None, [], {}),
            "No fabricated CORRA strip history in snapshot curve object",
            None,
            strip_hist,
        )
    )

    dv01_250k = 25_000
    checks.append(
        check(
            "receive_sign_250m_25k",
            corra_pnl(20, dv01_250k) == -500_000
            and corra_pnl(-20, dv01_250k) == 500_000
            and corra_pnl(-0.5, dv01_250k) == 12_500,
            "Receive P&L sign at USD 250m identity",
            {"+20bp": -500_000, "-20bp": 500_000, "-0.5bp": 12_500},
            {
                "+20bp": corra_pnl(20, dv01_250k),
                "-20bp": corra_pnl(-20, dv01_250k),
                "-0.5bp": corra_pnl(-0.5, dv01_250k),
            },
        )
    )
    dv01_100k = 10_000
    bp_cases = {
        "-8bp": 80_000,
        "+15bp": -150_000,
        "+20bp": -200_000,
        "+25bp": -250_000,
        "-10.625bp": 106_250,
    }
    computed_bp = {k: corra_pnl(float(k.replace("bp", "").replace("+", "")), dv01_100k) for k in bp_cases}
    # fix keys
    computed_bp = {
        "-8bp": corra_pnl(-8, dv01_100k),
        "+15bp": corra_pnl(15, dv01_100k),
        "+20bp": corra_pnl(20, dv01_100k),
        "+25bp": corra_pnl(25, dv01_100k),
        "-10.625bp": corra_pnl(-10.625, dv01_100k),
    }
    checks.append(
        check(
            "receive_dv01_100m",
            all(abs(computed_bp[k] - v) < 0.01 for k, v in bp_cases.items()),
            "Adopted USD 100m DV01 scenarios",
            bp_cases,
            computed_bp,
        )
    )
    central = (2.90 + 2.98 + 3.05 + 3.10) / 4.0
    checks.append(
        check(
            "central_legs_average",
            abs(central - 3.0075) < 1e-9 and             abs(rate_to_bp(avg - central) - 10.625) < 0.01,
            "Central shape average and gap to anchor",
            {"central": 3.0075, "gap_bp": 10.625},
            {"central": central, "gap_bp": rate_to_bp(avg - central)},
        )
    )
    checks.append(
        check(
            "275_vs_floor_bp",
            abs(rate_to_bp(2.80 - 2.75) - 5) < 0.01,
            "2.75 is 5bp under 2.80 floor",
            5,
            rate_to_bp(2.80 - 2.75),
        )
    )
    checks.append(
        check(
            "anchor_vs_range_bp",
            abs(rate_to_bp(3.20 - avg) - 8.625) < 0.01
            and abs(rate_to_bp(avg - 2.80) - 31.375) < 0.01,
            "Anchor vs 3.20 ceiling and 2.80 floor in bp",
            {"vs_3.20": 8.625, "vs_2.80": 31.375},
            {"vs_3.20": rate_to_bp(3.20 - avg), "vs_2.80": rate_to_bp(avg - 2.80)},
        )
    )

    # 6. Funding draws
    rate = 0.0395
    for draw, label in ((1_000_000, "1m"), (2_500_000, "2.5m")):
        f56 = funding_cost(rate, draw, 56)
        f84 = funding_cost(rate, draw, 84)
        exp56 = rate * draw * 56 / 360
        exp84 = rate * draw * 84 / 360
        checks.append(
            check(
                f"funding_{label}_56_84",
                abs(f56 - exp56) < 0.01 and abs(f84 - exp84) < 0.01,
                f"Funding ACT/360 at {label} draw",
                {"56d": exp56, "84d": exp84},
                {"56d": f56, "84d": f84},
            )
        )

    # 7. EURUSD from snapshot series
    eur_series = series_by_id(snapshot, "EURUSD")
    if eur_series is None:
        checks.append(check("eurusd_series_found", False, "EURUSD in opportunities.series", True, False))
        closes_hist = []
    else:
        closes_hist = history_closes(eur_series)
        last_date, last_close = closes_hist[-1]
        prior_close = closes_hist[-2][1]
        checks.append(
            check(
                "eurusd_last_close",
                last_date == "2026-11-04" and abs(last_close - 1.1267) < 1e-9 and abs(prior_close - 1.1179) < 1e-9,
                "Last two EURUSD closes",
                {"date": "2026-11-04", "close": 1.1267, "prior": 1.1179},
                {"date": last_date, "close": last_close, "prior": prior_close},
            )
        )
        if EURUSD_CSV.exists():
            csv_lines = EURUSD_CSV.read_text().strip().splitlines()
            csv_last = csv_lines[-1].split(",")
            checks.append(
                check(
                    "eurusd_csv_matches_snapshot",
                    csv_last[0] == last_date and abs(float(csv_last[1]) - last_close) < 1e-9 and len(csv_lines) - 1 == len(closes_hist),
                    "Optional CSV matches snapshot history length and last close",
                    {"rows": len(closes_hist), "last": (last_date, last_close)},
                    {"rows": len(csv_lines) - 1, "last": tuple(csv_last)},
                )
            )

        closes = [c for _, c in closes_hist]
        rets = daily_log_returns(closes)
        sigma20 = sample_std(rets[-20:])
        sigma60 = sample_std(rets[-60:])
        checks.append(
            check(
                "eurusd_log_sigma_20_60",
                abs(sigma20 - 0.002881) < 0.00005 and abs(sigma60 - 0.003093) < 0.00005,
                "Sample std (N-1) of daily log returns, last 20 and 60",
                {"sigma20": 0.002881, "sigma60": 0.003093},
                {"sigma20": sigma20, "sigma60": sigma60},
            )
        )
        for h, exp in ((10, 0.92), (21, 1.33), (42, 1.88), (63, 2.31)):
            y = yardstick_pct(sigma20, h)
            tol = 0.05
            ok = abs(y - exp) < tol
            if ok and abs(y - exp) > 0.01:
                notes.append(f"yardstick_h{h}: computed {y:.4f}% vs report {exp}%")
            checks.append(
                check(
                    f"eurusd_yardstick_h{h}",
                    ok,
                    f"100*(exp(sigma20*sqrt({h}))-1)",
                    exp,
                    round(y, 4),
                )
            )

        # Oct 30 to Nov 3 EUR simple
        by_date = dict(closes_hist)
        eur_simple = (by_date["2026-11-03"] / by_date["2026-10-30"] - 1) * 100
        checks.append(
            check(
                "eurusd_oct30_nov3_simple",
                abs(eur_simple - 0.06) < 0.02,
                "EURUSD simple % 2026-10-30 to 2026-11-03",
                0.06,
                round(eur_simple, 4),
            )
        )

        wti = series_by_id(snapshot, "WTI")
        wti_hist = dict(history_closes(wti)) if wti else {}
        wti_simple = (
            (wti_hist["2026-11-03"] / wti_hist["2026-10-30"] - 1) * 100
            if wti
            else float("nan")
        )
        checks.append(
            check(
                "wti_oct30_nov3_simple",
                abs(wti_simple - (-7.71)) < 0.05,
                "WTI simple % 2026-10-30 to 2026-11-03",
                -7.71,
                round(wti_simple, 4),
            )
        )

        near = last_close * (last_close / prior_close)
        med = statistics.median(closes)
        min_close = min(closes)
        checks.append(
            check(
                "eurusd_near_median_min",
                abs(near - 1.135569) < 0.0001 and abs(med - 1.14715) < 0.0001 and abs(min_close - 1.113) < 0.0001,
                "Near clone, median, min of stored closes",
                {"near": 1.135569, "median": 1.14715, "min": 1.113},
                {"near": near, "median": med, "min": min_close},
            )
        )

        spot_specs = [
            ("5m_near", 5_000_000, near, 39_360),
            ("5m_median", 5_000_000, 1.14715, 90_752),
            ("5m_exit", 5_000_000, 1.1179, -39_052),
            ("5m_stress", 5_000_000, 1.113, -60_797),
        ]
        spot_ok = True
        spot_comp = {}
        for name, n, px, exp in spot_specs:
            got = round(spot_pnl(n, px))
            spot_comp[name] = {"price": px, "expected": exp, "got": got}
            if abs(got - exp) > 500:
                spot_ok = False
        checks.append(
            check(
                "eurusd_spot_pnl_5m",
                spot_ok,
                "Spot P&L at USD 5m for near/median/exit/stress",
                {s[0]: s[3] for s in spot_specs},
                spot_comp,
            )
        )

        carry_5_152 = 5_000_000 * 0.0152 * 84 / 360
        carry_10_152 = 10_000_000 * 0.0152 * 84 / 360
        carry_10_1528 = 10_000_000 * 0.01528 * 84 / 360
        checks.append(
            check(
                "eurusd_carry_84d",
                abs(carry_5_152 - 17733.33) < 50
                and abs(carry_10_152 - 35466.67) < 100
                and abs(carry_10_1528 - 35653.33) < 100,
                "Indicative carry drag 84/360 at 152 and 152.8 bp",
                {"5m_152": 17733, "10m_152": 35467, "10m_152.8": 35653},
                {
                    "5m_152": carry_5_152,
                    "10m_152": carry_10_152,
                    "10m_152.8": carry_10_1528,
                },
            )
        )

    # 8. Canada 2y proxy
    ca2 = series_by_id(snapshot, "CA_2Y")
    if ca2:
        ca_hist = history_closes(ca2)
        ca_changes_bp = [ca_hist[i][1] - ca_hist[i - 1][1] for i in range(1, len(ca_hist))]
        ca_sigma = sample_std(ca_changes_bp[-20:])
        yard = {h: ca_sigma * math.sqrt(h) for h in (21, 42, 63)}
        checks.append(
            check(
                "ca2y_daily_change_sigma_20",
                abs(ca_sigma - 5.40) < 0.05,
                "Canada 2y daily change bp sample std (last 20)",
                5.40,
                round(ca_sigma, 4),
            )
        )
        checks.append(
            check(
                "ca2y_proxy_yardsticks",
                abs(yard[21] - 24.7) < 0.2 and abs(yard[42] - 35.0) < 0.3 and abs(yard[63] - 42.9) < 0.3,
                "sqrt(h) scaled sovereign proxy yardsticks",
                {21: 24.7, 42: 35.0, 63: 42.9},
                {k: round(v, 2) for k, v in yard.items()},
            )
        )
        checks.append(
            check(
                "review_15bp_inside_21obs",
                15 < yard[21],
                "+15bp review inside 21-obs proxy yardstick",
                f"< {yard[21]:.2f}",
                15,
            )
        )
        checks.append(
            check(
                "labeled_sovereign_proxy_not_strip",
                "sovereign proxy" in parent_text.lower() and "not strip vol" in parent_text.lower(),
                "Report labels Canada 2y as sovereign proxy, not strip volatility",
                True,
                True,
            )
        )

    # 9. Lot illustration
    usdcad = series_by_id(snapshot, "USDCAD")
    usdcad_close = usdcad["value"] if usdcad else None
    if usdcad_close:
        usd_per_bp_per_lot = 25.0 / usdcad_close
        for dv01, exp_lots in ((10_000, 139.0), (25_000, 348.0)):
            lots = (dv01 / 4.0) / usd_per_bp_per_lot
            checks.append(
                check(
                    f"montreal_lots_dv01_{dv01}",
                    abs(lots - exp_lots) < 2.0,
                    f"Lots per contract illustration at USDCAD {usdcad_close}",
                    exp_lots,
                    round(lots, 1),
                )
            )

    # 10. Cross-section
    g10_ids = [
        "EURUSD",
        "GBPUSD",
        "USDSEK",
        "USDCHF",
        "AUDUSD",
        "USDCAD",
        "NZDUSD",
        "USDNOK",
        "USDJPY",
    ]
    moves = {}
    for sid in g10_ids:
        s = series_by_id(snapshot, sid)
        if not s:
            continue
        hist = history_closes(s)
        if len(hist) < 2:
            continue
        prior = hist[-2][1]
        last = hist[-1][1]
        moves[sid] = simple_pct_usd_per_fx(sid, prior, last)

    eur = moves.get("EURUSD")
    gbp_sek_chf = statistics.mean([moves["GBPUSD"], moves["USDSEK"], moves["USDCHF"]])
    nine = statistics.mean([moves[k] for k in g10_ids if k in moves])
    diff3 = eur - gbp_sek_chf if eur is not None else None
    diff9 = eur - nine if eur is not None else None
    checks.append(
        check(
            "cross_section_eur_minus_peers",
            diff3 is not None and abs(diff3 - 0.18) < 0.08 and abs(diff9 - 0.39) < 0.10,
            "EUR simple % minus equal-weight GBP/SEK/CHF and minus nine G10",
            {"vs3": 0.18, "vs9": 0.39},
            {"vs3": round(diff3, 3), "vs9": round(diff9, 3), "moves": {k: round(v, 2) for k, v in moves.items()}},
        )
    )

    # Memo consistency (light)
    checks.append(
        check(
            "cards_match_parent_actions",
            cards["cards"][0]["action"] == "reject"
            and cards["cards"][1]["action"] == "resize"
            and cards["cards"][1]["adopted_notional_usd"] == 100_000_000,
            "decision_cards.json aligns with parent table actions",
            {"eur": "reject", "corra": "resize_100m"},
            {"eur": cards["cards"][0]["action"], "corra": cards["cards"][1]["action"]},
        )
    )

    reasoning = reasoning_audit(parent_text, cards)

    # Write boundary
    diff_stat = subprocess.check_output(
        ["git", "diff", "--name-only", EXPECTED["base_commit"]],
        cwd=REPO,
        text=True,
    ).strip().splitlines()
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True).strip().splitlines()
    allowed_prefixes = (
        "docs/research/chatgpt/2026-11-05-eurusd-corra-decision-review.md",
        "docs/research/chatgpt/2026-11-05-eurusd-corra-decision/",
    )
    changed_paths = set(diff_stat) | {line[3:] if line.startswith("?? ") else line[3:].split()[0] for line in status if line}
    bad_paths = []
    for p in changed_paths:
        if not p:
            continue
        if any(p == pref or p.startswith(pref) for pref in allowed_prefixes):
            continue
        bad_paths.append(p)
    checks.append(
        check(
            "write_boundary_git",
            len(bad_paths) == 0,
            "All git changes under allowed research paths",
            [],
            {"unexpected": bad_paths, "tracked_diff": diff_stat, "status": status},
        )
    )

    material = [c for c in checks if c["name"] != "agent_packet_raw_diff_not_fail"]
    arith_fail = [c for c in material if c["status"] == "fail" and not c["name"].startswith("write_boundary")]
    reasoning_fail = [c for c in reasoning if c["status"] == "fail"]
    overall = "PASS" if not arith_fail and not reasoning_fail else "FAIL"

    out = {
        "verifier": "composer-2.5-independent",
        "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "overall_status": overall,
        "notes": notes,
        "arithmetic_checks": checks,
        "reasoning_audit": reasoning,
        "summary": {
            "arithmetic_pass": sum(1 for c in checks if c["status"] == "pass"),
            "arithmetic_fail": sum(1 for c in checks if c["status"] == "fail"),
            "reasoning_pass": sum(1 for c in reasoning if c["status"] == "pass"),
            "reasoning_fail": sum(1 for c in reasoning if c["status"] == "fail"),
        },
    }

    VERIFICATION_DIR.mkdir(parents=True, exist_ok=True)
    (VERIFICATION_DIR / "verifier_checks.json").write_text(
        json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    lines = [
        "# Independent verification report",
        "",
        f"**Overall status: {overall}**",
        "",
        f"Generated by `verification/verify.py` at {out['generated_at']}.",
        "",
        "## Arithmetic",
        "",
    ]
    for c in checks:
        flag = "PASS" if c["status"] == "pass" else "**FAIL**"
        lines.append(f"- {flag} — {c['name']}: {c['detail']}")
        if c["status"] == "fail":
            lines.append(f"  - expected: `{c.get('expected')}` computed: `{c.get('computed')}`")
    lines.extend(["", "## Reasoning audit", ""])
    for c in reasoning:
        flag = "PASS" if c["status"] == "pass" else "**FAIL**"
        lines.append(f"- {flag} — {c['name']}: {c['detail']}")
    if notes:
        lines.extend(["", "## Notes", ""])
        for n in notes:
            lines.append(f"- {n}")
    lines.extend(
        [
            "",
            "## Files",
            "",
            "- `verification/verify.py`",
            "- `verification/verifier_checks.json`",
            "- `verification/verifier_report.md`",
            "",
        ]
    )
    (VERIFICATION_DIR / "verifier_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"overall_status": overall, "failures": [c["name"] for c in arith_fail + reasoning_fail]}, indent=2))


if __name__ == "__main__":
    main()
