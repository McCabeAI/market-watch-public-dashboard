"""ETA 538 advance weekly claims from official DOL press releases.

The Thursday pre-payroll print is read from ETA news-release PDFs. Each
release contributes only the advance week named in the advance sentence.
Revised prior weeks that appear in the same PDF are not emitted.

The key-gated DOL v4 API is not called. ETA 539 revised XML is not read.
If the latest official advance week is older than the week that should
already have printed, the batch fails closed (``due_missing``) and does
not invent a point or fall back to another dataset.
"""

from __future__ import annotations

import hashlib
import io
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from scripts.macro_ingestion.us_employment.cache import (
    cache_get,
    cache_put,
    is_challenge_page,
    open_url,
)
from scripts.macro_ingestion.us_employment.derived import week_contains_calendar_day

_NY = ZoneInfo("America/New_York")
_CACHE_KEY = "dol_advance_claims"
_CANONICAL_ALIAS = "https://www.dol.gov/ui/data.pdf"
_API_NOTE = "DOL v4 ui_national_weekly_claims requires X-API-KEY and was not called"
_HISTORY_LIMIT = 16
_LOOKBACK_WEEKS = 16
_WEEK_WINDOW_DAYS = 14

_SERIES_FIELDS = {
    "US.Labor.initial_claims": ("initial_claims_sa", "ETA538_INITIAL_CLAIMS_SA"),
    "US.Labor.initial_claims_4w": ("initial_claims_sa_4w", "ETA538_INITIAL_CLAIMS_SA4WK"),
    "US.Labor.continuing_claims": ("continued_claims_sa", "ETA538_CONTINUED_CLAIMS_SA"),
    "US.Labor.insured_unemployment_rate": ("iur_sa", "ETA538_IUR_SA"),
}

_COUNT = r"(\d{1,3}(?:,\d{3})+|\d+)"
_EMBARGO_RE = re.compile(
    r"EMBARGOED UNTIL\s+8:30\s+A\.M\.\s+\(Eastern\)\s+"
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
    r"([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})",
    re.IGNORECASE,
)
_INITIAL_RE = re.compile(
    r"In the week ending\s+([A-Za-z]+)\s+(\d{1,2}),\s+"
    r"the advance figure for seasonally adjusted initial claims was\s+"
    + _COUNT,
    re.IGNORECASE,
)
_FOUR_WEEK_RE = re.compile(
    r"The 4-week moving average was\s+" + _COUNT,
    re.IGNORECASE,
)
_IUR_RE = re.compile(
    r"The advance seasonally adjusted insured unemployment rate was\s+"
    r"(\d+(?:\.\d+)?)\s+percent for the week ending\s+([A-Za-z]+)\s+(\d{1,2})",
    re.IGNORECASE,
)
_CONTINUED_RE = re.compile(
    r"The advance number for seasonally adjusted insured unemployment during the week ending\s+"
    r"([A-Za-z]+)\s+(\d{1,2}),?\s+was\s+"
    + _COUNT,
    re.IGNORECASE,
)
_COVERED_RE = re.compile(
    r"Most recent week used covered employment of\s+" + _COUNT + r"\s+as denominator",
    re.IGNORECASE,
)
_INSURED_RE = re.compile(r"insured unemployment", re.IGNORECASE)
_PDF_NAME_RE = re.compile(r"(\d{6})\.pdf", re.IGNORECASE)


def expected_advance_week_ending(now: datetime) -> date:
    """Saturday week-ending date whose Thursday 08:30 ET advance print is out."""
    local = _as_ny(now)
    local_day = local.date()
    days_since_saturday = (local_day.weekday() - 5) % 7
    saturday = local_day - timedelta(days=days_since_saturday)
    release_at = datetime.combine(
        saturday + timedelta(days=5),
        time(8, 30),
        tzinfo=_NY,
    )
    if local < release_at:
        saturday -= timedelta(days=7)
    return saturday


