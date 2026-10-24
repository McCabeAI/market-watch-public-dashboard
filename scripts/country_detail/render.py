"""Country Detail HTML renderer (UI worker). Templates and formatting only."""

from __future__ import annotations

import html
import re
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from scripts.country_detail.policy import (
    ATTENTION_BADGE_TEXT,
    DATA_STATE_LABELS,
    DIMENSION_TOPIC,
    EVIDENCE_BLOCK_CONTEXT_CLASS,
    GEOGRAPHY_ALBERTA,
    HARD_SCORE_INPUTS_TITLE,
    LINEAGE_ANCHOR_PHRASE,
    SCORE_DETAIL_CLASS_ATTRIBUTE,
    SCORE_DIMENSIONS,
    TOPIC_IDS,
    TRANSFORMATION_LABELS,
    WMN_QUIET_TEXT,
)
from scripts.country_detail.present import (
    bucket_label,
    format_macro_value,
    history_limitation,
    plain_series_name,
    point_contribution,
    score_print_text,
    series_synopsis,
    why_it_surfaced,
)
from scripts.temperature_level import display_score, temperature_class

_CSS_PATH = Path(__file__).resolve().parent / "country_detail.css"

_DIRECTION_LABELS = {"cooling": "cooling", "static": "static", "warming": "warming"}
_DIRECTION_ARROW = {"cooling": "↓", "static": "→", "warming": "↑"}

_MONTHS = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()
_MONTHS_TITLE = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()

_COMPONENT_NAMES = {
    "core_pce": "Core PCE",
    "headline": "Headline",
    "underlying": "Underlying",
    "unemployment": "Unemployment",
    "wages": "Wages",
    "payrolls": "Payrolls",
    "employment": "Employment",
    "gdp_domestic_demand": "Domestic demand",
    "services_surveys": "Services surveys",
    "manufacturing_surveys": "Manufacturing surveys",
    "business_surveys": "Business surveys",
    "retail": "Retail",
    "income": "Income",
    "spending": "Spending",
    "confidence": "Confidence",
}


def country_detail_css() -> str:
    return _CSS_PATH.read_text(encoding="utf-8")


def _esc(text: Any) -> str:
    if text is None:
        return ""
    return html.escape(str(text), quote=True)


def _format_period(period: str | None) -> str:
    if not period:
        return ""
    text = str(period)
    if re.fullmatch(r"\d{4}-Q[1-4]", text):
        return text.upper()
    if len(text) == 7 and text[4] == "-":
        year, month = text.split("-")
        return f"{_MONTHS[int(month) - 1]} {year}"
    return text


def _transformation_label(transformation: str | None) -> str:
    if not transformation:
        return ""
    return str(TRANSFORMATION_LABELS.get(transformation, transformation.replace("_", " ")))


def _format_value(value: Any, units: str | None, transformation: str | None = None) -> str:
    return format_macro_value(value, units, transformation)


def _seasonal_text(obs: Mapping[str, Any]) -> str:
    transformation = str(obs.get("transformation") or "")
    if transformation == "calendar_day_rate":
        return "not seasonal adjustment (calendar-day rate)"
    sa = obs.get("seasonal_adjustment")
    if sa is True:
        return "seasonally adjusted"
    if sa is False:
        return "not seasonally adjusted"
    return "seasonal adjustment unknown"


def _geography_label(geography: str | None) -> str | None:
    if geography == GEOGRAPHY_ALBERTA:
        return "Alberta"
    return None


def _obs_by_id(observations: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(o["observation_id"]): o for o in observations if o.get("observation_id")}


def _dimension_spec(score_state: Mapping[str, Any], country_code: str, dimension: str) -> dict[str, Any]:
    if "countries" in score_state:
        bucket = score_state.get("countries") or {}
        country_bucket = bucket.get(country_code) or {}
        spec = country_bucket.get(dimension)
        return dict(spec) if spec else {}
    spec = score_state.get(dimension)
    return dict(spec) if spec else {}


def _pretty_vintage(text: str) -> str:
    monthly = re.fullmatch(r"(\d{4})-(\d{2})", str(text).strip())
    if monthly:
        month = int(monthly.group(2))
        if 1 <= month <= 12:
            return f"{_MONTHS_TITLE[month - 1]} {monthly.group(1)}"
    quarterly = re.fullmatch(r"(\d{4})-Q([1-4])", str(text).strip())
    if quarterly:
        return f"{quarterly.group(1)} Q{quarterly.group(2)}"
    daily = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", str(text).strip())
    if daily:
        month = int(daily.group(2))
        if 1 <= month <= 12:
            return f"{int(daily.group(3))} {_MONTHS_TITLE[month - 1]} {daily.group(1)}"
    return str(text)


def _component_label(key: str) -> str:
    return _COMPONENT_NAMES.get(key, str(key).replace("_", " "))


def _vintage_line(spec: Mapping[str, Any]) -> str:
    """Input vintage from component_state as_of. Empty when the score state has none."""
    components = spec.get("component_state")
    if not isinstance(components, Mapping):
        return ""
    items: list[tuple[str, str]] = []
    for key, state in components.items():
        if not isinstance(state, Mapping):
            continue
        if state.get("observed") is False:
            continue
        as_of = state.get("as_of")
        if not as_of:
            continue
        items.append((_component_label(str(key)), _pretty_vintage(str(as_of))))
    if not items:
        return ""
    if len(items) == 1:
        name, period = items[0]
        return f"{name} through {period}"
    periods = {period for _, period in items}
    if len(periods) == 1:
        return f"Inputs through {items[0][1]}"
    return " · ".join(f"{name} through {period}" for name, period in items)


def _impulse_markup(spec: Mapping[str, Any]) -> str:
    direction = str(spec.get("direction") or "static").lower()
    if direction not in _DIRECTION_LABELS:
        direction = "static"
    impulse = spec.get("impulse")
    number = "n/a" if impulse is None else f"{float(impulse):+.2f}"
    return (
        f'<span class="imp imp-{_esc(direction)}">{_esc(_DIRECTION_ARROW[direction])} '
        f"{_esc(_DIRECTION_LABELS[direction])} {_esc(number)}</span>"
        '<span class="mw-asof">vs prior print</span>'
    )


def _score_header(score_state: Mapping[str, Any]) -> str:
    if not isinstance(score_state, Mapping):
        line = "Score dates not published in this view"
    elif score_state.get("score_inputs_last_ingested_at") or score_state.get("calibration_anchor_date"):
        from scripts.dashboard_repair.score_dates import header_score_line

        line = header_score_line(score_state)
    elif score_state.get("as_of"):
        line = f"Calibration anchor {_pretty_vintage(str(score_state['as_of']))}"
    else:
        line = "Score dates not published in this view"
    legend = (
        "LEVEL is the 1–100 score, where 50 is the structural/policy neutral point. "
        "IMPULSE is the latest print versus the prior print, in score points."
    )
    return (
        '<header class="cd-head">'
        f'<span class="mw-asof" data-score-dates>{_esc(line)}</span>'
        f'<p class="cd-legend">{_esc(legend)}</p>'
        "</header>"
    )


def _score_level_parts(spec: Mapping[str, Any]) -> tuple[str, str, str]:
    level = spec.get("level")
    if level is None:
        return "—", "neutral", "0"
    level_f = float(level)
    klass = str(spec.get("temperature_class") or temperature_class(level_f) or "neutral")
    score_text = display_score(level_f)
    width_text = display_score(max(1.0, min(100.0, level_f)))
    return score_text, klass, width_text


def _data_state_markup(data_state: str | None, display_label: str | None = None) -> str:
    if not data_state or data_state == "ok":
        return ""
    label = display_label or DATA_STATE_LABELS.get(data_state)
    if not label:
        return ""
    return f'<span class="evidence-data-state">{_esc(label)}</span>'


def _member_for_observation(
    members: list[Mapping[str, Any]], observation_id: str
) -> Mapping[str, Any] | None:
    for member in members:
        if str(member.get("observation_id")) == observation_id:
            return member
    return None


def _member_ineligibility(
    members: list[Mapping[str, Any]], observation_id: str
) -> list[str]:
    member = _member_for_observation(members, observation_id)
    if member is None:
        return []
    return list(member.get("ineligibility") or [])


def _resolved_data_state(
    obs: Mapping[str, Any], members: list[Mapping[str, Any]]
) -> tuple[str, str | None]:
    """Use the attention member's state for this observation_id.

    Stale is classified on the member. The projection row can still say ``ok``.
    When no member matches, the projection state and label are the fallback.
    """
    member = _member_for_observation(members, str(obs.get("observation_id") or ""))
    if member is not None and member.get("data_state"):
        state = str(member.get("data_state") or "ok")
        label = member.get("display_label") or DATA_STATE_LABELS.get(state)
    else:
        state = str(obs.get("data_state") or "ok")
        label = obs.get("display_label") or DATA_STATE_LABELS.get(state)
    if state == "ok":
        return "ok", None
    return state, label


