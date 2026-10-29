"""Research edition end to end on the real 2026-10-27 pre-trader freeze.

The fixture is a shared clone of commit e9f757d7: launch
mwl-20261027T093212Z-9512d95d with Stage 04 verified and remotely attested,
traders pending, and no accepted overnight-20261027. The current ``scripts/``
tree is committed on top so the code under test is this checkout's.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from scripts.market_watch_launch import publication_release as pr
from scripts.market_watch_launch import research_pages as rp

REPO = Path(__file__).resolve().parents[1]
FIXTURE_COMMIT = "e9f757d7d6ae83e6c017fd9f95a1da40addda9ad"
LAUNCH = "mwl-20261027T093212Z-9512d95d"
REVIEW = "review-001"
PACKET = "74b06c13f1215b6521678c764356cae8ae2788e19bad038dad0a79f7e35f2109"
PREV_LAUNCH = "mwl-20261026T113710Z-1e472b39"
NOW = datetime(2026, 10, 27, 14, 30, tzinfo=timezone.utc)
NEXT_DAY = datetime(2026, 10, 28, 14, 30, tzinfo=timezone.utc)
LAUNCH_REL = Path("data") / "market_watch_launches" / LAUNCH

_STATE: dict[str, Path | str] = {}


def _git(root: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    if check and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr}")
    return proc.stdout.strip()


def _commit(root: Path, message: str) -> str:
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "commit", "-q", "-m", message)
    return _git(root, "rev-parse", "HEAD")


def setUpModule():
    if subprocess.run(["git", "cat-file", "-e", f"{FIXTURE_COMMIT}^{{commit}}"], cwd=REPO, check=False).returncode != 0:
        raise unittest.SkipTest(f"fixture commit {FIXTURE_COMMIT} is not in this clone; use fetch-depth: 0")
    tmp = Path(tempfile.mkdtemp(prefix="mw-research-fixture-"))
    clone = tmp / "repo"
    subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", str(REPO), str(clone)], check=True)
    _git(clone, "checkout", "-q", "--detach", FIXTURE_COMMIT)
    shutil.rmtree(clone / "scripts")
    shutil.copytree(REPO / "scripts", clone / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    _STATE["tmp"] = tmp
    _STATE["root"] = clone
    _STATE["head"] = _commit(clone, "fixture: current scripts over the 2026-10-27 pre-trader freeze")


def tearDownModule():
    tmp = _STATE.get("tmp")
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)


class FixtureCase(unittest.TestCase):
    @property
    def root(self) -> Path:
        return Path(_STATE["root"])

    def setUp(self):
        _git(self.root, "reset", "-q", "--hard", str(_STATE["head"]))
        _git(self.root, "clean", "-qfdx", "-e", "__pycache__")

    tearDown = setUp

    def read(self, rel) -> dict:
        return json.loads((self.root / rel).read_text(encoding="utf-8"))

    def write(self, rel, payload) -> None:
        (self.root / rel).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def edit_launch(self, mutate) -> None:
        launch = self.read(LAUNCH_REL / "launch.json")
        mutate(launch)
        self.write(LAUNCH_REL / "launch.json", launch)

    def contract(self, **kwargs):
        kwargs.setdefault("now", NOW)
        return rp.research_contract(self.root, **kwargs)

    def assertRefused(self, kind, reason, **kwargs):
        with self.assertRaises(rp.ResearchRefusal) as ctx:
            self.contract(**kwargs)
        self.assertEqual((ctx.exception.kind, ctx.exception.reason), (kind, reason), ctx.exception.detail)
        return ctx.exception

    def digest(self, rel) -> str:
        return hashlib.sha256((self.root / rel).read_bytes()).hexdigest()


class EligibilityTests(FixtureCase):
    def test_fresh_stage04_is_eligible_without_accepted_current_cycle(self):
        contract = self.contract()
        self.assertEqual(contract["launch_id"], LAUNCH)
        self.assertEqual((contract["session_date"], contract["review_id"], contract["packet_sha256"]), ("2026-10-27", REVIEW, PACKET))
        self.assertEqual(contract["books"]["overnight_run_id"], "overnight-20261026")
        self.assertNotEqual(contract["books"]["packet_sha256"], PACKET)
        self.assertFalse((self.root / "data/overnight/runs/overnight-20261027/assembled_dataset.json").exists())
        self.assertFalse(contract["news"]["current_session"])
        self.assertEqual(contract["news"]["age_label"], "21 h before this freeze")
        self.assertEqual(contract["headlines"]["status"], "available")
        self.assertEqual(len(contract["headlines"]["items"]), 6)
        self.assertEqual(contract["headlines"]["packet_sha256"], PACKET)
        self.assertEqual(contract["quality"]["coverage"], "PARTIAL")
        self.assertEqual(contract["remote_freeze_commit"], self.read(LAUNCH_REL / "remote_freeze.json")["commit_sha"])
        receipts = {row["path"]: row["sha256"] for row in contract["inputs"]}
        self.assertEqual(receipts[(LAUNCH_REL / "freeze_binding.json").as_posix()], self.digest(LAUNCH_REL / "freeze_binding.json"))
        self.assertIn("data/overnight/runs/overnight-20261027/reviews/review-001/evidence_snapshot.json", receipts)

    def test_no_live_launch_skips(self):
        index = self.read("data/market_watch_launches/index.json")
        index["live_launch_id"] = None
        self.write("data/market_watch_launches/index.json", index)
        self.assertRefused(rp.SKIP, "no_live_launch")

    def test_stub_fixture_and_unpublished_launches_skip(self):
        for key, value, reason in (
            ("provider", "stub", "provider_not_acp"),
            ("mode", "fixture", "mode_not_live"),
            ("publish_production", False, "production_publication_not_requested"),
        ):
            with self.subTest(key=key):
                self.setUp()
                self.edit_launch(lambda launch: launch["request"].__setitem__(key, value))
                self.assertRefused(rp.SKIP, reason)

    def test_terminal_launch_skips(self):
        self.edit_launch(lambda launch: launch.__setitem__("status", "succeeded"))
        self.assertRefused(rp.SKIP, "final_phase_published")
        self.edit_launch(lambda launch: launch.__setitem__("status", "failed"))
        self.assertRefused(rp.SKIP, "launch_not_live")

    def test_remote_attestation_missing_fails_closed(self):
        (self.root / LAUNCH_REL / "remote_freeze.json").unlink()
        self.assertRefused(rp.FAIL, "remote_freeze_attestation_missing")

    def test_remote_attestation_mismatch_fails_closed(self):
        attest = self.read(LAUNCH_REL / "remote_freeze.json")
        attest["packet_sha256"] = "0" * 64
        self.write(LAUNCH_REL / "remote_freeze.json", attest)
        _commit(self.root, "tamper attestation")
        self.assertRefused(rp.FAIL, "remote_freeze_attestation_mismatch")

    def test_binding_rewritten_after_attestation_fails_closed(self):
        binding = self.read(LAUNCH_REL / "freeze_binding.json")
        (self.root / LAUNCH_REL / "freeze_binding.json").write_text(json.dumps(binding, sort_keys=True), encoding="utf-8")
        _commit(self.root, "rewrite binding bytes")
        self.assertRefused(rp.FAIL, "remote_freeze_binding_changed_since_attestation")

    def test_attested_commit_not_in_checkout_fails_closed(self):
        attest = self.read(LAUNCH_REL / "remote_freeze.json")
        attest["commit_sha"] = "1" * 40
        self.write(LAUNCH_REL / "remote_freeze.json", attest)
        _commit(self.root, "point attestation elsewhere")
        self.assertRefused(rp.FAIL, "remote_freeze_commit_not_in_checkout")

    def test_uncommitted_checkout_drift_fails_closed(self):
        path = self.root / LAUNCH_REL / "remote_freeze.json"
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        self.assertRefused(rp.FAIL, "checkout_differs_from_committed_attestation")

    def test_stage_artifact_drift_fails_closed(self):
        artifact = self.read(LAUNCH_REL / "artifacts" / "03_quality_gate.json")
        artifact["tampered"] = True
        self.write(LAUNCH_REL / "artifacts" / "03_quality_gate.json", artifact)
        self.assertRefused(rp.FAIL, "stage_artifact_hash_drift")

    def test_quality_gate_reject_fails_closed(self):
        self.edit_launch(lambda launch: launch["stages"]["03_quality_gate"]["details"].__setitem__("outcome", "FAIL"))
        self.assertRefused(rp.FAIL, "quality_gate_not_pass")

    def test_freeze_stage_not_succeeded_fails_closed(self):
        self.edit_launch(lambda launch: launch["stages"]["04_freeze"].__setitem__("status", "failed"))
        self.assertRefused(rp.FAIL, "freeze_stage_not_succeeded")

    def test_mutated_packet_fails_closed(self):
        rel = Path("data/overnight/runs/overnight-20261027/reviews/review-001/evidence_snapshot.json")
        packet = self.read(rel)
        packet["families"]["market_state"]["data"]["generated_at"] = "2026-10-26T09:00:00Z"
        self.write(rel, packet)
        self.assertRefused(rp.FAIL, "frozen_packet_invalid")

    def test_missing_or_tampered_staged_scores_fail_closed_without_fallback(self):
        scores = self.root / LAUNCH_REL / "lineage" / "temperature_scores.json"
        scores.write_text(scores.read_text(encoding="utf-8") + " ", encoding="utf-8")
        self.assertRefused(rp.FAIL, "staged_scores_hash_mismatch")
        scores.unlink()
        self.assertRefused(rp.FAIL, "staged_scores_missing")
        self.setUp()
        (self.root / LAUNCH_REL / "lineage" / "history" / "nz.json").unlink()
        self.assertRefused(rp.FAIL, "staged_history_missing")

    def test_prior_day_dataset_cannot_be_published_as_today(self):
        self.assertRefused(rp.SKIP, "session_not_today", now=NEXT_DAY)
        self.edit_launch(lambda launch: launch.__setitem__("session_date", "2026-10-26"))
        self.assertRefused(rp.FAIL, "freeze_session_mismatch")

    def test_expected_identity_from_select_must_match(self):
        self.assertRefused(rp.FAIL, "expected_review_mismatch", expected_review_id="review-002")
        self.assertRefused(rp.FAIL, "expected_packet_mismatch", expected_packet_sha256="0" * 64)

    def test_acceptance_or_finalization_supersedes_research(self):
        for stage in ("06_acceptance", "07_finalize"):
            with self.subTest(stage=stage):
                self.setUp()
                self.edit_launch(lambda launch: launch["stages"][stage].__setitem__("status", "succeeded"))
                self.assertRefused(rp.SKIP, "final_phase_authorized")
        self.setUp()
        run = Path("data/overnight/runs/overnight-20261027")
        self.write(run / "assembled_dataset.json", {"packet_sha256": PACKET, "overnight_run_id": "overnight-20261027"})
        self.write("data/overnight/latest.json", {"overnight_run_id": "overnight-20261027", "as_of": "2026-10-27T08:50:00-04:00"})
        self.assertRefused(rp.SKIP, "final_phase_authorized")

    def test_newer_launch_supersedes_unless_concurrency_blocked(self):
        newer = "mwl-20261027T150000Z-0000beef"
        index = self.read("data/market_watch_launches/index.json")
        index["launches"].append({"launch_id": newer, "session_date": "2026-10-27", "status": "blocked"})
        self.write("data/market_watch_launches/index.json", index)
        record = self.read(LAUNCH_REL / "launch.json")
        record.update({"launch_id": newer, "status": "blocked"})
        record["stages"]["00_authenticate"]["reason"] = rp.CONCURRENCY_BLOCK
        (self.root / "data/market_watch_launches" / newer).mkdir()
        self.write(Path("data/market_watch_launches") / newer / "launch.json", record)
        self.assertEqual(self.contract()["launch_id"], LAUNCH)
        record["stages"]["00_authenticate"]["reason"] = "other"
        self.write(Path("data/market_watch_launches") / newer / "launch.json", record)
        self.assertRefused(rp.SKIP, "newer_launch_exists")

    def test_provider_delay_keeps_research_eligible_while_traders_pending(self):
        self.edit_launch(lambda launch: launch["stages"]["05_acp_handoff"].__setitem__("status", "running"))
        self.assertEqual(self.contract()["launch_id"], LAUNCH)


class SiteTests(FixtureCase):
    @classmethod
    def setUpClass(cls):
        root = Path(_STATE["root"])
        _git(root, "reset", "-q", "--hard", str(_STATE["head"]))
        cls.site_root = Path(tempfile.mkdtemp(prefix="mw-research-site-"))
        cls.protected = [
            LAUNCH_REL / "launch.json",
            Path("data/market_watch_launches/index.json"),
            Path("data/temperature_scores.json"),
            Path("data/temperature_history/score_paths.json"),
            Path("data/temperature_history/nz.json"),
            Path("data/policy_state.json"),
            Path("data/overnight/latest.json"),
        ]
        cls.before = {rel: hashlib.sha256((root / rel).read_bytes()).hexdigest() for rel in cls.protected}
        cls.contract_ = rp.research_contract(root, now=NOW)
        cls.site = cls.site_root / "site"
        cls.release = rp.build_research_site(root, cls.site, cls.contract_, now=NOW)
        cls.status_after = _git(root, "status", "--porcelain")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.site_root, ignore_errors=True)

    def copy_site(self) -> Path:
        target = Path(tempfile.mkdtemp(prefix="mw-research-tamper-")) / "site"
        shutil.copytree(self.site, target)
        self.addCleanup(shutil.rmtree, target.parent, True)
        return target

    def assertInvalid(self, site: Path, reason: str):
        with self.assertRaises(rp.ResearchRefusal) as ctx:
            rp.validate_research_site(site, self.contract_)
        self.assertEqual(ctx.exception.reason, reason, ctx.exception.detail)

    def test_build_is_read_only_on_source_checkout(self):
        self.assertEqual(self.status_after, "")
        for rel, digest in self.before.items():
            self.assertEqual(self.digest(rel), digest, rel)
        self.assertFalse((self.root / LAUNCH_REL / pr.RESEARCH_RECEIPT_NAME).exists())
        self.assertEqual(self.read(LAUNCH_REL / "launch.json")["stages"]["08_pages"]["status"], "pending")
        self.assertEqual(self.read("data/market_watch_launches/index.json")["live_launch_id"], LAUNCH)

    def test_release_identity_and_phase(self):
        release = json.loads((self.site / pr.RELEASE_FILENAME).read_text())
        self.assertEqual(release, self.release)
        self.assertEqual((release["phase"], release["channel"], release["trigger"]), ("research", "local", "stage04_verified"))
        self.assertEqual((release["launch_id"], release["review_id"], release["packet_sha256"]), (LAUNCH, REVIEW, PACKET))
        self.assertEqual(release["trader_cycle"], {"status": "pending", "overnight_run_id": "overnight-20261027"})
        self.assertEqual(release["site_sha256"], pr.site_digest(self.site))
        self.assertEqual(pr.release_rank(release), ("2026-10-27", "20261027T093212Z", 1))

    def test_visible_edition_labels(self):
        html = (self.site / "index.html").read_text(encoding="utf-8")
        self.assertIn("Research edition · Tue 27 Oct 2026 · provisional", html)
        self.assertIn("Trader &amp; PM cycle for Tue 27 Oct 2026: <b>pending</b>", html)
        self.assertIn("evidence boundary 27 Oct 2026 05:32 ET", html)
        self.assertIn("market data snapshot 27 Oct 2026 05:50 ET", html)
        self.assertIn("Previous accepted books.", html)
        self.assertIn("overnight-20261026</span> (as of 26 Oct 2026 07:37 ET, accepted 26 Oct 2026 08:55 ET)", html)
        self.assertIn("Previous accepted analysis (as of 26 Oct 2026 07:37 ET)", html)
        self.assertIn('data-headlines-panel="front"', html)
        self.assertIn('data-headlines-panel="news"', html)
        self.assertIn("Current verified headlines (as of 27 Oct 2026 05:32 ET)", html)
        release = json.loads((self.site / pr.RELEASE_FILENAME).read_text())
        self.assertEqual(release.get("headlines"), self.contract_["headlines"])
        self.assertIn("PARTIAL coverage (macro:NZ)", html)
        self.assertNotIn("Final edition", html)
        self.assertNotIn("Last refreshed 27 Oct 2026", html)
        self.assertIn("Last refreshed 26 Oct 2026 · 07:37 ET", html)

    def test_books_are_previous_cycle_with_full_roster(self):
        trader = json.loads((self.site / "trader-books.json").read_text())
        self.assertEqual(trader["publication"]["trader_books_status"], "previous_cycle")
        self.assertEqual(trader["edition"]["books_overnight_run_id"], "overnight-20261026")
        self.assertEqual(trader["edition"]["current_cycle_overnight_run_id"], "overnight-20261027")
        self.assertEqual(len(trader["seats"]), 14)
        pm = json.loads((self.site / "pm-books.json").read_text())
        self.assertEqual(pm["publication"]["pm_books_status"], "previous_cycle")
        self.assertNotIn("overnight-20261027", json.dumps(trader["seats"]))

    def test_market_data_and_sources_are_from_this_freeze(self):
        market = json.loads((self.site / "market-state.json").read_text())
        self.assertEqual(market["generated_at"], "2026-10-27T09:50:58Z")
        health = json.loads((self.site / "source-health.json").read_text())
        self.assertEqual(health["launch_id"], LAUNCH)

    def _restamp_site_digest(self, site: Path) -> None:
        release = json.loads((site / pr.RELEASE_FILENAME).read_text(encoding="utf-8"))
        release["site_sha256"] = pr.site_digest(site)
        (site / pr.RELEASE_FILENAME).write_text(pr.canonical_json(release), encoding="utf-8")

    def test_headline_url_with_ampersand_passes_validation(self):
        site = self.copy_site()
        contract = json.loads(json.dumps(self.contract_))
        items = list(contract["headlines"]["items"])
        old_url = items[0]["url"]
        new_url = "https://www.cnbc.com/2026/10/27/story?a=1&b=2"
        items[0] = {**items[0], "url": new_url}
        contract["headlines"]["items"] = items
        path = site / "index.html"
        text = path.read_text(encoding="utf-8")
        text = text.replace(f'href="{pr._esc(old_url)}"', f'href="{pr._esc(new_url)}"')
        path.write_text(text, encoding="utf-8")
        release = json.loads((site / pr.RELEASE_FILENAME).read_text(encoding="utf-8"))
        release["headlines"] = contract["headlines"]
        (site / pr.RELEASE_FILENAME).write_text(pr.canonical_json(release), encoding="utf-8")
        self._restamp_site_digest(site)
        rp.validate_research_site(site, contract)

    def test_rebuild_is_byte_identical(self):
        second = self.site_root / "second"
        release = rp.build_research_site(self.root, second, self.contract_, now=NOW)
        self.assertEqual(release["site_sha256"], self.release["site_sha256"])
        with self.assertRaises(rp.ResearchRefusal) as ctx:
            rp.build_research_site(self.root, second, self.contract_, now=NOW)
        self.assertEqual(ctx.exception.reason, "site_dir_not_empty")

    def test_validator_rejects_tampered_sites(self):
        cases = []

        def html_edit(old, new):
            def apply(site):
                path = site / "index.html"
                text = path.read_text(encoding="utf-8")
                self.assertIn(old, text)
                path.write_text(text.replace(old, new), encoding="utf-8")
            return apply

        def json_edit(name, mutate):
            def apply(site):
                payload = json.loads((site / name).read_text())
                mutate(payload)
                (site / name).write_text(json.dumps(payload), encoding="utf-8")
            return apply

        cases.append(("site_digest_mismatch", html_edit("Previous accepted books.", "Accepted books.")))
        cases.append(("release_claims_trader_cycle", json_edit("release.json", lambda r: r["trader_cycle"].__setitem__("status", "accepted"))))
        cases.append(("release_identity_mismatch", json_edit("release.json", lambda r: r.__setitem__("packet_sha256", "0" * 64))))
        for reason, mutate in cases:
            with self.subTest(reason=reason):
                site = self.copy_site()
                mutate(site)
                self.assertInvalid(site, reason)

        restamped = [
            ("trader_books_presented_as_current", json_edit("trader-books.json", lambda t: t["publication"].__setitem__("trader_books_status", "fresh"))),
            ("trader_books_roster_incomplete", json_edit("trader-books.json", lambda t: t.__setitem__("seats", t["seats"][:13]))),
            ("trader_books_dates_mismatch", json_edit("trader-books.json", lambda t: t.__setitem__("books_as_of", "2026-10-27T05:00:00-04:00"))),
            ("market_state_not_frozen_packet", json_edit("market-state.json", lambda m: m.__setitem__("generated_at", "2026-10-27T13:00:00Z"))),
            ("source_health_not_this_launch", json_edit("source-health.json", lambda h: h.__setitem__("launch_id", PREV_LAUNCH))),
            ("stale_news_labeled_current", html_edit("Last refreshed 26 Oct 2026 · 07:37 ET", "Last refreshed 26 Oct 2026 · 07:37 ET Last refreshed 27 Oct 2026 · 05:32 ET")),
            ("news_age_note_missing", html_edit('data-edition-note="news"', 'data-x="news"')),
            ("trader_book_pending_note_missing", html_edit('data-edition-note="traderbook"', 'data-x="traderbook"')),
            ("forbidden_wording", html_edit("Previous accepted books.", "Previous accepted books. Scores frozen.")),
            (
                "headlines_items_mismatch",
                html_edit('<li data-headline-id="news:3f5406490f809d1a">', '<li data-headline-id="news:removed">'),
            ),
            (
                "current_label_misapplied",
                html_edit(
                    "<b>Previous accepted analysis (as of 26 Oct 2026 07:37 ET).</b>",
                    "<b>Current verified headlines (as of 27 Oct 2026 05:32 ET).</b> "
                    "<b>Previous accepted analysis (as of 26 Oct 2026 07:37 ET).</b>",
                ),
            ),
            (
                "previous_label_misapplied",
                html_edit(
                    "Headline, source and link only;",
                    "Previous accepted analysis (as of 26 Oct 2026 07:37 ET). Headline, source and link only;",
                ),
            ),
        ]
        for reason, mutate in restamped:
            with self.subTest(reason=reason):
                site = self.copy_site()
                mutate(site)
                self._restamp_site_digest(site)
                self.assertInvalid(site, reason)

        site = self.copy_site()
        html = (site / "index.html").read_text(encoding="utf-8")
        front_anchor = 'data-headlines-panel="front"'
        front_at = html.find(front_anchor)
        sec_start = html.rfind('<section class="mw-headlines"', 0, front_at)
        sec_end = html.find("</section>", front_at)
        block = html[sec_start:sec_end]
        right_id = self.contract_["headlines"]["items"][0]["id"]
        wrong_id = self.contract_["headlines"]["items"][2]["id"]
        new_block = block.replace(
            f'data-headline-id="{pr._esc(right_id)}"',
            f'data-headline-id="{pr._esc(wrong_id)}"',
            1,
        )
        (site / "index.html").write_text(html[:sec_start] + new_block + html[sec_end:], encoding="utf-8")
        self._restamp_site_digest(site)
        self.assertInvalid(site, "headlines_items_mismatch")


class DegradedHeadlinesTests(FixtureCase):
    def test_empty_and_unavailable_headlines_render_and_validate(self):
        contract = self.contract()
        for status, reason, items in (
            ("empty", "no_eligible_headlines", []),
            ("unavailable", "news_family_not_fresh", []),
        ):
            with self.subTest(status=status):
                patched = dict(contract)
                headlines = dict(contract["headlines"])
                headlines.update({"status": status, "reason": reason, "items": items})
                if status == "unavailable":
                    headlines.update({"as_of": None, "window": None, "acquisition": None})
                patched["headlines"] = headlines
                release = rp.build_research_release(patched, channel=pr.CHANNEL_LOCAL)
                html = """<!doctype html><html><head><style></style></head><body>
