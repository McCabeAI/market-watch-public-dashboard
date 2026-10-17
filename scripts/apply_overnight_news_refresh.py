from __future__ import annotations

import argparse
import html as html_lib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scripts.overnight.accepted_news import (
    load_accepted_public_news,
    morning_dataset_from_public_news,
)
from scripts.overnight.public_prose import public_research_summary
from scripts.overnight.research_publishability import audit_agent_research

NY = ZoneInfo("America/New_York")
LAST24_START = '<div class="last24">'
ROLLUP_START = '<div class="stitle">Top Market Drivers</div>'
ROLLUP_END = '<div class="x-signal">'
UNDATED_PROVENANCE_ATTR = 'data-news-provenance="undated"'


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=NY)
    return stamp.astimezone(NY)


def _load_dataset(root: Path, dataset_path: Path | None = None) -> dict[str, Any]:
    if dataset_path is not None:
        if not dataset_path.is_file():
            raise ValueError(f"assembled dataset missing: {dataset_path}")
        dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
        if dataset.get("type") != "OVERNIGHT_MORNING_DATASET":
            raise ValueError("assembled dataset type mismatch")
        return dataset

    latest_path = root / "data" / "overnight" / "latest.json"
    if latest_path.is_file():
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        rel = latest.get("assembled_dataset")
        if rel:
            path = root / rel
            if path.is_file():
                dataset = json.loads(path.read_text(encoding="utf-8"))
                if dataset.get("type") == "OVERNIGHT_MORNING_DATASET":
                    return dataset

    artifact = load_accepted_public_news(root)
    if artifact is None:
        raise ValueError("no assembled dataset or accepted_public_news.json available")
    return morning_dataset_from_public_news(artifact)


def _cutoff(dataset: dict[str, Any]) -> datetime:
    raw = dataset.get("agent_research_cutoff") or dataset.get("as_of")
    stamp = _parse_iso(raw)
    if stamp is None:
        raise ValueError("assembled dataset missing a valid agent research cutoff")
    return stamp


def _display_title(raw: dict[str, Any]) -> str:
    # Central-bank research may carry title instead of headline.
    return str(raw.get("headline") or raw.get("title") or "").strip()


def _item_url(raw: dict[str, Any]) -> str:
    # URL is optional in the canonical accepted-research contract.
    return str(raw.get("url") or "").strip()


def _normalize_raw_item(raw: dict[str, Any], *, family: str) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    title = _display_title(raw)
    url = _item_url(raw)
    summary = str(raw.get("summary") or "").strip()
    if not title or not summary:
        return None
    item = dict(raw)
    item["headline"] = title
    item["summary"] = summary
    if url:
        item["url"] = url
    else:
        item.pop("url", None)
    item["_family"] = family
    return item


