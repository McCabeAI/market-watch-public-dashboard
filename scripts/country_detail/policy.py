"""Country Detail attention policy (v1).

Pure constants and helpers. No I/O, no temperature history, no threshold fitting.
Historical percentile bands were frozen before implementation and were not fit
to current prints. Direction-of-travel thresholds are round auditable cuts
(0.5 percentage point, 1.5x pace), also not fit to current prints.

Percentiles describe the historical distribution of comparable observations only.
They are not predictive probabilities and do not imply mean reversion.
A historical percentile is one admission reason. It is not the gate.
"""

from __future__ import annotations

import hashlib
import json
import re
import calendar
from datetime import date, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Mapping, Sequence

CONTRACT_VERSION = 1
CONTRACT_STATUS = "ACTIVE"

# --- Percentile bands (strict). Exactly 5, 95, 1, and 99 do not qualify. ---
NOTABLE_PERCENTILE_LOW = 5
NOTABLE_PERCENTILE_HIGH = 95
OUTLIER_PERCENTILE_LOW = 1
OUTLIER_PERCENTILE_HIGH = 99
# Pair form of the outlier cutoffs. Not the quotient 1/99.
OUTLIER = (OUTLIER_PERCENTILE_LOW, OUTLIER_PERCENTILE_HIGH)

PERCENTILE_FORMULA = (
    "(r - 0.5) / n * 100, where n is the comparable sample size, "
    "x is the latest comparable value inside that sample, and "
    "r = 1 + count(values < x) + 0.5 * count(values == x)"
)

# Comparable observations only. Other or unknown cadences are ineligible.
SAMPLE_MINIMA = MappingProxyType(
    {
        "monthly": MappingProxyType({"notable": 36, "outlier": 60}),
        "quarterly": MappingProxyType({"notable": 16, "outlier": 24}),
    }
)

CADENCE_MONTHLY = "monthly"
CADENCE_QUARTERLY = "quarterly"
KNOWN_CADENCES = (CADENCE_MONTHLY, CADENCE_QUARTERLY)

# --- Axes. Attention never encodes economic direction. ---
SCORE_ROLES = ("scored", "context", "unscored")
# ``interesting`` is a direction-of-travel finding. It is not a historical percentile.
ATTENTION_STATUSES = ("none", "interesting", "notable", "outlier")
# Smaller rank wins a correlation slot and sorts earlier among equal freshness.
ATTENTION_STATUS_RANK = MappingProxyType(
    {"outlier": 0, "notable": 1, "interesting": 2, "none": 3}
)
ECONOMIC_DIRECTION_IS_NOT_ATTENTION = True
FORBIDDEN_ATTENTION_TEMPERATURE_CLASSES = ("hot", "warm", "cold", "cool")
ATTENTION_BADGE_TEXT = MappingProxyType(
    {"interesting": "Interesting", "notable": "Notable", "outlier": "Outlier"}
)

# Direction-of-travel patterns. Historical percentile is not required.
# Smaller rank sorts earlier among Interesting findings.
TRAVEL_PATTERNS = (
    "reversal",
    "acceleration",
    "deceleration",
    "range_break",
    "persistence",
)
TRAVEL_PATTERN_RANK = MappingProxyType(
    {
        "reversal": 0,
        "acceleration": 1,
        "deceleration": 2,
        "range_break": 3,
        "persistence": 4,
    }
)
# mom/qoq prints already are the period's direction. yoy and levels use the
# change in the observation, so a long run of positive yoy is not persistence.
CHANGE_SIGN_TRANSFORMATIONS = frozenset({"mom_pct", "qoq_pct", "mom_sa_pct"})
# Percent-like pace change that counts as acceleration, deceleration, or reversal.
# Ten times the 0.05 reprint tolerance. Not fit to live prints.
PERCENT_STEP_MATERIAL = Decimal("0.5")
# Non-percent pace is material when the latest step is at least this multiple
# of the prior step. Not fit to live prints.
LEVEL_PACE_RATIO = Decimal("1.5")
MIN_SAME_DIRECTION_PERIODS = 3
MIN_PRIOR_RUN_FOR_TURN = 2

ALERT_FRESHNESS = ("new", "revised", "unchanged")
ALERT_FRESHNESS_RANK = MappingProxyType({"new": 0, "revised": 1, "unchanged": 2})

MAX_FINDINGS_INITIAL = 3
MAX_FINDINGS_EXPANDED = 5

# --- Ineligibility and data states ---
INELIGIBILITY_REASONS = frozenset(
    {
        "insufficient_history",
        "insufficient_history_for_outlier",
        "seasonal_history_insufficient",
        "structurally_non_comparable",
        "missing_value",
        "stale",
        "due_late",
        "superseded",
        "failed_fetch",
        "unchanged_reprint",
        "not_material",
        "correlated_companion",
        "unknown_cadence",
    }
)

DATA_STATES = (
    "ok",
    "missing",
    "stale",
    "due_late",
    "superseded",
    "revised",
    "structurally_non_comparable",
    "failed_fetch",
)
DATA_STATE_LABELS = MappingProxyType(
    {
        "missing": "Missing",
        "stale": "Stale",
        "due_late": "Due",
        "superseded": "Superseded",
        "revised": "Revised",
        "structurally_non_comparable": "Not comparable",
        "failed_fetch": "Source failed",
    }
)
# Analytical release states. ``current`` is the latest official observation.
# ``due_late`` means a successor should already exist. ``superseded`` means a
# newer official observation of the same series identity is present.
RELEASE_STATES = (
    "current",
    "due_late",
    "superseded",
    "missing",
    "failed_fetch",
    "revised",
    "structurally_non_comparable",
    "stale",
)
# Days after the *next* period ends before a missing successor is due.
# Long enough that a normal publication lag is still the latest official print.
# Clock age of retrieved_at is not an input.
NEXT_RELEASE_GRACE_DAYS = MappingProxyType({"monthly": 45, "quarterly": 60})

REVISED_REVISION_STATUSES = frozenset({"revised", "preliminary"})

# Value-equality tolerance for unchanged reprints. Decimal, not binary float.
PERCENT_ABSOLUTE_TOLERANCE = Decimal("0.05")
RELATIVE_TOLERANCE = Decimal("0.001")
ZERO_BASELINE_ABSOLUTE_TOLERANCE = Decimal("1e-9")

