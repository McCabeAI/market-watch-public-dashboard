#!/usr/bin/env python3
"""Discover and harvest S&P Global Canada Composite PMI Output Index from public press releases."""
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
SERIES_ID = "SP_GLOBAL_CA_COMPOSITE"
PUBLISHER = "S&P Global"
RAW_DIR = _ROOT / "data" / "temperature_history" / "raw" / "ca"
REPORT_PATH = RAW_DIR / "harvest_report.json"
CA_JSON = _ROOT / "data" / "temperature_history" / "ca.json"

LISTING_ROW_RE = re.compile(
    r'<span class="releaseDate">([^<]+)</span>\s*'
    r'<span class="releaseTitle">([^<]+)</span>\s*'
    r'<span class="greenListItem"><a href="([^"]+)"',
    re.IGNORECASE,
)
GUID_RE = re.compile(r"/PressRelease/([a-f0-9]{32})", re.IGNORECASE)
EMBARGO_RE = re.compile(
    r"Embargoed until\s+0930\s+EDT\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})",
    re.IGNORECASE,
)
HEADLINE_MONTH_RE = re.compile(
    r"####\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
    re.IGNORECASE,
)
DATA_COLLECTED_RE = re.compile(
    r"Data were collected\s+\d{1,2}-\d{1,2}\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
    re.IGNORECASE,
)
STANDALONE_MONTH_RE = re.compile(
    r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\s*$",
    re.IGNORECASE | re.MULTILINE,
)
CURL_CFFI_IMPERSONATES = ("safari18_0", "chrome", "chrome131", "chrome120")
# Primary PressRelease GUIDs recovered from the S&P listing / embargo search.
SEED_GUIDS: list[str] = [
    "b407c9ea0281441b9c39f5248f1fc263",  # 2026-06
    "b28d51a7ae54422e9e991e6ea2b06643",  # 2026-07
    "8b925a72bf154a35becc7364eb6e7e58",  # 2026-08
]
GUID_TO_LOCAL_PDF = {
    "b407c9ea0281441b9c39f5248f1fc263": RAW_DIR / "sp_canada_composite_2026-06.pdf",
    "b28d51a7ae54422e9e991e6ea2b06643": RAW_DIR / "sp_canada_composite_2026-07.pdf",
    "8b925a72bf154a35becc7364eb6e7e58": RAW_DIR / "sp_canada_composite_2026-08.pdf",
}
COMPOSITE_VALUE_RE = re.compile(
    r"S&P Global Canada Composite PMI.{0,400}?"
    r"(?:recorded|recording|registering|registered)\s+(\d+(?:\.\d+)?)",
    re.IGNORECASE | re.DOTALL,
)
COMPOSITE_VALUE_ALT_RE = re.compile(
    r"Composite PMI Output Index\*?\s+recorded\s+(\d+(?:\.\d+)?)",
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
            resp = cffi_requests.get(
                url, impersonate=impersonate, timeout=60, headers=headers
            )
            ctype = resp.headers.get("content-type", "")
            last_status, last_body, last_meta = resp.status_code, resp.content, f"{ctype}; {impersonate}"
            if resp.content[:4] == b"%PDF":
                return resp.status_code, resp.content, last_meta
        except Exception as exc:  # noqa: BLE001
            last_status, last_body, last_meta = 0, b"", f"{impersonate}: {exc}"
    return last_status, last_body, last_meta


def local_cached_pdf(guid: str) -> bytes | None:
    path = GUID_TO_LOCAL_PDF.get(guid)
    if path is not None and path.is_file() and path.stat().st_size > 1000:
        data = path.read_bytes()
        if data[:4] == b"%PDF":
            return data
    return None


def fetch_release_bytes(
    url: str,
    *,
    guid: str | None = None,
    fetcher: Callable[..., bytes] | None = None,
    attempted: list[dict[str, Any]],
) -> bytes | None:
    """Try curl_cffi (CloudFront), then market_state.fetch_bytes, then committed PDF cache."""
    status, body, meta = _curl_cffi_get(url)
    failure = "empty body" if status == 200 and not body else ""
    if status == 202 and (not body or body[:5] != b"%PDF"):
        failure = "http_202_challenge_or_empty"
    attempted.append(
        {
            "url": url,
            "http_status": status or None,
            "failure_mode": failure or (None if body[:4] == b"%PDF" else f"non_pdf_body ({meta})"),
            "notes": f"bytes={len(body)}",
        }
    )
    if body[:4] == b"%PDF" and len(body) > 1000:
        return body

    alt_urls = [
        url,
        f"{url}?format=pdf",
    ]
    for alt in alt_urls:
        if fetcher is None:
            continue
        try:
            data = fetcher(
                alt,
                user_agent=BROWSER_USER_AGENT,
                referer=PMI_LISTING_URL,
                retries=2,
            )
            attempted.append(
                {
                    "url": alt,
                    "http_status": 200,
                    "failure_mode": None if data[:4] == b"%PDF" else "non_pdf_body",
                    "notes": f"fetch_bytes bytes={len(data)}",
                }
            )
            if data[:4] == b"%PDF" and len(data) > 1000:
                return data
        except Exception as exc:  # noqa: BLE001
            attempted.append(
                {
                    "url": alt,
                    "http_status": None,
                    "failure_mode": str(exc),
                    "notes": "fetch_bytes",
                }
            )
    if guid:
        cached = local_cached_pdf(guid)
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
    return None


def discover_canada_services_listing(html: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for date_raw, title_raw, href in LISTING_ROW_RE.findall(html):
        title = unescape(title_raw).replace("\xa0", " ")
        if "Canada Services PMI" not in title or "Français" in title or "Francais" in title:
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


def fetch_listing_html(
    *,
    attempted: list[dict[str, Any]],
) -> str | None:
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


def pdf_to_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def parse_embargo_release_date(text: str) -> str | None:
    match = EMBARGO_RE.search(text)
    if not match:
        return None
    day = int(match.group(1))
    month = MONTH_MAP[match.group(2).lower()]
    year = int(match.group(3))
    return date(year, month, day).isoformat()


def parse_headline_reference_period(text: str) -> str | None:
    for pattern in (HEADLINE_MONTH_RE, DATA_COLLECTED_RE, STANDALONE_MONTH_RE):
        match = pattern.search(text)
        if not match:
            continue
        month = MONTH_MAP[match.group(1).lower()]
        year = int(match.group(2))
        return f"{year:04d}-{month:02d}"
    return None


def parse_composite_output_index(text: str) -> float | None:
    for pattern in (COMPOSITE_VALUE_RE, COMPOSITE_VALUE_ALT_RE):
        match = pattern.search(text)
        if match:
            return float(match.group(1))
    return None


def parse_release_artifact(data: bytes) -> dict[str, Any]:
    text = pdf_to_text(data)
    return {
        "text": text,
        "release_date": parse_embargo_release_date(text),
        "reference_period": parse_headline_reference_period(text),
        "composite_value": parse_composite_output_index(text),
    }


def choose_best_release(
    parsed_releases: list[dict[str, Any]],
    reference_period: str,
) -> dict[str, Any] | None:
    headline_matches = [r for r in parsed_releases if r.get("reference_period") == reference_period]
    if not headline_matches:
        return None
    return sorted(headline_matches, key=lambda r: r.get("release_date") or "")[-1]


def observation_from_release(
    reference_period: str,
    value: float,
    source_url: str,
    release_date: str,
    *,
    revision_status: str = "final",
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
        "release_date": release_date,
        "revision_status": revision_status,
        "series_id": SERIES_ID,
        "notes": notes,
    }


def harvest(
    *,
    cutoff: str,
    guids: list[str] | None = None,
    save_pdf: bool = True,
    fetcher: Callable[..., bytes] | None = None,
) -> dict[str, Any]:
    retrieved_at = utc_now_iso()
    attempted: list[dict[str, Any]] = []
    listing_html = fetch_listing_html(attempted=attempted)
    discovered: list[dict[str, str]] = []
    if listing_html:
        discovered = discover_canada_services_listing(listing_html)

    guid_set: list[str] = []
    for seed in SEED_GUIDS:
        if seed not in guid_set:
            guid_set.append(seed)
    if guids:
        for extra in guids:
            if extra not in guid_set:
                guid_set.append(extra)
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
        ref = meta.get("reference_period")
        if ref and save_pdf:
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            (RAW_DIR / f"sp_canada_composite_{ref}.pdf").write_bytes(data)
        parsed_releases.append(
            {
                "guid": guid,
                "source_url": url,
                "release_date": meta.get("release_date"),
                "reference_period": meta.get("reference_period"),
                "composite_value": meta.get("composite_value"),
            }
        )
        time.sleep(0.3)

    # Target months in cutoff window missing from scored history (Jun–Aug 2026 audit)
    target_periods = ["2026-06", "2026-07", "2026-08"]
    recovered: list[dict[str, Any]] = []
    genuine_gaps: list[dict[str, Any]] = []

    for period in target_periods:
        best = choose_best_release(parsed_releases, period)
        if best and best.get("composite_value") is not None and best.get("release_date"):
            recovered.append(
                observation_from_release(
                    period,
                    float(best["composite_value"]),
                    best["source_url"],
                    best["release_date"],
                    retrieved_at=retrieved_at,
                    notes=(
                        f"{period} Composite Output Index from S&P Global Canada Services PMI PDF "
                        f"(embargo {best['release_date']})."
                    ),
                )
            )
        else:
            genuine_gaps.append(
                {
                    "expected_period": period,
                    "reason": "primary PDF not retrieved",
                    "attempted_sources": [press_release_url(g) for g in guid_set],
                    "failure_mode": "http_202_or_challenge_page",
                    "notes": "PressRelease PDF returned HTTP 202 or non-PDF body and no committed cache hit.",
                }
            )

    genuine_gaps.append(
        {
            "expected_period": "2026-09",
            "reason": "not yet released",
            "attempted_sources": [PMI_LISTING_URL],
            "failure_mode": "not_published",
            "notes": f"September 2026 reference period not published as of cutoff {cutoff}.",
        }
    )

    report = {
        "country": "CA",
        "cutoff": cutoff,
        "series_id": SERIES_ID,
        "retrieval_path": (
            "pmi_press_release_listing_html + PressRelease/{guid} PDF via curl_cffi "
            "(safari18_0/chrome) with fetch_bytes fallback and committed raw PDF cache"
        ),
        "recovered_months": recovered,
        "genuine_gaps": genuine_gaps,
        "attempted_urls": attempted,
        "parser_notes": (
            "Composite Output Index parsed from Services PMI PDF composite section; "
            "listing discovery matches exact title 'S&P Global Canada Services PMI'."
        ),
        "conflict_only": "Ivey_PMI_conflict not scored",
        "do_not_score": ["CFIB", "Trading Economics", "Ivey"],
        "discovered_listing_rows": discovered,
        "parsed_release_count": len(parsed_releases),
    }
    return report


def merge_into_ca_json(report: dict[str, Any]) -> None:
    """Append recovered Composite observations to Activity.business_surveys only."""
    if not report.get("recovered_months"):
        return
    payload = json.loads(CA_JSON.read_text(encoding="utf-8"))
    component = payload["components"]["Activity.business_surveys"]
    existing = {
        o["reference_period"]
        for o in component["observations"]
        if o.get("series_id") == SERIES_ID
    }
    for obs in report["recovered_months"]:
        if obs["reference_period"] in existing:
            continue
        component["observations"].append(obs)
        existing.add(obs["reference_period"])

    gaps = component.get("gaps") or []
    recovered_periods = {o["reference_period"] for o in report["recovered_months"]}
    component["gaps"] = [g for g in gaps if g.get("expected_period") not in recovered_periods]

    composite_obs = [
        o
        for o in component["observations"]
        if o.get("series_id") == SERIES_ID
    ]
    latest = max(composite_obs, key=lambda o: o["reference_period"])
    component["coverage"] = {
        "expected_periods_in_window": 13,
        "observed_periods_in_window": len(
            [o for o in composite_obs if o["reference_period"] >= "2025-09"]
        ),
        "latest_reference_period": latest["reference_period"],
        "latest_release_date": latest.get("release_date"),
        "status": "partial" if component["gaps"] else "ok",
        "gap_count": len(component["gaps"]),
        "conflict_series": "Ivey_PMI_conflict",
    }
    component["notes"] = (
        "Scored target: S&P Global Canada Composite PMI Output Index (50=neutral) from primary "
        "Services PMI PDFs. Ivey PMI is conflict/corroboration only (series_id Ivey_PMI_conflict, "
        "not scored). CFIB Business Barometer is not scored."
    )
    CA_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Harvest S&P Global Canada Composite PMI")
    parser.add_argument("--cutoff", default=date.today().isoformat())
    parser.add_argument("--guid", action="append", dest="guids", help="Additional PressRelease GUID")
    parser.add_argument("--no-save-pdf", action="store_true")
    parser.add_argument("--write-ca-json", action="store_true")
    parser.add_argument("--write-report", action="store_true", default=True)
    args = parser.parse_args()

    report = harvest(
        cutoff=args.cutoff,
        guids=args.guids,
        save_pdf=not args.no_save_pdf,
        fetcher=fetch_bytes,
    )
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    if args.write_report:
        REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.write_ca_json:
        merge_into_ca_json(report)
    print(json.dumps({"recovered": len(report["recovered_months"]), "gaps": len(report["genuine_gaps"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
