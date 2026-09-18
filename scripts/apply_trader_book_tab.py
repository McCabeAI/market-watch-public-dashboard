"""Add the Trader Book tab after the Market Data tab. Additive only."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def apply_trader_book_tab(path: Path, *, repo_root: Path | None = None) -> Path:
    root = repo_root or Path.cwd()
    path = Path(path)
    site_dir = path.parent
    html = path.read_text()
    css = (root / "patch_v13/trader_book.css").read_text()
    page = (root / "patch_v13/trader_book_page.html").read_text()

    if 'id="p-traderbook"' in html or "Trader Book · paper P&L" in html:
        raise SystemExit("trader book tab patch already present")
    if 'id="p-marketdata"' not in html:
        raise SystemExit("Market Data tab must be applied before Trader Book")

    nav_rule_anchor = "#p-marketdata:checked~.app .nav label[for=p-marketdata],"
    if nav_rule_anchor not in html:
        raise SystemExit("trader book nav active-state CSS anchor changed")
    html = html.replace(
        nav_rule_anchor,
        nav_rule_anchor + "\n#p-traderbook:checked~.app .nav label[for=p-traderbook],",
        1,
    )

    page_display_anchor = "#p-marketdata:checked~.app .marketdata,"
    if page_display_anchor not in html:
        raise SystemExit("trader book page display CSS anchor changed")
    html = html.replace(
        page_display_anchor,
        page_display_anchor + "#p-traderbook:checked~.app .traderbook,",
        1,
    )

    radio_anchor = '<input id="p-marketdata" name="page" type="radio"/>'
    if html.count(radio_anchor) != 1:
        raise SystemExit("market data radio anchor changed")
    html = html.replace(
        radio_anchor,
        radio_anchor + '\n<input id="p-traderbook" name="page" type="radio"/>',
        1,
    )

    nav_anchor = '<label for="p-marketdata">Market Data</label>'
    if html.count(nav_anchor) != 1:
        raise SystemExit("market data nav label anchor changed")
    html = html.replace(
        nav_anchor,
        nav_anchor + '<label for="p-traderbook">Trader Book</label>',
        1,
    )

    section_anchor = '<section class="page marketdata">'
    if html.count(section_anchor) != 1:
        raise SystemExit("market data section anchor changed")

    if "</style>" not in html:
        raise SystemExit("style anchor missing")
    html = html.replace("</style>", css + "\n</style>", 1)

    end_anchor = '<section class="page relative">'
    if html.count(end_anchor) != 1:
        raise SystemExit("relative page section anchor changed")
    html = html.replace(end_anchor, page + "\n" + end_anchor, 1)

    for required in (
        "Last 24 Hours · Desk Summary",
        "7-Day Quick Digest",
        "Live 1–100 Score Board",
        "Market Data · official snapshot",
        "Trader Book · paper P&L",
    ):
        if required not in html:
            raise SystemExit(f"trader book tab lost required dashboard marker: {required}")

    path.write_text(html)
    shutil.copyfile(root / "patch_v13/trader-book.js", site_dir / "trader-book.js")
    return path


if __name__ == "__main__":
    apply_trader_book_tab(Path(sys.argv[1] if len(sys.argv) > 1 else "_site/index.html"))
