"""United States macro ingestion adapter."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from scripts.macro_freshness import values_close
from scripts.macro_ingestion.us_employment.dispatch import fetch_us_employment
from scripts.macro_ingestion.us_employment.empsit import (
    footnote_code_for_period,
    level_pairs,
    load_empsit_batch,
    native_series_id,
)
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


def _primary_result_from_bundle(bundle: dict[str, Any]) -> tuple[str, str | None]:
    if bundle.get("ok"):
        return "success", None
    err = str(bundle.get("error") or "bls_batch_failed")
    if "timeout" in err.lower() or "timed out" in err.lower():
        return "timeout", err
    return str(bundle.get("status") or "source_failed"), err


def _fred_validation_result(fred: dict[str, Any] | None, *, exc: BaseException | None = None) -> tuple[str, str | None]:
    if exc is not None:
        msg = str(exc)
        if isinstance(exc, TimeoutError) or "timeout" in msg.lower() or "timed out" in msg.lower():
            return "timeout", msg
        return "source_failed", msg
    if fred is None:
        return "source_failed", "fred_not_called"
    if fred.get("ok"):
        return "success", None
    err = str(fred.get("error") or "fred_fetch_failed")
    if "timeout" in err.lower() or "timed out" in err.lower():
        return "timeout", err
    return str(fred.get("status") or "source_failed"), err


def _enrich_empsit_point(
    spec: dict[str, Any],
    point: dict[str, Any],
    *,
    bls_series_id: str,
    level_series: list[tuple[str, float]],
    body: bytes,
    raw_sha256: str,
    accepted_source: str,
    retrieval_method: str,
    batch: str | None,
) -> dict[str, Any]:
    score_series_id = str(spec.get("series_id") or "")
    ordered = sorted(level_series, key=lambda item: item[0])
    prior_period: str | None = None
    prior_level: float | None = None
    raw_level: float | None = None
    if ordered:
        latest_period = str(point.get("period") or ordered[-1][0])
        raw_level = float(ordered[-1][1])
        if len(ordered) >= 2:
            prior_period = ordered[-2][0]
            prior_level = float(ordered[-2][1])
    foot = footnote_code_for_period(body, bls_series_id, str(point.get("period") or ""))
    if foot == "P":
        point["revision_status"] = "preliminary"
    derivation = dict(point.get("derivation") or {})
    derivation.update(
        {
            "publisher": "BLS",
            "bls_series_id": bls_series_id,
            "score_series_id": score_series_id,
            "retrieval_method": retrieval_method,
            "accepted_source": accepted_source,
            "fred_series_id": score_series_id,
            "prior_period": prior_period,
            "prior_level": prior_level,
            "raw_level": raw_level,
        }
    )
    if batch:
        derivation["batch"] = batch
    point["publisher"] = "BLS"
    point["derivation"] = derivation
    point["source_url"] = f"https://data.bls.gov/timeseries/{bls_series_id}"
    return {
        "ok": True,
        "points": [point],
        "vintage": "latest_available",
        "raw_sha256": raw_sha256,
        "body": body,
        "ledger_extra": {
            "acquisition": {
                "accepted_source": accepted_source,
                "primary": {
                    "provider": "BLS",
                    "series_id": bls_series_id,
                    "result": "success",
                    "error": None,
                },
                "validation_or_fallback": None,
            }
        },
    }


def _fetch_scored_empsit_labor(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    now: datetime,
    timeout: float,
) -> dict[str, Any]:
    catalog_id = str(spec["id"])
    bls_series_id = str(spec.get("bls_series_id") or native_series_id(catalog_id) or "")
    fred_series_id = str(spec.get("series_id") or "")
    score_transform = str(spec.get("transform") or "")

    bls_exc: BaseException | None = None
    bundle: dict[str, Any] = {}
    try:
        bundle = load_empsit_batch(opener, timeout=timeout, end_year=now.year)
    except BaseException as exc:  # noqa: BLE001
        bls_exc = exc
        msg = str(exc)
        if isinstance(exc, TimeoutError) or "timeout" in msg.lower() or "timed out" in msg.lower():
            primary_status, primary_error = "timeout", msg
        else:
            primary_status, primary_error = "source_failed", msg
    else:
        primary_status, primary_error = _primary_result_from_bundle(bundle)

    bls_point: dict[str, Any] | None = None
    bls_body = bundle.get("body") or b""
    bls_sha = str(bundle.get("raw_sha256") or "")
    if bls_exc is None and bundle.get("ok") and bls_series_id:
        levels = level_pairs(bundle, bls_series_id)
        bls_point = _derive_latest_point(
            spec,
            levels,
            source_url=f"https://data.bls.gov/timeseries/{bls_series_id}",
        )
        if bls_point is None:
            primary_status, primary_error = "source_failed", f"transform_not_derived:{score_transform}"
            bls_point = None

    fred_payload: dict[str, Any] | None = None
    fred_exc: BaseException | None = None
    try:
        fred_payload = _fetch_fred_series(spec, opener=opener, timeout=timeout)
    except BaseException as exc:  # noqa: BLE001
        fred_exc = exc

    fred_status, fred_error = _fred_validation_result(fred_payload, exc=fred_exc)
    fred_points = (fred_payload or {}).get("points") or []
    fred_point = fred_points[0] if fred_payload and fred_payload.get("ok") and fred_points else None

    def _acquisition(
        accepted: str | None,
        *,
        primary_result: str,
        primary_err: str | None,
        validation: dict[str, Any] | None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "accepted_source": accepted,
            "primary": {
                "provider": "BLS",
                "series_id": bls_series_id,
                "result": primary_result,
                "error": primary_err,
            },
            "validation_or_fallback": validation,
        }
        if extra:
            doc.update(extra)
        return {"acquisition": doc}

    if bls_point is not None and fred_point is not None:
        same_period = str(bls_point.get("period")) == str(fred_point.get("period"))
        bls_transform = str(bls_point.get("transformation") or score_transform)
        fred_transform = str(fred_point.get("transformation") or score_transform)
        if same_period and bls_transform == fred_transform and not values_close(
            float(bls_point["value"]), float(fred_point["value"])
        ):
            fred_body_conflict = (fred_payload or {}).get("body") or b""
            fred_sha_conflict = str((fred_payload or {}).get("raw_sha256") or "")
            if fred_body_conflict and not fred_sha_conflict:
                fred_sha_conflict = _sha256(fred_body_conflict)
            conflict_extra: dict[str, Any] = {
                "bls_value": float(bls_point["value"]),
                "fred_value": float(fred_point["value"]),
            }
            if bls_body:
                conflict_extra["bls_raw_sha256"] = bls_sha or _sha256(bls_body)
            if fred_body_conflict:
                conflict_extra["fred_raw_sha256"] = fred_sha_conflict
            return {
                "ok": False,
                "status": "source_failed",
                "error": (
                    "verification_conflict:"
                    f"bls={bls_point['value']};fred={fred_point['value']};period={bls_point.get('period')}"
                ),
                "body": bls_body,
                "ledger_extra": _acquisition(
                    None,
                    primary_result="success",
                    primary_err=None,
                    validation={
                        "provider": "FRED",
                        "series_id": fred_series_id,
                        "result": "success",
                        "error": None,
                    },
                    extra=conflict_extra,
                ),
            }

    if bls_point is not None:
        payload = _enrich_empsit_point(
            spec,
            bls_point,
            bls_series_id=bls_series_id,
            level_series=level_pairs(bundle, bls_series_id),
            body=bls_body,
            raw_sha256=bls_sha,
            accepted_source="bls_primary",
            retrieval_method="bls_public_api_v2_batch",
            batch="empsit",
        )
        payload["ledger_extra"]["acquisition"]["validation_or_fallback"] = {
            "provider": "FRED",
            "series_id": fred_series_id,
            "result": fred_status,
            "error": fred_error,
        }
        return payload

    if fred_point is not None and fred_payload and fred_payload.get("ok"):
        point = dict(fred_point)
        fred_body = fred_payload.get("body") or b""
        fred_sha = str(fred_payload.get("raw_sha256") or _sha256(fred_body))
        url = FRED_GRAPH_URL.format(series_id=fred_series_id)
        parsed = parse_fred_csv(fred_body.decode("utf-8", errors="replace"))
        payload = _enrich_empsit_point(
            spec,
            point,
            bls_series_id=bls_series_id,
            level_series=parsed,
            body=fred_body,
            raw_sha256=fred_sha,
            accepted_source="fred_fallback",
            retrieval_method="fredgraph.csv",
            batch=None,
        )
        point_out = payload["points"][0]
        point_out["source_url"] = url
        payload["ledger_extra"] = _acquisition(
            "fred_fallback",
            primary_result=primary_status,
            primary_err=primary_error,
            validation={
                "provider": "FRED",
                "series_id": fred_series_id,
                "result": "success",
                "error": None,
            },
        )
        return payload

    err_parts = [f"primary: {primary_error or primary_status}"]
    err_parts.append(f"fallback: {fred_error or fred_status}")
    return {
        "ok": False,
        "status": "source_failed",
        "error": "; ".join(err_parts),
        "body": bls_body or (fred_payload or {}).get("body") or b"",
        "ledger_extra": _acquisition(
            None,
            primary_result=primary_status,
            primary_err=primary_error,
            validation={
                "provider": "FRED",
                "series_id": fred_series_id,
                "result": fred_status,
                "error": fred_error,
            },
        ),
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

    if method == "bls_empsit_primary":
        return _fetch_scored_empsit_labor(spec, opener=opener, now=now, timeout=timeout)

    employment = fetch_us_employment(spec, opener=opener, now=now, timeout=timeout)
    if employment is not None:
        return employment

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
