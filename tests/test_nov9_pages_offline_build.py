# Offline replay of deploy-pages.yml from Rebuild v6 base through Stamp final publication edition.
# Skips large unittest batteries inside workflow steps; runs page-rendering scripts and inline assertions.

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from scripts.overnight.news_commentary_state import MODE, WARNING, commentary_missing_digest
from scripts.overnight.store import sha256_file
from tests.test_mw_research_parity import step_blocks

REPO = Path(__file__).resolve().parents[1]
DEPLOY = (REPO / ".github/workflows/deploy-pages.yml").read_text(encoding="utf-8")
NOV9_DIGEST = "52a54aa33a9928216e266d6ef6dc3dcd1c3c116e288eb478cd69bb6389587410"
NOV6_HEADLINE = "Williams Says Fed Should Gather Information to Judge Price Risks"

CANONICAL_PATHS = [
    REPO / "data/overnight/latest.json",
    REPO / "data/overnight/accepted_public_news.json",
    REPO / "data/overnight/runs/overnight-20261109/assembled_dataset.json",
    REPO / "data/overnight/books/latest.json",
    REPO / "data/market_watch_launches/mwl-20261109T103750Z-a4e987d1/launch.json",
    REPO / "data/pm/books/latest.json",
]

OFFLINE_STEPS = [
    "Rebuild v6 base",
    "Apply last-24-hours patch",
    "Apply rolling news rollup",
    "Extend dashboard to six economies",
    "Restore 1-100 temperature input scores",
    "Add August CPI context to US inflation evidence",
    "Apply Sep 14 completeness refresh",
    "Apply Sep 18 legacy completeness refresh",
    "Apply accepted overnight news refresh",
    "Sync news summary metadata",
    "Apply live temperature scores",
    "Generate market-state JSON for Pages",
    "Apply Country Detail",
    "Add Market Data tab",
    "Add Trader Book tab",
    "Add Trader Room tab",
    "Add Portfolio Manager public JSON",
    "Apply dashboard repair",
    "Stamp final publication edition",
]

CONTINUE_ON_ERROR = {
    "Generate market-state JSON for Pages",
}


def _sanitize_step(script: str) -> str:
    kept: list[str] = []
    skip = False
    for line in script.splitlines():
        if "python -m unittest" in line or "python3 -m unittest" in line:
            continue
        if line.strip().startswith("uses:"):
            skip = True
            continue
        if skip and line.strip() and not line.startswith(" "):
            skip = False
        if "actions/cache" in line or "actions/upload" in line or "actions/configure" in line:
            continue
        if "pip install" in line and "requirements-market-state" in line:
            kept.append(line)
            continue
        kept.append(line)
    return textwrap.dedent("\n".join(kept)).strip() + "\n"


class Nov9PagesOfflineBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = Path(tempfile.mkdtemp(prefix="mw-nov9-offline-"))
        ignore = shutil.ignore_patterns(".git", "__pycache__", "_site", ".mw-cache-restore")
        shutil.copytree(REPO, cls._tmp, ignore=ignore, dirs_exist_ok=True)
        cls._hashes_before = {str(p.relative_to(REPO)): sha256_file(p) for p in CANONICAL_PATHS if p.is_file()}
        cls._blocks = step_blocks(DEPLOY)
        cls._env = {
            **os.environ,
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "MW_LAUNCH_ID": "mwl-20261109T103750Z-a4e987d1",
            "MW_REVIEW_ID": "review-001",
            "MW_PACKET_SHA256": "36b651b69a9e2951d8f7c97819999a9354668967f97c455af200a46c3662fb11",
            "PYTHONPATH": ".",
        }
        cls._failures: list[str] = []

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def _run_step(self, name: str) -> None:
        script = _sanitize_step(self._blocks[name])
        script = script.replace("python ", "python3 ")
        proc = subprocess.run(
            ["bash", "-c", f"set -euo pipefail\ncd {self._tmp!s}\n{script}"],
            env=self._env,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            if name in CONTINUE_ON_ERROR:
                self._failures.append(f"{name}: {proc.stderr[-500:]}")
                return
            self.fail(f"step {name} failed:\n{proc.stdout}\n{proc.stderr}")

    def test_offline_pages_build_nov9(self) -> None:
        for step in OFFLINE_STEPS:
            with self.subTest(step=step):
                if step not in self._blocks:
                    self.fail(f"missing workflow step block: {step}")
                self._run_step(step)

        for rel, digest in self._hashes_before.items():
            path = REPO / rel
            if path.is_file():
                self.assertEqual(sha256_file(path), digest, rel)

        html = (self._tmp / "_site/index.html").read_text(encoding="utf-8")
        self.assertEqual(html.count(WARNING), 1)
        self.assertNotIn(NOV6_HEADLINE, html)
        self.assertNotIn("7-Day Quick Digest", html)
        self.assertNotIn("Top Market Drivers", html)
        self.assertNotIn("<b>Last scanned:</b>", html)
        self.assertNotIn("Sources include Reuters", html)
        self.assertIn("Last 24 Hours · Desk Summary", html)
        self.assertIn("General desk read", html)
        self.assertEqual(html.count('class="driver-card"'), 0)
        self.assertIn(f'data-news-commentary-digest="{NOV9_DIGEST}"', html)
        self.assertIn('data-publication-phase="final"', html)

        release = json.loads((self._tmp / "_site/release.json").read_text(encoding="utf-8"))
        self.assertEqual(release.get("phase"), "final")
        self.assertEqual(release.get("launch_id"), self._env["MW_LAUNCH_ID"])
        self.assertEqual(release.get("review_id"), self._env["MW_REVIEW_ID"])
        self.assertEqual(release.get("packet_sha256"), self._env["MW_PACKET_SHA256"])
        self.assertEqual(release.get("overnight_run_id"), "overnight-20261109")

        books = json.loads((self._tmp / "_site/trader-books.json").read_text(encoding="utf-8"))
        self.assertEqual(len(books.get("seats") or {}), 15)
        self.assertEqual(books.get("overnight_run_id") or books.get("books_run_id"), "overnight-20261109")

        dataset = json.loads(
            (REPO / "data/overnight/runs/overnight-20261109/assembled_dataset.json").read_text()
        )
        self.assertEqual(commentary_missing_digest(dataset), NOV9_DIGEST)


if __name__ == "__main__":
    unittest.main()
