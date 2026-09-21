#!/usr/bin/env python3
"""Discover and harvest S&P Global / Judo Bank Australia Composite PMI from public press releases."""
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

from pypdf import PdfReader

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.market_state import BROWSER_USER_AGENT, fetch_bytes  # noqa: E402

PMI_LISTING_URL = "https://www.pmi.spglobal.com/Public/Release/PressReleases"
PMI_PRESS_RELEASE_BASE = "https://www.pmi.spglobal.com/Public/Home/PressRelease/"
SERIES_ID = "SP_GLOBAL_AU_COMPOSITE_PMI"
PUBLISHER = "S&P Global / Judo Bank"
PUBLISHER_FINAL = "S&P Global"
RAW_DIR = _ROOT / "data" / "temperature_history" / "raw" / "au"
REPORT_PATH = RAW_DIR / "harvest_report.json"
AU_JSON = _ROOT / "data" / "temperature_history" / "au.json"

LISTING_ROW_RE = re.compile(
    r'<span class="releaseDate">([^<]+)</span>\s*'
    r'<span class="releaseTitle">([^<]+)</span>\s*'
    r'<span class="greenListItem"><a href="([^"]+)"',
    re.IGNORECASE,
)
GUID_RE = re.compile(r"/PressRelease/([a-f0-9]{32})", re.IGNORECASE)

