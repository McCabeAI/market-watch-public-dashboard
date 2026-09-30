"""Frozen Country Detail attention policy (v1).

Pure constants and helpers. No I/O, no temperature history, no threshold fitting.
Thresholds were frozen before implementation and were not fit to current prints.

Percentiles describe the historical distribution of comparable observations only.
They are not predictive probabilities and do not imply mean reversion.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
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
ATTENTION_STATUSES = ("none", "notable", "outlier")
# Smaller rank wins a correlation slot and sorts earlier among equal freshness.
ATTENTION_STATUS_RANK = MappingProxyType({"outlier": 0, "notable": 1, "none": 2})
ECONOMIC_DIRECTION_IS_NOT_ATTENTION = True
FORBIDDEN_ATTENTION_TEMPERATURE_CLASSES = ("hot", "warm", "cold", "cool")
ATTENTION_BADGE_TEXT = MappingProxyType({"notable": "Notable", "outlier": "Outlier"})

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
    "revised",
    "structurally_non_comparable",
    "failed_fetch",
)
DATA_STATE_LABELS = MappingProxyType(
    {
        "missing": "Missing",
        "stale": "Stale",
        "revised": "Revised",
        "structurally_non_comparable": "Not comparable",
        "failed_fetch": "Source failed",
    }
)

REVISED_REVISION_STATUSES = frozenset({"revised", "preliminary"})

# Value-equality tolerance for unchanged reprints. Decimal, not binary float.
PERCENT_ABSOLUTE_TOLERANCE = Decimal("0.05")
RELATIVE_TOLERANCE = Decimal("0.001")
ZERO_BASELINE_ABSOLUTE_TOLERANCE = Decimal("1e-9")

# Stale age is whole UTC days since the last successful retrieved_at.
# The day count comes from data/country_registry.json economies.<code>.stale_after_days.
# This module does not copy those day counts and does not read the file.
STALE_AFTER_DAYS_SOURCE = "data/country_registry.json#economies.<code>.stale_after_days"
STALE_WHEN_AGE_DAYS_STRICTLY_GREATER = True

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
    """Stale only when age in whole UTC days is strictly greater than the registry count."""
    if stale_after_days < 0:
        raise ValueError("stale_after_days must be >= 0")
    return age_in_days(retrieved_at, as_of) > stale_after_days


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
) -> tuple[Any, ...]:
    """Smaller key wins the correlation slot.

    Order: stronger status, then more extreme distance outside the nearest
    band edge, then lexicographically smaller observation_id.
    Status already prefers a qualifying transform over a companion with status none.
    """
    if attention_status not in ATTENTION_STATUS_RANK:
        raise ValueError(f"unknown attention_status: {attention_status}")
    distance = 0.0 if percentile is None else distance_outside_nearest_band(percentile)
    return (ATTENTION_STATUS_RANK[attention_status], -distance, observation_id)


def finding_list_sort_key(
    *,
    alert_freshness: str,
    attention_status: str,
    percentile: float | None,
    observation_id: str,
) -> tuple[Any, ...]:
    """Smaller key sorts earlier. Unchanged reprints sort after new and revised findings."""
    if alert_freshness not in ALERT_FRESHNESS_RANK:
        raise ValueError(f"unknown alert_freshness: {alert_freshness}")
    status_rank, distance_key, obs = preference_key(
        attention_status=attention_status,
        percentile=percentile,
        observation_id=observation_id,
    )
    return (ALERT_FRESHNESS_RANK[alert_freshness], status_rank, distance_key, obs)


def transformation_label(transformation: str) -> str:
    return TRANSFORMATION_LABELS.get(transformation, transformation)


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


def select_what_matters_now(
    members: Sequence[Mapping[str, Any]],
    *,
    limit: int = MAX_FINDINGS_INITIAL,
) -> dict[str, Any]:
    """Dedup by correlation key, then sort and cap findings.

    A group whose strongest member has status ``none`` contributes no finding
    and does not mark companions as ``correlated_companion``.
    Qualifying groups keep one slot. Every other member is a companion.
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
        winner = min(
            group,
            key=lambda member: preference_key(
                attention_status=str(member["attention_status"]),
                percentile=member.get("percentile"),
                observation_id=str(member["observation_id"]),
            ),
        )
        winner_status = str(winner["attention_status"])
        group_qualifies = winner_status in {"notable", "outlier"}
        related = tuple(
            sorted(
                str(member["observation_id"])
                for member in group
                if member is not winner
            )
        )
        if group_qualifies:
            freshness = str(winner.get("alert_freshness") or "new")
            finding = {
                "observation_id": winner["observation_id"],
                "attention_status": winner_status,
                "badge_text": badge_text(winner_status),
                "percentile": winner.get("percentile"),
                "comparable_n": winner.get("comparable_n"),
                "reason": wmn_reason(str(winner["reason"]), freshness),
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
            }
            if freshness == "unchanged" and "unchanged_reprint" not in finding["ineligibility"]:
                finding["ineligibility"] = [*finding["ineligibility"], "unchanged_reprint"]
            findings.append(finding)
        for member in group:
            record = dict(member)
            reasons = list(member.get("ineligibility") or [])
            won = member is winner
            record["what_matters_now_slot"] = bool(group_qualifies and won)
            if group_qualifies and not won and "correlated_companion" not in reasons:
                reasons.append("correlated_companion")
            if str(member.get("alert_freshness") or "new") == "unchanged" and "unchanged_reprint" not in reasons:
                reasons.append("unchanged_reprint")
            record["ineligibility"] = reasons
            if group_qualifies and won:
                record["related_observation_ids"] = list(related)
            else:
                record["related_observation_ids"] = []
            annotated.append(record)

    findings.sort(
        key=lambda finding: finding_list_sort_key(
            alert_freshness=str(finding["alert_freshness"]),
            attention_status=str(finding["attention_status"]),
            percentile=finding.get("percentile"),
            observation_id=str(finding["observation_id"]),
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
