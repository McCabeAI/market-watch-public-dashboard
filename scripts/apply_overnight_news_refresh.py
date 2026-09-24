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

NY = ZoneInfo("America/New_York")
LAST24_START = '<div class="last24">'
ROLLUP_START = '<div class="stitle">Top Market Drivers</div>'
ROLLUP_END = '<div class="x-signal">'


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


def _clean_items(dataset: dict[str, Any]) -> list[dict[str, Any]]:
    research = dataset.get("agent_research") or {}
    combined: list[dict[str, Any]] = []
    for family, items in (
        ("news", research.get("news") or []),
        ("central_bank_research", research.get("central_bank_research") or []),
    ):
        for raw in items:
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("headline") or "").strip()
            url = str(raw.get("url") or "").strip()
            summary = str(raw.get("summary") or "").strip()
            published = _parse_iso(raw.get("published_at"))
            if not title or not url or not summary or published is None:
                continue
            item = dict(raw)
            item["_family"] = family
            item["_published"] = published
            combined.append(item)

    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for item in sorted(combined, key=lambda row: row["_published"], reverse=True):
        key = (str(item.get("url")), str(item.get("headline")))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _impact(item: dict[str, Any]) -> tuple[str, str]:
    category = str(item.get("primary_category") or "").lower()
    family = item.get("_family")
    blob = " ".join(
        str(item.get(k) or "").lower()
        for k in ("headline", "summary", "institution", "source_name")
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


def _last24_html(items: list[dict[str, Any]], cutoff: datetime, summary: str | None) -> str:
    start = cutoff - timedelta(hours=24)
    current = [row for row in items if start <= row["_published"] <= cutoff][:6]
    headline = current[0]["headline"] if current else "No new qualifying market driver in the last 24 hours"
    desk_read = public_research_summary(summary)
    cards: list[str] = []
    for row in current:
        impact, _ = _impact(row)
        stamp = row["_published"]
        cards.append(
            f'''    <a class="last24-item" href="{_esc(row["url"])}" target="_blank" rel="noopener">
      <div class="meta">{_esc(_market_label(row))} · {impact}/10 · {_esc(_source_label(row).upper())} {_esc(_day_label(stamp).upper())}</div>
      <b>{_esc(row["headline"])}</b>
      <span>{_esc(row["summary"])}</span>
    </a>'''
        )
    if not cards:
        cards.append(
            '    <div class="last24-empty">No accepted overnight research item was published inside the exact rolling 24-hour window.</div>'
        )
    plural = "s" if len(current) != 1 else ""
    return (
        '<div class="last24">\n'
        '  <div class="last24-head">\n'
        '    <div>\n'
        '      <div class="stitle">Last 24 Hours · Desk Summary</div>\n'
        f'      <h2>{_esc(headline)}</h2>\n'
        f'      <p>{len(current)} accepted market-relevant development{plural} in the exact rolling window.</p>\n'
        '    </div>\n'
        f'    <div class="last24-window"><b>Window</b>{_esc(_window_label(start, cutoff))}<br>'
        f'Last refreshed {cutoff.day} {cutoff.strftime("%b")} {cutoff.year} · {cutoff.strftime("%H:%M")} ET</div>\n'
        '  </div>\n'
        f'  <div class="last24-thesis"><b>Desk read:</b> {_esc(desk_read)}</div>\n'
        '  <div class="last24-grid">\n'
        + "\n".join(cards)
        + '\n  </div>\n</div>\n\n'
    )


def _rollup_html(items: list[dict[str, Any]], cutoff: datetime) -> str:
    start = cutoff - timedelta(days=7)
    digest = [row for row in items if start <= row["_published"] <= cutoff]
    if not digest:
        raise ValueError("accepted overnight research has no items in the rolling 7-day window")

    ranked = sorted(
        digest,
        key=lambda row: (_impact(row)[0] == "HIGH", row["_published"]),
        reverse=True,
    )
    drivers = ranked[:3]
    driver_html: list[str] = []
    for row in drivers:
        impact, css = _impact(row)
        driver_html.append(
            f'<a class="driver-card" href="{_esc(row["url"])}" rel="noopener" target="_blank">'
            f'<div class="dmeta"><span class="impact {css}">{impact}</span>{_esc(_market_label(row))}</div>'
            f'<b>{_esc(row["headline"])}</b><span>{_esc(row["summary"])}</span></a>'
        )

    stories: list[str] = []
    for row in digest[:12]:
        impact, css = _impact(row)
        stamp = row["_published"]
        kicker = f'{_market_label(row)} · {_day_label(stamp)} · {_source_label(row)}'
        stories.append(
            '<details class="story"><summary>'
            f'<span class="impact {css}">{impact}</span><span>'
            f'<span class="story-title">{_esc(row["headline"])}</span>'
            f'<span class="story-kicker">{_esc(kicker)}</span></span></summary>'
            f'<div class="story-body"><p><b>What happened:</b> {_esc(row["summary"])}</p>'
            f'<a class="story-source" href="{_esc(row["url"])}" rel="noopener" target="_blank">Open source ↗</a>'
            '</div></details>'
        )

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


def apply_overnight_news_refresh(html: str, dataset: dict[str, Any]) -> str:
    cutoff = _cutoff(dataset)
    items = _clean_items(dataset)
    research = dataset.get("agent_research") or {}
    summary = research.get("summary")

    if LAST24_START not in html or ROLLUP_START not in html or ROLLUP_END not in html:
        raise ValueError("news section anchors changed")
    last_start = html.index(LAST24_START)
    rollup_start = html.index(ROLLUP_START, last_start)
    rollup_end = html.index(ROLLUP_END, rollup_start)

    new_last24 = _last24_html(items, cutoff, summary)
    new_rollup = _rollup_html(items, cutoff)
    out = html[:last_start] + new_last24 + new_rollup + html[rollup_end:]

    scan_date = f"{cutoff.day} {cutoff.strftime('%b')} {cutoff.year}"
    if f"Last refreshed {scan_date}" not in out:
        raise ValueError("live Last 24 Hours timestamp missing after refresh")
    if out.count('class="driver-card"') < 1 or out.count('class="driver-card"') > 3:
        raise ValueError("live Top Market Drivers count invalid")
    if not 1 <= out.count('class="story"') <= 12:
        raise ValueError("live 7-Day Quick Digest count invalid")
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
    print(
        f"Overnight news refreshed from {dataset['overnight_run_id']} "
        f"through {cutoff.isoformat()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
