from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.country_registry import (
    dashboard_headings,
    dashboard_keys,
    expected_temperature_gauge_count,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE = ROOT / "data" / "temperature_scores.json"
COUNTRY_KEYS = dashboard_keys()
COUNTRY_HEADINGS = dashboard_headings()
DIMENSIONS = ("Inflation", "Labor", "Activity", "Consumer")
PILL_LABELS = {
    "cold": "COLD",
    "cool": "COOL",
    "neutral": "NEUTRAL",
    "warm": "WARM",
    "hot": "HOT",
}
DIR_LABELS = {"cooling": "COOLING", "static": "STATIC", "warming": "WARMING"}
STALE_NARRATIVE_MARKERS = (
    "lineage-pinned",
    "contributing −",
    "contributing -1.0 point",
    "must not be guessed merely to move the score",
)
LINEAGE_ANCHOR_PHRASE = "50 = structural/policy neutral anchor"
SCORE_KEY_TEXT = (
    "50 = structural/policy anchor · LEVEL from latest hard data · "
    "impulse shows print-to-print direction (separate from LEVEL colour)"
)
DIRECTION_LABELS = {"cooling": "Cooling", "static": "Static", "warming": "Warming"}

from scripts.dashboard_mini_cards import patch_ea_jp_snapshot_minis

from scripts.temperature_level import (
    all_levels,
    display_score,
    load_state as load_level_state,
    temperature_class,
)


def load_state(path: Path = DEFAULT_STATE) -> dict[str, Any]:
    return load_level_state(path)


def _dimension_spec(state: dict[str, Any], country: str, dimension: str) -> dict[str, Any]:
    return state["countries"][country][dimension]


def _format_impulse(value: float | None) -> str:
    if value is None:
        return "n/a"
    rounded = round(float(value), 1)
    if abs(rounded) < 1e-9:
        return "0"
    sign = "+" if rounded > 0 else ""
    if abs(rounded - round(rounded)) < 1e-9:
        return f"{sign}{int(round(rounded))}"
    return f"{sign}{rounded:.1f}"


def _impulse_html(spec: dict[str, Any]) -> str:
    direction = str(spec.get("direction") or "static").lower()
    label = DIRECTION_LABELS.get(direction, direction.title())
    impulse_bit = _format_impulse(spec.get("impulse") if "impulse" in spec else None)
    return (
        '<div class="score-impulse" style="font-size:7px;margin-top:2px;color:var(--muted);">'
        f"{label} · impulse {impulse_bit}</div>"
    )


def _component_label(name: str) -> str:
    label = name.replace("_", " ")
    parts = []
    for word in label.split():
        upper = word.upper()
        if upper in {"GDP", "PCE", "CPI", "ISM"}:
            parts.append(upper)
        else:
            parts.append(word.capitalize())
    return " ".join(parts)


def _format_as_of_display(as_of: str | None) -> str:
    if not as_of:
        return "n/a"
    text = str(as_of)
    if re.fullmatch(r"\d{4}-Q[1-4]", text):
        return text.upper()
    if len(text) == 7 and text[4] == "-":
        year, month = text.split("-")
        months = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()
        return f"{months[int(month) - 1]} {year}"
    return text.upper()


def _format_transform_value(value: float | None) -> str:
    if value is None:
        return "n/a"
    rounded = round(float(value), 4)
    text = f"{rounded:.4f}".rstrip("0").rstrip(".")
    return text


def _format_weight_pct(weight: float | None) -> str:
    if weight is None:
        return "n/a"
    pct = round(float(weight) * 100)
    return f"{pct}%"


def _hard_input_row(
    name: str,
    component: dict[str, Any],
    weight: float | None,
) -> str:
    label = _component_label(name)
    as_of = _format_as_of_display(component.get("as_of"))
    weight_pct = _format_weight_pct(weight)
    transform = _format_transform_value(component.get("transform_value"))
    level = component.get("level")
    level_text = display_score(float(level)) if level is not None else "n/a"
    impulse = _format_impulse(component.get("impulse") if "impulse" in component else None)
    note = (
        f"V1 LEVEL {level_text} from transform {transform} "
        f"(registry weight {weight_pct}; coverage contribution "
        f"{_format_weight_pct(component.get('coverage_contribution'))}). "
        f"Component impulse {impulse} vs prior print."
    )
    return (
        '<div class="evidence-row"><div class="evidence-meta">'
        f'<span class="evidence-role">DIRECT · {weight_pct}</span><span>{as_of}</span></div>'
        f'<div class="evidence-main"><strong>{label}</strong>'
        f'<span class="evidence-value">{transform}</span></div>'
        f'<div class="evidence-note">{note}</div></div>'
    )


def _us_inflation_runrate_strip(component: dict[str, Any]) -> str:
    transform = component.get("transform_value")
    if transform is None:
        return ""
    text = _format_transform_value(transform)
    return (
        '<div class="runrate-strip"><div class="runrate-cell">'
        "<span>V1 scoring transform (3m ann.)</span>"
        f"<b>{text}%</b></div></div>"
    )


def _hard_inputs_html(
    country: str,
    dimension: str,
    spec: dict[str, Any],
) -> str:
    weights = spec.get("components") or {}
    component_state = spec.get("component_state") or {}
    rows: list[str] = []
    for name, weight in weights.items():
        component = component_state.get(name) or {}
        if not component.get("observed"):
            continue
        rows.append(_hard_input_row(name, component, float(weight)))

    runrate = ""
    if country == "US" and dimension == "Inflation":
        core = component_state.get("core_pce") or {}
        if core.get("observed"):
            runrate = _us_inflation_runrate_strip(core)

    grid = '<div class="evidence-grid">' + "".join(rows) + "</div>"
    return '<div class="evidence-title">Hard score inputs</div>' + runrate + grid


def _country_pill_spans(state: dict[str, Any], country: str) -> tuple[str, str]:
    levels: list[float] = []
    directions: list[str] = []
    for dimension in DIMENSIONS:
        spec = _dimension_spec(state, country, dimension)
        level = spec.get("level")
        if level is not None:
            levels.append(float(level))
        directions.append(str(spec.get("direction") or "static").lower())

    mean_level = sum(levels) / len(levels) if levels else 50.0
    pill_class = temperature_class(mean_level)
    pill_span = (
        f'<span class="pill {pill_class}">{PILL_LABELS[pill_class]}</span>'
    )

    counts = Counter(directions)
    ordered = counts.most_common()
    majority = ordered[0][0]
    if len(ordered) > 1 and ordered[0][1] == ordered[1][1]:
        majority = "static"
    dir_span = f'<span class="dir {majority}">{DIR_LABELS[majority]}</span>'
    return pill_span, dir_span


def _patch_country_pills(html: str, state: dict[str, Any]) -> str:
    for country, heading in COUNTRY_HEADINGS.items():
        pill_span, dir_span = _country_pill_spans(state, country)
        html, macro_count = re.subn(
            rf'(<h3>{heading}</h3>.*?<div class="pills">).*?(</div>)',
            rf"\1{pill_span}{dir_span}\2",
            html,
            count=1,
            flags=re.S,
        )
        key = COUNTRY_KEYS[country]
        if f'<div class="cdetail {key}">' in html:
            start, end = _country_slice(html, key)
            block = html[start:end]
            if '<div class="big">' in block:
                block, hero_count = re.subn(
                    r'<div class="big"><span class="pill [^"]+">[^<]+</span></div>\s*'
                    r'<span class="dir [^"]+">[^<]+</span>',
                    f'<div class="big">{pill_span}</div>{dir_span}',
                    block,
                    count=1,
                )
                if hero_count != 1:
                    raise ValueError(f"could not patch hero pills for {country}")
                html = html[:start] + block + html[end:]
        elif macro_count != 1:
            raise ValueError(f"could not patch macro snapshot pills for {country}")
    return html


def _scrub_stale_narrative(html: str) -> str:
    html = re.sub(
        r'<div class="evidence-row context-row"><div class="evidence-meta">'
        r'<span class="evidence-role">CONFIDENCE EVIDENCE · SCORED</span><span>SEP 2026 PRELIM</span></div>'
        r'<div class="evidence-main"><strong>Michigan sentiment</strong>'
        r'<span class="evidence-value">47\.8</span></div>.*?</a></div>',
        "",
        html,
        flags=re.S,
    )
    html = re.sub(
        r'<div class="evidence-note">[^<]*contributing [^<]*</div>',
        '<div class="evidence-note">V1 corroboration only; retired classified bucket impulses are not shown.</div>',
        html,
        flags=re.I,
    )
    html = re.sub(
        r'<div class="evidence-note">[^<]*(?:lineage-pinned|must not be guessed merely to move the score)[^<]*</div>',
        '<div class="evidence-note">See live V1 hard score inputs above.</div>',
        html,
        flags=re.I,
    )
    for marker in STALE_NARRATIVE_MARKERS:
        if marker in html:
            raise ValueError(f"stale narrative marker remains after patch: {marker}")
    if re.search(
        r"CONFIDENCE EVIDENCE · SCORED</span>.*?Michigan sentiment.*?47\.8",
        html,
        flags=re.S | re.I,
    ):
        raise ValueError("stale Michigan 47.8 SCORED narrative remains after patch")
    return html


def _lineage_html(spec: dict[str, Any], state: dict[str, Any]) -> str:
    level = spec.get("level")
    level_text = display_score(float(level)) if level is not None else "n/a"
    coverage = spec.get("coverage")
    cov_bit = ""
    if coverage is not None and float(coverage) < 1.0 - 1e-9:
        cov_bit = f" Coverage {float(coverage):.0%}; missing inputs omitted from LEVEL."
    methodology = state.get("methodology") or "docs/TEMPERATURE_LEVEL_CALIBRATION_V1.md"
    as_of = spec.get("as_of") or state.get("as_of") or "n/a"
    return (
        f'<div class="lineage-note"><b>Score lineage:</b> {LINEAGE_ANCHOR_PHRASE} '
        f"({methodology}). LEVEL {level_text} from latest verified observations as of {as_of}."
        f"{cov_bit} Impulse and direction are separate from LEVEL.</div>"
    )


def _country_slice(html: str, key: str) -> tuple[int, int]:
    anchor = f'<div class="cdetail {key}">'
    start = html.index(anchor)
    later = [html.find(f'<div class="cdetail {other}">', start + len(anchor)) for other in COUNTRY_KEYS.values()]
    later = [idx for idx in later if idx != -1]
    end = min(later) if later else len(html)
    return start, end


def _score_overview_html(levels: dict[str, dict[str, float | None]], state: dict[str, Any]) -> str:
    cells = []
    for country in COUNTRY_KEYS:
        bits = []
        for dimension in DIMENSIONS:
            spec = _dimension_spec(state, country, dimension)
            level = levels[country][dimension]
            level_text = display_score(level) if level is not None else "—"
            dir_abbr = {"cooling": "↓", "static": "→", "warming": "↑"}.get(
                str(spec.get("direction") or "static").lower(), "→"
            )
            bits.append(f"{dimension[:3]} {level_text}{dir_abbr}")
        values = " · ".join(bits)
        cells.append(
            '<div style="padding:8px 10px;border:1px solid currentColor;border-radius:8px;">'
            f'<b>{country}</b><div style="margin-top:4px;font-size:12px;">{values}</div></div>'
        )

    refreshed = state.get("as_of") or state.get("last_refresh_date", "")
    return (
        '<div data-score-overview="live" style="margin:0 0 18px;padding:12px;'
        'border:1px solid currentColor;border-radius:10px;">'
        '<div style="display:flex;justify-content:space-between;gap:12px;align-items:baseline;'
        'margin-bottom:10px;"><b>Live 1–100 Score Board</b>'
        f'<span style="font-size:11px;">calibrated LEVEL through {refreshed}</span></div>'
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;">'
        + "".join(cells)
        + '</div><div style="margin-top:8px;font-size:10px;color:var(--muted);">'
        "↑/↓/→ = warming / cooling / static impulse vs prior prints (not LEVEL colour).</div></div>"
    )


def _patch_top_board(html: str, levels: dict[str, dict[str, float | None]], state: dict[str, Any]) -> str:
    marker = '<div class="stitle">Temperature Board</div>'
    if html.count(marker) != 1:
        raise ValueError("expected one top-level Temperature Board marker")
    replacement = _score_overview_html(levels, state) + '<div class="stitle">Macro Snapshot</div>'
    return html.replace(marker, replacement, 1)


def _patch_dimension(
    block: str,
    country: str,
    dimension: str,
    level: float | None,
    spec: dict[str, Any],
    state: dict[str, Any],
) -> str:
    if level is None:
        score_text = "—"
        klass = "neutral"
        width_text = "0"
    else:
        score_text = display_score(level)
        klass = spec.get("temperature_class") or temperature_class(level)
        width_text = display_score(max(1.0, min(100.0, level)))

    score_pattern = re.compile(
        rf'(<b>{re.escape(dimension)}</b><span class="score-num">)([0-9.—]+)(/100</span></div>'
        rf'<div class="temp-bar"><i class=")(cold|cool|neutral|warm|hot)(" style="width:)([0-9.—]+)(%"></i></div>)'
    )
    block, count = score_pattern.subn(
        rf"\g<1>{score_text}\g<3>{klass}\g<5>{width_text}\g<7>",
        block,
        count=1,
    )
    if count != 1:
        raise ValueError(f"could not patch {dimension} score")

    impulse_pattern = re.compile(
        rf"(<b>{re.escape(dimension)}</b>.*?<div class=\"score-hint\">.*?</div>)"
        rf"(?:<div class=\"score-impulse\"[^>]*>.*?</div>)?",
        re.S,
    )
    block, count = impulse_pattern.subn(
        lambda m: m.group(1) + _impulse_html(spec),
        block,
        count=1,
    )
    if count != 1:
        raise ValueError(f"could not patch {dimension} impulse row")

    hard_pattern = re.compile(
        rf'(<details class="temp-dimension score-detail">.*?<b>{re.escape(dimension)}</b>.*?)'
        rf'<div class="evidence-title">Hard score inputs</div>'
        rf'.*?(?=<div class="lineage-note|<div class="evidence-block context")',
        re.S,
    )
    hard_html = _hard_inputs_html(country=country, dimension=dimension, spec=spec)
    block, count = hard_pattern.subn(rf"\1{hard_html}", block, count=1)
    if count != 1:
        raise ValueError(f"could not patch {dimension} hard score inputs")

    details_pattern = re.compile(
        rf'(<details class="temp-dimension score-detail">.*?<b>{re.escape(dimension)}</b>.*?)(<div class="lineage-note(?: lineage-gap)?">.*?</div>)',
        re.S,
    )
    lineage = _lineage_html(spec, state)
    block, count = details_pattern.subn(lambda m: m.group(1) + lineage, block, count=1)
    if count != 1:
        raise ValueError(f"could not patch {dimension} lineage")
    return block


def apply_scores(html: str, state: dict[str, Any]) -> str:
    levels = all_levels(state)
    html = _patch_top_board(html, levels, state)
    html = html.replace(
        "Tap any score to inspect hard inputs + corroborating evidence",
        SCORE_KEY_TEXT,
    )

    for country, key in COUNTRY_KEYS.items():
        start, end = _country_slice(html, key)
        block = html[start:end]
        for dimension in DIMENSIONS:
            spec = _dimension_spec(state, country, dimension)
            block = _patch_dimension(
                block,
                country,
                dimension,
                levels[country][dimension],
                spec,
                state,
            )
        html = html[:start] + block + html[end:]

    if any(f"<h3>{heading}</h3>" in html for heading in COUNTRY_HEADINGS.values()):
        html = _patch_country_pills(html, state)
        html = patch_ea_jp_snapshot_minis(html, state)
    html = _scrub_stale_narrative(html)

    expected = expected_temperature_gauge_count()
    if html.count('class="temp-dimension score-detail"') != expected:
        raise ValueError(f"expected {expected} temperature score drawers")
    if html.count(LINEAGE_ANCHOR_PHRASE) != expected:
        raise ValueError(f"expected {expected} V1 structural-anchor lineage notes")
    if "Reindexed to 50 on 2026-09-17" in html:
        raise ValueError("stale reindex lineage remains")
    if html.count('data-score-overview="live"') != 1:
        raise ValueError("expected one live top-level score overview")
    if "Temperature Board" in html:
        raise ValueError("stale top-level Temperature Board label remains")
    return html


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply calibrated Market Watch temperature LEVEL scores")
    parser.add_argument("html", nargs="?", help="HTML file to patch")
    parser.add_argument("--state", default=str(DEFAULT_STATE), help="score-state JSON (version 3)")
    parser.add_argument("--print-scores", action="store_true", help="print calculated LEVELs as JSON")
    args = parser.parse_args()

    state = load_state(Path(args.state))
    levels = all_levels(state)
    if args.print_scores:
        print(json.dumps(levels, indent=2, sort_keys=True))

    if args.html:
        path = Path(args.html)
        html = path.read_text(encoding="utf-8")
        path.write_text(apply_scores(html, state), encoding="utf-8")


if __name__ == "__main__":
    main()
