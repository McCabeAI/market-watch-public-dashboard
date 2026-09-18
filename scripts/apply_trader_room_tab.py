"""Add the full Trader Room tab after Trader Book. Additive only."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def apply_trader_room_tab(path: Path, *, repo_root: Path | None = None) -> Path:
    root = repo_root or Path.cwd()
    path = Path(path)
    site_dir = path.parent
    html = path.read_text()
    css = (root / "patch_v14/trader_room.css").read_text()
    page = (root / "patch_v14/trader_room_page.html").read_text()

    if 'id="p-traderroom"' in html or "Trader Room · adversarial ideas" in html:
        raise SystemExit("trader room tab patch already present")
    if 'id="p-traderbook"' not in html:
        raise SystemExit("Trader Book tab must be applied before Trader Room")

    radio_anchor = '<input id="p-traderbook" name="page" type="radio"/>'
    if html.count(radio_anchor) != 1:
        raise SystemExit("trader book radio anchor changed")
    html = html.replace(
        radio_anchor,
        radio_anchor + '\n<input id="p-traderroom" name="page" type="radio"/>',
        1,
    )

    nav_anchor = '<label for="p-traderbook">Trader Book</label>'
    if html.count(nav_anchor) != 1:
        raise SystemExit("trader book nav label anchor changed")
    html = html.replace(
        nav_anchor,
        nav_anchor + '<label for="p-traderroom">Trader Room</label>',
        1,
    )

    if "</style>" not in html:
        raise SystemExit("style anchor missing")
    html = html.replace("</style>", css + "\n</style>", 1)

    end_anchor = '<section class="page relative">'
    if html.count(end_anchor) != 1:
        raise SystemExit("relative page section anchor changed")
    html = html.replace(end_anchor, page + "\n" + end_anchor, 1)

    for required in (
        "Last 24 Hours · Desk Summary",
        "Live 1–100 Score Board",
        "Market Data · official snapshot",
        "Trader Book · paper P&L",
        "Trader Room · adversarial ideas",
    ):
        if required not in html:
            raise SystemExit(f"trader room tab lost required dashboard marker: {required}")

    path.write_text(html)
    shutil.copyfile(root / "patch_v14/trader-room.js", site_dir / "trader-room.js")
    return path


if __name__ == "__main__":
    apply_trader_room_tab(Path(sys.argv[1] if len(sys.argv) > 1 else "_site/index.html"))
