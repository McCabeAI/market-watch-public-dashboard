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
from scripts.temperature_level import display_score, temperature_class

_CSS_PATH = Path(__file__).resolve().parent / "country_detail.css"

_DIRECTION_LABELS = {"cooling": "Cooling", "static": "Static", "warming": "Warming"}

_MONTHS = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()


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


def _format_value(value: Any, units: str | None) -> str:
    if value is None:
        return "—"
    u = (units or "").strip().lower()
    if u in ("percent", "%", "pct") or u.startswith("percent "):
        return f"{value}%"
    return f"{value} {units or ''}".strip()


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


def _impulse_line(spec: Mapping[str, Any]) -> str:
    direction = str(spec.get("direction") or "static").lower()
    label = _DIRECTION_LABELS.get(direction, direction.title())
    impulse = spec.get("impulse")
    if impulse is None:
        impulse_bit = "n/a"
    else:
        impulse_bit = display_score(float(impulse))
    return f"{label} · impulse {impulse_bit}"


def _score_level_parts(spec: Mapping[str, Any]) -> tuple[str, str, str]:
    level = spec.get("level")
    if level is None:
        return "—", "neutral", "0"
    level_f = float(level)
    klass = str(spec.get("temperature_class") or temperature_class(level_f) or "neutral")
    score_text = display_score(level_f)
    width_text = display_score(max(1.0, min(100.0, level_f)))
    return score_text, klass, width_text


def _data_state_markup(data_state: str | None) -> str:
    if not data_state or data_state == "ok":
        return ""
    label = DATA_STATE_LABELS.get(data_state)
    if not label:
        return ""
    extra = ""
    if data_state == "failed_fetch":
        # retrieved_at should appear in evidence meta from observation; label only here
        pass
    return f'<span class="evidence-data-state">{_esc(label)}</span>{extra}'


def _member_ineligibility(
    members: list[Mapping[str, Any]], observation_id: str
) -> list[str]:
    for member in members:
        if str(member.get("observation_id")) == observation_id:
            return list(member.get("ineligibility") or [])
    return []


def _history_limitation_text(reasons: list[str]) -> str | None:
    if "insufficient_history" in reasons:
        return "History table omitted: comparable sample below the notable minimum (insufficient_history)."
    if "seasonal_history_insufficient" in reasons:
        return (
            "History table omitted: seasonal peer sample below the notable minimum "
            "(seasonal_history_insufficient)."
        )
    return None


