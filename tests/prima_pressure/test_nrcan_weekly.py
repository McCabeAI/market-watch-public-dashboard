"""Offline and live-smoke tests for NRCan weekly national fuel prices."""

from __future__ import annotations

import os
import sys
import unittest
from datetime import date
from pathlib import Path
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.canadian_cpi_release.sources.cache import default_opener
from scripts.canadian_cpi_release.sources.nrcan import (
    NRCAN_WEEKLY_URL_TEMPLATE,
    collect_nrcan,
    collect_nrcan_weekly,
    parse_nrcan_monthly_table,
    parse_nrcan_weekly_table,
    weekly_rows_in_month,
)

_WEEKLY_TABLE_SNIPPET = """
<table>
  <caption>Weekly Average Retail Prices for Regular Gasoline  in 2026</caption>
  <tr><th headers="headerDate">Week Ending</th><th headers="header4_1_1">Price</th></tr>
  <tr>
    <td headers="headerDate empty header1" class="nowrap">2026-10-27</td>
    <td headers="header4_1_1 header3_1 header1">179.5</td>
    <td headers="header5_1_2 header3_1 header1">30.2</td>
    <td headers="header6_1_3 header3_1 header1">15.1</td>
    <td headers="header7_1_4 header3_1 header1">45.7</td>
  </tr>
  <tr>
    <td headers=" headerDate  empty header1 " class="nowrap">2026-11-03</td>
    <td headers="header3_1 header4_1_1 header1">178.6</td>
    <td headers="header5_1_2 header3_1 header1">29.9</td>
    <td headers="header6_1_3 header3_1 header1">14.6</td>
    <td headers="header7_1_4 header3_1 header1">45.0</td>
  </tr>
  <tr>
    <td headers="headerDate empty header1" class="nowrap">2026-11-10</td>
    <td headers="header4_1_1 header3_1 header1">166.1</td>
    <td headers="header5_1_2 header3_1 header1">28.8</td>
    <td headers="header6_1_3 header3_1 header1">13.9</td>
    <td headers="header7_1_4 header3_1 header1">44.3</td>
  </tr>
</table>
"""

_WEEKLY_WITH_FUTURE_SNIPPET = _WEEKLY_TABLE_SNIPPET.replace(
    "</table>",
    """
  <tr>
    <td headers="headerDate empty header1" class="nowrap">2026-11-17</td>
    <td headers="header4_1_1 header3_1 header1">160.0</td>
  </tr>
</table>
""",
)

_MONTHLY_TABLE_SNIPPET = """
<table>
  <tr><td>2026-09</td><td>187.5</td></tr>
  <tr><td>2026-10</td><td>186.2</td></tr>
</table>
"""

_DIESEL_SNIPPET = """
<table>
  <caption>Weekly Average Retail Prices for Diesel  in 2026</caption>
  <tr>
    <td headers="headerDate empty header1">2026-11-10</td>
    <td headers="header4_1_1 header3_1 header1">253.3</td>
    <td headers="header5_1_2 header3_1 header1">29.0</td>
    <td headers="header6_1_3 header3_1 header1">19.5</td>
    <td headers="header7_1_4 header3_1 header1">127.0</td>
  </tr>
</table>
"""


def _weekly_opener(pages: dict[int, bytes], *, fail_product: int | None = None):
    def opener(url: str, timeout=120, data=None, content_type=None):
        if data is not None:
            raise RuntimeError("unexpected post")
        if fail_product is not None and f"productID={fail_product}" in url:
            raise URLError("simulated transport failure")
        for product_id, body in pages.items():
            if f"productID={product_id}" in url:
                return body
        return {"ok": False, "http_status": 404, "body": b"", "url": url, "error": "missing"}

    return opener


def _urllib_bytes_opener(url: str, data=None, timeout=120, content_type=None):
    return default_opener(url, timeout=timeout, data=data, content_type=content_type)["body"]


class ParseNrcanWeeklyTests(unittest.TestCase):
    def test_parse_weekly_headers_and_columns(self) -> None:
        rows = parse_nrcan_weekly_table(_WEEKLY_TABLE_SNIPPET)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[-1]["week_ending"], "2026-11-10")
        self.assertAlmostEqual(rows[-1]["price_cpl"], 166.1)
        self.assertAlmostEqual(rows[-1]["taxes_cpl"], 28.8)
        self.assertAlmostEqual(rows[-1]["marketing_margin_cpl"], 13.9)
        self.assertAlmostEqual(rows[-1]["refining_margin_cpl"], 44.3)

    def test_monthly_html_is_not_parsed_as_weekly(self) -> None:
        weekly_rows = parse_nrcan_weekly_table(_MONTHLY_TABLE_SNIPPET)
        monthly_rows = parse_nrcan_monthly_table(_MONTHLY_TABLE_SNIPPET)
        self.assertEqual(weekly_rows, [])
        self.assertEqual(monthly_rows["2026-09"], 187.5)

    def test_weekly_rows_in_month_filters_period(self) -> None:
        rows = parse_nrcan_weekly_table(_WEEKLY_TABLE_SNIPPET)
        november = weekly_rows_in_month(rows, "2026-11")
        self.assertEqual([row["week_ending"] for row in november], ["2026-11-03", "2026-11-10"])


