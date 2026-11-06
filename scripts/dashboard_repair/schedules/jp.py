"""Japan economic release schedule: parse official HTML bodies only (no network)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from html import unescape
from typing import Mapping

from scripts.dashboard_repair.release_contract import (
    EconomicReleaseEvent,
    SourceDocument,
    validate_events,
    validate_source_plan,
)

_TZ = "Asia/Tokyo"

# Populated by :meth:`JpOfficialSchedule.parse_documents` (tuple for tests / inspection).
GAPS: tuple[str, ...] = ()

_APPROX_EN_RE = re.compile(
    r"(?:early|middle|late)\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)",
    re.I,
)
_APPROX_JP_RE = re.compile(
    r"(?:\d{1,2}|[一二三四五六七八九十]+)?\s*月\s*(?:上旬|中旬|下旬|末)"
)
_HAS_DAY_NUMBER_RE = re.compile(r"\b\d{1,2}\b")


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


def _clean_cell(html: str) -> str:
    t = unescape(_strip_tags(html))
    return re.sub(r"\s+", " ", t).strip()


def _parse_am_pm_clock(raw: str) -> str | None:
    """Return HH:MM 24h from e.g. '8:50AM (JST)' or '8:50 a.m.' or '08:30'."""
    s = raw.strip()
    m = re.search(
        r"(?P<h>\d{1,2}):(?P<m>\d{2})\s*(?:(?P<ap>[AaPp])\.?[Mm]\.?)?",
        s,
    )
    if not m:
        return None
    h = int(m.group("h"))
    minute = int(m.group("m"))
    ap = m.group("ap")
    if ap:
        ap_u = ap.upper()
        if ap_u == "P" and h != 12:
            h += 12
        if ap_u == "A" and h == 12:
            h = 0
    if h > 23 or minute > 59:
        return None
    return f"{h:02d}:{minute:02d}"


def _parse_english_date(cell: str) -> date | None:
    """Parse 'Monday, November 16, 2026' style."""
    m = re.search(
        r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
        r"(\d{1,2}),\s+(\d{4})",
        cell,
        re.I,
    )
    if not m:
        return None
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
    mon = month_names[m.group(1).lower()]
    d = int(m.group(2))
    y = int(m.group(3))
    try:
        return date(y, mon, d)
    except ValueError:
        return None


def _gdp_quarter_label(period_cell: str) -> tuple[str, str] | None:
    """
    Map reporting period cell to (reference_period, preliminary_kind).
    preliminary_kind: 'first' | 'second'
    """
    m = re.search(
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.\s*[-–]\s*"
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.\s*(\d{4})",
        period_cell,
        re.I,
    )
    if not m:
        return None
    qmap = {
        ("Jan", "Mar"): "Q1",
        ("Apr", "Jun"): "Q2",
        ("Jul", "Sep"): "Q3",
        ("Oct", "Dec"): "Q4",
    }
    key = (m.group(1), m.group(2))
    q = qmap.get(key)
    if not q:
        return None
    year = m.group(3)
    ref = f"{year}-{q}"
    pre_m = re.search(r"First|Second", period_cell, re.I)
    if not pre_m:
        return None
    kind = (
        "first"
        if pre_m.group(0).lower().startswith("first")
        else "second"
    )
    return ref, kind


def _parse_cao_gdp(
    html: str,
    *,
    source_url: str,
    fetched_at: str,
) -> list[EconomicReleaseEvent]:
    events: list[EconomicReleaseEvent] = []
    m_block = re.search(
        r"<h2[^>]*>.*?Quarterly Estimates of GDP.*?</h2>\s*"
        r"<table[^>]*>.*?</table>",
        html,
        re.I | re.DOTALL,
    )
    if not m_block:
        return events
    tab = m_block.group(0)
    for row_m in re.finditer(r"<tr[^>]*>(.*?)</tr>", tab, re.I | re.DOTALL):
        row = row_m.group(1)
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.I | re.DOTALL)
        if len(cells) < 3:
            continue
        period_c = _clean_cell(cells[0])
        date_c = _clean_cell(cells[1])
        time_c = _clean_cell(cells[2])
        if _APPROX_JP_RE.search(date_c) or _APPROX_EN_RE.search(date_c):
            continue
        if not _HAS_DAY_NUMBER_RE.search(date_c):
            continue
        if date_c.strip().upper() == "TBA":
            continue
        parsed = _gdp_quarter_label(period_c)
        if not parsed:
            continue
        ref, kind = parsed
        d = _parse_english_date(date_c)
        if d is None:
            continue
        if time_c in ("-", ""):
            continue
        clock = _parse_am_pm_clock(time_c)
        if clock is None:
            continue
        if kind == "first":
            title = "Quarterly GDP first preliminary"
        else:
            title = "Quarterly GDP second preliminary"
        events.append(
            EconomicReleaseEvent(
                event_family="jp_gdp",
                country="JP",
                title=title,
                publisher="Cabinet Office",
                local_date=d,
                local_time=clock,
                timezone=_TZ,
                reference_period=ref,
                source_url=source_url,
                fetched_at=fetched_at,
                status="verified",
                series_ids=(
                    "JP.Activity.gdp_domestic_demand",
                    "JP.Activity.domestic_demand",
                ),
                provenance=(
                    "Cabinet Office GDP schedule row: "
                    f"{period_c!s} / {date_c!s} / {time_c!s}"
                ),
            )
        )
    return events


def _parse_yyyy_mm_jp(ref: str) -> str | None:
    """'2026年10月分' / full-width digits -> '2026-10'."""
    def norm(s: str) -> str:
        out: list[str] = []
        for c in s:
            o = ord(c)
            if 0xFF10 <= o <= 0xFF19:
                out.append(chr(o - 0xFF10 + ord("0")))
            else:
                out.append(c)
        return "".join(out)

    s = norm(ref)
    m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月(?:分)?", s)
    if not m:
        return None
    y, mo = m.group(1), int(m.group(2))
    if mo < 1 or mo > 12:
        return None
    return f"{y}-{mo:02d}"


def _estat_text_blob(html: str) -> str:
    return re.sub(r"\s+", " ", unescape(_strip_tags(html))).strip()


_MONTH_ABBREV = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sept": 9,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def _ref_from_parenthetical(desc: str) -> str:
    """Prefer the last (…年…月分) token inside trailing parentheses."""
    paren_m = re.search(r"\(([^)]+)\)\s*$", desc.strip())
    if not paren_m:
        return ""
    inside = paren_m.group(1)
    found: list[str] = []
    for m in re.finditer(
        r"(\d{4}|(?:[０-９]{4}))\s*年\s*(\d{1,2}|(?:[０-９]{1,2}))\s*月(?:分)?",
        inside,
    ):
        frag = m.group(0)
        ref = _parse_yyyy_mm_jp(frag)
        if ref:
            found.append(ref)
    return found[-1] if found else ""


def _iter_estat_segments(text: str) -> list[str]:
    """Split e-Stat calendar text into per-release segments after YYYY-MM-DD HH:MM."""
    idx = text.find("公表内容")
    blob = text[idx:] if idx != -1 else text
    pat = re.compile(r"\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2}")
    positions = [m.start() for m in pat.finditer(blob)]
    if not positions:
        return []
    out: list[str] = []
    for i, start in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else len(blob)
        seg = blob[start:end].strip()
        if seg:
            out.append(seg)
    return out


def _parse_statgojp_cpi_schedule(
    html: str, *, source_url: str, fetched_at: str
) -> list[EconomicReleaseEvent]:
    """Parse Statistics Bureau English CPI 'Schedule of Release' Japan column (national CPI)."""
    events: list[EconomicReleaseEvent] = []
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
    cycle_year = 2026
    lu = re.search(
        r"Last\s+Update\s*:\s*(?:\d{1,2}\s+)?(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
        html,
        re.I,
    )
    if lu:
        cycle_year = int(lu.group(1))

    tab_m = re.search(
        r'<table[^>]*class="datatable"[^>]*>(.*?)</table>',
        html,
        re.I | re.DOTALL,
    )
    tbody = tab_m.group(1) if tab_m else html

    for tr in re.finditer(r"<tr[^>]*>(.*?)</tr>", tbody, re.I | re.DOTALL):
        row_inner = tr.group(1)
        if "<th" in row_inner.lower():
            continue
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row_inner, re.I | re.DOTALL)
        if len(cells) < 2:
            continue
        sm_raw = re.sub(r"\s+", " ", _clean_cell(cells[0]))
        rel_jp = re.sub(r"\s+", " ", _clean_cell(cells[1]))
        if "survey month" in sm_raw.lower():
            continue
        sm_m = re.match(
            r"(January|February|March|April|May|June|July|August|September|October|November|December)"
            r"(?:,\s*(\d{4}))?",
            sm_raw,
            re.I,
        )
        if not sm_m:
            continue
        survey_month = month_names[sm_m.group(1).lower()]
        survey_year = int(sm_m.group(2)) if sm_m.group(2) else None

        rel_m = re.match(
            r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
            r"(\d{1,2})(?:,\s*(\d{4}))?",
            rel_jp,
            re.I,
        )
        if not rel_m:
            continue
        rel_mon = month_names[rel_m.group(1).lower()]
        rel_day = int(rel_m.group(2))
        rel_y_ex = rel_m.group(3)

        if rel_y_ex:
            rel_year = int(rel_y_ex)
        elif survey_year is not None:
            rel_year = survey_year + (1 if rel_mon < survey_month else 0)
        else:
            rel_year = cycle_year + (1 if rel_mon < survey_month else 0)

        try:
            local_d = date(rel_year, rel_mon, rel_day)
        except ValueError:
            continue

        if survey_year is not None:
            ref_year = survey_year
        else:
            ref_year = rel_year if rel_mon > survey_month else rel_year - 1
        ref = f"{ref_year}-{survey_month:02d}"

        events.append(
            EconomicReleaseEvent(
                event_family="jp_cpi",
                country="JP",
                title="Consumer Price Index, national",
                publisher="Statistics Bureau of Japan",
                local_date=local_d,
                local_time=None,
                timezone=_TZ,
                reference_period=ref,
                source_url=source_url,
                fetched_at=fetched_at,
                status="tba",
                series_ids=("JP.Inflation.headline", "JP.Inflation.underlying"),
                provenance=(
                    "Statistics Bureau CPI schedule (Japan column; release time not printed): "
                    f"survey {sm_raw!s}; release {rel_jp!s}"
                ),
            )
        )
    return events


def _parse_estat_calendar(
    html: str,
    *,
    source_url: str,
    fetched_at: str,
) -> list[EconomicReleaseEvent]:
    events: list[EconomicReleaseEvent] = []
    text = _estat_text_blob(html)
    segments = _iter_estat_segments(text)

    for seg in segments:
        head = re.match(r"(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})\s*(.*)", seg)
        if not head:
            continue
        ymd = head.group(1).split("-")
        try:
            ld = date(int(ymd[0]), int(ymd[1]), int(ymd[2]))
        except ValueError:
            continue
        t_parts = head.group(2).split(":")
        hh, minute = int(t_parts[0]), int(t_parts[1])
        if hh > 23 or minute > 59:
            continue
        clock = f"{hh:02d}:{minute:02d}"
        rest = head.group(3).strip()
        desc = re.sub(r"^(?:総務省|厚生労働省|内閣府|財務省|経済産業省|国土交通省|農林水産省)\s+", "", rest)

        approx_m = _APPROX_JP_RE.search(desc)
        main_desc = desc[: approx_m.start()].strip() if approx_m else desc
        if not main_desc.strip() and approx_m:
            continue

        if "消費者物価指数" in main_desc and "全国" in main_desc:
            ref = _ref_from_parenthetical(main_desc)
            if not ref:
                ym = re.search(r"(\d{4}|(?:[０-９]{4}))\s*年\s*(\d{1,2}|(?:[０-９]{1,2}))\s*月", main_desc)
                ref = _parse_yyyy_mm_jp(ym.group(0)) if ym else ""
            events.append(
                EconomicReleaseEvent(
                    event_family="jp_cpi",
                    country="JP",
                    title="Consumer Price Index, national",
                    publisher="Statistics Bureau of Japan",
                    local_date=ld,
                    local_time=clock,
                    timezone=_TZ,
                    reference_period=ref,
                    source_url=source_url,
                    fetched_at=fetched_at,
                    status="verified",
                    series_ids=("JP.Inflation.headline", "JP.Inflation.underlying"),
                    provenance=f"e-Stat release calendar segment: {seg[:400]}",
                )
            )
            continue

        if re.search(r"家計調査\s+家計収支編", main_desc) or (
            "家計調査" in main_desc and "家計収支編" in main_desc
        ):
            ref = _ref_from_parenthetical(main_desc)
            if not ref:
                ym = re.search(r"(\d{4}|(?:[０-９]{4}))\s*年\s*(\d{1,2}|(?:[０-９]{1,2}))\s*月分", main_desc)
                ref = _parse_yyyy_mm_jp(ym.group(0)) if ym else ""
            events.append(
                EconomicReleaseEvent(
                    event_family="jp_household",
                    country="JP",
                    title="Family Income and Expenditure Survey",
                    publisher="Statistics Bureau of Japan",
                    local_date=ld,
                    local_time=clock,
                    timezone=_TZ,
                    reference_period=ref,
                    source_url=source_url,
                    fetched_at=fetched_at,
                    status="verified",
                    series_ids=("JP.Consumer.spending",),
                    provenance=f"e-Stat release calendar segment: {seg[:400]}",
                )
            )
            continue

        if "労働力調査" in main_desc:
            ref = _ref_from_parenthetical(main_desc)
            if not ref:
                ym = re.search(
                    r"労働力調査\s*(?:\s*)(\d{4}|(?:[０-９]{4}))\s*年\s*(\d{1,2}|(?:[０-９]{1,2}))\s*月分",
                    main_desc,
                )
                if ym:
                    ref = _parse_yyyy_mm_jp(ym.group(0)) or ""
            if "詳細集計" in main_desc:
                fam = "jp_lfs_detail"
                title = "Labour Force Survey detailed results"
            else:
                fam = "jp_lfs"
                title = "Labour Force Survey"
            events.append(
                EconomicReleaseEvent(
                    event_family=fam,
                    country="JP",
                    title=title,
                    publisher="Statistics Bureau of Japan",
                    local_date=ld,
                    local_time=clock,
                    timezone=_TZ,
                    reference_period=ref,
                    source_url=source_url,
                    fetched_at=fetched_at,
                    status="verified",
                    series_ids=(
                        "JP.Labor.unemployment",
                        "JP.Labor.employment",
                        "JP.Labor.participation",
                    ),
                    provenance=f"e-Stat release calendar segment: {seg[:400]}",
                )
            )

    return events


def _boj_mpm_second_days_scan(
    html: str,
    *,
    source_url: str,
    fetched_at: str,
) -> list[EconomicReleaseEvent]:
    events: list[EconomicReleaseEvent] = []
    for h2m in re.finditer(r'<h2[^>]*id="p(20\d{2})"[^>]*>', html, re.I):
        y = int(h2m.group(1))
        start = h2m.end()
        nxt = re.search(r'<h2[^>]*id="p20', html[start:], re.I)
        end = start + (nxt.start() if nxt else len(html) - start)
        chunk = html[start:end]

        for tr in re.finditer(r"<tr[^>]*>(.*?)</tr>", chunk, re.I | re.DOTALL):
            row = tr.group(1)
            tds = re.findall(r"<td[^>]*>\s*(.*?)\s*</td>", row, re.I | re.DOTALL)
            if not tds:
                continue
            first = re.sub(r"<[^>]+>", "", tds[0])
            first = unescape(re.sub(r"\s+", " ", first).strip())
            # Full: "Dec. 17 (Thurs.), Dec. 18 (Fri.)" or short: "Dec. 17 (Thurs.), 18 (Fri.)"
            inner_m = re.search(
                r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s*"
                r"\d{1,2}\s*\([^)]+\)\s*,\s*"
                r"(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s*)?"
                r"\d{1,2}\s*\([^)]+\)(?:\s*,\s*\d{4})?)",
                first,
                re.I,
            )
            if not inner_m:
                continue
            span = inner_m.group(1)
            days = re.findall(
                r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s*(\d{1,2})\s*\([^)]+\)",
                span,
                re.I,
            )
            d_tail_m = re.search(
                r",\s*(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+)?"
                r"(\d{1,2})\s*\([^)]+\)\s*\Z",
                span,
                re.I,
            )
            if len(days) >= 2:
                m1_raw, d1 = days[0][0].lower(), int(days[0][1])
                m2_raw, d2 = days[1][0].lower(), int(days[1][1])
            elif len(days) == 1 and d_tail_m:
                m1_raw, d1 = days[0][0].lower(), int(days[0][1])
                d2 = int(d_tail_m.group(1))
                m2_raw = m1_raw
            else:
                continue
            m1 = m1_raw[:3] if m1_raw != "sept" else "sep"
            m2 = m2_raw[:3] if m2_raw != "sept" else "sep"
            mo1 = _MONTH_ABBREV.get(m1)
            mo2 = _MONTH_ABBREV.get(m2)
            if mo1 is None or mo2 is None:
                continue
            year_second = y
            y_extra = re.search(r",\s*(\d{4})\s*\Z", span.strip())
            if y_extra:
                year_second = int(y_extra.group(1))
            year_first = y
            if y_extra and mo1 == 12 and mo2 == 1:
                year_first = year_second - 1
            try:
                d_first = date(year_first, mo1, d1)
            except ValueError:
                continue
            try:
                d_second = date(year_second, mo2, d2)
            except ValueError:
                continue
            ref = f"{d_first.isoformat()}/{d_second.isoformat()}"
            events.append(
                EconomicReleaseEvent(
                    event_family="jp_boj_mpm",
                    country="JP",
                    title="Bank of Japan Monetary Policy Meeting",
                    publisher="Bank of Japan",
                    local_date=d_second,
                    local_time=None,
                    timezone=_TZ,
                    reference_period=ref,
                    source_url=source_url,
                    fetched_at=fetched_at,
                    status="tba",
                    series_ids=(),
                    provenance=(
                        "BoJ MPM schedule (second day of two-day meeting): "
                        f"{span}"
                    ),
                )
            )
    return events


def _cgsi_month_from_title(title: str) -> str | None:
    m = re.search(r"\(([^)]+)\)", title)
    if not m:
        return None
    inner = m.group(1).strip()
    mo_m = re.match(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\.?",
        inner,
        re.I,
    )
    if mo_m:
        month_names = {
            "january": "01",
            "february": "02",
            "march": "03",
            "april": "04",
            "may": "05",
            "june": "06",
            "july": "07",
            "august": "08",
            "september": "09",
            "october": "10",
            "november": "11",
            "december": "12",
        }
        return month_names[mo_m.group(1).lower()]
    abb_m = re.match(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?", inner, re.I)
    if not abb_m:
        return None
    a = abb_m.group(1).lower()
    if a == "sept":
        a = "sep"
    a = a[:3]
    mo = _MONTH_ABBREV.get(a)
    return f"{mo:02d}" if mo else None


def _release_schedule_table_tbody(html: str) -> str | None:
    m = re.search(
        r'<caption[^>]*>Table\s*:\s*Release Schedule\s*</caption>'
        r".*?<tbody[^>]*>(?P<body>.*?)</tbody>",
        html,
        re.I | re.DOTALL,
    )
    return m.group("body") if m else None


_M_D_MON = re.compile(
    r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+(\d{1,2})\s*$",
    re.I,
)
_DAY_NUM = re.compile(r"^(\d{1,2})$")


def _parse_boj_calendar(
    html: str,
    *,
    source_url: str,
    fetched_at: str,
    gaps: list[str],
) -> list[EconomicReleaseEvent]:
    events: list[EconomicReleaseEvent] = []
    tbody = _release_schedule_table_tbody(html)
    if not tbody:
        return events

    default_year = 2026
    cur_month: int | None = None
    cur_year = default_year

    for tr in re.finditer(r"<tr[^>]*>(.*?)</tr>", tbody, re.I | re.DOTALL):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr.group(1), re.I | re.DOTALL)
        if len(tds) < 3:
            continue
        day_raw = _clean_cell(tds[0])
        time_c = _clean_cell(tds[1])
        title_c = _clean_cell(tds[2])

        if not day_raw.strip():
            if "Services Producer Price Index" in title_c and re.search(
                r"\b8:50\b", time_c
            ):
                gaps.append(
                    "Skipped dated Services Producer Price Index row (series_ids empty policy)"
                )
            continue

        m_dm = _M_D_MON.match(day_raw)
        if m_dm:
            mon_s = m_dm.group(1).lower()
            if mon_s.startswith("sep"):
                mon_s = "sep"
            else:
                mon_s = mon_s[:3]
            mo = _MONTH_ABBREV.get(mon_s)
            if mo is None:
                continue
            cur_month = mo
            cur_year = default_year
            try:
                day_n = int(m_dm.group(2))
            except ValueError:
                continue
        else:
            m_dn = _DAY_NUM.match(day_raw)
            if not m_dn or cur_month is None:
                continue
            day_n = int(m_dn.group(1))

        low = title_c.lower()
        if "speech" in low:
            continue
        if "t-bill" in low or "t-bills" in low:
            continue
        if "bank of japan accounts" in low:
            continue

        tm = re.search(r"\b(\d{1,2}):(\d{2})\b", time_c)
        if not tm:
            continue
        hh, minute = int(tm.group(1)), int(tm.group(2))
        clock = f"{hh:02d}:{minute:02d}"

        if "Corporate Goods Price Index" not in title_c:
            continue

        try:
            ld = date(cur_year, cur_month, day_n)
        except ValueError:
            continue
        mo_oct = _cgsi_month_from_title(title_c)
        ref = f"{cur_year}-{mo_oct}" if mo_oct else ""
        events.append(
            EconomicReleaseEvent(
                event_family="jp_cgpi",
                country="JP",
                title="Corporate Goods Price Index",
                publisher="Bank of Japan",
                local_date=ld,
                local_time=clock,
                timezone=_TZ,
                reference_period=ref,
                source_url=source_url,
                fetched_at=fetched_at,
                status="verified",
                series_ids=("JP.Inflation.cgpi_ppi",),
                provenance=(
                    f"BoJ release schedule ({cur_year:04d}-{cur_month:02d}-{day_n:02d}) "
                    f"{clock} {title_c}"
                ),
            )
        )
    return events


@dataclass
class JpOfficialSchedule:
    country: str = field(init=False, default="JP")

    def source_plan(self) -> tuple[SourceDocument, ...]:
        plan = (
            SourceDocument(
                key="cao_gdp",
                url="https://www.esri.cao.go.jp/en/sna/kouhyou/kouhyou_top.html",
                description="Cabinet Office quarterly GDP release schedule (English).",
            ),
            SourceDocument(
                key="estat",
                url="https://www.e-stat.go.jp/release-calendar",
                description="e-Stat consolidated release calendar (Japanese).",
            ),
            SourceDocument(
                key="boj_mpm",
                url="https://www.boj.or.jp/en/mopo/mpmsche_minu/",
                description="Bank of Japan monetary policy meeting dates (English).",
            ),
            SourceDocument(
                key="boj_calendar",
                url="https://www.boj.or.jp/en/about/calendar/",
                description="Bank of Japan statistical release schedule (English).",
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
        gaps: list[str] = []
        events: list[EconomicReleaseEvent] = []

        cao = (documents.get("cao_gdp") or "").strip()
        if cao:
            events.extend(
                _parse_cao_gdp(
                    cao,
                    source_url="https://www.esri.cao.go.jp/en/sna/kouhyou/kouhyou_top.html",
                    fetched_at=fetched_at,
                )
            )

        estat_html = (documents.get("estat") or "").strip()
        estat_statgojp = (documents.get("estat_statgojp_cpi") or "").strip()
        if estat_html:
            ev_estat = _parse_estat_calendar(
                estat_html,
                source_url="https://www.e-stat.go.jp/release-calendar",
                fetched_at=fetched_at,
            )
            events.extend(ev_estat)
            estat_text = _estat_text_blob(estat_html)
            if not ev_estat:
                if estat_statgojp:
                    events.extend(
                        _parse_statgojp_cpi_schedule(
                            estat_statgojp,
                            source_url="https://www.stat.go.jp/english/data/cpi/1582.html",
                            fetched_at=fetched_at,
                        )
                    )
                elif re.search(
                    r"消費者物価指数|家計調査|労働力調査", estat_text
                ):
                    gaps.append(
                        "Statistics Bureau CPI/labour schedule was not in the fetched HTML"
                    )

        boj_mpm = (documents.get("boj_mpm") or "").strip()
        if boj_mpm:
            events.extend(
                _boj_mpm_second_days_scan(
                    boj_mpm,
                    source_url="https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm",
                    fetched_at=fetched_at,
                )
            )

        boj_cal = (documents.get("boj_calendar") or "").strip()
        if boj_cal:
            events.extend(
                _parse_boj_calendar(
                    boj_cal,
                    source_url="https://www.boj.or.jp/en/about/calendar/index.htm",
                    fetched_at=fetched_at,
                    gaps=gaps,
                )
            )

        GAPS = tuple(gaps)
        try:
            validate_events(events)
        except ValueError:
            return []
        return events


ADAPTER = JpOfficialSchedule()

__all__ = [
    "ADAPTER",
    "GAPS",
    "JpOfficialSchedule",
]
