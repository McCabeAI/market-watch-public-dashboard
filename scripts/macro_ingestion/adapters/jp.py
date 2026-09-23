"""Japan macro ingestion adapter (official sources only)."""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

from scripts.harvest_jp_pmi import (
    PMI_LISTING_URL,
    discover_japan_listing,
    parse_release_artifact,
    press_release_url,
)
from scripts.japan_macro_data import (
    ESTAT_FILE_DOWNLOAD,
    SOURCE_CONTRACT,
    discover_esri_gdp_csv_url,
    parse_cci_workbook,
    parse_cpi_yoy_csv,
    parse_esri_real_gdp_qoq_saar_csv,
    parse_fies_estat_nominal_yoy_xlsx,
    parse_lfs_major_items_xlsx,
    parse_meti_retail_yoy_xlsx,
    parse_mhlw_cash_earnings_yoy_xls,
    parse_tankan_large_mfg_di_zip,
)

COUNTRY = "JP"

BOJ_CGPI_INDEX_URL = "https://www.boj.or.jp/en/statistics/pi/cgpi_release/index.htm"
METI_IIP_URL = "https://www.meti.go.jp/english/statistics/tyo/iip/index.html"

_DOMESTIC_DEMAND_COL = 18


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fail(
    *,
    error: str,
    status: str | None = None,
    http_status: int | None = None,
    url: str | None = None,
    challenge_page: bool = False,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "ok": False,
        "points": [],
        "error": error,
        "http_status": http_status,
        "vintage": None,
        "raw_sha256": _sha256(error.encode()),
    }
    if status:
        out["status"] = status
    if challenge_page:
        out["challenge_page"] = True
    if url:
        out["source_url"] = url
    return out


def _success(
    *,
    body: bytes,
    points: list[dict[str, Any]],
    source_url: str,
    http_status: int | None = 200,
    vintage: str = "latest_available",
) -> dict[str, Any]:
    return {
        "ok": True,
        "points": points,
        "body": body,
        "raw_sha256": _sha256(body),
        "vintage": vintage,
        "http_status": http_status,
        "error": None,
        "source_url": source_url,
    }


def _looks_like_html(body: bytes) -> bool:
    head = body[:256].lstrip().lower()
    return head.startswith(b"<!doc") or head.startswith(b"<html")


def _looks_like_challenge(body: bytes, http_status: int | None) -> bool:
    if http_status in {202, 403, 401}:
        return True
    text = body[:4096].decode("utf-8", errors="replace").lower()
    return any(
        token in text
        for token in (
            "captcha",
            "access denied",
            "challenge",
            "please enable cookies",
            "bot detection",
        )
    )


def _fetch(opener: Callable[..., dict[str, Any]], url: str, *, timeout: float) -> dict[str, Any]:
    return opener(url, timeout=timeout)


def _require_body(
    resp: dict[str, Any],
    *,
    expect_binary: bool = True,
) -> tuple[bytes, int | None, str] | dict[str, Any]:
    url = str(resp.get("url") or "")
    if not resp.get("ok"):
        err = str(resp.get("error") or "transport_failed")
        if _looks_like_challenge(resp.get("body") or b"", resp.get("http_status")):
            return _fail(
                error=err,
                status="license_gap",
                http_status=resp.get("http_status"),
                url=url,
                challenge_page=True,
            )
        return _fail(error=err, status="source_failed", http_status=resp.get("http_status"), url=url)
    body: bytes = resp.get("body") or b""
    if not body:
        return _fail(error="empty_body", status="source_failed", http_status=resp.get("http_status"), url=url)
    if expect_binary and _looks_like_html(body):
        if _looks_like_challenge(body, resp.get("http_status")):
            return _fail(
                error="html_challenge_body",
                status="license_gap",
                http_status=resp.get("http_status"),
                url=url,
                challenge_page=True,
            )
        return _fail(error="html_instead_of_data", status="source_failed", http_status=resp.get("http_status"), url=url)
    return body, resp.get("http_status"), url


