#!/usr/bin/env python3
"""Discover and harvest S&P Global Eurozone Composite PMI from public press releases."""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
from datetime import date, datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

from pypdf import PdfReader

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.market_state import BROWSER_USER_AGENT, fetch_bytes  # noqa: E402

PMI_LISTING_URL = "https://www.pmi.spglobal.com/Public/Release/PressReleases"
PMI_PRESS_RELEASE_BASE = "https://www.pmi.spglobal.com/Public/Home/PressRelease/"
SERIES_ID = "SP_GLOBAL_EA_COMPOSITE_PMI"
PUBLISHER = "S&P Global"
RAW_DIR = _ROOT / "data" / "temperature_history" / "raw" / "ea"
REPORT_PATH = RAW_DIR / "harvest_report.json"
EA_JSON = _ROOT / "data" / "temperature_history" / "ea.json"

LISTING_ROW_RE = re.compile(
    r'<span class="releaseDate">([^<]+)</span>\s*'
    r'<span class="releaseTitle">([^<]+)</span>\s*'
    r'<span class="greenListItem"><a href="([^"]+)"',
    re.IGNORECASE,
)
GUID_RE = re.compile(r"/PressRelease/([a-f0-9]{32})", re.IGNORECASE)

EMBARGO_CET_RE = re.compile(
    r"Embargoed until\s+0900\s+(?:CET|CEST)\s+"
    r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})",
    re.IGNORECASE,
)
DATA_COLLECTED_RE = re.compile(
    r"Data were collected\s+\d{1,2}-\d{1,2}\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
    re.IGNORECASE,
)
HEADLINE_MONTH_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
    re.IGNORECASE,
)

