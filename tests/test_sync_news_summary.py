import unittest

from scripts.sync_news_summary import sync_news_summary


class SyncNewsSummaryTests(unittest.TestCase):
    def test_summary_and_front_alert_track_live_digest(self):
        html = """
        <div class="news-alert market-alert">
          <div class="flag">MARKET NEWS · 7-DAY WINDOW</div>
          <div><h3>Old Sep 8 headline</h3><p>Old Sep 8 summary.</p><span class="alert-sub">Research layer: 19 old items.</span></div>
          <label for="p-news">Open News &amp; Research</label>
        </div>
        <div class="market-news-head">
          <div class="panel">
            <div class="stitle">Market News · 7-day window</div>
            <div class="news-window"><b>Last scanned:</b> 8 Sep 2026 · Sources include Reuters, ABC, AP, FT and verified public X feeds.</div>
          </div>
          <div class="panel"><div class="stitle">Current tape</div><div class="news-count">19</div><p>curated market-relevant stories in the 2–8 September window, ranked by expected rates/FX significance rather than headline volume.</p></div>
        </div>
        <div class="last24-window"><b>Window</b>17 Sep 04:00 ET → 18 Sep 04:00 ET<br>Last refreshed 18 Sep 2026 · 04:00 ET</div>
        <div class="stitle">Top Market Drivers</div><div class="driver-grid">
          <a class="driver-card" href="#"><div class="dmeta"><span class="impact high">HIGH</span>US · FED</div><b>Fed move is the lead driver</b><span>Fed summary.</span></a>
          <a class="driver-card" href="#"><div class="dmeta"><span class="impact high">HIGH</span>GLOBAL · BOJ</div><b>BoJ broadens tightening</b><span>BoJ summary.</span></a>
        </div>
        <div class="digest-tools"><div class="scanline"><b>Window:</b> 11 Sep 04:00 ET → 18 Sep 04:00 ET</div></div>
        <div class="news-digest">
          <details class="story"></details>
          <details class="story"></details>
          <details class="story"></details>
        </div>
        """
        out = sync_news_summary(html)
        self.assertIn("<b>Last scanned:</b> 18 Sep 2026", out)
        self.assertIn('<div class="news-count">3</div>', out)
        self.assertIn(
            "curated market-relevant stories in the 11–18 September 2026 window",
            out,
        )
        self.assertIn("<h3>Fed move is the lead driver</h3>", out)
        self.assertIn("<b>BoJ broadens tightening:</b> BoJ summary.", out)
        self.assertIn(
            "3 qualifying events in the current 11–18 September 2026 digest · Last scanned 18 Sep 2026.",
            out,
        )
        self.assertNotIn("<b>Last scanned:</b> 8 Sep 2026", out)
        self.assertNotIn('<div class="news-count">19</div>', out)
        self.assertNotIn("Old Sep 8 headline", out)

    def test_rejects_mismatched_refresh_dates(self):
        html = """
        <div class="news-window"><b>Last scanned:</b> 8 Sep 2026 · Sources include Reuters.</div>
        <div class="stitle">Current tape</div><div class="news-count">19</div><p>curated market-relevant stories in the 2–8 September window, ranked by expected rates/FX significance rather than headline volume.</p>
        Last refreshed 17 Sep 2026 · 04:00 ET
        <div class="scanline"><b>Window:</b> 11 Sep 04:00 ET → 18 Sep 04:00 ET</div>
        <details class="story"></details>
        """
        with self.assertRaises(ValueError):
            sync_news_summary(html)


if __name__ == "__main__":
    unittest.main()
