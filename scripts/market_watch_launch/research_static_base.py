"""Static dashboard base used by the research edition renderer.

These functions reproduce the inline ``deploy-pages.yml`` steps that rebuild
the v6 page and apply the v7, v9 and v8 patches. ``tests/test_mw_research_parity``
executes the workflow heredocs and these functions on the same inputs and
requires byte-identical output, so the two paths cannot drift silently.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import re
from pathlib import Path

V6_B64_BYTES = 41912
V6_HTML_BYTES = 134496
V6_HTML_SHA256 = "2c68341978db2ccc8efdd8f1af7bee4e105c89427f741bb10e7747cb98dde917"
TOP_DRIVERS_ANCHOR = '<div class="stitle">Top Market Drivers</div>'
X_SIGNAL_ANCHOR = '<div class="x-signal">'
COUNTRY_KEYS = ("us", "ca", "au", "nz", "ea", "jp")


class StaticBaseError(RuntimeError):
    pass


def rebuild_v6_base(root: Path) -> str:
    parts = sorted((Path(root) / "payload_v6").glob("part*.b64"))
    blob = b"".join(path.read_bytes() for path in parts)
    if len(blob) != V6_B64_BYTES:
        raise StaticBaseError(f"v6 base64 payload is {len(blob)} bytes, expected {V6_B64_BYTES}")
    raw = gzip.decompress(base64.b64decode(blob))
    if len(raw) != V6_HTML_BYTES:
        raise StaticBaseError(f"v6 html is {len(raw)} bytes, expected {V6_HTML_BYTES}")
    if hashlib.sha256(raw).hexdigest() != V6_HTML_SHA256:
        raise StaticBaseError("v6 html sha256 mismatch")
    return raw.decode("utf-8")


def apply_last24(root: Path, base: str) -> str:
    patch = Path(root) / "patch_v7"
    css = (patch / "last24.css").read_text()
    html = "".join(path.read_text() for path in sorted(patch.glob("last24_*.html")))
    if ".last24{" in base or "Last 24 Hours · Desk Summary" in base:
        raise StaticBaseError("v6 base already contains v7 patch")
    if base.count("</style>") < 1 or base.count(TOP_DRIVERS_ANCHOR) != 1:
        raise StaticBaseError("v6 patch anchors changed")
    out = base.replace("</style>", css + "\n</style>", 1)
    out = out.replace(TOP_DRIVERS_ANCHOR, "\n" + html + TOP_DRIVERS_ANCHOR, 1)
    count = out.count('class="last24-item"')
    if not 1 <= count <= 6:
        raise StaticBaseError(f"invalid last-24 item count {count}")
    for needle in ("Last 24 Hours · Desk Summary", 'class="last24-window"', "Last refreshed"):
        if needle not in out:
            raise StaticBaseError(f"last-24 patch missing {needle!r}")
    return out


def apply_news_rollup(root: Path, base: str) -> str:
    rollup = (Path(root) / "patch_v9" / "news_rollup.html").read_text()
    if base.count(TOP_DRIVERS_ANCHOR) != 1 or base.count(X_SIGNAL_ANCHOR) != 1:
        raise StaticBaseError("rolling-news anchors changed")
    a = base.index(TOP_DRIVERS_ANCHOR)
    b = base.index(X_SIGNAL_ANCHOR, a)
    out = base[:a] + rollup + base[b:]
    if out.count('class="driver-card"') > 3 or out.count('class="driver-card"') < 1:
        raise StaticBaseError("invalid top-driver count")
    story_count = out.count('class="story"')
    if not 1 <= story_count <= 12:
        raise StaticBaseError(f"invalid rolling digest count: {story_count}")
    if '<div class="stitle">7-Day Quick Digest</div>' not in rollup or '<div class="scanline"><b>Window:</b>' not in rollup:
        raise StaticBaseError("rolling digest metadata missing")
    if "7-Day Quick Digest" not in out and "Accepted Overnight Research · Age Unverified" not in out:
        raise StaticBaseError("missing dated or undated news digest section")
    return out


def apply_temperature_inputs(root: Path, base: str) -> str:
    patch = Path(root) / "patch_v8"
    css = (patch / "temp_scores.css").read_text()
    blocks = {key: (patch / f"{key}.html").read_text() for key in COUNTRY_KEYS}
    if ".temp-inputs{" in base or 'class="temp-dimension"' in base:
        raise StaticBaseError("temperature score patch already present")
    if base.count("</style>") < 1:
        raise StaticBaseError("temperature score CSS anchor changed")
    out = base.replace("</style>", css + "\n</style>", 1)
    for key in COUNTRY_KEYS:
        anchor = f'<div class="cdetail {key}">'
        if out.count(anchor) != 1:
            raise StaticBaseError(f"{key} country anchor changed")
        out = out.replace(anchor, anchor + "\n" + blocks[key], 1)
    if len(re.findall(r'class="temp-dimension', out)) != 24:
        raise StaticBaseError("expected 24 temperature dimensions")
    if out.count("Hard score inputs") != 24 or out.count('class="evidence-block context"') != 24:
        raise StaticBaseError("temperature input evidence blocks changed")
    return out


def assert_six_economies(html: str) -> None:
    for needle in (
        'id="c-ea"',
        'id="c-jp"',
        "<h3>EURO AREA</h3>",
        "<h3>JAPAN</h3>",
        'class="cdetail ea"',
        'class="cdetail jp"',
    ):
        if needle not in html:
            raise StaticBaseError(f"six-economy extension missing {needle!r}")
