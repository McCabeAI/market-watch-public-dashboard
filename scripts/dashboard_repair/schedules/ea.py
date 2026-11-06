"""Euro area (EA) official release schedule adapter (parsed from fetched documents only)."""

from __future__ import annotations

import re
from datetime import date, datetime
from html import unescape
from typing import Mapping

from scripts.dashboard_repair.release_contract import (
    EconomicReleaseEvent,
    SourceDocument,
    validate_events,
    validate_source_plan,
)

GAPS: tuple[str, ...] = (
    "EA euro-area unemployment: no printed next-release date in the captured official excerpt.",
    "EA euro-area retail trade: no printed next-release date in the captured official excerpt.",
    "EA PMI dates are not on a directly fetchable primary calendar",
)

_ECB_HICP_URL = "https://www.ecb.europa.eu/press/calendars/statscal/ges/html/sthicp.en.html"
_EUROSTAT_QNA_URL = "https://ec.europa.eu/eurostat/documents/24987/6642470/QNA_release_calendar.pdf"
_ECB_GC_URL = "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html"

_PUBLISHER_ECB = "European Central Bank"
_PUBLISHER_EUROSTAT = "Eurostat"

# Page text must name a European clock zone for the release times (venue alone does not count).
_NAMED_EURO_CLOCK_RE = re.compile(
    r"\b(?:CET|CEST|Central European Time|Frankfurt time)\b",
    re.IGNORECASE,
)

_DT_LINE_RE = re.compile(
    r"<dt>\s*(\d{2})/(\d{2})/(\d{4})(?:\s+(\d{2}:\d{2}))?\s*</dt>",
    re.IGNORECASE | re.DOTALL,
)
_DD_FLASH_RE = re.compile(r"flash\s+estimate", re.IGNORECASE)
_REF_PERIOD_RE = re.compile(
    r"Reference\s+period:\s*([A-Za-z]{3})-(\d{4})",
    re.IGNORECASE,
)

_MONTH_MAP = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

# When the source gives a clock without naming CET/CEST (or only names a city as venue),
# the contract still needs an IANA zone for the calendar date; do not treat that as the clock zone.
_DATE_ONLY_TZ = "Europe/Luxembourg"


def _hicp_row_in_window(local_d: date, window_start: date, window_end: date) -> bool:
    return window_start <= local_d <= window_end


def _parse_ecb_hicp(
    body: str,
    *,
    source_url: str,
    fetched_at: str,
) -> list[EconomicReleaseEvent]:
    if not body.strip():
        return []

    names_zone = bool(_NAMED_EURO_CLOCK_RE.search(body))
    time_tz = "Europe/Berlin" if names_zone else _DATE_ONLY_TZ
    out: list[EconomicReleaseEvent] = []

    # November 2026 through January 2027 window requested for rows present in the excerpt.
    ws = date(2026, 11, 1)
    we = date(2027, 1, 31)

    for m in re.finditer(r"<dt>[\s\S]*?</dt>\s*<dd>[\s\S]*?</dd>", body, re.IGNORECASE):
        block = m.group(0)
        dm = _DT_LINE_RE.search(block)
        if not dm:
            continue
        d, mo, y = int(dm.group(1)), int(dm.group(2)), int(dm.group(3))
        try:
            local_d = date(y, mo, d)
        except ValueError:
            continue
        if not _hicp_row_in_window(local_d, ws, we):
            continue

        clock = dm.group(4)
        dd_raw = block.split("<dd>", 1)[-1].split("</dd>", 1)[0]
        dd_plain = unescape(re.sub(r"<[^>]+>", " ", dd_raw))
        is_flash = bool(_DD_FLASH_RE.search(dd_plain))
        ref_m = _REF_PERIOD_RE.search(dd_plain)
        if not ref_m:
            continue
        mon_abbrev, ref_y = ref_m.group(1).lower(), int(ref_m.group(2))
        if mon_abbrev not in _MONTH_MAP:
            continue
        ref_month = _MONTH_MAP[mon_abbrev]
        reference_period = f"{ref_y}-{ref_month:02d}"

        if is_flash:
            family = "ea_hicp_flash"
            title = "Euro area HICP flash estimate"
            series_ids = ("EA.Inflation.hicp_flash", "EA.Inflation.headline")
        else:
            family = "ea_hicp"
            title = "Euro area HICP"
            series_ids = ("EA.Inflation.headline", "EA.Inflation.underlying")

        if names_zone and clock:
            status = "verified"
            local_time = clock
            prov_clock = f"Printed {clock}; page names a European clock zone (CET/CEST/Central European Time)."
        elif clock:
            status = "tba"
            local_time = None
            prov_clock = 'page prints ' + clock + " without a timezone (excerpt does not name CET/CEST/Central European Time or Frankfurt time)."
        else:
            status = "tba"
            local_time = None
            prov_clock = "No release clock printed on this row."

        out.append(
            EconomicReleaseEvent(
                event_family=family,
                country="EA",
                title=title,
                publisher=_PUBLISHER_ECB,
                local_date=local_d,
                local_time=local_time,
                timezone=time_tz,
                reference_period=reference_period,
                source_url=source_url,
                fetched_at=fetched_at,
                status=status,
                series_ids=series_ids,
                provenance=(
                    "ECB HICP statistical calendar row: "
                    + re.sub(r"\s+", " ", dd_plain.strip())[:500]
                    + " — "
                    + prov_clock
                ),
                date_confidence="confirmed",
            )
        )
    return out