def _observations_to_points(
    observations: list[dict[str, Any]],
    *,
    transform: str,
    source_url: str,
    revision_status: str = "final",
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for obs in observations:
        period = str(obs["reference_period"])
        if period in {"latest", "unknown"}:
            continue
        points.append(
            {
                "period": period,
                "value": float(obs["value"]),
                "transformation": transform,
                "revision_status": revision_status,
                "source_url": source_url,
                "prior": obs.get("prior"),
            }
        )
    return points


def _estat_download(
    stat_infid: str,
    file_kind: int,
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    url = ESTAT_FILE_DOWNLOAD.format(sid=stat_infid, fk=file_kind)

    def fetcher(u: str) -> bytes:
        got = _require_body(_fetch(opener, u, timeout=timeout))
        if isinstance(got, dict):
            raise RuntimeError(got.get("error") or "estat_fetch_failed")
        return got[0]

    from scripts.japan_macro_data import download_estat

    try:
        body = download_estat(stat_infid, file_kind, fetcher=fetcher)
    except Exception as exc:  # noqa: BLE001
        return _fail(error=str(exc), status="source_failed", url=url)
    return _success(body=body, points=[], source_url=url)


def _fetch_cpi(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    contract = SOURCE_CONTRACT["Inflation.headline"]
    base = _estat_download(contract["stat_infid"], contract["file_kind"], opener=opener, timeout=timeout)
    if not base.get("ok"):
        return base
    body = base["body"]
    text = body.decode("cp932", errors="replace")
    headline, underlying = parse_cpi_yoy_csv(text)
    series_id = str(spec.get("series_id") or "")
    if series_id == SOURCE_CONTRACT["Inflation.underlying"]["series_id"]:
        obs = underlying
    else:
        obs = headline
    transform = str(spec.get("transform") or "yoy_pct")
    points = _observations_to_points(obs, transform=transform, source_url=base["source_url"])
    if not points:
        return _fail(error="cpi_parse_empty", status="source_failed", url=base["source_url"])
    base["points"] = points
    return base


def _fetch_lfs_unemployment_or_employment(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    contract = SOURCE_CONTRACT["Labor.unemployment"]
    base = _estat_download(contract["stat_infid"], 0, opener=opener, timeout=timeout)
    if not base.get("ok"):
        return base
    unemp, emp, _ = parse_lfs_major_items_xlsx(base["body"])
    series_id = str(spec.get("series_id") or "")
    if series_id == SOURCE_CONTRACT["Labor.employment"]["series_id"]:
        obs = emp
    else:
        obs = unemp
    transform = str(spec.get("transform") or "rate_pct")
    points = _observations_to_points(obs, transform=transform, source_url=base["source_url"])
    if not points:
        return _fail(error="lfs_parse_empty", status="source_failed", url=base["source_url"])
    base["points"] = points
    return base


def _fetch_wages(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    contract = SOURCE_CONTRACT["Labor.wages"]
    base = _estat_download(contract["stat_infid"], contract["file_kind"], opener=opener, timeout=timeout)
    if not base.get("ok"):
        return base
    wages = parse_mhlw_cash_earnings_yoy_xls(base["body"])
    transform = str(spec.get("transform") or "yoy_pct")
    points = _observations_to_points(wages, transform=transform, source_url=base["source_url"])
    if not points:
        return _fail(error="wages_parse_empty", status="source_failed", url=base["source_url"])
    base["points"] = points
    return base


def _fetch_gdp(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    def fetcher(u: str) -> bytes:
        got = _require_body(_fetch(opener, u, timeout=timeout))
        if isinstance(got, dict):
            raise RuntimeError(got.get("error") or "gdp_fetch_failed")
        return got[0]

    try:
        csv_url = discover_esri_gdp_csv_url(fetcher=fetcher)
        body = fetcher(csv_url)
    except Exception as exc:  # noqa: BLE001
        pinned = SOURCE_CONTRACT["Activity.gdp_domestic_demand"]["pinned_csv_url"]
        got = _require_body(_fetch(opener, pinned, timeout=timeout))
        if isinstance(got, dict):
            return got
        body, http_status, csv_url = got
    else:
        http_status = 200
    gdp_obs = parse_esri_real_gdp_qoq_saar_csv(body.decode("cp932", errors="replace"))
    transform = str(spec.get("transform") or "qoq_pct_saar")
    points = _observations_to_points(gdp_obs, transform=transform, source_url=csv_url)
    if not points:
        return _fail(error="gdp_parse_empty", status="source_failed", url=csv_url)
    return _success(body=body, points=points, source_url=csv_url, http_status=http_status)


def parse_esri_domestic_demand_qoq_saar_csv(text: str) -> list[dict[str, Any]]:
    """Domestic demand SAAR column from ESRI nritu-jk* sokuhou CSV (context)."""
    lines = text.splitlines()
    out: list[dict[str, Any]] = []
    year_carry: int | None = None
    quarter_map = {"1- 3.": 1, "4- 6.": 2, "7- 9.": 3, "10-12.": 4}

    def append_quarter(q: int, parts: list[str]) -> None:
        nonlocal year_carry
        if year_carry is None or q is None or len(parts) <= _DOMESTIC_DEMAND_COL:
            return
        cell = parts[_DOMESTIC_DEMAND_COL].strip()
        if not cell or cell == "***":
            return
        try:
            val = float(cell)
        except ValueError:
            return
        period = f"{year_carry}-Q{q}"
        from scripts.japan_macro_data import period_in_window_quarter

        if period_in_window_quarter(period):
            out.append({"reference_period": period, "value": val})

    for line in lines:
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        if not parts:
            continue
        head = parts[0]
        ym = re.match(r"(\d{4})/\s*(\d{1,2})-\s*(\d{1,2})\.", head)
        if ym:
            year_carry = int(ym.group(1))
            q_label = f"{ym.group(2)}- {ym.group(3)}."
            if q_label == "10- 12.":
                q_label = "10-12."
            q = quarter_map.get(q_label)
            if q:
                append_quarter(q, parts)
            continue
        qm = re.match(r"(\d{1,2})-\s*(\d{1,2})\.", head)
        if qm and year_carry:
            q_label = f"{qm.group(1)}- {qm.group(2)}."
            if q_label == "10- 12.":
                q_label = "10-12."
            q = quarter_map.get(q_label)
            if q:
                append_quarter(q, parts)
    return out


def _fetch_domestic_demand_context(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    gdp = _fetch_gdp(spec, opener=opener, timeout=timeout)
    if not gdp.get("ok"):
        return gdp
    text = gdp["body"].decode("cp932", errors="replace")
    obs = parse_esri_domestic_demand_qoq_saar_csv(text)
    transform = str(spec.get("transform") or "qoq_pct_saar")
    points = _observations_to_points(obs, transform=transform, source_url=gdp["source_url"])
    if not points:
        return _fail(error="domestic_demand_column_unparsed", status="source_failed", url=gdp["source_url"])
    gdp["points"] = points
    return gdp


def _meti_retail_url(spec: dict[str, Any]) -> str:
    endpoint = str(spec.get("endpoint") or "")
    if endpoint:
        return endpoint
    template = SOURCE_CONTRACT["Consumer.retail"]["url_template"]
    return template.format(yymm="202607")


def _fetch_retail(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    url = _meti_retail_url(spec)
    got = _require_body(_fetch(opener, url, timeout=timeout))
    if isinstance(got, dict):
        return got
    body, http_status, final_url = got
    retail = parse_meti_retail_yoy_xlsx(body)
    transform = str(spec.get("transform") or "yoy_pct")
    points = _observations_to_points(retail, transform=transform, source_url=final_url or url)
    if not points:
        return _fail(error="meti_retail_parse_empty", status="source_failed", url=url)
    return _success(body=body, points=points, source_url=final_url or url, http_status=http_status)


def _fetch_fies_row(
    spec: dict[str, Any],
    *,
    row_label: str,
    contract_key: str,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    contract = SOURCE_CONTRACT[contract_key]
    base = _estat_download(contract["stat_infid"], contract["file_kind"], opener=opener, timeout=timeout)
    if not base.get("ok"):
        return base
    obs = parse_fies_estat_nominal_yoy_xlsx(base["body"], row_label=row_label)
    transform = str(spec.get("transform") or "yoy_pct")
    points = _observations_to_points(obs, transform=transform, source_url=base["source_url"])
    if not points:
        return _fail(error="fies_parse_empty", status="source_failed", url=base["source_url"])
    base["points"] = points
    return base


def _fetch_confidence(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    contract = SOURCE_CONTRACT["Consumer.confidence"]
    urls = [
        contract["esri_shouhi2_sa_xlsx_en"],
        ESTAT_FILE_DOWNLOAD.format(sid=contract["stat_infid"], fk=0),
        ESTAT_FILE_DOWNLOAD.format(sid=contract["stat_infid_april_2026"], fk=0),
    ]
    last_err = "confidence_sources_unavailable"
    for url in urls:
        got = _require_body(_fetch(opener, url, timeout=timeout))
        if isinstance(got, dict):
            last_err = str(got.get("error") or last_err)
            continue
        body, http_status, final_url = got
        try:
            cci = parse_cci_workbook(body)
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            continue
        transform = str(spec.get("transform") or "diffusion_index")
        points = _observations_to_points(cci, transform=transform, source_url=final_url or url)
        if points:
            return _success(body=body, points=points, source_url=final_url or url, http_status=http_status)
    return _fail(error=last_err, status="source_failed", url=urls[0])


def _fetch_pmi_from_pdf_body(
    body: bytes,
    *,
    source_url: str,
    http_status: int | None,
    transform: str,
    allow_flash: bool,
) -> dict[str, Any]:
    if body[:4] != b"%PDF":
        return _fail(error="non_pdf_body", status="source_failed", url=source_url, http_status=http_status)
    parsed = parse_release_artifact(body)
    if parsed.get("is_flash") and not allow_flash:
        return _success(body=body, points=[], source_url=source_url, http_status=http_status)
    if not parsed.get("is_flash") and allow_flash:
        return _success(body=body, points=[], source_url=source_url, http_status=http_status)
    period = parsed.get("reference_period")
    value = parsed.get("composite_value")
    if not period or value is None:
        return _fail(error="pmi_pdf_unparsed", status="source_failed", url=source_url, http_status=http_status)
    rev = "flash" if parsed.get("is_flash") else "final"
    points = [
        {
            "period": str(period),
            "value": float(value),
            "transformation": transform,
            "revision_status": rev,
            "source_url": source_url,
        }
    ]
    return _success(body=body, points=points, source_url=source_url, http_status=http_status)


def _fetch_scored_pmi(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    listing_resp = _fetch(opener, PMI_LISTING_URL, timeout=timeout)
    listing_body = listing_resp.get("body") or b""
    if _looks_like_challenge(listing_body, listing_resp.get("http_status")) or not listing_resp.get("ok"):
        return _fail(
            error=str(listing_resp.get("error") or "pmi_listing_blocked"),
            status="license_gap",
            http_status=listing_resp.get("http_status"),
            url=PMI_LISTING_URL,
            challenge_page=True,
        )
    html = listing_body.decode("utf-8", errors="replace")
    rows = discover_japan_listing(html)
    guids = [r["guid"] for r in rows]
    transform = str(spec.get("transform") or "diffusion_index")
    for guid in guids[:12]:
        url = press_release_url(guid)
        resp = _fetch(opener, url, timeout=timeout)
        body = resp.get("body") or b""
        if _looks_like_challenge(body, resp.get("http_status")):
            continue
        if body[:4] == b"%PDF" and len(body) > 5000:
            parsed = _fetch_pmi_from_pdf_body(
                body,
                source_url=url,
                http_status=resp.get("http_status"),
                transform=transform,
                allow_flash=False,
            )
            if parsed.get("ok") and parsed.get("points"):
                return parsed
    return _fail(
        error="no_primary_final_pmi_pdf",
        status="license_gap",
        http_status=listing_resp.get("http_status"),
        url=PMI_LISTING_URL,
        challenge_page=True,
    )


def _fetch_flash_pmi_context(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    """Flash PMI: never invent a value; only parse a primary PDF retrieved in this call."""
    listing_resp = _fetch(opener, PMI_LISTING_URL, timeout=timeout)
    listing_body = listing_resp.get("body") or b""
    if not listing_resp.get("ok") or _looks_like_challenge(listing_body, listing_resp.get("http_status")):
        return _success(
            body=listing_body,
            points=[],
            source_url=PMI_LISTING_URL,
            http_status=listing_resp.get("http_status"),
        )
    html = listing_body.decode("utf-8", errors="replace")
    rows = [r for r in discover_japan_listing(html) if "Flash" in r.get("title", "")]
    transform = str(spec.get("transform") or "diffusion_index")
    for row in rows[:6]:
        url = row["source_url"]
        resp = _fetch(opener, url, timeout=timeout)
        body = resp.get("body") or b""
        if body[:4] == b"%PDF" and len(body) > 5000:
            return _fetch_pmi_from_pdf_body(
                body,
                source_url=url,
                http_status=resp.get("http_status"),
                transform=transform,
                allow_flash=True,
            )
    return _success(body=listing_body, points=[], source_url=PMI_LISTING_URL, http_status=listing_resp.get("http_status"))


def _fetch_tankan(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    url = str(spec.get("endpoint") or "https://www.boj.or.jp/en/statistics/tk/gaiyo/2026/tka2606.zip")
    got = _require_body(_fetch(opener, url, timeout=timeout))
    if isinstance(got, dict):
        return got
    body, http_status, final_url = got
    if not zipfile.is_zipfile(io.BytesIO(body)):
        return _fail(error="tankan_not_zip", status="source_failed", url=url, http_status=http_status)
    parsed = parse_tankan_large_mfg_di_zip(body)
    transform = str(spec.get("transform") or "diffusion_index")
    points: list[dict[str, Any]] = []
    for item in parsed:
        period = str(item.get("reference_period") or "")
        if period == "latest":
            continue
        points.append(
            {
                "period": period,
                "value": float(item["value"]),
                "transformation": transform,
                "revision_status": "final",
                "source_url": final_url or url,
            }
        )
    if not points:
        return _fail(error="tankan_zip_unparsed", status="source_failed", url=url, http_status=http_status)
    return _success(body=body, points=points, source_url=final_url or url, http_status=http_status)


def _fetch_participation_context(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    contract = SOURCE_CONTRACT["Labor.unemployment"]
    url = ESTAT_FILE_DOWNLOAD.format(sid=contract["stat_infid"], fk=0)
    resp = _fetch(opener, url, timeout=timeout)
    if not resp.get("ok"):
        return _fail(
            error=str(resp.get("error") or "lfs_fetch_failed"),
            status="source_failed",
            http_status=resp.get("http_status"),
            url=url,
        )
    return _fail(
        error="participation_rate_not_in_lfs_1a1_major_items_table",
        status="not_applicable",
        http_status=resp.get("http_status"),
        url=url,
    )


def _fetch_cgpi_context(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    url = str(spec.get("endpoint") or BOJ_CGPI_INDEX_URL)
    resp = _fetch(opener, url, timeout=timeout)
    if not resp.get("ok"):
        return _fail(
            error=str(resp.get("error") or "cgpi_page_failed"),
            status="source_failed",
            http_status=resp.get("http_status"),
            url=url,
        )
    body = resp.get("body") or b""
    html = body.decode("utf-8", errors="replace")
    if re.search(r"cgpi\d{4}\.pdf", html, re.I):
        return _fail(
            error="cgpi_index_level_only_in_official_pdf_no_pinned_csv",
            status="source_failed",
            http_status=resp.get("http_status"),
            url=url,
        )
    return _fail(
        error="cgpi_release_page_unparsed",
        status="source_failed",
        http_status=resp.get("http_status"),
        url=url,
    )


def _fetch_iip_context(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    url = str(spec.get("endpoint") or METI_IIP_URL)
    resp = _fetch(opener, url, timeout=timeout)
    body = resp.get("body") or b""
    if not resp.get("ok") or _looks_like_challenge(body, resp.get("http_status")):
        return _fail(
            error=str(resp.get("error") or "meti_iip_blocked"),
            status="source_failed",
            http_status=resp.get("http_status"),
            url=url,
        )
    html = body.decode("utf-8", errors="replace")
    xlsx_links = re.findall(r'href="([^"]+\.xlsx[^"]*)"', html, re.I)
    for href in xlsx_links[:5]:
        file_url = urljoin(url, href)
        got = _require_body(_fetch(opener, file_url, timeout=timeout))
        if isinstance(got, dict):
            continue
        file_body, http_status, file_url = got
        try:
            import openpyxl

            wb = openpyxl.load_workbook(io.BytesIO(file_body), read_only=True, data_only=True)
            _ = wb.sheetnames
        except Exception:  # noqa: BLE001
            continue
        return _fail(
            error="meti_iip_workbook_layout_unparsed",
            status="source_failed",
            http_status=http_status,
            url=file_url,
        )
    return _fail(
        error="meti_iip_page_unparsed",
        status="source_failed",
        http_status=resp.get("http_status"),
        url=url,
    )


_HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
    "JP.Inflation.headline": _fetch_cpi,
    "JP.Inflation.underlying": _fetch_cpi,
    "JP.Labor.unemployment": _fetch_lfs_unemployment_or_employment,
    "JP.Labor.employment": _fetch_lfs_unemployment_or_employment,
    "JP.Labor.wages": _fetch_wages,
    "JP.Activity.gdp_domestic_demand": _fetch_gdp,
    "JP.Activity.business_surveys": _fetch_scored_pmi,
    "JP.Consumer.retail": _fetch_retail,
    "JP.Consumer.income": lambda spec, *, opener, timeout: _fetch_fies_row(
        spec, row_label="実収入", contract_key="Consumer.income", opener=opener, timeout=timeout
    ),
    "JP.Consumer.spending": lambda spec, *, opener, timeout: _fetch_fies_row(
        spec, row_label="消費支出", contract_key="Consumer.spending", opener=opener, timeout=timeout
    ),
    "JP.Consumer.confidence": _fetch_confidence,
    "JP.Inflation.cgpi_ppi": _fetch_cgpi_context,
    "JP.Inflation.import_price_index": _fetch_cgpi_context,
    "JP.Inflation.export_price_index": _fetch_cgpi_context,
    "JP.Labor.participation": _fetch_participation_context,
    "JP.Activity.domestic_demand": _fetch_domestic_demand_context,
    "JP.Activity.flash_composite_pmi": _fetch_flash_pmi_context,
    "JP.Activity.tankan_large_manufacturing": _fetch_tankan,
    "JP.Activity.industrial_production": _fetch_iip_context,
}


def fetch_series(
    spec: dict[str, Any],
    *,
    opener: Callable[..., dict[str, Any]],
    now: datetime,
    timeout: float = 20,
) -> dict[str, Any]:
    """Fetch one catalog row from official Japan sources."""
    _ = now  # calendar handled by runner; adapter is acquisition-only
    handler = _HANDLERS.get(str(spec.get("id")))
    if handler is None:
        method = str(spec.get("retrieval_method") or "")
        return _fail(error=f"unsupported_jp_series:{method}", status="source_failed")
    return handler(spec, opener=opener, timeout=timeout)
