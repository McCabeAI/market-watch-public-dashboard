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
    ALT_PUBLIC_DISCOVERY_URLS,
    PMI_LISTING_URL,
    SEED_GUIDS,
    cached_release_pdf,
    choose_observations,
    discover_eurozone_composite_listing,
    parse_release_artifact,
    parse_release_html,
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
    release_date: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "period": period,
        "value": value,
        "transformation": transform,
        "revision_status": revision_status,
        "source_url": source_url,
        "publisher": "S&P Global",
    }
    if prior is not None:
        row["prior"] = prior
    if release_date:
        row["release_date"] = release_date
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


def _listing_url(spec: dict[str, Any]) -> str:
    if str(spec.get("id") or "") == "EA.Activity.flash_composite_pmi":
        return str((spec.get("known_fixture") or {}).get("primary_listing") or PMI_LISTING_URL)
    return str(spec.get("endpoint") or PMI_LISTING_URL)


def _usable_html(resp: dict[str, Any]) -> bool:
    body = resp.get("body") or b""
    if not resp.get("ok") or not body:
        return False
    return not _is_bot_challenge(body, resp.get("http_status"))


def _is_listing_html(body: bytes) -> bool:
    return b"releaseTitle" in body and b"releaseDate" in body


def _attempt_summary(attempts: list[dict[str, Any]]) -> str:
    parts = []
    for row in attempts:
        parts.append(f"{row.get('http_status')}:{row.get('url')}")
    return "; ".join(parts)[:700]


def _headline_release(meta: dict[str, Any], *, source_url: str, body: bytes) -> dict[str, Any] | None:
    period = meta.get("reference_period")
    value = meta.get("composite_value")
    if not isinstance(period, str) or value is None:
        return None
    return {
        "source_url": source_url,
        "body": body,
        "reference_period": period,
        "composite_value": float(value),
        "is_flash": bool(meta.get("is_flash")),
        "release_date": meta.get("release_date"),
        "restated_priors": meta.get("restated_priors") or {},
    }


def _fetch_sp_composite_pmi(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
    flash_only: bool,
) -> dict[str, Any]:
    """Eurozone composite PMI via the public listing, article, or archived final PDF.

    Flash reads only a flash composite document for its own reference period.
    Finals may use the local archive of public PDFs. An archived final is never
    returned as the flash print.
    """
    listing_url = _listing_url(spec)
    attempts: list[dict[str, Any]] = []
    html_docs: list[tuple[str, bytes]] = []

    def _get(url: str) -> dict[str, Any]:
        resp = _fetch_bytes(opener, url, timeout=timeout)
        attempts.append(
            {
                "url": url,
                "http_status": resp.get("http_status"),
                "ok": bool(resp.get("ok")),
            }
        )
        return resp

    listing_resp = _get(listing_url)
    if _usable_html(listing_resp):
        html_docs.append((listing_url, listing_resp.get("body") or b""))
    else:
        for alt in ALT_PUBLIC_DISCOVERY_URLS:
            if alt == listing_url:
                continue
            alt_resp = _get(alt)
            if _usable_html(alt_resp):
                html_docs.append((alt, alt_resp.get("body") or b""))

    discovered: list[dict[str, str]] = []
    article_releases: list[dict[str, Any]] = []
    for url, body in html_docs:
        if _is_listing_html(body):
            discovered.extend(_parse_listing(body))
            continue
        meta = parse_release_html(body)
        headline = _headline_release(meta, source_url=url, body=body)
        if headline is not None:
            article_releases.append(headline)

    guids: list[str] = []
    for row in discovered:
        title = row.get("title", "")
        is_flash_title = "Flash" in title
        if flash_only and not is_flash_title:
            continue
        if not flash_only and is_flash_title:
            continue
        if row["guid"] not in guids:
            guids.append(row["guid"])

    if not flash_only:
        for guid in SEED_GUIDS:
            if guid not in guids:
                guids.append(guid)

    parsed_releases: list[dict[str, Any]] = []
    bodies: dict[str, bytes] = {}
    last_body = html_docs[-1][1] if html_docs else (listing_resp.get("body") or b"")
    last_status = listing_resp.get("http_status")

    for guid in guids[:12]:
        pdf_url = press_release_url(guid)
        pdf_resp = _get(pdf_url)
        pdf_body = pdf_resp.get("body") or b""
        if pdf_body[:4] != b"%PDF" and not flash_only:
            cached = cached_release_pdf(guid)
            if cached is not None:
                pdf_body = cached
                attempts.append(
                    {
                        "url": pdf_url,
                        "http_status": 200,
                        "ok": True,
                        "notes": "local_public_archive",
                    }
                )
        if pdf_body[:4] != b"%PDF":
            continue
        meta = parse_release_artifact(pdf_body)
        if flash_only and not meta.get("is_flash"):
            continue
        if not flash_only and meta.get("is_flash"):
            continue
        headline = _headline_release(meta, source_url=pdf_url, body=pdf_body)
        if headline is None:
            continue
        parsed_releases.append(headline)
        bodies[pdf_url] = pdf_body
        last_body = pdf_body
        last_status = pdf_resp.get("http_status") or 200

    if flash_only:
        selected = [row for row in parsed_releases + article_releases if row.get("is_flash")]
        if not selected:
            return _base_payload(
                ok=False,
                error=f"primary_flash_pdf_unavailable; {_attempt_summary(attempts)}",
                http_status=last_status,
                body=last_body,
                raw_sha256=_sha256(last_body),
            )
        selected.sort(key=lambda row: str(row["reference_period"]))
        chosen_row = selected[-1]
        transform = str(spec.get("transform") or "")
        point = _point(
            str(chosen_row["reference_period"]),
            float(chosen_row["composite_value"]),
            transform=transform,
            source_url=str(chosen_row["source_url"]),
            revision_status="flash",
            release_date=str(chosen_row["release_date"]) if chosen_row.get("release_date") else None,
        )
        primary = chosen_row.get("body") or last_body
        return _base_payload(
            ok=True,
            points=[point],
            http_status=last_status,
            body=primary,
            raw_sha256=_sha256(primary),
            vintage="flash",
        )

    for row in article_releases:
        if row.get("is_flash"):
            continue
        parsed_releases.append(row)

    if not parsed_releases:
        return _flash_primary_unavailable(
            body=last_body,
            http_status=last_status,
            url=listing_url,
            flash_only=False,
        )

    chosen = choose_observations(
        [
            {
                "source_url": row["source_url"],
                "release_date": row.get("release_date"),
                "is_flash": False,
                "reference_period": row["reference_period"],
                "composite_value": row["composite_value"],
                "restated_priors": row.get("restated_priors") or {},
            }
            for row in parsed_releases
        ],
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
            release_date=str(obs["release_date"]) if obs.get("release_date") else None,
        )
        for period, obs in sorted(chosen.items())
    ]
    primary_body = last_body
    for row in parsed_releases:
        if row["source_url"] in bodies:
            primary_body = bodies[row["source_url"]]
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
