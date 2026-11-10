"""Production-shaped publication acceptance (integrator scenarios 1, 3, 7)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from scripts.market_watch_launch.contract import AWAITING_ACP, TWO_TRIGGER_CONTRACT
from scripts.market_watch_launch import publication_release as pr
from scripts.market_watch_launch import publication_issues as pi
from scripts.market_watch_launch import research_pages as rp
from scripts.market_watch_launch.milestones import (
    PHASE_RESEARCH_PUBLISHING,
    PHASE_RESEARCH_READY,
    launch_phase,
    research_publication,
    trader_acceptance_refusal,
)
from scripts.market_watch_launch.publication_checks import strip_issues_panel
from scripts.market_watch_launch.state import LaunchStateStore
from scripts.overnight.errors import PublicationError
from scripts.overnight.publish import publication_gate
from scripts.overnight.store import OvernightStore

REPO = Path(__file__).resolve().parents[1]
INVENTORY = REPO / "docs" / "publication_gate_inventory.json"
FIXTURE_COMMIT = "e9f757d7d6ae83e6c017fd9f95a1da40addda9ad"
LAUNCH = "mwl-20261027T093212Z-9512d95d"
LAUNCH_REL = Path("data") / "market_watch_launches" / LAUNCH
REVIEW = "review-001"
PACKET = "74b06c13f1215b6521678c764356cae8ae2788e19bad038dad0a79f7e35f2109"
NOW = datetime(2026, 10, 27, 14, 30, tzinfo=timezone.utc)

_FORBIDDEN_SUBPROCESS = ("trader_room_go", "pm-chatgpt", "acp_handshake", "cursor-agent", "provider")

_CLONE: dict[str, Path | str] = {}


def _git(root: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    if check and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr}")
    return proc.stdout.strip()


def _bootstrap_fixture_clone() -> None:
    if _CLONE.get("root") and _CLONE.get("head"):
        return
    _CLONE.clear()
    if subprocess.run(["git", "cat-file", "-e", f"{FIXTURE_COMMIT}^{{commit}}"], cwd=REPO, check=False).returncode != 0:
        raise unittest.SkipTest(f"fixture commit {FIXTURE_COMMIT} is not in this clone")
    tmp = Path(tempfile.mkdtemp(prefix="mw-acceptance-fixture-"))
    clone = tmp / "repo"
    subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", str(REPO), str(clone)], check=True)
    _git(clone, "checkout", "-q", "--detach", FIXTURE_COMMIT)
    shutil.rmtree(clone / "scripts")
    shutil.copytree(REPO / "scripts", clone / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    _git(clone, "add", "-A")
    _git(
        clone,
        "-c",
        "user.name=fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-q",
        "-m",
        "fixture scripts for acceptance",
    )
    head = _git(clone, "rev-parse", "HEAD")
    _CLONE["tmp"] = tmp
    _CLONE["root"] = clone
    _CLONE["head"] = head


def _teardown_fixture_clone() -> None:
    tmp = _CLONE.pop("tmp", None)
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)


class FixtureCloneCase(unittest.TestCase):
    root: Path
    head: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(_CLONE["root"])
        cls.head = str(_CLONE["head"])

    def setUp(self) -> None:
        _git(self.root, "reset", "-q", "--hard", self.head)
        _git(self.root, "clean", "-qfdx", "-e", "__pycache__")
        self._prepare_handoff_for_research_ready()

    def _prepare_handoff_for_research_ready(self) -> None:
        launch_path = self.root / LAUNCH_REL / "launch.json"
        launch = json.loads(launch_path.read_text(encoding="utf-8"))
        handoff = launch.setdefault("stages", {}).setdefault("05_acp_handoff", {})
        launch["publication_contract"] = TWO_TRIGGER_CONTRACT
        handoff["status"] = "blocked"
        handoff["reason"] = AWAITING_ACP
        details = handoff.setdefault("details", {})
        details.pop("research_publication", None)
        launch_path.write_text(json.dumps(launch, indent=2) + "\n", encoding="utf-8")

    def contract(self, **kwargs):
        kwargs.setdefault("now", NOW)
        kwargs.setdefault("expected_review_id", REVIEW)
        kwargs.setdefault("expected_packet_sha256", PACKET)
        return rp.research_contract(self.root, LAUNCH, require_git=False, **kwargs)

    def build_site(self, site_dir: Path) -> dict:
        contract = self.contract()
        return rp.build_research_site(
            self.root,
            site_dir,
            contract,
            channel=pr.CHANNEL_LOCAL,
            now=NOW,
            fetch_schedules=False,
        )

    def launch_on_disk(self) -> dict:
        return json.loads((self.root / LAUNCH_REL / "launch.json").read_text(encoding="utf-8"))

    def sync_handoff_publication(self, launch: dict) -> dict:
        store = LaunchStateStore(self.root)
        pub = research_publication(store.launch_dir(LAUNCH), launch)
        self.assertIsNotNone(pub)
        launch = store.load_launch(LAUNCH)
        handoff = launch["stages"]["05_acp_handoff"]
        handoff.setdefault("details", {})["research_publication"] = pub
        store.save_launch(launch)
        return launch


class PublicationGateUnitTests(unittest.TestCase):
    def test_inventory_documents_soft_news_and_tab_marker_removal(self):
        gates = {row["id"]: row for row in json.loads(INVENTORY.read_text(encoding="utf-8"))["gates"]}
        self.assertEqual(gates["books.publish_check_news_html"]["decision"], "BECOME_ISSUE")
        self.assertIn("soft", gates["books.publish_check_news_html"].get("note", "").lower())
        self.assertIn("REMOVE", gates["render.trader_book_tab"].get("note", ""))

    def test_publish_gate_soft_skips_wall_clock_news_freshness(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / "_site"
            site.mkdir()
            (site / "index.html").write_text("<html><body>placeholder</body></html>", encoding="utf-8")
            diag = Path(tmp) / "diag.jsonl"
            store = OvernightStore(root=REPO)
            ctx = {"as_of": "2020-01-01T00:00:00Z", "news": []}
            with mock.patch("scripts.overnight.publish.load_assembled", return_value=None):
                with mock.patch("scripts.overnight.publish.effective_public_news_context", return_value=ctx):
                    with mock.patch("scripts.overnight.publish.age_status", return_value="stale"):
                        with mock.patch.dict(os.environ, {"MW_RENDER_DIAGNOSTICS": str(diag)}):
                            gate = publication_gate(
                                store,
                                run_id=None,
                                require_dataset=False,
                                site_dir=site,
                                news_policy="soft",
                            )
            self.assertTrue(gate.get("may_publish"))
            lines = [json.loads(line) for line in diag.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertTrue(any(row.get("code") == "news_freshness_soft" for row in lines))

    def test_publish_gate_strict_still_raises_on_stale_news(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / "_site"
            site.mkdir()
            (site / "index.html").write_text("<html></html>", encoding="utf-8")
            store = OvernightStore(root=REPO)
            ctx = {"as_of": "2020-01-01T00:00:00Z", "news": []}
            with mock.patch("scripts.overnight.publish.load_assembled", return_value=None):
                with mock.patch("scripts.overnight.publish.effective_public_news_context", return_value=ctx):
                    with mock.patch("scripts.overnight.publish.age_status", return_value="stale"):
                        with self.assertRaises(PublicationError):
                            publication_gate(
                                store,
                                run_id=None,
                                require_dataset=False,
                                site_dir=site,
                                news_policy="strict",
                            )


class NormalDayPublicationChainTests(FixtureCloneCase):
    # Scenario (1)

    def test_research_build_receipt_milestones_and_final_ordering(self):
        launch = self.launch_on_disk()
        launch_dir = self.root / LAUNCH_REL
        verified_before = research_publication(launch_dir, launch)
        self.assertIsNone(verified_before)
        self.assertNotEqual(launch_phase(launch, research_verified=False), PHASE_RESEARCH_READY)
        self.assertEqual(trader_acceptance_refusal(self.root, launch), "research_publication_not_verified")

        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / "site"
            built = self.build_site(site)
        contract = self.contract()
        production = rp.build_research_release(contract, channel=pr.CHANNEL_PRODUCTION)
        production["site_sha256"] = pr.site_digest(site)
        deploy = {
            "run_id": "18100000001",
            "run_attempt": "1",
            "page_url": "https://example.github.io/market-watch-public-dashboard/",
            "public_state": "matched",
            "recorded_at": NOW.isoformat(),
        }
        rp.record_research_receipt(self.root, production, deploy=deploy)

        launch = self.launch_on_disk()
        launch = self.sync_handoff_publication(launch)
        verified_after = research_publication(launch_dir, launch)
        self.assertIsNotNone(verified_after)
        self.assertEqual(verified_after.get("public_state"), "matched")
        self.assertEqual(launch_phase(launch, research_verified=True), PHASE_RESEARCH_READY)
        self.assertIsNone(trader_acceptance_refusal(self.root, launch))

        research_release = dict(production)
        research_release["site_sha256"] = built["site_sha256"]
        final_candidate = pr.final_release_for_launch(launch)
        known = pr.committed_publications(self.root)
        allow_final = pr.ordering_decision(final_candidate, known=known)
        self.assertTrue(allow_final["allowed"], allow_final)

        launch = self.launch_on_disk()
        launch["stages"]["07_finalize"]["status"] = "succeeded"
        (self.root / LAUNCH_REL / "launch.json").write_text(json.dumps(launch, indent=2) + "\n", encoding="utf-8")
        known_after_final = pr.committed_publications(self.root)
        for origin, release in known_after_final:
            if origin == f"finalized:{LAUNCH}":
                break
        else:
            self.fail("finalized release not in committed publications")
        block_research = pr.ordering_decision(research_release, known=known_after_final)
        self.assertFalse(block_research["allowed"])
        self.assertEqual(block_research["reason"], pr.SUPERSEDED)


class CountryDetailIsolationFullBuildTests(FixtureCloneCase):
    # Scenario (3)

    def test_one_country_detail_failure_isolates_in_full_research_build(self):
        marker = self.root / "data" / "country_detail" / "au_render_failure.marker"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("fixture\n", encoding="utf-8")
        self.addCleanup(lambda: marker.unlink(missing_ok=True))

        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / "site"
            release = self.build_site(site)
            self.assertEqual(release["phase"], "research")
            contract = self.contract()
            rp.validate_research_site(site, contract)

            html = strip_issues_panel((site / "index.html").read_text(encoding="utf-8"))
            au_start = html.find('<div class="cdetail au">')
            nz_start = html.find('<div class="cdetail nz">', au_start)
            au_block = html[au_start:nz_start]
            self.assertIn('data-country-detail-state="unavailable"', au_block)
            self.assertNotIn('class="score-num"', au_block)
            for key in ("us", "ca", "nz", "ea", "jp"):
                idx = html.find(f'<div class="cdetail {key}">')
                self.assertGreater(idx, 0, key)
                snippet = html[idx : idx + 8000]
                self.assertNotIn('data-country-detail-state="unavailable"', snippet, key)

            feed = json.loads((site / pi.ISSUES_FILENAME).read_text(encoding="utf-8"))
            chart_rows = [
                row
                for row in feed.get("issues") or []
                if row.get("category") == "chart"
                and row.get("component") == "country_detail"
                and row.get("country") == "AU"
            ]
            self.assertEqual(len(chart_rows), 1, chart_rows)


class FrozenLaunchRecoveryTests(FixtureCloneCase):
    # Scenario (7)

    def test_identical_research_rebuild_and_recovery_guards(self):
        recorded_argv: list[list[str]] = []
        real_run = subprocess.run

        def recording_run(cmd, *args, **kwargs):
            recorded_argv.append([str(part) for part in (cmd if isinstance(cmd, (list, tuple)) else [cmd])])
            return real_run(cmd, *args, **kwargs)

        with mock.patch("scripts.market_watch_launch.render_steps.subprocess.run", side_effect=recording_run):
            with tempfile.TemporaryDirectory() as tmp:
                site_a = Path(tmp) / "site-a"
                site_b = Path(tmp) / "site-b"
                rel_a = self.build_site(site_a)
                rel_b = self.build_site(site_b)

        joined = " ".join(" ".join(row) for row in recorded_argv).lower()
        for token in _FORBIDDEN_SUBPROCESS:
            self.assertNotIn(token, joined, token)
        self.assertFalse(any("fetch" in row and "schedule" in " ".join(row).lower() for row in recorded_argv))

        self.assertEqual(rel_a["site_sha256"], rel_b["site_sha256"])
        self.assertEqual(
            (rel_a["launch_id"], rel_a["review_id"], rel_a["packet_sha256"]),
            (rel_b["launch_id"], rel_b["review_id"], rel_b["packet_sha256"]),
        )

        contract = self.contract()
        production = rp.build_research_release(contract, channel=pr.CHANNEL_PRODUCTION)
        production["site_sha256"] = rel_a["site_sha256"]
        rp.record_research_receipt(
            self.root,
            production,
            deploy={"run_id": "18100000002", "public_state": "matched"},
        )

        with self.assertRaises(rp.ResearchRefusal) as ctx:
            self.contract()
        self.assertEqual(ctx.exception.kind, rp.SKIP)
        self.assertEqual(ctx.exception.reason, "research_already_published")

        launch_path = self.root / LAUNCH_REL / "launch.json"
        launch = json.loads(launch_path.read_text(encoding="utf-8"))
        launch["stages"]["07_finalize"]["status"] = "succeeded"
        launch_path.write_text(json.dumps(launch, indent=2) + "\n", encoding="utf-8")

        with self.assertRaises(rp.ResearchRefusal) as ctx2:
            self.contract()
        self.assertEqual(ctx2.exception.kind, rp.SKIP)
        self.assertEqual(ctx2.exception.reason, "final_phase_authorized")


def setUpModule():
    _bootstrap_fixture_clone()


def tearDownModule():
    _teardown_fixture_clone()


if __name__ == "__main__":
    unittest.main()