class CollectNrcanWeeklyTests(unittest.TestCase):
    def test_as_of_drops_future_weeks(self) -> None:
        pages = {
            1: _WEEKLY_WITH_FUTURE_SNIPPET.encode("utf-8"),
            5: _DIESEL_SNIPPET.encode("utf-8"),
        }
        out = collect_nrcan_weekly(
            as_of=date(2026, 11, 10),
            opener=_weekly_opener(pages),
            retrieved_at="2026-11-11T12:00:00Z",
            weeks=13,
        )
        gas_weeks = [row["week_ending"] for row in out["series"]["gasoline_regular"]["observations"]]
        self.assertNotIn("2026-11-17", gas_weeks)
        self.assertEqual(out["series"]["gasoline_regular"]["latest"]["week_ending"], "2026-11-10")

    def test_caption_mismatch_marks_series_unavailable(self) -> None:
        bad = b"<table><caption>Weekly Average Retail Prices for Diesel in 2026</caption></table>"
        pages = {1: bad, 5: _DIESEL_SNIPPET.encode("utf-8")}
        out = collect_nrcan_weekly(
            as_of=date(2026, 11, 11),
            opener=_weekly_opener(pages),
            retrieved_at="2026-11-11T12:00:00Z",
        )
        self.assertEqual(out["status"], "partial")
        self.assertEqual(out["series"]["gasoline_regular"]["status"], "unavailable")
        self.assertEqual(out["series"]["gasoline_regular"]["reason"], "caption_mismatch")
        self.assertEqual(out["series"]["diesel"]["status"], "ok")

    def test_one_product_failure_yields_partial(self) -> None:
        pages = {1: _WEEKLY_TABLE_SNIPPET.encode("utf-8"), 5: _DIESEL_SNIPPET.encode("utf-8")}
        out = collect_nrcan_weekly(
            as_of=date(2026, 11, 11),
            opener=_weekly_opener(pages, fail_product=5),
            retrieved_at="2026-11-11T12:00:00Z",
        )
        self.assertEqual(out["status"], "partial")
        self.assertEqual(out["series"]["gasoline_regular"]["status"], "ok")
        self.assertEqual(out["series"]["diesel"]["status"], "unavailable")

    def test_opener_failure_never_raises(self) -> None:
        def boom(url: str, data=None, timeout=120, content_type=None):
            raise URLError("offline")

        out = collect_nrcan_weekly(
            as_of=date(2026, 11, 11),
            opener=boom,
            retrieved_at="2026-11-11T12:00:00Z",
        )
        self.assertEqual(out["status"], "unavailable")
        self.assertEqual(out["series"]["gasoline_regular"]["status"], "unavailable")
        self.assertEqual(out["series"]["diesel"]["status"], "unavailable")

    def test_monthly_collect_nrcan_signature_unchanged(self) -> None:
        """Regression guard: monthly collector API is still present."""
        self.assertTrue(callable(collect_nrcan))
        self.assertTrue(callable(parse_nrcan_monthly_table))


class LiveNrcanWeeklySmoke(unittest.TestCase):
    def test_live_collect_nrcan_weekly_smoke(self) -> None:
        if os.environ.get("PRIMA_LIVE_SMOKE") != "1":
            self.skipTest("set PRIMA_LIVE_SMOKE=1 to run live NRCan weekly smoke")
        out = collect_nrcan_weekly(
            as_of=date(2026, 11, 11),
            opener=_urllib_bytes_opener,
            retrieved_at="2026-11-11T12:00:00+00:00",
            weeks=13,
        )
        self.assertEqual(out["frequency"], "weekly")
        self.assertEqual(out["geography"], "Canada")
        self.assertEqual(out["location_id"], 66)
        self.assertIn(out["status"], {"ok", "partial"})
        self.assertEqual(
            out["source_url_template"],
            NRCAN_WEEKLY_URL_TEMPLATE,
        )
        gas = out["series"]["gasoline_regular"]
        self.assertEqual(gas["status"], "ok")
        self.assertIn("Regular Gasoline", gas["caption"] or "")
        self.assertIn("Weekly", gas["caption"] or "")
        self.assertGreaterEqual(len(gas["observations"]), 3)
        self.assertEqual(gas["latest"]["week_ending"], gas["observations"][-1]["week_ending"])


if __name__ == "__main__":
    unittest.main()
