"""SEEK Employment Report job-ad trend (context-only, weight 0)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from html import unescape
from typing import Any, Callable
from urllib.parse import urljoin

from scripts.macro_ingestion.au_leading.asof import observation_eligible
from scripts.macro_ingestion.au_leading.discovery import (
    MAX_PAGES,
    bounded_get,
    failure_class,
    honest_transport_failure,
)

CATALOG_ID = "AU.Labor.seek_job_ad_trend"
PUBLISHER = "seek_employment_report"

CATEGORY_URL = "https://au.seek.com/about/news/category/seek-employment-reports/0"
AUGUST_ARTICLE_URL = "https://au.seek.com/about/news/seek-employment-report-august26/"

AUGUST_RELEASE_DATE = date(2026, 9, 17)
AUGUST_REFERENCE_PERIOD = "2026-08"
UNITS = "percent"


@dataclass(frozen=True)
class FetchAttempt:
    url: str
    http_status: int | None
    content_type: str | None
    sha256: str | None
    outcome: str


_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_SLUG_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def _record_attempt(attempts: list[FetchAttempt], url: str, resp: dict[str, Any], *, ok_outcome: str) -> None:
    body = resp.get("body") or b""
    attempts.append(
        FetchAttempt(
            url=url,
            http_status=resp.get("http_status"),
            content_type=resp.get("content_type"),
            sha256=_sha256(body) if body else None,
            outcome=ok_outcome if resp.get("ok") else str(failure_class(resp) or "source_failed"),
        )
    )


def _gap(status: str, reason: str) -> dict[str, str]:
    return {"id": CATALOG_ID, "publisher": PUBLISHER, "status": status, "reason": reason}


def _article_links(html: str) -> list[str]:
    found: list[str] = []
    for match in re.finditer(
        r'href="([^"]*seek-employment-report-[a-z0-9-]+/?)"',
        html,
        flags=re.IGNORECASE,
    ):
        href = unescape(match.group(1))
        if href.startswith("http"):
            url = href
        else:
            url = urljoin("https://au.seek.com/", href)
        if not url.endswith("/"):
            url += "/"
        if url not in found:
            found.append(url)
        if len(found) >= MAX_PAGES:
            break
    if len(found) < MAX_PAGES:
        for slug_match in re.finditer(
            r"seek-employment-report-([a-z]+)(\d{2})",
            html,
            flags=re.IGNORECASE,
        ):
            slug = slug_match.group(0).lower()
            url = f"https://au.seek.com/about/news/{slug}/"
            if url not in found:
                found.append(url)
            if len(found) >= MAX_PAGES:
                break
    return found


def _period_from_slug(url: str) -> str | None:
    match = re.search(r"seek-employment-report-([a-z]+)(\d{2})", url, flags=re.IGNORECASE)
    if not match:
        return None
    month = _SLUG_MONTHS.get(match.group(1).lower())
    if month is None:
        return None
    return f"{2000 + int(match.group(2)):04d}-{month:02d}"


def _parse_publish_date(html: str) -> date | None:
    patterns = (
        r'name="article-publish-date"\s+content="(\d{4}-\d{2}-\d{2})"',
        r'property="article:published_time"\s+content="(\d{4}-\d{2}-\d{2})"',
        r'article-publish-date"\s+content="(\d{4}-\d{2}-\d{2})"',
        r'"publishedDate"\s*:\s*"(\d{4}-\d{2}-\d{2})"',
        r'"publishDate"\s*:\s*"(\d{4}-\d{2}-\d{2})"',
    )
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            return date.fromisoformat(match.group(1))
    match = re.search(r'content="(\d{4}-\d{2}-\d{2})"', html)
    if not match:
        return None
    return date.fromisoformat(match.group(1))


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _parse_trend_mom_pct(html: str) -> tuple[float, str]:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.S | re.I)
    text = unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"\s+", " ", text)
    match = re.search(
        r"Job ads rose[^,]{0,120}, up\s+(-?\d+(?:\.\d+)?)%\s+from\s+([A-Za-z]+)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        match = re.search(
            r"up\s+(-?\d+(?:\.\d+)?)%\s+from\s+([A-Za-z]+)",
            text,
            flags=re.IGNORECASE,
        )
    if not match:
        raise ValueError("trend m/m job ad change not found in article")
    value = float(match.group(1))
    if value != value:
        raise ValueError("non-finite trend m/m percent")
    prior = match.group(2).lower()
    if prior not in _MONTHS:
        raise ValueError(f"unrecognized prior month {prior}")
    return value, prior


def _prior_month_matches(period: str, prior_name: str) -> bool:
    year = int(period[:4])
    month = int(period[5:7])
    prior_month = month - 1
    prior_year = year
    if prior_month == 0:
        prior_month = 12
        prior_year -= 1
    return _MONTHS.get(prior_name) == prior_month and prior_year > 0


def collect_seek(
    *,
    as_of: date,
    opener: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    attempts: list[FetchAttempt] = []
    gaps: list[dict[str, str]] = []
    points: list[dict[str, Any]] = []
    qualitative: list[dict[str, str]] = []

    category = bounded_get(opener, CATEGORY_URL)
    _record_attempt(attempts, CATEGORY_URL, category, ok_outcome="parsed")
    candidates: list[dict[str, str]] = []
    if honest_transport_failure(category):
        gaps.append(
            _gap(
                failure_class(category) or "source_failed",
                str(category.get("error") or "SEEK employment-report index transport failure"),
            )
        )
        return {"points": points, "gaps": gaps, "qualitative": qualitative, "attempts": attempts}
    if category.get("ok") and category.get("body"):
        html = (category.get("body") or b"").decode("utf-8", errors="replace")
        for url in _article_links(html):
            candidates.append({"url": url, "provenance": "publisher_index"})
    if not candidates:
        gaps.append(
            _gap(
                "discovery_gap",
                "SEEK employment-report index did not list a dated article; controlled vintage index used",
            )
        )
        candidates.append({"url": AUGUST_ARTICLE_URL, "provenance": "controlled_release_index"})

    chosen: dict[str, Any] | None = None
    for cand in candidates[:MAX_PAGES]:
        article_url = cand["url"]
        article = bounded_get(opener, article_url)
        _record_attempt(attempts, article_url, article, ok_outcome="parsed")
        if honest_transport_failure(article):
            gaps.append(
                _gap(failure_class(article) or "source_failed", str(article.get("error") or "SEEK article transport failure"))
            )
            continue
        if not article.get("ok") or not article.get("body"):
            gaps.append(_gap("source_failed", str(article.get("error") or "employment report page unavailable")))
            continue
        html = (article.get("body") or b"").decode("utf-8", errors="replace")
        period = _period_from_slug(article_url)
        release_date = _parse_publish_date(html)
        if period is None or release_date is None:
            gaps.append(_gap("source_failed", f"period or release date missing on {article_url}"))
            continue
        if not observation_eligible(release_date, as_of):
            gaps.append(
                _gap(
                    "not_yet_released",
                    f"release_date {release_date.isoformat()} not eligible at as_of {as_of.isoformat()}",
                )
            )
            continue
        try:
            mom_pct, prior = _parse_trend_mom_pct(html)
        except ValueError as exc:
            gaps.append(_gap("parse_failed", str(exc)))
            continue
        if not _prior_month_matches(period, prior):
            gaps.append(_gap("parse_failed", f"article prior month {prior} does not match period {period}"))
            continue
        if chosen is None or release_date > chosen["release_date"]:
            chosen = {
                "url": article_url,
                "release_date": release_date,
                "period": period,
                "value": mom_pct,
                "sha": _sha256(article.get("body") or b""),
                "provenance": cand["provenance"],
            }

    if chosen is None:
        if not gaps:
            gaps.append(_gap("source_failed", "no eligible SEEK employment report discovered"))
        return {"points": points, "gaps": gaps, "qualitative": qualitative, "attempts": attempts}

    points.append(
        {
            "id": CATALOG_ID,
            "publisher": PUBLISHER,
            "weight": 0.0,
            "period": chosen["period"],
            "value": chosen["value"],
            "units": UNITS,
            "transformation": "trend_mom_pct",
            "series_label": "trend",
            "release_date": chosen["release_date"].isoformat(),
            "raw_sha256": chosen["sha"],
            "source_url": chosen["url"],
            "vintage": f"release:{chosen['release_date'].isoformat()}",
            "revision_status": "latest_available",
            "provenance": chosen["provenance"],
        }
    )
    return {"points": points, "gaps": gaps, "qualitative": qualitative, "attempts": attempts}


def attempts_to_json(attempts: list[FetchAttempt]) -> list[dict[str, Any]]:
    return [
        {
            "url": a.url,
            "http_status": a.http_status,
            "content_type": a.content_type,
            "sha256": a.sha256,
            "outcome": a.outcome,
        }
        for a in attempts
    ]
