"""Forward release calendar from pinned official timestamps only.

Cadence does not create a date. A row is dated only when a fragment note cites
an official parse, a schedule fixture contains that timestamp, the curated ABS
CPI table has a non-inferred entry, or the Stats NZ fixture quotes the day.
Clocks that are not on the cited line stay TBA or are labeled standing clocks.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scripts.au_cpi_release.calendar import (
    PROVENANCE_CLOCK,
    PROVENANCE_FUTURE,
    PROVENANCE_WAYBACK,
    _EXPLICIT,
)
from scripts.dashboard_repair.htmlutil import esc
from scripts.macro_ingestion.contract import load_catalog

ROOT = Path(__file__).resolve().parents[2]
ET = ZoneInfo("America/New_York")
_OFFICIAL_NOTE = re.compile(r"parsed from|as published|verified \d{4}-\d{2}-\d{2}", re.IGNORECASE)
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


def _aware(now: datetime) -> datetime:
    if now.tzinfo is None:
        return now.replace(tzinfo=ET)
    return now.astimezone(ET)


def _parse_stamp(raw: str, timezone_name: str) -> datetime:
    text = str(raw).strip()
    if text.endswith("Z"):
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    if len(text) > 19 and (text[10:].find("+") >= 0 or text[10:].find("-") >= 0):
        return datetime.fromisoformat(text)
    return datetime.fromisoformat(text).replace(tzinfo=ZoneInfo(timezone_name or "UTC"))


def _https(value: object) -> str:
    text = str(value or "")
    return text if text.startswith("https://") else ""


def _impact(row: dict[str, Any]) -> str:
    country = str(row.get("country") or "")
    dimension = str(row.get("dimension") or "")
    component = str(row.get("component") or "")
    series_id = str(row.get("id") or "")
    try:
        weight = float(row.get("weight") or 0)
    except (TypeError, ValueError):
        weight = 0.0
    cpi_ppi = component in {"mapped_bridge", "cpi_headline", "cpi", "ppi"} or any(
        token in series_id.lower() for token in (".cpi", ".ppi", "cpi_", "ppi_")
    )
    if country == "US" and cpi_ppi and weight == 0:
        return (
            "Bridge input only when mapped to Core PCE components; not a standalone US score. "
            "Context only / zero score weight."
        )
    role = str(row.get("role") or "")
    if weight == 0 or role in {"context", "registry_unweighted"}:
        return f"Context only / zero score weight. Does not by itself move the {country} {dimension} level."
    return f"Scored input: {country} {dimension} · {component} · weight {weight:g}."


def _fixture_text(source: str) -> str:
    if not source or source.startswith("http") or " " in source:
        return ""
    path = ROOT / source
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _clock_for_rule(raw: str, rule: dict[str, Any]) -> str:
    note = str(rule.get("note") or "")
    if _OFFICIAL_NOTE.search(note):
        return "verified"
    fixture = _fixture_text(str(rule.get("schedule_source") or ""))
    if fixture and raw in fixture:
        return "verified"
    return ""


def _au_clock(entry_provenance: tuple[str, ...]) -> str:
    if PROVENANCE_WAYBACK in entry_provenance and PROVENANCE_CLOCK not in entry_provenance:
        return "verified"
    if PROVENANCE_FUTURE in entry_provenance or PROVENANCE_CLOCK in entry_provenance:
        return "standing"
    if PROVENANCE_WAYBACK in entry_provenance:
        return "verified"
    return "standing"


def _source_for(row: dict[str, Any], rule: dict[str, Any]) -> str:
    for candidate in row.get("registry_urls") or []:
        if _https(candidate):
            return str(candidate)
    fixture = _fixture_text(str(rule.get("schedule_source") or ""))
    match = re.search(r"https://\S+", fixture)
    if match:
        return match.group(0).rstrip(").,")
    return _https(row.get("endpoint"))


def _period(rule: dict[str, Any], raw: str) -> str:
    expected = rule.get("expected_periods") or {}
    if isinstance(expected, dict) and expected.get(raw):
        return str(expected[raw])
    return ""


def _ledger_actual(row: dict[str, Any], period: str) -> str:
    latest = str(row.get("latest_period") or "")
    if not period or latest != period or row.get("latest_value_held") is None:
        return "not observed in the score ledger"
    return (
        f"ledger value {row.get('latest_value_held')} for reference {latest}, "
        f"retrieved {row.get('latest_retrieved_at') or 'retrieval time not recorded'}"
    )


@lru_cache(maxsize=1)
def _nz_quoted_release() -> dict[str, str] | None:
    path = ROOT / "tests/macro_ingestion/fixtures/nz/stats_nz_schedule_excerpt.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    for excerpt in payload.get("excerpts") or []:
        text = str(excerpt.get("content_html") or "")
        text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
        match = re.search(
            r"([A-Za-z]+ \d{4} quarter).*?released on (\d{1,2}) ([A-Za-z]+) (\d{4})",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            continue
        month = _MONTHS.get(match.group(3).lower())
        if month is None:
            continue
        return {
            "reference_period": match.group(1),
            "local_date": date(int(match.group(4)), month, int(match.group(2))).isoformat(),
            "source_url": _https(excerpt.get("source_url")),
            "provenance": "Stats NZ next-release sentence in the pinned schedule fixture. The sentence has a date and no clock.",
        }
    return None


def _candidate_slots(row: dict[str, Any]) -> list[dict[str, Any]]:
    rule = row.get("release_rule") if isinstance(row.get("release_rule"), dict) else {}
    timezone_name = str(rule.get("timezone") or row.get("timezone") or "UTC")
    slots: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rule.get("dates") or []:
        raw_text = str(raw)
        clock = _clock_for_rule(raw_text, rule)
        note = str(rule.get("note") or "").strip()
        provenance = note or "Pinned from the captured official schedule. Cadence was not used."
        if not clock:
            explicit = _EXPLICIT.get(_period(rule, raw_text)) if str(row.get("id") or "").startswith("AU.Inflation.") else None
            if explicit is not None and explicit.release_at.startswith(raw_text[:19]):
                clock = _au_clock(explicit.provenance)
                provenance = explicit.note
            else:
                continue
        elif str(row.get("id") or "").startswith("AU.Inflation."):
            explicit = _EXPLICIT.get(_period(rule, raw_text))
            if explicit is not None and explicit.release_at.startswith(raw_text[:19]) and not note:
                provenance = explicit.note
        instant = _parse_stamp(raw_text, timezone_name)
        key = instant.isoformat()
        if key in seen:
            continue
        seen.add(key)
        slots.append(
            {
                "instant": instant,
                "clock": clock,
                "reference_period": _period(rule, raw_text),
                "provenance": provenance,
                "source_url": _source_for(row, rule),
            }
        )
    if str(row.get("id") or "") in {"AU.Inflation.headline", "AU.Inflation.underlying"}:
        for entry in _EXPLICIT.values():
            instant = _parse_stamp(entry.release_at, "Australia/Sydney")
            key = instant.isoformat()
            if key in seen:
                continue
            if "rule_inferred" in entry.provenance or "backcast" in entry.provenance:
                continue
            seen.add(key)
            slots.append(
                {
                    "instant": instant,
                    "clock": _au_clock(entry.provenance),
                    "reference_period": entry.reference_period,
                    "provenance": entry.note,
                    "source_url": _https(entry.source) or _source_for(row, rule),
                }
            )
    return slots


def _row_shell(row: dict[str, Any], slot: dict[str, Any] | None, *, clock: str, local_date: date | None) -> dict[str, Any]:
    instant = None if slot is None else slot["instant"]
    if instant is not None:
        local_date = instant.date()
        local_display = instant.strftime("%Y-%m-%d %H:%M %Z")
        et = instant.astimezone(ET)
        et_display = et.strftime("%Y-%m-%d %H:%M ET")
        et_date = et.date()
    else:
        et = None
        et_date = None
        local_display = local_date.isoformat() if local_date else "date unavailable"
        et_display = "ET time TBA"
    return {
        "country": str(row.get("country") or ""),
        "series_id": str(row.get("id") or ""),
        "name": str(row.get("canonical_name") or row.get("component") or row.get("id") or "Release"),
        "publisher": str(row.get("publisher") or ""),
        "instant": instant,
        "et_date": et_date,
        "local_date": local_date,
        "clock": clock,
        "local_display": local_display,
        "et_display": et_display,
        "reference_period": "" if slot is None else str(slot.get("reference_period") or ""),
        "impact": _impact(row),
        "source_url": "" if slot is None else str(slot.get("source_url") or ""),
        "provenance": "" if slot is None else str(slot.get("provenance") or ""),
        "actual": "not observed in the score ledger" if slot is None else _ledger_actual(row, str(slot.get("reference_period") or "")),
        "prior": "not in this read-model",
        "weight": float(row.get("weight") or 0),
    }


def _group(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = (
            row["country"],
            row["publisher"],
            row["instant"].isoformat() if row["instant"] is not None else f"tba:{row['local_date']}",
            row["clock"],
        )
        current = grouped.get(key)
        if current is None:
            current = dict(row)
            current["impacts"] = [row["impact"]]
            current["names"] = [row["name"]]
            current["series_ids"] = [row["series_id"]]
            grouped[key] = current
            continue
        if row["impact"] not in current["impacts"]:
            current["impacts"].append(row["impact"])
        if row["name"] not in current["names"]:
            current["names"].append(row["name"])
        current["series_ids"].append(row["series_id"])
        if row["actual"] != "not observed in the score ledger" and current["actual"] == "not observed in the score ledger":
            current["actual"] = row["actual"]
        if row["source_url"] and not current["source_url"]:
            current["source_url"] = row["source_url"]
        if row["reference_period"] and not current["reference_period"]:
            current["reference_period"] = row["reference_period"]
    return list(grouped.values())


def build_release_model(now: datetime, series: list[dict[str, Any]] | None = None, score_as_of: str = "2026-09-21") -> dict[str, Any]:
    clock = _aware(now)
    start = clock.date()
    end = start + timedelta(days=13)
    recent_start = start - timedelta(days=7)
    freeze = date.fromisoformat(score_as_of)
    rows = series if series is not None else load_catalog()["series"]
    upcoming: list[dict[str, Any]] = []
    recent: list[dict[str, Any]] = []
    later_rows: list[dict[str, Any]] = []

    for row in rows:
        for slot in _candidate_slots(row):
            instant = slot["instant"]
            et_date = instant.astimezone(ET).date()
            built = _row_shell(row, slot, clock=slot["clock"], local_date=instant.astimezone(ET).date())
            built["et_date"] = et_date
            built["local_display"] = instant.strftime("%Y-%m-%d %H:%M %Z")
            built["et_display"] = instant.astimezone(ET).strftime("%Y-%m-%d %H:%M ET")
            if slot["clock"] == "standing":
                built["et_display"] += " if the standing clock holds"
                built["local_display"] += " standing clock"
            if recent_start <= et_date <= end and instant <= clock:
                recent.append(built)
            elif start <= et_date <= end and instant > clock:
                upcoming.append(built)
            elif instant > clock:
                later_rows.append(built)
        quoted = _nz_quoted_release()
        if quoted and str(row.get("id") or "") in {"NZ.Inflation.headline", "NZ.Inflation.underlying"}:
            local = date.fromisoformat(quoted["local_date"])
            built = _row_shell(row, None, clock="tba", local_date=local)
            built["reference_period"] = quoted["reference_period"]
            built["source_url"] = quoted["source_url"]
            built["provenance"] = quoted["provenance"]
            built["actual"] = "not observed in the score ledger"
            built["name"] = "Consumers price index"
            built["publisher"] = "Stats NZ"
            if recent_start <= local < start:
                recent.append(built)
            elif start <= local <= end:
                upcoming.append(built)
            elif local > end:
                later_rows.append(built)

    unscheduled = []
    seen_ids: set[str] = set()
    scheduled_ids = {item["series_id"] for item in upcoming + later_rows}
    for row in rows:
        series_id = str(row.get("id") or "")
        try:
            weight = float(row.get("weight") or 0)
        except (TypeError, ValueError):
            weight = 0.0
        if weight <= 0 or series_id in scheduled_ids or series_id in seen_ids:
            continue
        seen_ids.add(series_id)
        unscheduled.append(
            {
                "country": str(row.get("country") or ""),
                "series_id": series_id,
                "name": str(row.get("canonical_name") or row.get("component") or series_id),
                "dimension": str(row.get("dimension") or ""),
                "component": str(row.get("component") or ""),
                "impact": _impact(row),
                "cadence": str(row.get("cadence") or ""),
                "reason": "date unavailable",
            }
        )

    def _sort(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(items, key=lambda item: (item["et_date"] or item["local_date"] or date.max, item["country"], item["name"]))

    later_grouped = _group(later_rows)
    next_later: list[dict[str, Any]] = []
    seen_later: set[str] = set()
    for item in sorted(later_grouped, key=lambda item: item["instant"] or datetime.max.replace(tzinfo=ET)):
        for series_id in item["series_ids"]:
            if series_id in seen_later:
                continue
            seen_later.add(series_id)
            if item not in next_later:
                next_later.append(item)

    def _annotate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for item in items:
            when = item["et_date"] or item["local_date"]
            item["after_freeze"] = bool(when and when > freeze)
        return items

    return {
        "window_start": start,
        "window_end": end,
        "recent_start": recent_start,
        "score_freeze": score_as_of,
        "generated_at": clock.isoformat(),
        "upcoming": _annotate(_group(_sort(upcoming))),
        "recent": _annotate(_group(_sort(recent))),
        "later": _annotate(next_later[:40]),
        "unscheduled_scored": unscheduled,
    }


def _event_html(item: dict[str, Any]) -> str:
    names = item.get("names") or [item.get("name")]
    if len(names) == 1:
        title = names[0]
        name_block = ""
    else:
        title = f"{item.get('publisher') or 'Release'} · {len(names)} series"
        name_block = "<details><summary>Series names</summary><p>" + esc("; ".join(names)) + "</p></details>"
    impacts = "".join(f"<li>{esc(text)}</li>" for text in item.get("impacts") or [item.get("impact")])
    link = ""
    if str(item.get("source_url") or "").startswith("https://"):
        link = f'<a href="{esc(item["source_url"])}" rel="noopener" target="_blank">Official source</a>'
    freeze_text = (
        "After the published score freeze, so this release is not in the 1–100 levels on this page."
        if item.get("after_freeze")
        else "At or before the published score freeze."
    )
    clock_note = ""
    if item.get("clock") == "standing":
        clock_note = " Clock is the standing publisher time, not a time reprinted on the future-date line."
    elif item.get("clock") == "tba":
        clock_note = " Time is TBA. No ET hour is shown."
    return (
        '<article class="release-card" data-release-country="' + esc(item.get("country")) + '">'
        f'<header><b>{esc(item.get("country"))}</b> · {esc(title)}</header>'
        f"{name_block}"
        f'<p>ET: {esc(item.get("et_display"))}. Local: {esc(item.get("local_display"))}.{esc(clock_note)}</p>'
        f'<p>Reference period: {esc(item.get("reference_period") or "not pinned")}. '
        f'Publisher: {esc(item.get("publisher") or "not recorded")}. {link}</p>'
        f'<p>Verification: {esc(item.get("provenance") or "pinned timestamp")}.</p>'
        f"<ul>{impacts}</ul>"
        f'<p>Actual: {esc(item.get("actual"))}. Prior: {esc(item.get("prior"))}. No consensus is published here.</p>'
        f"<p>{esc(freeze_text)}</p>"
        "</article>"
    )


def render_releases(model: dict[str, Any]) -> str:
    def day_groups(items: list[dict[str, Any]]) -> str:
        if not items:
            return '<p class="note">None with a verified timestamp in this window.</p>'
        chunks = []
        current = None
        bucket: list[str] = []
        for item in items:
            label = str(item.get("et_date") or item.get("local_date") or "undated")
            if item.get("clock") == "tba":
                label = f"{item.get('local_date')} local date, ET time TBA"
            if label != current:
                if bucket:
                    chunks.append(f'<section class="release-day"><h3>{esc(current)}</h3>{"".join(bucket)}</section>')
                current = label
                bucket = []
            bucket.append(_event_html(item))
        if bucket:
            chunks.append(f'<section class="release-day"><h3>{esc(current)}</h3>{"".join(bucket)}</section>')
        return "".join(chunks)

    by_country: dict[str, list[dict[str, Any]]] = {}
    for row in model["unscheduled_scored"]:
        by_country.setdefault(str(row["country"]), []).append(row)
    tba_blocks = []
    for country, rows in by_country.items():
        lines = "".join(
            f'<li data-unscheduled="{esc(row["series_id"])}">{esc(row["name"])} · {esc(row["dimension"])} · {esc(row["impact"])} · date unavailable</li>'
            for row in rows
        )
        tba_blocks.append(f"<details><summary>{esc(country)} · {len(rows)} scored series with no verified future date</summary><ul>{lines}</ul></details>")
    later = day_groups(model["later"]) if model["later"] else '<p class="note">No later verified timestamp is pinned.</p>'
    return (
        '<section class="page releases" data-release-calendar="repair">'
        '<div class="stitle">Releases · next 14 days</div>'
        f'<p class="note">Window {esc(model["window_start"])} through {esc(model["window_end"])} '
        f'(America/New_York dates, 14 calendar days). Score freeze {esc(model["score_freeze"])}. '
        "Only pinned official timestamps are dated. Cadence is not a date. Unknown dates stay unavailable. "
        "Prior, consensus, and surprise are omitted unless the score ledger holds the reference period.</p>"
        '<h2>Upcoming</h2>'
        + (day_groups(model["upcoming"]) if model["upcoming"] else '<p class="note" data-empty-upcoming="1">No verified release with a confirmed clock falls in the next 14 days.</p>')
        + "<h2>Just released</h2>"
        + day_groups(model["recent"])
        + '<h2>Later verified dates</h2><p class="note">Outside this 14-day window. Still not estimated from cadence.</p>'
        + later
        + "<h2>Scored series with no verified future date</h2>"
        + ("".join(tba_blocks) if tba_blocks else '<p class="note">Every scored series has a verified future timestamp.</p>')
        + "</section>"
    )
