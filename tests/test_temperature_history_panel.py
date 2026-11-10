from __future__ import annotations

import html as html_module
import unittest

from scripts.country_detail.policy import SCORE_DETAIL_CLASS_ATTRIBUTE
from scripts.country_detail.temperature_history_panel import (
    render_temperature_history_panel,
    temperature_chart_script,
)
from scripts.temperature_trends import (
    format_month,
    provenance_note,
    proposed_composite,
    tooltip_text,
)
from tests.test_country_detail_render import (
    SHARED_OBS_ID,
    synthetic_attention_quiet,
    synthetic_projection,
    synthetic_score_state,
)

try:
    from scripts.country_detail.render import render_country_detail
except ImportError:
    render_country_detail = None


def _synthetic_points() -> list[dict]:
    months = ("2025-06", "2025-07", "2025-08", "2025-09")
    rows: list[dict] = []
    for index, period in enumerate(months):
        inflation = None if period == "2025-08" else 48.0 + index
        labor = 52.0 + index
        activity = 50.0
        consumer = 51.0 + index
        levels = {
            "Inflation": inflation,
            "Labor": labor,
            "Activity": activity,
            "Consumer": consumer,
        }
        rows.append(
            {
                "period": period,
                "label": format_month(period),
                "tick": format_month(period, tick=True),
                "aggregate": proposed_composite(levels),
                "inflation": inflation,
                "labor": labor,
                "activity": activity,
                "consumer": consumer,
                "divergence": None,
                "source_periods": {},
                "provenance": "reconstructed",
            }
        )
    return rows


class TemperatureHistoryPanelTest(unittest.TestCase):
    def test_panel_markup_and_gap_tooltip(self) -> None:
        points = _synthetic_points()
        fragment = render_temperature_history_panel(
            {
                "country": "CA",
                "name": "Canada",
                "points": points,
                "provenance_note": provenance_note(),
            }
        )
        self.assertIn(": historical temperature trends", fragment)
        self.assertIn("proposed 40/40/10/10", fragment)
        self.assertIn("not the existing production mean", fragment)
        for color in ("#1687FF", "#12BF4A", "#FFD13D", "#FF7626", "#CBAAF5"):
            self.assertIn(color, fragment)
        self.assertIn('class="temp-tile-body"', fragment)
        self.assertRegex(
            fragment,
            r'<div class="temp-tile" data-series="aggregate">'
            r'<i class="temp-swatch"[^>]*></i><div class="temp-tile-body">'
            r'<span class="temp-tile-name">Aggregate</span>'
            r"<b class=\"temp-tile-value\">",
        )
        self.assertIn('data-window="12"', fragment)
        self.assertIn('aria-pressed="true"', fragment)
        self.assertIn('data-window-panel="3" hidden', fragment)
        self.assertIn('data-window-panel="6" hidden', fragment)
        self.assertIn("temp-neutral-note", fragment)
        note = provenance_note()
        self.assertIn(html_module.escape(note, quote=True), fragment)
        self.assertIn("reconstructed", note.lower())
        self.assertIn("not a historical real-time published snapshot", note.lower())
        gap = next(p for p in points if p["period"] == "2025-08")
        tip = tooltip_text(gap)
        self.assertIn("Aggregate: unavailable", tip)
        self.assertIn("Aggregate: unavailable", fragment)
        self.assertIn("<polyline", fragment)
        self.assertNotRegex(fragment, r'\sC\s[\d.-]+')

    def test_render_country_detail_includes_panel_and_drilldown(self) -> None:
        if render_country_detail is None:
            self.skipTest("render_country_detail unavailable")
        temperature_view = {
            "country": "US",
            "name": "United States",
            "points": _synthetic_points(),
            "provenance_note": provenance_note(),
        }
        html = render_country_detail(
            "US",
            synthetic_projection(SHARED_OBS_ID),
            synthetic_attention_quiet(),
            synthetic_score_state(),
            temperature_view=temperature_view,
        )
        self.assertIn('class="temp-panel"', html)
        self.assertEqual(html.count(SCORE_DETAIL_CLASS_ATTRIBUTE), 4)

    def test_chart_script_contract(self) -> None:
        js = temperature_chart_script()
        self.assertIn("ArrowLeft", js)
        self.assertIn("data-window", js)
        self.assertIn("data-tip", js)


if __name__ == "__main__":
    unittest.main()
