"""One indicator view model for release cards, score drivers, and evidence cards.

Display facts only. Values come from committed projection history and the
stored score state; nothing here rescores or changes attention.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta
from typing import Any, Mapping, Sequence

from scripts.country_detail.present import (
    _component_state,
    _is_count_change,
    _is_percent,
    _names_price_index,
    format_macro_value,
    is_raw_price_index_level,
    plain_series_name,
    point_contribution,
    transformation_mark,
)

_MONTHLY = re.compile(r"^(\d{4})-(\d{2})$")
_QUARTERLY = re.compile(r"^(\d{4})-Q([1-4])$")
_ISO_DAY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()

# A first release lands after its period ends and within a few months. A date
# outside that window on a committed row is a later vintage stamp or a date
# carried over from an earlier row, so it is not shown as the release date.
MAX_FIRST_RELEASE_LAG_DAYS = 120

HISTORY_POINTS = {"monthly": 12, "quarterly": 8}
DEFAULT_HISTORY_POINTS = 12

_PMI_TOKENS = ("pmi", "ism", "purchasing", "ivey", "composite", "business survey")
_SURVEY_INDEX_TOKENS = ("confidence", "sentiment")


def period_key(period: str) -> tuple[int, int]:
    monthly = _MONTHLY.match(period or "")
    if monthly:
        return int(monthly.group(1)), int(monthly.group(2))
    quarterly = _QUARTERLY.match(period or "")
    if quarterly:
        return int(quarterly.group(1)), int(quarterly.group(2)) * 3
    return 0, 0


def period_label(period: Any) -> str:
    text = str(period or "")
    monthly = _MONTHLY.match(text)
    if monthly and 1 <= int(monthly.group(2)) <= 12:
        return f"{_MONTHS[int(monthly.group(2)) - 1]} {monthly.group(1)}"
    quarterly = _QUARTERLY.match(text)
    if quarterly:
        return f"Q{quarterly.group(2)} {quarterly.group(1)}"
    return text


def period_span(first: str, last: str) -> str:
    if first == last:
        return period_label(first)
    a, b = period_label(first).split(" "), period_label(last).split(" ")
    if len(a) == 2 and len(b) == 2 and a[1] == b[1]:
        return f"{a[0]}–{b[0]} {b[1]}"
    return f"{period_label(first)}–{period_label(last)}"


def period_end(period: str) -> date | None:
    year, month = period_key(period)
    if not year or not 1 <= month <= 12:
        return None
    return date(year, month, calendar.monthrange(year, month)[1])


def _cadence_of(period: str) -> str:
    if _QUARTERLY.match(period or ""):
        return "quarterly"
    if _MONTHLY.match(period or ""):
        return "monthly"
    return "other"


def _unit_word(cadence: str, count: int) -> str:
    word = {"monthly": "month", "quarterly": "quarter"}.get(cadence, "period")
    return word if count == 1 else f"{word}s"


def parse_day(value: Any) -> date | None:
    match = _ISO_DAY.match(str(value or "").strip())
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def day_label(day: date) -> str:
    return f"{day.day} {_MONTHS[day.month - 1]} {day.year}"


def credible_release_dates(points: Sequence[Mapping[str, Any]]) -> dict[str, date]:
    """Release date per period, only where the committed date can be a first release.

    A vintage stamp shared by several periods belongs to the newest of them;
    the older periods were revised on that day, not first published.
    """
    newest_for_day: dict[date, str] = {}
    for point in points:
        period = str(point.get("reference_period") or "")
        day = parse_day(point.get("release_date"))
        end = period_end(period)
        if day is None or end is None:
            continue
        if not end < day <= end + timedelta(days=MAX_FIRST_RELEASE_LAG_DAYS):
            continue
        current = newest_for_day.get(day)
        if current is None or period_key(period) > period_key(current):
            newest_for_day[day] = period
    return {period: day for day, period in newest_for_day.items()}


def measure_kind(obs: Mapping[str, Any]) -> str:
    """How a print is read: pct_change, rate, count_change, diffusion, index, balance, level."""
    units = str(obs.get("units") or "").strip().lower()
    transformation = str(obs.get("transformation") or "").strip().lower()
    name = f"{plain_series_name(obs)} {obs.get('label') or ''}".lower()
    if _is_count_change(units, transformation) or "change_thousands" in transformation:
        return "count_change"
    if units == "diffusion_index":
        return "diffusion"
    if units == "balance":
        return "balance"
    if _is_percent(units):
        if transformation in {"percent", "rate_pct"} or "unemployment" in name:
            return "rate"
        return "pct_change"
    if is_raw_price_index_level(obs):
        return "level"
    if units == "index" or any(token in name for token in _SURVEY_INDEX_TOKENS):
        return "index"
    return "level"


def is_pmi(obs: Mapping[str, Any]) -> bool:
    text = f"{plain_series_name(obs)} {obs.get('label') or ''} {obs.get('series_id') or ''}".lower()
    return measure_kind(obs) == "diffusion" and any(token in text for token in _PMI_TOKENS)


def value_text(value: Any, obs: Mapping[str, Any], kind: str | None = None) -> str:
    """Display value. Changes carry a sign; survey readings use one decimal."""
    kind = kind or measure_kind(obs)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if number != number:
        return "—"
    if kind == "pct_change":
        return f"{number:+.2f}%"
    if kind in {"diffusion", "index", "balance"}:
        return f"{number:.1f}"
    return format_macro_value(number, obs.get("units"), obs.get("transformation"))


def delta_text(latest: float, previous: float, kind: str) -> str:
    """Latest minus prior, in the unit a desk would quote for this measure."""
    diff = latest - previous
    if kind in {"pct_change", "rate"}:
        return f"{diff:+.2f} pp"
    if kind == "count_change":
        return f"{diff:+,.2f}k"
    if kind in {"diffusion", "index", "balance"}:
        return f"{diff:+.1f} pts"
    if previous == 0:
        return ""
    return f"{(latest / previous - 1.0) * 100.0:+.2f}%"


def _subject(obs: Mapping[str, Any], kind: str) -> str:
    subject = plain_series_name(obs).split(" · ")[0].strip()
    if kind == "count_change":
        subject = re.sub(r"(?i)\s*(?:monthly|quarterly)?\s*change$", "", subject).strip() or subject
    return subject


def _series_points(obs: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Committed history of the card's own source series, oldest first."""
    points = [dict(p) for p in (obs.get("history") or []) if isinstance(p, Mapping) and p.get("value") is not None]
    series = str(obs.get("series_id") or "")
    if any(p.get("series_id") for p in points):
        points = [p for p in points if not p.get("series_id") or p.get("series_id") == series]
    latest_period = str(obs.get("reference_period") or "")
    if obs.get("value") is not None and latest_period:
        for point in points:
            if point.get("reference_period") == latest_period:
                point["value"] = obs["value"]
                break
        else:
            points.append({"reference_period": latest_period, "value": obs["value"]})
    if obs.get("release_date") and points and points[-1].get("reference_period") == latest_period:
        points[-1].setdefault("release_date", obs.get("release_date"))
    points.sort(key=lambda p: period_key(str(p.get("reference_period") or "")))
    return points