def first_friday(year: int, month: int) -> date:
    """First Friday of the calendar month."""
    opening = date(year, month, 1)
    return opening + timedelta(days=(4 - opening.weekday()) % 7)


def parse_advance_release_text(
    text: str,
    *,
    source_url: str,
    source_sha256: str,
) -> dict[str, Any] | None:
    """Parse one ETA 538 advance release. None when the advance week is unreadable."""
    collapsed = _collapse(text)
    release = _embargo_date(collapsed)
    initial = _INITIAL_RE.search(collapsed)
    if release is None or initial is None:
        return None
    initial_week = _week_ending(initial.group(1), int(initial.group(2)), release)
    if initial_week is None:
        return None
    parsed: dict[str, Any] = {
        "release_date": release.isoformat(),
        "source_url": source_url,
        "source_sha256": source_sha256,
        "initial_claims_sa": {
            "week_ending": initial_week.isoformat(),
            "value": _number(initial.group(3)),
        },
        "covered_employment": None,
    }
    after_initial = collapsed[initial.end():]
    insured = _INSURED_RE.search(after_initial)
    four_window = after_initial if insured is None else after_initial[: insured.start()]
    four_week = _FOUR_WEEK_RE.search(four_window)
    if four_week is not None:
        parsed["initial_claims_sa_4w"] = {
            "week_ending": initial_week.isoformat(),
            "value": _number(four_week.group(1)),
        }
    continued = _CONTINUED_RE.search(collapsed)
    continued_week: date | None = None
    if continued is not None:
        continued_week = _week_ending(continued.group(1), int(continued.group(2)), release)
        if continued_week is not None:
            parsed["continued_claims_sa"] = {
                "week_ending": continued_week.isoformat(),
                "value": _number(continued.group(3)),
            }
    iur = _IUR_RE.search(collapsed)
    if iur is not None:
        iur_week = continued_week or _week_ending(iur.group(2), int(iur.group(3)), release)
        if iur_week is not None:
            parsed["iur_sa"] = {
                "week_ending": iur_week.isoformat(),
                "value": _number(iur.group(1)),
            }
    covered = _COVERED_RE.search(collapsed)
    if covered is not None:
        parsed["covered_employment"] = _number(covered.group(1))
    return parsed


