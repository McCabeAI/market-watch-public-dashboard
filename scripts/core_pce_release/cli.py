"""Manual CLI. prepare and arm run only when invoked."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from scripts.core_pce_release.acquire import acquire_official
from scripts.core_pce_release.bls_quota import (
    BLSQuotaLedger,
    PacketArmLock,
    default_daily_ceiling,
    default_not_before,
    key_present_in_env,
)
from scripts.core_pce_release.calculator import calculate
from scripts.core_pce_release.listener import run_listener
from scripts.core_pce_release.oneshot import (
    authorize_from_environment,
    run_oneshot,
    write_github_output,
    write_unexpected_error,
)
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


def _parse_not_before(raw: str) -> datetime:
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        raise ValueError("not-before must be timezone-aware ISO-8601")
    return parsed


def _hold_payload(ledger: BLSQuotaLedger, reason: str) -> dict:
    status = ledger.status_dict(reason)
    return {
        "observations": [],
        "gaps": [{"reason": reason}],
        "quota_status": status,
        "requests_made": 0,
        "budget_exhausted": False,
        "quota_exhausted": reason in {"ceiling", "bls_throttled", "ledger_unreadable"},
        "quota_reason": reason,
        "key_present": ledger.key_present,
        "source_latency_seconds": 0.0,
        "series_latest": {},
        "raw_documents": [],
    }


def main(
    argv: list[str] | None = None,
    *,
    poster=None,
    wall_clock=None,
    monotonic=None,
    sleeper=None,
) -> int:
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

    run_ppi_parser = sub.add_parser("run-ppi")
    run_ppi_parser.add_argument("--release", default="2026-09")
    run_ppi_parser.add_argument("--out", type=Path, required=True)

    sub.add_parser("authorize-ppi-issue")

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
    arm_parser.add_argument("--bls-daily-ceiling", type=int, default=None)
    arm_parser.add_argument("--not-before", type=str, default=None)

    args = parser.parse_args(argv)
    if args.command == "prepare":
        code, text = prepare(args.kind, args.release, args.out, args.snapshot)
        print(text, end="", flush=True)
        return code
    if args.command == "run":
        code, text = _run(args.packet, args.observations)
        print(text, end="", flush=True)
        return code
    if args.command == "authorize-ppi-issue":
        decision = authorize_from_environment(os.environ)
        write_github_output(decision)
        print(json.dumps({"authorized": decision["authorized"], "reason": decision["reason"]}), flush=True)
        return 0
    if args.command == "run-ppi":
        if args.release != "2026-09":
            print("refusing: release must be 2026-09", flush=True)
            return 2
        try:
            run_oneshot(args.out, release=args.release)
        except Exception:  # noqa: BLE001 — comment stays free of exception text
            write_unexpected_error(args.out)
            return 1
        return 0

    wall = wall_clock or (lambda: datetime.now(timezone.utc))
    mono = monotonic or time.monotonic
    sleep_fn = sleeper or time.sleep

    if args.no_live_fetch:

        def _fetch(series_ids: list[str], release: str) -> dict:
            return acquire_official(series_ids, release, poster=poster)

        outcome = run_listener(
            args.packet,
            args.inbox,
            now=mono,
            sleep=sleep_fn,
            max_runtime_seconds=args.max_runtime_seconds,
            interval_seconds=args.interval_seconds,
            fetch=None if args.no_live_fetch else _fetch,
        )
        reason = outcome.get("reason")
        if reason:
            print(f"stopped: {reason}", flush=True)
        return 0 if outcome.get("headline") else 0

    if args.bls_daily_ceiling is not None and args.bls_daily_ceiling < 0:
        print("stopped: invalid_bls_daily_ceiling", flush=True)
        return 2

    packet = load_packet(args.packet)
    key_present = key_present_in_env()
    not_before = default_not_before(packet["release"], packet["kind"])
    if args.not_before is not None:
        try:
            not_before = _parse_not_before(args.not_before)
        except ValueError:
            print("stopped: invalid_not_before", flush=True)
            return 2
    ceiling = default_daily_ceiling(key_present, override=args.bls_daily_ceiling)

    lock = PacketArmLock(args.packet)
    if not lock.acquire():
        print("stopped: concurrent_arm_blocked", flush=True)
        return 2

    try:
        return _run_live_arm(
            args,
            packet=packet,
            ceiling=ceiling,
            not_before=not_before,
            key_present=key_present,
            wall=wall,
            mono=mono,
            sleep_fn=sleep_fn,
            poster=poster,
        )
    finally:
        lock.release()


def _run_live_arm(
    args,
    *,
    packet: dict,
    ceiling: int,
    not_before,
    key_present: bool,
    wall,
    mono,
    sleep_fn,
    poster,
) -> int:
    ledger = BLSQuotaLedger.open_ledger(
        args.packet,
        release=packet["release"],
        kind=packet["kind"],
        ceiling=ceiling,
        not_before=not_before,
        key_present=key_present,
        wall_clock=wall,
    )
    last_status_reason: str | None = "__init__"

    def _emit_quota_line(reason: str | None) -> None:
        nonlocal last_status_reason
        if reason == last_status_reason:
            return
        print(ledger.format_status_line(reason), flush=True)
        last_status_reason = reason

    def _fetch(series_ids: list[str], release: str) -> dict:
        permitted, deny = ledger.network_permitted(wall())
        if not permitted:
            payload = _hold_payload(ledger, deny or "pacing")
            _emit_quota_line(deny)
            return payload
        result = acquire_official(series_ids, release, quota=ledger, poster=poster)
        if result.get("quota_reason"):
            _emit_quota_line(result.get("quota_reason"))
        elif result.get("quota_status", {}).get("reason"):
            _emit_quota_line(result["quota_status"].get("reason"))
        return result

    outcome = run_listener(
        args.packet,
        args.inbox,
        now=mono,
        sleep=sleep_fn,
        max_runtime_seconds=args.max_runtime_seconds,
        interval_seconds=args.interval_seconds,
        fetch=_fetch,
    )
    reason = outcome.get("reason")
    if reason:
        print(f"stopped: {reason}", flush=True)
    final_reason = outcome.get("bls_quota", {}).get("reason") if outcome.get("bls_quota") else last_status_reason
    if final_reason == "__init__":
        permitted, deny = ledger.network_permitted(wall())
        final_reason = deny if not permitted else None
    print(ledger.format_status_line(final_reason), flush=True)
    return 0 if outcome.get("headline") else 0


if __name__ == "__main__":
    raise SystemExit(main())