def _history_limitation_text(reasons: list[str]) -> tuple[str, str] | None:
    return history_limitation(reasons)


def _related_obs_text(
    related_ids: list[str], obs_map: dict[str, Mapping[str, Any]]
) -> str:
    if not related_ids:
        return ""
    parts: list[str] = []
    for rid in related_ids:
        obs = obs_map.get(rid)
        if obs:
            parts.append(plain_series_name(obs))
        else:
            parts.append("a related series")
    return "; ".join(parts)


def _empty_evidence_line(country_code: str) -> str:
    lines = {
        "US": "United States Country Evidence has no projection rows in this view.",
        "CA": "Canada Country Evidence has no projection rows in this view.",
        "AU": "Australia Country Evidence has no projection rows in this view.",
        "NZ": "New Zealand Country Evidence has no projection rows in this view.",
        "EA": "Euro area Country Evidence has no projection rows in this fixture.",
        "JP": "Japan Country Evidence has no projection rows in this fixture.",
    }
    return lines.get(country_code, f"{country_code} Country Evidence has no projection rows.")


def _render_score_compact(country_code: str, score_state: Mapping[str, Any]) -> str:
    parts: list[str] = ['<div class="score-compact">']
    for dimension in SCORE_DIMENSIONS:
        spec = _dimension_spec(score_state, country_code, dimension)
        level_text, klass, width_text = _score_level_parts(spec)
        class_word = "" if spec.get("level") is None else str(spec.get("temperature_class") or klass)
        vintage = _vintage_line(spec)
        vintage_html = f'<span class="cd-vintage mw-asof">{_esc(vintage)}</span>' if vintage else ""
        anchor = f"#cd-{_esc(country_code)}-{_esc(dimension)}"
        parts.append(
            f'<a class="score-compact-btn" href="{anchor}">'
            f'<span class="scd-dim mw-label">{_esc(dimension)}</span>'
            '<span class="scd-level"><span class="mw-label">Level</span> '
            f'<span class="mw-num">{_esc(level_text)}</span><span class="scd-scale">/100</span> '
            f'<span class="scd-class">{_esc(class_word)}</span></span>'
            f'<span class="lvl-track" aria-hidden="true"><span class="lvl-bar" data-temp="{_esc(klass)}" style="width:{_esc(width_text)}%"></span></span>'
            f'<span class="scd-impulse"><span class="mw-label">Impulse</span> {_impulse_markup(spec)}</span>'
            f"{vintage_html}"
            "</a>"
        )
    parts.append("</div>")
    return "".join(parts)


def _render_wmn(
    attention_country: Mapping[str, Any],
    obs_map: dict[str, Mapping[str, Any]],
) -> str:
    finding_count = int(attention_country.get("finding_count") or 0)
    findings = list(attention_country.get("findings") or [])
    parts = ['<section class="what-matters-now"><h2>What Matters Now</h2>']
    if finding_count == 0 or not findings:
        why = _quiet_explanation(attention_country.get("review"))
        why_html = f' <span class="wmn-quiet-why">{_esc(why)}</span>' if why else ""
        parts.append(f'<p class="wmn-quiet">{_esc(WMN_QUIET_TEXT)}{why_html}</p>')
    else:
        parts.append('<ol class="wmn-list">')
        for finding in findings:
            oid = str(finding["observation_id"])
            status = str(finding["attention_status"])
            badge = finding.get("badge_text") or ATTENTION_BADGE_TEXT.get(status, "")
            parts.append(
                f'<article class="wmn-finding" id="ev-{_esc(oid)}" '
                f'data-observation-id="{_esc(oid)}" '
                f'data-attention="{_esc(status)}">'
            )
            if badge:
                parts.append(f'<span class="wmn-badge">{_esc(badge)}</span>')
            obs = obs_map.get(oid) or finding
            geo = _geography_label(finding.get("geography") or obs.get("geography"))
            if geo:
                parts.append(f'<p class="wmn-geo">{_esc(geo)}</p>')
            parts.append(f'<h3 class="wmn-series">{_esc(plain_series_name(obs))}</h3>')
            value_s = _format_value(obs.get("value"), obs.get("units"), obs.get("transformation"))
            period = _format_period(obs.get("reference_period") or finding.get("reference_period"))
            value_bits = " · ".join(bit for bit in (value_s, period) if bit)
            parts.append(f'<p class="wmn-value mw-num">{_esc(value_bits)}</p>')
            parts.append(f'<p class="wmn-bucket">{_esc(bucket_label(obs))}</p>')
            parts.append(f'<p class="wmn-why">{_esc(why_it_surfaced(finding, obs))}</p>')
            parts.append(f'<p class="wmn-synopsis">{_esc(series_synopsis(obs))}</p>')
            related = list(finding.get("related_observation_ids") or [])
            rel_text = _related_obs_text(related, obs_map)
            if rel_text:
                parts.append(
                    f'<p class="wmn-related">Related: {_esc(rel_text)}</p>'
                )
            parts.append('<details class="wmn-technical"><summary>Technical detail</summary>')
            official = str(obs.get("label") or "")
            if official:
                parts.append(f'<p class="wmn-official">Official title: {_esc(official)}</p>')
            parts.append(f'<p class="wmn-reason">{_esc(finding.get("reason", ""))}</p>')
            parts.append(
                f'<p class="wmn-headline">{_esc(finding.get("headline_text", ""))}</p>'
            )
            series_id = obs.get("series_id") or finding.get("series_id")
            if series_id:
                parts.append(f'<p class="evidence-code mw-raw">{_esc(series_id)}</p>')
            raw_transformation = obs.get("transformation") or finding.get("transformation")
            if raw_transformation:
                parts.append(f'<p class="evidence-code mw-raw">{_esc(raw_transformation)}</p>')
            parts.append("</details></article>")
        parts.append("</ol>")
    parts.append("</section>")
    return "".join(parts)


def _quiet_explanation(review: Mapping[str, Any] | None) -> str:
    """Say why a country is quiet after its own evidence was evaluated."""
    if not isinstance(review, Mapping):
        return ""
    evaluated = int(review.get("evaluated_count") or 0)
    eligible = int(review.get("eligible_count") or 0)
    due = int(review.get("due_late_count") or 0)
    superseded = int(review.get("superseded_count") or 0)
    if evaluated == 0:
        return "No observations were available to review."
    if eligible == 0 and due:
        return (
            f"{evaluated} observations were reviewed. "
            f"{due} are due or late because a newer release should exist, "
            "not because a short number of days passed since the last print."
        )
    if eligible == 0 and superseded and not due:
        return (
            f"{evaluated} observations were reviewed. "
            f"{superseded} are superseded by a newer official observation."
        )
    return (
        f"{eligible} of {evaluated} observations were eligible latest evidence "
        "and none qualified."
    )


def _search_text(obs: Mapping[str, Any], *, label: str, value_s: str, period: str, geo_label: str) -> str:
    bits = [
        label,
        series_synopsis(obs),
        str(obs.get("topic") or ""),
        period,
        str(obs.get("publisher") or ""),
        geo_label,
        value_s,
        bucket_label(obs),
        str(obs.get("reference_period") or ""),
    ]
    return " ".join(bit for bit in bits if bit)


