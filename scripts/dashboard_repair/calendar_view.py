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
from scripts.dashboard_repair.score_dates import format_calibration_anchor, format_ingestion_day
from scripts.macro_ingestion.contract import load_catalog
from scripts.macro_ingestion.us_employment.contract import EMPSIT_RELEASE_IDS, JOLTS_RELEASE_IDS

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

_AU_CPI_IDS = frozenset({"AU.Inflation.headline", "AU.Inflation.underlying"})
_NZ_CPI_IDS = frozenset({"NZ.Inflation.headline", "NZ.Inflation.underlying"})
# Membership only. Do not iterate these for display text; set order follows PYTHONHASHSEED.
_JOLTS_CATALOG_IDS = frozenset(JOLTS_RELEASE_IDS)
_EMPSIT_CATALOG_IDS = frozenset(EMPSIT_RELEASE_IDS)
_RELEASE_FAMILY_TITLES = {
    "au_cpi": "Consumer Price Index, Australia (headline and trimmed-mean inflation)",
    "au_labour_force": "Labour Force, Australia",
    "chicago_fed_lmi": "Chicago Fed Labor Market Indicators (unemployment nowcast and flows)",
    "us_empsit": "US Nonfarm Payrolls (NFP) — BLS Employment Situation",
    "us_cpi": "Consumer Price Index",
    "nz_cpi": "Consumers Price Index",
    "ca_lfs": "Labour Force Survey",
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


def _shell_from_slot(slot: dict[str, Any], *, series_id: str, row: dict[str, Any] | None) -> dict[str, Any]:
    """Minimal catalog row so :func:`_stamp_event` can build a release row."""
    country = str(slot.get("country") or (row or {}).get("country") or "")
    return {
        "id": series_id,
        "country": country,
        "dimension": str((row or {}).get("dimension") or ""),
        "component": str((row or {}).get("component") or ""),
        "role": str((row or {}).get("role") or "scored"),
        "weight": float((row or {}).get("weight") or 0),
        "canonical_name": str((row or {}).get("canonical_name") or (row or {}).get("component") or slot.get("name") or "Release"),
        "publisher": str((row or {}).get("publisher") or ""),
        "release_rule": (row or {}).get("release_rule") or {},
        "registry_urls": (row or {}).get("registry_urls") or [],
        "endpoint": (row or {}).get("endpoint") or "",
        "retrieval_method": (row or {}).get("retrieval_method") or "",
        "employment_section": (row or {}).get("employment_section") or "",
    }


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


@lru_cache(maxsize=1)
def _catalog_rows_by_id() -> dict[str, dict[str, Any]]:
    return {str(row.get("id") or ""): row for row in load_catalog()["series"]}


def _registry_blob(row: dict[str, Any]) -> str:
    return " ".join(str(url) for url in row.get("registry_urls") or []).lower()


def _cites_jolts_release(row: dict[str, Any]) -> bool:
    blob = _registry_blob(row)
    return "/jlt/" in blob or "jolts.htm" in blob


def _cites_empsit_release(row: dict[str, Any]) -> bool:
    blob = _registry_blob(row)
    return "/news.release/empsit" in blob or "empsit.htm" in blob


def _is_us_employment_situation(series_id: str, row: dict[str, Any]) -> bool:
    """Primary BLS Employment Situation metrics and context released with that print.

    ``employment_section`` is also set on JOLTS, claims, Chicago Fed, and other labor
    rows, so it is not a family key. JOLTS is identified by catalog id and the jlt registry.
    """
    if series_id in _JOLTS_CATALOG_IDS or _cites_jolts_release(row):
        return False
    method = str(row.get("retrieval_method") or "")
    endpoint = str(row.get("endpoint") or "")
    if method.startswith("bls_empsit"):
        return True
    if method == "derived_employment_context" or "derived://us-employment-context" in endpoint:
        return True
    if method == "bls_public_api_batch" and (
        _cites_empsit_release(row) or series_id in _EMPSIT_CATALOG_IDS
    ):
        return True
    return False


def _release_family_key(series_id: str) -> str:
    if series_id in _AU_CPI_IDS:
        return "au_cpi"
    if series_id in _NZ_CPI_IDS:
        return "nz_cpi"
    if series_id.startswith("AU.Labor."):
        return "au_labour_force"
    row = _catalog_rows_by_id().get(series_id) or {}
    method = str(row.get("retrieval_method") or "")
    if method == "chicago_fed_lmi_json":
        return "chicago_fed_lmi"
    if series_id.startswith("US.Labor.") and _is_us_employment_situation(series_id, row):
        return "us_empsit"
    if series_id.startswith("US.Inflation.cpi"):
        return "us_cpi"
    return series_id


def _event_title(item: dict[str, Any]) -> str:
    names = [str(name) for name in (item.get("names") or [item.get("name")]) if name]
    series_ids = [
        str(series_id)
        for series_id in (item.get("series_ids") or [item.get("series_id")])
        if series_id is not None and str(series_id) != ""
    ]
    if len(names) == 1:
        return names[0]
    families: set[str] = set()
    ef = str(item.get("event_family") or "").strip()
    if ef:
        families.add(ef)
    for series_id in series_ids:
        families.add(_release_family_key(series_id))
    if len(families) == 1:
        family = next(iter(families))
        titled = _RELEASE_FAMILY_TITLES.get(family)
        if titled:
            return titled
    return names[0]


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


def _group_family_key(row: dict[str, Any]) -> str:
    ef = str(row.get("event_family") or "").strip()
    if ef:
        return ef
    return _release_family_key(str(row.get("series_id") or ""))


def _group(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = (
            row["country"],
            row["instant"].isoformat() if row["instant"] is not None else f"tba:{row['local_date']}",
            row["clock"],
            _group_family_key(row),
        )
        current = grouped.get(key)
        if current is None:
            current = dict(row)
            current["impacts"] = [row["impact"]]
            current["names"] = [row["name"]]
            current["series_ids"] = [row["series_id"]]
            current["_seen_series"] = {str(row["series_id"])} if str(row.get("series_id") or "") else set()
            grouped[key] = current
            continue
        if row["impact"] not in current["impacts"]:
            current["impacts"].append(row["impact"])
        if row["name"] not in current["names"]:
            current["names"].append(row["name"])
        sid = str(row.get("series_id") or "")
        seen: set[str] = current.setdefault("_seen_series", set())  # type: ignore[assignment]
        token = sid if sid else "__empty_series__"
        if token not in seen:
            seen.add(token)
            current["series_ids"].append(row["series_id"])
        if row["actual"] != "not observed in the score ledger" and current["actual"] == "not observed in the score ledger":
            current["actual"] = row["actual"]
        if row["source_url"] and not current["source_url"]:
            current["source_url"] = row["source_url"]
        if row["reference_period"] and not current["reference_period"]:
            current["reference_period"] = row["reference_period"]
        if str(row.get("publisher") or "") == "BLS":
            current["publisher"] = "BLS"
    out = list(grouped.values())
    for item in out:
        item.pop("_seen_series", None)
    return out


def _stamp_event(row: dict[str, Any], slot: dict[str, Any], *, clock_now: datetime) -> dict[str, Any]:
    clock = str(slot.get("clock") or "tba")
    if clock in {"verified", "standing"} and slot.get("stamp"):
        instant = _parse_stamp(str(slot["stamp"]), str(slot.get("timezone") or "America/New_York"))
        built = _row_shell(
            row,
            {
                "instant": instant,
                "reference_period": slot.get("reference_period") or "",
                "source_url": slot.get("source_url") or "",
                "provenance": slot.get("provenance") or "",
            },
            clock=clock,
            local_date=instant.date(),
        )
        built["et_date"] = instant.astimezone(ET).date()
        built["local_display"] = instant.strftime("%Y-%m-%d %H:%M %Z")
        built["et_display"] = instant.astimezone(ET).strftime("%Y-%m-%d %H:%M ET")
        if clock == "standing":
            built["local_display"] += " standing clock"
            built["et_display"] += " if the standing clock holds"
        built["name"] = str(slot.get("name") or built["name"])
        built["publisher"] = str(slot.get("publisher") or built["publisher"])
        for key in ("event_family", "event_id", "date_confidence"):
            if slot.get(key) is not None:
                built[key] = slot.get(key)
        return built
    local = date.fromisoformat(str(slot["local_date"]))
    built = _row_shell(row, None, clock="tba", local_date=local)
    built["reference_period"] = str(slot.get("reference_period") or "")
    built["source_url"] = str(slot.get("source_url") or "")
    built["provenance"] = str(slot.get("provenance") or "")
    built["name"] = str(slot.get("name") or built["name"])
    built["publisher"] = str(slot.get("publisher") or built["publisher"])
    built["local_display"] = local.isoformat()
    built["et_display"] = "ET time TBA"
    for key in ("event_family", "event_id", "date_confidence"):
        if slot.get(key) is not None:
            built[key] = slot.get(key)
    built["actual"] = "not observed in the score ledger"
    return built


def _place_event(built: dict[str, Any], *, clock_now: datetime, start: date, end: date, recent_start: date, upcoming: list, recent: list, later_rows: list) -> None:
    instant = built.get("instant")
    if instant is not None:
        et_date = instant.astimezone(ET).date()
        if recent_start <= et_date <= end and instant <= clock_now:
            recent.append(built)
        elif start <= et_date <= end and instant > clock_now:
            upcoming.append(built)
        elif instant > clock_now:
            later_rows.append(built)
        return
    local = built.get("local_date")
    if local is None:
        return
    if recent_start <= local < start:
        recent.append(built)
    elif start <= local <= end:
        upcoming.append(built)
    elif local > end:
        later_rows.append(built)


def _parse_score_day(value: object) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def build_release_model_from_economic_calendar(
    block: dict[str, Any],
    now: datetime,
    *,
    score_as_of: str = "2026-09-21",
    score_inputs_last_ingested_at: str | None = None,
) -> dict[str, Any]:
    from scripts.dashboard_repair.calendar_packet import release_model_from_economic_calendar

    return release_model_from_economic_calendar(
        block,
        now,
        score_as_of=score_as_of,
        score_inputs_last_ingested_at=score_inputs_last_ingested_at,
    )


def build_release_model(
    now: datetime,
    series: list[dict[str, Any]] | None = None,
    score_as_of: str = "2026-09-21",
    score_inputs_last_ingested_at: str | None = None,
    fetched_slots: list[dict[str, Any]] | None = None,
    schedule_fetch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clock = _aware(now)
    start = clock.date()
    end = start + timedelta(days=13)
    recent_start = start - timedelta(days=7)
    calibration_anchor = _parse_score_day(score_as_of) or date.fromisoformat("2026-09-21")
    ingestion_day = _parse_score_day(score_inputs_last_ingested_at) or calibration_anchor
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
            built["event_family"] = _release_family_key(str(row.get("id") or ""))
            if recent_start <= et_date <= end and instant <= clock:
                recent.append(built)
            elif start <= et_date <= end and instant > clock:
                upcoming.append(built)
            elif instant > clock:
                later_rows.append(built)
        fetched_covers_nz_cpi = False
        for _slot in fetched_slots or []:
            for _sid in _slot.get("series_ids") or []:
                if str(_sid) in {"NZ.Inflation.headline", "NZ.Inflation.underlying"}:
                    fetched_covers_nz_cpi = True
                    break
            if fetched_covers_nz_cpi:
                break
        quoted = _nz_quoted_release()
        if (
            quoted
            and str(row.get("id") or "") in {"NZ.Inflation.headline", "NZ.Inflation.underlying"}
            and not fetched_covers_nz_cpi
        ):
            local = date.fromisoformat(quoted["local_date"])
            built = _row_shell(row, None, clock="tba", local_date=local)
            built["reference_period"] = quoted["reference_period"]
            built["source_url"] = quoted["source_url"]
            built["provenance"] = quoted["provenance"]
            built["actual"] = "not observed in the score ledger"
            built["name"] = "Consumers price index"
            built["publisher"] = "Stats NZ"
            built["event_family"] = "nz_cpi"
            built["local_display"] = local.isoformat()
            built["et_display"] = "ET time TBA"
            if recent_start <= local < start:
                recent.append(built)
            elif start <= local <= end:
                upcoming.append(built)
            elif local > end:
                later_rows.append(built)

    seen_dates: set[tuple[str, date | None]] = set()
    for item in upcoming + recent + later_rows:
        seen_dates.add((item["series_id"], item.get("et_date")))
        seen_dates.add((item["series_id"], item.get("local_date")))
    by_id = {str(row.get("id") or ""): row for row in rows}
    for slot in fetched_slots or []:
        raw_ids = [str(s) for s in (slot.get("series_ids") or []) if str(s)]
        catalog_hits = [sid for sid in raw_ids if sid in by_id]
        if catalog_hits:
            emit_ids = catalog_hits
        elif raw_ids:
            emit_ids = [raw_ids[0]]
        else:
            emit_ids = [""]

        for series_id in emit_ids:
            spec = (
                by_id.get(series_id)
                if series_id
                else _shell_from_slot(slot, series_id="", row=None)
            ) or _shell_from_slot(slot, series_id=series_id, row=None)
            built = _stamp_event(spec, slot, clock_now=clock)
            days = [built.get("et_date"), built.get("local_date")]
            dedupe_key = str(built.get("series_id") or "") or str(slot.get("event_id") or slot.get("event_family") or "")
            if dedupe_key and any((dedupe_key, day) in seen_dates for day in days if day is not None):
                continue
            if dedupe_key:
                for day in days:
                    seen_dates.add((dedupe_key, day))
            _place_event(
                built,
                clock_now=clock,
                start=start,
                end=end,
                recent_start=recent_start,
                upcoming=upcoming,
                recent=recent,
                later_rows=later_rows,
            )

    unscheduled = []
    seen_ids: set[str] = set()
    scheduled_ids = set()
    for item in upcoming + recent + later_rows:
        for sid in item.get("series_ids") or [item.get("series_id")]:
            text = str(sid or "")
            if text:
                scheduled_ids.add(text)
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
        clock_day = clock.astimezone(ET).date()
        for item in items:
            when = item["et_date"] or item["local_date"]
            item["after_freeze"] = bool(when and when > calibration_anchor)
            item["after_score_input_ingestion"] = bool(when and ingestion_day and when > ingestion_day)
            if isinstance(when, date) and when > clock_day:
                item["score_release_context"] = "upcoming"
            elif item["after_score_input_ingestion"]:
                item["score_release_context"] = "after_ingestion"
            else:
                item["score_release_context"] = "before_ingestion"
            item["score_inputs_ingestion_day"] = ingestion_day.isoformat()
        return items

    return {
        "window_start": start,
        "window_end": end,
        "recent_start": recent_start,
        "calibration_anchor": score_as_of,
        "score_inputs_last_ingested": score_inputs_last_ingested_at,
        "score_freeze": score_as_of,
        "generated_at": clock.isoformat(),
        "upcoming": _annotate(_group(_sort(upcoming))),
        "recent": _annotate(_group(_sort(recent))),
        "later": _annotate(next_later[:40]),
        "unscheduled_scored": unscheduled,
        "schedule_fetch": schedule_fetch
        or {"attempted": False, "pages": [], "errors": [], "retrieved_at": "", "countries": {}, "cache": []},
    }


def _display_date(value: date | None) -> str:
    if value is None:
        return "date unavailable"
    return f"{value.day} {value.strftime('%b %Y')}"


def _weekday(value: date | None) -> str:
    if value is None:
        return ""
    return value.strftime("%A")


# Fixed order. A set would reshuffle this line across processes (PYTHONHASHSEED)
# and change the research-site digest.
_SCORED_EMPSIT_ORDER = ("US.Labor.payrolls", "US.Labor.unemployment", "US.Labor.wages")


def _is_derived_empsit_series(series_id: str) -> bool:
    row = _catalog_rows_by_id().get(series_id) or {}
    method = str(row.get("retrieval_method") or "")
    endpoint = str(row.get("endpoint") or "")
    return method == "derived_employment_context" or "derived://us-employment-context" in endpoint


def _empsit_face_roles(series_ids: list[str]) -> str:
    by_id = _catalog_rows_by_id()
    parts: list[str] = []
    scored_names = [
        str((by_id.get(series_id) or {}).get("canonical_name") or series_id)
        for series_id in _SCORED_EMPSIT_ORDER
        if series_id in series_ids
    ]
    if scored_names:
        parts.append("Scored: " + ", ".join(scored_names))
    if "US.Labor.participation" in series_ids:
        participation = str((by_id.get("US.Labor.participation") or {}).get("canonical_name") or "Labor force participation rate")
        parts.append(f"Context: {participation}")
    if any(_is_derived_empsit_series(series_id) for series_id in series_ids):
        parts.append("Derived household context")
    return " · ".join(parts)


def _impact_feed(impacts: list[str]) -> tuple[str, str]:
    has_scored = any(text.startswith("Scored input:") for text in impacts)
    has_context = any(
        "Context only" in text or "Bridge input" in text or "zero score weight" in text for text in impacts
    )
    if has_scored and has_context:
        return "Scored and context", "mw-chip--ok"
    for text in impacts:
        if text.startswith("Scored input:"):
            head = text.removeprefix("Scored input:").strip().split("·", 1)[0].strip()
            return f"Feeds score: {head}", "mw-chip--ok"
        if "Context only" in text or "Bridge input" in text or "zero score weight" in text:
            return "Context only", "mw-chip--info"
    return "Context only", "mw-chip--info"


def _row_times(item: dict[str, Any]) -> tuple[str, str]:
    local = str(item.get("local_display") or "")
    et = str(item.get("et_display") or "")
    if item.get("clock") == "standing":
        local = local.replace(" standing clock", "")
        et = et.replace(" if the standing clock holds", "")
    return local, et


def _ledger_status(actual: str) -> str:
    if actual == "not observed in the score ledger":
        return "Actual not yet in score ledger"
    return f"Actual: {actual}"


def _event_html(item: dict[str, Any]) -> str:
    names = item.get("names") or [item.get("name")]
    title = _event_title(item)
    impacts = list(item.get("impacts") or [item.get("impact")])
    feed_label, feed_class = _impact_feed([str(text) for text in impacts if text])
    when = item.get("et_date") or item.get("local_date")
    day_label = _display_date(when if isinstance(when, date) else None)
    weekday = _weekday(when if isinstance(when, date) else None)
    link = ""
    if str(item.get("source_url") or "").startswith("https://"):
        link = f'<a href="{esc(item["source_url"])}" rel="noopener" target="_blank">Official source</a>'
    context = str(item.get("score_release_context") or "")
    ingestion_day = _parse_score_day(item.get("score_inputs_ingestion_day"))
    ingested_label = format_ingestion_day(ingestion_day.isoformat()) if ingestion_day else "unknown date"
    if context == "upcoming":
        freeze_text = "Upcoming; not in the 1–100 levels yet."
    elif context == "after_ingestion":
        freeze_text = (
            f"Released after the latest score-input ingestion ({ingested_label}); "
            "not yet in the 1–100 levels."
        )
    else:
        freeze_text = (
            "Released before the latest score-input ingestion; "
            "see the country's score inputs for whether this period is scored."
        )
    clock_note = ""
    if item.get("clock") == "standing":
        clock_note = "Clock is the standing publisher time, not a time reprinted on the future-date line."
    elif item.get("clock") == "tba":
        clock_note = "Time is TBA. No ET hour is shown."
    impact_lines = "".join(f"<li>{esc(text)}</li>" for text in impacts)
    names_detail = ""
    if len(names) > 1:
        names_detail = "<p><span class=\"mw-label\">Series</span> " + esc("; ".join(names)) + "</p>"
    detail_bits = [
        f"<p>Verification: {esc(item.get('provenance') or 'pinned timestamp')}.</p>",
        names_detail,
        f"<p>Reference period: {esc(item.get('reference_period') or 'not pinned')}. "
        f"Publisher: {esc(item.get('publisher') or 'not recorded')}. {link}</p>",
        f"<ul>{impact_lines}</ul>" if impact_lines else "",
        f"<p>{esc(item.get('actual'))}. Prior: {esc(item.get('prior'))}. No consensus is published here.</p>",
        f"<p>{esc(freeze_text)}</p>",
    ]
    if clock_note:
        detail_bits.insert(1, f"<p>{esc(clock_note)}</p>")
    details = (
        '<details class="mw-release-detail"><summary>Provenance and score context</summary>'
        + "".join(detail_bits)
        + "</details>"
    )
    local_show, et_show = _row_times(item)
    series_ids = [str(series_id) for series_id in (item.get("series_ids") or [item.get("series_id")]) if series_id]
    role_line = ""
    if len(series_ids) > 1 and all(_release_family_key(series_id) == "us_empsit" for series_id in series_ids):
        role_line = _empsit_face_roles(series_ids)
    role_html = f'<span class="mw-asof mw-release-roles">{esc(role_line)}</span>' if role_line else ""
    return (
        '<article class="release-card mw-release-row" data-release-country="' + esc(item.get("country")) + '">'
        f'<div class="mw-release-date"><span class="mw-num mw-release-day">{esc(day_label)}</span>'
        + (f'<span class="mw-asof mw-release-weekday">{esc(weekday)}</span>' if weekday else "")
        + "</div>"
        f'<span class="mw-chip">{esc(item.get("country"))}</span>'
        f'<div class="mw-release-main"><b>{esc(title)}</b>'
        f'<span class="mw-asof">{esc(item.get("publisher") or "Publisher not recorded")}</span>'
        f"{role_html}</div>"
        f'<div class="mw-release-times mw-asof"><span>Local {esc(local_show)}</span>'
        f'<span>ET {esc(et_show)}</span></div>'
        f'<span class="mw-chip {feed_class}">{esc(feed_label)}</span>'
        f'<span class="mw-asof mw-release-status">{esc(_ledger_status(str(item.get("actual") or "")))}</span>'
        f"{details}"
        "</article>"
    )


def _fetch_note(model: dict[str, Any]) -> str:
    report = model.get("schedule_fetch") or {}
    if not report.get("attempted"):
        return (
            "This build did not fetch live official schedule pages. "
            "Dates come from pinned official evidence already in the repository. "
            "The calendar is rebuilt on each Pages publication."
        )
    pages = report.get("pages") or []
    ok = sum(1 for page in pages if page.get("status") == "ok")
    failed = [page for page in pages if page.get("status") != "ok"]
    note = (
        f"Live official schedule fetch at {report.get('retrieved_at') or 'unknown time'}: "
        f"{ok} page(s) read, {len(failed)} failed. Failed pages add no newly parsed dates."
    )
    countries_report = report.get("countries") or {}
    order = ("US", "CA", "EA", "AU", "NZ", "JP")
    country_bits: list[str] = []
    any_retained = False
    for code in order:
        diag = countries_report.get(code)
        if not isinstance(diag, dict):
            continue
        status = str(diag.get("status") or "")
        count = int(diag.get("event_count") or 0)
        if status == "ok":
            country_bits.append(f"{code} ok {count}")
        elif status == "retained":
            any_retained = True
            cf = str(diag.get("cache_fetched_at") or "").replace("T", " ")[:10]
            country_bits.append(f"{code} retained {count} from {cf or 'cache'}")
        elif status == "failed":
            country_bits.append(f"{code} failed")
        elif status == "empty":
            country_bits.append(f"{code} empty")
        else:
            country_bits.append(f"{code} {status or 'unknown'}")
    if country_bits:
        note += " " + " · ".join(country_bits) + "."
    if any_retained:
        note += " Some countries retained schedule dates from the committed cache after a failed or empty live fetch."
    gap_bits: list[str] = []
    for code in order:
        diag = countries_report.get(code)
        if not isinstance(diag, dict):
            continue
        gaps = [str(item).strip() for item in (diag.get("gaps") or []) if str(item).strip()]
        if gaps:
            gap_bits.append(f"{code}: {gaps[0]}")
    if gap_bits:
        note += " Gaps: " + "; ".join(gap_bits[:6]) + "."
    if failed:
        note += " Failures: " + "; ".join(
            f"{page.get('url')} ({page.get('error') or 'failed'})" for page in failed[:4]
        )
    return note


def _day_key(item: dict[str, Any]) -> tuple[str, str]:
    when = item.get("et_date") or item.get("local_date")
    if isinstance(when, date):
        heading = f"{_display_date(when)} · {_weekday(when)}"
        if item.get("clock") == "tba":
            heading += " · ET time TBA"
        return heading, heading
    if item.get("clock") == "tba":
        local = item.get("local_date")
        label = f"{_display_date(local if isinstance(local, date) else None)} · ET time TBA"
        return label, label
    return "date unavailable", "date unavailable"


def render_releases(model: dict[str, Any]) -> str:
    def day_groups(items: list[dict[str, Any]]) -> str:
        if not items:
            return '<p class="note">None with a verified timestamp in this window.</p>'
        chunks = []
        current = None
        bucket: list[str] = []
        for item in items:
            _, label = _day_key(item)
            if label != current:
                if bucket:
                    chunks.append(
                        f'<section class="release-day"><h3 class="mw-release-dayhead">{esc(current)}</h3>'
                        f'<div class="mw-release-list">{"".join(bucket)}</div></section>'
                    )
                current = label
                bucket = []
            bucket.append(_event_html(item))
        if bucket:
            chunks.append(
                f'<section class="release-day"><h3 class="mw-release-dayhead">{esc(current)}</h3>'
                f'<div class="mw-release-list">{"".join(bucket)}</div></section>'
            )
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
    anchor_label = format_calibration_anchor(model.get("calibration_anchor") or model.get("score_freeze"))
    ingested_label = format_ingestion_day(model.get("score_inputs_last_ingested") or "")
    window_line = (
        f"Window {_display_date(model['window_start'])} through {_display_date(model['window_end'])} "
        f"(America/New_York). Calibration anchor {esc(anchor_label)}. "
        f"Score inputs last ingested {esc(ingested_label)}."
    )
    window_detail = (
        "<p>Cadence is not a date. A missing official timestamp stays TBA / date unavailable. "
        "Actual values appear only when the score ledger holds that reference period.</p>"
        f"<p>{esc(_fetch_note(model))}</p>"
    )
    return (
        '<section class="page releases" data-release-calendar="repair">'
        '<div class="stitle">Releases · next 14 days</div>'
        f'<p class="note mw-release-intro">{esc(window_line)} '
        '<details class="mw-release-window"><summary>Window, score inputs and schedule fetch</summary>'
        f"{window_detail}</details></p>"
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
