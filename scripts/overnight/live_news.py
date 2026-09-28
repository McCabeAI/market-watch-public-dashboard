"""Live Bloomberg / Reuters discovery for overnight collect (no article HTML)."""

from __future__ import annotations

import email.utils
import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse, quote

from scripts.overnight.clock import isoformat, now_ny, parse_iso

Fetcher = Callable[[str], bytes]

BLOOMBERG_QUERY = (
    "site:bloomberg.com (Federal Reserve OR FOMC OR inflation OR CPI OR payrolls OR Treasury OR yields "
    "OR oil OR Brent OR crude OR Hormuz OR OPEC OR FX OR dollar OR tariff OR sanctions OR "
    '"central bank" OR RBA OR "Bank of Canada" OR RBNZ OR ECB OR "Bank of Japan")'
)
BLOOMBERG_SURFACE = (
    f"https://www.bing.com/news/search?q={quote(BLOOMBERG_QUERY)}&format=rss&qft=interval%3d%227%22"
)
REUTERS_SURFACE = "https://www.reuters.com/arc/outboundfeeds/news-sitemap/?outputType=xml"

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

ENERGY_TOKENS = ("oil", "crude", "brent", "hormuz", "opec")
RATES_INFLATION_FED = ("treasury", "yield", "inflation", "cpi", "fed", "fomc")
FX_TARIFF = ("fx", "tariff", "sanction", "dollar", "forex", "currency")

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

REUTERS_HEADLINE_ONLY = "Headline-only public metadata; article body was not retrieved."

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


_USER_AGENT = (
    "MarketWatch-Public-News-Discovery/1.0 "
    "(McCabeAI market-watch-public-dashboard; lawful RSS/sitemap discovery only)"
)


def _default_fetcher(url: str) -> bytes:
    import urllib.request

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def _collapse_ws(text: str, max_len: int = 400) -> str:
    collapsed = re.sub(r"\s+", " ", (text or "").strip())
    if len(collapsed) <= max_len:
        return collapsed
    return collapsed[: max_len - 1].rstrip() + "…"


def _canonical_from_bing_link(link: str) -> str | None:
    parsed = urlparse(link)
    qs = parse_qs(parsed.query)
    raw = qs.get("url", [None])[0]
    if not raw:
        return None
    url = unquote(raw)
    if url.startswith("http://"):
        url = "https://" + url[7:]
    host = urlparse(url).netloc.lower()
    if host.endswith("bloomberg.com") or host.endswith("reuters.com"):
        return url
    return None


def _headline_clean(title: str) -> str:
    t = (title or "").strip()
    for suffix in (" - Bloomberg.com", " - Bloomberg"):
        if t.endswith(suffix):
            t = t[: -len(suffix)].strip()
    return t


def _contains_market_token(blob: str, tok: str) -> bool:
    if " " in tok:
        return tok in blob
    return re.search(rf"\b{re.escape(tok)}\b", blob, flags=re.IGNORECASE) is not None


def _text_matches_market_gate(headline: str, snippet: str) -> bool:
    blob = f"{headline} {snippet}".lower()
    has_macro = any(_contains_market_token(blob, tok) for tok in MARKET_TOKENS)
    if not has_macro:
        return False
    policy_tokens = (
        *ENERGY_TOKENS,
        *RATES_INFLATION_FED,
        "fx",
        "forex",
        "dollar",
        "currency",
        "tariff",
        "sanction",
        "central bank",
        "rba",
        "rbnz",
        "bank of canada",
        "boc",
        "ecb",
        "bank of japan",
        "boj",
        "fed",
        "fomc",
    )
    energy_rates_fx_policy = any(_contains_market_token(blob, tok) for tok in policy_tokens)
    if not energy_rates_fx_policy and any(noise in blob for noise in NOISE_EXCLUDE):
        return False
    return True


