"""Playwright contrast checks for Country Detail CSS stack."""

from __future__ import annotations

import os
import re
import shutil
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

try:
    from playwright.sync_api import sync_playwright

    _HAS_PLAYWRIGHT = True
except ImportError:
    _HAS_PLAYWRIGHT = False

_CHROME = os.environ.get("CHROME_PATH", "/usr/local/bin/google-chrome")
_HAS_CHROME = Path(_CHROME).is_file()

from scripts.country_detail.render import (  # noqa: E402
    _preview_fixtures,
    country_detail_css,
    render_country_detail,
)
from scripts.visual_qa.contrast import CONTRAST_AUDIT_SCRIPT  # noqa: E402

_TEMP_SCORES = (ROOT / "patch_v8" / "temp_scores.css").read_text(encoding="utf-8")
_THEME = (ROOT / "scripts" / "dashboard_repair" / "theme.css").read_text(encoding="utf-8")
_COUNTRY_SURFACES_MARKER = "Country Detail surfaces"


def _stacked_css(include_country_surfaces: bool = True) -> str:
    theme = _THEME
    if not include_country_surfaces:
        start = theme.find("/* ---- Country Detail surfaces")
        end = theme.find("@media(prefers-reduced-motion:reduce)")
        if start >= 0 and end > start:
            theme = theme[:start] + theme[end:]
    return "\n".join(
        [
            _TEMP_SCORES,
            country_detail_css(),
            theme,
        ]
    )


def _fixture_html(include_country_surfaces: bool = True) -> str:
    fixtures = _preview_fixtures()
    code, proj, att, scores = fixtures["populated"]
    fragment = render_country_detail(code, proj, att, scores)
    css = _stacked_css(include_country_surfaces)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<style>{css}</style>
</head><body class="mw-qa-shell">
<div class="cdetail ca">{fragment}</div>
</body></html>"""


def _audit_html(html: str) -> dict:
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=_CHROME)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.set_content(html, wait_until="load")
        page.evaluate(
            """() => document.querySelectorAll('.cdetail details').forEach((d) => { d.open = true; })"""
        )
        result = page.evaluate(CONTRAST_AUDIT_SCRIPT, ".cdetail.ca")
        browser.close()
    return result


@unittest.skipUnless(_HAS_PLAYWRIGHT and _HAS_CHROME, "playwright and Chrome required")
class TestVisualContrast(unittest.TestCase):
    def test_country_detail_passes_with_theme_surfaces(self) -> None:
        audit = _audit_html(_fixture_html(include_country_surfaces=True))
        self.assertNotIn("error", audit)
        self.assertEqual(audit.get("failures"), [])
        tiny = [f for f in (audit.get("failures") or []) if f.get("kind", "").startswith("font")]
        self.assertEqual(tiny, [])

    def test_negative_control_without_country_surfaces(self) -> None:
        audit = _audit_html(_fixture_html(include_country_surfaces=False))
        self.assertTrue(audit.get("failures"), "expected contrast failures without theme surfaces")


if __name__ == "__main__":
    unittest.main()
