"""Explicit publication mode when the Trader Room news supplement is legitimately empty."""

from __future__ import annotations

import html as html_lib
import re
from pathlib import Path
from typing import Any

from scripts.overnight.clock import parse_iso
from scripts.overnight.errors import PublicationError
from scripts.overnight.public_prose import public_research_summary
from scripts.overnight.research_publishability import audit_agent_research
from scripts.overnight.store import sha256_json

MODE = "current-cycle-news-commentary-missing"
LEGACY_NO_AGENT_RESEARCH = "legacy-no-agent-research"
SUPPLEMENT_WITHOUT_STORIES = "supplement-without-stories"
WARNING = "Trader Room news write-up unavailable for this run."
FRONT_FLAG = "MARKET NEWS · WRITE-UP UNAVAILABLE"
FRONT_TITLE = "Trader Room news write-up unavailable"
FRONT_SUB = "No sourced news digest was published for this cycle."

LAST24_START = '<div class="last24">'
ROLLUP_START = '<div class="stitle">Top Market Drivers</div>'
ROLLUP_END = '<div class="x-signal">'
UNDATED_PROVENANCE_ATTR = 'data-news-provenance="undated"'
DESK_READ_FALLBACK = (
    "Accepted overnight developments are shown below; no clean desk summary was published for this cycle."
)

MARKER_RE = re.compile(
    r'data-publication-state="current-cycle-news-commentary-missing"'
    r'[^>]*data-news-commentary-run="([^"]+)"'
    r'[^>]*data-news-commentary-digest="([0-9a-f]{64})"',
    re.S,
)
FRONT_MISSING_ALERT_RE = re.compile(
    r'<div class="news-alert market-alert"[^>]*>.*?'
    r'<label for="p-news">Open News &amp; Research</label>\s*</div>',
    re.S,
)


def _dataset_cutoff_iso(dataset: dict[str, Any]) -> str:
    raw = dataset.get("agent_research_cutoff") or dataset.get("as_of")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("assembled dataset missing a valid agent research cutoff")
    parse_iso(raw)
    return raw


def _agent_research(dataset: dict[str, Any]) -> dict[str, Any]:
    research = dataset.get("agent_research")
    if not isinstance(research, dict):
        raise ValueError("agent_research must be a dict for commentary classification")
    return research