# Registry retrieval TTL. This is not the Country Detail analytical gate.
# ``is_stale`` remains for that TTL. Attention must not exclude the latest
# official observation because this many days have elapsed since retrieval.
# The day count comes from data/country_registry.json economies.<code>.stale_after_days.
# This module does not copy those day counts and does not read the file.
STALE_AFTER_DAYS_SOURCE = "data/country_registry.json#economies.<code>.stale_after_days"
STALE_WHEN_AGE_DAYS_STRICTLY_GREATER = True
CLOCK_AGE_DOES_NOT_GATE_ANALYTICAL_ELIGIBILITY = True

# --- Identity ---
# Canonical JSON uses sorted keys. This tuple is the exact key set, user order.
OBSERVATION_ID_FIELDS = (
    "country",
    "series_id",
    "reference_period",
    "transformation",
    "geography",
    "seasonal_adjustment",
    "units",
    "nominal_basis",
)
NOMINAL_BASIS = ("nominal", "real", "physical", "index", "balance", "unknown")
COUNTRY_CODES = ("US", "CA", "AU", "NZ", "EA", "JP")
GEOGRAPHY_ALBERTA = "AB"
# National series use the country code as geography. Alberta does not use "CA".
NATIONAL_GEOGRAPHY_EQUALS_COUNTRY = True

# --- Topics ---
TOPIC_IDS = (
    "inflation",
    "labor",
    "activity",
    "consumer",
    "housing",
    "energy_physical",
    "rates_fx",
    "external",
    "other",
)
DIMENSION_TOPIC = MappingProxyType(
    {
        "Inflation": "inflation",
        "Labor": "labor",
        "Activity": "activity",
        "Consumer": "consumer",
    }
)
SCORE_DIMENSIONS = ("Inflation", "Labor", "Activity", "Consumer")
TOPIC_RULES = (
    "Map Inflation, Labor, Activity, and Consumer through DIMENSION_TOPIC.",
    "Physical production (oil or gas cubic metres, nominal_basis physical), including Alberta AER rows, is energy_physical. Country stays CA and Alberta geography is AB.",
    "A catalog id prefix is not a topic. CA.Activity volume indexes that are not physical production are not energy_physical.",
    "Real manufacturing, wholesale, and building volume indexes stay activity.",
    "Retail volume stays consumer.",
    "Housing series are housing.",
    "Rates, yields, and FX are rates_fx.",
    "Merchandise trade, including CA.Activity.crude_export_volume, is external.",
    "Anything else is other.",
)

# Examples of a stable release_family id, not a closed catalog.
EXAMPLE_RELEASE_FAMILIES = MappingProxyType(
    {
        "au_mhsi_total": "AU MHSI total monthly percent and through-the-year percent",
        "au_cpi": "AU CPI headline and trimmed mean published together",
        "aer_st3_oil": "Alberta oil rows from one AER ST3 workbook",
    }
)

TRANSFORMATION_LABELS = MappingProxyType(
    {
        "mom_pct": "monthly percent change",
        "yoy_pct": "through-the-year percent change",
        "qoq_pct": "quarterly percent change",
        "mom_sa_pct": "monthly percent change",
        "monthly_level": "monthly level",
        "calendar_day_rate": "calendar-day rate",
    }
)

# calendar_day_rate is a transformation, never a seasonal-adjustment flag.
CALENDAR_DAY_RATE_IS_SEASONAL_ADJUSTMENT = False

# --- AU household spending (two identities; never collapsed) ---
AU_HOUSEHOLD_SPENDING_MONTHLY = MappingProxyType(
    {
        "catalog_id": "AU.Consumer.spending",
        "series_id": "A130200586W",
        "transformation": "mom_pct",
        "seasonal_adjustment": True,
        "geography": "AU",
        "units": "percent",
        "nominal_basis": "nominal",
        "score_role": "scored",
        "weight": 0.25,
        "topic": "consumer",
        "country": "AU",
    }
)
# series_id is required and must be parsed from the official MHSI workbook
# column (through the year / corresponding month of previous year).
# None is intentional: this contract does not invent an ABS series id.
AU_HOUSEHOLD_SPENDING_ANNUAL = MappingProxyType(
    {
        "series_id": None,
        "series_id_rule": "required_from_official_workbook_column",
        "workbook_column": "through the year / corresponding month of previous year",
        "transformation": "yoy_pct",
        "seasonal_adjustment": True,
        "geography": "AU",
        "units": "percent",
        "nominal_basis": "nominal",
        "score_role": "unscored",
        "weight": 0.0,
        "topic": "consumer",
        "country": "AU",
        "release_family": "au_mhsi_total",
        "must_not_compound_monthly_percent": True,
    }
)
AU_MHSI_RELEASE_FAMILY = "au_mhsi_total"

# Within a correlation group, status and extremity choose the slot.
# Freshness orders distinct findings after that choice.
DEDUPE_BEFORE_FRESHNESS = True
# Final tie-break when status and band distance are equal.
FINAL_TIE_BREAK = "lexicographic observation_id ascending"

# --- Score audit and trader-room firewall ---
SCORE_AUDIT_REFERENCES_OBSERVATION_ID_ONLY = True
LINEAGE_ANCHOR_PHRASE = "50 = structural/policy neutral anchor"
ATTENTION_MUST_NOT_CHANGE_SCORES = True
ATTENTION_IMPORT_FORBIDDEN_PREFIXES = (
    "scripts/trader_room/",
    "scripts/trading/",
    "scripts/pm/",
    "scripts/market_watch_launch/freeze.py",
)
PACKET_FORBIDDEN_KEYS = (
    "attention",
    "attention_status",
    "what_matters_now",
    "wmn",
    "research_narrative",
    "notable",
    "outlier",
    "interesting",
    "travel_pattern",
)
NARRATIVE_MUST_BE_COUNTRY_SPECIFIC = ("EA", "JP")

# --- Renderer hooks (UI worker). Class attribute order is significant. ---
RENDERER_COUNTRY_DETAIL = "section.country-detail"
RENDERER_SCORE_COMPACT_CLASS = "score-compact"
RENDERER_WMN_SECTION = "section.what-matters-now"
RENDERER_WMN_LIST = "ol.wmn-list"
RENDERER_WMN_QUIET = "p.wmn-quiet"
WMN_QUIET_TEXT = "No finding clears the attention rules."
RENDERER_FINDING = "article.wmn-finding"
RENDERER_REASON_CLASS = "wmn-reason"
RENDERER_HEADLINE_CLASS = "wmn-headline"
RENDERER_EVIDENCE_SECTION = "section.country-evidence"
# Exact attribute required by scripts/apply_temperature_scores.py.
SCORE_DETAIL_CLASS_ATTRIBUTE = "temp-dimension score-detail"
HARD_SCORE_INPUTS_TITLE = "Hard score inputs"
EVIDENCE_BLOCK_CONTEXT_CLASS = "evidence-block context"
KEYBOARD_CONTROLS = ("button", "summary", "input", "a[href]")
WMN_INITIAL_LIST_CAP = MAX_FINDINGS_INITIAL

