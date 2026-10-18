"""NRCan monthly fuel price HTML acquisition."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from scripts.canadian_cpi_release.contract import NRCAN_PAGES, Observation, SERIES_BY_ID
from scripts.canadian_cpi_release.sources.cache import SourceError
from scripts.canadian_cpi_release.sources.cache import fetch_bytes

ROW_RE = re.compile(
    r"<td[^>]*>\s*(\d{4}-\d{2})\s*</td>\s*<td[^>]*>\s*([\d.]+)\s*</td>",
    re.IGNORECASE,
)

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
