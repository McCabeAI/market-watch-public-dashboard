"""Country detail historical temperature trends panel (markup only)."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Mapping

from scripts.temperature_trends import (
    DEFAULT_WINDOW,
    SERIES_COLORS,
    SERIES_KEYS,
    SERIES_LABELS,
    WINDOWS,
    format_level,
    render_trend_svg,
    slice_window,
)

_MULTIPLE_KEYS = ("inflation", "labor", "activity", "consumer")
_CHART_JS = Path(__file__).resolve().parent / "temperature_chart.js"


def temperature_chart_script() -> str:
    return _CHART_JS.read_text(encoding="utf-8")


def _latest_values(slice_points: list[Mapping[str, Any]]) -> dict[str, str]:
    last = slice_points[-1] if slice_points else {}
    out: dict[str, str] = {}
    for key in SERIES_KEYS:
        raw = last.get(key)
        value = float(raw) if isinstance(raw, (int, float)) else None
        out[key] = format_level(value)
    return out


def _legend_tiles(slice_points: list[Mapping[str, Any]]) -> str:
    latest = _latest_values(slice_points)
    parts: list[str] = []
    for key in SERIES_KEYS:
        color = SERIES_COLORS[key]
        parts.append(
            f'<div class="temp-tile" data-series="{html.escape(key, quote=True)}">'
            f'<i class="temp-swatch" style="background:{color}"></i>'
            '<div class="temp-tile-body">'
            f'<span class="temp-tile-name">{html.escape(SERIES_LABELS[key], quote=True)}</span>'
            f'<b class="temp-tile-value">{html.escape(latest[key], quote=True)}</b>'
            "</div></div>"
        )
    return "".join(parts)


def _window_buttons() -> str:
    parts: list[str] = []
    for months in WINDOWS:
        pressed = "true" if months == DEFAULT_WINDOW else "false"
        parts.append(
            f'<button type="button" class="temp-window-btn" data-window="{months}" '
            f'aria-pressed="{pressed}">{months}m</button>'
        )
    return "".join(parts)


def _chart_block(
    name: str,
    points: list[Mapping[str, Any]],
    months: int,
    *,
    hidden: bool,
) -> str:
    slice_points = slice_window(points, months)
    latest_label = slice_points[-1].get("label") if slice_points else "unavailable"
    latest_values = _latest_values(slice_points)
    values_json = html.escape(json.dumps(latest_values, separators=(",", ":")), quote=True)
    label_esc = html.escape(str(latest_label), quote=True)
    hidden_attr = " hidden" if hidden else ""
    title_main = f"{name} temperature history {months} months"
    title_agg = f"{name} aggregate trajectory {months} months"
    multiples_html: list[str] = []
    for key in _MULTIPLE_KEYS:
        multiples_html.append(
            f'<figure class="temp-multiple" data-series="{html.escape(key, quote=True)}">'
            f'<figcaption>{html.escape(SERIES_LABELS[key], quote=True)}</figcaption>'
            f'{render_trend_svg(slice_points, (key,), compact=True, title=f"{name} {SERIES_LABELS[key]} {months} months")}'
            "</figure>"
        )
    return (
        f'<div class="temp-chart-block" data-window-panel="{months}"{hidden_attr} '
        f'data-latest-label="{label_esc}" data-latest-values="{values_json}">'
        f'<div class="temp-chart-scroll" tabindex="0">'
        f"{render_trend_svg(slice_points, SERIES_KEYS, title=title_main)}"
        "</div>"
        f'<figure class="temp-focus">'
        f'<figcaption>Aggregate trajectory</figcaption>'
        f'{render_trend_svg(slice_points, ("aggregate",), compact=True, title=title_agg)}'
        "</figure>"
        f'<div class="temp-multiples">{"".join(multiples_html)}</div>'
        "</div>"
    )


def render_temperature_history_panel(view: Mapping[str, Any]) -> str:
    country = str(view.get("country") or "")
    name = str(view.get("name") or country)
    points = list(view.get("points") or [])
    provenance = str(view.get("provenance_note") or "")

    default_slice = slice_window(points, DEFAULT_WINDOW)
    month_label = (
        str(default_slice[-1].get("label"))
        if default_slice
        else (str(points[-1].get("label")) if points else "unavailable")
    )
    full_latest = str(points[-1].get("label")) if points else "unavailable"

    blocks = [
        _chart_block(name, points, months, hidden=(months != DEFAULT_WINDOW))
        for months in (12, 6, 3)
    ]

    return (
        f'<section class="temp-panel" data-temp-panel data-country="{html.escape(country, quote=True)}">'
        '<div class="temp-panel-top">'
        f'<h2 class="temp-panel-title">{html.escape(name, quote=True)}: historical temperature trends</h2>'
        f'<p class="temp-panel-month" data-temp-month>{html.escape(month_label, quote=True)}</p>'
        "</div>"
        f'<p class="temp-panel-desc">Actual stored monthly dimension scores through {html.escape(full_latest, quote=True)}.'
        "<br>Aggregate uses proposed 40/40/10/10 weights; not the existing production mean.</p>"
        f'<div class="temp-legend" data-temp-legend>{_legend_tiles(default_slice)}</div>'
        f'<div class="temp-window" role="tablist" aria-label="History window">{_window_buttons()}</div>'
        f'{"".join(blocks)}'
        '<p class="temp-neutral-note">The line at 50 is a structural neutral reference, not a claim of policy balance.</p>'
        f'<p class="temp-panel-provenance">{html.escape(provenance, quote=True)}</p>'
        "</section>"
    )
