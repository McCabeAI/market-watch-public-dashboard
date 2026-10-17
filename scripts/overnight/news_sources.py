"""Discovery surface definitions and mechanical parsers (no relevance gates)."""

from __future__ import annotations

import email.utils
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse, quote

from scripts.overnight.clock import isoformat, now_ny, parse_iso

DISCOVERY_USER_AGENT = (
    "MarketWatch-Public-News-Discovery/1.0 "
    "(McCabeAI market-watch-public-dashboard; lawful RSS/sitemap discovery only)"
)

BLOOMBERG_QUERY = (
    "site:bloomberg.com (Federal Reserve OR FOMC OR inflation OR CPI OR payrolls OR Treasury OR yields "
    "OR oil OR Brent OR crude OR Hormuz OR OPEC OR FX OR dollar OR tariff OR sanctions OR "
    '"central bank" OR RBA OR "Bank of Canada" OR RBNZ OR ECB OR "Bank of Japan")'
)

BLOOMBERG_CREDIT_QUERY = (
    "site:bloomberg.com (CoreWeave OR neocloud OR \"data center\" OR hyperscaler) "
    "(bond OR debt OR financing OR \"credit facility\" OR IPO OR CDS OR \"credit default\")"
)

BLOOMBERG_EQUITY_QUERY = (
    'site:bloomberg.com ("S&P 500" OR Nasdaq OR "bank stocks" OR selloff) '
    "(Fed OR yields OR dollar OR Treasury)"
)

REUTERS_CREDIT_QUERY = (
    'site:reuters.com ("private credit" OR "high-yield" OR "credit spread" OR CLO OR "funding stress" '
    'OR CoreWeave OR CDS OR "credit default")'
)

REUTERS_SURFACE = "https://www.reuters.com/arc/outboundfeeds/news-sitemap/?outputType=xml"

REUTERS_HEADLINE_ONLY = "Headline-only public metadata; article body was not retrieved."

CNBC_SITEMAP_URL = "https://www.cnbc.com/sitemap_news.xml"
CNBC_HEADLINE_ONLY = "Headline-only public metadata; article body was not retrieved."
CNBC_CREDIT_QUERY = (
    'site:cnbc.com (CoreWeave OR CDS OR "credit default" OR "credit default swap")'
)

_BING_QFT = "interval%3d%227%22"

ENERGY_TOKENS = ("oil", "crude", "brent", "hormuz", "opec")

_ATOM_NS = "http://www.w3.org/2005/Atom"

_BOJ_BOE_SURFACE_MARKERS = (
    "boj.or.jp/en/rss/whatsnew",
    "bankofengland.co.uk/rss/news",
)


def _bing_surface(query: str) -> str:
    return (
        f"https://www.bing.com/news/search?q={quote(query)}&format=rss&qft={_BING_QFT}"
    )


