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
import re
import sys
from pathlib import Path
from typing import Any, Callable, Iterable

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

_FORBIDDEN_PHRASES = ("Current verified headlines", "Last refreshed")
_TEMP_PATH_RE = re.compile(r"(?:(?:/tmp|/var/tmp|/var/folders)/[^\s\"']+)")

_MARKET_SOURCE_BAD = frozenset({"unavailable", "partial", "error"})
_MARKET_KEY_COUNTRY_RE = re.compile(
    r"^(US|CA|AU|NZ|EA|JP)_",
    re.I,
)
_PREV_INGEST_FAILURE = frozenset({"source_failed", "license_gap", "due_missing"})
_LAUNCHES_REL = Path("data") / "market_watch_launches"


class IssueSchemaError(ValueError):
    pass


def _bounded(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split()) if limit <= TEXT_LIMIT else str(value or "")
    text = _sanitize_text(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _sanitize_text(text: str) -> str:
    out = str(text or "")
    for phrase in _FORBIDDEN_PHRASES:
        out = out.replace(phrase, "[redacted label]")
    return _TEMP_PATH_RE.sub("[temp path]", out)


def _market_source_country(key: str) -> str | None:
    match = _MARKET_KEY_COUNTRY_RE.match(str(key or ""))
    if not match:
        return None
    code = match.group(1).upper()
    return code if code in COUNTRIES else None


def _market_source_cause(note: str, error: str, *, fetch_failed: bool = True) -> str:
    from scripts.dashboard_repair.sources_view import _human_market_detail

    human, _ = _human_market_detail(note, error)
    if human:
        text = re.sub(r"https?://\S+", "", human)
        text = " ".join(text.split()).strip(" ,;:")
    else:
        text = "Market-data source fetch failed." if fetch_failed else "Market-data source is stale."
    if len(text) <= 160:
        return text
    return text[:159] + "…"


def _error_summary(error: str) -> str:
    line = " ".join(str(error or "").split())
    if not line:
        return ""
    if len(line) <= 120:
        return line
    return line[:119] + "…"


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


def _release_fields(release: dict[str, Any] | None) -> tuple[str | None, str | None]:
    if not isinstance(release, dict):
        return None, None
    return (
        str(release.get("launch_id") or "") or None,
        str(release.get("phase") or "") or None,
    )


def _succeeded_ingest(path: Path, launch_name: str, root: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    rows = payload.get("rows")
    if payload.get("status") != "succeeded" or not isinstance(rows, list) or not rows:
        return None
    return {
        "launch_id": launch_name,
        "checked_at": str(payload.get("checked_at") or ""),
        "stage_status": str(payload.get("status") or ""),
        "rows": rows,
        "source": str(path.relative_to(root)),
    }


def load_preceding_succeeded_ingest(root: Path, before_launch_id: str) -> dict[str, Any] | None:
    """Stage 01 ingest immediately before ``before_launch_id`` in launch dir sort order."""
    base = root / _LAUNCHES_REL
    if not base.is_dir():
        return None
    candidates = sorted(path.name for path in base.iterdir() if path.is_dir() and path.name.startswith("mwl-"))
    try:
        index = candidates.index(before_launch_id)
    except ValueError:
        return None
    for launch_name in reversed(candidates[:index]):
        ingest = _succeeded_ingest(base / launch_name / "artifacts" / "01_ingest.json", launch_name, root)
        if ingest is not None:
            return ingest
    return None


def _ingest_row_status(ingest: dict[str, Any] | None, series_id: str) -> str:
    if not ingest:
        return ""
    for row in ingest.get("rows") or []:
        if isinstance(row, dict) and str(row.get("series_id") or "") == series_id:
            return str(row.get("status") or "")
    return ""


def collect_source_health_issues(
    snapshot: dict[str, Any],
    release: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    launch_id, phase = _release_fields(release)
    ingest_launch = str(snapshot.get("launch_id") or "") or None
    rows = snapshot.get("rows") if isinstance(snapshot.get("rows"), list) else []
    issues: list[dict[str, Any]] = []
    not_checked: dict[str, list[str]] = {}

    for row in rows:
        if not isinstance(row, dict):
            continue
        bucket = str(row.get("bucket") or "")
        series_id = str(row.get("series_id") or "")
        country = str(row.get("country") or "") or None
        publisher = str(row.get("publisher") or "") or None
        url = str(row.get("url") or "") or None
        error = str(row.get("error") or "")
        vintage = str(row.get("observation_period") or "") or None
        common = {
            "country": country,
            "series_id": series_id or None,
            "publisher": publisher,
            "url": url,
            "launch_id": launch_id,
            "ingest_launch_id": ingest_launch,
            "phase": phase,
            "last_verified_vintage": vintage,
        }
        if bucket == "failure":
            summary = _error_summary(error)
            cause = "Fetch failed at the stage check."
            if summary:
                cause = f"{cause} {summary}"
            issues.append(
                make_issue(
                    "source_fetch_failed",
                    category="source",
                    severity="warning",
                    component=f"source:{series_id}",
                    cause=cause,
                    impact="Last verified value stays dated; it is not shown as fresh.",
                    detail=error,
                    **common,
                )
            )
        elif bucket == "blocked":
            issues.append(
                make_issue(
                    "source_blocked",
                    category="source",
                    severity="info",
                    component=f"source:{series_id}",
                    cause="Publisher blocks automated access.",
                    impact="Last verified value stays dated; it is not shown as fresh.",
                    detail=error,
                    **common,
                )
            )
        elif bucket == "partial":
            issues.append(
                make_issue(
                    "source_partial",
                    category="source",
                    severity="info",
                    component=f"source:{series_id}",
                    cause="Stage 01 marked this series as partially covered.",
                    impact="The published score may rely on carried or incomplete inputs.",
                    detail=error,
                    **common,
                )
            )
        elif bucket == "not_checked":
            key = str(country or "unknown").upper()
            not_checked.setdefault(key, []).append(series_id)

    for country, series_ids in sorted(not_checked.items()):
        ids = sorted(series_ids)
        row = make_issue(
            "sources_not_checked",
            category="source",
            severity="info",
            component="sources:not_checked",
            country=country if country != "UNKNOWN" else None,
            cause=f"{len(ids)} series were not checked on the latest Stage 01 ledger.",
            impact="Those series are listed without a fresh verification time.",
            launch_id=launch_id,
            ingest_launch_id=ingest_launch,
            phase=phase,
            detail=", ".join(ids),
        )
        row["occurrences"] = len(ids)
        issues.append(row)
    return issues


def collect_market_state_issues(
    packet: dict[str, Any],
    release: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    launch_id, phase = _release_fields(release)
    issues: list[dict[str, Any]] = []
    top_status = str(packet.get("status") or "")
    if top_status == "unavailable":
        issues.append(
            make_issue(
                "market_state_unavailable",
                category="market_data",
                severity="critical",
                component="market_state",
                cause="The market-state packet is unavailable for this edition.",
                impact="Market Data marks and cross-asset context are not shown as current.",
                launch_id=launch_id,
                phase=phase,
            )
        )
    sources = packet.get("sources") if isinstance(packet.get("sources"), dict) else {}
    for key in sorted(sources):
        entry = sources.get(key)
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("status") or "ok")
        error = str(entry.get("error") or "")
        note = str(entry.get("note") or "")
        vintage = str(entry.get("observation_date") or "") or None
        affects_marks = key == "FX" or key.endswith("_rates")
        detail = error or note
        if status == "stale":
            issues.append(
                make_issue(
                    "market_source_stale",
                    category="market_data",
                    severity="warning",
                    component=f"market_state:{key}",
                    cause=f"{key} observation is older than the freshness window.",
                    impact=(
                        "Published FX and rate marks may be stale."
                        if affects_marks
                        else "This market-data source is not fully current on the page."
                    ),
                    country=_market_source_country(key),
                    launch_id=launch_id,
                    phase=phase,
                    last_verified_vintage=vintage,
                    detail=detail,
                )
            )
            continue
        if status in _MARKET_SOURCE_BAD or error:
            from scripts.dashboard_repair.sources_view import _human_market_detail

            severity = "critical" if affects_marks else "warning"
            cause = _market_source_cause(note, error, fetch_failed=True)
            _, blob = _human_market_detail(note, error)
            detail = blob or detail
            issues.append(
                make_issue(
                    "market_source_degraded",
                    category="market_data",
                    severity=severity,
                    component=f"market_state:{key}",
                    cause=cause,
                    impact=(
                        "Published FX and rate marks may be missing or stale."
                        if affects_marks
                        else "This market-data source is not fully current on the page."
                    ),
                    country=_market_source_country(key),
                    launch_id=launch_id,
                    phase=phase,
                    last_verified_vintage=vintage,
                    detail=detail,
                )
            )
    return issues


def _gap_country(gap: str) -> str | None:
    text = str(gap or "")
    if ":" in text:
        code = text.split(":", 1)[1].upper()
        if code in COUNTRIES:
            return code
    return None


def collect_release_issues(release: dict[str, Any]) -> list[dict[str, Any]]:
    launch_id, phase = _release_fields(release)
    issues: list[dict[str, Any]] = []
    quality = release.get("quality") if isinstance(release.get("quality"), dict) else {}
    if str(quality.get("coverage") or "").upper() == "PARTIAL":
        for gap in sorted(str(item) for item in quality.get("research_coverage_gaps") or []):
            issues.append(
                make_issue(
                    "quality_coverage_gap",
                    category="source",
                    severity="info",
                    component="quality:coverage",
                    country=_gap_country(gap),
                    cause=f"Research coverage gap: {gap}.",
                    impact="Macro inputs for this economy may be incomplete in scores.",
                    launch_id=launch_id,
                    phase=phase,
                    detail=gap,
                )
            )
    for expr in sorted(str(item) for item in quality.get("blocked_expressions") or []):
        issues.append(
            make_issue(
                "quality_blocked_expression",
                category="publication",
                severity="warning",
                component="quality:blocked_expression",
                country=_gap_country(expr),
                cause=f"Expression blocked from publication: {expr}.",
                impact="That macro expression is withheld from the public score board.",
                launch_id=launch_id,
                phase=phase,
                detail=expr,
            )
        )
    news = release.get("news") if isinstance(release.get("news"), dict) else {}
    if str(news.get("status") or "") == "unavailable":
        issues.append(
            make_issue(
                "news_unavailable",
                category="news",
                severity="warning",
                component="news",
                cause="Accepted news context is unavailable.",
                impact="News sections show an unavailable placeholder.",
                launch_id=launch_id,
                phase=phase,
            )
        )
    if str(news.get("mode") or "") == "current-cycle-news-commentary-missing":
        issues.append(
            make_issue(
                "news_commentary_missing",
                category="news",
                severity="info",
                component="news",
                cause="Current-cycle news commentary is missing.",
                impact="The Front page shows news context without same-cycle commentary.",
                launch_id=launch_id,
                phase=phase,
            )
        )
    if news and news.get("current_session") is False:
        issues.append(
            make_issue(
                "news_previous_session",
                category="news",
                severity="info",
                component="news",
                cause="Accepted analysis is from an earlier session",
                impact="News and commentary reflect the prior overnight cycle, not this session.",
                launch_id=launch_id,
                phase=phase,
                last_verified_vintage=str(news.get("as_of") or "") or None,
            )
        )
    headlines = release.get("headlines") if isinstance(release.get("headlines"), dict) else {}
    if str(headlines.get("status") or "") == "unavailable":
        issues.append(
            make_issue(
                "headlines_unavailable",
                category="news",
                severity="warning",
                component="headlines",
                cause="Verified headlines are unavailable for this edition.",
                impact="Headline panels show an empty or unavailable state.",
                launch_id=launch_id,
                phase=phase,
            )
        )
    return issues


def collect_trader_room_issues(payload: dict[str, Any], release: dict[str, Any] | None) -> list[dict[str, Any]]:
    launch_id, phase = _release_fields(release)
    if payload.get("available") is not False:
        return []
    return [
        make_issue(
            "trader_room_unavailable",
            category="render",
            severity="info",
            component="research_debate",
            cause="The research debate room is not available.",
            impact="Trader Room shows as unavailable on this edition.",
            launch_id=launch_id,
            phase=phase,
        )
    ]


def collect_resolved_source_issues(
    snapshot: dict[str, Any],
    preceding_ingest: dict[str, Any] | None,
    release: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not preceding_ingest:
        return []
    launch_id, phase = _release_fields(release)
    prev_launch = str(preceding_ingest.get("launch_id") or "")
    rows = snapshot.get("rows") if isinstance(snapshot.get("rows"), list) else []
    issues: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or str(row.get("bucket") or "") != "checked":
            continue
        series_id = str(row.get("series_id") or "")
        prev_status = _ingest_row_status(preceding_ingest, series_id)
        if prev_status not in _PREV_INGEST_FAILURE:
            continue
        issues.append(
            make_issue(
                "source_resolved",
                category="source",
                severity="info",
                state="resolved",
                component=f"source:{series_id}",
                country=str(row.get("country") or "") or None,
                series_id=series_id,
                publisher=str(row.get("publisher") or "") or None,
                url=str(row.get("url") or "") or None,
                cause=f"Fetch succeeded after {prev_launch} had reported {prev_status.replace('_', ' ')}.",
                impact="The series is checked on the current Stage 01 ledger.",
                launch_id=launch_id,
                ingest_launch_id=str(snapshot.get("launch_id") or "") or None,
                phase=phase,
                last_verified_vintage=str(row.get("observation_period") or "") or None,
            )
        )
    return issues


def _input_unreadable(name: str, release: dict[str, Any] | None) -> dict[str, Any]:
    launch_id, phase = _release_fields(release)
    return make_issue(
        "issues_input_unreadable",
        category="publication",
        severity="info",
        component=f"issues_input:{name}",
        cause=f"Could not read {name} for the issues feed.",
        impact="Problems from that input are omitted from this feed.",
        launch_id=launch_id,
        phase=phase,
    )


def _extend_collector(
    issues: list[dict[str, Any]],
    name: str,
    release: dict[str, Any] | None,
    collector: Callable[[], list[dict[str, Any]]],
) -> None:
    try:
        issues.extend(collector())
    except Exception:  # noqa: BLE001 - one bad collector must not break the feed
        issues.append(_input_unreadable(name, release))


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
    repo_root = Path(root) if root else site.parent
    release_raw = _read_json(site / "release.json")
    release = release_raw if isinstance(release_raw, dict) else None
    launch_id, phase = _release_fields(release)
    issues: list[dict[str, Any]] = []
    for row in diagnostics:
        if isinstance(row, dict) and row.get("id"):
            issues.append(row)

    health_path = site / "source-health.json"

    def collect_health() -> list[dict[str, Any]]:
        if not health_path.is_file():
            return [
                make_issue(
                    "source_health_unavailable",
                    category="source",
                    severity="warning",
                    component="sources",
                    cause="The source-health snapshot was not published.",
                    impact="Source freshness for this edition is not shown.",
                    launch_id=launch_id,
                    phase=phase,
                )
            ]
        snapshot = _read_json(health_path)
        if not isinstance(snapshot, dict):
            raise ValueError("source-health unreadable")
        out = collect_source_health_issues(snapshot, release)
        snap_launch = str(snapshot.get("launch_id") or "")
        if snap_launch:
            preceding = load_preceding_succeeded_ingest(repo_root, snap_launch)
            out.extend(collect_resolved_source_issues(snapshot, preceding, release))
        return out

    _extend_collector(issues, "source-health.json", release, collect_health)

    market_path = site / "market-state.json"

    def collect_market() -> list[dict[str, Any]]:
        if not market_path.is_file():
            return [
                make_issue(
                    "market_state_unavailable",
                    category="market_data",
                    severity="critical",
                    component="market_state",
                    cause="The market-state packet is not present on this site.",
                    impact="Market Data marks and cross-asset context are not shown as current.",
                    launch_id=launch_id,
                    phase=phase,
                )
            ]
        packet = _read_json(market_path)
        if not isinstance(packet, dict):
            raise ValueError("market-state unreadable")
        return collect_market_state_issues(packet, release)

    _extend_collector(issues, "market-state.json", release, collect_market)

    def collect_release() -> list[dict[str, Any]]:
        if not isinstance(release, dict):
            raise ValueError("release unreadable")
        return collect_release_issues(release)

    _extend_collector(issues, "release.json", release, collect_release)

    room_path = site / "trader-room.json"

    def collect_room() -> list[dict[str, Any]]:
        if not room_path.is_file():
            return []
        payload = _read_json(room_path)
        if not isinstance(payload, dict):
            raise ValueError("trader-room unreadable")
        return collect_trader_room_issues(payload, release)

    _extend_collector(issues, "trader-room.json", release, collect_room)

    issues = dedupe(issues)
    return finalize_feed(issues, release=release, inputs=_input_digests(site))


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
