"""Phase-aware publication contract: rank, ordering, stamping, final identity.

Synthetic fixtures only, so this module runs on a shallow checkout inside the
deploy-pages build.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

from scripts.market_watch_launch import publication_release as pr

LAUNCH_A = "mwl-20261027T093212Z-9512d95d"
LAUNCH_B = "mwl-20261027T150000Z-0000beef"
LAUNCH_PREV = "mwl-20261026T113710Z-1e472b39"
PACKET_A = "a" * 64
PACKET_PREV = "c" * 64

SITE_HTML = """<!doctype html><html><head><style>body{}</style></head><body>
<div class="app"><header class="topbar"><div class="brand">MW</div></header>
<nav class="nav"><label for="p-front">Front</label></nav>
<section class="page news"><p>news</p></section>
<section class="page traderbook"><div class="cd"><header class="cd-head">x</header></div></section>
</div></body></html>
"""


def research(**overrides):
    release = {
        "type": pr.RELEASE_TYPE,
        "schema_version": 1,
        "phase": pr.PHASE_RESEARCH,
        "channel": pr.CHANNEL_PRODUCTION,
        "session_date": "2026-10-27",
        "launch_id": LAUNCH_A,
        "review_id": "review-001",
        "packet_sha256": PACKET_A,
        "overnight_run_id": "overnight-20261027",
        "frozen_at": "2026-10-27T05:32:12-04:00",
        "market_state": {"as_of": "2026-10-27T09:50:58Z"},
        "books": {
            "overnight_run_id": "overnight-20261026",
            "books_run_id": "overnight-20261026",
            "as_of": "2026-10-26T07:37:10-04:00",
            "accepted_at": "2026-10-26T08:55:26-04:00",
            "packet_sha256": PACKET_PREV,
        },
        "news": {"as_of": "2026-10-26T07:37:10-04:00", "current_session": False, "age_label": "21 h before this freeze"},
        "scores": {"inputs_last_ingested_at": "2026-10-26T11:37:10Z", "checked_at": "2026-10-27T09:32:12Z"},
        "quality": {"coverage": "PARTIAL", "blocked_expressions": ["macro:NZ"]},
        "trader_cycle": {"status": "pending"},
    }
    release.update(overrides)
    return release


def final(**overrides):
    release = {
        "type": pr.RELEASE_TYPE,
        "schema_version": 1,
        "phase": pr.PHASE_FINAL,
        "channel": pr.CHANNEL_PRODUCTION,
        "trigger": pr.TRIGGER_LAUNCH,
        "session_date": "2026-10-27",
        "launch_id": LAUNCH_A,
        "review_id": "review-001",
        "packet_sha256": PACKET_A,
        "overnight_run_id": "overnight-20261027",
        "finalized_at": "2026-10-27T08:55:00-04:00",
        "trader_cycle": {"status": "accepted"},
    }
    release.update(overrides)
    return release


def launch_record(launch_id, *, session, run_id, packet, provider="acp", finalized=False, status="running"):
    stages = {name: {"status": "succeeded"} for name in ("00_authenticate", "01_ingest", "02_acquire", "03_quality_gate")}
    stages["04_freeze"] = {
        "status": "succeeded",
        "details": {"review_id": "review-001", "packet_sha256": packet, "overnight_run_id": run_id},
    }
    for name in ("05_acp_handoff", "06_acceptance", "07_finalize", "08_pages"):
        stages[name] = {"status": "pending"}
    if finalized:
        for name in ("05_acp_handoff", "06_acceptance"):
            stages[name] = {"status": "succeeded"}
        stages["07_finalize"] = {"status": "succeeded", "finished_at": f"{session}T08:55:00-04:00"}
    return {
        "type": "MARKET_WATCH_LAUNCH",
        "launch_id": launch_id,
        "session_date": session,
        "status": status,
        "overnight_run_id": run_id,
        "review_id": "review-001",
        "base_packet_sha256": packet,
        "request": {"provider": provider, "mode": "live", "publish_production": True},
        "stages": stages,
    }


class Root:
    """Minimal repository state: launches, latest.json and the assembled dataset."""

    def __init__(self, base: Path) -> None:
        self.base = base

    def launch(self, record):
        path = self.base / "data" / "market_watch_launches" / record["launch_id"] / "launch.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record), encoding="utf-8")
        return path

    def receipt(self, release):
        path = self.base / "data" / "market_watch_launches" / release["launch_id"] / pr.RESEARCH_RECEIPT_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"type": pr.RESEARCH_RECEIPT_TYPE, "release": release}), encoding="utf-8")

    def accepted(self, run_id, packet, as_of):
        overnight = self.base / "data" / "overnight"
        (overnight / "runs" / run_id).mkdir(parents=True, exist_ok=True)
        (overnight / "latest.json").write_text(json.dumps({"overnight_run_id": run_id, "as_of": as_of}), encoding="utf-8")
        (overnight / "runs" / run_id / "assembled_dataset.json").write_text(json.dumps({"packet_sha256": packet}), encoding="utf-8")


def opener_returning(payload):
    def _open(url):
        assert "release.json?t=" in url
        if isinstance(payload, Exception):
            raise payload
        return payload

    return _open


def http_error(code):
    return urllib.error.HTTPError("https://x/release.json", code, "err", {}, io.BytesIO(b""))


class RankTests(unittest.TestCase):
    def test_launch_stamp_and_rank(self):
        self.assertEqual(pr.launch_stamp(LAUNCH_A), "20261027T093212Z")
        self.assertEqual(pr.launch_stamp("not-a-launch"), "")
        self.assertEqual(pr.release_rank(research()), ("2026-10-27", "20261027T093212Z", 1))
        self.assertEqual(pr.release_rank(final()), ("2026-10-27", "20261027T093212Z", 2))
        self.assertIsNone(pr.release_rank({"phase": "research"}))
        self.assertIsNone(pr.release_rank(research(phase="draft")))
        self.assertIsNone(pr.release_rank(research(session_date="")))

    def test_rank_is_strictly_monotonic_across_phase_launch_and_session(self):
        prev_final = final(session_date="2026-10-26", launch_id=LAUNCH_PREV, packet_sha256=PACKET_PREV, overnight_run_id="overnight-20261026")
        ordered = [prev_final, research(), final(), research(launch_id=LAUNCH_B), final(launch_id=LAUNCH_B)]
        ranks = [pr.release_rank(item) for item in ordered]
        self.assertEqual(ranks, sorted(ranks))
        self.assertEqual(len(set(ranks)), len(ranks))

    def test_session_from_run_id(self):
        self.assertEqual(pr.session_from_run_id("overnight-20261027"), "2026-10-27")
        self.assertEqual(pr.session_from_run_id("overnight-2026x027"), "")
        self.assertEqual(pr.session_from_run_id(None), "")


class OrderingTests(unittest.TestCase):
    def test_final_supersedes_research_for_matching_launch(self):
        decision = pr.ordering_decision(research(), known=[("public_release", final())])
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["reason"], pr.SUPERSEDED)
        self.assertTrue(pr.ordering_decision(final(), known=[("public_release", research())])["allowed"])

    def test_late_research_cannot_displace_newer_launch(self):
        newer = research(launch_id=LAUNCH_B)
        decision = pr.ordering_decision(research(), known=[("research_receipt", newer)])
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["blocking"]["launch_id"], LAUNCH_B)

    def test_stale_refresh_cannot_overwrite_newer_research(self):
        refresh = final(
            trigger=pr.TRIGGER_REFRESH,
            session_date="2026-10-26",
            launch_id=LAUNCH_PREV,
            packet_sha256=PACKET_PREV,
            overnight_run_id="overnight-20261026",
        )
        decision = pr.ordering_decision(refresh, known=[("public_release", research())])
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["reason"], pr.SUPERSEDED)

    def test_replay_of_same_identity_is_idempotent(self):
        self.assertTrue(pr.ordering_decision(research(), known=[("research_receipt", research(channel="production"))])["allowed"])

    def test_equal_rank_with_different_identity_fails_closed(self):
        conflict = research(packet_sha256="d" * 64)
        decision = pr.ordering_decision(research(), known=[("public_release", conflict)])
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["reason"], pr.IDENTITY_CONFLICT)

    def test_unranked_candidate_is_refused_and_unranked_known_ignored(self):
        self.assertFalse(pr.ordering_decision({"phase": "research"}, known=[])["allowed"])
        self.assertTrue(pr.ordering_decision(research(), known=[("legacy", {"overnight_run_id": "x"})])["allowed"])


class StampTests(unittest.TestCase):
    def _site(self, tmp: Path) -> Path:
        site = tmp / "site"
        site.mkdir()
        (site / "index.html").write_text(SITE_HTML, encoding="utf-8")
        (site / "trader-books.json").write_text(
            json.dumps({"books_run_id": "overnight-20261026", "publication": {"trader_books_status": "fresh"}, "seats": []}),
            encoding="utf-8",
        )
        (site / "pm-books.json").write_text(json.dumps({"publication": {"pm_books_status": "fresh"}, "books": []}), encoding="utf-8")
        return site

    def test_research_banner_and_notes_inserted_once_after_topbar(self):
        html = pr.stamp_html(SITE_HTML, research())
        self.assertEqual(html.count('data-publication-phase="research"'), 1)
        banner = html.index('<section class="mw-edition mw-edition--research"')
        self.assertLess(html.index("</header>"), banner)
        self.assertLess(banner, html.index('<nav class="nav">'))
        self.assertIn('data-edition-note="traderbook"', html)
        self.assertIn('data-edition-note="news"', html)
        self.assertIn("Research edition · Tue 27 Oct 2026 · provisional", html)
        self.assertIn("<b>pending</b>", html)
        self.assertIn("They are not today's positions.", html)
        self.assertIn("evidence boundary 27 Oct 2026 05:32 ET", html)
        self.assertIn("market data snapshot 27 Oct 2026 05:50 ET", html)
        self.assertIn("PARTIAL coverage (macro:NZ)", html)
        self.assertIn("21 h before this freeze", html)
        self.assertIn("(as of 26 Oct 2026 07:37 ET, accepted 26 Oct 2026 08:55 ET)", html)
        with self.assertRaises(ValueError):
            pr.stamp_html(html, research())

    def test_current_session_news_has_no_age_note(self):
        html = pr.stamp_html(SITE_HTML, research(news={"as_of": "2026-10-27T05:00:00-04:00", "current_session": True}))
        self.assertNotIn('data-edition-note="news"', html)
        self.assertIn("News: accepted digest as of 27 Oct 2026 05:00 ET.", html)

    def test_final_banner_has_no_research_notes(self):
        html = pr.stamp_html(SITE_HTML, final())
        self.assertIn('data-publication-phase="final"', html)
        self.assertIn("Final edition · Tue 27 Oct 2026", html)
        self.assertNotIn("data-edition-note", html)
        self.assertNotIn("pending", html)

    def test_banner_escapes_identity_text(self):
        html = pr.render_edition_banner(research(review_id='"><script>x</script>'))
        self.assertNotIn("<script>", html)

    def test_missing_anchor_is_refused(self):
        with self.assertRaises(ValueError):
            pr.stamp_html(SITE_HTML.replace('<header class="topbar">', "<header>"), research())
        with self.assertRaises(ValueError):
            pr.stamp_html(SITE_HTML.replace('<section class="page traderbook">', "<section>"), research())

    def test_research_site_marks_books_previous_cycle_and_digest_binds_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = self._site(Path(tmp))
            stamped = pr.stamp_site(site, research())
            trader = json.loads((site / "trader-books.json").read_text())
            pm = json.loads((site / "pm-books.json").read_text())
            self.assertEqual(trader["publication"]["trader_books_status"], "previous_cycle")
            self.assertEqual(trader["publication"]["source_publication"], {"trader_books_status": "fresh"})
            self.assertEqual(trader["edition"]["current_cycle_status"], "pending")
            self.assertEqual(trader["edition"]["books_overnight_run_id"], "overnight-20261026")
            self.assertEqual(pm["publication"]["pm_books_status"], "previous_cycle")
            self.assertIn("not today's positions", trader["publication"]["reason"])
            on_disk = json.loads((site / pr.RELEASE_FILENAME).read_text())
            self.assertEqual(on_disk, stamped)
            self.assertEqual(stamped["site_sha256"], pr.site_digest(site))
            (site / "market-state.json").write_text("{}", encoding="utf-8")
            self.assertNotEqual(stamped["site_sha256"], pr.site_digest(site))

    def test_final_site_keeps_books_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = self._site(Path(tmp))
            before = (site / "trader-books.json").read_bytes()
            pr.stamp_site(site, final())
            self.assertEqual((site / "trader-books.json").read_bytes(), before)


class CommittedAndFinalTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.root = Root(self.base)

    def tearDown(self):
        self._tmp.cleanup()

    def test_committed_publications_include_finalized_launches_and_receipts_only(self):
        self.root.launch(launch_record(LAUNCH_PREV, session="2026-10-26", run_id="overnight-20261026", packet=PACKET_PREV, finalized=True, status="succeeded"))
        self.root.launch(launch_record(LAUNCH_A, session="2026-10-27", run_id="overnight-20261027", packet=PACKET_A))
        self.root.launch(launch_record("mwl-20261027T120000Z-5ab0b0b0", session="2026-10-27", run_id="overnight-20261027-stub", packet="e" * 64, provider="stub", finalized=True))
        self.root.receipt(research())
        known = dict(pr.committed_publications(self.base))
        self.assertEqual(set(known), {f"finalized:{LAUNCH_PREV}", f"research_receipt:{LAUNCH_A}"})
        self.assertEqual(known[f"finalized:{LAUNCH_PREV}"]["phase"], pr.PHASE_FINAL)

    def test_finalized_launch_outranks_its_research_receipt_before_stage08(self):
        self.root.launch(launch_record(LAUNCH_A, session="2026-10-27", run_id="overnight-20261027", packet=PACKET_A, finalized=True))
        self.root.receipt(research())
        decision = pr.guard_publication(research(), root=self.base)
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["blocking"]["origin"], f"finalized:{LAUNCH_A}")
        self.assertTrue(pr.guard_publication(final(), root=self.base)["allowed"])

    def test_build_final_release_binds_launch_identity(self):
        self.root.launch(launch_record(LAUNCH_A, session="2026-10-27", run_id="overnight-20261027", packet=PACKET_A, finalized=True))
        self.root.accepted("overnight-20261027", PACKET_A, "2026-10-27T08:50:00-04:00")
        release = pr.build_final_release(
            self.base, launch_id=LAUNCH_A, review_id="review-001", packet_sha256=PACKET_A, channel="production", source_commit="f" * 40
        )
        self.assertEqual(release["trigger"], pr.TRIGGER_LAUNCH)
        self.assertEqual(release["session_date"], "2026-10-27")
        self.assertEqual(release["finalized_at"], "2026-10-27T08:55:00-04:00")
        for kwargs in ({"review_id": "review-002"}, {"packet_sha256": "b" * 64}):
            with self.assertRaises(SystemExit):
                pr.build_final_release(self.base, launch_id=LAUNCH_A, channel="production", source_commit="", **kwargs)
        with self.assertRaises(SystemExit):
            pr.build_final_release(self.base, launch_id=LAUNCH_B, channel="production", source_commit="")

    def test_build_final_release_refuses_unaccepted_launch_output(self):
        self.root.launch(launch_record(LAUNCH_A, session="2026-10-27", run_id="overnight-20261027", packet=PACKET_A))
        self.root.accepted("overnight-20261026", PACKET_PREV, "2026-10-26T08:55:00-04:00")
        with self.assertRaises(SystemExit):
            pr.build_final_release(self.base, launch_id=LAUNCH_A, channel="production", source_commit="")
        self.root.accepted("overnight-20261027", "9" * 64, "2026-10-27T08:50:00-04:00")
        with self.assertRaises(SystemExit):
            pr.build_final_release(self.base, launch_id=LAUNCH_A, channel="production", source_commit="")

    def test_refresh_resolves_finalized_launch_or_stays_unbound(self):
        self.root.launch(launch_record(LAUNCH_PREV, session="2026-10-26", run_id="overnight-20261026", packet=PACKET_PREV, finalized=True, status="succeeded"))
        self.root.accepted("overnight-20261026", PACKET_PREV, "2026-10-26T08:55:00-04:00")
        refresh = pr.build_final_release(self.base, channel="production", source_commit="")
        self.assertEqual((refresh["trigger"], refresh["launch_id"], refresh["session_date"]), (pr.TRIGGER_REFRESH, LAUNCH_PREV, "2026-10-26"))
        self.root.accepted("overnight-20261025", "7" * 64, "2026-10-25T08:55:00-04:00")
        unbound = pr.build_final_release(self.base, channel="production", source_commit="")
        self.assertIsNone(unbound["launch_id"])
        self.assertEqual(unbound["session_date"], "2026-10-25")
        self.assertLess(pr.release_rank(unbound), pr.release_rank(refresh))

    def test_guard_reads_public_release(self):
        self.root.launch(launch_record(LAUNCH_PREV, session="2026-10-26", run_id="overnight-20261026", packet=PACKET_PREV, finalized=True, status="succeeded"))
        refresh = final(trigger=pr.TRIGGER_REFRESH, session_date="2026-10-26", launch_id=LAUNCH_PREV, packet_sha256=PACKET_PREV, overnight_run_id="overnight-20261026")
        blocked = pr.guard_publication(refresh, root=self.base, public_base_url="https://x.github.io/mw/", opener=opener_returning(research()))
        self.assertFalse(blocked["allowed"])
        self.assertEqual(blocked["public_state"], "ok")
        absent = pr.guard_publication(refresh, root=self.base, public_base_url="https://x.github.io/mw/", opener=opener_returning(http_error(404)))
        self.assertTrue(absent["allowed"])
        self.assertEqual(absent["public_state"], "absent")
        down = pr.guard_publication(refresh, root=self.base, public_base_url="https://x.github.io/mw/", opener=opener_returning(http_error(503)))
        self.assertEqual(down["public_state"], "unreachable")
        self.assertEqual(pr.fetch_public_release("http://insecure")[0], "unreachable")


class VerifyPublicTests(unittest.TestCase):
    def test_matched_superseded_and_not_served(self):
        sleeps = []
        expected = research()
        self.assertEqual(
            pr.verify_public_release(expected, "https://x/", attempts=2, sleep=sleeps.append, opener=opener_returning(dict(expected)))["state"],
            "matched",
        )
        self.assertEqual(
            pr.verify_public_release(expected, "https://x/", attempts=2, sleep=sleeps.append, opener=opener_returning(final()))["state"],
            "superseded",
        )
        older = final(session_date="2026-10-26", launch_id=LAUNCH_PREV)
        result = pr.verify_public_release(expected, "https://x/", attempts=3, interval_seconds=1, sleep=sleeps.append, opener=opener_returning(older))
        self.assertFalse(result["verified"])
        self.assertEqual(result["state"], "not_served:ok")
        self.assertEqual(sleeps, [1, 1])


class CliTests(unittest.TestCase):
    def test_guard_cli_exits_nonzero_when_superseded(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = Root(base)
            root.launch(launch_record(LAUNCH_A, session="2026-10-27", run_id="overnight-20261027", packet=PACKET_A, finalized=True))
            site = base / "site"
            site.mkdir()
            (site / pr.RELEASE_FILENAME).write_text(json.dumps(research()), encoding="utf-8")
            self.assertEqual(pr.main(["guard", "--site-dir", str(site), "--root", str(base)]), 1)
            (site / pr.RELEASE_FILENAME).write_text(json.dumps(final()), encoding="utf-8")
            self.assertEqual(pr.main(["guard", "--site-dir", str(site), "--root", str(base)]), 0)


if __name__ == "__main__":
    unittest.main()