EMBARGO_AEST_RE = re.compile(
    r"Embargoed until\s+0900\s+(?:AEST|AEDT)\s+"
    r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})",
    re.IGNORECASE,
)
EMBARGO_AEST_PAREN_RE = re.compile(
    r"Embargoed until\s+0900\s+(?:AEST|AEDT)\s+"
    r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\s*\(",
    re.IGNORECASE,
)
HEADLINE_MONTH_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
    re.IGNORECASE,
)
DATA_COLLECTED_RE = re.compile(
    r"Data were collected\s+(\d{1,2})-(\d{1,2})\s+"
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

# Seeds from primary-source discovery (listing, search, cross-release restatement targets).
SEED_GUIDS: list[str] = [
    "75fd3562725941c4a3c77d176e93f929",
    "6c26872271534430bd2556521d2fe425",
    "76c27f9824f24fafaa9415a19c54ff19",
    "f300c58c8acc4c599c45f7ef16616b33",
    "3e446e09e41f474a900bdc93ce906d94",
    "d4a5504cf0174c5c9513484b01df7f3b",
    "c1101fa4aba847799a6e28e43e587053",
    "19b01742d07c4deaa90a63e5d585b150",
    "5e210a2556224269a36d74a5288687df",
    "fc9666a5c84d437f94e0fa46202d0aec",
    "5c5f34cfdfb1434b83f8eb4f2f9189da",
    "1406ace3389f4056ad742043ab5b2e92",
]

WINDOW_START = "2025-09"
WINDOW_END = "2026-09"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def press_release_url(guid: str) -> str:
    return f"{PMI_PRESS_RELEASE_BASE}{guid}"


def _curl_cffi_get(url: str, *, referer: str | None = None) -> tuple[int, bytes, str]:
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        return 0, b"", "curl_cffi not installed"
    headers = {"Referer": referer or PMI_LISTING_URL}
    try:
        resp = cffi_requests.get(url, impersonate="chrome", timeout=60, headers=headers)
        ctype = resp.headers.get("content-type", "")
        return resp.status_code, resp.content, ctype
    except Exception as exc:  # noqa: BLE001
        return 0, b"", str(exc)


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


def _local_cached_pdf(guid: str) -> bytes | None:
    guid_paths = {
        "5c5f34cfdfb1434b83f8eb4f2f9189da": RAW_DIR / "sp_australia_composite_2025-10.pdf",
        "75fd3562725941c4a3c77d176e93f929": RAW_DIR / "sp_australia_composite_2025-11.pdf",
        "6c26872271534430bd2556521d2fe425": RAW_DIR / "sp_australia_composite_2025-12.pdf",
        "f300c58c8acc4c599c45f7ef16616b33": RAW_DIR / "sp_australia_composite_2026-03.pdf",
        "3e446e09e41f474a900bdc93ce906d94": RAW_DIR / "sp_australia_composite_2026-04.pdf",
        "1406ace3389f4056ad742043ab5b2e92": RAW_DIR / "sp_australia_composite_2026-08.pdf",
        "76c27f9824f24fafaa9415a19c54ff19": RAW_DIR / "sp_australia_flash_composite_2026-02.pdf",
        "d4a5504cf0174c5c9513484b01df7f3b": RAW_DIR / "sp_australia_flash_composite_2026-04.pdf",
        "c1101fa4aba847799a6e28e43e587053": RAW_DIR / "sp_australia_flash_composite_2026-05.pdf",
        "19b01742d07c4deaa90a63e5d585b150": RAW_DIR / "sp_australia_flash_composite_2026-06.pdf",
        "5e210a2556224269a36d74a5288687df": RAW_DIR / "sp_australia_flash_composite_2026-07.pdf",
    }
    p = guid_paths.get(guid)
    if p and p.is_file():
        data = p.read_bytes()
        if data[:4] == b"%PDF":
            return data
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
    for _ in range(8):
        status, body, meta = _curl_cffi_get(PMI_LISTING_URL)
        if body and b"releaseTitle" in body:
            attempted.append(
                {
                    "url": PMI_LISTING_URL,
                    "http_status": status,
                    "failure_mode": None,
                    "notes": meta,
                }
            )
            return body.decode("utf-8", "replace")
        time.sleep(2)
    try:
        data = fetch_bytes(PMI_LISTING_URL, user_agent=BROWSER_USER_AGENT, retries=3)
        return data.decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        attempted.append(
            {
                "url": PMI_LISTING_URL,
                "http_status": None,
                "failure_mode": str(exc),
                "notes": "listing",
            }
        )
    return None


def discover_australia_listing(html: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for date_raw, title_raw, href in LISTING_ROW_RE.findall(html):
        title = unescape(title_raw).replace("\xa0", " ")
        if "Australia" not in title or "PMI" not in title:
            continue
        guid_match = GUID_RE.search(href)
        if not guid_match:
            continue
        rows.append(
            {
                "listing_release_utc": unescape(date_raw).replace("\xa0", " "),
                "title": title,
                "guid": guid_match.group(1),
                "source_url": press_release_url(guid_match.group(1)),
            }
        )
    return rows


def pdf_to_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def parse_embargo_release_date(text: str) -> str | None:
    match = EMBARGO_AEST_PAREN_RE.search(text) or EMBARGO_AEST_RE.search(text)
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
        return _month_year_to_period(collected.group(3), int(collected.group(4)))
    if is_flash:
        m = re.search(
            r"Flash Australia Composite PMI Output Index:\s*[\d.]+\s*\([^:]+:\s*[\d.]+\)",
            text,
            re.I,
        )
        if m:
            pass
        headline = re.search(
            r"Flash Australia PMI Composite Output Index[^\n]{0,120}?\(\w+:\s*[\d.]+\)",
            text,
            re.I,
        )
        if headline:
            pass
    for match in HEADLINE_MONTH_RE.finditer(text[:3500]):
        month = match.group(1)
        year = int(match.group(2))
        if month.lower() in {"news", "release"}:
            continue
        return _month_year_to_period(month, year)
    return None


def is_flash_release(text: str) -> bool:
    head = text[:2500].lower()
    return "flash australia" in head or "flash' pmi" in head or "flash australia pmi" in head


def parse_headline_composite(text: str, reference_period: str | None) -> float | None:
    patterns = [
        r"Composite\s+PMI\s+Output\s+Index:\s*([\d.]+)",
        r"Composite Output Index moved back.{0,220}?post(?:ing|ed)\s+([\d.]+)\s+from",
        r"Composite Output Index posted\s+(?:at\s+)?([\d.]+)\s+in\s+"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)",
        r"Composite Output Index[^\n]{0,50}posted\s+([\d.]+)\s+in\s+"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)",
        r"Composite Output Index[^\n]{0,40}posted\s+([\d.]+)",
        r"Composite Output Index[^\n]{0,60}?([\d.]+)\s+in\s+"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)",
    ]
    for pat in patterns:
        flags = re.I | (re.DOTALL if "moved back" in pat else 0)
        m = re.search(pat, text, flags)
        if not m:
            continue
        val = float(m.group(1))
        if len(m.groups()) >= 2 and m.group(2):
            period = _month_year_to_period(m.group(2), int(reference_period[:4]) if reference_period else 2026)
            if reference_period and period != reference_period:
                continue
        return val
    flash = re.search(
        r"Flash Australia PMI[^\n]{0,80}Composite Output Index[^\n]{0,40}posted\s+([\d.]+)",
        text,
        re.I,
    )
    if flash:
        return float(flash.group(1))
    flash2 = re.search(
        r"Composite Output Index posted\s+([\d.]+)\s+in\s+"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)",
        text,
        re.I,
    )
    if flash2:
        return float(flash2.group(1))
    return None


