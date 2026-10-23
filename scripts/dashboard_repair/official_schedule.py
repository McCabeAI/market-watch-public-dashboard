"""Bounded official schedule pages. Parsers never invent a date.

A page that does not contain a release date contributes nothing. Failures are
recorded and the pinned calendar is left unchanged.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from scripts.macro_ingestion.us_employment.schedule import (
    parse_bls_month_schedule,
    parse_chicago_fed_schedule,
)

ET = ZoneInfo("America/New_York")
USER_AGENT = "MarketWatchDashboard/1.0"
BLS_ORIGIN = "https://blsmon1.bls.gov"
CHICAGO_SCHEDULE_URL = (
    "https://www.chicagofed.org/research/data/chicago-fed-labor-market-indicators/release-schedule"
)
ABS_CPI_URL = (
    "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/"
    "consumer-price-index-australia/latest-release"
)
ABS_LABOUR_URL = (
    "https://www.abs.gov.au/statistics/labour/employment-and-unemployment/"
    "labour-force-australia/latest-release"
)
STATS_NZ_CPI_URL = (
    "https://www.stats.govt.nz/information-releases/consumers-price-index-june-2026-quarter/"
)

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
_ABS_MONTH = {
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


def parse_abs_future_releases(html: str) -> list[dict[str, str]]:
    """ABS 'Next Release d/m/yyyy' lines. The clock is TBA unless that line prints one."""
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for part in re.split(r"Next Release", html, flags=re.IGNORECASE)[1:]:
        match = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})", part)
        if not match:
            continue
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        try:
            local = date(year, month, day)
        except ValueError:
            continue
        rest = re.sub(r"<[^>]+>", " ", part[match.end() : match.end() + 240])
        rest = " ".join(rest.split())
        title = rest.strip(" -:")
        clock = ""
        time_match = re.search(r"\b(\d{1,2}):(\d{2})\s*(am|pm)?\b", rest, flags=re.IGNORECASE)
        if time_match and time_match.start() < 48:
            clock = time_match.group(0)
        key = local.isoformat()
        if key in seen:
            continue
        seen.add(key)
        found.append({"local_date": local.isoformat(), "title": title, "clock": clock})
    return found


def parse_stats_nz_next_release(html: str) -> list[dict[str, str]]:
    text = html.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    text = re.sub(r"<[^>]+>", " ", text)
    text = " ".join(text.split())
    found: list[dict[str, str]] = []
    for match in re.finditer(
        r"([A-Za-z]+ \d{4} quarter).*?released on (\d{1,2}) ([A-Za-z]+) (\d{4})",
        text,
        flags=re.IGNORECASE,
    ):
        month = _MONTHS.get(match.group(3).lower())
        if month is None:
            continue
        try:
            local = date(int(match.group(4)), month, int(match.group(2)))
        except ValueError:
            continue
        found.append(
            {
                "local_date": local.isoformat(),
                "reference": match.group(1),
                "clock": "",
            }
        )
    return found


def _shift_month(day: date, offset: int) -> tuple[int, int]:
    index = day.year * 12 + (day.month - 1) + offset
    return index // 12, index % 12 + 1


def _abs_period(title: str) -> str:
    match = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
        title,
        flags=re.IGNORECASE,
    )
    if not match:
        return ""
    return f"{match.group(2)}-{_ABS_MONTH[match.group(1).lower()]}"


def _default_get(url: str, timeout: float) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def _page(url: str, getter: Callable[[str, float], str], timeout: float) -> dict[str, Any]:
    try:
        body = getter(url, timeout)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return {"url": url, "status": "failed", "error": f"{type(exc).__name__}: {exc}", "html": ""}
    if not body or "Just a moment" in body or "cf-browser-verification" in body:
        return {"url": url, "status": "failed", "error": "page blocked or empty", "html": ""}
    return {"url": url, "status": "ok", "error": "", "html": body}


def fetch_official_schedules(
    now: datetime,
    *,
    timeout: float = 6.0,
    getter: Callable[[str, float], str] | None = None,
) -> dict[str, Any]:
    """Read a fixed set of official schedule pages. Network errors add no dates."""
    fetch = getter or _default_get
    if now.tzinfo is None:
        now = now.replace(tzinfo=ET)
    today = now.astimezone(ET).date()
    months = [_shift_month(today, 0), _shift_month(today, 1)]
    urls = [CHICAGO_SCHEDULE_URL, ABS_CPI_URL, ABS_LABOUR_URL, STATS_NZ_CPI_URL]
    urls.extend(f"{BLS_ORIGIN}/schedule/{year:04d}/{month:02d}_sched.htm" for year, month in months)
    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    with ThreadPoolExecutor(max_workers=4) as pool:
        pages = list(pool.map(lambda url: _page(url, fetch, timeout), urls))
    slots: list[dict[str, Any]] = []
    report_pages: list[dict[str, Any]] = []
    for page in pages:
        parsed = 0
        url = page["url"]
        html = page["html"]
        if page["status"] != "ok":
            report_pages.append({"url": url, "status": "failed", "error": page["error"], "parsed": 0})
            continue
        if "/schedule/" in url and url.endswith("_sched.htm"):
            match = re.search(r"/schedule/(\d{4})/(\d{2})_sched\.htm", url)
            if match:
                year, month = int(match.group(1)), int(match.group(2))
                for item in parse_bls_month_schedule(html, year=year, month=month):
                    family = item["family"]
                    if family == "empsit":
                        series_ids = ["US.Labor.unemployment", "US.Labor.wages", "US.Labor.payrolls"]
                        name = "Employment Situation"
                    elif family == "cpi":
                        series_ids = ["US.Inflation.cpi_headline"]
                        name = "Consumer Price Index"
                    else:
                        continue
                    slots.append(
                        {
                            "series_ids": series_ids,
                            "country": "US",
                            "name": name,
                            "publisher": "Bureau of Labor Statistics",
                            "source_url": url,
                            "provenance": (
                                f"Parsed from the official BLS monthly schedule {url} fetched {retrieved_at}. "
                                "The page prints the release time."
                            ),
                            "reference_period": item.get("period") or "",
                            "clock": "verified",
                            "timezone": "America/New_York",
                            "stamp": item["stamp"],
                        }
                    )
                    parsed += 1
        elif url == CHICAGO_SCHEDULE_URL:
            for item in parse_chicago_fed_schedule(html):
                series_id = (
                    "US.Labor.chicago_fed_u3_nowcast_final"
                    if item["release_type"] == "final"
                    else "US.Labor.chicago_fed_u3_nowcast_advance"
                )
                slots.append(
                    {
                        "series_ids": [series_id],
                        "country": "US",
                        "name": f"Chicago Fed labor market indicators {item['release_type']}",
                        "publisher": "Federal Reserve Bank of Chicago",
                        "source_url": url,
                        "provenance": (
                            f"Parsed from the Chicago Fed release schedule fetched {retrieved_at}. "
                            "8:30 a.m. Eastern is the time printed by that schedule's parser contract."
                        ),
                        "reference_period": item.get("period") or "",
                        "clock": "verified",
                        "timezone": "America/New_York",
                        "stamp": item["stamp"],
                    }
                )
                parsed += 1
        elif url in {ABS_CPI_URL, ABS_LABOUR_URL}:
            for item in parse_abs_future_releases(html):
                title = item["title"]
                if url == ABS_CPI_URL and "consumer price index" not in title.lower() and title:
                    continue
                if url == ABS_LABOUR_URL and "labour force" not in title.lower() and title:
                    continue
                series_ids = (
                    ["AU.Inflation.headline", "AU.Inflation.underlying"]
                    if url == ABS_CPI_URL
                    else ["AU.Labor.unemployment", "AU.Labor.employment", "AU.Labor.participation"]
                )
                slots.append(
                    {
                        "series_ids": series_ids,
                        "country": "AU",
                        "name": title or ("CPI" if url == ABS_CPI_URL else "Labour Force"),
                        "publisher": "Australian Bureau of Statistics",
                        "source_url": url,
                        "provenance": (
                            f"Official ABS latest-release page fetched {retrieved_at}. "
                            "The next-release line prints a date"
                            + (" and a clock." if item["clock"] else " and no clock, so the time stays TBA.")
                        ),
                        "reference_period": _abs_period(title),
                        "clock": "verified" if item["clock"] else "tba",
                        "timezone": "Australia/Sydney",
                        "stamp": "",
                        "local_date": item["local_date"],
                        "printed_clock": item["clock"],
                    }
                )
                parsed += 1
        elif url == STATS_NZ_CPI_URL:
            for item in parse_stats_nz_next_release(html):
                slots.append(
                    {
                        "series_ids": ["NZ.Inflation.headline", "NZ.Inflation.underlying"],
                        "country": "NZ",
                        "name": "Consumers price index",
                        "publisher": "Stats NZ",
                        "source_url": url,
                        "provenance": (
                            f"Stats NZ release page fetched {retrieved_at}. "
                            "The next-release sentence has a date and no clock."
                        ),
                        "reference_period": item["reference"],
                        "clock": "tba",
                        "timezone": "Pacific/Auckland",
                        "stamp": "",
                        "local_date": item["local_date"],
                    }
                )
                parsed += 1
        report_pages.append({"url": url, "status": "ok", "error": "", "parsed": parsed})
    return {
        "attempted": True,
        "retrieved_at": retrieved_at,
        "pages": report_pages,
        "errors": [page["error"] for page in report_pages if page["status"] != "ok"],
        "slots": slots,
    }