_MONTHLY_PERIOD = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_QUARTERLY_PERIOD = re.compile(r"^(\d{4})-Q([1-4])$")


def inclusive_midrank_percentile(sample: Sequence[float], x: float) -> float:
    """Inclusive nearest-rank percentile of ``x``.

    ``sample`` is the comparable sample and already contains the latest point.
    Equality is exact (source values), not the reprint tolerance.
    ``r = 1 + count(v < x) + 0.5 * count(v == x)``
    ``percentile = (r - 0.5) / n * 100``
    """
    if not sample:
        raise ValueError("comparable sample is empty")
    values = [float(value) for value in sample]
    latest = float(x)
    if any(value != value or value in (float("inf"), float("-inf")) for value in (*values, latest)):
        raise ValueError("percentile sample must be finite")
    less = sum(1 for value in values if value < latest)
    equal = sum(1 for value in values if value == latest)
    if equal == 0:
        raise ValueError("latest point must be inside the comparable sample")
    n = len(values)
    rank = 1 + less + 0.5 * equal
    return (rank - 0.5) / n * 100.0


def distance_outside_nearest_band(percentile: float) -> float:
    """Positive distance beyond the tightest band edge already crossed.

    Outlier region uses 1 or 99. Notable-only region uses 5 or 95.
    Inside the closed interval [5, 95] the distance is 0.
    """
    if percentile > OUTLIER_PERCENTILE_HIGH:
        return percentile - OUTLIER_PERCENTILE_HIGH
    if percentile < OUTLIER_PERCENTILE_LOW:
        return OUTLIER_PERCENTILE_LOW - percentile
    if percentile > NOTABLE_PERCENTILE_HIGH:
        return percentile - NOTABLE_PERCENTILE_HIGH
    if percentile < NOTABLE_PERCENTILE_LOW:
        return NOTABLE_PERCENTILE_LOW - percentile
    return 0.0


def sample_minima(cadence: str) -> Mapping[str, int] | None:
    """Return notable/outlier minima, or None when the cadence is ineligible."""
    return SAMPLE_MINIMA.get(cadence)


def _format_percentile(percentile: float) -> str:
    return f"{percentile:.6f}"


def badge_text(attention_status: str) -> str | None:
    """Badge label. None means no badge. Never a temperature class."""
    if attention_status == "none":
        return None
    try:
        return ATTENTION_BADGE_TEXT[attention_status]
    except KeyError as exc:
        raise ValueError(f"unknown attention_status: {attention_status}") from exc


def classify_attention(
    *,
    cadence: str,
    comparable_n: int,
    percentile: float | None = None,
    seasonal_adjustment: bool | None = None,
    data_state: str = "ok",
    comparison_broken: bool = False,
) -> dict[str, Any]:
    """Map an already-filtered comparable sample to a status and reasons.

    ``comparable_n`` is the count after methodology-break and seasonal-peer
    filters. For ``seasonal_adjustment is False`` that count is the same-month
    or same-quarter peer count, not the all-month count.
    """
    if data_state not in DATA_STATES:
        raise ValueError(f"unknown data_state: {data_state}")
    if comparable_n < 0:
        raise ValueError("comparable_n must be >= 0")

    effective_state = data_state
    if comparison_broken and effective_state == "ok":
        effective_state = "structurally_non_comparable"

    def _result(status: str, reasons: tuple[str, ...], reason: str) -> dict[str, Any]:
        unknown = set(reasons) - INELIGIBILITY_REASONS
        if unknown:
            raise ValueError(f"unknown ineligibility: {sorted(unknown)}")
        return {
            "attention_status": status,
            "ineligibility": list(reasons),
            "badge_text": badge_text(status),
            "reason": reason,
            "percentile": percentile,
            "comparable_n": comparable_n,
            "data_state": effective_state,
        }

    if effective_state == "missing":
        return _result("none", ("missing_value",), "No attention badge: missing_value.")
    if effective_state == "failed_fetch":
        return _result("none", ("failed_fetch",), "No attention badge: failed_fetch.")
    if effective_state == "structurally_non_comparable":
        return _result(
            "none",
            ("structurally_non_comparable",),
            "No attention badge: structurally_non_comparable.",
        )
    if effective_state == "due_late":
        return _result("none", ("due_late",), "No attention badge: due_late.")
    if effective_state == "superseded":
        return _result("none", ("superseded",), "No attention badge: superseded.")
    if effective_state == "stale":
        return _result("none", ("stale",), "No attention badge: stale.")

    minima = sample_minima(cadence)
    if minima is None:
        return _result("none", ("unknown_cadence",), "No attention badge: unknown_cadence.")

    notable_min = minima["notable"]
    outlier_min = minima["outlier"]
    if seasonal_adjustment is False and comparable_n < notable_min:
        return _result(
            "none",
            ("seasonal_history_insufficient",),
            (
                "No attention badge: seasonal_history_insufficient "
                f"(same-calendar-period n={comparable_n} < {notable_min} {cadence})."
            ),
        )
    if comparable_n < notable_min:
        return _result(
            "none",
            ("insufficient_history",),
            (
                "No attention badge: insufficient_history "
                f"(n={comparable_n} < {notable_min} {cadence})."
            ),
        )
    if percentile is None:
        raise ValueError("percentile is required once the sample is eligible")

    outlier_region = percentile < OUTLIER_PERCENTILE_LOW or percentile > OUTLIER_PERCENTILE_HIGH
    notable_region = percentile < NOTABLE_PERCENTILE_LOW or percentile > NOTABLE_PERCENTILE_HIGH
    rendered = _format_percentile(percentile)
    if outlier_region and comparable_n < outlier_min:
        return _result(
            "notable",
            ("insufficient_history_for_outlier",),
            (
                f"Notable: inclusive nearest-rank percentile {rendered} on {cadence} "
                f"n={comparable_n} is outside 1/99; outlier minimum is {outlier_min}; "
                "insufficient_history_for_outlier."
            ),
        )
    if outlier_region:
        return _result(
            "outlier",
            (),
            (
                f"Outlier: inclusive nearest-rank percentile {rendered} is outside "
                f"1/99 on {cadence} n={comparable_n}."
            ),
        )
    if notable_region:
        return _result(
            "notable",
            (),
            (
                f"Notable: inclusive nearest-rank percentile {rendered} is outside "
                f"5/95 on {cadence} n={comparable_n}."
            ),
        )
    return _result(
        "none",
        ("not_material",),
        (
            f"No attention badge: not_material (percentile {rendered} is inside "
            f"5/95 on {cadence} n={comparable_n})."
        ),
    )


