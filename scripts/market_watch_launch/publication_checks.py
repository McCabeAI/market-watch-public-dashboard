"""Publication checks shared by the research and final Pages editions.

``check_*`` functions are hard: they raise ``PublicationIntegrityError`` when a
page would present stale or unverified data as current or a failed source as
freshly checked. They are the only HTML/sidecar checks that may refuse a
publication. ``soft_*`` functions never raise; they return issue rows (see
``publication_issues``) for presentation problems that the page survives.

Checks that scan the whole page ignore the Sources & Issues panel, because
issue text legitimately quotes what went wrong.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

from scripts.market_watch_launch.publication_issues import make_issue, record_diagnostic

STALE_TAPE_VALUES = ("4.79%", "1.3790", "0.7210", "0.58755", "98.83", "$92.33", "$97.23")
STALE_STATIC_NEWS = ("Last refreshed 18 Sep 2026",)
TAPE_START = 'data-global-tape="repair"'
TAPE_END = 'data-score-overview="calibrated"'
ISSUES_PANEL_OPEN = '<div class="mw-issues"'
REQUIRED_NAV = ("p-front", "p-country", "p-marketdata", "p-traderbook", "p-releases", "p-sources")
RETIRED_NAV = ("p-feed", "p-relative", "p-traderroom")
COUNTRY_CODES = ("us", "ca", "au", "nz", "ea", "jp")
LAST_REFRESHED_RE = re.compile(r"Last refreshed\s+(\d{1,2})\s+([A-Za-z]{3})\s+(20\d{2})")


class PublicationIntegrityError(Exception):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason + (f" ({detail})" if detail else ""))
        self.reason = reason
        self.detail = detail


def strip_issues_panel(html: str) -> str:
    """Page text without the Sources & Issues panel (and its badge)."""
    from scripts.dashboard_repair.htmlutil import balanced_element_end

    out = html
    for opener in (ISSUES_PANEL_OPEN, '<span class="mw-issues-badge"'):
        while True:
            start = out.find(opener)
            if start < 0:
                break
            try:
                end = balanced_element_end(out, start)
            except ValueError:
                # An unbalanced panel is not stripped: hard checks must still see the rest of the page.
                return html
            out = out[:start] + out[end:]
    return out


# ------------------------------------------------------------------ hard


def check_no_stale_tape(html: str) -> None:
    """The base page's September tape must not survive as current prices."""
    start = html.find(TAPE_START)
    end = html.find(TAPE_END, start)
    if start < 0 or end < 0:
        raise PublicationIntegrityError("repaired_tape_missing")
    region = html[start:end]
    for stale in STALE_TAPE_VALUES:
        if stale in region:
            raise PublicationIntegrityError("stale_tape_value", stale)


def check_no_stale_static_news(html: str) -> None:
    page = strip_issues_panel(html)
    for needle in STALE_STATIC_NEWS:
        if needle in page:
            raise PublicationIntegrityError("stale_news_survived", needle)


def _visible_refresh_dates(html: str) -> list[date]:
    from datetime import datetime

    out = []
    for match in LAST_REFRESHED_RE.finditer(strip_issues_panel(html)):
        try:
            out.append(datetime.strptime(f"{match.group(1)} {match.group(2)} {match.group(3)}", "%d %b %Y").date())
        except ValueError:
            continue
    return out


def check_news_dates_not_overstated(
    html: str,
    *,
    accepted_as_of: str | None,
    frozen_at: str | None = None,
    current_session: bool = True,
) -> None:
    """No visible news label may claim a date newer than the accepted news.

    With no accepted news, no "Last refreshed" label may be visible at all.
    When the accepted news is from an earlier session, the freeze session date
    must not appear as a refresh date.
    """
    from scripts.overnight.clock import parse_iso

    dates = _visible_refresh_dates(html)
    if not accepted_as_of:
        if dates:
            raise PublicationIntegrityError("news_label_without_accepted_news", dates[0].isoformat())
        return
    accepted = parse_iso(str(accepted_as_of)).date()
    for seen in dates:
        if seen > accepted:
            raise PublicationIntegrityError("news_label_overstated", f"visible={seen} accepted={accepted}")
    if frozen_at and not current_session:
        session = parse_iso(str(frozen_at)).date()
        if session != accepted and session in dates:
            raise PublicationIntegrityError("stale_news_labeled_current", session.isoformat())


