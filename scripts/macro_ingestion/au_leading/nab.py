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

CATALOG_ID = "AU.Labor.nab_employment_subindex"
PUBLISHER = "nab_business_survey"

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


def _asof_visible(as_of: date, release_date: date) -> bool:
    return as_of >= release_date


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _discover_pdf_url(html: str) -> str | None:
    for m in re.finditer(
        r'href="(https://www\.nab\.com\.au/content/dam/[^"]+Business%20Survey[^"]+\.pdf)"',
        html,
        flags=re.IGNORECASE,
    ):
        return unescape(m.group(1))
    for m in re.finditer(
        r'href="([^"]+2026m09[^"]+Survey[^"]+\.pdf)"',
        html,
        flags=re.IGNORECASE,
    ):
        return urljoin(NEWS_URL, unescape(m.group(1)))
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
    opener: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    attempts: list[FetchAttempt] = []
    gaps: list[dict[str, str]] = []
    points: list[dict[str, Any]] = []
    qualitative: list[dict[str, str]] = []

    if not _asof_visible(as_of, RELEASE_DATE):
        gaps.append(
            {
                "id": CATALOG_ID,
                "publisher": PUBLISHER,
                "status": "not_yet_released",
                "reason": f"release_date {RELEASE_DATE.isoformat()} after as_of {as_of.isoformat()}",
            }
        )
        return {"points": points, "gaps": gaps, "qualitative": qualitative, "attempts": attempts}

    news = opener(NEWS_URL)
    news_body = news.get("body") or b""
    news_sha = _sha256(news_body) if news_body else None
    attempts.append(
        FetchAttempt(
            url=NEWS_URL,
            http_status=news.get("http_status"),
            content_type=news.get("content_type"),
            sha256=news_sha,
            outcome="parsed" if news.get("ok") else "source_failed",
        )
    )
    if not news.get("ok"):
        gaps.append(
            {
                "id": CATALOG_ID,
                "publisher": PUBLISHER,
                "status": "source_failed",
                "reason": str(news.get("error") or "news page fetch failed"),
            }
        )
        return {"points": points, "gaps": gaps, "qualitative": qualitative, "attempts": attempts}

    html = news_body.decode("utf-8", errors="replace")
    pdf_url = _discover_pdf_url(html) or DEFAULT_PDF_URL

    pdf = opener(pdf_url)
    pdf_body = pdf.get("body") or b""
    pdf_sha = _sha256(pdf_body) if pdf_body else None
    attempts.append(
        FetchAttempt(
            url=pdf_url,
            http_status=pdf.get("http_status"),
            content_type=pdf.get("content_type"),
            sha256=pdf_sha,
            outcome="parsed" if pdf.get("ok") else "license_gap",
        )
    )
    if not pdf.get("ok") or not pdf_body:
        qualitative.append(
            {
                "publisher": PUBLISHER,
                "release_date": RELEASE_DATE.isoformat(),
                "source_url": NEWS_URL,
                "summary": "September 2026 survey commentary available; full PDF not retrieved.",
            }
        )
        gaps.append(
            {
                "id": CATALOG_ID,
                "publisher": PUBLISHER,
                "status": "license_gap",
                "reason": "employment sub-index spreadsheet/PDF not accessible",
            }
        )
        return {"points": points, "gaps": gaps, "qualitative": qualitative, "attempts": attempts}

    try:
        value = _parse_employment_index(_pdf_text(pdf_body))
    except ValueError as exc:
        qualitative.append(
            {
                "publisher": PUBLISHER,
                "release_date": RELEASE_DATE.isoformat(),
                "source_url": NEWS_URL,
                "summary": str(exc),
            }
        )
        gaps.append(
            {
                "id": CATALOG_ID,
                "publisher": PUBLISHER,
                "status": "qualitative_only",
                "reason": str(exc),
            }
        )
        return {"points": points, "gaps": gaps, "qualitative": qualitative, "attempts": attempts}

    points.append(
        {
            "id": CATALOG_ID,
            "publisher": PUBLISHER,
            "weight": 0.0,
            "period": REFERENCE_PERIOD,
            "value": value,
            "units": UNITS,
            "transformation": "level",
            "series_label": "employment_subindex",
            "release_date": RELEASE_DATE.isoformat(),
            "raw_sha256": pdf_sha,
            "source_url": pdf_url,
            "vintage": f"release:{RELEASE_DATE.isoformat()}",
            "revision_status": "latest_available",
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
