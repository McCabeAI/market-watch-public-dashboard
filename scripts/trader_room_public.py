#!/usr/bin/env python3
"""Emit a compact public Trader Room summary for the dashboard."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_RELPATH = Path("data/trader-room/public/latest.json")


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
    text = _text(value)
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
    }


def build_public_packet(root: Path = ROOT) -> dict[str, Any]:
    published = root / PUBLIC_RELPATH
    if not published.is_file():
        return {
            "available": False,
            "status": "no_published_run",
            "message": "No Trader Room run has been published to the dashboard yet.",
            "trades": [],
        }
    packet = _load(published)
    if not isinstance(packet, dict) or not isinstance(packet.get("trades"), list):
        raise ValueError("published Trader Room summary is malformed")
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
