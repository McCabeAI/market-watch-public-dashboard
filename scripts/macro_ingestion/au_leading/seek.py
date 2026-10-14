"""SEEK Employment Report job-ad trend (context-only, weight 0)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from html import unescape
from typing import Any, Callable

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


def _asof_visible(as_of: date, release_date: date) -> bool:
    return as_of >= release_date


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _parse_trend_mom_pct(html: str) -> float:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.S | re.I)
    text = unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"\s+", " ", text)
    m = re.search(
        r"Job ads rose[^,]{0,80}, up\s+(-?\d+(?:\.\d+)?)%\s+from\s+July",
        text,
        flags=re.IGNORECASE,
    )
    if not m:
        m = re.search(
            r"up\s+(-?\d+(?:\.\d+)?)%\s+from\s+July",
            text,
            flags=re.IGNORECASE,
        )
    if not m:
        raise ValueError("trend m/m job ad change not found in article")
    value = float(m.group(1))
    if value != value:
        raise ValueError("non-finite trend m/m percent")
    return value


def collect_seek(
    *,
    as_of: date,
    opener: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    attempts: list[FetchAttempt] = []
    gaps: list[dict[str, str]] = []
    points: list[dict[str, Any]] = []
    qualitative: list[dict[str, str]] = []

    category = opener(CATEGORY_URL)
    cat_body = category.get("body") or b""
    attempts.append(
        FetchAttempt(
            url=CATEGORY_URL,
            http_status=category.get("http_status"),
            content_type=category.get("content_type"),
            sha256=_sha256(cat_body) if cat_body else None,
            outcome="parsed" if category.get("ok") else "source_failed",
        )
    )

    if not _asof_visible(as_of, AUGUST_RELEASE_DATE):
        gaps.append(
            {
                "id": CATALOG_ID,
                "publisher": PUBLISHER,
                "status": "not_yet_released",
                "reason": f"August 2026 release after as_of {as_of.isoformat()}",
            }
        )
        return {"points": points, "gaps": gaps, "qualitative": qualitative, "attempts": attempts}

    article = opener(AUGUST_ARTICLE_URL)
    art_body = article.get("body") or b""
    art_sha = _sha256(art_body) if art_body else None
    attempts.append(
        FetchAttempt(
            url=AUGUST_ARTICLE_URL,
            http_status=article.get("http_status"),
            content_type=article.get("content_type"),
            sha256=art_sha,
            outcome="parsed" if article.get("ok") else "source_failed",
        )
    )
    if not article.get("ok") or not art_body:
        gaps.append(
            {
                "id": CATALOG_ID,
                "publisher": PUBLISHER,
                "status": "source_failed",
                "reason": "August 2026 employment report page unavailable",
            }
        )
        return {"points": points, "gaps": gaps, "qualitative": qualitative, "attempts": attempts}

    html = art_body.decode("utf-8", errors="replace")

    try:
        mom_pct = _parse_trend_mom_pct(html)
    except ValueError as exc:
        gaps.append(
            {
                "id": CATALOG_ID,
                "publisher": PUBLISHER,
                "status": "parse_failed",
                "reason": str(exc),
            }
        )
        return {"points": points, "gaps": gaps, "qualitative": qualitative, "attempts": attempts}

    points.append(
        {
            "id": CATALOG_ID,
            "publisher": PUBLISHER,
            "weight": 0.0,
            "period": AUGUST_REFERENCE_PERIOD,
            "value": mom_pct,
            "units": UNITS,
            "transformation": "trend_mom_pct",
            "series_label": "trend",
            "release_date": AUGUST_RELEASE_DATE.isoformat(),
            "raw_sha256": art_sha,
            "source_url": AUGUST_ARTICLE_URL,
            "vintage": f"release:{AUGUST_RELEASE_DATE.isoformat()}",
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