def _signed_number(value: float) -> str:
    """Display a source number with an explicit plus on positives."""
    text = format_source_value(value)
    if value > 0 and not text.startswith("+"):
        return f"+{text}"
    return text


def _join_signed(values: Sequence[float]) -> str:
    parts = [_signed_number(value) for value in values]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def _ending_run(steps: Sequence[int]) -> tuple[int, int]:
    """Sign and length of the same-direction run ending at the last step.

    A flat step (0) ends the run. Returns ``(0, 0)`` when the last step is flat
    or the sequence is empty.
    """
    if not steps or steps[-1] == 0:
        return 0, 0
    sign = steps[-1]
    run = 0
    for step in reversed(steps):
        if step != sign:
            break
        run += 1
    return sign, run


def _percentish(units: str) -> bool:
    return is_percent_like_units(units)


def _flat_change(value: float, units: str) -> bool:
    """A change-series print too small to be a direction."""
    if _percentish(units):
        return abs(_decimal(value)) < PERCENT_ABSOLUTE_TOLERANCE
    return value_unchanged(units, 0.0, value)


def _flat_diff(previous: float, current: float, units: str) -> bool:
    return value_unchanged(units, previous, current)


def _pace_increased(previous_mag: float, latest_mag: float, units: str) -> bool:
    if previous_mag <= 0:
        return False
    if _percentish(units):
        return _decimal(latest_mag) - _decimal(previous_mag) >= PERCENT_STEP_MATERIAL
    return _decimal(latest_mag) >= _decimal(previous_mag) * LEVEL_PACE_RATIO


def _pace_decreased(previous_mag: float, latest_mag: float, units: str) -> bool:
    if previous_mag <= 0:
        return False
    if _percentish(units):
        return _decimal(previous_mag) - _decimal(latest_mag) >= PERCENT_STEP_MATERIAL
    if latest_mag == 0:
        return True
    return _decimal(previous_mag) >= _decimal(latest_mag) * LEVEL_PACE_RATIO


def _reversal_material(latest_mag: float, units: str) -> bool:
    if _percentish(units):
        return _decimal(latest_mag) >= PERCENT_STEP_MATERIAL
    return latest_mag > 0


def uses_print_sign(transformation: str) -> bool:
    """True when the print itself is the period's direction.

    Month-on-month and quarter-on-quarter changes, including job-change
    transforms, use the sign of the print. Through-the-year percent and
    rate levels use the change in that rate, so a long positive run is not
    treated as persistence. Levels and indexes use the first difference.
    """
    name = transformation.strip().lower()
    if name in {"yoy_pct", "rate_pct"}:
        return False
    if name in CHANGE_SIGN_TRANSFORMATIONS:
        return True
    if "change" in name:
        return True
    if name.endswith("_pct") or name.endswith("_pct_saar") or "saar" in name:
        return True
    return False


def _travel_steps(
    values: Sequence[float],
    *,
    units: str,
    transformation: str,
) -> tuple[list[int], list[float], list[float]]:
    """Return step signs, step magnitudes, and the observation tail those steps use.

    Change-sign transforms (mom/qoq and other period changes) use the print
    itself. yoy and levels use the first difference, so a structurally positive
    yoy rate is not persistence.
    """
    if uses_print_sign(transformation):
        signs: list[int] = []
        magnitudes: list[float] = []
        for value in values:
            if _flat_change(value, units):
                signs.append(0)
                magnitudes.append(0.0)
            elif value > 0:
                signs.append(1)
                magnitudes.append(abs(value))
            else:
                signs.append(-1)
                magnitudes.append(abs(value))
        return signs, magnitudes, list(values)
    signs = []
    magnitudes = []
    for previous, current in zip(values, values[1:]):
        if _flat_diff(previous, current, units):
            signs.append(0)
            magnitudes.append(0.0)
        elif current > previous:
            signs.append(1)
            magnitudes.append(abs(current - previous))
        else:
            signs.append(-1)
            magnitudes.append(abs(current - previous))
    return signs, magnitudes, list(values)


def _display_tail(observed: Sequence[float], run: int, *, differenced: bool) -> list[float]:
    """Observations that illustrate the ending run. At most four numbers."""
    span = run + 1 if differenced else run
    span = max(span, 2)
    tail = list(observed[-span:])
    if len(tail) > 4:
        tail = tail[-4:]
    return tail


