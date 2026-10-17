"""Cluster baseline and live news, score transmission, rank for presentation."""

from __future__ import annotations

import hashlib
import re

from scripts.overnight.clock import isoformat, now_ny, parse_iso
from scripts.overnight.news_relevance import (
    _any_phrase,
    _any_word,
    _hormuz_acute,
    _hormuz_diplomatic,
    _hormuz_mentioned,
    _india_named,
    _oil_supply_role,
    _phrase,
    _vietnam_named,
    _word,
    apply_transmission,
)

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

DEDUP_STOP = frozenset(
    {"the", "and", "for", "after", "with", "says", "said", "its", "won", "will", "not"}
)

_PRESENTATION_CAP = 24
_TWELVE_HOURS_SECONDS = 12 * 3600


def _tokenize_headline(headline: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9']+", (headline or "").lower())
    filtered = {t for t in tokens if len(t) > 2 and t not in DEDUP_STOP}
    return {"hormuz" if t == "ormuz" else t for t in filtered}


def _loose_oil_word(text: str) -> bool:
    return _any_word(text, ("oil", "crude", "hormuz", "supply")) or _word(text, "ormuz")


def _headline_facet(headline: str) -> str:
    text = (headline or "").lower()
    # A supply role outranks a domestic trade/GDP phrase on the same headline
    # so an export halt is not clustered into the suppressed domestic story.
    if _india_named(text) and _oil_supply_role(text):
        return "india_oil"
    if _india_named(text) and _any_phrase(
        text, ("trade deficit", "trade gap", "import bill")
    ):
        return "india_trade"
    if _india_named(text) and _loose_oil_word(text):
        return "india_oil"
    if _vietnam_named(text) and _oil_supply_role(text):
        return "vietnam_oil"
    if _vietnam_named(text) and _word(text, "gdp"):
        return "vietnam_gdp"
    if _vietnam_named(text) and _loose_oil_word(text):
        return "vietnam_oil"
    if _hormuz_mentioned(text) and _hormuz_diplomatic(text) and not _hormuz_acute(text):
        return "hormuz_diplomacy"
    if _hormuz_mentioned(text):
        return "hormuz_supply"
    tokens = _tokenize_headline(headline)
    if "coreweave" in tokens and (
        _word(text, "cds")
        or _phrase(text, "credit default")
        or _word(text, "debt")
        or _word(text, "distress")
    ):
        return "coreweave_cds"
    if "coreweave" in tokens:
        return "coreweave_other"
    return ""


def _same_event(a: str, b: str) -> bool:
    ta, tb = _tokenize_headline(a), _tokenize_headline(b)
    if not ta or not tb:
        return False
    fa, fb = _headline_facet(a), _headline_facet(b)
    if fa and fb and fa != fb:
        return False
    if ("coreweave" in ta) ^ ("coreweave" in tb):
        return False
    shared = ta & tb
    if len(shared) < 4:
        return False
    if fa and fb and fa == fb:
        return True
    union = ta | tb
    jaccard = len(shared) / len(union) if union else 0.0
    return jaccard >= 0.55


def _publisher_family(source_name: str) -> str:
    if source_name == "Bloomberg":
        return "bloomberg"
    if source_name == "Reuters":
        return "reuters"
    return source_name.lower()


def _edge_from_item(item: dict) -> dict:
    return {
        "source_name": item.get("source_name"),
        "url": item.get("url"),
        "headline": item.get("headline"),
        "published_at": item.get("published_at"),
        "snippet": item.get("summary") or item.get("snippet"),
        "distribution_weight": item.get("distribution_weight") or "standard",
        "discovery_surface": item.get("discovery_surface"),
    }


def _stable_id(edges: list[dict]) -> str:
    urls = sorted({str(e.get("url") or "") for e in edges if e.get("url")})
    digest = hashlib.sha256("|".join(urls).encode("utf-8")).hexdigest()[:16]
    return f"news:{digest}"


def _verification_from_edges(edges: list[dict], prior_statuses: list[str] | None = None) -> str:
    """Publisher count can corroborate. It must not downgrade a baseline status."""
    if any(str(e.get("source_name") or "") in OFFICIAL_SOURCES for e in edges):
        return "official"
    families = {_publisher_family(str(e.get("source_name") or "")) for e in edges if e.get("source_name")}
    if len(families) >= 2:
        return "corroborated"
    for status in prior_statuses or []:
        if status in {"official", "corroborated", "single_source", "unverified"}:
            return status
    return "single_source"


def _merge_cluster(
    baseline_items: list[dict],
    live_items: list[dict],
) -> tuple[dict, bool]:
    edges: list[dict] = []
    for raw in baseline_items + live_items:
        if raw.get("source_edges"):
            edges.extend(dict(e) for e in raw["source_edges"])
        else:
            edges.append(_edge_from_item(raw))

    seen_urls: set[str] = set()
    unique_edges: list[dict] = []
    for e in edges:
        url = str(e.get("url") or "")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        unique_edges.append(e)

    bloomberg_edges = [e for e in unique_edges if e.get("source_name") == "Bloomberg"]
    if bloomberg_edges:
        bloomberg_edges.sort(key=lambda e: e.get("published_at") or "", reverse=True)
        display = bloomberg_edges[0]
    else:
        unique_edges.sort(key=lambda e: e.get("published_at") or "", reverse=True)
        display = unique_edges[0]

    from_live = bool(live_items)
    published_at = max((e.get("published_at") or "") for e in unique_edges)
    prior_statuses = [str(item.get("verification_status") or "") for item in baseline_items]
    chosen_raw = live_items[0] if live_items else baseline_items[0]

    merged: dict = {
        "headline": display.get("headline"),
        "url": display.get("url"),
        "summary": baseline_items[0].get("summary") if baseline_items else (live_items[0].get("summary") if live_items else ""),
        "published_at": published_at,
        "source_name": display.get("source_name"),
        "verification_status": _verification_from_edges(unique_edges, prior_statuses),
        "primary_category": chosen_raw.get("primary_category", "macro"),
        "country_codes": chosen_raw.get("country_codes", ["US"]),
        "source_edges": unique_edges,
        "id": _stable_id(unique_edges),
    }
    if not merged["summary"] and live_items:
        merged["summary"] = live_items[0].get("summary", "")

    try:
        merged["published_at"] = isoformat(parse_iso(str(merged.get("published_at") or "")))
    except ValueError:
        pass

    return merged, from_live


def _recency_component(published_at: str | None, when) -> int:
    if not published_at:
        return 0
    try:
        pub = parse_iso(str(published_at))
    except ValueError:
        return 0
    cutoff = now_ny(when)
    if pub > cutoff:
        return 0
    if (cutoff - pub).total_seconds() > _TWELVE_HOURS_SECONDS:
        return 0
    return 1


def _apply_tie_break(item: dict, edges: list[dict], when, from_live: bool) -> None:
    transmission = item.get("transmission") or {}
    trans_score = int(transmission.get("score") or 0)

    recency = _recency_component(item.get("published_at"), when)
    novelty = 1 if from_live else 0
    distribution_weight = 1 if any(str(e.get("source_name") or "") == "Bloomberg" for e in edges) else 0
    tie_break = recency + novelty + distribution_weight

    salience = dict(item.get("market_salience") or {})
    components = dict(salience.get("components") or {})
    components["recency"] = recency
    components["novelty"] = novelty
    components["distribution_weight"] = distribution_weight

    distribution = "high" if distribution_weight else "standard"
    item["market_salience"] = {
        "score": max(0, trans_score) + tie_break,
        "distribution": distribution,
        "components": components,
    }


def _disposition(item: dict) -> str:
    transmission = item.get("transmission") or {}
    return str(transmission.get("disposition") or "")


def _reason_code(item: dict) -> str:
    transmission = item.get("transmission") or {}
    return str(transmission.get("reason_code") or "")


def _rank_key(item: dict) -> tuple:
    score = (item.get("market_salience") or {}).get("score", 0)
    published = item.get("published_at") or ""
    return (score, published)


def _diagnostics_row(item: dict, stage: str, reason: str) -> dict:
    return {
        "headline": item.get("headline"),
        "url": item.get("url"),
        "source": item.get("source_name"),
        "published_at": item.get("published_at"),
        "stage": stage,
        "reason": reason,
    }


def _cluster_baseline_live(baseline: list[dict], live: list[dict]) -> list[dict]:
    clusters: list[dict] = []
    for item in baseline:
        headline = str(item.get("headline") or "")
        matched = False
        for cluster in clusters:
            if _same_event(headline, str(cluster["headline"])):
                cluster["baseline"].append(item)
                matched = True
                break
        if not matched:
            clusters.append({"headline": headline, "baseline": [item], "live": []})

    for item in live:
        headline = str(item.get("headline") or "")
        matched = False
        for cluster in clusters:
            if _same_event(headline, str(cluster["headline"])):
                cluster["live"].append(item)
                matched = True
                break
        if not matched:
            clusters.append({"headline": headline, "baseline": [], "live": [item]})

    return clusters


def cluster_and_rank(baseline: list, live: list, when) -> dict:
    clusters = _cluster_baseline_live(baseline, live)

    assessed: list[dict] = []
    for cluster in clusters:
        merged, from_live = _merge_cluster(cluster["baseline"], cluster["live"])
        item = apply_transmission(merged)
        _apply_tie_break(item, item.get("source_edges") or [], when, from_live)
        assessed.append(item)

    eligible = [i for i in assessed if _disposition(i) in {"show", "assess"}]
    eligible.sort(key=_rank_key, reverse=True)
    shown_items = eligible[:_PRESENTATION_CAP]
    shown_ids = {i.get("id") for i in shown_items}

    diagnostics_rows: list[dict] = []
    for item in assessed:
        disp = _disposition(item)
        reason = _reason_code(item)
        if disp in {"suppress", "hold-for-review"}:
            diagnostics_rows.append(_diagnostics_row(item, "relevance_rejection", reason))
        elif disp in {"show", "assess"}:
            if item.get("id") in shown_ids:
                diagnostics_rows.append(_diagnostics_row(item, "shown", reason))
            else:
                diagnostics_rows.append(_diagnostics_row(item, "presentation_suppression", reason))

    items = list(shown_items)

    flat_sources: list[dict] = []
    for item in items:
        flat_sources.extend(item.get("source_edges") or [])

    top_ids = [item["id"] for item in items[:3]]

    research_supplement = {
        "summary": None,
        "news": items,
        "central_bank_research": [],
        "sources": flat_sources,
        "top_market_driver_candidates": top_ids,
        "presentation_caps": {"last_24_hours": 6, "top_market_drivers": 3},
    }

    return {
        "items": items,
        "research_supplement": research_supplement,
        "diagnostics_rows": diagnostics_rows,
    }


def merge_live_news(
    *,
    baseline: list,
    live_candidates: list,
    when,
) -> dict:
    return cluster_and_rank(baseline, live_candidates, when)
