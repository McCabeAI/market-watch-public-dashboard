"""United States official economic release schedule adapter (fixture-driven parsing)."""

from __future__ import annotations

import html as html_lib
import re
from datetime import date, datetime
from typing import Mapping

from scripts.dashboard_repair.release_contract import (
    EconomicReleaseEvent,
    SourceDocument,
    validate_events,
    validate_source_plan,
)

TZ_NY = "America/New_York"

_US_REPS_URL = "https://www.census.gov/retail/marts/www/martsdates.pdf"

_MONTH_ABBREV = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_FULL_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

_EMPSIT_SERIES = (
    "US.Labor.payrolls",
    "US.Labor.unemployment",
    "US.Labor.wages",
    "US.Labor.participation",
)
_CPI_SERIES = ("US.Inflation.cpi_headline", "US.Inflation.cpi_core")
_PPI_SERIES = ("US.Inflation.ppi_final_demand",)
_JOLTS_SERIES = (
    "US.Labor.jolts_openings",
    "US.Labor.jolts_openings_rate",
    "US.Labor.jolts_hires",
    "US.Labor.jolts_hires_rate",
    "US.Labor.jolts_quits",
    "US.Labor.jolts_quits_rate",
    "US.Labor.jolts_layoffs",
    "US.Labor.jolts_layoffs_rate",
)
_GDP_SERIES = ("US.Activity.gdp_domestic_demand", "US.Activity.gdp_level")
_PCE_SERIES = (
    "US.Inflation.core_pce",
    "US.Inflation.pce_headline",
    "US.Consumer.income",
    "US.Consumer.spending",
)
_RETAIL_SERIES = ("US.Consumer.retail",)

# Standing ISM clock from publisher text (same document as the day-of-month table).
_ISM_STANDING_TIME = "10:00"

_GAPS: tuple[str, ...] = (
    "Chicago Fed national economic activity and related releases are parsed by official_schedule, not us.py.",
    "us_retail: Census Advance Monthly Retail (martsdates.pdf) trimmed excerpt contains only "
    "2023/2024 scheduled dates; no post-now future release date is printed for parsing.",
    "bls_jolts: Official BLS JOLTS schedule table (snapshot 2026-11-06) lists only October 2026 "
    "(release Dec 1, 2026); no November 2026-or-later reference month row appears yet.",
)


def _ym_from_reference_month_label(label: str) -> str | None:
    label = label.strip()
    m = re.match(
        r"^(?P<mon>January|February|March|April|May|June|July|August|September|October|November|December)\s+(?P<y>\d{4})\s*$",
        label,
        re.I,
    )
    if not m:
        return None
    mon = _FULL_MONTHS[m.group("mon").lower()]
    y = int(m.group("y"))
    return f"{y:04d}-{mon:02d}"


def _parse_release_date_cell(cell: str) -> date | None:
    cell = re.sub(r"\s+", " ", cell.strip())
    # e.g. "Nov. 06, 2026" or "December 1, 2026"
    m = re.match(
        r"^(?P<ma>[A-Za-z]+)\.?\s+(?P<d>\d{1,2}),\s+(?P<y>\d{4})$",
        cell,
    )
    if not m:
        return None
    ma = m.group("ma").lower().rstrip(".")
    month = _MONTH_ABBREV.get(ma[:3]) or _FULL_MONTHS.get(ma)
    if month is None:
        return None
    return date(int(m.group("y")), month, int(m.group("d")))


def _parse_time_cell(cell: str) -> str | None:
    cell = cell.strip()
    m = re.match(r"^(\d{1,2}):(\d{2})\s*(AM|PM)\s*$", cell, re.I)
    if not m:
        return None
    h, mm, ap = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if ap == "PM" and h != 12:
        h += 12
    if ap == "AM" and h == 12:
        h = 0
    return f"{h:02d}:{mm:02d}"


def _parse_bls_markdown_table(body: str) -> list[tuple[str, date, str]]:
    """Parse BLS schedule pages rendered as markdown pipe tables."""
    rows: list[tuple[str, date, str]] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        parts = [p.strip() for p in line.split("|")]
        # leading/trailing empty from split
        inner = [p for p in parts if p]
        if len(inner) < 3:
            continue
        ref_month, rel_cell, time_cell = inner[0], inner[1], inner[2]
        if re.match(r"^reference\s+month", ref_month, re.I):
            continue
        if "---" in ref_month:
            continue
        ref_key = ref_month.strip()
        rel_date = _parse_release_date_cell(rel_cell)
        t = _parse_time_cell(time_cell)
        if rel_date is None or t is None:
            continue
        rows.append((ref_key, rel_date, t))
    return rows