def load_advance_claims_batch(
    opener: Callable[..., Any],
    *,
    timeout: float,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Load advance ETA 538 releases. Fails closed when the due week is absent."""
    cached = cache_get(opener, _CACHE_KEY)
    if cached is not None:
        return cached
    when = now or datetime.now(timezone.utc)
    expected = expected_advance_week_ending(when)
    today = _as_ny(when).date()
    statuses: list[int] = []
    confirmed: dict[str, date] = {}
    for year in _index_years(expected):
        index_url = f"https://oui.doleta.gov/press/{year}/"
        response = open_url(opener, index_url, timeout=timeout)
        _remember(statuses, response)
        body = response.get("body") or b""
        if response.get("ok") and body and not is_challenge_page(body):
            for release_day, url in _urls_from_index(body):
                if release_day <= today:
                    confirmed[url] = release_day
    speculative: dict[str, date] = {}
    for release_day, url in _constructed_urls(expected, today):
        if url not in confirmed:
            speculative[url] = release_day
    selected = _select_press_urls(confirmed, speculative)
    parsed_rows: list[dict[str, Any]] = []
    bodies: dict[str, bytes] = {}
    for url in selected:
        response = open_url(opener, url, timeout=timeout)
        _remember(statuses, response)
        if not response.get("ok"):
            continue
        body = response.get("body") or b""
        parsed = _parse_body(body, url)
        if parsed is None:
            continue
        parsed_rows.append(parsed)
        bodies[url] = body

    alias_response = open_url(opener, _CANONICAL_ALIAS, timeout=timeout)
    _remember(statuses, alias_response)
    alias_status = alias_response.get("http_status")
    if isinstance(alias_status, int):
        canonical_alias_http_status: int | None = alias_status
    else:
        canonical_alias_http_status = None
    alias_body = alias_response.get("body") or b""
    if alias_response.get("ok") and alias_body.startswith(b"%PDF"):
        parsed = _parse_body(alias_body, _CANONICAL_ALIAS)
        if parsed is not None:
            have = {row["initial_claims_sa"]["week_ending"] for row in parsed_rows}
            if parsed["initial_claims_sa"]["week_ending"] not in have:
                parsed_rows.append(parsed)
                bodies[_CANONICAL_ALIAS] = alias_body

    if not parsed_rows:
        bundle = {
            "ok": False,
            "status": "source_failed",
            "error": _unavailable(statuses),
            "http_status": statuses[-1] if statuses else None,
            "body": b"",
            "canonical_alias_http_status": canonical_alias_http_status,
            "api_note": _API_NOTE,
            "expected_week_ending": expected.isoformat(),
        }
        return cache_put(opener, _CACHE_KEY, bundle)

    parsed_rows.sort(key=lambda row: row["release_date"])
    latest = max(date.fromisoformat(row["initial_claims_sa"]["week_ending"]) for row in parsed_rows)
    accepted = latest == expected or latest == expected + timedelta(days=7)
    if not accepted:
        if latest < expected:
            error = (
                "advance_claims_due_missing:"
                f"expected_week_ending={expected.isoformat()}:"
                f"latest_official_week_ending={latest.isoformat()}:"
                "source=eta_538"
            )
            status = "due_missing"
        else:
            error = _unavailable(statuses)
            status = "source_failed"
        stale = _choose_release(parsed_rows, latest)
        bundle = {
            "ok": False,
            "status": status,
            "error": error,
            "http_status": 200 if stale is not None else None,
            "body": b"" if stale is None else bodies.get(stale["source_url"], b""),
            "canonical_alias_http_status": canonical_alias_http_status,
            "api_note": _API_NOTE,
            "expected_week_ending": expected.isoformat(),
            "latest_initial_week_ending": latest.isoformat(),
        }
        return cache_put(opener, _CACHE_KEY, bundle)

    chosen = _choose_release(parsed_rows, latest)
    if chosen is None:
        bundle = {
            "ok": False,
            "status": "source_failed",
            "error": _unavailable(statuses),
            "http_status": statuses[-1] if statuses else None,
            "body": b"",
            "canonical_alias_http_status": canonical_alias_http_status,
            "api_note": _API_NOTE,
            "expected_week_ending": expected.isoformat(),
        }
        return cache_put(opener, _CACHE_KEY, bundle)
    body = bodies.get(chosen["source_url"], b"")
    bundle = {
        "ok": True,
        "releases": parsed_rows,
        "latest_initial_week_ending": latest.isoformat(),
        "expected_week_ending": expected.isoformat(),
        "body": body,
        "raw_sha256": chosen["source_sha256"],
        "http_status": 200,
        "batch_url": chosen["source_url"],
        "canonical_alias_http_status": canonical_alias_http_status,
        "api_note": _API_NOTE,
    }
    return cache_put(opener, _CACHE_KEY, bundle)


def fetch_advance_claims_series(
    spec: dict[str, Any],
    *,
    opener: Callable[..., Any],
    timeout: float,
    now: datetime | None = None,
) -> dict[str, Any]:
    """One advance ETA 538 series. Passes ``due_missing`` and ``source_failed`` through."""
    catalog_id = str(spec.get("id") or "")
    mapped = _SERIES_FIELDS.get(catalog_id)
    if mapped is None:
        return {
            "ok": False,
            "status": "source_failed",
            "error": "claims_series_not_in_advance_batch",
        }
    field_name, series_id = mapped
    bundle = load_advance_claims_batch(opener, timeout=timeout, now=now)
    if not bundle.get("ok"):
        result: dict[str, Any] = {
            "ok": False,
            "status": bundle.get("status") or "source_failed",
            "error": bundle.get("error") or "dol_advance_claims_unavailable",
        }
        if "body" in bundle:
            result["body"] = bundle.get("body") or b""
        if bundle.get("http_status") is not None:
            result["http_status"] = bundle.get("http_status")
        return result
    transform = str(spec.get("transform") or "level")
    rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for release in bundle.get("releases") or []:
        field = release.get(field_name)
        if not isinstance(field, dict) or field.get("week_ending") is None or field.get("value") is None:
            continue
        rows.append((release, field))
    rows.sort(key=lambda item: (item[1]["week_ending"], item[0]["release_date"]))
    points: list[dict[str, Any]] = []
    previous: float | None = None
    for release, field in rows:
        week_ending = str(field["week_ending"])[:10]
        release_date = str(release["release_date"])[:10]
        reference_month = _cps_reference_month(week_ending)
        if reference_month is None:
            payroll_bound = None
            available = None
        else:
            payroll_bound = _payroll_release_bound(reference_month)
            available = date.fromisoformat(release_date) < date.fromisoformat(payroll_bound)
        point: dict[str, Any] = {
            "period": week_ending,
            "value": float(field["value"]),
            "transformation": transform,
            "revision_status": "advance",
            "source_url": release["source_url"],
            "vintage": release_date,
            "derivation": {
                "publisher": "U.S. Department of Labor",
                "report": "ETA 538",
                "claims_form": "ETA 538",
                "vintage_kind": "advance",
                "revision_status": "advance",
                "week_ending": week_ending,
                "advance_release_date": release_date,
                "source_sha256": release["source_sha256"],
                "cps_reference_week": reference_month is not None,
                "cps_reference_month": reference_month,
                "available_before_payroll": available,
                "payroll_release_bound": payroll_bound,
                "advance_embargo": True,
                "not_eta_539": True,
                "series_id": series_id,
            },
        }
        if previous is not None:
            point["prior"] = previous
        points.append(point)
        previous = float(field["value"])
    points = points[-_HISTORY_LIMIT:]
    if not points:
        return {
            "ok": False,
            "status": "source_failed",
            "error": "dol_advance_claims_series_empty",
            "http_status": bundle.get("http_status"),
            "body": bundle.get("body") or b"",
        }
    return {
        "ok": True,
        "points": points,
        "vintage": points[-1]["vintage"],
        "raw_sha256": bundle.get("raw_sha256"),
        "http_status": bundle.get("http_status"),
        "body": bundle.get("body") or b"",
    }


def _as_ny(now: datetime) -> datetime:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(_NY)


def _collapse(text: str) -> str:
    text = (
        text.replace("\u00a0", " ")
        .replace("\u202f", " ")
        .replace("\u2009", " ")
        .replace("\u2007", " ")
        .replace("\u00ad", "")
        .replace("\u2011", "-")
        .replace("\u2010", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
    )
    return re.sub(r"\s+", " ", text).strip()


def _number(token: str) -> float:
    return float(token.replace(",", ""))


def _month_number(name: str) -> int | None:
    try:
        return datetime.strptime(name.title(), "%B").month
    except ValueError:
        return None


def _embargo_date(text: str) -> date | None:
    match = _EMBARGO_RE.search(text)
    if match is None:
        return None
    month = _month_number(match.group(1))
    if month is None:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(2)))
    except ValueError:
        return None


def _week_ending(month_name: str, day: int, release: date) -> date | None:
    """Month/day from the sentence, year from the embargo, inside the prior 14 days."""
    month = _month_number(month_name)
    if month is None:
        return None
    try:
        candidate = date(release.year, month, day)
    except ValueError:
        return None
    if candidate > release:
        try:
            candidate = date(release.year - 1, month, day)
        except ValueError:
            return None
    delta = (release - candidate).days
    if delta < 0 or delta > _WEEK_WINDOW_DAYS:
        return None
    return candidate


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _press_url(release_day: date) -> str:
    stamp = f"{release_day.month:02d}{release_day.day:02d}{release_day.year % 100:02d}"
    return f"https://oui.doleta.gov/press/{release_day.year}/{stamp}.pdf"


def _date_from_stamp(token: str) -> date | None:
    if len(token) != 6 or not token.isdigit():
        return None
    month, day, year_2 = int(token[0:2]), int(token[2:4]), int(token[4:6])
    year = 2000 + year_2 if year_2 < 80 else 1900 + year_2
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _index_years(expected: date) -> list[int]:
    release_year = (expected + timedelta(days=5)).year
    years = [release_year]
    if expected.month == 1 and expected.year - 1 not in years:
        years.append(expected.year - 1)
    return years


def _urls_from_index(body: bytes) -> list[tuple[date, str]]:
    text = body.decode("utf-8", errors="replace")
    found: list[tuple[date, str]] = []
    seen: set[str] = set()
    for match in _PDF_NAME_RE.finditer(text):
        token = match.group(1)
        if token in seen:
            continue
        seen.add(token)
        release_day = _date_from_stamp(token)
        if release_day is None:
            continue
        found.append((release_day, _press_url(release_day)))
    return found


def _constructed_urls(expected: date, today: date) -> list[tuple[date, str]]:
    found: list[tuple[date, str]] = []
    for week in range(_LOOKBACK_WEEKS + 1):
        saturday = expected - timedelta(days=7 * week)
        for offset in (4, 5, 6):
            release_day = saturday + timedelta(days=offset)
            if release_day <= today:
                found.append((release_day, _press_url(release_day)))
    return found


def _select_press_urls(confirmed: dict[str, date], speculative: dict[str, date]) -> list[str]:
    """At most 16 press PDFs. Indexed files win over older guessed Wed/Fri URLs."""
    confirmed_rows = sorted(confirmed.items(), key=lambda item: item[1], reverse=True)
    if confirmed_rows:
        newest = confirmed_rows[0][1]
        leading = [item for item in speculative.items() if item[1] > newest]
    else:
        leading = list(speculative.items())
    pool = leading + confirmed_rows
    pool.sort(key=lambda item: item[1], reverse=True)
    return [url for url, _day in pool[:_HISTORY_LIMIT]]


def _remember(statuses: list[int], response: dict[str, Any]) -> None:
    code = response.get("http_status")
    if isinstance(code, int):
        statuses.append(code)


def _unavailable(statuses: list[int]) -> str:
    joined = ",".join(str(code) for code in statuses)
    return f"dol_advance_claims_unavailable:http_statuses={joined}"


def _release_text(body: bytes) -> str | None:
    if not body:
        return None
    if body.startswith(b"%PDF"):
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(body))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception:
            return None
    if is_challenge_page(body):
        return None
    return body.decode("utf-8", errors="replace")


def _parse_body(body: bytes, url: str) -> dict[str, Any] | None:
    text = _release_text(body)
    if not text:
        return None
    return parse_advance_release_text(text, source_url=url, source_sha256=_sha256(body))


def _choose_release(rows: list[dict[str, Any]], latest: date) -> dict[str, Any] | None:
    latest_iso = latest.isoformat()
    matching = [row for row in rows if row["initial_claims_sa"]["week_ending"] == latest_iso]
    press = [row for row in matching if row.get("source_url") != _CANONICAL_ALIAS]
    pool = press or matching
    if not pool:
        return None
    pool.sort(key=lambda row: row["release_date"])
    return pool[-1]


def _cps_reference_month(week_ending: str) -> str | None:
    if not week_contains_calendar_day(week_ending, 12):
        return None
    end = date.fromisoformat(week_ending[:10])
    start = end - timedelta(days=6)
    for offset in range(7):
        day = start + timedelta(days=offset)
        if day.day == 12:
            return f"{day.year:04d}-{day.month:02d}"
    return None


def _payroll_release_bound(reference_month: str) -> str:
    year, month = (int(part) for part in reference_month.split("-"))
    if month == 12:
        year, month = year + 1, 1
    else:
        month += 1
    return first_friday(year, month).isoformat()
