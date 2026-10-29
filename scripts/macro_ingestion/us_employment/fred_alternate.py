"""Official BLS paths for FRED graph series ids (same SA index definitions)."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

from scripts.macro_ingestion.us_employment.bls_public import _parse_observations
from scripts.macro_ingestion.us_employment.cache import cache_get, cache_put, open_url
from scripts.macro_ingestion.us_employment.contract import BLS_API_URL

# FRED mnemonic -> BLS public API series id (verified via bls.gov / FRED metadata).
FRED_TO_BLS_SERIES: dict[str, str] = {
    "CPIAUCSL": "CUSR0000SA0",
    "CPILFESL": "CUSR0000SA0L1E",
    "WPSFD49207": "WPSFD49207",
    "IR": "EIUIR",
    "IQ": "EIUIQ",
}


def bls_series_for_fred(fred_id: str, spec: dict[str, Any]) -> str | None:
    alt = spec.get("alternate_series_id")
    if isinstance(alt, str) and alt.strip():
        return alt.strip()
    return FRED_TO_BLS_SERIES.get(fred_id)


def load_bls_single_series(
    opener: Callable[..., Any],
    bls_series_id: str,
    *,
    timeout: float,
    end_year: int,
) -> dict[str, Any]:
    key = f"bls:single:{bls_series_id}:{end_year}"
    cached = cache_get(opener, key)
    if cached is not None:
        return cached

    payload = json.dumps(
        {
            "seriesid": [bls_series_id],
            "startyear": str(end_year - 2),
            "endyear": str(end_year),
        }
    ).encode("utf-8")
    response = open_url(opener, BLS_API_URL, timeout=timeout, data=payload)
    body: bytes = response.get("body") or b""
    if not response.get("ok"):
        bundle = {
            "ok": False,
            "status": "source_failed",
            "error": response.get("error") or "bls_fetch_failed",
            "http_status": response.get("http_status"),
            "body": body,
        }
        return cache_put(opener, key, bundle)
    try:
        document = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        bundle = {
            "ok": False,
            "status": "source_failed",
            "error": "bls_json_unparsed",
            "http_status": response.get("http_status"),
            "body": body,
        }
        return cache_put(opener, key, bundle)
    if document.get("status") != "REQUEST_SUCCEEDED":
        bundle = {
            "ok": False,
            "status": "source_failed",
            "error": f"bls_request_not_succeeded:{document.get('message')}",
            "http_status": response.get("http_status"),
            "body": body,
        }
        return cache_put(opener, key, bundle)

    series_blocks = (document.get("Results") or {}).get("series") or []
    if not series_blocks:
        bundle = {
            "ok": False,
            "status": "source_failed",
            "error": "bls_series_empty",
            "http_status": response.get("http_status"),
            "body": body,
        }
        return cache_put(opener, key, bundle)
    pairs = _parse_observations(series_blocks[0])
    if not pairs:
        bundle = {
            "ok": False,
            "status": "source_failed",
            "error": "bls_series_empty",
            "http_status": response.get("http_status"),
            "body": body,
        }
        return cache_put(opener, key, bundle)
    bundle = {
        "ok": True,
        "body": body,
        "raw_sha256": hashlib.sha256(body).hexdigest(),
        "http_status": response.get("http_status"),
        "level_pairs": pairs,
        "source_url": f"https://data.bls.gov/timeseries/{bls_series_id}",
        "bls_series_id": bls_series_id,
    }
    return cache_put(opener, key, bundle)