<header class="topbar"></header>
<div class="news-alert market-alert"></div>
<section class="page news"><p>n</p></section>
<section class="page traderbook"><p>t</p></section></body></html>"""
                stamped = pr.stamp_html(html, release)
                self.assertIn(f'data-current-headlines="{status}"', stamped)
                self.assertIn("mw-headlines-empty", stamped)
                if status == "unavailable":
                    self.assertIn("<b class=\"mw-headlines-title\">Current verified headlines: unavailable</b>", stamped)
                    self.assertNotIn("Current verified headlines (as of time not recorded)", stamped)
                site = Path(tempfile.mkdtemp(prefix="mw-degraded-"))
                self.addCleanup(shutil.rmtree, site, True)
                (site / "index.html").write_text(stamped, encoding="utf-8")
                for name in ("trader-books.json", "pm-books.json", "release.json", "market-state.json", "source-health.json", "trader-room.json"):
                    (site / name).write_text("{}", encoding="utf-8")
                self.assertIn("Previous accepted analysis", stamped)


class OverlayTests(FixtureCase):
    def test_overlay_uses_staged_lineage_not_canonical_scores(self):
        canonical = self.root / "data" / "temperature_scores.json"
        scores = json.loads(canonical.read_text(encoding="utf-8"))
        scores["as_of"] = "1999-01-01"
        canonical.write_text(json.dumps(scores), encoding="utf-8")
        contract = self.contract()
        with tempfile.TemporaryDirectory() as tmp:
            work = rp.prepare_overlay(self.root, Path(tmp) / "work", contract)
            staged = work / "data" / "temperature_scores.json"
            self.assertFalse(staged.is_symlink())
            self.assertEqual(staged.read_bytes(), (self.root / LAUNCH_REL / "lineage" / "temperature_scores.json").read_bytes())
            self.assertFalse((work / "data" / "temperature_history" / "nz.json").is_symlink())
            self.assertFalse((work / "data" / "policy_state.json").is_symlink())
            self.assertFalse((work / "scripts").is_symlink())
            self.assertTrue((work / "data" / "overnight").is_symlink())
        self.assertIn("1999-01-01", canonical.read_text(encoding="utf-8"))

    def test_research_module_never_promotes_or_writes_launch_state(self):
        source = (REPO / "scripts" / "market_watch_launch" / "research_pages.py").read_text(encoding="utf-8")
        for forbidden in ("promote_accepted_launch_lineage", "save_launch", "write_launch", "update_index", "release_live"):
            self.assertNotIn(forbidden, source)


class ReceiptAndOrderingTests(FixtureCase):
    def production_release(self, contract=None):
        release = rp.build_research_release(contract or self.contract(), channel=pr.CHANNEL_PRODUCTION)
        release["site_sha256"] = "f" * 64
        return release

    def test_receipt_is_separate_idempotent_and_leaves_launch_untouched(self):
        launch_before = self.digest(LAUNCH_REL / "launch.json")
        index_before = self.digest("data/market_watch_launches/index.json")
        release = self.production_release()
        deploy = {"run_id": "18000000001", "run_attempt": "1", "page_url": "https://x.github.io/mw/", "public_state": "matched"}
        path, changed = rp.record_research_receipt(self.root, release, deploy=deploy)
        self.assertTrue(changed)
        self.assertEqual(path, self.root / LAUNCH_REL / "research_pages.json")
        self.assertEqual(rp.record_research_receipt(self.root, release, deploy=deploy), (path, False))
        rp.record_research_receipt(self.root, release, deploy={**deploy, "run_id": "18000000002"})
        receipt = json.loads(path.read_text())
        self.assertEqual([row["run_id"] for row in receipt["deploys"]], ["18000000001", "18000000002"])
        self.assertFalse(receipt["launch_terminal"])
        self.assertTrue(receipt["stage_08_untouched"])
        self.assertEqual(self.digest(LAUNCH_REL / "launch.json"), launch_before)
        self.assertEqual(self.digest("data/market_watch_launches/index.json"), index_before)
        self.assertEqual(rp.receipt_allowlist(LAUNCH), ((LAUNCH_REL / "research_pages.json").as_posix(),))
        self.assertEqual(self.read("data/market_watch_launches/index.json")["live_launch_id"], LAUNCH)
        self.assertRefused(rp.SKIP, "research_already_published")

    def test_receipt_refuses_local_or_mismatched_release(self):
        local = rp.build_research_release(self.contract(), channel=pr.CHANNEL_LOCAL)
        for release, deploy, reason in (
            (local, {"run_id": "1"}, "receipt_requires_production_research_release"),
            ({**self.production_release(), "packet_sha256": "0" * 64}, {"run_id": "1"}, "receipt_identity_mismatch"),
            (self.production_release(), {"run_id": "abc"}, "receipt_requires_run_id"),
        ):
            with self.subTest(reason=reason):
                with self.assertRaises(rp.ResearchRefusal) as ctx:
                    rp.record_research_receipt(self.root, release, deploy=deploy)
                self.assertEqual(ctx.exception.reason, reason)

    def test_replay_allowed_final_supersedes_and_stale_refresh_refused(self):
        release = self.production_release()
        self.assertTrue(pr.guard_publication(release, root=self.root)["allowed"])
        rp.record_research_receipt(self.root, release, deploy={"run_id": "18000000001"})
        self.assertTrue(pr.guard_publication(release, root=self.root)["allowed"], "replay of the same edition")

        refresh = pr.build_final_release(self.root, channel=pr.CHANNEL_PRODUCTION, source_commit="")
        self.assertEqual((refresh["trigger"], refresh["session_date"], refresh["launch_id"]), ("refresh", "2026-10-26", PREV_LAUNCH))
        refused = pr.guard_publication(refresh, root=self.root)
        self.assertFalse(refused["allowed"])
        self.assertEqual(refused["blocking"]["origin"], f"research_receipt:{LAUNCH}")

        self.edit_launch(lambda launch: launch["stages"]["07_finalize"].__setitem__("status", "succeeded"))
        late = pr.guard_publication(release, root=self.root)
        self.assertFalse(late["allowed"])
        self.assertEqual(late["blocking"]["origin"], f"finalized:{LAUNCH}")
        final = pr.final_release_for_launch(self.read(LAUNCH_REL / "launch.json"))
        self.assertTrue(pr.guard_publication({**final, "type": pr.RELEASE_TYPE}, root=self.root)["allowed"])

    def test_late_research_refused_when_public_already_final(self):
        release = self.production_release()
        public_final = {**pr.final_release_for_launch(self.read(LAUNCH_REL / "launch.json")), "channel": "production"}
        decision = pr.guard_publication(release, root=self.root, public_base_url="https://x.github.io/mw/", opener=lambda url: public_final)
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["blocking"]["origin"], "public_release")


class CliTests(FixtureCase):
    def run_cli(self, *args, env=None):
        out = io.StringIO()
        base = {k: v for k, v in os.environ.items() if not k.startswith("GITHUB_")}
        base.update(env or {})
        with mock.patch.dict(os.environ, base, clear=True), contextlib.redirect_stdout(out):
            code = rp.main(["--root", str(self.root), *args])
        return code, json.loads(out.getvalue())

    ACTIONS_ENV = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": rp.PRODUCTION_REPOSITORY, "GITHUB_REF": "refs/heads/main"}

    def test_select_reports_eligibility_and_skips_with_exit_zero(self):
        code, payload = self.run_cli("select", "--now", NOW.isoformat())
        self.assertEqual((code, payload["eligible"], payload["launch_id"]), (0, True, LAUNCH))
        code, payload = self.run_cli("select", "--now", NEXT_DAY.isoformat())
        self.assertEqual((code, payload["kind"], payload["reason"]), (0, "skip", "session_not_today"))
        (self.root / LAUNCH_REL / "remote_freeze.json").unlink()
        code, payload = self.run_cli("select", "--now", NOW.isoformat())
        self.assertEqual((code, payload["kind"]), (1, "fail"))

    def test_production_channel_needs_actions_on_main(self):
        args = ("build", "--launch-id", LAUNCH, "--review-id", REVIEW, "--packet-sha256", PACKET, "--site-dir", str(self.root / "_site"), "--channel", "production", "--now", NOW.isoformat())
        code, payload = self.run_cli(*args)
        self.assertEqual((code, payload["reason"]), (1, "production_channel_requires_main_actions_run"))
        code, payload = self.run_cli(*args, env={**self.ACTIONS_ENV, "GITHUB_REF": "refs/heads/feature"})
        self.assertEqual((code, payload["reason"]), (1, "production_channel_requires_main_actions_run"))
        self.assertFalse((self.root / "_site").exists())

    def test_stub_launch_cannot_reach_production_even_on_main(self):
        self.edit_launch(lambda launch: launch["request"].__setitem__("provider", "stub"))
        args = ("build", "--launch-id", LAUNCH, "--review-id", REVIEW, "--packet-sha256", PACKET, "--site-dir", str(self.root / "_site"), "--channel", "production", "--now", NOW.isoformat())
        code, payload = self.run_cli(*args, env=self.ACTIONS_ENV)
        self.assertEqual((code, payload["reason"]), (0, "provider_not_acp"))
        self.assertFalse((self.root / "_site").exists())

    def test_guard_refuses_local_release_and_superseded_production_release(self):
        site = self.root / "_guard"
        site.mkdir()
        local = rp.build_research_release(self.contract(), channel=pr.CHANNEL_LOCAL)
        (site / pr.RELEASE_FILENAME).write_text(pr.canonical_json(local), encoding="utf-8")
        code, payload = self.run_cli("guard", "--site-dir", str(site), "--now", NOW.isoformat(), env=self.ACTIONS_ENV)
        self.assertEqual((code, payload["reason"]), (1, "deploy_requires_production_release"))
        production = rp.build_research_release(self.contract(), channel=pr.CHANNEL_PRODUCTION)
        (site / pr.RELEASE_FILENAME).write_text(pr.canonical_json(production), encoding="utf-8")
        code, payload = self.run_cli("guard", "--site-dir", str(site), "--now", NOW.isoformat(), env=self.ACTIONS_ENV)
        self.assertEqual((code, payload["allowed"]), (0, True))
        self.edit_launch(lambda launch: launch["stages"]["07_finalize"].__setitem__("status", "succeeded"))
        code, payload = self.run_cli("guard", "--site-dir", str(site), "--now", NOW.isoformat(), env=self.ACTIONS_ENV)
        self.assertEqual((code, payload["kind"], payload["reason"]), (0, "skip", "final_phase_authorized"))

if __name__ == "__main__":
    unittest.main()
