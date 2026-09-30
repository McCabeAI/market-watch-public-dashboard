"""Inject the shared Country Detail renderer into the static dashboard HTML.

Reads the projection, temperature score state, and country registry. Does not
rewrite score files and does not import trader, PM, or freeze modules.
"""

from __future__ import annotations

import argparse
import html
from pathlib import Path

from scripts.country_detail.attention import evaluate_projection
from scripts.country_detail.policy import COUNTRY_CODES
from scripts.country_detail.projection import build_projection
from scripts.country_detail.render import (
    _preview_fixtures,
    _preview_script,
    country_detail_css,
    render_country_detail,
)
from scripts.country_registry import dashboard_keys, load_country_registry, stale_after_days
from scripts.temperature_level import load_state

ROOT = Path(__file__).resolve().parents[1]
SCORES_PATH = ROOT / "data" / "temperature_scores.json"
REGISTRY_PATH = ROOT / "data" / "country_registry.json"
REVIEW_PATH = ROOT / "tests" / "fixtures" / "country_detail" / "review.html"
_CSS_MARKER = "Country Detail — mobile-first"
_TEMP_INPUTS = '<div class="temp-inputs"'


def _registry(root: Path):
    path = root / "data" / "country_registry.json"
    if path.is_file():
        return load_country_registry(path)
    return load_country_registry(REGISTRY_PATH)


def _scores_path(root: Path) -> Path:
    path = root / "data" / "temperature_scores.json"
    if path.is_file():
        return path
    return SCORES_PATH


def load_country_detail_context(root: Path | None = None) -> dict:
    """Read-only projection, attention, and stored score state."""
    root = root or ROOT
    projection = build_projection(root)
    registry = _registry(root)
    attention = evaluate_projection(
        projection,
        stale_after_days=stale_after_days(registry),
    )
    scores = load_state(_scores_path(root))
    return {"projection": projection, "attention": attention, "scores": scores}


def render_dashboard_sections(root: Path | None = None, context: dict | None = None) -> dict[str, str]:
    ctx = context or load_country_detail_context(root)
    projection = ctx["projection"]
    attention = ctx["attention"]
    scores = ctx["scores"]
    sections: dict[str, str] = {}
    for code in COUNTRY_CODES:
        sections[code] = render_country_detail(
            code,
            projection["countries"][code],
            attention["countries"][code],
            scores,
        )
    return sections


def _inject_css(page: str) -> str:
    style_end = page.find("</style>")
    if style_end < 0:
        raise ValueError("dashboard HTML has no </style> for country detail CSS")
    head = page[:style_end]
    if _CSS_MARKER in head:
        return page
    css = country_detail_css().strip()
    return page[:style_end] + "\n" + css + "\n" + page[style_end:]


def _closing_div(page: str, start: int) -> int:
    """Return the index just after the </div> that closes the div at start."""
    if not page.startswith("<div", start):
        raise ValueError("expected a div tag")
    open_end = page.find(">", start)
    if open_end < 0:
        raise ValueError("unclosed div start tag")
    pos = open_end + 1
    depth = 1
    while depth:
        next_open = page.find("<div", pos)
        next_close = page.find("</div>", pos)
        if next_close < 0:
            raise ValueError("unbalanced div while matching temp-inputs")
        if next_open != -1 and next_open < next_close:
            depth += 1
            pos = next_open + 4
        else:
            depth -= 1
            pos = next_close + len("</div>")
    return pos


def _country_bounds(page: str, key: str, keys: list[str]) -> tuple[int, int]:
    anchor = f'<div class="cdetail {key}">'
    start = page.find(anchor)
    if start < 0:
        raise ValueError(f"missing cdetail block for {key}")
    later = []
    for other in keys:
        idx = page.find(f'<div class="cdetail {other}">', start + len(anchor))
        if idx != -1:
            later.append(idx)
    end = min(later) if later else len(page)
    return start, end


def _inject_section(block: str, key: str, section: str) -> str:
    count = block.count(_TEMP_INPUTS)
    if count > 1:
        raise ValueError(f"cdetail {key} has {count} temp-inputs blocks")
    if count == 1:
        start = block.find(_TEMP_INPUTS)
        end = _closing_div(block, start)
        return block[:start] + section + block[end:]
    anchor = f'<div class="cdetail {key}">'
    idx = block.find(anchor)
    if idx < 0:
        raise ValueError(f"cdetail {key} opening tag missing")
    insert_at = idx + len(anchor)
    return block[:insert_at] + section + block[insert_at:]


def apply_country_detail(page: str, *, root: Path | None = None) -> str:
    """Replace each country's temp-inputs block with a country-detail section."""
    root = root or ROOT
    registry = _registry(root)
    keys = dashboard_keys(registry)
    page = _inject_css(page)
    present = [
        code
        for code in COUNTRY_CODES
        if f'<div class="cdetail {keys[code]}">' in page
    ]
    if not present:
        raise ValueError("dashboard HTML has no cdetail blocks")
    sections = render_dashboard_sections(root)
    key_list = [keys[code] for code in COUNTRY_CODES]
    bounds = [(code, _country_bounds(page, keys[code], key_list)) for code in present]
    for code, (start, end) in reversed(bounds):
        block = page[start:end]
        updated = _inject_section(block, keys[code], sections[code])
        page = page[:start] + updated + page[end:]
    return page


def write_review_html(path: Path | None = None, *, root: Path | None = None) -> str:
    """Write a review document from the real projection plus synthetic panes."""
    root = root or ROOT
    ctx = load_country_detail_context(root)
    sections = render_dashboard_sections(root, ctx)
    fixtures = _preview_fixtures()
    css = country_detail_css()
    as_of = ctx["projection"].get("as_of") or ""

    synthetic_order = (
        ("Populated", "populated"),
        ("Quiet", "quiet"),
        ("Degraded", "degraded"),
    )
    synthetic_html: list[str] = []
    for heading, key in synthetic_order:
        code, proj, att, scores = fixtures[key]
        fragment = render_country_detail(code, proj, att, scores)
        synthetic_html.append(
            f'<div class="review-pane"><h2>{html.escape(heading)} ({html.escape(code)})</h2>{fragment}</div>'
        )

    switcher = "".join(
        f'<label><input type="radio" name="cd-country" value="{code}"'
        f'{" checked" if code == "US" else ""}> {html.escape(code)}</label>'
        for code in COUNTRY_CODES
    )
    panes: list[str] = []
    for code in COUNTRY_CODES:
        active = " is-active" if code == "US" else ""
        panes.append(
            f'<div class="country-pane{active}" data-country-pane="{html.escape(code)}">'
            f"{sections[code]}</div>"
        )

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Country Detail review</title>
<style>
{css}
</style>
</head>
<body class="cdetail-preview">
<h1>Country Detail review</h1>
<p>Real projection as of {html.escape(str(as_of))}. Synthetic panes below are renderer fixtures, separate from the six live countries.</p>
<h2>Synthetic panes</h2>
{"".join(synthetic_html)}
<h2>Real countries</h2>
<div class="country-switcher">{switcher}</div>
{"".join(panes)}
<script>
{_preview_script()}
</script>
</body>
</html>
"""
    out = path or REVIEW_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    return doc


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Apply Country Detail sections to dashboard HTML")
    parser.add_argument("index_html", type=Path, help="path to index.html")
    args = parser.parse_args(argv)
    path = args.index_html
    page = path.read_text(encoding="utf-8")
    path.write_text(apply_country_detail(page), encoding="utf-8")


if __name__ == "__main__":
    main()
