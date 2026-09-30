"""Policy / Transmission reads canonical policy state, not rendered news cards."""

from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from scripts.country_detail.policy_rate import policy_clause, rewrite_policy_transmission
from scripts.policy_state import load_policy_state

ROOT = Path(__file__).resolve().parents[1]
STATEMENT_URL = "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm"

NEWS_CARD = """<article class="news-card n-us new" data-date="2026-09-16">
<div class="news-meta"><span><b>US</b> · Federal Reserve</span><span>Sep 16 · Policy Decision</span></div>
<h3>FOMC raises the federal funds target range to 9.99–9.99%</h3>
<p>This card is presentation and must not set the policy rate.</p>
<a class="news-link" href="https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm" rel="noopener" target="_blank">Open official source ↗</a>
</article>"""

PANELS = """
<div class="panel"><div class="stitle">Policy / Transmission</div><p>Fed target range: 3.50–3.75%. The mix is still restrictive.</p></div>
<div class="panel"><div class="stitle">Policy / Transmission</div><p>BoC target overnight rate: 2.25%. Core inflation is near target.</p></div>
<div class="panel"><div class="stitle">Policy / Transmission</div><p>RBA cash rate: 4.35%. Underlying inflation is still hot.</p></div>
<div class="panel"><div class="stitle">Policy / Transmission</div><p>RBNZ raised the OCR to 2.75%. The policy response is aimed at second-round inflation risk.</p></div>
"""


def _us_decision(**overrides: object) -> dict:
    decision = {
        "lower": 3.75,
        "upper": 4.0,
        "decision_date": "2026-09-16",
        "effective_date": "2026-09-17",
        "source_name": "Federal Reserve",
        "source_url": STATEMENT_URL,
        "implementation_url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a1.htm",
        "retrieved_at": "2026-09-30T12:00:00Z",
        "status": "current",
        "provenance": "official_fomc_statement",
    }
    decision.update(overrides)
    return decision


def _state(*decisions: dict, countries: dict | None = None) -> dict:
    body = {
        "schema_version": 1,
        "countries": {
            "US": {"central_bank": "Federal Reserve", "decisions": list(decisions)},
            "CA": {"status": "unavailable", "decisions": [], "gap": "no target series"},
            "AU": {"status": "unavailable", "decisions": [], "gap": "no target series"},
            "NZ": {"status": "unavailable", "decisions": [], "gap": "no target series"},
            "EA": {"status": "unavailable", "decisions": [], "gap": "no target series"},
            "JP": {"status": "unavailable", "decisions": [], "gap": "no target series"},
        },
    }
    if countries:
        body["countries"].update(countries)
    return body


def _us_panel(page: str) -> str:
    start = page.find("Fed target range:")
    end = page.find("</p>", start)
    return page[start:end]


