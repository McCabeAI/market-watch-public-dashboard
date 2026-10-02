"""Guards for replaying an already-accepted launch through Stage 07.

The accepted scheduled_output.json is an immutable input. This module checks
identity and whether finalization already reached the remote branch. It does
not call traders, PMs, learning models, or a provider.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def inbox_scheduled_output(repo_root: Path, run_id: str) -> Path:
    return repo_root / "data" / "overnight" / "inbox" / run_id / "scheduled_output.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def launch_stages_finalized(launch: dict[str, Any]) -> bool:
    stages = launch.get("stages") or {}
    acceptance = stages.get("06_acceptance") or {}
    finalize = stages.get("07_finalize") or {}
    if acceptance.get("status") != "succeeded" or finalize.get("status") != "succeeded":
        return False
    publication = (finalize.get("details") or {}).get("publication") or {}
    return publication.get("may_publish") is True


def _git_show(repo_root: Path, spec: str) -> str | None:
    result = subprocess.run(
        ["git", "show", spec],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def _load_json_blob(text: str, spec: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{spec} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"{spec} must be a JSON object")
    return payload


def load_scheduled_output(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"accepted scheduled output is missing: {path}")
    return _load_json_blob(path.read_text(encoding="utf-8"), str(path))


def assert_accepted_inputs(
    repo_root: Path,
    *,
    launch_id: str,
    run_id: str,
    provider_payload_path: Path | None = None,
) -> str:
    """Validate the immutable accepted output. Return its sha256 hex digest."""
    inbox = inbox_scheduled_output(repo_root, run_id)
    payload = load_scheduled_output(inbox)
    if payload.get("launch_id") != launch_id:
        raise SystemExit(
            f"scheduled output launch_id {payload.get('launch_id')!r} does not match {launch_id}"
        )
    if payload.get("overnight_run_id") != run_id:
        raise SystemExit(
            f"scheduled output overnight_run_id {payload.get('overnight_run_id')!r} does not match {run_id}"
        )
    review_id = payload.get("review_id")
    packet_sha = payload.get("base_packet_sha256")
    if not isinstance(review_id, str) or not review_id:
        raise SystemExit("scheduled output is missing review_id")
    if not isinstance(packet_sha, str) or not packet_sha:
        raise SystemExit("scheduled output is missing base_packet_sha256")

    launch_path = repo_root / "data" / "market_watch_launches" / launch_id / "launch.json"
    if not launch_path.is_file():
        raise SystemExit(f"launch record is missing: {launch_path}")
    launch = _load_json_blob(launch_path.read_text(encoding="utf-8"), str(launch_path))
    if launch.get("launch_id") != launch_id:
        raise SystemExit("launch record launch_id does not match the recovery target")
    if launch.get("overnight_run_id") != run_id:
        raise SystemExit("launch record overnight_run_id does not match the recovery target")
    freeze_stage = (launch.get("stages") or {}).get("04_freeze") or {}
    freeze = freeze_stage.get("details") or {}
    if freeze_stage.get("status") != "succeeded":
        raise SystemExit("bound launch freeze did not succeed")
    if freeze.get("review_id") != review_id or launch.get("review_id") != review_id:
        raise SystemExit("scheduled output review_id does not match the frozen launch")
    if freeze.get("packet_sha256") != packet_sha or launch.get("base_packet_sha256") != packet_sha:
        raise SystemExit("scheduled output packet SHA does not match the frozen launch")
    request = launch.get("request") or {}
    if request.get("provider") != "acp" or request.get("mode") != "live":
        raise SystemExit("recovery requires the accepted live ACP launch")
    if request.get("publish_production") is not True:
        raise SystemExit("bound launch did not authorize production publication")

    review_path = (
        repo_root / "data" / "overnight" / "runs" / run_id / "reviews" / review_id / "review.json"
    )
    if not review_path.is_file():
        raise SystemExit(f"accepted review is missing: {review_path}")
    review = _load_json_blob(review_path.read_text(encoding="utf-8"), str(review_path))
    if review.get("status") != "accepted":
        raise SystemExit(f"review {review_id} is not accepted")
    if review.get("packet_sha256") != packet_sha:
        raise SystemExit("accepted review packet SHA does not match the scheduled output")

    digest = sha256_file(inbox)
    if provider_payload_path is not None:
        provider_path = Path(provider_payload_path)
        if sha256_file(provider_path) != digest:
            raise SystemExit("provider payload does not match the accepted scheduled_output on disk")
        provider_payload = load_scheduled_output(provider_path)
        if provider_payload.get("launch_id") != launch_id or provider_payload.get("overnight_run_id") != run_id:
            raise SystemExit("provider payload identity does not match the recovery target")
    return digest


def remote_recovery_complete(
    repo_root: Path,
    *,
    launch_id: str,
    run_id: str,
    remote: str = "origin",
    branch: str = "main",
) -> bool:
    """True when this launch's finalization commit is already on the remote branch."""
    prefix = f"{remote}/{branch}"
    launch_blob = _git_show(repo_root, f"{prefix}:data/market_watch_launches/{launch_id}/launch.json")
    if launch_blob is None:
        return False
    launch = _load_json_blob(launch_blob, f"{prefix} launch.json")
    if not launch_stages_finalized(launch):
        return False
    latest_blob = _git_show(repo_root, f"{prefix}:data/overnight/latest.json")
    if latest_blob is None:
        return False
    latest = _load_json_blob(latest_blob, f"{prefix} latest.json")
    if latest.get("overnight_run_id") != run_id:
        return False
    dataset = latest.get("assembled_dataset")
    if not isinstance(dataset, str) or not dataset:
        return False
    if _git_show(repo_root, f"{prefix}:{dataset}") is None:
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check an accepted-launch finalization recovery.")
    parser.add_argument("command", choices=("preflight", "check-finalized", "assert-published"))
    parser.add_argument("--launch-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--provider-payload", type=Path, default=None)
    parser.add_argument("--expect-sha256", default="")
    args = parser.parse_args(argv)
    root = Path(args.repo_root)
    if args.command == "preflight":
        digest = assert_accepted_inputs(
            root,
            launch_id=args.launch_id,
            run_id=args.run_id,
            provider_payload_path=args.provider_payload,
        )
        print(digest)
        return 0
    complete = remote_recovery_complete(
        root,
        launch_id=args.launch_id,
        run_id=args.run_id,
        remote=args.remote,
        branch=args.branch,
    )
    if args.command == "check-finalized":
        return 0 if complete else 1
    if not complete:
        print(
            f"launch {args.launch_id} is not finalized for {args.run_id} on {args.remote}/{args.branch}",
            file=sys.stderr,
        )
        return 1
    digest = assert_accepted_inputs(
        root,
        launch_id=args.launch_id,
        run_id=args.run_id,
        provider_payload_path=args.provider_payload,
    )
    if args.expect_sha256 and digest != args.expect_sha256:
        print("accepted scheduled_output.json changed during recovery", file=sys.stderr)
        return 1
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
