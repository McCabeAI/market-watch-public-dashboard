"""New Zealand official economic release calendar adapter (parse-only)."""

from __future__ import annotations

import html as html_lib
import json
import re
import sys
from datetime import date, datetime
from typing import Any, Mapping

from scripts.dashboard_repair.release_contract import (
    EconomicReleaseEvent,
    SourceDocument,
)

TZ = "Pacific/Auckland"
PUBLISHER_STATS_NZ = "Stats NZ"

SOURCE_STATS_CALENDAR = "https://www.stats.govt.nz/release-calendar/"
SOURCE_GDP_TOPIC = "https://www.stats.govt.nz/topics/gross-domestic-product"
SOURCE_CPI_LATEST = "https://www.stats.govt.nz/information-releases/consumers-price-index-september-2026-quarter/"
SOURCE_RBNZ_STATS = "https://www.rbnz.govt.nz/statistics"

_NEXT_RELEASE_SENTENCE = re.compile(
    r"will\s+be\s+released\s+on\s+"
    r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})",
    re.IGNORECASE,
)
_MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}

_OCR_DATE_PART = re.compile(
    r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})",
)
_OCR_TIME = re.compile(
    r"\b(\d{1,2}):(\d{2})\s*(am|pm)?\b",
    re.IGNORECASE,
)

_ICS_VEVENT = re.compile(
    r"BEGIN:VEVENT\s*(.*?)END:VEVENT",
    re.DOTALL | re.IGNORECASE,
)
_ICS_DTSTART = re.compile(
    r"^DTSTART(?:;[^:\r\n]+)?:([\dTZ]+)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_ICS_SUMMARY = re.compile(
    r"^SUMMARY:(.+)\s*$",
    re.MULTILINE | re.IGNORECASE,
)

_SKIP_CAL_SUBSTR = (
    "births",
    "deaths",
    "population estimates",
    "population",
    "livestock",
    "national population",
)


def _parse_page_view_json(body: str) -> dict[str, Any] | None:
    m = re.search(
        r'id="pageViewData"\s+data-value="([^"]+)"',
        body,
        re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return None
    raw = html_lib.unescape(m.group(1))
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return out if isinstance(out, dict) else None


def _https_page_link(body: str) -> str | None:
    data = _parse_page_view_json(body)
    if data is None:
        return None
    pl = data.get("PageLink")
    if not isinstance(pl, str) or not pl.strip():
        return None
    pl = pl.strip()
    if pl.startswith("https://"):
        return pl
    if pl.startswith("/"):
        return f"https://www.stats.govt.nz{pl}"
    return None


def _latest_gdp_release_url(body: str) -> str | None:
    data = _parse_page_view_json(body)
    if data is None:
        return None
    blocks = data.get("PageBlocks")
    if not isinstance(blocks, list):
        return None
    for b in blocks:
        if not isinstance(b, dict):
            continue
        thumbs = b.get("Thumbnails")
        if not isinstance(thumbs, list):
            continue
        for t in thumbs:
            if not isinstance(t, dict):
                continue
            title = (t.get("Title") or "").strip()
            low = title.lower()
            if not title.startswith("Gross domestic product:"):
                continue
            if "regional" in low or "input-output" in low:
                continue
            pl = t.get("PageLink")
            if isinstance(pl, str) and pl.startswith("/"):
                return f"https://www.stats.govt.nz{pl}"
    return None


def _parse_next_release_from_stats_page(
    body: str, *, product: str
) -> tuple[date, str | None, str] | None:
    """Return (local_date, local_time_hhmm or None, reference_period) from a Stats NZ BlockPage body."""
    data = _parse_page_view_json(body)
    if data is None:
        return None
    blocks = data.get("PageBlocks")
    if not isinstance(blocks, list):
        return None
    needle = "gross domestic product" if product == "gdp" else "consumers price index"
    content = ""
    for b in blocks:
        if not isinstance(b, dict):
            continue
        title = (b.get("Title") or "").lower()
        if "next release" not in title:
            continue
        if product == "gdp":
            if needle not in title:
                continue
        elif "consumers price index" not in title and "cpi" not in title:
            continue
        c = b.get("Content")
        if isinstance(c, str) and "<h2>Next release</h2>" in c:
            content = c
            break
    if not content:
        return None
    m_sent = _NEXT_RELEASE_SENTENCE.search(content)
    if not m_sent:
        return None
    d_int, mon_s, y_int = m_sent.group(1), m_sent.group(2).lower(), int(m_sent.group(3))
    mon = _MONTHS.get(mon_s)
    if mon is None:
        return None
    local_d = date(y_int, mon, int(d_int))
    # Time must appear in the same sentence as the printed date; ignore metadata timestamps.
    sentence = content[m_sent.start() : m_sent.end() + 80]
    t_match = re.search(
        r"\b(\d{1,2}):(\d{2})\s*(am|pm)?\b",
        sentence,
        re.IGNORECASE,
    )
    local_time: str | None
    if t_match:
        hh = int(t_match.group(1))
        mm = int(t_match.group(2))
        ap = (t_match.group(3) or "").lower()
        if ap == "pm" and hh < 12:
            hh += 12
        if ap == "am" and hh == 12:
            hh = 0
        local_time = f"{hh:02d}:{mm:02d}"
    else:
        local_time = None
    ref = ""
    em = re.search(r"<em>\s*([^<]+)\s*</em>", content, re.IGNORECASE)
    if em:
        title_bit = em.group(1).strip()
        if product == "gdp":
            ref = _reference_from_gdp_title(title_bit)
        else:
            ref = _reference_from_cpi_title(title_bit)
    return local_d, local_time, ref


def _reference_from_cpi_title(title: str) -> str:
    t = title.lower()
    q = re.search(r"(march|june|september|december)\s+(\d{4})\s+quarter", t)
    if q:
        quarter = {"march": "Q1", "june": "Q2", "september": "Q3", "december": "Q4"}[
            q.group(1)
        ]
        return f"{q.group(2)}-{quarter}"
    return ""


def _reference_from_gdp_title(title: str) -> str:
    t = title.lower()
    q = re.search(
        r"gross\s+domestic\s+product:\s*"
        r"(march|june|september|december)\s+(\d{4})\s+quarter",
        t,
    )
    if q:
        quarter = {"march": "Q1", "june": "Q2", "september": "Q3", "december": "Q4"}[
            q.group(1)
        ]
        return f"{q.group(2)}-{quarter}"
    return ""


def _ics_date_only(dt_str: str) -> date | None:
    # Examples: 20261117T104500, 20261117
    dm = re.match(r"^(\d{4})(\d{2})(\d{2})", dt_str.strip())
    if not dm:
        return None
    y, mo, d = int(dm.group(1)), int(dm.group(2)), int(dm.group(3))
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def _reference_from_summary(summary: str) -> str:
    s = summary.strip()
    m_q = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\s+quarter",
        s,
        re.IGNORECASE,
    )
    if m_q:
        quarter = {
            "march": "Q1",
            "june": "Q2",
            "september": "Q3",
            "december": "Q4",
        }[m_q.group(1).lower()]
        return f"{m_q.group(2)}-{quarter}"
    m_m = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b",
        s,
        re.IGNORECASE,
    )
    if m_m:
        mon_name = m_m.group(1).lower()
        y = m_m.group(2)
        mm = _MONTHS.get(mon_name)
        if mm is not None:
            return f"{y}-{mm:02d}"
    return ""


