"""Canada macro ingestion adapter (StatCan WDS, S&P PMI, housing collectors)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

from scripts.canada_housing_data import (
    STATCAN_NHPI_CSV,
    STATCAN_NHPI_PAGE,
    parse_statcan_nhpi,
    _statcan_rows,
)
from scripts.harvest_ca_pmi import (
    PMI_LISTING_URL,
    discover_canada_services_listing,
    parse_release_artifact,
)
from scripts.macro_source_refresh import parse_statcan_vector_payload
from scripts.macro_ingestion.runner import live_opener
from scripts.temperature_level import month_before

COUNTRY = "CA"
USER_AGENT = "market-watch-macro-ingestion/1.0"
STATCAN_WDS_URL = (
    "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods"
)

# Vectors proven in data/temperature_history/ca.json (not guessed).
_TRIM_MEDIAN_VECTOR_IDS = (108785715, 108785714)
# Published q/q percent series (not levels) on StatCan WDS.
_DIRECT_QOQ_VECTOR_IDS = frozenset({1594571755, 1594571783})

_VECTOR_RE = re.compile(r"v(\d+)", re.IGNORECASE)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _quarter_period_from_raw(ref_per_raw: str) -> str | None:
    if len(ref_per_raw) < 7:
        return None
    try:
        year = int(ref_per_raw[:4])
        month = int(ref_per_raw[5:7])
    except ValueError:
        return None
    quarter = (month - 1) // 3 + 1
    return f"{year}-Q{quarter}"


def _month_period(ref_per: str) -> str | None:
    if len(ref_per) < 7:
        return None
    return ref_per[:7]


def _wds_points_by_vector(payload: Any) -> dict[int, list[dict[str, Any]]]:
    blocks = payload if isinstance(payload, list) else [payload]
    out: dict[int, list[dict[str, Any]]] = {}
    for block in blocks:
        if not isinstance(block, dict):
            continue
        obj = block.get("object") if isinstance(block.get("object"), dict) else block
        vid = obj.get("vectorId")
        if vid is None:
            continue
        points = obj.get("vectorDataPoint") or obj.get("vectorDataPoints") or []
        out[int(vid)] = [p for p in points if isinstance(p, dict)]
    return out


def _statcan_wds_fetch(
    vector_ids: list[int],
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
    latest_n: int,
) -> dict[str, Any]:
    if not vector_ids:
        return {
            "ok": False,
            "error": "no StatCan vector id",
            "http_status": None,
            "body": b"",
            "url": STATCAN_WDS_URL,
        }
    body = json.dumps(
        [{"vectorId": int(v), "latestN": int(latest_n)} for v in vector_ids]
    ).encode("utf-8")
    url = STATCAN_WDS_URL
    if opener is live_opener:
        try:
            request = Request(
                url,
                data=body,
                headers={
                    "User-Agent": USER_AGENT,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
                return {
                    "ok": True,
                    "url": url,
                    "http_status": getattr(response, "status", None) or response.getcode(),
                    "body": raw,
                    "error": None,
                }
        except (URLError, TimeoutError, OSError) as exc:
            return {
                "ok": False,
                "url": url,
                "http_status": None,
                "body": b"",
                "error": str(exc),
            }
    return opener(url, timeout=timeout)


def _levels_monthly(points: list[dict[str, Any]]) -> list[tuple[str, float]]:
    rows: list[tuple[str, float]] = []
    for point in points:
        period = _month_period(str(point.get("refPer") or ""))
        if not period:
            continue
        try:
            rows.append((period, float(point.get("value"))))
        except (TypeError, ValueError):
            continue
    rows.sort()
    return rows


def _levels_quarterly(points: list[dict[str, Any]]) -> list[tuple[str, float]]:
    rows: list[tuple[str, float]] = []
    for point in points:
        raw = str(point.get("refPerRaw") or point.get("refPer") or "")
        period = _quarter_period_from_raw(raw)
        if not period:
            continue
        try:
            rows.append((period, float(point.get("value"))))
        except (TypeError, ValueError):
            continue
    rows.sort()
    return rows


def _yoy_from_monthly_levels(levels: list[tuple[str, float]]) -> tuple[str, float] | None:
    if not levels:
        return None
    by_period = dict(levels)
    period = levels[-1][0]
    lag = period
    for _ in range(12):
        lag = month_before(lag)
        if lag is None:
            return None
    prior = by_period.get(lag)
    latest = by_period.get(period)
    if prior in (None, 0) or latest is None:
        return None
    return period, (latest / prior - 1.0) * 100.0


def _mom_pct_from_levels(levels: list[tuple[str, float]]) -> tuple[str, float] | None:
    if len(levels) < 2:
        return None
    prev_period, prev_val = levels[-2]
    period, latest = levels[-1]
    if prev_val == 0:
        return None
    if month_before(period) != prev_period:
        return None
    return period, (latest / prev_val - 1.0) * 100.0


def _mom_change_thousands(levels: list[tuple[str, float]]) -> tuple[str, float] | None:
    if len(levels) < 2:
        return None
    prev_period, prev_val = levels[-2]
    period, latest = levels[-1]
    if month_before(period) != prev_period:
        return None
    return period, latest - prev_val


def _qoq_from_quarterly_levels(levels: list[tuple[str, float]]) -> tuple[str, float] | None:
    if len(levels) < 2:
        return None
    prev_period, prev_val = levels[-2]
    period, latest = levels[-1]
    if prev_val == 0:
        return None
    if month_before(period) != prev_period:
        return None
    return period, (latest / prev_val - 1.0) * 100.0


def _latest_direct_monthly(points: list[dict[str, Any]]) -> tuple[str, float] | None:
    parsed = parse_statcan_vector_payload([{"object": {"vectorDataPoint": points}}])
    if not parsed:
        return None
    period, value = parsed[-1]
    return period, value


def _latest_direct_quarterly(points: list[dict[str, Any]]) -> tuple[str, float] | None:
    levels = _levels_quarterly(points)
    if not levels:
        return None
    return levels[-1]


def _vector_ids_for_spec(spec: dict[str, Any]) -> list[int]:
    series_id = str(spec.get("series_id") or "")
    if series_id == "CPI_trim_and_median_yoy":
        return list(_TRIM_MEDIAN_VECTOR_IDS)
    return [int(v) for v in _VECTOR_RE.findall(series_id)]


def _latest_n_for_spec(spec: dict[str, Any]) -> int:
    series_id = str(spec.get("series_id") or "")
    transform = str(spec.get("transform") or "")
    if "_derived_yoy" in series_id or series_id == "CPI_trim_and_median_yoy":
        return 15
    if "_derived_qq" in series_id or transform == "mom_sa_pct_and_qoq_sa_pct":
        return 8
    if transform in {"mom_sa_pct", "mom_sa_change_thousands", "qoq_sa_pct"}:
        return 6
    return 4


def _make_point(
    period: str,
    value: float,
    *,
    transform: str,
    source_url: str,
    revision_status: str = "final",
) -> dict[str, Any]:
    return {
        "period": period,
        "value": value,
        "transformation": transform,
        "revision_status": revision_status,
        "source_url": source_url,
    }


def _statcan_points(spec: dict[str, Any], wds_by_vector: dict[int, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    transform = str(spec.get("transform") or "")
    series_id = str(spec.get("series_id") or "")
    source_url = str(spec.get("endpoint") or STATCAN_WDS_URL)
    points: list[dict[str, Any]] = []

    if series_id == "CPI_trim_and_median_yoy":
        trim_pts = wds_by_vector.get(_TRIM_MEDIAN_VECTOR_IDS[0]) or []
        med_pts = wds_by_vector.get(_TRIM_MEDIAN_VECTOR_IDS[1]) or []
        trim_map = dict(parse_statcan_vector_payload([{"object": {"vectorDataPoint": trim_pts}}]))
        med_map = dict(parse_statcan_vector_payload([{"object": {"vectorDataPoint": med_pts}}]))
        common = sorted(set(trim_map) & set(med_map))
        if not common:
            return []
        period = common[-1]
        value = (trim_map[period] + med_map[period]) / 2.0
        return [_make_point(period, value, transform=transform, source_url=source_url)]

    if transform == "mom_sa_pct_and_qoq_sa_pct":
        monthly_id = int(_VECTOR_RE.findall(series_id.split(";")[0])[0])
        quarterly_id = int(_VECTOR_RE.findall(series_id.split(";")[1])[0])
        mom = _mom_pct_from_levels(_levels_monthly(wds_by_vector.get(monthly_id) or []))
        qoq = _latest_direct_quarterly(wds_by_vector.get(quarterly_id) or [])
        if mom:
            points.append(_make_point(mom[0], mom[1], transform=transform, source_url=source_url))
        if qoq:
            points.append(_make_point(qoq[0], qoq[1], transform=transform, source_url=source_url))
        return points

    vector_ids = _vector_ids_for_spec(spec)
    if not vector_ids:
        return []
    vid = vector_ids[0]
    raw_points = wds_by_vector.get(vid) or []

    if transform == "percent":
        latest = _latest_direct_monthly(raw_points)
        if latest:
            points.append(_make_point(latest[0], latest[1], transform=transform, source_url=source_url))
        return points

    if transform == "yoy_pct":
        if "_derived_yoy" in series_id:
            derived = _yoy_from_monthly_levels(_levels_monthly(raw_points))
            if derived:
                points.append(_make_point(derived[0], derived[1], transform=transform, source_url=source_url))
            return points
        latest = _latest_direct_monthly(raw_points)
        if latest:
            points.append(_make_point(latest[0], latest[1], transform=transform, source_url=source_url))
        return points

    if transform == "mom_sa_pct":
        latest = _mom_pct_from_levels(_levels_monthly(raw_points))
        if latest:
            points.append(_make_point(latest[0], latest[1], transform=transform, source_url=source_url))
        return points

    if transform == "mom_sa_change_thousands":
        derived = _mom_change_thousands(_levels_monthly(raw_points))
        if derived:
            points.append(_make_point(derived[0], derived[1], transform=transform, source_url=source_url))
        return points

    if transform == "qoq_sa_pct":
        if vid in _DIRECT_QOQ_VECTOR_IDS:
            latest = _latest_direct_quarterly(raw_points)
        elif "_derived_qq" in series_id:
            latest = _qoq_from_quarterly_levels(_levels_quarterly(raw_points))
        else:
            latest = _latest_direct_quarterly(raw_points)
        if latest:
            points.append(_make_point(latest[0], latest[1], transform=transform, source_url=source_url))
        return points

    if transform == "index_level":
        latest = _latest_direct_monthly(raw_points)
        if latest:
            points.append(_make_point(latest[0], latest[1], transform=transform, source_url=source_url))
        return points

    return points


def _payload_ok(
    *,
    body: bytes,
    http_status: int | None,
    points: list[dict[str, Any]],
    source_url: str,
) -> dict[str, Any]:
    digest = _sha256(body)
    return {
        "ok": True,
        "points": points,
        "vintage": f"latest_available:{digest[:12]}",
        "raw_sha256": digest,
        "http_status": http_status,
        "body": body,
        "error": None,
        "source_url": source_url,
    }


def _fetch_statcan_series(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    series_id = spec.get("series_id")
    if series_id is None:
        return {
            "ok": False,
            "status": "source_failed",
            "error": f"{spec['id']}: series_id unpinned; no official vector id in catalog",
            "http_status": None,
        }
    vector_ids = _vector_ids_for_spec(spec)
    if not vector_ids:
        return {
            "ok": False,
            "status": "source_failed",
            "error": f"{spec['id']}: no StatCan vector id on series_id",
            "http_status": None,
        }
    latest_n = _latest_n_for_spec(spec)
    fetched = _statcan_wds_fetch(vector_ids, opener=opener, timeout=timeout, latest_n=latest_n)
    if not fetched.get("ok"):
        return {
            "ok": False,
            "status": "source_failed",
            "error": fetched.get("error") or "statcan_wds_failed",
            "http_status": fetched.get("http_status"),
        }
    body = fetched.get("body") or b""
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {
            "ok": False,
            "status": "source_failed",
            "error": "statcan_wds_invalid_json",
            "http_status": fetched.get("http_status"),
        }
    wds_by_vector = _wds_points_by_vector(payload)
    points = _statcan_points(spec, wds_by_vector)
    if not points:
        return {
            "ok": False,
            "status": "source_failed",
            "error": "statcan payload had no scored points",
            "http_status": fetched.get("http_status"),
            "raw_sha256": _sha256(body),
        }
    return _payload_ok(
        body=body,
        http_status=fetched.get("http_status"),
        points=points,
        source_url=str(spec.get("endpoint") or STATCAN_WDS_URL),
    )


def _opener_bytes(
    opener: Callable[..., dict[str, Any]],
    url: str,
    *,
    timeout: float,
) -> tuple[bytes | None, int | None, str | None]:
    result = opener(url, timeout=timeout)
    if not result.get("ok"):
        return None, result.get("http_status"), result.get("error") or "fetch_failed"
    return result.get("body") or b"", result.get("http_status"), None


def _fetch_sp_global_pmi(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    body, http_status, err = _opener_bytes(opener, PMI_LISTING_URL, timeout=timeout)
    if body is None:
        return {
            "ok": False,
            "status": "license_gap",
            "error": err or "pmi_listing_unreachable",
            "http_status": http_status,
            "challenge_page": http_status in {403, 202, 401},
        }
    if b"releaseTitle" not in body and body[:4] != b"%PDF":
        return {
            "ok": False,
            "status": "license_gap",
            "error": "pmi_listing_challenge_or_empty",
            "http_status": http_status,
            "challenge_page": True,
            "raw_sha256": _sha256(body),
            "body": body,
        }
    listing = body.decode("utf-8", errors="replace")
    rows = discover_canada_services_listing(listing)
    if not rows:
        return {
            "ok": False,
            "status": "license_gap",
            "error": "no_canada_services_pmi_in_listing",
            "http_status": http_status,
            "raw_sha256": _sha256(body),
            "body": body,
        }
    latest = rows[0]
    pdf_body, pdf_status, pdf_err = _opener_bytes(
        opener, latest["source_url"], timeout=timeout
    )
    if pdf_body is None or pdf_body[:4] != b"%PDF":
        return {
            "ok": False,
            "status": "license_gap",
            "error": pdf_err or "pmi_press_release_not_pdf",
            "http_status": pdf_status or http_status,
            "challenge_page": True,
            "raw_sha256": _sha256(pdf_body or body),
            "body": pdf_body or body,
        }
    parsed = parse_release_artifact(pdf_body)
    period = parsed.get("reference_period")
    value = parsed.get("composite_value")
    if not period or value is None:
        return {
            "ok": False,
            "status": "source_failed",
            "error": "pmi_pdf_missing_composite_value",
            "http_status": pdf_status,
            "raw_sha256": _sha256(pdf_body),
            "body": pdf_body,
        }
    transform = str(spec.get("transform") or "diffusion_index")
    point = _make_point(
        str(period),
        float(value),
        transform=transform,
        source_url=latest["source_url"],
        revision_status="final",
    )
    return _payload_ok(
        body=pdf_body,
        http_status=pdf_status,
        points=[point],
        source_url=latest["source_url"],
    )


def _fetch_housing_nhpi(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    def _fetch(url: str) -> bytes:
        data, _, err = _opener_bytes(opener, url, timeout=timeout)
        if data is None:
            raise OSError(err or "housing_fetch_failed")
        return data

    try:
        rows = _statcan_rows(STATCAN_NHPI_CSV, _fetch)
        parsed = parse_statcan_nhpi(rows)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": "source_failed",
            "error": str(exc),
            "http_status": None,
        }
    ref = str(parsed.get("reference_period") or "")
    period = ref[:7] if len(ref) >= 7 else ref
    metric = (parsed.get("metrics") or {}).get("new_housing_price_index") or {}
    value = metric.get("value")
    if not period or value is None:
        return {
            "ok": False,
            "status": "source_failed",
            "error": "nhpi_parse_missing_value",
        }
    point = _make_point(
        period,
        float(value),
        transform=str(spec.get("transform") or "index_level"),
        source_url=STATCAN_NHPI_PAGE,
    )
    return _payload_ok(
        body=json.dumps(parsed).encode(),
        http_status=200,
        points=[point],
        source_url=STATCAN_NHPI_PAGE,
    )


def fetch_series(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    now: datetime,
    timeout: float = 20,
) -> dict[str, Any]:
    """Return adapter payload for one Canada catalog row."""
    spec_id = str(spec.get("id") or "")
    method = str(spec.get("retrieval_method") or "")

    if spec_id == "CA.Consumer.confidence" or method == "unavailable":
        return {
            "ok": False,
            "status": "license_gap",
            "error": "bank_of_canada_csce_no_machine_readable_series",
            "http_status": None,
        }

    if spec_id == "CA.Activity.ivey_pmi":
        return {
            "ok": False,
            "status": "not_applicable",
            "error": "ivey_pmi_conflict_only_weight_zero_not_fetched",
            "http_status": None,
        }

    if spec_id == "CA.Activity.flash_composite_pmi":
        return {
            "ok": False,
            "status": "not_applicable",
            "error": "flash_composite_context_only_no_public_primary_pinned",
            "http_status": None,
        }

    if method == "existing_canada_housing_data":
        return _fetch_housing_nhpi(spec, opener=opener, timeout=timeout)

    if method in {
        "s_p_global_services_pmi_pdf_composite_section",
        "existing_harvest_ca_pmi",
    } or str(spec.get("series_id") or "") == "SP_GLOBAL_CA_COMPOSITE":
        return _fetch_sp_global_pmi(spec, opener=opener, timeout=timeout)

    if method == "statcan_wds_vectors":
        if spec.get("series_id") is None:
            return {
                "ok": False,
                "status": "source_failed",
                "error": f"{spec_id}: vector id unpinned in catalog fragment",
                "http_status": None,
            }
        return _fetch_statcan_series(spec, opener=opener, timeout=timeout)

    return {
        "ok": False,
        "status": "source_failed",
        "error": f"unsupported retrieval_method={method}",
        "http_status": None,
    }