def _revision_note(status: str) -> str:
    return {
        "preliminary": "Preliminary",
        "flash": "Flash estimate",
        "revised": "Revised",
    }.get(status, "")


def indicator_view(obs: Mapping[str, Any]) -> dict[str, Any]:
    """Facts shared by all three card surfaces for one observation."""
    kind = measure_kind(obs)
    period = str(obs.get("reference_period") or "")
    cadence = str(obs.get("cadence") or _cadence_of(period))
    points = _series_points(obs)
    released = credible_release_dates(points)
    want = HISTORY_POINTS.get(cadence, DEFAULT_HISTORY_POINTS)
    chart_points = points[-want:]

    prints: list[dict[str, Any]] = []
    for point in reversed(points[-3:]):
        p_period = str(point.get("reference_period") or "")
        day = released.get(p_period)
        first = point.get("revised_from")
        prints.append(
            {
                "period": p_period,
                "period_label": period_label(p_period),
                "value": float(point["value"]),
                "value_text": value_text(point["value"], obs, kind),
                "released": day_label(day) if day else "",
                "revised_from_text": value_text(first, obs, kind) if first is not None else "",
            }
        )

    latest = prints[0] if prints and prints[0]["period"] == period else None
    previous = prints[1] if latest and len(prints) > 1 else None
    delta = ""
    if latest and previous:
        delta = delta_text(latest["value"], previous["value"], kind)

    release_day = released.get(period)
    limitations: list[str] = []
    if not release_day:
        limitations.append(
            "The official release date is not recorded for this print; the source link has the publisher's calendar."
        )
    if len(points) < want:
        limitations.append(
            f"Only {len(points)} {_unit_word(cadence, len(points))} of this series "
            f"{'is' if len(points) == 1 else 'are'} committed; "
            f"the chart would normally show {want}."
        )

    companions = [str(s) for s in obs.get("companion_series") or []]
    if companions:
        count = len(companions)
        limitations.append(
            f"This card shows one published series; {count} other "
            f"{'series is' if count == 1 else 'series are'} stored under the same indicator and not shown here."
        )

    revision = _revision_note(str(obs.get("revision_status") or "").lower())
    return {
        "kind": kind,
        "pmi": is_pmi(obs),
        "name": plain_series_name(obs),
        "subject": _subject(obs, kind),
        "mark": transformation_mark(str(obs.get("transformation") or "")),
        "period": period,
        "period_label": period_label(period),
        "cadence": cadence,
        "value_text": value_text(obs.get("value"), obs, kind),
        "release_day": release_day,
        "release_text": f"Released {day_label(release_day)}" if release_day else "Release date not recorded",
        "revision": revision,
        "prints": prints,
        "latest": latest,
        "previous": previous,
        "delta_text": delta,
        "chart_points": chart_points,
        "limitations": limitations,
        "publisher": str(obs.get("publisher") or "Source"),
        "source_url": str(obs.get("source_url") or ""),
    }


