"""ISM PMI press releases via PR Newswire (same ISM survey headlines as ismworld.org)."""

from __future__ import annotations

import re
from typing import Any, Callable

from scripts.macro_ingestion.us_employment.cache import cache_get, cache_put, is_challenge_page, open_url

PRNEWSWIRE_ISM_LISTING = "https://www.prnewswire.com/news/institute-for-supply-management/"

_MANUFACTURING_HREF = re.compile(
    r'href="(?P<path>/news-releases/manufacturing-pmi[^"]+)"',
    re.IGNORECASE,
)
_SERVICES_HREF = re.compile(
    r'href="(?P<path>/news-releases/services-pmi[^"]+)"',
    re.IGNORECASE,
)
_TITLE_PMI = re.compile(
    r"(?P<kind>Manufacturing|Services)\s+PMI(?:®|&(?:reg|#174);)?\s+at\s+(?P<value>\d{2}\.\d{1,2})",
    re.IGNORECASE,
)
_TITLE_PERIOD = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
    re.IGNORECASE,
)
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def _listing_cache_key(services: bool) -> str:
    return f"ism:prnewswire_listing:{int(services)}"


def discover_latest_release_path(body: bytes, *, services: bool) -> str | None:
    text = body.decode("utf-8", errors="replace")
    pattern = _SERVICES_HREF if services else _MANUFACTURING_HREF
    match = pattern.search(text)
    if not match:
        return None
    return match.group("path")


def resolve_ism_release_url(
    spec: dict[str, Any],
    *,
    opener: Callable[..., Any],
    timeout: float,
    services: bool,
) -> tuple[str, bytes | None]:
    """Return (url, optional prefetched listing body)."""
    endpoint = str(spec.get("endpoint") or "").strip()
    registry = [str(u) for u in (spec.get("registry_urls") or []) if u]
    candidates = [endpoint, *registry, PRNEWSWIRE_ISM_LISTING]
    seen: set[str] = set()
    listing_body: bytes | None = None
    for raw in candidates:
        if not raw or raw in seen:
            continue
        seen.add(raw)
        if "prnewswire.com/news/institute-for-supply-management" in raw:
            cached = cache_get(opener, _listing_cache_key(services))
            if cached is not None:
                listing_body = cached
            else:
                response = open_url(opener, raw, timeout=timeout)
                listing_body = response.get("body") or b""
                cache_put(opener, _listing_cache_key(services), listing_body)
            path = discover_latest_release_path(listing_body, services=services)
            if path:
                base = "https://www.prnewswire.com"
                return f"{base}{path}", listing_body
            continue
        if "prnewswire.com/news-releases/" in raw and ("manufacturing-pmi" in raw or "services-pmi" in raw):
            return raw, None
        if raw.endswith("/pmi/") or raw.endswith("/services/"):
            continue
    return PRNEWSWIRE_ISM_LISTING, listing_body


def parse_ism_pmi(body: bytes, *, services: bool) -> dict[str, Any] | None:
    text = body.decode("utf-8", errors="replace")
    value: float | None = None
    period: str | None = None

    title_match = _TITLE_PMI.search(text)
    if title_match:
        kind = title_match.group("kind").lower()
        if services and kind != "services":
            return None
        if not services and kind != "manufacturing":
            return None
        value = float(title_match.group("value"))
        period_match = _TITLE_PERIOD.search(text)
        if period_match:
            month_num = _MONTHS.index(period_match.group(1).capitalize()) + 1
            period = f"{period_match.group(2)}-{month_num:02d}"

    if value is None:
        if services:
            patterns = (
                r"Services PMI(?:[^\d]{0,80})(\d{2}\.\d)",
                r"Non-Manufacturing PMI(?:[^\d]{0,80})(\d{2}\.\d)",
            )
        else:
            patterns = (
                r"Manufacturing PMI(?:[^\d]{0,80})(\d{2}\.\d)",
                r"ISM Manufacturing(?:[^\d]{0,80})(\d{2}\.\d)",
            )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
            if match:
                candidate = float(match.group(1))
                if 0 <= candidate <= 100:
                    value = candidate
                    break
    if value is None:
        return None
    if period is None:
        period_match = re.search(
            r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
            text,
            flags=re.IGNORECASE,
        )
        if period_match:
            month_num = _MONTHS.index(period_match.group(1).capitalize()) + 1
            period = f"{period_match.group(2)}-{month_num:02d}"
    if period is None:
        return None
    return {"value": value, "period": period}


def fetch_ism_pmi_release(
    spec: dict[str, Any],
    *,
    opener: Callable[..., Any],
    timeout: float,
    services: bool,
) -> dict[str, Any]:
    url, _listing = resolve_ism_release_url(spec, opener=opener, timeout=timeout, services=services)
    if "institute-for-supply-management" in url and not url.endswith(".html"):
        listing = _listing
        if listing is None:
            response = open_url(opener, url, timeout=timeout)
            listing = response.get("body") or b""
        path = discover_latest_release_path(listing, services=services)
        if not path:
            return {
                "ok": False,
                "status": "source_failed",
                "error": "ism_listing_unparsed",
                "http_status": 200,
                "body": listing,
            }
        url = f"https://www.prnewswire.com{path}"
    response = open_url(opener, url, timeout=timeout)
    body: bytes = response.get("body") or b""
    base: dict[str, Any] = {"http_status": response.get("http_status"), "body": body}
    if is_challenge_page(body):
        return {
            **base,
            "ok": False,
            "status": "license_gap",
            "challenge_page": True,
            "error": "ism_challenge_page",
        }
    if response.get("ok") and body:
        parsed = parse_ism_pmi(body, services=services)
        if parsed:
            return {**base, "ok": True, "resolved_url": url, "parsed": parsed}
    return {
        **base,
        "ok": False,
        "status": "source_failed",
        "error": response.get("error") or "ism_primary_unparsed",
    }