def _range_break(values: Sequence[float], units: str) -> bool:
    """Latest print leaves the prior range by more than a typical step."""
    if len(values) < 4:
        return False
    prior = list(values[:-1])
    latest = float(values[-1])
    lo = min(prior)
    hi = max(prior)
    if lo <= latest <= hi:
        return False
    overshoot = latest - hi if latest > hi else lo - latest
    extreme = hi if latest > hi else lo
    if _percentish(units):
        if _decimal(abs(overshoot)) < PERCENT_STEP_MATERIAL:
            return False
    elif value_unchanged(units, extreme, latest):
        return False
    steps = [abs(after - before) for before, after in zip(prior, prior[1:])]
    if not steps:
        return True
    ordered = sorted(steps)
    median = ordered[len(ordered) // 2]
    if median == 0:
        return True
    return abs(overshoot) >= float(LEVEL_PACE_RATIO) * median


def _travel_reason(
    pattern: str,
    *,
    transformation: str,
    tail: Sequence[float],
    run: int,
) -> str:
    label = transformation_label(transformation)
    joined = _join_signed(tail)
    if pattern == "persistence":
        return (
            f"Persistence: {label} kept the same direction for {run} periods, "
            f"ending {joined}."
        )
    if pattern == "acceleration":
        return (
            f"Acceleration: {label} ran {joined}. The latest {_signed_number(tail[-1])} "
            f"is larger in the same direction than the prior {_signed_number(tail[-2])}."
        )
    if pattern == "deceleration":
        return (
            f"Deceleration: {label} ran {joined}. The latest {_signed_number(tail[-1])} "
            "materially slows the prior direction of travel."
        )
    if pattern == "reversal":
        return (
            f"Reversal: {label} ran {joined}. The latest {_signed_number(tail[-1])} "
            "flips the prior direction of travel."
        )
    if pattern == "range_break":
        prior = list(tail[:-1]) if len(tail) > 1 else list(tail)
        return (
            f"Range break: the latest {_signed_number(tail[-1])} on {label} is outside "
            f"the prior comparable range {_signed_number(min(prior))} to "
            f"{_signed_number(max(prior))}."
        )
    raise ValueError(f"unknown travel pattern: {pattern}")


def classify_travel(
    values: Sequence[float],
    *,
    units: str,
    transformation: str,
    cadence: str,
) -> dict[str, Any] | None:
    """Direction-of-travel pattern on an ordered comparable sample, or None.

    ``values`` includes the latest observation and is chronological.
    This does not apply source-health blocks and does not assign Notable or
    Outlier. Callers suppress the result when the row is stale, missing,
    failed, or structurally non-comparable.
    """
    if cadence not in KNOWN_CADENCES:
        return None
    if len(values) < 3:
        return None
    finite = []
    for value in values:
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            return None
        finite.append(number)
    signs, magnitudes, observed = _travel_steps(
        finite,
        units=units,
        transformation=transformation,
    )
    if len(signs) < 2:
        return None
    differenced = not uses_print_sign(transformation)
    latest_sign, run = _ending_run(signs)
    prior_sign, prior_run = _ending_run(signs[:-1])
    latest_mag = magnitudes[-1]
    previous_mag = magnitudes[-2] if len(magnitudes) >= 2 else 0.0

    pattern: str | None = None
    direction = 0
    reported_run = run
    if (
        prior_run >= MIN_PRIOR_RUN_FOR_TURN
        and latest_sign != 0
        and prior_sign != 0
        and latest_sign == -prior_sign
        and _reversal_material(latest_mag, units)
    ):
        pattern = "reversal"
        direction = latest_sign
        reported_run = prior_run
    elif run >= MIN_SAME_DIRECTION_PERIODS and _pace_increased(previous_mag, latest_mag, units):
        pattern = "acceleration"
        direction = latest_sign
    elif (
        prior_run >= MIN_PRIOR_RUN_FOR_TURN
        and prior_sign != 0
        and (latest_sign == prior_sign or latest_sign == 0)
        and _pace_decreased(previous_mag, latest_mag, units)
    ):
        pattern = "deceleration"
        direction = prior_sign
        reported_run = prior_run if latest_sign == 0 else run
    elif run >= MIN_SAME_DIRECTION_PERIODS:
        pattern = "persistence"
        direction = latest_sign
    elif _range_break(finite, units):
        pattern = "range_break"
        direction = 1 if finite[-1] > max(finite[:-1]) else -1
        reported_run = 1

    if pattern is None or direction == 0:
        return None
    display_run = prior_run + 1 if pattern == "reversal" else reported_run
    tail = _display_tail(observed, display_run, differenced=differenced)
    if pattern == "range_break":
        tail = [min(finite[:-1]), max(finite[:-1]), finite[-1]]
    if len(tail) < 2:
        return None
    return {
        "pattern": pattern,
        "direction": direction,
        "run_length": reported_run,
        "reason": _travel_reason(
            pattern,
            transformation=transformation,
            tail=tail,
            run=reported_run,
        ),
        "tail_values": tail,
    }


def historical_label_clause(ineligibility: Sequence[str]) -> str:
    """Sentence appended when a travel finding must not wear a historical badge."""
    if "seasonal_history_insufficient" in ineligibility:
        return (
            " A historical percentile badge is not claimed (seasonal_history_insufficient)."
        )
    if "insufficient_history" in ineligibility:
        return " A historical percentile badge is not claimed (insufficient_history)."
    return ""


def _require_period(period: str, cadence: str) -> str:
    if cadence == CADENCE_MONTHLY:
        if not _MONTHLY_PERIOD.match(period):
            raise ValueError(f"monthly period must be YYYY-MM: {period}")
        return period
    if cadence == CADENCE_QUARTERLY:
        if not _QUARTERLY_PERIOD.match(period):
            raise ValueError(f"quarterly period must be YYYY-Qn: {period}")
        return period
    raise ValueError(f"cannot filter periods for cadence: {cadence}")


def filter_comparable_history(
    history: Sequence[Mapping[str, Any]],
    *,
    latest_period: str,
    cadence: str,
    seasonal_adjustment: bool | None,
    methodology_breaks: Sequence[str] = (),
    comparison_broken: bool = False,
) -> dict[str, Any]:
    """Apply comparability filters. Does not read storage.

    Methodology breaks are the first period of a new regime (inclusive).
    Points strictly before the latest break that is <= ``latest_period`` are
    excluded and counted in ``excluded_count``. Seasonal unadjusted samples
    then keep only the same calendar month (monthly) or quarter (quarterly).
    ``seasonal_adjustment is None`` does not apply that peer filter.
    One value per reference period; resolve vintages before calling.
    """
    if cadence not in KNOWN_CADENCES:
        raise ValueError(f"unknown cadence: {cadence}")
    _require_period(latest_period, cadence)
    seen: set[str] = set()
    points: list[dict[str, Any]] = []
    for item in history:
        period = _require_period(str(item["reference_period"]), cadence)
        if period in seen:
            raise ValueError(f"duplicate reference_period: {period}")
        seen.add(period)
        points.append({"reference_period": period, "value": item["value"]})
    if latest_period not in seen:
        raise ValueError("latest point must be inside the sample")

    up_to = [item for item in points if item["reference_period"] <= latest_period]
    if comparison_broken:
        return {
            "comparable": [],
            "excluded_count": len(up_to),
            "seasonal_excluded_count": 0,
            "comparison_broken": True,
        }

    regime_start: str | None = None
    for boundary in methodology_breaks:
        _require_period(boundary, cadence)
        if boundary <= latest_period and (regime_start is None or boundary > regime_start):
            regime_start = boundary
    if regime_start is None:
        after_break = up_to
    else:
        after_break = [item for item in up_to if item["reference_period"] >= regime_start]
    excluded_count = len(up_to) - len(after_break)

    if seasonal_adjustment is False and cadence == CADENCE_MONTHLY:
        month = latest_period[5:7]
        comparable = [item for item in after_break if item["reference_period"][5:7] == month]
    elif seasonal_adjustment is False and cadence == CADENCE_QUARTERLY:
        quarter = latest_period[-2:]
        comparable = [item for item in after_break if item["reference_period"].endswith(quarter)]
    else:
        comparable = after_break
    return {
        "comparable": comparable,
        "excluded_count": excluded_count,
        "seasonal_excluded_count": len(after_break) - len(comparable),
        "comparison_broken": False,
    }


def is_percent_like_units(units: str) -> bool:
    """Percent-like units use the absolute 0.05 reprint tolerance."""
    token = units.strip().lower()
    if token in {"%", "pct"}:
        return True
    return token == "percent" or token.startswith("percent ") or token.startswith("percent_")


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))


