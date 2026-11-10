#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from copy import deepcopy
from pathlib import Path

from scripts.apply_overnight_news_refresh import (
    _load_dataset,
    apply_overnight_news_refresh,
    explain_display_slots,
)
from scripts.overnight.accepted_news import (
    effective_public_news_context,
    load_accepted_public_news,
)
from scripts.overnight.errors import PublicationError
from scripts.overnight.news_commentary_state import (
    LEGACY_NO_AGENT_RESEARCH,
    MODE,
    SUPPLEMENT_WITHOUT_STORIES,
    WARNING,
    assert_built_news_matches_context,
    assert_news_html,
    commentary_missing_digest,
    classify_news_commentary,
)
from scripts.overnight.publish import publication_gate
from scripts.overnight.store import OvernightStore, sha256_file
from scripts.sync_news_summary import sync_news_summary

try:
    from tests.test_mw_research_parity import step_blocks
except ImportError:  # pragma: no cover
    step_blocks = None  # type: ignore

REPO = Path(__file__).resolve().parents[1]
NOV9_DATASET = REPO / "data/overnight/runs/overnight-20261109/assembled_dataset.json"
ACCEPTED_ARTIFACT = REPO / "data/overnight/accepted_public_news.json"
NOV6_HEADLINE = "Williams Says Fed Should Gather Information to Judge Price Risks"
NOV9_DIGEST = "52a54aa33a9928216e266d6ef6dc3dcd1c3c116e288eb478cd69bb6389587410"

BASE_HTML = """
<div class="news-alert market-alert">
  <div class="flag">MARKET NEWS · 7-DAY WINDOW</div>
  <div><h3>Old Sep 8 headline</h3><p>Old Sep 8 summary.</p><span class="alert-sub">Research layer: 19 old items.</span></div>
  <label for="p-news">Open News &amp; Research</label>
</div>
<div class="market-news-head">
  <div class="panel">
    <div class="stitle">Market News · 7-day window</div>
    <div class="news-window"><b>Last scanned:</b> 8 Sep 2026 · Sources include Reuters, ABC, AP, FT and verified public X feeds.</div>
  </div>
  <div class="panel"><div class="stitle">Current tape</div><div class="news-count">19</div><p>curated market-relevant stories in the 2–8 September window, ranked by expected rates/FX significance rather than headline volume.</p></div>
</div>
<div class="last24"><div>OLD LAST24</div></div>
<div class="stitle">Top Market Drivers</div><div>OLD ROLLUP</div>
<div class="x-signal"><div>X</div></div>
"""


def _nov9_dataset() -> dict:
    return json.loads(NOV9_DATASET.read_text(encoding="utf-8"))


def _dataset() -> dict:
    from tests.test_overnight_news_refresh import _dataset as dated_fixture

    return dated_fixture()


