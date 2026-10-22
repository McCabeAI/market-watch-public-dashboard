"""Focused checks for the public dashboard repair. No network."""

from __future__ import annotations

import base64
import gzip
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.apply_six_economy_dashboard import apply_six_economy_dashboard
from scripts.dashboard_repair.apply import apply_dashboard_repair, load_scores, render_debate_html
from scripts.dashboard_repair.calendar_view import build_release_model
from scripts.dashboard_repair.official_schedule import parse_abs_future_releases, parse_stats_nz_next_release
from scripts.dashboard_repair.scoreboard import score_cards
from scripts.dashboard_repair.source_health import build_source_health_snapshot, load_latest_ingest
from scripts.dashboard_repair.tape import tape_cards
from scripts.temperature_level import display_score

ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 10, 22, 12, 0, tzinfo=ET)


def _packet() -> dict:
    return {
        "generated_at": "2026-10-22T14:00:00Z",
        "status": "ok",
        "rates": {
            "US": {
                "status": "ok",
                "latest_observation": "2026-10-21",
                "tenors": {"10Y": {"value": 5.13, "as_of": "2026-10-21", "bp_1d": 1.5}},
            }
        },
        "sources": {
            "US_rates": {
                "name": "U.S. Treasury daily par yield curve",
                "url": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve",
                "status": "ok",
                "observation_date": "2026-10-21",
            },
            "FX": {
                "name": "ECB euro foreign exchange reference rates",
                "url": "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html",
                "status": "ok",
                "observation_date": "2026-10-21",
            },
        },
        "fx": {
            "status": "ok",
            "source_observation": "2026-10-21",
            "pairs": {
                "USDCAD": {"spot": 1.3812, "as_of": "2026-10-21", "ret_1d": -0.12},
                "AUDUSD": {"spot": 0.6644, "as_of": "2026-10-21", "ret_1d": 0.2},
                "NZDUSD": {"spot": 0.5921, "as_of": "2026-10-21", "ret_1d": None},
            },
        },
        "cross_assets": {
            "series": {
                "WTI": {
                    "status": "stale",
                    "value": 78.25,
                    "as_of": "2026-10-16",
                    "unit": "USD/bbl",
                    "label": "WTI futures",
                    "source": "Yahoo Finance",
                    "symbol": "CL=F",
                    "url": "https://finance.yahoo.com/quote/CL=F/history/",
                },
                "BRENT": {"status": "unavailable", "value": None, "error": "source failed", "unit": "USD/bbl"},
                "SP500": {
                    "status": "ok",
                    "value": 6730.5,
                    "as_of": "2026-10-21",
                    "unit": "index",
                    "label": "S&P 500",
                    "source": "FRED",
                    "symbol": "SP500",
                    "url": "https://fred.stlouisfed.org/series/SP500",
                },
            }
        },
    }