def _related_obs_text(
    related_ids: list[str], obs_map: dict[str, Mapping[str, Any]]
) -> str:
    if not related_ids:
        return ""
    parts: list[str] = []
    for rid in related_ids:
        obs = obs_map.get(rid)
        if obs:
            parts.append(f"{obs.get('label', rid)} ({rid[:8]}…)")
        else:
            parts.append(rid)
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
        level_text, _, _ = _score_level_parts(spec)
        impulse = _impulse_line(spec)
        anchor = f"#cd-{_esc(country_code)}-{_esc(dimension)}"
        parts.append(
            f'<a class="score-compact-btn" href="{anchor}">'
            f'<span class="scd-dim">{_esc(dimension)}</span>'
            f'<span class="scd-level">{_esc(level_text)}</span>'
            f'<span class="scd-impulse">{_esc(impulse)}</span>'
            f"</a>"
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
        parts.append(f'<p class="wmn-quiet">{_esc(WMN_QUIET_TEXT)}</p>')
    else:
        parts.append('<ol class="wmn-list">')
        for finding in findings:
            oid = str(finding["observation_id"])
            status = str(finding["attention_status"])
            badge = finding.get("badge_text") or ATTENTION_BADGE_TEXT.get(status, "")
            parts.append(
                f'<article class="wmn-finding" data-observation-id="{_esc(oid)}" '
                f'data-attention="{_esc(status)}">'
            )
            if badge:
                parts.append(f'<span class="wmn-badge">{_esc(badge)}</span>')
            geo = _geography_label(finding.get("geography"))
            if geo:
                parts.append(f'<p class="wmn-geo">{_esc(geo)}</p>')
            parts.append(f'<p class="wmn-reason">{_esc(finding.get("reason", ""))}</p>')
            parts.append(
                f'<p class="wmn-headline">{_esc(finding.get("headline_text", ""))}</p>'
            )
            related = list(finding.get("related_observation_ids") or [])
            rel_text = _related_obs_text(related, obs_map)
            if rel_text:
                parts.append(
                    f'<p class="wmn-related">Related observations: {_esc(rel_text)}</p>'
                )
            parts.append("</article>")
        parts.append("</ol>")
    parts.append("</section>")
    return "".join(parts)


def _render_evidence_row(
    obs: Mapping[str, Any],
    members: list[Mapping[str, Any]],
) -> str:
    oid = str(obs["observation_id"])
    topic = str(obs.get("topic") or "other")
    label = obs.get("label") or obs.get("series_id") or oid
    value_s = _format_value(obs.get("value"), obs.get("units"))
    period = _format_period(obs.get("reference_period"))
    transform = _transformation_label(str(obs.get("transformation") or ""))
    geo_bits: list[str] = []
    geo_label = _geography_label(obs.get("geography"))
    if geo_label:
        geo_bits.append(geo_label)
    elif obs.get("geography"):
        geo_bits.append(str(obs["geography"]))
    sa = _seasonal_text(obs)
    data_state = str(obs.get("data_state") or "ok")
    state_html = _data_state_markup(data_state)
    source_url = obs.get("source_url") or "#"
    publisher = obs.get("publisher") or "Source"
    retrieved = obs.get("retrieved_at") or ""

    meta_parts = [
        _esc(value_s),
        _esc(period) if period else "",
        _esc(transform) if transform else "",
    ]
    series_id = obs.get("series_id")
    if series_id:
        meta_parts.append(_esc(str(series_id)))
    raw_transformation = obs.get("transformation")
    if raw_transformation:
        meta_parts.append(_esc(str(raw_transformation)))
    if geo_bits:
        meta_parts.append(_esc(", ".join(geo_bits)))
    meta_parts.append(_esc(sa))
    meta_line = " · ".join(p for p in meta_parts if p)
    if state_html:
        meta_line = f"{state_html} · {meta_line}" if meta_line else state_html
    if data_state == "failed_fetch" and retrieved:
        meta_line = f"{meta_line} · retrieved {_esc(retrieved)}".strip(" · ")

    history = list(obs.get("history") or [])
    reasons = _member_ineligibility(members, oid)
    limitation = _history_limitation_text(reasons)

    parts = [
        f'<article class="evidence-item" data-observation-id="{_esc(oid)}" data-topic="{_esc(topic)}">',
        f'<div class="evidence-item-header">{_esc(label)}</div>',
        f'<div class="evidence-item-meta">{meta_line}</div>',
        f'<a href="{_esc(str(source_url))}" rel="noopener noreferrer">{_esc(publisher)}</a>',
        '<details class="history-drill"><summary>History</summary>',
    ]
    if history:
        parts.append('<table class="history-table"><thead><tr><th>Period</th><th>Value</th></tr></thead><tbody>')
        for point in history:
            parts.append(
                "<tr><td>"
                f'{_esc(_format_period(point.get("reference_period") or point.get("period")))}'
                f"</td><td>{_esc(_format_value(point.get('value'), obs.get('units')))}</td></tr>"
            )
        parts.append("</tbody></table>")
    elif limitation:
        parts.append(f'<p class="history-limitation">{_esc(limitation)}</p>')
    else:
        parts.append('<p class="history-limitation">No history points in projection.</p>')
    parts.append("</details></article>")
    return "".join(parts)


def _render_country_evidence(
    country_code: str,
    observations: list[Mapping[str, Any]],
    members: list[Mapping[str, Any]],
) -> str:
    parts = [
        '<section class="country-evidence"><h2>Country Evidence</h2>',
        '<div class="evidence-toolbar">',
        '<input type="search" class="evidence-search" aria-label="Search country evidence" placeholder="Search evidence">',
    ]
    parts.append(
        '<button type="button" class="topic-btn" data-topic="all" aria-pressed="true">All</button>'
    )
    for topic_id in TOPIC_IDS:
        parts.append(
            f'<button type="button" class="topic-btn" data-topic="{_esc(topic_id)}">'
            f"{_esc(topic_id.replace('_', ' '))}</button>"
        )
    parts.append('</div><div class="evidence-list">')
    if not observations:
        parts.append(f'<p class="evidence-empty">{_esc(_empty_evidence_line(country_code))}</p>')
    else:
        for obs in observations:
            parts.append(_render_evidence_row(obs, members))
    parts.append("</div></section>")
    return "".join(parts)


def _audit_row(obs: Mapping[str, Any], link_only: bool = False) -> str:
    oid = str(obs["observation_id"])
    label = obs.get("label") or obs.get("series_id") or oid
    if link_only:
        return (
            f'<div class="evidence-grid-row" data-observation-id="{_esc(oid)}">'
            f"<strong>{_esc(label)}</strong> — "
            f'see <a href="#ev-{_esc(oid)}">{_esc(oid[:12])}…</a> in Country Evidence'
            "</div>"
        )
    period = _format_period(obs.get("reference_period"))
    value_s = _format_value(obs.get("value"), obs.get("units"))
    weight = obs.get("weight")
    role = obs.get("score_role") or ""
    weight_bit = f" · weight {weight}" if weight is not None and role == "scored" else ""
    return (
        f'<div class="evidence-grid-row" id="ev-{_esc(oid)}" data-observation-id="{_esc(oid)}">'
        f"<strong>{_esc(label)}</strong> · {_esc(value_s)} · {_esc(period)}{_esc(weight_bit)}"
        "</div>"
    )


def _render_score_drilldown(
    country_code: str,
    observations: list[Mapping[str, Any]],
    score_state: Mapping[str, Any],
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
        context = [o for o in topic_obs if o.get("score_role") in ("context", "unscored")]

        hard_rows = "".join(_audit_row(o) for o in scored) or (
            '<div class="evidence-grid-row">No scored inputs for this dimension in projection.</div>'
        )
        ctx_rows = "".join(_audit_row(o, link_only=True) for o in context)
        if not ctx_rows:
            ctx_rows = '<div class="evidence-grid-row">No context rows for this topic.</div>'

        detail_id = f"cd-{country_code}-{dimension}"
        impulse_html = (
            f'<div class="score-impulse">{_esc(_impulse_line(spec))}</div>'
        )
        lineage = (
            f"<div class=\"lineage-note\"><b>Score lineage:</b> {LINEAGE_ANCHOR_PHRASE}. "
            "LEVEL is the stored calibrated score. Impulse is separate from attention.</div>"
        )

        parts.append(
            f'<details class="{SCORE_DETAIL_CLASS_ATTRIBUTE}" id="{_esc(detail_id)}">'
            f'<summary class="score-summary">'
            f'<div class="score-top"><b>{_esc(dimension)}</b>'
            f'<span class="score-num">{_esc(score_text)}/100</span></div>'
            f'<div class="temp-bar"><i class="{_esc(klass)}" style="width:{_esc(width_text)}%"></i></div>'
            f'<div class="score-hint">{_esc(dimension)} score</div>'
            f"{impulse_html}"
            f"</summary>"
            f'<div class="score-evidence">'
            f'<div class="evidence-block">'
            f'<div class="evidence-title">{_esc(HARD_SCORE_INPUTS_TITLE)}</div>'
            f'<div class="evidence-grid">{hard_rows}</div>'
            f"{lineage}"
            f"</div>"
            f'<div class="{EVIDENCE_BLOCK_CONTEXT_CLASS}">'
            f'<div class="evidence-title">Context / corroboration</div>'
            f'<div class="evidence-grid">{ctx_rows}</div>'
            f"</div>"
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
        _render_score_compact(code, score_state),
        _render_wmn(attention_country, obs_map),
        _render_country_evidence(code, observations, members),
        _render_score_drilldown(code, observations, score_state),
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


def _preview_script() -> str:
    return """
(function () {
  function wire(root) {
    if (!root) return;
    var search = root.querySelector('.evidence-search');
    var topicBtns = root.querySelectorAll('.topic-btn');
    var items = root.querySelectorAll('.evidence-item');
    var activeTopic = 'all';

    function applyFilter() {
      var q = (search && search.value || '').toLowerCase();
      items.forEach(function (el) {
        var text = el.textContent.toLowerCase();
        var topic = el.getAttribute('data-topic') || '';
        var topicOk = activeTopic === 'all' || topic === activeTopic;
        var searchOk = !q || text.indexOf(q) !== -1;
        el.style.display = topicOk && searchOk ? '' : 'none';
      });
    }

    topicBtns.forEach(function (btn) {
      btn.addEventListener('click', function () {
        activeTopic = btn.getAttribute('data-topic') || 'all';
        topicBtns.forEach(function (b) {
          b.setAttribute('aria-pressed', b === btn ? 'true' : 'false');
        });
        applyFilter();
      });
    });
    if (search) search.addEventListener('input', applyFilter);
  }

  document.querySelectorAll('.country-detail').forEach(wire);

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