def _direction_word(diff: float) -> str:
    return "up" if diff > 0 else "down"


def headline(
    obs: Mapping[str, Any],
    view: Mapping[str, Any] | None = None,
    prior_value: float | None = None,
) -> str:
    """One plain sentence on what the latest print says, in its own measure.

    ``prior_value`` stands in for the previous print when committed history
    is too short to carry one; it has no period of its own.
    """
    view = view or indicator_view(obs)
    latest, previous = view["latest"], view["previous"]
    subject, kind, when = view["subject"], view["kind"], view["period_label"]
    if latest is None:
        return f"{subject}: no value in {when}." if when else f"{subject}: no value."
    value = latest["value"]
    if previous is None and prior_value is not None:
        previous = {
            "value": float(prior_value),
            "value_text": value_text(prior_value, obs, kind),
            "period_label": "the prior print",
            "undated": True,
        }
    prior = f" in {previous['period_label']}" if previous and not previous.get("undated") else ""
    if kind == "pct_change":
        mark = f" {view['mark']}" if view["mark"] else ""
        name = f"{plain_series_name(obs)} {obs.get('label') or ''}".lower()
        if _names_price_index(name):
            text = f"{subject} was {value:.2f}%{mark} in {when}"
            if previous:
                diff = value - previous["value"]
                text += (
                    f", unchanged from {previous['period_label']}"
                    if abs(diff) < 0.005
                    else f", {_direction_word(diff)} from {previous['value']:.2f}%{prior}"
                )
            return text + "."
        if abs(value) < 0.005:
            text = f"{subject} was flat{mark} in {when}"
        else:
            verb = "rose" if value > 0 else "fell"
            text = f"{subject} {verb} {abs(value):.2f}%{mark} in {when}"
        if previous:
            text += f", after {previous['value_text']}{prior}"
        return text + "."
    if kind == "count_change":
        if abs(value) < 1e-9:
            text = f"{subject} was unchanged in {when}"
        else:
            verb = "rose" if value > 0 else "fell"
            text = f"{subject} {verb} {latest['value_text'].lstrip('+-')} in {when}"
        if previous:
            text += f", after {previous['value_text']}{prior}"
        return text + "."
    if kind == "rate":
        text = f"{subject} was {value:.2f}% in {when}"
        if previous:
            diff = value - previous["value"]
            text += (
                f", unchanged from {previous['period_label']}"
                if abs(diff) < 0.005
                else f", {_direction_word(diff)} {abs(diff):.2f} pp from {previous['period_label']}"
            )
        return text + "."
    if kind == "diffusion":
        side = "above" if value > 50 else "below" if value < 50 else "at"
        meaning = {
            "above": "more respondents report increases than decreases",
            "below": "more respondents report decreases than increases",
            "at": "as many respondents report increases as decreases",
        }[side]
        text = f"{subject} was {value:.1f} in {when}, {side} the 50 no-change line: {meaning}"
        if previous:
            diff = value - previous["value"]
            if abs(diff) >= 0.05:
                text += f"; {_direction_word(diff)} {abs(diff):.1f} pts from {previous['period_label']}"
            else:
                text += f"; unchanged from {previous['period_label']}"
        return text + "."
    if kind in {"index", "balance"}:
        text = f"{subject} was {value:.1f} in {when}"
        if previous:
            diff = value - previous["value"]
            text += (
                f", unchanged from {previous['period_label']}"
                if abs(diff) < 0.05
                else f", {_direction_word(diff)} {abs(diff):.1f} pts from {previous['period_label']}"
            )
        return text + "."
    text = f"{subject} was {latest['value_text']} in {when}"
    if previous and previous["value"]:
        change = (value / previous["value"] - 1.0) * 100.0
        text += f", {change:+.2f}% from {previous['period_label']}"
    return text + "."