def _ym_order(ym: str) -> tuple[int, int]:
    y, m = ym.split("-", 1)
    return int(y), int(m)


def _ref_month_in_range(ref_label: str, start: str, end: str) -> bool:
    ym = _ym_from_reference_month_label(ref_label)
    if ym is None:
        return False
    return _ym_order(start) <= _ym_order(ym) <= _ym_order(end)


def _parse_bea_schedule(html_body: str, *, source_url: str, fetched_at: str) -> list[EconomicReleaseEvent]:
    """Parse BEA Drupal schedule table for GDP/PCE rows (skips experimental/outdoor rows)."""
    events: list[EconomicReleaseEvent] = []
    for block in re.finditer(
        r'<tr class="scheduled-releases-type-press"[^>]*>(.*?)</tr>',
        html_body,
        flags=re.I | re.DOTALL,
    ):
        row_html = block.group(1)
        dm = re.search(
            r'<div class="release-date">\s*([^<]+)</div>',
            row_html,
            re.I,
        )
        tm = re.search(
            r'<small class="text-muted">\s*([^<]+)</small>',
            row_html,
            re.I,
        )
        tit = re.search(
            r'headers="view-field-scheduled-release-subject-table-column"[^>]*>\s*([^<]+)',
            row_html,
            re.I,
        )
        if not (dm and tm and tit):
            continue
        date_token = html_lib.unescape(dm.group(1)).strip()
        time_token = html_lib.unescape(tm.group(1)).strip()
        title = html_lib.unescape(tit.group(1)).strip()
        tl = title.lower()
        if "experimental" in tl or "outdoor recreation" in tl:
            continue
        local_date = _parse_bea_month_day(date_token, year=2026)
        lt = _parse_time_cell(time_token)
        if local_date is None or lt is None:
            continue
        provenance = f"{local_date.isoformat()} {time_token} — {title}"

        if "gdp (second estimate)" in tl and "3rd quarter 2026" in tl:
            events.append(
                EconomicReleaseEvent(
                    event_family="us_gdp",
                    country="US",
                    title="GDP (Second Estimate) and Corporate Profits, 3rd Quarter 2026",
                    publisher="U.S. Bureau of Economic Analysis",
                    local_date=local_date,
                    local_time=lt,
                    timezone=TZ_NY,
                    reference_period="2026-Q3",
                    source_url=source_url,
                    fetched_at=fetched_at,
                    status="verified",
                    series_ids=_GDP_SERIES,
                    provenance=provenance,
                )
            )
        elif "gdp (third estimate)" in tl and "3rd quarter 2026" in tl:
            events.append(
                EconomicReleaseEvent(
                    event_family="us_gdp",
                    country="US",
                    title="GDP (Third Estimate), Industries, Corporate Profits, State GDP, and State Personal Income, 3rd Quarter 2026",
                    publisher="U.S. Bureau of Economic Analysis",
                    local_date=local_date,
                    local_time=lt,
                    timezone=TZ_NY,
                    reference_period="2026-Q3",
                    source_url=source_url,
                    fetched_at=fetched_at,
                    status="verified",
                    series_ids=_GDP_SERIES,
                    provenance=provenance,
                )
            )
        elif title == "Personal Income and Outlays, October 2026":
            events.append(
                EconomicReleaseEvent(
                    event_family="us_pce",
                    country="US",
                    title="Personal Income and Outlays, October 2026",
                    publisher="U.S. Bureau of Economic Analysis",
                    local_date=local_date,
                    local_time=lt,
                    timezone=TZ_NY,
                    reference_period="2026-10",
                    source_url=source_url,
                    fetched_at=fetched_at,
                    status="verified",
                    series_ids=_PCE_SERIES,
                    provenance=provenance,
                )
            )
        elif title == "Personal Income and Outlays, November 2026":
            events.append(
                EconomicReleaseEvent(
                    event_family="us_pce",
                    country="US",
                    title="Personal Income and Outlays, November 2026",
                    publisher="U.S. Bureau of Economic Analysis",
                    local_date=local_date,
                    local_time=lt,
                    timezone=TZ_NY,
                    reference_period="2026-11",
                    source_url=source_url,
                    fetched_at=fetched_at,
                    status="verified",
                    series_ids=_PCE_SERIES,
                    provenance=provenance,
                )
            )
    return events


