"""Bounded one-release listener.

Arm is a foreground process. It keeps publishing while the release is
INCOMPLETE, and it stops on a settled source set, cancellation, or its deadline.
It does not install a cron or a recurring workflow.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.core_pce_release.calculator import calculate
from scripts.core_pce_release.ledger import export_observations, merge_observations, series_ids_for_period
from scripts.core_pce_release.packet import load_packet
from scripts.core_pce_release.report import render_detailed, render_flash
from scripts.core_pce_release.snapshot import load_snapshot, residual_weight


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_ledger(packet_dir: Path) -> tuple[dict, list[dict]]:
    path = packet_dir / "ledger.json"
    if not path.exists():
        return {}, []
    document = json.loads(path.read_text(encoding="utf-8"))
    ledger: dict = {}
    conflicts: list[dict] = list(document.get("conflicts") or [])
    merge_observations(ledger, list(document.get("observations") or []))
    return ledger, conflicts


def _save_ledger(packet_dir: Path, ledger: dict, conflicts: list[dict]) -> None:
    payload = {
        "observations": export_observations(ledger),
        "conflicts": conflicts,
    }
    (packet_dir / "ledger.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _outstanding(expected: list[str], ledger: dict, release: str) -> list[str]:
    if not expected:
        return []
    present = series_ids_for_period(ledger, release)
    return [series_id for series_id in expected if series_id not in present]


def _publish(packet_dir: Path, calculated: dict, revision: dict) -> None:
    (packet_dir / "flash.txt").write_text(render_flash(calculated), encoding="utf-8")
    (packet_dir / "detailed.txt").write_text(render_detailed(calculated), encoding="utf-8")
    (packet_dir / "detailed.json").write_text(json.dumps(calculated, indent=2) + "\n", encoding="utf-8")
    with (packet_dir / "revisions.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(revision) + "\n")


def run_listener(
    packet_dir: Path,
    inbox: Path,
    *,
    now,
    sleep,
    max_runtime_seconds: float,
    interval_seconds: float,
    fetch=None,
) -> dict:
    packet = load_packet(packet_dir)
    if packet.get("status") != "READY":
        return {"state": "STOPPED", "reason": "packet_not_ready", "polls": 0, "headline": None}
    snapshot = load_snapshot(Path(packet["snapshot_dir"]))
    release = packet["release"]
    expected = list(packet.get("fetch_series") or [])
    inbox.mkdir(parents=True, exist_ok=True)
    (packet_dir / "raw").mkdir(parents=True, exist_ok=True)
    started = now()
    deadline = started + max(0.0, max_runtime_seconds)
    seen_files: set[str] = set()
    seen_rejections: set[str] = set()
    seen_raw: set[str] = set()
    rejections: list[dict] = []

    def _reject(row: dict) -> None:
        key = json.dumps(row, sort_keys=True, default=str)
        if key in seen_rejections:
            return
        seen_rejections.add(key)
        rejections.append(row)
    ledger, conflicts = _load_ledger(packet_dir)
    polls = 0
    revisions = 0
    published_once = False
    previous_contribution = None
    latest_seen: dict[str, str] = {}

    def _reject_stale_latest(batch: dict) -> dict:
        fresh_observations = []
        for observation in batch.get("observations") or []:
            series_id = observation.get("series_id")
            latest = (batch.get("series_latest") or {}).get(series_id)
            previous = latest_seen.get(series_id)
            if series_id and latest and previous and latest < previous:
                _reject({"series_id": series_id, "reason": "stale_cache", "latest": latest, "previous": previous})
                continue
            fresh_observations.append(observation)
            if series_id and latest:
                latest_seen[series_id] = latest
        batch = dict(batch)
        batch["observations"] = fresh_observations
        return batch

    def _calculate_and_maybe_publish(source_latency: float | None, seen_at: float, new_count: int) -> dict:
        nonlocal revisions, published_once, previous_contribution
        calculated = calculate(
            snapshot["components"],
            snapshot["levels"],
            release,
            export_observations(ledger),
            residual_weight=residual_weight(snapshot),
        )
        flash_at = now()
        calculated["latency"] = {
            "source_seen_clock": seen_at,
            "flash_clock": flash_at,
            "source_latency_seconds": source_latency,
            "flash_seconds_after_seen": flash_at - seen_at,
            "official_publication_latency": "UNMEASURED",
            "sla_claim": None,
            "note": (
                "source_latency_seconds is BLS HTTP time. "
                "flash_seconds_after_seen is local handler time after the response was in memory. "
                "Neither is official publication lag."
            ),
        }
        (packet_dir / "flash.txt").write_text(render_flash(calculated), encoding="utf-8")
        detailed_at = now()
        calculated["latency"]["detailed_clock"] = detailed_at
        calculated["latency"]["detailed_seconds_after_seen"] = detailed_at - seen_at
        contribution = calculated.get("resolved_contribution_percent")
        delta = None
        if contribution is not None and previous_contribution is not None:
            from decimal import Decimal

            delta = format(Decimal(contribution) - Decimal(previous_contribution), "f")
        revision = {
            "revision": revisions + 1,
            "headline": calculated["headline"],
            "headline_reason": calculated.get("headline_reason"),
            "resolved_contribution_percent": contribution,
            "contribution_delta_vs_previous": delta,
            "projected_core_pce_mom_percent": calculated.get("projected_core_pce_mom_percent"),
            "horizons": calculated["horizons"],
            "coverage": calculated["coverage"],
            "source_latency_seconds": source_latency,
            "handler_flash_seconds": calculated["latency"]["flash_seconds_after_seen"],
            "new_observations": new_count,
            "outstanding_series": len(_outstanding(expected, ledger, release)),
        }
        _publish(packet_dir, calculated, revision)
        revisions += 1
        published_once = True
        previous_contribution = contribution
        return calculated

    while True:
        if (packet_dir / "CANCEL").exists():
            result = {"state": "STOPPED", "reason": "cancelled", "polls": polls, "headline": None, "revisions": revisions}
            (packet_dir / "listener_result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            return result
        polls += 1
        new_count = 0
        source_latency = None
        if fetch is not None and expected:
            batch = fetch(expected, release)
            if not isinstance(batch, dict):
                raise TypeError("fetch must return a dict")
            source_latency = batch.get("source_latency_seconds")
            batch = _reject_stale_latest(batch)
            for gap in batch.get("gaps") or []:
                _reject(gap)
            raw_documents = batch.get("raw_documents") or []
            if raw_documents:
                encoded = json.dumps(raw_documents).encode("utf-8")
                digest = hashlib.sha256(encoded).hexdigest()
                if digest not in seen_raw:
                    seen_raw.add(digest)
                    (packet_dir / "raw" / f"poll-{polls}.json").write_bytes(encoded)
                    (packet_dir / "raw" / f"poll-{polls}.sha256").write_text(digest + "\n", encoding="utf-8")
            merged = merge_observations(ledger, list(batch.get("observations") or []))
            conflicts.extend(merged["conflicts"])
            new_count += len(merged["changed"])
        for path in sorted(inbox.glob("*.json")):
            try:
                digest = _sha256(path)
            except OSError as exc:
                _reject({"file": path.name, "reason": "transport_error", "detail": str(exc)})
                continue
            if digest in seen_files:
                continue
            seen_files.add(digest)
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                _reject({"file": path.name, "reason": "transport_error"})
                continue
            if payload.get("target_period") != release:
                _reject({"file": path.name, "reason": "stale_period", "target_period": payload.get("target_period")})
                continue
            incoming = list(payload.get("observations") or [])
            if payload.get("simulated"):
                for observation in incoming:
                    observation["simulated"] = True
            merged = merge_observations(ledger, incoming)
            conflicts.extend(merged["conflicts"])
            new_count += len(merged["changed"])
        calculated = None
        if new_count:
            # Clock starts after the source body is in memory, so handler time
            # does not include BLS HTTP time.
            seen_at = now()
            calculated = _calculate_and_maybe_publish(source_latency, seen_at, new_count)
            _save_ledger(packet_dir, ledger, conflicts)
        (packet_dir / "rejections.json").write_text(json.dumps(rejections, indent=2) + "\n", encoding="utf-8")
        (packet_dir / "conflicts.json").write_text(json.dumps(conflicts, indent=2) + "\n", encoding="utf-8")
        outstanding = _outstanding(expected, ledger, release)
        headline = None if calculated is None else calculated["headline"]
        if calculated is None and (packet_dir / "detailed.json").exists() and published_once:
            headline = json.loads((packet_dir / "detailed.json").read_text(encoding="utf-8"))["headline"]
        settled = published_once and not outstanding and new_count == 0
        if now() >= deadline or max_runtime_seconds <= 0:
            outcome = {
                "state": "STOPPED",
                "reason": "deadline",
                "polls": polls,
                "headline": headline,
                "revisions": revisions,
                "outstanding_series": len(outstanding),
                "rejections": rejections,
            }
            (packet_dir / "listener_result.json").write_text(json.dumps(outcome, indent=2) + "\n", encoding="utf-8")
            return outcome
        if settled:
            outcome = {
                "state": "COMPLETED",
                "reason": "sources_settled",
                "polls": polls,
                "headline": headline,
                "revisions": revisions,
                "outstanding_series": 0,
            }
            (packet_dir / "listener_result.json").write_text(json.dumps(outcome, indent=2) + "\n", encoding="utf-8")
            return outcome
        if headline in {"HOT", "NEUTRAL", "COLD"} and not outstanding:
            outcome = {
                "state": "COMPLETED",
                "reason": "estimate_complete",
                "polls": polls,
                "headline": headline,
                "revisions": revisions,
                "outstanding_series": 0,
            }
            (packet_dir / "listener_result.json").write_text(json.dumps(outcome, indent=2) + "\n", encoding="utf-8")
            return outcome
        remaining = deadline - now()
        sleep(min(interval_seconds, max(0.0, remaining)))
