"""Bounded one-release listener. Exits on its own. No recurring timer and no cron."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.core_pce_release.calculator import calculate
from scripts.core_pce_release.packet import load_packet
from scripts.core_pce_release.report import render_detailed, render_flash
from scripts.core_pce_release.snapshot import load_snapshot, residual_weight


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _latency(seen_at: float, flash_at: float, detailed_at: float) -> dict:
    return {
        "source_seen_clock": seen_at,
        "flash_clock": flash_at,
        "detailed_clock": detailed_at,
        "flash_seconds_after_seen": flash_at - seen_at,
        "detailed_seconds_after_seen": detailed_at - seen_at,
        "official_publication_latency": "UNMEASURED",
        "sla_claim": None,
        "note": "Seconds above are local handler time after this process saw a file. They are not BLS or BEA publication latency.",
    }


def run_listener(
    packet_dir: Path,
    inbox: Path,
    *,
    now,
    sleep,
    max_runtime_seconds: float,
    interval_seconds: float,
) -> dict:
    packet = load_packet(packet_dir)
    if packet.get("status") != "READY":
        return {"state": "STOPPED", "reason": "packet_not_ready", "polls": 0, "headline": None}
    snapshot = load_snapshot(Path(packet["snapshot_dir"]))
    release = packet["release"]
    inbox.mkdir(parents=True, exist_ok=True)
    started = now()
    deadline = started + max(0.0, max_runtime_seconds)
    seen: set[str] = set()
    rejections: list[dict] = []
    polls = 0
    while True:
        if (packet_dir / "CANCEL").exists():
            result = {"state": "STOPPED", "reason": "cancelled", "polls": polls, "headline": None}
            (packet_dir / "listener_result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            return result
        polls += 1
        for path in sorted(inbox.glob("*.json")):
            try:
                digest = _sha256(path)
            except OSError as exc:
                rejections.append({"file": path.name, "reason": "transport_error", "detail": str(exc)})
                continue
            if digest in seen:
                continue
            seen.add(digest)
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                rejections.append({"file": path.name, "reason": "transport_error"})
                continue
            if payload.get("target_period") != release:
                rejections.append(
                    {
                        "file": path.name,
                        "reason": "stale_period",
                        "target_period": payload.get("target_period"),
                    }
                )
                continue
            seen_at = now()
            calculated = calculate(
                snapshot["components"],
                snapshot["levels"],
                release,
                list(payload.get("observations") or []),
                residual_weight=residual_weight(snapshot),
            )
            flash_at = now()
            (packet_dir / "flash.txt").write_text(render_flash(calculated), encoding="utf-8")
            detailed_at = now()
            calculated["latency"] = _latency(seen_at, flash_at, detailed_at)
            (packet_dir / "detailed.json").write_text(json.dumps(calculated, indent=2) + "\n", encoding="utf-8")
            (packet_dir / "detailed.txt").write_text(render_detailed(calculated), encoding="utf-8")
            # Rewrite JSON so the latency block is the one on disk after detailed timing.
            calculated["latency"]["detailed_clock"] = detailed_at
            (packet_dir / "detailed.json").write_text(json.dumps(calculated, indent=2) + "\n", encoding="utf-8")
            outcome = {
                "state": "COMPLETED",
                "reason": "release_file_processed",
                "polls": polls,
                "headline": calculated["headline"],
                "latency": calculated["latency"],
            }
            (packet_dir / "listener_result.json").write_text(json.dumps(outcome, indent=2) + "\n", encoding="utf-8")
            (packet_dir / "rejections.json").write_text(json.dumps(rejections, indent=2) + "\n", encoding="utf-8")
            return outcome
        (packet_dir / "rejections.json").write_text(json.dumps(rejections, indent=2) + "\n", encoding="utf-8")
        if now() >= deadline or max_runtime_seconds <= 0:
            outcome = {"state": "STOPPED", "reason": "deadline", "polls": polls, "headline": None, "rejections": rejections}
            (packet_dir / "listener_result.json").write_text(json.dumps(outcome, indent=2) + "\n", encoding="utf-8")
            return outcome
        remaining = deadline - now()
        sleep(min(interval_seconds, remaining))
