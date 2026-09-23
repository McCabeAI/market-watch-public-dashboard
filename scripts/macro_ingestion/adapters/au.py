"""Australia macro ingestion adapter (ABS workbooks, S&P PMI, housing context)."""

from __future__ import annotations

import hashlib
import io
import re
from calendar import monthrange
from datetime import date, datetime
from typing import Any, Callable

from scripts.australia_housing_data import collect_australia_housing
from scripts.harvest_au_pmi import (
    PMI_LISTING_URL,
    SEED_GUIDS,
    choose_observations,
    discover_australia_listing,
    is_flash_release,
    parse_release_artifact,
    press_release_url,
)

COUNTRY = "AU"

_CHALLENGE_MARKERS = (
    b"access denied",
    b"cf-chl",
    b"challenge-platform",
    b"just a moment",
    b"enable javascript",
)
_HTML_PREFIX = re.compile(rb"^\s*<(!DOCTYPE|html\b)", re.I)

RETAIL_SERIES_CEASED_AFTER = "2025-06"

_CONTEXT_SERIES_ENDPOINTS: dict[str, str] = {
    "AU.Inflation.ppi": (
        "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/"
        "producer-price-indexes-australia/jun-2026/642701.xlsx"
    ),
    "AU.Inflation.import_price_index": (
        "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/"
        "international-trade-price-indexes-australia/jun-2026/645701.xlsx"
    ),
    "AU.Inflation.export_price_index": (
        "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/"
        "international-trade-price-indexes-australia/jun-2026/645704.xlsx"
    ),
    "AU.Labor.participation": (
        "https://www.abs.gov.au/statistics/labour/employment-and-unemployment/"
        "labour-force-australia/jul-2026/62020001.xlsx"
    ),
}