def _primary_category(headline: str, snippet: str) -> str:
    blob = f"{headline} {snippet}".lower()
    if any(_contains_market_token(blob, t) for t in ENERGY_TOKENS):
        return "energy"
    if _contains_market_token(blob, "cpi") or _contains_market_token(blob, "inflation"):
        return "inflation"
    if any(
        _contains_market_token(blob, t)
        for t in ("fed", "fomc", "central bank", "rate cut", "rate hike", "policy rate")
    ):
        return "monetary_policy"
    if _contains_market_token(blob, "treasury") or _contains_market_token(blob, "yield"):
        return "rates"
    if any(_contains_market_token(blob, t) for t in ("dollar", "fx", "forex", "currency")):
        return "fx"
    if any(_contains_market_token(blob, t) for t in ("iran", "hormuz", "sanction", "tariff")):
        return "geopolitics"
    return "macro"


def _parse_pub_rss(pub: str) -> datetime | None:
    if not pub:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(pub)
        return now_ny(dt)
    except (TypeError, ValueError, OverflowError):
        return None


def _parse_pub_iso(pub: str) -> datetime | None:
    if not pub:
        return None
    try:
        return parse_iso(pub.replace("Z", "+00:00") if pub.endswith("Z") else pub)
    except ValueError:
        return None


def _publisher_family(source_name: str) -> str:
    if source_name == "Bloomberg":
        return "bloomberg"
    if source_name == "Reuters":
        return "reuters"
    return source_name.lower()


