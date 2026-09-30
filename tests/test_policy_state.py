"""Canonical policy state is parsed from official Federal Reserve text."""

from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from scripts.policy_state import (
    acquire_us_decision,
    decision_status,
    latest_fomc_statement_url,
    load_policy_state,
    refresh_policy_state,
    resolve_country,
)

ROOT = Path(__file__).resolve().parents[1]
STATEMENT_URL = "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm"
JULY_URL = "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm"
NOTE_URL = "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a1.htm"

FEED = f"""<?xml version="1.0"?>
<rss><channel>
<item><title>Federal Reserve issues FOMC statement</title>
<link><![CDATA[{JULY_URL}]]></link></item>
<item><title>Federal Reserve Board and Federal Open Market Committee release economic projections from the September 15-16 FOMC meeting</title>
<link><![CDATA[https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916b.htm]]></link></item>
<item><title>Federal Reserve issues FOMC statement</title>
<link><![CDATA[{STATEMENT_URL}]]></link></item>
</channel></rss>
"""

STATEMENT = """
<p class="article__time">September 16, 2026</p>
<p>The Committee decided to raise the target range for the federal funds rate by 1/4 percentage point<strong> </strong>to 3-3/4<strong> </strong>to 4 percent, in support of the dual mandate.</p>
<p><a href="/newsevents/pressreleases/monetary20260916a1.htm">Implementation Note issued September 16, 2026</a></p>
"""

IMPLEMENTATION = """
<p>Effective September 17, 2026, the Federal Open Market Committee directs the Desk to:</p>
<ul><li>Undertake open market operations as necessary to maintain the federal funds rate in a target range of 3-3/4 to 4 percent.</li>
<li>Conduct standing overnight repurchase agreement operations at a rate of 4.0 percent.</li></ul>
"""

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


def _fetch(url: str) -> str:
    if url.endswith("press_monetary.xml"):
        return FEED
    if url == STATEMENT_URL:
        return STATEMENT
    if url == NOTE_URL:
        return IMPLEMENTATION
    raise AssertionError(url)


def _prior_decision(**overrides: object) -> dict:
    decision = {
        "lower": 3.5,
        "upper": 3.75,
        "decision_date": "2026-07-29",
        "effective_date": "2026-07-30",
        "source_name": "Federal Reserve",
        "source_url": JULY_URL,
        "implementation_url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a1.htm",
        "retrieved_at": "2026-07-30T00:00:00Z",
        "status": "current",
        "provenance": "official_fomc_statement",
    }
    decision.update(overrides)
    return decision


