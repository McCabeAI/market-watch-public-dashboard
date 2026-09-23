"""Euro-area (EA21) macro ingestion adapter."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable

from scripts.euro_area_macro_data import (
    employment_qq_change_thousands,
    eurostat_sdmx_url,
    eurostat_stats_url,
    parse_ecb_csvdata,
    parse_eurostat_sdmx_json,
    parse_eurostat_statistics_json,
)
from scripts.harvest_ea_pmi import (
    PMI_LISTING_URL,
    SEED_GUIDS,
    choose_observations,
    discover_eurozone_composite_listing,
    parse_release_artifact,
    press_release_url,
)

COUNTRY = "EA"

PPI_DATASET = "STS_INPPD_M"
PPI_PARAMS = {
    "geo": "EA21",
    "nace_r2": "B-E36",
    "indic_bt": "PRC_PRR_DOM",
    "s_adj": "NSA",
    "unit": "PCH_SM",
    "sinceTimePeriod": "2024-01",
}
PPI_SERIES_ID = "STS_INPPD_M.M.PRC_PRR_DOM.NSA.PCH_SM.B-E36.EA21"
PPI_AUTHORITY = "https://ec.europa.eu/eurostat/databrowser/view/sts_inppd_m/default/table"

IMPORT_EXPORT_CHECK_URL = (
    "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/STS_INPPD_M"
    "?geo=EA21&sinceTimePeriod=2025-01"
)
PARTICIPATION_CHECK_URL = "https://ec.europa.eu/eurostat/web/lfs"
HICP_FLASH_CHECK_URL = "https://ec.europa.eu/eurostat/web/hicp"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _base_payload(**kwargs: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "ok": False,
        "points": [],
        "vintage": "latest_available",
        "error": None,
        "http_status": None,
        "challenge_page": False,
        "body": b"",
    }
    out.update(kwargs)
    return out


def _looks_like_html(body: bytes) -> bool:
    head = body[:800].lower()
    return b"<!doctype html" in head or b"<html" in head


def _is_bot_challenge(body: bytes, http_status: int | None, *, expect_pdf: bool = False) -> bool:
    if not body:
        return http_status in {403, 202, 503, 429}
    if body[:4] == b"%PDF":
        return False
    if not _looks_like_html(body):
        return http_status in {403, 202, 429}
    lower = body.lower()
    markers = (
        b"challenge",
        b"captcha",
        b"access denied",
        b"request blocked",
        b"cf-browser-verification",
        b"akamai",
    )
    if any(m in lower for m in markers):
        return True
    if expect_pdf or http_status in {403, 202, 429}:
        return True
    return False


def _point(
    period: str,
    value: float,
    *,
    transform: str,
    source_url: str,
    revision_status: str = "final",
    prior: float | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "period": period,
        "value": value,
        "transformation": transform,
        "revision_status": revision_status,
        "source_url": source_url,
    }
    if prior is not None:
        row["prior"] = prior
    return row


def _fetch_bytes(opener: Callable[..., dict[str, Any]], url: str, *, timeout: float) -> dict[str, Any]:
    return opener(url, timeout=timeout)


def _fetch_eurostat_statistics(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
    url: str | None = None,
) -> dict[str, Any]:
    fetch_url = url or str(spec.get("endpoint") or "")
    if not fetch_url:
        return _base_payload(error="missing_endpoint")

    resp = _fetch_bytes(opener, fetch_url, timeout=timeout)
    body = resp.get("body") or b""
    http_status = resp.get("http_status")
    if not resp.get("ok"):
        return _base_payload(
            error=resp.get("error") or "transport_failed",
            http_status=http_status,
            body=body,
        )
    if _is_bot_challenge(body, http_status):
        return _base_payload(
            ok=False,
            status="license_gap",
            challenge_page=True,
            error=f"challenge_page at {fetch_url}",
            http_status=http_status,
            body=body,
            raw_sha256=_sha256(body),
        )
    try:
        payload = json.loads(body.decode("utf-8"))
        rows = parse_eurostat_statistics_json(payload)
    except Exception as exc:  # noqa: BLE001
        return _base_payload(
            error=f"parse_failed: {exc}",
            http_status=http_status,
            body=body,
            raw_sha256=_sha256(body),
        )

    transform = str(spec.get("transform") or "")
    points = [
        _point(p, v, transform=transform, source_url=fetch_url, revision_status="final")
        for p, v in rows
    ]
    return _base_payload(
        ok=True,
        points=points,
        http_status=http_status,
        body=body,
        raw_sha256=_sha256(body),
    )


def _fetch_eurostat_sdmx(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    fetch_url = str(spec.get("endpoint") or "")
    if not fetch_url:
        return _base_payload(error="missing_endpoint")
    resp = _fetch_bytes(opener, fetch_url, timeout=timeout)
    body = resp.get("body") or b""
    http_status = resp.get("http_status")
    if not resp.get("ok"):
        return _base_payload(error=resp.get("error") or "transport_failed", http_status=http_status, body=body)
    if _is_bot_challenge(body, http_status):
        return _base_payload(
            ok=False,
            status="license_gap",
            challenge_page=True,
            error=f"challenge_page at {fetch_url}",
            http_status=http_status,
            body=body,
            raw_sha256=_sha256(body),
        )
    try:
        payload = json.loads(body.decode("utf-8"))
        rows = parse_eurostat_sdmx_json(payload)
    except Exception as exc:  # noqa: BLE001
        return _base_payload(
            error=f"parse_failed: {exc}",
            http_status=http_status,
            body=body,
            raw_sha256=_sha256(body),
        )
    transform = str(spec.get("transform") or "")
    points = [
        _point(p, v, transform=transform, source_url=fetch_url, revision_status="final")
        for p, v in rows
    ]
    return _base_payload(
        ok=True,
        points=points,
        http_status=http_status,
        body=body,
        raw_sha256=_sha256(body),
    )


def _fetch_ecb_wages(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    series_key = str(spec.get("series_id") or "")
    key_tail = series_key[4:] if series_key.startswith("INW.") else series_key
    fetch_url = (
        f"https://data-api.ecb.europa.eu/service/data/INW/{key_tail}"
        f"?format=csvdata&startPeriod=2024-Q1"
    )
    resp = _fetch_bytes(opener, fetch_url, timeout=timeout)
    body = resp.get("body") or b""
    http_status = resp.get("http_status")
    if not resp.get("ok"):
        return _base_payload(error=resp.get("error") or "transport_failed", http_status=http_status, body=body)
    if _is_bot_challenge(body, http_status):
        return _base_payload(
            ok=False,
            status="license_gap",
            challenge_page=True,
            error=f"challenge_page at {fetch_url}",
            http_status=http_status,
            body=body,
            raw_sha256=_sha256(body),
        )
    try:
        rows = parse_ecb_csvdata(body.decode("utf-8"), series_key=series_key)
    except Exception as exc:  # noqa: BLE001
        return _base_payload(
            error=f"parse_failed: {exc}",
            http_status=http_status,
            body=body,
            raw_sha256=_sha256(body),
        )
    transform = str(spec.get("transform") or "")
    points = [
        _point(p, v, transform=transform, source_url=fetch_url, revision_status="final")
        for p, v in rows
    ]
    return _base_payload(
        ok=True,
        points=points,
        http_status=http_status,
        body=body,
        raw_sha256=_sha256(body),
    )


def _fetch_employment_derived(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    level_id = "LFSI_EMP_Q.Q.SA.EMP_LFS.T.Y15-74.THS_PER.EA21"
    url = eurostat_stats_url(
        "LFSI_EMP_Q",
        {
            "geo": "EA21",
            "indic_em": "EMP_LFS",
            "sex": "T",
            "age": "Y15-74",
            "s_adj": "SA",
            "unit": "THS_PER",
            "sinceTimePeriod": "2024-Q1",
        },
    )
    resp = _fetch_eurostat_statistics(spec, opener=opener, timeout=timeout, url=url)
    if not resp.get("ok"):
        return resp
    try:
        payload = json.loads((resp.get("body") or b"").decode("utf-8"))
        levels = parse_eurostat_statistics_json(payload)
        changes = employment_qq_change_thousands(levels)
    except Exception as exc:  # noqa: BLE001
        return _base_payload(error=f"derive_failed: {exc}", body=resp.get("body") or b"")

    transform = str(spec.get("transform") or "")
    points = [
        _point(
            p,
            v,
            transform=transform,
            source_url=url,
            revision_status="final",
        )
        for p, v in changes
    ]
    return _base_payload(
        ok=True,
        points=points,
        http_status=resp.get("http_status"),
        body=resp.get("body") or b"",
        raw_sha256=resp.get("raw_sha256") or _sha256(resp.get("body") or b""),
    )


def _not_applicable(spec: dict[str, Any], *, url: str, reason: str) -> dict[str, Any]:
    return _base_payload(
        ok=False,
        status="not_applicable",
        error=f"{reason} (checked {url})",
        http_status=None,
    )


def _fetch_ppi_context(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    url = eurostat_stats_url(PPI_DATASET, PPI_PARAMS)
    resp = _fetch_eurostat_statistics(spec, opener=opener, timeout=timeout, url=url)
    if resp.get("ok") and resp.get("points"):
        return resp
    if resp.get("challenge_page"):
        return resp
    return _base_payload(
        ok=False,
        status="source_failed",
        error=f"EA21 domestic PPI key not returned from {PPI_AUTHORITY}",
        http_status=resp.get("http_status"),
        body=resp.get("body") or b"",
    )


def _parse_listing(html: bytes) -> list[dict[str, str]]:
    try:
        text = html.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return []
    return discover_eurozone_composite_listing(text)


def _flash_primary_unavailable(
    *,
    body: bytes,
    http_status: int | None,
    url: str,
    flash_only: bool,
) -> dict[str, Any]:
    """Flash due-window failures must not be classified as license_gap in the ledger."""
    if flash_only:
        return _base_payload(
            ok=False,
            error=f"primary_flash_pdf_unavailable at {url}",
            http_status=http_status,
            body=body,
            raw_sha256=_sha256(body),
        )
    return _base_payload(
        ok=False,
        status="license_gap",
        challenge_page=True,
        error=f"challenge_page at {url}",
        http_status=http_status,
        body=body,
        raw_sha256=_sha256(body),
    )


def _fetch_sp_composite_pmi(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
    flash_only: bool,
) -> dict[str, Any]:
    listing_url = str(spec.get("endpoint") or PMI_LISTING_URL)
    if str(spec.get("id") or "") == "EA.Activity.flash_composite_pmi":
        listing_url = str(
            (spec.get("known_fixture") or {}).get("primary_listing") or PMI_LISTING_URL
        )
    listing_resp = _fetch_bytes(opener, listing_url, timeout=timeout)
    listing_body = listing_resp.get("body") or b""
    http_status = listing_resp.get("http_status")

    if not listing_resp.get("ok") or not listing_body:
        return _flash_primary_unavailable(
            body=listing_body,
            http_status=http_status,
            url=listing_url,
            flash_only=flash_only,
        )
    if _is_bot_challenge(listing_body, http_status):
        return _flash_primary_unavailable(
            body=listing_body,
            http_status=http_status,
            url=listing_url,
            flash_only=flash_only,
        )

    discovered = _parse_listing(listing_body)
    guids: list[str] = []
    for row in discovered:
        title = row.get("title", "")
        is_flash_title = "Flash" in title
        if flash_only and not is_flash_title:
            continue
        if not flash_only and is_flash_title:
            continue
        guids.append(row["guid"])

    if flash_only and not guids:
        for row in discovered:
            if "Flash" in row.get("title", ""):
                guids.append(row["guid"])

    for guid in SEED_GUIDS:
        if guid not in guids and not flash_only:
            guids.append(guid)

    parsed_releases: list[dict[str, Any]] = []
    last_body = listing_body
    last_status = http_status

    for guid in guids[:12]:
        pdf_url = press_release_url(guid)
        pdf_resp = _fetch_bytes(opener, pdf_url, timeout=timeout)
        pdf_body = pdf_resp.get("body") or b""
        last_body = pdf_body or last_body
        last_status = pdf_resp.get("http_status")

        if not pdf_resp.get("ok"):
            continue
        if pdf_body[:4] != b"%PDF":
            if _is_bot_challenge(pdf_body, pdf_resp.get("http_status"), expect_pdf=True):
                return _flash_primary_unavailable(
                    body=pdf_body,
                    http_status=pdf_resp.get("http_status"),
                    url=pdf_url,
                    flash_only=flash_only,
                )
            continue
        meta = parse_release_artifact(pdf_body)
        if flash_only and not meta.get("is_flash"):
            continue
        if not flash_only and meta.get("is_flash"):
            continue
        parsed_releases.append({"guid": guid, "source_url": pdf_url, **meta})

    if not parsed_releases:
        return _flash_primary_unavailable(
            body=last_body,
            http_status=last_status,
            url=listing_url,
            flash_only=flash_only,
        )

    chosen = choose_observations(
        parsed_releases,
        retrieved_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )
    transform = str(spec.get("transform") or "")
    points = [
        _point(
            period,
            float(obs["value"]),
            transform=transform,
            source_url=str(obs["source_url"]),
            revision_status=str(obs.get("revision_status") or "final"),
        )
        for period, obs in sorted(chosen.items())
    ]
    primary_body = last_body
    for rel in parsed_releases:
        pdf_resp = _fetch_bytes(opener, rel["source_url"], timeout=timeout)
        if (pdf_resp.get("body") or b"")[:4] == b"%PDF":
            primary_body = pdf_resp.get("body") or primary_body
            break

    return _base_payload(
        ok=True,
        points=points,
        http_status=last_status,
        body=primary_body,
        raw_sha256=_sha256(primary_body),
    )


def fetch_series(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    now: datetime,
    timeout: float = 20,
) -> dict[str, Any]:
    """Fetch one catalog row for EA21. Never invent observations."""
    _ = now
    series_id = spec.get("id") or ""
    method = str(spec.get("retrieval_method") or "")

    if series_id == "EA.Inflation.ppi":
        return _fetch_ppi_context(spec, opener=opener, timeout=timeout)
    if series_id == "EA.Inflation.import_price_index":
        return _not_applicable(
            spec,
            url=IMPORT_EXPORT_CHECK_URL,
            reason="No EA21 import-price index in Eurostat STS API",
        )
    if series_id == "EA.Inflation.export_price_index":
        return _not_applicable(
            spec,
            url=IMPORT_EXPORT_CHECK_URL,
            reason="No EA21 export-price index distinct from domestic PPI in Eurostat STS API",
        )
    if series_id == "EA.Labor.participation":
        return _not_applicable(
            spec,
            url=PARTICIPATION_CHECK_URL,
            reason="EA21 quarterly participation series not exposed on checked Eurostat LFS API",
        )
    if series_id == "EA.Inflation.hicp_flash":
        return _not_applicable(
            spec,
            url=HICP_FLASH_CHECK_URL,
            reason="Distinct HICP flash vintage not pinned from Eurostat statistics API",
        )
    if series_id == "EA.Activity.flash_composite_pmi":
        return _fetch_sp_composite_pmi(spec, opener=opener, timeout=timeout, flash_only=True)
    if series_id == "EA.Activity.business_surveys":
        return _fetch_sp_composite_pmi(spec, opener=opener, timeout=timeout, flash_only=False)
    if method == "sp_global_press_release_pdf":
        listing_url = str(spec.get("endpoint") or PMI_LISTING_URL)
        return _not_applicable(
            spec,
            url=listing_url,
            reason="Sector PMI PDF parser not implemented; composite scored series uses business_surveys",
        )

    if method == "eurostat_statistics_api_derived" or series_id == "EA.Labor.employment":
        return _fetch_employment_derived(spec, opener=opener, timeout=timeout)
    if method == "ecb_sdmx_csvdata":
        return _fetch_ecb_wages(spec, opener=opener, timeout=timeout)
    if method == "eurostat_sdmx_json":
        return _fetch_eurostat_sdmx(spec, opener=opener, timeout=timeout)
    if method == "eurostat_statistics_api":
        return _fetch_eurostat_statistics(spec, opener=opener, timeout=timeout)

    return _base_payload(error=f"unsupported_retrieval_method:{method}")