def discovery_surfaces() -> list[dict[str, Any]]:
    return [
        {
            "source": "bloomberg",
            "surface": _bing_surface(BLOOMBERG_QUERY),
            "kind": "bing_rss",
            "source_name": "Bloomberg",
            "distribution_weight": "high",
        },
        {
            "source": "reuters",
            "surface": REUTERS_SURFACE,
            "kind": "reuters_sitemap",
            "source_name": "Reuters",
            "distribution_weight": "standard",
        },
        {
            "source": "bloomberg_credit",
            "surface": _bing_surface(BLOOMBERG_CREDIT_QUERY),
            "kind": "bing_rss",
            "source_name": "Bloomberg",
            "distribution_weight": "high",
        },
        {
            "source": "bloomberg_equity",
            "surface": _bing_surface(BLOOMBERG_EQUITY_QUERY),
            "kind": "bing_rss",
            "source_name": "Bloomberg",
            "distribution_weight": "high",
        },
        {
            "source": "reuters_credit",
            "surface": _bing_surface(REUTERS_CREDIT_QUERY),
            "kind": "bing_rss",
            "source_name": "Reuters",
            "distribution_weight": "standard",
        },
        {
            "source": "cnbc",
            "surface": CNBC_SITEMAP_URL,
            "kind": "cnbc_sitemap",
            "source_name": "CNBC",
            "distribution_weight": "standard",
        },
        {
            "source": "cnbc_credit",
            "surface": _bing_surface(CNBC_CREDIT_QUERY),
            "kind": "bing_rss",
            "source_name": "CNBC",
            "distribution_weight": "standard",
            "allowed_hosts": ("cnbc.com",),
        },
        {
            "source": "fed_monetary",
            "surface": "https://www.federalreserve.gov/feeds/press_monetary.xml",
            "kind": "rss_official",
            "source_name": "Federal Reserve",
            "distribution_weight": "standard",
        },
        {
            "source": "boc_press",
            "surface": "https://www.bankofcanada.ca/content_type/press/feed/",
            "kind": "rss_official",
            "source_name": "Bank of Canada",
            "distribution_weight": "standard",
        },
        {
            "source": "rba_media",
            "surface": "https://www.rba.gov.au/rss/rss-cb-media-releases.xml",
            "kind": "rss_official",
            "source_name": "Reserve Bank of Australia",
            "distribution_weight": "standard",
        },
        {
            "source": "ecb_press",
            "surface": "https://www.ecb.europa.eu/rss/press.html",
            "kind": "rss_official",
            "source_name": "European Central Bank",
            "distribution_weight": "standard",
        },
        {
            "source": "boj_whatsnew",
            "surface": "https://www.boj.or.jp/en/rss/whatsnew.xml",
            "kind": "rss_official",
            "source_name": "Bank of Japan",
            "distribution_weight": "standard",
        },
        {
            "source": "boe_news",
            "surface": "https://www.bankofengland.co.uk/rss/news",
            "kind": "rss_official",
            "source_name": "Bank of England",
            "distribution_weight": "standard",
        },
    ]


def parse_surface(
    kind: str,
    data: bytes,
    *,
    surface: str,
    cutoff: datetime,
    source_name: str,
    distribution_weight: str = "standard",
    allowed_hosts: tuple[str, ...] = ("bloomberg.com",),
) -> dict[str, Any]:
    if kind == "bing_rss":
        return _parse_bing_rss(
            data,
            surface=surface,
            cutoff=cutoff,
            source_name=source_name,
            distribution_weight=distribution_weight,
            allowed_hosts=allowed_hosts,
        )
    if kind == "reuters_sitemap":
        return _parse_reuters_sitemap(data, surface=surface, cutoff=cutoff)
    if kind == "cnbc_sitemap":
        return _parse_cnbc_sitemap(data, surface=surface, cutoff=cutoff)
    if kind == "rss_official":
        return _parse_rss_official(
            data,
            surface=surface,
            cutoff=cutoff,
            source_name=source_name,
            distribution_weight=distribution_weight,
        )
    return {"raw_count": 0, "items": [], "dropped": []}


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
    if (
        host.endswith("bloomberg.com")
        or host.endswith("reuters.com")
        or host.endswith("cnbc.com")
    ):
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


def _path_blocked(path: str) -> bool:
    lower = path.lower()
    return (
        "/video" in lower
        or "/newsletter" in lower
        or "/podcast" in lower
        or "/audio" in lower
    )


def _host_allowed(host: str, allowed_hosts: tuple[str, ...]) -> bool:
    h = host.lower()
    return any(h.endswith(allowed) for allowed in allowed_hosts)


