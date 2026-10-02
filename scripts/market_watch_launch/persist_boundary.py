"""Explicit git persistence boundaries for Market Watch freeze and finalization commits."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from scripts.country_registry import history_files
from scripts.overnight.constants import ROOT

ACP_ALLOWLIST: tuple[str, ...] = (
    "data/market_watch_launches",
    "data/overnight/runs",
    "data/overnight/books",
    "data/overnight/latest.json",
    "data/pm",
    "data/trading",
)

STUB_ALLOWLIST: tuple[str, ...] = ("data/market_watch_launches",)

# Stage 07 writes the launch record, assembled overnight dataset, PM packets,
# trading memory touched by assembly, and the canonical temperature history and
# scores promoted from the accepted lineage. score_paths.json is the derived
# chart the Pages temperature gate compares against those histories.
def finalization_persist_allowlist() -> tuple[str, ...]:
    histories = tuple(
        f"data/temperature_history/{filename}" for filename in history_files().values()
    )
    return (
        "data/market_watch_launches",
        "data/overnight",
        "data/pm",
        "data/trading",
        "data/temperature_scores.json",
        *histories,
        "data/temperature_history/score_paths.json",
    )


def freeze_persist_allowlist(provider: str) -> tuple[str, ...]:
    if provider == "acp":
        return ACP_ALLOWLIST
    return STUB_ALLOWLIST


def _normalize_rel(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def path_allowed(rel_path: str, allowlist: tuple[str, ...]) -> bool:
    rel = _normalize_rel(rel_path).rstrip("/")
    for entry in allowlist:
        entry_norm = entry.rstrip("/")
        if rel == entry_norm:
            return True
        if rel.startswith(entry_norm + "/"):
            return True
    return False


def expand_repo_path(repo_root: Path, rel_path: str) -> list[str]:
    """Expand git directory porcelain entries to concrete file paths for checks."""
    rel = _normalize_rel(rel_path).rstrip("/")
    full = repo_root / rel
    if full.is_dir():
        files = sorted(
            p.relative_to(repo_root).as_posix() for p in full.rglob("*") if p.is_file()
        )
        return files if files else [rel]
    return [rel]


def _run_git(args: list[str], *, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        detail = stderr or stdout or f"git {' '.join(args)} failed"
        raise RuntimeError(detail)
    return result.stdout


def porcelain_paths(repo_root: Path) -> list[str]:
    out = _run_git(["status", "--porcelain"], cwd=repo_root)
    paths: list[str] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        if line.startswith("??"):
            for expanded in expand_repo_path(repo_root, line[3:].strip()):
                paths.append(expanded)
            continue
        body = line[3:].strip()
        if " -> " in body:
            old, new = body.split(" -> ", 1)
            for raw in (old.strip(), new.strip()):
                for expanded in expand_repo_path(repo_root, raw):
                    paths.append(expanded)
        else:
            for expanded in expand_repo_path(repo_root, body):
                paths.append(expanded)
    return paths


def unexpected_paths(paths: list[str], allowlist: tuple[str, ...]) -> list[str]:
    bad = sorted({p for p in paths if not path_allowed(p, allowlist)})
    return bad


def has_unstaged_or_untracked(repo_root: Path) -> list[str]:
    out = _run_git(["status", "--porcelain"], cwd=repo_root)
    remaining: list[str] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        if line.startswith("??"):
            remaining.append(_normalize_rel(line[3:].strip()))
            continue
        x, y = line[0], line[1]
        body = line[3:].strip()
        if " -> " in body:
            body = body.split(" -> ", 1)[1].strip()
        if y != " ":
            remaining.append(_normalize_rel(body))
    return sorted(set(remaining))


def stage_allowlisted_paths(allowlist: tuple[str, ...], *, repo_root: Path) -> bool:
    for entry in allowlist:
        target = repo_root / entry
        if target.exists():
            _run_git(["add", "--", entry], cwd=repo_root)
    return (
        subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=repo_root,
            check=False,
        ).returncode
        != 0
    )


def refresh_promoted_score_paths(repo_root: Path) -> bool:
    """Rewrite score_paths.json from the canonical histories already on disk.

    Promotion copies staged histories and scores. The Pages temperature gate
    recomputes score paths from those histories and rejects a stale chart.
    Calibration is read and not rewritten. Returns True when the file changes.
    """
    from scripts.temperature_level import build_paths, load_calibration, load_history

    root = Path(repo_root)
    history_dir = root / "data" / "temperature_history"
    calibration_path = root / "data" / "temperature_calibration.json"
    paths_path = history_dir / "score_paths.json"
    calibration = load_calibration(calibration_path)
    histories = load_history(history_dir)
    document = build_paths(calibration, histories)
    text = json.dumps(document, indent=2) + "\n"
    if paths_path.is_file() and paths_path.read_text(encoding="utf-8") == text:
        return False
    paths_path.parent.mkdir(parents=True, exist_ok=True)
    paths_path.write_text(text, encoding="utf-8")
    return True


def _stage_boundary(allowlist: tuple[str, ...], *, repo_root: Path, label: str) -> int:
    before = porcelain_paths(repo_root)
    bad = unexpected_paths(before, allowlist)
    if bad:
        print(f"unexpected paths outside {label} persistence boundary:", file=sys.stderr)
        for path in bad:
            print(path, file=sys.stderr)
        return 1

    try:
        has_staged = stage_allowlisted_paths(allowlist, repo_root=repo_root)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if not has_staged:
        print(f"no {label} artifacts to commit")
        return 0

    leftover = has_unstaged_or_untracked(repo_root)
    if leftover:
        print("unstaged or untracked paths remain after staging:", file=sys.stderr)
        for path in leftover:
            print(path, file=sys.stderr)
        return 1
    return 0


def stage_freeze_artifacts(provider: str, *, repo_root: Path | None = None) -> int:
    root = Path(repo_root or ROOT)
    allowlist = freeze_persist_allowlist(provider)
    return _stage_boundary(allowlist, repo_root=root, label="freeze")


def stage_finalization_artifacts(
    *,
    repo_root: Path | None = None,
    refresh_score_paths: bool = False,
) -> int:
    root = Path(repo_root or ROOT)
    if refresh_score_paths:
        refresh_promoted_score_paths(root)
    return _stage_boundary(finalization_persist_allowlist(), repo_root=root, label="finalization")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Stage Market Watch freeze or finalization artifacts within an allowlist."
    )
    parser.add_argument(
        "--boundary",
        choices=("freeze", "finalization"),
        default="freeze",
        help="Persistence boundary to enforce (default: freeze).",
    )
    parser.add_argument("--provider", default=None, help="Launch provider (required for freeze).")
    parser.add_argument(
        "--refresh-score-paths",
        action="store_true",
        help="Rewrite data/temperature_history/score_paths.json from canonical histories before staging.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root (default: overnight ROOT).",
    )
    args = parser.parse_args(argv)
    if args.boundary == "freeze":
        if args.refresh_score_paths:
            print("--refresh-score-paths is only valid for the finalization boundary", file=sys.stderr)
            return 1
        if not args.provider:
            print("--provider is required for the freeze boundary", file=sys.stderr)
            return 1
        return stage_freeze_artifacts(args.provider, repo_root=args.repo_root)
    return stage_finalization_artifacts(
        repo_root=args.repo_root,
        refresh_score_paths=args.refresh_score_paths,
    )


if __name__ == "__main__":
    raise SystemExit(main())
