"""Tape publication checks refuse missing provenance, never a printed number."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from scripts.dashboard_repair.tape import render_tape
from scripts.market_watch_launch.publication_checks import (
    PublicationIntegrityError,
    check_no_stale_tape,
    check_repaired_tape,
)

REPO = Path(__file__).resolve().parents[1]
FORMER_BLACKLIST = ("4.79%", "1.3790", "0.7210", "0.58755", "98.83", "$92.33", "$97.23")


def _packet(*, yield_value: float = 4.79, rate_status: str = "ok", as_of: str = "2026-11-19") -> dict:
    return {
        "generated_at": "2026-11-19T21:00:00Z",
        "status": "ok",
        "rates": {
            "US": {
                "status": rate_status,
                "latest_observation": as_of,
                "tenors": {"10Y": {"value": yield_value, "as_of": as_of, "bp_1d": -3.0}},
            }
        },
        "sources": {
            "US_rates": {
                "name": "U.S. Treasury daily par yield curve",
                "url": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve",
                "status": rate_status,
                "observation_date": as_of,
            },
            "FX": {
                "name": "ECB euro foreign exchange reference rates",
                "url": "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html",
                "status": "ok",
            },
        },
        "fx": {
            "status": "ok",
            "source_observation": as_of,
            "pairs": {
                "USDCAD": {"spot": 1.3790, "as_of": as_of, "ret_1d": 0.1, "status": "ok"},
                "AUDUSD": {"spot": 0.7210, "as_of": as_of, "ret_1d": -0.2, "status": "ok"},
                "NZDUSD": {"spot": 0.58755, "as_of": as_of, "ret_1d": 0.05, "status": "ok"},
            },
        },
        "cross_assets": {"series": {}},
    }


def _page(packet: dict) -> str:
    return render_tape(packet) + '<div data-score-overview="calibrated"></div>'


def _present_sourced_us10y(html: str, value: str) -> str:
    """Put a sourced official-close US 10Y print on an existing repaired card."""
    opener = re.search(r'<div class="tape-card" data-tape="US10Y" data-tape-status="[^"]*">', html)
    if opener is None:
        raise AssertionError("repaired US10Y card missing")
    start = opener.start()
    next_card = html.find('<div class="tape-card"', opener.end())
    end = next_card if next_card >= 0 else len(html)
    segment = html[start:end]
    segment = re.sub(
        r'<div class="tape-card" data-tape="US10Y" data-tape-status="[^"]*">',
        '<div class="tape-card" data-tape="US10Y" data-tape-status="ok">',
        segment,
        count=1,
    )
    segment = re.sub(r'(<div class="val[^"]*">)[^<]*', rf"\g<1>{value}", segment, count=1)
    segment = re.sub(r'(<div class="mw-asof">)[^<]*', r"\g<1>19 Nov 2026", segment, count=1)
    segment = re.sub(r'(<span class="mw-chip[^"]*">)[^<]*', r"\g<1>Official close", segment, count=1)
    if "<summary>Source</summary>" not in segment:
        segment = segment.replace(
            "</div>",
            '<details class="tape-more"><summary>Source</summary><p>U.S. Treasury daily par yield. Observation 2026-11-19.</p></details></div>',
            1,
        )
    return html[:start] + segment + html[end:]


class RepairedTapeChecks(unittest.TestCase):
    def test_sourced_us10y_equal_to_a_former_blacklist_value_publishes(self) -> None:
        page = _page(_packet())
        self.assertIn(">4.79%</div>", page)
        self.assertIn('data-tape="US10Y"', page)
        self.assertIn('data-tape-status="ok"', page)
        self.assertIn("Official close", page)
        self.assertIn("2026-11-19", page)
        check_repaired_tape(page)
        check_no_stale_tape(page)

    def test_former_blacklist_strings_inside_a_sourced_card_do_not_veto(self) -> None:
        page = _page(_packet())
        note = " ".join(FORMER_BLACKLIST)
        stamped = page.replace("<summary>Source</summary>", f"<summary>Source</summary>{note}", 1)
        for literal in FORMER_BLACKLIST:
            self.assertIn(literal, stamped)
        check_repaired_tape(stamped)

    def test_stale_labeled_us10y_publishes(self) -> None:
        page = _page(_packet(rate_status="stale", as_of="2026-09-08"))
        self.assertIn(">4.79%</div>", page)
        self.assertIn(">Stale</span>", page)
        check_repaired_tape(page)

    def test_stale_card_without_the_stale_chip_is_refused(self) -> None:
        page = _page(_packet(rate_status="stale", as_of="2026-09-08"))
        stripped = page.replace(">Stale</span>", ">Official close</span>", 1)
        with self.assertRaises(PublicationIntegrityError) as ctx:
            check_repaired_tape(stripped)
        self.assertEqual(ctx.exception.reason, "stale_tape_unlabeled")
        self.assertNotEqual(ctx.exception.reason, "stale_tape_value")

    def test_unlabeled_september_card_is_refused_without_reading_the_number(self) -> None:
        page = (
            '<div class="mw-tape" data-global-tape="repair">'
            '<div class="tape-card"><div class="lab">US 10Y</div><div class="val">4.79%</div></div>'
            "</div>"
            '<div data-score-overview="calibrated"></div>'
        )
        with self.assertRaises(PublicationIntegrityError) as ctx:
            check_repaired_tape(page)
        self.assertEqual(ctx.exception.reason, "tape_card_missing_provenance")

    def test_missing_repaired_tape_is_refused(self) -> None:
        page = '<div class="tape"><div class="val">4.79%</div></div><div data-score-overview="calibrated"></div>'
        with self.assertRaises(PublicationIntegrityError) as ctx:
            check_repaired_tape(page)
        self.assertEqual(ctx.exception.reason, "repaired_tape_missing")

    def test_ok_card_without_an_observation_date_is_refused(self) -> None:
        page = _page(_packet())
        stripped = page.replace(
            '<div class="mw-asof">19 Nov 2026</div>',
            '<div class="mw-asof">date missing</div>',
            1,
        )
        self.assertIn("date missing", stripped)
        with self.assertRaises(PublicationIntegrityError) as ctx:
            check_repaired_tape(stripped)
        self.assertEqual(ctx.exception.reason, "tape_as_of_missing")

    def test_check_module_has_no_exact_price_blacklist(self) -> None:
        source = (REPO / "scripts" / "market_watch_launch" / "publication_checks.py").read_text(encoding="utf-8")
        self.assertNotIn("STALE_TAPE_VALUES", source)
        self.assertNotIn("stale_tape_value", source)
        for literal in FORMER_BLACKLIST:
            self.assertNotIn(literal, source)


if __name__ == "__main__":
    unittest.main()