FIXTURE = """<!DOCTYPE html><html><head><style></style></head><body>
<input checked id="p-front" name="page" type="radio"/>
<input id="p-country" name="page" type="radio"/>
<input id="p-feed" name="page" type="radio"/>
<input id="p-news" name="page" type="radio"/>
<input id="p-relative" name="page" type="radio"/>
<input id="p-releases" name="page" type="radio"/>
<input id="p-sources" name="page" type="radio"/>
<input id="p-marketdata" name="page" type="radio"/>
<input id="p-traderbook" name="page" type="radio"/>
<input id="p-traderroom" name="page" type="radio"/>
<input checked id="c-us" name="country" type="radio"/>
<input id="c-ca" name="country" type="radio"/>
<input id="c-au" name="country" type="radio"/>
<input id="c-nz" name="country" type="radio"/>
<input id="c-ea" name="country" type="radio"/>
<input id="c-jp" name="country" type="radio"/>
<div class="app"><nav class="nav">
<label for="p-front">Front Page</label><label for="p-country">Country Detail</label><label for="p-marketdata">Market Data</label><label for="p-feed">Feed &amp; Momentum</label><label for="p-news">News &amp; Research</label><label for="p-relative">Relative</label><label for="p-releases">Releases</label><label for="p-sources">Sources</label><label for="p-traderbook">Trader Book</label><label for="p-traderroom">Trader Room</label>
</nav><main>
<section class="page front">
<div class="stitle">Global Tape · Sep 8 public snapshot</div>
<div class="tape">
<div class="tape-card"><div class="lab">USDCAD</div><div class="val">1.3790</div></div>
<div class="tape-card"><div class="lab">AUDUSD</div><div class="val">0.7210</div></div>
<div class="tape-card"><div class="lab">NZDUSD</div><div class="val">0.58755</div></div>
<div class="tape-card"><div class="lab">DXY</div><div class="val">98.83</div></div>
<div class="tape-card"><div class="lab">WTI</div><div class="val">$92.33</div></div>
<div class="tape-card"><div class="lab">Brent</div><div class="val">$97.23</div></div>
<div class="tape-card"><div class="lab">US 10Y</div><div class="val">4.79%</div></div>
<div class="tape-card"><div class="lab">S&amp;P 500</div><div class="val">-0.33%</div></div>
<div class="tape-card"><div class="lab">Copper</div><div class="val">$14,728/t</div></div>
</div>
<div data-score-overview="live"><b>Live 1–100 Score Board</b><div>Inf 63.1</div></div>
<label class="jump" for="c-us">Open US detail</label>
<label class="jump" for="c-ca">Open Canada detail</label>
<label class="jump" for="c-au">Open Australia detail</label>
<label class="jump" for="c-nz">Open NZ detail</label>
<label class="jump" for="c-ea">Open EA detail</label>
<label class="jump" for="c-jp">Open JP detail</label>
<div class="stitle">Momentum Watch</div>
<div class="stitle" style="margin-top:10px">Next Catalysts</div>
<div class="catalysts"><div class="cat"><b>Sep 10</b>US PPI</div></div>
</section>
<section class="page country"><div class="country-switch"><label for="c-us">United States</label><label for="c-ca">Canada</label><label for="c-au">Australia</label><label for="c-nz">New Zealand</label><label for="c-ea">Euro Area</label><label for="c-jp">Japan</label></div></section>
<section class="page feed">FEED PAGE</section>
<section class="page news">NEWS PAGE</section>
<section class="page marketdata">Market Data · official snapshot</section>
<section class="page traderbook"><div class="stitle">Trader Book · paper P&amp;L</div><div id="trader-book-root"></div></section>
<section class="page traderroom">Trader Room · adversarial ideas</section>
<section class="page relative">RELATIVE PAGE</section>
<section class="page releases"><div>Sep 4 Nonfarm payrolls +162k</div></section>
<section class="page sources"><p>The tape is a dated Sep 8 public snapshot</p></section>
<div class="footer"></div>
</main></div></body></html>
"""


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


class TapeTests(unittest.TestCase):
    def test_us_10y_uses_packet_percent_points_and_date(self):
        cards = {card["key"]: card for card in tape_cards(_packet())}
        self.assertEqual(cards["US10Y"]["value"], "5.13%")
        self.assertIn("2026-10-21", cards["US10Y"]["detail"])
        self.assertIn("par yield", cards["US10Y"]["detail"])
        self.assertNotIn("4.79", cards["US10Y"]["value"])
        self.assertEqual(cards["USDCAD"]["value"], "1.3812")
        self.assertEqual(cards["WTI"]["status"], "stale")
        self.assertIn("Stale", cards["WTI"]["detail"])
        self.assertIn("$78.25/bbl", cards["WTI"]["value"])
        self.assertEqual(cards["BRENT"]["value"], "unavailable")
        self.assertEqual(cards["COPPER"]["value"], "unavailable")
        self.assertNotIn("DXY", cards)

    def test_missing_packet_and_decimal_yield_do_not_invent_a_quote(self):
        missing = {card["key"]: card for card in tape_cards(None)}
        for key, _label in (
            ("USDCAD", ""),
            ("AUDUSD", ""),
            ("NZDUSD", ""),
            ("US10Y", ""),
            ("WTI", ""),
            ("BRENT", ""),
            ("SP500", ""),
            ("COPPER", ""),
        ):
            self.assertEqual(missing[key]["value"], "unavailable", key)
            self.assertNotIn("4.79", missing[key]["detail"])
        packet = _packet()
        packet["rates"]["US"]["tenors"]["10Y"]["value"] = 0.0513
        refused = {card["key"]: card for card in tape_cards(packet)}["US10Y"]
        self.assertEqual(refused["value"], "unavailable")
        self.assertNotEqual(refused["value"], "5.13%")
        self.assertIn("not rescaled", refused["detail"])

    def test_stale_rate_keeps_the_dated_print(self):
        packet = _packet()
        packet["rates"]["US"]["status"] = "stale"
        packet["rates"]["US"]["tenors"]["10Y"]["value"] = 4.79
        packet["rates"]["US"]["tenors"]["10Y"]["as_of"] = "2026-09-08"
        card = {item["key"]: item for item in tape_cards(packet)}["US10Y"]
        self.assertEqual(card["value"], "4.79%")
        self.assertEqual(card["status"], "stale")
        self.assertIn("2026-09-08", card["detail"])
        self.assertIn("Stale", card["detail"])


