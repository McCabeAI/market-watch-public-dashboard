"""CLI entrypoint for macro ingestion runner."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts.macro_ingestion.contract import COUNTRY_CODES
from scripts.macro_ingestion.runner import RAW_DIR, run_ingestion

ROOT = Path(__file__).resolve().parents[2]


def resolve_raw_dir(mode: str) -> Path | None:
    if mode == "live":
        return RAW_DIR
    return None


def _parse_countries(raw: str) -> list[str]:
    if raw.lower() == "all":
        return list(COUNTRY_CODES)
    return [part.strip().upper() for part in raw.split(",") if part.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Six-economy macro ingestion runner")
    parser.add_argument("--mode", choices=("offline", "live"), default="offline")
    parser.add_argument("--country", default="all", help="Country code or 'all'")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args(argv)

    countries = _parse_countries(args.country)
    kwargs: dict = {
        "mode": args.mode,
        "countries": countries,
        "run_id": args.run_id,
        "persist_canonical": args.mode == "live",
    }
    raw_dir = resolve_raw_dir(args.mode)
    if raw_dir is not None:
        kwargs["raw_dir"] = raw_dir
    result = run_ingestion(**kwargs)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