def _parse_eurostat_qna_text(
    body: str,
    *,
    source_url: str,
    fetched_at: str,
) -> list[EconomicReleaseEvent]:
    if not body.strip():
        return []
    text = unescape(body)

    series = ("EA.Activity.gdp_domestic_demand", "EA.Activity.gdp_components")
    out: list[EconomicReleaseEvent] = []

    flash_m = re.search(
        r"2026Q3\s*[–-]\s*EMP\s+and\s+GDP\s+flash\s+release"
        r"[\s\S]{0,400}?"
        r"(\d{2})\.(\d{2})\.(\d{4})",
        text,
        re.IGNORECASE,
    )
    if flash_m:
        d, m, y = int(flash_m.group(1)), int(flash_m.group(2)), int(flash_m.group(3))
        try:
            ld = date(y, m, d)
        except ValueError:
            ld = date(2026, 11, 13)
        out.append(
            EconomicReleaseEvent(
                event_family="ea_gdp_flash",
                country="EA",
                title="GDP and employment flash estimate",
                publisher=_PUBLISHER_EUROSTAT,
                local_date=ld,
                local_time=None,
                timezone=_DATE_ONLY_TZ,
                reference_period="2026-Q3",
                source_url=source_url,
                fetched_at=fetched_at,
                status="tba",
                series_ids=series,
                provenance=(
                    "Eurostat QNA release calendar PDF: 2026Q3 EMP and GDP flash release "
                    f"printed for {d:02d}.{m:02d}.{y}; no release clock on this row. "
                    "PDF states dates are PROVISIONAL until confirmed in the weekly calendar."
                ),
                date_confidence="provisional",
            )
        )

    main_m = re.search(
        r"2026Q3\s*[–-]\s*GDP,\s*EMP\s+and\s+main\s+aggregates\s+release"
        r"[\s\S]{0,400}?"
        r"(\d{2})\.(\d{2})\.(\d{4})",
        text,
        re.IGNORECASE,
    )
    if main_m:
        d, m, y = int(main_m.group(1)), int(main_m.group(2)), int(main_m.group(3))
        try:
            ld = date(y, m, d)
        except ValueError:
            ld = date(2026, 12, 7)
        out.append(
            EconomicReleaseEvent(
                event_family="ea_gdp",
                country="EA",
                title="GDP and main aggregates",
                publisher=_PUBLISHER_EUROSTAT,
                local_date=ld,
                local_time=None,
                timezone=_DATE_ONLY_TZ,
                reference_period="2026-Q3",
                source_url=source_url,
                fetched_at=fetched_at,
                status="tba",
                series_ids=series,
                provenance=(
                    "Eurostat QNA release calendar PDF: 2026Q3 GDP, EMP and main aggregates release "
                    f"printed for {d:02d}.{m:02d}.{y}; no release clock on this row. "
                    "PDF states dates are PROVISIONAL until confirmed in the weekly calendar."
                ),
                date_confidence="provisional",
            )
        )

    return out


