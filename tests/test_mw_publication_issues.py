"""Deterministic public issues feed collectors and publish contract."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.market_watch_launch import publication_issues as pi

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "docs" / "examples" / "issues.example.json"
LAUNCH_NOV10 = "mwl-20261110T095036Z-eaa0689a"
_FORBIDDEN = ("Current verified headlines", "Last refreshed")


def _release(**overrides) -> dict:
    base = {
        "type": "MARKET_WATCH_PUBLICATION_RELEASE",
        "schema_version": 1,
        "phase": "research",
        "session_date": "2026-11-10",
        "launch_id": LAUNCH_NOV10,
        "trader_cycle": {"status": "pending"},
        "quality": {"coverage": "FULL"},
        "news": {"current_session": True},
        "headlines": {"status": "available"},
    }
    base.update(overrides)
    return base


def _write_site(site: Path, **files: dict) -> None:
    site.mkdir(parents=True, exist_ok=True)
    for name, payload in files.items():
        (site / name).write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def regenerate_issues_example(path: Path | None = None) -> dict:
    from scripts.dashboard_repair.source_health import build_source_health_snapshot
    from scripts.macro_ingestion.contract import load_catalog

    target = path or EXAMPLE
    ingest_path = ROOT / "data" / "market_watch_launches" / LAUNCH_NOV10 / "artifacts" / "01_ingest.json"
    ingest = json.loads(ingest_path.read_text(encoding="utf-8"))
    ingest["launch_id"] = LAUNCH_NOV10
    ingest["stage_status"] = ingest["status"]
    snap = build_source_health_snapshot(load_catalog()["series"], ingest)
    release = json.loads(
        (ROOT / "data" / "market_watch_launches" / LAUNCH_NOV10 / "research_pages.json").read_text(encoding="utf-8")
    )["release"]
    market = {
        "status": "ok",
        "sources": {
            "US_rates": {
                "name": "U.S. Treasury daily par yield curve",
                "status": "ok",
                "observation_date": "2026-11-07",
                "url": "https://home.treasury.gov/",
            },
            "FX": {
                "name": "ECB euro foreign exchange reference rates",
                "status": "ok",
                "observation_date": "2026-11-07",
                "url": "https://www.ecb.europa.eu/",
            },
            "CME_positioning": {
                "name": "CME",
                "status": "unavailable",
                "error": "HTTP Error 403: Forbidden",
                "url": "https://www.cmegroup.com/market-data/volume-open-interest.html",
            },
        },
    }
    with tempfile.TemporaryDirectory() as td:
        site = Path(td)
        _write_site(site, **{"source-health.json": snap, "market-state.json": market, "release.json": release})
        feed = pi.build_issues_feed(site, root=ROOT)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(pi.canonical_json(feed), encoding="utf-8")
    return feed


class PublicationIssuesCollectorsTests(unittest.TestCase):
    def test_source_health_buckets_and_not_checked_aggregate(self):
        snapshot = {
            "launch_id": "mwl-test",
            "rows": [
                {
                    "series_id": "US.Test.fail",
                    "country": "US",
                    "bucket": "failure",
                    "error": "timeout",
                    "observation_period": "2026-01",
                    "publisher": "BLS",
                    "url": "https://www.bls.gov/",
                },
                {
                    "series_id": "CA.Test.blocked",
                    "country": "CA",
                    "bucket": "blocked",
                    "error": "403",
                    "observation_period": "",
                    "publisher": "StatCan",
                    "url": "https://www.statcan.gc.ca/",
                },
                {
                    "series_id": "AU.Test.partial",
                    "country": "AU",
                    "bucket": "partial",
                    "error": "",
                    "observation_period": "2026-Q1",
                    "publisher": "ABS",
                    "url": "https://www.abs.gov.au/",
                },
                {"series_id": "NZ.A", "country": "NZ", "bucket": "not_checked"},
                {"series_id": "NZ.B", "country": "NZ", "bucket": "not_checked"},
                {"series_id": "JP.A", "country": "JP", "bucket": "checked"},
            ],
        }
        release = _release()
        rows = pi.collect_source_health_issues(snapshot, release)
        codes = {row["code"] for row in rows}
        self.assertIn("source_fetch_failed", codes)
        self.assertIn("source_blocked", codes)
        blocked = next(row for row in rows if row["code"] == "source_blocked")
        self.assertEqual(blocked["severity"], "info")
        self.assertIn("source_partial", codes)
        agg = next(row for row in rows if row["component"] == "sources:not_checked")
        self.assertEqual(agg["occurrences"], 2)
        self.assertEqual(agg["country"], "NZ")

    def test_market_state_severity_rules(self):
        packet = {
            "status": "ok",
            "sources": {
                "FX": {"status": "unavailable", "error": "fx down", "observation_date": None},
                "US_rates": {"status": "stale", "observation_date": "2026-10-01"},
                "CME_positioning": {"status": "unavailable", "error": "403"},
            },
        }
        rows = pi.collect_market_state_issues(packet, _release())
        by_component = {row["component"]: row for row in rows}
        self.assertEqual(by_component["market_state:FX"]["severity"], "critical")
        self.assertEqual(by_component["market_state:US_rates"]["severity"], "warning")
        self.assertEqual(by_component["market_state:US_rates"]["code"], "market_source_stale")
        self.assertEqual(by_component["market_state:CME_positioning"]["severity"], "warning")

    def test_market_state_degraded_short_cause_and_country_prefix(self):
        rbnz_note = (
            "RBNZ official B2 workbook was blocked; "
            "see https://www.rbnz.govt.nz/statistics/series/exchange-and-interest-rates/b2"
        )
        packet = {
            "status": "ok",
            "sources": {
                "NZ_rates": {"status": "unavailable", "error": rbnz_note},
                "CME_positioning": {
                    "status": "unavailable",
                    "error": "errors={'AUD': HTTP Error 403: Forbidden https://www.cmegroup.com/market-data/…}",
                },
            },
        }
        rows = pi.collect_market_state_issues(packet, _release())
        by_component = {row["component"]: row for row in rows}
        nz = by_component["market_state:NZ_rates"]
        self.assertEqual(nz["country"], "NZ")
        self.assertNotIn("https://", nz["cause"])
        self.assertLessEqual(len(nz["cause"]), 160)
        self.assertIn(rbnz_note, nz["detail"])
        cme = by_component["market_state:CME_positioning"]
        self.assertIsNone(cme.get("country"))
        self.assertIn("403", cme["cause"])
        self.assertNotIn("cmegroup.com", cme["cause"].lower())

    def test_market_state_top_unavailable(self):
        with tempfile.TemporaryDirectory() as td:
            site = Path(td)
            _write_site(
                site,
                **{
                    "release.json": _release(),
                    "market-state.json": {"status": "unavailable", "sources": {}},
                    "source-health.json": {"launch_id": "x", "rows": []},
                },
            )
            feed = pi.build_issues_feed(site, root=site)
            row = next(i for i in feed["issues"] if i["component"] == "market_state")
            self.assertEqual(row["severity"], "critical")

    def test_release_quality_news_headlines(self):
        release = _release(
            quality={
                "coverage": "PARTIAL",
                "research_coverage_gaps": ["macro:CA", "macro:AU"],
                "blocked_expressions": ["macro:NZ"],
            },
            news={
                "status": "unavailable",
                "mode": "current-cycle-news-commentary-missing",
                "current_session": False,
                "as_of": "2026-11-09T05:37:50-05:00",
            },
            headlines={"status": "unavailable"},
        )
        rows = pi.collect_release_issues(release)
        codes = [row["code"] for row in rows]
        self.assertEqual(codes.count("quality_coverage_gap"), 2)
        self.assertIn("quality_blocked_expression", codes)
        self.assertIn("news_unavailable", codes)
        self.assertIn("news_commentary_missing", codes)
        self.assertIn("news_previous_session", codes)
        self.assertIn("headlines_unavailable", codes)

    def test_trader_cycle_pending_research_no_issue(self):
        rows = pi.collect_release_issues(_release(trader_cycle={"status": "pending"}))
        self.assertFalse(any("trader" in row["code"] for row in rows))

    def test_trader_room_available_false(self):
        with tempfile.TemporaryDirectory() as td:
            site = Path(td)
            _write_site(
                site,
                **{
                    "release.json": _release(),
                    "source-health.json": {"launch_id": "mwl-x", "rows": []},
                    "market-state.json": {"status": "ok", "sources": {}},
                    "trader-room.json": {"available": False},
                },
            )
            feed = pi.build_issues_feed(site, root=site)
            self.assertTrue(any(i["component"] == "research_debate" for i in feed["issues"]))

    def test_resolved_state_requires_both_ledgers(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            launches = root / "data" / "market_watch_launches"
            for name, rows in (
                ("mwl-20261109T000000Z-aaaa1111", [{"series_id": "US.X", "status": "source_failed"}]),
                ("mwl-20261110T000000Z-bbbb2222", [{"series_id": "US.X", "status": "checked_unchanged"}]),
            ):
                art = launches / name / "artifacts"
                art.mkdir(parents=True)
                (art / "01_ingest.json").write_text(
                    json.dumps({"status": "succeeded", "rows": rows}, sort_keys=True),
                    encoding="utf-8",
                )
            snapshot = {
                "launch_id": "mwl-20261110T000000Z-bbbb2222",
                "rows": [
                    {
                        "series_id": "US.X",
                        "country": "US",
                        "bucket": "checked",
                        "observation_period": "2026-01",
                        "publisher": "BLS",
                        "url": "https://www.bls.gov/",
                    }
                ],
            }
            resolved = pi.collect_resolved_source_issues(
                snapshot,
                pi.load_preceding_succeeded_ingest(root, snapshot["launch_id"]),
                _release(),
            )
            self.assertEqual(len(resolved), 1)
            self.assertEqual(resolved[0]["state"], "resolved")

    def test_stable_ids_and_dedupe(self):
        row_a = pi.make_issue(
            "dup",
            category="render",
            severity="info",
            component="x",
            cause="first",
            impact="one",
        )
        row_b = pi.make_issue(
            "dup",
            category="render",
            severity="warning",
            component="x",
            cause="second",
            impact="two",
        )
        merged = pi.dedupe([row_a, row_b])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["severity"], "warning")
        self.assertEqual(merged[0]["occurrences"], 2)

    def test_determinism(self):
        with tempfile.TemporaryDirectory() as td:
            site = Path(td)
            _write_site(
                site,
                **{
                    "release.json": _release(),
                    "source-health.json": {"launch_id": "mwl-x", "rows": []},
                    "market-state.json": {"status": "ok", "sources": {}},
                },
            )
            a = pi.canonical_json(pi.build_issues_feed(site, root=site))
            b = pi.canonical_json(pi.build_issues_feed(site, root=site))
            self.assertEqual(a, b)

    def test_publish_issues_corrupt_inputs_never_raises(self):
        with tempfile.TemporaryDirectory() as td:
            site = Path(td)
            (site / "release.json").write_text("{not json", encoding="utf-8")
            (site / "source-health.json").write_text("{", encoding="utf-8")
            (site / "market-state.json").write_text("[", encoding="utf-8")
            (site / "index.html").write_text("<!doctype html><body></body>", encoding="utf-8")
            feed = pi.publish_issues(site, root=site)
            self.assertEqual(feed["status"], "available")
            self.assertTrue((site / "issues.json").is_file())

    def test_publish_issues_build_failure_unavailable(self):
        with tempfile.TemporaryDirectory() as td:
            site = Path(td)
            _write_site(site, **{"release.json": _release()})
            with mock.patch.object(pi, "build_issues_feed", side_effect=RuntimeError("boom")):
                feed = pi.publish_issues(site, root=ROOT)
            self.assertEqual(feed["status"], "unavailable")
            payload = json.loads((site / "issues.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "unavailable")

    def test_forbidden_phrases_and_temp_paths_sanitized(self):
        row = pi.make_issue(
            "x",
            category="render",
            severity="info",
            component="c",
            cause="Current verified headlines appear",
            impact="Last refreshed now",
            detail="/tmp/secret/file.log failed",
        )
        text = " ".join((row["cause"], row["impact"], row["detail"]))
        for phrase in _FORBIDDEN:
            self.assertNotIn(phrase, text)
        self.assertIn("[temp path]", row["detail"])

    def test_production_shaped_example_feed(self):
        self.assertTrue(EXAMPLE.is_file(), "missing docs/examples/issues.example.json")
        expected = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        from scripts.dashboard_repair.source_health import build_source_health_snapshot
        from scripts.macro_ingestion.contract import load_catalog

        ingest_path = ROOT / "data" / "market_watch_launches" / LAUNCH_NOV10 / "artifacts" / "01_ingest.json"
        ingest = json.loads(ingest_path.read_text(encoding="utf-8"))
        ingest["launch_id"] = LAUNCH_NOV10
        ingest["stage_status"] = ingest["status"]
        snap = build_source_health_snapshot(load_catalog()["series"], ingest)
        release = json.loads(
            (ROOT / "data" / "market_watch_launches" / LAUNCH_NOV10 / "research_pages.json").read_text(encoding="utf-8")
        )["release"]
        market = {
            "status": "ok",
            "sources": {
                "US_rates": {
                    "name": "U.S. Treasury daily par yield curve",
                    "status": "ok",
                    "observation_date": "2026-11-07",
                    "url": "https://home.treasury.gov/",
                },
                "FX": {
                    "name": "ECB euro foreign exchange reference rates",
                    "status": "ok",
                    "observation_date": "2026-11-07",
                    "url": "https://www.ecb.europa.eu/",
                },
                "CME_positioning": {
                    "name": "CME",
                    "status": "unavailable",
                    "error": "HTTP Error 403: Forbidden",
                    "url": "https://www.cmegroup.com/market-data/volume-open-interest.html",
                },
            },
        }
        with tempfile.TemporaryDirectory() as td:
            site = Path(td)
            _write_site(
                site,
                **{"source-health.json": snap, "market-state.json": market, "release.json": release},
            )
            feed = pi.build_issues_feed(site, root=ROOT)
        self.assertEqual(feed, expected)
        for row in feed["issues"]:
            blob = json.dumps(row)
            for phrase in _FORBIDDEN:
                self.assertNotIn(phrase, blob)


if __name__ == "__main__":
    if os.environ.get("MW_REGENERATE_EXAMPLES") == "1":
        regenerate_issues_example()
        print(f"regenerated {EXAMPLE}")
    unittest.main()