class ScoreboardTests(unittest.TestCase):
    def test_cards_match_score_state_and_separate_impulse_from_level(self):
        state = load_scores()
        cards = {card["country"]: card for card in score_cards(state)}
        us = cards["US"]["dimensions"]
        inflation = next(row for row in us if row["dimension"] == "Inflation")
        labor = next(row for row in us if row["dimension"] == "Labor")
        self.assertEqual(inflation["level_text"], display_score(state["countries"]["US"]["Inflation"]["level"]))
        self.assertEqual(inflation["klass"], "warm")
        self.assertEqual(inflation["direction"], "static")
        self.assertEqual(labor["direction"], "cooling")
        self.assertNotEqual(labor["klass"], "cooling")
        partial = [
            (country, row)
            for country, card in cards.items()
            for row in card["dimensions"]
            if row["coverage"] is not None and row["coverage"] < 1
        ]
        self.assertTrue(partial)


class CalendarTests(unittest.TestCase):
    def test_empty_dates_stay_unavailable(self):
        model = build_release_model(
            NOW,
            series=[_series("US.Inflation.core_pce"), _series("CA.Labor.unemployment", weight=0.7)],
            score_as_of="2026-09-21",
        )
        self.assertEqual(model["upcoming"], [])
        self.assertEqual(model["window_start"].isoformat(), "2026-10-22")
        self.assertEqual(model["window_end"].isoformat(), "2026-11-04")
        self.assertEqual(
            {row["series_id"] for row in model["unscheduled_scored"]},
            {"US.Inflation.core_pce", "CA.Labor.unemployment"},
        )
        self.assertTrue(all(row["reason"] == "date unavailable" for row in model["unscheduled_scored"]))

    def test_official_window_uses_pinned_clocks_and_score_weights(self):
        model = build_release_model(NOW, score_as_of="2026-09-21")
        html_bits = []
        for bucket in ("upcoming", "recent", "later"):
            for item in model[bucket]:
                html_bits.append(" ".join(item["series_ids"]) + " " + item["et_display"] + " " + " ".join(item["impacts"]))
        blob = "\n".join(html_bits)
        self.assertIn("AU.Inflation.headline", blob)
        self.assertIn("2026-10-27 20:30 ET", blob)
        self.assertIn("standing clock", blob)
        self.assertIn("Scored input: AU Inflation", blob)
        self.assertIn("US.Labor.chicago_fed_u3_nowcast_final", blob)
        self.assertIn("zero score weight", blob)
        self.assertNotIn("US.Inflation.core_pce", blob)
        nz = [item for item in model["upcoming"] if "NZ.Inflation.headline" in item["series_ids"]]
        self.assertEqual(len(nz), 1)
        self.assertEqual(nz[0]["clock"], "tba")
        self.assertIn("no clock", nz[0]["provenance"])
        self.assertNotIn("10:45", nz[0]["local_display"])
        self.assertNotIn("consensus", blob.lower())
        self.assertTrue(all(item["after_freeze"] for item in model["upcoming"]))
        self.assertTrue(any(row["series_id"] == "US.Inflation.core_pce" for row in model["unscheduled_scored"]))
        later_ids = {series_id for item in model["later"] for series_id in item["series_ids"]}
        self.assertIn("US.Inflation.cpi_headline", later_ids)
        cpi = next(item for item in model["later"] if "US.Inflation.cpi_headline" in item["series_ids"])
        self.assertIn("Bridge input", " ".join(cpi["impacts"]))
        self.assertIn("2026-11-10", cpi["et_display"])
        for bucket in ("upcoming", "recent", "later"):
            for item in model[bucket]:
                self.assertNotIn("tests/", item["provenance"])


