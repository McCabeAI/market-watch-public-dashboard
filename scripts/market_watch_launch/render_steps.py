"""One runner for dashboard render steps, shared by the research and final builds.

A ``hard`` step failure stops the build: these steps carry frozen data,
numeric marks, book identity or edition labels. An ``optional`` step failure
restores ``index.html`` to its state before the step, applies the named
truthful fallback from ``render_fallbacks`` (for example an "unavailable"
placeholder that removes stale base-page content), records one render
diagnostic, and lets the build continue.

If an optional step needs a fallback and that fallback cannot be applied, the
step is treated as hard: a page that might show stale content as current is
not published.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from scripts.market_watch_launch.publication_issues import record_diagnostic

HARD = "hard"
OPTIONAL = "optional"


class StepFailed(RuntimeError):
    def __init__(self, label: str, detail: str) -> None:
        super().__init__(f"{label}: {detail}")
        self.label = label
        self.detail = detail


@dataclass(frozen=True)
class StepResult:
    label: str
    ok: bool
    fallback: str | None = None
    detail: str = ""


def _tail(proc: subprocess.CompletedProcess[str]) -> str:
    return (proc.stderr or proc.stdout or "").strip()[-2000:]


def run_step(
    html_path: Path,
    argv: Sequence[str],
    *,
    label: str,
    policy: str = HARD,
    fallback: str | None = None,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    diagnostics: Path | str | None = None,
    category: str = "render",
    component: str = "render",
    severity: str = "warning",
    impact: str = "",
    country: str | None = None,
    launch_id: str | None = None,
    phase: str | None = None,
) -> StepResult:
    """Run one render command against ``html_path`` under ``policy``."""
    if policy not in (HARD, OPTIONAL):
        raise ValueError(f"unknown step policy {policy!r}")
    html_path = Path(html_path)
    before = html_path.read_bytes() if html_path.is_file() else None
    proc = subprocess.run(list(argv), cwd=cwd, env=env, capture_output=True, text=True, check=False)
    if proc.returncode == 0:
        return StepResult(label=label, ok=True)
    detail = _tail(proc)
    if policy == HARD:
        raise StepFailed(label, detail)
    if before is not None:
        html_path.write_bytes(before)
    applied = None
    if fallback:
        from scripts.market_watch_launch.render_fallbacks import FallbackUnavailable, apply_fallback

        try:
            html = html_path.read_text(encoding="utf-8")
            html_path.write_text(apply_fallback(fallback, html, reason=detail), encoding="utf-8")
            applied = fallback
        except FallbackUnavailable as exc:
            raise StepFailed(label, f"optional step failed and fallback {fallback!r} is unavailable: {exc}; {detail}") from exc
    record_diagnostic(
        f"render_step_fallback:{label}",
        path=diagnostics,
        category=category,
        severity=severity,
        component=component,
        country=country,
        launch_id=launch_id,
        phase=phase,
        cause=f"The {label} render step failed; the page shows a truthful fallback for this part.",
        impact=impact or "This part of the page is shown as unavailable or in its previous verified form.",
        detail=detail,
    )
    return StepResult(label=label, ok=False, fallback=applied, detail=detail)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one Market Watch render step under a hard/optional policy")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run")
    run_p.add_argument("--html", type=Path, required=True)
    run_p.add_argument("--label", required=True)
    run_p.add_argument("--optional", action="store_true")
    run_p.add_argument("--fallback", default="")
    run_p.add_argument("--category", default="render")
    run_p.add_argument("--component", default="render")
    run_p.add_argument("--severity", default="warning")
    run_p.add_argument("--impact", default="")
    run_p.add_argument("--country", default="")
    run_p.add_argument("--phase", default="")
    run_p.add_argument("cmd", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    cmd = list(args.cmd)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        parser.error("missing command after --")
    try:
        result = run_step(
            args.html,
            cmd,
            label=args.label,
            policy=OPTIONAL if args.optional else HARD,
            fallback=args.fallback or None,
            env=dict(os.environ),
            category=args.category,
            component=args.component,
            severity=args.severity,
            impact=args.impact,
            country=args.country or None,
            launch_id=os.environ.get("MW_LAUNCH_ID") or None,
            phase=args.phase or None,
        )
    except StepFailed as exc:
        print(f"render step failed: {exc}", file=sys.stderr)
        return 1
    status: dict[str, Any] = {"label": result.label, "ok": result.ok, "fallback": result.fallback}
    print(status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