MONTH_MAP = {
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

CURL_CFFI_IMPERSONATES = ("safari18_0", "chrome", "chrome131", "chrome120")

SEED_GUIDS: list[str] = [
    "28c3f5d8cd55496b976ee43ab2e1066f",  # 2025-09 HCOB final
    "223ebbc5708245de8b680cd0abf17f65",  # 2025-10 HCOB final
    "782bddb90d9a4258bb1efe5b6a46e86d",  # 2025-11 HCOB final
    "85a7e7b2b2864290b945f2bd8d7c41eb",  # 2025-12 HCOB final
    "96530bc528ed4c7d856ec7e770f9fbf9",  # 2026-01 HCOB final
    "2fda0e818e2047f3b5f1bc7e982f7249",  # 2026-02 HCOB final
    "a319e0a783f040d0b760d719f6160326",  # 2026-03 S&P final
    "e189dc5785424a6f9dd3384266699426",  # 2026-04 S&P final
    "e023f278ec0a499cbe1c6f97b8360695",  # 2026-05 S&P final
    "ee04639d3fa04104b6248a31a71ebd12",  # 2026-06 S&P final
    "6efbc02cd9b849e6aafcc6c3a9b703db",  # 2026-07 S&P final
    "0a3fb112708046bba18d27b555ce7ecb",  # 2026-08 S&P final (listing 2026-09-03)
]

WINDOW_START = "2025-09"
WINDOW_END = "2026-09"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def press_release_url(guid: str) -> str:
    return urljoin(PMI_PRESS_RELEASE_BASE, guid)


def _curl_cffi_get(url: str, *, referer: str | None = None) -> tuple[int, bytes, str]:
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        return 0, b"", "curl_cffi not installed"
    headers = {
        "Referer": referer or PMI_LISTING_URL,
        "Accept": "application/pdf,text/html,*/*",
    }
    last_status, last_body, last_meta = 0, b"", ""
    for impersonate in CURL_CFFI_IMPERSONATES:
        try:
            resp = cffi_requests.get(url, impersonate=impersonate, timeout=60, headers=headers)
            ctype = resp.headers.get("content-type", "")
            last_status, last_body, last_meta = resp.status_code, resp.content, f"{ctype}; {impersonate}"
            if resp.content[:4] == b"%PDF":
                return resp.status_code, resp.content, last_meta
        except Exception as exc:  # noqa: BLE001
            last_status, last_body, last_meta = 0, b"", f"{impersonate}: {exc}"
    return last_status, last_body, last_meta


def _local_cached_pdf(guid: str) -> bytes | None:
    for path in RAW_DIR.glob("sp_eurozone_*.pdf"):
        if guid in path.read_bytes()[:200]:
            pass
    guid_map = {
        "28c3f5d8cd55496b976ee43ab2e1066f": RAW_DIR / "sp_eurozone_composite_2025-09.pdf",
        "223ebbc5708245de8b680cd0abf17f65": RAW_DIR / "sp_eurozone_composite_2025-10.pdf",
        "782bddb90d9a4258bb1efe5b6a46e86d": RAW_DIR / "sp_eurozone_composite_2025-11.pdf",
        "85a7e7b2b2864290b945f2bd8d7c41eb": RAW_DIR / "sp_eurozone_composite_2025-12.pdf",
        "96530bc528ed4c7d856ec7e770f9fbf9": RAW_DIR / "sp_eurozone_composite_2026-01.pdf",
        "2fda0e818e2047f3b5f1bc7e982f7249": RAW_DIR / "sp_eurozone_composite_2026-02.pdf",
        "a319e0a783f040d0b760d719f6160326": RAW_DIR / "sp_eurozone_composite_2026-03.pdf",
        "e189dc5785424a6f9dd3384266699426": RAW_DIR / "sp_eurozone_composite_2026-04.pdf",
        "e023f278ec0a499cbe1c6f97b8360695": RAW_DIR / "sp_eurozone_composite_2026-05.pdf",
        "ee04639d3fa04104b6248a31a71ebd12": RAW_DIR / "sp_eurozone_composite_2026-06.pdf",
        "6efbc02cd9b849e6aafcc6c3a9b703db": RAW_DIR / "sp_eurozone_composite_2026-07.pdf",
        "0a3fb112708046bba18d27b555ce7ecb": RAW_DIR / "sp_eurozone_composite_2026-08.pdf",
    }
    path = guid_map.get(guid)
    if path and path.is_file():
        data = path.read_bytes()
        if data[:4] == b"%PDF":
            return data
    return None


def _wayback_pdf(url: str, *, attempted: list[dict[str, Any]]) -> bytes | None:
    cdx = (
        "https://web.archive.org/cdx/search/cdx?"
        f"url={url.replace('https://', '')}&output=json&filter=statuscode:200"
        "&filter=mimetype:application/pdf&limit=1"
    )
    try:
        raw = fetch_bytes(cdx, user_agent=BROWSER_USER_AGENT, retries=2, timeout=45)
        rows = json.loads(raw.decode("utf-8", errors="replace"))
        if len(rows) < 2:
            attempted.append(
                {"url": cdx, "http_status": 200, "failure_mode": "wayback_no_snapshot", "notes": url}
            )
            return None
        ts = rows[1][1]
        wb_url = f"https://web.archive.org/web/{ts}id_/{url}"
        status, body, meta = _curl_cffi_get(wb_url)
        attempted.append(
            {
                "url": wb_url,
                "http_status": status or None,
                "failure_mode": None if body[:4] == b"%PDF" else "wayback_non_pdf",
                "notes": meta,
            }
        )
        if body[:4] == b"%PDF" and len(body) > 5000:
            return body
    except Exception as exc:  # noqa: BLE001
        attempted.append(
            {"url": url, "http_status": None, "failure_mode": f"wayback_error: {exc}", "notes": "cdx"}
        )
    return None


def fetch_release_bytes(
    url: str,
    *,
    guid: str,
    fetcher: Callable[..., bytes] | None,
    attempted: list[dict[str, Any]],
) -> bytes | None:
    status, body, meta = _curl_cffi_get(url)
    failure = ""
    if status == 202 and body[:4] != b"%PDF":
        failure = "http_202_empty_or_challenge"
    elif status == 200 and not body:
        failure = "empty_body"
    attempted.append(
        {
            "url": url,
            "http_status": status or None,
            "failure_mode": failure or (None if body[:4] == b"%PDF" else "non_pdf_body"),
            "notes": f"bytes={len(body)}; {meta}",
        }
    )
    if body[:4] == b"%PDF" and len(body) > 5000:
        return body

    if fetcher is not None:
        try:
            data = fetcher(url, user_agent=BROWSER_USER_AGENT, referer=PMI_LISTING_URL, retries=3)
            attempted.append(
                {
                    "url": url,
                    "http_status": 200,
                    "failure_mode": None if data[:4] == b"%PDF" else "non_pdf_body",
                    "notes": f"fetch_bytes bytes={len(data)}",
                }
            )
            if data[:4] == b"%PDF" and len(data) > 5000:
                return data
        except Exception as exc:  # noqa: BLE001
            attempted.append(
                {"url": url, "http_status": None, "failure_mode": str(exc), "notes": "fetch_bytes"}
            )

    cached = _local_cached_pdf(guid)
    if cached:
        attempted.append(
            {
                "url": url,
                "http_status": 200,
                "failure_mode": None,
                "notes": f"local_cache bytes={len(cached)}",
            }
        )
        return cached

    wb = _wayback_pdf(url, attempted=attempted)
    if wb:
        return wb
    return None


def fetch_listing_html(*, attempted: list[dict[str, Any]]) -> str | None:
    status, body, meta = _curl_cffi_get(PMI_LISTING_URL)
    attempted.append(
        {
            "url": PMI_LISTING_URL,
            "http_status": status or None,
            "failure_mode": None if body and b"releaseTitle" in body else "listing_unavailable",
            "notes": meta,
        }
    )
    if body and b"releaseTitle" in body:
        return body.decode("utf-8", "replace")
    try:
        data = fetch_bytes(PMI_LISTING_URL, user_agent=BROWSER_USER_AGENT, retries=3)
        return data.decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        attempted.append(
            {
                "url": PMI_LISTING_URL,
                "http_status": None,
                "failure_mode": str(exc),
                "notes": "fetch_bytes listing",
            }
        )
    return None


_ENGLISH_EA_COMPOSITE_TITLES = frozenset(
    {
        "S&P Global Eurozone Composite PMI",
        "S&P Global Flash Eurozone Composite PMI",
        # HCOB was the S&P Eurozone composite sponsor through early 2026.
        "HCOB Eurozone Composite PMI",
        "HCOB Flash Eurozone PMI",
        "HCOB Flash Eurozone Composite PMI",
    }
)


def discover_eurozone_composite_listing(html: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for date_raw, title_raw, href in LISTING_ROW_RE.findall(html):
        title = unescape(title_raw).replace("\xa0", " ")
        if title not in _ENGLISH_EA_COMPOSITE_TITLES:
            continue
        if "Germany" in title or "EU " in title:
            continue
        guid_match = GUID_RE.search(href)
        if not guid_match:
            continue
        guid = guid_match.group(1)
        if guid in seen:
            continue
        seen.add(guid)
        rows.append(
            {
                "listing_release_utc": unescape(date_raw).replace("\xa0", " "),
                "title": title,
                "guid": guid,
                "source_url": press_release_url(guid),
            }
        )
    return rows


def discover_guids_from_wayback_listings(
    *,
    from_yyyymmdd: str = "20250901",
    to_yyyymmdd: str = "20260921",
    attempted: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    """Enumerate English Eurozone composite GUIDs from archived S&P listing pages."""
    attempted = attempted if attempted is not None else []
    cdx = (
        "https://web.archive.org/cdx/search/cdx?"
        f"url={PMI_LISTING_URL.replace('https://', '')}&output=json"
        f"&from={from_yyyymmdd}&to={to_yyyymmdd}&filter=statuscode:200&limit=200"
    )
    rows: list[list[str]] = []
    try:
        from curl_cffi import requests as cffi_requests

        resp = cffi_requests.get(cdx, impersonate="chrome", timeout=120)
        attempted.append(
            {
                "url": cdx,
                "http_status": resp.status_code,
                "failure_mode": None if resp.status_code == 200 else "cdx_http_error",
                "notes": f"bytes={len(resp.content)}",
            }
        )
        if resp.status_code == 200 and resp.text.strip().startswith("["):
            rows = json.loads(resp.text)
    except Exception as exc:  # noqa: BLE001
        attempted.append(
            {"url": cdx, "http_status": None, "failure_mode": f"cdx_error: {exc}", "notes": ""}
        )
    if len(rows) < 2:
        return []

    discovered: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows[1:]:
        ts = row[1]
        wb_url = f"https://web.archive.org/web/{ts}id_/{PMI_LISTING_URL}"
        status, body, meta = _curl_cffi_get(wb_url)
        attempted.append(
            {
                "url": wb_url,
                "http_status": status or None,
                "failure_mode": None if body and b"releaseTitle" in body else "wayback_listing_unavailable",
                "notes": meta,
            }
        )
        if not body or b"releaseTitle" not in body:
            continue
        html = body.decode("utf-8", errors="replace")
        for item in discover_eurozone_composite_listing(html):
            if item["guid"] in seen:
                continue
            seen.add(item["guid"])
            discovered.append(item)
        time.sleep(0.1)
    return discovered


def pdf_to_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def parse_embargo_release_date(text: str) -> str | None:
    match = EMBARGO_CET_RE.search(text)
    if not match:
        return None
    day = int(match.group(1))
    month = MONTH_MAP[match.group(2).lower()]
    year = int(match.group(3))
    return date(year, month, day).isoformat()


def _month_year_to_period(month_name: str, year: int) -> str:
    return f"{year:04d}-{MONTH_MAP[month_name.lower()]:02d}"


def infer_reference_period(text: str, *, is_flash: bool) -> str | None:
    collected = DATA_COLLECTED_RE.search(text)
    if collected:
        return _month_year_to_period(collected.group(1), int(collected.group(2)))
    if is_flash:
        flash = re.search(
            r"Flash Eurozone Composite PMI Output Index[^\n]{0,80}(\w+ \d{4})",
            text,
            re.I,
        )
        if flash:
            m = HEADLINE_MONTH_RE.search(flash.group(1))
            if m:
                return _month_year_to_period(m.group(1), int(m.group(2)))
    for match in HEADLINE_MONTH_RE.finditer(text[:4000]):
        month = match.group(1)
        year = int(match.group(2))
        if month.lower() in {"release", "comment"}:
            continue
        return _month_year_to_period(month, year)
    return None


def is_flash_release(text: str) -> bool:
    head = text[:2500].lower()
    return "flash eurozone" in head or "flash euro area" in head


def parse_headline_composite(text: str, reference_period: str | None) -> float | None:
    patterns = [
        r"HCOB Eurozone Composite PMI Output\s*Index at\s+([\d.]+)",
        r"Eurozone Composite PMI Output\s*Index at\s+([\d.]+)",
        r"Eurozone Composite PMI Output\s*Index[^\n]{0,40}posted\s+([\d.]+)",
        r"Composite PMI Output\s*Index at\s+([\d.]+)",
        r"Composite PMI Output Index[^\n]{0,60}?posted\s+([\d.]+)\s+in\s+"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)",
        r"Flash Eurozone Composite PMI Output Index:\s*([\d.]+)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I | re.DOTALL)
        if not m:
            continue
        val = float(m.group(1))
        if len(m.groups()) >= 2 and m.group(2):
            period = _month_year_to_period(m.group(2), int(reference_period[:4]) if reference_period else 2026)
            if reference_period and period != reference_period:
                continue
        return val
    return None


def parse_restated_priors(text: str, *, headline_period: str | None = None) -> dict[str, float]:
    priors: dict[str, float] = {}
    headline_year = int(headline_period[:4]) if headline_period else None
    month_pat = (
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    )
    for m in re.finditer(r"\((\w{3,9}):\s*([\d.]+)\)", text):
        label = m.group(1).lower()
        for name, num in MONTH_MAP.items():
            if label.startswith(name[:3]):
                y = re.search(rf"{name}\s+(\d{{4}})", text, re.I)
                if y:
                    priors[f"{int(y.group(1)):04d}-{num:02d}"] = float(m.group(2))
                break
    for m in re.finditer(
        rf"(?:from|down from|up from)\s+([\d.]+)\s+in\s+{month_pat}",
        text,
        re.I,
    ):
        prior_month = m.group(2)
        y = re.search(rf"{prior_month}\s+(\d{{4}})", text, re.I)
        year = int(y.group(1)) if y else (headline_year or 2026)
        priors[_month_year_to_period(prior_month, year)] = float(m.group(1))
    return priors


def parse_release_artifact(data: bytes) -> dict[str, Any]:
    text = pdf_to_text(data)
    flash = is_flash_release(text)
    ref = infer_reference_period(text, is_flash=flash)
    composite = parse_headline_composite(text, ref)
    return {
        "text": text,
        "release_date": parse_embargo_release_date(text),
        "reference_period": ref,
        "composite_value": composite,
        "is_flash": flash,
        "restated_priors": parse_restated_priors(text, headline_period=ref),
    }


def observation_from_release(
    reference_period: str,
    value: float,
    source_url: str,
    release_date: str | None,
    *,
    revision_status: str,
    retrieved_at: str,
    notes: str,
) -> dict[str, Any]:
    return {
        "units": "diffusion_index",
        "transformation": "diffusion_index",
        "vintage": "latest_available",
        "retrieved_at": retrieved_at,
        "reference_period": reference_period,
        "value": value,
        "publisher": PUBLISHER,
        "source_url": source_url,
        "release_date": release_date or "",
        "revision_status": revision_status,
        "series_id": SERIES_ID,
        "notes": notes,
    }


def _period_in_window(period: str) -> bool:
    return WINDOW_START <= period <= WINDOW_END


def choose_observations(
    parsed_releases: list[dict[str, Any]],
    *,
    retrieved_at: str,
) -> dict[str, dict[str, Any]]:
    by_period: dict[str, list[dict[str, Any]]] = {}
    for rel in parsed_releases:
        url = rel["source_url"]
        release_date = rel.get("release_date")
        flash = rel.get("is_flash", False)
        status = "preliminary" if flash else "final"
        headline_period = rel.get("reference_period")
        headline_val = rel.get("composite_value")
        if headline_period and headline_val is not None and _period_in_window(headline_period):
            by_period.setdefault(headline_period, []).append(
                {
                    "value": float(headline_val),
                    "source_url": url,
                    "release_date": release_date,
                    "revision_status": status,
                    "headline": True,
                    "notes": (
                        f"{headline_period} Eurozone Composite Output Index {headline_val} from "
                        f"{'flash' if flash else 'final'} S&P Global PDF."
                    ),
                }
            )
        for period, val in (rel.get("restated_priors") or {}).items():
            if not _period_in_window(period):
                continue
            by_period.setdefault(period, []).append(
                {
                    "value": float(val),
                    "source_url": url,
                    "release_date": release_date,
                    "revision_status": "revised",
                    "headline": False,
                    "notes": (
                        f"{period} restated prior {val} in "
                        f"{'flash' if flash else 'final'} Eurozone composite PDF."
                    ),
                }
            )

    chosen: dict[str, dict[str, Any]] = {}
    for period, candidates in by_period.items():

        def rank(c: dict[str, Any]) -> tuple[int, int, str]:
            status_score = {"final": 3, "revised": 2, "preliminary": 1}.get(c["revision_status"], 0)
            headline_score = 1 if c.get("headline") else 0
            return (status_score, headline_score, c.get("release_date") or "")

        best = sorted(candidates, key=rank)[-1]
        chosen[period] = observation_from_release(
            period,
            best["value"],
            best["source_url"],
            best.get("release_date"),
            revision_status=best["revision_status"],
            retrieved_at=retrieved_at,
            notes=best["notes"],
        )
    return chosen


def save_pdf(data: bytes, *, reference_period: str | None, is_flash: bool) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    if reference_period:
        name = (
            f"sp_eurozone_flash_composite_{reference_period}.pdf"
            if is_flash
            else f"sp_eurozone_composite_{reference_period}.pdf"
        )
    else:
        name = f"sp_eurozone_composite_unknown_{int(time.time())}.pdf"
    path = RAW_DIR / name
    path.write_bytes(data)
    return path


def harvest(
    *,
    cutoff: str,
    guids: list[str] | None = None,
    save_pdfs: bool = True,
    fetcher: Callable[..., bytes] | None = None,
) -> dict[str, Any]:
    retrieved_at = utc_now_iso()
    attempted: list[dict[str, Any]] = []
    listing_html = fetch_listing_html(attempted=attempted)
    discovered = discover_eurozone_composite_listing(listing_html) if listing_html else []
    wayback_discovered = discover_guids_from_wayback_listings(attempted=attempted)

    guid_set: list[str] = []
    for g in SEED_GUIDS:
        if g not in guid_set:
            guid_set.append(g)
    if guids:
        for g in guids:
            if g not in guid_set:
                guid_set.append(g)
    for row in discovered + wayback_discovered:
        if row["guid"] not in guid_set:
            guid_set.append(row["guid"])

    parsed_releases: list[dict[str, Any]] = []
    for guid in guid_set:
        url = press_release_url(guid)
        data = fetch_release_bytes(url, guid=guid, fetcher=fetcher, attempted=attempted)
        if not data:
            continue
        meta = parse_release_artifact(data)
        if save_pdfs:
            save_pdf(
                data,
                reference_period=meta.get("reference_period"),
                is_flash=meta.get("is_flash", False),
            )
        parsed_releases.append({"guid": guid, "source_url": url, **meta})
        time.sleep(0.25)

    chosen = choose_observations(parsed_releases, retrieved_at=retrieved_at)
    target_periods = [f"2025-{m:02d}" for m in range(9, 13)] + [
        f"2026-{m:02d}" for m in range(1, 10)
    ]
    target_periods = [p for p in target_periods if p <= cutoff[:7]]

    recovered = [chosen[p] for p in sorted(chosen) if p in target_periods]
    recovered_periods = {o["reference_period"] for o in recovered}
    genuine_gaps: list[dict[str, Any]] = []
    for period in target_periods:
        if period in recovered_periods:
            continue
        if period >= "2026-09":
            genuine_gaps.append(
                {
                    "expected_period": period,
                    "reason": "not yet released",
                    "attempted_sources": [PMI_LISTING_URL],
                    "failure_mode": "future_release",
                    "notes": "Reference month not published as of cutoff.",
                }
            )
            continue
        genuine_gaps.append(
            {
                "expected_period": period,
                "reason": "primary PDF not retrieved",
                "attempted_sources": [press_release_url(g) for g in guid_set[:8]],
                "failure_mode": "listing_single_month_only",
                "notes": (
                    "S&P listing exposes only the latest Eurozone Composite PMI; "
                    "historical months require committed PDFs or Wayback snapshots."
                ),
            }
        )

    report = {
        "country": "EA",
        "cutoff": cutoff,
        "series_id": SERIES_ID,
        "retrieval_path": (
            "pmi_press_release_listing + PressRelease/{guid} PDF via curl_cffi "
            "(safari18_0/chrome), fetch_bytes, local cache, Wayback id_"
        ),
        "recovered_months": recovered,
        "genuine_gaps": genuine_gaps,
        "attempted_urls": attempted,
        "parser_notes": (
            "English title 'S&P Global Eurozone Composite PMI' only; "
            "Composite Output Index from headline line; final beats flash."
        ),
        "do_not_score": ["Trading Economics", "Markit legacy vendor tables"],
        "discovered_listing_rows": discovered,
        "discovered_wayback_listing_rows": wayback_discovered,
        "parsed_release_count": len(parsed_releases),
    }
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def merge_into_ea_json(report: dict[str, Any], *, ea_path: Path = EA_JSON) -> None:
    if ea_path.is_file():
        history = json.loads(ea_path.read_text(encoding="utf-8"))
    else:
        history = {
            "country": "EA",
            "window": {"start": WINDOW_START + "-21", "end": WINDOW_END + "-21"},
            "retrieved_at": utc_now_iso(),
            "notes": "",
            "components": {},
        }
    from scripts.euro_area_macro_data import merge_pmi_component  # noqa: WPS433

    merge_pmi_component(
        history,
        report.get("recovered_months", []),
        gaps=report.get("genuine_gaps"),
    )
    ea_path.parent.mkdir(parents=True, exist_ok=True)
    ea_path.write_text(json.dumps(history, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Harvest S&P Global Eurozone Composite PMI.")
    parser.add_argument("--cutoff", default=WINDOW_END + "-21")
    parser.add_argument("--merge-ea-json", action="store_true")
    args = parser.parse_args(argv)
    report = harvest(cutoff=args.cutoff)
    if args.merge_ea_json:
        merge_into_ea_json(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
