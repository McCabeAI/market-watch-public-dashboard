"""Parse official BLS and Chicago Fed release calendars. No hand-typed month."""

from __future__ import annotations

import re
from datetime import datetime
from html.parser import HTMLParser
from typing import Any

_MONTHS = {
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

_BLS_RELEASE_NAMES = {
    "Employment Situation": "empsit",
    "Job Openings and Labor Turnover": "jolts",
    "Consumer Price Index": "cpi",
}


def _month_period(label: str) -> str | None:
    match = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
        label,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    month = _MONTHS[match.group(1).lower()]
    return f"{match.group(2)}-{month:02d}"


def _clock(raw: str) -> str | None:
    match = re.search(r"(\d{1,2}):(\d{2})\s*([AP]M)", raw, flags=re.IGNORECASE)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    meridiem = match.group(3).upper()
    if meridiem == "PM" and hour != 12:
        hour += 12
    if meridiem == "AM" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}"


def parse_bls_month_schedule(html: str, *, year: int, month: int) -> list[dict[str, str]]:
    """Extract release instants from one BLS monthly schedule page.

    `year` and `month` are the calendar page (the release month), taken from
    the page URL `/schedule/YYYY/MM_sched.htm`, not from a hard-coded list.
    """
    releases: list[dict[str, str]] = []
    cells = re.findall(r"<td\b([^>]*)>(.*?)</td>", html, flags=re.IGNORECASE | re.DOTALL)
    for attrs, inner in cells:
        day_match = re.search(r'class="day"[^>]*>\s*(\d{1,2})\s*<', inner, flags=re.IGNORECASE)
        if not day_match:
            continue
        day = int(day_match.group(1))
        if "other-month" in attrs:
            continue
        try:
            release_day = datetime(year, month, day).date()
        except ValueError:
            continue
        blocks = re.findall(
            r"<strong>\s*([^<]+?)\s*(?:<br\s*/?>)?\s*</strong>\s*([^<]+?)<br\s*/?>\s*([^<]+)",
            inner,
            flags=re.IGNORECASE | re.DOTALL,
        )
        for name, reference, clock in blocks:
            family = None
            cleaned = " ".join(name.split())
            for prefix, code in _BLS_RELEASE_NAMES.items():
                if cleaned.startswith(prefix):
                    family = code
                    break
            if family is None:
                continue
            period = _month_period(reference)
            hhmm = _clock(clock)
            if period is None or hhmm is None:
                continue
            stamp = f"{release_day.isoformat()}T{hhmm}:00"
            releases.append(
                {
                    "family": family,
                    "stamp": stamp,
                    "period": period,
                    "name": cleaned,
                }
            )
    return releases


def discover_bls_month_urls(index_html: str) -> list[str]:
    found = re.findall(r'href="(/schedule/\d{4}/\d{2}_sched\.htm)"', index_html, flags=re.IGNORECASE)
    unique: list[str] = []
    seen: set[str] = set()
    for path in found:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


class _CommentStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        rendered = " ".join(f'{name}="{value}"' if value is not None else name for name, value in attrs)
        self.parts.append(f"<{tag} {rendered}>" if rendered else f"<{tag}>")

    def handle_endtag(self, tag: str) -> None:
        self.parts.append(f"</{tag}>")


def _strip_comments(html: str) -> str:
    parser = _CommentStripper()
    parser.feed(html)
    return "".join(parser.parts)


def parse_chicago_fed_schedule(html: str) -> list[dict[str, str]]:
    """Advance and final Chicago Fed LMI instants from the published schedule table.

    HTML comments are removed first so retired rows are not treated as live.
    Release time is 8:30 a.m. Eastern, as the schedule page states.
    """
    visible = _strip_comments(html)
    rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", visible, flags=re.IGNORECASE | re.DOTALL)
    releases: list[dict[str, str]] = []
    for row in rows:
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row, flags=re.IGNORECASE | re.DOTALL)
        if len(cells) < 2:
            continue
        label = re.sub(r"<[^>]+>", " ", cells[0])
        when = re.sub(r"<[^>]+>", " ", cells[1])
        label = " ".join(label.split())
        when = " ".join(when.split())
        release_type = "final" if "final" in label.lower() else "advance" if "advance" in label.lower() else None
        period = _month_period(label)
        date_match = re.search(
            r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s*(\d{4})",
            when,
            flags=re.IGNORECASE,
        )
        if release_type is None or period is None or not date_match:
            continue
        month = _MONTHS[date_match.group(1).lower()]
        day = int(date_match.group(2))
        year = int(date_match.group(3))
        stamp = f"{year:04d}-{month:02d}-{day:02d}T08:30:00"
        releases.append(
            {
                "family": "chicago_fed_lmi",
                "release_type": release_type,
                "stamp": stamp,
                "period": period,
            }
        )
    return releases


def release_rule_from_entries(entries: list[dict[str, str]], *, note: str) -> dict[str, Any]:
    ordered = sorted(entries, key=lambda item: item["stamp"])
    dates = [item["stamp"] for item in ordered]
    expected = {item["stamp"]: item["period"] for item in ordered}
    return {
        "kind": "country_local_schedule_required",
        "timezone": "America/New_York",
        "dates": dates,
        "expected_periods": expected,
        "note": note,
    }
