from __future__ import annotations

import shutil
import sys
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else "_site/index.html")
site_dir = path.parent
html = path.read_text()
css = Path("patch_v12/market_data.css").read_text()
page = Path("patch_v12/market_data_page.html").read_text()

if 'id="p-marketdata"' in html or "Market Data · official snapshot" in html:
    raise SystemExit("market data tab patch already present")

nav_rule_anchor = "#p-feed:checked~.app .nav label[for=p-feed],"
if nav_rule_anchor not in html:
    raise SystemExit("nav active-state CSS anchor changed")
html = html.replace(
    nav_rule_anchor,
    nav_rule_anchor + "\n#p-marketdata:checked~.app .nav label[for=p-marketdata],",
    1,
)

page_display_anchor = "#p-feed:checked~.app .feed,"
if page_display_anchor not in html:
    raise SystemExit("page display CSS anchor changed")
html = html.replace(
    page_display_anchor,
    page_display_anchor + "#p-marketdata:checked~.app .marketdata,",
    1,
)

radio_anchor = '<input id="p-feed" name="page" type="radio"/>'
if html.count(radio_anchor) != 1:
    raise SystemExit("page radio anchor changed")
html = html.replace(
    radio_anchor,
    '<input id="p-marketdata" name="page" type="radio"/>\n' + radio_anchor,
    1,
)

nav_anchor = '<label for="p-feed">Feed &amp; Momentum</label>'
if html.count(nav_anchor) != 1:
    raise SystemExit("nav label anchor changed")
html = html.replace(
    nav_anchor,
    '<label for="p-marketdata">Market Data</label>' + nav_anchor,
    1,
)

section_anchor = '<section class="page relative">'
if html.count(section_anchor) != 1:
    raise SystemExit("relative page section anchor changed")

if "</style>" not in html:
    raise SystemExit("style anchor missing")
html = html.replace("</style>", css + "\n</style>", 1)
html = html.replace(section_anchor, page + "\n" + section_anchor, 1)

path.write_text(html)
shutil.copyfile("patch_v12/market-data.js", site_dir / "market-data.js")
