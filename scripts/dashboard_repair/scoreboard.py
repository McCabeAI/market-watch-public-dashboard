"""Readable 1–100 score board. Levels and classes come from the published score state.

The equal-weight line is the same simple mean already used for the country pills.
It is labeled as that summary. Temperature-class thresholds are unchanged.
"""

from __future__ import annotations

from typing import Any

from scripts.country_registry import dashboard_headings
from scripts.dashboard_repair.htmlutil import esc
from scripts.dashboard_repair.score_dates import format_reference_period_through
from scripts.temperature_level import DIMENSIONS, display_score, temperature_class

_CLASS_WORD = {
    "cold": "cold",
    "cool": "cool",
    "neutral": "neutral",
    "warm": "warm",
    "hot": "hot",
}
_DIR_WORD = {"cooling": "cooling", "static": "static", "warming": "warming"}
_DIR_ARROW = {"cooling": "↓", "static": "→", "warming": "↑"}


def _spec(state: dict[str, Any], country: str, dimension: str) -> dict[str, Any]:
    countries = state.get("countries") if isinstance(state.get("countries"), dict) else {}
    block = countries.get(country) if isinstance(countries.get(country), dict) else {}
    spec = block.get(dimension) if isinstance(block.get(dimension), dict) else {}
    return spec


def score_cards(state: dict[str, Any]) -> list[dict[str, Any]]:
    headings = dashboard_headings()
    cards = []
    for country, heading in headings.items():
        dims = []
        levels: list[float] = []
        impulses: list[tuple[str, float]] = []
        partial = False
        for dimension in DIMENSIONS:
            spec = _spec(state, country, dimension)
            level = spec.get("level")
            level_value = float(level) if level is not None else None
            if level_value is not None:
                levels.append(level_value)
            else:
                partial = True
            coverage = spec.get("coverage")
            coverage_value = float(coverage) if coverage is not None else None
            if coverage_value is not None and coverage_value < 1.0 - 1e-9:
                partial = True
            direction = str(spec.get("direction") or "static").lower()
            if direction not in _DIR_WORD:
                direction = "static"
            klass = spec.get("temperature_class")
            if level_value is not None and not klass:
                klass = temperature_class(level_value)
            klass = str(klass or "neutral")
            impulse = spec.get("impulse")
            impulse_value = float(impulse) if impulse is not None else None
            if impulse_value is not None:
                impulses.append((dimension, impulse_value))
            dims.append(
                {
                    "dimension": dimension,
                    "level": level_value,
                    "level_text": display_score(level_value) if level_value is not None else "—",
                    "klass": klass,
                    "direction": direction,
                    "impulse": impulse_value,
                    "coverage": coverage_value,
                    "as_of": str(spec.get("as_of") or ""),
                }
            )
        mean = sum(levels) / len(levels) if levels else None
        mean_class = temperature_class(mean) if mean is not None else None
        if impulses:
            material_name, material_impulse = max(impulses, key=lambda item: abs(item[1]))
        else:
            material_name, material_impulse = None, None
        spread = None
        if len(levels) >= 2:
            spread = max(levels) - min(levels)
        cards.append(
            {
                "country": country,
                "heading": heading,
                "dimensions": dims,
                "mean": mean,
                "mean_text": display_score(mean) if mean is not None else "—",
                "mean_class": mean_class or "neutral",
                "material": material_name,
                "material_impulse": material_impulse,
                "spread": spread,
                "partial": partial,
            }
        )
    return cards


def _impulse_face(row: dict[str, Any]) -> str:
    direction = row["direction"] if row["direction"] in _DIR_WORD else "static"
    if row["impulse"] is None:
        number = "n/a"
    else:
        number = f"{float(row['impulse']):+.2f}"
    return (
        f'<span class="imp imp-{esc(direction)}">{esc(_DIR_ARROW[direction])} {esc(_DIR_WORD[direction])} {esc(number)}</span>'
        '<span class="mw-asof">vs prior print</span>'
    )


def _coverage_chip(coverage: float | None) -> str:
    if coverage is None or coverage >= 1.0 - 1e-9:
        return ""
    return f'<span class="mw-chip mw-chip--warn">Coverage {coverage:.0%}</span>'


def _component_period_label(as_of: str) -> str:
    text = str(as_of or "").strip()
    if not text:
        return ""
    return f"Latest component {format_reference_period_through(text)}"


def _level_face(row: dict[str, Any]) -> str:
    width = 0.0 if row["level"] is None else max(0.0, min(100.0, float(row["level"])))
    if row["level"] is None:
        number = "—"
        klass_word = ""
    else:
        number = f'{row["level_text"]} {_CLASS_WORD.get(row["klass"], row["klass"])}'
        klass_word = str(row["klass"])
    period_label = _component_period_label(str(row.get("as_of") or ""))
    period_html = (
        f'<span class="mw-asof">{esc(period_label)}</span>' if period_label else ""
    )
    return (
        '<div class="lvl">'
        '<span class="mw-label">Level</span>'
        f'<span class="lvl-num mw-num">{esc(number)}</span>'
        '<span class="lvl-scale">/100</span>'
        f'<span class="score-bar" aria-hidden="true"><i class="{esc(klass_word)}" style="width:{width:.1f}%"></i></span>'
        "</div>"
        '<div class="imp-line"><span class="mw-label">Impulse</span>'
        f"{_impulse_face(row)}</div>"
        f"{period_html}"
    )


def _delta_dd_class(delta_text: str) -> str:
    if delta_text == "unavailable":
        return ' class="temp-unavailable"'
    return ""


