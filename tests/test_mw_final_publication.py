"""Acceptance checks for the final Pages edition.

The build is the same offline replay as the Nov 9 fixture: accepted artifacts
in, stamped site out, no trader or model calls.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.market_watch_launch.publication_release import (
    RELEASE_TYPE,
    SUPERSEDED,
    guard_publication,
    ordering_decision,
)
from tests.test_mw_research_parity import DEPLOY, step_blocks
from tests.test_nov9_pages_offline_build import (
    NOV9_LAUNCH,
    NOV9_PACKET,
    NOV9_REVIEW,
    NOV9_RUN,
    POST_STAMP_STEPS,
    PRE_STAMP_STEPS,
    materialize_nov9_fixture,
    offline_env,
    run_offline_steps,
)

REPO = Path(__file__).resolve().parents[1]
IDENTITY_FIELDS = (
    "phase",
    "channel",
    "trigger",
    "session_date",
    "launch_id",
    "review_id",
    "packet_sha256",
    "overnight_run_id",
    "source_commit",
    "site_sha256",
)
RUN_BLOCK_FORBIDDEN = (
    "trader_room_go",
    "pm-chatgpt",
    "cursor-agent",
    "acp_handshake",
    "acp handshake",
)


def _release(site: Path) -> dict:
    return json.loads((site / "release.json").read_text(encoding="utf-8"))


def _run_checks(site: Path, root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.market_watch_launch.publication_checks",
            "final",
            "--site-dir",
            str(site),
            "--root",
            str(root),
        ],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(REPO)},
        capture_output=True,
        text=True,
        check=False,
    )


class FinalPublicationAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = Path(tempfile.mkdtemp(prefix="mw-final-publication-"))
        cls.root = cls._tmp / "fixture"
        materialize_nov9_fixture(cls.root)
        cls.diagnostics = cls._tmp / "render-diagnostics.jsonl"
        cls.env = offline_env(cls.diagnostics)
        run_offline_steps(cls.root, cls.env, PRE_STAMP_STEPS)
        cls.pre_stamp = cls._tmp / "pre-stamp"
        shutil.copytree(cls.root / "_site", cls.pre_stamp)
        run_offline_steps(cls.root, cls.env, POST_STAMP_STEPS)
        cls.site = cls.root / "_site"

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def test_final_edition_builds_and_guard_allows(self) -> None:
        release = _release(self.site)
        self.assertEqual(release.get("phase"), "final")
        self.assertEqual(release.get("launch_id"), NOV9_LAUNCH)
        self.assertEqual(release.get("review_id"), NOV9_REVIEW)
        self.assertEqual(release.get("packet_sha256"), NOV9_PACKET)
        self.assertEqual(release.get("overnight_run_id"), NOV9_RUN)
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.market_watch_launch.publication_release",
                "guard",
                "--site-dir",
                str(self.site),
                "--root",
                str(self.root),
            ],
            cwd=self.root,
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:] or proc.stdout[-2000:])
        decision = json.loads(proc.stdout)
        self.assertTrue(decision["allowed"])
        self.assertEqual(decision["reason"], "monotonic")

    def test_stale_tape_value_refuses_publication(self) -> None:
        site = self._copy_site("stale-tape")
        html_path = site / "index.html"
        html = html_path.read_text(encoding="utf-8")
        marker = 'data-global-tape="repair"'
        self.assertIn(marker, html)
        html_path.write_text(html.replace(marker, marker + " 4.79%", 1), encoding="utf-8")
        proc = _run_checks(site, self.root)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("stale_tape_value", proc.stderr)

    def test_news_label_newer_than_accepted_refuses_publication(self) -> None:
        site = self._copy_site("news-label")
        html_path = site / "index.html"
        html = html_path.read_text(encoding="utf-8")
        html_path.write_text("<p>Last refreshed 31 Dec 2026</p>\n" + html, encoding="utf-8")
        proc = _run_checks(site, self.root)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("news_label_overstated", proc.stderr)

    def test_failed_source_with_success_time_refuses_publication(self) -> None:
        site = self._copy_site("source-health")
        path = site / "source-health.json"
        health = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"rows": []}
        rows = health.setdefault("rows", [])
        rows.append(
            {
                "bucket": "failure",
                "series_id": "TEST_SERIES",
                "last_successful_check": "2026-11-09T12:00:00Z",
            }
        )
        path.write_text(json.dumps(health), encoding="utf-8")
        proc = _run_checks(site, self.root)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("failed_source_given_success_time", proc.stderr)

    def test_newer_publication_makes_guard_refuse(self) -> None:
        candidate = _release(self.site)
        newer_launch = "mwl-20261110T120000Z-abcdef01"
        newer = {
            "type": RELEASE_TYPE,
            "phase": "research",
            "session_date": "2026-11-10",
            "launch_id": newer_launch,
            "review_id": "review-010",
            "packet_sha256": "b" * 64,
            "overnight_run_id": "overnight-20261110",
        }
        decision = ordering_decision(candidate, known=[(f"research_receipt:{newer_launch}", newer)])
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["reason"], SUPERSEDED)

        receipt_root = self._tmp / "newer-research"
        self._write_launch(receipt_root, newer_launch, session="2026-11-10", research=newer)
        decision = guard_publication(candidate, root=receipt_root)
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["reason"], SUPERSEDED)

        final_root = self._tmp / "newer-final"
        final_id = "mwl-20261110T150000Z-abcdef02"
        self._write_launch(final_root, final_id, session="2026-11-10", finalize=True)
        decision = guard_publication(candidate, root=final_root)
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["reason"], SUPERSEDED)

        before = (self.site / "release.json").read_bytes()

        def opener(url: str) -> dict:
            self.assertIn("release.json", url)
            public = dict(candidate)
            public["session_date"] = "2026-11-10"
            public["launch_id"] = final_id
            return public

        decision = guard_publication(
            candidate,
            root=self.root,
            public_base_url="https://example.github.io/market-watch/",
            opener=opener,
        )
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["reason"], SUPERSEDED)
        self.assertEqual((self.site / "release.json").read_bytes(), before)

    def test_restamp_is_idempotent_and_deploy_does_not_call_models(self) -> None:
        first = self._stamp_copy(self._tmp / "stamp-a")
        second = self._stamp_copy(self._tmp / "stamp-b")
        for field in IDENTITY_FIELDS:
            self.assertEqual(first.get(field), second.get(field), field)
        decision = ordering_decision(second, known=[("replay", first)])
        self.assertTrue(decision["allowed"])
        self.assertIsNone(decision["blocking"])
        replay = guard_publication(second, root=self.root)
        self.assertTrue(replay["allowed"])
        self.assertEqual(replay["reason"], "monotonic")

        blocks = step_blocks(DEPLOY)
        blob = "\n".join(blocks.values())
        for name in RUN_BLOCK_FORBIDDEN:
            self.assertNotIn(name, blob, name)

    def test_optional_legacy_patch_failure_lands_in_issues(self) -> None:
        site = self._copy_site("optional-patch")
        html_path = site / "index.html"
        html_path.write_text("<html><body>corrupt</body></html>", encoding="utf-8")
        diagnostics = self._tmp / "optional-diagnostics.jsonl"
        if diagnostics.exists():
            diagnostics.unlink()
        env = {**os.environ, "PYTHONPATH": str(REPO), "MW_RENDER_DIAGNOSTICS": str(diagnostics)}
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.market_watch_launch.render_steps",
                "run",
                "--html",
                str(html_path),
                "--label",
                "Sep 14 completeness refresh",
                "--optional",
                "--fallback",
                "legacy_patch_skipped",
                "--category",
                "render",
                "--component",
                "legacy_patch",
                "--phase",
                "final",
                "--",
                sys.executable,
                "scripts/apply_v11_refresh.py",
                str(html_path),
            ],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn("'ok': False", proc.stdout)
        self.assertIn("legacy_patch_skipped", proc.stdout)
        publish = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.market_watch_launch.publication_issues",
                "publish",
                "--site-dir",
                str(site),
                "--root",
                str(self.root),
                "--diagnostics",
                str(diagnostics),
            ],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(publish.returncode, 0, publish.stderr[-2000:])
        feed = json.loads((site / "issues.json").read_text(encoding="utf-8"))
        self.assertEqual(feed.get("status"), "available")
        codes = [row.get("code") for row in feed.get("issues") or []]
        self.assertIn("render_step_fallback:Sep 14 completeness refresh", codes)

    def _copy_site(self, name: str) -> Path:
        dest = self._tmp / name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(self.site, dest)
        return dest

    def _stamp_copy(self, dest: Path) -> dict:
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(self.pre_stamp, dest)
        env = dict(self.env)
        env["MW_RENDER_DIAGNOSTICS"] = str(self._tmp / f"{dest.name}-diagnostics.jsonl")
        direct = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.market_watch_launch.publication_release",
                "stamp-final",
                "--site-dir",
                str(dest),
                "--root",
                str(self.root),
            ],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(direct.returncode, 0, direct.stderr[-2000:])
        return _release(dest)

    def _write_launch(
        self,
        root: Path,
        launch_id: str,
        *,
        session: str,
        research: dict | None = None,
        finalize: bool = False,
    ) -> None:
        launch_dir = root / "data" / "market_watch_launches" / launch_id
        launch_dir.mkdir(parents=True, exist_ok=True)
        run_id = "overnight-" + session.replace("-", "")
        launch = {
            "launch_id": launch_id,
            "session_date": session,
            "review_id": "review-new",
            "base_packet_sha256": "b" * 64,
            "overnight_run_id": run_id,
            "request": {"provider": "acp"},
            "stages": {
                "04_freeze": {
                    "status": "succeeded",
                    "details": {
                        "review_id": "review-new",
                        "packet_sha256": "b" * 64,
                        "overnight_run_id": run_id,
                    },
                },
                "07_finalize": {"status": "succeeded" if finalize else "pending"},
            },
        }
        (launch_dir / "launch.json").write_text(json.dumps(launch), encoding="utf-8")
        if research is not None:
            (launch_dir / "research_pages.json").write_text(
                json.dumps({"release": research}),
                encoding="utf-8",
            )


if __name__ == "__main__":
    unittest.main()
