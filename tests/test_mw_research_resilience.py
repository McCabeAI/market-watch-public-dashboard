"""Research edition keeps publishing when optional parts fail, and still refuses hard breaches.

The 2026-10-27 fixture is commit e9f757d7. The Nov 10 anchor regression uses
launch mwl-20261110T095036Z-eaa0689a (freeze commit d6c297e2). News, score, and
country fallbacks are the real ``render_fallbacks`` implementations: those cases
pass once that module neutralizes stale base content.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.market_watch_launch import publication_issues as pi
from scripts.market_watch_launch import publication_release as pr
from scripts.market_watch_launch import research_pages as rp
from scripts.market_watch_launch.publication_checks import strip_issues_panel

REPO = Path(__file__).resolve().parents[1]
FIXTURE_COMMIT = "e9f757d7d6ae83e6c017fd9f95a1da40addda9ad"
LAUNCH = "mwl-20261027T093212Z-9512d95d"
NOW = datetime(2026, 10, 27, 14, 30, tzinfo=timezone.utc)
NOV10_LAUNCH = "mwl-20261110T095036Z-eaa0689a"
NOV10_COMMIT = "d6c297e27f541e52f242e496f427df4f8a847f82"

_STATE: dict[str, Path | str] = {}


def _git(root: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    if check and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr}")
    return proc.stdout.strip()


def setUpModule():
    if subprocess.run(["git", "cat-file", "-e", f"{FIXTURE_COMMIT}^{{commit}}"], cwd=REPO, check=False).returncode != 0:
        raise unittest.SkipTest(f"fixture commit {FIXTURE_COMMIT} is not in this clone; use fetch-depth: 0")
    tmp = Path(tempfile.mkdtemp(prefix="mw-research-resilience-"))
    clone = tmp / "repo"
    subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", str(REPO), str(clone)], check=True)
    _git(clone, "checkout", "-q", "--detach", FIXTURE_COMMIT)
    shutil.rmtree(clone / "scripts")
    shutil.copytree(REPO / "scripts", clone / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    _git(clone, "add", "-A")
    _git(clone, "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "commit", "-q", "-m", "fixture scripts")
    _STATE["tmp"] = tmp
    _STATE["root"] = clone
    _STATE["head"] = _git(clone, "rev-parse", "HEAD")


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
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def contract(self, **kwargs):
        kwargs.setdefault("now", NOW)
        return rp.research_contract(self.root, **kwargs)

    def assertRefused(self, reason, **kwargs):
        with self.assertRaises(rp.ResearchRefusal) as ctx:
            self.contract(**kwargs)
        self.assertEqual(ctx.exception.kind, "fail", ctx.exception.detail)
        self.assertEqual(ctx.exception.reason, reason, ctx.exception.detail)
        return ctx.exception


def _restamp(site: Path) -> None:
    release = json.loads((site / pr.RELEASE_FILENAME).read_text(encoding="utf-8"))
    release["site_sha256"] = pr.site_digest(site)
    (site / pr.RELEASE_FILENAME).write_text(pr.canonical_json(release), encoding="utf-8")


def _minimal_release(**overrides) -> dict:
    release = {
        "type": pr.RELEASE_TYPE,
        "schema_version": 1,
        "phase": pr.PHASE_RESEARCH,
        "channel": pr.CHANNEL_LOCAL,
        "session_date": "2026-11-10",
        "launch_id": NOV10_LAUNCH,
        "review_id": "review-001",
        "packet_sha256": "e" * 64,
        "overnight_run_id": "overnight-20261110",
        "frozen_at": "2026-11-10T04:50:36-05:00",
        "market_state": {"as_of": "2026-11-10T09:50:36Z", "generated_at": "2026-11-10T09:50:36Z"},
        "books": {
            "overnight_run_id": "overnight-20261109",
            "books_run_id": "overnight-20261109",
            "as_of": "2026-11-09T05:37:50-05:00",
            "accepted_at": "2026-11-09T05:37:50-05:00",
            "packet_sha256": "d" * 64,
        },
        "news": {
            "as_of": "2026-11-09T05:37:50-05:00",
            "overnight_run_id": "overnight-20261109",
            "current_session": False,
            "age_label": "23 h before this freeze",
        },
        "headlines": {
            "status": "available",
            "as_of": "2026-11-10T04:50:36-05:00",
            "packet_sha256": "e" * 64,
            "window": {"start": "2026-11-09T05:37:50-05:00", "end": "2026-11-10T04:50:36-05:00", "basis": "previous_acceptance"},
            "items": [
                {
                    "id": "news:nov10",
                    "headline": "Nov 10 sample",
                    "source_name": "Reuters",
                    "url": "https://www.reuters.com/nov10",
                    "published_at": "2026-11-10T04:00:00-05:00",
                    "verification_status": "single_source",
                    "channel": "global_risk",
                }
            ],
        },
        "scores": {},
        "quality": {"outcome": "PASS", "coverage": "COMPLETE"},
    }
    release.update(overrides)
    return release


_PAGE = """<!doctype html><html><head><style>body{}</style></head><body>
<header class="topbar"></header>
<section class="page front"><div class="news-alert market-alert"><p>alert</p></div></section>
<section class="page news"><p>news</p></section>
<section class="page traderbook"><div id="trader-book-root"></div></section>
</body></html>
"""


class HardInputRefusals(FixtureCase):
    def test_mutated_frozen_packet_is_refused(self):
        rel = Path("data/overnight/runs/overnight-20261027/reviews/review-001/evidence_snapshot.json")
        packet = self.read(rel)
        packet["mutated"] = True
        self.write(rel, packet)
        self.assertRefused("frozen_packet_invalid")

    def test_tampered_staged_scores_are_refused(self):
        path = self.root / "data" / "market_watch_launches" / LAUNCH / "lineage" / "temperature_scores.json"
        path.write_bytes(path.read_bytes() + b"\n")
        self.assertRefused("staged_scores_hash_mismatch")


class BuiltResearchResilience(FixtureCase):
    @classmethod
    def setUpClass(cls):
        root = Path(_STATE["root"])
        _git(root, "reset", "-q", "--hard", str(_STATE["head"]))
        cls.contract_ = rp.research_contract(root, now=NOW)
        cls.site_root = Path(tempfile.mkdtemp(prefix="mw-resilience-site-"))
        cls.site = cls.site_root / "site"
        cls.release = rp.build_research_site(root, cls.site, cls.contract_, now=NOW)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.site_root, ignore_errors=True)

    def copy_site(self) -> Path:
        target = Path(tempfile.mkdtemp(prefix="mw-resilience-tamper-")) / "site"
        shutil.copytree(self.site, target)
        self.addCleanup(shutil.rmtree, target.parent, True)
        return target

    def test_issues_feed_is_deterministic_and_bound_into_the_release(self):
        feed_path = self.site / pi.ISSUES_FILENAME
        self.assertTrue(feed_path.is_file())
        first = feed_path.read_bytes()
        feed = json.loads(first)
        self.assertEqual(feed["type"], pi.ISSUES_TYPE)
        self.assertEqual(feed["status"], "available")
        self.assertNotIn("/tmp/", first.decode("utf-8"))
        self.assertEqual(self.release["site_sha256"], pr.site_digest(self.site))
        second_dir = self.site_root / "second"
        second = rp.build_research_site(self.root, second_dir, self.contract_, now=NOW)
        self.assertEqual((second_dir / pi.ISSUES_FILENAME).read_bytes(), first)
        self.assertEqual(second["site_sha256"], self.release["site_sha256"])
        self.assertEqual(second["site_sha256"], pr.site_digest(second_dir))

    def test_false_fresh_market_timestamp_is_refused(self):
        site = self.copy_site()
        market = json.loads((site / "market-state.json").read_text(encoding="utf-8"))
        market["generated_at"] = "2026-10-27T18:00:00Z"
        (site / "market-state.json").write_text(json.dumps(market), encoding="utf-8")
        _restamp(site)
        with self.assertRaises(rp.ResearchRefusal) as ctx:
            rp.validate_research_site(site, self.contract_)
        self.assertEqual(ctx.exception.reason, "market_state_not_frozen_packet")

    def test_current_books_and_wrong_roster_are_refused(self):
        site = self.copy_site()
        trader = json.loads((site / "trader-books.json").read_text(encoding="utf-8"))
        trader["publication"]["trader_books_status"] = "fresh"
        (site / "trader-books.json").write_text(json.dumps(trader), encoding="utf-8")
        _restamp(site)
        with self.assertRaises(rp.ResearchRefusal) as ctx:
            rp.validate_research_site(site, self.contract_)
        self.assertEqual(ctx.exception.reason, "trader_books_presented_as_current")

        site = self.copy_site()
        trader = json.loads((site / "trader-books.json").read_text(encoding="utf-8"))
        trader["seats"] = trader["seats"][:13]
        (site / "trader-books.json").write_text(json.dumps(trader), encoding="utf-8")
        _restamp(site)
        with self.assertRaises(rp.ResearchRefusal) as ctx:
            rp.validate_research_site(site, self.contract_)
        self.assertEqual(ctx.exception.reason, "trader_books_roster_incomplete")

    def test_news_label_newer_than_accepted_is_refused(self):
        site = self.copy_site()
        path = site / "index.html"
        text = path.read_text(encoding="utf-8")
        self.assertIn("Last refreshed 26 Oct 2026", text)
        path.write_text(text.replace("Last refreshed 26 Oct 2026", "Last refreshed 28 Oct 2026", 1), encoding="utf-8")
        _restamp(site)
        with self.assertRaises(rp.ResearchRefusal) as ctx:
            rp.validate_research_site(site, self.contract_)
        self.assertEqual(ctx.exception.reason, "news_label_overstated")

    def test_stale_tape_value_is_refused(self):
        site = self.copy_site()
        path = site / "index.html"
        text = path.read_text(encoding="utf-8")
        marker = 'data-global-tape="repair"'
        self.assertIn(marker, text)
        path.write_text(text.replace(marker, marker + " 4.79%", 1), encoding="utf-8")
        _restamp(site)
        with self.assertRaises(rp.ResearchRefusal) as ctx:
            rp.validate_research_site(site, self.contract_)
        self.assertEqual(ctx.exception.reason, "stale_tape_value")


class OptionalDegradation(FixtureCase):
    def _clear_accepted_news(self) -> None:
        latest = self.read("data/overnight/latest.json")
        rel = latest.get("assembled_dataset")
        self.assertTrue(rel)
        dataset = self.read(rel)
        dataset["agent_research"] = None
        core = dataset.setdefault("core", {})
        for key in ("news", "central_bank_research"):
            family = core.get(key)
            if isinstance(family, dict):
                family["items"] = []
        self.write(rel, dataset)
        artifact = self.root / "data" / "overnight" / "accepted_public_news.json"
        if artifact.exists():
            artifact.unlink()

    def test_accepted_news_missing_publishes_without_a_refresh_label(self):
        self._clear_accepted_news()
        contract = self.contract()
        self.assertEqual(
            contract["news"],
            {
                "status": "unavailable",
                "as_of": None,
                "reason": "accepted_news_missing",
                "current_session": False,
                "age_label": "no accepted news",
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / "site"
            release = rp.build_research_site(self.root, site, contract, now=NOW)
            html = strip_issues_panel((site / "index.html").read_text(encoding="utf-8"))
            feed = json.loads((site / pi.ISSUES_FILENAME).read_text(encoding="utf-8"))
            self.assertEqual(release["site_sha256"], pr.site_digest(site))
        self.assertNotIn("Last refreshed", html)
        self.assertIn("Previous accepted analysis: unavailable", html)
        self.assertTrue(any(row.get("category") == "news" for row in feed.get("issues") or []))

    def test_optional_legacy_patch_failure_still_publishes(self):
        script = self.root / "scripts" / "apply_v11_refresh.py"
        script.write_text("import sys\nsys.exit('v11 refresh forced failure')\n", encoding="utf-8")
        contract = self.contract()
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / "site"
            release = rp.build_research_site(self.root, site, contract, now=NOW)
            feed = json.loads((site / pi.ISSUES_FILENAME).read_text(encoding="utf-8"))
            self.assertEqual(release["site_sha256"], pr.site_digest(site))
        components = [str(row.get("component") or "") for row in feed.get("issues") or []]
        self.assertTrue(any("v11 refresh" in component for component in components), components)
        self.assertEqual(release["phase"], "research")


class Nov10NewsAlertAnchor(unittest.TestCase):
    """The Nov 10 publication failure: zero or many front news-alert anchors must not veto."""

    def _publish(self, html: str) -> tuple[dict, dict]:
        tmp = Path(tempfile.mkdtemp(prefix="mw-nov10-anchor-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        site = tmp / "site"
        site.mkdir()
        (site / "index.html").write_text(html, encoding="utf-8")
        (site / "trader-books.json").write_text("{}\n", encoding="utf-8")
        (site / "pm-books.json").write_text("{}\n", encoding="utf-8")
        rows: list = []
        pr.stamp_site(site, _minimal_release(), diagnostics=rows)
        rows = rows + rows
        feed = pi.publish_issues(site, root=tmp, diagnostics=rows)
        return feed, {"rows": rows, "html": (site / "index.html").read_text(encoding="utf-8")}

    def test_absent_and_duplicated_front_alert_publish_one_issue(self):
        absent = _PAGE.replace('<div class="news-alert market-alert"><p>alert</p></div>', "")
        duplicated = _PAGE.replace(
            '<div class="news-alert market-alert"><p>alert</p></div>',
            '<div class="news-alert market-alert"><p>a</p></div><div class="news-alert market-alert"><p>b</p></div>',
        )
        for label, html in (("absent", absent), ("duplicated", duplicated)):
            with self.subTest(case=label):
                feed, built = self._publish(html)
                self.assertIn('data-headlines-panel="front"', built["html"])
                self.assertIn('data-edition-note="traderbook"', built["html"])
                front = [row for row in feed["issues"] if row.get("component") == "edition:front_headlines"]
                self.assertEqual(len(front), 1, [row.get("component") for row in feed["issues"]])
                self.assertGreaterEqual(front[0]["occurrences"], 2)
                self.assertEqual(front[0]["code"], "edition_anchor_fallback")
                self.assertEqual(front[0]["category"], "render")


if __name__ == "__main__":
    unittest.main()
