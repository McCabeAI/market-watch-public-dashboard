"""Euro-area member-state HICP: national flash/preliminary plus Eurostat final reconciliation."""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urljoin as _urljoin

from scripts.macro_ingestion.vintage import _record_sha_alias
from scripts.macro_freshness import values_close

COUNTRY_HICP_IDS = frozenset(
    {
        "EA.Inflation.hicp_de",
        "EA.Inflation.hicp_fr",
        "EA.Inflation.hicp_it",
        "EA.Inflation.hicp_es",
        "EA.Inflation.hicp_pt",
    }
)

CATALOG_ID_TO_GEO: dict[str, str] = {
    "EA.Inflation.hicp_de": "DE",
    "EA.Inflation.hicp_fr": "FR",
    "EA.Inflation.hicp_it": "IT",
    "EA.Inflation.hicp_es": "ES",
    "EA.Inflation.hicp_pt": "PT",
}

NATIONAL_LISTING_URLS: dict[str, str] = {
    "DE": "https://www.destatis.de/DE/Themen/Wirtschaft/Preise/Verbraucherpreisindex/_inhalt.html",
    "FR": "https://www.insee.fr/fr/solr/consultation",
    "IT": "https://www.istat.it/tag/prezzi-al-consumo/",
    "ES": "https://www.ine.es/dyngs/Prensa/notasPrensa.htm",
    "PT": "https://www.ine.pt/xportal/xmain?xpid=INE&xpgid=ine_destaques&DESTAQUEStema=5414296&xlang=pt",
}

DESTATIS_BASE = "https://www.destatis.de/"
DESTATIS_PRESS_RE = re.compile(
    r'href="([^"]*Pressemitteilungen/(\d{4})/(\d{2})/PD(\d{2})_(\d+)_611\.html)"',
    re.IGNORECASE,
)
DESTATIS_HICP_RE = re.compile(
    r"Harmonisierter\s+Verbraucherpreisindex,\s+(\w+)\s+(\d{4}):\s*[^%]*?(-?\d+[,.]\d+)\s*%\s*zum\s+Vorjahresmonat\s*\(([^)]+)\)",
    re.IGNORECASE | re.DOTALL,
)

INSEE_SOLR_BODY = json.dumps(
    {
        "q": "prix à la consommation",
        "start": 0,
        "rows": 8,
        "sortFields": [{"field": "dateDiffusion", "order": "desc"}],
        "filters": [{"field": "facetteCollectionId", "values": ["5"]}],
    }
).encode("utf-8")
INSEE_BDM_URL = "https://bdm.insee.fr/series/sdmx/data/SERIES_BDM/011812232?lastNObservations=6"
INSEE_ENSEMBLE_ROW_RE = re.compile(
    r"<tr[^>]*>.*?<t[hd][^>]*>\s*Ensemble\s+IPCH\*?\*?\s*</t[hd]>(.*?)</tr>",
    re.IGNORECASE | re.DOTALL,
)
INSEE_NUMERIC_CELL_RE = re.compile(r"(-?\d+[,.]\d+)")
INSEE_PROSE_HICP_RE = re.compile(
    r"indice\s+des\s+prix\s+à\s+la\s+consommation\s+harmonisé[^.]{0,400}?"
    r"(-?\d+[,.]\d+)\s*%",
    re.IGNORECASE | re.DOTALL,
)
INSEE_TITLE_MONTH_RE = re.compile(
    r"\b(janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre)\s+(\d{4})",
    re.IGNORECASE,
)

ISTAT_PROVV_RE = re.compile(
    r'href="((?:https://www\.istat\.it)?/comunicato-stampa/prezzi-al-consumo-dati-provvisori-([a-z]+)-(\d{4})/)"',
    re.IGNORECASE,
)
ISTAT_FINAL_RE = re.compile(
    r'href="(/comunicato-stampa/prezzi-al-consumo-([a-z]+)-(\d{4})/)"',
    re.IGNORECASE,
)
ISTAT_IPCA_ANNUAL_RE = re.compile(
    r"indice\s+armonizzato\s+dei\s+prezzi\s+al\s+consumo\s*\(IPCA\)[^%]*?"
    r"(-?\d+[,.]\d+)\s*%[^%]*?(-?\d+[,.]\d+)\s*%\s*su\s+base\s+annua",
    re.IGNORECASE | re.DOTALL,
)

