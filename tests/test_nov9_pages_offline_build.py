# Offline replay of deploy-pages.yml from the static base through the issues feed.
# The Nov 9 accepted dataset is pinned to the finalize commit so later overnight
# drift cannot change the inputs. Current scripts, patches, the v6 payload and
# workflows are overlaid on that tree.

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from scripts.market_watch_launch.publication_release import site_digest
from scripts.overnight.news_commentary_state import WARNING, commentary_missing_digest
from scripts.overnight.store import sha256_file
from tests.test_mw_research_parity import step_blocks

REPO = Path(__file__).resolve().parents[1]
DEPLOY = (REPO / ".github/workflows/deploy-pages.yml").read_text(encoding="utf-8")

# Finalize commit for mwl-20261109T103750Z-a4e987d1. latest.json is
# overnight-20261109 and Stage 07 succeeded with the accepted packet.
FIXTURE_COMMIT = "1b84c08833dc0ae88c4c9da14e16e0484acf18c1"
NOV9_LAUNCH = "mwl-20261109T103750Z-a4e987d1"
NOV9_REVIEW = "review-001"
NOV9_PACKET = "36b651b69a9e2951d8f7c97819999a9354668967f97c455af200a46c3662fb11"
NOV9_RUN = "overnight-20261109"
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
    "Rebuild static base",
    "Extend dashboard to six economies",
    "Restore 1-100 temperature input scores",
    "Add August CPI context to US inflation evidence",
    "Apply Sep 14 completeness refresh",
    "Apply Sep 18 legacy completeness refresh",
    "Apply accepted overnight news refresh",
    "Apply live temperature scores",
    "Generate market-state JSON for Pages",
    "Apply Country Detail",
    "Add Market Data tab",
    "Add Trader Book tab",
    "Add Trader Room tab",
    "Add Portfolio Manager public JSON",
    "Apply dashboard repair",
    "Stamp final publication edition",
    "Check final publication integrity",
    "Publish issues feed",
]

POST_STAMP_STEPS = [
    "Stamp final publication edition",
    "Check final publication integrity",
    "Publish issues feed",
]
PRE_STAMP_STEPS = [name for name in OFFLINE_STEPS if name not in POST_STAMP_STEPS]

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


