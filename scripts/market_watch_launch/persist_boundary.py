"""Explicit git persistence boundary for Market Watch freeze commits."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

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


def stage_freeze_artifacts(provider: str, *, repo_root: Path | None = None) -> int:
    root = Path(repo_root or ROOT)
    allowlist = freeze_persist_allowlist(provider)

    before = porcelain_paths(root)
    bad = unexpected_paths(before, allowlist)
    if bad:
        print("unexpected paths outside freeze persistence boundary:", file=sys.stderr)
        for path in bad:
            print(path, file=sys.stderr)
        return 1

    try:
        has_staged = stage_allowlisted_paths(allowlist, repo_root=root)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if not has_staged:
        print("no launch artifacts to commit")
        return 0

    leftover = has_unstaged_or_untracked(root)
    if leftover:
        print("unstaged or untracked paths remain after staging:", file=sys.stderr)
        for path in leftover:
            print(path, file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage Market Watch freeze artifacts within an allowlist.")
    parser.add_argument("--provider", required=True, help="Launch provider (acp or stub).")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root (default: overnight ROOT).",
    )
    args = parser.parse_args(argv)
    return stage_freeze_artifacts(args.provider, repo_root=args.repo_root)


if __name__ == "__main__":
    raise SystemExit(main())
