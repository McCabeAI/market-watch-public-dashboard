#!/usr/bin/env python3
"""Materialize deterministic conflict routing for an existing Trader Room round 1."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.trader_room.conflict import detect_conflicts, rebuttal_assignments
from scripts.trader_room.schema import validate_contribution


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", type=Path, required=True)
    args = ap.parse_args(argv)

    run_dir = args.run_dir
    packet = load_json(run_dir / "evidence_packet.json")
    originals = {}
    for path in sorted((run_dir / "submissions").glob("*.json")):
        item = load_json(path)
        originals[item["agent"]] = validate_contribution(item, packet=packet, expected_agent=item["agent"])

    conflict_map = detect_conflicts(originals)
    assignments = rebuttal_assignments(conflict_map)

    (run_dir / "conflict_map.json").write_text(
        json.dumps(conflict_map, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (run_dir / "rebuttal_assignments.json").write_text(
        json.dumps(assignments, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "run_id": packet["run_id"],
        "method": conflict_map.get("method"),
        "direct_conflicts": len(conflict_map["conflicts"]),
        "theoretical_tensions": len(conflict_map.get("theoretical_tensions") or []),
        "context_tensions": len(conflict_map.get("context_tensions") or []),
        "rebuttal_seats": sorted(assignments),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