def _parse_bea_month_day(token: str, *, year: int) -> date | None:
    token = re.sub(r"\s+", " ", token.strip())
    m = re.match(r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})$", token, re.I)
    if not m:
        return None
    mon = _FULL_MONTHS[m.group(1).lower()]
    day = int(m.group(2))
    return date(year, mon, day)


def _parse_fomc(html_body: str, *, source_url: str, fetched_at: str) -> list[EconomicReleaseEvent]:
    """Emit December 8–9, 2026 meeting on the second day; clock only if printed next to the row."""
    # Scope to 2026 meeting list: content between 2026 header and 2025 header.
    m_year = re.search(
        r'<h4><a id="42828">\s*2026 FOMC Meetings\s*</a></h4>(.*?)(?=<h4><a id="42827">\s*2025 FOMC Meetings)',
        html_body,
        flags=re.I | re.DOTALL,
    )
    if not m_year:
        return []
    chunk = m_year.group(1)
    dec = re.search(
        r'<div class="fomc-meeting[^"]*__month[^"]*"[^>]*>\s*<strong>December</strong>\s*</div>\s*'
        r'<div class="fomc-meeting__date[^"]*"[^>]*>\s*([^<]+?)\s*</div>(.*)',
        chunk,
        flags=re.I | re.DOTALL,
    )
    if not dec:
        return []
    date_cell = dec.group(1).strip().rstrip("*").strip()
    rest = dec.group(2)
    m_range = re.match(r"^(\d{1,2})-(\d{1,2})", date_cell)
    if not m_range:
        return []
    end_day = int(m_range.group(2))
    local_d = date(2026, 12, end_day)
    # Optional statement clock if printed as HH:MM (none on the overview page for Dec 2026 in Nov 2026 snapshot).
    clock_m = re.search(
        r"\b(\d{1,2}):(\d{2})\s*(a\.m\.|p\.m\.|AM|PM)\b",
        rest,
        re.I,
    )
    if clock_m:
        h = int(clock_m.group(1))
        mm = int(clock_m.group(2))
        ap = clock_m.group(3).lower().replace(".", "")
        if "p" in ap and h != 12:
            h += 12
        if "a" in ap and h == 12:
            h = 0
        lt = f"{h:02d}:{mm:02d}"
        status = "verified"
    else:
        lt = None
        status = "tba"
    return [
        EconomicReleaseEvent(
            event_family="us_fomc",
            country="US",
            title="FOMC monetary policy meeting",
            publisher="Federal Reserve Board",
            local_date=local_d,
            local_time=lt,
            timezone=TZ_NY,
            reference_period="2026-12-08/2026-12-09",
            source_url=source_url,
            fetched_at=fetched_at,
            status=status,
            series_ids=(),
            provenance=f"Meeting week {date_cell.strip()} — {rest[:200]}",
            date_confidence="confirmed",
        )
    ]


def _parse_ism_calendar(body: str, *, source_url: str, fetched_at: str) -> list[EconomicReleaseEvent]:
    """ISM PMI: day-of-month from table; 10:00 standing from publisher sentences."""
    events: list[EconomicReleaseEvent] = []
    # Month row: | November 2026 | 2 | 4 |
    row_re = re.compile(
        r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$",
    )
    for line in body.splitlines():
        m = row_re.match(line.strip())
        if not m:
            continue
        month_cell, mfg_cell, svc_cell = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
        if "supply chain" in month_cell.lower() or "forecast" in month_cell.lower():
            continue
        m_month = re.match(
            r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\s*$",
            month_cell,
            re.I,
        )
        if not m_month:
            continue
        mon_name, y_s = m_month.group(1), m_month.group(2)
        year = int(y_s)
        mon = _FULL_MONTHS[mon_name.lower()]
        if not (mfg_cell.isdigit() and svc_cell.isdigit()):
            continue
        mfg_d = int(mfg_cell)
        svc_d = int(svc_cell)
        if mfg_d < 1 or mfg_d > 31 or svc_d < 1 or svc_d > 31:
            continue
        try:
            d_mfg = date(year, mon, mfg_d)
            d_svc = date(year, mon, svc_d)
        except ValueError:
            continue
        ref = f"{mon_name} {year}"
        base_kw = dict(
            country="US",
            publisher="Institute for Supply Management",
            local_time=_ISM_STANDING_TIME,
            timezone=TZ_NY,
            source_url=source_url,
            fetched_at=fetched_at,
            status="standing",
            date_confidence="confirmed",
            provenance=f"{ref} — Manufacturing day {mfg_d}, Services day {svc_d}; "
            f"standing time {_ISM_STANDING_TIME} from ISM schedule page text.",
        )
        events.append(
            EconomicReleaseEvent(
                event_family="us_ism_manufacturing",
                title="ISM Manufacturing PMI",
                local_date=d_mfg,
                reference_period=ref,
                series_ids=("US.Activity.manufacturing_surveys",),
                **base_kw,
            )
        )
        events.append(
            EconomicReleaseEvent(
                event_family="us_ism_services",
                title="ISM Services PMI",
                local_date=d_svc,
                reference_period=ref,
                series_ids=("US.Activity.services_surveys",),
                **base_kw,
            )
        )
    return events


