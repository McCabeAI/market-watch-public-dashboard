"""Render fallbacks and resilient static-base patching."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.apply_country_detail import apply_country_detail
from scripts.country_detail import render as country_detail_render
from scripts.apply_six_economy_dashboard import apply_six_economy_dashboard
from scripts.apply_temperature_scores import apply_scores, load_state
from scripts.market_watch_launch import publication_checks as pc
from scripts.market_watch_launch import research_static_base as static_base
from scripts.market_watch_launch.publication_issues import load_diagnostics
from scripts.market_watch_launch.render_fallbacks import (
    FallbackUnavailable,
    apply_fallback,
    country_detail_unavailable,
    news_unavailable,
    scores_unavailable,
)

REPO = Path(__file__).resolve().parents[1]


def _build_pre_scores_html() -> str:
    v6 = static_base.rebuild_v6_base(REPO)
    html = static_base.apply_news_rollup(REPO, static_base.apply_last24(REPO, v6))
    return apply_six_economy_dashboard(html)


def _build_pre_scores_with_temp_inputs() -> str:
    return static_base.apply_temperature_inputs(REPO, _build_pre_scores_html())


class RenderFallbackTests(unittest.TestCase):
    def test_news_unavailable_passes_publication_checks_and_is_idempotent(self):
        html = _build_pre_scores_with_temp_inputs()
        once = news_unavailable(html)
        pc.check_no_stale_static_news(once)
        pc.check_news_dates_not_overstated(once, accepted_as_of=None)
        self.assertIn('data-news-state="unavailable"', once)
        self.assertIn("Last 24 Hours · Desk Summary", once)
        self.assertIn("Accepted Overnight Research · Age Unverified", once)
        self.assertNotIn("Last refreshed 18 Sep 2026", once)
        twice = news_unavailable(once)
        self.assertEqual(twice, once)

    def test_scores_unavailable_keeps_score_overview_anchor(self):
        html = _build_pre_scores_with_temp_inputs()
        out = scores_unavailable(html)
        self.assertIn('data-score-overview="calibrated"', out)
        self.assertNotIn('<div class="stitle">Temperature Board</div>', out)
        self.assertIn("Live 1–100 Score Board", out)
        self.assertIsNone(re.search(r'<span class="score-num">\s*[0-9]', out))

    def test_country_detail_unavailable_preserves_cdetail_blocks(self):
        html = _build_pre_scores_with_temp_inputs()
        out = country_detail_unavailable(html)
        for key in static_base.COUNTRY_KEYS:
            self.assertIn(f'<div class="cdetail {key}">', out)
            self.assertIn('data-country-detail-state="unavailable"', out)

    def test_downstream_trader_book_survives_news_and_scores_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            index = site / "index.html"
            html = scores_unavailable(news_unavailable(_build_pre_scores_with_temp_inputs()))
            index.write_text(html, encoding="utf-8")
            for script in ("scripts/apply_market_data_tab.py", "scripts/apply_trader_book_tab.py"):
                proc = subprocess.run(
                    [sys.executable, str(REPO / script), str(index)],
                    cwd=REPO,
                    env={**os.environ, "PYTHONPATH": str(REPO)},
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)
            text = index.read_text(encoding="utf-8")
            self.assertIn("Trader Book · paper P&L", text)
            self.assertIn("Accepted Overnight Research · Age Unverified", text)

    def test_apply_fallback_registry(self):
        html = _build_pre_scores_with_temp_inputs()
        self.assertIn('data-news-state="unavailable"', apply_fallback("news_unavailable", html))


class StaticBaseResilienceTests(unittest.TestCase):
    def test_real_inputs_stay_byte_identical_to_strict_chain(self):
        v6 = static_base.rebuild_v6_base(REPO)
        cli_out = tempfile.NamedTemporaryFile(delete=False)
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.market_watch_launch.research_static_base",
                    "base",
                    "--root",
                    str(REPO),
                    "--out",
                    cli_out.name,
                ],
                cwd=REPO,
                env={**os.environ, "PYTHONPATH": str(REPO)},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            base_only = Path(cli_out.name).read_text(encoding="utf-8")
            self.assertEqual(
                base_only,
                static_base.apply_news_rollup(REPO, static_base.apply_last24(REPO, v6)),
            )
        finally:
            Path(cli_out.name).unlink(missing_ok=True)

    def test_v6_sha_tamper_still_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "payload_v6").mkdir()
            (root / "payload_v6" / "part001.b64").write_bytes(b"x")
            with self.assertRaises(static_base.StaticBaseError):
                static_base.rebuild_v6_base(root)

    def test_missing_last24_anchor_skips_with_diagnostic_when_not_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            diag = Path(tmp) / "diag.jsonl"
            v6 = static_base.rebuild_v6_base(REPO)
            broken = v6.replace(static_base.TOP_DRIVERS_ANCHOR, "", 1)
            out = static_base.apply_last24(REPO, broken, diagnostics=diag, strict=False)
            self.assertIn('data-news-state="unavailable"', out)
            rows = load_diagnostics(diag)
            self.assertTrue(any(r.get("component") == "static_base:last24" for r in rows))

class StaticBasePerCountrySkipTests(unittest.TestCase):
    def test_temperature_inputs_per_country_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            diag = Path(tmp) / "diag.jsonl"
            six = apply_six_economy_dashboard(
                static_base.apply_news_rollup(REPO, static_base.apply_last24(REPO, static_base.rebuild_v6_base(REPO))),
            )
            broken = six.replace('<div class="cdetail au">', "", 1)
            out = static_base.apply_temperature_inputs(REPO, broken, diagnostics=diag, strict=False)
            self.assertIn('<div class="cdetail ca">', out)
            self.assertGreater(out.count("temp-dimension"), 20)
            rows = load_diagnostics(diag)
            self.assertTrue(any(r.get("country") == "AU" for r in rows))


class CountryDetailIsolationTests(unittest.TestCase):
    def test_one_country_failure_isolated(self):
        page = _build_pre_scores_with_temp_inputs()
        with tempfile.TemporaryDirectory() as tmp:
            diag = Path(tmp) / "diag.jsonl"
            real = country_detail_render.render_country_detail

            def _render(code, *args, **kwargs):
                if code == "AU":
                    raise RuntimeError("synthetic AU failure")
                return real(code, *args, **kwargs)

            with mock.patch("scripts.apply_country_detail.render_country_detail", side_effect=_render):
                out = apply_country_detail(page, root=REPO, diagnostics=diag)
            self.assertIn('data-country-detail-state="unavailable"', out)
            self.assertIn('data-country="AU"', out)
            self.assertIn('data-country="US"', out)
            rows = load_diagnostics(diag)
            au_rows = [r for r in rows if r.get("country") == "AU"]
            self.assertEqual(len(au_rows), 1)
            self.assertEqual(au_rows[0].get("component"), "country_detail")


if __name__ == "__main__":
    unittest.main()
