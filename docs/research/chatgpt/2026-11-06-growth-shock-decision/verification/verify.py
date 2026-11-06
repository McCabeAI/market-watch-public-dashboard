#!/usr/bin/env python3
"""Independent verifier for the 2026-11-06 growth-shock packet.

Stdlib only. Does not import calc.py or any analyst module.
Reads source/source_map.json and quant/results.json.
Reads book/fx/rates judgment JSON only to test whether a non-statistical
level in results was copied from a judgment rather than invented.
Writes verifier_checks.json and verifier_report.md beside this file.

Exit 0 when no unit, sign, lineage, sample, or horizon check fails.
Economic objections are recorded as class economic, status pass, and do
not affect the exit code.
"""

from __future__ import annotations

import json
import math
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple


ROOT = Path(__file__).resolve().parent.parent
SOURCE_PATH = ROOT / "source" / "source_map.json"
RESULTS_PATH = ROOT / "quant" / "results.json"
JUDGMENT_PATHS = {
    "book": ROOT / "book" / "judgment.json",
    "fx": ROOT / "fx" / "judgment.json",
    "rates": ROOT / "rates" / "judgment.json",
}
OUT_JSON = Path(__file__).resolve().parent / "verifier_checks.json"
OUT_MD = Path(__file__).resolve().parent / "verifier_report.md"

EMBEDDED_HASH = "57cbe09b78e90e4d87a1fc08764ce3f0983ef627fa58c168f36bd2db09081ac8"
CORRA_CODES = ("CRAH27", "CRAM27", "CRAU27", "CRAZ27")
CORRA_RATES = {
    "CRAH27": Decimal("2.885"),
    "CRAM27": Decimal("3.01"),
    "CRAU27": Decimal("3.11"),
    "CRAZ27": Decimal("3.20"),
}
BOOK_MARK = Decimal("3.10875")
BOOK_ENTRY = Decimal("3.4")
SR3_RATE = Decimal("4.24")
SR3_PRICE = Decimal("95.76")
FUNDING_RATE = Decimal("3.94")
EUR_ENTRY = Decimal("1.1267")
EUR_SPOT = Decimal("1.1224")
EUR_NOTIONAL = Decimal("5000000")
CORRA_NOTIONAL_100M = Decimal("100000000")
CORRA_NOTIONAL_50M = Decimal("50000000")
CORRA_ADVERSE = Decimal("3.26")
EUR_ADVERSE = Decimal("1.113")
LOSS_BUDGET_CORRA = Decimal("100000")
SR3_BUDGET = Decimal("10000")
SR3_RECEIVE_ADVERSE = Decimal("4.53")
SR3_PAY_ADVERSE = Decimal("3.94")
HARD_CLASSES = {"unit", "sign", "lineage", "sample", "horizon"}
FORBIDDEN = ("post_rate", "cumulative_bp", "incremental_bp")