class RepairHtmlTests(unittest.TestCase):
    def setUp(self):
        self.scores = load_scores()
        self.html = apply_dashboard_repair(
            FIXTURE,
            market_state=_packet(),
            scores=self.scores,
            now=NOW,
            audit=None,
            series=[_series("US.Inflation.core_pce")],
        )

    def test_tape_navigation_scoreboard_and_tabs(self):
        tape_at = self.html.find('data-global-tape="repair"')
        tape = self.html[tape_at : self.html.find('data-score-overview="calibrated"', tape_at)]
        self.assertIn("5.13%", tape)
        self.assertIn("2026-10-21", tape)
        self.assertNotIn("4.79%", tape)
        self.assertNotIn("1.3790", tape)
        self.assertNotIn("98.83", tape)
        self.assertNotIn("$92.33", tape)
        self.assertIn("DXY is omitted", self.html)
        self.assertNotIn("Live 1–100 Score Board", self.html)
        self.assertIn("Published score freeze 2026-09-21", self.html)
        self.assertIn("Equal-weight summary", self.html)
        self.assertIn(">Inflation<", self.html)
        self.assertIn("63.1 warm", self.html)
        for code in ("us", "ca", "au", "nz", "ea", "jp"):
            self.assertIn(f'data-country="{code}"', self.html)
        self.assertIn('id="p-country"', self.html)
        self.assertIn('getElementById("p-country")', self.html)
        self.assertIn('getElementById("c-" + code)', self.html)
        self.assertNotIn('for="p-feed"', self.html)
        self.assertNotIn('for="p-relative"', self.html)
        self.assertNotIn('for="p-traderroom"', self.html)
        self.assertNotIn(">FEED PAGE<", self.html)
        self.assertNotIn(">RELATIVE PAGE<", self.html)
        self.assertNotIn("Trader Room · adversarial ideas", self.html)
        self.assertIn("Trader Book · paper P&amp;L", self.html)
        self.assertIn("Market Data · official snapshot", self.html)
        self.assertIn("NEWS PAGE", self.html)
        self.assertIn('id="research-debate"', self.html)
        self.assertNotIn("Momentum Watch", self.html)
        self.assertNotIn(">Next Catalysts<", self.html)
        releases = self.html.split('data-release-calendar="repair"', 1)[1].split("</section>", 1)[0]
        self.assertIn("date unavailable", releases)
        self.assertNotIn("+162k", releases)
        sources = self.html.split('data-source-health="repair"', 1)[1]
        self.assertIn("not checked", sources)
        self.assertIn("No succeeded Stage 01", sources)
        self.assertNotIn("Last successful check 2026", sources)
        self.assertIn('data-market-source="US_rates"', sources)
        self.assertNotIn("Sep 8 public snapshot", sources)
        self.assertEqual(self.html.count('data-score-overview="calibrated"'), 1)
        again = apply_dashboard_repair(
            self.html,
            market_state=None,
            scores=self.scores,
            now=NOW,
            audit=None,
            series=[_series("US.Inflation.core_pce")],
        )
        self.assertEqual(again.count('data-score-overview="calibrated"'), 1)
        self.assertEqual(again.count('data-country="jp"'), 1)
        self.assertIn("market-state packet missing", again)
        again_at = again.find('data-global-tape="repair"')
        again_tape = again[again_at : again.find('data-score-overview="calibrated"', again_at)]
        self.assertNotIn("5.13%", again_tape)

    def test_v6_base_tape_is_replaced(self):
        parts = sorted((ROOT / "payload_v6").glob("part*.b64"))
        raw = gzip.decompress(base64.b64decode(b"".join(part.read_bytes() for part in parts))).decode("utf-8")
        html = apply_six_economy_dashboard(raw)
        html = html.replace(
            '<div class="stitle">Temperature Board</div>',
            '<div data-score-overview="live"><b>Live 1–100 Score Board</b></div><div class="stitle">Macro Snapshot</div>',
            1,
        )
        repaired = apply_dashboard_repair(html, market_state=None, scores=self.scores, now=NOW, audit=None, series=[])
        self.assertNotIn("4.79%", repaired)
        self.assertNotIn("1.3790", repaired)
        self.assertNotIn("0.7210", repaired)
        self.assertNotIn("98.83", repaired)
        self.assertNotIn("$92.33", repaired)
        self.assertNotIn("$97.23", repaired)
        self.assertNotIn("$14,728/t", repaired)
        self.assertNotIn("Momentum Watch", repaired)
        self.assertNotIn("short-run cooler", repaired)
        self.assertIn('data-momentum="removed"', repaired)
        self.assertIn("Published score freeze 2026-09-21", repaired)
        for code in ("us", "ca", "au", "nz", "ea", "jp"):
            self.assertIn(f'data-country="{code}"', repaired)
        self.assertIn('id="country-detail"', repaired)
        self.assertNotIn('for="p-feed"', repaired)
        self.assertNotIn('for="p-relative"', repaired)


