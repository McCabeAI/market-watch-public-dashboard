"""Record a successful explicit Pages deploy into canonical launch state.

This is the durable handoff for a ``deploy-pages.yml`` ``workflow_dispatch``
that already succeeded on ``main``. It reuses ``publication_evidence_proven``
and ``reconcile_published_pages`` and does not rerun traders, PMs, learning,
ingestion, market evidence, score calibration, books, or P&L.

A second recovery of the same proven deploy is a no-op. The commit set is
only that launch's ``launch.json``, ``artifacts/08_pages.json``, and
``data/market_watch_launches/index.json``.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from scripts.market_watch_launch.contract import LAUNCH_ID_RE
from scripts.market_watch_launch.pages import (
    PAGES_RECONCILED,
    REQUIRED_PRIOR_STAGES,
    publication_evidence_proven,
    reconcile_published_pages,
)
from scripts.market_watch_launch.persist_boundary import (
    has_unstaged_or_untracked,
    porcelain_paths,
    stage_allowlisted_paths,
    unexpected_paths,
)
from scripts.market_watch_launch.state import LaunchStateStore

DEPLOY_WORKFLOW = "deploy-pages.yml"
DEPLOY_WORKFLOW_PATH = ".github/workflows/deploy-pages.yml"
DEFAULT_REPOSITORY = "McCabeAI/market-watch-public-dashboard"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_RUN_ID_RE = re.compile(r"^[0-9]{1,20}$")
_PACKET_STAGES = ("04_freeze", "06_acceptance", "07_finalize")
_REVIEW_STAGES = ("04_freeze", "06_acceptance", "07_finalize")


def pages_reconcile_allowlist(launch_id: str) -> tuple[str, ...]:
    _validate_launch_id(launch_id)
    base = f"data/market_watch_launches/{launch_id}"
    return (
        f"{base}/launch.json",
        f"{base}/artifacts/08_pages.json",
        "data/market_watch_launches/index.json",
    )


def _fail(message: str) -> None:
    raise SystemExit(message)


def _validate_launch_id(launch_id: str) -> None:
    if not LAUNCH_ID_RE.fullmatch(launch_id or ""):
        _fail("mismatched launch_id")


def _validate_run_id(run_id: str) -> str:
    text = str(run_id or "").strip()
    if not _RUN_ID_RE.fullmatch(text):
        _fail("workflow run id does not match the recovery target")
    return text


def _git(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )


def _stage_details(launch: dict[str, Any], stage: str) -> dict[str, Any]:
    details = ((launch.get("stages") or {}).get(stage) or {}).get("details") or {}
    return details if isinstance(details, dict) else {}


def _identity_values(launch: dict[str, Any], field: str, stages: tuple[str, ...]) -> set[str]:
    values: set[str] = set()
    top = launch.get(field)
    if isinstance(top, str) and top:
        values.add(top)
    for stage in stages:
        value = _stage_details(launch, stage).get(field)
        if isinstance(value, str) and value:
            values.add(value)
    return values


def _require_same_identity(
    current: dict[str, Any],
    finalized: dict[str, Any],
    *,
    launch_id: str,
) -> None:
    if current.get("launch_id") != launch_id or finalized.get("launch_id") != launch_id:
        _fail("mismatched launch_id")
    current_reviews = _identity_values(current, "review_id", _REVIEW_STAGES)
    final_reviews = _identity_values(finalized, "review_id", _REVIEW_STAGES)
    if len(current_reviews) != 1 or current_reviews != final_reviews:
        _fail("mismatched review_id")
    current_packets = _identity_values(current, "packet_sha256", _PACKET_STAGES)
    final_packets = _identity_values(finalized, "packet_sha256", _PACKET_STAGES)
    current_base = current.get("base_packet_sha256")
    final_base = finalized.get("base_packet_sha256")
    if not isinstance(current_base, str) or not current_base:
        _fail("mismatched packet SHA")
    if current_base != final_base:
        _fail("mismatched packet SHA")
    if current_packets != final_packets or current_base not in current_packets:
        _fail("mismatched packet SHA")


def _require_prior_stages(current: dict[str, Any], finalized: dict[str, Any]) -> None:
    current_stages = current.get("stages") or {}
    final_stages = finalized.get("stages") or {}
    for name in REQUIRED_PRIOR_STAGES:
        if (current_stages.get(name) or {}).get("status") != "succeeded":
            _fail(f"stages 00-07 not all succeeded: {name}")
        if (final_stages.get(name) or {}).get("status") != "succeeded":
            _fail(f"stages 00-07 not all succeeded: {name}")
    for launch in (current, finalized):
        handoff = (launch.get("stages") or {}).get("05_acp_handoff") or {}
        if handoff.get("reason") != "provider_output_accepted":
            _fail("pages publication not proven")
        publication = _stage_details(launch, "07_finalize").get("publication") or {}
        if not isinstance(publication, dict) or publication.get("may_publish") is not True:
            _fail("pages publication not proven")
        if (launch.get("request") or {}).get("provider") != "acp":
            _fail("pages publication not proven")


def _repo_full_name(payload: dict[str, Any], key: str) -> str | None:
    repo = payload.get(key)
    if repo is None:
        return None
    if not isinstance(repo, dict):
        _fail("workflow run is not bound to the target repository")
    name = repo.get("full_name")
    if not isinstance(name, str) or not name:
        _fail("workflow run is not bound to the target repository")
    return name


def normalize_actions_run(
    run: dict[str, Any],
    *,
    run_id: str,
    repository: str,
) -> dict[str, str]:
    """Fail closed unless ``run`` is a successful main ``workflow_dispatch`` of deploy-pages."""
    expected_run = _validate_run_id(run_id)
    if not isinstance(run, dict):
        _fail("non-success conclusion")
    if str(run.get("id") or "") != expected_run:
        _fail("workflow run id does not match the recovery target")
    if run.get("path") != DEPLOY_WORKFLOW_PATH:
        _fail("workflow is not deploy-pages.yml")
    if run.get("event") != "workflow_dispatch":
        _fail("non-workflow_dispatch event")
    if run.get("head_branch") != "main":
        _fail("non-main ref")
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        _fail("non-success conclusion")
    repo_name = _repo_full_name(run, "repository")
    if repo_name != repository:
        _fail("workflow run is not bound to the target repository")
    head_repo = _repo_full_name(run, "head_repository")
    if head_repo is not None and head_repo != repository:
        _fail("workflow run is not bound to the target repository")
    head_sha = str(run.get("head_sha") or "").strip().lower()
    if not _SHA_RE.fullmatch(head_sha):
        _fail("mismatched deploy head SHA")
    run_url = str(run.get("html_url") or "")
    marker = f"/actions/runs/{expected_run}"
    if not run_url.startswith("https://github.com/") or marker not in run_url:
        _fail("workflow run id does not match the recovery target")
    tail = run_url.split(marker, 1)[1]
    if tail[:1].isdigit():
        _fail("workflow run id does not match the recovery target")
    return {
        "workflow": DEPLOY_WORKFLOW,
        "event": "workflow_dispatch",
        "ref": "main",
        "conclusion": "success",
        "head_sha": head_sha,
        "run_url": run_url,
        "run_id": expected_run,
    }


def _require_deploy_commit(repo_root: Path, head_sha: str) -> None:
    if not _SHA_RE.fullmatch(head_sha):
        _fail("mismatched deploy head SHA")
    kind = _git(repo_root, ["cat-file", "-t", head_sha])
    if kind.returncode != 0 or kind.stdout.strip() != "commit":
        _fail("mismatched deploy head SHA")
    ancestor = _git(repo_root, ["merge-base", "--is-ancestor", head_sha, "HEAD"])
    if ancestor.returncode != 0:
        _fail("mismatched deploy head SHA")


def load_launch_at_commit(repo_root: Path, head_sha: str, launch_id: str) -> dict[str, Any]:
    """Load the launch record from the deploy commit itself."""
    _validate_launch_id(launch_id)
    _require_deploy_commit(repo_root, head_sha)
    spec = f"{head_sha}:data/market_watch_launches/{launch_id}/launch.json"
    shown = _git(repo_root, ["show", spec])
    if shown.returncode != 0 or not shown.stdout:
        _fail("mismatched deploy head SHA")
    try:
        payload = json.loads(shown.stdout)
    except json.JSONDecodeError:
        _fail("mismatched deploy head SHA")
    if not isinstance(payload, dict):
        _fail("mismatched deploy head SHA")
    if payload.get("launch_id") != launch_id:
        _fail("mismatched launch_id")
    return payload


def _publication_evidence_row(launch: dict[str, Any]) -> dict[str, Any]:
    stage = (launch.get("stages") or {}).get("08_pages") or {}
    details = stage.get("details") or {}
    evidence = details.get("publication_evidence") or {}
    return evidence if isinstance(evidence, dict) else {}


def matching_reconciliation(launch: dict[str, Any], normalized: dict[str, str]) -> bool:
    """True when this launch was already terminalized from the same proven deploy."""
    stage = (launch.get("stages") or {}).get("08_pages") or {}
    details = stage.get("details") or {}
    evidence = _publication_evidence_row(launch)
    return (
        launch.get("status") == "succeeded"
        and stage.get("status") == "succeeded"
        and stage.get("reason") == PAGES_RECONCILED
        and details.get("reconciled") is True
        and details.get("production_published") is True
        and details.get("executed") is True
        and details.get("dry_run") is False
        and evidence.get("workflow") == normalized["workflow"]
        and evidence.get("event") == normalized["event"]
        and evidence.get("ref") == normalized["ref"]
        and evidence.get("conclusion") == normalized["conclusion"]
        and evidence.get("head_sha") == normalized["head_sha"]
        and evidence.get("run_url") == normalized["run_url"]
        and evidence.get("launch_id") == launch.get("launch_id")
    )


def assess_published_pages(
    *,
    repo_root: Path,
    launch_id: str,
    run: dict[str, Any],
    run_id: str,
    current_launch: dict[str, Any],
    repository: str = DEFAULT_REPOSITORY,
) -> dict[str, Any]:
    """Read-only proof that ``run`` binds ``current_launch`` to the deploy commit.

    Returns a decision. Raises ``SystemExit`` when the bind is not proven.
    Does not write launch state.
    """
    _validate_launch_id(launch_id)
    if not isinstance(current_launch, dict):
        _fail("mismatched launch_id")
    normalized = normalize_actions_run(run, run_id=run_id, repository=repository)
    finalized = load_launch_at_commit(repo_root, normalized["head_sha"], launch_id)
    _require_same_identity(current_launch, finalized, launch_id=launch_id)
    _require_prior_stages(current_launch, finalized)
    if (finalized.get("stages") or {}).get("08_pages", {}).get("status") != "pending":
        _fail("pages publication not proven")
    already = matching_reconciliation(current_launch, normalized)
    current_pages = (current_launch.get("stages") or {}).get("08_pages") or {}
    if not already and current_pages.get("status") != "pending":
        _fail("launch is terminal without matching pages publication evidence")
    evidence = {
        "workflow": normalized["workflow"],
        "event": normalized["event"],
        "ref": normalized["ref"],
        "conclusion": normalized["conclusion"],
        "launch_id": launch_id,
        "head_sha": normalized["head_sha"],
        "run_url": normalized["run_url"],
        "finalized_launch": json.loads(json.dumps(finalized)),
    }
    if not already and not publication_evidence_proven(current_launch, evidence):
        _fail("pages publication not proven")
    return {
        "launch_id": launch_id,
        "run_id": normalized["run_id"],
        "head_sha": normalized["head_sha"],
        "run_url": normalized["run_url"],
        "already_reconciled": already,
        "changed": False,
        "status": "succeeded",
        "reason": "already_reconciled" if already else PAGES_RECONCILED,
        "evidence": evidence,
    }


def apply_published_pages(
    *,
    repo_root: Path,
    state_root: Path,
    launch_id: str,
    run: dict[str, Any],
    run_id: str,
    repository: str = DEFAULT_REPOSITORY,
) -> dict[str, Any]:
    """Reconcile ``launch_id`` from ``run``, or no-op when that deploy is already recorded."""
    store = LaunchStateStore(state_root)
    try:
        current = store.load_launch(launch_id)
    except FileNotFoundError:
        _fail("launch record is missing")
    decision = assess_published_pages(
        repo_root=repo_root,
        launch_id=launch_id,
        run=run,
        run_id=run_id,
        current_launch=current,
        repository=repository,
    )
    if decision["already_reconciled"]:
        decision.pop("evidence", None)
        return decision
    evidence = decision.pop("evidence")
    receipt = reconcile_published_pages(current, evidence, store=store)
    if receipt.get("status") != "succeeded" or receipt.get("reason") != PAGES_RECONCILED:
        _fail("pages publication not proven")
    decision["changed"] = True
    decision["already_reconciled"] = False
    decision["reason"] = PAGES_RECONCILED
    return decision


def load_launch_from_ref(repo_root: Path, ref: str, launch_id: str) -> dict[str, Any]:
    _validate_launch_id(launch_id)
    if not ref or ref.startswith("-") or not re.fullmatch(r"[A-Za-z0-9_./-]+", ref):
        _fail("mismatched deploy head SHA")
    spec = f"{ref}:data/market_watch_launches/{launch_id}/launch.json"
    shown = _git(repo_root, ["show", spec])
    if shown.returncode != 0 or not shown.stdout:
        _fail("launch record is missing")
    try:
        payload = json.loads(shown.stdout)
    except json.JSONDecodeError:
        _fail("launch record is missing")
    if not isinstance(payload, dict) or payload.get("launch_id") != launch_id:
        _fail("mismatched launch_id")
    return payload


def assert_reconciled_at_ref(
    *,
    repo_root: Path,
    launch_id: str,
    run: dict[str, Any],
    run_id: str,
    ref: str,
    repository: str = DEFAULT_REPOSITORY,
) -> dict[str, Any]:
    """Fail unless the launch at ``ref`` is already reconciled to ``run``."""
    current = load_launch_from_ref(repo_root, ref, launch_id)
    decision = assess_published_pages(
        repo_root=repo_root,
        launch_id=launch_id,
        run=run,
        run_id=run_id,
        current_launch=current,
        repository=repository,
    )
    if not decision["already_reconciled"]:
        _fail("pages publication not proven")
    decision.pop("evidence", None)
    return decision


def preflight_worktree(
    repo_root: Path,
    launch_id: str,
    *,
    remote: str = "origin",
    branch: str = "main",
) -> None:
    """Refuse a diverged checkout or any dirty path outside this launch's state files."""
    _validate_launch_id(launch_id)
    if (
        not remote
        or remote.startswith("-")
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", remote)
        or not branch
        or branch.startswith("-")
        or not re.fullmatch(r"[A-Za-z0-9_./-]+", branch)
    ):
        _fail("HEAD is not the requested branch")
    head = _git(repo_root, ["rev-parse", "HEAD"])
    upstream = _git(repo_root, ["rev-parse", f"{remote}/{branch}"])
    if head.returncode != 0 or upstream.returncode != 0:
        _fail(f"HEAD is not {remote}/{branch}")
    if head.stdout.strip() != upstream.stdout.strip():
        _fail(f"HEAD is not {remote}/{branch}")
    allowlist = pages_reconcile_allowlist(launch_id)
    bad = unexpected_paths(porcelain_paths(repo_root), allowlist)
    if bad:
        print("unexpected paths outside pages reconciliation persistence boundary:", file=sys.stderr)
        for path in bad:
            print(path, file=sys.stderr)
        _fail("unexpected dirty paths")