def D(x: Any) -> Decimal:
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def nearest_dollar(x: Decimal) -> int:
    return int(D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fnum(x: Any) -> float:
    return float(x)


def usd_close(claimed: Any, reproduced: Any) -> bool:
    diff = abs(fnum(claimed) - fnum(reproduced))
    scale = max(abs(fnum(claimed)), abs(fnum(reproduced)), 1.0)
    return diff <= 0.02 or (diff / scale) <= 1e-9


def nearest_close(claimed_nearest: Any, reproduced: Any) -> bool:
    return abs(fnum(claimed_nearest) - nearest_dollar(D(reproduced))) <= 1.0


def num_close(claimed: Any, reproduced: Any, abs_tol: float = 1e-6, rel_tol: float = 1e-9) -> bool:
    diff = abs(fnum(claimed) - fnum(reproduced))
    scale = max(abs(fnum(claimed)), abs(fnum(reproduced)), 1.0)
    return diff <= abs_tol or (diff / scale) <= rel_tol


def rel_err(claimed: Any, reproduced: Any) -> float:
    denom = max(abs(fnum(reproduced)), 1e-15)
    return abs(fnum(claimed) - fnum(reproduced)) / denom


def sample_std(values: Sequence[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    var = sum((x - mean) ** 2 for x in values) / (n - 1)
    return math.sqrt(var)


def population_std(values: Sequence[float]) -> float:
    n = len(values)
    if n < 1:
        return 0.0
    mean = sum(values) / n
    var = sum((x - mean) ** 2 for x in values) / n
    return math.sqrt(var)


def median_even_average(levels: Sequence[float]) -> float:
    ordered = sorted(levels)
    n = len(ordered)
    if n == 0:
        raise ValueError("empty median")
    if n % 2 == 1:
        return ordered[n // 2]
    return 0.5 * (ordered[n // 2 - 1] + ordered[n // 2])


def series_changes(series: Dict[str, Any]) -> Tuple[List[float], str]:
    hist = series.get("history") or []
    unit = series.get("unit")
    out: List[float] = []
    if unit == "bp":
        for i in range(1, len(hist)):
            out.append(float(hist[i][1]) - float(hist[i - 1][1]))
        return out, "daily_difference_bp"
    for i in range(1, len(hist)):
        p0 = float(hist[i - 1][1])
        p1 = float(hist[i][1])
        if p0 <= 0 or p1 <= 0:
            raise ValueError(f"{series.get('id')}: non-positive level")
        out.append(100.0 * math.log(p1 / p0))
    return out, "hundred_times_log_return"


def extreme(hist: Sequence[Sequence[Any]], which: str) -> Tuple[str, float, List[str]]:
    levels = [float(row[1]) for row in hist]
    if which == "max":
        target = max(levels)
    else:
        target = min(levels)
    dates = [str(row[0]) for row, level in zip(hist, levels) if num_close(level, target, abs_tol=1e-9, rel_tol=0.0)]
    # ties within a tight absolute tolerance of the extreme
    dates = []
    for row in hist:
        level = float(row[1])
        if abs(level - target) <= 1e-9 or abs(level - target) <= 1e-12 * max(abs(target), 1.0):
            dates.append(str(row[0]))
    return dates[0], target, dates


def walk_numbers(obj: Any) -> Iterable[float]:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        yield float(obj)
        return
    if isinstance(obj, dict):
        for value in obj.values():
            yield from walk_numbers(value)
        return
    if isinstance(obj, list):
        for value in obj:
            yield from walk_numbers(value)


def level_known(value: float, pool: Sequence[float], abs_tol: float = 1e-6) -> bool:
    for other in pool:
        if num_close(value, other, abs_tol=abs_tol, rel_tol=1e-9):
            return True
    return False


def jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        text = format(value, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        try:
            as_float = float(value)
            if num_close(as_float, value, abs_tol=1e-12, rel_tol=1e-12):
                return as_float
        except Exception:
            pass
        return text
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return str(value)
        return value
    return value


class Verifier:
    def __init__(self) -> None:
        self.checks: List[Dict[str, Any]] = []
        self.figures: Dict[str, Any] = {}

    def add(
        self,
        check_id: str,
        check_class: str,
        status: str,
        claimed: Any,
        reproduced: Any,
        detail: str,
    ) -> None:
        if check_class not in HARD_CLASSES | {"economic"}:
            raise ValueError(check_class)
        if status not in {"pass", "fail"}:
            raise ValueError(status)
        self.checks.append(
            {
                "id": check_id,
                "class": check_class,
                "status": status,
                "claimed": jsonable(claimed),
                "reproduced": jsonable(reproduced),
                "detail": detail,
            }
        )

    def ok(self, flag: bool) -> str:
        return "pass" if flag else "fail"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def contract_by_code(contracts: Sequence[Dict[str, Any]], code: str) -> Dict[str, Any]:
    for contract in contracts:
        if contract.get("code") == code:
            return contract
    raise KeyError(code)


def build_report(verifier: Verifier, exit_code: int) -> str:
    counts: Dict[str, Dict[str, int]] = {}
    for check in verifier.checks:
        bucket = counts.setdefault(check["class"], {"pass": 0, "fail": 0})
        bucket[check["status"]] += 1
    order = ["unit", "sign", "lineage", "sample", "horizon", "economic"]
    lines: List[str] = []
    lines.append("# Verifier report: 2026-11-06 growth-shock packet")
    lines.append("")
    lines.append(f"Process exit code: {exit_code}.")
    lines.append("")
    lines.append("## Pass and fail counts")
    lines.append("")
    lines.append("| class | pass | fail |")
    lines.append("| --- | ---: | ---: |")
    for name in order:
        bucket = counts.get(name, {"pass": 0, "fail": 0})
        lines.append(f"| {name} | {bucket['pass']} | {bucket['fail']} |")
    lines.append("")
    failed = [c for c in verifier.checks if c["status"] == "fail"]
    lines.append("## Failed checks")
    lines.append("")
    if not failed:
        lines.append("No check failed.")
    else:
        lines.append("Quoted in full.")
        lines.append("")
        for check in failed:
            lines.append(f"### {check['id']}")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(check, indent=2, sort_keys=False))
            lines.append("```")
            lines.append("")
    lines.append("## Reproduced figures")
    lines.append("")
    fig = verifier.figures
    lines.append(
        f"- EUR mark-to-market versus entry, 5,000,000 * (1.1224/1.1267 - 1): "
        f"unrounded {fig.get('eur_mtm_unrounded')}, nearest dollar {fig.get('eur_mtm_nearest')}."
    )
    lines.append(
        f"- Specified short window is the last 20 observations, which is "
        f"{fig.get('short_window_correct_n')} changes. Published short-window n_changes is "
        f"{fig.get('short_window_published_n')}."
    )
    lines.append(
        f"- CA_2Y 19-change sample standard deviation: {fig.get('ca2y_std_19')}. "
        f"EURUSD 19-change sample standard deviation: {fig.get('eurusd_std_19')}."
    )
    lines.append(
        f"- EURUSD median of 126 closes: {fig.get('eurusd_median')}. "
        f"Median claim 1.1467 passed: {fig.get('median_claim_passed')}."
    )
    lines.append(
        f"- CORRA equal-weight mean {fig.get('corra_mean')}; gap versus book mark 3.10875 "
        f"is {fig.get('gap_bp')} bp; receive PnL at 100m is {fig.get('receive_pnl_100m')}."
    )
    lines.append(
        f"- Book identity (3.4 - 3.10875) * 100 * 10000 = {fig.get('book_identity')}."
    )
    lines.append(
        f"- Financing on the draw, ACT/360, 3.94 percent, 70 calendar days: "
        f"500,000 costs {fig.get('financing_500k')}; 50,000 costs {fig.get('financing_50k')}."
    )
    lines.append(
        f"- CORRA 50m to 3.26 PnL {fig.get('corra_50m_pnl')}; EUR 5m to 1.113 PnL "
        f"{fig.get('eur_5m_pnl')}; sum of those nearest dollars {fig.get('sum_nearest')}."
    )
    lines.append(
        f"- Budget-implied CORRA notional {fig.get('budget_corra_notional')}; "
        f"overrun of the 100,000 budget at 50m is {fig.get('overrun')}."
    )
    lines.append(
        f"- SR3 10m receive adverse PnL {fig.get('sr3_10m_receive')}; "
        f"10m pay adverse PnL {fig.get('sr3_10m_pay')}; "
        f"budget-implied receive notional in USD {fig.get('sr3_receive_notional')} "
        f"(10000/(29*25) million dollars, times 1,000,000)."
    )
    lines.append("")
    lines.append("## Objections")
    lines.append("")
    lines.append(
        "Economic rows are judgment limits, not arithmetic failures. "
        "They are status pass so they stay on the record and do not change the exit code. "
        "Horizon fails only when full-sample std times sqrt(h) is wrong or 70 is under the square root."
    )
    lines.append("")
    for check in verifier.checks:
        if check["class"] == "economic" or (
            check["class"] == "horizon" and check["status"] == "pass" and "objection" in check["detail"].lower()
        ):
            lines.append(f"- `{check['id']}` ({check['class']}, {check['status']}). {check['detail']}")
            lines.append(f"  - claimed: `{json.dumps(check['claimed'])}`")
            lines.append(f"  - reproduced: `{json.dumps(check['reproduced'])}`")
    lines.append("")
    lines.append("## What this report is not")
    lines.append("")
    lines.append(
        "This is an objection list with recomputed figures. It does not choose a position, "
        "a size, or a fair value."
    )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    source = load_json(SOURCE_PATH)
    results = load_json(RESULTS_PATH)
    results_text = RESULTS_PATH.read_text(encoding="utf-8")
    judgments = {name: load_json(path) for name, path in JUDGMENT_PATHS.items()}
    judgment_numbers: List[float] = []
    for payload in judgments.values():
        judgment_numbers.extend(walk_numbers(payload))

    verifier = Verifier()
    series_by_id = {row["id"]: row for row in source["series"]}
    bindings = source["bindings"]
    embedded = bindings["embedded_packet_sha256_in_snapshot"]
    base_hash = bindings["agent_packet_fields"]["base_packet_sha256"]
    outer_hash = bindings["agent_packet_fields"]["packet_sha256"]
    echo = results["bindings_echo"]
    echo_embedded = echo.get("embedded_packet_sha256_in_snapshot")
    echo_agent = echo.get("agent_packet_sha256")

    source_hash_ok = embedded == EMBEDDED_HASH and base_hash == EMBEDDED_HASH
    verifier.add(
        "lineage_source_embedded_packet_hash",
        "lineage",
        verifier.ok(source_hash_ok),
        {"embedded_packet_sha256_in_snapshot": embedded, "base_packet_sha256": base_hash},
        EMBEDDED_HASH,
        "source_map bindings embedded hash and agent_packet_fields.base_packet_sha256 "
        "are the snapshot embedded packet hash.",
    )
    echo_ok = (
        echo_embedded == EMBEDDED_HASH
        and echo_embedded == embedded
        and echo_agent == outer_hash
        and echo_agent is not None
    )
    verifier.add(
        "lineage_results_bindings_echo_hashes",
        "lineage",
        verifier.ok(echo_ok),
        {
            "embedded_packet_sha256_in_snapshot": echo_embedded,
            "agent_packet_sha256": echo_agent,
        },
        {
            "embedded_packet_sha256_in_snapshot": EMBEDDED_HASH,
            "agent_packet_sha256": outer_hash,
        },
        "bindings_echo.embedded_packet_sha256_in_snapshot must equal the snapshot embedded hash "
        f"{EMBEDDED_HASH} and source_map.bindings.embedded_packet_sha256_in_snapshot. "
        "bindings_echo.agent_packet_sha256 must equal source_map.bindings.agent_packet_fields.packet_sha256. "
        "Those two hashes are different fields. A difference between them is not a failure.",
    )

    corra_contracts = source["tradable_curves"]["CORRA"]["contracts"]
    subset = source["tradable_curves"]["CORRA"]["contracts_subset_2027_HMUZ"]
    subset_by_code = {row["code"]: row for row in subset}
    nc = results["noncanonical_mark"]["corra_four_contracts_mean_implied_percent"]
    claimed_codes = list(nc["contracts"])
    claimed_rates = [D(x) for x in nc["implied_rates_percent"]]
    source_rates = []
    rate_mismatches = []
    obs_dates = {}
    for code in CORRA_CODES:
        full = contract_by_code(corra_contracts, code)
        sub = subset_by_code[code]
        source_rates.append(D(str(full["implied_rate"])))
        obs_dates[code] = full.get("observation_date")
        if D(str(full["implied_rate"])) != CORRA_RATES[code] or D(str(sub["implied_rate"])) != CORRA_RATES[code]:
            rate_mismatches.append(
                {
                    "code": code,
                    "full": full["implied_rate"],
                    "subset": sub["implied_rate"],
                    "expected": str(CORRA_RATES[code]),
                }
            )
        price_ok = num_close(full["price"], 100.0 - float(full["implied_rate"]), abs_tol=1e-9, rel_tol=1e-12)
        if not price_ok:
            rate_mismatches.append({"code": code, "price": full["price"], "implied": full["implied_rate"]})
    rates_block_ok = (
        claimed_codes == list(CORRA_CODES)
        and claimed_rates == [CORRA_RATES[c] for c in CORRA_CODES]
        and not rate_mismatches
    )
    verifier.add(
        "lineage_corra_hmuz_implied_rates",
        "lineage",
        verifier.ok(rates_block_ok),
        {"contracts": claimed_codes, "implied_rates_percent": nc["implied_rates_percent"]},
        {"contracts": list(CORRA_CODES), "implied_rates_percent": [str(CORRA_RATES[c]) for c in CORRA_CODES]},
        "Noncanonical CRAH27/CRAM27/CRAU27/CRAZ27 implied rates must match the source-map "
        "contracts and the 2027 HMUZ subset. Prices in the source map equal 100 minus the implied rate."
        + ("" if not rate_mismatches else f" Mismatches: {rate_mismatches}."),
    )

    sr3 = contract_by_code(source["tradable_curves"]["SOFR"]["contracts"], "SR3H7")
    sr3_id = results["identity_checks"]["SR3H7_from_tradable_curves"]
    sr3_ok = (
        D(str(sr3["implied_rate"])) == SR3_RATE
        and D(str(sr3["price"])) == SR3_PRICE
        and num_close(sr3["price"], 100.0 - float(sr3["implied_rate"]), abs_tol=1e-9, rel_tol=1e-12)
        and num_close(sr3_id["implied_rate_percent"], SR3_RATE, abs_tol=1e-12, rel_tol=1e-12)
        and num_close(sr3_id["price"], SR3_PRICE, abs_tol=1e-12, rel_tol=1e-12)
    )
    verifier.add(
        "lineage_sr3h7_rate_and_price",
        "lineage",
        verifier.ok(sr3_ok),
        {"results_price": sr3_id["price"], "results_implied": sr3_id["implied_rate_percent"]},
        {"source_price": sr3["price"], "source_implied": sr3["implied_rate"], "expected_price": "95.76", "expected_implied": "4.24"},
        "SR3H7 implied rate is 4.24 and price is 95.76, and price = 100 - implied rate.",
    )

    eurusd = series_by_id["EURUSD"]
    us2y = series_by_id["US_2Y"]
    ea2y = series_by_id["EA_2Y"]
    eur_last_ok = (
        num_close(eurusd["last_value"], EUR_SPOT, abs_tol=1e-12, rel_tol=1e-12)
        and eurusd.get("as_of") == "2026-11-05"
        and eurusd.get("last_date") == "2026-11-05"
        and num_close(eurusd["history"][-1][1], eurusd["last_value"], abs_tol=1e-12, rel_tol=1e-12)
        and num_close(results["noncanonical_mark"]["eur_long_spot_vs_entry"]["frozen_spot_from_EURUSD_series_last"], EUR_SPOT, abs_tol=1e-12, rel_tol=1e-12)
    )
    verifier.add(
        "lineage_eurusd_last_and_asof",
        "lineage",
        verifier.ok(eur_last_ok),
        {
            "results_spot": results["noncanonical_mark"]["eur_long_spot_vs_entry"]["frozen_spot_from_EURUSD_series_last"],
        },
        {"last_value": eurusd["last_value"], "as_of": eurusd.get("as_of"), "last_date": eurusd.get("last_date")},
        "EURUSD last_value is 1.1224 and as_of / last_date are 2026-11-05. The history endpoint matches last_value.",
    )
    carry = results["eur_carry_sensitivity"]["series_based"]
    us_ok = (
        num_close(us2y["last_value"], 446, abs_tol=1e-9, rel_tol=1e-12)
        and us2y.get("as_of") == "2026-11-05"
        and us2y.get("last_date") == "2026-11-05"
        and num_close(carry["US_2Y_last_bp"], 446, abs_tol=1e-9, rel_tol=1e-12)
        and carry["US_2Y_last_as_of"] == "2026-11-05"
        and num_close(carry["US_2Y_as_percent_from_bp"], 4.46, abs_tol=1e-12, rel_tol=1e-12)
    )
    verifier.add(
        "lineage_us2y_last_446bp",
        "lineage",
        verifier.ok(us_ok),
        {"results_bp": carry["US_2Y_last_bp"], "results_as_of": carry["US_2Y_last_as_of"], "results_percent": carry["US_2Y_as_percent_from_bp"]},
        {"last_value_bp": us2y["last_value"], "as_of": us2y.get("as_of"), "percent": 4.46},
        "US_2Y last is 446 bp on 2026-11-05, which is 4.46 percent. A 100x reading of 446 as percent would fail.",
    )
    ea_ok = (
        num_close(ea2y["last_value"], 295, abs_tol=1e-9, rel_tol=1e-12)
        and ea2y.get("as_of") == "2026-11-06"
        and ea2y.get("last_date") == "2026-11-06"
        and num_close(carry["EA_2Y_last_bp"], 295, abs_tol=1e-9, rel_tol=1e-12)
        and carry["EA_2Y_last_as_of"] == "2026-11-06"
        and num_close(carry["EA_2Y_as_percent_from_bp"], 2.95, abs_tol=1e-12, rel_tol=1e-12)
    )
    verifier.add(
        "lineage_ea2y_last_295bp",
        "lineage",
        verifier.ok(ea_ok),
        {"results_bp": carry["EA_2Y_last_bp"], "results_as_of": carry["EA_2Y_last_as_of"], "results_percent": carry["EA_2Y_as_percent_from_bp"]},
        {"last_value_bp": ea2y["last_value"], "as_of": ea2y.get("as_of"), "percent": 2.95},
        "EA_2Y last is 295 bp on 2026-11-06, which is 2.95 percent.",
    )

    funding = source["tradable_curves"]["funding_context_sofr"]
    fund_res = results["identity_checks"]["funding_context_sofr_matches_candidate_card"]
    fund_ok = (
        D(str(funding["percent_rate"])) == FUNDING_RATE
        and funding.get("observation_date") == "2026-11-04"
        and funding.get("convention") == "ACT/360"
        and int(funding.get("day_count")) == 360
        and num_close(fund_res["percent_rate"], FUNDING_RATE, abs_tol=1e-12, rel_tol=1e-12)
        and fund_res.get("observation_date") == "2026-11-04"
    )
    verifier.add(
        "lineage_funding_3_94_on_2026_11_04",
        "lineage",
        verifier.ok(fund_ok),
        {"percent_rate": fund_res["percent_rate"], "observation_date": fund_res["observation_date"]},
        {"percent_rate": funding["percent_rate"], "observation_date": funding["observation_date"], "convention": funding["convention"], "day_count": funding["day_count"]},
        "Financing reference is the SOFR fixing at 3.94 percent, observation 2026-11-04, ACT/360.",
    )

    book = source["book"]["pms_chatgpt"]
    positions = {row["instrument"]: row for row in book["positions"]}
    corra_pos = positions["CORRA_2027H-Z"]
    eur_pos = positions["EURUSD"]
    ident = results["identity_checks"]["corra_book_identity_parallel_average"]
    book_ok = (
        D(str(corra_pos["entry_price"])) == BOOK_ENTRY
        and D(str(corra_pos["mark_price"])) == BOOK_MARK
        and num_close(corra_pos["unrealized_pnl_usd"], 291250, abs_tol=1e-6, rel_tol=1e-12)
        and num_close(book["unrealized_pnl_usd"], 291250, abs_tol=1e-6, rel_tol=1e-12)
        and D(str(ident["entry_implied_percent"])) == BOOK_ENTRY
        and D(str(ident["book_mark_implied_percent"])) == BOOK_MARK
        and D(str(eur_pos["entry_price"])) == EUR_ENTRY
        and D(str(eur_pos["notional_usd"])) == EUR_NOTIONAL
        and D(str(results["noncanonical_mark"]["eur_long_spot_vs_entry"]["entry"])) == EUR_ENTRY
        and D(str(results["noncanonical_mark"]["eur_long_spot_vs_entry"]["notional_usd"])) == EUR_NOTIONAL
    )
    verifier.add(
        "lineage_book_entry_mark_unrealized_and_eur",
        "lineage",
        verifier.ok(book_ok),
        {
            "results_entry": ident["entry_implied_percent"],
            "results_mark": ident["book_mark_implied_percent"],
            "results_eur_entry": results["noncanonical_mark"]["eur_long_spot_vs_entry"]["entry"],
            "results_eur_notional": results["noncanonical_mark"]["eur_long_spot_vs_entry"]["notional_usd"],
        },
        {
            "entry": str(BOOK_ENTRY),
            "mark": str(BOOK_MARK),
            "unrealized": 291250,
            "eur_entry": str(EUR_ENTRY),
            "eur_notional": 5000000,
            "book_position_unrealized": corra_pos["unrealized_pnl_usd"],
            "book_total_unrealized": book["unrealized_pnl_usd"],
        },
        "Cited book facts: CORRA entry 3.4, mark 3.10875, unrealized 291250; EUR entry 1.1267, notional 5e6.",
    )

    mean = sum(CORRA_RATES.values(), Decimal("0")) / Decimal(len(CORRA_RATES))
    gap_bp = (mean - BOOK_MARK) * Decimal(100)
    receive_100m = (BOOK_MARK - mean) * Decimal(100) * Decimal(10000)
    identity_pnl = (BOOK_ENTRY - BOOK_MARK) * Decimal(100) * Decimal(10000)
    verifier.figures["corra_mean"] = str(mean)
    verifier.figures["gap_bp"] = str(gap_bp)
    verifier.figures["receive_pnl_100m"] = str(receive_100m)
    verifier.figures["book_identity"] = str(identity_pnl)

    mean_ok = num_close(nc["arithmetic_mean"], mean, abs_tol=1e-12, rel_tol=1e-12) and mean == Decimal("3.05125")
    verifier.add(
        "unit_corra_four_rate_mean",
        "unit",
        verifier.ok(mean_ok),
        nc["arithmetic_mean"],
        str(mean),
        "Arithmetic mean of 2.885, 3.01, 3.11 and 3.20 is 3.05125. Nothing is subtracted inside the mean.",
    )
    gap_ok = num_close(nc["gap_bp_unrounded"], gap_bp, abs_tol=1e-6, rel_tol=1e-9) and gap_bp == Decimal("-5.75")
    verifier.add(
        "unit_corra_gap_bp_versus_book_mark",
        "unit",
        verifier.ok(gap_ok),
        nc["gap_bp_unrounded"],
        str(gap_bp),
        "Gap in bp is (mean - 3.10875) * 100 = -5.75. A sign flip or a 100x percent/bp mix fails this check.",
    )
    pnl_ok = (
        usd_close(nc["pnl_usd_unrounded"], receive_100m)
        and nearest_close(nc["nearest_dollar_pnl_at_100m_book_parallel"], receive_100m)
        and receive_100m == Decimal("57500")
    )
    hundred_x = abs(fnum(nc["pnl_usd_unrounded"]) - fnum(receive_100m) * 100) < 1 or abs(fnum(nc["pnl_usd_unrounded"]) * 100 - fnum(receive_100m)) < 1
    verifier.add(
        "unit_corra_receive_pnl_100m",
        "unit",
        verifier.ok(pnl_ok and not hundred_x),
        {"unrounded": nc["pnl_usd_unrounded"], "nearest_dollar": nc["nearest_dollar_pnl_at_100m_book_parallel"]},
        {"unrounded": str(receive_100m), "nearest_dollar": nearest_dollar(receive_100m)},
        "Receive PnL at 100m is (3.10875 - mean) * 100 * 10000 = 57500. "
        "DV01 is 10000 USD per bp per 100m. A 100x scaling fails.",
    )
    identity_ok = (
        usd_close(ident["unrealized_usd_identity_check"], identity_pnl)
        and identity_pnl == Decimal("291250")
        and num_close(ident["usd_per_bp_per_100m_notional"], 10000, abs_tol=1e-6, rel_tol=1e-12)
    )
    verifier.add(
        "unit_book_unrealized_identity",
        "unit",
        verifier.ok(identity_ok),
        ident["unrealized_usd_identity_check"],
        str(identity_pnl),
        "Identity (3.4 - 3.10875) * 100 * 10000 = 291250. Float dust inside 0.02 USD passes.",
    )

    bp_receive = (SR3_RECEIVE_ADVERSE - SR3_RATE) * Decimal(100)
    bp_pay = (SR3_RATE - SR3_PAY_ADVERSE) * Decimal(100)
    sr3_10m_receive = -bp_receive * Decimal(25) * (Decimal("10000000") / Decimal("1000000"))
    sr3_10m_pay = -bp_pay * Decimal(25) * (Decimal("10000000") / Decimal("1000000"))
    sr3_block = results["portfolio"]["declined_illustrations"]["sr3h7_declined_at_compare_10m_and_budget_implied"]
    recv_claimed = sr3_block["receive_adverse"]["compare_at_10m"]
    pay_claimed = sr3_block["pay_adverse"]["compare_at_10m"]
    corra_scaled_10m = bp_receive * Decimal(10000) * (Decimal("10000000") / Decimal("100000000"))
    sr3_scaled_ok = (
        bp_receive == Decimal(29)
        and bp_pay == Decimal(30)
        and usd_close(recv_claimed["unrounded"], sr3_10m_receive)
        and nearest_close(recv_claimed["nearest_dollar"], sr3_10m_receive)
        and usd_close(pay_claimed["unrounded"], sr3_10m_pay)
        and nearest_close(pay_claimed["nearest_dollar"], sr3_10m_pay)
        and sr3_10m_receive == Decimal("-7250")
        and sr3_10m_pay == Decimal("-7500")
        and not usd_close(recv_claimed["unrounded"], -corra_scaled_10m)
    )
    dv01_fields_ok = True
    for cand in results["candidates"]:
        if cand.get("instrument") == "SR3H7":
            if cand.get("dv01_usd_per_bp_per_1m") != 25:
                dv01_fields_ok = False
        if str(cand.get("instrument", "")).startswith("CORRA"):
            if cand.get("dv01_usd_per_bp_per_100m") != 10000:
                dv01_fields_ok = False
    verifier.figures["sr3_10m_receive"] = str(sr3_10m_receive)
    verifier.figures["sr3_10m_pay"] = str(sr3_10m_pay)
    verifier.add(
        "unit_sr3_dv01_not_corra_book_scale",
        "unit",
        verifier.ok(sr3_scaled_ok and dv01_fields_ok),
        {
            "receive_10m": recv_claimed["unrounded"],
            "pay_10m": pay_claimed["unrounded"],
            "receive_nearest": recv_claimed["nearest_dollar"],
            "pay_nearest": pay_claimed["nearest_dollar"],
        },
        {
            "receive_bp": str(bp_receive),
            "pay_bp": str(bp_pay),
            "receive_pnl": str(sr3_10m_receive),
            "pay_pnl": str(sr3_10m_pay),
            "corra_style_10m_receive_would_be": str(-corra_scaled_10m),
        },
        "Single SR3 DV01 is 25 USD per bp per 1m notional. At 10m, 29 bp adverse on a receive is -7250 "
        "and 30 bp adverse on a pay is -7500. The CORRA identity of 10000 USD per bp per 100m would price "
        "the same 10m receive at -2900 to -29000 depending on the 100m scaling; the published -7250 is not that identity.",
    )

    percent_from_bp_ok = num_close(Decimal(446) / Decimal(100), carry["US_2Y_as_percent_from_bp"], abs_tol=1e-12, rel_tol=1e-12)
    verifier.add(
        "unit_yield_bp_versus_percent",
        "unit",
        verifier.ok(us_ok and ea_ok and percent_from_bp_ok),
        {"US_2Y_percent": carry["US_2Y_as_percent_from_bp"], "EA_2Y_percent": carry["EA_2Y_as_percent_from_bp"]},
        {"US_2Y_percent": "4.46", "EA_2Y_percent": "2.95"},
        "Yield history is in bp. Percent used in the carry sensitivity is bp/100. 446 bp is not 446 percent.",
    )

    yardsticks = results["yardsticks"]
    change_rule_ok = True
    change_rule_detail = {}
    my_changes: Dict[str, List[float]] = {}
    my_rules: Dict[str, str] = {}
    for sid, block in yardsticks.items():
        changes, rule = series_changes(series_by_id[sid])
        my_changes[sid] = changes
        my_rules[sid] = rule
        change_rule_detail[sid] = {"results": block.get("change_rule"), "reproduced": rule, "source_unit": series_by_id[sid].get("unit")}
        if block.get("change_rule") != rule:
            change_rule_ok = False
        if rule == "hundred_times_log_return" and series_by_id[sid].get("unit") == "bp":
            change_rule_ok = False
        if rule == "daily_difference_bp" and series_by_id[sid].get("unit") != "bp":
            change_rule_ok = False
    verifier.add(
        "unit_change_rule_log_percent_and_yield_bp",
        "unit",
        verifier.ok(change_rule_ok),
        {sid: block.get("change_rule") for sid, block in yardsticks.items()},
        {sid: my_rules[sid] for sid in yardsticks},
        "Price, spot, and index yardsticks use hundred_times_log_return, which is 100*ln(p1/p0), percent-log units. "
        "Yield yardsticks use daily_difference_bp. Pass requires the results change_rule to say that.",
    )

    fin = results["financing"]["prospective_preferred_set"]
    cost_500k = Decimal("500000") * (FUNDING_RATE / Decimal(100)) * (Decimal(70) / Decimal(360))
    cost_50k = Decimal("50000") * (FUNDING_RATE / Decimal(100)) * (Decimal(70) / Decimal(360))
    cost_1m = Decimal("1000000") * (FUNDING_RATE / Decimal(100)) * (Decimal(70) / Decimal(360))
    cost_zero = Decimal(0)
    fin_lines = fin["lines"]
    sq = results["financing"]["status_quo_financing_comparison_not_preferred"]["lines"]
    fin_ok = (
        int(fin["financing_horizon_days"]) == 70
        and num_close(fin["financing_rate_percent"], FUNDING_RATE, abs_tol=1e-12, rel_tol=1e-12)
        and int(fin["day_count"]) == 360
        and usd_close(fin_lines["corra_cut_50m"]["cost_usd_unrounded"], cost_500k)
        and usd_close(fin_lines["eur_hold_5m"]["cost_usd_unrounded"], cost_50k)
        and usd_close(fin_lines["sofr_h7_flat"]["cost_usd_unrounded"], cost_zero)
        and usd_close(fin["sum_cost_usd_unrounded"], cost_500k + cost_50k + cost_zero)
        and D(str(fin_lines["corra_cut_50m"]["draw_usd"])) == Decimal("500000")
        and D(str(fin_lines["eur_hold_5m"]["draw_usd"])) == Decimal("50000")
        and usd_close(sq["corra_incumbent_draw"]["cost_usd_unrounded"], cost_1m)
        and usd_close(sq["eur_incumbent_draw"]["cost_usd_unrounded"], cost_50k)
    )
    notional_cost_50m = CORRA_NOTIONAL_50M * (FUNDING_RATE / Decimal(100)) * (Decimal(70) / Decimal(360))
    on_draw_not_notional = not usd_close(fin_lines["corra_cut_50m"]["cost_usd_unrounded"], notional_cost_50m)
    verifier.figures["financing_500k"] = str(cost_500k)
    verifier.figures["financing_50k"] = str(cost_50k)
    verifier.add(
        "unit_financing_70d_act360_on_draw",
        "unit",
        verifier.ok(fin_ok and on_draw_not_notional),
        {
            "corra_500k": fin_lines["corra_cut_50m"]["cost_usd_unrounded"],
            "eur_50k": fin_lines["eur_hold_5m"]["cost_usd_unrounded"],
            "sum": fin["sum_cost_usd_unrounded"],
            "status_quo_1m": sq["corra_incumbent_draw"]["cost_usd_unrounded"],
        },
        {
            "corra_500k": str(cost_500k),
            "eur_50k": str(cost_50k),
            "sum": str(cost_500k + cost_50k),
            "status_quo_1m": str(cost_1m),
            "wrong_if_charged_on_50m_notional": str(notional_cost_50m),
        },
        "Preferred financing is 70 calendar days, ACT/360, 3.94 percent, on the draw. "
        "500000*0.0394*70/360 and 50000*0.0394*70/360. Charging the full notional would be a 100x-class error on the 50m line.",
    )

    carry_repro = EUR_NOTIONAL * ((Decimal("4.46") - Decimal("2.95")) / Decimal(100)) * (Decimal(70) / Decimal(360))
    carry_ok = usd_close(carry["cost_sensitivity_usd_unrounded"], carry_repro)
    verifier.add(
        "unit_yield_gap_sensitivity_arithmetic",
        "unit",
        verifier.ok(carry_ok),
        carry["cost_sensitivity_usd_unrounded"],
        str(carry_repro),
        "5000000 * ((4.46 - 2.95)/100) * 70/360. This check is the arithmetic only.",
    )

    eur_mtm = EUR_NOTIONAL * (EUR_SPOT / EUR_ENTRY - 1)
    eur_block = results["noncanonical_mark"]["eur_long_spot_vs_entry"]
    combined_repro = receive_100m + eur_mtm
    comb = results["noncanonical_mark"]["combined_gross_before_financing"]
    verifier.figures["eur_mtm_unrounded"] = str(eur_mtm)
    verifier.figures["eur_mtm_nearest"] = nearest_dollar(eur_mtm)
    eur_sign_ok = (
        eur_mtm < 0
        and eur_block["nearest_dollar"] < 0
        and usd_close(eur_block["pnl_usd_unrounded"], eur_mtm)
        and nearest_close(eur_block["nearest_dollar"], eur_mtm)
    )
    verifier.add(
        "sign_eur_long_mtm_negative_when_spot_falls",
        "sign",
        verifier.ok(eur_sign_ok),
        {"unrounded": eur_block["pnl_usd_unrounded"], "nearest_dollar": eur_block["nearest_dollar"]},
        {"unrounded": str(eur_mtm), "nearest_dollar": nearest_dollar(eur_mtm)},
        "Long EUR PnL is notional * (new/old - 1) = 5000000 * (1.1224/1.1267 - 1). "
        "New is below old, so the sign is negative.",
    )
    receive_sign_ok = receive_100m > 0 and nc["nearest_dollar_pnl_at_100m_book_parallel"] > 0 and mean < BOOK_MARK
    verifier.add(
        "sign_corra_receive_positive_when_implied_falls",
        "sign",
        verifier.ok(receive_sign_ok and pnl_ok),
        nc["nearest_dollar_pnl_at_100m_book_parallel"],
        str(receive_100m),
        "The equal-weight implied rate 3.05125 is below the book mark 3.10875, so a receive mark-to-market versus that mark is positive.",
    )
    comb_ok = (
        usd_close(comb["unrounded"], combined_repro)
        and nearest_close(comb["nearest_dollar"], combined_repro)
        and eur_mtm < 0
        and receive_100m > 0
    )
    verifier.add(
        "sign_combined_noncanonical_gross",
        "sign",
        verifier.ok(comb_ok),
        {"unrounded": comb["unrounded"], "nearest_dollar": comb["nearest_dollar"]},
        {"unrounded": str(combined_repro), "nearest_dollar": nearest_dollar(combined_repro), "eur_mtm": str(eur_mtm), "corra": str(receive_100m)},
        "Combined noncanonical gross is the +57500 CORRA receive leg plus the negative EUR mark-to-market. "
        "Financing is not inside this sum.",
    )

    audjpy = series_by_id["AUDJPY"]
    audnzd = series_by_id["AUDNZD"]
    audjpy_max_date, audjpy_max, audjpy_max_dates = extreme(audjpy["history"], "max")
    audnzd_max_date, audnzd_max, audnzd_max_dates = extreme(audnzd["history"], "max")
    eurusd_min_date, eurusd_min, eurusd_min_dates = extreme(eurusd["history"], "min")
    aud_candidates = {c["candidate_id"]: c for c in results["candidates"]}
    audjpy_c = aud_candidates["audjpy_short"]
    audnzd_c = aud_candidates["audnzd_short"]
    aud_illustr = results["portfolio"]["declined_illustrations"]["fx_aud_shorts_compare_at_5m_adverse"]

    def short_pnl(notional: Decimal, ref: float, new: float) -> Decimal:
        return -notional * (D(str(new)) / D(str(ref)) - 1)

    audjpy_pnl = short_pnl(EUR_NOTIONAL, float(audjpy["last_value"]), audjpy_max)
    audnzd_pnl = short_pnl(EUR_NOTIONAL, float(audnzd["last_value"]), audnzd_max)
    aud_sign_ok = (
        audjpy_max > float(audjpy["last_value"])
        and audnzd_max > float(audnzd["last_value"])
        and audjpy_pnl < 0
        and audnzd_pnl < 0
        and usd_close(aud_illustr["audjpy"]["unrounded"], audjpy_pnl)
        and nearest_close(aud_illustr["audjpy"]["nearest_dollar"], audjpy_pnl)
        and usd_close(aud_illustr["audnzd"]["unrounded"], audnzd_pnl)
        and nearest_close(aud_illustr["audnzd"]["nearest_dollar"], audnzd_pnl)
        and num_close(audjpy_c["reference_level"], audjpy["last_value"], abs_tol=1e-8, rel_tol=1e-12)
        and num_close(audjpy_c["adverse_level"], audjpy_max, abs_tol=1e-8, rel_tol=1e-12)
    )
    verifier.add(
        "sign_short_cross_negative_when_cross_rises",
        "sign",
        verifier.ok(aud_sign_ok),
        {"audjpy": aud_illustr["audjpy"]["unrounded"], "audnzd": aud_illustr["audnzd"]["unrounded"]},
        {"audjpy": str(audjpy_pnl), "audnzd": str(audnzd_pnl)},
        "Short cross PnL is -notional * (new/reference - 1). Both illustrative adverses are above the 2026-11-05 reference, so both PnLs are negative.",
    )

    # Sample windows. Short window is the last 20 observations, which is 19 changes.
    SHORT_KEY = "last_20_observations_19_changes"
    full_bad = []
    short_bad = []
    full_std_bad = []
    std_rows = {}
    for sid, block in yardsticks.items():
        changes = my_changes[sid]
        n_full = len(changes)
        n_hist = len(series_by_id[sid]["history"])
        published_full = block["num_changes"]
        short_block = block.get("std_sample", {}).get(SHORT_KEY)
        stale_key = "last_20_obs_changes_note_19_deltas" in block.get("std_sample", {})
        if not isinstance(short_block, dict):
            published_short = None
            published_short_std = None
        else:
            published_short = short_block.get("n_changes")
            published_short_std = short_block.get("std_unrounded")
        if not (n_hist == 126 and n_full == 125 and published_full == 125 and block["len_history"] == 126):
            full_bad.append(
                {
                    "id": sid,
                    "len_history_source": n_hist,
                    "len_history_results": block["len_history"],
                    "reproduced_changes": n_full,
                    "results_num_changes": published_full,
                }
            )
        full_std = sample_std(changes)
        short_19 = sample_std(changes[-19:])
        short_20 = sample_std(changes[-20:])
        published_full_std = block["std_sample"]["all_changes"]["std_unrounded"]
        std_rows[sid] = {
            "full_std": full_std,
            "std_19": short_19,
            "std_20": short_20,
            "published_full": published_full_std,
            "published_short": published_short_std,
            "published_n": published_short,
            "window_start": series_by_id[sid]["history"][-20][0],
            "window_end": series_by_id[sid]["history"][-1][0],
        }
        short_rel = None if published_short_std is None else rel_err(published_short_std, short_19)
        if published_short != 19 or stale_key or short_rel is None or short_rel > 1e-9:
            short_bad.append(
                {
                    "id": sid,
                    "results_n_changes": published_short,
                    "reproduced_n_changes": 19,
                    "results_std": published_short_std,
                    "reproduced_std_19": short_19,
                    "relative_error": short_rel,
                    "stale_20_change_key": stale_key,
                }
            )
        if not num_close(published_full_std, full_std, abs_tol=1e-8, rel_tol=1e-9):
            pop = population_std(changes)
            full_std_bad.append(
                {
                    "id": sid,
                    "published": published_full_std,
                    "sample_ddof1": full_std,
                    "population_ddof0": pop,
                }
            )
        if block.get("stored_n_field") == published_full:
            full_bad.append({"id": sid, "used_n_field_as_num_changes": block.get("stored_n_field")})

    verifier.figures["short_window_correct_n"] = 19
    verifier.figures["short_window_published_n"] = std_rows["CA_2Y"]["published_n"]
    verifier.figures["ca2y_std_19"] = std_rows["CA_2Y"]["std_19"]
    verifier.figures["eurusd_std_19"] = std_rows["EURUSD"]["std_19"]

    nfield_ok = all(
        block.get("stored_n_field") == 252 and block["num_changes"] == 125 and block["len_history"] == 126
        for block in yardsticks.values()
    ) and not any(block["num_changes"] == 252 for block in yardsticks.values())
    verifier.add(
        "lineage_n_field_252_not_the_sample",
        "lineage",
        verifier.ok(nfield_ok and not full_bad),
        {sid: {"stored_n_field": block.get("stored_n_field"), "num_changes": block["num_changes"], "len_history": block["len_history"]} for sid, block in yardsticks.items()},
        {"len_history": 126, "num_changes": 125, "stored_n_field_recorded_not_used": 252},
        "n_field 252 is stored and is not the sample. A full series is 126 points and 125 changes.",
    )
    verifier.add(
        "sample_full_window_125_changes",
        "sample",
        verifier.ok(not full_bad and not full_std_bad),
        {"num_changes": {sid: block["num_changes"] for sid, block in yardsticks.items()}},
        {"num_changes": 125, "len_history": 126, "full_std_mismatches": full_std_bad},
        "FULL window is 125 changes from 126 points. Sample standard deviation uses the n-1 divisor. "
        "Fail if any yardstick num_changes is not 125 or the full-sample standard deviation disagrees.",
    )
    published_short_counts = {sid: std_rows[sid]["published_n"] for sid in std_rows}
    verifier.add(
        "sample_short_window_last_20_observations_are_19_changes",
        "sample",
        verifier.ok(not short_bad),
        published_short_counts,
        {"n_changes": 19, "key": SHORT_KEY, "mismatches": short_bad},
        "std_sample.last_20_observations_19_changes is the last 20 observations, which is 19 changes. "
        "Sample standard deviation uses the N-1 divisor. Price changes are 100*ln. Yield changes are bp differences. "
        "Fail if n_changes is not 19 or the published standard deviation differs from the recomputed "
        "19-change standard deviation by more than 1e-9 relative. "
        f"CA_2Y reproduced 19-change std {std_rows['CA_2Y']['std_19']}. "
        f"EURUSD reproduced 19-change std {std_rows['EURUSD']['std_19']}.",
    )
    for sid in ("CA_2Y", "EURUSD"):
        row = std_rows[sid]
        std_match = row["published_short"] is not None and rel_err(row["published_short"], row["std_19"]) <= 1e-9
        verifier.add(
            f"sample_{sid.lower()}_short_window_std_19_changes",
            "sample",
            verifier.ok(std_match and row["published_n"] == 19),
            {"n_changes": row["published_n"], "std_unrounded": row["published_short"]},
            {
                "n_changes": 19,
                "std_unrounded": row["std_19"],
                "relative_error": None if row["published_short"] is None else rel_err(row["published_short"], row["std_19"]),
                "window_start": row["window_start"],
                "window_end": row["window_end"],
            },
            f"{sid} 19-change sample standard deviation, N-1, from the last 20 source_map observations "
            f"({row['window_start']} through {row['window_end']}). "
            "Tolerance is 1e-9 relative.",
        )

    # Horizon. Only the h40 and h60 products are scaled. Financing still uses 70 calendar days.
    horizon_mismatches = []
    used_70 = []
    std_source_rows = {}
    for sid, block in yardsticks.items():
        hs = block["horizon_scale"]
        std_full = std_rows[sid]["full_std"]
        std_source_rows[sid] = hs.get("std_source")
        for h, key in ((40, "h40_trading_days"), (60, "h60_trading_days")):
            payload = hs.get(key)
            if not isinstance(payload, dict) or "std_times_sqrt_h_unrounded" not in payload:
                horizon_mismatches.append({"id": sid, "key": key, "reason": "missing std_times_sqrt_h_unrounded"})
                continue
            claimed = payload["std_times_sqrt_h_unrounded"]
            pred = std_full * math.sqrt(h)
            pred70 = std_full * math.sqrt(70)
            if rel_err(claimed, pred70) <= 1e-6 and rel_err(claimed, pred) > 1e-6:
                used_70.append({"id": sid, "key": key, "claimed": claimed, "std_sqrt_70": pred70})
            if rel_err(claimed, pred) > 1e-6:
                horizon_mismatches.append(
                    {"id": sid, "key": key, "claimed": claimed, "full_std_sqrt_h": pred, "relative": rel_err(claimed, pred)}
                )
    horizon_ok = not horizon_mismatches and not used_70
    sources_named = all(value == "all_changes" for value in std_source_rows.values())
    verifier.add(
        "horizon_scale_equals_full_sample_std_times_sqrt_h",
        "horizon",
        verifier.ok(horizon_ok),
        {"std_source": std_source_rows},
        {"mismatches": horizon_mismatches, "used_sqrt_70": used_70, "h": [40, 60], "std_source_is_all_changes": sources_named},
        "Each horizon_scale.std_source is "
        + ("all_changes. " if sources_named else "not all_changes on every series. ")
        + "The h40 and h60 products must equal the full-sample standard deviation times sqrt(40) and sqrt(60). "
        "Fail only if that product is wrong or 70 is under the square root. "
        "The financing day count of 70 stays outside the square root.",
    )

    # Median, AUDJPY high, EUR low, forbidden strings
    eurusd_levels = [float(row[1]) for row in eurusd["history"]]
    eurusd_median = median_even_average(eurusd_levels)
    median_label = "1.1467 is the median of these 126 closes"
    median_claimed = median_label in results_text
    median_ok = (not median_claimed) or abs(eurusd_median - 1.1467) <= 1e-6
    verifier.figures["eurusd_median"] = eurusd_median
    verifier.figures["median_claim_passed"] = bool(median_ok and median_claimed)
    copied_median_label = median_label in JUDGMENT_PATHS["book"].read_text(encoding="utf-8")
    verifier.add(
        "lineage_eurusd_median_of_126_closes",
        "lineage",
        verifier.ok(median_ok),
        1.1467 if median_claimed else None,
        {"median": eurusd_median, "n": len(eurusd_levels), "label_present": median_claimed, "same_label_in_book_judgment": copied_median_label},
        "The candidate label says 1.1467 is the median of these 126 EURUSD closes. "
        "Median of an even sample averages the two middle history levels. "
        "Tolerance 1e-6. The judgment file was used only to see that the label text was copied; "
        "the median itself is recomputed from source_map history.",
    )

    aud_date_claimed = "2026-08-28" in results_text or "2026-08-28" in JUDGMENT_PATHS["fx"].read_text(encoding="utf-8")
    aud_level_ok = num_close(audjpy_c["adverse_level"], audjpy_max, abs_tol=1e-8, rel_tol=1e-12)
    aud_date_ok = (not aud_date_claimed) or ("2026-08-28" in audjpy_max_dates)
    results_extreme = yardsticks["AUDJPY"]["history_level_extremes"]["max"]
    extreme_matches_source = (
        results_extreme["date"] in audjpy_max_dates
        and num_close(results_extreme["level"], audjpy_max, abs_tol=1e-8, rel_tol=1e-12)
    )
    verifier.add(
        "lineage_audjpy_adverse_is_sample_high",
        "lineage",
        verifier.ok(aud_level_ok and aud_date_ok and extreme_matches_source),
        {"adverse_level": audjpy_c["adverse_level"], "results_extreme": results_extreme, "date_stated": "2026-08-28"},
        {"max_level": audjpy_max, "max_dates": audjpy_max_dates},
        "AUDJPY adverse is recomputed as max(source_map history), not from results.history_level_extremes alone. "
        "Results and the fx judgment state 2026-08-28. Fail if the level or that date disagrees.",
    )

    eur_adverse_candidates = [
        c["adverse_level"] for c in results["candidates"] if c.get("instrument") == "EURUSD" and c.get("adverse_level") not in (None, 0)
    ]
    eur_min_ok = abs(eurusd_min - 1.113) <= 1e-6 and all(abs(float(level) - eurusd_min) <= 1e-6 for level in eur_adverse_candidates)
    results_eur_min = yardsticks["EURUSD"]["history_level_extremes"]["min"]
    eur_extreme_ok = num_close(results_eur_min["level"], eurusd_min, abs_tol=1e-8, rel_tol=1e-12) and results_eur_min["date"] in eurusd_min_dates
    verifier.add(
        "lineage_eur_adverse_1_113_is_sample_min",
        "lineage",
        verifier.ok(eur_min_ok and eur_extreme_ok),
        {"candidate_adverse_levels": eur_adverse_candidates, "results_extreme": results_eur_min},
        {"min_level": eurusd_min, "min_dates": eurusd_min_dates},
        "EUR adverse 1.113 is min(source_map EURUSD history). The results extreme is checked against that recomputation, not used as the source.",
    )

    forbidden_hits = {token: results_text.find(token) for token in FORBIDDEN}
    forbidden_ok = all(pos < 0 for pos in forbidden_hits.values())
    verifier.add(
        "lineage_forbidden_substrings_absent",
        "lineage",
        verifier.ok(forbidden_ok),
        forbidden_hits,
        "absent",
        "results must not contain the substrings post_rate, cumulative_bp, or incremental_bp.",
    )

    # US 2y factual claims tied to the 29 bp SR3 adverse
    us_hist = us2y["history"]
    us_window = us_hist[-20:]
    us_decline = float(us_window[0][1]) - float(us_window[-1][1])
    us_changes = my_changes["US_2Y"]
    us_max_abs = max(abs(x) for x in us_changes)
    us_max_date, us_max_level, us_max_dates = extreme(us_hist, "max")
    us_claim_bits = {
        "start_date": us_window[0][0],
        "start_level": float(us_window[0][1]),
        "end_date": us_window[-1][0],
        "end_level": float(us_window[-1][1]),
        "decline_bp": us_decline,
        "max_abs_daily_bp": us_max_abs,
        "max_level": us_max_level,
        "max_dates": us_max_dates,
    }
    text_claims_29 = "475 bp on 2026-10-08" in results_text and "29 bp" in results_text
    text_claims_492 = "492 bp on 2026-09-28" in results_text
    text_claims_16 = "16 bp" in results_text and "largest absolute" in results_text
    us_facts_ok = True
    us_fact_notes = []
    if text_claims_29:
        ok29 = (
            us_window[0][0] == "2026-10-08"
            and abs(float(us_window[0][1]) - 475) <= 1e-6
            and us_window[-1][0] == "2026-11-05"
            and abs(float(us_window[-1][1]) - 446) <= 1e-6
            and abs(us_decline - 29) <= 1e-6
        )
        us_facts_ok = us_facts_ok and ok29
        us_fact_notes.append(f"last 20 observations net decline claim matches={ok29}")
    if text_claims_492:
        ok492 = abs(us_max_level - 492) <= 1e-6 and "2026-09-28" in us_max_dates
        us_facts_ok = us_facts_ok and ok492
        us_fact_notes.append(f"US_2Y sample max 492 on 2026-09-28 matches={ok492}")
    if text_claims_16:
        ok16 = abs(us_max_abs - 16) <= 0.5
        us_facts_ok = us_facts_ok and ok16
        us_fact_notes.append(f"largest absolute daily US_2Y change near 16 bp matches={ok16}")
    verifier.add(
        "lineage_us2y_proxy_facts_behind_sr3_adverse",
        "lineage",
        verifier.ok(us_facts_ok),
        "results prose cites 475 to 446 = 29 bp over the last 20 observations, max 492 on 2026-09-28, and a 16 bp largest absolute daily difference",
        us_claim_bits,
        "Recomputed from source_map US_2Y history. The last 20 observations are 19 changes. "
        + " ".join(us_fact_notes),
    )

    # EUR ordinary-move count cited beside the adverse path
    eur_big_rows = []
    for i in range(1, len(eurusd["history"])):
        prev = D(str(eurusd["history"][i - 1][1]))
        cur = D(str(eurusd["history"][i][1]))
        move = abs(cur - prev)
        if move >= Decimal("0.0045"):
            eur_big_rows.append({"date": eurusd["history"][i][0], "abs_change": str(move)})
    tie = [row for row in eur_big_rows if row["abs_change"] == "0.0045" and row["date"] == "2026-10-16"]
    says_21 = "21 of 125" in results_text
    says_20 = "20 of 125" in results_text
    eur_count_ok = says_21 and not says_20 and len(eur_big_rows) == 21 and len(tie) == 1 and len(eurusd["history"]) - 1 == 125
    verifier.add(
        "lineage_eurusd_abs_move_count_21_of_125",
        "lineage",
        verifier.ok(eur_count_ok),
        {"text_contains_21_of_125": says_21, "text_contains_20_of_125": says_20},
        {"count_at_least_0_0045": len(eur_big_rows), "n_changes": len(eurusd["history"]) - 1, "exact_0_0045_on_2026_10_16": tie},
        "The sentence 20 of 125 must be absent. The corrected clause counts 21 of 125 absolute daily EURUSD "
        "changes of at least 0.0045, including 2026-10-16 at exactly 0.0045. Differences are exact decimals, "
        "not raw binary subtraction.",
    )

    # Levels copied from judgment or equal to a source statistic
    source_levels: List[float] = []
    for row in source["series"]:
        for point in row.get("history") or []:
            source_levels.append(float(point[1]))
        if isinstance(row.get("last_value"), (int, float)):
            source_levels.append(float(row["last_value"]))
    for contract in source["tradable_curves"]["CORRA"]["contracts"] + source["tradable_curves"]["SOFR"]["contracts"]:
        source_levels.append(float(contract["implied_rate"]))
        source_levels.append(float(contract["price"]))
    source_levels.extend(
        [
            float(mean),
            float(BOOK_MARK),
            float(BOOK_ENTRY),
            float(eurusd_median),
            float(eurusd_min),
            float(audjpy_max),
            float(audnzd_max),
            float(funding["percent_rate"]),
            float(book["funding_percent_rate"]),
        ]
    )
    invented = []
    level_keys = ("reference_level", "target_low", "target_high", "adverse_level", "planned_exit_level", "gap_stress_level", "entry_level", "book_mark_level")
    for cand in results["candidates"]:
        for key in level_keys:
            if key not in cand:
                continue
            value = cand.get(key)
            if value is None or value == 0:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if level_known(number, source_levels) or level_known(number, judgment_numbers):
                continue
            invented.append({"candidate_id": cand["candidate_id"], "field": key, "value": number})
    verifier.add(
        "lineage_candidate_levels_copied_or_recomputed",
        "lineage",
        verifier.ok(not invented),
        invented,
        "each numeric level is a source statistic or appears in book, fx, or rates judgment JSON",
        "Judgment files are used only to confirm a level was copied rather than invented. "
        "A level that matches source history, a contract, the book, or a recomputed median or extreme passes without adopting judgment prose.",
    )

    # Portfolio signs
    bp_adverse = (CORRA_ADVERSE - mean) * Decimal(100)
    corra_dv01_50m = Decimal(10000) * (CORRA_NOTIONAL_50M / Decimal("100000000"))
    corra_50m_pnl = -bp_adverse * corra_dv01_50m
    eur_5m_pnl = EUR_NOTIONAL * (EUR_ADVERSE / EUR_SPOT - 1)
    sum_nearest = nearest_dollar(corra_50m_pnl) + nearest_dollar(eur_5m_pnl)
    budget_notional = LOSS_BUDGET_CORRA / (bp_adverse * Decimal(10000) / Decimal("100000000"))
    overrun = -corra_50m_pnl - LOSS_BUDGET_CORRA
    verifier.figures["corra_50m_pnl"] = str(corra_50m_pnl)
    verifier.figures["eur_5m_pnl"] = str(eur_5m_pnl)
    verifier.figures["sum_nearest"] = sum_nearest
    verifier.figures["budget_corra_notional"] = str(budget_notional)
    verifier.figures["overrun"] = str(overrun)

    both = results["portfolio"]["scenarios"]["both_adverse_no_correlation_assumed"]["both_legs_adverse"]
    corra_leg_ok = (
        bp_adverse == Decimal("20.875")
        and corra_dv01_50m == Decimal(5000)
        and corra_50m_pnl == Decimal("-104375")
        and usd_close(both["corra"]["unrounded"], corra_50m_pnl)
        and nearest_close(both["corra"]["nearest_dollar"], corra_50m_pnl)
        and both["corra"]["nearest_dollar"] < 0
    )
    verifier.add(
        "sign_portfolio_corra_50m_to_3_26",
        "sign",
        verifier.ok(corra_leg_ok),
        both["corra"],
        {"bp": str(bp_adverse), "dv01_usd_per_bp": str(corra_dv01_50m), "pnl": str(corra_50m_pnl), "nearest_dollar": nearest_dollar(corra_50m_pnl)},
        "CORRA 50m from 3.05125 to 3.26 is 20.875 bp times 5000 USD per bp = 104375 loss, PnL -104375. "
        "A receive loses when the implied rate rises.",
    )
    eur_leg_ok = (
        eur_5m_pnl < 0
        and usd_close(both["eurusd"]["unrounded"], eur_5m_pnl)
        and nearest_close(both["eurusd"]["nearest_dollar"], eur_5m_pnl)
    )
    verifier.add(
        "sign_portfolio_eur_5m_to_1_113",
        "sign",
        verifier.ok(eur_leg_ok),
        both["eurusd"],
        {"pnl": str(eur_5m_pnl), "nearest_dollar": nearest_dollar(eur_5m_pnl)},
        "EUR 5m to 1.113 is 5000000 * (1.113/1.1224 - 1), negative because 1.113 is below 1.1224.",
    )
    sum_ok = nearest_close(both["combined_directional_pnl_usd"]["nearest_dollar"], Decimal(sum_nearest)) and usd_close(
        both["combined_directional_pnl_usd"]["unrounded"], corra_50m_pnl + eur_5m_pnl
    )
    verifier.add(
        "sign_portfolio_sum_of_nearest_dollars",
        "sign",
        verifier.ok(sum_ok),
        both["combined_directional_pnl_usd"]["nearest_dollar"],
        {"sum_of_nearest_dollars": sum_nearest, "unrounded_sum": str(corra_50m_pnl + eur_5m_pnl)},
        "Sum of the CORRA 50m adverse nearest dollar and the EUR 5m adverse nearest dollar.",
    )

    columns = results["portfolio"]["notional_columns"]
    budget_ok = usd_close(columns["budget_implied_corra_usd_unrounded"], budget_notional)
    # notional is USD, tolerance 0.02 is tight relative to 4.8e7 but relative 1e-9 also applies inside usd_close
    verifier.add(
        "unit_budget_implied_corra_notional",
        "unit",
        verifier.ok(budget_ok),
        columns["budget_implied_corra_usd_unrounded"],
        str(budget_notional),
        "Budget-implied CORRA notional = 100000 / (20.875 * 10000 / 1e8).",
    )
    sr3_receive_notional = (SR3_BUDGET / (bp_receive * Decimal(25))) * Decimal("1000000")
    sr3_formula_millions = SR3_BUDGET / (bp_receive * Decimal(25))
    sr3_notional_claimed = sr3_block["receive_adverse"]["budget_implied_notional_unrounded"]
    sr3_notional_ok = usd_close(sr3_notional_claimed, sr3_receive_notional) and bp_receive == Decimal(29)
    verifier.figures["sr3_receive_notional"] = str(sr3_receive_notional)
    verifier.add(
        "unit_sr3_budget_implied_receive_notional",
        "unit",
        verifier.ok(sr3_notional_ok),
        sr3_notional_claimed,
        {"usd": str(sr3_receive_notional), "millions": str(sr3_formula_millions), "formula": "1e6 * 10000/(29*25)"},
        "SR3 budget-implied receive notional is 10000/(29*25) million USD, stored in USD as 1,000,000 times that quotient. "
        "DV01 is 25 USD per bp per 1m, so the dollar notional that loses 10000 on a 29 bp receive is 13793103.45.",
    )

    flat_rows = []
    flat_ok = True
    for cid in ("sofr_h7_flat", "audjpy_short", "audnzd_short", "corra_close", "eur_exit"):
        cand = aud_candidates[cid]
        adverse = cand["forward_pnl_by_level_and_notional"].get("adverse_level", {})
        analyst = adverse.get("analyst_proposed_notional_usd", {})
        budget_pnl = adverse.get("budget_implied_notional_usd", {})
        flat_rows.append(
            {
                "candidate_id": cid,
                "analyst_nearest": analyst.get("nearest_dollar"),
                "budget_nearest": budget_pnl.get("nearest_dollar"),
            }
        )
        if analyst.get("nearest_dollar") != 0 or not usd_close(analyst.get("unrounded", 1), 0):
            flat_ok = False
        if budget_pnl.get("nearest_dollar") != 0 or not usd_close(budget_pnl.get("unrounded", 1), 0):
            flat_ok = False
    preferred_flat = both.get("sofr_flat", {})
    if preferred_flat.get("nearest_dollar") != 0 or not usd_close(preferred_flat.get("unrounded", 1), 0):
        flat_ok = False
    verifier.add(
        "sign_flat_and_no_trade_sized_pnl_is_zero",
        "sign",
        verifier.ok(flat_ok),
        flat_rows,
        0,
        "Flat and no-trade sized PnL is 0. SR3 wait, AUD no-trade, CORRA close, and EUR exit are sized at zero. "
        "The preferred both-adverse scenario keeps the SR3 leg at 0.",
    )

    preferred_ids = results["portfolio"]["preferred_set_candidate_ids"]
    aud_outside = (
        "audjpy_short" not in preferred_ids
        and "audnzd_short" not in preferred_ids
        and "audjpy" not in both
        and "audnzd" not in both
        and usd_close(both["combined_directional_pnl_usd"]["unrounded"], fnum(both["corra"]["unrounded"]) + fnum(both["eurusd"]["unrounded"]) + fnum(both["sofr_flat"]["unrounded"]))
        and aud_illustr["audjpy"]["nearest_dollar"] != 0
    )
    verifier.add(
        "sign_illustrative_aud_shorts_outside_recommended_sum",
        "sign",
        verifier.ok(aud_outside),
        {"preferred_set_candidate_ids": preferred_ids, "audjpy_5m_nearest": aud_illustr["audjpy"]["nearest_dollar"], "audnzd_5m_nearest": aud_illustr["audnzd"]["nearest_dollar"]},
        "illustrative 5m shorts are not in the preferred combined directional sum",
        "AUDJPY and AUDNZD 5m shorts are declined illustrations. Their losses are not added to the recommended CORRA plus EUR sum.",
    )

    fin_cost = results["portfolio"]["scenarios"]["both_adverse_no_correlation_assumed"]["financing_cost_separate_positive"]["unrounded"]
    directional = fnum(both["combined_directional_pnl_usd"]["unrounded"])
    mixed = directional - fnum(fin_cost)
    financing_separate = (
        fnum(fin_cost) > 0
        and usd_close(directional, fnum(both["corra"]["unrounded"]) + fnum(both["eurusd"]["unrounded"]))
        and not usd_close(directional, mixed)
    )
    net_field = results["portfolio"]["scenarios"]["domestic_reacceleration"].get("net_directional_plus_financing_not_ev", {})
    financing_separate = financing_separate and net_field.get("unrounded") is None
    verifier.add(
        "sign_financing_positive_and_not_inside_directional_pnl",
        "sign",
        verifier.ok(financing_separate),
        {"combined_directional": directional, "financing_cost": fin_cost, "net_field_unrounded": net_field.get("unrounded")},
        {"financing_positive": str(cost_500k + cost_50k), "directional_excludes_financing": True},
        "Financing cost is positive. It is not subtracted inside directional PnL. "
        "The both-adverse combined directional figure equals the sum of the legs.",
    )

    # Economic objections. Status pass. Facts confirmed from source_map.
    ca_labor = [
        {
            "series_id": row.get("series_id"),
            "status": row.get("status"),
            "research_status": row.get("research_status"),
        }
        for row in source["macro_components_filtered"]
        if row.get("country") == "CA" and "Labor" in str(row.get("series_id"))
    ]
    labor_failed = [row for row in ca_labor if row["status"] == "source_failed" or row["research_status"] == "source_failed"]
    verifier.add(
        "economic_meeting_price_exclusion",
        "economic",
        "pass",
        source["quarantine"]["statement"],
        "policy inference from meeting prices is coarse",
        "Objection: derived meeting-price and Fed path estimates are excluded. "
        "Calendars keep scheduling metadata only, so policy inference from meeting prices is coarse. "
        "This is not an arithmetic error.",
    )
    verifier.add(
        "economic_ca_labor_not_a_print",
        "economic",
        "pass",
        ca_labor,
        {"source_failed_or_unavailable_rows": labor_failed},
        "Objection: CA labor components are source_failed. A Canadian employment scenario is not a print in this packet.",
    )
    corra_hist = any("history" in contract for contract in source["tradable_curves"]["CORRA"]["contracts"])
    sr3_hist = any("history" in contract for contract in source["tradable_curves"]["SOFR"]["contracts"])
    proxy_ids = sorted({c.get("yardstick_series_id") for c in results["candidates"] if c.get("yardstick_kind") and "proxy" in str(c.get("yardstick_kind"))})
    verifier.add(
        "economic_no_strip_history_proxies",
        "economic",
        "pass",
        {"corra_contracts_have_history": corra_hist, "sr3_contracts_have_history": sr3_hist, "proxy_yardsticks": proxy_ids},
        "CA_2Y and US_2Y are proxies",
        "Objection: there is no CORRA strip history and no SR3 strip history. CA_2Y and US_2Y daily differences are proxies, not the futures strip.",
    )
    verifier.add(
        "economic_no_eur_forward_yield_gap_is_not_spot_carry",
        "economic",
        "pass",
        {"US_2Y_as_of": us2y.get("as_of"), "EA_2Y_as_of": ea2y.get("as_of"), "results_sensitivity": carry["cost_sensitivity_usd_unrounded"]},
        {"sensitivity_reproduced": str(carry_repro), "dates_differ": us2y.get("as_of") != ea2y.get("as_of")},
        "Objection: there is no EUR forward. The 2y yield-gap figure is a labeled sensitivity, not carry that predicts spot. "
        "US_2Y is dated 2026-11-05 and EA_2Y is dated 2026-11-06.",
    )
    dates_null = all(obs_dates[code] is None for code in CORRA_CODES)
    verifier.add(
        "economic_corra_observation_dates_null",
        "economic",
        "pass",
        obs_dates,
        "all four CRAH27/CRAM27/CRAU27/CRAZ27 observation_date values are null" if dates_null else obs_dates,
        "Objection: CORRA observation dates are null, so the frozen implied average is not assigned to a session.",
    )
    spx = series_by_id["SP500"]
    vix = series_by_id["VIX"]
    broad = series_by_id["BROAD_USD"]
    stale_ok_facts = spx.get("as_of") == "2026-11-04" and vix.get("as_of") == "2026-11-04" and broad.get("last_date") == "2026-10-30"
    verifier.add(
        "economic_spx_vix_and_broad_usd_dates",
        "economic",
        "pass",
        {"SP500_as_of": spx.get("as_of"), "VIX_as_of": vix.get("as_of"), "BROAD_USD_last_date": broad.get("last_date")},
        {"confirmed": stale_ok_facts},
        "Objection: S&P and VIX are 2026-11-04. Broad USD ends 2026-10-30. They are not a 2026-11-05 confirmation print.",
    )
    oil_notes = {
        "WTI": series_by_id["WTI"].get("note"),
        "BRENT": series_by_id["BRENT"].get("note"),
    }
    verifier.add(
        "economic_oil_histories_include_rolls",
        "economic",
        "pass",
        oil_notes,
        "roll jumps can distort screens",
        "Objection: WTI and Brent histories include contract rolls. Roll jumps can distort screens. They are not a clean spot path.",
    )
    verifier.add(
        "economic_corra_50m_overspends_100k_budget",
        "economic",
        "pass",
        {"proposed_notional_usd": 50000000, "results_budget_implied": columns["budget_implied_corra_usd_unrounded"]},
        {
            "adverse_loss_usd": str(-corra_50m_pnl),
            "budget_usd": str(LOSS_BUDGET_CORRA),
            "overrun_usd": str(overrun),
            "budget_implied_notional_usd": str(budget_notional),
            "budget_implied_about_millions": "47.9",
        },
        "Objection: the 50m CORRA proposal overspends a 100000 budget. "
        "Adverse loss at 50m is 104375, overrun 4375. Size-from-budget is 47904191.62 USD, about 47.9 million. "
        "This objects to treating 50m as exactly the budget. It is not a new trade idea.",
    )
    fair_value_labels = sorted(
        {
            c.get("target_label")
            for c in results["candidates"]
            if isinstance(c.get("target_label"), str) and "not fair value" in c["target_label"]
        }
    )
    verifier.add(
        "economic_targets_are_not_probabilities_or_fair_values",
        "economic",
        "pass",
        {"target_labels_saying_not_fair_value": fair_value_labels, "horizon_label": "convention_not_a_probability"},
        "targets remain judgmental marks",
        "Objection: targets are not probabilities and not fair values. A horizon multiple of a sample standard deviation is a scale, not a probability.",
    )
    n_fields = sorted({row.get("n_field") for row in source["series"] if row.get("len_history") == 126})
    verifier.add(
        "economic_n252_screens_are_not_the_126_point_sample",
        "economic",
        "pass",
        {"n_field_values_on_126_point_series": n_fields, "len_history": 126, "num_changes": 125},
        "126 points, 125 changes",
        "Objection: n=252 screens are not the 126-point sample. Stored n_field is 252 while the history used here has 126 points and 125 changes.",
    )
    verifier.add(
        "economic_one_day_equity_and_yield_moves_are_not_one_cause",
        "economic",
        "pass",
        {
            "SP500_as_of": spx.get("as_of"),
            "NASDAQ_as_of": series_by_id["NASDAQ"].get("as_of"),
            "US_2Y_as_of": us2y.get("as_of"),
            "CA_2Y_as_of": series_by_id["CA_2Y"].get("as_of"),
        },
        "one session does not identify one cause",
        "Objection: one-day equity and yield moves are not a single cause. "
        "S&P is dated 2026-11-04 while US_2Y and NASDAQ are dated 2026-11-05, and CA_2Y ends 2026-11-04. "
        "Sharing a headline date does not make the moves one cause.",
    )

    failed_hard = [c for c in verifier.checks if c["class"] in HARD_CLASSES and c["status"] == "fail"]
    exit_code = 1 if failed_hard else 0
    OUT_JSON.write_text(json.dumps(verifier.checks, indent=2) + "\n", encoding="utf-8")
    OUT_MD.write_text(build_report(verifier, exit_code), encoding="utf-8")

    counts: Dict[str, Dict[str, int]] = {}
    for check in verifier.checks:
        bucket = counts.setdefault(check["class"], {"pass": 0, "fail": 0})
        bucket[check["status"]] += 1
    summary = {
        "exit_code": exit_code,
        "counts": counts,
        "failed_ids": [c["id"] for c in failed_hard],
        "eur_mtm_nearest_dollar": verifier.figures["eur_mtm_nearest"],
        "short_window_change_count": verifier.figures["short_window_correct_n"],
        "median_claim_passed": verifier.figures["median_claim_passed"],
        "eurusd_median": verifier.figures["eurusd_median"],
    }
    print(json.dumps(summary, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