INE_ES_PRESS_RE = re.compile(
    r'href="(/dyngs/Prensa/(?:es/)?adIPC(\d{2})(\d{2})\.htm)',
    re.IGNORECASE,
)
INE_ES_IPCA_RE = re.compile(
    r"variación\s+anual\s+del\s+indicador\s+adelantado\s+del\s+IPCA\s+es\s+del\s+(-?\d+,\d+)\s*%",
    re.IGNORECASE,
)

INE_PT_FLASH_HREF_RE = re.compile(
    r'DESTAQUESdest_boui=(\d+)[^>]*>\s*Taxa de variação homóloga do IPC terá',
    re.IGNORECASE,
)
INE_PT_ATTR_RE = re.compile(
    r'DESTAQUESdest_boui="([^"]+)"[^>]{0,40}>[\s\S]{0,800}?Estimativa\s+R[aá]pida',
    re.IGNORECASE,
)
INE_PT_IHPC_RE = re.compile(
    r"Índice\s+Harmonizado\s+de\s+Preços\s+no\s+Consumidor\s*\(IHPC\)[^%]*?"
    r"variação\s+homóloga\s+de\s+(-?\d+[,.]\d+)\s*%",
    re.IGNORECASE | re.DOTALL,
)
INE_PT_PERIOD_RE = re.compile(
    r"\b(janeiro|fevereiro|março|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\s+de\s+(\d{4})",
    re.IGNORECASE,
)

_GERMAN_MONTHS = {
    "januar": 1,
    "februar": 2,
    "märz": 3,
    "maerz": 3,
    "april": 4,
    "mai": 5,
    "juni": 6,
    "juli": 7,
    "august": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "dezember": 12,
}
_FRENCH_MONTHS = {
    "janvier": 1,
    "février": 2,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "août": 8,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "décembre": 12,
    "decembre": 12,
}
_ITALIAN_MONTHS = {
    "gennaio": 1,
    "febbraio": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6,
    "luglio": 7,
    "agosto": 8,
    "settembre": 9,
    "ottobre": 10,
    "novembre": 11,
    "dicembre": 12,
}
_PORTUGUESE_MONTHS = {
    "janeiro": 1,
    "fevereiro": 2,
    "março": 3,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}

_YOY_ABS_MAX = 30.0


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stamp_source_artifact(point: dict[str, Any], body: bytes) -> dict[str, Any]:
    """Fingerprint the bytes that were parsed into this point.

    The digest is the source document itself. It is not a hash of the merged
    point list and not another publisher's response body.
    """
    stamped = dict(point)
    stamped["raw_sha256"] = _sha256(body)
    return stamped


def _normalize_html_text(body: bytes) -> str:
    text = body.decode("utf-8", errors="replace")
    text = html.unescape(text)
    text = text.replace("\xa0", " ").replace("&nbsp;", " ")
    return text


def _parse_rate(raw: str) -> float | None:
    cleaned = raw.strip().replace(",", ".")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    if abs(value) >= _YOY_ABS_MAX:
        return None
    return value