def parse_restated_priors(text: str, *, headline_period: str | None = None) -> dict[str, float]:
    priors: dict[str, float] = {}
    headline_year = int(headline_period[:4]) if headline_period else None
    month_pat = (
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    )
    for m in re.finditer(rf"\((\w{{3,9}}):\s*([\d.]+)\)", text):
        label = m.group(1).lower()
        for name, num in MONTH_MAP.items():
            if label.startswith(name[:3]):
                year_guess = None
                y = re.search(rf"{name}\s+(\d{{4}})", text, re.I)
                if y:
                    year_guess = int(y.group(1))
                if year_guess:
                    priors[f"{year_guess:04d}-{num:02d}"] = float(m.group(2))
                break
    for m in re.finditer(
        rf"(?:from|down from|up from)\s+([\d.]+)\s+in\s+{month_pat}",
        text,
        re.I,
    ):
        val = float(m.group(1))
        prior_month = m.group(2)
        y = re.search(rf"{prior_month}\s+(\d{{4}})", text, re.I)
        if y:
            year = int(y.group(1))
        elif headline_year and headline_period:
            year = headline_year
            if MONTH_MAP[prior_month.lower()] > int(headline_period[5:7]):
                year = headline_year - 1
        else:
            year = 2026
        priors[_month_year_to_period(prior_month, year)] = val
    for m in re.finditer(
        rf"in\s+({month_pat}),\s+down from\s+([\d.]+)\s+in\s+({month_pat})",
        text,
        re.I,
    ):
        headline_month = m.group(1)
        if not re.match(r"[\d.]+$", m.group(2)):
            continue
        prior_val = float(m.group(2))
        prior_month = m.group(3)
        y = re.search(rf"{headline_month}\s+(\d{{4}})", text, re.I)
        if y:
            year = int(y.group(1))
        elif headline_year and headline_period:
            year = headline_year
            if MONTH_MAP[prior_month.lower()] > MONTH_MAP[headline_month.lower()]:
                year = headline_year - 1
        else:
            year = 2026
        priors[_month_year_to_period(prior_month, year)] = prior_val
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
    publisher: str = PUBLISHER_FINAL,
) -> dict[str, Any]:
    return {
        "units": "diffusion_index",
        "transformation": "diffusion_index",
        "vintage": "latest_available",
        "retrieved_at": retrieved_at,
        "reference_period": reference_period,
        "value": value,
        "publisher": publisher,
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
    """Pick best observation per reference period (final beats flash; headline match beats restated)."""
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
                        f"{headline_period} Composite Output Index {headline_val} from "
                        f"{'flash' if flash else 'final'} S&P Global Australia PMI PDF."
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
                        f"{period} Composite Output Index {val} restated as prior month in "
                        f"{'flash' if flash else 'final'} PDF (release {release_date or 'unknown'})."
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
        if is_flash:
            name = f"sp_australia_flash_composite_{reference_period}.pdf"
        else:
            name = f"sp_australia_composite_{reference_period}.pdf"
    else:
        name = f"sp_australia_composite_unknown_{int(time.time())}.pdf"
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
    discovered = discover_australia_listing(listing_html) if listing_html else []

    guid_set: list[str] = []
    for g in SEED_GUIDS:
        if g not in guid_set:
            guid_set.append(g)
    if guids:
        for g in guids:
            if g not in guid_set:
                guid_set.append(g)
    for row in discovered:
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
        parsed_releases.append(
            {
                "guid": guid,
                "source_url": url,
                **meta,
            }
        )
        time.sleep(0.25)

    chosen = choose_observations(parsed_releases, retrieved_at=retrieved_at)

    target_periods = [
        f"2025-{m:02d}" for m in range(9, 13)
    ] + [f"2026-{m:02d}" for m in range(1, 10)]
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
                    "notes": "September 2026 PMI not published as of cutoff.",
                }
            )
            continue
        genuine_gaps.append(
            {
                "expected_period": period,
                "reason": "source inaccessible",
                "attempted_sources": [press_release_url(g) for g in guid_set[:6]],
                "failure_mode": "http_202_empty_or_challenge",
                "notes": (
                    "Primary PressRelease PDF not retrieved after curl_cffi, fetch_bytes, "
                    "local cache, and Wayback CDX."
                ),
            }
        )

    flash_count = sum(1 for r in parsed_releases if r.get("is_flash"))
    final_count = len(parsed_releases) - flash_count
    report = {
        "country": "AU",
        "cutoff": cutoff,
        "series_id": SERIES_ID,
        "retrieval_path": (
            "pmi_press_release_listing + PressRelease/{guid} PDF via curl_cffi chrome impersonation, "
            "fetch_bytes fallback, local raw cache, Wayback CDX id_ snapshot"
        ),
        "recovered_months": recovered,
        "genuine_gaps": genuine_gaps,
        "attempted_urls": attempted,
        "parser_notes": (
            "Composite Output Index from Australia Services or Flash Australia composite section; "
            "restated priors from parenthetical (Mon: x.x) and 'from x.x in Month' strings."
        ),
        "flash_vs_final": (
            f"Parsed {final_count} non-flash and {flash_count} flash PDFs; "
            "final revision_status preferred over preliminary when both exist for a month."
        ),
        "discovered_listing_rows": discovered,
        "parsed_release_count": len(parsed_releases),
    }
    return report