def stage_pages_reconciliation(launch_id: str, *, repo_root: Path) -> int:
    """Stage only this launch's reconciliation files. Nonzero when anything else is dirty."""
    allowlist = pages_reconcile_allowlist(launch_id)
    bad = unexpected_paths(porcelain_paths(repo_root), allowlist)
    if bad:
        print("unexpected paths outside pages reconciliation persistence boundary:", file=sys.stderr)
        for path in bad:
            print(path, file=sys.stderr)
        return 1
    try:
        stage_allowlisted_paths(allowlist, repo_root=repo_root)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    leftover = has_unstaged_or_untracked(repo_root)
    if leftover:
        print("unstaged or untracked paths remain after staging:", file=sys.stderr)
        for path in leftover:
            print(path, file=sys.stderr)
        return 1
    staged = _git(repo_root, ["diff", "--cached", "--name-only"])
    if staged.returncode != 0:
        print(staged.stderr.strip() or "git diff --cached failed", file=sys.stderr)
        return 1
    names = [line.strip() for line in staged.stdout.splitlines() if line.strip()]
    extra = unexpected_paths(names, allowlist)
    if extra:
        print("staged paths outside pages reconciliation persistence boundary:", file=sys.stderr)
        for path in extra:
            print(path, file=sys.stderr)
        return 1
    return 0