_CONTEXT_SERIES_IDS: dict[str, str] = {
    "AU.Inflation.ppi": "A2314865F",
    "AU.Inflation.import_price_index": "A2295765J",
    "AU.Inflation.export_price_index": "A2294886K",
    "AU.Labor.participation": "A84423051C",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _base_payload(**kwargs: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "status": None,
        "points": [],
        "vintage": None,
        "raw_sha256": None,
        "error": None,
        "http_status": None,
        "challenge_page": False,
        "body": b"",
        **kwargs,
    }


def _looks_like_challenge(body: bytes, *, expect: str | None = None) -> bool:
    if not body:
        return False
    lower = body[:8000].lower()
    if any(marker in lower for marker in _CHALLENGE_MARKERS):
        return True
    if expect == "xlsx" and _HTML_PREFIX.match(body):
        return True
    if expect == "pdf" and _HTML_PREFIX.match(body):
        return True
    return False


def _period_from_cell(raw: Any, cadence: str) -> str | None:
    if isinstance(raw, datetime):
        dt = raw.date()
    elif isinstance(raw, date):
        dt = raw
    else:
        text = str(raw or "").strip()
        if not text:
            return None
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(text, fmt).date()
                break
            except ValueError:
                dt = None
        if dt is None:
            return None
    if cadence == "quarterly":
        quarter = (dt.month - 1) // 3 + 1
        return f"{dt.year:04d}-Q{quarter}"
    return f"{dt.year:04d}-{dt.month:02d}"


def _quarter_end_month(period: str) -> int:
    return int(period.split("-Q")[1]) * 3


def parse_abs_time_series_workbook(
    data: bytes,
    series_id: str,
    *,
    cadence: str,
) -> list[tuple[str, float]]:
    """Parse ABS 'Time Series Workbook' Data* sheet for one Series ID column."""
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover - dependency in requirements-market-state
        raise RuntimeError("openpyxl required for ABS workbook parse") from exc

    if data[:2] != b"PK":
        raise ValueError("not_xlsx_zip")

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    data_sheet = next((wb[name] for name in wb.sheetnames if name.startswith("Data")), None)
    if data_sheet is None:
        raise ValueError("missing_data_sheet")

    rows = list(data_sheet.iter_rows(values_only=True))
    if len(rows) < 11:
        raise ValueError("workbook_too_short")

    header_ids = rows[9]
    col_index = None
    for idx, cell in enumerate(header_ids):
        if cell == series_id:
            col_index = idx
            break
    if col_index is None:
        raise ValueError(f"series_id_not_in_workbook:{series_id}")

    out: list[tuple[str, float]] = []
    for row in rows[10:]:
        if not row or row[0] is None:
            continue
        period = _period_from_cell(row[0], cadence)
        if period is None:
            continue
        raw_val = row[col_index] if col_index < len(row) else None
        if raw_val is None:
            continue
        try:
            value = float(raw_val)
        except (TypeError, ValueError):
            continue
        out.append((period, value))
    if not out:
        raise ValueError("no_observations_parsed")
    return out


def _derive_mom_change_thousands(levels: list[tuple[str, float]]) -> list[tuple[str, float]]:
    derived: list[tuple[str, float]] = []
    for i in range(1, len(levels)):
        period, value = levels[i]
        prior = levels[i - 1][1]
        derived.append((period, float(value - prior)))
    return derived


def _derive_qoq_pct(levels: list[tuple[str, float]]) -> list[tuple[str, float]]:
    derived: list[tuple[str, float]] = []
    for i in range(1, len(levels)):
        period, value = levels[i]
        prior = levels[i - 1][1]
        if prior == 0:
            continue
        derived.append((period, (value - prior) / prior * 100.0))
    return derived


def _latest_point(
    series: list[tuple[str, float]],
    *,
    transform: str,
    source_url: str,
    max_period: str | None = None,
) -> dict[str, Any] | None:
    if not series:
        return None
    filtered = series
    if max_period is not None:
        filtered = [(p, v) for p, v in series if p <= max_period]
    if not filtered:
        return None
    period, value = filtered[-1]
    return {
        "period": period,
        "value": value,
        "transformation": transform,
        "revision_status": "final",
        "source_url": source_url,
    }


def _resolve_series_id(spec: dict[str, Any]) -> str | None:
    sid = spec.get("series_id")
    if not sid:
        return _CONTEXT_SERIES_IDS.get(spec["id"])
    text = str(sid)
    if ";" in text:
        return text.split(";")[0].strip()
    return text


def _resolve_endpoint(spec: dict[str, Any]) -> str | None:
    return spec.get("endpoint") or _CONTEXT_SERIES_ENDPOINTS.get(spec["id"])


def _fetch_workbook_bytes(
    url: str,
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    resp = opener(url, timeout=timeout)
    body = resp.get("body") or b""
    if _looks_like_challenge(body, expect="xlsx"):
        return _base_payload(
            ok=False,
            status="license_gap",
            challenge_page=True,
            http_status=resp.get("http_status"),
            error="challenge_page",
            raw_sha256=_sha256(body) if body else None,
            body=body,
            url=resp.get("url") or url,
        )
    if not resp.get("ok") or not body:
        return _base_payload(
            ok=False,
            status="source_failed",
            http_status=resp.get("http_status"),
            error=resp.get("error") or "fetch_failed",
            body=body,
        )
    if body[:2] != b"PK":
        return _base_payload(
            ok=False,
            status="source_failed",
            http_status=resp.get("http_status"),
            error="not_xlsx",
            raw_sha256=_sha256(body),
            body=body,
        )
    return {
        "ok": True,
        "body": body,
        "http_status": resp.get("http_status"),
        "error": None,
        "raw_sha256": _sha256(body),
        "url": resp.get("url") or url,
    }


def _fetch_abs_workbook_series(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
    max_period: str | None = None,
) -> dict[str, Any]:
    series_id = _resolve_series_id(spec)
    url = _resolve_endpoint(spec)
    if not series_id or not url:
        return _base_payload(
            ok=False,
            status="source_failed",
            error="missing_series_or_endpoint",
        )

    fetched = _fetch_workbook_bytes(url, opener=opener, timeout=timeout)
    if not fetched.get("ok"):
        return _base_payload(**{k: fetched[k] for k in fetched if k != "url"})

    cadence = str(spec.get("cadence") or "monthly")
    if cadence == "ceased":
        cadence = "monthly"

    try:
        levels = parse_abs_time_series_workbook(fetched["body"], series_id, cadence=cadence)
    except ValueError as exc:
        return _base_payload(
            ok=False,
            status="source_failed",
            error=str(exc),
            http_status=fetched.get("http_status"),
            raw_sha256=fetched.get("raw_sha256"),
            body=fetched.get("body") or b"",
        )

    transform = str(spec.get("transform") or "")
    retrieval = str(spec.get("retrieval_method") or "")

    if transform == "mom_change_thousands_sa":
        series = _derive_mom_change_thousands(levels)
    elif transform == "qoq_pct" and retrieval == "abs_time_series_workbook_derived_qoq":
        series = _derive_qoq_pct(levels)
    else:
        series = levels

    point = _latest_point(
        series,
        transform=transform,
        source_url=url,
        max_period=max_period,
    )
    if point is None:
        return _base_payload(
            ok=False,
            status="source_failed",
            error="no_point_after_filters",
            raw_sha256=fetched.get("raw_sha256"),
            body=fetched.get("body") or b"",
            http_status=fetched.get("http_status"),
        )

    return _base_payload(
        ok=True,
        points=[point],
        vintage="latest_available",
        raw_sha256=fetched.get("raw_sha256"),
        http_status=fetched.get("http_status"),
        body=fetched.get("body") or b"",
    )


def _opener_fetch_bytes(
    opener: Callable[..., dict[str, Any]],
    url: str,
    *,
    timeout: float,
) -> bytes:
    resp = opener(url, timeout=timeout)
    if not resp.get("ok"):
        raise RuntimeError(resp.get("error") or "fetch_failed")
    return resp.get("body") or b""


def _fetch_housing_context(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    now: datetime,
    timeout: float,
) -> dict[str, Any]:
    def fetch_bytes(url: str, **_kwargs: Any) -> bytes:
        return _opener_fetch_bytes(opener, url, timeout=timeout)

    block = collect_australia_housing(today=now.date(), fetch_bytes=fetch_bytes)
    status = block.get("status")
    if status == "unavailable":
        return _base_payload(
            ok=False,
            status="source_failed",
            error="housing_feeds_unavailable",
        )
    return _base_payload(
        ok=True,
        vintage="latest_available",
        raw_sha256=_sha256(repr(block).encode()),
        points=[],
    )


def _fetch_pmi(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    now: datetime,
    timeout: float,
    flash_only: bool,
    finals_only: bool,
) -> dict[str, Any]:
    attempted_urls: list[str] = []
    listing = opener(spec.get("endpoint") or PMI_LISTING_URL, timeout=timeout)
    listing_body = listing.get("body") or b""
    if _looks_like_challenge(listing_body, expect="pdf") or listing.get("http_status") in {403, 202}:
        return _base_payload(
            ok=False,
            status="license_gap",
            challenge_page=True,
            http_status=listing.get("http_status"),
            error="pmi_listing_challenge",
            raw_sha256=_sha256(listing_body) if listing_body else None,
            body=listing_body,
        )

    html = listing_body.decode("utf-8", errors="replace") if listing_body else ""
    discovered = discover_australia_listing(html) if html else []
    guids: list[str] = []
    for guid in SEED_GUIDS:
        if guid not in guids:
            guids.append(guid)
    for row in discovered:
        guid = row.get("guid")
        if guid and guid not in guids:
            guids.append(guid)

    parsed_releases: list[dict[str, Any]] = []
    last_body = listing_body
    last_status = listing.get("http_status")

    for guid in guids:
        url = press_release_url(guid)
        attempted_urls.append(url)
        resp = opener(url, timeout=timeout)
        body = resp.get("body") or b""
        last_body = body or last_body
        last_status = resp.get("http_status")
        if _looks_like_challenge(body, expect="pdf"):
            return _base_payload(
                ok=False,
                status="license_gap",
                challenge_page=True,
                http_status=resp.get("http_status"),
                error="pmi_release_challenge",
                raw_sha256=_sha256(body) if body else None,
                body=body,
            )
        if body[:4] != b"%PDF":
            continue
        meta = parse_release_artifact(body)
        flash = bool(meta.get("is_flash"))
        if flash_only and not flash:
            continue
        if finals_only and flash:
            continue
        parsed_releases.append(
            {
                "source_url": url,
                "release_date": meta.get("release_date"),
                "reference_period": meta.get("reference_period"),
                "composite_value": meta.get("composite_value"),
                "is_flash": flash,
                "restated_priors": meta.get("restated_priors"),
                "body": body,
            }
        )

    if not parsed_releases:
        return _base_payload(
            ok=False,
            status="license_gap",
            challenge_page=True,
            http_status=last_status,
            error="pmi_no_primary_pdf",
            raw_sha256=_sha256(last_body) if last_body else None,
            body=last_body,
        )

    retrieved_at = now.astimezone().isoformat()
    chosen = choose_observations(
        [
            {
                "source_url": rel["source_url"],
                "release_date": rel.get("release_date"),
                "reference_period": rel.get("reference_period"),
                "composite_value": rel.get("composite_value"),
                "is_flash": rel.get("is_flash"),
                "restated_priors": rel.get("restated_priors"),
            }
            for rel in parsed_releases
        ],
        retrieved_at=retrieved_at,
    )
    if not chosen:
        return _base_payload(
            ok=False,
            status="source_failed",
            error="pmi_no_observation_in_window",
            body=parsed_releases[-1].get("body") or b"",
            raw_sha256=_sha256(parsed_releases[-1].get("body") or b""),
        )

    latest_period = sorted(chosen.keys())[-1]
    obs = chosen[latest_period]
    revision = obs.get("revision_status") or "final"
    if flash_only:
        revision = "flash"

    point = {
        "period": latest_period,
        "value": float(obs["value"]),
        "transformation": spec.get("transform"),
        "revision_status": revision,
        "source_url": obs.get("source_url"),
    }
    pdf_body = next(
        (rel.get("body") for rel in parsed_releases if rel.get("source_url") == obs.get("source_url")),
        parsed_releases[-1].get("body") or b"",
    )
    return _base_payload(
        ok=True,
        points=[point],
        vintage="latest_available",
        raw_sha256=_sha256(pdf_body),
        http_status=200,
        body=pdf_body,
    )


def fetch_series(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    now: datetime,
    timeout: float = 20,
) -> dict[str, Any]:
    role = spec.get("role")
    spec_id = spec.get("id", "")

    if role == "explanatory_alias":
        return _base_payload(
            ok=False,
            status="not_applicable",
            error="explanatory_alias",
        )

    if spec_id == "AU.Consumer.confidence":
        return _base_payload(
            ok=False,
            status="source_failed",
            error="westpac_unverified_no_primary_adapter",
        )

    if spec.get("retrieval_method") == "existing_australia_housing_data":
        return _fetch_housing_context(spec, opener=opener, now=now, timeout=timeout)

    if spec_id == "AU.Activity.business_surveys":
        return _fetch_pmi(spec, opener=opener, now=now, timeout=timeout, flash_only=False, finals_only=True)

    if spec_id == "AU.Activity.flash_composite_pmi":
        return _fetch_pmi(spec, opener=opener, now=now, timeout=timeout, flash_only=True, finals_only=False)

    max_period: str | None = None
    if spec_id in {"AU.Consumer.retail", "AU.Consumer.retail_ceased"}:
        max_period = RETAIL_SERIES_CEASED_AFTER

    if spec.get("retrieval_method", "").startswith("abs_time_series_workbook"):
        return _fetch_abs_workbook_series(
            spec,
            opener=opener,
            timeout=timeout,
            max_period=max_period,
        )

    if spec.get("series_id") is None and spec_id in _CONTEXT_SERIES_ENDPOINTS:
        overlay = dict(spec)
        overlay["series_id"] = _CONTEXT_SERIES_IDS[spec_id]
        overlay["endpoint"] = _CONTEXT_SERIES_ENDPOINTS[spec_id]
        return _fetch_abs_workbook_series(
            overlay,
            opener=opener,
            timeout=timeout,
            max_period=max_period,
        )

    return _base_payload(
        ok=False,
        status="source_failed",
        error="unsupported_au_series",
    )