class SourceHealthTests(unittest.TestCase):
    def test_failed_check_is_not_a_successful_check_and_missing_ledger_invents_nothing(self):
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
                    "error": "The read operation timed out",
                    "source_health": {
                        "carried_forward": True,
                        "retrieved_at": "2026-09-21T14:41:19Z",
                        "fetch_status": "source_failed",
                    },
                },
            ],
        }
        snapshot = build_source_health_snapshot(series, ingest, None)
        by_id = {row["series_id"]: row for row in snapshot["rows"]}
        self.assertEqual(by_id["US.Labor.wages"]["last_successful_check"], "2026-10-22T11:09:51Z")
        self.assertEqual(by_id["US.Labor.wages"]["observation_period"], "2026-09")
        failed = by_id["US.Inflation.core_pce"]
        self.assertEqual(failed["bucket"], "failure")
        self.assertEqual(failed["last_successful_check"], "")
        self.assertEqual(failed["ledger_retrieval"], "2026-09-21T14:41:19Z")
        self.assertNotEqual(failed["ledger_retrieval"], snapshot["stage_checked_at"])
        self.assertEqual(failed["carried_forward"], "yes")
        self.assertEqual(by_id["CA.Labor.unemployment"]["bucket"], "not_checked")
        self.assertEqual(by_id["CA.Labor.unemployment"]["stage_attempt"], "")
        self.assertEqual(by_id["CA.Labor.unemployment"]["expected_next"], "date unavailable")
        self.assertEqual(snapshot["counts"]["checked"], 1)
        self.assertEqual(snapshot["counts"]["failure"], 1)
        self.assertEqual(snapshot["counts"]["not_checked"], 1)
        self.assertEqual(sum(snapshot["counts"][name] for name in ("checked", "failure", "blocked", "partial", "not_checked", "not_applicable")), 3)
        empty = build_source_health_snapshot(series, None, None)
        self.assertEqual(empty["stage_checked_at"], "")
        self.assertTrue(all(row["last_successful_check"] == "" for row in empty["rows"]))
        self.assertTrue(all(row["bucket"] == "not_checked" for row in empty["rows"]))

    def test_latest_stage_one_ledger_matches_its_file(self):
        ingest = load_latest_ingest()
        self.assertIsNotNone(ingest)
        assert ingest is not None
        self.assertEqual(ingest["stage_status"], "succeeded")
        self.assertTrue(ingest["checked_at"])
        failed = next(row for row in ingest["rows"] if row.get("status") == "source_failed")
        snapshot = build_source_health_snapshot(
            [{"id": failed["series_id"], "country": failed.get("country"), "weight": failed.get("weight"), "role": failed.get("role")}],
            ingest,
            None,
        )
        row = snapshot["rows"][0]
        self.assertEqual(row["bucket"], "failure")
        self.assertEqual(row["last_successful_check"], "")
        self.assertEqual(row["stage_attempt"], ingest["checked_at"])
        self.assertEqual(snapshot["counts"]["checked"], 0)


