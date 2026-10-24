"""Playwright contrast checks for Country Detail CSS stack."""

from __future__ import annotations

import base64
import gzip
import os
import re
import tempfile
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

from scripts.country_detail.attention import evaluate_projection  # noqa: E402
from scripts.country_detail.projection import build_projection  # noqa: E402
from scripts.country_detail.render import country_detail_css, render_country_detail  # noqa: E402
from scripts.country_registry import load_country_registry, stale_after_days  # noqa: E402
from scripts.temperature_level import load_state  # noqa: E402
from scripts.visual_qa.contrast import CONTRAST_AUDIT_SCRIPT  # noqa: E402

_TEMP_SCORES = (ROOT / "patch_v8" / "temp_scores.css").read_text(encoding="utf-8")
_THEME = (ROOT / "scripts" / "dashboard_repair" / "theme.css").read_text(encoding="utf-8")
_V6_PARTS = tuple(sorted((ROOT / "payload_v6").glob("part*.b64")))
_V6_CACHE = Path(tempfile.gettempdir()) / "mw_v6_base_styles.css"


def _v6_base_css() -> str:
    newest_part = max(p.stat().st_mtime for p in _V6_PARTS) if _V6_PARTS else 0
    if _V6_CACHE.is_file() and _V6_CACHE.stat().st_mtime >= newest_part:
        return _V6_CACHE.read_text(encoding="utf-8")
    raw = b"".join(base64.b64decode(part.read_bytes()) for part in _V6_PARTS)
    html = gzip.decompress(raw).decode("utf-8")
    blocks = [m.group(1) for m in re.finditer(r"<style[^>]*>(.*?)</style>", html, re.I | re.S)]
    css = "\n".join(blocks)
    _V6_CACHE.write_text(css, encoding="utf-8")
    return css


def _stacked_css(include_country_surfaces: bool = True) -> str:
    theme = _THEME
    if not include_country_surfaces:
        start = theme.find("/* ---- Country Detail surfaces")
        end = theme.find("@media(prefers-reduced-motion:reduce)")
        if start >= 0 and end > start:
            theme = theme[:start] + theme[end:]
    return "\n".join(
        [
            _v6_base_css(),
            _TEMP_SCORES,
            country_detail_css(),
            theme,
            ".cdetail.ca{display:block}",
        ]
    )


def _ca_country_detail_html() -> str:
    projection = build_projection(ROOT)
    registry = load_country_registry(ROOT / "data" / "country_registry.json")
    attention = evaluate_projection(
        projection,
        stale_after_days=stale_after_days(registry),
    )
    scores = load_state(ROOT / "data" / "temperature_scores.json")
    return render_country_detail(
        "CA",
        projection["countries"]["CA"],
        attention["countries"]["CA"],
        scores,
    )


def _fixture_html(include_country_surfaces: bool = True) -> str:
    fragment = _ca_country_detail_html()
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
            """() => {
            document.querySelectorAll('.cdetail details').forEach((d) => { d.open = true; });
        }"""
        )
        result = page.evaluate(CONTRAST_AUDIT_SCRIPT, ".cdetail.ca")
        browser.close()
    return result


@unittest.skipUnless(_HAS_PLAYWRIGHT and _HAS_CHROME, "playwright and Chrome required")
class TestVisualContrast(unittest.TestCase):
    def test_country_detail_passes_with_theme_surfaces(self) -> None:
        audit = _audit_html(_fixture_html(include_country_surfaces=True))
        self.assertNotIn("error", audit)
        self.assertGreater(audit.get("checked", 0), 100)
        self.assertEqual(audit.get("failures"), [])
        self.assertEqual(audit.get("primaFailures"), [])

    def test_negative_control_without_country_surfaces(self) -> None:
        audit = _audit_html(_fixture_html(include_country_surfaces=False))
        self.assertTrue(audit.get("failures"), "expected contrast failures without theme surfaces")


if __name__ == "__main__":
    unittest.main()
