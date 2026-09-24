#!/usr/bin/env python3
"""Emit a compact public Trader Room summary for the dashboard.

Pages publication selects the newest COMPLETE VALID run from canonical Git
state under trader-room/runs/. A manually maintained latest.json pointer is
not required and is never the source of truth.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from scripts.trader_room.constants import HANDOFF_MARKER, STANDING_ADVOCATES

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_RELPATH = Path("data/trader-room/public/latest.json")
RUNS_RELPATH = Path("trader-room/runs")
REQUIRED_RUN_FILES = (
    "evidence_packet.json",
    "pm_handoff.json",
    "conflict_map.json",
    "artifact_index.json",
)
_RUN_ID_TS = re.compile(r"^tr-(\d{8}T\d{6}Z)")


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return " ".join(str(x).strip() for x in value if str(x).strip())
    return str(value).strip()


def _clip(value: Any, limit: int = 420) -> str:
    from scripts.overnight.public_prose import sanitize_public_prose

    text = sanitize_public_prose(_text(value), max_chars=limit, fallback="")
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _entry_reason(contribution: dict[str, Any]) -> str:
    trade = contribution.get("trade") or {}
    for candidate in (
        trade.get("why_now"),
        contribution.get("why_now"),
        trade.get("thesis"),
        contribution.get("thesis"),
        contribution.get("stance_summary"),
    ):
        text = _clip(candidate)
        if text:
            return text
    return "No concise entry rationale was supplied."


def _trade_row(agent: str, contribution: dict[str, Any], rebuttal: dict[str, Any] | None) -> dict[str, Any]:
    trade = contribution.get("trade")
    if trade is None:
        return {
            "agent": agent,
            "stance_summary": _clip(contribution.get("stance_summary"), 220),
            "trade": None,
            "confidence": contribution.get("confidence"),
            "entry_reason": _entry_reason(contribution),
            "rebuttal": rebuttal,
        }
    return {
        "agent": agent,
        "stance_summary": _clip(contribution.get("stance_summary"), 220),
        "trade": {
            "instrument": trade.get("instrument"),
            "structure": trade.get("structure"),
            "direction": trade.get("direction"),
            "expression": trade.get("expression"),
            "horizon": trade.get("horizon"),
            "entry": trade.get("entry"),
            "target": trade.get("target"),
            "invalidation": trade.get("invalidation"),
        },
        "confidence": contribution.get("confidence", trade.get("confidence")),
        "entry_reason": _entry_reason(contribution),
        "mispricing": _clip(trade.get("mispricing") or contribution.get("pricing_or_mispricing"), 320),
        "rebuttal": rebuttal,
    }


def run_sort_key(run_id: str) -> tuple[str, str]:
    match = _RUN_ID_TS.match(run_id)
    return (match.group(1) if match else "", run_id)


def list_run_dirs(root: Path = ROOT) -> list[Path]:
    runs_dir = root / RUNS_RELPATH
    if not runs_dir.is_dir():
        return []
    return sorted(
        (path for path in runs_dir.iterdir() if path.is_dir() and not path.name.startswith(".")),
        key=lambda path: run_sort_key(path.name),
    )


def completeness_errors(run_dir: Path) -> list[str]:
    """Return why a run is not a complete valid public candidate. Empty = valid."""
    errors: list[str] = []
    for name in REQUIRED_RUN_FILES:
        if not (run_dir / name).is_file():
            errors.append(f"missing {name}")
    submissions_dir = run_dir / "submissions"
    if not submissions_dir.is_dir():
        errors.append("missing submissions/")
        return errors
    seats = {path.stem for path in submissions_dir.glob("*.json")}
    expected = set(STANDING_ADVOCATES)
    if seats != expected:
        missing = sorted(expected - seats)
        extra = sorted(seats - expected)
        if missing:
            errors.append("missing submissions: " + ",".join(missing))
        if extra:
            errors.append("unexpected submissions: " + ",".join(extra))
    try:
        handoff = _load(run_dir / "pm_handoff.json")
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"unreadable pm_handoff.json: {exc}")
        return errors
    if not isinstance(handoff, dict):
        errors.append("pm_handoff.json is not an object")
        return errors
    if handoff.get("status") != HANDOFF_MARKER:
        errors.append(f"handoff status is {handoff.get('status')!r}, expected {HANDOFF_MARKER}")
    run_id = handoff.get("run_id") or run_dir.name
    if run_id != run_dir.name:
        errors.append(f"handoff run_id {run_id!r} does not match directory {run_dir.name}")
    try:
        evidence = _load(run_dir / "evidence_packet.json")
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"unreadable evidence_packet.json: {exc}")
        return errors
    if not isinstance(evidence, dict) or not evidence.get("packet_sha256"):
        errors.append("evidence_packet.json missing packet_sha256")
    try:
        conflict_map = _load(run_dir / "conflict_map.json")
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"unreadable conflict_map.json: {exc}")
        return errors
    if not isinstance(conflict_map, dict):
        errors.append("conflict_map.json is not an object")
    return errors


def is_complete_valid_run(run_dir: Path) -> bool:
    return not completeness_errors(run_dir)


def select_newest_complete_run(root: Path = ROOT) -> Path | None:
    complete = [path for path in list_run_dirs(root) if is_complete_valid_run(path)]
    return complete[-1] if complete else None


def build_from_run(run_dir: Path) -> dict[str, Any]:
    handoff = _load(run_dir / "pm_handoff.json")
    evidence = _load(run_dir / "evidence_packet.json") if (run_dir / "evidence_packet.json").is_file() else {}
    conflict_map = _load(run_dir / "conflict_map.json") if (run_dir / "conflict_map.json").is_file() else {"conflicts": []}
    rebuttals_dir = run_dir / "rebuttals"
    submissions: dict[str, Any] = {}
    for path in sorted((run_dir / "submissions").glob("*.json")):
        submissions[path.stem] = _load(path)

    rows = []
    for agent, contribution in submissions.items():
        rebuttal = None
        path = rebuttals_dir / f"{agent}.json"
        if path.is_file():
            raw = _load(path)
            rebuttal = {
                "trade_change": raw.get("trade_change"),
                "strongest_opponent_point": _clip(raw.get("strongest_opponent_point"), 260),
            }
        rows.append(_trade_row(agent, contribution, rebuttal))

    return {
        "available": True,
        "run_id": handoff.get("run_id") or evidence.get("run_id") or run_dir.name,
        "status": handoff.get("status"),
        "as_of": evidence.get("as_of"),
        "trade_count": sum(1 for row in rows if row.get("trade")),
        "seat_count": len(rows),
        "conflict_count": len(conflict_map.get("conflicts") or []),
        "trades": rows,
        "selection": {
            "mode": "newest_complete_valid",
            "source": "trader-room/runs",
            "manual_pointer": False,
        },
    }


def empty_public_packet() -> dict[str, Any]:
    return {
        "available": False,
        "status": "no_complete_run",
        "message": "No complete valid Trader Room run is present in canonical Git state.",
        "trades": [],
        "selection": {
            "mode": "newest_complete_valid",
            "source": "trader-room/runs",
            "manual_pointer": False,
        },
    }


def build_public_packet(root: Path = ROOT) -> dict[str, Any]:
    """Project the newest complete valid run. latest.json is never required."""
    selected = select_newest_complete_run(root)
    if selected is None:
        return empty_public_packet()
    packet = build_from_run(selected)
    ignored = [
        {"run_id": path.name, "errors": completeness_errors(path)}
        for path in list_run_dirs(root)
        if path != selected and completeness_errors(path)
    ]
    packet["selection"] = {
        "mode": "newest_complete_valid",
        "source": "trader-room/runs",
        "manual_pointer": False,
        "selected_run_id": packet["run_id"],
        "ignored_incomplete": ignored,
    }
    return packet


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--from-run", type=Path, default=None)
    args = ap.parse_args(argv)
    packet = build_from_run(args.from_run) if args.from_run else build_public_packet(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"available": packet["available"], "run_id": packet.get("run_id"), "trades": len(packet["trades"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
