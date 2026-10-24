"""Capture dashboard screenshots for visual QA.

Usage:
    python3 scripts/visual_qa/capture.py http://localhost:8000/ OUT_DIR [--full]
    python3 scripts/visual_qa/capture.py --serve _site OUT_DIR [--full] [--only=front]

Requires the optional ``playwright`` Python package and a Chrome/Chromium
binary (``CHROME_PATH`` or ``/usr/local/bin/google-chrome``). The dashboard
must be served over HTTP because the Market Data and Trader Book tabs fetch
JSON siblings. Not used by CI.
"""

from __future__ import annotations

import functools
import http.server
import os
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

VIEWPORTS = {
    "wide": {"width": 1920, "height": 1080, "mobile": False},
    "laptop": {"width": 1440, "height": 900, "mobile": False},
    "iphone": {"width": 390, "height": 844, "mobile": True},
}

PAGES = [
    ("front", "p-front", None),
    ("country-us", "p-country", "c-us"),
    ("country-ca", "p-country", "c-ca"),
    ("country-au", "p-country", "c-au"),
    ("country-nz", "p-country", "c-nz"),
    ("country-ea", "p-country", "c-ea"),
    ("country-jp", "p-country", "c-jp"),
    ("marketdata", "p-marketdata", None),
    ("traderbook", "p-traderbook", None),
    ("releases", "p-releases", None),
    ("sources", "p-sources", None),
]


def select(page, radio: str) -> None:
    page.evaluate(
        """(id) => { const el = document.getElementById(id);
        if (!el) return; el.checked = true;
        el.dispatchEvent(new Event('change', {bubbles: true})); window.scrollTo(0, 0); }""",
        radio,
    )


def open_details_in_country(page, country_key: str) -> None:
    """Open every <details> inside ``.cdetail.<country_key>`` (nested included)."""
    page.evaluate(
        """(code) => {
        const root = document.querySelector('.cdetail.' + code);
        if (!root) return;
        root.querySelectorAll('details').forEach((d) => { d.open = true; });
    }""",
        country_key,
    )


def slice_image(path: Path, dest: Path) -> None:
    """Cut a full-page capture into readable viewport-sized chunks (needs Pillow)."""
    try:
        from PIL import Image
    except ImportError:
        return
    Image.MAX_IMAGE_PIXELS = None
    dest.mkdir(parents=True, exist_ok=True)
    with Image.open(path) as image:
        width, height = image.size
        step = width * 7 // 10 if width > 1000 else width * 2
        for index, top in enumerate(range(0, height, step)):
            image.crop((0, top, width, min(height, top + step))).save(dest / f"{path.stem}-{index:02d}.png")


def serve(directory: str) -> str:
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

    handler = functools.partial(QuietHandler, directory=directory)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}/"


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--only=") and a != "--full"]
    if args[0] == "--serve":
        base, out = serve(args[1]), Path(args[2])
    else:
        base, out = args[0], Path(args[1])
    full = "--full" in sys.argv
    open_details = "--open-details" in sys.argv
    only = [a.split("=", 1)[1] for a in sys.argv if a.startswith("--only=")]
    out.mkdir(parents=True, exist_ok=True)
    chrome = os.environ.get("CHROME_PATH", "/usr/local/bin/google-chrome")
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome)
        for vname, vp in VIEWPORTS.items():
            ctx = browser.new_context(
                viewport={"width": vp["width"], "height": vp["height"]},
                device_scale_factor=2 if vp["mobile"] else 1,
                is_mobile=vp["mobile"],
                has_touch=vp["mobile"],
            )
            page = ctx.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(base, wait_until="networkidle")
            for name, radio, sub in PAGES:
                if only and not any(name.startswith(o) for o in only):
                    continue
                select(page, radio)
                if sub:
                    select(page, sub)
                    if open_details:
                        open_details_in_country(page, sub.removeprefix("c-"))
                page.wait_for_timeout(600)
                shot = out / f"{vname}-{name}.png"
                page.screenshot(path=str(shot), full_page=full)
                if full:
                    slice_image(shot, out / "slices")
                overflow = page.evaluate(
                    "document.documentElement.scrollWidth - document.documentElement.clientWidth"
                )
                if overflow > 0:
                    print(f"{vname}-{name}: horizontal overflow {overflow}px")
            for e in errors:
                print(f"{vname}: pageerror {e}")
            ctx.close()
        browser.close()


if __name__ == "__main__":
    main()