def _print_sign(transformation: str) -> bool:
    from scripts.country_detail.policy import uses_print_sign

    return uses_print_sign(transformation)


def rationale(finding: Mapping[str, Any], obs: Mapping[str, Any]) -> str:
    """Why the attention rules picked this print, without detector codes."""
    pattern = str(finding.get("travel_pattern") or "")
    run = int(finding.get("travel_run_length") or 0)
    direction = int(finding.get("travel_direction") or 0)
    cadence = str(obs.get("cadence") or _cadence_of(str(obs.get("reference_period") or "")))
    periods = _unit_word(cadence, run)
    by_print = _print_sign(str(obs.get("transformation") or finding.get("transformation") or ""))
    if direction == 0 and by_print and obs.get("value") is not None:
        try:
            direction = 1 if float(obs["value"]) > 0 else -1 if float(obs["value"]) < 0 else 0
        except (TypeError, ValueError):
            direction = 0
    up = direction > 0
    # Period changes (m/m, q/q, net hires) read by the sign of the print;
    # rates, y/y and levels read by the change from the prior print.
    if pattern == "reversal" and by_print:
        return f"Reversal: {'an increase' if up else 'a decline'} after {run} straight {periods} of {'declines' if up else 'increases'}."
    if pattern == "reversal":
        return f"Reversal: turned {'higher' if up else 'lower'} after {run} straight {'falls' if up else 'rises'}."
    if pattern == "acceleration" and by_print:
        return f"Acceleration: a bigger {'increase' if up else 'decline'} than the {_unit_word(cadence, 1)} before."
    if pattern == "acceleration":
        return f"Acceleration: the {'rise' if up else 'fall'} picked up pace."
    if pattern == "deceleration" and by_print:
        moves = "increases" if up else "declines"
        try:
            flat = abs(float(obs.get("value"))) < 1e-9
        except (TypeError, ValueError):
            flat = False
        if flat:
            return f"Slowdown: flat after {run} straight {periods} of {moves}."
        return (
            f"Slowdown: a much smaller {'increase' if up else 'decline'} than the "
            f"{_unit_word(cadence, 1)} before; {run} straight {periods} of {moves}."
        )
    if pattern == "deceleration":
        return f"Slowdown: still {'rising' if up else 'falling'}, but by much less than before."
    if pattern == "persistence" and by_print:
        return f"Persistence: {run} straight {periods} of {'increases' if up else 'declines'}."
    if pattern == "persistence":
        return f"Persistence: {run} straight {'rises' if up else 'falls'}."
    if pattern == "range_break":
        return "Range break: the print is outside its recent range."
    status = str(finding.get("attention_status") or "")
    percentile = finding.get("percentile")
    if status in {"notable", "outlier"} and percentile is not None:
        rank = float(percentile)
        side = "high" if rank >= 50 else "low"
        return f"Unusually {side} against its own history (percentile {rank:.0f})."
    return str(finding.get("badge_text") or "Selected by the attention rules.")