class ScheduleFetchTests(unittest.TestCase):
    def test_abs_and_stats_nz_parsers_do_not_invent_dates(self):
        parsed = parse_abs_future_releases(
            '<li>Next Release 19/11/2026<br><span>Labour Force, Australia, October 2026</span></li>'
        )
        self.assertEqual(parsed, [{"local_date": "2026-11-19", "title": "Labour Force, Australia, October 2026", "clock": ""}])
        self.assertEqual(parse_abs_future_releases("<p>Monthly cadence, no printed date</p>"), [])
        nz = parse_stats_nz_next_release(
            "<p><em>Consumers price index: September 2026 quarter</em> will be released on 22 October 2026.</p>"
        )
        self.assertEqual(nz[0]["local_date"], "2026-10-22")
        self.assertEqual(nz[0]["clock"], "")
        self.assertEqual(parse_stats_nz_next_release("<p>No release sentence</p>"), [])

    def test_fetched_slot_is_scheduled_and_unknown_series_stays_tba(self):
        series = [
            _series(
                "US.Labor.unemployment",
                weight=0.7,
                release_rule={"kind": "country_local_schedule_required", "timezone": "America/New_York", "dates": []},
            ),
            _series("CA.Inflation.headline"),
        ]
        fetched = {
            "attempted": True,
            "retrieved_at": "2026-10-22T16:00:00Z",
            "pages": [{"url": "https://blsmon1.bls.gov/schedule/2026/11_sched.htm", "status": "ok", "parsed": 1}],
            "errors": ["https://example.invalid (timed out)"],
            "slots": [
                {
                    "series_ids": ["US.Labor.unemployment"],
                    "country": "US",
                    "name": "Employment Situation",
                    "publisher": "Bureau of Labor Statistics",
                    "source_url": "https://blsmon1.bls.gov/schedule/2026/11_sched.htm",
                    "provenance": "Parsed from the official BLS monthly schedule.",
                    "reference_period": "2026-10",
                    "clock": "verified",
                    "timezone": "America/New_York",
                    "stamp": "2026-11-06T08:30:00",
                }
            ],
        }
        model = build_release_model(NOW, series=series, fetched_slots=fetched["slots"], schedule_fetch=fetched)
        upcoming_ids = {series_id for item in model["upcoming"] + model["later"] for series_id in item["series_ids"]}
        self.assertIn("US.Labor.unemployment", upcoming_ids)
        self.assertNotIn("CA.Inflation.headline", upcoming_ids)
        self.assertTrue(any(row["series_id"] == "CA.Inflation.headline" and row["reason"] == "date unavailable" for row in model["unscheduled_scored"]))
        self.assertIn("timed out", " ".join(model["schedule_fetch"]["errors"]))


class DebateTests(unittest.TestCase):
    def test_complete_debate_is_escaped_and_incomplete_debate_is_hidden(self):
        trades = []
        for index in range(14):
            trades.append(
                {
                    "agent": f"seat-{index}",
                    "entry_reason": "<script>alert(1)</script>",
                    "mispricing": "wide",
                    "confidence": 0.4,
                    "trade": {"instrument": "USDCAD", "direction": "long", "expression": "spot", "horizon": "2w"},
                    "rebuttal": {"trade_change": "cut size", "strongest_opponent_point": "already priced"},
                }
            )
        html = render_debate_html(
            {"available": True, "seat_count": 14, "run_id": "tr-test", "as_of": "2026-10-22T12:00:00Z", "trades": trades}
        )
        self.assertEqual(html.count('data-debate-card="1"'), 14)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("<script>alert", html)
        self.assertIn("Rebuttal", html)
        self.assertIn("already priced", html)
        self.assertIn("Not a book instruction", html)
        self.assertEqual(render_debate_html({"available": True, "seat_count": 13, "trades": trades[:13]}), "")
        self.assertEqual(render_debate_html({"available": False, "seat_count": 14, "trades": trades}), "")


if __name__ == "__main__":
    unittest.main()