class NewsCommentaryMissingTests(unittest.TestCase):
    def _legacy_null_dataset(self, *, omit_key: bool = False) -> dict:
        base = {
            "type": "OVERNIGHT_MORNING_DATASET",
            "overnight_run_id": "overnight-legacy-null",
            "as_of": "2026-09-18T12:00:00-04:00",
            "agent_research_cutoff": "2026-09-18T11:00:00-04:00",
        }
        if not omit_key:
            base["agent_research"] = None
        return base

    def test_legacy_null_agent_research_classifies_and_falls_back_to_artifact(self) -> None:
        artifact = load_accepted_public_news(REPO)
        self.assertIsNotNone(artifact)
        store = OvernightStore(root=REPO)
        for omit in (False, True):
            with self.subTest(omit_key=omit):
                dataset = self._legacy_null_dataset(omit_key=omit)
                self.assertEqual(classify_news_commentary(dataset), LEGACY_NO_AGENT_RESEARCH)
                ctx = effective_public_news_context(store, dataset)
                self.assertIsNotNone(ctx)
                self.assertNotIn("mode", ctx or {})
                self.assertEqual(ctx.get("source"), "accepted-public-news-artifact")
                self.assertEqual(ctx.get("as_of"), artifact.get("as_of"))
                self.assertNotEqual(ctx.get("as_of"), dataset["as_of"])

    def test_present_empty_dict_still_raises(self) -> None:
        dataset = {
            "type": "OVERNIGHT_MORNING_DATASET",
            "overnight_run_id": "overnight-empty-dict",
            "agent_research_cutoff": "2026-11-09T05:37:50-05:00",
            "agent_research": {},
        }
        with self.assertRaises(ValueError):
            classify_news_commentary(dataset)
        store = OvernightStore(root=REPO)
        with self.assertRaises(PublicationError):
            effective_public_news_context(store, dataset)

    def test_non_dict_agent_research_raises(self) -> None:
        dataset = self._legacy_null_dataset()
        dataset["agent_research"] = []
        with self.assertRaises(ValueError):
            classify_news_commentary(dataset)

    def test_supplement_without_stories_falls_back_to_artifact(self) -> None:
        artifact = load_accepted_public_news(REPO)
        self.assertIsNotNone(artifact)
        dataset = {
            "type": "OVERNIGHT_MORNING_DATASET",
            "overnight_run_id": "overnight-sources-only",
            "as_of": "2026-09-18T12:00:00-04:00",
            "agent_research_cutoff": "2026-09-18T11:00:00-04:00",
            "agent_research": {
                "news": [],
                "central_bank_research": [],
                "sources": [{"id": "src"}],
            },
        }
        self.assertEqual(classify_news_commentary(dataset), SUPPLEMENT_WITHOUT_STORIES)
        store = OvernightStore(root=REPO)
        ctx = effective_public_news_context(store, dataset)
        self.assertIsNotNone(ctx)
        self.assertNotIn("mode", ctx or {})
        self.assertNotIn("digest", ctx or {})
        self.assertEqual(ctx.get("source"), "accepted-public-news-artifact")
        self.assertEqual(ctx.get("as_of"), artifact.get("as_of"))
        self.assertNotEqual(ctx.get("as_of"), dataset["agent_research_cutoff"])
        html = BASE_HTML
        with self.assertRaises(ValueError):
            apply_overnight_news_refresh(html, dataset)
        self.assertNotIn(MODE, html)
        self.assertNotIn(WARNING, html)

    def test_legacy_null_apply_refresh_raises_without_missing_marker(self) -> None:
        dataset = self._legacy_null_dataset()
        html = BASE_HTML
        with self.assertRaises(ValueError) as caught:
            apply_overnight_news_refresh(html, dataset)
        self.assertIn("no renderable items", str(caught.exception))
        self.assertNotIn(WARNING, html)
        self.assertNotIn(MODE, html)

    def test_nov9_apply_refresh(self) -> None:
        dataset = _nov9_dataset()
        out = apply_overnight_news_refresh(BASE_HTML, dataset)
        self.assertEqual(out.count(WARNING), 1)
        self.assertIn("<b>General desk read:</b>", out)
        self.assertIn("Markets are trading stress", out)
        self.assertEqual(out.count('class="driver-card"'), 0)
        self.assertEqual(out.count('<details class="story"'), 0)
        self.assertEqual(out.count('class="last24-item"'), 0)
        self.assertNotIn("Last refreshed", out)
        self.assertNotIn("7-Day Quick Digest", out)
        self.assertNotIn("Top Market Drivers", out)
        self.assertNotIn(NOV6_HEADLINE, out)
        self.assertIn(f'data-news-commentary-digest="{NOV9_DIGEST}"', out)
        self.assertIn('data-news-commentary-run="overnight-20261109"', out)
        self.assertEqual(commentary_missing_digest(dataset), NOV9_DIGEST)

    def test_sync_and_idempotent(self) -> None:
        dataset = _nov9_dataset()
        html = sync_news_summary(apply_overnight_news_refresh(BASE_HTML, dataset))
        self.assertEqual(html.count(WARNING), 1)
        self.assertNotIn("8 Sep 2026", html)
        self.assertNotIn('<div class="news-count">19</div>', html)
        self.assertIn("MARKET NEWS · WRITE-UP UNAVAILABLE", html)
        self.assertIn(
            '<div class="news-window"><b>News commentary:</b> unavailable for this run.</div>',
            html,
        )
        self.assertNotIn("<b>Last scanned:</b>", html)
        self.assertNotIn("Sources include Reuters", html)
        self.assertIn('<div class="news-count">none</div>', html)
        html2 = sync_news_summary(html)
        self.assertEqual(html2, html)

    def test_publication_gate_nov9(self) -> None:
        dataset = _nov9_dataset()
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / "_site"
            site.mkdir()
            html = sync_news_summary(apply_overnight_news_refresh(BASE_HTML, dataset))
            (site / "index.html").write_text(html, encoding="utf-8")
            store = OvernightStore(root=REPO)
            gate = publication_gate(
                store,
                run_id="overnight-20261109",
                require_dataset=True,
                site_dir=site,
            )
            self.assertTrue(gate.get("may_publish"))
            self.assertNotIn(NOV6_HEADLINE, html)

    def test_artifact_unchanged(self) -> None:
        before = sha256_file(ACCEPTED_ARTIFACT)
        store = OvernightStore(root=REPO)
        ctx = effective_public_news_context(store, _nov9_dataset())
        self.assertEqual(ctx.get("mode"), MODE)
        self.assertEqual(ctx.get("source"), "assembled-dataset")
        self.assertEqual(ctx.get("news"), [])
        self.assertEqual(sha256_file(ACCEPTED_ARTIFACT), before)

    def test_dated_news_still_renders(self) -> None:
        out = apply_overnight_news_refresh(BASE_HTML, _dataset())
        self.assertIn("Oil rebounds in early trade", out)
        self.assertGreaterEqual(out.count('class="driver-card"'), 1)

    def test_undated_only_fixture(self) -> None:
        dataset = {
            "type": "OVERNIGHT_MORNING_DATASET",
            "overnight_run_id": "overnight-test-undated",
            "agent_research_cutoff": "2026-10-05T06:08:00-04:00",
            "agent_research": {
                "summary": "Undated supplement only.",
                "news": [],
                "central_bank_research": [
                    {
                        "headline": "Undated macro note",
                        "summary": "Summary without timestamp.",
                        "source_name": "Desk",
                    }
                ],
                "sources": [],
            },
        }
        out = apply_overnight_news_refresh(BASE_HTML, dataset)
        self.assertIn("Accepted Overnight Research · Age Unverified", out)
        self.assertIn('data-news-provenance="undated"', out)

    def test_legitimate_empty_summary_blank(self) -> None:
        dataset = {
            "type": "OVERNIGHT_MORNING_DATASET",
            "overnight_run_id": "overnight-empty-summary",
            "agent_research_cutoff": "2026-11-09T05:37:50-05:00",
            "agent_research": {
                "summary": "",
                "news": [],
                "central_bank_research": [],
                "sources": [],
            },
        }
        out = apply_overnight_news_refresh(BASE_HTML, dataset)
        self.assertIn(WARNING, out)
        self.assertNotIn("General desk read", out)

    def test_missing_sources_raises_on_apply(self) -> None:
        dataset = _dataset()
        dataset["agent_research"] = {"news": [], "central_bank_research": [], "summary": ""}
        with self.assertRaises(ValueError):
            apply_overnight_news_refresh(BASE_HTML, dataset)

    def test_corrupt_structures_raise(self) -> None:
        base = {
            "type": "OVERNIGHT_MORNING_DATASET",
            "overnight_run_id": "overnight-bad",
            "agent_research_cutoff": "2026-11-09T05:37:50-05:00",
            "agent_research": {
                "summary": "",
                "news": [],
                "central_bank_research": [],
                "sources": [],
            },
        }
        wrong_type = deepcopy(base)
        wrong_type["type"] = "OTHER"
        with self.assertRaises(ValueError):
            classify_news_commentary(wrong_type)
        missing_news = deepcopy(base)
        missing_news["agent_research"].pop("news")
        with self.assertRaises(ValueError):
            apply_overnight_news_refresh(BASE_HTML, missing_news)
        bad_news = deepcopy(base)
        bad_news["agent_research"]["news"] = "nope"
        with self.assertRaises(ValueError):
            classify_news_commentary(bad_news)
        missing_sources = deepcopy(base)
        missing_sources["agent_research"].pop("sources")
        with self.assertRaises(ValueError):
            apply_overnight_news_refresh(BASE_HTML, missing_sources)

    def test_missing_dataset_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "overnight").mkdir(parents=True)
            (root / "data" / "overnight" / "latest.json").write_text(
                json.dumps({"assembled_dataset": "data/overnight/runs/missing/assembled_dataset.json"}),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                _load_dataset(root)

    def test_invalid_date_item_not_missing_mode(self) -> None:
        dataset = {
            "type": "OVERNIGHT_MORNING_DATASET",
            "overnight_run_id": "overnight-invalid",
            "agent_research_cutoff": "2026-11-09T05:37:50-05:00",
            "agent_research": {
                "summary": "",
                "news": [
                    {
                        "headline": "Bad date story",
                        "summary": "Still has body text.",
                        "published_at": "not-a-date",
                    }
                ],
                "central_bank_research": [],
                "sources": [],
            },
        }
        planted = BASE_HTML.replace(
            "OLD LAST24",
            (
                'data-publication-state="current-cycle-news-commentary-missing" '
                f'data-news-commentary-digest="{NOV9_DIGEST}" '
                'data-news-commentary-run="overnight-20261109"'
            ),
        )
        with self.assertRaises(ValueError):
            apply_overnight_news_refresh(planted, dataset)

    def test_explain_display_slots_row(self) -> None:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        rows = explain_display_slots(
            _nov9_dataset(),
            cutoff=datetime.fromisoformat("2026-11-09T05:37:50.499948-05:00").astimezone(ZoneInfo("America/New_York")),
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], MODE)

    def test_assert_helper_rejects_bad_digest(self) -> None:
        dataset = _nov9_dataset()
        html = apply_overnight_news_refresh(BASE_HTML, dataset)
        ctx = effective_public_news_context(OvernightStore(root=REPO), dataset)
        bad = html.replace(NOV9_DIGEST, "0" * 64)
        with self.assertRaises(PublicationError):
            assert_news_html(bad, ctx, require_front_alert=False)

    def test_workflow_scripts_use_shared_helper(self) -> None:
        if step_blocks is None:
            self.skipTest("step_blocks helper unavailable")
        deploy = (REPO / ".github/workflows/deploy-pages.yml").read_text(encoding="utf-8")
        blocks = step_blocks(deploy)
        news_step = blocks["Apply accepted overnight news refresh"]
        trader_step = blocks["Add Trader Book tab"]
        integrity = blocks["Check final publication integrity"]
        self.assertIn("render_steps", news_step)
        self.assertIn("news_unavailable", news_step)
        self.assertIn("publish-check", trader_step)
        self.assertIn("--news-html-policy soft", trader_step)
        self.assertIn("publication_checks final", integrity)
        self.assertNotIn('raise SystemExit("accepted public news headlines missing from built HTML")', news_step)
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            site = work / "_site"
            site.mkdir()
            html = sync_news_summary(apply_overnight_news_refresh(BASE_HTML, _nov9_dataset()))
            (site / "index.html").write_text(html, encoding="utf-8")
            script = textwrap.dedent(
                """
                import sys
                from pathlib import Path
                sys.path.insert(0, {root!r})
                from scripts.overnight.accepted_news import effective_public_news_context
                from scripts.overnight.news_commentary_state import assert_built_news_matches_context
                from scripts.overnight.store import OvernightStore
                html = Path({site!r}).read_text(encoding="utf-8")
                store = OvernightStore(root=Path({root!r}))
                dataset = store.read_artifact("overnight-20261109", "assembled_dataset.json")
                context = effective_public_news_context(store, dataset)
                assert_built_news_matches_context(html, context, require_front_alert=True)
                """
            ).format(root=str(REPO), site=str(site / "index.html"))
            proc = subprocess.run(
                [sys.executable, "-c", script],
                cwd=work,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