def _parse_bing_rss(
    data: bytes,
    *,
    surface: str,
    cutoff: datetime,
    source_name: str,
    distribution_weight: str,
    allowed_hosts: tuple[str, ...],
) -> dict[str, Any]:
    window_start = cutoff - timedelta(hours=24)
    items: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    raw_count = 0
    root = ET.fromstring(data)
    channel = root.find("channel")
    if channel is None:
        return {"raw_count": 0, "items": items, "dropped": dropped}
    for item in channel.findall("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        pub_el = item.find("pubDate")
        desc_el = item.find("description")
        headline = _headline_clean(title_el.text if title_el is not None else "")
        link = link_el.text if link_el is not None else ""
        canonical = _canonical_from_bing_link(link)
        if not canonical:
            continue
        host = urlparse(canonical).netloc.lower()
        if not _host_allowed(host, allowed_hosts):
            continue
        raw_count += 1
        path = urlparse(canonical).path.lower()
        if _path_blocked(path):
            dropped.append({"headline": headline, "url": canonical, "reason": "path_drop"})
            continue
        snippet = _collapse_ws(_strip_html(desc_el.text if desc_el is not None else ""))
        published = _parse_pub_rss(pub_el.text if pub_el is not None else "")
        if published is None or published > cutoff or published < window_start:
            dropped.append(
                {
                    "headline": headline,
                    "url": canonical,
                    "reason": "window" if published is not None else "unparsed_date",
                }
            )
            continue
        items.append(
            {
                "published_at": isoformat(published),
                "url": canonical,
                "headline": headline,
                "summary": snippet,
                "source_name": source_name,
                "verification_status": "single_source",
                "primary_category": _primary_category(headline, snippet),
                "discovery_surface": surface,
                "distribution_weight": distribution_weight,
            }
        )
    items.sort(key=lambda x: x["published_at"], reverse=True)
    return {"raw_count": raw_count, "items": items, "dropped": dropped}


def _parse_reuters_sitemap(
    data: bytes,
    *,
    surface: str,
    cutoff: datetime,
) -> dict[str, Any]:
    window_start = cutoff - timedelta(hours=24)
    ns = {
        "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
        "news": "http://www.google.com/schemas/sitemap-news/0.9",
    }
    items: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
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
        path = urlparse(loc).path.lower()
        if _path_blocked(path):
            dropped.append({"headline": headline, "url": loc, "reason": "path_drop"})
            continue
        published = _parse_pub_iso(pub_el.text if pub_el is not None else "")
        if published is None or published > cutoff or published < window_start:
            dropped.append(
                {
                    "headline": headline,
                    "url": loc,
                    "reason": "window" if published is not None else "unparsed_date",
                }
            )
            continue
        pub_name = (name_el.text if name_el is not None else "").strip() or "Reuters"
        if pub_name != "Reuters":
            dropped.append({"headline": headline, "url": loc, "reason": "publication_name"})
            continue
        items.append(
            {
                "published_at": isoformat(published),
                "url": loc,
                "headline": headline,
                "summary": snippet,
                "source_name": "Reuters",
                "verification_status": "single_source",
                "primary_category": _primary_category(headline, snippet),
                "discovery_surface": surface,
                "distribution_weight": "standard",
            }
        )
    items.sort(key=lambda x: x["published_at"], reverse=True)
    return {"raw_count": raw_count, "items": items, "dropped": dropped}


def _parse_cnbc_sitemap(
    data: bytes,
    *,
    surface: str,
    cutoff: datetime,
) -> dict[str, Any]:
    window_start = cutoff - timedelta(hours=24)
    ns = {
        "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
        "news": "http://www.google.com/schemas/sitemap-news/0.9",
    }
    items: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
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
        snippet = CNBC_HEADLINE_ONLY
        path = urlparse(loc).path.lower()
        if _path_blocked(path):
            dropped.append({"headline": headline, "url": loc, "reason": "path_drop"})
            continue
        published = _parse_pub_iso(pub_el.text if pub_el is not None else "")
        if published is None or published > cutoff or published < window_start:
            dropped.append(
                {
                    "headline": headline,
                    "url": loc,
                    "reason": "window" if published is not None else "unparsed_date",
                }
            )
            continue
        pub_name = (name_el.text if name_el is not None else "").strip() or "CNBC"
        if pub_name != "CNBC":
            dropped.append({"headline": headline, "url": loc, "reason": "publication_name"})
            continue
        items.append(
            {
                "published_at": isoformat(published),
                "url": loc,
                "headline": headline,
                "summary": snippet,
                "source_name": "CNBC",
                "verification_status": "single_source",
                "primary_category": _primary_category(headline, snippet),
                "discovery_surface": surface,
                "distribution_weight": "standard",
            }
        )
    items.sort(key=lambda x: x["published_at"], reverse=True)
    return {"raw_count": raw_count, "items": items, "dropped": dropped}


def _is_boj_boe_surface(surface: str) -> bool:
    return any(marker in surface for marker in _BOJ_BOE_SURFACE_MARKERS)


def _boj_boe_title_kept(title: str) -> bool:
    t = (title or "").lower()
    if any(
        phrase in t
        for phrase in (
            "bank rate",
            "money market operations",
            "complementary deposit facility",
            "financial stability",
            "intervention",
            "official cash rate",
            "monetary policy",
            "policy board",
            "policy rate",
            "interest rate",
            "financial policy committee",
            "monetary policy committee",
            "cpi",
            "inflation",
            "gilt",
        )
    ):
        return True
    has_inst = any(
        inst in t
        for inst in ("bank of japan", "boj", "bank of england", "boe", "gilt")
    )
    if has_inst and any(word in t for word in ("rate", "policy", "inflation")):
        return True
    return False


def _atom_text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return (el.text or "").strip()


def _atom_link(entry: ET.Element) -> str:
    for link in entry:
        if _local_tag(link.tag) != "link":
            continue
        href = link.attrib.get("href")
        if not href:
            continue
        rel = link.attrib.get("rel", "alternate")
        if rel in ("alternate", ""):
            return href.strip()
    for link in entry:
        if _local_tag(link.tag) == "link" and link.attrib.get("href"):
            return link.attrib["href"].strip()
    return ""


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find_children(parent: ET.Element, local: str) -> list[ET.Element]:
    return [c for c in parent if _local_tag(c.tag) == local]


def _parse_rss_official(
    data: bytes,
    *,
    surface: str,
    cutoff: datetime,
    source_name: str,
    distribution_weight: str,
) -> dict[str, Any]:
    window_start = cutoff - timedelta(hours=24)
    items: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    raw_count = 0
    title_filter = _is_boj_boe_surface(surface)
    root = ET.fromstring(data)
    root_local = _local_tag(root.tag)

    if root_local == "feed":
        entries = _find_children(root, "entry")
        for entry in entries:
            title_el = next((c for c in entry if _local_tag(c.tag) == "title"), None)
            headline = _atom_text(title_el)
            link = _atom_link(entry)
            if not headline or not link:
                continue
            raw_count += 1
            updated_el = next((c for c in entry if _local_tag(c.tag) == "updated"), None)
            summary_el = next((c for c in entry if _local_tag(c.tag) == "summary"), None)
            published = _parse_pub_iso(_atom_text(updated_el))
            snippet = _collapse_ws(_strip_html(_atom_text(summary_el)))
            _append_official_item(
                items,
                dropped,
                headline=headline,
                link=link,
                snippet=snippet,
                published=published,
                cutoff=cutoff,
                window_start=window_start,
                surface=surface,
                source_name=source_name,
                distribution_weight=distribution_weight,
                title_filter=title_filter,
            )
    else:
        channel = root.find("channel")
        if channel is None:
            return {"raw_count": 0, "items": items, "dropped": dropped}
        for item in channel.findall("item"):
            title_el = item.find("title")
            link_el = item.find("link")
            pub_el = item.find("pubDate")
            desc_el = item.find("description")
            headline = (title_el.text if title_el is not None else "").strip()
            link = (link_el.text if link_el is not None else "").strip()
            if not headline or not link:
                continue
            raw_count += 1
            snippet = _collapse_ws(_strip_html(desc_el.text if desc_el is not None else ""))
            published = _parse_pub_rss(pub_el.text if pub_el is not None else "")
            _append_official_item(
                items,
                dropped,
                headline=headline,
                link=link,
                snippet=snippet,
                published=published,
                cutoff=cutoff,
                window_start=window_start,
                surface=surface,
                source_name=source_name,
                distribution_weight=distribution_weight,
                title_filter=title_filter,
            )

    items.sort(key=lambda x: x["published_at"], reverse=True)
    return {"raw_count": raw_count, "items": items, "dropped": dropped}


def _append_official_item(
    items: list[dict[str, Any]],
    dropped: list[dict[str, Any]],
    *,
    headline: str,
    link: str,
    snippet: str,
    published: datetime | None,
    cutoff: datetime,
    window_start: datetime,
    surface: str,
    source_name: str,
    distribution_weight: str,
    title_filter: bool,
) -> None:
    if title_filter and not _boj_boe_title_kept(headline):
        dropped.append({"headline": headline, "url": link, "reason": "official_title_filter"})
        return
    if published is None or published > cutoff or published < window_start:
        dropped.append(
            {
                "headline": headline,
                "url": link,
                "reason": "window" if published is not None else "unparsed_date",
            }
        )
        return
    items.append(
        {
            "published_at": isoformat(published),
            "url": link,
            "headline": headline,
            "summary": snippet,
            "source_name": source_name,
            "verification_status": "official",
            "primary_category": _primary_category(headline, snippet),
            "discovery_surface": surface,
            "distribution_weight": distribution_weight,
        }
    )
