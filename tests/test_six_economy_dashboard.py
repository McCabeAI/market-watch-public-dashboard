from __future__ import annotations

import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

from scripts.apply_six_economy_dashboard import (
    COUNTRY_PAGE_END,
    NZ_CDETAIL_CLOSE,
    apply_six_economy_dashboard,
)
from scripts.apply_temperature_scores import apply_scores
from scripts.dashboard_mini_cards import PLACEHOLDER_VALUES, mini_rows_for_country

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_V3 = Path(__file__).resolve().parent / "fixtures" / "temperature_scores_v3_minimal.json"


class _CdetailStackParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stack: list[tuple[str, str | None]] = []
        self.cdetail_parent: dict[str, str | None] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "div":
            return
        classes = dict(attrs).get("class") or ""
        klass = classes if isinstance(classes, str) else " ".join(classes)
        cdetail_key = None
        for token in klass.split():
            if token in {"us", "ca", "au", "nz", "ea", "jp"} and "cdetail" in klass:
                cdetail_key = token
                break
        parent = None
        for entry in reversed(self.stack):
            if entry[1] is not None:
                parent = entry[1]
                break
        if cdetail_key:
            self.cdetail_parent[cdetail_key] = parent
        self.stack.append((tag, cdetail_key))

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self.stack:
            self.stack.pop()


def _tiny_country_page_fixture() -> str:
    css_label = (
        "#c-us:checked~.app label[for=c-us],#c-ca:checked~.app label[for=c-ca],"
        "#c-au:checked~.app label[for=c-au],#c-nz:checked~.app label[for=c-nz]"
        "{background:var(--navy);color:#fff;border-color:var(--navy)}"
    )
    css_detail = (
        "#c-us:checked~.app .cdetail.us,#c-ca:checked~.app .cdetail.ca,"
        "#c-au:checked~.app .cdetail.au,#c-nz:checked~.app .cdetail.nz{display:block}"
    )
    board_css = ".board{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin-bottom:12px}"
    switch_anchor = (
        '<label for="c-us">United States</label>'
        '<label for="c-ca">Canada</label>'
        '<label for="c-au">Australia</label>'
        '<label for="c-nz">New Zealand</label>'
    )
    nz_jump = '<label class="jump" for="c-nz">Open NZ detail</label>\n</div>\n</div>'
    return f"""<html><style>{css_label}
{css_detail}
{board_css}
</style>
<section class="page country">
<input id="c-nz" name="country" type="radio"/>
<div class="board">{switch_anchor}
<div class="card"><h3>NEW ZEALAND</h3>{nz_jump}
<div class="cdetail us"></div>
<div class="cdetail nz"><span>nz-inner</span>{COUNTRY_PAGE_END}
"""


def _pipeline_html() -> str:
    import base64
    import gzip

    chunks = b"".join(Path(p).read_bytes() for p in sorted(ROOT.glob("payload_v6/part*.b64")))
    html = gzip.decompress(base64.b64decode(chunks)).decode("utf-8")
    css = (ROOT / "patch_v7" / "last24.css").read_text(encoding="utf-8")
    last24 = (ROOT / "patch_v7").glob("last24_*.html")
    last24_html = "".join(Path(p).read_text(encoding="utf-8") for p in sorted(last24))
    anchor = '<div class="stitle">Top Market Drivers</div>'
    html = html.replace("</style>", css + "\n</style>", 1)
    html = html.replace(anchor, "\n" + last24_html + anchor, 1)
    rollup = (ROOT / "patch_v9" / "news_rollup.html").read_text(encoding="utf-8")
    start = '<div class="stitle">Top Market Drivers</div>'
    end = '<div class="x-signal">'
    a = html.index(start)
    b = html.index(end, a)
    html = html[:a] + rollup + html[b:]
    html = apply_six_economy_dashboard(html)
    css_v8 = (ROOT / "patch_v8" / "temp_scores.css").read_text(encoding="utf-8")
    html = html.replace("</style>", css_v8 + "\n</style>", 1)
    for key in ("us", "ca", "au", "nz", "ea", "jp"):
        anchor_tag = f'<div class="cdetail {key}">'
        block = (ROOT / "patch_v8" / f"{key}.html").read_text(encoding="utf-8")
        html = html.replace(anchor_tag, anchor_tag + "\n" + block, 1)
    return html


