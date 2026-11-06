"""Monetary policy meetings fold for country detail pages."""

from __future__ import annotations

import html
import re
from typing import Any, Mapping

_EM = "—"
_BANK_ANCHOR_LABEL = {
    "US": "Fed target midpoint",
    "CA": "BoC target overnight rate",
    "AU": "RBA cash rate target",
    "NZ": "RBNZ official cash rate",
    "EA": "ECB deposit facility rate",
    "JP": "BoJ policy rate guideline",
}


def _esc(text: Any) -> str:
    if text is None:
        return ""
    return html.escape(str(text), quote=True)


def _fmt_rate(value: Any) -> str:
    if value is None:
        return _EM
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _EM
    if number != number:
        return _EM
    return f"{number:.2f}%"


def _fmt_bp(value: Any) -> str:
    if value is None:
        return _EM
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _EM
    if number != number:
        return _EM
    text = f"{number:+.2f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _fmt_method(method: Any) -> str:
    if method is None or method == "":
        return "unavailable"
    return str(method).replace("_", " ")


def _short_date(iso_day: str) -> str:
    text = str(iso_day).strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return text


def _pretty_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    daily = re.fullmatch(r"(\d{4}-\d{2}-\d{2})", text)
    if daily:
        return daily.group(1)
    if "T" in text:
        return text.split("T", 1)[0]
    return text


def _reason(prices: Mapping[str, Any] | None, calendar: Mapping[str, Any] | None) -> str | None:
    for block in (prices, calendar):
        if not block:
            continue
        reason = block.get("reason")
        if reason:
            return str(reason)
    return None


def _calendar_upcoming(calendar: Mapping[str, Any] | None, limit: int = 5) -> list[Mapping[str, Any]]:
    if not calendar:
        return []
    decisions = calendar.get("decisions") or []
    upcoming: list[Mapping[str, Any]] = []
    for row in decisions:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("state") or "") != "upcoming":
            continue
        upcoming.append(row)
        if len(upcoming) >= limit:
            break
    return upcoming


def _meeting_rows(
    prices: Mapping[str, Any] | None,
    calendar: Mapping[str, Any] | None,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    if prices:
        raw = prices.get("meetings")
        if isinstance(raw, list) and raw:
            rows: list[dict[str, Any]] = []
            for item in raw[:limit]:
                if not isinstance(item, Mapping):
                    continue
                rows.append(dict(item))
            if rows:
                return rows

    cal_rows = _calendar_upcoming(calendar, limit=limit)
    if not cal_rows:
        return []

    return [
        {
            "decision_date": row.get("decision_date"),
            "post_rate": None,
            "incremental_bp": None,
            "cumulative_bp": None,
            "chg_1d_bp": None,
            "chg_1w_bp": None,
            "method": None,
        }
        for row in cal_rows
    ]


def _render_table(rows: list[dict[str, Any]]) -> str:
    head = (
        "<thead><tr>"
        "<th>Decision</th>"
        "<th>Implied rate</th>"
        "<th>Step bp</th>"
        "<th>Cumulative bp</th>"
        "<th>1d</th>"
        "<th>1w</th>"
        "<th>Method</th>"
        "</tr></thead>"
    )
    body_parts: list[str] = ["<tbody>"]
    for row in rows:
        decision = _short_date(str(row.get("decision_date") or ""))
        body_parts.append(
            "<tr>"
            f"<td>{_esc(decision)}</td>"
            f"<td>{_esc(_fmt_rate(row.get('post_rate')))}</td>"
            f"<td>{_esc(_fmt_bp(row.get('incremental_bp')))}</td>"
            f"<td>{_esc(_fmt_bp(row.get('cumulative_bp')))}</td>"
            f"<td>{_esc(_fmt_bp(row.get('chg_1d_bp')))}</td>"
            f"<td>{_esc(_fmt_bp(row.get('chg_1w_bp')))}</td>"
            f"<td>{_esc(_fmt_method(row.get('method')))}</td>"
            "</tr>"
        )
    body_parts.append("</tbody>")
    return (
        '<div class="table-wrap"><table>'
        f"{head}{''.join(body_parts)}"
        "</table></div>"
    )


def _render_source(
    code: str,
    prices: Mapping[str, Any] | None,
    calendar: Mapping[str, Any] | None,
) -> str:
    parts: list[str] = []
    if prices:
        anchor = prices.get("anchor")
        if anchor is not None:
            label = str(prices.get("anchor_name") or _BANK_ANCHOR_LABEL.get(code) or "Anchor")
            parts.append(f"{label} {_fmt_rate(anchor)}")
        futures_as_of = _pretty_timestamp(prices.get("futures_as_of"))
        if futures_as_of:
            parts.append(f"futures as of {futures_as_of}")
        basis = prices.get("basis_bp")
        if basis is not None:
            parts.append(f"basis {_fmt_bp(basis)} bp")

    calendar_retrieved = None
    if prices:
        calendar_retrieved = _pretty_timestamp(prices.get("calendar_retrieved_at"))
    if calendar_retrieved is None and calendar:
        calendar_retrieved = _pretty_timestamp(calendar.get("retrieved_at"))
    if calendar_retrieved:
        parts.append(f"calendar retrieved {calendar_retrieved}")

    if not parts:
        return ""
    prose = "; ".join(parts) + "."
    return f'<p class="policy-meetings-source">{_esc(prose)}</p>'


def render_policy_meetings(
    code: str,
    prices: dict | None,
    calendar: dict | None,
) -> str:
    """Render the Monetary policy fold for one economy."""
    bank_code = str(code)
    price_block: Mapping[str, Any] | None = prices if isinstance(prices, Mapping) else None
    calendar_block: Mapping[str, Any] | None = calendar if isinstance(calendar, Mapping) else None

    rows = _meeting_rows(price_block, calendar_block)
    reason = _reason(price_block, calendar_block)

    chunks = [
        '<details class="policy-meetings">',
        "<summary>Monetary policy</summary>",
    ]
    if rows:
        chunks.append(_render_table(rows))
        source = _render_source(bank_code, price_block, calendar_block)
        if source:
            chunks.append(source)
    elif reason:
        chunks.append(f"<p>{_esc(reason)}</p>")
    chunks.append("</details>")
    return "".join(chunks)