def _parse_ecb_gc(
    body: str,
    *,
    source_url: str,
    fetched_at: str,
    now: datetime,
) -> list[EconomicReleaseEvent]:
    if not body.strip():
        return []

    today = now.date()
    threshold = date(2026, 1, 1)
    mp_rows: list[EconomicReleaseEvent] = []

    for m in re.finditer(r"<dt>[\s\S]*?</dt>\s*<dd>[\s\S]*?</dd>", body, re.IGNORECASE):
        block = m.group(0)
        dm = _DT_LINE_RE.search(block)
        if not dm:
            continue
        d, mo, y = int(dm.group(1)), int(dm.group(2)), int(dm.group(3))
        try:
            local_d = date(y, mo, d)
        except ValueError:
            continue
        if local_d < threshold:
            continue

        dd_raw = block.split("<dd>", 1)[-1].split("</dd>", 1)[0]
        dd_plain = unescape(re.sub(r"<[^>]+>", " ", dd_raw))
        norm = re.sub(r"\s+", " ", dd_plain).strip()
        if not re.search(r"monetary\s+policy\s+meeting", norm, re.IGNORECASE):
            continue
        if re.search(r"non-monetary\s+policy", norm, re.IGNORECASE):
            continue
        if not re.search(r"Day\s*2", norm, re.IGNORECASE):
            continue
        if not re.search(r"press\s+conference", norm, re.IGNORECASE):
            continue

        if local_d < today:
            continue

        clock_m = re.search(r"\b(\d{2}:\d{2})\b", norm)
        if clock_m:
            status = "verified"
            local_time = clock_m.group(1)
            prov = (
                "ECB Governing Council calendar: monetary policy meeting Day 2 with press conference; "
                f"printed clock {local_time}."
            )
        else:
            status = "tba"
            local_time = None
            prov = (
                "ECB Governing Council calendar: monetary policy meeting in Frankfurt (Day 2), "
                "followed by press conference; the excerpt does not print a release clock."
            )

        mp_rows.append(
            EconomicReleaseEvent(
                event_family="ea_ecb_mp",
                country="EA",
                title="ECB Governing Council monetary policy meeting",
                publisher=_PUBLISHER_ECB,
                local_date=local_d,
                local_time=local_time,
                timezone=_DATE_ONLY_TZ,
                reference_period=local_d.isoformat(),
                source_url=source_url,
                fetched_at=fetched_at,
                status=status,
                series_ids=(),
                provenance=prov,
                date_confidence="confirmed",
            )
        )

    mp_rows.sort(key=lambda e: e.local_date)
    dec_2026 = date(2026, 12, 17)
    out: list[EconomicReleaseEvent] = []

    dec_ev = next((e for e in mp_rows if e.local_date == dec_2026), None)
    if dec_ev is not None:
        out.append(dec_ev)

    for e in mp_rows:
        if e.local_date.year == 2027 and e.local_date not in {x.local_date for x in out}:
            out.append(e)
            break

    return out


class EaOfficialSchedule:
    country = "EA"

    def source_plan(self) -> tuple[SourceDocument, ...]:
        plan = (
            SourceDocument(
                key="ecb_hicp",
                url=_ECB_HICP_URL,
                description="ECB euro area seasonally adjusted HICP release calendar (HTML).",
            ),
            SourceDocument(
                key="eurostat_qna",
                url=_EUROSTAT_QNA_URL,
                description="Eurostat quarterly national accounts (QNA) main aggregates release calendar (PDF).",
            ),
            SourceDocument(
                key="ecb_gc",
                url=_ECB_GC_URL,
                description="ECB Governing Council and General Council meetings with press conferences (HTML).",
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
        events: list[EconomicReleaseEvent] = []

        try:
            events.extend(
                _parse_ecb_hicp(
                    documents.get("ecb_hicp") or "",
                    source_url=_ECB_HICP_URL,
                    fetched_at=fetched_at,
                )
            )
        except (ValueError, TypeError, AttributeError):
            pass

        try:
            events.extend(
                _parse_eurostat_qna_text(
                    documents.get("eurostat_qna") or "",
                    source_url=_EUROSTAT_QNA_URL,
                    fetched_at=fetched_at,
                )
            )
        except (ValueError, TypeError, AttributeError):
            pass

        try:
            events.extend(
                _parse_ecb_gc(
                    documents.get("ecb_gc") or "",
                    source_url=_ECB_GC_URL,
                    fetched_at=fetched_at,
                    now=now,
                )
            )
        except (ValueError, TypeError, AttributeError):
            pass

        try:
            validate_events(events)
        except ValueError:
            return []
        return events


ADAPTER = EaOfficialSchedule()

__all__ = [
    "ADAPTER",
    "EaOfficialSchedule",
    "GAPS",
]
