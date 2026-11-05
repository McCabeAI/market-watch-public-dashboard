#!/usr/bin/env python3
"""Extract the 2026-11-05 frozen curves and apply labeled scenario assumptions.

Reads only the overnight evidence snapshot, the ChatGPT book block, and the
CORRA hypothesis prior. Scenario policy rates are judgments. They are not
probabilities, expected values, or portfolio P&L.

Identity check: packet_sha256 is the repo canonical digest of the snapshot
with the packet_sha256 field removed (indent=2, sort_keys, trailing newline).
The raw file digest differs because those bytes include the digest field.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
SNAPSHOT = (
    ROOT
    / "data/overnight/runs/overnight-20261105/reviews/review-001/evidence_snapshot.json"
)
BOOK = ROOT / "data/pm/books/latest.json"
HYPOTHESIS = (
    ROOT
    / "data/trading/pm/chatgpt/research/hypotheses/hyp-chatgpt-corra-2027hz-20260919.json"
)
OUT = Path(__file__).resolve().parent / "paths.json"

EXPECTED_PACKET_SHA256 = "0bc766c948f4f88f81ea6e28bc00ad0a67e09ee5605b23b47cb69b039f415b10"
PACKET_AS_OF = "2026-11-05T04:53:53.458055-05:00"
MARKET_STATE_GENERATED_AT = "2026-11-05T10:17:36Z"

# Previous-vintage levels live in the hypothesis prose. They are a comparison
# of averages across packets, not inputs to today's strip decomposition.
PREVIOUS_VINTAGE_RATES = {
    "2027-03": Decimal("2.970"),
    "2027-06": Decimal("3.115"),
    "2027-09": Decimal("3.225"),
    "2027-12": Decimal("3.310"),
}
PREVIOUS_VINTAGE_FIXING = Decimal("2.54")

# Judgments, in percent. Positive gap_bp means the futures period rate is
# above the assumption. A gap is not an expected value and has no probability.
BOC_A = [Decimal("2.75")] * 4
BOC_B = [Decimal("3.00"), Decimal("3.20"), Decimal("3.35"), Decimal("3.50")]
BOC_C = [Decimal("2.85"), Decimal("2.95"), Decimal("3.00"), Decimal("3.05")]
FED_A = [Decimal("4.20")] * 4
FED_B = [Decimal("4.45"), Decimal("4.60"), Decimal("4.70"), Decimal("4.75")]
# Scenario C for the Fed is the judgment that the SR3 path itself is the
# conditional path. The script copies the futures rates after they are read.
RBA_A_STEP = Decimal("0.05")
RBA_A_START = Decimal("4.75")
RBA_B_LEVEL = Decimal("5.00")
RBA_C_LEVEL = Decimal("4.90")
AONIA_BACK_START = "2027-11"
AONIA_BACK_END = "2028-04"


def dump_canonical(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def D(value: object) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.0000001"), rounding=ROUND_HALF_UP)


def q_rate(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)


def q_bp(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def num(value: Decimal) -> str:
    text = format(q_rate(value), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def bp_num(value: Decimal) -> str:
    text = format(q_bp(value), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def pct_to_bp(spread: Decimal) -> Decimal:
    return q_bp(spread * Decimal("100"))


def avg(values: list[Decimal]) -> Decimal:
    if not values:
        raise SystemExit("empty average")
    return q_rate(sum(values) / Decimal(len(values)))


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_hash(snapshot: dict) -> dict:
    raw = SNAPSHOT.read_bytes()
    file_sha = hashlib.sha256(raw).hexdigest()
    body = {key: value for key, value in snapshot.items() if key != "packet_sha256"}
    canonical = hashlib.sha256(dump_canonical(body).encode("utf-8")).hexdigest()
    stored = snapshot.get("packet_sha256")
    if canonical != EXPECTED_PACKET_SHA256 or stored != EXPECTED_PACKET_SHA256:
        raise SystemExit(
            f"packet identity mismatch stored={stored} canonical={canonical} "
            f"expected={EXPECTED_PACKET_SHA256}"
        )
    if snapshot.get("as_of") != PACKET_AS_OF:
        raise SystemExit(f"packet as_of changed: {snapshot.get('as_of')}")
    return {
        "expected_packet_sha256": EXPECTED_PACKET_SHA256,
        "stored_packet_sha256": stored,
        "canonical_sha256_excluding_packet_sha256": canonical,
        "identity_match": True,
        "canonicalization": "json.dumps(indent=2, sort_keys=True) + newline, packet_sha256 removed",
        "file_byte_sha256": file_sha,
        "file_byte_note": (
            "Raw file bytes include packet_sha256, so the file digest is not the identity digest."
        ),
    }


def contract_row(contract: dict, benchmark: Decimal) -> dict:
    implied = D(contract["implied_rate"])
    price = D(contract["price"])
    reconstructed = q_rate(Decimal("100") - price)
    if abs(reconstructed - q_rate(implied)) > Decimal("0.0001"):
        raise SystemExit(f"implied_rate != 100 - price for {contract.get('code')} {contract.get('expiry')}")
    stored_change = contract.get("change_from_overnight_bps")
    computed_change = pct_to_bp(q_rate(implied) - benchmark)
    change_gap = None
    if stored_change is not None:
        change_gap = q_bp(computed_change - D(stored_change))
        if abs(change_gap) > Decimal("0.05"):
            raise SystemExit(
                f"change_from_overnight identity failed {contract.get('code')} "
                f"{contract.get('expiry')} stored={stored_change} computed={computed_change}"
            )
    return {
        "expiry": contract.get("expiry"),
        "code": contract.get("code"),
        "price": num(price),
        "implied_rate": num(q_rate(implied)),
        "change_from_overnight_bps": None if stored_change is None else num(D(stored_change)),
        "change_from_overnight_identity_bp": None if change_gap is None else bp_num(change_gap),
        "open_interest": contract.get("open_interest"),
        "volume": contract.get("volume"),
        "source": contract.get("source"),
        "observation_date": contract.get("observation_date") or contract.get("as_of"),
    }


def benchmark_block(raw: dict) -> dict:
    history = raw.get("history")
    latest = None
    if isinstance(history, list) and history:
        latest = {
            "effective_date": history[-1].get("effective_date"),
            "percent_rate": history[-1].get("percent_rate"),
            "n_history_points_not_averaged": len(history),
        }
    return {
        "name": raw.get("name") or raw.get("label"),
        "as_of": raw.get("as_of"),
        "rate": raw.get("rate"),
        "source": raw.get("source"),
        "underlying_note": raw.get("underlying_note"),
        "latest_history_point": latest,
    }


def curve_table(curve: dict, expiries: list[str] | None = None) -> dict:
    benchmark_rate = D(curve["benchmark"]["rate"])
    rows = []
    for contract in curve["contracts"]:
        if expiries is not None and contract.get("expiry") not in expiries:
            continue
        rows.append(contract_row(contract, benchmark_rate))
    return {
        "country": curve.get("country"),
        "instrument": curve.get("instrument"),
        "product_code": curve.get("product_code"),
        "contract_period_months": curve.get("contract_period_months"),
        "mark_convention": curve.get("mark_convention"),
        "status": curve.get("status"),
        "source_url": curve.get("source_url"),
        "error": curve.get("error"),
        "benchmark": benchmark_block(curve["benchmark"]),
        "contracts": rows,
    }


def by_expiry(rows: list[dict]) -> dict[str, Decimal]:
    return {row["expiry"]: D(row["implied_rate"]) for row in rows}


def steps(rates: dict[str, Decimal], order: list[str]) -> list[dict]:
    out = []
    previous = None
    previous_expiry = None
    for expiry in order:
        if expiry not in rates:
            continue
        rate = rates[expiry]
        if previous is not None:
            out.append(
                {
                    "from_expiry": previous_expiry,
                    "to_expiry": expiry,
                    "from_rate": num(previous),
                    "to_rate": num(rate),
                    "period_rate_change_bp": bp_num(pct_to_bp(rate - previous)),
                    "meaning": "difference of two period rates, not a meeting count",
                }
            )
        previous = rate
        previous_expiry = expiry
    return out


def quarter_gap(futures: list[Decimal], assumption: list[Decimal], labels: list[str]) -> dict:
    if len(futures) != len(assumption) or len(labels) != len(futures):
        raise SystemExit("scenario length mismatch")
    rows = []
    for label, fut, assumed in zip(labels, futures, assumption):
        rows.append(
            {
                "expiry": label,
                "futures_period_rate": num(fut),
                "assumed_period_rate": num(assumed),
                "assumption": True,
                "gap_bp_futures_minus_assumption": bp_num(pct_to_bp(fut - assumed)),
            }
        )
    fut_avg = avg(futures)
    ass_avg = avg(assumption)
    return {
        "contracts": rows,
        "futures_average": num(fut_avg),
        "assumed_average": num(ass_avg),
        "assumed_average_is_assumption": True,
        "gap_bp_futures_minus_assumption": bp_num(pct_to_bp(fut_avg - ass_avg)),
    }


def series_brief(series: dict) -> dict:
    moves = {}
    for horizon, move in (series.get("moves") or {}).items():
        moves[horizon] = {
            "value": move.get("value"),
            "unit": move.get("unit"),
            "z": move.get("z"),
        }
    return {
        "id": series["id"],
        "as_of": series.get("as_of"),
        "age_days": series.get("age_days"),
        "value": series.get("value"),
        "unit": series.get("unit"),
        "percentile": series.get("percentile"),
        "z": series.get("z"),
        "status": series.get("status"),
        "note": series.get("note"),
        "moves": moves,
    }


def temperature_brief(block: dict) -> dict:
    components = {}
    for name, state in block["component_state"].items():
        components[name] = {
            "as_of": state.get("as_of"),
            "transform_value": state.get("transform_value"),
            "level": state.get("level"),
            "impulse": state.get("impulse"),
            "observed": state.get("observed"),
            "release_date": state.get("release_date"),
            "release_date_status": state.get("release_date_status"),
            "retrieved_at": state.get("retrieved_at"),
        }
    return {
        "as_of": block.get("as_of"),
        "level": block.get("level"),
        "direction": block.get("direction"),
        "impulse": block.get("impulse"),
        "coverage": block.get("coverage"),
        "temperature_class": block.get("temperature_class"),
        "latest_reference_period": block.get("latest_reference_period"),
        "components": components,
    }


def component_status(components: list[dict], series_id: str) -> dict | None:
    for row in components:
        if row.get("series_id") == series_id:
            return {
                "series_id": series_id,
                "status": row.get("status"),
                "observation_period": row.get("observation_period"),
                "due_period": row.get("due_period"),
                "research_status": row.get("research_status"),
                "error": row.get("error"),
            }
    return None


def aonia_window(rates: dict[str, Decimal], start: str, end: str) -> dict:
    order = [expiry for expiry in sorted(rates) if start <= expiry <= end]
    values = [rates[expiry] for expiry in order]
    return {
        "start": start,
        "end": end,
        "expiries": order,
        "rates": [num(value) for value in values],
        "n": len(values),
        "arithmetic_average": num(avg(values)),
        "first_to_last_bp": bp_num(pct_to_bp(values[-1] - values[0])),
    }


def main() -> None:
    snapshot = load_json(SNAPSHOT)
    identity = verify_hash(snapshot)
    market = snapshot["families"]["market_state"]
    if market.get("as_of") != MARKET_STATE_GENERATED_AT:
        raise SystemExit(f"market_state as_of changed: {market.get('as_of')}")
    data = market["data"]
    if data.get("generated_at") != MARKET_STATE_GENERATED_AT:
        raise SystemExit(f"generated_at changed: {data.get('generated_at')}")

    curves = data["tradable_rate_curves"]["curves"]
    corra = curve_table(curves["CORRA"])
    sofr_all = curve_table(curves["SOFR"])
    aonia = curve_table(curves["AONIA"])
    tona_all = curve_table(curves["TONA"])
    estr = curve_table(curves["ESTR"])

    sofr_keep = []
    peak = max(sofr_all["contracts"], key=lambda row: D(row["implied_rate"]))
    for row in sofr_all["contracts"]:
        if row["expiry"] <= "2028-12" or row["expiry"] == peak["expiry"]:
            sofr_keep.append(row)
    sofr = dict(sofr_all)
    sofr["contracts"] = sofr_keep
    sofr["peak_in_full_curve"] = {
        "expiry": peak["expiry"],
        "code": peak["code"],
        "implied_rate": peak["implied_rate"],
        "open_interest": peak["open_interest"],
        "volume": peak["volume"],
        "note": "Curve maximum. Zero open interest. Not the liquid 2027 policy peak.",
    }
    liquid = [
        row
        for row in sofr_all["contracts"]
        if row["expiry"] <= "2028-12" and (row["open_interest"] or 0) >= 1000
    ]
    liquid_peak = max(liquid, key=lambda row: D(row["implied_rate"]))
    sofr["liquid_peak_through_2028"] = {
        "expiry": liquid_peak["expiry"],
        "code": liquid_peak["code"],
        "implied_rate": liquid_peak["implied_rate"],
        "open_interest": liquid_peak["open_interest"],
        "volume": liquid_peak["volume"],
    }

    tona = dict(tona_all)
    tona["contracts"] = [row for row in tona_all["contracts"] if row["expiry"] <= "2028-12"]

    corra_rates = by_expiry(corra["contracts"])
    sofr_rates = by_expiry(sofr_all["contracts"])
    aonia_rates = by_expiry(aonia["contracts"])
    tona_rates = by_expiry(tona_all["contracts"])
    corra_bench = D(corra["benchmark"]["rate"])
    sofr_bench = D(sofr["benchmark"]["rate"])
    aonia_bench = D(aonia["benchmark"]["rate"])
    tona_bench = D(tona["benchmark"]["rate"])

    strip_labels = ["2027-03", "2027-06", "2027-09", "2027-12"]
    strip_codes = {"2027-03": "CRAH27", "2027-06": "CRAM27", "2027-09": "CRAU27", "2027-12": "CRAZ27"}
    sofr_codes = {"2027-03": "SR3H7", "2027-06": "SR3M7", "2027-09": "SR3U7", "2027-12": "SR3Z7"}
    corra_strip = [corra_rates[label] for label in strip_labels]
    sofr_strip = [sofr_rates[label] for label in strip_labels]
    corra_avg = avg(corra_strip)
    sofr_avg = avg(sofr_strip)

    books = load_json(BOOK)
    chatgpt = books["pms"]["chatgpt"]
    position = next(
        row for row in chatgpt["positions"] if row["position_id"] == "pm-chatgpt-595561a1b90f"
    )
    if D(position["mark_price"]) != D("3.14375"):
        raise SystemExit("book prior mark changed")
    book_mark = D(position["mark_price"])

    hypothesis = load_json(HYPOTHESIS)
    previous_rates = [PREVIOUS_VINTAGE_RATES[label] for label in strip_labels]
    previous_avg = avg(previous_rates)
    if previous_avg != D("3.155"):
        raise SystemExit(f"previous vintage average drifted: {previous_avg}")

    policy = data["policy_paths"]["countries"]
    ca_1m = [
        contract_row(row, corra_bench) for row in policy["CA"]["contracts_1m"]
    ]
    us_1m = [
        contract_row(row, sofr_bench) for row in policy["US"]["contracts_1m"]
    ]

    def triplet(monthly: dict[str, Decimal], months: list[str]) -> dict:
        values = [monthly[month] for month in months]
        return {
            "months": months,
            "rates": [num(value) for value in values],
            "arithmetic_average": num(avg(values)),
            "first_to_last_bp": bp_num(pct_to_bp(values[-1] - values[0])),
            "object": "arithmetic mean of monthly futures, not a quarterly compounded contract",
        }

    us_1m_rates = {row["expiry"]: D(row["implied_rate"]) for row in us_1m}
    sr3_vs_months = []
    for quarter, months in {
        "2027-03": ["2027-03", "2027-04", "2027-05"],
        "2027-06": ["2027-06", "2027-07", "2027-08"],
        "2027-09": ["2027-09", "2027-10", "2027-11"],
        "2027-12": ["2027-12", "2028-01", "2028-02"],
    }.items():
        bucket = triplet(us_1m_rates, months)
        futures_rate = sofr_rates[quarter]
        bucket["nearest_sr3_expiry"] = quarter
        bucket["sr3_implied_rate"] = num(futures_rate)
        bucket["sr3_minus_monthly_average_bp"] = bp_num(
            pct_to_bp(futures_rate - D(bucket["arithmetic_average"]))
        )
        bucket["sources"] = "SR3 is CME settlement; SR1 monthly path is eSignal delayed ICE. Not a tradable basis."
        sr3_vs_months.append(bucket)

    aonia_buckets = [
        triplet(aonia_rates, months)
        for months in (
            ["2027-03", "2027-04", "2027-05"],
            ["2027-06", "2027-07", "2027-08"],
            ["2027-09", "2027-10", "2027-11"],
            ["2027-12", "2028-01", "2028-02"],
        )
    ]
    mar_dec = aonia_window(aonia_rates, "2027-03", "2027-12")
    front = aonia_window(aonia_rates, "2026-11", "2027-04")
    back_overlap = aonia_window(aonia_rates, "2027-08", "2027-12")
    later_easing = aonia_window(aonia_rates, AONIA_BACK_START, AONIA_BACK_END)

    rba_a = [q_rate(RBA_A_START - RBA_A_STEP * Decimal(i)) for i in range(10)]
    rba_b = [RBA_B_LEVEL] * 10
    rba_c = [RBA_C_LEVEL] * 10
    aonia_mar_dec_rates = [aonia_rates[expiry] for expiry in mar_dec["expiries"]]
    if len(aonia_mar_dec_rates) != 10:
        raise SystemExit("expected 10 AONIA months from Mar to Dec 2027")

    def monthly_gap(futures_rates: list[Decimal], assumption: list[Decimal], labels: list[str]) -> dict:
        return quarter_gap(futures_rates, assumption, labels)

    # Extend scenario A past December by the same 5bp-per-month step so the
    # later-easing bucket has an assumption. Still a judgment.
    rba_a_by_month = {
        expiry: q_rate(RBA_A_START - RBA_A_STEP * Decimal(index))
        for index, expiry in enumerate(mar_dec["expiries"])
    }
    last_index = 9
    extra_order = ["2028-01", "2028-02", "2028-03", "2028-04"]
    for step, expiry in enumerate(extra_order, start=1):
        rba_a_by_month[expiry] = q_rate(RBA_A_START - RBA_A_STEP * Decimal(last_index + step))
    rba_b_by_month = {expiry: RBA_B_LEVEL for expiry in list(mar_dec["expiries"]) + extra_order}
    rba_c_by_month = {expiry: RBA_C_LEVEL for expiry in list(mar_dec["expiries"]) + extra_order}

    def bucket_gap(window: dict, assumed_by_month: dict[str, Decimal]) -> dict:
        futures_rates = [aonia_rates[expiry] for expiry in window["expiries"]]
        assumed = [assumed_by_month[expiry] for expiry in window["expiries"]]
        return quarter_gap(futures_rates, assumed, window["expiries"])

    fed_c = list(sofr_strip)
    scenarios = {
        "label": "conditional judgments, not probabilities",
        "gap_sign": "gap_bp = (futures period rate - assumed period rate) * 100. Positive: futures above the assumption.",
        "gap_is_not_expected_value": True,
        "BoC": {
            "instrument": "CORRA quarterly contracts CRAH27 CRAM27 CRAU27 CRAZ27",
            "overnight": {"rate": num(corra_bench), "as_of": corra["benchmark"]["as_of"]},
            "A": {
                "name": "Sustained cheaper oil, disinflation treated as persistent",
                "assumption_rule": (
                    "Flat 2.75 on all four 2027 quarters. 2.75 is the packet prima proxy midpoint, "
                    "used here as a stall level. It is not a Bank of Canada neutral-rate estimate."
                ),
                **quarter_gap(corra_strip, BOC_A, [strip_codes[label] for label in strip_labels]),
            },
            "B": {
                "name": "Renewed physical disruption, oil premia return",
                "assumption_rule": "Rising quarterly period rates 3.00 / 3.20 / 3.35 / 3.50.",
                **quarter_gap(corra_strip, BOC_B, [strip_codes[label] for label in strip_labels]),
            },
            "C": {
                "name": "Stronger demand, oil lower because supply fear faded",
                "assumption_rule": "Firming then stall: 2.85 / 2.95 / 3.00 / 3.05. Not an easing path and not the futures climb.",
                **quarter_gap(corra_strip, BOC_C, [strip_codes[label] for label in strip_labels]),
            },
        },
        "Fed": {
            "instrument": "CME SR3 quarterly contracts SR3H7 SR3M7 SR3U7 SR3Z7",
            "overnight": {"rate": num(sofr_bench), "as_of": sofr["benchmark"]["as_of"], "history_not_averaged": True},
            "A": {
                "name": "Sustained cheaper oil, disinflation treated as persistent",
                "assumption_rule": "Flat 4.20 period rate. A stall above the 3.97 fixing, not a cut back to the fixing.",
                **quarter_gap(sofr_strip, FED_A, [sofr_codes[label] for label in strip_labels]),
            },
            "B": {
                "name": "Renewed physical disruption, oil premia return",
                "assumption_rule": "Rising quarterly period rates 4.45 / 4.60 / 4.70 / 4.75.",
                **quarter_gap(sofr_strip, FED_B, [sofr_codes[label] for label in strip_labels]),
            },
            "C": {
                "name": "Stronger demand, oil lower because supply fear faded",
                "assumption_rule": (
                    "Assumed period rates are set equal to the SR3 futures. "
                    "The judgment is that this conditional path does not conflict with the futures."
                ),
                **quarter_gap(sofr_strip, fed_c, [sofr_codes[label] for label in strip_labels]),
            },
        },
        "RBA": {
            "instrument": "ASX 30-day AONIA months March 2027 through December 2027",
            "overnight": {"rate": num(aonia_bench), "as_of": aonia["benchmark"]["as_of"]},
            "A": {
                "name": "Sustained cheaper oil, disinflation treated as persistent",
                "assumption_rule": "March 2027 at 4.75, then -5bp of period rate per month through December 2027 at 4.30.",
                **monthly_gap(aonia_mar_dec_rates, rba_a, mar_dec["expiries"]),
                "later_easing_bucket_2027_11_to_2028_04": bucket_gap(later_easing, rba_a_by_month),
            },
            "B": {
                "name": "Renewed physical disruption, oil premia return",
                "assumption_rule": "Flat 5.00 period rate across March-December 2027. No easing.",
                **monthly_gap(aonia_mar_dec_rates, rba_b, mar_dec["expiries"]),
                "later_easing_bucket_2027_11_to_2028_04": bucket_gap(later_easing, rba_b_by_month),
            },
            "C": {
                "name": "Stronger demand, oil lower because supply fear faded",
                "assumption_rule": "Flat 4.90. The small front hump stays; the later easing does not.",
                **monthly_gap(aonia_mar_dec_rates, rba_c, mar_dec["expiries"]),
                "later_easing_bucket_2027_11_to_2028_04": bucket_gap(later_easing, rba_c_by_month),
            },
        },
    }

    wanted_series = [
        "US_2Y", "US_10Y", "CA_2Y", "CA_10Y", "AU_2Y", "AU_10Y", "JP_2Y", "JP_10Y",
        "EA_2Y", "EA_10Y", "NZ_2Y", "NZ_10Y", "WTI", "BRENT", "US_REAL10", "US_BE10",
        "HY_OAS", "VIX", "USDCAD",
    ]
    series_map = {row["id"]: series_brief(row) for row in data["opportunities"]["series"]}
    yields = {key: series_map[key] for key in wanted_series}

    tenors = {}
    for country in ("US", "CA", "AU", "JP", "EA", "NZ"):
        block = data["rates"][country]
        tenors[country] = {
            "latest_observation": block.get("latest_observation"),
            "age_days": block.get("age_days"),
            "status": block.get("status"),
            "levels_percent": {
                tenor: {
                    "as_of": payload.get("as_of"),
                    "value_percent": payload.get("value"),
                }
                for tenor, payload in block["tenors"].items()
                if tenor in ("2Y", "10Y", "5Y", "30Y", "LONG")
            },
            "curve_2s10s_bp": {
                "as_of": block["curves"]["2s10s"].get("as_of"),
                "bps": block["curves"]["2s10s"].get("bps"),
            },
        }

    macro_components = snapshot["families"]["macro_hard"]["components"]
    watched = [
        "CA.Inflation.headline", "CA.Inflation.underlying", "CA.Labor.unemployment",
        "CA.Labor.wages", "CA.Labor.employment", "CA.Labor.participation",
        "US.Inflation.core_pce", "US.Inflation.pce_headline", "US.Labor.unemployment",
        "US.Labor.wages", "US.Activity.manufacturing_surveys", "US.Activity.services_surveys",
        "US.Activity.gdp_domestic_demand", "AU.Inflation.headline", "AU.Inflation.underlying",
        "AU.Labor.unemployment", "AU.Labor.wages", "AU.Labor.employment",
    ]
    temperatures = snapshot["temperature_scores"]["countries"]
    prima = snapshot["canada_prima_pressure"]
    shock_inputs = prima["channel_evidence"]["shock_persistence"]["inputs"]
    prima_brief = {
        "direction": prima.get("direction"),
        "strength": prima.get("strength"),
        "confidence": prima.get("confidence"),
        "staleness": prima.get("staleness"),
        "front_shock_classification": prima.get("front_shock_classification"),
        "change_since_last_mpr": prima.get("change_since_last_mpr"),
        "mpr_status": prima.get("mpr_status"),
        "conditioning_date": prima.get("conditioning_date"),
        "subcomponent_directions": prima.get("subcomponent_directions"),
        "neutral_midpoint": prima["channel_evidence"]["demand_pass_through_constraint"]["inputs"][0],
        "breadth": {
            "direction": prima["channel_evidence"]["consumer_price_breadth"]["direction"],
            "share": prima["channel_evidence"]["consumer_price_breadth"]["inputs"][0]["breadth_share"],
            "positive_majors": prima["channel_evidence"]["consumer_price_breadth"]["inputs"][0]["breadth_positive_majors"],
            "majors_with_mom": prima["channel_evidence"]["consumer_price_breadth"]["inputs"][0]["breadth_majors_with_mom"],
            "period": "2026-09",
        },
        "ippi_ex_energy_mom": prima["channel_evidence"]["production_network_pressure"]["inputs"][0]["mom"],
        "rmpi_ex_crude_energy_mom": prima["channel_evidence"]["imported_pressure"]["inputs"][0]["mom"],
        "imported_pressure_note": prima["channel_evidence"]["imported_pressure"]["note"],
        "shock_persistence_stale": prima["channel_evidence"]["shock_persistence"]["stale"],
        "brent_contracts": shock_inputs,
        "direct_energy_mom": {
            "ippi_energy": prima["shadow_sector_layer"]["direct_energy"]["monthly_ippi_energy"]["change"],
            "ippi_energy_period": prima["shadow_sector_layer"]["direct_energy"]["monthly_ippi_energy"]["period"],
            "rmpi_crude_energy": prima["shadow_sector_layer"]["direct_energy"]["monthly_rmpi_crude_energy"]["change"],
            "rmpi_crude_period": prima["shadow_sector_layer"]["direct_energy"]["monthly_rmpi_crude_energy"]["period"],
            "counted_in_score": prima["shadow_sector_layer"]["direct_energy"]["counted_in_score"],
        },
    }

    official = {}
    for country, block in data["official_curves"]["countries"].items():
        official[country] = {
            "as_of": block.get("as_of"),
            "status": block.get("status"),
            "curve_type": block.get("curve_type") or block.get("kind"),
            "forward_rate_count": len(block.get("forward_rates") or {}),
            "note": block.get("note"),
        }
    jp_par = data["official_curves"]["countries"]["JP"]["par_yields"]
    au_policy = policy["AU"]
    au_bill_ois = {
        "bank_bills": au_policy["bank_bills"],
        "ois": au_policy["ois"],
        "bank_bill_minus_ois": au_policy["bank_bill_minus_ois"],
        "use": (
            "Bank bills are a credit instrument. OIS in this block is December 2022, "
            "so the bill-OIS basis is unavailable. Neither object is the AONIA futures path."
        ),
    }

    news_items = []
    for item in snapshot["families"]["news"]["items"]:
        summary = item.get("summary") or ""
        if summary == "":
            summary_status = "empty"
        elif summary.startswith("Headline-only"):
            summary_status = "headline_only_body_not_retrieved"
        else:
            summary_status = "summary_present"
        news_items.append(
            {
                "id": item.get("id"),
                "published_at": item.get("published_at"),
                "headline": item.get("headline"),
                "verification_status": item.get("verification_status"),
                "country_codes": item.get("country_codes"),
                "summary_status": summary_status,
            }
        )

    au_notes = snapshot["families"]["macro_hard"]["notes"]
    au_leading = snapshot["families"]["macro_hard"]["au_labor_leading"]
    leading_obs = [
        {
            "id": row["id"],
            "period": row["period"],
            "value": row["value"],
            "units": row["units"],
            "weight": row["weight"],
            "release_date": row["release_date"],
        }
        for row in au_leading["observations"]
    ]

    fixing_gap = pct_to_bp(corra_avg - corra_bench)
    midpoint = D(prima_brief["neutral_midpoint"]["neutral_midpoint"])
    midpoint_gap = pct_to_bp(corra_avg - midpoint)
    fixing_to_midpoint = pct_to_bp(midpoint - corra_bench)
    if q_bp(fixing_to_midpoint + midpoint_gap - fixing_gap) != Decimal("0"):
        raise SystemExit("BoC gap decomposition does not add up")

    feb = next(row for row in ca_1m if row["expiry"] == "2027-02")
    calendar_spread = pct_to_bp(corra_rates["2027-12"] - corra_rates["2027-03"])
    uz_avg = avg([corra_rates["2027-09"], corra_rates["2027-12"]])

    payload = {
        "type": "RATES_PATHS_2026_11_05",
        "clocks": {
            "packet_as_of": snapshot["as_of"],
            "packet_collect_as_of": snapshot.get("collect_as_of"),
            "market_state_as_of": market["as_of"],
            "market_state_generated_at": data["generated_at"],
            "clock_gap_repaired": False,
            "macro_hard_family_as_of": snapshot["families"]["macro_hard"]["as_of"],
            "temperature_last_refresh_date": snapshot["temperature_scores"]["last_refresh_date"],
            "temperature_scoring_cutoff": snapshot["temperature_scores"]["scoring_cutoff"],
            "temperature_inputs_ingested_at": snapshot["temperature_scores"]["score_inputs_last_ingested_at"],
        },
        "hash": identity,
        "book_context_read_only": {
            "pm_id": "chatgpt",
            "position_id": position["position_id"],
            "instrument": position["instrument"],
            "side": position["side"],
            "side_meaning": "long = receive",
            "notional_usd": position["notional_usd"],
            "expiries": position["paper_expression"]["expiries"],
            "entry_price": position["entry_price"],
            "entry_price_as_of": position["entry_price_as_of"],
            "entry_is_historical": True,
            "prior_mark_price": position["mark_price"],
            "prior_mark_as_of": position["mark_price_as_of"],
            "prior_mark_is_not_this_snapshot": True,
            "last_action": chatgpt["last_action"],
            "last_decision_at": chatgpt["last_decision_at"],
            "unrealized_pnl_is_historical_and_not_used": True,
        },
        "hypothesis_prior": {
            "hypothesis_id": hypothesis["hypothesis_id"],
            "current_revision_id": hypothesis["current_revision_id"],
            "status": hypothesis["status"],
            "claim": hypothesis["claim"],
            "falsifiers": [row["statement"] for row in hypothesis["falsifiers"]],
            "forecast": hypothesis["forecast"],
            "owned_not_obeyed": True,
        },
        "benchmarks": {
            "CORRA": corra["benchmark"],
            "SOFR": sofr["benchmark"],
            "AONIA": aonia["benchmark"],
            "TONA": tona["benchmark"],
            "ESTR": estr["benchmark"],
            "estr_policy_status": policy["EA"]["status"],
            "estr_futures_count": len(estr["contracts"]),
            "nz_official_curve_present": "NZ" in data["official_curves"]["countries"],
            "nz_futures_curve_present": "NZ" in curves,
        },
        "curves": {
            "CORRA": corra,
            "SOFR_through_2028_plus_peak": sofr,
            "AONIA": aonia,
            "TONA_through_2028": tona,
            "ESTR": estr,
        },
        "change_from_overnight_meaning": (
            "Stored change_from_overnight_bps equals (implied_rate - overnight benchmark) * 100. "
            "It is futures minus the overnight print. It is not unused tightening and not a meeting probability."
        ),
        "corra_2027_strip": {
            "contracts": [
                {
                    "expiry": label,
                    "code": strip_codes[label],
                    "implied_rate": num(corra_rates[label]),
                    "change_from_overnight_bps": bp_num(pct_to_bp(corra_rates[label] - corra_bench)),
                }
                for label in strip_labels
            ],
            "average_implied_rate": num(corra_avg),
            "overnight_rate": num(corra_bench),
            "overnight_as_of": corra["benchmark"]["as_of"],
            "average_minus_overnight_bp": bp_num(fixing_gap),
            "h_to_z_period_rate_change_bp": bp_num(calendar_spread),
            "prima_proxy_midpoint": num(midpoint),
            "prima_proxy_midpoint_source": "canada_prima_pressure demand_pass_through_constraint neutral_midpoint",
            "fixing_to_proxy_midpoint_bp": bp_num(fixing_to_midpoint),
            "strip_average_minus_proxy_midpoint_bp": bp_num(midpoint_gap),
            "decomposition_note": (
                "22bp from the Nov 3 fixing to the stored 2.75 midpoint, plus 36.375bp from that midpoint "
                "to the strip average, equals the 58.375bp futures-minus-fixing gap. "
                "This is today's snapshot only. It is not a hike count."
            ),
        },
        "sofr_2027_strip": {
            "contracts": [
                {
                    "expiry": label,
                    "code": sofr_codes[label],
                    "implied_rate": num(sofr_rates[label]),
                    "change_from_overnight_bps": bp_num(pct_to_bp(sofr_rates[label] - sofr_bench)),
                    "open_interest": next(row["open_interest"] for row in sofr_all["contracts"] if row["expiry"] == label),
                }
                for label in strip_labels
            ],
            "average_implied_rate": num(sofr_avg),
            "overnight_rate": num(sofr_bench),
            "overnight_as_of": sofr["benchmark"]["as_of"],
            "average_minus_overnight_bp": bp_num(pct_to_bp(sofr_avg - sofr_bench)),
            "sep_to_dec_2027_change_bp": bp_num(pct_to_bp(sofr_rates["2027-12"] - sofr_rates["2027-09"])),
        },
        "shape": {
            "CORRA_quarterly_steps_bp": steps(corra_rates, [row["expiry"] for row in corra["contracts"]]),
            "SOFR_steps_through_2028_bp": steps(
                sofr_rates, [row["expiry"] for row in sofr_all["contracts"] if row["expiry"] <= "2028-12"]
            ),
            "AONIA_monthly_steps_bp": steps(aonia_rates, [row["expiry"] for row in aonia["contracts"]]),
            "TONA_steps_through_2028_bp": steps(
                tona_rates, [row["expiry"] for row in tona_all["contracts"] if row["expiry"] <= "2028-12"]
            ),
            "ten_year_minus_overnight_is_not_a_hike_count": True,
        },
        "vintage_comparison_separate": {
            "label": "Previous morning packet versus this snapshot. Not one decomposition.",
            "previous_source": "hyp-chatgpt-corra-2027hz-20260919 calculation citing the 2026-11-04 morning packet",
            "previous_implied_rates": {key: num(value) for key, value in PREVIOUS_VINTAGE_RATES.items()},
            "previous_average": num(previous_avg),
            "previous_fixing": num(PREVIOUS_VINTAGE_FIXING),
            "previous_average_minus_previous_fixing_bp": bp_num(pct_to_bp(previous_avg - PREVIOUS_VINTAGE_FIXING)),
            "this_average": num(corra_avg),
            "this_fixing": num(corra_bench),
            "this_average_minus_this_fixing_bp": bp_num(fixing_gap),
            "average_change_bp": bp_num(pct_to_bp(corra_avg - previous_avg)),
            "per_contract_change_bp": {
                strip_codes[label]: bp_num(pct_to_bp(corra_rates[label] - PREVIOUS_VINTAGE_RATES[label]))
                for label in strip_labels
            },
            "separately_computed_gap_change_bp": bp_num(
                pct_to_bp((corra_avg - corra_bench) - (previous_avg - PREVIOUS_VINTAGE_FIXING))
            ),
            "book_prior_mark": num(book_mark),
            "book_prior_mark_as_of": position["mark_price_as_of"],
            "this_average_minus_book_prior_mark_bp": bp_num(pct_to_bp(corra_avg - book_mark)),
        },
        "monthly_paths_separate_objects": {
            "CA_1m_corra_through_2027_02": ca_1m,
            "CA_1m_terminal_in_policy_paths": policy["CA"]["terminal"],
            "CA_1m_does_not_cover_2027_quarters": True,
            "feb_2027_minus_proxy_midpoint_bp": bp_num(pct_to_bp(D(feb["implied_rate"]) - midpoint)),
            "US_1m_sofr_esignal_delayed": us_1m,
            "US_1m_source_note": policy["US"]["method"],
            "AU_policy_terminal_is_not_the_last_future": policy["AU"]["terminal"],
            "sr3_versus_three_monthly_prints": sr3_vs_months,
        },
        "aonia_versus_corra_object": {
            "mar_dec_2027_month_average": mar_dec,
            "mar_dec_average_minus_aonia_overnight_bp": bp_num(
                pct_to_bp(D(mar_dec["arithmetic_average"]) - aonia_bench)
            ),
            "mar_dec_average_minus_corra_2027_average_bp": bp_num(
                pct_to_bp(D(mar_dec["arithmetic_average"]) - corra_avg)
            ),
            "rate_spread_meaning": (
                "Basis points of rate level between an Australian monthly average and a Canadian quarterly average. "
                "Not P&L, not DV01, and not a mispricing."
            ),
            "front_hump_2026_11_to_2027_04": front,
            "front_peak_minus_overnight_bp": bp_num(pct_to_bp(max(aonia_rates[e] for e in front["expiries"]) - aonia_bench)),
            "back_of_overlap_2027_08_to_2027_12": back_overlap,
            "later_easing_2027_11_to_2028_04": later_easing,
            "later_easing_average_minus_overnight_bp": bp_num(
                pct_to_bp(D(later_easing["arithmetic_average"]) - aonia_bench)
            ),
            "three_month_arithmetic_buckets": aonia_buckets,
            "why_not_the_same_object": [
                "CORRA and SOFR contract_period_months are 3. AONIA contract_period_months is 1.",
                "An average of three monthly AONIA prints is an arithmetic mean of 30-day cash-rate futures.",
                "A CORRA quarter is one three-month futures implied rate, quoted as 100 minus price.",
                "Matching DV01 would still leave different accrual, different fixings, and intra-quarter path risk.",
                "Canadian one-month CORRA futures in this packet stop at February 2027, so the 2027 quarterly strip has no monthly siblings here.",
                "The US monthly-versus-SR3 comparison uses two sources and is an illustration, not a basis.",
            ],
        },
        "sovereigns": {
            "yields_in_opportunities_series_are_bp": True,
            "tenor_value_in_rates_country_blocks_is_percent": True,
            "do_not_subtract_stale_sovereign_from_fresh_futures": True,
            "series": yields,
            "country_blocks": tenors,
            "official_curve_dates_only": official,
            "jp_official_par_yields_percent": {
                tenor: {"as_of": row["as_of"], "value": row["value"]} for tenor, row in jp_par.items()
            },
            "au_bank_bills_and_ois": au_bill_ois,
        },
        "macro": {
            "known_gaps": snapshot.get("known_gaps"),
            "macro_hard_notes": au_notes,
            "component_status": {series_id: component_status(macro_components, series_id) for series_id in watched},
            "due_missing_status_count": sum(1 for row in macro_components if row.get("status") == "due_missing"),
            "due_missing_series": [
                row["series_id"] for row in macro_components if row.get("status") == "due_missing"
            ],
            "temperature": {
                country: {
                    block: temperature_brief(temperatures[country][block])
                    for block in ("Inflation", "Labor", "Activity", "Consumer")
                }
                for country in ("CA", "US", "AU", "JP")
            },
            "au_labor_leading": {
                "as_of": au_leading["as_of"],
                "partial": au_leading["partial"],
                "observations": leading_obs,
                "gap_ids": [row["id"] for row in au_leading["gaps"]],
            },
            "prima": prima_brief,
        },
        "news_narrative_index": news_items,
        "scenarios": scenarios,
        "expression_comparison": {
            "keep_existing_corra_receive": {
                "contracts": ["CRAH27", "CRAM27", "CRAU27", "CRAZ27"],
                "side": "receive",
                "base_scenario": "A",
                "gap_vs_assumption_A_bp": scenarios["BoC"]["A"]["gap_bp_futures_minus_assumption"],
                "verdict": "keep",
            },
            "shorter_calendar_CRAH27_vs_CRAZ27": {
                "pay": "CRAH27",
                "receive": "CRAZ27",
                "futures_spread_z_minus_h_bp": bp_num(calendar_spread),
                "assumption_A_spread_bp": "0",
                "spread_gap_bp": bp_num(calendar_spread),
                "front_contract_gap_vs_A_bp": scenarios["BoC"]["A"]["contracts"][0][
                    "gap_bp_futures_minus_assumption"
                ],
                "verdict": "reject as a replacement. Paying CRAH27 is the wrong side of that contract under assumption A.",
            },
            "uz_only_not_recommended": {
                "contracts": ["CRAU27", "CRAZ27"],
                "average": num(uz_avg),
                "gap_vs_assumption_A_bp": bp_num(pct_to_bp(uz_avg - Decimal("2.75"))),
                "verdict": "larger gap on fewer contracts, not a better expression of the same level claim",
            },
            "receive_sofr_2027": {
                "contracts": ["SR3H7", "SR3M7", "SR3U7", "SR3Z7"],
                "futures_minus_fixing_bp": None,
                "gap_vs_A_bp": scenarios["Fed"]["A"]["gap_bp_futures_minus_assumption"],
                "gap_vs_C_bp": scenarios["Fed"]["C"]["gap_bp_futures_minus_assumption"],
                "verdict": "reject. Weaker conviction was the right prior ranking. Scenario C, the better US domestic fit, has a zero gap by assumption.",
            },
            "pay_later_aonia_and_canada_australia_rv": {
                "au_leg": "pay ASX 30-day months 2027-11 through 2028-04",
                "ca_leg": "receive CRAH27 CRAM27 CRAU27 CRAZ27",
                "later_bucket_gap_A_bp": scenarios["RBA"]["A"]["later_easing_bucket_2027_11_to_2028_04"][
                    "gap_bp_futures_minus_assumption"
                ],
                "later_bucket_gap_B_bp": scenarios["RBA"]["B"]["later_easing_bucket_2027_11_to_2028_04"][
                    "gap_bp_futures_minus_assumption"
                ],
                "later_bucket_gap_C_bp": scenarios["RBA"]["C"]["later_easing_bucket_2027_11_to_2028_04"][
                    "gap_bp_futures_minus_assumption"
                ],
                "verdict": "reject. The Australian sign flips across A, B, and C, and the CPI print is unresolved inside the packet.",
            },
            "japan": {
                "tona_2027_12": num(tona_rates["2027-12"]),
                "tona_call_rate": num(tona_bench),
                "tona_call_as_of": tona["benchmark"]["as_of"],
                "dec_2027_minus_call_bp": bp_num(pct_to_bp(tona_rates["2027-12"] - tona_bench)),
                "jp_2y_par_percent": jp_par["2Y"]["value"],
                "jp_2y_as_of": jp_par["2Y"]["as_of"],
                "verdict": "no new pay and no new receive. Normalization is already a rising path. The 2Y par yield and the TONA futures are different objects and are not subtracted.",
            },
        },
        "most_mispriced": {
            "bank": "BoC",
            "path": (
                "CORRA quarterly period rates continue to rise through 2027 and 2028 "
                "(CRAH27 2.93, CRAZ27 3.265, CRAZ28 3.425) after the one-month curve has already reached the proxy midpoint by February 2027."
            ),
            "base_scenario": "A",
            "expression": "Keep the existing equal-weight receive of CRAH27, CRAM27, CRAU27, and CRAZ27.",
            "corra_forward_gap_under_base_scenario_bp": scenarios["BoC"]["A"]["gap_bp_futures_minus_assumption"],
            "futures_minus_fixing_bp_is_not_the_mispricing": bp_num(fixing_gap),
            "why_the_futures_path_is_wrong_under_the_base_reading": (
                "September underlying inflation transform 1.85 is near the temperature anchor and its impulse is negative. "
                "Unemployment transform 6.5 sits in a cool labor block. Ex-energy producer prices are stable to slightly down. "
                "The Nov 4 oil drop is large in log-change space and ordinary in level-percentile space. "
                "That combination does not validate a period-rate path that keeps climbing past the stored 2.75 midpoint into the mid-3s."
            ),
            "what_would_make_the_futures_path_right": (
                "Scenario B: September's energy jump and rising CPI breadth pass into underlying inflation, "
                "and deferred oil premia return. Scenario C would also support a higher path if Canadian labor and demand reaccelerate despite the current 6.5 unemployment transform. "
                "Either outcome is a falsifier, not a probability."
            ),
        },
        "forward_gap_versus_profit_since_entry": {
            "entry_price_historical": position["entry_price"],
            "prior_mark_historical": position["mark_price"],
            "current_average": num(corra_avg),
            "base_gap_bp": scenarios["BoC"]["A"]["gap_bp_futures_minus_assumption"],
            "vintage_average_change_bp": bp_num(pct_to_bp(corra_avg - previous_avg)),
            "election_rally_has_consumed_the_edge": False,
            "judgment": (
                "The strip average is 4.125bp below the previous morning vintage and 3bp below the Nov 4 12:12Z book mark. "
                "Under assumption A the remaining gap versus 2.75 is 36.375bp. The rally has not consumed that gap. "
                "This note does not size the keep."
            ),
        },
        "falsifiers_and_horizon": {
            "horizon": "Into the 2027 CORRA H/M/U/Z contracts. Review on the next shared packet.",
            "forced_hedge": False,
            "fiscal_or_term_premium_point_estimate": None,
            "falsifiers": [
                "Canadian underlying inflation, wages, and employment reaccelerate enough that a period-rate path above the 2.75 stall is validated. The September headline transform 3.0928 and rising major-component breadth are the current evidence that could start that pass-through.",
                "Deferred oil premia return. The Nov 4 Dec-2027 Brent mark is 79.12, still 9.12 dollars above the July MPR prose assumption of 70, with the shock-persistence channel marked stale.",
                "The four-contract average cheapens back through roughly 3.35 to 3.40 with domestic confirmation. That remains a review trigger from the prior hypothesis, not a new mechanical stop.",
                "A later packet shows the four-contract average no longer materially above the 2.75 assumption. The keep case is about the remaining forward gap.",
            ],
        },
        "data_gaps": [
            "Packet freeze 2026-11-05T04:53:53.458055-05:00 and market_state generated_at 2026-11-05T10:17:36Z are both kept. The clock gap is not repaired.",
            "ESTR futures list is empty and EA policy status is partial. Euro short-rate futures are not used. €STR overnight is 2.442 on 2026-11-04.",
            "NZ has no official curve in this packet and no futures curve.",
            "US core PCE component status is source_failed, previous release retained, observation 2026-07. Headline PCE is unavailable.",
            "US source-health is a carry-forward. Several consumer series are July or August and were retrieved in September.",
            "AU inflation transforms exist, component rows say checked_unchanged, and macro notes plus known_gaps list AU.Inflation.headline and underlying as due_missing. Release dates on the temperature block are inherited_or_inconsistent. No AU CPI number is treated as verified.",
            "AU labor-leading packet is partial. Stored job-ads and NAB observations have weight 0.0. Several leading series failed or are discovery gaps.",
            "AU sovereign 2Y and 10Y are 2026-10-28. AONIA futures are 4 Nov 2026. They are not subtracted.",
            "AU official zero curve is 2026-09-30. RBA OIS in the policy block is 2022-12-01, so bank-bill minus OIS is unavailable_cross_vintage.",
            "Canada official zero curve is 2026-10-14 and its forward curve is empty. It is not a check on the November CORRA futures.",
            "US_REAL10 is 2026-11-03, US_BE10 is 2026-11-04, WTI and Brent are 2026-11-04. No same-day real-yield versus breakeven versus oil decomposition.",
            "Prima shock persistence is stale. The Dec-2026 Brent input is observed 2026-10-30. Dec-2027 and Dec-2028 inputs are 2026-11-04. They are not one curve.",
            "CME positioning is unavailable. CORRA and TONA open interest and volume are null.",
            "BoJ minutes item has an empty summary. The BoJ-hold and Fed-hold items are headline-only. News is narrative.",
            "No October or November Canadian CPI, and no unemployment print newer than the September transforms, is in the packet.",
            "Oil percentiles are of a rolled futures history. The series note says roll jumps can distort the screen.",
        ],
    }
    payload["expression_comparison"]["receive_sofr_2027"]["futures_minus_fixing_bp"] = payload["sofr_2027_strip"][
        "average_minus_overnight_bp"
    ]

    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    print("identity", identity["identity_match"], identity["canonical_sha256_excluding_packet_sha256"])
    print("corra avg", num(corra_avg), "gap vs fixing", bp_num(fixing_gap), "gap vs 2.75", bp_num(midpoint_gap))
    print("sofr avg", num(sofr_avg), "aonia mar-dec", mar_dec["arithmetic_average"])
    print("vintage bp", bp_num(pct_to_bp(corra_avg - previous_avg)))


if __name__ == "__main__":
    main()