def check_source_health_truthful(health: Any, *, launch_id: str | None = None) -> None:
    """Failed sources are never given a success time; research health is this launch's."""
    if not isinstance(health, dict):
        raise PublicationIntegrityError("source_health_missing")
    rows = health.get("rows") or []
    if any(isinstance(row, dict) and row.get("bucket") == "failure" and row.get("last_successful_check") for row in rows):
        raise PublicationIntegrityError("failed_source_given_success_time")
    if launch_id is not None:
        if health.get("launch_id") != launch_id:
            raise PublicationIntegrityError("source_health_not_this_launch", str(health.get("launch_id")))
        if not health.get("stage_checked_at"):
            raise PublicationIntegrityError("source_health_check_time_missing")


# ------------------------------------------------------------------ soft


def _soft(code: str, *, component: str, cause: str, impact: str, category: str = "render", severity: str = "warning", **extra: Any) -> dict[str, Any]:
    return make_issue(code, category=category, severity=severity, component=component, cause=cause, impact=impact, **extra)


def soft_page_structure(html: str, *, phase: str | None = None, scores: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Presentation problems the page survives. Never raises."""
    issues: list[dict[str, Any]] = []
    try:
        for nav in REQUIRED_NAV:
            if f'for="{nav}"' not in html:
                issues.append(_soft("navigation_missing", component=f"nav:{nav}", phase=phase,
                                    cause=f"The {nav.removeprefix('p-')} tab link is missing from the navigation.",
                                    impact="That tab cannot be opened from the navigation bar."))
        for code in COUNTRY_CODES:
            if f'data-country="{code}"' not in html:
                issues.append(_soft("country_jump_missing", component="front:country_jumps", country=code, phase=phase,
                                    cause="The front-page jump button for this country is missing.",
                                    impact="Open the country from Country Detail instead."))
        for needle, component, label in (
            ('data-release-calendar="repair"', "releases", "Releases calendar"),
            ('data-source-health="repair"', "sources", "Sources inventory"),
            ("Market Data · official snapshot", "market_data_tab", "Market Data tab"),
            ("Trader Book", "trader_book_tab", "Trader Book tab"),
        ):
            if needle not in html:
                issues.append(_soft("section_missing", component=component, phase=phase,
                                    cause=f"The {label} section was not rendered.",
                                    impact=f"The {label} is unavailable on this edition."))
        for radio in RETIRED_NAV:
            if f'for="{radio}"' in html or f'id="{radio}"' in html:
                issues.append(_soft("retired_navigation_present", component=f"nav:{radio}", severity="info", phase=phase,
                                    cause=f"A retired tab ({radio.removeprefix('p-')}) is still in the page.",
                                    impact="The retired tab shows archived content only."))
        if "Momentum Watch" in html:
            issues.append(_soft("static_momentum_watch_survived", component="front:momentum", severity="info", phase=phase,
                                cause="The September static run-rate table was not removed.",
                                impact="That table is a dated base-page snapshot, not current data."))
        if isinstance(scores, dict):
            from scripts.dashboard_repair.score_dates import format_calibration_anchor, format_ingestion_day

            anchor = scores.get("calibration_anchor_date") or scores.get("as_of")
            ingested = scores.get("score_inputs_last_ingested_at")
            if anchor and f"calibration anchor {format_calibration_anchor(anchor)}" not in html:
                issues.append(_soft("calibration_anchor_label_missing", component="scoreboard", category="scores", phase=phase,
                                    cause="The score board does not show its calibration anchor date.",
                                    impact="Score dates are listed in the score drawers and release record."))
            if ingested and f"inputs last ingested {format_ingestion_day(ingested)}" not in html:
                issues.append(_soft("score_ingestion_label_missing", component="scoreboard", category="scores", phase=phase,
                                    cause="The score board does not show when score inputs were last ingested.",
                                    impact="Score dates are listed in the score drawers and release record."))
    except Exception as exc:  # noqa: BLE001 - soft checks never veto
        issues.append(_soft("soft_check_error", component="publication_checks", severity="info", phase=phase,
                            cause="A presentation check could not run.", impact="Some presentation problems may be unlisted.",
                            detail=f"{type(exc).__name__}: {exc}"))
    return issues


def soft_source_health(health: Any, *, phase: str | None = None) -> list[dict[str, Any]]:
    if not isinstance(health, dict):
        return [_soft("source_health_unavailable", component="sources", category="source", phase=phase,
                      cause="The source-health snapshot was not published.",
                      impact="Source freshness for this edition is not shown.")]
    rows = health.get("rows") or []
    counts = health.get("counts") or {}
    buckets = ("checked", "failure", "blocked", "partial", "not_checked", "not_applicable")
    try:
        total = sum(int(counts.get(name) or 0) for name in buckets)
    except (TypeError, ValueError):
        total = -1
    if total != len(rows):
        return [_soft("source_health_counts_mismatch", component="sources", category="source", severity="info", phase=phase,
                      cause="Source-health summary counts do not add up to the listed series.",
                      impact="Use the per-series rows; the summary chips may be off.",
                      detail=f"counts total {total}, rows {len(rows)}")]
    return []


def soft_news_consistency(html: str, context: dict[str, Any] | None, *, require_front_alert: bool, phase: str | None = None) -> list[dict[str, Any]]:
    """The legacy strict news HTML assertion, reported instead of raised."""
    if context is None:
        return [_soft("accepted_news_missing", component="news", category="news", phase=phase,
                      cause="No accepted news context was available for this edition.",
                      impact="News sections show an unavailable placeholder.")]
    from scripts.overnight.news_commentary_state import assert_built_news_matches_context

    try:
        assert_built_news_matches_context(html, context, require_front_alert=require_front_alert)
    except Exception as exc:  # noqa: BLE001
        return [_soft("news_html_inconsistent", component="news", category="news", phase=phase,
                      cause="The rendered news sections do not fully match the accepted news record.",
                      impact="Some news labels or headlines may be missing; no newer date than the accepted news is shown.",
                      last_verified_vintage=str(context.get("as_of") or "") or None,
                      detail=f"{type(exc).__name__}: {exc}")]
    return []


# ------------------------------------------------------------------- CLI


def _final_news_context(root: Path) -> dict[str, Any] | None:
    from scripts.overnight.accepted_news import effective_public_news_context
    from scripts.overnight.store import OvernightStore

    store = OvernightStore(root=root)
    dataset = None
    latest = store.read_latest()
    if latest and latest.get("overnight_run_id"):
        run_id = latest["overnight_run_id"]
        if store.has_artifact(run_id, "assembled_dataset.json"):
            dataset = store.read_artifact(run_id, "assembled_dataset.json")
    return effective_public_news_context(store, dataset)


def run_final_checks(site_dir: Path, *, root: Path, diagnostics: Path | str | None = None) -> list[dict[str, Any]]:
    """Hard checks for the final edition's built site; soft findings are recorded."""
    site = Path(site_dir)
    html = (site / "index.html").read_text(encoding="utf-8")
    check_no_stale_tape(html)
    check_no_stale_static_news(html)
    health_path = site / "source-health.json"
    health = json.loads(health_path.read_text(encoding="utf-8")) if health_path.is_file() else None
    if health is not None:
        check_source_health_truthful(health)
    try:
        context = _final_news_context(root)
    except Exception:  # noqa: BLE001 - a broken news record makes news unavailable, not the page
        context = None
    check_news_dates_not_overstated(html, accepted_as_of=(context or {}).get("as_of") if context else None)
    scores = None
    scores_path = root / "data" / "temperature_scores.json"
    if scores_path.is_file():
        scores = json.loads(scores_path.read_text(encoding="utf-8"))
    soft = soft_page_structure(html, phase="final", scores=scores)
    soft += soft_source_health(health, phase="final")
    soft += soft_news_consistency(html, context, require_front_alert=True, phase="final")
    for row in soft:
        fields = {k: row[k] for k in ("category", "severity", "component", "cause", "impact", "country", "series_id", "detail")}
        record_diagnostic(row["code"], path=diagnostics, phase="final", last_verified_vintage=row.get("last_verified_vintage"), **fields)
    return soft


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Market Watch shared publication checks")
    sub = parser.add_subparsers(dest="command", required=True)
    final_p = sub.add_parser("final", help="Hard integrity checks of a built final site; soft findings become diagnostics")
    final_p.add_argument("--site-dir", type=Path, required=True)
    final_p.add_argument("--root", type=Path, default=Path.cwd())
    final_p.add_argument("--diagnostics", default="")
    args = parser.parse_args(argv)
    try:
        soft = run_final_checks(args.site_dir, root=args.root, diagnostics=args.diagnostics or None)
    except PublicationIntegrityError as exc:
        print(f"publication refused: {exc.reason} {exc.detail}".strip(), file=sys.stderr)
        return 1
    print(json.dumps({"hard": "pass", "soft_issues": len(soft)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
