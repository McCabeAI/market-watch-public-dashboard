"""United States macro ingestion adapter."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from scripts.macro_source_refresh import parse_fred_csv
from scripts.temperature_level import month_before

COUNTRY = "US"

ROOT = Path(__file__).resolve().parents[3]
FRED_GRAPH_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"

_DIRECT_TRANSFORMS = frozenset(
    {
        "percent",
        "yoy_pct",
        "diffusion_index",
        "saar_pct",
        "index_level",
        "identity",
    }
)

_CHALLENGE_MARKERS = (
    "cf-challenge",
    "just a moment",
    "access denied",
    "captcha",
    "enable javascript",
    "bot activity",
    "please turn javascript on",
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_challenge_page(body: bytes) -> bool:
    if not body:
        return False
    sample = body[:12000].decode("utf-8", errors="replace").lower()
    return any(marker in sample for marker in _CHALLENGE_MARKERS)


def _fred_stamp_to_period(stamp: str, cadence: str) -> str:
    if cadence == "quarterly" and len(stamp) >= 7:
        year = int(stamp[:4])
        month = int(stamp[5:7])
        quarter = (month - 1) // 3 + 1
        return f"{year}-Q{quarter}"
    return stamp[:7]


def _derive_latest_point(
    spec: dict[str, Any],
    level_points: list[tuple[str, float]],
    *,
    source_url: str,
) -> dict[str, Any] | None:
    if not level_points:
        return None
    transform = str(spec.get("transform") or "")
    cadence = str(spec.get("cadence") or "monthly")
    ordered = sorted(level_points, key=lambda item: item[0])
    stamp, raw_value = ordered[-1]
    period = _fred_stamp_to_period(stamp, cadence)

    if transform == "mom_sa_pct" and len(ordered) >= 2:
        prev_stamp, prev_level = ordered[-2]
        prev_period = _fred_stamp_to_period(prev_stamp, cadence)
        if prev_level == 0 or month_before(period) != prev_period:
            return None
        value = (raw_value / prev_level - 1.0) * 100.0
        return {
            "period": period,
            "value": value,
            "transformation": transform,
            "revision_status": "final",
            "prior": prev_level,
            "source_url": source_url,
        }

    if transform == "mm_change_thousands_sa" and len(ordered) >= 2:
        prev_stamp, prev_level = ordered[-2]
        prev_period = _fred_stamp_to_period(prev_stamp, cadence)
        if month_before(period) != prev_period:
            return None
        value = raw_value - prev_level
        return {
            "period": period,
            "value": value,
            "transformation": transform,
            "revision_status": "final",
            "prior": prev_level,
            "source_url": source_url,
        }

    if transform in _DIRECT_TRANSFORMS:
        return {
            "period": period,
            "value": float(raw_value),
            "transformation": transform,
            "revision_status": "final",
            "source_url": source_url,
        }

    return None


def _fetch_fred_series(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    series_id = spec.get("series_id")
    if not isinstance(series_id, str) or not series_id:
        return {
            "ok": False,
            "status": "source_failed",
            "error": "missing_fred_series_id",
        }
    url = FRED_GRAPH_URL.format(series_id=series_id)
    response = opener(url, timeout=timeout)
    http_status = response.get("http_status")
    body: bytes = response.get("body") or b""
    base: dict[str, Any] = {
        "http_status": http_status,
        "body": body,
    }
    if not response.get("ok"):
        return {
            **base,
            "ok": False,
            "status": "source_failed",
            "error": response.get("error") or "fred_fetch_failed",
        }
    if _is_challenge_page(body):
        return {
            **base,
            "ok": False,
            "status": "license_gap",
            "challenge_page": True,
            "error": "fred_challenge_page",
        }
    text = body.decode("utf-8", errors="replace")
    parsed = parse_fred_csv(text)
    if not parsed:
        return {
            **base,
            "ok": False,
            "status": "source_failed",
            "error": "fred_csv_empty",
        }
    point = _derive_latest_point(spec, parsed, source_url=url)
    if point is None:
        return {
            **base,
            "ok": False,
            "status": "source_failed",
            "error": f"transform_not_derived:{spec.get('transform')}",
        }
    digest = _sha256(body)
    return {
        **base,
        "ok": True,
        "points": [point],
        "vintage": "latest_available",
        "raw_sha256": digest,
    }


def _parse_ism_pmi(body: bytes, *, services: bool) -> dict[str, Any] | None:
    text = body.decode("utf-8", errors="replace")
    if services:
        patterns = (
            r"Services PMI(?:[^\d]{0,80})(\d{2}\.\d)",
            r"Non-Manufacturing PMI(?:[^\d]{0,80})(\d{2}\.\d)",
        )
    else:
        patterns = (
            r"Manufacturing PMI(?:[^\d]{0,80})(\d{2}\.\d)",
            r"ISM Manufacturing(?:[^\d]{0,80})(\d{2}\.\d)",
        )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            value = float(match.group(1))
            if 0 <= value <= 100:
                period_match = re.search(
                    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
                    text,
                    flags=re.IGNORECASE,
                )
                period = None
                if period_match:
                    from calendar import month_name

                    month_num = list(month_name).index(period_match.group(1).capitalize())
                    period = f"{period_match.group(2)}-{month_num:02d}"
                return {"value": value, "period": period}
    return None


def _fetch_ism_series(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    url = str(spec.get("endpoint") or (spec.get("registry_urls") or [""])[0])
    services = "services" in str(spec.get("component") or "")
    response = opener(url, timeout=timeout)
    body: bytes = response.get("body") or b""
    base: dict[str, Any] = {"http_status": response.get("http_status"), "body": body}
    if response.get("ok") and body and not _is_challenge_page(body):
        parsed = _parse_ism_pmi(body, services=services)
        if parsed and parsed.get("period"):
            digest = _sha256(body)
            return {
                **base,
                "ok": True,
                "points": [
                    {
                        "period": parsed["period"],
                        "value": parsed["value"],
                        "transformation": spec.get("transform"),
                        "revision_status": "final",
                        "source_url": url,
                    }
                ],
                "vintage": "latest_available",
                "raw_sha256": digest,
            }
    if _is_challenge_page(body):
        return {
            **base,
            "ok": False,
            "status": "license_gap",
            "challenge_page": True,
            "error": "ism_challenge_page",
        }
    return {
        **base,
        "ok": False,
        "status": "source_failed",
        "error": response.get("error") or "ism_primary_unparsed",
    }


def _fetch_flash_pmi(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    url = str(spec.get("endpoint") or (spec.get("registry_urls") or [""])[0])
    response = opener(url, timeout=timeout)
    body: bytes = response.get("body") or b""
    base: dict[str, Any] = {"http_status": response.get("http_status"), "body": body}
    if response.get("http_status") in {401, 403, 202} or _is_challenge_page(body):
        return {
            **base,
            "ok": False,
            "status": "license_gap" if _is_challenge_page(body) else "source_failed",
            "challenge_page": _is_challenge_page(body),
            "error": response.get("error") or "sp_global_release_schedule_unavailable",
        }
    if not response.get("ok"):
        return {
            **base,
            "ok": False,
            "status": "source_failed",
            "error": response.get("error") or "sp_global_fetch_failed",
        }
    return {
        **base,
        "ok": False,
        "status": "source_failed",
        "error": "flash_pmi_primary_pdf_not_parsed",
    }


def _fetch_mapped_bridge(spec: dict[str, Any]) -> dict[str, Any]:
    endpoint = str(spec.get("endpoint") or "")
    path = ROOT / endpoint
    if not path.is_file():
        return {
            "ok": False,
            "status": "source_failed",
            "error": "mapped_bridge_file_missing",
        }
    body = path.read_bytes()
    return {
        "ok": False,
        "status": "source_failed",
        "error": "mapped_bridge_transform_not_wired",
        "body": body,
        "raw_sha256": _sha256(body),
    }


def fetch_series(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    now: datetime,
    timeout: float = 20,
) -> dict[str, Any]:
    """Fetch one US catalog row via the injectable opener."""
    _ = now
    role = str(spec.get("role") or "")
    if role == "explanatory_alias":
        return {
            "ok": False,
            "status": "not_applicable",
            "error": "alias_of_scored_series",
        }

    classification = str(spec.get("classification") or "")
    if classification == "proprietary_blocked":
        return {
            "ok": False,
            "status": "license_gap",
            "error": "proprietary_blocked",
        }

    method = str(spec.get("retrieval_method") or "")
    if method == "unavailable":
        return {
            "ok": False,
            "status": "license_gap",
            "error": "retrieval_unavailable",
        }

    if method in {"fredgraph.csv", "existing_us_housing_data"}:
        return _fetch_fred_series(spec, opener=opener, timeout=timeout)

    if method == "ism_prnewswire_press_releases":
        return _fetch_ism_series(spec, opener=opener, timeout=timeout)

    if method == "sp_global_press_release_pdf":
        return _fetch_flash_pmi(spec, opener=opener, timeout=timeout)

    if spec.get("id") == "US.Inflation.mapped_bridge" or method == "repository_csv":
        return _fetch_mapped_bridge(spec)

    if method == "internal_csv":
        return _fetch_mapped_bridge(spec)

    return {
        "ok": False,
        "status": "source_failed",
        "error": f"unsupported_retrieval_method:{method or 'unknown'}",
    }
