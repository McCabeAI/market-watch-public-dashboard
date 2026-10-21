"""Manual CLI for the Australian CPI data layer.

T2 can register ``nowcast``, ``backtest``, ``replay``, and ``scorecard``
by calling ``register_command`` before ``main``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from scripts.au_cpi_release.archive import (
    ArchiveConflict,
    snapshot_archive_dir,
    write_snapshot_archive,
)
from scripts.au_cpi_release.calendar import entry_for, sydney_now
from scripts.au_cpi_release.sources.acquire import build_snapshot
from scripts.au_cpi_release.sources.http import SourceError

# T2 appends subparser registrars here. Each callable receives the subparsers object.
SUBPARSER_REGISTRARS: list[Callable[[Any], None]] = []


def register_command(registrar: Callable[[Any], None]) -> None:
    """Extension point for later nowcast, backtest, replay, and scorecard commands."""
    SUBPARSER_REGISTRARS.append(registrar)


def _release_time(release: str | None) -> str | None:
    if not release:
        return None
    return entry_for(release).release_at


def cmd_snapshot(args: argparse.Namespace) -> int:
    if not args.live:
        print("NOT PUBLISHED\nreason: snapshot requires --live\n", file=sys.stderr)
        return 2
    as_of = args.as_of or sydney_now().isoformat()
    release = args.release
    try:
        release_time = _release_time(release)
        snapshot, raw_files = build_snapshot(wayback=not args.no_wayback)
        directory = snapshot_archive_dir(Path(args.out), as_of, snapshot)
        generated_at = sydney_now().isoformat()
        manifest = write_snapshot_archive(
            directory,
            snapshot,
            raw_files,
            as_of=as_of,
            release=release,
            release_time=release_time,
            generated_at=generated_at,
        )
    except ArchiveConflict as exc:
        print(f"NOT PUBLISHED\nreason: {exc}\n", file=sys.stderr)
        return 2
    except (SourceError, OSError) as exc:
        print(f"NOT PUBLISHED\nreason: {exc}\n", file=sys.stderr)
        return 2
    print(directory)
    print(manifest.get("snapshot_sha256", ""))
    print(f"retrieved_at={snapshot.retrieved_at}")
    return 0


def cmd_verify_trim(args: argparse.Namespace) -> int:
    from scripts.au_cpi_release.sources.acquire import load_snapshot
    from scripts.au_cpi_release.trim import write_trim_report

    try:
        snapshot = load_snapshot(Path(args.fixture))
        report_path = write_trim_report(snapshot, Path(args.fixture).parent, Path(args.out))
    except (SourceError, OSError) as exc:
        print(f"NOT PUBLISHED\nreason: {exc}\n", file=sys.stderr)
        return 2
    print(report_path)
    return 0


def _register_snapshot(sub: Any) -> None:
    parser = sub.add_parser("snapshot", help="Fetch official sources into an immutable snapshot archive")
    parser.add_argument("--as-of", dest="as_of", default=None, help="Information cutoff (default: now, Australia/Sydney)")
    parser.add_argument("--out", type=Path, required=True, help="Parent directory for snapshots/")
    parser.add_argument("--live", action="store_true", help="Required. Fetch official sources over the network")
    parser.add_argument("--release", default=None, help="Optional reference period recorded on the manifest")
    parser.add_argument(
        "--no-wayback",
        action="store_true",
        help="Skip the time-boxed Wayback workbook attempt",
    )
    parser.set_defaults(func=cmd_snapshot)


def _register_verify_trim(sub: Any) -> None:
    parser = sub.add_parser("verify-trim", help="Rank-and-trim reconstruction diagnostic (offline fixture)")
    parser.add_argument("--fixture", type=Path, required=True, help="snapshot.json")
    parser.add_argument("--out", type=Path, required=True, help="Directory for the verification report")
    parser.set_defaults(func=cmd_verify_trim)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.au_cpi_release")
    sub = parser.add_subparsers(dest="command", required=True)
    _register_snapshot(sub)
    _register_verify_trim(sub)
    for registrar in SUBPARSER_REGISTRARS:
        registrar(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 2
    return int(func(args))


if __name__ == "__main__":
    raise SystemExit(main())