class PolicyRateWiringTest(unittest.TestCase):
    def test_module_does_not_parse_presentation_or_hard_code_a_rate(self) -> None:
        source = (ROOT / "scripts" / "country_detail" / "policy_rate.py").read_text(encoding="utf-8")
        self.assertNotIn("news-card", source)
        self.assertNotIn("findall", source)
        self.assertNotIn("3.75", source)
        self.assertNotIn("4.00", source)
        self.assertNotIn("POLICY_MAX_AGE", source)

    def test_current_fed_decision_replaces_stale_range(self) -> None:
        state = _state(_us_decision())
        html = rewrite_policy_transmission(NEWS_CARD + PANELS, policy_state=state, as_of=date(2026, 9, 30))
        panel = _us_panel(html)
        self.assertIn("3.75%-4.00%", panel)
        self.assertIn("monetary20260916a.htm", panel)
        self.assertIn("16 Sep 2026", panel)
        self.assertIn("17 Sep 2026", panel)
        self.assertNotIn("3.50", panel)
        self.assertNotIn("9.99", panel)
        self.assertNotIn("3.50–3.75", html)
        again = rewrite_policy_transmission(html, policy_state=state, as_of=date(2026, 9, 30))
        self.assertEqual(again, html)

    def test_clause_renders_without_any_page_markup(self) -> None:
        clause = policy_clause("US", _state(_us_decision()), date(2026, 9, 30))
        self.assertIn("3.75%-4.00%", clause)
        self.assertIn(STATEMENT_URL, clause)
        self.assertNotIn("<article", clause)

    def test_news_card_cannot_fill_a_missing_record(self) -> None:
        html = rewrite_policy_transmission(NEWS_CARD + PANELS, policy_state=None, as_of=date(2026, 9, 30))
        panel = _us_panel(html)
        self.assertIn("missing", panel)
        self.assertNotIn("3.50", panel)
        self.assertNotIn("3.75%", panel)
        self.assertNotIn("9.99", panel)
        self.assertNotIn("4.00%", panel)

    def test_old_standing_decision_is_still_current(self) -> None:
        state = _state(
            _us_decision(
                decision_date="2026-01-16",
                effective_date="2026-01-17",
                retrieved_at="2026-01-17T00:00:00Z",
            )
        )
        panel = _us_panel(
            rewrite_policy_transmission(PANELS, policy_state=state, as_of=date(2026, 9, 30))
        )
        self.assertIn("3.75%-4.00%", panel)
        self.assertNotIn("stale", panel)
        self.assertIn("16 Jan 2026", panel)

    def test_superseded_decision_is_not_the_rate_shown(self) -> None:
        state = _state(
            _us_decision(
                lower=3.5,
                upper=3.75,
                decision_date="2026-07-29",
                effective_date="2026-07-30",
                source_url="https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm",
            ),
            _us_decision(),
        )
        panel = _us_panel(
            rewrite_policy_transmission(PANELS, policy_state=state, as_of=date(2026, 9, 30))
        )
        self.assertIn("3.75%-4.00%", panel)
        self.assertNotIn("3.50%", panel)
        self.assertNotIn("monetary20260729a.htm", panel)

    def test_stale_record_is_not_shown_as_current(self) -> None:
        state = _state(_us_decision(status="stale"))
        panel = _us_panel(
            rewrite_policy_transmission(PANELS, policy_state=state, as_of=date(2026, 9, 30))
        )
        self.assertIn("stale", panel)
        self.assertNotIn("3.75%-4.00%", panel)
        self.assertNotIn("3.50", panel)

    def test_unavailable_and_other_hard_coded_rates_are_not_left_as_current(self) -> None:
        state = _state()
        state["countries"]["US"] = {"status": "unavailable", "decisions": []}
        html = rewrite_policy_transmission(PANELS, policy_state=state, as_of=date(2026, 9, 30))
        panel = _us_panel(html)
        self.assertIn("unavailable", panel)
        self.assertNotIn("3.50", panel)
        self.assertNotIn("3.75%", panel)
        self.assertNotIn("2.25%", html)
        self.assertNotIn("4.35%", html)
        self.assertNotIn("2.75%", html)
        self.assertIn("Bank of Canada", html)
        self.assertIn("Reserve Bank of Australia", html)
        self.assertIn("Reserve Bank of New Zealand", html)
        self.assertIn("Core inflation is near target", html)
        self.assertIn("second-round inflation risk", html)

    def test_board_badges_and_matrix_cells_do_not_keep_hard_coded_rates(self) -> None:
        page = (
            '<span class="policy">Fed 3.50–3.75%</span>'
            '<span class="policy">BoC 2.25%</span>'
            '<tr><td><b>CA</b></td><td>Trim 1.9%</td><td>2.25%</td><td>Softening</td></tr>'
            '<article class="news-card"><h3>BoC holds 2.25%</h3></article>'
        )
        html = rewrite_policy_transmission(
            page,
            policy_state=_state(_us_decision()),
            as_of=date(2026, 9, 30),
        )
        self.assertIn('class="policy">Fed 3.75%-4.00%', html)
        self.assertIn('class="policy">BoC unavailable', html)
        self.assertIn("<td>unavailable</td>", html)
        self.assertIn("BoC holds 2.25%", html)
        self.assertNotIn("3.50", html)
        again = rewrite_policy_transmission(html, policy_state=_state(_us_decision()), as_of=date(2026, 9, 30))
        self.assertEqual(again, html)

    def test_committed_state_renders_the_verified_us_range(self) -> None:
        state = load_policy_state(ROOT)
        clause = policy_clause("US", state, date(2026, 9, 30))
        self.assertIn("3.75%-4.00%", clause)
        self.assertIn("Federal Reserve", clause)
        self.assertIn(STATEMENT_URL, clause)
        for code in ("CA", "AU", "NZ", "EA", "JP"):
            text = policy_clause(code, state, date(2026, 9, 30))
            self.assertIn("unavailable", text)
            self.assertNotIn("%", text.split(":", 1)[1])


if __name__ == "__main__":
    unittest.main()
