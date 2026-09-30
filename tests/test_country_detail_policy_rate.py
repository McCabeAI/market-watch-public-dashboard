"""Policy / Transmission uses the accepted official decision, not a hard-coded range."""

from __future__ import annotations

import unittest
from datetime import date

from scripts.country_detail.policy_rate import rewrite_policy_transmission

FOMC_CARD = """<article class="news-card n-us new" data-date="2026-09-16">
<div class="news-meta"><span><b>US</b> · Federal Reserve</span><span>Sep 16 · Policy Decision</span></div>
<h3>FOMC raises the federal funds target range to 3.75–4.00%</h3>
<p>The Committee voted unanimously for a 25bp increase.</p>
<a class="news-link" href="https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm" rel="noopener" target="_blank">Open official source ↗</a>
</article>"""

PANELS = """
<div class="panel"><div class="stitle">Policy / Transmission</div><p>Fed target range: 3.50–3.75%. The mix is still restrictive.</p></div>
<div class="panel"><div class="stitle">Policy / Transmission</div><p>BoC target overnight rate: 2.25%. Core inflation is near target.</p></div>
<div class="panel"><div class="stitle">Policy / Transmission</div><p>RBA cash rate: 4.35%. Underlying inflation is still hot.</p></div>
<div class="panel"><div class="stitle">Policy / Transmission</div><p>RBNZ raised the OCR to 2.75%. The policy response is aimed at second-round inflation risk.</p></div>
"""


def _us_panel(html: str) -> str:
    start = html.find("Fed target range:")
    end = html.find("</p>", start)
    return html[start:end]


class PolicyRateWiringTest(unittest.TestCase):
    def test_current_fed_decision_replaces_stale_range(self) -> None:
        html = rewrite_policy_transmission(
            FOMC_CARD + PANELS,
            as_of=date(2026, 9, 30),
        )
        panel = _us_panel(html)
        self.assertIn("3.75%-4.00%", panel)
        self.assertIn("monetary20260916a.htm", panel)
        self.assertIn("16 Sep 2026", panel)
        self.assertNotIn("3.50", panel)
        self.assertNotIn("3.50–3.75", html)
        again = rewrite_policy_transmission(html, as_of=date(2026, 9, 30))
        self.assertEqual(again, html)

    def test_missing_decision_is_unavailable(self) -> None:
        html = rewrite_policy_transmission(PANELS, as_of=date(2026, 9, 30))
        panel = _us_panel(html)
        self.assertIn("unavailable", panel)
        self.assertNotIn("3.50", panel)
        self.assertNotIn("3.75%", panel)
        self.assertNotIn("4.00%", panel)

    def test_old_decision_is_stale_and_not_shown_as_current(self) -> None:
        old = FOMC_CARD.replace('data-date="2026-09-16"', 'data-date="2026-01-01"')
        html = rewrite_policy_transmission(old + PANELS, as_of=date(2026, 9, 30))
        panel = _us_panel(html)
        self.assertIn("stale", panel)
        self.assertNotIn("3.75%-4.00%", panel)
        self.assertNotIn("3.50", panel)

    def test_other_hard_coded_policy_rates_are_not_left_as_current(self) -> None:
        html = rewrite_policy_transmission(PANELS, as_of=date(2026, 9, 30))
        self.assertNotIn("2.25%", html)
        self.assertNotIn("4.35%", html)
        self.assertNotIn("2.75%", html)
        self.assertIn("Bank of Canada", html)
        self.assertIn("Reserve Bank of Australia", html)
        self.assertIn("Reserve Bank of New Zealand", html)
        self.assertIn("Core inflation is near target", html)
        self.assertIn("second-round inflation risk", html)


if __name__ == "__main__":
    unittest.main()
