"""Wire Policy / Transmission rates to an accepted official decision.

The v6 dashboard hard-codes a Fed target range. The accepted range is the
Federal Reserve policy-decision card already inserted by the daily refresh.
This module reads that card. It does not invent a rate. A missing or stale
card is labeled, and the old hard-coded number is not left in place.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

# A standing policy decision stays current across an FOMC cycle. Past this
# age the page must say the record is stale instead of calling it current.
POLICY_MAX_AGE_DAYS = 70

_CARD = re.compile(
    r'<article class="news-card[^"]*"[^>]*data-date="(\d{4}-\d{2}-\d{2})"[^>]*>(.*?)</article>',
    re.S,
)
_RANGE = re.compile(
    r"target range to\s+([0-9]+(?:\.[0-9]+)?)[\u2013-]([0-9]+(?:\.[0-9]+)?)%",
    re.I,
)
_HREF = re.compile(r'href="(https://www\.federalreserve\.gov[^"]+)"')

_HARD_CODED_CLAUSES = (
    ("Fed target range:", None),
    (
        "BoC target overnight rate:",
        "BoC target overnight rate: unavailable, because no current official Bank of Canada policy-rate record is on this page and an older hard-coded rate is not shown.",
    ),
    (
        "RBA cash rate:",
        "RBA cash rate: unavailable, because no current official Reserve Bank of Australia policy-rate record is on this page and an older hard-coded rate is not shown.",
    ),
    (
        "RBNZ raised the OCR to",
        "RBNZ official cash rate: unavailable, because no current official Reserve Bank of New Zealand policy-rate record is on this page and an older hard-coded rate is not shown.",
    ),
)


def extract_us_fed_decision(page: str) -> dict[str, Any] | None:
    """Official FOMC target range already present as a policy-decision card."""
    for decision_date, body in _CARD.findall(page):
        if "Federal Reserve" not in body or "Policy Decision" not in body:
            continue
        title_match = re.search(r"<h3>(.*?)</h3>", body, re.S)
        if not title_match:
            continue
        title = re.sub(r"<[^>]+>", "", title_match.group(1))
        title = title.replace("&ndash;", "–").replace("&#8211;", "–")
        range_match = _RANGE.search(title)
        url_match = _HREF.search(body)
        if not range_match or not url_match:
            continue
        lower = float(range_match.group(1))
        upper = float(range_match.group(2))
        return {
            "lower": lower,
            "upper": upper,
            "decision_date": decision_date,
            "source_url": url_match.group(1),
            "source_name": "Federal Reserve",
            "display": f"{lower:.2f}%-{upper:.2f}%",
        }
    return None


def policy_rate_status(decision: dict[str, Any] | None, as_of: date) -> str:
    if not decision or not decision.get("source_url") or not decision.get("display"):
        return "unavailable"
    try:
        decided = date.fromisoformat(str(decision["decision_date"]))
    except ValueError:
        return "unavailable"
    if decided > as_of:
        return "unavailable"
    if (as_of - decided).days > POLICY_MAX_AGE_DAYS:
        return "stale"
    return "current"


def us_policy_clause(page: str, *, as_of: date) -> str:
    decision = extract_us_fed_decision(page)
    status = policy_rate_status(decision, as_of)
    if status == "current" and decision is not None:
        decided = date.fromisoformat(str(decision["decision_date"]))
        label = decided.strftime("%d %b %Y").lstrip("0")
        return (
            f'Fed target range: {decision["display"]} '
            f'(<a href="{decision["source_url"]}" rel="noopener noreferrer">'
            f"Federal Reserve policy decision, {label}</a>)."
        )
    if status == "stale":
        return (
            "Fed target range: stale, because the official policy-rate record on this page "
            "is older than the standing-decision window and is not shown as current."
        )
    return (
        "Fed target range: unavailable, because no current official Federal Reserve "
        "policy decision is on this page and an older hard-coded range is not shown."
    )


def rewrite_policy_transmission(page: str, *, as_of: date | None = None) -> str:
    """Replace hard-coded policy-rate sentences. Idempotent for the US clause."""
    as_of = as_of or date.today()
    if isinstance(as_of, datetime):
        as_of = as_of.date()
    us_clause = us_policy_clause(page, as_of=as_of)
    page = _replace_clause(page, "Fed target range:", us_clause)
    for prefix, clause in _HARD_CODED_CLAUSES:
        if prefix == "Fed target range:" or clause is None:
            continue
        page = _replace_clause(page, prefix, clause)
    return page


def _replace_clause(page: str, prefix: str, clause: str) -> str:
    start = page.find(prefix)
    if start < 0:
        return page
    paragraph_end = page.find("</p>", start)
    paragraph = page[start:paragraph_end if paragraph_end >= 0 else None]
    if paragraph.startswith(clause):
        return page
    end = _sentence_end(page, start)
    return page[:start] + clause + page[end:]


def _sentence_end(page: str, start: int) -> int:
    index = start
    while index < len(page):
        if page[index] == "." and not _decimal_point(page, index):
            return index + 1
        index += 1
    return len(page)


def _decimal_point(page: str, index: int) -> bool:
    return (
        index > 0
        and index + 1 < len(page)
        and page[index - 1].isdigit()
        and page[index + 1].isdigit()
    )
