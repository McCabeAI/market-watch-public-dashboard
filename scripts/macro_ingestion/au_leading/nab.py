"""NAB Monthly Business Survey employment sub-index (context-only, weight 0)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from html import unescape
from typing import Any, Callable
from urllib.parse import urljoin

from pypdf import PdfReader

from scripts.macro_ingestion.au_leading.asof import observation_eligible
from scripts.macro_ingestion.au_leading.discovery import (
    MAX_PAGES,
    bounded_get,
    failure_class,
    honest_transport_failure,
)

CATALOG_ID = "AU.Labor.nab_employment_subindex"
PUBLISHER = "nab_business_survey"

NEWS_INDEX_URL = "https://www.nabtrade.com.au/insights/news/"
NEWS_URL = (
    "https://www.nabtrade.com.au/insights/news/2026/10/nab-business-survey---september-2026"
)
DEFAULT_PDF_URL = (
    "https://www.nab.com.au/content/dam/nab-email-composer/nabmarketsresearchembargo/"
    "economics/pdf/2026m09%20NAB%20Monthly%20Business%20Survey%20qwe.pdf"
)
RELEASE_DATE = date(2026, 10, 13)
REFERENCE_PERIOD = "2026-09"
UNITS = "index_points"


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


def _index_article_links(html: str) -> list[str]:
    found: list[str] = []
    for match in re.finditer(r'href="([^"]+)"', html, flags=re.IGNORECASE):
        href = unescape(match.group(1))
        if "nab-business-survey" not in href.lower():
            continue
        if href.startswith("http"):
            url = href
        elif href.startswith("/"):
            url = urljoin("https://www.nabtrade.com.au/", href)
        else:
            url = urljoin(NEWS_INDEX_URL, href)
        if url not in found:
            found.append(url)
        if len(found) >= MAX_PAGES:
            break
    return found


def _period_from_text(text: str) -> str | None:
    match = re.search(
        r"business survey\s*[-–—]\s*([A-Za-z]+)\s+(\d{4})",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        match = re.search(
            r"nab-business-survey---([a-z]+)-(\d{4})",
            text,
            flags=re.IGNORECASE,
        )
    if not match:
        return None
    month = _MONTHS.get(match.group(1).lower())
    if month is None:
        return None
    return f"{int(match.group(2)):04d}-{month:02d}"


def _parse_release_date(html: str) -> date | None:
    match = re.search(
        r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
        html,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    month = _MONTHS.get(match.group(2).lower())
    if month is None:
        return None
    return date(int(match.group(3)), month, int(match.group(1)))


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _discover_pdf_url(html: str, page_url: str) -> str | None:
    patterns = (
        r'href="(https://www\.nab\.com\.au/content/dam/[^"]+Business%20Survey[^"]*\.pdf)"',
        r'href="(https://www\.nab\.com\.au/content/dam/[^"]+Monthly%20Business%20Survey[^"]*\.pdf)"',
        r'href="([^"]+Business%20Survey[^"]*\.pdf)"',
        r'href="([^"]+Monthly%20Business%20Survey[^"]*\.pdf)"',
    )
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            return urljoin(page_url, unescape(match.group(1)))
    return None


def _pdf_text(body: bytes) -> str:
    import io

    reader = PdfReader(io.BytesIO(body))
    return "".join((page.extract_text() or "") for page in reader.pages)


def _parse_employment_index(text: str) -> float:
    m = re.search(
        r"Employment\s+To\s+(-?\d+(?:\.\d+)?)\s+index\s+points",
        text,
        flags=re.IGNORECASE,
    )
    if not m:
        m = re.search(
            r"employment index declined[^.]{0,120}",
            text,
            flags=re.IGNORECASE,
        )
        if m:
            raise ValueError("employment index mentioned qualitatively without numeric level")
        raise ValueError("employment sub-index level not found in report")
    value = float(m.group(1))
    if value != value:
        raise ValueError("non-finite employment index")
    return value


def collect_nab(
    *,
    as_of: date,
    opener: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    attempts: list[FetchAttempt] = []
    gaps: list[dict[str, str]] = []
    points: list[dict[str, Any]] = []
    qualitative: list[dict[str, str]] = []

    index = bounded_get(opener, NEWS_INDEX_URL)
    _record_attempt(attempts, NEWS_INDEX_URL, index, ok_outcome="parsed")
    candidates: list[dict[str, Any]] = []
    if honest_transport_failure(index):
        gaps.append(
            _gap(
                failure_class(index) or "source_failed",
                str(index.get("error") or f"NAB news index transport failure HTTP {index.get('http_status')}"),
            )
        )
        return {"points": points, "gaps": gaps, "qualitative": qualitative, "attempts": attempts}
    if index.get("ok") and index.get("body"):
        html = (index.get("body") or b"").decode("utf-8", errors="replace")
        for url in _index_article_links(html):
            candidates.append({"news_url": url, "provenance": "publisher_index"})
    if not candidates:
        gaps.append(
            _gap(
                "discovery_gap",
                "NAB news index did not list a dated business survey; controlled vintage index used",
            )
        )
        candidates.append(
            {
                "news_url": NEWS_URL,
                "provenance": "controlled_release_index",
                "release_date": RELEASE_DATE,
                "reference_period": REFERENCE_PERIOD,
            }
        )

    chosen: dict[str, Any] | None = None
    for cand in candidates[:MAX_PAGES]:
        news_url = str(cand["news_url"])
        news = bounded_get(opener, news_url)
        _record_attempt(attempts, news_url, news, ok_outcome="parsed")
        if honest_transport_failure(news):
            gaps.append(_gap(failure_class(news) or "source_failed", str(news.get("error") or "NAB article transport failure")))
            continue
        if not news.get("ok") or not news.get("body"):
            gaps.append(_gap("source_failed", str(news.get("error") or "news page fetch failed")))
            continue
        html = (news.get("body") or b"").decode("utf-8", errors="replace")
        release_date = _parse_release_date(html) or cand.get("release_date")
        period = _period_from_text(html) or _period_from_text(news_url) or cand.get("reference_period")
        if release_date is None or period is None:
            gaps.append(_gap("source_failed", f"release date or reference period missing on {news_url}"))
            continue
        if not observation_eligible(release_date, as_of):
            gaps.append(
                _gap(
                    "not_yet_released",
                    f"release_date {release_date.isoformat()} not eligible at as_of {as_of.isoformat()}",
                )
            )
            continue
        pdf_url = _discover_pdf_url(html, news_url)
        if pdf_url is None and cand.get("provenance") == "controlled_release_index":
            pdf_url = DEFAULT_PDF_URL
        if not pdf_url:
            gaps.append(_gap("license_gap", f"employment survey PDF link missing on {news_url}"))
            continue
        if chosen is None or release_date > chosen["release_date"]:
            chosen = {
                "news_url": news_url,
                "release_date": release_date,
                "period": period,
                "pdf_url": pdf_url,
                "provenance": cand.get("provenance") or "publisher_index",
                "html": html,
            }

    if chosen is None:
        if not any(g.get("status") == "not_yet_released" for g in gaps):
            gaps.append(_gap("source_failed", "no eligible NAB employment release discovered"))
        return {"points": points, "gaps": gaps, "qualitative": qualitative, "attempts": attempts}

    pdf_url = str(chosen["pdf_url"])
    pdf = bounded_get(opener, pdf_url)
    pdf_body = pdf.get("body") or b""
    _record_attempt(attempts, pdf_url, pdf, ok_outcome="parsed")
    if not pdf.get("ok") or not pdf_body:
        qualitative.append(
            {
                "publisher": PUBLISHER,
                "release_date": chosen["release_date"].isoformat(),
                "source_url": chosen["news_url"],
                "summary": "Survey commentary page retrieved; employment PDF not retrieved.",
            }
        )
        gaps.append(_gap(failure_class(pdf) or "license_gap", "employment sub-index PDF not accessible"))
        return {"points": points, "gaps": gaps, "qualitative": qualitative, "attempts": attempts}

    try:
        value = _parse_employment_index(_pdf_text(pdf_body))
    except ValueError as exc:
        qualitative.append(
            {
                "publisher": PUBLISHER,
                "release_date": chosen["release_date"].isoformat(),
                "source_url": chosen["news_url"],
                "summary": str(exc),
            }
        )
        gaps.append(_gap("qualitative_only", str(exc)))
        return {"points": points, "gaps": gaps, "qualitative": qualitative, "attempts": attempts}

    release_date = chosen["release_date"]
    points.append(
        {
            "id": CATALOG_ID,
            "publisher": PUBLISHER,
            "weight": 0.0,
            "period": chosen["period"],
            "value": value,
            "units": UNITS,
            "transformation": "level",
            "series_label": "employment_subindex",
            "release_date": release_date.isoformat(),
            "raw_sha256": _sha256(pdf_body),
            "source_url": pdf_url,
            "vintage": f"release:{release_date.isoformat()}",
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