def _render_evidence_row(
    obs: Mapping[str, Any],
    members: list[Mapping[str, Any]],
) -> str:
    oid = str(obs["observation_id"])
    topic = str(obs.get("topic") or "other")
    label = plain_series_name(obs)
    value_s = _format_value(obs.get("value"), obs.get("units"), obs.get("transformation"))
    period = _format_period(obs.get("reference_period"))
    geo_label = _geography_label(obs.get("geography"))
    data_state, display_label = _resolved_data_state(obs, members)
    state_html = _data_state_markup(data_state, display_label)
    source_url = obs.get("source_url") or "#"
    publisher = obs.get("publisher") or "Source"
    retrieved = obs.get("retrieved_at") or ""

    meta_parts = [_esc(value_s), _esc(period) if period else "", _esc(bucket_label(obs))]
    if geo_label:
        meta_parts.append(_esc(geo_label))
    meta_line = " · ".join(p for p in meta_parts if p)
    if state_html:
        meta_line = f"{state_html} · {meta_line}" if meta_line else state_html

    history = list(obs.get("history") or [])
    reasons = _member_ineligibility(members, oid)
    limitation = _history_limitation_text(reasons)

    search = _search_text(obs, label=label, value_s=value_s, period=period or "", geo_label=geo_label)
    parts = [
        f'<article class="evidence-item" data-observation-id="{_esc(oid)}" '
        f'data-topic="{_esc(topic)}" data-search="{_esc(search)}">',
        '<details class="evidence-details">',
        "<summary>",
        f'<div class="evidence-item-header">{_esc(label)}</div>',
        f'<div class="evidence-item-meta">{meta_line}</div>',
        "</summary>",
        '<div class="evidence-technical">',
        f'<p class="evidence-synopsis">{_esc(series_synopsis(obs))}</p>',
    ]
    official = str(obs.get("label") or "")
    if official:
        parts.append(f'<p class="wmn-official">Official title: {_esc(official)}</p>')
    series_id = obs.get("series_id")
    if series_id:
        parts.append(f'<p class="evidence-code mw-raw">Series {_esc(series_id)}</p>')
    raw_transformation = obs.get("transformation")
    if raw_transformation:
        parts.append(
            f'<p class="evidence-code">Transform {_esc(raw_transformation)}'
            f" · {_esc(_transformation_label(str(raw_transformation)))}</p>"
        )
    parts.append(f'<p class="evidence-code">{_esc(_seasonal_text(obs))}</p>')
    if obs.get("geography") and not geo_label:
        parts.append(f'<p class="evidence-code">Geography {_esc(obs.get("geography"))}</p>')
    if data_state == "failed_fetch" and retrieved:
        parts.append(f'<p class="evidence-code">Retrieved {_esc(retrieved)}</p>')
    parts.append(
        f'<a href="{_esc(str(source_url))}" rel="noopener noreferrer">{_esc(publisher)}</a>'
    )
    parts.append('<details class="history-drill"><summary>History</summary>')
    if history:
        parts.append('<table class="history-table"><thead><tr><th>Period</th><th>Value</th></tr></thead><tbody>')
        for point in history:
            parts.append(
                "<tr><td>"
                f'{_esc(_format_period(point.get("reference_period") or point.get("period")))}'
                f"</td><td>{_esc(_format_value(point.get('value'), obs.get('units'), obs.get('transformation')))}</td></tr>"
            )
        parts.append("</tbody></table>")
    elif limitation:
        prose, code = limitation
        parts.append(f'<p class="history-limitation">{_esc(prose)}</p>')
        parts.append(f'<p class="evidence-code">{_esc(code)}</p>')
    else:
        parts.append('<p class="history-limitation">No history points in projection.</p>')
    parts.append("</details></div></details></article>")
    return "".join(parts)


def _wmn_observation_ids(attention_country: Mapping[str, Any]) -> set[str]:
    return {
        str(finding.get("observation_id"))
        for finding in (attention_country.get("findings") or [])
        if finding.get("observation_id")
    }


def _render_country_evidence(
    country_code: str,
    observations: list[Mapping[str, Any]],
    members: list[Mapping[str, Any]],
    *,
    shown_ids: set[str] | None = None,
) -> str:
    """Remaining evidence. Observations already on a What Matters Now card are omitted."""
    remaining = [
        obs
        for obs in observations
        if str(obs.get("observation_id")) not in (shown_ids or set())
    ]
    parts = [
        '<section class="country-evidence">',
        '<details class="country-evidence-fold">',
        "<summary><h2>Remaining Country Evidence</h2></summary>",
        '<div class="evidence-toolbar">',
        '<input type="search" class="evidence-search" aria-label="Search country evidence" '
        'placeholder="Search evidence" autocomplete="off">',
    ]
    parts.append(
        '<button type="button" class="topic-btn" data-topic="all" aria-pressed="true">All</button>'
    )
    for topic_id in TOPIC_IDS:
        parts.append(
            f'<button type="button" class="topic-btn" data-topic="{_esc(topic_id)}" aria-pressed="false">'
            f"{_esc(topic_id.replace('_', ' '))}</button>"
        )
    parts.append('</div><div class="evidence-list">')
    parts.append(
        '<p class="evidence-filter-empty" hidden>No evidence matches this search or topic.</p>'
    )
    if not remaining:
        if observations and shown_ids:
            parts.append(
                '<p class="evidence-empty">Every observation in this view is already on a What Matters Now card.</p>'
            )
        else:
            parts.append(f'<p class="evidence-empty">{_esc(_empty_evidence_line(country_code))}</p>')
    else:
        for obs in remaining:
            parts.append(_render_evidence_row(obs, members))
    parts.append("</div></details></section>")
    return "".join(parts)


def _audit_row(
    obs: Mapping[str, Any],
    country_code: str,
    score_state: Mapping[str, Any],
    link_only: bool = False,
    state_markup: str = "",
) -> str:
    oid = str(obs["observation_id"])
    label = plain_series_name(obs)
    if link_only:
        lead = f"<strong>{_esc(label)}</strong>"
        if state_markup:
            lead = f"{lead} {state_markup}"
        official = str(obs.get("label") or "")
        series_id = obs.get("series_id")
        technical_bits = []
        if official:
            technical_bits.append(f"<p>Official title: {_esc(official)}</p>")
        if series_id:
            technical_bits.append(f'<p class="evidence-code mw-raw">Series {_esc(series_id)}</p>')
        raw_transformation = obs.get("transformation")
        if raw_transformation:
            technical_bits.append(f'<p class="evidence-code mw-raw">{_esc(raw_transformation)}</p>')
        technical = ""
        if technical_bits:
            technical = (
                '<details class="score-input-technical"><summary>Technical detail</summary>'
                + "".join(technical_bits)
                + "</details>"
            )
        return (
            f'<div class="evidence-grid-row" data-observation-id="{_esc(oid)}">'
            f"{lead} — "
            f'<a href="#ev-{_esc(oid)}">Country Evidence</a>'
            f"{technical}"
            "</div>"
        )
    period = _format_period(obs.get("reference_period"))
    contribution = point_contribution(obs, country_code, score_state)
    value_s = score_print_text(obs, contribution)
    points = ""
    technical = ""
    if contribution:
        points = f' <span class="score-points">{_esc(contribution["text"])}</span>'
        level_text = f"{float(contribution['level']):.2f}"
        weight_text = f"{float(contribution['weight']):.2f}"
        technical = (
            '<details class="score-input-technical"><summary>Score detail</summary>'
            f'<p class="evidence-code">Component level {_esc(level_text)}'
            f" · weight {_esc(weight_text)}"
            " · points versus the neutral 50 anchor.</p></details>"
        )
    return (
        f'<div class="evidence-grid-row" id="ev-{_esc(oid)}" data-observation-id="{_esc(oid)}">'
        f"<strong>{_esc(label)}</strong> · {_esc(value_s)}"
        f"{(' · ' + _esc(period)) if period else ''}"
        f"{points}{technical}"
        "</div>"
    )