def value_unchanged(units: str, previous: float, current: float) -> bool:
    """Reprint tolerance. Percent-like: absolute difference < 0.05.

    Other units: relative difference < 0.001 against ``abs(previous)``.
    A zero previous value uses absolute difference < 1e-9 instead of a ratio.
    Comparison is decimal (via ``str`` of each source number), not binary float dust.
    """
    if isinstance(previous, bool) or isinstance(current, bool):
        raise ValueError("values must be numeric")
    before = _decimal(previous)
    after = _decimal(current)
    if not before.is_finite() or not after.is_finite():
        raise ValueError("values must be finite")
    difference = abs(after - before)
    if is_percent_like_units(units):
        return difference < PERCENT_ABSOLUTE_TOLERANCE
    if before == 0:
        return difference < ZERO_BASELINE_ABSOLUTE_TOLERANCE
    return difference / abs(before) < RELATIVE_TOLERANCE


def is_revised_data_state(
    *,
    revision_status: str | None,
    vintage_changed: bool,
    value_changed: bool,
) -> bool:
    """Revised when the publisher says so, or a vintage change moves the value."""
    if revision_status in REVISED_REVISION_STATUSES:
        return True
    return bool(vintage_changed and value_changed)


def is_unchanged_reprint(
    *,
    units: str,
    previous_value: float | None,
    current_value: float | None,
    previous_reference_period: str | None,
    current_reference_period: str | None,
    previous_transformation: str | None,
    current_transformation: str | None,
    previous_revision_status: str | None,
    current_revision_status: str | None,
) -> bool:
    """Same observation identity's prior attention snapshot, within tolerance.

    Vintage is not part of this match. A vintage change without a value change
    stays an unchanged reprint. A value change that fails this match is not
    automatically ``revised``; see ``is_revised_data_state``.
    """
    if previous_value is None or current_value is None:
        return False
    return bool(
        value_unchanged(units, previous_value, current_value)
        and previous_reference_period == current_reference_period
        and previous_transformation == current_transformation
        and previous_revision_status == current_revision_status
    )


def alert_freshness_for(*, has_prior: bool, unchanged_reprint: bool, revised: bool) -> str:
    """``new`` if there is no prior snapshot or the value moved without a revision flag.

    ``unchanged`` does not raise a new alert and sorts after new and revised findings.
    """
    if not has_prior:
        return "new"
    if unchanged_reprint:
        return "unchanged"
    if revised:
        return "revised"
    return "new"


def wmn_reason(base_reason: str, alert_freshness: str) -> str:
    """Deterministic What Matters Now reason string."""
    if alert_freshness == "new":
        return base_reason
    if alert_freshness == "unchanged":
        return (
            f"{base_reason} Freshness unchanged_reprint: visible, not a new alert, "
            "sorts after new or revised findings."
        )
    if alert_freshness == "revised":
        return f"{base_reason} Freshness revised."
    raise ValueError(f"unknown alert_freshness: {alert_freshness}")


def age_in_days(retrieved_at: str, as_of: str) -> int:
    """Whole UTC calendar days from ``retrieved_at`` to ``as_of`` (date prefix)."""
    start = date.fromisoformat(retrieved_at[:10])
    end = date.fromisoformat(as_of[:10])
    return (end - start).days


def is_stale(*, retrieved_at: str, as_of: str, stale_after_days: int) -> bool:
    """Registry retrieval TTL. Not the Country Detail analytical exclusion.

    Whole UTC days since ``retrieved_at`` strictly greater than the registry
    count. Country Detail must not call this to drop a latest official print.
    Macro-ingestion freshness stays on its own gate.
    """
    if stale_after_days < 0:
        raise ValueError("stale_after_days must be >= 0")
    return age_in_days(retrieved_at, as_of) > stale_after_days


def series_identity(observation: Mapping[str, Any]) -> tuple[Any, ...]:
    """Series identity without reference period. A later period supersedes this one."""
    return tuple(
        observation.get(field)
        for field in OBSERVATION_ID_FIELDS
        if field != "reference_period"
    )


def period_sort_key(period: str) -> tuple[int, int]:
    """Order monthly and quarterly reference periods. Unparsed periods sort first."""
    monthly = _MONTHLY_PERIOD.match(period or "")
    if monthly:
        return (int(monthly.group(1)), int(monthly.group(2)))
    quarterly = _QUARTERLY_PERIOD.match(period or "")
    if quarterly:
        return (int(quarterly.group(1)), int(quarterly.group(2)) * 3)
    return (0, 0)


def _advance_period(period: str, cadence: str) -> str:
    if cadence == CADENCE_MONTHLY:
        year = int(period[:4])
        month = int(period[5:7])
        if month == 12:
            return f"{year + 1}-01"
        return f"{year}-{month + 1:02d}"
    year = int(period[:4])
    quarter = int(period[-1])
    if quarter == 4:
        return f"{year + 1}-Q1"
    return f"{year}-Q{quarter + 1}"


def _period_end(period: str, cadence: str) -> date:
    if cadence == CADENCE_MONTHLY:
        year = int(period[:4])
        month = int(period[5:7])
        return date(year, month, calendar.monthrange(year, month)[1])
    year = int(period[:4])
    quarter = int(period[-1])
    month = quarter * 3
    return date(year, month, calendar.monthrange(year, month)[1])


def successor_due_date(reference_period: str, cadence: str) -> date | None:
    """First date on which a missing successor is analytically due.

    Monthly: 45 days after the next month ends. Quarterly: 60 days after the
    next quarter ends. Unknown cadence or an unparsable period returns None,
    which means the latest observation stays current.
    """
    if cadence not in KNOWN_CADENCES or not reference_period:
        return None
    try:
        _require_period(reference_period, cadence)
    except ValueError:
        return None
    following = _advance_period(reference_period, cadence)
    return _period_end(following, cadence) + timedelta(days=int(NEXT_RELEASE_GRACE_DAYS[cadence]))


def release_is_due(*, reference_period: str, cadence: str, as_of: str) -> bool:
    """True when a newer official release should already have been ingested."""
    due = successor_due_date(reference_period, cadence)
    if due is None or not as_of:
        return False
    try:
        today = date.fromisoformat(str(as_of)[:10])
    except ValueError:
        return False
    return today >= due


