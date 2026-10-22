"""Readable 1–100 score board. Levels and classes come from the published score state.

The equal-weight line is the same simple mean already used for the country pills.
It is labeled as that summary. Temperature-class thresholds are unchanged.
"""

from __future__ import annotations

from typing import Any

from scripts.country_registry import dashboard_headings
from scripts.dashboard_repair.htmlutil import esc
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


def render_scoreboard(state: dict[str, Any]) -> str:
    as_of = str(state.get("as_of") or state.get("last_refresh_date") or "date missing")
    cards = []
    for card in score_cards(state):
        material = card["material"]
        material_dim = next((row for row in card["dimensions"] if row["dimension"] == material), None)
        if material_dim is None:
            headline = "No dimension impulse is published in the score state."
        else:
            headline = (
                f"Largest impulse: {material_dim['dimension']} "
                f"{_DIR_ARROW[material_dim['direction']]} {_DIR_WORD[material_dim['direction']]} "
                f"{material_dim['impulse']:+.2f} (level {material_dim['level_text']} {_CLASS_WORD.get(material_dim['klass'], material_dim['klass'])})."
            )
        spread_bit = ""
        if card["spread"] is not None and card["spread"] >= 15:
            ordered = [row for row in card["dimensions"] if row["level"] is not None]
            low = min(ordered, key=lambda row: row["level"])
            high = max(ordered, key=lambda row: row["level"])
            spread_bit = (
                f' <span class="score-spread">Level spread {esc(low["dimension"])} {esc(low["level_text"])} '
                f'to {esc(high["dimension"])} {esc(high["level_text"])}.</span>'
            )
        chips = []
        for row in card["dimensions"]:
            coverage = "coverage not recorded"
            if row["coverage"] is not None:
                coverage = f"coverage {row['coverage']:.0%}"
            width = 0 if row["level"] is None else max(0.0, min(100.0, row["level"]))
            chips.append(
                '<div class="score-dim">'
                f'<span class="score-dim-name">{esc(row["dimension"])}</span>'
                f'<span class="pill {esc(row["klass"])}">{esc(row["level_text"])} {esc(_CLASS_WORD.get(row["klass"], row["klass"]))}</span>'
                f'<span class="dir {esc(row["direction"])}">{esc(_DIR_ARROW[row["direction"]])} {esc(_DIR_WORD[row["direction"]])}</span>'
                f'<span class="score-cov">{esc(coverage)}</span>'
                f'<span class="score-bar" aria-hidden="true"><i class="{esc(row["klass"])}" style="width:{width:.1f}%"></i></span>'
                "</div>"
            )
        partial = "Partial dimension coverage." if card["partial"] else "All four dimensions have a published level."
        cards.append(
            f'<article class="score-card" data-score-country="{esc(card["country"])}">'
            f'<h3>{esc(card["heading"])}</h3>'
            f'<p class="score-headline">{esc(headline)}{spread_bit}</p>'
            '<p class="score-mean">Equal-weight summary '
            f'<span class="pill {esc(card["mean_class"])}">{esc(card["mean_text"])} {esc(_CLASS_WORD.get(card["mean_class"], card["mean_class"]))}</span>'
            " Simple mean of the published dimension levels. Not a separate weighted aggregate.</p>"
            f'<p class="score-cov">{esc(partial)}</p>'
            + "".join(chips)
            + "</article>"
        )
    return (
        '<div data-score-overview="calibrated" class="scoreboard">'
        '<div class="scoreboard-head"><b>1–100 Score Board</b>'
        f'<span>Published score freeze {esc(as_of)}. Level bands use the existing cold/cool/neutral/warm/hot thresholds. '
        "Arrows are the impulse versus the prior print and use their own cooling/static/warming labels.</span></div>"
        '<div class="scoreboard-grid">' + "".join(cards) + "</div></div>"
    )