def _fmt_employment_value(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{number:.2f}"


def _fmt_thousands_delta(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if number == int(number):
        return f"{int(number):,}"
    return f"{number:,.1f}"


def _render_post_print_accounting_line(accounting: Mapping[str, Any]) -> str:
    keys = (
        "delta_unemployed",
        "delta_labor_force",
        "delta_household_employment",
        "labor_force_absorption",
    )
    if not any(accounting.get(key) is not None for key in keys):
        return ""
    parts: list[str] = []
    if accounting.get("delta_unemployed") is not None:
        parts.append(f"unemployment change {_fmt_thousands_delta(accounting['delta_unemployed'])} (thousands)")
    if accounting.get("delta_labor_force") is not None:
        parts.append(f"labor force {_fmt_thousands_delta(accounting['delta_labor_force'])}")
    if accounting.get("delta_household_employment") is not None:
        parts.append(f"household employment {_fmt_thousands_delta(accounting['delta_household_employment'])}")
    if accounting.get("labor_force_absorption") is not None:
        parts.append(f"absorption {_fmt_thousands_delta(accounting['labor_force_absorption'])}")
    if accounting.get("identity_residual") is not None:
        parts.append(f"identity residual {_fmt_thousands_delta(accounting['identity_residual'])}")
    detail = "; ".join(parts)
    return (
        '<p class="evidence-code">Accounting: the change in unemployment equals labor-force change '
        "minus household-employment change"
        f" ({detail}). Diagnostic channels are not an additive decomposition.</p>"
    )


def _render_us_employment_context(block: Mapping[str, Any]) -> str:
    sections = block.get("sections") or {}
    if not isinstance(sections, Mapping):
        return ""
    order = (
        ("forecast", "Forecast"),
        ("current_flows", "Current labor-market flows"),
        ("labor_supply_regime", "Labor-supply regime"),
        ("corroboration", "Corroborating data"),
        ("post_print_attribution", "Post-print attribution"),
    )
    parts: list[str] = [
        '<div class="evidence-block us-employment-context" data-employment-context="us">',
        '<div class="evidence-title">US employment context</div>',
        '<p class="evidence-code">Context only. Weight 0. Does not change the calibrated US Labor score.</p>',
    ]
    for key, title in order:
        raw = sections.get(key)
        rows: list[Mapping[str, Any]]
        cause = ""
        if key == "post_print_attribution" and isinstance(raw, Mapping):
            rows = list(raw.get("metrics") or [])
            accounting = raw.get("accounting")
            if isinstance(accounting, Mapping):
                cause = _render_post_print_accounting_line(accounting)
        elif isinstance(raw, list):
            rows = raw
        else:
            rows = []
        rendered = []
        for row in rows:
            if row.get("status") == "license_gap":
                rendered.append(
                    f'<div class="evidence-grid-row">{_esc(row.get("name"))}: license gap. {_esc(row.get("error") or "")}</div>'
                )
                continue
            if row.get("status") != "observed":
                continue
            value = _fmt_employment_value(row.get("value"))
            period = str(row.get("period") or "")
            rendered.append(
                f'<div class="evidence-grid-row"><strong>{_esc(row.get("name"))}</strong>'
                f'{(" · " + _esc(value)) if value else ""}'
                f'{(" · " + _esc(period)) if period else ""}</div>'
            )
        body = "".join(rendered) or '<div class="evidence-grid-row">No observations in this section yet.</div>'
        parts.append(
            f'<div class="evidence-block" data-employment-section="{_esc(key)}">'
            f'<div class="evidence-title">{_esc(title)}</div>'
            f'<div class="evidence-grid">{cause}{body}</div></div>'
        )
    parts.append("</div>")
    return "".join(parts)


_PRIMA_CHANNEL_LABELS = {
    "shock_persistence": "Shock persistence",
    "production_network_pressure": "Production network pressure",
    "imported_pressure": "Imported pressure",
    "consumer_price_breadth": "Consumer price breadth",
    "demand_pass_through_constraint": "Demand pass-through constraint",
}
_PRIMA_CATEGORIES = ("RISING", "STABLE", "FALLING")
# Oil context is claimed only when a stored line names one of these products.
# "ex-energy" and a bare "oil curve" freshness label do not match.
_PRIMA_OIL_TOKEN = re.compile(
    r"(?i)(?<![A-Za-z])(?:brent|wti|crude|rbob|ulsd|heating oil|gasoline|natural gas)(?![A-Za-z])"
)


def _prima_day(observed_at: str) -> str:
    text = observed_at.strip()
    match = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    return match.group(1) if match else text


def _prima_last_transition(transitions: list[Any]) -> Mapping[str, Any] | None:
    for item in reversed(transitions):
        if isinstance(item, Mapping):
            return item
    return None


def _prima_vs_previous(direction: str, transitions: list[Any]) -> tuple[str, str]:
    """Glance phrase and a stable kind. Kinds are not magnitudes."""
    if direction not in _PRIMA_CATEGORIES:
        return "Stored direction unavailable", "unavailable"
    last = _prima_last_transition(transitions)
    if last is None:
        return "No previous stored observation", "no-previous"
    previous = str(last.get("from_direction") or "")
    current = str(last.get("to_direction") or "")
    label = str(last.get("label") or "").strip()
    if previous in _PRIMA_CATEGORIES and current == direction and previous == current:
        return "Unchanged vs previous stored observation", "unchanged"
    if previous in _PRIMA_CATEGORIES and current == direction and previous != current:
        return f"Changed vs previous stored observation ({previous} → {current})", "changed"
    if label:
        return f"Latest stored transition: {label}", "recorded"
    return "Previous stored observation is on file", "recorded"


def _prima_oil_hits(drivers: list[str], change_text: str) -> tuple[list[str], bool]:
    hits = [item for item in drivers if _PRIMA_OIL_TOKEN.search(item)]
    mpr_names_oil = bool(
        change_text
        and change_text.lower() != "unavailable"
        and _PRIMA_OIL_TOKEN.search(change_text)
    )
    return hits, mpr_names_oil


def _prima_means_sentences(
    *,
    direction: str,
    subs: Mapping[str, Any],
    transitions: list[Any],
    trend: list[Any],
    drivers: list[str],
    change_text: str,
    staleness: str | None,
    stale: bool,
    mpr_status: Any,
    conditioning_date: Any,
    vs_phrase: str,
) -> list[str]:
    """Plain sentences from stored proxy fields. No score and no new oil math."""
    sentences: list[str] = [
        (
            "This is the Market Watch deterministic proxy, not the Bank of Canada's Prima model. "
            "It does not feed the Inflation score."
        )
    ]
    if direction in _PRIMA_CATEGORIES:
        sentences.append(f"Current stored direction is {direction}.")
    else:
        sentences.append("Current stored direction is unavailable.")
    sentences.append(vs_phrase + ".")
    sentences.append(
        "The aggregate signal is a direction category. No numeric Prima score or magnitude is stored."
    )

    stored = [point for point in trend if isinstance(point, Mapping)]
    if not stored:
        sentences.append("No stored observation is on file.")
    elif len(stored) == 1:
        sentences.append(
            "One stored observation is on file, so there is no transition to a previous observation."
        )
    else:
        sentences.append(
            f"{len(stored)} stored observations are on file. "
            "Transitions compare consecutive stored runs only."
        )

    last = _prima_last_transition(transitions)
    if last is not None:
        label = str(last.get("label") or "").strip()
        if not label:
            label = (
                f"{last.get('from_direction') or 'UNAVAILABLE'} → "
                f"{last.get('to_direction') or 'UNAVAILABLE'}"
            )
        sentences.append(
            "Latest stored transition: "
            f"{label} ({last.get('from_observed_at') or ''} → {last.get('to_observed_at') or ''})."
        )

    if direction in _PRIMA_CATEGORIES:
        matching: list[str] = []
        differing: list[str] = []
        missing: list[str] = []
        for key, label in _PRIMA_CHANNEL_LABELS.items():
            channel_direction = str(subs.get(key) or "UNAVAILABLE")
            if channel_direction == direction:
                matching.append(label)
            elif channel_direction in _PRIMA_CATEGORIES:
                differing.append(f"{label} {channel_direction}")
            else:
                missing.append(label)
        if matching:
            sentences.append(
                "Channels stored in the current direction: " + ", ".join(matching) + "."
            )
        else:
            sentences.append("No stored channel is in the current direction.")
        if differing:
            sentences.append("Other stored channel directions: " + "; ".join(differing) + ".")
        if missing:
            sentences.append(
                "Channels without a stored direction: " + ", ".join(missing) + "."
            )
    else:
        sentences.append(
            "There is no aggregate direction to match. Channel directions are listed below."
        )

    imported = str(subs.get("imported_pressure") or "UNAVAILABLE")
    sentences.append(f"Imported pressure is stored as {imported}.")

    oil_drivers, mpr_names_oil = _prima_oil_hits(drivers, change_text)
    if oil_drivers:
        sentences.append(
            "Oil context in stored driver lines: "
            + "; ".join(oil_drivers)
            + ". Quoted as stored. This view does not add an oil weight, contribution, or forecast."
        )
        if mpr_names_oil:
            sentences.append(
                "The stored last-MPR comparison also names Brent, WTI, crude, or a listed oil product. "
                "It is quoted below and is not recomputed. No oil contribution is shown beyond that stored text."
            )
    elif mpr_names_oil:
        sentences.append(
            "No stored driver line names Brent, WTI, crude, or a listed oil product. "
            "The stored last-MPR comparison does. It is quoted below and is not recomputed. "
            "No oil contribution is shown."
        )
    else:
        sentences.append(
            "No stored driver line or last-MPR comparison names Brent, WTI, crude, or a listed oil product. "
            "No oil contribution is shown."
        )

    if staleness:
        sentences.append(f"Staleness as stored: {staleness}.")
    else:
        sentences.append("Staleness is not recorded.")
    sentences.append(
        "This observation is marked stale." if stale else "This observation is not marked stale."
    )

    if not change_text or change_text.lower() == "unavailable":
        sentences.append("The comparison versus the last BoC MPR is unavailable.")
    else:
        bits: list[str] = []
        if mpr_status is not None and str(mpr_status).strip():
            bits.append(f"MPR status {mpr_status}")
        if conditioning_date:
            bits.append(f"conditioning date {conditioning_date}")
        suffix = f" ({', '.join(bits)})" if bits else ""
        sentences.append(
            "A stored comparison versus the last BoC MPR is on file"
            + suffix
            + ". The wording below is quoted as stored and is not recomputed here."
        )
    return sentences


def _render_prima_pressure(block: Mapping[str, Any] | None) -> str:
    if not isinstance(block, Mapping):
        block = {
            "current": {
                "direction": "UNAVAILABLE",
                "subcomponent_directions": {
                    ch: "UNAVAILABLE" for ch in _PRIMA_CHANNEL_LABELS
                },
                "confidence": None,
                "coverage": None,
                "staleness": None,
                "status": "unavailable",
                "reason": "no_persisted_prima_observation",
                "mpr_status": "unavailable",
                "conditioning_date": None,
                "change_since_last_mpr": None,
                "disclaimer": (
                    "Deterministic Market Watch proxy for observable oil-curve persistence and "
                    "inflation-propagation channels. It is not a reconstruction or reproduction "
                    "of the Bank of Canada's proprietary Prima model."
                ),
                "largest_drivers": [],
                "stale": False,
            },
            "history_state": "none",
            "history_note": (
                "History begins here: no stored Market Watch Prima observations have been recorded yet."
            ),
            "trend": [],
            "transitions": [],
        }

    current = block.get("current") if isinstance(block.get("current"), Mapping) else {}
    direction = str(current.get("direction") or "UNAVAILABLE")
    subs = current.get("subcomponent_directions")
    if not isinstance(subs, Mapping):
        subs = {}

    coverage = current.get("coverage")
    if isinstance(coverage, (int, float)) and not isinstance(coverage, bool):
        coverage_text = f"Coverage {float(coverage):.2f}"
    else:
        coverage_text = "Coverage unavailable"

    confidence = current.get("confidence")
    if confidence is not None and str(confidence).strip():
        confidence_text = f"confidence {str(confidence).strip()}"
    else:
        confidence_text = "confidence unavailable"

    stale = bool(current.get("stale"))
    status = str(current.get("status") or "").strip().lower()
    reason = str(current.get("reason") or "").strip()
    status_bits: list[str] = []
    if status:
        status_bits.append(f"Signal status: {_esc(status)}.")
    if reason:
        status_bits.append(_esc(reason) + ".")

    aggregate_available = direction in _PRIMA_CATEGORIES
    partial_channels = [
        label
        for key, label in _PRIMA_CHANNEL_LABELS.items()
        if aggregate_available and str(subs.get(key) or "UNAVAILABLE") == "UNAVAILABLE"
    ]
    if partial_channels:
        status_bits.append(
            "Partial channel coverage: "
            + ", ".join(partial_channels)
            + " unavailable."
        )

    driver_values = current.get("largest_drivers")
    drivers = (
        [str(item).strip() for item in driver_values if str(item).strip()]
        if isinstance(driver_values, list)
        else []
    )
    if drivers:
        driver_items = "".join(f"<li>{_esc(item)}</li>" for item in drivers)
        driver_html = (
            '<div class="prima-kicker">Largest drivers</div>'
            f'<ul class="prima-drivers">{driver_items}</ul>'
        )
    else:
        driver_html = (
            '<div class="prima-kicker">Largest drivers</div>'
            '<p class="prima-meta">No stored driver lines.</p>'
        )

    history_note = str(block.get("history_note") or "")
    trend = block.get("trend") if isinstance(block.get("trend"), list) else []
    transitions = block.get("transitions") if isinstance(block.get("transitions"), list) else []
    vs_phrase, vs_kind = _prima_vs_previous(direction, transitions)

    timeline_steps: list[str] = []
    for point in trend:
        if not isinstance(point, Mapping):
            continue
        at = str(point.get("observed_at") or "")
        dir_word = str(point.get("direction") or "UNAVAILABLE")
        staleness_point = str(point.get("staleness") or "").strip()
        note = (
            f'<span class="prima-step-note">{_esc(staleness_point)}</span>'
            if staleness_point
            else ""
        )
        timeline_steps.append(
            f'<li class="prima-step" data-prima-step-direction="{_esc(dir_word)}">'
            f'<span class="prima-step-dir">{_esc(dir_word)}</span>'
            f'<time datetime="{_esc(at)}">{_esc(_prima_day(at))}</time>'
            f"{note}</li>"
        )
    if timeline_steps:
        timeline_html = (
            '<div class="prima-kicker">Stored direction timeline</div>'
            '<ol class="prima-timeline">'
            + "".join(timeline_steps)
            + "</ol>"
            '<p class="prima-meta">Direction categories and dates only. Not a numeric chart.</p>'
        )
    else:
        timeline_html = (
            '<div class="prima-kicker">Stored direction timeline</div>'
            '<p class="prima-meta">No stored direction timeline. History is not fabricated.</p>'
        )

    transition_lines: list[str] = []
    for transition in transitions:
        if not isinstance(transition, Mapping):
            continue
        label = str(transition.get("label") or "")
        from_at = str(transition.get("from_observed_at") or "")
        to_at = str(transition.get("to_observed_at") or "")
        if label or from_at or to_at:
            transition_lines.append(
                f"<li>{_esc(from_at)} → {_esc(to_at)}: {_esc(label)}</li>"
            )
    if transition_lines:
        transition_html = (
            '<div class="prima-kicker">Stored transitions</div>'
            f'<ul class="prima-transitions">{"".join(transition_lines)}</ul>'
        )
    else:
        transition_html = ""

    channel_rows = []
    for channel, label in _PRIMA_CHANNEL_LABELS.items():
        ch_dir = str(subs.get(channel) or "UNAVAILABLE")
        channel_rows.append(
            f'<div class="prima-channel" data-prima-channel="{_esc(channel)}" '
            f'data-prima-channel-direction="{_esc(ch_dir)}">{_esc(label)}: {_esc(ch_dir)}</div>'
        )

    mpr_status = current.get("mpr_status")
    conditioning_date = current.get("conditioning_date")
    change_since = current.get("change_since_last_mpr")
    change_text = str(change_since or "").strip()
    if not change_text or change_text.lower() == "unavailable":
        mpr_body = "<p>The comparison versus the last BoC MPR is unavailable.</p>"
    else:
        gloss = ""
        if "brent_end_2027_vs_prose" in change_text:
            gloss = (
                '<p class="prima-meta">Stored line name: Brent end-2027 versus the MPR prose assumption. '
                "The figure below is quoted as stored.</p>"
            )
        mpr_body = gloss + f"<p>{_esc(change_text)}</p>"
    mpr_meta = []
    if conditioning_date:
        mpr_meta.append(f"Conditioning date: {_esc(conditioning_date)}")
    if mpr_status is not None and str(mpr_status).strip():
        mpr_meta.append(f"MPR status: {_esc(mpr_status)}")
    if mpr_meta:
        mpr_body = f'<p class="prima-meta">{". ".join(mpr_meta)}</p>{mpr_body}'

    staleness = current.get("staleness")
    staleness_text = str(staleness).strip() if staleness is not None and str(staleness).strip() else None
    means = _prima_means_sentences(
        direction=direction,
        subs=subs,
        transitions=transitions,
        trend=trend,
        drivers=drivers,
        change_text=change_text,
        staleness=staleness_text,
        stale=stale,
        mpr_status=mpr_status,
        conditioning_date=conditioning_date,
        vs_phrase=vs_phrase,
    )
    means_html = "".join(f"<p>{_esc(sentence)}</p>" for sentence in means)

    disclaimer = str(
        current.get("disclaimer")
        or (
            "Deterministic Market Watch proxy for observable oil-curve persistence and "
            "inflation-propagation channels. It is not a reconstruction or reproduction "
            "of the Bank of Canada's proprietary Prima model."
        )
    )

    tech_lines: list[str] = []
    history_state = str(block.get("history_state") or "")
    if history_state:
        tech_lines.append(f"history_state: {history_state}")
    for flag in ("feeds_inflation_score", "score_inputs_changed"):
        if flag not in block:
            continue
        value = block.get(flag)
        if value is True:
            rendered_flag = "true"
        elif value is False:
            rendered_flag = "false"
        else:
            rendered_flag = str(value)
        tech_lines.append(f"{flag}: {rendered_flag}")
    limitations = block.get("limitations")
    if isinstance(limitations, list) and limitations:
        tech_lines.append("limitations: " + "; ".join(str(item) for item in limitations))
    for channel, _label in _PRIMA_CHANNEL_LABELS.items():
        tech_lines.append(f"{channel} = {subs.get(channel) or 'UNAVAILABLE'}")
    for point in trend:
        if not isinstance(point, Mapping):
            continue
        bits = [
            str(point.get("observed_at") or ""),
            str(point.get("direction") or "UNAVAILABLE"),
        ]
        for field in ("status", "staleness", "source_id", "run_id", "review_id", "source_kind"):
            value = point.get(field)
            if value:
                bits.append(f"{field} {value}")
        tech_lines.append(" · ".join(bits))
    tech_html = "".join(f"<div>{_esc(line)}</div>" for line in tech_lines)

    status_html = (
        f'<div class="prima-meta">{" ".join(status_bits)}</div>' if status_bits else ""
    )
    stale_html = '<span class="prima-stale">Stale</span>' if stale else ""
    freshness = staleness_text or "staleness not recorded"

    return (
        f'<div class="evidence-block prima-pressure" data-prima-pressure="ca" data-prima-context="only">'
        f'<div class="evidence-title">Prima Pressure</div>'
        f'<div class="prima-badges">'
        f'<span class="prima-badge">Market Watch proxy</span>'
        f'<span class="prima-badge">Not the Bank of Canada Prima model</span>'
        f"</div>"
        f'<div class="prima-context-note">context only — does not feed Inflation score</div>'
        f'<div class="prima-direction" data-prima-direction="{_esc(direction)}" data-prima-vs="{_esc(vs_kind)}">'
        f'<span class="prima-direction-word">{_esc(direction)}</span>'
        f"{stale_html}"
        f'<span class="prima-vs">{_esc(vs_phrase)}</span>'
        f"</div>"
        f'<div class="prima-meta">{_esc(coverage_text)} · {_esc(confidence_text)} · {_esc(freshness)}</div>'
        f'<div class="prima-means"><div class="prima-kicker">What this shows</div>{means_html}</div>'
        f"{timeline_html}"
        f"{transition_html}"
        f'<div class="prima-history">{_esc(history_note)}</div>'
        f"{driver_html}"
        f'<div class="prima-kicker">Channel directions</div>'
        f'<div class="prima-channels">{"".join(channel_rows)}</div>'
        f'<div class="prima-mpr"><div class="prima-kicker">Versus last BoC MPR</div>{mpr_body}</div>'
        f"{status_html}"
        f'<div class="prima-meta">{_esc(disclaimer)}</div>'
        f'<details class="prima-detail"><summary>Technical detail</summary>'
        f'<div class="prima-meta">{tech_html}</div></details>'
        f"</div>"
    )


def _render_score_drilldown(
    country_code: str,
    observations: list[Mapping[str, Any]],
    score_state: Mapping[str, Any],
    members: list[Mapping[str, Any]],
    employment_context: Mapping[str, Any] | None = None,
    prima_pressure: Mapping[str, Any] | None = None,
) -> str:
    obs_by_topic: dict[str, list[Mapping[str, Any]]] = {t: [] for t in TOPIC_IDS}
    for obs in observations:
        topic = str(obs.get("topic") or "other")
        obs_by_topic.setdefault(topic, []).append(obs)

    parts: list[str] = []
    for dimension in SCORE_DIMENSIONS:
        spec = _dimension_spec(score_state, country_code, dimension)
        score_text, klass, width_text = _score_level_parts(spec)
        topic = DIMENSION_TOPIC[dimension]
        topic_obs = obs_by_topic.get(topic, [])

        scored = [o for o in topic_obs if o.get("score_role") == "scored"]
        scoring = [o for o in scored if o.get("score_input")]
        hard = scoring or scored
        hard_ids = {str(o.get("observation_id")) for o in hard}
        context = [
            o
            for o in topic_obs
            if str(o.get("observation_id")) not in hard_ids
            and o.get("score_role") in ("context", "unscored", "scored")
        ]

        hard_rows = "".join(
            _audit_row(o, country_code, score_state) for o in hard
        ) or (
            '<div class="evidence-grid-row">No scored inputs for this dimension in projection.</div>'
        )
        ctx_rows = "".join(
            _audit_row(
                o,
                country_code,
                score_state,
                link_only=True,
                state_markup=_data_state_markup(*_resolved_data_state(o, members)),
            )
            for o in context
        )
        if not ctx_rows:
            ctx_rows = '<div class="evidence-grid-row">No context rows for this topic.</div>'

        detail_id = f"cd-{country_code}-{dimension}"
        vintage = _vintage_line(spec)
        class_word = "" if spec.get("level") is None else str(spec.get("temperature_class") or klass)
        vintage_html = f'<div class="score-hint mw-asof">{_esc(vintage)}</div>' if vintage else ""
        impulse_html = (
            '<div class="score-impulse"><span class="mw-label">Impulse</span>'
            f"{_impulse_markup(spec)}</div>"
        )
        lineage = (
            f"<div class=\"lineage-note\"><b>Score lineage:</b> {LINEAGE_ANCHOR_PHRASE}. "
            "LEVEL is the stored calibrated score. Impulse is separate from attention.</div>"
        )

        prima_html = ""
        if country_code == "CA" and dimension == "Inflation":
            prima_html = _render_prima_pressure(prima_pressure)

        parts.append(
            f'<details class="{SCORE_DETAIL_CLASS_ATTRIBUTE}" id="{_esc(detail_id)}">'
            f'<summary class="score-summary">'
            f'<div class="score-top"><b>{_esc(dimension)}</b>'
            f'<span class="score-level-block"><span class="mw-label">Level</span> '
            f'<span class="score-num mw-num">{_esc(score_text)}</span><span class="scd-scale">/100</span> '
            f'<span class="scd-class">{_esc(class_word)}</span></span></div>'
            f'<div class="temp-bar"><i class="{_esc(klass)}" style="width:{_esc(width_text)}%"></i></div>'
            f"{impulse_html}"
            f"{vintage_html}"
            f"</summary>"
            f'<div class="score-evidence">'
            f'<div class="evidence-block">'
            f'<div class="evidence-title">{_esc(HARD_SCORE_INPUTS_TITLE)}</div>'
            f'<div class="evidence-grid">{hard_rows}</div>'
            f"{lineage}"
            f"</div>"
            f"{prima_html}"
            f'<div class="{EVIDENCE_BLOCK_CONTEXT_CLASS}">'
            f'<div class="evidence-title">Context / corroboration</div>'
            f'<div class="evidence-grid">{ctx_rows}</div>'
            f"</div>"
            f"{_render_us_employment_context(employment_context) if dimension == 'Labor' and employment_context else ''}"
            f"</div></details>"
        )
    return "".join(parts)


def render_country_detail(
    country_code: str,
    projection_country: Mapping[str, Any],
    attention_country: Mapping[str, Any],
    score_state: Mapping[str, Any],
) -> str:
    """Render the Country Detail fragment for one economy."""
    code = str(country_code)
    observations = list(projection_country.get("observations") or [])
    obs_map = _obs_by_id(observations)
    members = list(attention_country.get("members") or [])

    chunks = [
        f'<section class="country-detail" data-country="{_esc(code)}">',
        _score_header(score_state),
        _render_score_compact(code, score_state),
        _render_wmn(attention_country, obs_map),
        _render_score_drilldown(
            code,
            observations,
            score_state,
            members,
            employment_context=projection_country.get("employment_context")
            if isinstance(projection_country, Mapping)
            else None,
            prima_pressure=projection_country.get("prima_pressure")
            if isinstance(projection_country, Mapping)
            else None,
        ),
        _render_country_evidence(
            code,
            observations,
            members,
            shown_ids=_wmn_observation_ids(attention_country),
        ),
        "</section>",
    ]
    return "".join(chunks)


def _preview_fixtures() -> dict[str, dict[str, Any]]:
    """Synthetic fixtures for browser preview (not production data)."""
    au_headline_id = "au_fixture_tty_outlier_001"
    au_monthly_id = "au_fixture_mom_related_002"
    ab_oil_id = "ca_fixture_ab_oil_003"

    au_obs = [
        {
            "observation_id": au_headline_id,
            "label": "Household spending through-the-year",
            "value": 7,
            "units": "percent",
            "transformation": "yoy_pct",
            "topic": "consumer",
            "geography": "AU",
            "seasonal_adjustment": True,
            "data_state": "ok",
            "source_url": "https://example.invalid/au/mhsi",
            "reference_period": "2024-07",
            "history": [{"reference_period": "2024-06", "value": 6.2}],
            "score_role": "unscored",
            "weight": 0,
            "publisher": "ABS fixture",
            "retrieved_at": "2024-08-01T00:00:00Z",
            "nominal_basis": "nominal",
            "series_id": "FIXTURE_MHSI_TTY",
        },
        {
            "observation_id": au_monthly_id,
            "label": "Household spending monthly change",
            "value": 0.4,
            "units": "percent",
            "transformation": "mom_pct",
            "topic": "consumer",
            "geography": "AU",
            "seasonal_adjustment": True,
            "data_state": "ok",
            "source_url": "https://example.invalid/au/mhsi-mom",
            "reference_period": "2024-07",
            "history": [],
            "score_role": "scored",
            "weight": 0.25,
            "publisher": "ABS fixture",
            "retrieved_at": "2024-08-01T00:00:00Z",
            "nominal_basis": "nominal",
            "series_id": "A130200586W",
        },
        {
            "observation_id": ab_oil_id,
            "label": "Alberta crude bitumen production",
            "value": 1200,
            "units": "cubic metres per calendar day",
            "transformation": "calendar_day_rate",
            "topic": "energy_physical",
            "geography": "AB",
            "seasonal_adjustment": False,
            "data_state": "ok",
            "source_url": "https://example.invalid/ca/aer-st3",
            "reference_period": "2024-01",
            "history": [{"reference_period": "2023-12", "value": 1180}],
            "score_role": "unscored",
            "weight": 0,
            "publisher": "AER fixture",
            "retrieved_at": "2024-02-01T00:00:00Z",
            "nominal_basis": "physical",
            "series_id": "AER_ST3_FIXTURE",
        },
    ]

    au_attention = {
        "finding_count": 1,
        "findings": [
            {
                "observation_id": au_headline_id,
                "attention_status": "outlier",
                "badge_text": "Outlier",
                "reason": "Through-the-year percent ranks above the outlier band on a 60-month sample.",
                "headline_text": "fixture annual 7 — through-the-year percent change",
                "related_observation_ids": [au_monthly_id],
                "geography": "AU",
            }
        ],
        "members": [],
    }

    au_scores = {
        "Inflation": {"level": 62, "impulse": 1.2, "direction": "warming", "temperature_class": "warm"},
        "Labor": {"level": 48, "impulse": 0, "direction": "static", "temperature_class": "neutral"},
        "Activity": {"level": 55, "impulse": -0.5, "direction": "cooling", "temperature_class": "neutral"},
        "Consumer": {"level": 71, "impulse": 2.1, "direction": "warming", "temperature_class": "warm"},
    }

    nz_obs = [
        {
            "observation_id": "nz_fixture_cpi_001",
            "label": "Consumers price index",
            "value": 2.2,
            "units": "percent",
            "transformation": "yoy_pct",
            "topic": "inflation",
            "geography": "NZ",
            "seasonal_adjustment": None,
            "data_state": "ok",
            "source_url": "https://example.invalid/nz/cpi",
            "reference_period": "2024-Q2",
            "history": [{"reference_period": "2024-Q1", "value": 2.1}],
            "score_role": "scored",
            "weight": 0.4,
            "publisher": "Stats NZ fixture",
            "retrieved_at": "2024-07-15T00:00:00Z",
            "nominal_basis": "nominal",
            "series_id": "NZ_CPI_FIXTURE",
        },
    ]
    nz_attention = {"finding_count": 0, "findings": [], "members": []}
    nz_scores = {
        "Inflation": {"level": 52, "impulse": 0.1, "direction": "static", "temperature_class": "neutral"},
        "Labor": {"level": 44, "impulse": -0.2, "direction": "cooling", "temperature_class": "cool"},
        "Activity": {"level": 50, "impulse": 0, "direction": "static", "temperature_class": "neutral"},
        "Consumer": {"level": 47, "impulse": 0, "direction": "static", "temperature_class": "neutral"},
    }

    ca_degraded_obs = [
        {
            "observation_id": "ca_fixture_missing",
            "label": "Retail trade volume",
            "value": None,
            "units": "percent",
            "transformation": "mom_pct",
            "topic": "consumer",
            "geography": "CA",
            "seasonal_adjustment": True,
            "data_state": "missing",
            "source_url": "https://example.invalid/ca/retail",
            "reference_period": "2024-06",
            "history": [],
            "score_role": "context",
            "weight": 0,
            "publisher": "StatCan fixture",
            "retrieved_at": "2024-07-01T00:00:00Z",
            "nominal_basis": "real",
            "series_id": "CA_RETAIL_FIX",
        },
        {
            "observation_id": "ca_fixture_stale",
            "label": "GDP monthly",
            "value": 0.1,
            "units": "percent",
            "transformation": "mom_pct",
            "topic": "activity",
            "geography": "CA",
            "seasonal_adjustment": True,
            "data_state": "stale",
            "source_url": "https://example.invalid/ca/gdp",
            "reference_period": "2024-04",
            "history": [],
            "score_role": "scored",
            "weight": 0.3,
            "publisher": "StatCan fixture",
            "retrieved_at": "2024-04-20T00:00:00Z",
            "nominal_basis": "real",
            "series_id": "CA_GDP_FIX",
        },
        {
            "observation_id": "ca_fixture_revised",
            "label": "Employment change",
            "value": -12,
            "units": "thousands",
            "transformation": "monthly_level",
            "topic": "labor",
            "geography": "CA",
            "seasonal_adjustment": True,
            "data_state": "revised",
            "source_url": "https://example.invalid/ca/emp",
            "reference_period": "2024-06",
            "history": [{"reference_period": "2024-05", "value": 20}],
            "score_role": "scored",
            "weight": 0.2,
            "publisher": "StatCan fixture",
            "retrieved_at": "2024-07-05T00:00:00Z",
            "nominal_basis": "nominal",
            "series_id": "CA_EMP_FIX",
        },
        {
            "observation_id": "ca_fixture_noncomp",
            "label": "Oil production benchmark",
            "value": 5.1,
            "units": "percent",
            "transformation": "mom_pct",
            "topic": "energy_physical",
            "geography": "CA",
            "seasonal_adjustment": False,
            "data_state": "structurally_non_comparable",
            "source_url": "https://example.invalid/ca/oil",
            "reference_period": "2024-06",
            "history": [],
            "score_role": "unscored",
            "weight": 0,
            "publisher": "NEB fixture",
            "retrieved_at": "2024-06-30T00:00:00Z",
            "nominal_basis": "physical",
            "series_id": "CA_OIL_FIX",
        },
        {
            "observation_id": "ca_fixture_failed",
            "label": "Building permits",
            "value": None,
            "units": "index",
            "transformation": "monthly_level",
            "topic": "housing",
            "geography": "CA",
            "seasonal_adjustment": True,
            "data_state": "failed_fetch",
            "source_url": "https://example.invalid/ca/permits",
            "reference_period": "2024-06",
            "history": [],
            "score_role": "context",
            "weight": 0,
            "publisher": "StatCan fixture",
            "retrieved_at": "2024-05-01T00:00:00Z",
            "nominal_basis": "index",
            "series_id": "CA_PERM_FIX",
        },
    ]
    ca_attention = {"finding_count": 0, "findings": [], "members": []}
    ca_scores = {
        "Inflation": {"level": 55, "impulse": 0, "direction": "static", "temperature_class": "neutral"},
        "Labor": {"level": 38, "impulse": -1, "direction": "cooling", "temperature_class": "cool"},
        "Activity": {"level": 42, "impulse": 0.5, "direction": "warming", "temperature_class": "cool"},
        "Consumer": {"level": None, "impulse": None, "direction": "static", "temperature_class": "neutral"},
    }

    us_obs = [
        {
            "observation_id": "us_fixture_pce",
            "label": "Core PCE inflation",
            "value": 0.2,
            "units": "percent",
            "transformation": "mom_pct",
            "topic": "inflation",
            "geography": "US",
            "seasonal_adjustment": True,
            "data_state": "ok",
            "source_url": "https://example.invalid/us/pce",
            "reference_period": "2024-07",
            "history": [],
            "score_role": "scored",
            "weight": 1.0,
            "publisher": "BEA fixture",
            "retrieved_at": "2024-08-30T00:00:00Z",
            "nominal_basis": "nominal",
            "series_id": "US_PCE_FIX",
        },
    ]
    us_attention = {"finding_count": 0, "findings": [], "members": []}
    us_scores = {
        "Inflation": {"level": 72, "impulse": 1.5, "direction": "warming", "temperature_class": "warm"},
        "Labor": {"level": 75, "impulse": 0.8, "direction": "warming", "temperature_class": "warm"},
        "Activity": {"level": 69, "impulse": 0.3, "direction": "static", "temperature_class": "warm"},
        "Consumer": {"level": 74, "impulse": 1.0, "direction": "warming", "temperature_class": "warm"},
    }

    ea_obs = [
        {
            "observation_id": "ea_fixture_hicp",
            "label": "Euro area HICP flash estimate",
            "value": 2.4,
            "units": "percent",
            "transformation": "yoy_pct",
            "topic": "inflation",
            "geography": "EA",
            "seasonal_adjustment": None,
            "data_state": "ok",
            "source_url": "https://example.invalid/ea/hicp",
            "reference_period": "2024-08",
            "history": [{"reference_period": "2024-07", "value": 2.6}],
            "score_role": "scored",
            "weight": 0.5,
            "publisher": "Eurostat fixture",
            "retrieved_at": "2024-08-31T00:00:00Z",
            "nominal_basis": "nominal",
            "series_id": "EA_HICP_FIX",
        },
    ]
    ea_attention = {"finding_count": 0, "findings": [], "members": []}
    ea_scores = {
        "Inflation": {"level": 58, "impulse": -0.4, "direction": "cooling", "temperature_class": "neutral"},
        "Labor": {"level": 51, "impulse": 0, "direction": "static", "temperature_class": "neutral"},
        "Activity": {"level": 46, "impulse": -0.3, "direction": "cooling", "temperature_class": "neutral"},
        "Consumer": {"level": 49, "impulse": 0.1, "direction": "static", "temperature_class": "neutral"},
    }

    jp_obs = [
        {
            "observation_id": "jp_fixture_cpi",
            "label": "Japan nationwide CPI ex fresh food",
            "value": 2.7,
            "units": "percent",
            "transformation": "yoy_pct",
            "topic": "inflation",
            "geography": "JP",
            "seasonal_adjustment": None,
            "data_state": "ok",
            "source_url": "https://example.invalid/jp/cpi",
            "reference_period": "2024-07",
            "history": [{"reference_period": "2024-06", "value": 2.8}],
            "score_role": "scored",
            "weight": 0.6,
            "publisher": "e-Stat fixture",
            "retrieved_at": "2024-08-25T00:00:00Z",
            "nominal_basis": "nominal",
            "series_id": "JP_CPI_FIX",
        },
    ]
    jp_attention = {"finding_count": 0, "findings": [], "members": []}
    jp_scores = {
        "Inflation": {"level": 64, "impulse": 0.6, "direction": "warming", "temperature_class": "warm"},
        "Labor": {"level": 53, "impulse": 0.2, "direction": "static", "temperature_class": "neutral"},
        "Activity": {"level": 45, "impulse": -0.1, "direction": "static", "temperature_class": "neutral"},
        "Consumer": {"level": 41, "impulse": -0.5, "direction": "cooling", "temperature_class": "cool"},
    }

    return {
        "populated": ("AU", {"code": "AU", "observations": au_obs}, au_attention, au_scores),
        "quiet": ("NZ", {"code": "NZ", "observations": nz_obs}, nz_attention, nz_scores),
        "degraded": ("CA", {"code": "CA", "observations": ca_degraded_obs}, ca_attention, ca_scores),
        "US": ("US", {"code": "US", "observations": us_obs}, us_attention, us_scores),
        "CA": ("CA", {"code": "CA", "observations": ca_degraded_obs}, ca_attention, ca_scores),
        "AU": ("AU", {"code": "AU", "observations": au_obs}, au_attention, au_scores),
        "NZ": ("NZ", {"code": "NZ", "observations": nz_obs}, nz_attention, nz_scores),
        "EA": ("EA", {"code": "EA", "observations": ea_obs}, ea_attention, ea_scores),
        "JP": ("JP", {"code": "JP", "observations": jp_obs}, jp_attention, jp_scores),
    }


def evidence_filter_script() -> str:
    """Production search and topic controls. No network and no runtime model calls."""
    return """
(function () {
  function wire(root) {
    if (!root || root.getAttribute('data-evidence-wired') === '1') return;
    var search = root.querySelector('.evidence-search');
    var topicBtns = root.querySelectorAll('.topic-btn');
    if (!search && !topicBtns.length) return;
    root.setAttribute('data-evidence-wired', '1');
    var items = root.querySelectorAll('.evidence-item');
    var empty = root.querySelector('.evidence-filter-empty');
    var activeTopic = 'all';

    function applyFilter() {
      var q = (search && search.value || '').trim().toLowerCase();
      var visible = 0;
      items.forEach(function (el) {
        var topic = el.getAttribute('data-topic') || '';
        var hay = (el.getAttribute('data-search') || el.textContent || '').toLowerCase();
        var topicOk = activeTopic === 'all' || topic === activeTopic;
        var searchOk = !q || hay.indexOf(q) !== -1;
        var show = topicOk && searchOk;
        el.hidden = !show;
        if (show) visible += 1;
      });
      if (empty) empty.hidden = visible !== 0;
    }

    topicBtns.forEach(function (btn) {
      btn.addEventListener('click', function () {
        activeTopic = btn.getAttribute('data-topic') || 'all';
        topicBtns.forEach(function (other) {
          other.setAttribute('aria-pressed', other === btn ? 'true' : 'false');
        });
        applyFilter();
      });
    });
    if (search) {
      search.addEventListener('input', applyFilter);
      search.addEventListener('search', applyFilter);
      search.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') {
          search.value = '';
          applyFilter();
        }
      });
    }
  }

  function boot() {
    document.querySelectorAll('.country-detail').forEach(wire);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
"""


def _preview_script() -> str:
    return evidence_filter_script() + """
(function () {

  var radios = document.querySelectorAll('input[name="cd-country"]');
  var panes = document.querySelectorAll('.country-pane');
  function showCountry(code) {
    panes.forEach(function (p) {
      p.classList.toggle('is-active', p.getAttribute('data-country-pane') === code);
    });
  }
  radios.forEach(function (r) {
    r.addEventListener('change', function () {
      if (r.checked) showCountry(r.value);
    });
  });
  var checked = document.querySelector('input[name="cd-country"]:checked');
  if (checked) showCountry(checked.value);
})();
"""


def write_preview_html(path: Path | None = None) -> str:
    out = path or Path(__file__).resolve().parents[2] / "tests/fixtures/country_detail/preview.html"
    fixtures = _preview_fixtures()
    css = country_detail_css()

    review_order = [
        ("Populated", "populated"),
        ("Quiet", "quiet"),
        ("Degraded", "degraded"),
    ]
    switcher_codes = ["US", "CA", "AU", "NZ", "EA", "JP"]

    review_html: list[str] = []
    for heading, key in review_order:
        code, proj, att, scores = fixtures[key]
        fragment = render_country_detail(code, proj, att, scores)
        review_html.append(
            f'<div class="review-pane"><h2>{_esc(heading)} ({_esc(code)})</h2>{fragment}</div>'
        )

    switcher_labels = "".join(
        f'<label><input type="radio" name="cd-country" value="{c}"'
        f'{" checked" if c == "US" else ""}> {_esc(c)}</label>'
        for c in switcher_codes
    )
    country_panes: list[str] = []
    for c in switcher_codes:
        code, proj, att, scores = fixtures[c]
        fragment = render_country_detail(code, proj, att, scores)
        active = " is-active" if c == "US" else ""
        country_panes.append(
            f'<div class="country-pane{active}" data-country-pane="{_esc(c)}">{fragment}</div>'
        )

    today = date.today().isoformat()
    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Country Detail preview</title>
<style>
{css}
</style>
</head>
<body class="cdetail-preview">
<h1>Country Detail renderer preview</h1>
<p>Fixture document for browser review. Generated without network calls.</p>
{"".join(review_html)}
<h2>Country switcher</h2>
<div class="country-switcher">{switcher_labels}</div>
{"".join(country_panes)}
<script>
{_preview_script()}
</script>
<!-- generated {today} -->
</body>
</html>
"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    return doc


def _run_assertions(html_pop: str, html_quiet: str, html_degraded: str) -> list[str]:
    results: list[str] = []
    forbidden = ("hot", "warm", "cold", "cool")

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append(f"{name}: {'PASS' if ok else 'FAIL'}" + (f" ({detail})" if detail and not ok else ""))

    check(
        "populated wmn-headline",
        "wmn-headline" in html_pop and "fixture annual 7" in html_pop,
    )
    check(
        "populated shared observation id",
        "data-observation-id=\"au_fixture_tty_outlier_001\"" in html_pop
        and html_pop.count("data-observation-id=\"au_fixture_tty_outlier_001\"") >= 2,
    )
    check("quiet sentence", WMN_QUIET_TEXT in html_quiet)
    check("quiet no Outlier badge", "Outlier" not in html_quiet)
    for label in ("Missing", "Stale", "Revised", "Not comparable", "Source failed"):
        check(f"degraded contains {label}", label in html_degraded)
    check("failed_fetch timestamp", "2024-05-01" in html_degraded)
    check("no today in failed row", date.today().isoformat() not in html_degraded.split("ca_fixture_failed")[1][:400])
    for frag in (html_pop, html_quiet, html_degraded):
        check(
            "four score drill-downs",
            frag.count('class="temp-dimension score-detail"') == 4,
            frag[:40],
        )
        check("lineage phrase", LINEAGE_ANCHOR_PHRASE in frag)
    badge_zone = html_pop.split("wmn-badge")[1][:200] if "wmn-badge" in html_pop else ""
    check(
        "badges avoid temp classes",
        not any(f'class="{c}"' in badge_zone or f'class="wmn-badge {c}"' in html_pop for c in forbidden),
    )
    return results


if __name__ == "__main__":
    fixtures = _preview_fixtures()
    _, au_proj, au_att, au_sc = fixtures["populated"]
    _, nz_proj, nz_att, nz_sc = fixtures["quiet"]
    _, ca_proj, ca_att, ca_sc = fixtures["degraded"]

    pop_html = render_country_detail("AU", au_proj, au_att, au_sc)
    quiet_html = render_country_detail("NZ", nz_proj, nz_att, nz_sc)
    degraded_html = render_country_detail("CA", ca_proj, ca_att, ca_sc)

    write_preview_html()
    for line in _run_assertions(pop_html, quiet_html, degraded_html):
        print(line)
