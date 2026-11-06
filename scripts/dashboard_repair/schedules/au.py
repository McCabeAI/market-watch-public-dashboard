"""Australia (AU) economic release schedule adapter (official ABS + RBA sources only)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from html import unescape
from typing import Mapping
from zoneinfo import ZoneInfo

from scripts.dashboard_repair.release_contract import (
    EconomicReleaseEvent,
    SourceDocument,
    validate_events,
    validate_source_plan,
)

AU_ZONE = ZoneInfo("Australia/Sydney")

_ABS_PUBLISHER = "Australian Bureau of Statistics"
_RBA_PUBLISHER = "Reserve Bank of Australia"

_URL_ABS_WPI = (
    "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/"
    "wage-price-index-australia"
)
_URL_ABS_MONTH = "https://www.abs.gov.au/release-calendar/future-releases-calendar/202611"
_URL_RBA_DECISIONS = "https://www.rba.gov.au/monetary-policy/int-rate-decisions/"

# Printed clock in publisher text (12-hour); never infer from cadence.
_CLOCK_RE = re.compile(
    r"(?P<h>[0-1]?\d):(?P<m>\d{2})\s*(?P<ap>am|pm)\b",
    re.IGNORECASE,
)
_DMY_RE = re.compile(
    r"(?P<d>\d{1,2})/(?P<mon>\d{1,2})/(?P<y>\d{4})",
)
# ABS calendar row: event name + reference + time element
_CAL_EVENT_RE = re.compile(
    r'<strong[^>]*class="event-name"[^>]*>\s*([^<]+)</strong>\s*'
    r'<span[^>]*class="reference-period-value"[^>]*>\s*([^<]+)</span>[^<]*'
    r'<span[^>]*class="event-date"[^>]*>\s*'
    r'<time[^>]*datetime="(?P<iso>[^"]+)"[^>]*class="datetime"[^>]*>'
    r"(?P<inner>.*?)</time>",
    re.IGNORECASE | re.DOTALL,
)
# WPI product page: views-row blocks
_WPI_ROW_RE = re.compile(
    r'<div class="views-row">(?P<body>Wage Price Index, Australia.+?</div>)',
    re.IGNORECASE | re.DOTALL,
)

_MONTH_TO_Q = {
    "january": "Q1",
    "february": "Q1",
    "march": "Q1",
    "april": "Q2",
    "may": "Q2",
    "june": "Q2",
    "july": "Q3",
    "august": "Q3",
    "september": "Q3",
    "october": "Q4",
    "november": "Q4",
    "december": "Q4",
}


def _strip_tags(fragment: str) -> str:
    return re.sub(r"<[^>]+>", " ", fragment)


def _clock_from_printed(text: str) -> str | None:
    """Return HH:MM 24-hour from printed am/pm text, or None when no clock is printed."""
    m = _CLOCK_RE.search(text.replace("\xa0", " "))
    if not m:
        return None
    h = int(m.group("h"))
    minute = int(m.group("m"))
    ap = m.group("ap").lower()
    if ap == "pm" and h != 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return f"{h:02d}:{minute:02d}"


def _parse_iso_date(iso: str) -> date | None:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(AU_ZONE).date()


def _quarter_label_from_month_year(month_name: str, year: int) -> str:
    mq = _MONTH_TO_Q.get(month_name.strip().lower(), "")
    if not mq:
        return ""
    return f"{year}-{mq}"


def _wpi_reference_from_title(title_tail: str) -> str:
    """Derive reference_period like 2026-Q3 from 'September 2026' segment in title text."""
    tail = title_tail.strip()
    m = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
        tail,
        re.IGNORECASE,
    )
    if not m:
        return ""
    month = m.group(1).lower()
    year = int(m.group(2))
    return _quarter_label_from_month_year(month, year)


def _parse_abs_wpi(
    html: str,
    *,
    fetched_at: str,
    source_url: str,
) -> list[EconomicReleaseEvent]:
    out: list[EconomicReleaseEvent] = []
    if not html or not html.strip():
        return out
    for m in _WPI_ROW_RE.finditer(html):
        body = m.group("body")
        if "Wage Price Index, Australia" not in body:
            continue
        tmatch = re.search(r"<time[^>]*>([^<]+)</time>", body)
        if not tmatch:
            continue
        printed = unescape(tmatch.group(1)).strip()
        dmy = _DMY_RE.search(printed)
        if not dmy:
            continue
        local_d = date(int(dmy.group("y")), int(dmy.group("mon")), int(dmy.group("d")))
        title_line = body.split("<", 1)[0].strip()
        title_line = re.sub(r"\s+", " ", title_line)
        ref = _wpi_reference_from_title(
            title_line.replace("Wage Price Index, Australia,", "").strip()
        )
        if not ref:
            continue
        clock = _clock_from_printed(printed)
        provenance = f"ABS WPI product page (trimmed): {title_line[:120]} | {printed[:80]}"
        if clock is not None:
            status = "verified"
            local_time = clock
        else:
            status = "tba"
            local_time = None
        out.append(
            EconomicReleaseEvent(
                event_family="au_wpi",
                country="AU",
                title="Wage Price Index",
                publisher=_ABS_PUBLISHER,
                local_date=local_d,
                local_time=local_time,
                timezone="Australia/Sydney",
                reference_period=ref,
                source_url=source_url,
                fetched_at=fetched_at,
                status=status,
                series_ids=("AU.Labor.wages",),
                provenance=provenance,
            )
        )
    return out


def _calendar_row_event(
    name: str,
    reference_label: str,
    iso: str,
    inner_html: str,
    *,
    event_family: str,
    title: str,
    series_ids: tuple[str, ...],
    source_url: str,
    fetched_at: str,
    reference_formatter: str | None = None,
) -> EconomicReleaseEvent | None:
    local_d = _parse_iso_date(iso)
    if local_d is None:
        return None
    inner = unescape(_strip_tags(inner_html)).strip()
    clock = _clock_from_printed(inner) if inner else None
    if clock is not None:
        status = "verified"
        local_time = clock
    else:
        status = "tba"
        local_time = None

    ref = reference_label.strip()
    if reference_formatter == "yyyymm":
        # "October 2026" -> 2026-10
        rm = re.match(r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})$", ref, re.I)
        if rm:
            month_names = {
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
            mi = month_names[rm.group(1).lower()]
            ref = f"{rm.group(2)}-{mi:02d}"
        else:
            ref = ref.replace(" ", "-")[:20]

    prov_name = unescape(name).strip()
    prov = (
        f"ABS November 2026 future-release calendar (trimmed): {prov_name} | "
        f"reference {reference_label.strip()} | time cell: {inner[:60]}"
    )
    return EconomicReleaseEvent(
        event_family=event_family,
        country="AU",
        title=title,
        publisher=_ABS_PUBLISHER,
        local_date=local_d,
        local_time=local_time,
        timezone="Australia/Sydney",
        reference_period=ref,
        source_url=source_url,
        fetched_at=fetched_at,
        status=status,
        series_ids=series_ids,
        provenance=prov,
    )


def _parse_abs_month_calendar(
    html: str,
    *,
    fetched_at: str,
    source_url: str,
    skip_wpi: bool,
) -> list[EconomicReleaseEvent]:
    out: list[EconomicReleaseEvent] = []
    if not html or not html.strip():
        return out
    for m in _CAL_EVENT_RE.finditer(html):
        raw_name = m.group(1)
        ref_label = m.group(2)
        iso = m.group("iso")
        inner = m.group("inner")
        name_l = unescape(raw_name).strip().lower()
        if skip_wpi and "wage price index" in name_l:
            continue
        ev: EconomicReleaseEvent | None = None
        if "labour force" in name_l and "australia" in name_l:
            ev = _calendar_row_event(
                raw_name,
                ref_label,
                iso,
                inner,
                event_family="au_labour_force",
                title="Labour Force, Australia",
                series_ids=(
                    "AU.Labor.unemployment",
                    "AU.Labor.employment",
                    "AU.Labor.participation",
                ),
                source_url=source_url,
                fetched_at=fetched_at,
                reference_formatter="yyyymm",
            )
        elif "consumer price index" in name_l and "australia" in name_l:
            ev = _calendar_row_event(
                raw_name,
                ref_label,
                iso,
                inner,
                event_family="au_cpi",
                title="Consumer Price Index, Australia",
                series_ids=("AU.Inflation.headline", "AU.Inflation.underlying"),
                source_url=source_url,
                fetched_at=fetched_at,
                reference_formatter="yyyymm",
            )
        elif "monthly household spending indicator" in name_l:
            ev = _calendar_row_event(
                raw_name,
                ref_label,
                iso,
                inner,
                event_family="au_household_spending",
                title="Monthly Household Spending Indicator",
                series_ids=("AU.Consumer.spending",),
                source_url=source_url,
                fetched_at=fetched_at,
                reference_formatter="yyyymm",
            )
        elif "wage price index" in name_l and not skip_wpi:
            rstrip = ref_label.strip()
            rm = re.match(
                r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})$",
                rstrip,
                re.I,
            )
            ref_q = _quarter_label_from_month_year(rm.group(1), int(rm.group(2))) if rm else ""
            if ref_q:
                ev = _calendar_row_event(
                    raw_name,
                    ref_label,
                    iso,
                    inner,
                    event_family="au_wpi",
                    title="Wage Price Index",
                    series_ids=("AU.Labor.wages",),
                    source_url=source_url,
                    fetched_at=fetched_at,
                    reference_formatter=None,
                )
                if ev is not None:
                    ev = replace(ev, reference_period=ref_q)
            else:
                ev = None
        if ev is not None:
            out.append(ev)
    return out


_RBA_ITEM_RE = re.compile(
    r'<a href="/media-releases/\d{4}/mr-[^"]+\.html">([^<]+)</a>',
    re.IGNORECASE,
)


def _parse_rba_future_decisions(
    html: str,
    *,
    now: datetime,
    fetched_at: str,
    source_url: str,
) -> list[EconomicReleaseEvent]:
    out: list[EconomicReleaseEvent] = []
    if not html or not html.strip():
        return out
    today_sydney = now.astimezone(AU_ZONE).date()
    month_lookup = {
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
    for m in _RBA_ITEM_RE.finditer(html):
        label = unescape(m.group(1)).strip()
        rm = re.match(
            r"^(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})$",
            label,
            re.IGNORECASE,
        )
        if not rm:
            continue
        d = date(int(rm.group(3)), month_lookup[rm.group(2).lower()], int(rm.group(1)))
        if d <= today_sydney:
            continue
        prov = (
            "RBA Monetary Policy Decisions index (trimmed): list entry "
            f"\"{label}\" -> {m.group(0)[:120]}"
        )
        out.append(
            EconomicReleaseEvent(
                event_family="au_rba",
                country="AU",
                title="RBA monetary policy decision",
                publisher=_RBA_PUBLISHER,
                local_date=d,
                local_time=None,
                timezone="Australia/Sydney",
                reference_period="",
                source_url=source_url,
                fetched_at=fetched_at,
                status="tba",
                series_ids=(),
                provenance=prov,
            )
        )
    return out


def _dedupe_prefer_wpi_product(events: list[EconomicReleaseEvent]) -> list[EconomicReleaseEvent]:
    """Drop duplicate event_id; prefer WPI rows from the product page over the calendar."""
    by_id: dict[str, EconomicReleaseEvent] = {}
    product_wpi_ids: set[str] = set()
    for ev in events:
        if ev.event_family == "au_wpi" and "/wage-price-index-australia" in ev.source_url:
            product_wpi_ids.add(ev.event_id())
    for ev in events:
        eid = ev.event_id()
        if eid in by_id:
            continue
        if (
            ev.event_family == "au_wpi"
            and "/future-releases-calendar/" in ev.source_url
            and eid in product_wpi_ids
        ):
            continue
        by_id[eid] = ev
    return list(by_id.values())


@dataclass
class AuOfficialSchedule:
    country: str = "AU"
    _gaps: tuple[str, ...] = field(default_factory=tuple)

    def source_plan(self) -> tuple[SourceDocument, ...]:
        plan = (
            SourceDocument(
                key="abs_wpi",
                url=_URL_ABS_WPI,
                description="ABS Wage Price Index product page (future releases block).",
            ),
            SourceDocument(
                key="abs_month",
                url=_URL_ABS_MONTH,
                description="ABS future releases calendar for November 2026.",
            ),
            SourceDocument(
                key="rba_int_rate",
                url=_URL_RBA_DECISIONS,
                description="RBA monetary policy decision / media release schedule (2026 index).",
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
        gaps_list: list[str] = []
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        wpi_html = documents.get("abs_wpi") or ""
        month_html = documents.get("abs_month") or ""
        rba_html = documents.get("rba_int_rate") or ""

        events: list[EconomicReleaseEvent] = []
        events.extend(
            _parse_abs_wpi(wpi_html, fetched_at=fetched_at, source_url=_URL_ABS_WPI)
        )
        skip_cal_wpi = bool(wpi_html.strip())
        events.extend(
            _parse_abs_month_calendar(
                month_html,
                fetched_at=fetched_at,
                source_url=_URL_ABS_MONTH,
                skip_wpi=skip_cal_wpi,
            )
        )
        rba_future = _parse_rba_future_decisions(
            rba_html,
            now=now,
            fetched_at=fetched_at,
            source_url=_URL_RBA_DECISIONS,
        )
        events.extend(rba_future)

        if month_html.strip() and "retail trade" not in month_html.lower():
            gaps_list.append(
                "ABS retail trade is not on the November 2026 future-release calendar; "
                "household spending is the consumer release when printed."
            )

        if rba_html.strip() and not rba_future:
            gaps_list.append(
                "No explicit future RBA monetary policy decision date found on "
                f"{_URL_RBA_DECISIONS} at parse time."
            )

        merged = _dedupe_prefer_wpi_product(events)
        validate_events(merged)
        self._gaps = tuple(gaps_list)
        GAPS = self._gaps
        return merged

    @property
    def gaps(self) -> tuple[str, ...]:
        return self._gaps


ADAPTER = AuOfficialSchedule()
GAPS: tuple[str, ...] = ()

__all__ = ["ADAPTER", "AuOfficialSchedule", "GAPS"]
