"""Issues panel on the Sources & Issues tab."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from scripts.dashboard_repair.sources_view import (
    ISSUES_SLOT,
    inject_issues_panel,
    render_issues_panel,
    render_sources,
    rename_sources_nav_label,
)
from scripts.market_watch_launch.publication_checks import strip_issues_panel
from scripts.market_watch_launch.publication_issues import finalize_feed, make_issue

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PATH = ROOT / "docs/examples/sources_issues_panel.example.html"


def _sample_issues() -> list[dict]:
    return [
        make_issue(
            "tape_stale",
            category="market_data",
            severity="critical",
            component="global_tape",
            country="US",
            cause="Stale September tape value would have been shown",
            impact="Readers could misread prices as current",
            publisher="Treasury",
            url="https://home.treasury.gov/",
            launch_id="mwl-abc",
            ingest_launch_id="mwi-abc",
            phase="final",
            last_verified_vintage="2026-09-08",
            detail="Full diagnostic text for the stale tape row.",
        ),
        make_issue(
            "schedule_gap",
            category="calendar",
            severity="warning",
            component="release_calendar",
            country="CA",
            cause="Official schedule page was empty",
            impact="Some release rows lack a verified clock",
            detail="Fetcher returned zero slots.",
        ),
        make_issue(
            "source_note",
            category="source",
            severity="info",
            component="CME_positioning",
            cause="CME volume feed returned HTTP 403",
            impact="Tape positioning card stays unavailable",
        ),
        make_issue(
            "old_gap",
            category="source",
            severity="warning",
            component="resolved_example",
            state="resolved",
            cause="Prior stage gap",
            impact="Was fixed in a later ingest",
        ),
    ]


def _sample_feed(**overrides) -> dict:
    issues = overrides.pop("issues", None)
    rows = list(issues) if issues is not None else _sample_issues()
    feed = finalize_feed(rows, release={"phase": "final", "launch_id": "mwl-demo"}, inputs=[])
    feed.update(overrides)
    return feed


def _minimal_page() -> str:
    return """<!DOCTYPE html><html><head></head><body>
<header class="topbar"><div class="brand"><b>Market Watch</b></div></header>
<section class="page sources" data-source-health="repair">
""" + ISSUES_SLOT + """</section>
<nav><label for="p-sources">Sources</label></nav>
</body></html>"""


class IssuesPanelTests(unittest.TestCase):
    def test_render_counts_filters_and_rows(self):
        feed = _sample_feed()
        html = render_issues_panel(feed)
        self.assertIn('data-issues-root="rendered"', html)
        self.assertIn("mw-issues-severity", html)
        self.assertIn("mw-issues-category", html)
        self.assertIn("mw-issues-search", html)
        self.assertIn("1 critical", html)
        self.assertIn("Stale September tape", html)
        self.assertIn("Resolved (1)", html)
        self.assertRegex(html, r'data-issue-severity="critical"')
        self.assertIn("Full diagnostic text", html)
        self.assertIn("https://home.treasury.gov/", html)

    def test_zero_active_issues(self):
        feed = _sample_feed(issues=[row for row in _sample_issues() if row.get("state") == "resolved"])
        html = render_issues_panel(feed)
        self.assertIn("No active issues for this edition", html)

    def test_unavailable_feed(self):
        html = render_issues_panel({"status": "unavailable"})
        self.assertIn('data-issues-root="unavailable"', html)

    def test_malformed_rows_skipped(self):
        feed = _sample_feed()
        feed["issues"] = list(feed["issues"]) + [{"id": "x", "severity": "nope"}, "not-a-dict"]
        html = render_issues_panel(feed)
        self.assertNotIn('data-issue-id="x"', html)
        self.assertIn("Stale September tape", html)

    def test_escaping(self):
        feed = _sample_feed(
            issues=[
                make_issue(
                    "xss",
                    category="render",
                    severity="info",
                    component="panel",
                    cause='<script>alert("x")</script>',
                    impact="None",
                    detail="<b>not html</b>",
                )
            ]
        )
        html = render_issues_panel(feed)
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;alert", html)

    def test_inject_idempotent_and_badge(self):
        feed = _sample_feed()
        page = _minimal_page()
        once = inject_issues_panel(page, feed)
        twice = inject_issues_panel(once, feed)
        self.assertEqual(once, twice)
        self.assertIn("mw-issues-badge", once)
        self.assertIn("1 critical issue(s)", once)
        self.assertNotIn("Last refreshed", once)
        self.assertNotIn("Current verified headlines", once)

    def test_badge_removed_without_critical(self):
        feed = _sample_feed(issues=[row for row in _sample_issues() if row.get("severity") != "critical"])
        page = inject_issues_panel(_minimal_page(), _sample_feed())
        cleared = inject_issues_panel(page, feed)
        self.assertNotIn("mw-issues-badge", cleared)

    def test_strip_issues_panel(self):
        feed = _sample_feed()
        html = inject_issues_panel(_minimal_page(), feed)
        stripped = strip_issues_panel(html)
        self.assertNotIn("mw-issues", stripped)
        self.assertNotIn("mw-issues-badge", stripped)

    def test_nav_rename_keeps_id(self):
        page = '<label for="p-sources">Sources</label>'
        once = rename_sources_nav_label(page)
        twice = rename_sources_nav_label(once)
        self.assertEqual(once, twice)
        self.assertIn('for="p-sources"', twice)
        self.assertIn("Sources &amp; Issues", twice)

    def test_render_sources_slot_and_heading(self):
        html = render_sources(None, {"rows": [], "counts": {}})
        self.assertIn("Sources &amp; Issues", html)
        self.assertIn('data-issues-root="pending"', html)
        self.assertIn("once the edition is assembled", html)
        self.assertIn("Sources · provenance and freshness", html)

    def test_example_html_matches_or_regenerates(self):
        from scripts.dashboard_repair.apply import theme_css
        from scripts.dashboard_repair.apply import CSS as REPAIR_CSS

        panel = render_issues_panel(_sample_feed())
        doc = (
            "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>Sources & Issues panel example</title>"
            + theme_css()
            + REPAIR_CSS
            + "</head><body>"
            + panel
            + "</body></html>"
        )
        if os.environ.get("MW_REGENERATE_EXAMPLES") == "1":
            EXAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)
            EXAMPLE_PATH.write_text(doc, encoding="utf-8")
            return
        self.assertTrue(EXAMPLE_PATH.is_file(), f"missing {EXAMPLE_PATH}; set MW_REGENERATE_EXAMPLES=1")
        self.assertEqual(EXAMPLE_PATH.read_text(encoding="utf-8"), doc)


if __name__ == "__main__":
    unittest.main()