def score_usage(
    obs: Mapping[str, Any],
    country_code: str,
    score_state: Mapping[str, Any],
    window: Mapping[str, Any] | None,
    view: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """What the stored score actually used from this series, and how it differs from the latest print."""
    located = _component_state(obs, country_code, score_state)
    if located is None or not obs.get("score_input"):
        return None
    dimension, _spec, state = located
    view = view or indicator_view(obs)
    if not state.get("observed"):
        return {"dimension": dimension, "observed": False}
    as_of = str(state.get("as_of") or "")
    used = state.get("transform_value")
    contribution = point_contribution(obs, country_code, score_state)
    kind = view["kind"]
    used_text = value_text(used, obs, kind) if used is not None else "—"
    window_text = ""
    if window and window.get("verified"):
        window_text = describe_window(window, obs, kind)
    released = credible_release_dates(_series_points(obs)).get(as_of)
    same_value = used is not None and obs.get("value") is not None and abs(float(used) - float(obs["value"])) < 0.005
    scored_series = list((window or {}).get("series_ids") or [])
    other_series = bool(scored_series) and str(obs.get("series_id") or "") not in scored_series
    return {
        "dimension": dimension,
        "observed": True,
        "as_of": as_of,
        "as_of_label": period_label(as_of),
        "used_text": used_text,
        "window_text": window_text,
        "other_series": other_series,
        "scored_series": scored_series,
        "same_as_latest": same_value and as_of == view["period"] and not other_series,
        "behind_latest": bool(as_of) and period_key(as_of) < period_key(view["period"]),
        "released_text": f"released {day_label(released)}" if released else "release date not recorded",
        "contribution": contribution,
    }


def describe_window(window: Mapping[str, Any], obs: Mapping[str, Any], kind: str) -> str:
    periods = list(window.get("periods") or [])
    values = list(window.get("values") or [])
    if not periods:
        return ""
    transform = str(window.get("transform") or "")
    cadence = _cadence_of(periods[-1])
    span = period_span(periods[0], periods[-1])
    listed = ", ".join(value_text(v, obs, kind) for v in values)
    n = len(periods)
    if transform == "identity":
        text = f"the {period_label(periods[-1])} print"
    elif transform in {"trailing_mean_n2", "trailing_mean_n3", "mom_mean_n3"}:
        text = f"average of {n} {_unit_word(cadence, n)}, {span}: {listed}"
    elif transform == "mom_sa_compound_annualized_n3":
        text = f"{n}-month annualised rate, {span} (m/m {listed})"
    elif transform == "qoq_to_saar":
        text = f"{period_label(periods[-1])} q/q {listed} at an annual rate"
    elif transform == "mean_qoq_to_saar_n2":
        text = f"average of {span} q/q, each at an annual rate ({listed})"
    else:
        text = f"{span}"
    if int(window.get("series_count") or 1) > 1:
        text += f"; each period is the mean of {int(window['series_count'])} published measures"
    if window.get("short_window"):
        text += " (shorter window: not enough consecutive periods)"
    return text


def score_windows(
    calibration: Mapping[str, Any],
    histories: Mapping[str, Any],
    score_state: Mapping[str, Any],
) -> dict[str, dict[str, dict[str, Any]]]:
    """Window of committed periods behind each stored component value.

    The window is shown only when replaying the calibrated transform over it
    reproduces the stored ``transform_value``; otherwise only the stored value
    is shown. Stored scores are never replaced.
    """
    from scripts.temperature_level import (
        _n_periods_for_transform,
        _transform_name,
        consecutive_tail,
        raw_values_by_period,
        transform_at_period,
    )

    cutoff = str(score_state.get("scoring_cutoff") or "")
    components = calibration.get("components") or {}
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for country, dims in (score_state.get("countries") or {}).items():
        history = histories.get(country)
        bucket: dict[str, dict[str, Any]] = {}
        for dimension, dim_state in (dims or {}).items():
            if not isinstance(dim_state, Mapping):
                continue
            for name, state in (dim_state.get("component_state") or {}).items():
                key = f"{dimension}.{name}"
                spec = components.get(f"{country}.{key}") or {}
                if not state.get("observed"):
                    bucket[key] = {"observed": False, "note": str(spec.get("note") or "")}
                    continue
                as_of = str(state.get("as_of") or "")
                if not history or not spec or not cutoff or not as_of:
                    continue
                try:
                    values = raw_values_by_period(history, spec, cutoff)
                    transform = _transform_name(spec, "level")
                    tail = consecutive_tail(values, as_of, _n_periods_for_transform(transform, spec))
                    replay = transform_at_period(values, as_of, spec, role="level")
                except (KeyError, ValueError):
                    continue
                stored = state.get("transform_value")
                verified = replay is not None and stored is not None and abs(round(replay, 4) - float(stored)) < 1e-4
                series_ids = list(spec.get("series_ids") or ([spec["series_id"]] if spec.get("series_id") else []))
                bucket[key] = {
                    "observed": True,
                    "transform": transform,
                    "periods": [p for p, _ in tail],
                    "values": [v for _, v in tail],
                    "series_ids": series_ids,
                    "series_count": len(spec.get("series_ids") or []) or 1,
                    "short_window": bool(state.get("short_window")),
                    "verified": verified,
                }
        out[country] = bucket
    return out


def contribution_sum_text(
    country_code: str,
    dimension: str,
    score_state: Mapping[str, Any],
    labels: Mapping[str, str],
    notes: Mapping[str, str] | None = None,
) -> tuple[str, list[str]]:
    """Exact reconciliation of a stored level: 50 plus each observed component's points.

    Returns an empty sentence when the stored figures do not reconcile.
    """
    countries = score_state.get("countries") or {}
    spec = (countries.get(country_code) or {}).get(dimension) if countries else score_state.get(dimension)
    if not isinstance(spec, Mapping) or spec.get("level") is None:
        return "", []
    coverage = spec.get("coverage")
    states = spec.get("component_state") or {}
    try:
        baseline = float(score_state.get("baseline_score", 50.0))
        coverage_f = float(coverage)
    except (TypeError, ValueError):
        return "", []
    if coverage_f <= 0:
        return "", []
    parts: list[str] = []
    total = baseline
    missing: list[str] = []
    for name, state in states.items():
        label = labels.get(name, name.replace("_", " "))
        if not state.get("observed") or state.get("level") is None:
            weight = float(state.get("weight") or 0.0)
            note = (notes or {}).get(name) or ""
            reason = f" {note.rstrip('.')}." if note else ""
            missing.append(f"{label} is not scored and its {weight:.0%} weight is left out.{reason}")
            continue
        points = float(state["weight"]) / coverage_f * (float(state["level"]) - baseline)
        total += points
        parts.append(f"{points:+.2f} {label.lower()}")
    level = float(spec["level"])
    if not parts or abs(total - level) > 0.06:
        return "", missing
    joined = " ".join(parts)
    text = f"{level:.2f} = {baseline:.0f} {joined}"
    if missing:
        text += f" (coverage {coverage_f:.0%})"
    return text, missing