def _period_from_ym(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def vintage_rank(row: dict[str, Any]) -> int:
    vintage = str(row.get("vintage") or "")
    if vintage == "eurostat_final":
        return 3
    if vintage == "national_final":
        return 2
    if vintage == "national_preliminary":
        return 1

    rev = str(row.get("revision_status") or "").lower()
    source = str(row.get("source_url") or "").lower()
    if rev == "final" and "eurostat" in source:
        return 3
    if rev in {"preliminary", "flash", "prelim"}:
        return 1
    if rev == "final":
        return 2
    return 0


def _collapse_national_by_period(national_points: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_period: dict[str, dict[str, Any]] = {}
    for point in national_points:
        period = str(point["period"])
        existing = by_period.get(period)
        if existing is None or vintage_rank(point) > vintage_rank(existing):
            by_period[period] = point
    return by_period


def reconcile_country_hicp_points(
    eurostat_points: list[dict[str, Any]],
    national_points: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """One point per period; Eurostat final wins over national for the same month."""
    national_by_period = _collapse_national_by_period(national_points)
    euro_by_period: dict[str, dict[str, Any]] = {}
    for point in eurostat_points:
        euro_by_period[str(point["period"])] = point

    periods = sorted(set(national_by_period) | set(euro_by_period))
    out: list[dict[str, Any]] = []
    for period in periods:
        euro = euro_by_period.get(period)
        national = national_by_period.get(period)
        if euro is not None:
            out.append(dict(euro))
        elif national is not None:
            out.append(dict(national))
    return out


def select_current_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the highest (vintage_rank, retrieved_at) row per period."""
    by_period: dict[str, dict[str, Any]] = {}
    for row in rows:
        period = str(row.get("period") or row.get("reference_period") or "")
        if not period:
            continue
        current = by_period.get(period)
        key = (vintage_rank(row), str(row.get("retrieved_at") or ""))
        if current is None:
            by_period[period] = row
            continue
        current_key = (vintage_rank(current), str(current.get("retrieved_at") or ""))
        if key > current_key:
            by_period[period] = row
    return [by_period[p] for p in sorted(by_period)]


def discover_destatis_press_url(listing_html: bytes) -> str | None:
    text = listing_html.decode("utf-8", errors="replace")
    best: tuple[int, int, int, str] | None = None
    for match in DESTATIS_PRESS_RE.finditer(text):
        href, year_s, month_s, _pd, release_s = match.groups()
        year, month, release = int(year_s), int(month_s), int(release_s)
        candidate = (year, month, release, href)
        if best is None or candidate[:3] > best[:3]:
            best = candidate
    if best is None:
        return None
    return _urljoin(DESTATIS_BASE, best[3])


def parse_destatis_hicp_press(body: bytes, source_url: str) -> dict[str, Any] | None:
    text = _normalize_html_text(body)
    if not text.strip().startswith("<") and "Harmonisierter" not in text:
        return None
    match = DESTATIS_HICP_RE.search(text)
    if not match:
        return None
    month_name, year_s, rate_s, status = match.groups()
    month = _GERMAN_MONTHS.get(month_name.lower())
    if month is None:
        return None
    value = _parse_rate(rate_s)
    if value is None:
        return None
    status_l = status.lower()
    if ("vorläufig" in status_l or "vorlaeufig" in status_l) and "bestätigt" not in status_l:
        vintage = "national_preliminary"
        revision = "preliminary"
    elif "bestätigt" in status_l or "bestaetigt" in status_l or "endgültig" in status_l:
        vintage = "national_final"
        revision = "final"
    else:
        vintage = "national_preliminary"
        revision = "preliminary"
    return {
        "period": _period_from_ym(int(year_s), month),
        "value": value,
        "transformation": "yoy_pct",
        "revision_status": revision,
        "source_url": source_url,
        "vintage": vintage,
        "publisher": "Destatis",
    }


def discover_insee_statistic_id(solr_json: bytes) -> str | None:
    try:
        payload = json.loads(solr_json.decode("utf-8"))
    except json.JSONDecodeError:
        return None
    docs = payload.get("documents") or payload.get("response", {}).get("docs") or []
    for doc in docs:
        title = str(doc.get("title") or doc.get("titre") or "")
        if "prix à la consommation" not in title.lower() and "prix a la consommation" not in title.lower():
            continue
        doc_id = doc.get("id") or doc.get("identifiant")
        if doc_id:
            return str(doc_id)
    return None


def parse_insee_bdm_sdmx(body: bytes, source_url: str) -> list[dict[str, Any]]:
    text = body.decode("utf-8", errors="replace")
    if "HICP" not in text.upper() and "harmonis" not in text.lower():
        return []
    if "011812232" not in text and "SERIES_BDM" not in text:
        return []
    periods = re.findall(r'TIME_PERIOD="([^"]+)"', text)
    values = re.findall(r'<Obs[^>]*OBS_VALUE="([^"]+)"', text)
    quals = re.findall(r"OBS_QUAL=\"([^\"]+)\"", text)
    if not periods or not values:
        return []
    out: list[dict[str, Any]] = []
    for idx, period in enumerate(periods):
        if idx >= len(values):
            break
        value = _parse_rate(values[idx])
        if value is None:
            continue
        qual = quals[idx] if idx < len(quals) else ""
        if str(qual).upper() == "DEF":
            vintage = "national_final"
            revision = "final"
        else:
            vintage = "national_preliminary"
            revision = "preliminary"
        out.append(
            {
                "period": period,
                "value": value,
                "transformation": "yoy_pct",
                "revision_status": revision,
                "source_url": source_url,
                "vintage": vintage,
                "publisher": "INSEE",
            }
        )
    return out


def parse_insee_press_page(body: bytes, source_url: str) -> dict[str, Any] | None:
    text = _normalize_html_text(body)
    if "Ensemble IPCH" not in text and "ensemble ipch" not in text.lower():
        return None
    row_match = INSEE_ENSEMBLE_ROW_RE.search(text)
    table_rate: float | None = None
    if row_match:
        cells = INSEE_NUMERIC_CELL_RE.findall(row_match.group(1))
        if cells:
            table_rate = _parse_rate(cells[-1])
    prose_match = INSEE_PROSE_HICP_RE.search(text)
    prose_rate: float | None = None
    if prose_match:
        prose_rate = _parse_rate(prose_match.group(1))
    if table_rate is None and prose_rate is None:
        return None
    if table_rate is not None and prose_rate is not None and abs(table_rate - prose_rate) > 0.05:
        return None
    value = table_rate if table_rate is not None else prose_rate
    if value is None:
        return None

    period = _insee_reference_period(text)
    if period is None:
        return None

    if _insee_release_is_final(text):
        vintage = "national_final"
        revision = "final"
    else:
        vintage = "national_preliminary"
        revision = "preliminary"

    return {
        "period": period,
        "value": value,
        "transformation": "yoy_pct",
        "revision_status": revision,
        "source_url": source_url,
        "vintage": vintage,
        "publisher": "INSEE",
    }


def _insee_heading_text(text: str) -> str:
    chunks: list[str] = []
    title = re.search(r"<title>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
    if title:
        chunks.append(re.sub(r"<[^>]+>", " ", title.group(1)))
    for match in re.finditer(
        r'<meta[^>]+(?:name="description"[^>]+content="([^"]*)"|content="([^"]*)"[^>]+name="description")',
        text,
        re.IGNORECASE,
    ):
        chunks.append(match.group(1) or match.group(2) or "")
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.IGNORECASE | re.DOTALL)
    if h1:
        chunks.append(re.sub(r"<[^>]+>", " ", h1.group(1)))
    return html.unescape(" ".join(chunks))


def _french_period(fragment: str) -> str | None:
    match = INSEE_TITLE_MONTH_RE.search(fragment)
    if not match:
        return None
    month = _FRENCH_MONTHS.get(match.group(1).lower())
    if month is None:
        return None
    return _period_from_ym(int(match.group(2)), month)


def _insee_reference_period(text: str) -> str | None:
    """Use the release title, not the first month name elsewhere on the page."""
    headed = _french_period(_insee_heading_text(text))
    if headed:
        return headed
    return _french_period(text)


def _insee_release_is_final(text: str) -> bool:
    """A flash page names the later definitive publication; that is not this vintage."""
    head = _insee_heading_text(text).lower()
    if re.search(r"provisoire|augmenteraient|augmenterait", head):
        return False
    if re.search(r"définitif|definitif", head):
        return True
    body = text.lower()
    body = re.sub(r"résultats?\s+définitifs?\s+seront\s+publiés", " ", body)
    body = re.sub(r"resultats?\s+definitifs?\s+seront\s+publies", " ", body)
    if "résultats définitifs" in body or "resultats definitifs" in body:
        return True
    return False


def discover_istat_provisional_url(listing_html: bytes) -> str | None:
    text = listing_html.decode("utf-8", errors="replace")
    best: tuple[int, int, str] | None = None
    for href, month_name, year_s in ISTAT_PROVV_RE.findall(text):
        month = _ITALIAN_MONTHS.get(month_name.lower())
        if month is None:
            continue
        candidate = (int(year_s), month, href)
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    if best is None:
        return None
    return _urljoin("https://www.istat.it", best[2])


def parse_istat_ipca_press(body: bytes, source_url: str, *, provisional: bool = True) -> dict[str, Any] | None:
    text = _normalize_html_text(body)
    match = ISTAT_IPCA_ANNUAL_RE.search(text)
    if not match:
        return None
    _monthly, annual_s = match.group(1), match.group(2)
    value = _parse_rate(annual_s)
    if value is None:
        return None
    slug_match = re.search(r"prezzi-al-consumo-dati-provvisori-([a-z]+)-(\d{4})", source_url, re.I)
    if not slug_match:
        slug_match = re.search(r"prezzi-al-consumo-([a-z]+)-(\d{4})", source_url, re.I)
    if not slug_match:
        return None
    month = _ITALIAN_MONTHS.get(slug_match.group(1).lower())
    if month is None:
        return None
    period = _period_from_ym(int(slug_match.group(2)), month)
    if provisional:
        vintage = "national_preliminary"
        revision = "preliminary"
    else:
        vintage = "national_final"
        revision = "final"
    return {
        "period": period,
        "value": value,
        "transformation": "yoy_pct",
        "revision_status": revision,
        "source_url": source_url,
        "vintage": vintage,
        "publisher": "Istat",
    }


def discover_ine_spain_press_url(listing_html: bytes) -> str | None:
    text = listing_html.decode("utf-8", errors="replace")
    best: tuple[int, int, str] | None = None
    for match in INE_ES_PRESS_RE.finditer(text):
        path, mm_s, yy_s = match.groups()
        mm, yy = int(mm_s), int(yy_s)
        year = 2000 + yy if yy < 100 else yy
        candidate = (year, mm, path)
        if best is None or (candidate[0], candidate[1]) > (best[0], best[1]):
            best = candidate
    if best is None:
        return None
    return "https://www.ine.es" + best[2]


def parse_ine_spain_ipca_press(body: bytes, source_url: str) -> dict[str, Any] | None:
    text = _normalize_html_text(body)
    match = INE_ES_IPCA_RE.search(text)
    if not match:
        return None
    value = _parse_rate(match.group(1))
    if value is None:
        return None
    url_match = re.search(r"adIPC(\d{2})(\d{2})\.htm", source_url, re.IGNORECASE)
    if not url_match:
        url_match = INE_ES_PRESS_RE.search(text)
    if not url_match:
        return None
    if url_match.lastindex and url_match.lastindex >= 3:
        mm, yy = int(url_match.group(2)), int(url_match.group(3))
    else:
        mm, yy = int(url_match.group(1)), int(url_match.group(2))
    year = 2000 + yy if yy < 100 else yy
    period = _period_from_ym(year, mm)
    return {
        "period": period,
        "value": value,
        "transformation": "yoy_pct",
        "revision_status": "preliminary",
        "source_url": source_url,
        "vintage": "national_preliminary",
        "publisher": "INE",
    }


def _portugal_period_in(fragment: str) -> str | None:
    found: list[tuple[int, int]] = []
    for month_name, year_s in INE_PT_PERIOD_RE.findall(fragment):
        month = _PORTUGUESE_MONTHS.get(month_name.lower())
        if month is None:
            continue
        found.append((int(year_s), month))
    if not found:
        return None
    year, month = found[-1]
    return _period_from_ym(year, month)


def _html_to_plain(fragment: str) -> str:
    plain = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", plain)


def _portugal_reference_period(text: str, ihpc_end: int) -> str | None:
    """Bind the month to the IHPC sentence or the flash headline, not an earlier dateline.

    The window is measured on text with tags removed. A raw character cap stops
    inside the markup between the flash title and "Setembro de 2026" and drops
    the print. The plain-text cap still ends before the later year-ago comparison.
    """
    near_rate = _portugal_period_in(_html_to_plain(text[ihpc_end : ihpc_end + 800])[:240])
    if near_rate:
        return near_rate
    for marker in ("Estimativa Rápida", "Estimativa Rapida", "terá", "tera"):
        start = text.lower().find(marker.lower())
        if start < 0:
            continue
        headed = _portugal_period_in(_html_to_plain(text[start : start + 4000])[:240])
        if headed:
            return headed
    return None


def discover_ine_portugal_flash_url(listing_html: bytes) -> str | None:
    text = html.unescape(listing_html.decode("utf-8", errors="replace"))
    match = INE_PT_FLASH_HREF_RE.search(text)
    if match is None:
        match = INE_PT_ATTR_RE.search(text)
    if not match:
        return None
    boui = match.group(1)
    return (
        "https://www.ine.pt/xportal/xmain?xpid=INE&xpgid=ine_destaques"
        f"&DESTAQUESdest_boui={boui}&DESTAQUEStema=5414296&DESTAQUESmodo=2&xlang=pt"
    )


def parse_ine_portugal_ihpc_press(body: bytes, source_url: str) -> dict[str, Any] | None:
    text = _normalize_html_text(body)
    match = INE_PT_IHPC_RE.search(text)
    if not match:
        return None
    value = _parse_rate(match.group(1))
    if value is None:
        return None
    period = _portugal_reference_period(text, match.end())
    if period is None:
        return None
    lower = text.lower()
    if "terá" in lower or "tera" in lower:
        vintage = "national_preliminary"
        revision = "preliminary"
    else:
        vintage = "national_final"
        revision = "final"
    return {
        "period": period,
        "value": value,
        "transformation": "yoy_pct",
        "revision_status": revision,
        "source_url": source_url,
        "vintage": vintage,
        "publisher": "Statistics Portugal",
    }


def _post_json(
    opener: Callable[..., dict[str, Any]],
    url: str,
    data: bytes,
    *,
    timeout: float,
) -> dict[str, Any]:
    """POST through the ingestion opener. Openers that cannot POST fail closed."""
    try:
        return opener(url, timeout=timeout, data=data)
    except TypeError:
        return {
            "ok": False,
            "url": url,
            "http_status": None,
            "body": b"",
            "error": "opener_does_not_accept_post",
        }


def _fetch_url(opener: Callable[..., dict[str, Any]], url: str, *, timeout: float) -> dict[str, Any]:
    return opener(url, timeout=timeout)


def fetch_national_hicp_points(
    geo: str,
    *,
    opener: Callable[..., dict[str, Any]],
    timeout: float,
    _attempt: int = 0,
) -> tuple[list[dict[str, Any]], str | None]:
    geo = geo.upper()
    points: list[dict[str, Any]] = []
    errors: list[str] = []

    if geo == "DE":
        listing = _fetch_url(opener, NATIONAL_LISTING_URLS["DE"], timeout=timeout)
        if listing.get("ok") and listing.get("body"):
            press_url = discover_destatis_press_url(listing["body"])
            if press_url:
                press = _fetch_url(opener, press_url, timeout=timeout)
                if press.get("ok") and press.get("body"):
                    row = parse_destatis_hicp_press(press["body"], press_url)
                    if row:
                        points.append(stamp_source_artifact(row, press["body"]))
        if not points:
            errors.append("de_national_unavailable")

    elif geo == "FR":
        solr_url = NATIONAL_LISTING_URLS["FR"]
        solr = {"ok": False, "body": b"", "error": "not_attempted"}
        for _solr_try in range(3):
            solr = _post_json(opener, solr_url, INSEE_SOLR_BODY, timeout=timeout)
            if solr.get("ok") and solr.get("body"):
                break
        if not solr.get("ok"):
            solr = _fetch_url(opener, solr_url, timeout=timeout)
        if solr.get("ok") and solr.get("body"):
            doc_id = discover_insee_statistic_id(solr["body"])
            if doc_id:
                page_url = f"https://www.insee.fr/fr/statistiques/{doc_id}"
                page = _fetch_url(opener, page_url, timeout=timeout)
                if page.get("ok") and page.get("body"):
                    row = parse_insee_press_page(page["body"], page_url)
                    if row:
                        points.append(stamp_source_artifact(row, page["body"]))
        bdm = _fetch_url(opener, INSEE_BDM_URL, timeout=timeout)
        if bdm.get("ok") and bdm.get("body"):
            points.extend(
                stamp_source_artifact(row, bdm["body"])
                for row in parse_insee_bdm_sdmx(bdm["body"], INSEE_BDM_URL)
            )
        if not points:
            errors.append("fr_national_unavailable")

    elif geo == "IT":
        listing = _fetch_url(opener, NATIONAL_LISTING_URLS["IT"], timeout=timeout)
        if listing.get("ok") and listing.get("body"):
            press_url = discover_istat_provisional_url(listing["body"])
            if press_url:
                press = _fetch_url(opener, press_url, timeout=timeout)
                if press.get("ok") and press.get("body"):
                    row = parse_istat_ipca_press(press["body"], press_url, provisional=True)
                    if row:
                        points.append(stamp_source_artifact(row, press["body"]))
        if not points:
            errors.append("it_national_unavailable")

    elif geo == "ES":
        listing = _fetch_url(opener, NATIONAL_LISTING_URLS["ES"], timeout=timeout)
        if listing.get("ok") and listing.get("body"):
            press_url = discover_ine_spain_press_url(listing["body"])
            if press_url:
                press = _fetch_url(opener, press_url, timeout=timeout)
                if press.get("ok") and press.get("body"):
                    row = parse_ine_spain_ipca_press(press["body"], press_url)
                    if row:
                        points.append(stamp_source_artifact(row, press["body"]))
        if not points:
            errors.append("es_national_unavailable")

    elif geo == "PT":
        listing = _fetch_url(opener, NATIONAL_LISTING_URLS["PT"], timeout=timeout)
        if listing.get("ok") and listing.get("body"):
            press_url = discover_ine_portugal_flash_url(listing["body"])
            if press_url:
                press = _fetch_url(opener, press_url, timeout=timeout)
                if press.get("ok") and press.get("body"):
                    row = parse_ine_portugal_ihpc_press(press["body"], press_url)
                    if row:
                        points.append(stamp_source_artifact(row, press["body"]))
        if not points:
            errors.append("pt_national_unavailable")

    else:
        errors.append(f"unsupported_geo:{geo}")

    if not points and errors and _attempt < 1:
        return fetch_national_hicp_points(
            geo, opener=opener, timeout=timeout, _attempt=_attempt + 1
        )
    err = ";".join(errors) if errors and not points else None
    return points, err


def _rows_for_period(
    store: dict[str, Any], series_id: str, period: str, transformation: str
) -> list[dict[str, Any]]:
    return [
        row
        for row in store.get("observations", [])
        if row.get("series_id") == series_id
        and row.get("period") == period
        and row.get("transformation", "") == transformation
    ]


def _winning_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return max(rows, key=lambda r: (vintage_rank(r), str(r.get("retrieved_at") or "")))


@dataclass
class RankedAppendResult:
    appended: bool
    duplicate: bool
    upgraded: bool
    observation: dict[str, Any] | None = None
    provenance_updated: bool = False


def _claim_artifact_sha(row: dict[str, Any], raw_sha256: str) -> bool:
    """Make raw_sha256 the artifact that produced this row's current vintage."""
    previous = str(row.get("raw_sha256") or "")
    if not raw_sha256 or previous == raw_sha256:
        return False
    row["raw_sha256"] = raw_sha256
    if previous:
        _record_sha_alias(row, previous)
    return True


def artifact_sha_belongs_to_other_source(store: dict[str, Any], row: dict[str, Any]) -> bool:
    """True when this row's digest is the fingerprint of a different source URL.

    A shared Eurostat payload hash copied onto a national print matches this.
    A tie between sources does not, so a later byte-identical re-fetch is left
    on the original artifact.
    """
    sha = str(row.get("raw_sha256") or "")
    source = str(row.get("source_url") or "")
    if not sha or not source:
        return False
    counts: dict[str, int] = {}
    for other in store.get("observations", []):
        if str(other.get("raw_sha256") or "") != sha:
            continue
        key = str(other.get("source_url") or "")
        counts[key] = counts.get(key, 0) + 1
    if source not in counts:
        return False
    best = max(counts.values())
    leaders = [url for url, count in counts.items() if count == best]
    if len(leaders) != 1:
        return False
    return leaders[0] != source


def append_ranked_country_hicp(
    store: dict[str, Any],
    *,
    series_id: str,
    period: str,
    transformation: str,
    value: float,
    raw_sha256: str,
    retrieved_at: str,
    release_date: str | None = None,
    vintage: str | None = None,
    revision_status: str | None = None,
    source_url: str | None = None,
    prior: float | None = None,
    units: str | None = None,
    derivation: dict[str, Any] | None = None,
) -> RankedAppendResult:
    incoming_rank = vintage_rank(
        {
            "vintage": vintage,
            "revision_status": revision_status,
            "source_url": source_url,
        }
    )
    period_rows = _rows_for_period(store, series_id, period, transformation)
    winner = _winning_row(period_rows)
    winner_rank = vintage_rank(winner) if winner is not None else -1

    if winner is not None and incoming_rank < winner_rank:
        if values_close(float(winner["value"]), value):
            _record_sha_alias(winner, raw_sha256)
        return RankedAppendResult(appended=False, duplicate=True, upgraded=False, observation=winner)

    if winner is not None and incoming_rank == winner_rank and values_close(float(winner["value"]), value):
        same_source = str(winner.get("source_url") or "") == str(source_url or "")
        if same_source and artifact_sha_belongs_to_other_source(store, winner):
            claimed = _claim_artifact_sha(winner, raw_sha256)
            return RankedAppendResult(
                appended=False,
                duplicate=True,
                upgraded=False,
                provenance_updated=claimed,
                observation=winner,
            )
        _record_sha_alias(winner, raw_sha256)
        return RankedAppendResult(appended=False, duplicate=True, upgraded=False, observation=winner)

    if winner is not None and incoming_rank > winner_rank and values_close(float(winner["value"]), value):
        deriv = dict(winner.get("derivation") or {})
        deriv["superseded_vintage"] = winner.get("vintage")
        deriv["superseded_source_url"] = winner.get("source_url")
        deriv["superseded_value"] = winner.get("value")
        if derivation:
            deriv.update(derivation)
        if derivation and derivation.get("publisher"):
            deriv["publisher"] = derivation["publisher"]
        elif derivation is None and winner.get("derivation", {}).get("publisher"):
            deriv["publisher"] = winner["derivation"]["publisher"]

        winner["vintage"] = vintage
        winner["revision_status"] = revision_status
        winner["source_url"] = source_url
        winner["release_date"] = release_date
        winner["latest_release_vintage"] = release_date
        winner["retrieved_at"] = retrieved_at
        winner["derivation"] = deriv
        claimed = _claim_artifact_sha(winner, raw_sha256)
        return RankedAppendResult(
            appended=False,
            duplicate=False,
            upgraded=True,
            provenance_updated=claimed,
            observation=winner,
        )

    row = {
        "series_id": series_id,
        "period": period,
        "transformation": transformation,
        "value": value,
        "raw_sha256": raw_sha256,
        "retrieved_at": retrieved_at,
        "release_date": release_date,
        "vintage": vintage,
        "earliest_release_vintage": release_date,
        "latest_release_vintage": release_date,
        "revision_status": revision_status,
        "source_url": source_url,
        "prior": prior,
    }
    if units is not None:
        row["units"] = units
    deriv_out: dict[str, Any] = dict(derivation or {})
    if derivation and derivation.get("publisher"):
        deriv_out["publisher"] = derivation["publisher"]
    if deriv_out:
        row["derivation"] = deriv_out
    store.setdefault("observations", []).append(row)
    return RankedAppendResult(appended=True, duplicate=False, upgraded=False, observation=row)