def merge_into_au_json(report: dict[str, Any], *, preserve_existing: bool = True) -> None:
    payload = json.loads(AU_JSON.read_text(encoding="utf-8"))
    component = payload["components"]["Activity.business_surveys"]
    existing_by_period = {
        o["reference_period"]: o for o in component["observations"] if o.get("series_id") == SERIES_ID
    }

    for obs in report.get("recovered_months") or []:
        period = obs["reference_period"]
        prev = existing_by_period.get(period)
        if prev and preserve_existing:
            prev_status = prev.get("revision_status", "final")
            new_status = obs.get("revision_status", "final")
            rank = {"final": 3, "revised": 2, "preliminary": 1}
            if rank.get(new_status, 0) < rank.get(prev_status, 0):
                continue
            if rank.get(new_status, 0) == rank.get(prev_status, 0) and prev.get("value") == obs.get("value"):
                continue
        if prev:
            component["observations"] = [
                o
                for o in component["observations"]
                if not (o.get("series_id") == SERIES_ID and o.get("reference_period") == period)
            ]
        component["observations"].append(obs)
        existing_by_period[period] = obs

    recovered_periods = {o["reference_period"] for o in report.get("recovered_months") or []}
    gaps = component.get("gaps") or []
    component["gaps"] = [g for g in gaps if g.get("expected_period") not in recovered_periods]
    scored_periods = {o["reference_period"] for o in component["observations"] if o.get("series_id") == SERIES_ID}
    for gap in report.get("genuine_gaps") or []:
        if gap["expected_period"] in scored_periods:
            continue
        if gap["expected_period"] not in recovered_periods:
            if not any(g.get("expected_period") == gap["expected_period"] for g in component["gaps"]):
                component["gaps"].append(
                    {
                        "expected_period": gap["expected_period"],
                        "reason": gap["reason"],
                        "attempted_sources": gap.get("attempted_sources", []),
                        "as_of": report["cutoff"],
                        "notes": gap.get("notes", ""),
                    }
                )

    composite_obs = [o for o in component["observations"] if o.get("series_id") == SERIES_ID]
    composite_obs.sort(key=lambda o: o["reference_period"])
    latest = composite_obs[-1] if composite_obs else None
    in_window = [o for o in composite_obs if _period_in_window(o["reference_period"])]
    component["coverage"] = {
        "expected_periods_in_window": 13,
        "observed_periods_in_window": len(in_window),
        "latest_reference_period": latest["reference_period"] if latest else None,
        "latest_release_date": latest.get("release_date") if latest else None,
        "status": "partial" if component["gaps"] else "ok",
        "gap_count": len(component["gaps"]),
    }
    payload["retrieved_at"] = report.get("cutoff", payload.get("retrieved_at"))
    AU_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Harvest S&P Global Australia Composite PMI")
    parser.add_argument("--cutoff", default="2026-09-21")
    parser.add_argument("--guid", action="append", dest="guids")
    parser.add_argument("--no-save-pdf", action="store_true")
    parser.add_argument("--write-au-json", action="store_true")
    parser.add_argument("--write-report", action="store_true", default=True)
    args = parser.parse_args()

    report = harvest(
        cutoff=args.cutoff,
        guids=args.guids,
        save_pdfs=not args.no_save_pdf,
        fetcher=fetch_bytes,
    )
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    if args.write_report:
        REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.write_au_json:
        merge_into_au_json(report)
    print(
        json.dumps(
            {
                "recovered": len(report["recovered_months"]),
                "gaps": len(report["genuine_gaps"]),
                "parsed": report["parsed_release_count"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
