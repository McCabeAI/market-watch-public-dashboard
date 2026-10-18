"""Live Bloomberg / Reuters discovery for overnight collect (no article HTML)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Callable
from urllib.parse import quote

from scripts.overnight.clock import isoformat, now_ny
from scripts.overnight.news_cluster import merge_live_news
from scripts.overnight.news_relevance import recall_candidate
from scripts.overnight.news_sources import (
    BLOOMBERG_QUERY,
    DISCOVERY_USER_AGENT,
    REUTERS_SURFACE,
    discovery_surfaces,
    parse_surface,
)

Fetcher = Callable[[str], bytes]

BLOOMBERG_SURFACE = (
    f"https://www.bing.com/news/search?q={quote(BLOOMBERG_QUERY)}&format=rss&qft=interval%3d%227%22"
)

REQUIRED_SOURCES = ("bloomberg", "reuters")

MARKET_TOKENS = (
    "fed",
    "fomc",
    "inflation",
    "cpi",
    "ppi",
    "payroll",
    "unemployment",
    "treasury",
    "yield",
    "oil",
    "brent",
    "wti",
    "crude",
    "hormuz",
    "opec",
    "lng",
    "pipeline",
    "fx",
    "forex",
    "dollar",
    "currency",
    "tariff",
    "sanction",
    "blockade",
    "central bank",
    "rba",
    "rbnz",
    "bank of canada",
    "boc",
    "ecb",
    "bank of japan",
    "boj",
    "rate cut",
    "rate hike",
    "policy rate",
    "recession",
    "gdp",
)

NOISE_EXCLUDE = ("podcast", "golf", "celebrity")

OFFICIAL_SOURCES = frozenset(
    {
        "Federal Reserve",
        "Bank of Canada",
        "Reserve Bank of Australia",
        "Reserve Bank of New Zealand",
        "European Central Bank",
        "Bank of Japan",
        "Bank of England",
    }
)

_COUNTRY_ATTRIBUTION_ORDER = ("US", "CA", "AU", "NZ", "EA", "JP")

_COUNTRY_ALIASES: tuple[tuple[str, str, int], ...] = (
    ("US", r"\bFederal Reserve\b", re.IGNORECASE),
    ("US", r"\bFOMC\b", re.IGNORECASE),
    ("US", r"\bFed\b", 0),
    ("US", r"\bFED\b", 0),
    ("US", r"\bUnited States\b", re.IGNORECASE),
    ("US", r"\bU\.S\.A\.?(?!\w)", re.IGNORECASE),
    ("US", r"\bU\.S\.(?!\w)", re.IGNORECASE),
    ("US", r"\bUSA\b", re.IGNORECASE),
    ("US", r"\bUSD\b", re.IGNORECASE),
    ("US", r"\bUS\b", 0),
    ("CA", r"\bBank of Canada\b", re.IGNORECASE),
    ("CA", r"\bBoC\b", re.IGNORECASE),
    ("CA", r"\bCanada\b", re.IGNORECASE),
    ("CA", r"\bCanadian\b", re.IGNORECASE),
    ("CA", r"\bCAD\b", re.IGNORECASE),
    ("AU", r"\bReserve Bank of Australia\b", re.IGNORECASE),
    ("AU", r"\bRBA\b", re.IGNORECASE),
    ("AU", r"\bAustralia\b", re.IGNORECASE),
    ("AU", r"\bAustralian\b", re.IGNORECASE),
    ("AU", r"\bAUD\b", re.IGNORECASE),
    ("NZ", r"\bReserve Bank of New Zealand\b", re.IGNORECASE),
    ("NZ", r"\bRBNZ\b", re.IGNORECASE),
    ("NZ", r"\bNew Zealand\b", re.IGNORECASE),
    ("NZ", r"\bNZD\b", re.IGNORECASE),
    ("NZ", r"\bNZ\b", 0),
    ("EA", r"\bEuropean Central Bank\b", re.IGNORECASE),
    ("EA", r"\bECB\b", re.IGNORECASE),
    ("EA", r"\beuro area\b", re.IGNORECASE),
    ("EA", r"\beurozone\b", re.IGNORECASE),
    ("EA", r"\beuro-zone\b", re.IGNORECASE),
    ("EA", r"\beuro zone\b", re.IGNORECASE),
    ("EA", r"\bEUR\b", re.IGNORECASE),
    ("EA", r"\beuro\b", re.IGNORECASE),
    ("JP", r"\bBank of Japan\b", re.IGNORECASE),
    ("JP", r"\bBoJ\b", re.IGNORECASE),
    ("JP", r"\bJapan\b", re.IGNORECASE),
    ("JP", r"\bJapanese\b", re.IGNORECASE),
    ("JP", r"\bJPY\b", re.IGNORECASE),
    ("JP", r"\byen\b", re.IGNORECASE),
)

_COMPILED_COUNTRY_ALIASES: list[tuple[str, re.Pattern[str]]] = [
    (code, re.compile(pattern, flags)) for code, pattern, flags in _COUNTRY_ALIASES
]

_NON_US_TREASURY = re.compile(
    r"\b(?:australian|canadian|canada(?:['\u2019]s)?|british|uk|u\.k\.|japanese|japan(?:['\u2019]s)?|"
    r"new zealand(?:['\u2019]s)?|eurozone|euro-zone|euro area|european)\s+treasury\b",
    re.IGNORECASE,
)
_TREASURY_TOKEN = re.compile(r"\btreasury\b", re.IGNORECASE)


def attribute_country_codes(headline: str, snippet: str) -> list[str]:
    """Infer covered economy codes from headline and snippet text only."""
    h = headline if headline is not None else ""
    s = snippet if snippet is not None else ""
    if not h and not s:
        return []
    text = f"{h}\n{s}"
    matched: set[str] = set()
    for code, pattern in _COMPILED_COUNTRY_ALIASES:
        if pattern.search(text):
            matched.add(code)
    if _TREASURY_TOKEN.search(text):
        stripped = _NON_US_TREASURY.sub("", text)
        if _TREASURY_TOKEN.search(stripped):
            matched.add("US")
    return [code for code in _COUNTRY_ATTRIBUTION_ORDER if code in matched]


# Per-surface safety ceiling diagnostics (source id -> applied).
SAFETY_CEILING_APPLIED: dict[str, bool] = {}


def _default_fetcher(url: str) -> bytes:
    import urllib.request

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": DISCOVERY_USER_AGENT,
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def _receipt(
    source: str,
    *,
    checked_at: str,
    status: str,
    candidate_count: int,
    result_count: int,
    failure: str | None,
    surface: str | None,
    feed_health: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "source": source,
        "checked_at": checked_at,
        "status": status,
        "candidate_count": candidate_count,
        "result_count": result_count,
        "failure": failure,
        "surface": surface,
    }
    if feed_health is not None:
        out["feed_health"] = feed_health
    return out


def _allowed_hosts_for_surface(source: str, kind: str) -> tuple[str, ...]:
    if kind == "bing_rss" and source == "reuters_credit":
        return ("reuters.com",)
    if kind == "bing_rss" and source == "cnbc_credit":
        return ("cnbc.com",)
    if kind == "bing_rss":
        return ("bloomberg.com",)
    return ()


def _drop_row(item: dict[str, Any], *, source: str, stage: str, reason: str) -> dict[str, Any]:
    return {
        "headline": item.get("headline"),
        "url": item.get("url"),
        "source": source,
        "published_at": item.get("published_at"),
        "stage": stage,
        "reason": reason,
    }


def _apply_recall_and_ceiling(
    parsed_items: list[dict[str, Any]],
    *,
    source: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    recalled: list[dict[str, Any]] = []
    drops: list[dict[str, Any]] = []
    for item in parsed_items:
        headline = str(item.get("headline") or "")
        summary = str(item.get("summary") or "")
        if not recall_candidate(headline, summary):
            drops.append(_drop_row(item, source=source, stage="relevance_rejection", reason="stage1_recall"))
            continue
        stamped = dict(item)
        stamped["country_codes"] = attribute_country_codes(headline, summary)
        recalled.append(stamped)
    recalled.sort(key=lambda x: x.get("published_at") or "", reverse=True)
    if len(recalled) > 60:
        SAFETY_CEILING_APPLIED[source] = True
        for omitted in recalled[60:]:
            drops.append(
                _drop_row(omitted, source=source, stage="discovery_failure", reason="safety_ceiling")
            )
        recalled = recalled[:60]
    return recalled, drops


def acquire_current_news(
    *,
    when: datetime,
    offline: bool = False,
    fetcher: Fetcher | None = None,
) -> dict[str, Any]:
    """Return {mode, cutoff, partial, receipts, candidates}."""
    SAFETY_CEILING_APPLIED.clear()
    cutoff = now_ny(when)
    cutoff_iso = isoformat(cutoff)
    surfaces = discovery_surfaces()

    if offline:
        skipped = [
            _receipt(
                entry["source"],
                checked_at=cutoff_iso,
                status="skipped",
                candidate_count=0,
                result_count=0,
                failure=None,
                surface=None,
                feed_health="skipped",
            )
            for entry in surfaces
        ]
        return {
            "mode": "offline",
            "cutoff": cutoff_iso,
            "partial": False,
            "receipts": skipped,
            "candidates": [],
        }

    fn = fetcher or _default_fetcher
    checked_at = cutoff_iso
    receipts: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    story_drops: list[dict[str, Any]] = []

    for entry in surfaces:
        source = entry["source"]
        surface_url = entry["surface"]
        kind = entry["kind"]
        source_name = entry["source_name"]
        distribution_weight = entry.get("distribution_weight") or "standard"
        allowed_hosts = tuple(entry.get("allowed_hosts") or ()) or _allowed_hosts_for_surface(
            source, kind
        )
        try:
            data = fn(surface_url)
            parsed = parse_surface(
                kind,
                data,
                surface=surface_url,
                cutoff=cutoff,
                source_name=source_name,
                distribution_weight=distribution_weight,
                allowed_hosts=allowed_hosts or ("bloomberg.com",),
            )
            for dropped in parsed.get("dropped") or []:
                story_drops.append(
                    _drop_row(
                        dropped,
                        source=source,
                        stage="relevance_rejection",
                        reason=str(dropped.get("reason") or "mechanical_drop"),
                    )
                )
            feed_parse = parsed.get("feed_parse") or (
                "parsed" if parsed["raw_count"] > 0 else "empty"
            )
            if feed_parse == "unparsed":
                receipts.append(
                    _receipt(
                        source,
                        checked_at=checked_at,
                        status="failed",
                        candidate_count=0,
                        result_count=0,
                        failure="unparsed_feed_items",
                        surface=surface_url,
                        feed_health="zero_item_parse",
                    )
                )
                continue
            survivors, recall_drops = _apply_recall_and_ceiling(parsed["items"], source=source)
            story_drops.extend(recall_drops)
            raw_count = int(parsed["raw_count"])
            result_count = len(survivors)
            if result_count > 0:
                feed_health = "candidates"
            elif raw_count == 0:
                feed_health = "empty_feed"
            elif not parsed["items"]:
                feed_health = "no_in_window"
            else:
                feed_health = "no_relevant_candidates"
            receipts.append(
                _receipt(
                    source,
                    checked_at=checked_at,
                    status="ok",
                    candidate_count=raw_count,
                    result_count=result_count,
                    failure=None,
                    surface=surface_url,
                    feed_health=feed_health,
                )
            )
            candidates.extend(survivors)
        except Exception as exc:  # noqa: BLE001
            receipts.append(
                _receipt(
                    source,
                    checked_at=checked_at,
                    status="failed",
                    candidate_count=0,
                    result_count=0,
                    failure=str(exc),
                    surface=surface_url,
                    feed_health="fetch_failed",
                )
            )

    seen_urls: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in candidates:
        url = str(item.get("url") or "")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        deduped.append(item)

    statuses = {r["source"]: r["status"] for r in receipts if r["source"] in REQUIRED_SOURCES}
    partial = (
        statuses.get("bloomberg") == "failed" and statuses.get("reuters") == "ok"
    ) or (statuses.get("reuters") == "failed" and statuses.get("bloomberg") == "ok")

    return {
        "mode": "live",
        "cutoff": cutoff_iso,
        "partial": partial,
        "receipts": receipts,
        "candidates": deduped,
        "story_drops": story_drops,
    }


__all__ = [
    "BLOOMBERG_QUERY",
    "BLOOMBERG_SURFACE",
    "Fetcher",
    "MARKET_TOKENS",
    "NOISE_EXCLUDE",
    "OFFICIAL_SOURCES",
    "REQUIRED_SOURCES",
    "REUTERS_SURFACE",
    "SAFETY_CEILING_APPLIED",
    "acquire_current_news",
    "attribute_country_codes",
    "merge_live_news",
]