def release_state_for_data_state(data_state: str) -> str:
    """Map an analytical data state onto the release-state vocabulary."""
    if data_state == "ok":
        return "current"
    if data_state not in RELEASE_STATES:
        raise ValueError(f"unknown data_state: {data_state}")
    return data_state


def next_retrieved_at(
    *,
    previous: str | None,
    attempted: str | None,
    data_state: str,
) -> str | None:
    """A failed fetch must not advance retrieved_at or observed_at."""
    if data_state == "failed_fetch":
        return previous
    return attempted


def correlation_key(
    country: str,
    topic: str,
    release_family: str,
    reference_period: str,
) -> tuple[str, str, str, str]:
    """One release/theme. Members of a key share at most one What Matters Now slot."""
    return (country, topic, release_family, reference_period)


def preference_key(
    *,
    attention_status: str,
    percentile: float | None,
    observation_id: str,
    travel_pattern: str | None = None,
    run_length: int = 0,
) -> tuple[Any, ...]:
    """Smaller key wins the correlation slot.

    Order: stronger status, then (for Interesting only) the travel pattern and
    run length, then more extreme distance outside the nearest band edge, then
    lexicographically smaller observation_id.
    Notable and Outlier keep the historical distance order. Status prefers a
    qualifying transform over a companion with status none.
    """
    if attention_status not in ATTENTION_STATUS_RANK:
        raise ValueError(f"unknown attention_status: {attention_status}")
    distance = 0.0 if percentile is None else distance_outside_nearest_band(percentile)
    if attention_status == "interesting":
        pattern_rank = TRAVEL_PATTERN_RANK.get(str(travel_pattern), 99)
        run_key = -int(run_length)
    else:
        pattern_rank = 0
        run_key = 0
    return (
        ATTENTION_STATUS_RANK[attention_status],
        pattern_rank,
        run_key,
        -distance,
        observation_id,
    )


def finding_list_sort_key(
    *,
    alert_freshness: str,
    attention_status: str,
    percentile: float | None,
    observation_id: str,
    travel_pattern: str | None = None,
    run_length: int = 0,
) -> tuple[Any, ...]:
    """Smaller key sorts earlier. Unchanged reprints sort after new and revised findings."""
    if alert_freshness not in ALERT_FRESHNESS_RANK:
        raise ValueError(f"unknown alert_freshness: {alert_freshness}")
    status_rank, pattern_rank, run_key, distance_key, obs = preference_key(
        attention_status=attention_status,
        percentile=percentile,
        observation_id=observation_id,
        travel_pattern=travel_pattern,
        run_length=run_length,
    )
    return (
        ALERT_FRESHNESS_RANK[alert_freshness],
        status_rank,
        pattern_rank,
        run_key,
        distance_key,
        obs,
    )


def transformation_label(transformation: str) -> str:
    """Human label. Unknown ids keep their words without underscores."""
    return TRANSFORMATION_LABELS.get(transformation, transformation.replace("_", " "))


def format_source_value(value: float) -> str:
    """Display the source value. Integers stay integers; this is not a second stored value."""
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return str(value)


def headline_text(transformation: str, value: float) -> str:
    """Headline is the qualifying transformation's label and source value."""
    return f"{transformation_label(transformation)} {format_source_value(value)}"


def require_topic(topic: str) -> str:
    if topic not in TOPIC_IDS:
        raise ValueError(f"unknown topic: {topic}")
    return topic


def _json_seasonal(value: Any) -> bool | None:
    if value is None or value is True or value is False:
        return value
    raise ValueError("seasonal_adjustment must be true, false, or null")


def observation_identity_payload(identity: Mapping[str, Any]) -> dict[str, Any]:
    """Exact canonical object. Missing keys raise. Extra keys are not hashed."""
    missing = [field for field in OBSERVATION_ID_FIELDS if field not in identity]
    if missing:
        raise ValueError(f"observation identity missing {missing}")
    country = identity["country"]
    if country not in COUNTRY_CODES:
        raise ValueError(f"country must be one of {COUNTRY_CODES}")
    series_id = identity["series_id"]
    if not isinstance(series_id, str) or not series_id:
        raise ValueError("series_id is required and must be a non-empty string")
    nominal_basis = identity["nominal_basis"]
    if nominal_basis not in NOMINAL_BASIS:
        raise ValueError(f"nominal_basis must be one of {NOMINAL_BASIS}")
    for field in ("reference_period", "transformation", "geography", "units"):
        field_value = identity[field]
        if not isinstance(field_value, str) or not field_value:
            raise ValueError(f"{field} is required and must be a non-empty string")
    return {
        "country": country,
        "series_id": series_id,
        "reference_period": identity["reference_period"],
        "transformation": identity["transformation"],
        "geography": identity["geography"],
        "seasonal_adjustment": _json_seasonal(identity["seasonal_adjustment"]),
        "units": identity["units"],
        "nominal_basis": nominal_basis,
    }


def canonical_observation_json(identity: Mapping[str, Any]) -> str:
    """Sorted keys, no whitespace, UTF-8 JSON (``ensure_ascii``)."""
    payload = observation_identity_payload(identity)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def observation_id(identity: Mapping[str, Any]) -> str:
    """Lowercase hex SHA-256 of the canonical identity JSON. Order-independent."""
    encoded = canonical_observation_json(identity).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def attention_import_forbidden(module_path: str) -> bool:
    """True when this path must not import attention, projection, or render output."""
    normalized = module_path.replace("\\", "/").lstrip("./")
    for prefix in ATTENTION_IMPORT_FORBIDDEN_PREFIXES:
        if normalized == prefix.rstrip("/") or normalized.startswith(prefix):
            return True
    return False


def packet_contains_attention(packet: Mapping[str, Any]) -> bool:
    """True when a frozen packet carries attention ranks or research narrative keys."""
    forbidden = set(PACKET_FORBIDDEN_KEYS)

    def _walk(node: Any) -> bool:
        if isinstance(node, Mapping):
            if any(key in forbidden for key in node):
                return True
            return any(_walk(value) for value in node.values())
        if isinstance(node, Sequence) and not isinstance(node, (str, bytes)):
            return any(_walk(item) for item in node)
        return False

    return _walk(packet)


_QUALIFYING_STATUSES = frozenset({"interesting", "notable", "outlier"})


