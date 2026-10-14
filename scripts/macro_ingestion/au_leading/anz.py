"""ANZ–Indeed Australian Job Ads publisher (context-only, weight 0)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime
from html import unescape
from typing import Any, Callable
from urllib.parse import urljoin

import openpyxl

CATALOG_ID_SA = "AU.Labor.anz_indeed_job_ads_sa"
PUBLISHER = "anz_indeed"

PRESS_RELEASE_URL = (
    "https://www.anz.com.au/newsroom/media/2026/october/job-ads-up-again/"
)
DEFAULT_XLSX_URL = (
    "https://www.anz.com.au/content/dam/anzcomau/mediacentre/images/jobads/2026/october/"
    "ANZ-Indeed%20Australian%20Job%20Ads%20data_Sep26.xlsx"
)
RELEASE_DATE = date(2026, 10, 6)
REFERENCE_PERIOD = "2026-09"
UNITS = "index"
INDEX_BASE = "2019=100"


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


def _period_from_dt(when: datetime) -> str:
    return f"{when.year:04d}-{when.month:02d}"


def _parse_release_date_from_html(html: str) -> date | None:
    for pat in (
        r'<meta name="modified_date"[^>]*content="(\d{4}-\d{2}-\d{2})"',
        r'article-hub-container__update-publish-date">(\d{4}-\d{2}-\d{2})',
        r'"effectiveDate":"(\d{4}-\d{2}-\d{2})"',
    ):
        m = re.search(pat, html)
        if m:
            return date.fromisoformat(m.group(1))
    return None


def _discover_xlsx_url(html: str, base_url: str = PRESS_RELEASE_URL) -> str | None:
    for m in re.finditer(
        r'href="([^"]+Job%20Ads%20data[^"]+\.xlsx)"', html, flags=re.IGNORECASE
    ):
        return urljoin(base_url, unescape(m.group(1)))
    for m in re.finditer(
        r'href="([^"]+jobads/[^"]+\.xlsx)"', html, flags=re.IGNORECASE
    ):
        return urljoin(base_url, unescape(m.group(1)))
    return None


def _parse_xlsx_sa_level(
    body: bytes, *, target_period: str = REFERENCE_PERIOD
) -> tuple[float, str]:
    import io

    wb = openpyxl.load_workbook(io.BytesIO(body), read_only=True, data_only=True)
    sheet_name = "ANZ-Indeed Australian Job Ads"
    if sheet_name not in wb.sheetnames:
        raise ValueError(f"missing sheet {sheet_name}")
    ws = wb[sheet_name]
    target_year, target_month = (int(target_period[:4]), int(target_period[5:7]))
    for row in ws.iter_rows(min_row=4, values_only=True):
        when = row[0]
        if not isinstance(when, datetime):
            continue
        if when.year == target_year and when.month == target_month:
            sa_val = row[2]
            if sa_val is None or not isinstance(sa_val, (int, float)):
                raise ValueError("missing seasonally adjusted level")
            if not (isinstance(sa_val, float) and sa_val == sa_val):  # NaN check
                raise ValueError("non-finite SA level")
            return float(sa_val), _period_from_dt(when)
    raise ValueError(f"period {target_period} not found in workbook")


def collect_anz(
    *,
    as_of: date,
    opener: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    attempts: list[FetchAttempt] = []
    gaps: list[dict[str, str]] = []
    points: list[dict[str, Any]] = []

    if not _asof_visible(as_of, RELEASE_DATE):
        gaps.append(
            {
                "id": CATALOG_ID_SA,
                "publisher": PUBLISHER,
                "status": "not_yet_released",
                "reason": f"release_date {RELEASE_DATE.isoformat()} after as_of {as_of.isoformat()}",
            }
        )
        return {"points": points, "gaps": gaps, "qualitative": [], "attempts": attempts}

    press = opener(PRESS_RELEASE_URL)
    press_body = press.get("body") or b""
    press_sha = _sha256(press_body) if press_body else None
    attempts.append(
        FetchAttempt(
            url=PRESS_RELEASE_URL,
            http_status=press.get("http_status"),
            content_type=press.get("content_type"),
            sha256=press_sha,
            outcome="parsed" if press.get("ok") else "source_failed",
        )
    )
    if not press.get("ok"):
        gaps.append(
            {
                "id": CATALOG_ID_SA,
                "publisher": PUBLISHER,
                "status": "source_failed",
                "reason": str(press.get("error") or "press release fetch failed"),
            }
        )
        return {"points": points, "gaps": gaps, "qualitative": [], "attempts": attempts}

    html = press_body.decode("utf-8", errors="replace")
    release_date = _parse_release_date_from_html(html) or RELEASE_DATE
    xlsx_url = _discover_xlsx_url(html) or DEFAULT_XLSX_URL

    xlsx = opener(xlsx_url)
    xlsx_body = xlsx.get("body") or b""
    xlsx_sha = _sha256(xlsx_body) if xlsx_body else None
    attempts.append(
        FetchAttempt(
            url=xlsx_url,
            http_status=xlsx.get("http_status"),
            content_type=xlsx.get("content_type"),
            sha256=xlsx_sha,
            outcome="parsed" if xlsx.get("ok") else "license_gap",
        )
    )
    if not xlsx.get("ok") or not xlsx_body:
        gaps.append(
            {
                "id": CATALOG_ID_SA,
                "publisher": PUBLISHER,
                "status": "license_gap",
                "reason": "dated XLSX download unavailable",
            }
        )
        return {"points": points, "gaps": gaps, "qualitative": [], "attempts": attempts}

    try:
        value, period = _parse_xlsx_sa_level(xlsx_body)
    except ValueError as exc:
        gaps.append(
            {
                "id": CATALOG_ID_SA,
                "publisher": PUBLISHER,
                "status": "parse_failed",
                "reason": str(exc),
            }
        )
        return {"points": points, "gaps": gaps, "qualitative": [], "attempts": attempts}

    points.append(
        {
            "id": CATALOG_ID_SA,
            "publisher": PUBLISHER,
            "weight": 0.0,
            "period": period,
            "value": value,
            "units": UNITS,
            "index_base": INDEX_BASE,
            "transformation": "sa_level",
            "series_label": "seasonally_adjusted",
            "release_date": release_date.isoformat(),
            "raw_sha256": xlsx_sha,
            "source_url": xlsx_url,
            "vintage": f"release:{release_date.isoformat()}",
            "revision_status": "latest_available",
        }
    )
    return {"points": points, "gaps": gaps, "qualitative": [], "attempts": attempts}


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
