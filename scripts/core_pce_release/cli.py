"""Manual CLI. prepare and arm run only when invoked."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from scripts.core_pce_release.acquire import acquire_official
from scripts.core_pce_release.calculator import calculate
from scripts.core_pce_release.listener import run_listener
from scripts.core_pce_release.packet import load_packet, prepare
from scripts.core_pce_release.report import render_detailed, render_flash
from scripts.core_pce_release.snapshot import DEFAULT_SNAPSHOT, load_snapshot, residual_weight


def _run(packet_dir: Path, observations_path: Path) -> tuple[int, str]:
    packet = load_packet(packet_dir)
    if packet.get("status") != "READY":
        return 2, "NOT READY\nreason: packet_not_ready\n"
    payload = json.loads(observations_path.read_text(encoding="utf-8"))
    if payload.get("target_period") != packet["release"]:
        return 2, "NOT READY\nreason: stale_period\n"
    snapshot = load_snapshot(Path(packet["snapshot_dir"]))
    started = time.perf_counter()
    result = calculate(
        snapshot["components"],
        snapshot["levels"],
        packet["release"],
        list(payload.get("observations") or []),
        residual_weight=residual_weight(snapshot),
    )
    elapsed = time.perf_counter() - started
    result["latency"] = {
        "compute_seconds": elapsed,
        "source_available_at": payload.get("source_available_at"),
        "official_publication_latency": "UNMEASURED",
        "sla_claim": None,
        "note": "compute_seconds is local arithmetic after the observation file was already in hand.",
    }
    flash = render_flash(result)
    detailed = render_detailed(result)
    (packet_dir / "flash.txt").write_text(flash, encoding="utf-8")
    (packet_dir / "detailed.txt").write_text(detailed, encoding="utf-8")
    (packet_dir / "detailed.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0, detailed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.core_pce_release")
    sub = parser.add_subparsers(dest="command", required=True)

    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("kind", choices=("cpi", "ppi"))
    prepare_parser.add_argument("--release", default="2026-09")
    prepare_parser.add_argument("--out", type=Path, required=True)
    prepare_parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)

    run_parser = sub.add_parser("run")
    run_parser.add_argument("--packet", type=Path, required=True)
    run_parser.add_argument("--observations", type=Path, required=True)

    arm_parser = sub.add_parser("arm")
    arm_parser.add_argument("--packet", type=Path, required=True)
    arm_parser.add_argument("--inbox", type=Path, required=True)
    arm_parser.add_argument("--max-runtime-seconds", type=float, default=0)
    arm_parser.add_argument("--interval-seconds", type=float, default=5)
    arm_parser.add_argument(
        "--no-live-fetch",
        action="store_true",
        help="Inbox only. The operator pilot omits this flag so arm fetches BLS itself.",
    )

    args = parser.parse_args(argv)
    if args.command == "prepare":
        code, text = prepare(args.kind, args.release, args.out, args.snapshot)
        print(text, end="")
        return code
    if args.command == "run":
        code, text = _run(args.packet, args.observations)
        print(text, end="")
        return code

    def _fetch(series_ids: list[str], release: str) -> dict:
        return acquire_official(series_ids, release)

    outcome = run_listener(
        args.packet,
        args.inbox,
        now=time.monotonic,
        sleep=time.sleep,
        max_runtime_seconds=args.max_runtime_seconds,
        interval_seconds=args.interval_seconds,
        fetch=None if args.no_live_fetch else _fetch,
    )
    reason = outcome.get("reason")
    if reason:
        print(f"stopped: {reason}", flush=True)
    return 0 if outcome.get("headline") else 0


if __name__ == "__main__":
    raise SystemExit(main())
