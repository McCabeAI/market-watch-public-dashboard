"""End-to-end manual launch on a disposable state root.

The stub provider path proves freeze, trusted acceptance, books, assembly,
and an explicit Pages dry-run. It does not call a trader model and it does
not publish production Pages.
"""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.market_watch_launch.contract import LAUNCH_ID_RE, STAGES
from scripts.market_watch_launch.graph import run_launch
from scripts.overnight.constants import ROOT

NY = ZoneInfo("America/New_York")
WHEN = datetime(2026, 9, 18, 12, 0, tzinfo=NY)

IMMUTABLE = (
    ROOT / "data/overnight/runs/overnight-20260923/reviews/review-001/evidence_snapshot.json",
    ROOT / "data/overnight/books/latest.json",
    ROOT / "data/pm/books/latest.json",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _request(**overrides: object) -> dict:
    payload = {
        "session_date": "2026-09-18",
        "rerun": False,
        "mode": "fixture",
        "provider": "stub",
        "source": "workflow_dispatch",
        "actor_type": "User",
        "actor": "kevin",
        "publish_production": False,
    }
    payload.update(overrides)
    return payload


class ManualLaunchIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._before = {path: _sha(path) for path in IMMUTABLE}

    @classmethod
    def tearDownClass(cls) -> None:
        after = {path: _sha(path) for path in IMMUTABLE}
        if after != cls._before:
            raise AssertionError("Sep 23 accepted evidence or canonical books changed")

    def test_fixture_stub_path_reaches_pages_dry_run_without_production_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            first = run_launch(_request(token="aaaaaaa1"), root=ROOT, state_root=state, when=WHEN)
            self.assertEqual(first["status"], "succeeded", _stage_debug(first))
            self.assertRegex(first["launch_id"], LAUNCH_ID_RE)
            launch = first["launch"]
            stages = launch["stages"]
            self.assertTrue(all(stages[name]["status"] == "succeeded" for name in STAGES))
            gate = stages["03_quality_gate"]["details"]
            self.assertEqual(gate["outcome"], "PASS")
            self.assertEqual(gate["hold_decisions_emitted"], 0)
            self.assertFalse(gate["synthetic_holds"])
            freeze = stages["04_freeze"]["details"]
            self.assertFalse(freeze["legacy_0150_used"])
            self.assertEqual(freeze["evidence_boundary"], "actual_freeze_timestamp")
            self.assertTrue(freeze["review_id"].startswith("review-"))
            self.assertTrue(freeze["packet_sha256"])
            accept = stages["06_acceptance"]["details"]
            self.assertEqual(accept["trader_seats"], 14)
            self.assertEqual(accept["pm_count"], 3)
            self.assertEqual(accept["live_model_calls"], 0)
            books = state / "scratch-overnight" / "2026-09-18" / "data/overnight/books/latest.json"
            self.assertTrue(books.is_file())
            final = stages["07_finalize"]["details"]
            self.assertEqual(final["launch_id"], first["launch_id"])
            self.assertEqual(final["review_id"], freeze["review_id"])
            self.assertTrue(final["publication"]["may_publish"])
            pages = stages["08_pages"]["details"]
            self.assertTrue(pages["dry_run"])
            self.assertFalse(pages["executed"])
            self.assertFalse(pages["production_published"])
            self.assertEqual(pages["plan"]["workflow"], "deploy-pages.yml")
            self.assertEqual(pages["plan"]["event"], "workflow_dispatch")

            again = run_launch(_request(token="bbbbbbb2"), root=ROOT, state_root=state, when=WHEN)
            self.assertTrue(again["returned_existing"])
            self.assertEqual(again["launch_id"], first["launch_id"])

            rerun = run_launch(
                _request(token="ccccccc3", rerun=True),
                root=ROOT,
                state_root=state,
                when=WHEN,
            )
            self.assertEqual(rerun["status"], "succeeded", _stage_debug(rerun))
            self.assertNotEqual(rerun["launch_id"], first["launch_id"])
            self.assertNotEqual(
                rerun["launch"]["stages"]["04_freeze"]["details"]["review_id"],
                freeze["review_id"],
            )

    def test_workflows_have_no_market_watch_cron_or_push_pages_deploy(self) -> None:
        workflow_dir = ROOT / ".github" / "workflows"
        for path in workflow_dir.glob("*.yml"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("\nschedule:", "\n" + text, path.name)
            self.assertNotRegex(text, r"(?m)^[\s]*- cron:")
        pages = (workflow_dir / "deploy-pages.yml").read_text(encoding="utf-8")
        self.assertNotIn("push:", pages.split("jobs:", 1)[0])
        self.assertIn("workflow_dispatch:", pages)
        launch = (workflow_dir / "launch-market-watch.yml").read_text(encoding="utf-8")
        self.assertNotIn("deploy-pages.yml", launch)
        self.assertIn("launch-market-watch", launch)
        self.assertIn("workflow_dispatch:", launch)
        self.assertIn("issues:", launch)


def _stage_debug(result: dict) -> str:
    launch = result.get("launch") or {}
    lines = [f"status={result.get('status')} launch={result.get('launch_id')}"]
    for name, row in (launch.get("stages") or {}).items():
        if row.get("status") != "succeeded":
            lines.append(f"{name} {row.get('status')} {row.get('reason')}")
    return "\n".join(lines)