def _parse_us_retail_pdf_text(body: str, *, source_url: str, fetched_at: str, now: datetime) -> list[EconomicReleaseEvent]:
    """Retail sales from Census PDF text; only when a full calendar release date is explicit and after ``now``."""
    events: list[EconomicReleaseEvent] = []
    # Table rows like: October 2024 | November 15, 2024 | 8:30 am
    for raw in body.splitlines():
        line = raw.strip()
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        data_month_s, rel_s, time_s = parts[0], parts[1], parts[2]
        if re.match(r"^data month$", data_month_s, re.I):
            continue
        if not re.search(r"\d{4}", data_month_s):
            continue
        dm = re.match(
            r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\s*$",
            data_month_s,
            re.I,
        )
        if not dm:
            continue
        ref_ym = f"{dm.group(2)}-{_FULL_MONTHS[dm.group(1).lower()]:02d}"
        rel_m = re.match(
            r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(\d{4})$",
            rel_s,
            re.I,
        )
        if not rel_m:
            continue
        rmon = _FULL_MONTHS[rel_m.group(1).lower()]
        rday = int(rel_m.group(2))
        ryear = int(rel_m.group(3))
        try:
            local_d = date(ryear, rmon, rday)
        except ValueError:
            continue
        lt = _parse_time_cell(time_s)
        if lt is None:
            continue
        if datetime(local_d.year, local_d.month, local_d.day, 23, 59, 59, tzinfo=now.tzinfo) <= now:
            continue
        events.append(
            EconomicReleaseEvent(
                event_family="us_retail",
                country="US",
                title="Advance Monthly Sales for Retail and Food Services",
                publisher="U.S. Census Bureau",
                local_date=local_d,
                local_time=lt,
                timezone=TZ_NY,
                reference_period=ref_ym,
                source_url=source_url,
                fetched_at=fetched_at,
                status="verified",
                series_ids=_RETAIL_SERIES,
                provenance=f"{data_month_s} -> {rel_s} {time_s} (Census retail schedule PDF).",
            )
        )
    return events


def _dedupe_event_ids(events: list[EconomicReleaseEvent]) -> list[EconomicReleaseEvent]:
    seen: set[str] = set()
    out: list[EconomicReleaseEvent] = []
    for ev in events:
        eid = ev.event_id()
        if eid in seen:
            continue
        seen.add(eid)
        out.append(ev)
    return out


