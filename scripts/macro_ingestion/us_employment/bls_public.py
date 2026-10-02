"""Batched BLS public API reads for CPS, nativity, JOLTS, and CES payroll level."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

from scripts.macro_ingestion.us_employment.cache import cache_get, cache_put, open_url
from scripts.macro_ingestion.us_employment.contract import (
    BLS_API_URL,
    BLS_CPS_SERIES,
    BLS_JOLTS_SERIES,
)

_HISTORY_LIMIT = 13
_BATCHES = {
    "cps": BLS_CPS_SERIES,
    "jolts": BLS_JOLTS_SERIES,
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _batch_for(catalog_id: str) -> str | None:
    if catalog_id in BLS_CPS_SERIES:
        return "cps"
    if catalog_id in BLS_JOLTS_SERIES:
        return "jolts"
    return None


def _parse_observations(series_block: dict[str, Any]) -> list[tuple[str, float]]:
    pairs: list[tuple[str, float]] = []
    for row in series_block.get("data") or []:
        period_code = str(row.get("period") or "")
        if not period_code.startswith("M"):
            continue
        try:
            month = int(period_code[1:])
        except ValueError:
            continue
        if not 1 <= month <= 12:
            continue
        year = str(row.get("year") or "")
        if len(year) != 4:
            continue
        try:
            value = float(str(row.get("value")).replace(",", ""))
        except (TypeError, ValueError):
            continue
        pairs.append((f"{year}-{month:02d}", value))
    return sorted(pairs, key=lambda item: item[0])


def load_bls_batch(
    opener: Callable[..., Any],
    batch_name: str,
    *,
    timeout: float,
    end_year: int,
) -> dict[str, Any]:
    key = f"bls:{batch_name}:{end_year}"
    cached = cache_get(opener, key)
    if cached is not None:
        return cached

    mapping = _BATCHES[batch_name]
    series_ids = list(dict.fromkeys(mapping.values()))
    if len(series_ids) > 25:
        bundle = {
            "ok": False,
            "status": "source_failed",
            "error": f"bls_batch_exceeds_public_limit:{len(series_ids)}",
            "body": b"",
        }
        return cache_put(opener, key, bundle)

    payload = json.dumps(
        {
            "seriesid": series_ids,
            "startyear": str(end_year - 1),
            "endyear": str(end_year),
        }
    ).encode("utf-8")
    response = open_url(opener, BLS_API_URL, timeout=timeout, data=payload)
    body: bytes = response.get("body") or b""
    if response.get("error") == "opener_does_not_accept_post" or response.get("status") == "source_failed":
        bundle = {
            "ok": False,
            "status": "source_failed",
            "error": response.get("error") or "bls_fetch_failed",
            "http_status": response.get("http_status"),
            "body": body,
        }
        return cache_put(opener, key, bundle)
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
        message = document.get("message")
        bundle = {
            "ok": False,
            "status": "source_failed",
            "error": f"bls_request_not_succeeded:{message}",
            "http_status": response.get("http_status"),
            "body": body,
        }
        return cache_put(opener, key, bundle)

    parsed: dict[str, list[tuple[str, float]]] = {}
    for block in (document.get("Results") or {}).get("series") or []:
        parsed[str(block.get("seriesID") or "")] = _parse_observations(block)
    bundle = {
        "ok": True,
        "body": body,
        "raw_sha256": _sha256(body),
        "http_status": response.get("http_status"),
        "series": parsed,
        "messages": document.get("message") or [],
    }
    return cache_put(opener, key, bundle)


def fetch_bls_series(
    spec: dict[str, Any],
    *,
    opener: Callable[..., Any],
    timeout: float,
    end_year: int,
) -> dict[str, Any]:
    catalog_id = str(spec["id"])
    batch_name = _batch_for(catalog_id)
    if batch_name is None:
        return {"ok": False, "status": "source_failed", "error": "bls_series_not_in_batch"}
    bundle = load_bls_batch(opener, batch_name, timeout=timeout, end_year=end_year)
    if not bundle.get("ok"):
        return {
            "ok": False,
            "status": bundle.get("status") or "source_failed",
            "error": bundle.get("error") or "bls_batch_failed",
            "http_status": bundle.get("http_status"),
            "body": bundle.get("body") or b"",
        }
    source_id = str(spec.get("series_id") or "")
    pairs = (bundle.get("series") or {}).get(source_id) or []
    tail = pairs[-_HISTORY_LIMIT:]
    if not tail:
        return {
            "ok": False,
            "status": "source_failed",
            "error": "bls_series_empty",
            "http_status": bundle.get("http_status"),
            "body": bundle.get("body") or b"",
            "raw_sha256": bundle.get("raw_sha256"),
        }
    points: list[dict[str, Any]] = []
    previous: float | None = None
    transform = str(spec.get("transform") or "")
    for period, value in tail:
        point: dict[str, Any] = {
            "period": period,
            "value": value,
            "transformation": transform,
            "revision_status": "final",
            "source_url": f"https://data.bls.gov/timeseries/{source_id}",
            "vintage": "latest_available",
            "derivation": {
                "publisher": "BLS",
                "series_id": source_id,
                "retrieval": "bls_public_api_v2_batch",
                "batch": batch_name,
            },
        }
        if previous is not None:
            point["prior"] = previous
        points.append(point)
        previous = value
    return {
        "ok": True,
        "points": points,
        "vintage": "latest_available",
        "raw_sha256": bundle["raw_sha256"],
        "http_status": bundle.get("http_status"),
        "body": bundle.get("body") or b"",
    }
