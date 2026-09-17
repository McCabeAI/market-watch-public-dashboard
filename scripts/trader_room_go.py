#!/usr/bin/env python3
"""One on-demand Trader Room entrypoint.

Default `go` is a complete dry-run: freeze-validate the evidence packet and
run the 14-advocate -> conflict aggregator -> one-pass rebuttal -> final
aggregator workflow without consuming the production Grok/Composer budget.

A live 14-trader research run requires TRADER_ROOM_LIVE=1 and `--live`.
That path uses Cursor native parent-agent orchestration: one grok-4.6 parent
invokes the 14 standing grok-4.6 seats against the identical frozen packet.
The Python LiveRunner does not synthesize model output. CI remains refused.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts.trader_room.artifacts import retrieve
from scripts.trader_room.constants import HANDOFF_MARKER, ROOT
from scripts.trader_room.errors import LiveRunBlocked, ParentDispatchRequired, TraderRoomError
from scripts.trader_room.orchestrator import go, prepare_evidence
from scripts.trader_room.runners import build_launch_plan


def _print(payload: dict) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="On-demand Trader Room entrypoint")
    parser.add_argument(
        "command",
        nargs="?",
        default="go",
        choices=("go", "prepare", "retrieve"),
        help="go is the single on-demand workflow (default)",
    )
    parser.add_argument("--topic", default="go", help="User topic/hypothesis; 'go' is sufficient")
    parser.add_argument("--synthetic", action="store_true", help="Use the minimal frozen fixture")
    parser.add_argument("--repo-evidence", action="store_true", help="Assemble evidence from repo surfaces")
    parser.add_argument("--fixture", type=Path, help="Override synthetic fixture path")
    parser.add_argument("--market-state", type=Path, help="Optional market-state JSON")
    parser.add_argument("--artifact-root", type=Path, default=ROOT)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Request the production 14-trader Cursor-native run (requires TRADER_ROOM_LIVE=1)",
    )
    parser.add_argument("--resume", action="store_true", help="Resume a live run from persisted packet")
    parser.add_argument("--run-id", help="retrieve/resume: run id")
    parser.add_argument("--kind", help="retrieve: evidence_packet|submission|rebuttal|conflict_map|pm_handoff")
    parser.add_argument("--agent", help="retrieve: advocate name when kind is submission/rebuttal")
    args = parser.parse_args(argv)

    try:
        if args.command == "prepare":
            packet, preflight = prepare_evidence(
                topic=args.topic,
                synthetic=not args.repo_evidence,
                fixture=args.fixture,
                market_state_path=args.market_state,
            )
            _print(
                {
                    "run_id": packet["run_id"],
                    "evidence_cutoff": packet["as_of"],
                    "packet_sha256": packet["packet_sha256"],
                    "preflight": preflight,
                    "launch_plan": build_launch_plan(packet),
                    "status": "EVIDENCE_FROZEN",
                }
            )
            return 0
        if args.command == "retrieve":
            if not args.run_id or not args.kind:
                raise SystemExit("retrieve requires --run-id and --kind")
            _print(retrieve(args.artifact_root, args.run_id, args.kind, args.agent))
            return 0

        result = go(
            topic=args.topic,
            live=args.live,
            synthetic=not args.repo_evidence,
            fixture=args.fixture,
            market_state_path=args.market_state,
            artifact_root=args.artifact_root,
            resume_run_id=args.run_id if args.resume else None,
        )
        _print(
            {
                "run_id": result["run_id"],
                "evidence_cutoff": result["evidence_cutoff"],
                "packet_sha256": result["packet_sha256"],
                "artifact_index": result["artifact_index"],
                "budget": {
                    "grok": result["budget"]["grok"],
                    "composer": result["budget"]["composer"],
                    "rebuttals": result["budget"]["rebuttals"],
                    "ceilings": result["budget"]["ceilings"],
                },
                "conflicts": len(result["conflict_map"]["conflicts"]),
                "rebuttals": sorted(result["rebuttals"]),
                "status": result["handoff"]["status"],
            }
        )
        if result["handoff"]["status"] != HANDOFF_MARKER:
            return 2
        return 0
    except ParentDispatchRequired as exc:
        _print(exc.as_dict())
        return 4
    except LiveRunBlocked as exc:
        print(f"LIVE RUN BLOCKED: {exc}", file=sys.stderr)
        return 3
    except TraderRoomError as exc:
        print(f"TRADER ROOM ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
