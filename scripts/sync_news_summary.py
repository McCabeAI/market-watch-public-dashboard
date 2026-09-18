from __future__ import annotations

import re
import sys
from pathlib import Path

MONTHS = {
    "Jan": "January",
    "Feb": "February",
    "Mar": "March",
    "Apr": "April",
    "May": "May",
    "Jun": "June",
    "Jul": "July",
    "Aug": "August",
    "Sep": "September",
    "Oct": "October",
    "Nov": "November",
    "Dec": "December",
}

DIGEST_WINDOW_RE = re.compile(
    r'<div class="scanline"><b>Window:</b>\s*'
    r'(\d{1,2})\s+([A-Z][a-z]{2})\s+[^→<]+→\s*'
    r'(\d{1,2})\s+([A-Z][a-z]{2})\s+[^<]+</div>'
)
LAST_REFRESH_RE = re.compile(
    r'Last refreshed\s+(\d{1,2})\s+([A-Z][a-z]{2})\s+(\d{4})'
)
NEWS_SCAN_RE = re.compile(
    r'(<div class="news-window"><b>Last scanned:</b>)\s*'
    r'[^<·]+'
    r'(\s*·\s*Sources include .*?</div>)'
)
CURRENT_TAPE_RE = re.compile(
    r'(<div class="stitle">Current tape</div><div class="news-count">)'
    r'\d+'
    r'(</div><p>curated market-relevant stories in the )'
    r'.*?'
    r'( window, ranked by expected rates/FX significance rather than headline volume\.</p>)'
)
DRIVER_RE = re.compile(
    r'<a class="driver-card"[^>]*>.*?<div class="dmeta">.*?</div>'
    r'<b>(.*?)</b><span>(.*?)</span></a>',
    re.S,
)
FRONT_ALERT_RE = re.compile(
    r'<div class="news-alert market-alert">.*?'
    r'<label for="p-news">Open News &amp; Research</label>\s*</div>',
    re.S,
)


def _display_window(start_day: str, start_mon: str, end_day: str, end_mon: str, year: str) -> str:
    if start_mon == end_mon:
        return f"{int(start_day)}–{int(end_day)} {MONTHS[end_mon]} {year}"
    return f"{int(start_day)} {MONTHS[start_mon]}–{int(end_day)} {MONTHS[end_mon]} {year}"


def _sync_front_alert(html: str, story_count: int, display_window: str, scan_date: str) -> str:
    drivers = DRIVER_RE.findall(html)
    if not 1 <= len(drivers) <= 3:
        raise ValueError(f"invalid Top Market Drivers count: {len(drivers)}")

    lead_title = drivers[0][0].strip()
    driver_summary = " ".join(
        f"<b>{title.strip()}:</b> {summary.strip()}" for title, summary in drivers
    )
    replacement = (
        '<div class="news-alert market-alert">'
        '<div class="flag">MARKET NEWS · 7-DAY WINDOW</div>'
        f'<div><h3>{lead_title}</h3><p>{driver_summary}</p>'
        f'<span class="alert-sub">{story_count} qualifying events in the current '
        f'{display_window} digest · Last scanned {scan_date}.</span></div>'
        '<label for="p-news">Open News &amp; Research</label>'
        '</div>'
    )
    html, replacements = FRONT_ALERT_RE.subn(replacement, html, count=1)
    if replacements != 1:
        raise ValueError("Front-page Market News alert could not be synchronized")
    return html


def sync_news_summary(html: str) -> str:
    window = DIGEST_WINDOW_RE.search(html)
    if not window:
        raise ValueError("7-Day Quick Digest window not found")

    refreshed = LAST_REFRESH_RE.search(html)
    if not refreshed:
        raise ValueError("Last 24 Hours refresh timestamp not found")

    start_day, start_mon, end_day, end_mon = window.groups()
    refreshed_day, refreshed_mon, year = refreshed.groups()
    if (int(end_day), end_mon) != (int(refreshed_day), refreshed_mon):
        raise ValueError(
            "7-Day Quick Digest end date does not match Last 24 Hours refresh date"
        )

    story_count = html.count('<details class="story">')
    if not 1 <= story_count <= 12:
        raise ValueError(f"invalid 7-Day Quick Digest story count: {story_count}")

    scan_date = f"{int(end_day)} {end_mon} {year}"
    display_window = _display_window(start_day, start_mon, end_day, end_mon, year)

    html, scan_replacements = NEWS_SCAN_RE.subn(
        rf"\1 {scan_date}\2",
        html,
        count=1,
    )
    if scan_replacements != 1:
        raise ValueError("Market News last-scanned summary could not be synchronized")

    html, tape_replacements = CURRENT_TAPE_RE.subn(
        rf"\g<1>{story_count}\g<2>{display_window}\g<3>",
        html,
        count=1,
    )
    if tape_replacements != 1:
        raise ValueError("Current tape summary could not be synchronized")

    html = _sync_front_alert(html, story_count, display_window, scan_date)

    if f"<b>Last scanned:</b> {scan_date}" not in html:
        raise ValueError("Market News last-scanned summary verification failed")
    if (
        f'<div class="news-count">{story_count}</div>'
        f"<p>curated market-relevant stories in the {display_window} window"
    ) not in html:
        raise ValueError("Current tape summary verification failed")
    if (
        f"{story_count} qualifying events in the current {display_window} digest "
        f"· Last scanned {scan_date}."
    ) not in html:
        raise ValueError("Front-page Market News alert verification failed")

    return html


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "_site/index.html")
    html = path.read_text()
    path.write_text(sync_news_summary(html))
    print("News summary metadata and front-page alert synchronized to the live 7-Day Quick Digest")


if __name__ == "__main__":
    main()
