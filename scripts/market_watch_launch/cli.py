"""CLI for manual Market Watch launch orchestration."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts.market_watch_launch.graph import run_launch, run_stage


def _build_launch_request(args: argparse.Namespace) -> dict:
    request: dict = {
        "rerun": bool(args.rerun),
        "mode": args.mode,
        "provider": args.provider,
        "source": args.source,
        "actor_type": args.actor_type,
        "actor": args.actor,
        "publish_production": bool(args.publish_production),
    }
    if args.session_date:
        request["session_date"] = args.session_date
    if args.as_of:
        request["as_of"] = args.as_of
    if args.issue_number is not None:
        request["issue_number"] = args.issue_number
    if args.issue_title:
        request["issue_title"] = args.issue_title
    if args.issue_url:
        request["issue_url"] = args.issue_url
    if args.market_state:
        request["market_state_path"] = args.market_state
    return request


def cmd_launch(args: argparse.Namespace) -> int:
    when = None
    if args.as_of:
        from scripts.overnight.clock import parse_iso

        when = parse_iso(args.as_of)
    result = run_launch(
        _build_launch_request(args),
        root=Path(args.root),
        state_root=Path(args.state_root),
        when=when,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    status = result["status"]
    if status == "failed":
        return 1
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    from scripts.market_watch_launch.state import LaunchStateStore

    store = LaunchStateStore(Path(args.state_root))
    launch = store.load_launch(args.launch_id)
    print(json.dumps(launch, indent=2, sort_keys=True))
    return 0


def cmd_stage(args: argparse.Namespace) -> int:
    result = run_stage(
        args.launch_id,
        args.name,
        root=Path(args.root),
        state_root=Path(args.state_root),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["status"] == "failed":
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="market_watch_launch")
    parser.add_argument("--root", default=".", help="repository root")
    parser.add_argument("--state-root", default=".", help="durable state root")

    sub = parser.add_subparsers(dest="command", required=True)

    launch_p = sub.add_parser("launch", help="start or resume a launch")
    launch_p.add_argument("--session-date", dest="session_date")
    launch_p.add_argument("--rerun", action="store_true")
    launch_p.add_argument("--mode", choices=("fixture", "live"), default="live")
    launch_p.add_argument("--provider", choices=("stub", "acp"), default="acp")
    launch_p.add_argument("--as-of")
    launch_p.add_argument("--source", choices=("workflow_dispatch", "github_issue"), default="workflow_dispatch")
    launch_p.add_argument("--actor-type", dest="actor_type", default="User")
    launch_p.add_argument("--actor")
    launch_p.add_argument("--issue-number", dest="issue_number", type=int)
    launch_p.add_argument("--issue-title", dest="issue_title")
    launch_p.add_argument("--issue-url", dest="issue_url")
    launch_p.add_argument("--market-state", dest="market_state")
    launch_p.add_argument("--publish-production", dest="publish_production", action="store_true")
    launch_p.set_defaults(func=cmd_launch)

    show_p = sub.add_parser("show", help="show a launch record")
    show_p.add_argument("--launch-id", required=True)
    show_p.set_defaults(func=cmd_show)

    stage_p = sub.add_parser("stage", help="run one resumable stage")
    stage_p.add_argument("--launch-id", required=True)
    stage_p.add_argument("--name", required=True)
    stage_p.set_defaults(func=cmd_stage)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
