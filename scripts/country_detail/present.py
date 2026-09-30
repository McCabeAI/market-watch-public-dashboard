"""Country Detail display copy. Formatting only; score math stays untouched."""

from __future__ import annotations

import re
from typing import Any, Mapping

from scripts.country_detail.policy import DIMENSION_TOPIC, TRANSFORMATION_LABELS

_TOPIC_DIMENSION = {topic: dimension for dimension, topic in DIMENSION_TOPIC.items()}
_NEUTRAL_SCORE = 50.0

_INTERNAL_CODES = (
    "mom_change_thousands_sa",
    "mm_change_thousands_sa",
    "insufficient_history",
    "seasonal_history_insufficient",
    "insufficient_history_for_outlier",
    "unchanged_reprint",
    "structurally_non_comparable",
)


def plain_series_name(obs: Mapping[str, Any]) -> str:
    """Series title without a trailing transformation code."""
    label = str(obs.get("label") or obs.get("series_id") or "Series").strip()
    transformation = str(obs.get("transformation") or "")
    suffix = _transformation_words(transformation)
    if suffix:
        paren = f" ({suffix})"
        if label.endswith(paren):
            label = label[: -len(paren)].strip()
    if transformation.lower().startswith("level") and re.search(r"\bchange\b", label, flags=re.I):
        label = re.sub(r"(?i)^monthly change in ", "Level of ", label)
        label = re.sub(r"(?i)^change in ", "Level of ", label)
    return label or "Series"


def bucket_label(obs: Mapping[str, Any]) -> str:
    """Score dimension this series enters, or Context only."""
    topic = str(obs.get("topic") or "")
    dimension = _TOPIC_DIMENSION.get(topic)
    if obs.get("score_input") and dimension:
        return dimension
    if obs.get("score_role") == "scored" and dimension and "score_input" not in obs:
        return dimension
    return "Context only"


def series_synopsis(obs: Mapping[str, Any]) -> str:
    """One sentence on what the series measures."""
    name = plain_series_name(obs).lower()
    units = str(obs.get("units") or "").lower()
    transformation = str(obs.get("transformation") or "").lower()
    if "unemployment" in name:
        return "The share of the labor force that is unemployed."
    if "pmi" in name or "business survey" in name or units == "diffusion_index" or "ism " in name:
        return "A business survey of activity. Readings above 50 mean more firms report expansion than contraction."
    if any(token in name for token in ("payroll", "employed", "employment")) or "thousands" in transformation:
        if "change" in name or "change" in transformation:
            return "How many jobs were added or lost over the period."
        return "The number of people employed."
    if any(token in name for token in ("wage", "earning", "hourly")):
        return "How fast pay is growing."
    if "income" in name:
        return "How fast household income is growing."
    if "retail" in name:
        return "How fast retail sales are growing."
    if any(token in name for token in ("consumption", "spending", "household spending")):
        return "How fast household spending is growing."
    if any(token in name for token in ("confidence", "sentiment")):
        return "How households say they feel about the economy."
    if "gdp" in name or "domestic demand" in name:
        return "How fast the economy is growing."
    if any(token in name for token in ("cpi", "price index", "pce", "inflation", "hicp")):
        return "How fast prices are rising."
    if any(token in name for token in ("oil", "bitumen", "crude", "gas")):
        return "Physical energy supply, kept as context beside the scores."
    if "permit" in name:
        return "Housing construction approvals."
    return f"This series measures {plain_series_name(obs).rstrip('.')}."


def format_macro_value(value: Any, units: str | None, transformation: str | None = None) -> str:
    """Display formatting only. Stored values are not rounded in place."""
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number != number or number in (float("inf"), float("-inf")):
        return "—"
    unit = (units or "").strip().lower()
    transform = (transformation or "").strip().lower()
    if _is_count_change(unit, transform):
        return _format_count_change(number)
    if _is_percent(unit):
        return f"{number:.2f}%"
    if "thousand" in unit:
        if number.is_integer():
            return f"{int(number):,} thousand"
        return f"{number:,.2f} thousand"
    if abs(number) >= 10000 and number.is_integer():
        return f"{int(number):,}"
    if unit and unit not in {"index", "diffusion_index", "index points"} and not _is_percent(unit):
        label = _human_unit(units or "")
        if label:
            return f"{number:.2f} {label}"
    return f"{number:.2f}"


def format_signed_macro(value: float, obs: Mapping[str, Any]) -> str:
    text = format_macro_value(value, obs.get("units"), obs.get("transformation"))
    if value > 0 and not text.startswith("+"):
        return f"+{text}"
    return text


def why_it_surfaced(finding: Mapping[str, Any], obs: Mapping[str, Any]) -> str:
    """Plain-English reason. Internal codes stay in the technical detail."""
    reason = str(finding.get("reason") or "")
    pattern = str(finding.get("travel_pattern") or "")
    status = str(finding.get("attention_status") or "")
    if pattern == "reversal":
        lead = "The latest readings reversed direction."
    elif pattern == "acceleration":
        lead = "The latest move sped up in the same direction."
    elif pattern == "deceleration":
        lead = "The latest move slowed the prior direction."
    elif pattern == "persistence":
        run = int(finding.get("travel_run_length") or 0)
        lead = (
            f"It has moved the same way for {run} periods."
            if run
            else "It has kept the same direction."
        )
    elif pattern == "range_break":
        lead = "The latest reading moved outside its recent range."
    elif status in {"notable", "outlier"}:
        lead = "It stands out against its own history."
    else:
        lead = "It cleared the attention rules."

    extras = [_tail_phrase(reason, obs)]
    if "Confirmed divergence" in reason:
        extras.append("The monthly and longer-run readings point opposite ways.")
    if "insufficient_history" in reason or "seasonal_history_insufficient" in reason:
        extras.append("Comparable history is too short for a historical notable or outlier label.")
    if "unchanged_reprint" in reason:
        extras.append("This print matches the prior vintage, so it is not a new alert.")
    if "Freshness revised" in reason:
        extras.append("The publisher revised this print.")
    sentence = " ".join(part for part in [lead, *extras] if part)
    return f"Why it surfaced: {sentence}"


