from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE = ROOT / "data" / "temperature_scores.json"
COUNTRY_KEYS = {"US": "us", "CA": "ca", "AU": "au", "NZ": "nz"}
DIMENSIONS = ("Inflation", "Labor", "Activity", "Consumer")
LINEAGE_ANCHOR_PHRASE = "50 = structural/policy neutral anchor"
SCORE_KEY_TEXT = (
    "50 = structural/policy anchor · LEVEL from latest hard data · "
    "impulse shows print-to-print direction (separate from LEVEL colour)"
)
DIRECTION_LABELS = {"cooling": "Cooling", "static": "Static", "warming": "Warming"}

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
                dimension,
                levels[country][dimension],
                spec,
                state,
            )
        html = html[:start] + block + html[end:]

    if html.count('class="temp-dimension score-detail"') != 16:
        raise ValueError("expected 16 temperature score drawers")
    if html.count(LINEAGE_ANCHOR_PHRASE) != 16:
        raise ValueError("expected 16 V1 structural-anchor lineage notes")
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
