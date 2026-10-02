"""DOL ETA 539 revised national weekly claims in one XML request.

This file is revised history. It is not the Thursday ETA 538 advance print.
Callers must not present these points as the current pre-payroll claims signal.
FRED graph CSV is not used. From this environment that download stalls and
would burn the country budget on a predictable timeout.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlencode
from xml.etree import ElementTree

from scripts.macro_ingestion.us_employment.cache import cache_get, cache_put, is_challenge_page, open_url
from scripts.macro_ingestion.us_employment.contract import (
    CLAIMS_COVERED_SERIES,
    CLAIMS_SERIES,
    DOL_CLAIMS_REGISTRY,
    DOL_CLAIMS_REPORT,
)
from scripts.macro_ingestion.us_employment.derived import week_contains_calendar_day

_HISTORY_LIMIT = 16

_FIELD_PATHS = {
    "ETA539_INITIAL_CLAIMS_SA": ("InitialClaims", "SA"),
    "ETA539_INITIAL_CLAIMS_SA4WK": ("InitialClaims", "SA4WK"),
    "ETA539_CONTINUED_CLAIMS_SA": ("ContinuedClaims", "SA"),
    "ETA539_IUR_SA": ("IUR", "SA"),
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_number(text: str | None) -> float | None:
    if text is None:
        return None
    cleaned = text.strip().replace(",", "")
    if cleaned in {"", "."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _week_iso(text: str | None) -> str | None:
    if not text:
        return None
    try:
        month, day, year = (int(part) for part in text.strip().split("/"))
        return f"{year:04d}-{month:02d}-{day:02d}"
    except ValueError:
        return None


def _rundate_iso(text: str | None) -> str:
    parsed = _week_iso(text)
    return parsed or (text or "latest_available")


def parse_dol_claims_xml(body: bytes) -> dict[str, Any] | None:
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        return None
    series: dict[str, list[tuple[str, float]]] = {series_id: [] for series_id in _FIELD_PATHS}
    series[CLAIMS_COVERED_SERIES] = []
    for week in root.findall("week"):
        stamp = _week_iso(week.findtext("weekEnded"))
        if stamp is None:
            continue
        for series_id, (parent, child) in _FIELD_PATHS.items():
            node = week.find(parent)
            value = _parse_number(None if node is None else node.findtext(child))
            if value is not None:
                series[series_id].append((stamp, value))
        covered = _parse_number(week.findtext("CoveredEmployment"))
        if covered is not None:
            series[CLAIMS_COVERED_SERIES].append((stamp, covered))
    if not series["ETA539_INITIAL_CLAIMS_SA"]:
        return None
    return {"vintage": _rundate_iso(root.attrib.get("rundate")), "series": series}


def load_claims_batch(
    opener: Callable[..., Any],
    *,
    timeout: float,
    now: datetime | None = None,
) -> dict[str, Any]:
    cached = cache_get(opener, "dol_claims")
    if cached is not None:
        return cached
    when = now or datetime.now(timezone.utc)
    payload = urlencode(
        {
            "level": "us",
            "final_yr": str(when.year + 1),
            "strtdate": str(when.year - 1),
            "enddate": str(when.year),
            "filetype": "xml",
        }
    ).encode()
    response = open_url(
        opener,
        DOL_CLAIMS_REPORT,
        timeout=timeout,
        data=payload,
        content_type="application/x-www-form-urlencoded",
    )
    body: bytes = response.get("body") or b""
    if not response.get("ok"):
        bundle = {
            "ok": False,
            "status": "source_failed",
            "error": response.get("error") or "dol_claims_fetch_failed",
            "http_status": response.get("http_status"),
            "body": body,
        }
        return cache_put(opener, "dol_claims", bundle)
    if is_challenge_page(body):
        bundle = {
            "ok": False,
            "status": "license_gap",
            "challenge_page": True,
            "error": "dol_claims_challenge_page",
            "http_status": response.get("http_status"),
            "body": body,
        }
        return cache_put(opener, "dol_claims", bundle)
    parsed = parse_dol_claims_xml(body)
    if parsed is None:
        bundle = {
            "ok": False,
            "status": "source_failed",
            "error": "dol_claims_xml_unparsed",
            "http_status": response.get("http_status"),
            "body": body,
        }
        return cache_put(opener, "dol_claims", bundle)
    bundle = {
        "ok": True,
        "body": body,
        "raw_sha256": _sha256(body),
        "http_status": response.get("http_status"),
        "batch_url": DOL_CLAIMS_REPORT,
        "vintage": parsed["vintage"],
        "series": parsed["series"],
    }
    return cache_put(opener, "dol_claims", bundle)


def fetch_claims_series(
    spec: dict[str, Any],
    *,
    opener: Callable[..., Any],
    timeout: float,
    now: datetime | None = None,
) -> dict[str, Any]:
    catalog_id = str(spec["id"])
    series_id = CLAIMS_SERIES.get(catalog_id)
    if not series_id:
        return {"ok": False, "status": "source_failed", "error": "claims_series_not_in_batch"}
    bundle = load_claims_batch(opener, timeout=timeout, now=now)
    if not bundle.get("ok"):
        return {
            "ok": False,
            "status": bundle.get("status") or "source_failed",
            "error": bundle.get("error") or "dol_claims_failed",
            "http_status": bundle.get("http_status"),
            "body": bundle.get("body") or b"",
            "challenge_page": bundle.get("challenge_page"),
        }
    pairs = (bundle.get("series") or {}).get(series_id) or []
    tail = pairs[-_HISTORY_LIMIT:]
    if not tail:
        return {
            "ok": False,
            "status": "source_failed",
            "error": "dol_claims_series_empty",
            "http_status": bundle.get("http_status"),
            "body": bundle.get("body") or b"",
        }
    transform = str(spec.get("transform") or "level")
    vintage = str(bundle.get("vintage") or "latest_available")
    points: list[dict[str, Any]] = []
    previous: float | None = None
    for stamp, value in tail:
        period = stamp[:10]
        reference_week = week_contains_calendar_day(period, 12)
        point: dict[str, Any] = {
            "period": period,
            "value": value,
            "transformation": transform,
            "revision_status": "revised",
            "source_url": DOL_CLAIMS_REGISTRY,
            "vintage": vintage,
            "derivation": {
                "publisher": "U.S. Department of Labor",
                "report": "ETA 539",
                "claims_form": "ETA 539",
                "vintage_kind": "revised",
                "revision_status": "revised",
                "series_id": series_id,
                "batch_url": bundle["batch_url"],
                "cps_reference_week": reference_week,
                "week_ending": period,
                "advance_embargo": False,
                "not_eta_538": True,
                "masquerades_as_advance": False,
            },
        }
        if previous is not None:
            point["prior"] = previous
        points.append(point)
        previous = value
    return {
        "ok": True,
        "points": points,
        "vintage": vintage,
        "raw_sha256": bundle["raw_sha256"],
        "http_status": bundle.get("http_status"),
        "body": bundle.get("body") or b"",
    }
