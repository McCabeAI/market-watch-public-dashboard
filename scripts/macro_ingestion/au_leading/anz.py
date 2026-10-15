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

from scripts.macro_ingestion.au_leading.asof import observation_eligible
from scripts.macro_ingestion.au_leading.discovery import (
    MAX_PAGES,
    bounded_get,
    failure_class,
    honest_transport_failure,
)

CATALOG_ID_SA = "AU.Labor.anz_indeed_job_ads_sa"
PUBLISHER = "anz_indeed"

NEWSROOM_INDEX_URL = "https://www.anz.com.au/newsroom/media/"
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


_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
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
    return {"id": CATALOG_ID_SA, "publisher": PUBLISHER, "status": status, "reason": reason}


def _index_press_links(html: str) -> list[str]:
    found: list[str] = []
    for match in re.finditer(r'href="([^"]+)"', html, flags=re.IGNORECASE):
        href = unescape(match.group(1))
        lowered = href.lower()
        if "job-ads" not in lowered and "job_ads" not in lowered and "job ads" not in lowered:
            continue
        if href.startswith("http"):
            url = href
        elif href.startswith("/"):
            url = urljoin("https://www.anz.com.au/", href)
        else:
            url = urljoin(NEWSROOM_INDEX_URL, href)
        if url not in found:
            found.append(url)
        if len(found) >= MAX_PAGES:
            break
    return found


def _period_from_xlsx_name(url: str) -> str | None:
    match = re.search(r"data_([A-Za-z]{3})(\d{2})\.xlsx", url, flags=re.IGNORECASE)
    if not match:
        return None
    month = _MONTHS.get(match.group(1).lower())
    if month is None:
        return None
    year = 2000 + int(match.group(2))
    return f"{year:04d}-{month:02d}"


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
    opener: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    attempts: list[FetchAttempt] = []
    gaps: list[dict[str, str]] = []
    points: list[dict[str, Any]] = []

    index = bounded_get(opener, NEWSROOM_INDEX_URL)
    _record_attempt(attempts, NEWSROOM_INDEX_URL, index, ok_outcome="parsed")
    candidates: list[dict[str, Any]] = []
    if honest_transport_failure(index):
        gaps.append(
            _gap(
                failure_class(index) or "source_failed",
                str(index.get("error") or f"ANZ newsroom index transport failure HTTP {index.get('http_status')}"),
            )
        )
        return {"points": points, "gaps": gaps, "qualitative": [], "attempts": attempts}
    if index.get("ok") and index.get("body"):
        html = (index.get("body") or b"").decode("utf-8", errors="replace")
        for url in _index_press_links(html):
            candidates.append({"press_url": url, "provenance": "publisher_index", "reference_period": None})
    if not candidates:
        gaps.append(
            _gap(
                "discovery_gap",
                "ANZ newsroom index did not list a dated job-ads release; controlled vintage index used",
            )
        )
        candidates.append(
            {
                "press_url": PRESS_RELEASE_URL,
                "provenance": "controlled_release_index",
                "reference_period": REFERENCE_PERIOD,
                "release_date": RELEASE_DATE,
            }
        )

    chosen: dict[str, Any] | None = None
    for cand in candidates[:MAX_PAGES]:
        press_url = str(cand["press_url"])
        press = bounded_get(opener, press_url)
        _record_attempt(attempts, press_url, press, ok_outcome="parsed")
        if honest_transport_failure(press):
            gaps.append(
                _gap(
                    failure_class(press) or "source_failed",
                    str(press.get("error") or "ANZ press release transport failure"),
                )
            )
            continue
        if not press.get("ok") or not press.get("body"):
            gaps.append(_gap("source_failed", str(press.get("error") or "press release fetch failed")))
            continue
        html = (press.get("body") or b"").decode("utf-8", errors="replace")
        release_date = _parse_release_date_from_html(html) or cand.get("release_date")
        if release_date is None:
            gaps.append(_gap("source_failed", f"release date missing on {press_url}"))
            continue
        if not observation_eligible(release_date, as_of):
            gaps.append(
                _gap(
                    "not_yet_released",
                    f"release_date {release_date.isoformat()} not eligible at as_of {as_of.isoformat()}",
                )
            )
            continue
        xlsx_url = _discover_xlsx_url(html, press_url)
        if xlsx_url is None and cand.get("provenance") == "controlled_release_index":
            xlsx_url = DEFAULT_XLSX_URL
        if not xlsx_url:
            gaps.append(_gap("source_failed", f"job-ads workbook link missing on {press_url}"))
            continue
        reference_period = cand.get("reference_period") or _period_from_xlsx_name(xlsx_url)
        if chosen is None or release_date > chosen["release_date"]:
            chosen = {
                "press_url": press_url,
                "release_date": release_date,
                "xlsx_url": xlsx_url,
                "reference_period": reference_period,
                "provenance": cand.get("provenance") or "publisher_index",
            }

    if chosen is None:
        if not any(g.get("status") == "not_yet_released" for g in gaps):
            gaps.append(_gap("source_failed", "no eligible ANZ–Indeed release discovered"))
        return {"points": points, "gaps": gaps, "qualitative": [], "attempts": attempts}

    xlsx_url = str(chosen["xlsx_url"])
    xlsx = bounded_get(opener, xlsx_url)
    xlsx_body = xlsx.get("body") or b""
    _record_attempt(attempts, xlsx_url, xlsx, ok_outcome="parsed")
    if not xlsx.get("ok") or not xlsx_body:
        status = failure_class(xlsx) or "license_gap"
        gaps.append(_gap(status, str(xlsx.get("error") or "dated XLSX download unavailable")))
        return {"points": points, "gaps": gaps, "qualitative": [], "attempts": attempts}

    try:
        if chosen.get("reference_period"):
            value, period = _parse_xlsx_sa_level(xlsx_body, target_period=str(chosen["reference_period"]))
        else:
            value, period = _parse_xlsx_sa_level(xlsx_body, target_period=REFERENCE_PERIOD)
    except ValueError as exc:
        gaps.append(_gap("parse_failed", str(exc)))
        return {"points": points, "gaps": gaps, "qualitative": [], "attempts": attempts}

    release_date = chosen["release_date"]
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
            "raw_sha256": _sha256(xlsx_body),
            "source_url": xlsx_url,
            "vintage": f"release:{release_date.isoformat()}",
            "revision_status": "latest_available",
            "provenance": chosen["provenance"],
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
