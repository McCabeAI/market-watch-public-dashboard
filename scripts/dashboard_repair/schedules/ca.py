"""Canada (CA) official economic release schedule adapter (Statistics Canada + BoC)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from html import unescape
from html.parser import HTMLParser
from typing import Mapping

from scripts.dashboard_repair.release_contract import (
    EconomicReleaseEvent,
    SourceDocument,
    validate_events,
    validate_source_plan,
)

# --- Official document keys (stable ids for integrator fetch maps) ---

_KEY_PRIMARY = "primary_table"
_KEY_CLOCK = "daily_clock"
_KEY_LFS_DAILY = "lfs_daily"
_KEY_BOC = "boc_rate"

_URL_STATCAN_PDF = "https://www150.statcan.gc.ca/n1/release-diffusion/2026-eng.pdf"
_URL_STATCAN_CLOCK = "https://www150.statcan.gc.ca/n1/dai-quo/cal2-eng.htm"
_URL_BOC_KEY = "https://www.bankofcanada.ca/core-functions/monetary-policy/key-interest-rate/"

_TZ_TORONTO = "America/Toronto"
_PUBLISHER_STATCAN = "Statistics Canada"
_PUBLISHER_BOC = "Bank of Canada"

_MONTH_NAMES = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)

_MONTH_TO_NUM = {n: i + 1 for i, n in enumerate(_MONTH_NAMES)}

_QUARTER_WORD = {
    "first": "Q1",
    "second": "Q2",
    "third": "Q3",
    "fourth": "Q4",
}

# PDF text often concatenates titles; HTML uses spaced titles.
_SECTION_HEADERS = (
    ("ca_lfs", ("LabourForceSurvey",), "Labour Force Survey"),
    ("ca_cpi", ("ConsumerPriceIndex",), "Consumer Price Index"),
    ("ca_retail", ("Retailtrade",), "Retail trade"),
    ("ca_gdp_industry", ("Grossdomesticproductbyindustry",), "Gross domestic product by industry"),
    (
        "ca_gdp_expenditure",
        ("Grossdomesticproduct,incomeandexpenditure",),
        "Gross domestic product, income and expenditure",
    ),
)

_KNOWN_PDF_SECTION_MARKERS: frozenset[str] = frozenset(
    hk for _fam, hks, _title in _SECTION_HEADERS for hk in hks
)

_SERIES_BY_FAMILY: dict[str, tuple[str, ...]] = {
    "ca_lfs": (
        "CA.Labor.unemployment",
        "CA.Labor.wages",
        "CA.Labor.employment",
        "CA.Labor.participation",
    ),
    "ca_cpi": ("CA.Inflation.headline", "CA.Inflation.underlying"),
    "ca_retail": ("CA.Consumer.retail", "CA.Consumer.retail_sales_volume"),
    "ca_gdp_industry": ("CA.Activity.gdp_domestic_demand",),
    "ca_gdp_expenditure": ("CA.Activity.gdp_domestic_demand",),
}

_ROW_DATE_RE = re.compile(
    r"^([A-Z][a-z]+\s+\d{1,2},\s+\d{4})\s+(.+)$",
)
# Standing clock (Eastern) — map to America/Toronto per task; 24h 08:30
_STANDING_CLOCK_SENTENCE_RE = re.compile(
    r"8:30\s*a\.m\.\s*Eastern",
    re.IGNORECASE,
)
_LFS_RELEASED_RE = re.compile(
    r"Released:\D*(\d{4})-(\d{2})-(\d{2})",
    re.IGNORECASE,
)
_LFS_TITLE_REF_RE = re.compile(
    r"Labour\s+Force\s+Survey,\s*([A-Za-z]+)\s+(\d{4})",
    re.IGNORECASE,
)
_LFS_NEXT_RE = re.compile(
    r"next\s+release\s+of\s+the\s+LFS\s+will\s+be\s+on\s+"
    r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})",
    re.IGNORECASE,
)
_STATCAN_CAL2_HEADING_RE = re.compile(
    r'<h3\s+class="hd1">\s*([^<]+?)\s*</h3>',
    re.IGNORECASE,
)
_STATCAN_RTITLE_RE = re.compile(
    r'<div class="rtitle">\s*([^<]+?)\s*,\s*'
    r'<span class="refper">\s*([^<]+?)\s*</span>\s*</div>',
    re.IGNORECASE,
)
_STATCAN_CAL2_RANGE_YEAR_RE = re.compile(
    r"<h2>\s*[A-Za-z]+\s+\d{1,2}.+?\d{1,2},\s*(\d{4})\s*</h2>",
    re.IGNORECASE,
)


def _statcan_cal2_window_year(html: str, *, now: datetime) -> int:
    m = _STATCAN_CAL2_RANGE_YEAR_RE.search(html)
    if m:
        return int(m.group(1))
    return now.year


def _family_from_statcan_rtitle(title: str) -> str | None:
    t = re.sub(r"\s+", " ", unescape(title).strip()).lower()
    if t == "labour force survey":
        return "ca_lfs"
    if t == "consumer price index":
        return "ca_cpi"
    if t == "retail trade":
        return "ca_retail"
    if t == "gross domestic product by industry":
        return "ca_gdp_industry"
    if t == "gross domestic product, income and expenditure":
        return "ca_gdp_expenditure"
    return None


def _parse_cal2_day_heading(heading_html: str) -> tuple[str, int] | None:
    raw = re.sub(r"[\s\xa0]+", " ", unescape(heading_html)).strip()
    m = re.match(r"^([A-Za-z]+)\s+(\d{1,2})\s*$", raw)
    if not m:
        return None
    return m.group(1).lower(), int(m.group(2))


def _events_from_statcan_cal2_html(
    html: str,
    *,
    now: datetime,
    has_standing_clock: bool,
    fetched_at: str,
    source_url: str,
) -> list[EconomicReleaseEvent]:
    if not html.strip():
        return []
    year = _statcan_cal2_window_year(html, now=now)
    local_time, status = _standing_time_status(has_standing_clock)
    events: list[EconomicReleaseEvent] = []
    for m in _STATCAN_CAL2_HEADING_RE.finditer(html):
        heading_inner = m.group(1)
        parsed = _parse_cal2_day_heading(heading_inner)
        if not parsed:
            continue
        mon_s, day_n = parsed
        if mon_s not in _MONTH_TO_NUM:
            continue
        try:
            local_d = date(year, _MONTH_TO_NUM[mon_s], day_n)
        except ValueError:
            continue
        start = m.end()
        next_h = _STATCAN_CAL2_HEADING_RE.search(html, start)
        block_end = next_h.start() if next_h else len(html)
        block = html[start:block_end]
        for rm in _STATCAN_RTITLE_RE.finditer(block):
            title = rm.group(1).strip()
            ref_label = unescape(rm.group(2)).strip()
            ref_label = re.sub(r"\s+", " ", ref_label)
            family = _family_from_statcan_rtitle(title)
            if family is None:
                continue
            ref_code = _reference_period_label_to_code(ref_label)
            if ref_code is None:
                continue
            prov = (
                f"{title} — cal2 upcoming list {local_d.isoformat()}, "
                f"reference period {ref_label!r}."
            )
            events.append(
                EconomicReleaseEvent(
                    event_family=family,
                    country="CA",
                    title=title,
                    publisher=_PUBLISHER_STATCAN,
                    local_date=local_d,
                    local_time=local_time,
                    timezone=_TZ_TORONTO,
                    reference_period=ref_code,
                    source_url=source_url,
                    fetched_at=fetched_at,
                    status=status,
                    series_ids=_SERIES_BY_FAMILY[family],
                    provenance=prov,
                )
            )
    return events
_REF_MONTH_YEAR_RE = re.compile(
    r"^([A-Za-z]+)\s+(\d{4})\s*$",
)
_REF_QUARTER_RE = re.compile(
    r"^(First|Second|Third|Fourth)\s+quarter\s+(\d{4})\s*$",
    re.IGNORECASE,
)


def _parse_calendar_date(s: str) -> date | None:
    s = s.strip()
    m = re.match(r"^([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})\s*$", s)
    if not m:
        return None
    mon = m.group(1).lower()
    d = int(m.group(2))
    y = int(m.group(3))
    if mon not in _MONTH_TO_NUM:
        return None
    try:
        return date(y, _MONTH_TO_NUM[mon], d)
    except ValueError:
        return None


def _english_date(d: date) -> str:
    return f"{_MONTH_NAMES[d.month - 1].title()} {d.day}, {d.year}"


def _reference_period_label_to_code(label: str) -> str | None:
    raw = label.strip()
    raw = re.sub(r"\s+", " ", raw)
    # Quarters before month names ("Third quarter 2026" is not March 2026).
    q = _REF_QUARTER_RE.match(raw)
    if q:
        w = q.group(1).lower()
        y = q.group(2)
        qn = _QUARTER_WORD.get(w)
        if qn:
            return f"{y}-{qn}"
    m = _REF_MONTH_YEAR_RE.match(raw)
    if m:
        mon = m.group(1).lower()
        y = m.group(2)
        if mon in _MONTH_TO_NUM:
            return f"{y}-{_MONTH_TO_NUM[mon]:02d}"
    return None


def _standing_time_status(has_clock: bool) -> tuple[str | None, str]:
    if has_clock:
        return "08:30", "standing"
    return None, "tba"


def _looks_like_pdf_section_header(stripped: str) -> bool:
    """Detect PDF table section titles (one-line headings before 'Release date' rows)."""
    if stripped in _KNOWN_PDF_SECTION_MARKERS:
        return True
    if not stripped or " " in stripped:
        return False
    if stripped in ("Releasedate",):
        return False
    low = stripped.lower()
    if "release" in low:
        return False
    # Compound CamelCase: ConsumerPriceIndex, LabourForceSurvey
    if re.match(r"^[A-Z][a-zA-Z]+(?:[A-Z][a-zA-Z]+)+$", stripped):
        return True
    # Single leading capital, rest lower — e.g. Retailtrade, Grossdomesticproductbyindustry
    if re.match(r"^[A-Z][a-z]{9,}$", stripped):
        return True
    # Heading that still includes a comma (rare); only when whitelisted
    return False


def _extract_section_blocks(text: str) -> dict[str, str]:
    """Map section id (e.g. LabourForceSurvey) to block text following the header."""
    lines = text.splitlines()
    section_starts: list[tuple[str, int]] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if _looks_like_pdf_section_header(stripped):
            section_starts.append((stripped, i))
    blocks: dict[str, str] = {}
    for header_key, _fam, _title in [
        (hk, fam, title) for fam, hks, title in _SECTION_HEADERS for hk in hks
    ]:
        pos = next((idx for hk, idx in section_starts if hk == header_key), None)
        if pos is None:
            continue
        next_any = next((idx for hk, idx in section_starts if idx > pos), None)
        end_line = next_any if next_any is not None else len(lines)
        blocks[header_key] = "\n".join(lines[pos:end_line])
    return blocks


def _parse_table_rows(block: str) -> list[tuple[date, str]]:
    """Parse 'Month D, YYYY Reference period' rows from a StatCan PDF-style block."""
    out: list[tuple[date, str]] = []
    for line in block.splitlines():
        line_st = line.strip()
        if not line_st or line_st.lower().startswith("release"):
            continue
        m = _ROW_DATE_RE.match(line_st)
        if not m:
            continue
        d = _parse_calendar_date(m.group(1))
        if d is None:
            continue
        ref = m.group(2).strip()
        out.append((d, ref))
    return out


def _events_from_primary(
    text: str,
    *,
    has_standing_clock: bool,
    fetched_at: str,
    source_url: str,
) -> list[EconomicReleaseEvent]:
    if not text.strip():
        return []
    blocks = _extract_section_blocks(text)
    local_time, status = _standing_time_status(has_standing_clock)
    events: list[EconomicReleaseEvent] = []

    for family, header_keys, title in _SECTION_HEADERS:
        block = ""
        for hk in header_keys:
            block = blocks.get(hk, "")
            if block:
                break
        if not block:
            continue
        rows = _parse_table_rows(block)
        series = _SERIES_BY_FAMILY[family]
        for local_d, ref_label in rows:
            ref_code = _reference_period_label_to_code(ref_label)
            if ref_code is None:
                continue
            prov = f"{title} — release date {local_d.isoformat()}, reference period {ref_label!r} (Statistics Canada 2026–2027 major economic releases table)."
            events.append(
                EconomicReleaseEvent(
                    event_family=family,
                    country="CA",
                    title=title,
                    publisher=_PUBLISHER_STATCAN,
                    local_date=local_d,
                    local_time=local_time,
                    timezone=_TZ_TORONTO,
                    reference_period=ref_code,
                    source_url=source_url,
                    fetched_at=fetched_at,
                    status=status,
                    series_ids=series,
                    provenance=prov,
                )
            )
    return events


def _parse_lfs_daily_html(
    html: str,
    *,
    has_standing_clock: bool,
    fetched_at: str,
    source_url: str,
) -> list[EconomicReleaseEvent]:
    if not html.strip():
        return []
    local_time, status = _standing_time_status(has_standing_clock)
    events: list[EconomicReleaseEvent] = []

    m_rel = _LFS_RELEASED_RE.search(html)
    m_title = _LFS_TITLE_REF_RE.search(html)
    if m_rel and m_title:
        y, mo, d = int(m_rel.group(1)), int(m_rel.group(2)), int(m_rel.group(3))
        month_name = m_title.group(1).lower()
        ref_y = int(m_title.group(2))
        if month_name in _MONTH_TO_NUM:
            try:
                local_d = date(y, mo, d)
            except ValueError:
                local_d = None
            if local_d is not None:
                ref_m = _MONTH_TO_NUM[month_name]
                ref_code = f"{ref_y}-{ref_m:02d}"
                prov = (
                    "Labour Force Survey Daily page: "
                    f"Released {local_d.isoformat()} for reference {month_name.title()} {ref_y} (title line)."
                )
                events.append(
                    EconomicReleaseEvent(
                        event_family="ca_lfs",
                        country="CA",
                        title="Labour Force Survey",
                        publisher=_PUBLISHER_STATCAN,
                        local_date=local_d,
                        local_time=local_time,
                        timezone=_TZ_TORONTO,
                        reference_period=ref_code,
                        source_url=source_url,
                        fetched_at=fetched_at,
                        status=status,
                        series_ids=_SERIES_BY_FAMILY["ca_lfs"],
                        provenance=prov,
                    )
                )

    m_next = _LFS_NEXT_RE.search(html)
    if m_next:
        mon = m_next.group(1).lower()
        day = int(m_next.group(2))
        year = int(m_next.group(3))
        if mon in _MONTH_TO_NUM:
            try:
                local_d = date(year, _MONTH_TO_NUM[mon], day)
            except ValueError:
                local_d = None
            if local_d is not None:
                # Next release publishes November reference when release is Dec 4
                ref_anchor = html[m_next.end() : m_next.end() + 120]
                ref_mo = None
                ref_y = None
                m_nov = re.search(
                    r"(November|December|October|September|August|July|June|May|April|March|February|January)\s+(\d{4})",
                    ref_anchor,
                    re.I,
                )
                if m_nov:
                    ref_mo = _MONTH_TO_NUM.get(m_nov.group(1).lower())
                    ref_y = int(m_nov.group(2))
                ref_code = f"{ref_y}-{ref_mo:02d}" if ref_y and ref_mo else ""
                prov = (
                    "Labour Force Survey Daily page — next release sentence: "
                    f"{local_d.isoformat()} ({_english_date(local_d)})."
                )
                events.append(
                    EconomicReleaseEvent(
                        event_family="ca_lfs",
                        country="CA",
                        title="Labour Force Survey",
                        publisher=_PUBLISHER_STATCAN,
                        local_date=local_d,
                        local_time=local_time,
                        timezone=_TZ_TORONTO,
                        reference_period=ref_code,
                        source_url=source_url,
                        fetched_at=fetched_at,
                        status=status,
                        series_ids=_SERIES_BY_FAMILY["ca_lfs"],
                        provenance=prov,
                    )
                )
    return events


def _parse_boc_announcements(
    html: str,
    *,
    now: datetime,
    fetched_at: str,
    source_url: str,
) -> tuple[list[EconomicReleaseEvent], tuple[str, ...]]:
    if not html.strip():
        return [], ("ca_boc:no_bank_of_canada_html",)

    class _RowParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self._caption_text: list[str] = []
            self._in_caption = False
            self._current_schedule_year: int | None = None
            self._in_tr = False
            self._in_td = False
            self._skip_tr = False
            self._td_idx = 0
            self._cell_text: list[str] = []
            self._pending_date = ""
            self.pairs: list[tuple[int, str, str]] = []  # year, date_cell, pub_cell

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag == "caption":
                self._in_caption = True
                self._caption_text = []
            elif tag == "tr":
                self._in_tr = True
                self._td_idx = 0
                self._pending_date = ""
                self._skip_tr = self._current_schedule_year is None
            elif tag == "td" and self._in_tr and not self._skip_tr:
                self._in_td = True
                self._cell_text = []

        def handle_endtag(self, tag: str) -> None:
            if tag == "caption":
                self._in_caption = False
                cap = " ".join(self._caption_text).strip()
                m = re.search(r"Schedule\s+for\s+(\d{4})", cap)
                self._current_schedule_year = int(m.group(1)) if m else None
            elif tag == "td" and self._in_td:
                self._in_td = False
                text = " ".join(self._cell_text).strip()
                if self._current_schedule_year is None or self._skip_tr:
                    return
                if self._td_idx == 0:
                    self._pending_date = text
                elif self._td_idx == 1:
                    self.pairs.append((self._current_schedule_year, self._pending_date, text))
                self._td_idx += 1
            elif tag == "tr":
                self._in_tr = False

        def handle_data(self, data: str) -> None:
            if self._in_caption:
                self._caption_text.append(data)
            if self._in_td:
                self._cell_text.append(data)

    rp = _RowParser()
    try:
        rp.feed(html)
        rp.close()
    except Exception:
        return [], ("ca_boc:unparseable_bank_of_canada_html",)

    events: list[EconomicReleaseEvent] = []
    today = now.date()
    for year, date_cell, pub_cell in rp.pairs:
        if "Interest rate announcement" not in pub_cell:
            continue
        m = re.match(
            r"^([A-Za-z]+)[\s\u00a0]+(\d{1,2})\s*$",
            date_cell.strip(),
        )
        if not m:
            continue
        mon_s = m.group(1).lower()
        day_n = int(m.group(2))
        if mon_s not in _MONTH_TO_NUM:
            continue
        try:
            local_d = date(year, _MONTH_TO_NUM[mon_s], day_n)
        except ValueError:
            continue
        if local_d <= today:
            continue
        prov = (
            f"Bank of Canada key interest rate page — Schedule for {year}: "
            f"{date_cell.strip()} / {re.sub(r'\\s+', ' ', pub_cell.strip())[:200]}"
        )
        events.append(
            EconomicReleaseEvent(
                event_family="ca_boc",
                country="CA",
                title="Bank of Canada interest rate announcement",
                publisher=_PUBLISHER_BOC,
                local_date=local_d,
                local_time=None,
                timezone=_TZ_TORONTO,
                reference_period="",
                source_url=source_url,
                fetched_at=fetched_at,
                status="tba",
                series_ids=(),
                provenance=prov,
            )
        )
    gaps: tuple[str, ...] = ()
    if not events:
        gaps = ("ca_boc:no_explicit_future_interest_rate_announcement_date",)
    return events, gaps


def _dedupe_by_event_id(events: list[EconomicReleaseEvent]) -> list[EconomicReleaseEvent]:
    seen: set[str] = set()
    out: list[EconomicReleaseEvent] = []
    for ev in events:
        eid = ev.event_id()
        if eid in seen:
            continue
        seen.add(eid)
        out.append(ev)
    return out


@dataclass
class CaOfficialSchedule:
    """Parses fetched official documents for Canadian release metadata."""

    country: str = "CA"

    def source_plan(self) -> tuple[SourceDocument, ...]:
        plan = (
            SourceDocument(
                key=_KEY_PRIMARY,
                url=_URL_STATCAN_PDF,
                description=(
                    "Statistics Canada annual PDF table of major economic release dates "
                    "(2026–2027)."
                ),
            ),
            SourceDocument(
                key=_KEY_CLOCK,
                url=_URL_STATCAN_CLOCK,
                description=(
                    "Statistics Canada Daily release schedule page (standing publication clock)."
                ),
            ),
            SourceDocument(
                key=_KEY_LFS_DAILY,
                url=(
                    "https://www150.statcan.gc.ca/n1/daily-quotidien/261106/"
                    "dq261106a-eng.htm"
                ),
                description=(
                    "Optional Statistics Canada Daily article confirming Labour Force Survey "
                    "release timing and next release date."
                ),
            ),
            SourceDocument(
                key=_KEY_BOC,
                url=_URL_BOC_KEY,
                description="Bank of Canada key interest rate / fixed announcement schedule.",
            ),
        )
        validate_source_plan(plan)
        return plan

    def parse_documents(
        self,
        documents: Mapping[str, str],
        *,
        now: datetime,
        fetched_at: str,
    ) -> list[EconomicReleaseEvent]:
        global GAPS

        if not isinstance(documents, Mapping):
            GAPS = ()
            return []

        clock_body = documents.get(_KEY_CLOCK) or ""
        has_standing_clock = bool(_STANDING_CLOCK_SENTENCE_RE.search(clock_body))

        primary_text = documents.get(_KEY_PRIMARY) or ""

        all_events: list[EconomicReleaseEvent] = []

        # StatCan: annual PDF-style tables, else an HTML cal2-style schedule body
        statcan_pdf_events = _events_from_primary(
            primary_text,
            has_standing_clock=has_standing_clock,
            fetched_at=fetched_at,
            source_url=_URL_STATCAN_PDF,
        )
        if statcan_pdf_events:
            all_events.extend(statcan_pdf_events)
        else:
            cal2_html = (
                primary_text
                if 'class="rtitle"' in primary_text
                else clock_body
            )
            all_events.extend(
                _events_from_statcan_cal2_html(
                    cal2_html,
                    now=now,
                    has_standing_clock=has_standing_clock,
                    fetched_at=fetched_at,
                    source_url=_URL_STATCAN_CLOCK,
                )
            )

        # Optional LFS Daily (confirmation; does not duplicate event_ids)
        lfs_html = documents.get(_KEY_LFS_DAILY) or ""
        lfs_url = (
            "https://www150.statcan.gc.ca/n1/daily-quotidien/261106/dq261106a-eng.htm"
        )
        all_events.extend(
            _parse_lfs_daily_html(
                lfs_html,
                has_standing_clock=has_standing_clock,
                fetched_at=fetched_at,
                source_url=lfs_url,
            )
        )

        boc_html = documents.get(_KEY_BOC) or ""
        boc_events, boc_gaps = _parse_boc_announcements(
            boc_html,
            now=now,
            fetched_at=fetched_at,
            source_url=_URL_BOC_KEY,
        )
        all_events.extend(boc_events)

        GAPS = boc_gaps

        # Drop duplicate ids; tolerate garbage (parsers return nothing)
        merged = _dedupe_by_event_id(all_events)

        try:
            validate_events(merged)
        except ValueError:
            GAPS = ()
            return []

        if not merged:
            GAPS = ()

        return merged


ADAPTER = CaOfficialSchedule()
GAPS: tuple[str, ...] = ()


__all__ = ["ADAPTER", "GAPS", "CaOfficialSchedule"]
