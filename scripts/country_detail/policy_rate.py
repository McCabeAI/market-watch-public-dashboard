"""Render Policy / Transmission lines from canonical policy state.

The rate comes from ``data/policy_state.json`` via ``scripts.policy_state``.
This module does not parse dashboard HTML, news cards, headlines, or prose,
and it has no hard-coded current rate to fall back on.
"""

from __future__ import annotations

import html
import re
from datetime import date, datetime
from typing import Any

from scripts.policy_state import resolve_country

# Canonical label, then legacy sentence starts that the v6 dashboard still uses.
_PANELS: dict[str, tuple[str, ...]] = {
    "US": ("Fed target range:",),
    "CA": ("BoC target overnight rate:",),
    "AU": ("RBA cash rate:",),
    "NZ": ("RBNZ official cash rate:", "RBNZ raised the OCR to"),
    "EA": ("ECB deposit facility rate:",),
    "JP": ("BoJ policy rate:",),
}

_BANKS = {
    "US": "Federal Reserve",
    "CA": "Bank of Canada",
    "AU": "Reserve Bank of Australia",
    "NZ": "Reserve Bank of New Zealand",
    "EA": "European Central Bank",
    "JP": "Bank of Japan",
}
_BADGE_CODE = {"Fed": "US", "BoC": "CA", "RBA": "AU", "RBNZ": "NZ"}
_BADGE_SHORT = {code: short for short, code in _BADGE_CODE.items()}
# Slot markers only. The previous number is not read.
_BADGE_SLOT = re.compile(r'(<span class="policy">)(Fed|BoC|RBA|RBNZ)\b[^<]*')
_MATRIX_RATE_CELL = re.compile(
    r"(<tr>\s*<td>\s*<b>(US|CA|AU|NZ)</b>\s*</td>(?:(?!</tr>).)*?<td>\s*)"
    r"\d+(?:\.\d+)?%(?:\s*[–-]\s*\d+(?:\.\d+)?%)?"
    r"(\s*</td>)",
    re.S,
)


def _as_date(as_of: date | datetime | None) -> date:
    if as_of is None:
        return date.today()
    if isinstance(as_of, datetime):
        return as_of.date()
    return as_of


def _label(code: str) -> str:
    return _PANELS[code][0].rstrip(":")


def _display_rate(decision: dict[str, Any]) -> str | None:
    lower = decision.get("lower")
    upper = decision.get("upper")
    if lower is not None and upper is not None:
        return f"{float(lower):.2f}%-{float(upper):.2f}%"
    rate = decision.get("rate")
    if rate is None:
        return None
    return f"{float(rate):.2f}%"


def _long_date(iso_day: str) -> str:
    return date.fromisoformat(iso_day).strftime("%d %b %Y").lstrip("0")


def policy_clause(code: str, policy_state: dict[str, Any] | None, as_of: date) -> str:
    """One policy sentence for a country. Does not read page markup."""
    label = _label(code)
    bank = _BANKS[code]
    resolved = resolve_country(policy_state, code, as_of)
    status = resolved["status"]
    decision = resolved["decision"]
    if status == "current" and decision is not None:
        display = _display_rate(decision)
        source_url = str(decision.get("source_url") or "")
        if display and source_url.startswith("https://"):
            decided = _long_date(str(decision["decision_date"]))
            source_name = html.escape(str(decision.get("source_name") or bank))
            href = html.escape(source_url, quote=True)
            effective = decision.get("effective_date")
            effective_text = f", effective {_long_date(str(effective))}" if effective else ""
            return (
                f'{label}: {display} '
                f'(<a href="{href}" rel="noopener noreferrer">'
                f"{source_name} policy decision, {decided}</a>{effective_text})."
            )
        status = "unavailable"
    if status == "missing":
        return (
            f"{label}: missing, because no canonical policy-state record exists "
            "for this country and an older hard-coded rate is not shown."
        )
    if status == "stale":
        return (
            f"{label}: stale, because the canonical policy-state record is not a "
            "verified standing decision and is not shown as current."
        )
    return (
        f"{label}: unavailable, because the canonical policy state has no verified "
        f"{bank} rate and an older hard-coded rate is not shown."
    )


def policy_badge(code: str, policy_state: dict[str, Any] | None, as_of: date) -> str:
    """Compact board label. A missing or unverified setting is not a number."""
    short = _BADGE_SHORT[code]
    resolved = resolve_country(policy_state, code, as_of)
    decision = resolved["decision"]
    if resolved["status"] == "current" and decision is not None:
        display = _display_rate(decision)
        if display:
            return f"{short} {display}"
    return f"{short} {resolved['status']}"


def rewrite_policy_transmission(
    page: str,
    *,
    policy_state: dict[str, Any] | None,
    as_of: date | datetime | None = None,
) -> str:
    """Replace hard-coded policy sentences from structured state. Idempotent."""
    on = _as_date(as_of)
    for code, prefixes in _PANELS.items():
        clause = policy_clause(code, policy_state, on)
        for prefix in prefixes:
            page = _replace_clause(page, prefix, clause)
    page = _rewrite_badges(page, policy_state, on)
    page = _rewrite_matrix_rates(page, policy_state, on)
    return page


def _rewrite_badges(page: str, policy_state: dict[str, Any] | None, as_of: date) -> str:
    def replace(match: re.Match[str]) -> str:
        code = _BADGE_CODE[match.group(2)]
        return match.group(1) + policy_badge(code, policy_state, as_of)

    return _BADGE_SLOT.sub(replace, page)


def _rewrite_matrix_rates(page: str, policy_state: dict[str, Any] | None, as_of: date) -> str:
    """Replace a Policy-column cell whose entire value is a hard-coded rate."""

    def replace(match: re.Match[str]) -> str:
        code = match.group(2)
        resolved = resolve_country(policy_state, code, as_of)
        decision = resolved["decision"]
        if resolved["status"] == "current" and decision is not None:
            display = _display_rate(decision)
            if display:
                return f"{match.group(1)}{display}{match.group(3)}"
        return f"{match.group(1)}{resolved['status']}{match.group(3)}"

    return _MATRIX_RATE_CELL.sub(replace, page)


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
