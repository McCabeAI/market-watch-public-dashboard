"""Static dashboard base used by the research edition renderer.

These functions reproduce the inline ``deploy-pages.yml`` steps that rebuild
the v6 page and apply the v7, v9 and v8 patches. ``tests/test_mw_research_parity``
executes the workflow heredocs and these functions on the same inputs and
requires byte-identical output, so the two paths cannot drift silently.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import sys
from pathlib import Path

from scripts.market_watch_launch.publication_issues import record_diagnostic

V6_B64_BYTES = 41912
V6_HTML_BYTES = 134496
V6_HTML_SHA256 = "2c68341978db2ccc8efdd8f1af7bee4e105c89427f741bb10e7747cb98dde917"
TOP_DRIVERS_ANCHOR = '<div class="stitle">Top Market Drivers</div>'
X_SIGNAL_ANCHOR = '<div class="x-signal">'
COUNTRY_KEYS = ("us", "ca", "au", "nz", "ea", "jp")
_COUNTRY_CODES = {"us": "US", "ca": "CA", "au": "AU", "nz": "NZ", "ea": "EA", "jp": "JP"}


class StaticBaseError(RuntimeError):
    pass


def _skip_static_patch(
    html: str,
    *,
    component: str,
    cause: str,
    country: str | None = None,
    diagnostics: Path | str | None = None,
) -> str:
    record_diagnostic(
        f"static_base_skipped:{component}",
        path=diagnostics,
        category="render",
        severity="warning",
        component=component,
        country=country,
        cause=cause,
        impact="This static patch was not applied; downstream fallbacks may neutralize stale base-page content.",
    )
    from scripts.market_watch_launch.render_fallbacks import news_unavailable

    if component in ("static_base:last24", "static_base:news_rollup"):
        try:
            return news_unavailable(html)
        except Exception:
            return html
    return html


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


def apply_last24(
    root: Path,
    base: str,
    *,
    diagnostics: Path | str | None = None,
    strict: bool = True,
) -> str:
    patch = Path(root) / "patch_v7"
    if ".last24{" in base or "Last 24 Hours · Desk Summary" in base:
        record_diagnostic(
            "static_base_present:last24",
            path=diagnostics,
            category="render",
            severity="info",
            component="static_base:last24",
            cause="The last-24-hours static patch is already present on the page.",
            impact="The patch step was skipped.",
        )
        return base
    if base.count("</style>") < 1 or base.count(TOP_DRIVERS_ANCHOR) != 1:
        if strict:
            raise StaticBaseError("v6 patch anchors changed")
        return _skip_static_patch(
            base,
            component="static_base:last24",
            cause="Last-24 patch anchors are missing or ambiguous on the v6 base page.",
            diagnostics=diagnostics,
        )
    css = (patch / "last24.css").read_text()
    html = "".join(path.read_text() for path in sorted(patch.glob("last24_*.html")))
    out = base.replace("</style>", css + "\n</style>", 1)
    out = out.replace(TOP_DRIVERS_ANCHOR, "\n" + html + TOP_DRIVERS_ANCHOR, 1)
    return out


def apply_news_rollup(
    root: Path,
    base: str,
    *,
    diagnostics: Path | str | None = None,
    strict: bool = True,
) -> str:
    rollup = (Path(root) / "patch_v9" / "news_rollup.html").read_text()
    if base.count(TOP_DRIVERS_ANCHOR) != 1 or base.count(X_SIGNAL_ANCHOR) != 1:
        if strict:
            raise StaticBaseError("rolling-news anchors changed")
        return _skip_static_patch(
            base,
            component="static_base:news_rollup",
            cause="Rolling-news anchors are missing or ambiguous on the page.",
            diagnostics=diagnostics,
        )
    a = base.index(TOP_DRIVERS_ANCHOR)
    b = base.index(X_SIGNAL_ANCHOR, a)
    return base[:a] + rollup + base[b:]


def apply_temperature_inputs(
    root: Path,
    base: str,
    *,
    diagnostics: Path | str | None = None,
    strict: bool = True,
) -> str:
    patch = Path(root) / "patch_v8"
    if 'class="temp-dimension"' in base and "Hard score inputs" in base:
        record_diagnostic(
            "static_base_present:temperature_inputs",
            path=diagnostics,
            category="render",
            severity="info",
            component="static_base:temperature_inputs",
            cause="Temperature input score blocks are already present on the page.",
            impact="The patch step was skipped.",
        )
        return base
    if base.count("</style>") < 1:
        raise StaticBaseError("temperature score CSS anchor changed")
    css = (patch / "temp_scores.css").read_text()
    blocks = {key: (patch / f"{key}.html").read_text() for key in COUNTRY_KEYS}
    out = base.replace("</style>", css + "\n</style>", 1)
    for key in COUNTRY_KEYS:
        anchor = f'<div class="cdetail {key}">'
        if out.count(anchor) != 1:
            if strict:
                raise StaticBaseError(f"{key} country anchor changed")
            record_diagnostic(
                f"static_base_skipped:temperature_inputs:{key}",
                path=diagnostics,
                category="render",
                severity="warning",
                component="static_base:temperature_inputs",
                country=_COUNTRY_CODES[key],
                cause=f"The {key.upper()} country-detail anchor is missing or ambiguous.",
                impact="Temperature input score blocks were not applied for this country.",
            )
            continue
        out = out.replace(anchor, anchor + "\n" + blocks[key], 1)
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


def build_static_base_html(
    root: Path,
    *,
    diagnostics: Path | str | None = None,
    strict: bool = True,
) -> str:
    v6 = rebuild_v6_base(root)
    return apply_news_rollup(
        root,
        apply_last24(root, v6, diagnostics=diagnostics, strict=strict),
        diagnostics=diagnostics,
        strict=strict,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Market Watch static base patcher")
    sub = parser.add_subparsers(dest="command", required=True)
    base_p = sub.add_parser("base", help="Rebuild v6 and apply last-24 + news rollup patches")
    base_p.add_argument("--root", type=Path, required=True)
    base_p.add_argument("--out", type=Path, required=True)
    base_p.add_argument(
        "--strict",
        action="store_true",
        help="Refuse when last-24 or rolling-news patch anchors are missing (default: skip with diagnostics)",
    )
    temp_p = sub.add_parser("temperature-inputs", help="Apply temperature input score blocks in place")
    temp_p.add_argument("--root", type=Path, required=True)
    temp_p.add_argument("--html", type=Path, required=True)
    temp_p.add_argument(
        "--strict",
        action="store_true",
        help="Refuse when a country-detail anchor is missing (default: skip that country with diagnostics)",
    )
    args = parser.parse_args(argv)
    strict = bool(args.strict)
    try:
        if args.command == "base":
            html = build_static_base_html(args.root, strict=strict)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(html, encoding="utf-8")
        else:
            page = args.html.read_text(encoding="utf-8")
            args.html.write_text(
                apply_temperature_inputs(args.root, page, strict=strict),
                encoding="utf-8",
            )
    except StaticBaseError as exc:
        print(f"static base error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