def _parse_bing_rss(data: bytes, *, surface: str, cutoff: datetime) -> tuple[int, list[dict[str, Any]]]:
    window_start = cutoff - timedelta(hours=24)
    out: list[dict[str, Any]] = []
    raw_count = 0
    root = ET.fromstring(data)
    channel = root.find("channel")
    if channel is None:
        return 0, out
    for item in channel.findall("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        pub_el = item.find("pubDate")
        desc_el = item.find("description")
        source_el = item.find("Source")
        headline = _headline_clean(title_el.text if title_el is not None else "")
        link = link_el.text if link_el is not None else ""
        canonical = _canonical_from_bing_link(link)
        if not canonical:
            continue
        source_name = (source_el.text if source_el is not None else "").strip() or "Bloomberg"
        if "bloomberg" not in canonical.lower():
            continue
        source_name = "Bloomberg"
        raw_count += 1
        path = urlparse(canonical).path.lower()
        if "/video" in path or "/newsletter" in path or "/podcast" in path:
            continue
        snippet = _collapse_ws(_strip_html(desc_el.text if desc_el is not None else ""))
        if not _text_matches_market_gate(headline, snippet):
            continue
        published = _parse_pub_rss(pub_el.text if pub_el is not None else "")
        if published is None or published > cutoff or published < window_start:
            continue
        out.append(
            {
                "published_at": isoformat(published),
                "url": canonical,
                "headline": headline,
                "summary": snippet,
                "source_name": source_name,
                "verification_status": "single_source",
                "primary_category": _primary_category(headline, snippet),
                "country_codes": attribute_country_codes(headline, snippet),
                "discovery_surface": surface,
                "distribution_weight": "high",
            }
        )
    out.sort(key=lambda x: x["published_at"], reverse=True)
    return raw_count, out[:8]


def _parse_reuters_sitemap(data: bytes, *, surface: str, cutoff: datetime) -> tuple[int, list[dict[str, Any]]]:
    window_start = cutoff - timedelta(hours=24)
    ns = {
        "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
        "news": "http://www.google.com/schemas/sitemap-news/0.9",
    }
    out: list[dict[str, Any]] = []
    raw_count = 0
    root = ET.fromstring(data)
    for url_el in root.findall("sm:url", ns):
        loc_el = url_el.find("sm:loc", ns)
        news_el = url_el.find("news:news", ns)
        if loc_el is None or news_el is None:
            continue
        title_el = news_el.find("news:title", ns)
        pub_el = news_el.find("news:publication_date", ns)
        name_el = news_el.find("news:publication/news:name", ns)
        headline = (title_el.text if title_el is not None else "").strip()
        loc = (loc_el.text if loc_el is not None else "").strip()
        if not headline or not loc:
            continue
        raw_count += 1
        snippet = REUTERS_HEADLINE_ONLY
        if not _text_matches_market_gate(headline, snippet):
            continue
        published = _parse_pub_iso(pub_el.text if pub_el is not None else "")
        if published is None or published > cutoff or published < window_start:
            continue
        pub_name = (name_el.text if name_el is not None else "").strip() or "Reuters"
        if pub_name != "Reuters":
            continue
        out.append(
            {
                "published_at": isoformat(published),
                "url": loc,
                "headline": headline,
                "summary": snippet,
                "source_name": "Reuters",
                "verification_status": "single_source",
                "primary_category": _primary_category(headline, snippet),
                "country_codes": attribute_country_codes(headline, snippet),
                "discovery_surface": surface,
                "distribution_weight": "standard",
            }
        )
    out.sort(key=lambda x: x["published_at"], reverse=True)
    return raw_count, out[:8]


def _receipt(
    source: str,
    *,
    checked_at: str,
    status: str,
    candidate_count: int,
    result_count: int,
    failure: str | None,
    surface: str | None,
) -> dict[str, Any]:
    return {
        "source": source,
        "checked_at": checked_at,
        "status": status,
        "candidate_count": candidate_count,
        "result_count": result_count,
        "failure": failure,
        "surface": surface,
    }


def _fetch_source(
    source: str,
    surface: str,
    fetcher: Fetcher,
    cutoff: datetime,
    checked_at: str,
    parser: Callable[..., tuple[int, list[dict[str, Any]]]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        data = fetcher(surface)
        raw_count, candidates = parser(data, surface=surface, cutoff=cutoff)
        return (
            _receipt(
                source,
                checked_at=checked_at,
                status="ok",
                candidate_count=raw_count,
                result_count=len(candidates),
                failure=None,
                surface=surface,
            ),
            candidates,
        )
    except Exception as exc:  # noqa: BLE001
        return (
            _receipt(
                source,
                checked_at=checked_at,
                status="failed",
                candidate_count=0,
                result_count=0,
                failure=str(exc),
                surface=surface,
            ),
            [],
        )


def acquire_current_news(
    *,
    when: datetime,
    offline: bool = False,
    fetcher: Fetcher | None = None,
) -> dict[str, Any]:
    """Return {mode, cutoff, partial, receipts, candidates}."""
    cutoff = now_ny(when)
    cutoff_iso = isoformat(cutoff)
    if offline:
        skipped = [
            _receipt(
                src,
                checked_at=cutoff_iso,
                status="skipped",
                candidate_count=0,
                result_count=0,
                failure=None,
                surface=None,
            )
            for src in REQUIRED_SOURCES
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

    bloomberg_receipt, bloomberg_items = _fetch_source(
        "bloomberg",
        BLOOMBERG_SURFACE,
        fn,
        cutoff,
        checked_at,
        _parse_bing_rss,
    )
    receipts.append(bloomberg_receipt)
    candidates.extend(bloomberg_items)

    reuters_receipt, reuters_items = _fetch_source(
        "reuters",
        REUTERS_SURFACE,
        fn,
        cutoff,
        checked_at,
        _parse_reuters_sitemap,
    )
    receipts.append(reuters_receipt)
    candidates.extend(reuters_items)

    statuses = {r["source"]: r["status"] for r in receipts}
    partial = (
        statuses.get("bloomberg") == "failed" and statuses.get("reuters") == "ok"
    ) or (statuses.get("reuters") == "failed" and statuses.get("bloomberg") == "ok")

    return {
        "mode": "live",
        "cutoff": cutoff_iso,
        "partial": partial,
        "receipts": receipts,
        "candidates": candidates,
    }


def _tokenize_headline(headline: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9']+", (headline or "").lower())
    return {t for t in tokens if len(t) > 2 and t not in DEDUP_STOP}


def _same_event(a: str, b: str) -> bool:
    ta, tb = _tokenize_headline(a), _tokenize_headline(b)
    if not ta or not tb:
        return False
    shared = ta & tb
    if len(shared) < 4:
        return False
    union = ta | tb
    jaccard = len(shared) / len(union) if union else 0.0
    return jaccard >= 0.55


def _edge_from_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_name": item.get("source_name"),
        "url": item.get("url"),
        "headline": item.get("headline"),
        "published_at": item.get("published_at"),
        "snippet": item.get("summary") or item.get("snippet"),
        "distribution_weight": item.get("distribution_weight") or "standard",
        "discovery_surface": item.get("discovery_surface"),
    }


def _stable_id(edges: list[dict[str, Any]]) -> str:
    urls = sorted({str(e.get("url") or "") for e in edges if e.get("url")})
    digest = hashlib.sha256("|".join(urls).encode("utf-8")).hexdigest()[:16]
    return f"news:{digest}"


def _verification_from_edges(edges: list[dict[str, Any]], prior_statuses: list[str] | None = None) -> str:
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


def _salience_components(item: dict[str, Any], edges: list[dict[str, Any]], when: datetime, from_live: bool) -> dict[str, int]:
    text = f"{item.get('headline') or ''} {item.get('summary') or ''}".lower()
    tier3 = ("fed", "fomc", "inflation", "cpi", "payroll", "treasury", "yield", "oil", "crude", "brent", "hormuz", "fx", "dollar", "tariff", "central bank")
    tier1_relevance = (
        3
        if any(_contains_market_token(text, t) for t in tier3)
        else (2 if any(_contains_market_token(text, t) for t in MARKET_TOKENS) else 0)
    )
    if any(_contains_market_token(text, t) for t in ENERGY_TOKENS) or any(
        _contains_market_token(text, t) for t in RATES_INFLATION_FED
    ):
        transmission = 3
    elif any(_contains_market_token(text, t) for t in FX_TARIFF):
        transmission = 2
    else:
        transmission = 1
    distribution_weight = 2 if any(str(e.get("source_name")) == "Bloomberg" for e in edges) else 0
    cutoff = now_ny(when)
    try:
        pub = parse_iso(str(item.get("published_at") or ""))
    except ValueError:
        pub = cutoff
    recency = 2 if (cutoff - pub) <= timedelta(hours=12) else 0
    novelty = 2 if from_live else 0
    return {
        "tier1_relevance": tier1_relevance,
        "transmission": transmission,
        "novelty": novelty,
        "distribution_weight": distribution_weight,
        "recency": recency,
    }


def _apply_salience(item: dict[str, Any], edges: list[dict[str, Any]], when: datetime, from_live: bool) -> None:
    components = _salience_components(item, edges, when, from_live)
    score = sum(components.values())
    distribution = "high" if any(str(e.get("source_name")) == "Bloomberg" for e in edges) else "standard"
    item["market_salience"] = {
        "score": score,
        "distribution": distribution,
        "components": components,
    }


def _merge_cluster(
    baseline_items: list[dict[str, Any]],
    live_items: list[dict[str, Any]],
    when: datetime,
) -> dict[str, Any]:
    edges: list[dict[str, Any]] = []
    for raw in baseline_items + live_items:
        if raw.get("source_edges"):
            edges.extend(dict(e) for e in raw["source_edges"])
        else:
            edges.append(_edge_from_item(raw))

    # Deduplicate edges by url
    seen_urls: set[str] = set()
    unique_edges: list[dict[str, Any]] = []
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

    merged: dict[str, Any] = {
        "headline": display.get("headline"),
        "url": display.get("url"),
        "summary": baseline_items[0].get("summary") if baseline_items else (live_items[0].get("summary") if live_items else ""),
        "published_at": published_at,
        "source_name": display.get("source_name"),
        "verification_status": _verification_from_edges(unique_edges, prior_statuses),
        "primary_category": (live_items[0] if live_items else baseline_items[0]).get("primary_category", "macro"),
        "country_codes": (live_items[0] if live_items else baseline_items[0]).get("country_codes", ["US"]),
        "source_edges": unique_edges,
        "id": _stable_id(unique_edges),
    }
    if not merged["summary"] and live_items:
        merged["summary"] = live_items[0].get("summary", "")
    _apply_salience(merged, unique_edges, when, from_live)
    return merged


def _cap_items(items: list[dict[str, Any]], baseline_urls: set[str], live_urls: set[str]) -> list[dict[str, Any]]:
    if len(items) <= 16:
        return items

    def has_live_bloomberg(item: dict[str, Any]) -> bool:
        for e in item.get("source_edges") or []:
            if e.get("source_name") == "Bloomberg" and str(e.get("url") or "") in live_urls:
                return True
        return False

    def is_live_only(item: dict[str, Any]) -> bool:
        edges = item.get("source_edges") or []
        urls = {str(e.get("url") or "") for e in edges}
        return bool(urls & live_urls) and not bool(urls & baseline_urls)

    def is_baseline_only(item: dict[str, Any]) -> bool:
        edges = item.get("source_edges") or []
        urls = {str(e.get("url") or "") for e in edges}
        return bool(urls & baseline_urls) and not bool(urls & live_urls)

    kept = list(items)
    while len(kept) > 16:
        droppable = [
            i
            for i in kept
            if is_live_only(i) and not has_live_bloomberg(i)
        ]
        if droppable:
            droppable.sort(key=lambda x: x.get("market_salience", {}).get("score", 0))
            kept.remove(droppable[0])
            continue
        droppable = [i for i in kept if is_baseline_only(i)]
        if droppable:
            droppable.sort(key=lambda x: x.get("market_salience", {}).get("score", 0))
            kept.remove(droppable[0])
            continue
        kept.sort(key=lambda x: x.get("market_salience", {}).get("score", 0))
        kept.pop(0)
    return kept


def merge_live_news(
    *,
    baseline: list[dict[str, Any]],
    live_candidates: list[dict[str, Any]],
    when: datetime,
) -> dict[str, Any]:
    """Return {items, research_supplement}."""
    baseline_urls = {str(i.get("url") or "") for i in baseline if i.get("url")}
    live_urls = {str(i.get("url") or "") for i in live_candidates if i.get("url")}

    clusters: list[dict[str, Any]] = []
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

    for item in live_candidates:
        headline = str(item.get("headline") or "")
        matched = False
        for cluster in clusters:
            if _same_event(headline, str(cluster["headline"])):
                cluster["live"].append(item)
                matched = True
                break
        if not matched:
            clusters.append({"headline": headline, "baseline": [], "live": [item]})

    merged_items: list[dict[str, Any]] = []
    for cluster in clusters:
        merged_items.append(_merge_cluster(cluster["baseline"], cluster["live"], when))

    merged_items = _cap_items(merged_items, baseline_urls, live_urls)

    merged_items.sort(
        key=lambda x: (
            (x.get("market_salience") or {}).get("score", 0),
            x.get("published_at") or "",
        ),
        reverse=True,
    )

    flat_sources: list[dict[str, Any]] = []
    for item in merged_items:
        flat_sources.extend(item.get("source_edges") or [])

    top_ids = [item["id"] for item in merged_items[:3]]

    supplement = {
        "summary": None,
        "news": merged_items,
        "central_bank_research": [],
        "sources": flat_sources,
        "top_market_driver_candidates": top_ids,
        "presentation_caps": {"last_24_hours": 6, "top_market_drivers": 3},
    }
    return {"items": merged_items, "research_supplement": supplement}