def _parse_calendar_ics(body: str) -> list[tuple[date, str]]:
    rows: list[tuple[date, str]] = []
    for block in _ICS_VEVENT.finditer(body):
        chunk = block.group(1)
        dtm = _ICS_DTSTART.search(chunk)
        summ = _ICS_SUMMARY.search(chunk)
        if not dtm or not summ:
            continue
        d = _ics_date_only(dtm.group(1))
        if d is None:
            continue
        summary = summ.group(1).strip()
        rows.append((d, summary))
    return rows


def _calendar_row_to_event(
    *,
    local_date: date,
    summary: str,
    fetched_at: str,
    source_url: str,
) -> EconomicReleaseEvent | None:
    low = summary.lower()
    if any(x in low for x in _SKIP_CAL_SUBSTR):
        if "labour market" not in low:
            return None
    ref = _reference_from_summary(summary)

    if "selected price indexes" in low:
        if "october 2026" not in low:
            return None
        return EconomicReleaseEvent(
            event_family="nz_selected_prices",
            country="NZ",
            title="Selected price indexes",
            publisher=PUBLISHER_STATS_NZ,
            local_date=local_date,
            local_time=None,
            timezone=TZ,
            reference_period=ref,
            source_url=source_url,
            fetched_at=fetched_at,
            status="tba",
            series_ids=(),
            provenance=(
                f'Calendar export line SUMMARY:"{summary}"; DTSTART date {local_date.isoformat()} '
                "(ICS includes a default time; per-release clock not printed on the row — time TBA)."
            ),
        )
    if "business price indexes" in low:
        if "september 2026" not in low:
            return None
        return EconomicReleaseEvent(
            event_family="nz_business_prices",
            country="NZ",
            title="Business price indexes",
            publisher=PUBLISHER_STATS_NZ,
            local_date=local_date,
            local_time=None,
            timezone=TZ,
            reference_period=ref,
            source_url=source_url,
            fetched_at=fetched_at,
            status="tba",
            series_ids=(
                "NZ.Inflation.ppi",
                "NZ.Inflation.import_price_index",
                "NZ.Inflation.export_price_index",
            ),
            provenance=(
                f'Calendar export line SUMMARY:"{summary}"; DTSTART date {local_date.isoformat()} '
                "(ICS includes a default time; per-release clock not printed on the row — time TBA)."
            ),
        )
    if "retail trade survey" in low:
        if "september 2026" not in low:
            return None
        return EconomicReleaseEvent(
            event_family="nz_retail",
            country="NZ",
            title="Retail trade survey",
            publisher=PUBLISHER_STATS_NZ,
            local_date=local_date,
            local_time=None,
            timezone=TZ,
            reference_period=ref,
            source_url=source_url,
            fetched_at=fetched_at,
            status="tba",
            series_ids=("NZ.Consumer.retail",),
            provenance=(
                f'Calendar export line SUMMARY:"{summary}"; DTSTART date {local_date.isoformat()} '
                "(ICS includes a default time; per-release clock not printed on the row — time TBA)."
            ),
        )
    if "employment indicators" in low:
        if "october 2026" not in low:
            return None
        return EconomicReleaseEvent(
            event_family="nz_employment_indicators",
            country="NZ",
            title="Employment indicators",
            publisher=PUBLISHER_STATS_NZ,
            local_date=local_date,
            local_time=None,
            timezone=TZ,
            reference_period=ref,
            source_url=source_url,
            fetched_at=fetched_at,
            status="tba",
            series_ids=(),
            provenance=(
                f'Calendar export line SUMMARY:"{summary}"; DTSTART date {local_date.isoformat()} '
                "(ICS includes a default time; per-release clock not printed on the row — time TBA)."
            ),
        )
    if "labour market statistics" in low:
        return EconomicReleaseEvent(
            event_family="nz_labour_market",
            country="NZ",
            title="Labour market statistics",
            publisher=PUBLISHER_STATS_NZ,
            local_date=local_date,
            local_time=None,
            timezone=TZ,
            reference_period=ref,
            source_url=source_url,
            fetched_at=fetched_at,
            status="tba",
            series_ids=(
                "NZ.Labor.unemployment",
                "NZ.Labor.employment",
                "NZ.Labor.wages",
                "NZ.Labor.participation",
            ),
            provenance=(
                f'Calendar export line SUMMARY:"{summary}"; DTSTART date {local_date.isoformat()} '
                "(ICS includes a default time; per-release clock not printed on the row — time TBA)."
            ),
        )
    return None