def _load_run_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail(f"workflow run evidence is not valid JSON: {exc}")
    if not isinstance(payload, dict):
        _fail("non-success conclusion")
    return payload


def _public_decision(decision: dict[str, Any]) -> dict[str, Any]:
    public = dict(decision)
    public.pop("evidence", None)
    return public


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile a successful deploy-pages.yml workflow_dispatch into launch state."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--launch-id", required=True)
    shared.add_argument("--repo-root", type=Path, default=Path.cwd())

    preflight_p = sub.add_parser("preflight", parents=[shared])
    preflight_p.add_argument("--remote", default="origin")
    preflight_p.add_argument("--branch", default="main")

    run_shared = argparse.ArgumentParser(add_help=False)
    run_shared.add_argument("--run-id", required=True)
    run_shared.add_argument("--run-json", type=Path, required=True)
    run_shared.add_argument("--repository", default=DEFAULT_REPOSITORY)

    apply_p = sub.add_parser("apply", parents=[shared, run_shared])
    apply_p.add_argument("--state-root", type=Path, default=None)
    apply_p.add_argument("--decision-out", type=Path, default=None)

    sub.add_parser("stage", parents=[shared])

    assert_p = sub.add_parser("assert-reconciled", parents=[shared, run_shared])
    assert_p.add_argument("--ref", required=True)

    args = parser.parse_args(argv)
    root = Path(args.repo_root)
    try:
        if args.command == "preflight":
            preflight_worktree(root, args.launch_id, remote=args.remote, branch=args.branch)
            return 0
        if args.command == "stage":
            return stage_pages_reconciliation(args.launch_id, repo_root=root)
        run = _load_run_json(Path(args.run_json))
        if args.command == "apply":
            state_root = Path(args.state_root) if args.state_root is not None else root
            decision = apply_published_pages(
                repo_root=root,
                state_root=state_root,
                launch_id=args.launch_id,
                run=run,
                run_id=args.run_id,
                repository=args.repository,
            )
            text = json.dumps(_public_decision(decision), indent=2, sort_keys=True) + "\n"
            if args.decision_out is not None:
                Path(args.decision_out).write_text(text, encoding="utf-8")
            sys.stdout.write(text)
            return 0
        decision = assert_reconciled_at_ref(
            repo_root=root,
            launch_id=args.launch_id,
            run=run,
            run_id=args.run_id,
            ref=args.ref,
            repository=args.repository,
        )
        sys.stdout.write(json.dumps(_public_decision(decision), indent=2, sort_keys=True) + "\n")
        return 0
    except SystemExit as exc:
        message = exc.code
        if isinstance(message, str) and message:
            print(message, file=sys.stderr)
            return 1
        if message in (None, 0):
            return 0
        if isinstance(message, int):
            return message
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