def _partition_items(dataset: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split accepted research into dated (time-window eligible) and undated renderables."""
    research = dataset.get("agent_research") or {}
    dated_combined: list[dict[str, Any]] = []
    undated_combined: list[dict[str, Any]] = []
    for family, items in (
        ("news", research.get("news") or []),
        ("central_bank_research", research.get("central_bank_research") or []),
    ):
        for raw in items:
            item = _normalize_raw_item(raw, family=family)
            if item is None:
                continue
            published = _parse_iso(raw.get("published_at"))
            if published is not None:
                item["_published"] = published
                dated_combined.append(item)
            elif raw.get("published_at") in (None, ""):
                undated_combined.append(item)
            # Malformed published_at values are excluded (fail-closed for time windows).

    def _dedupe(rows: list[dict[str, Any]], *, sort_key) -> list[dict[str, Any]]:
        seen: set[tuple[str, str]] = set()
        out: list[dict[str, Any]] = []
        for item in sorted(rows, key=sort_key, reverse=True):
            key = (_item_url(item), _display_title(item))
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

    dated = _dedupe(dated_combined, sort_key=lambda row: row["_published"])
    undated = _dedupe(undated_combined, sort_key=lambda row: (_impact(row)[0] == "HIGH", _display_title(row)))
    return dated, undated


def _clean_items(dataset: dict[str, Any]) -> list[dict[str, Any]]:
    """Dated items only — preserved for callers expecting the rolling-window list."""
    dated, _undated = _partition_items(dataset)
    return dated


def _impact(item: dict[str, Any]) -> tuple[str, str]:
    category = str(item.get("primary_category") or "").lower()
    family = item.get("_family")
    blob = " ".join(
        str(item.get(k) or "").lower()
        for k in ("headline", "title", "summary", "institution", "source_name")
    )
    high = (
        family == "central_bank_research"
        or category in {"energy", "inflation", "monetary_policy", "rates"}
        or any(token in blob for token in ("rate", "inflation", "oil", "cpi", "fomc", "central bank"))
    )
    return ("HIGH", "high") if high else ("MED", "med")


def _market_label(item: dict[str, Any]) -> str:
    countries = [str(x).upper() for x in (item.get("country_codes") or []) if x]
    country = " / ".join(countries[:3]) if countries else "GLOBAL"
    category = str(item.get("primary_category") or item.get("institution") or "MACRO")
    return f"{country} · {category.replace('_', ' ').upper()}"


def _source_label(item: dict[str, Any]) -> str:
    return str(item.get("source_name") or item.get("institution") or "Source").strip()


def _day_label(stamp: datetime) -> str:
    return f"{stamp.day} {stamp.strftime('%b')}"


def _window_label(start: datetime, end: datetime) -> str:
    return (
        f"{start.day} {start.strftime('%b')} {start.strftime('%H:%M')} ET → "
        f"{end.day} {end.strftime('%b')} {end.strftime('%H:%M')} ET"
    )


def _esc(value: Any) -> str:
    return html_lib.escape(str(value), quote=True)


def _driver_card(row: dict[str, Any], *, kicker: str) -> str:
    impact, css = _impact(row)
    inner = (
        f'<div class="dmeta"><span class="impact {css}">{impact}</span>{_esc(kicker)}</div>'
        f'<b>{_esc(row["headline"])}</b><span>{_esc(row["summary"])}</span>'
    )
    url = _item_url(row)
    if url:
        return f'<a class="driver-card" href="{_esc(url)}" rel="noopener" target="_blank">{inner}</a>'
    return f'<div class="driver-card">{inner}</div>'


def _story_details(row: dict[str, Any], *, kicker: str) -> str:
    impact, css = _impact(row)
    source = ""
    url = _item_url(row)
    if url:
        source = (
            f'<a class="story-source" href="{_esc(url)}" rel="noopener" target="_blank">Open source ↗</a>'
        )
    return (
        '<details class="story"><summary>'
        f'<span class="impact {css}">{impact}</span><span>'
        f'<span class="story-title">{_esc(row["headline"])}</span>'
        f'<span class="story-kicker">{_esc(kicker)}</span></span></summary>'
        f'<div class="story-body"><p><b>What happened:</b> {_esc(row["summary"])}</p>'
        f"{source}"
        "</div></details>"
    )


def _last24_html(dated_items: list[dict[str, Any]], cutoff: datetime, summary: str | None) -> str:
    start = cutoff - timedelta(hours=24)
    current = [row for row in dated_items if start <= row["_published"] <= cutoff][:6]
    headline = current[0]["headline"] if current else "No dated market driver in the rolling 24-hour window"
    desk_read = public_research_summary(summary, items=current)
    cards: list[str] = []
    for row in current:
        impact, _ = _impact(row)
        stamp = row["_published"]
        body = (
            f'      <div class="meta">{_esc(_market_label(row))} · {impact}/10 · {_esc(_source_label(row).upper())} {_esc(_day_label(stamp).upper())}</div>\n'
            f'      <b>{_esc(row["headline"])}</b>\n'
            f'      <span>{_esc(row["summary"])}</span>'
        )
        url = _item_url(row)
        if url:
            cards.append(
                f'    <a class="last24-item" href="{_esc(url)}" target="_blank" rel="noopener">\n'
                f"{body}\n"
                "    </a>"
            )
        else:
            cards.append(f'    <div class="last24-item">\n{body}\n    </div>')
    if not cards:
        cards.append(
            '    <div class="last24-empty">No accepted overnight research item with a verified publication timestamp fell inside the exact rolling 24-hour window.</div>'
        )
    plural = "s" if len(current) != 1 else ""
    return (
        '<div class="last24">\n'
        '  <div class="last24-head">\n'
        '    <div>\n'
        '      <div class="stitle">Last 24 Hours · Desk Summary</div>\n'
        f'      <h2>{_esc(headline)}</h2>\n'
        f'      <p>{len(current)} dated market-relevant development{plural} in the exact rolling window.</p>\n'
        '    </div>\n'
        f'    <div class="last24-window"><b>Window</b>{_esc(_window_label(start, cutoff))}<br>'
        f'Last refreshed {cutoff.day} {cutoff.strftime("%b")} {cutoff.year} · {cutoff.strftime("%H:%M")} ET</div>\n'
        '  </div>\n'
        f'  <div class="last24-thesis"><b>Desk read:</b> {_esc(desk_read)}</div>\n'
        '  <div class="last24-grid">\n'
        + "\n".join(cards)
        + '\n  </div>\n</div>\n\n'
    )


def _dated_rollup_html(digest: list[dict[str, Any]], cutoff: datetime) -> str:
    start = cutoff - timedelta(days=7)
    ranked = sorted(
        digest,
        key=lambda row: (_impact(row)[0] == "HIGH", row["_published"]),
        reverse=True,
    )
    drivers = ranked[:3]
    driver_html = [
        _driver_card(
            row,
            kicker=_market_label(row),
        )
        for row in drivers
    ]

    stories = []
    for row in digest[:12]:
        stamp = row["_published"]
        kicker = f'{_market_label(row)} · {_day_label(stamp)} · {_source_label(row)}'
        stories.append(_story_details(row, kicker=kicker))

    return (
        '<div class="stitle">Top Market Drivers</div><div class="driver-grid">\n'
        + "\n".join(driver_html)
        + '\n</div>\n'
        '<div class="digest-tools"><div><div class="stitle">7-Day Quick Digest</div>'
        '<p>Accepted overnight research that still matters to the current macro and rates setup.</p></div>'
        f'<div class="scanline"><b>Window:</b> {_esc(_window_label(start, cutoff))}</div></div>\n'
        '<div class="news-digest">\n'
        + "\n".join(stories)
        + '\n</div>\n'
    )


def _undated_block_html(undated_items: list[dict[str, Any]], cutoff: datetime) -> str:
    ranked = sorted(
        undated_items,
        key=lambda row: (_impact(row)[0] == "HIGH", _display_title(row)),
        reverse=True,
    )
    drivers = ranked[:3]
    driver_html = [
        _driver_card(row, kicker=f"AGE UNVERIFIED · {_market_label(row)}") for row in drivers
    ]
    stories = []
    for row in ranked[:12]:
        kicker = f"AGE UNVERIFIED · {_market_label(row)} · {_source_label(row)}"
        stories.append(_story_details(row, kicker=kicker))

    accepted_label = (
        f"{cutoff.day} {cutoff.strftime('%b')} {cutoff.year} · {cutoff.strftime('%H:%M')} ET"
    )
    return (
        '<div class="stitle">Top Market Drivers</div><div class="driver-grid">\n'
        + "\n".join(driver_html)
        + '\n</div>\n'
        '<div class="digest-tools undated-research-tools" '
        + UNDATED_PROVENANCE_ATTR
        + '><div><div class="stitle">Accepted Overnight Research · Age Unverified</div>'
        "<p>These accepted summaries carry no verified publication timestamp. "
        "They are shown for desk context only and are not placed in the rolling 24-hour or 7-day windows.</p></div>"
        f'<div class="scanline"><b>Provenance:</b> Publication dates not supplied · packet accepted {accepted_label}</div></div>\n'
        '<div class="news-digest undated-research-digest">\n'
        + "\n".join(stories)
        + '\n</div>\n'
    )


def _undated_supplement_html(
    undated_items: list[dict[str, Any]],
    cutoff: datetime,
    *,
    max_stories: int = 12,
) -> str:
    ranked = sorted(
        undated_items,
        key=lambda row: (_impact(row)[0] == "HIGH", _display_title(row)),
        reverse=True,
    )
    stories = []
    for row in ranked[: max(0, min(12, max_stories))]:
        kicker = f"AGE UNVERIFIED · {_market_label(row)} · {_source_label(row)}"
        stories.append(_story_details(row, kicker=kicker))
    accepted_label = (
        f"{cutoff.day} {cutoff.strftime('%b')} {cutoff.year} · {cutoff.strftime('%H:%M')} ET"
    )
    return (
        '<div class="digest-tools undated-research-tools" '
        + UNDATED_PROVENANCE_ATTR
        + '><div><div class="stitle">Additional Accepted Research · Age Unverified</div>'
        "<p>Accepted summaries below carry no verified publication timestamp and are excluded from the rolling windows above.</p></div>"
        f'<div class="scanline"><b>Provenance:</b> Publication dates not supplied · packet accepted {accepted_label}</div></div>\n'
        '<div class="news-digest undated-research-digest">\n'
        + "\n".join(stories)
        + '\n</div>\n'
    )


def _rollup_html(
    dated_items: list[dict[str, Any]],
    undated_items: list[dict[str, Any]],
    cutoff: datetime,
) -> str:
    start = cutoff - timedelta(days=7)
    digest = [row for row in dated_items if start <= row["_published"] <= cutoff]
    if digest:
        html = _dated_rollup_html(digest, cutoff)
        if undated_items:
            dated_story_count = min(len(digest), 12)
            extra_story_slots = max(0, 12 - dated_story_count)
            if extra_story_slots:
                html += _undated_supplement_html(
                    undated_items,
                    cutoff,
                    max_stories=extra_story_slots,
                )
        return html
    if undated_items:
        return _undated_block_html(undated_items, cutoff)
    raise ValueError("accepted overnight research has no renderable items for the rolling windows or undated fallback")


def _publication_identity(item: dict[str, Any]) -> tuple[str, str]:
    return (_item_url(item), _display_title(item))


def _publication_fields(item: dict[str, Any]) -> dict[str, Any]:
    family = str(item.get("_family") or "news")
    return {
        "headline": _display_title(item),
        "url": _item_url(item) or None,
        "source": str(item.get("source_name") or item.get("institution") or "").strip() or None,
        "published_at": item.get("published_at"),
        "id": item.get("id") if item.get("id") else None,
        "family": family,
    }


def _publication_row(
    item: dict[str, Any],
    *,
    outcome: str,
    reason: str,
    cap: int | None,
    slot: str | None,
) -> dict[str, Any]:
    return {
        **_publication_fields(item),
        "outcome": outcome,
        "reason": reason,
        "cap": cap,
        "slot": slot,
    }


def _raw_publication_row(
    raw: dict[str, Any],
    *,
    family: str,
    outcome: str,
    reason: str,
    cap: int | None,
    slot: str | None,
) -> dict[str, Any]:
    title = _display_title(raw)
    url = _item_url(raw)
    return {
        "headline": title or None,
        "url": url or None,
        "source": str(raw.get("source_name") or raw.get("institution") or "").strip() or None,
        "published_at": raw.get("published_at"),
        "id": raw.get("id") if raw.get("id") else None,
        "family": family,
        "outcome": outcome,
        "reason": reason,
        "cap": cap,
        "slot": slot,
    }


def explain_display_slots(dataset: dict[str, Any], *, cutoff: datetime) -> list[dict[str, Any]]:
    """Explain webpage slot membership using the same slice math as the HTML builders."""
    rows: list[dict[str, Any]] = []
    research = dataset.get("agent_research") or {}
    start_24 = cutoff - timedelta(hours=24)
    start_7 = cutoff - timedelta(days=7)

    dated_combined: list[dict[str, Any]] = []
    undated_combined: list[dict[str, Any]] = []

    for family, items in (
        ("news", research.get("news") or []),
        ("central_bank_research", research.get("central_bank_research") or []),
    ):
        for raw in items:
            if not isinstance(raw, dict):
                continue
            title = _display_title(raw)
            summary = str(raw.get("summary") or "").strip()
            if not title or not summary:
                rows.append(
                    _raw_publication_row(
                        raw,
                        family=family,
                        outcome="display_slot_drop",
                        reason="missing_title_or_summary",
                        cap=None,
                        slot=None,
                    )
                )
                continue

            published = _parse_iso(raw.get("published_at"))
            if raw.get("published_at") not in (None, "") and published is None:
                rows.append(
                    _raw_publication_row(
                        raw,
                        family=family,
                        outcome="display_slot_drop",
                        reason="malformed_timestamp",
                        cap=None,
                        slot=None,
                    )
                )
                continue

            item = _normalize_raw_item(raw, family=family)
            if item is None:
                continue
            if published is not None:
                item["_published"] = published
                dated_combined.append(item)
            else:
                undated_combined.append(item)

    dated_items, undated_items = _partition_items(dataset)

    def _dedupe_drops(combined: list[dict[str, Any]], *, sort_key) -> None:
        seen: set[tuple[str, str]] = set()
        for item in sorted(combined, key=sort_key, reverse=True):
            ident = _publication_identity(item)
            if ident in seen:
                rows.append(
                    _publication_row(
                        item,
                        outcome="display_slot_drop",
                        reason="deduped",
                        cap=None,
                        slot=None,
                    )
                )
                continue
            seen.add(ident)

    _dedupe_drops(dated_combined, sort_key=lambda row: row["_published"])
    _dedupe_drops(
        undated_combined,
        sort_key=lambda row: (_impact(row)[0] == "HIGH", _display_title(row)),
    )

    last24_pool = [row for row in dated_items if start_24 <= row["_published"] <= cutoff]
    last24_slots = {_publication_identity(row) for row in last24_pool[:6]}

    digest = [row for row in dated_items if start_7 <= row["_published"] <= cutoff]
    digest_ids = {_publication_identity(row) for row in digest}

    ranked_undated = sorted(
        undated_items,
        key=lambda row: (_impact(row)[0] == "HIGH", _display_title(row)),
        reverse=True,
    )

    driver_slots: set[tuple[str, str]] = set()
    dated_story_slots = {_publication_identity(row) for row in digest[:12]}

    if digest:
        ranked_drivers = sorted(
            digest,
            key=lambda row: (_impact(row)[0] == "HIGH", row["_published"]),
            reverse=True,
        )
        driver_slots = {_publication_identity(row) for row in ranked_drivers[:3]}
        supplement_rows = ranked_undated[: max(0, 12 - len(digest))] if undated_items else []
    elif undated_items:
        driver_slots = {_publication_identity(row) for row in ranked_undated[:3]}
        supplement_rows = ranked_undated[:12]
    else:
        supplement_rows = []

    supplement_slots = {_publication_identity(row) for row in supplement_rows}

    def _emit_last24(item: dict[str, Any]) -> None:
        ident = _publication_identity(item)
        published = item["_published"]
        if ident in last24_slots:
            rows.append(
                _publication_row(
                    item,
                    outcome="published",
                    reason="in_slot",
                    cap=6,
                    slot="last_24_hours",
                )
            )
        elif published < start_24 or published > cutoff:
            rows.append(
                _publication_row(
                    item,
                    outcome="display_slot_drop",
                    reason="outside_24h",
                    cap=6,
                    slot="last_24_hours",
                )
            )
        elif ident in {_publication_identity(row) for row in last24_pool}:
            rows.append(
                _publication_row(
                    item,
                    outcome="display_slot_drop",
                    reason="beyond_6",
                    cap=6,
                    slot="last_24_hours",
                )
            )

    def _emit_drivers(item: dict[str, Any]) -> None:
        ident = _publication_identity(item)
        if not digest and not undated_items:
            return
        if digest:
            if ident not in digest_ids:
                return
            if ident in driver_slots:
                rows.append(
                    _publication_row(
                        item,
                        outcome="published",
                        reason="in_slot",
                        cap=3,
                        slot="top_market_drivers",
                    )
                )
            else:
                rows.append(
                    _publication_row(
                        item,
                        outcome="display_slot_drop",
                        reason="beyond_3",
                        cap=3,
                        slot="top_market_drivers",
                    )
                )
        elif ident in driver_slots:
            rows.append(
                _publication_row(
                    item,
                    outcome="published",
                    reason="in_slot",
                    cap=3,
                    slot="top_market_drivers",
                )
            )

    def _emit_digest(item: dict[str, Any]) -> None:
        ident = _publication_identity(item)
        if ident in dated_story_slots:
            rows.append(
                _publication_row(
                    item,
                    outcome="published",
                    reason="in_slot",
                    cap=12,
                    slot="digest_stories",
                )
            )
        elif ident in digest_ids:
            rows.append(
                _publication_row(
                    item,
                    outcome="display_slot_drop",
                    reason="beyond_12",
                    cap=12,
                    slot="digest_stories",
                )
            )
        else:
            rows.append(
                _publication_row(
                    item,
                    outcome="display_slot_drop",
                    reason="outside_7d",
                    cap=12,
                    slot="digest_stories",
                )
            )

    for item in dated_items:
        _emit_last24(item)
        _emit_drivers(item)
        _emit_digest(item)

    if digest and undated_items:
        for item in ranked_undated:
            ident = _publication_identity(item)
            if ident in supplement_slots:
                rows.append(
                    _publication_row(
                        item,
                        outcome="published",
                        reason="in_slot",
                        cap=12,
                        slot="digest_stories",
                    )
                )
            elif len(digest) >= 12:
                rows.append(
                    _publication_row(
                        item,
                        outcome="display_slot_drop",
                        reason="dated_digest_full",
                        cap=12,
                        slot="digest_stories",
                    )
                )
            else:
                rows.append(
                    _publication_row(
                        item,
                        outcome="display_slot_drop",
                        reason="beyond_12",
                        cap=12,
                        slot="digest_stories",
                    )
                )
    elif not digest and undated_items:
        for item in ranked_undated:
            ident = _publication_identity(item)
            if ident in driver_slots:
                rows.append(
                    _publication_row(
                        item,
                        outcome="published",
                        reason="in_slot",
                        cap=3,
                        slot="top_market_drivers",
                    )
                )
            else:
                rows.append(
                    _publication_row(
                        item,
                        outcome="display_slot_drop",
                        reason="beyond_3",
                        cap=3,
                        slot="top_market_drivers",
                    )
                )
            if ident in supplement_slots:
                rows.append(
                    _publication_row(
                        item,
                        outcome="published",
                        reason="in_slot",
                        cap=12,
                        slot="digest_stories",
                    )
                )
            else:
                rows.append(
                    _publication_row(
                        item,
                        outcome="display_slot_drop",
                        reason="beyond_12",
                        cap=12,
                        slot="digest_stories",
                    )
                )

    return rows


def _rollup_mode(dated_items: list[dict[str, Any]], undated_items: list[dict[str, Any]], cutoff: datetime) -> str:
    start = cutoff - timedelta(days=7)
    digest = [row for row in dated_items if start <= row["_published"] <= cutoff]
    if digest:
        return "dated"
    if undated_items:
        return "undated_only"
    return "empty"


def _assert_refresh_output(
    out: str,
    *,
    cutoff: datetime,
    mode: str,
) -> None:
    scan_date = f"{cutoff.day} {cutoff.strftime('%b')} {cutoff.year}"
    if f"Last refreshed {scan_date}" not in out:
        raise ValueError("live Last 24 Hours timestamp missing after refresh")
    driver_count = out.count('class="driver-card"')
    if not 1 <= driver_count <= 3:
        raise ValueError("live Top Market Drivers count invalid")
    story_count = out.count('<details class="story"')
    if not 1 <= story_count <= 12:
        raise ValueError("live digest story count invalid")
    if mode == "undated_only":
        if UNDATED_PROVENANCE_ATTR not in out:
            raise ValueError("undated research provenance marker missing")
        if "Accepted Overnight Research · Age Unverified" not in out:
            raise ValueError("undated research section title missing")
        if '<div class="stitle">7-Day Quick Digest</div>' in out:
            raise ValueError("undated-only refresh must not render a 7-Day Quick Digest")
    elif mode == "dated":
        if '<div class="stitle">7-Day Quick Digest</div>' not in out:
            raise ValueError("dated rolling digest title missing")


def apply_overnight_news_refresh(html: str, dataset: dict[str, Any]) -> str:
    cutoff = _cutoff(dataset)
    audit = audit_agent_research(dataset.get("agent_research"))
    if audit.renderable == 0:
        raise ValueError("accepted overnight research has no renderable items")
    dated_items, undated_items = _partition_items(dataset)
    research = dataset.get("agent_research") or {}
    summary = research.get("summary")

    if LAST24_START not in html or ROLLUP_START not in html or ROLLUP_END not in html:
        raise ValueError("news section anchors changed")
    last_start = html.index(LAST24_START)
    rollup_start = html.index(ROLLUP_START, last_start)
    rollup_end = html.index(ROLLUP_END, rollup_start)

    mode = _rollup_mode(dated_items, undated_items, cutoff)
    if mode == "empty":
        raise ValueError("accepted overnight research has no items in the rolling 7-day window")

    new_last24 = _last24_html(dated_items, cutoff, summary)
    new_rollup = _rollup_html(dated_items, undated_items, cutoff)
    out = html[:last_start] + new_last24 + new_rollup + html[rollup_end:]

    _assert_refresh_output(out, cutoff=cutoff, mode=mode)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("html", nargs="?", type=Path, default=Path("_site/index.html"))
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args(argv)

    dataset = _load_dataset(args.root, args.dataset)
    current = args.html.read_text(encoding="utf-8")
    updated = apply_overnight_news_refresh(current, dataset)
    args.html.write_text(updated, encoding="utf-8")
    cutoff = _cutoff(dataset)
    audit = audit_agent_research(dataset.get("agent_research"))
    print(
        f"Overnight news refreshed from {dataset['overnight_run_id']} "
        f"through {cutoff.isoformat()} "
        f"(dated={audit.dated}, undated={audit.undated})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