class PolicyStateParseTest(unittest.TestCase):
    def test_feed_selects_latest_fomc_statement_not_projections(self) -> None:
        self.assertEqual(latest_fomc_statement_url(FEED), STATEMENT_URL)

    def test_acquire_reads_official_range_and_effective_date(self) -> None:
        decision = acquire_us_decision(_fetch, "2026-09-30T12:00:00Z")
        self.assertEqual(decision["lower"], 3.75)
        self.assertEqual(decision["upper"], 4.0)
        self.assertEqual(decision["decision_date"], "2026-09-16")
        self.assertEqual(decision["effective_date"], "2026-09-17")
        self.assertEqual(decision["source_url"], STATEMENT_URL)
        self.assertEqual(decision["source_name"], "Federal Reserve")
        self.assertEqual(decision["provenance"], "official_fomc_statement")
        self.assertNotIn("SOFR", decision["source_url"])

    def test_newer_decision_supersedes_the_previous_one(self) -> None:
        previous = {
            "schema_version": 1,
            "countries": {"US": {"decisions": [_prior_decision()]}},
        }
        updated = refresh_policy_state(previous, _fetch, NOW)
        decisions = updated["countries"]["US"]["decisions"]
        self.assertEqual(decisions[0]["status"], "superseded")
        self.assertEqual(decisions[0]["lower"], 3.5)
        self.assertEqual(decisions[1]["status"], "current")
        self.assertEqual(decisions[1]["lower"], 3.75)
        self.assertEqual(decision_status(updated, "US", "2026-07-29", date(2026, 9, 30)), "superseded")
        self.assertEqual(decision_status(updated, "US", "2026-09-16", date(2026, 9, 30)), "current")
        standing = resolve_country(updated, "US", date(2026, 9, 30))
        self.assertEqual(standing["decision"]["upper"], 4.0)

    def test_decision_not_yet_effective_does_not_replace_the_standing_rate(self) -> None:
        previous = {
            "schema_version": 1,
            "countries": {"US": {"decisions": [_prior_decision()]}},
        }
        updated = refresh_policy_state(previous, _fetch, NOW)
        standing = resolve_country(updated, "US", date(2026, 9, 16))
        self.assertEqual(standing["status"], "current")
        self.assertEqual(standing["decision"]["decision_date"], "2026-07-29")
        self.assertEqual(decision_status(updated, "US", "2026-09-16", date(2026, 9, 16)), "unavailable")

    def test_standing_decision_stays_current_far_past_the_meeting(self) -> None:
        state = {
            "schema_version": 1,
            "countries": {
                "US": {
                    "decisions": [
                        _prior_decision(
                            lower=3.75,
                            upper=4.0,
                            decision_date="2026-01-16",
                            effective_date="2026-01-17",
                            retrieved_at="2026-01-17T00:00:00Z",
                        )
                    ]
                }
            },
        }
        resolved = resolve_country(state, "US", date(2026, 9, 30))
        self.assertEqual(resolved["status"], "current")
        self.assertEqual(resolved["decision"]["lower"], 3.75)
        self.assertEqual(decision_status(state, "US", "2026-01-16", date(2026, 9, 30)), "current")

    def test_explicit_stale_record_is_not_current_and_does_not_fall_back(self) -> None:
        state = {
            "schema_version": 1,
            "countries": {
                "US": {
                    "decisions": [
                        _prior_decision(),
                        _prior_decision(
                            lower=3.75,
                            upper=4.0,
                            decision_date="2026-09-16",
                            effective_date="2026-09-17",
                            source_url=STATEMENT_URL,
                            status="stale",
                        ),
                    ]
                }
            },
        }
        resolved = resolve_country(state, "US", date(2026, 9, 30))
        self.assertEqual(resolved["status"], "stale")
        self.assertIsNone(resolved["decision"])
        self.assertEqual(decision_status(state, "US", "2026-09-16", date(2026, 9, 30)), "stale")
        self.assertEqual(decision_status(state, "US", "2026-07-29", date(2026, 9, 30)), "superseded")

    def test_failed_refresh_keeps_the_standing_decision(self) -> None:
        previous = {
            "schema_version": 1,
            "countries": {
                "US": {
                    "decisions": [
                        _prior_decision(
                            lower=3.75,
                            upper=4.0,
                            decision_date="2026-09-16",
                            effective_date="2026-09-17",
                            source_url=STATEMENT_URL,
                        )
                    ]
                }
            },
        }

        def news_card(url: str) -> str:
            if url.endswith("press_monetary.xml"):
                return FEED
            return (
                '<article class="news-card" data-date="2026-09-16">'
                "<h3>FOMC raises the federal funds target range to 9.99–9.99%</h3></article>"
            )

        updated = refresh_policy_state(previous, news_card, NOW)
        decision = updated["countries"]["US"]["decisions"][0]
        self.assertEqual(decision["lower"], 3.75)
        self.assertEqual(decision["upper"], 4.0)
        self.assertEqual(decision["status"], "current")
        self.assertTrue(updated["countries"]["US"]["last_refresh_error"])
        self.assertEqual(resolve_country(updated, "US", date(2026, 9, 30))["status"], "current")

    def test_missing_country_and_empty_gap(self) -> None:
        self.assertEqual(resolve_country(None, "US", date(2026, 9, 30))["status"], "missing")
        self.assertEqual(resolve_country({"schema_version": 1, "countries": {}}, "CA", date(2026, 9, 30))["status"], "missing")
        unavailable = resolve_country(
            {"schema_version": 1, "countries": {"CA": {"status": "unavailable", "decisions": []}}},
            "CA",
            date(2026, 9, 30),
        )
        self.assertEqual(unavailable["status"], "unavailable")
        self.assertIsNone(unavailable["decision"])


class CommittedPolicyStateTest(unittest.TestCase):
    def test_canonical_file_has_verified_us_range_and_explicit_gaps(self) -> None:
        state = load_policy_state(ROOT)
        self.assertIsNotNone(state)
        assert state is not None
        us = state["countries"]["US"]["decisions"]
        self.assertEqual(len(us), 1)
        decision = us[0]
        self.assertEqual(decision["lower"], 3.75)
        self.assertEqual(decision["upper"], 4.0)
        self.assertEqual(decision["decision_date"], "2026-09-16")
        self.assertEqual(decision["effective_date"], "2026-09-17")
        self.assertEqual(decision["source_url"], STATEMENT_URL)
        self.assertEqual(decision["source_name"], "Federal Reserve")
        self.assertEqual(decision["status"], "current")
        self.assertNotIn("sofr", json.dumps(decision).lower())
        resolved = resolve_country(state, "US", date(2026, 9, 30))
        self.assertEqual(resolved["status"], "current")
        for code in ("CA", "AU", "NZ", "EA", "JP"):
            block = state["countries"][code]
            self.assertEqual(block["status"], "unavailable", code)
            self.assertEqual(block["decisions"], [], code)
            self.assertTrue(block.get("gap"), code)
            self.assertNotIn("lower", block)
            self.assertNotIn("rate", block)


if __name__ == "__main__":
    unittest.main()
