"""NRCan monthly fuel price HTML acquisition."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Iterable
from urllib.error import URLError

from scripts.canadian_cpi_release.contract import NRCAN_PAGES, Observation, SERIES_BY_ID
from scripts.canadian_cpi_release.sources.cache import SourceError
from scripts.canadian_cpi_release.sources.cache import fetch_bytes

ROW_RE = re.compile(
    r"<td[^>]*>\s*(\d{4}-\d{2})\s*</td>\s*<td[^>]*>\s*([\d.]+)\s*</td>",
    re.IGNORECASE,
)

NRCAN_WEEKLY_URL_TEMPLATE = (
    "https://www2.nrcan.gc.ca/eneene/sources/pripri/prices_bycity_e.cfm"
    "?productID={product_id}&locationID=66&frequency=W&priceYear={year}&Redisplay="
)
NRCAN_WEEKLY_PRODUCTS: dict[str, int] = {
    "gasoline_regular": 1,
    "diesel": 5,
}
NRCAN_WEEKLY_CAPTION_NEEDLES: dict[str, tuple[str, ...]] = {
    "gasoline_regular": ("Regular Gasoline", "Weekly"),
    "diesel": ("Diesel", "Weekly"),
}

_WEEKLY_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_WEEKLY_TD_RE = re.compile(r"<td([^>]*)>(.*?)</td>", re.IGNORECASE | re.DOTALL)
_WEEKLY_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_WEEKLY_CAPTION_RE = re.compile(
    r"<caption[^>]*>\s*(.*?)\s*</caption>",
    re.IGNORECASE | re.DOTALL,
)
_WEEKLY_HEADING_RE = re.compile(
    r"<h[12][^>]*>\s*(.*?)\s*</h[12]>",
    re.IGNORECASE | re.DOTALL,
)
_WEEKLY_META_MODIFIED_RE = re.compile(
    r'name="dcterms\.modified"[^>]*content="([^"]+)"',
    re.IGNORECASE,
)

_WEEKLY_COL_HEADERS = {
    "week_ending": "headerDate",
    "price_cpl": "header4_1_1",
    "taxes_cpl": "header5_1_2",
    "marketing_margin_cpl": "header6_1_3",
    "refining_margin_cpl": "header7_1_4",
}

REQUIRED_START = "2016-07"
DEFAULT_THROUGH = "2026-09"


@dataclass
class NrcanRawPage:
    canonical_id: str
    year: int
    url: str
    body: bytes

    @property
    def filename(self) -> str:
        return f"nrcan_{self.canonical_id}_{self.year}.html"

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()


def _weekly_header_tokens(attrs: str) -> set[str]:
    headers_match = re.search(r'\bheaders="([^"]*)"', attrs, re.IGNORECASE)
    if not headers_match:
        return set()
    return {token.strip() for token in headers_match.group(1).split() if token.strip()}


def _weekly_cell_text(inner: str) -> str:
    return re.sub(r"<[^>]+>", "", inner, flags=re.IGNORECASE).strip()


def _optional_weekly_float(text: str) -> float | None:
    text = text.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _extract_weekly_caption(html: str) -> str | None:
    for pattern in (_WEEKLY_CAPTION_RE, _WEEKLY_HEADING_RE):
        match = pattern.search(html)
        if match:
            return re.sub(r"\s+", " ", _weekly_cell_text(match.group(1))).strip()
    return None


def _caption_matches_product(caption: str | None, series_key: str) -> bool:
    if not caption:
        return False
    caption_lower = caption.casefold()
    for needle in NRCAN_WEEKLY_CAPTION_NEEDLES[series_key]:
        if needle.casefold() not in caption_lower:
            return False
    return True


def parse_nrcan_weekly_table(html: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for tr_match in _WEEKLY_TR_RE.finditer(html):
        row_html = tr_match.group(1)
        cells: dict[str, str] = {}
        for td_match in _WEEKLY_TD_RE.finditer(row_html):
            attrs, inner = td_match.group(1), td_match.group(2)
            headers = _weekly_header_tokens(attrs)
            if not headers:
                continue
            text = _weekly_cell_text(inner)
            for field, header_id in _WEEKLY_COL_HEADERS.items():
                if header_id in headers:
                    cells[field] = text
        week_ending = cells.get("week_ending")
        if not week_ending or not _WEEKLY_DATE_RE.fullmatch(week_ending):
            continue
        price = _optional_weekly_float(cells.get("price_cpl", ""))
        if price is None:
            continue
        rows.append(
            {
                "week_ending": week_ending,
                "price_cpl": price,
                "taxes_cpl": _optional_weekly_float(cells.get("taxes_cpl", "")),
                "marketing_margin_cpl": _optional_weekly_float(cells.get("marketing_margin_cpl", "")),
                "refining_margin_cpl": _optional_weekly_float(cells.get("refining_margin_cpl", "")),
            }
        )
    return rows


def weekly_rows_in_month(rows: list[dict[str, Any]], period: str) -> list[dict[str, Any]]:
    """Return weekly observations whose week_ending falls in YYYY-MM."""
    if len(period) != 7 or period[4] != "-":
        return []
    return [row for row in rows if str(row.get("week_ending", "")).startswith(f"{period}-")]


def _weekly_page_published_at(html: str) -> str | None:
    match = _WEEKLY_META_MODIFIED_RE.search(html)
    if not match:
        return None
    value = match.group(1).strip()
    # Static GCWeb template metadata (often years stale), not a per-table publish time.
    if len(value) == 10 and value[4] == "-" and int(value[:4]) < 2020:
        return None
    return value


def collect_nrcan_weekly(
    *,
    as_of: date,
    opener: Callable[..., Any],
    retrieved_at: str,
    weeks: int = 13,
) -> dict[str, Any]:
    publication_note = (
        "Fuel Focus weekly Canada retail tables advance once per week after the stated "
        "week-ending date (week endings observed as Tuesdays). The HTML exposes only stale "
        "GCWeb template dcterms.modified metadata, not a reliable per-table publish timestamp."
    )
    notes: list[str] = []
    series_out: dict[str, Any] = {}
    page_published_at: str | None = None
    dropped_future = 0

    for series_key, product_id in NRCAN_WEEKLY_PRODUCTS.items():
        caption: str | None = None
        fetched: list[tuple[str, bytes]] = []
        try:
            combined_rows: list[dict[str, Any]] = []
            for year in (as_of.year, as_of.year - 1):
                url = NRCAN_WEEKLY_URL_TEMPLATE.format(product_id=product_id, year=year)
                try:
                    body = fetch_bytes(opener, url, data=None, content_type=None)
                except (URLError, OSError, SourceError) as exc:
                    if year == as_of.year:
                        raise
                    break
                fetched.append((url, body))
                html = body.decode("utf-8", errors="replace")
                if caption is None:
                    caption = _extract_weekly_caption(html)
                page_published_at = page_published_at or _weekly_page_published_at(html)
                combined_rows.extend(parse_nrcan_weekly_table(html))
                eligible_weeks = {
                    row["week_ending"]
                    for row in combined_rows
                    if date.fromisoformat(row["week_ending"]) <= as_of
                }
                if year == as_of.year and len(eligible_weeks) >= weeks:
                    break

            by_week: dict[str, dict[str, Any]] = {}
            for row in combined_rows:
                week = row["week_ending"]
                week_d = date.fromisoformat(week)
                if week_d > as_of:
                    dropped_future += 1
                    continue
                by_week[week] = row
            observations = [by_week[k] for k in sorted(by_week)]
            if len(observations) > weeks:
                observations = observations[-weeks:]

            if not _caption_matches_product(caption, series_key):
                series_out[series_key] = {
                    "status": "unavailable",
                    "reason": "caption_mismatch",
                    "product_id": product_id,
                    "caption": caption,
                    "observations": observations,
                    "latest": observations[-1] if observations else None,
                    "source_sha256": hashlib.sha256(b"".join(b for _, b in fetched)).hexdigest(),
                    "source_urls": [url for url, _ in fetched],
                }
                notes.append(f"{series_key}: caption did not match expected weekly product text ({caption!r}).")
                continue

            if not observations:
                series_out[series_key] = {
                    "status": "unavailable",
                    "reason": "no_observations",
                    "product_id": product_id,
                    "caption": caption,
                    "observations": [],
                    "latest": None,
                    "source_sha256": hashlib.sha256(b"".join(b for _, b in fetched)).hexdigest(),
                    "source_urls": [url for url, _ in fetched],
                }
                notes.append(f"{series_key}: no weekly rows on/before as_of {as_of.isoformat()}.")
                continue

            series_out[series_key] = {
                "status": "ok",
                "product_id": product_id,
                "caption": caption,
                "observations": observations,
                "latest": {
                    "week_ending": observations[-1]["week_ending"],
                    "price_cpl": observations[-1]["price_cpl"],
                },
                "source_sha256": hashlib.sha256(b"".join(b for _, b in fetched)).hexdigest(),
                "source_urls": [url for url, _ in fetched],
            }
        except (URLError, OSError, SourceError, ValueError, KeyError) as exc:
            detail = getattr(exc, "detail", None) or str(exc)
            code = getattr(exc, "code", type(exc).__name__)
            parse_reason = f"{code}: {detail}"
            series_out[series_key] = {
                "status": "unavailable",
                "reason": parse_reason,
                "product_id": product_id,
                "caption": caption,
                "observations": [],
                "latest": None,
                "source_sha256": hashlib.sha256(b"").hexdigest(),
                "source_urls": [url for url, _ in fetched],
            }
            notes.append(f"{series_key}: fetch/parse failed ({parse_reason}).")

    if dropped_future:
        notes.append(
            f"Dropped {dropped_future} weekly row(s) with week_ending after as_of {as_of.isoformat()}."
        )

    ok_count = sum(1 for row in series_out.values() if row.get("status") == "ok")
    if ok_count == 2:
        block_status = "ok"
    elif ok_count == 1:
        block_status = "partial"
    else:
        block_status = "unavailable"

    return {
        "status": block_status,
        "frequency": "weekly",
        "geography": "Canada",
        "location_id": 66,
        "units": "cents_per_litre_incl_taxes",
        "source": "Natural Resources Canada, Fuel Focus weekly average retail prices",
        "source_url_template": NRCAN_WEEKLY_URL_TEMPLATE,
        "retrieved_at": retrieved_at,
        "published_at": page_published_at,
        "publication_note": publication_note,
        "series": series_out,
        "notes": notes,
    }


def parse_nrcan_monthly_table(html: str) -> dict[str, float]:
    rows: dict[str, float] = {}
    for match in ROW_RE.finditer(html):
        period, value_text = match.group(1), match.group(2)
        try:
            rows[period] = float(value_text)
        except ValueError:
            continue
    return rows


def _page_hash_for_period(period: str, pages: list[NrcanRawPage], canonical_id: str) -> str:
    year = int(period[:4])
    for page in pages:
        if page.canonical_id == canonical_id and page.year == year:
            return page.sha256
    return hashlib.sha256(b"").hexdigest()


def periods_after(periods: Iterable[str], through_period: str) -> list[str]:
    """Months strictly after the requested through period. YYYY-MM compares in order."""
    return sorted(period for period in periods if period > through_period)


def _missing_months(covered: set[str], through_period: str) -> list[str]:
    year, month = 2016, 7
    end_year, end_month = int(through_period[:4]), int(through_period[5:7])
    missing: list[str] = []
    while (year, month) <= (end_year, end_month):
        period = f"{year:04d}-{month:02d}"
        if period not in covered:
            missing.append(period)
        month += 1
        if month > 12:
            month = 1
            year += 1
    return missing


def collect_nrcan(
    *,
    opener: Callable[..., Any],
    sleeper: Callable[[float], None] | None,
    retrieved_at: str,
    through_period: str = DEFAULT_THROUGH,
    require_full_history: bool = False,
) -> tuple[list[Observation], list[NrcanRawPage], list[str]]:
    notes: list[str] = []
    observations: list[Observation] = []
    raw_pages: list[NrcanRawPage] = []
    if len(through_period) != 7 or through_period[4] != "-":
        raise SourceError("nrcan_bad_through_period", through_period)
    end_year = int(through_period[:4])
    years = list(range(2016, end_year + 1))

    for canonical_id in ("nrcan_gasoline", "nrcan_furnace_oil"):
        spec = SERIES_BY_ID[canonical_id]
        page_cfg = NRCAN_PAGES[canonical_id]
        combined: dict[str, float] = {}
        for year in years:
            url = str(page_cfg["url_template"]).format(year=year)
            body = fetch_bytes(opener, url, data=None, content_type=None, sleeper=sleeper)
            page = NrcanRawPage(canonical_id=canonical_id, year=year, url=url, body=body)
            raw_pages.append(page)
            parsed = parse_nrcan_monthly_table(body.decode("utf-8", errors="replace"))
            for period, value in parsed.items():
                combined[period] = value

        if through_period not in combined:
            raise SourceError(
                "nrcan_missing_target_month",
                f"{canonical_id} has no official monthly price for {through_period}",
            )
        missing = _missing_months(set(combined), through_period)
        if missing:
            if require_full_history:
                raise SourceError("nrcan_incomplete_history", f"{canonical_id} missing {missing[0]}")
            notes.append(
                f"{canonical_id}: official NRCan monthly Canada table missing {len(missing)} month(s) "
                f"in 2016-07..{through_period} (first gap {missing[0]}). "
                "Available rows are kept; training drops incomplete bridge months. "
                "This is not a substituted research value."
            )

        future = periods_after(combined, through_period)
        if future:
            shown = future[0]
            notes.append(
                f"{canonical_id}: {len(future)} monthly row(s) after requested through period "
                f"{through_period} were retained in the source archive and are not eligible as "
                f"the target-month input (first {shown}={combined[shown]}). "
                "The forecast gates them by release month and as_of."
            )

        for period, value in sorted(combined.items()):
            observations.append(
                Observation(
                    canonical_id=canonical_id,
                    period=period,
                    value=value,
                    published_at=None,
                    retrieved_at=retrieved_at,
                    source_hash=_page_hash_for_period(period, raw_pages, canonical_id),
                    units=spec.units,
                    seasonal_status=spec.seasonal_status,
                    source_url=NRCAN_PAGES[canonical_id]["url_template"],
                    vector_id=None,
                    table_pid=None,
                )
            )

    notes.append(
        "NRCan fuel prices: historical posting timestamps are not archived; a completed reference "
        "month is treated as eligible once that month has ended and as_of is on or after month-end."
    )
    return observations, raw_pages, notes
