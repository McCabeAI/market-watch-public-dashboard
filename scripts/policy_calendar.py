"""Official central-bank meeting calendars for policy decision dates."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
CALENDAR_PATH = Path("data") / "policy_meetings.json"
SCHEMA_VERSION = 1
BANK_CODES = ("US", "CA", "AU", "NZ", "EA", "JP")

Fetch = Callable[[str], str]

SOURCE_URLS: dict[str, str] = {
    "US": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
    "CA": "https://www.bankofcanada.ca/core-functions/monetary-policy/key-interest-rate/",
    "AU": "https://www.rba.gov.au/schedules-events/board-meeting-schedules.html",
    "NZ": "https://www.rbnz.govt.nz/news-and-events/how-we-release-information/ocr-decision-dates-and-financial-stability-report-dates-to-feb-2028",
    "EA": "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html",
    "JP": "https://www.boj.or.jp/en/mopo/mpmsche_minu/",
}

BANK_META: dict[str, dict[str, str | None]] = {
    "US": {"timezone": "America/New_York", "local_time": "14:00"},
    "CA": {"timezone": "America/Toronto", "local_time": "09:45"},
    "AU": {"timezone": "Australia/Sydney", "local_time": "14:30"},
    "NZ": {"timezone": "Pacific/Auckland", "local_time": "14:00"},
    "EA": {"timezone": "Europe/Berlin", "local_time": "14:15"},
    "JP": {"timezone": "Asia/Tokyo", "local_time": None},
}

_MONTHS: dict[str, int] = {
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
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_NBSP = "\u00a0"


def _stamp(now: datetime | None = None) -> str:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso(year: int, month: int, day: int) -> str:
    return date(year, month, day).isoformat()


def _split_month_label(label: str) -> tuple[int, int]:
    cleaned = unescape(label).replace(_NBSP, " ")
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    cleaned = cleaned.strip().lower()
    if "/" in cleaned:
        first, second = cleaned.split("/", 1)
        return _MONTHS[first.strip()], _MONTHS[second.strip()]
    return _MONTHS[cleaned], _MONTHS[cleaned]


def effective_date(bank: str, decision_date: str) -> str:
    """Weekend skip only; ECB uses the first Wednesday strictly after the decision."""
    decided = date.fromisoformat(decision_date)
    if bank == "EA":
        candidate = decided + timedelta(days=1)
        while candidate.weekday() != 2:
            candidate += timedelta(days=1)
        return candidate.isoformat()
    candidate = decided + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate.isoformat()


def parse_fed_calendar(html: str) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    panel_pattern = re.compile(
        r'<div class="panel panel-default">\s*<div class="panel-heading">\s*<h4>\s*<a id="\d+">(\d{4}) FOMC Meetings</a>\s*</h4>\s*</div>(.*?)(?=<div class="panel panel-default">|<p>Note:|</body>)',
        re.S,
    )
    row_pattern = re.compile(
        r'fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>\s*</div>\s*'
        r'<div class="fomc-meeting__date[^"]*">\s*([^<]+?)\s*</div>',
        re.S,
    )
    for panel in panel_pattern.finditer(html):
        year = int(panel.group(1))
        body = panel.group(2)
        for row in row_pattern.finditer(body):
            month_label = row.group(1).strip()
            date_text = unescape(row.group(2)).strip().rstrip("*")
            if "notation vote" in date_text.lower():
                continue
            if "longer-run goals" in body[row.start() : row.end() + 400].lower():
                snippet = body[row.start() : row.end() + 400].lower()
                if "statement on longer-run goals" in snippet and not re.search(
                    r"\d{1,2}-\d{1,2}", date_text
                ):
                    continue
            range_match = re.match(r"(\d{1,2})-(\d{1,2})", date_text)
            if not range_match:
                continue
            start_day = int(range_match.group(1))
            end_day = int(range_match.group(2))
            month_a, month_b = _split_month_label(month_label)
            if month_a == month_b:
                meeting_start = _iso(year, month_a, start_day)
                decision_date = _iso(year, month_b, end_day)
            elif start_day > end_day:
                meeting_start = _iso(year, month_a, start_day)
                decision_date = _iso(year, month_b, end_day)
            else:
                meeting_start = _iso(year, month_a, start_day)
                decision_date = _iso(year, month_b, end_day)
            decisions.append(
                {
                    "decision_date": decision_date,
                    "meeting_start": meeting_start,
                    "local_time": BANK_META["US"]["local_time"],
                }
            )
    decisions.sort(key=lambda item: item["decision_date"])
    return decisions


def parse_boc_calendar(html: str) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    table_pattern = re.compile(
        r"<table[^>]*>.*?Schedule for\s+(\d{4}).*?</table>",
        re.S | re.I,
    )
    row_pattern = re.compile(r"<tr>\s*<td>([^<]+)</td>\s*<td>(.*?)</td>\s*</tr>", re.S | re.I)
    for table in table_pattern.finditer(html):
        year = int(table.group(1))
        for row in row_pattern.finditer(table.group(0)):
            date_cell = unescape(row.group(1)).replace(_NBSP, " ").strip()
            pub_cell = unescape(re.sub(r"<[^>]+>", " ", row.group(2)))
            pub_cell = re.sub(r"\s+", " ", pub_cell).strip()
            if "interest rate announcement" not in pub_cell.lower():
                continue
            date_match = re.match(r"([A-Za-z]+)\s+(\d{1,2})", date_cell)
            if not date_match:
                continue
            month = _MONTHS[date_match.group(1).lower()]
            day = int(date_match.group(2))
            decisions.append(
                {
                    "decision_date": _iso(year, month, day),
                    "meeting_start": None,
                    "local_time": BANK_META["CA"]["local_time"],
                }
            )
    decisions.sort(key=lambda item: item["decision_date"])
    return decisions


def parse_rba_calendar(html: str) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    table_pattern = re.compile(
        r"<table[^>]*>.*?Board meeting schedules\s+(\d{4}).*?</table>",
        re.S | re.I,
    )
    for table in table_pattern.finditer(html):
        year = int(table.group(1))
        headers = re.findall(r"<th[^>]*>([^<]+)</th>", table.group(0), re.I)
        mp_col = 1
        for index, header in enumerate(headers):
            if "monetary policy board" in unescape(header).lower():
                mp_col = index
                break
        row_pattern = re.compile(r"<tr>(.*?)</tr>", re.S | re.I)
        for row in row_pattern.finditer(table.group(0)):
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row.group(1), re.S | re.I)
            if len(cells) <= mp_col:
                continue
            if any("colspan" in row.group(1).lower() and "month" in unescape(c).lower() for c in cells[:1]):
                continue
            cell = unescape(re.sub(r"<[^>]+>", " ", cells[mp_col]))
            cell = cell.replace("\u2013", "-").replace("\u2014", "-").replace(_NBSP, " ").strip()
            if not cell or not re.search(r"\d", cell):
                continue
            match = re.search(
                r"(\d{1,2})\s*-\s*(\d{1,2})\s+([A-Za-z]+)",
                cell,
            )
            if not match:
                continue
            _start_day, end_day, month_name = match.groups()
            month = _MONTHS[month_name.lower()]
            start_day = int(match.group(1))
            end_day_int = int(end_day)
            decisions.append(
                {
                    "decision_date": _iso(year, month, end_day_int),
                    "meeting_start": _iso(year, month, start_day),
                    "local_time": BANK_META["AU"]["local_time"],
                }
            )
    decisions.sort(key=lambda item: item["decision_date"])
    return decisions


def parse_rbnz_calendar(html: str) -> list[dict[str, Any]]:
    text = unescape(re.sub(r"<[^>]+>", " ", html))
    text = re.sub(r"\s+", " ", text)
    if not re.search(r"official cash rate|ocr decision", text, re.I):
        return []
    if re.search(r"financial stability report only", text, re.I):
        return []
    decisions: list[dict[str, Any]] = []
    for match in re.finditer(
        r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})",
        text,
    ):
        day = int(match.group(1))
        month = _MONTHS.get(match.group(2).lower())
        year = int(match.group(3))
        if month is None:
            continue
        snippet = text[max(0, match.start() - 80) : match.end() + 80].lower()
        if "financial stability" in snippet and "ocr" not in snippet and "official cash rate" not in snippet:
            continue
        decisions.append(
            {
                "decision_date": _iso(year, month, day),
                "meeting_start": None,
                "local_time": BANK_META["NZ"]["local_time"],
            }
        )
    unique = {item["decision_date"]: item for item in decisions}
    return sorted(unique.values(), key=lambda item: item["decision_date"])


def parse_ecb_calendar(html: str) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    dl_pattern = re.compile(
        r"<dt[^>]*>\s*(\d{2}/\d{2}/\d{4})\s*</dt>\s*<dd[^>]*>(.*?)</dd>",
        re.S | re.I,
    )
    for entry in dl_pattern.finditer(html):
        day, month, year = entry.group(1).split("/")
        decision_date = _iso(int(year), int(month), int(day))
        description = unescape(re.sub(r"<[^>]+>", " ", entry.group(2)))
        description = re.sub(r"\s+", " ", description).strip().lower()
        if "general council" in description:
            continue
        if "non-monetary" in description:
            continue
        if "monetary policy meeting" not in description:
            continue
        if "press conference" not in description:
            continue
        if "day 1" in description:
            continue
        decisions.append(
            {
                "decision_date": decision_date,
                "meeting_start": None,
                "local_time": BANK_META["EA"]["local_time"],
            }
        )
    decisions.sort(key=lambda item: item["decision_date"])
    return decisions


def parse_boj_calendar(html: str) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    section_pattern = re.compile(
        r'<h2 id="p(\d{4})">\1</h2>\s*<div class="tbl-box">\s*<table>(.*?)</table>',
        re.S | re.I,
    )
    row_pattern = re.compile(r"<tr>\s*<td[^>]*>(.*?)</td>", re.S | re.I)
    day_pattern = re.compile(
        r"([A-Za-z]+)\.?\s*(\d{1,2})\s*\([^)]+\)(?:,\s*(?:([A-Za-z]+)\.?\s+)?(\d{1,2})\s*\([^)]+\))?",
        re.I,
    )
    for section in section_pattern.finditer(html):
        panel_year = int(section.group(1))
        table = section.group(2)
        for row in row_pattern.finditer(table):
            cell = unescape(re.sub(r"<[^>]+>", " ", row.group(1)))
            cell = re.sub(r"\s+", " ", cell).strip()
            if not cell or cell.lower().startswith("date of mpm"):
                continue
            match = day_pattern.search(cell)
            if not match:
                continue
            month1 = _MONTHS[match.group(1).lower().rstrip(".")]
            day1 = int(match.group(2))
            if match.group(3) and match.group(4):
                month2 = _MONTHS[match.group(3).lower().rstrip(".")]
                day2 = int(match.group(4))
                year2 = panel_year
                if month2 < month1:
                    year2 = panel_year + 1
                meeting_start = _iso(panel_year, month1, day1)
                decision_date = _iso(year2, month2, day2)
            elif match.group(4):
                day2 = int(match.group(4))
                meeting_start = _iso(panel_year, month1, day1)
                decision_date = _iso(panel_year, month1, day2)
            else:
                meeting_start = _iso(panel_year, month1, day1)
                decision_date = meeting_start
            decisions.append(
                {
                    "decision_date": decision_date,
                    "meeting_start": meeting_start if decision_date != meeting_start else meeting_start,
                    "local_time": BANK_META["JP"]["local_time"],
                }
            )
    decisions.sort(key=lambda item: item["decision_date"])
    return decisions


PARSERS: dict[str, Callable[[str], list[dict[str, Any]]]] = {
    "US": parse_fed_calendar,
    "CA": parse_boc_calendar,
    "AU": parse_rba_calendar,
    "NZ": parse_rbnz_calendar,
    "EA": parse_ecb_calendar,
    "JP": parse_boj_calendar,
}


def merge_bank(
    bank: str,
    parsed: list[dict[str, Any]],
    *,
    source_url: str,
    as_of: date,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    cutoff = as_of - timedelta(days=365)
    for item in parsed:
        decision_date = str(item["decision_date"])
        decided = date.fromisoformat(decision_date)
        if decided < cutoff:
            continue
        state = "upcoming" if decided >= as_of else "past"
        merged.append(
            {
                "decision_date": decision_date,
                "meeting_start": item.get("meeting_start"),
                "local_time": item.get("local_time", BANK_META[bank]["local_time"]),
                "effective_date": effective_date(bank, decision_date),
                "source_url": source_url,
                "state": state,
            }
        )
    merged.sort(key=lambda item: item["decision_date"])
    return merged


def detect_revisions(
    bank: str,
    previous_decisions: list[dict[str, Any]],
    new_decisions: list[dict[str, Any]],
    detected_at: str,
) -> list[dict[str, Any]]:
    prev_upcoming = {
        str(item["decision_date"])
        for item in previous_decisions
        if item.get("state") == "upcoming"
    }
    new_upcoming = {
        str(item["decision_date"]) for item in new_decisions if item.get("state") == "upcoming"
    }
    revisions: list[dict[str, Any]] = []
    removed = sorted(prev_upcoming - new_upcoming)
    added = sorted(new_upcoming - prev_upcoming)
    if len(removed) == 1 and len(added) == 1:
        old_date = removed[0]
        new_date = added[0]
        delta = abs((date.fromisoformat(new_date) - date.fromisoformat(old_date)).days)
        if delta <= 31:
            revisions.append(
                {
                    "bank": bank,
                    "kind": "date_changed",
                    "decision_date": new_date,
                    "previous_date": old_date,
                    "detected_at": detected_at,
                }
            )
            return revisions
    for decision_date in added:
        revisions.append(
            {
                "bank": bank,
                "kind": "added",
                "decision_date": decision_date,
                "previous_date": None,
                "detected_at": detected_at,
            }
        )
    for decision_date in removed:
        revisions.append(
            {
                "bank": bank,
                "kind": "removed",
                "decision_date": decision_date,
                "previous_date": None,
                "detected_at": detected_at,
            }
        )
    return revisions


def next_decisions(
    calendar: dict[str, Any],
    bank: str,
    as_of: date,
    n: int = 5,
) -> list[dict[str, Any]]:
    block = (calendar.get("banks") or {}).get(bank) or {}
    decisions = [
        item
        for item in (block.get("decisions") or [])
        if isinstance(item, dict)
        and item.get("state") == "upcoming"
        and date.fromisoformat(str(item["decision_date"])) > as_of
    ]
    decisions.sort(key=lambda item: item["decision_date"])
    return decisions[:n]


def empty_calendar(now: datetime | None = None) -> dict[str, Any]:
    banks: dict[str, Any] = {}
    for code in BANK_CODES:
        meta = BANK_META[code]
        banks[code] = {
            "timezone": meta["timezone"],
            "source_url": SOURCE_URLS[code],
            "status": "unavailable",
            "retrieved_at": None,
            "last_attempt_at": None,
            "last_error": None,
            "decisions": [],
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": _stamp(now),
        "banks": banks,
        "revisions": [],
    }


def calendar_file(root: Path | None = None) -> Path:
    return (root or ROOT) / CALENDAR_PATH


def load_calendar(root: Path | None = None) -> dict[str, Any] | None:
    path = calendar_file(root)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        return None
    return payload


def write_calendar(calendar: dict[str, Any], root: Path | None = None) -> Path:
    path = calendar_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(calendar, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def refresh_calendars(
    fetch: Fetch,
    previous: dict[str, Any] | None,
    now: datetime | None = None,
    *,
    save: bool = False,
    root: Path | None = None,
) -> dict[str, Any]:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    as_of = moment.date()
    retrieved_at = _stamp(moment)
    calendar = empty_calendar(moment)
    prior_banks = (previous or {}).get("banks") if isinstance(previous, dict) else {}
    prior_revisions = list((previous or {}).get("revisions") or []) if isinstance(previous, dict) else []
    all_revisions: list[dict[str, Any]] = deepcopy(prior_revisions)

    for bank in BANK_CODES:
        prior_block = prior_banks.get(bank) if isinstance(prior_banks, dict) else None
        prior_decisions = deepcopy((prior_block or {}).get("decisions") or [])
        try:
            html = fetch(SOURCE_URLS[bank])
            parsed = PARSERS[bank](html)
            decisions = merge_bank(bank, parsed, source_url=SOURCE_URLS[bank], as_of=as_of)
            if not decisions and not prior_decisions:
                calendar["banks"][bank].update(
                    {
                        "status": "unavailable",
                        "retrieved_at": None,
                        "last_attempt_at": retrieved_at,
                        "last_error": None,
                        "decisions": [],
                    }
                )
                continue
            calendar["banks"][bank].update(
                {
                    "status": "verified",
                    "retrieved_at": retrieved_at,
                    "last_attempt_at": retrieved_at,
                    "last_error": None,
                    "decisions": decisions,
                }
            )
            all_revisions.extend(
                detect_revisions(bank, prior_decisions, decisions, retrieved_at)
            )
        except Exception as exc:
            if prior_block and prior_block.get("status") == "verified" and prior_decisions:
                calendar["banks"][bank] = {
                    "timezone": BANK_META[bank]["timezone"],
                    "source_url": SOURCE_URLS[bank],
                    "status": "verified",
                    "retrieved_at": prior_block.get("retrieved_at"),
                    "last_attempt_at": retrieved_at,
                    "last_error": str(exc),
                    "decisions": deepcopy(prior_decisions),
                }
            else:
                calendar["banks"][bank].update(
                    {
                        "status": "unavailable",
                        "retrieved_at": prior_block.get("retrieved_at") if prior_block else None,
                        "last_attempt_at": retrieved_at,
                        "last_error": str(exc),
                        "decisions": [],
                    }
                )

    calendar["revisions"] = all_revisions[-100:]
    if save:
        write_calendar(calendar, root)
    return calendar