def _parse_rbnz_ocr(body: str, fetched_at: str, source_url: str) -> EconomicReleaseEvent | None:
    if "official cash rate" not in body.lower():
        return None
    nu = re.search(r"Next\s+update\s*:\s*", body, re.IGNORECASE)
    if not nu:
        return None
    window = body[nu.start() : nu.start() + 400]
    dm = _OCR_DATE_PART.search(window)
    if not dm:
        dm = _OCR_DATE_PART.search(body[nu.start() :])
    if not dm:
        return None
    mon = _MONTHS.get(dm.group(2).lower())
    if mon is None:
        return None
    local_d = date(int(dm.group(3)), mon, int(dm.group(1)))
    before_date = window[: dm.start()]
    t_match = _OCR_TIME.search(before_date)
    if t_match:
        hh = int(t_match.group(1))
        mm = int(t_match.group(2))
        ap = (t_match.group(3) or "").lower()
        if ap == "pm" and hh < 12:
            hh += 12
        if ap == "am" and hh == 12:
            hh = 0
        lt = f"{hh:02d}:{mm:02d}"
        status = "verified"
    else:
        lt = None
        status = "tba"
    return EconomicReleaseEvent(
        event_family="nz_ocr",
        country="NZ",
        title="Official Cash Rate decision",
        publisher="Reserve Bank of New Zealand",
        local_date=local_d,
        local_time=lt,
        timezone=TZ,
        reference_period=local_d.isoformat(),
        source_url=source_url,
        fetched_at=fetched_at,
        status=status,
        series_ids=(),
        provenance=(
            "RBNZ statistics page: Official Cash Rate line with Next update and date as printed."
            + (
                f" Extracted clock {lt}."
                if lt
                else " No clock printed with the next update line."
            )
        ),
    )