def _member_preference(member: Mapping[str, Any]) -> tuple[Any, ...]:
    return preference_key(
        attention_status=str(member["attention_status"]),
        percentile=member.get("percentile"),
        observation_id=str(member["observation_id"]),
        travel_pattern=member.get("travel_pattern"),
        run_length=int(member.get("travel_run_length") or 0),
    )


def _travel_direction(member: Mapping[str, Any]) -> int:
    raw = member.get("travel_direction") or 0
    try:
        direction = int(raw)
    except (TypeError, ValueError):
        return 0
    if direction not in (-1, 0, 1):
        return 0
    return direction


def _divergence_sentence(left: Mapping[str, Any], right: Mapping[str, Any]) -> str:
    left_label = transformation_label(str(left["transformation"]))
    right_label = transformation_label(str(right["transformation"]))
    left_pattern = left.get("travel_pattern") or left.get("attention_status")
    right_pattern = right.get("travel_pattern") or right.get("attention_status")
    return (
        f"Confirmed divergence: {left_label} is {left_pattern} while "
        f"{right_label} is {right_pattern}."
    )


def _slot_winners(group: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """One slot, or two when opposite travel directions are both legitimate.

    Same-direction monthly and yoy variants stay one release. Opposite
    directions are distinct information and each keep a slot.
    """
    qualifying = [
        member
        for member in group
        if str(member["attention_status"]) in _QUALIFYING_STATUSES
    ]
    if not qualifying:
        return []
    primary = min(qualifying, key=_member_preference)
    winners: list[Mapping[str, Any]] = [primary]
    primary_direction = _travel_direction(primary)
    if primary_direction == 0:
        return winners
    opposite = [
        member
        for member in qualifying
        if member is not primary and _travel_direction(member) == -primary_direction
    ]
    if opposite:
        winners.append(min(opposite, key=_member_preference))
    return winners


def _finding_from_winner(
    winner: Mapping[str, Any],
    *,
    related: list[str],
    divergence: str | None,
) -> dict[str, Any]:
    winner_status = str(winner["attention_status"])
    freshness = str(winner.get("alert_freshness") or "new")
    reason = wmn_reason(str(winner["reason"]), freshness)
    if divergence:
        reason = f"{reason} {divergence}"
    finding = {
        "observation_id": winner["observation_id"],
        "attention_status": winner_status,
        "badge_text": badge_text(winner_status),
        "percentile": winner.get("percentile"),
        "comparable_n": winner.get("comparable_n"),
        "reason": reason,
        "ineligibility": list(winner.get("ineligibility") or []),
        "alert_freshness": freshness,
        "fresh_alert": freshness != "unchanged",
        "headline_observation_id": winner["observation_id"],
        "headline_transformation": winner["transformation"],
        "headline_label": transformation_label(str(winner["transformation"])),
        # Display string only. The stored number stays on the observation.
        "headline_text": headline_text(str(winner["transformation"]), winner["value"]),
        "related_observation_ids": list(related),
        "topic": winner["topic"],
        "release_family": winner["release_family"],
        "reference_period": winner["reference_period"],
        "geography": winner["geography"],
        "seasonal_adjustment": winner["seasonal_adjustment"],
        "score_role": winner["score_role"],
        "weight": winner["weight"],
        "data_state": winner["data_state"],
        "country": winner["country"],
        "series_id": winner["series_id"],
        "transformation": winner["transformation"],
        "units": winner["units"],
        "nominal_basis": winner["nominal_basis"],
        "travel_pattern": winner.get("travel_pattern"),
        "travel_direction": _travel_direction(winner),
        "travel_run_length": int(winner.get("travel_run_length") or 0),
    }
    if freshness == "unchanged" and "unchanged_reprint" not in finding["ineligibility"]:
        finding["ineligibility"] = [*finding["ineligibility"], "unchanged_reprint"]
    return finding


def select_what_matters_now(
    members: Sequence[Mapping[str, Any]],
    *,
    limit: int = MAX_FINDINGS_INITIAL,
) -> dict[str, Any]:
    """Dedup by correlation key, then sort and cap findings.

    A group whose strongest member has status ``none`` contributes no finding
    and does not mark companions as ``correlated_companion``.
    Qualifying groups keep one slot unless two members have opposite
    direction-of-travel patterns. Those two are distinct and both keep a slot.
    Every other member is a companion.
    """
    if limit < 0:
        raise ValueError("limit must be >= 0")
    grouped: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = {}
    order: list[tuple[str, str, str, str]] = []
    for member in members:
        require_topic(str(member["topic"]))
        key = correlation_key(
            str(member["country"]),
            str(member["topic"]),
            str(member["release_family"]),
            str(member["reference_period"]),
        )
        if key not in grouped:
            order.append(key)
            grouped[key] = []
        grouped[key].append(member)

    annotated: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for key in order:
        group = grouped[key]
        winners = _slot_winners(group)
        winner_ids = {id(winner) for winner in winners}
        group_qualifies = bool(winners)
        divergence = _divergence_sentence(winners[0], winners[1]) if len(winners) == 2 else None
        for winner in winners:
            related = sorted(
                str(member["observation_id"])
                for member in group
                if member is not winner
            )
            findings.append(
                _finding_from_winner(winner, related=related, divergence=divergence)
            )
        for member in group:
            record = dict(member)
            reasons = list(member.get("ineligibility") or [])
            won = id(member) in winner_ids
            record["what_matters_now_slot"] = bool(group_qualifies and won)
            if group_qualifies and not won and "correlated_companion" not in reasons:
                reasons.append("correlated_companion")
            if str(member.get("alert_freshness") or "new") == "unchanged" and "unchanged_reprint" not in reasons:
                reasons.append("unchanged_reprint")
            record["ineligibility"] = reasons
            if group_qualifies and won:
                record["related_observation_ids"] = sorted(
                    str(other["observation_id"])
                    for other in group
                    if other is not member
                )
            else:
                record["related_observation_ids"] = []
            annotated.append(record)

    findings.sort(
        key=lambda finding: finding_list_sort_key(
            alert_freshness=str(finding["alert_freshness"]),
            attention_status=str(finding["attention_status"]),
            percentile=finding.get("percentile"),
            observation_id=str(finding["observation_id"]),
            travel_pattern=finding.get("travel_pattern"),
            run_length=int(finding.get("travel_run_length") or 0),
        )
    )
    shown = findings[:limit]
    withheld = [str(finding["observation_id"]) for finding in findings[limit:]]
    return {
        "findings": shown,
        "finding_count": len(shown),
        "withheld_by_cap": withheld,
        "members": annotated,
    }
