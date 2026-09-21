#!/usr/bin/env python3
"""Smallest six-economy dashboard generalization: add EA/JP radios, cards, and drawers."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from scripts.dashboard_mini_cards import ea_jp_mini_shell_html

NZ_CDETAIL_CLOSE = "</div>\n"
COUNTRY_PAGE_END = "</div>\n</section>\n<section class=\"page feed\">"


def apply_six_economy_dashboard(html: str) -> str:
    if 'id="c-ea"' in html and 'id="c-jp"' in html and '<div class="cdetail ea">' in html:
        return html

    radio_anchor = '<input id="c-nz" name="country" type="radio"/>'
    if html.count(radio_anchor) != 1:
        raise SystemExit("country radio anchor changed")
    html = html.replace(
        radio_anchor,
        radio_anchor
        + '\n<input id="c-ea" name="country" type="radio"/>'
        + '\n<input id="c-jp" name="country" type="radio"/>',
        1,
    )

    css_label = (
        "#c-us:checked~.app label[for=c-us],#c-ca:checked~.app label[for=c-ca],"
        "#c-au:checked~.app label[for=c-au],#c-nz:checked~.app label[for=c-nz]"
        "{background:var(--navy);color:#fff;border-color:var(--navy)}"
    )
    css_label_new = (
        "#c-us:checked~.app label[for=c-us],#c-ca:checked~.app label[for=c-ca],"
        "#c-au:checked~.app label[for=c-au],#c-nz:checked~.app label[for=c-nz],"
        "#c-ea:checked~.app label[for=c-ea],#c-jp:checked~.app label[for=c-jp]"
        "{background:var(--navy);color:#fff;border-color:var(--navy)}"
    )
    if html.count(css_label) != 1:
        raise SystemExit("country-switch CSS anchor changed")
    html = html.replace(css_label, css_label_new, 1)

    css_detail = (
        "#c-us:checked~.app .cdetail.us,#c-ca:checked~.app .cdetail.ca,"
        "#c-au:checked~.app .cdetail.au,#c-nz:checked~.app .cdetail.nz{display:block}"
    )
    css_detail_new = (
        "#c-us:checked~.app .cdetail.us,#c-ca:checked~.app .cdetail.ca,"
        "#c-au:checked~.app .cdetail.au,#c-nz:checked~.app .cdetail.nz,"
        "#c-ea:checked~.app .cdetail.ea,#c-jp:checked~.app .cdetail.jp{display:block}"
    )
    if html.count(css_detail) != 1:
        raise SystemExit("cdetail display CSS anchor changed")
    html = html.replace(css_detail, css_detail_new, 1)

    board_css = ".board{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin-bottom:12px}"
    board_css_new = (
        ".board{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));"
        "gap:9px;margin-bottom:12px}"
    )
    if html.count(board_css) != 1:
        raise SystemExit("temperature board CSS anchor changed")
    html = html.replace(board_css, board_css_new, 1)

    switch_anchor = (
        '<label for="c-us">United States</label>'
        '<label for="c-ca">Canada</label>'
        '<label for="c-au">Australia</label>'
        '<label for="c-nz">New Zealand</label>'
    )
    if html.count(switch_anchor) != 1:
        raise SystemExit("country-switch label anchor changed")
    html = html.replace(
        switch_anchor,
        switch_anchor
        + '<label for="c-ea">Euro Area</label>'
        + '<label for="c-jp">Japan</label>',
        1,
    )

    ea_mini = ea_jp_mini_shell_html("EA")
    jp_mini = ea_jp_mini_shell_html("JP")
    nz_jump = '<label class="jump" for="c-nz">Open NZ detail</label>\n</div>\n</div>'
    if html.count(nz_jump) != 1:
        raise SystemExit("NZ snapshot card anchor changed")
    html = html.replace(
        nz_jump,
        nz_jump
        + f"""
<div class="card"><div class="chead"><h3>EURO AREA</h3><span class="policy">ECB</span></div><div class="pills"><span class="pill neutral">NEUTRAL</span><span class="dir static">STATIC</span></div>
<div class="engine"><b>Euro area:</b> scored euro-area macro/policy. German Bunds are the EUR cash-rates benchmark only; peripheral spreads are fragmentation context.</div>
{ea_mini}
<label class="jump" for="c-ea">Open EA detail</label>
</div>
<div class="card"><div class="chead"><h3>JAPAN</h3><span class="policy">BOJ</span></div><div class="pills"><span class="pill neutral">NEUTRAL</span><span class="dir static">STATIC</span></div>
<div class="engine"><b>Japan:</b> scored Japan macro/policy with MOF JGB cash yields and TONA policy context.</div>
{jp_mini}
<label class="jump" for="c-jp">Open JP detail</label>
</div>
""",
        1,
    )

    marker = '<div class="cdetail nz">'
    if html.count(marker) != 1:
        raise SystemExit("NZ country-detail anchor changed")
    idx = html.find(marker)
    end = html.find(COUNTRY_PAGE_END, idx)
    if end == -1:
        raise SystemExit("country page end anchor changed")
    insert_at = end + len(NZ_CDETAIL_CLOSE)
    shells = """
<div class="cdetail ea">
<div class="panel hero"><div class="thermo"><div class="stitle">Temperature</div><b>EURO AREA</b><div class="big"><span class="pill neutral">NEUTRAL</span></div><span class="dir static">STATIC</span></div></div>
</div>
<div class="cdetail jp">
<div class="panel hero"><div class="thermo"><div class="stitle">Temperature</div><b>JAPAN</b><div class="big"><span class="pill neutral">NEUTRAL</span></div><span class="dir static">STATIC</span></div></div>
</div>
"""
    html = html[:insert_at] + shells + html[insert_at:]
    return html


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "_site/index.html")
    html = path.read_text(encoding="utf-8")
    out = apply_six_economy_dashboard(html)
    if 'id="c-ea"' not in out or '<h3>EURO AREA</h3>' not in out or '<div class="cdetail jp">' not in out:
        raise SystemExit("six-economy dashboard patch failed")
    path.write_text(out, encoding="utf-8")


if __name__ == "__main__":
    main()