class NzOfficialSchedule:
    country = "NZ"

    def source_plan(self) -> tuple[SourceDocument, ...]:
        return (
            SourceDocument(
                key="stats_nz_calendar",
                url=SOURCE_STATS_CALENDAR,
                description=(
                    "Stats NZ official release calendar (HTML shell; calendar rows often via export feed)."
                ),
            ),
            SourceDocument(
                key="stats_nz_gdp",
                url=SOURCE_GDP_TOPIC,
                description="Stats NZ GDP topic; follow latest GDP information release for next date.",
            ),
            SourceDocument(
                key="stats_nz_cpi",
                url=SOURCE_CPI_LATEST,
                description="Latest Stats NZ Consumers price index information release page.",
            ),
            SourceDocument(
                key="rbnz_ocr",
                url=SOURCE_RBNZ_STATS,
                description="RBNZ statistics hub (Official Cash Rate next update).",
            ),
        )

    def parse_documents(
        self,
        documents: Mapping[str, str],
        *,
        now: datetime,
        fetched_at: str,
    ) -> list[EconomicReleaseEvent]:
        gaps: list[str] = []
        events: list[EconomicReleaseEvent] = []
        today = now.date()

        cal = documents.get("stats_nz_calendar") or ""
        if cal.strip():
            if "BEGIN:VEVENT" in cal:
                for local_d, summary in _parse_calendar_ics(cal):
                    ev = _calendar_row_to_event(
                        local_date=local_d,
                        summary=summary,
                        fetched_at=fetched_at,
                        source_url=SOURCE_STATS_CALENDAR,
                    )
                    if ev is None:
                        continue
                    if ev.event_family == "nz_labour_market" and ev.local_date <= today:
                        continue
                    events.append(ev)
            else:
                # Plain-text / table excerpt without VEVENT: no calendar rows.
                pass

        # Future HLFS / labour market row
        labour_future = [e for e in events if e.event_family == "nz_labour_market" and e.local_date > today]
        if not labour_future:
            gaps.append(
                "No future Stats NZ labour market statistics date was printed on the release calendar."
            )

        gdp_body = documents.get("stats_nz_gdp") or ""
        if gdp_body.strip():
            gdp_src = _latest_gdp_release_url(gdp_body) or _https_page_link(gdp_body) or SOURCE_GDP_TOPIC
            parsed = _parse_next_release_from_stats_page(gdp_body, product="gdp")
            if parsed:
                local_d, lt, ref = parsed
                st: str = "verified" if lt else "tba"
                events.append(
                    EconomicReleaseEvent(
                        event_family="nz_gdp",
                        country="NZ",
                        title="Gross domestic product",
                        publisher=PUBLISHER_STATS_NZ,
                        local_date=local_d,
                        local_time=lt,
                        timezone=TZ,
                        reference_period=ref,
                        source_url=gdp_src,
                        fetched_at=fetched_at,
                        status=st,
                        series_ids=(
                            "NZ.Activity.gdp_domestic_demand",
                            "NZ.Activity.gdp_expenditure",
                        ),
                        provenance=(
                            "Next release sentence from latest GDP information release page "
                            f"({local_d.isoformat()})."
                            + (
                                " Sentence did not print a clock; time TBA."
                                if lt is None
                                else f" Printed clock {lt}."
                            )
                        ),
                    )
                )
            else:
                gaps.append(
                    "No printed next GDP release date was found on the latest Stats NZ GDP information page."
                )

        cpi_body = documents.get("stats_nz_cpi") or ""
        if cpi_body.strip():
            cpi_src = _https_page_link(cpi_body) or SOURCE_CPI_LATEST
            parsed_c = _parse_next_release_from_stats_page(cpi_body, product="cpi")
            if parsed_c:
                local_d, lt, ref = parsed_c
                st_c: str = "verified" if lt else "tba"
                events.append(
                    EconomicReleaseEvent(
                        event_family="nz_cpi",
                        country="NZ",
                        title="Consumers price index",
                        publisher=PUBLISHER_STATS_NZ,
                        local_date=local_d,
                        local_time=lt,
                        timezone=TZ,
                        reference_period=ref,
                        source_url=cpi_src,
                        fetched_at=fetched_at,
                        status=st_c,
                        series_ids=("NZ.Inflation.headline", "NZ.Inflation.underlying"),
                        provenance=(
                            "Next release sentence from latest Consumers price index information release page "
                            f"({local_d.isoformat()})."
                            + (
                                " Sentence did not print a clock; time TBA."
                                if lt is None
                                else f" Printed clock {lt}."
                            )
                        ),
                    )
                )
            else:
                gaps.append(
                    "No printed next CPI release date was found on the latest Stats NZ CPI information page."
                )

        rbnz = documents.get("rbnz_ocr") or ""
        if rbnz.strip():
            ocr_ev = _parse_rbnz_ocr(rbnz, fetched_at, SOURCE_RBNZ_STATS)
            if ocr_ev:
                events.append(ocr_ev)

        # Dedupe by event_id preserving first
        seen: set[str] = set()
        uniq: list[EconomicReleaseEvent] = []
        for ev in events:
            eid = ev.event_id()
            if eid in seen:
                continue
            seen.add(eid)
            uniq.append(ev)

        _mod = sys.modules[__name__]
        _mod.GAPS = tuple(gaps)  # type: ignore[misc]
        return uniq


ADAPTER = NzOfficialSchedule()
GAPS: tuple[str, ...] = ()
