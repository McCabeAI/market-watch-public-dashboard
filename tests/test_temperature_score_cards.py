"""Temperature overview cards prepended on the score board."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.country_registry import temperature_countries
from scripts.dashboard_repair.apply import load_scores
from scripts.dashboard_repair.scoreboard import render_scoreboard
from scripts.temperature_trends import equal_weight_mean, overview_card, proposed_composite

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_STATE = ROOT / "tests" / "fixtures" / "temperature_scores_v3_minimal.json"


def _load_fixture_state() -> dict:
    return json.loads(FIXTURE_STATE.read_text(encoding="utf-8"))


def _empty_paths_doc() -> dict:
    paths = {
        code: {dim: [] for dim in ("Inflation", "Labor", "Activity", "Consumer")}
        for code in temperature_countries()
    }
    return {"paths": paths}


def _add_month(
    block: dict,
    period: str,
    inflation: float,
    labor: float,
    activity: float,
    consumer: float,
    *,
    omit: frozenset[str] | None = None,
) -> None:
    omit = omit or frozenset()
    pairs = (
        ("Inflation", inflation),
        ("Labor", labor),
        ("Activity", activity),
        ("Consumer", consumer),
    )
    for dim, level in pairs:
        if dim in omit:
            continue
        block[dim].append(
            {"period": period, "level": level, "source_period": period}
        )


class TemperatureScoreCardsTests(unittest.TestCase):
    def test_six_cards_order_labels_and_note(self) -> None:
        doc = _empty_paths_doc()
        _add_month(doc["paths"]["US"], "2025-10", 55.0, 55.0, 55.0, 55.0)
        html = render_scoreboard(_load_fixture_state(), paths_doc=doc)
        self.assertIn('class="temp-cards"', html)
        self.assertIn("Proposed temperature composite", html)
        self.assertIn("Not the equal-weight production mean", html)
        self.assertEqual(html.count('class="temp-card"'), 6)
        order = re.findall(r'<article class="temp-card" data-country="([^"]+)"', html)
        self.assertEqual(order, list(temperature_countries()))
        self.assertEqual(html.count("Proposed composite"), 6)
        self.assertIn("United States", html)
        self.assertNotIn('data-country="US"><h3>US</h3>', html)

    def test_composite_matches_proposed_weights_not_equal_weight_mean(self) -> None:
        levels = {
            "Inflation": 100.0,
            "Labor": 100.0,
            "Activity": 0.0,
            "Consumer": 0.0,
        }
        self.assertEqual(proposed_composite(levels), 80.0)
        self.assertEqual(equal_weight_mean(levels), 50.0)
        doc = _empty_paths_doc()
        _add_month(doc["paths"]["US"], "2025-10", 100.0, 100.0, 0.0, 0.0)
        card = overview_card(doc, "US")
        self.assertEqual(card["composite_text"], "80.00")
        html = render_scoreboard(_load_fixture_state(), paths_doc=doc)
        us = re.search(
            r'<article class="temp-card" data-country="US">(.*?</article>)',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(us)
        assert us is not None
        self.assertIn('<span class="temp-card-value">80.00</span>', us.group(1))
        self.assertNotIn('<span class="temp-card-value">50.00</span>', us.group(1))

    def test_inflation_labor_gap_signed_positive_and_negative(self) -> None:
        doc = _empty_paths_doc()
        _add_month(doc["paths"]["US"], "2025-10", 70.0, 50.0, 50.0, 50.0)
        _add_month(doc["paths"]["CA"], "2025-10", 50.0, 62.0, 50.0, 50.0)
        html = render_scoreboard(_load_fixture_state(), paths_doc=doc)
        us = re.search(
            r'<article class="temp-card" data-country="US">(.*?</article>)',
            html,
            re.DOTALL,
        )
        ca = re.search(
            r'<article class="temp-card" data-country="CA">(.*?</article>)',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(us)
        self.assertIsNotNone(ca)
        assert us is not None and ca is not None
        self.assertIn('<span class="temp-gap-value">+20.00</span>', us.group(1))
        self.assertIn('<span class="temp-gap-value">-12.00</span>', ca.group(1))
        self.assertIn("Opposing pressure", ca.group(1))

    def test_missing_dimension_makes_composite_unavailable(self) -> None:
        doc = _empty_paths_doc()
        _add_month(
            doc["paths"]["US"],
            "2025-10",
            60.0,
            60.0,
            60.0,
            60.0,
        )
        _add_month(
            doc["paths"]["US"],
            "2025-11",
            60.0,
            60.0,
            60.0,
            60.0,
            omit=frozenset({"Activity"}),
        )
        card = overview_card(doc, "US")
        self.assertIsNone(card["composite"])
        self.assertEqual(card["composite_text"], "unavailable")
        html = render_scoreboard(_load_fixture_state(), paths_doc=doc)
        us = re.search(
            r'<article class="temp-card" data-country="US">(.*?</article>)',
            html,
            re.DOTALL,
        )
        assert us is not None
        self.assertIn('<span class="temp-card-value">unavailable</span>', us.group(1))
        self.assertIn("Activity unavailable", us.group(1))

    def test_one_month_delta_unavailable_without_prior_month(self) -> None:
        doc = _empty_paths_doc()
        _add_month(doc["paths"]["US"], "2025-09", 40.0, 40.0, 40.0, 40.0)
        _add_month(doc["paths"]["US"], "2025-11", 100.0, 100.0, 0.0, 0.0)
        card = overview_card(doc, "US")
        self.assertEqual(card["delta_1m_text"], "unavailable")
        self.assertEqual(card["flags"], [])
        html = render_scoreboard(_load_fixture_state(), paths_doc=doc)
        us = re.search(
            r'<article class="temp-card" data-country="US">(.*?</article>)',
            html,
            re.DOTALL,
        )
        assert us is not None
        self.assertRegex(
            us.group(1),
            r'<dt>1-month</dt><dd class="temp-unavailable">unavailable</dd>',
        )
        self.assertNotRegex(us.group(1), r"<dd[^>]*>\+[0-9]")

    def test_scoreboard_table_unchanged_with_paths(self) -> None:
        doc = _empty_paths_doc()
        _add_month(doc["paths"]["US"], "2025-10", 50.0, 50.0, 50.0, 50.0)
        scores = load_scores()
        html = render_scoreboard(scores, paths_doc=doc)
        self.assertIn("Equal-weight", html)
        self.assertIn(
            '<td class="score-cell" data-dimension="Inflation"><span class="score-cell-dim">Inflation</span>',
            html,
        )
        self.assertIn("Equal-weight summary is the simple mean", html)
        self.assertIn("Latest component", html)

    def test_no_cards_when_paths_unavailable(self) -> None:
        with patch("scripts.temperature_trends.load_paths", return_value=None):
            html = render_scoreboard(_load_fixture_state(), paths_doc=None)
        self.assertNotIn("temp-cards", html)
        self.assertIn("Equal-weight", html)

    def test_partial_score_state_still_renders_table(self) -> None:
        state = {"countries": {}}
        html = render_scoreboard(state, paths_doc=_empty_paths_doc())
        self.assertIn("data-score-overview", html)
        self.assertIn("Equal-weight", html)


if __name__ == "__main__":
    unittest.main()