class UsOfficialSchedule:
    country = "US"

    def source_plan(self) -> tuple[SourceDocument, ...]:
        return (
            SourceDocument(
                key="bls_empsit",
                url="https://www.bls.gov/schedule/news_release/empsit.htm",
                description="BLS Employment Situation release schedule",
            ),
            SourceDocument(
                key="bls_cpi",
                url="https://www.bls.gov/schedule/news_release/cpi.htm",
                description="BLS Consumer Price Index release schedule",
            ),
            SourceDocument(
                key="bls_ppi",
                url="https://www.bls.gov/schedule/news_release/ppi.htm",
                description="BLS Producer Price Index release schedule",
            ),
            SourceDocument(
                key="bls_jolts",
                url="https://www.bls.gov/schedule/news_release/jolts.htm",
                description="BLS Job Openings and Labor Turnover Survey release schedule",
            ),
            SourceDocument(
                key="bea_schedule",
                url="https://www.bea.gov/news/schedule",
                description="BEA national release schedule",
            ),
            SourceDocument(
                key="fomc",
                url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                description="Federal Reserve FOMC meeting calendar",
            ),
            SourceDocument(
                key="ism",
                url="https://www.ismworld.org/supply-management-news-and-reports/reports/rob-report-calendar/",
                description="ISM Manufacturing and Services PMI release calendar",
            ),
            SourceDocument(
                key="us_retail",
                url=_US_REPS_URL,
                description="Census Bureau advance monthly retail sales release dates (PDF)",
            ),
        )

    def parse_documents(
        self,
        documents: Mapping[str, str],
        *,
        now: datetime,
        fetched_at: str,
    ) -> list[EconomicReleaseEvent]:
        collected: list[EconomicReleaseEvent] = []

        try:
            # BLS tables (markdown-style or HTML with similar cells)
            bls_specs: list[tuple[str, str, str, str, tuple[str, ...]]] = [
                (
                    "bls_empsit",
                    "https://www.bls.gov/schedule/news_release/empsit.htm",
                    "us_empsit",
                    "Employment Situation",
                    _EMPSIT_SERIES,
                ),
                (
                    "bls_cpi",
                    "https://www.bls.gov/schedule/news_release/cpi.htm",
                    "us_cpi",
                    "Consumer Price Index",
                    _CPI_SERIES,
                ),
                (
                    "bls_ppi",
                    "https://www.bls.gov/schedule/news_release/ppi.htm",
                    "us_ppi",
                    "Producer Price Index",
                    _PPI_SERIES,
                ),
            ]
            for key, url, family, title, series in bls_specs:
                body = documents.get(key)
                if not body:
                    continue
                rows = _parse_bls_markdown_table(body)
                for ref_label, rel_date, lt in rows:
                    if not _ref_month_in_range(ref_label, "2026-10", "2027-03"):
                        continue
                    ym = _ym_from_reference_month_label(ref_label)
                    if ym is None:
                        continue
                    collected.append(
                        EconomicReleaseEvent(
                            event_family=family,
                            country="US",
                            title=title,
                            publisher="Bureau of Labor Statistics",
                            local_date=rel_date,
                            local_time=lt,
                            timezone=TZ_NY,
                            reference_period=ym,
                            source_url=url,
                            fetched_at=fetched_at,
                            status="verified",
                            series_ids=series,
                            provenance=f"{ref_label} -> {rel_date.isoformat()} {lt} (BLS schedule table).",
                            date_confidence="confirmed",
                        )
                    )

            jolts_body = documents.get("bls_jolts")
            if jolts_body:
                for ref_label, rel_date, lt in _parse_bls_markdown_table(jolts_body):
                    ym = _ym_from_reference_month_label(ref_label)
                    if ym is None:
                        continue
                    # Publisher rows for survey months November 2026 and later only.
                    if _ym_order(ym) < _ym_order("2026-11"):
                        continue
                    collected.append(
                        EconomicReleaseEvent(
                            event_family="us_jolts",
                            country="US",
                            title="Job Openings and Labor Turnover Survey",
                            publisher="Bureau of Labor Statistics",
                            local_date=rel_date,
                            local_time=lt,
                            timezone=TZ_NY,
                            reference_period=ym,
                            source_url="https://www.bls.gov/schedule/news_release/jolts.htm",
                            fetched_at=fetched_at,
                            status="verified",
                            series_ids=_JOLTS_SERIES,
                            provenance=f"{ref_label} -> {rel_date.isoformat()} {lt} (BLS JOLTS schedule).",
                            date_confidence="confirmed",
                        )
                    )

            bea_body = documents.get("bea_schedule")
            if bea_body:
                collected.extend(
                    _parse_bea_schedule(
                        bea_body,
                        source_url="https://www.bea.gov/news/schedule",
                        fetched_at=fetched_at,
                    )
                )

            fomc_body = documents.get("fomc")
            if fomc_body:
                collected.extend(
                    _parse_fomc(
                        fomc_body,
                        source_url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                        fetched_at=fetched_at,
                    )
                )

            ism_body = documents.get("ism")
            if ism_body:
                collected.extend(
                    _parse_ism_calendar(
                        ism_body,
                        source_url="https://www.ismworld.org/supply-management-news-and-reports/reports/rob-report-calendar/",
                        fetched_at=fetched_at,
                    )
                )

            retail_body = documents.get("us_retail")
            if retail_body:
                collected.extend(
                    _parse_us_retail_pdf_text(
                        retail_body,
                        source_url=_US_REPS_URL,
                        fetched_at=fetched_at,
                        now=now,
                    )
                )
        except Exception:
            return []

        out = _dedupe_event_ids(collected)
        try:
            validate_events(out)
        except ValueError:
            return []
        return out


ADAPTER = UsOfficialSchedule()
GAPS = _GAPS

__all__ = ["ADAPTER", "GAPS", "UsOfficialSchedule"]


def _self_check() -> None:
    validate_source_plan(ADAPTER.source_plan())


_self_check()
