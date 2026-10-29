"""CLI entrypoint for macro ingestion runner."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from typing import Any

from scripts.macro_ingestion.contract import COUNTRY_CODES
from scripts.macro_ingestion.ledger import load_latest
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


def run_data_only_catch_up(
    *,
    root: Path,
    output_dir: Path,
    mode: str = "offline",
    countries: list[str] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Refresh macro observations and research-facing builders under ``output_dir`` only.

    Does not run trader room, PM decisions, or mutate repo canonical stores.
    """
    from scripts.apply_country_detail import render_dashboard_sections

    output_dir = output_dir.resolve()
    obs_dir = output_dir / "observations"
    health_dir = output_dir / "health"
    raw_dir = output_dir / "raw" if mode == "live" else None
    for path in (obs_dir, health_dir):
        path.mkdir(parents=True, exist_ok=True)
    if raw_dir is not None:
        raw_dir.mkdir(parents=True, exist_ok=True)

    persistent = root / "data" / "macro_ingestion" / "observations"
    prior_rows: list[dict] | None = None
    persistent_health = root / "data" / "macro_ingestion" / "health" / "latest.json"
    if persistent_health.is_file():
        rows = load_latest(persistent_health.parent).get("rows")
        if isinstance(rows, list) and rows:
            prior_rows = list(rows)

    target_countries = countries or list(COUNTRY_CODES)
    ingestion = run_ingestion(
        mode=mode,
        countries=target_countries,
        run_id=run_id,
        persist_canonical=False,
        observations_dir=obs_dir,
        health_dir=health_dir,
        raw_dir=raw_dir,
        seed_observations_from=persistent if persistent.is_dir() else None,
        prior_rows=prior_rows,
        write_health=True,
    )

    sections = render_dashboard_sections(root, observations_dir=obs_dir)
    builders_dir = output_dir / "research_builders"
    builders_dir.mkdir(parents=True, exist_ok=True)
    (builders_dir / "country_detail_sections.json").write_text(
        json.dumps(sections, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return {
        "mode": "data_only_catch_up",
        "output_dir": str(output_dir),
        "ingestion": {
            "checked_at": ingestion.get("checked_at"),
            "row_count": len(ingestion.get("rows") or []),
        },
        "research_builders": {
            "country_detail_sections": str(builders_dir / "country_detail_sections.json"),
            "country_count": len(sections),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Six-economy macro ingestion runner")
    parser.add_argument("--mode", choices=("offline", "live"), default="offline")
    parser.add_argument("--country", default="all", help="Country code or 'all'")
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--data-only-catch-up",
        action="store_true",
        help="Write observations and research builder output under --output-dir only",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Required with --data-only-catch-up; must not be the repo canonical macro tree",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="Repository root for read-only catalog/history inputs",
    )
    args = parser.parse_args(argv)

    if args.data_only_catch_up:
        if args.output_dir is None:
            parser.error("--data-only-catch-up requires --output-dir")
        canonical = (args.root / "data" / "macro_ingestion").resolve()
        out = args.output_dir.resolve()
        if out == canonical or canonical in out.parents:
            parser.error("--output-dir must be outside the canonical macro_ingestion tree")
        stamp = datetime.now(timezone.utc).strftime("catchup-%Y%m%dT%H%M%SZ")
        payload = run_data_only_catch_up(
            root=args.root,
            output_dir=out,
            mode=args.mode,
            countries=_parse_countries(args.country),
            run_id=args.run_id or stamp,
        )
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

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
