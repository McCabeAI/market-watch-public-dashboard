"""Presentation tests for releases, sources, and theme.css. No network."""

from __future__ import annotations

import re
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.dashboard_repair.calendar_view import build_release_model, render_releases
from scripts.dashboard_repair.source_health import build_source_health_snapshot
from scripts.dashboard_repair.sources_view import render_sources

ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 10, 22, 12, 0, tzinfo=ET)
THEME = ROOT / "scripts/dashboard_repair/theme.css"


def _series(series_id: str, **extra) -> dict:
    country, dimension, component = series_id.split(".")
    row = {
        "id": series_id,
        "country": country,
        "dimension": dimension,
        "component": component,
        "role": "scored",
        "weight": 1,
        "canonical_name": component,
        "publisher": "Publisher",
        "cadence": "monthly",
        "timezone": "America/New_York",
        "release_rule": {"kind": "country_local_schedule_required", "timezone": "America/New_York", "dates": []},
        "freshness_state": "pending_daily_check",
        "verification_state": "held_in_temperature_history",
    }
    row.update(extra)
    return row


class ReleasesPresentationTests(unittest.TestCase):
    def test_unknown_dates_stay_unavailable_in_render(self):
        model = build_release_model(
            NOW,
            series=[_series("US.Inflation.core_pce")],
            score_as_of="2026-09-21",
        )
        html = render_releases(model)
        self.assertIn("date unavailable", html)

    def test_compact_row_keeps_feed_and_provenance_collapsed(self):
        model = build_release_model(NOW, score_as_of="2026-09-21")
        html = render_releases(model)
        self.assertIn("Feeds score:", html)
        self.assertIn("Provenance and score context", html)
        self.assertIn("standing", html.lower())


class SourcesPresentationTests(unittest.TestCase):
    def test_status_chips_use_human_labels_and_bucket_sum(self):
        series = [
            _series("US.Labor.wages", weight=0.2),
            _series("US.Inflation.core_pce"),
            _series("CA.Labor.unemployment", weight=0.7),
        ]
        ingest = {
            "launch_id": "mwl-test",
            "checked_at": "2026-10-22T11:09:51Z",
            "stage_status": "succeeded",
            "source": "fixture",
            "rows": [
                {
                    "series_id": "US.Labor.wages",
                    "status": "new_observation",
                    "observation_period": "2026-09",
                    "error": None,
                },
                {
                    "series_id": "US.Inflation.core_pce",
                    "status": "source_failed",
                    "observation_period": "2026-07",
                    "error": "The read operation timed out after 30 seconds while contacting upstream",
                    "source_health": {
                        "carried_forward": True,
                        "retrieved_at": "2026-09-21T14:41:19Z",
                        "fetch_status": "source_failed",
                    },
                },
            ],
        }
        snapshot = build_source_health_snapshot(series, ingest, None)
        html = render_sources(None, snapshot)
        self.assertIn("Checked ·", html)
        self.assertIn("Failure ·", html)
        self.assertIn("Not checked ·", html)
        self.assertIn("date unavailable", html)
        bucket_total = sum(
            snapshot["counts"][name]
            for name in ("checked", "failure", "blocked", "partial", "not_checked", "not_applicable")
        )
        self.assertEqual(bucket_total, len(snapshot["rows"]))
        self.assertNotIn("carried_forward:", html)
        self.assertIn("Stage check", html)
        self.assertNotIn("new_observation", html.split("Stage ledger notes")[0])
        self.assertRegex(html, r"<details[^>]*class=\"[^\"]*mw-raw")
        self.assertNotRegex(
            html,
            r"The read operation timed out after 30 seconds while contacting upstream</li>",
        )

    def test_empty_ledger_shows_not_checked_wording(self):
        snapshot = build_source_health_snapshot([_series("US.Inflation.core_pce")], None, None)
        html = render_sources(None, snapshot)
        self.assertIn("not checked", html.lower())
        self.assertIn("No succeeded Stage 01", html)


class ThemeCssTests(unittest.TestCase):
    def test_theme_has_tokens_focus_and_print(self):
        css = THEME.read_text(encoding="utf-8")
        self.assertIn(":root", css)
        self.assertIn("--mw-bg", css)
        self.assertIn(":focus-visible", css)
        self.assertIn("@media print", css)

    def test_theme_labels_avoid_live_wording(self):
        css = THEME.read_text(encoding="utf-8")
        self.assertNotRegex(css, r"\blive\b", msg="theme.css should not use 'live' in labels")


if __name__ == "__main__":
    unittest.main()