def classify_news_commentary(dataset: dict[str, Any]) -> str:
    if not isinstance(dataset, dict) or dataset.get("type") != "OVERNIGHT_MORNING_DATASET":
        raise ValueError("assembled dataset type mismatch")
    run_id = dataset.get("overnight_run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("overnight_run_id missing")
    research = dataset.get("agent_research")
    if research is None:
        return LEGACY_NO_AGENT_RESEARCH
    if not isinstance(research, dict):
        raise ValueError("agent_research must be a dict for commentary classification")
    for key in ("news", "central_bank_research"):
        if key not in research:
            raise ValueError(f"agent_research missing required key: {key}")
        if not isinstance(research[key], list):
            raise ValueError(f"agent_research.{key} must be a list")
    news = research["news"]
    central = research["central_bank_research"]
    if news or central:
        return "renderable"
    if "sources" not in research:
        raise ValueError("agent_research.sources missing on empty research supplement")
    sources = research["sources"]
    if not isinstance(sources, list):
        raise ValueError("agent_research.sources must be a list")
    if sources:
        return SUPPLEMENT_WITHOUT_STORIES
    summary = research.get("summary")
    if summary is not None and not isinstance(summary, str):
        raise ValueError("agent_research.summary must be a string when present")
    audit = audit_agent_research(research)
    if audit.invalid:
        raise ValueError(
            "accepted overnight research has invalid items "
            f"(invalid={audit.invalid}, dated={audit.dated}, undated={audit.undated})"
        )
    _dataset_cutoff_iso(dataset)
    if audit.dated == 0 and audit.undated == 0:
        return MODE
    return "renderable"


def is_current_cycle_news_commentary_missing(dataset: dict[str, Any]) -> bool:
    return classify_news_commentary(dataset) == MODE


def commentary_missing_digest(dataset: dict[str, Any]) -> str:
    if classify_news_commentary(dataset) != MODE:
        raise ValueError("dataset is not current-cycle-news-commentary-missing")
    research = _agent_research(dataset)
    payload = {
        "mode": MODE,
        "overnight_run_id": dataset["overnight_run_id"],
        "agent_research_cutoff": _dataset_cutoff_iso(dataset),
        "news": [],
        "central_bank_research": [],
        "sources": [],
    }
    return sha256_json(payload)


def news_region(html: str) -> str:
    if LAST24_START not in html or ROLLUP_END not in html:
        raise PublicationError("news section anchors changed")
    last_start = html.index(LAST24_START)
    rollup_end = html.index(ROLLUP_END, last_start)
    return html[last_start:rollup_end]


def _general_desk_read_html(summary: Any) -> str:
    if not isinstance(summary, str) or not summary.strip():
        return ""
    desk = public_research_summary(summary, items=[])
    if desk == DESK_READ_FALLBACK:
        return ""
    return f'<div class="last24-thesis"><b>General desk read:</b> {html_lib.escape(desk, quote=True)}</div>\n'


def commentary_missing_news_html(dataset: dict[str, Any]) -> str:
    if classify_news_commentary(dataset) != MODE:
        raise ValueError("dataset is not current-cycle-news-commentary-missing")
    run_id = str(dataset["overnight_run_id"])
    digest = commentary_missing_digest(dataset)
    research = _agent_research(dataset)
    desk = _general_desk_read_html(research.get("summary"))
    inner = (
        f'<div class="last24-missing" data-publication-state="{MODE}" '
        f'data-news-commentary-run="{html_lib.escape(run_id, quote=True)}" '
        f'data-news-commentary-digest="{digest}">\n'
        '  <div class="last24-head">\n'
        '    <div>\n'
        '      <div class="stitle">Last 24 Hours · Desk Summary</div>\n'
        f'      <p class="news-commentary-warning">{html_lib.escape(WARNING, quote=True)}</p>\n'
        "    </div>\n"
        "  </div>\n"
        f"{desk}"
        "</div>\n"
    )
    return f"{LAST24_START}\n{inner}</div>\n\n"


def assert_news_html(html: str, context: dict[str, Any], *, require_front_alert: bool) -> None:
    if context.get("mode") != MODE:
        raise PublicationError("assert_news_html requires current-cycle-news-commentary-missing context")
    expected_digest = context.get("digest")
    if not isinstance(expected_digest, str) or len(expected_digest) != 64:
        raise PublicationError("missing news commentary digest in publication context")
    if html.count(WARNING) != 1:
        raise PublicationError(f"expected warning sentence exactly once, found {html.count(WARNING)}")
    region = news_region(html)
    match = MARKER_RE.search(region)
    if not match:
        raise PublicationError("news commentary missing-mode marker absent or malformed")
    run_id = context.get("overnight_run_id")
    if match.group(1) != run_id:
        raise PublicationError("news commentary run id does not match publication context")
    if match.group(2) != expected_digest:
        raise PublicationError("news commentary digest does not match publication context")
    forbidden = (
        'class="driver-card"',
        '<details class="story"',
        'class="last24-item"',
        "7-Day Quick Digest",
        "Accepted Overnight Research · Age Unverified",
        UNDATED_PROVENANCE_ATTR,
        "Last refreshed",
        "Top Market Drivers",
    )
    for needle in forbidden:
        if needle in region:
            raise PublicationError(f"forbidden news markup in missing mode: {needle}")
    if "Last 24 Hours · Desk Summary" not in region:
        raise PublicationError("missing Last 24 Hours · Desk Summary heading")
    if require_front_alert:
        if "<b>Last scanned:</b>" in html:
            raise PublicationError("missing-mode HTML must not retain Last scanned summary line")
        if "Sources include Reuters" in html:
            raise PublicationError("missing-mode HTML must not retain stale source-scan claim")
        if WARNING in html.replace(region, "", 1):
            pass
        front_match = FRONT_MISSING_ALERT_RE.search(html)
        if not front_match:
            raise PublicationError("front-page missing-mode news alert absent")
        block = front_match.group(0)
        if WARNING in block:
            raise PublicationError("front-page alert must not duplicate the news-section warning sentence")
        if FRONT_FLAG not in block or FRONT_TITLE not in block or FRONT_SUB not in block:
            raise PublicationError("front-page missing-mode alert metadata incomplete")
        if f'data-publication-state="{MODE}"' not in block:
            raise PublicationError("front-page alert missing publication state marker")
        if f'data-news-commentary-digest="{expected_digest}"' not in block:
            raise PublicationError("front-page alert missing commentary digest")
        if "qualifying events" in block:
            raise PublicationError("front-page alert must not claim qualifying events")
    from scripts.overnight.accepted_news import load_accepted_public_news

    artifact = load_accepted_public_news(Path("."))
    if artifact:
        for item in (artifact.get("news") or []) + (artifact.get("central_bank_research") or []):
            if not isinstance(item, dict):
                continue
            headline = str(item.get("headline") or item.get("title") or "").strip()
            if headline and headline in region:
                raise PublicationError(f"stale accepted headline visible in news region: {headline}")


def assert_built_news_matches_context(
    html: str,
    context: dict[str, Any],
    *,
    require_front_alert: bool,
) -> None:
    if context.get("mode") == MODE:
        assert_news_html(html, context, require_front_alert=require_front_alert)
        return
    from scripts.overnight.accepted_news import last_refreshed_label, parse_visible_last_refreshed

    raw_as_of = context.get("as_of")
    if not isinstance(raw_as_of, str):
        raise PublicationError("accepted public news missing as_of for HTML consistency check")
    cutoff = parse_iso(raw_as_of)
    visible = parse_visible_last_refreshed(html)
    if visible is None:
        raise PublicationError("built dashboard is missing a visible Last refreshed timestamp")
    if visible != cutoff.date():
        raise PublicationError(
            f"visible Last refreshed {visible.isoformat()} does not match accepted news as_of {cutoff.date().isoformat()}"
        )
    expected = last_refreshed_label(cutoff)
    if expected not in html:
        raise PublicationError(f"built dashboard missing expected visible marker: {expected}")
    plain = html_lib.unescape(html)
    headlines = [
        str(item.get("headline") or "").strip()
        for item in (context.get("news") or [])
        if isinstance(item, dict)
    ]
    if not any(headline and headline in plain for headline in headlines):
        raise PublicationError("accepted public news headlines missing from built HTML")
    if '<div class="stitle">7-Day Quick Digest</div>' in html:
        return
    if "Accepted Overnight Research · Age Unverified" in html:
        return
    raise PublicationError("built HTML missing dated or undated news digest section")
