"""Public issues feed shared by the research and final Pages editions.

One deterministic ``issues.json`` per built site. It is derived only from
artifacts the build already produced or read: the Stage 01 source-health
snapshot, the published market-state packet, the edition ``release.json``,
committed launch ingest ledgers, and bounded render diagnostics recorded by
optional render steps. It never fetches anything, never adds a wall-clock
timestamp, and never invents a check time or a data vintage.

Building or rendering the feed is never a publication veto: ``publish`` always
leaves a valid site (a feed with ``status: unavailable`` in the worst case).

Render diagnostics are JSON lines appended to the file named by
``MW_RENDER_DIAGNOSTICS`` (or an explicit path). Subprocess render steps call
``record_diagnostic``; when no path is configured the call is a no-op apart
from a single stderr line, so a missing collector can never fail a build.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable

ISSUES_FILENAME = "issues.json"
ISSUES_TYPE = "MARKET_WATCH_PUBLIC_ISSUES"
ISSUES_SCHEMA_VERSION = 1
DIAGNOSTICS_ENV = "MW_RENDER_DIAGNOSTICS"

SEVERITIES = ("critical", "warning", "info")
SEVERITY_RANK = {name: index for index, name in enumerate(SEVERITIES)}
STATES = ("active", "resolved")
CATEGORIES = (
    "market_data",
    "source",
    "scores",
    "news",
    "calendar",
    "chart",
    "trader_books",
    "render",
    "publication",
)
COUNTRIES = ("US", "CA", "AU", "NZ", "EA", "JP")

DETAIL_LIMIT = 4000
TEXT_LIMIT = 400


class IssueSchemaError(ValueError):
    pass


def _bounded(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split()) if limit <= TEXT_LIMIT else str(value or "")
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def issue_id(category: str, component: str, code: str, country: str | None = None, series_id: str | None = None) -> str:
    """Stable id: the same problem in the same place has the same id across builds."""
    key = "|".join((category, component, code, country or "", series_id or ""))
    return "iss-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def make_issue(
    code: str,
    *,
    category: str,
    severity: str,
    component: str,
    cause: str,
    impact: str,
    country: str | None = None,
    series_id: str | None = None,
    publisher: str | None = None,
    url: str | None = None,
    launch_id: str | None = None,
    ingest_launch_id: str | None = None,
    phase: str | None = None,
    last_verified_vintage: str | None = None,
    detail: str = "",
    state: str = "active",
) -> dict[str, Any]:
    """Validated issue row (schema v1). Raises ``IssueSchemaError`` on bad input."""
    if category not in CATEGORIES:
        raise IssueSchemaError(f"unknown issue category {category!r}")
    if severity not in SEVERITIES:
        raise IssueSchemaError(f"unknown issue severity {severity!r}")
    if state not in STATES:
        raise IssueSchemaError(f"unknown issue state {state!r}")
    if not code or not component or not cause or not impact:
        raise IssueSchemaError("issue code, component, cause and impact are required")
    country_value = str(country).upper() if country else None
    link = str(url) if url and str(url).startswith("https://") else None
    return {
        "id": issue_id(category, component, code, country_value, series_id),
        "code": str(code),
        "state": state,
        "severity": severity,
        "category": category,
        "component": str(component),
        "country": country_value,
        "series_id": str(series_id) if series_id else None,
        "source": {"publisher": str(publisher) if publisher else None, "url": link},
        "run": {
            "launch_id": launch_id or None,
            "ingest_launch_id": ingest_launch_id or None,
            "phase": phase or None,
        },
        "cause": _bounded(cause, TEXT_LIMIT),
        "impact": _bounded(impact, TEXT_LIMIT),
        "last_verified_vintage": str(last_verified_vintage) if last_verified_vintage else None,
        "detail": _bounded(detail, DETAIL_LIMIT),
        "occurrences": 1,
    }


def sort_key(issue: dict[str, Any]) -> tuple[Any, ...]:
    return (
        0 if issue.get("state") == "active" else 1,
        SEVERITY_RANK.get(str(issue.get("severity")), len(SEVERITIES)),
        str(issue.get("category") or ""),
        str(issue.get("country") or ""),
        str(issue.get("component") or ""),
        str(issue.get("id") or ""),
    )


def dedupe(issues: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge rows with the same id. Keeps the most severe row, sums occurrences.

    An ``active`` row always wins over a ``resolved`` row with the same id.
    """
    merged: dict[str, dict[str, Any]] = {}
    for row in issues:
        key = str(row.get("id") or "")
        if not key:
            continue
        current = merged.get(key)
        if current is None:
            merged[key] = dict(row)
            continue
        occurrences = int(current.get("occurrences") or 1) + int(row.get("occurrences") or 1)
        if sort_key(row) < sort_key(current):
            current = dict(row)
        current["occurrences"] = occurrences
        merged[key] = current
    return sorted(merged.values(), key=sort_key)


# ------------------------------------------------------------ diagnostics


def diagnostics_path(path: Path | str | None = None) -> Path | None:
    if path:
        return Path(path)
    raw = os.environ.get(DIAGNOSTICS_ENV, "").strip()
    return Path(raw) if raw else None


def record_diagnostic(code: str, *, path: Path | str | None = None, **fields: Any) -> dict[str, Any] | None:
    """Append one render diagnostic. Never raises; returns the row or None."""
    try:
        row = make_issue(code, **fields)
    except IssueSchemaError as exc:
        print(f"render diagnostic rejected ({code}): {exc}", file=sys.stderr)
        return None
    target = diagnostics_path(path)
    if target is None:
        print(f"render diagnostic ({row['severity']}) {row['component']}: {row['cause']}", file=sys.stderr)
        return row
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    except OSError as exc:
        print(f"render diagnostic not written ({code}): {exc}", file=sys.stderr)
    return row