def materialize_nov9_fixture(dest: Path) -> None:
    """Shared clone of the Nov 9 finalize commit, with the current build code overlaid."""
    subprocess.run(
        ["git", "clone", "--shared", "--no-checkout", str(REPO), str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "checkout", "--detach", FIXTURE_COMMIT],
        cwd=dest,
        check=True,
        capture_output=True,
        text=True,
    )
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=dest, text=True).strip()
    if head != FIXTURE_COMMIT:
        raise AssertionError(f"fixture HEAD {head} is not {FIXTURE_COMMIT}")
    latest = json.loads((dest / "data/overnight/latest.json").read_text(encoding="utf-8"))
    if latest.get("overnight_run_id") != NOV9_RUN:
        raise AssertionError(f"fixture latest.json is {latest.get('overnight_run_id')}")
    launch = json.loads(
        (dest / "data/market_watch_launches" / NOV9_LAUNCH / "launch.json").read_text(encoding="utf-8")
    )
    freeze = (launch.get("stages") or {}).get("04_freeze", {}).get("details") or {}
    finalize = (launch.get("stages") or {}).get("07_finalize") or {}
    if finalize.get("status") != "succeeded":
        raise AssertionError("fixture Stage 07 did not succeed")
    if freeze.get("review_id") != NOV9_REVIEW or freeze.get("packet_sha256") != NOV9_PACKET:
        raise AssertionError("fixture freeze identity does not match the Nov 9 packet")
    if freeze.get("overnight_run_id") != NOV9_RUN:
        raise AssertionError("fixture freeze run is not overnight-20261109")
    overlay = ["scripts", "payload_v6", ".github/workflows"]
    overlay += sorted(path.name for path in REPO.iterdir() if path.is_dir() and path.name.startswith("patch_"))
    for rel in overlay:
        target = dest / rel
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(REPO / rel, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def offline_env(diagnostics: Path) -> dict[str, str]:
    return {
        **os.environ,
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_SHA": FIXTURE_COMMIT,
        "MW_LAUNCH_ID": NOV9_LAUNCH,
        "MW_REVIEW_ID": NOV9_REVIEW,
        "MW_PACKET_SHA256": NOV9_PACKET,
        "PYTHONPATH": ".",
        "MW_RENDER_DIAGNOSTICS": str(diagnostics),
    }


def run_offline_steps(root: Path, env: dict[str, str], steps: list[str] | None = None) -> list[str]:
    """Run workflow ``run:`` blocks. Returns continue-on-error failures."""
    blocks = step_blocks(DEPLOY)
    continued: list[str] = []
    for name in steps if steps is not None else OFFLINE_STEPS:
        script = blocks.get(name)
        if script is None:
            raise AssertionError(f"missing workflow step block: {name}")
        script = _sanitize_step(script).replace("python ", "python3 ")
        proc = subprocess.run(
            ["bash", "-c", f"set -euo pipefail\ncd {shlex.quote(str(root))}\n{script}"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "")[-2000:]
            if name in CONTINUE_ON_ERROR:
                continued.append(f"{name}: {detail}")
                continue
            raise AssertionError(f"step {name} failed:\n{proc.stdout}\n{proc.stderr}")
    return continued


class Nov9PagesOfflineBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = Path(tempfile.mkdtemp(prefix="mw-nov9-offline-"))
        cls.root = cls._tmp / "fixture"
        materialize_nov9_fixture(cls.root)
        cls.diagnostics = cls._tmp / "render-diagnostics.jsonl"
        cls.env = offline_env(cls.diagnostics)
        cls._hashes_before = {str(p.relative_to(REPO)): sha256_file(p) for p in CANONICAL_PATHS if p.is_file()}

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def test_offline_pages_build_nov9(self) -> None:
        run_offline_steps(self.root, self.env)

        for rel, digest in self._hashes_before.items():
            path = REPO / rel
            if path.is_file():
                self.assertEqual(sha256_file(path), digest, rel)

        latest = json.loads((self.root / "data/overnight/latest.json").read_text(encoding="utf-8"))
        self.assertEqual(latest.get("overnight_run_id"), NOV9_RUN)

        html = (self.root / "_site/index.html").read_text(encoding="utf-8")
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

        release = json.loads((self.root / "_site/release.json").read_text(encoding="utf-8"))
        self.assertEqual(release.get("phase"), "final")
        self.assertEqual(release.get("launch_id"), NOV9_LAUNCH)
        self.assertEqual(release.get("review_id"), NOV9_REVIEW)
        self.assertEqual(release.get("packet_sha256"), NOV9_PACKET)
        self.assertEqual(release.get("overnight_run_id"), NOV9_RUN)
        self.assertEqual(release.get("site_sha256"), site_digest(self.root / "_site"))

        issues = json.loads((self.root / "_site/issues.json").read_text(encoding="utf-8"))
        self.assertEqual(issues.get("status"), "available")
        self.assertEqual(issues.get("schema_version"), 1)

        books = json.loads((self.root / "_site/trader-books.json").read_text(encoding="utf-8"))
        self.assertEqual(len(books.get("seats") or {}), 15)
        self.assertEqual(books.get("overnight_run_id") or books.get("books_run_id"), NOV9_RUN)

        dataset = json.loads(
            (self.root / "data/overnight/runs" / NOV9_RUN / "assembled_dataset.json").read_text(encoding="utf-8")
        )
        self.assertEqual(commentary_missing_digest(dataset), NOV9_DIGEST)


if __name__ == "__main__":
    unittest.main()
