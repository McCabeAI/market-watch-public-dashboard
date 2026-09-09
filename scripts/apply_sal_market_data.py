#!/usr/bin/env python3
"""Inject the validated Sal V1 fragment into the reconstructed dashboard."""
from __future__ import annotations

import argparse
from pathlib import Path

ANCHOR = '<div class="stitle">Top Market Drivers</div>'
MARKER = 'id="sal-market-data"'


def apply(index: Path, css_path: Path, fragment_path: Path) -> None:
    base = index.read_text()
    css = css_path.read_text()
    fragment = fragment_path.read_text().strip()
    if MARKER in base:
        raise SystemExit("Sal market-data patch already present")
    if base.count(ANCHOR) != 1:
        raise SystemExit("Sal dashboard anchor changed")
    if base.count("</style>") < 1:
        raise SystemExit("Sal style anchor missing")
    if MARKER not in fragment:
        raise SystemExit("Sal fragment marker missing")
    out = base.replace("</style>", css + "\n</style>", 1)
    out = out.replace(ANCHOR, fragment + "\n" + ANCHOR, 1)
    if out.count(MARKER) != 1:
        raise SystemExit("Sal patch marker count invalid")
    index.write_text(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True)
    ap.add_argument("--css", required=True)
    ap.add_argument("--fragment", required=True)
    args = ap.parse_args()
    apply(Path(args.index), Path(args.css), Path(args.fragment))


if __name__ == "__main__":
    main()