class SixEconomyDashboardTest(unittest.TestCase):
    def test_cdetail_insertion_after_nz_close_on_tiny_fixture(self) -> None:
        html = apply_six_economy_dashboard(_tiny_country_page_fixture())
        self.assertRegex(
            html,
            r'<div class="cdetail nz"><span>nz-inner</span></div>\s*<div class="cdetail ea">',
        )
        self.assertNotIn(
            '<div class="cdetail nz"><span>nz-inner</span><div class="cdetail ea">',
            html,
        )

    def test_ea_jp_cdetail_are_siblings_not_inside_nz(self) -> None:
        html = _pipeline_html()
        parser = _CdetailStackParser()
        parser.feed(html)
        self.assertIsNone(parser.cdetail_parent.get("ea"))
        self.assertIsNone(parser.cdetail_parent.get("jp"))
        self.assertIsNone(parser.cdetail_parent.get("us"))
        self.assertNotEqual(parser.cdetail_parent.get("ea"), "nz")
        self.assertNotEqual(parser.cdetail_parent.get("jp"), "nz")

    def test_four_drawers_per_country_block(self) -> None:
        html = _pipeline_html()
        state = json.loads(FIXTURE_V3.read_text(encoding="utf-8"))
        html = apply_scores(html, state)
        self.assertEqual(html.count('class="temp-dimension score-detail"'), 24)
        for key in ("us", "ca", "au", "nz", "ea", "jp"):
            anchor = f'<div class="cdetail {key}">'
            start = html.index(anchor)
            later = [
                html.find(f'<div class="cdetail {other}">', start + len(anchor))
                for other in ("us", "ca", "au", "nz", "ea", "jp")
                if other != key
            ]
            end = min(i for i in later if i != -1) if any(i != -1 for i in later) else len(html)
            block = html[start:end]
            self.assertEqual(block.count('class="temp-dimension score-detail"'), 4)

    def test_ea_jp_mini_values_not_placeholders_from_fixture(self) -> None:
        html = _pipeline_html()
        state = json.loads(FIXTURE_V3.read_text(encoding="utf-8"))
        out = apply_scores(html, state)
        for heading in ("EURO AREA", "JAPAN"):
            match = re.search(
                rf"<h3>{heading}</h3>.*?<div class=\"mini\">(.*?)</div>\s*<label class=\"jump\"",
                out,
                flags=re.S,
            )
            self.assertIsNotNone(match, heading)
            for value in re.findall(r"<b>([^<]*)</b>", match.group(1)):
                self.assertNotIn(value.strip(), PLACEHOLDER_VALUES, msg=heading)

    def test_mini_rows_mapping_fixture(self) -> None:
        state = json.loads(FIXTURE_V3.read_text(encoding="utf-8"))
        ea_rows = dict(mini_rows_for_country(state, "EA"))
        self.assertEqual(ea_rows["HICP / core"], "3.2% / 2.4%")
        self.assertEqual(ea_rows["Unemployment"], "6.4%")
        self.assertEqual(ea_rows["Business surveys"], "51.3333")
        jp_rows = dict(mini_rows_for_country(state, "JP"))
        self.assertEqual(jp_rows["CPI / core"], "2% / 1.7%")
        self.assertEqual(jp_rows["Unemployment"], "2.4%")
        self.assertEqual(jp_rows["Domestic demand"], "1.65%")

    def test_mini_rows_mapping_live_state(self) -> None:
        from scripts.apply_temperature_scores import load_state

        state = load_state()
        ea_rows = dict(mini_rows_for_country(state, "EA"))
        self.assertEqual(ea_rows["HICP / core"], "3.2% / 2.4%")
        self.assertEqual(ea_rows["Unemployment"], "6.4%")
        jp_rows = dict(mini_rows_for_country(state, "JP"))
        self.assertEqual(jp_rows["CPI / core"], "2% / 1.7%")
        self.assertEqual(jp_rows["Unemployment"], "2.4%")


if __name__ == "__main__":
    unittest.main()