def _render_temp_card(card: dict[str, Any]) -> str:
    from scripts.temperature_trends import render_sparkline

    title = f'{card["name"]} proposed composite'
    spark = render_sparkline(card["sparkline"], title)
    component_bits = []
    for dimension in DIMENSIONS:
        face = card["components"][dimension]
        component_bits.append(f"{esc(dimension)} {esc(face['text'])}")
    flags_html = "".join(
        f'<p class="temp-card-flag">{esc(flag)}</p>' for flag in (card.get("flags") or [])
    )
    return (
        f'<article class="temp-card" data-country="{esc(card["country"])}">'
        f"<h3>{esc(card['name'])}</h3>"
        f'<p class="temp-card-period">{esc(card["period_label"])}</p>'
        f'<p class="temp-card-score"><span class="temp-card-value">{esc(card["composite_text"])}</span>'
        '<span class="temp-card-unit">/100</span></p>'
        f'<p class="temp-card-kind">Proposed composite</p>'
        f'<div class="temp-spark">{spark}</div>'
        '<dl class="temp-card-deltas">'
        f"<div><dt>1-month</dt><dd{_delta_dd_class(card['delta_1m_text'])}>"
        f"{esc(card['delta_1m_text'])}</dd></div>"
        f"<div><dt>3-month</dt><dd{_delta_dd_class(card['delta_3m_text'])}>"
        f"{esc(card['delta_3m_text'])}</dd></div>"
        "</dl>"
        f'<p class="temp-card-gap">Inflation \u2212 Labor <span class="temp-gap-value">'
        f"{esc(card['divergence_text'])}</span></p>"
        f'<p class="temp-card-components">{"; ".join(component_bits)}</p>'
        f'<p class="temp-card-move">{esc(card["movement"])}</p>'
        f"{flags_html}"
        '<p class="temp-card-provenance">Reconstructed monthly replay</p>'
        "</article>"
    )


def _render_temp_cards(paths_doc: dict[str, Any]) -> str:
    from scripts.temperature_trends import overview_cards

    articles = "".join(_render_temp_card(card) for card in overview_cards(paths_doc))
    return (
        '<section class="temp-cards" data-temp-cards>'
        '<div class="temp-cards-head">'
        "<b>Proposed temperature composite</b>"
        '<p class="temp-cards-note">40/40/10/10 proposed weights. Not the equal-weight production mean. '
        "50 is a structural reference, not a policy-balance claim.</p>"
        "</div>"
        f'<div class="temp-card-grid">{articles}</div>'
        "</section>"
    )


def _scoreboard_markup(state: dict[str, Any]) -> str:
    from scripts.dashboard_repair.score_dates import scoreboard_asof_line

    as_of_line = scoreboard_asof_line(state)
    heads = "".join(f"<th scope=\"col\">{esc(name)}</th>" for name in ("Economy", *DIMENSIONS, "Equal-weight", ""))
    body = []
    for card in score_cards(state):
        peak_name = card["material"]
        cells = []
        for row in card["dimensions"]:
            marker = ""
            if peak_name and row["dimension"] == peak_name and row["impulse"] is not None:
                marker = '<span class="score-peak">Largest impulse</span>'
            cells.append(
                f'<td class="score-cell" data-dimension="{esc(row["dimension"])}">'
                f'<span class="score-cell-dim">{esc(row["dimension"])}</span>'
                f"{_level_face(row)}{_coverage_chip(row['coverage'])}{marker}</td>"
            )
        mean_word = ""
        if card["mean"] is not None:
            mean_word = f'{card["mean_text"]} {_CLASS_WORD.get(card["mean_class"], card["mean_class"])}'
        else:
            mean_word = "—"
        partial = '<span class="mw-chip mw-chip--warn">Partial</span>' if card["partial"] else ""
        mean_width = 0.0 if card["mean"] is None else max(0.0, min(100.0, float(card["mean"])))
        cells.append(
            '<td class="score-cell score-mean-cell">'
            '<div class="lvl"><span class="mw-label">Equal-weight</span>'
            f'<span class="lvl-num mw-num">{esc(mean_word)}</span><span class="lvl-scale">/100</span>'
            f'<span class="score-bar" aria-hidden="true"><i class="{esc(card["mean_class"])}" style="width:{mean_width:.1f}%"></i></span>'
            f"</div>{partial}</td>"
        )
        cells.append(
            '<td class="score-open">'
            f'<button type="button" class="jump country-jump" data-country="{esc(str(card["country"]).lower())}" '
            f'aria-label="Open {esc(card["heading"])}">Open</button></td>'
        )
        body.append(
            f'<tr data-score-country="{esc(card["country"])}">'
            f'<th scope="row">{esc(card["heading"])}</th>'
            + "".join(cells)
            + "</tr>"
        )
    legend = (
        "LEVEL is the 1–100 score (50 = structural/policy neutral). "
        "IMPULSE is the latest print versus the prior print, in score points. "
        "Equal-weight summary is the simple mean of the published dimension levels, not a separate weighted aggregate."
    )
    return (
        '<div class="scoreboard-head"><b>1–100 Score Board</b>'
        f'<span class="mw-asof">{esc(as_of_line)}</span></div>'
        f'<p class="score-legend">{esc(legend)}</p>'
        '<div class="score-scroll"><table class="score-matrix">'
        f"<thead><tr>{heads}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def render_scoreboard(state: dict[str, Any], paths_doc: dict[str, Any] | None = None) -> str:
    cards_html = ""
    if paths_doc is None:
        from scripts.temperature_trends import load_paths

        paths_doc = load_paths()
    if paths_doc is not None:
        cards_html = _render_temp_cards(paths_doc)
    # Cards stay inside the replaced scoreboard element so a later repair does not duplicate them.
    return (
        '<div data-score-overview="calibrated" class="scoreboard">'
        + cards_html
        + _scoreboard_markup(state)
        + "</div>"
    )