def contains_internal_code(text: str) -> bool:
    lowered = text.lower()
    return any(code in lowered for code in _INTERNAL_CODES)


def point_contribution(
    obs: Mapping[str, Any],
    country_code: str,
    score_state: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Points this scored input adds versus the neutral anchor.

    Uses the stored component level, weight, and coverage. Does not rescore.
    """
    if not obs.get("score_input"):
        return None
    located = _component_state(obs, country_code, score_state)
    if located is None:
        return None
    dimension, spec, state = located
    if not state.get("observed"):
        return None
    level = state.get("level")
    weight = state.get("weight")
    if level is None or weight is None:
        return None
    coverage = spec.get("coverage")
    try:
        coverage_f = float(coverage) if coverage not in (None, "") else float(weight)
    except (TypeError, ValueError):
        return None
    if coverage_f == 0:
        return None
    baseline = score_state.get("baseline_score", _NEUTRAL_SCORE)
    try:
        baseline_f = float(baseline)
    except (TypeError, ValueError):
        baseline_f = _NEUTRAL_SCORE
    points = (float(weight) / coverage_f) * (float(level) - baseline_f)
    return {
        "dimension": dimension,
        "points": points,
        "level": float(level),
        "weight": float(weight),
        "transform_value": state.get("transform_value"),
        "text": f"{points:+.2f} points in {dimension}",
    }


def score_print_text(obs: Mapping[str, Any], contribution: Mapping[str, Any] | None) -> str:
    """Latest print, and the scored pace when it differs from that print."""
    latest = format_macro_value(obs.get("value"), obs.get("units"), obs.get("transformation"))
    if not contribution:
        return latest
    scored = contribution.get("transform_value")
    if scored is None or obs.get("value") is None:
        return latest
    try:
        if abs(float(scored) - float(obs["value"])) < 0.005:
            return latest
    except (TypeError, ValueError):
        return latest
    scored_text = format_macro_value(scored, obs.get("units"), obs.get("transformation"))
    return f"Score uses {scored_text} · latest {latest}"


def _component_state(
    obs: Mapping[str, Any],
    country_code: str,
    score_state: Mapping[str, Any],
) -> tuple[str, Mapping[str, Any], Mapping[str, Any]] | None:
    catalog_id = str(obs.get("catalog_id") or "")
    parts = catalog_id.split(".")
    if len(parts) != 3:
        return None
    code, dimension, name = parts
    if code != country_code or dimension not in DIMENSION_TOPIC:
        return None
    if "countries" in score_state:
        country_bucket = (score_state.get("countries") or {}).get(country_code) or {}
        spec = country_bucket.get(dimension) or {}
    else:
        spec = score_state.get(dimension) or {}
    if not isinstance(spec, Mapping):
        return None
    state = (spec.get("component_state") or {}).get(name)
    if not isinstance(state, Mapping):
        return None
    return dimension, spec, state


def _transformation_words(transformation: str) -> str:
    if not transformation:
        return ""
    return str(TRANSFORMATION_LABELS.get(transformation, transformation.replace("_", " ")))


def _is_percent(unit: str) -> bool:
    return unit in {"percent", "%", "pct"} or unit.startswith("percent ") or unit.startswith("percent_")


def _human_unit(units: str) -> str:
    """Drop seasonal ETL suffixes so the face never prints codes like thousands_sa."""
    text = units.strip()
    lowered = text.lower()
    for suffix in ("_saar", "_nsa", "_sa"):
        if lowered.endswith(suffix):
            text = text[: -len(suffix)]
            break
    text = text.replace("_", " ").strip()
    if text.lower() in {"index", "diffusion index", "index points"}:
        return ""
    return text


def _is_count_change(unit: str, transformation: str) -> bool:
    count_units = "thousand" in unit or "thousands" in transformation
    if not count_units:
        return False
    return "change" in transformation or transformation.startswith(("mom_", "mm_"))


def _format_count_change(number: float) -> str:
    if number.is_integer():
        sign = "+" if number > 0 else ""
        return f"{sign}{int(number)}k"
    sign = "+" if number > 0 else ""
    return f"{sign}{number:.2f}k"


def history_limitation(reasons: list[str]) -> tuple[str, str] | None:
    """Plain limitation plus the code, for the expanded history block."""
    if "insufficient_history" in reasons:
        return (
            "Comparable history is too short to rank this against a long sample.",
            "insufficient_history",
        )
    if "seasonal_history_insufficient" in reasons:
        return (
            "Same-season history is too short to rank this against a long sample.",
            "seasonal_history_insufficient",
        )
    return None


_RAN = re.compile(r" ran (.+?)\. ")


def _tail_phrase(reason: str, obs: Mapping[str, Any]) -> str:
    match = _RAN.search(reason)
    if not match:
        return ""
    numbers = re.findall(r"[+-]?\d+(?:\.\d+)?", match.group(1))
    if not numbers:
        return ""
    formatted = [format_signed_macro(float(number), obs) for number in numbers]
    if len(formatted) == 1:
        joined = formatted[0]
    elif len(formatted) == 2:
        joined = f"{formatted[0]} and {formatted[1]}"
    else:
        joined = ", ".join(formatted[:-1]) + f", and {formatted[-1]}"
    return f"Recent readings: {joined}."