def load_diagnostics(path: Path | str | None = None) -> list[dict[str, Any]]:
    target = diagnostics_path(path)
    if target is None or not target.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("id"):
            rows.append(row)
    return rows


# ------------------------------------------------------------------ feed


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _edition(release: dict[str, Any] | None) -> dict[str, Any]:
    release = release if isinstance(release, dict) else {}
    return {
        "phase": release.get("phase"),
        "session_date": release.get("session_date"),
        "launch_id": release.get("launch_id"),
        "review_id": release.get("review_id"),
    }


def build_issues_feed(
    site_dir: Path,
    *,
    root: Path | None = None,
    diagnostics: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Deterministic feed for a built site.

    Worker D extends the collectors (source health, market state, release
    quality/news/headlines, resolved-state from the previous committed ingest).
    The contract of this function's return value is fixed by the schema here.
    """
    site = Path(site_dir)
    release = _read_json(site / "release.json")
    issues: list[dict[str, Any]] = list(diagnostics)
    issues = dedupe(issues)
    del root
    return finalize_feed(issues, release=release if isinstance(release, dict) else None, inputs=_input_digests(site))


def _input_digests(site: Path) -> list[dict[str, str]]:
    out = []
    for name in ("release.json", "source-health.json", "market-state.json", "release-calendar.json"):
        path = site / name
        if path.is_file():
            out.append({"name": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return out


def finalize_feed(
    issues: list[dict[str, Any]],
    *,
    release: dict[str, Any] | None,
    inputs: list[dict[str, str]],
    status: str = "available",
    reason: str | None = None,
) -> dict[str, Any]:
    rows = dedupe(issues)
    active = [row for row in rows if row.get("state") == "active"]
    feed: dict[str, Any] = {
        "type": ISSUES_TYPE,
        "schema_version": ISSUES_SCHEMA_VERSION,
        "status": status,
        "edition": _edition(release),
        "inputs": inputs,
        "counts": {
            "active": len(active),
            "resolved": len(rows) - len(active),
            **{name: sum(1 for row in active if row.get("severity") == name) for name in SEVERITIES},
        },
        "issues": rows,
    }
    if reason:
        feed["reason"] = _bounded(reason, TEXT_LIMIT)
    return feed


def unavailable_feed(reason: str, *, release: dict[str, Any] | None = None) -> dict[str, Any]:
    return finalize_feed([], release=release, inputs=[], status="unavailable", reason=reason)


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def restamp_release_digest(site_dir: Path) -> dict[str, Any] | None:
    """Recompute ``release.json`` ``site_sha256`` after the issues step changed files."""
    from scripts.market_watch_launch.publication_release import canonical_json as release_json
    from scripts.market_watch_launch.publication_release import site_digest

    site = Path(site_dir)
    path = site / "release.json"
    release = _read_json(path)
    if not isinstance(release, dict):
        return None
    release["site_sha256"] = site_digest(site)
    path.write_text(release_json(release), encoding="utf-8")
    return release


def publish_issues(
    site_dir: Path,
    *,
    root: Path | None = None,
    diagnostics: Iterable[dict[str, Any]] | None = None,
    diagnostics_file: Path | str | None = None,
) -> dict[str, Any]:
    """Write ``issues.json``, render the Issues panel, restamp the release digest.

    Never raises for feed or render problems. A feed that cannot be built is
    published as ``status: unavailable``; a panel that cannot be rendered keeps
    the page's quiet unavailable placeholder.
    """
    from scripts.dashboard_repair.sources_view import inject_issues_panel

    site = Path(site_dir)
    release = _read_json(site / "release.json")
    rows = list(diagnostics) if diagnostics is not None else load_diagnostics(diagnostics_file)
    try:
        feed = build_issues_feed(site, root=root, diagnostics=rows)
    except Exception as exc:  # noqa: BLE001 - the issues feed is never a publication veto
        feed = unavailable_feed(f"issues feed could not be built: {type(exc).__name__}: {exc}", release=release)
    index = site / "index.html"
    if index.is_file():
        html = index.read_text(encoding="utf-8")
        try:
            updated = inject_issues_panel(html, feed)
        except Exception as exc:  # noqa: BLE001
            print(f"issues panel not rendered: {type(exc).__name__}: {exc}", file=sys.stderr)
            updated = html
        if updated != html:
            index.write_text(updated, encoding="utf-8")
    (site / ISSUES_FILENAME).write_text(canonical_json(feed), encoding="utf-8")
    if isinstance(release, dict):
        restamp_release_digest(site)
    return feed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Market Watch public issues feed")
    sub = parser.add_subparsers(dest="command", required=True)
    pub = sub.add_parser("publish", help="Write issues.json into a built site and render the Issues panel")
    pub.add_argument("--site-dir", type=Path, required=True)
    pub.add_argument("--root", type=Path, default=Path.cwd())
    pub.add_argument("--diagnostics", default="", help=f"JSONL diagnostics file (default ${DIAGNOSTICS_ENV})")
    args = parser.parse_args(argv)
    try:
        feed = publish_issues(args.site_dir, root=args.root, diagnostics_file=args.diagnostics or None)
    except Exception as exc:  # noqa: BLE001 - never a publication veto
        print(f"issues feed step failed softly: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 0
    print(json.dumps({"status": feed.get("status"), "counts": feed.get("counts")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
