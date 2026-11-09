"""Pre-freeze economic release and policy calendar assembly (no vendor scrapes)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scripts.dashboard_repair.release_contract import (
    COUNTRIES,
    EconomicReleaseEvent,
    event_to_slot,
    validate_event,
)
from scripts.dashboard_repair.release_pipeline import (
    _event_from_cache_dict,
    fetch_official_schedules,
)
from scripts.overnight.store import sha256_json
from scripts.policy_calendar import BANK_CODES, BANK_META, SOURCE_URLS, load_calendar

ET = ZoneInfo("America/New_York")

_WINDOW_DAYS = 30
_POLICY_DECISION_COUNT = 5

# Official near-term prints the block must retain when the committed cache lists them in-window.
_NEAR_TERM_OFFICIAL_FAMILIES: tuple[tuple[str, str], ...] = (
    ("US", "us_empsit"),
    ("US", "us_cpi"),
    ("CA", "ca_lfs"),
    ("CA", "ca_cpi"),
    ("AU", "au_labour_force"),
    ("AU", "au_cpi"),
    ("EA", "ea_hicp"),
    ("JP", "jp_cpi"),
)


def _root_path(root: Path | None) -> Path:
    if root is not None:
        return Path(root)
    return Path(__file__).resolve().parents[2]


def _aware_as_of(as_of: datetime) -> datetime:
    if as_of.tzinfo is None:
        return as_of.replace(tzinfo=ET)
    return as_of.astimezone(ET)


def _parse_utc_stamp(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _slot_local_instant(slot: dict[str, Any]) -> datetime | None:
    clock = str(slot.get("clock") or "")
    stamp = str(slot.get("stamp") or "").strip()
    if clock in {"verified", "standing"} and stamp:
        tz_name = str(slot.get("timezone") or "UTC")
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            return None
        try:
            naive = datetime.fromisoformat(stamp)
        except ValueError:
            return None
        return naive.replace(tzinfo=tz)
    return None


def _offline_getter(url: str, timeout: float) -> str:
    raise RuntimeError(f"network disabled (attempted {url})")


def _load_schedule_slots(
    as_of: datetime,
    *,
    root: Path,
    allow_network: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cache_path = root / "data" / "dashboard_repair" / "official_release_cache.json"
    getter = None if allow_network else _offline_getter
    fetched = fetch_official_schedules(
        as_of,
        getter=getter,
        cache_path=cache_path,
        write_cache=False,
    )
    return list(fetched.get("slots") or []), fetched


def _slot_to_event(slot: dict[str, Any]) -> dict[str, Any]:
    ld = date.fromisoformat(str(slot["local_date"])[:10])
    lt = slot.get("printed_clock") or slot.get("local_time")
    if lt is not None and str(lt) == "":
        lt = None
    if isinstance(lt, str) and lt:
        local_time = lt if ":" in lt else None
    else:
        local_time = None
    ev = EconomicReleaseEvent(
        event_family=str(slot.get("event_family") or ""),
        country=str(slot.get("country") or ""),
        title=str(slot.get("name") or ""),
        publisher=str(slot.get("publisher") or ""),
        local_date=ld,
        local_time=local_time if slot.get("clock") != "tba" else None,
        timezone=str(slot.get("timezone") or "UTC"),
        reference_period=str(slot.get("reference_period") or ""),
        source_url=str(slot.get("source_url") or ""),
        fetched_at=str(slot.get("fetched_at") or ""),
        status=str(slot.get("clock") or "tba"),
        series_ids=tuple(str(s) for s in (slot.get("series_ids") or [])),
        provenance=str(slot.get("provenance") or "official schedule slot"),
        date_confidence=str(slot.get("date_confidence") or "confirmed"),
    )
    validate_event(ev)
    merged = event_to_slot(ev)
    return {
        "event_id": merged.get("event_id"),
        "event_family": merged.get("event_family"),
        "country": merged.get("country"),
        "title": merged.get("name"),
        "locale": merged.get("country"),
        "series_ids": sorted(str(s) for s in (merged.get("series_ids") or [])),
        "local_date": merged.get("local_date"),
        "time": merged.get("printed_clock") or "",
        "timezone": merged.get("timezone"),
        "clock": merged.get("clock"),
        "source_url": merged.get("source_url"),
        "retrieved_at": merged.get("fetched_at"),
        "release_validity": merged.get("date_confidence"),
        "reference_period": merged.get("reference_period"),
        "publisher": merged.get("publisher"),
        "provenance": merged.get("provenance"),
    }


def _merge_event_group(slots: list[dict[str, Any]]) -> dict[str, Any]:
    if len(slots) == 1:
        return _slot_to_event(slots[0])
    base = _slot_to_event(slots[0])
    series: set[str] = set(base.get("series_ids") or [])
    for slot in slots[1:]:
        for sid in slot.get("series_ids") or []:
            text = str(sid)
            if text:
                series.add(text)
    base["series_ids"] = sorted(series)
    return base


def _group_slots(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for slot in slots:
        key = str(
            slot.get("event_id")
            or f"{slot.get('country')}:{slot.get('event_family')}:{slot.get('local_date')}:{slot.get('clock')}:{slot.get('stamp')}"
        )
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(slot)
    return [_merge_event_group(buckets[k]) for k in order]


def _policy_decision_instant(
    decision: dict[str, Any],
    *,
    timezone_name: str,
) -> datetime:
    decision_date = date.fromisoformat(str(decision["decision_date"]))
    local_time = decision.get("local_time")
    tz = ZoneInfo(timezone_name)
    if local_time:
        hour, minute = map(int, str(local_time).split(":", 1))
        return datetime(decision_date.year, decision_date.month, decision_date.day, hour, minute, tzinfo=tz)
    return datetime(decision_date.year, decision_date.month, decision_date.day, 0, 0, tzinfo=tz)


def _build_policy_block(
    as_of: datetime,
    *,
    root: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    calendar = load_calendar(root)
    gaps: list[dict[str, Any]] = []
    banks_out: dict[str, Any] = {}

    if not calendar:
        for bank in BANK_CODES:
            gaps.append(
                {
                    "kind": "policy_calendar",
                    "country": bank,
                    "reason": "policy_meetings.json missing or invalid",
                }
            )
            banks_out[bank] = {"decisions": [], "count": 0}
        return banks_out, gaps

    for bank in BANK_CODES:
        block = (calendar.get("banks") or {}).get(bank) or {}
        status = str(block.get("status") or "unavailable")
        retrieved_at = block.get("retrieved_at")
        source_url = str(block.get("source_url") or SOURCE_URLS.get(bank) or "")
        tz_name = str(block.get("timezone") or BANK_META[bank]["timezone"])

        if status != "verified":
            gaps.append(
                {
                    "kind": "policy_calendar",
                    "country": bank,
                    "reason": f"policy calendar status={status!r}",
                    "source_url": source_url,
                }
            )
            banks_out[bank] = {
                "timezone": tz_name,
                "source_url": source_url,
                "retrieved_at": retrieved_at,
                "clock": "verified" if block.get("local_time") or BANK_META[bank].get("local_time") else "tba",
                "decisions": [],
                "count": 0,
            }
            continue

        as_of_local = as_of.astimezone(ZoneInfo(tz_name))
        upcoming: list[dict[str, Any]] = []
        for row in block.get("decisions") or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("state") or "") != "upcoming":
                continue
            instant = _policy_decision_instant(row, timezone_name=tz_name)
            if instant <= as_of_local:
                continue
            clock = "tba" if row.get("local_time") is None else "verified"
            upcoming.append(
                {
                    "decision_date": str(row.get("decision_date")),
                    "meeting_start": row.get("meeting_start"),
                    "effective_date": str(row.get("effective_date") or ""),
                    "local_time": row.get("local_time"),
                    "timezone": tz_name,
                    "clock": clock,
                    "source_url": str(row.get("source_url") or source_url),
                    "retrieved_at": retrieved_at,
                }
            )
        upcoming.sort(key=lambda item: item["decision_date"])
        chosen = upcoming[:_POLICY_DECISION_COUNT]
        if not chosen:
            gaps.append(
                {
                    "kind": "policy_calendar",
                    "country": bank,
                    "reason": "no verified upcoming policy decisions after as_of",
                    "source_url": source_url,
                }
            )
        banks_out[bank] = {
            "timezone": tz_name,
            "source_url": source_url,
            "retrieved_at": retrieved_at,
            "decisions": chosen,
            "count": len(chosen),
        }
    return banks_out, gaps


def _expected_near_term_from_cache(
    slots: list[dict[str, Any]],
    *,
    window_start: date,
    window_end_exclusive: date,
) -> list[tuple[str, str, str, str]]:
    """Return (country, family, source_url, retrieved_at) expected in-window from inputs."""
    expected: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    wanted = set(_NEAR_TERM_OFFICIAL_FAMILIES)
    for slot in slots:
        family = str(slot.get("event_family") or "")
        country = str(slot.get("country") or "")
        if (country, family) not in wanted:
            continue
        try:
            local_d = date.fromisoformat(str(slot["local_date"])[:10])
        except ValueError:
            continue
        if not (window_start <= local_d < window_end_exclusive):
            continue
        key = (country, family, str(slot.get("local_date")))
        if key in seen:
            continue
        seen.add(key)
        expected.append(
            (
                country,
                family,
                str(slot.get("source_url") or ""),
                str(slot.get("fetched_at") or ""),
            )
        )
    return expected


def build_evidence_calendar(
    as_of: datetime,
    *,
    root: Path,
    allow_network: bool = False,
) -> dict[str, Any]:
    """Assemble official macro releases and policy decisions for an evidence freeze."""
    root = _root_path(root)
    clock = _aware_as_of(as_of)
    window_start = clock.date()
    window_end_exclusive = window_start + timedelta(days=_WINDOW_DAYS)
    as_of_utc = clock.astimezone(timezone.utc)

    raw_slots, schedule_fetch = _load_schedule_slots(clock, root=root, allow_network=allow_network)

    gaps: list[dict[str, Any]] = []
    accepted_slots: list[dict[str, Any]] = []

    for slot in raw_slots:
        try:
            local_d = date.fromisoformat(str(slot["local_date"])[:10])
        except (TypeError, ValueError, KeyError):
            gaps.append(
                {
                    "kind": "release_schedule",
                    "country": str(slot.get("country") or ""),
                    "reason": "invalid or missing local_date",
                    "event_family": str(slot.get("event_family") or ""),
                }
            )
            continue

        if local_d < window_start or local_d >= window_end_exclusive:
            continue

        fetched_at = _parse_utc_stamp(str(slot.get("fetched_at") or ""))
        if fetched_at is not None and fetched_at > as_of_utc:
            gaps.append(
                {
                    "kind": "release_schedule",
                    "country": str(slot.get("country") or ""),
                    "reason": "schedule row retrieved_at is after as_of",
                    "retrieved_at": slot.get("fetched_at"),
                    "event_family": str(slot.get("event_family") or ""),
                    "local_date": slot.get("local_date"),
                    "source_url": slot.get("source_url"),
                }
            )
            continue

        release_instant = _slot_local_instant(slot)
        if release_instant is not None and release_instant < clock:
            continue

        try:
            _slot_to_event(slot)
        except (ValueError, TypeError, KeyError) as exc:
            gaps.append(
                {
                    "kind": "release_schedule",
                    "country": str(slot.get("country") or ""),
                    "reason": f"invalid schedule row: {exc}",
                    "event_family": str(slot.get("event_family") or ""),
                    "local_date": slot.get("local_date"),
                }
            )
            continue

        accepted_slots.append(slot)

    events = _group_slots(accepted_slots)
    events.sort(
        key=lambda ev: (
            ev.get("local_date") or "",
            ev.get("country") or "",
            ev.get("event_family") or "",
            ev.get("title") or "",
        )
    )

    countries_with_events = {str(ev.get("country") or "") for ev in events}
    for cc in COUNTRIES:
        if cc not in countries_with_events:
            country_diag = (schedule_fetch.get("countries") or {}).get(cc) or {}
            adapter_gaps = list(country_diag.get("gaps") or [])
            if adapter_gaps:
                for msg in adapter_gaps:
                    gaps.append(
                        {
                            "kind": "release_schedule",
                            "country": cc,
                            "reason": msg,
                        }
                    )
            else:
                gaps.append(
                    {
                        "kind": "release_schedule",
                        "country": cc,
                        "reason": "no official release rows in the 30-day window",
                    }
                )

    for cc, diag in (schedule_fetch.get("countries") or {}).items():
        for msg in diag.get("gaps") or []:
            text = str(msg)
            if not any(g.get("country") == cc and g.get("reason") == text for g in gaps):
                gaps.append({"kind": "release_schedule", "country": str(cc), "reason": text})

    policy_decisions, policy_gaps = _build_policy_block(clock, root=root)
    gaps.extend(policy_gaps)

    present_families = {(ev["country"], ev["event_family"]) for ev in events}
    for country, family, source_url, retrieved_at in _expected_near_term_from_cache(
        raw_slots,
        window_start=window_start,
        window_end_exclusive=window_end_exclusive,
    ):
        if (country, family) not in present_families:
            gaps.append(
                {
                    "kind": "cross_check",
                    "country": country,
                    "event_family": family,
                    "reason": "official near-term release listed in cache but missing from calendar block",
                    "source_url": source_url,
                    "retrieved_at": retrieved_at,
                }
            )

    gaps.sort(
        key=lambda g: (
            str(g.get("kind") or ""),
            str(g.get("country") or ""),
            str(g.get("event_family") or ""),
            str(g.get("reason") or ""),
        )
    )

    body_for_hash = {
        "events": events,
        "coverage_gaps": gaps,
        "policy_decisions": policy_decisions,
        "window_end_exclusive": window_end_exclusive.isoformat(),
        "window_start": window_start.isoformat(),
    }
    content_hash = sha256_json(body_for_hash)

    return {
        "as_of": clock.isoformat(),
        "allow_network": allow_network,
        "window_start": window_start.isoformat(),
        "window_end_exclusive": window_end_exclusive.isoformat(),
        "events": events,
        "policy_decisions": policy_decisions,
        "coverage_gaps": gaps,
        "content_hash": content_hash,
        "schedule_sources": {
            "cache_path": "data/dashboard_repair/official_release_cache.json",
            "policy_calendar_path": "data/policy_meetings.json",
            "countries_attempted": list(COUNTRIES),
        },
    }


def events_from_committed_cache(
    root: Path,
    *,
    horizon_start: date,
    horizon_end: date,
) -> list[EconomicReleaseEvent]:
    """Load parsed events from the committed official cache (tests / diagnostics)."""
    path = root / "data" / "dashboard_repair" / "official_release_cache.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: list[EconomicReleaseEvent] = []
    for blob in (raw.get("countries") or {}).values():
        for item in blob.get("events") or []:
            if not isinstance(item, dict):
                continue
            try:
                ev = _event_from_cache_dict(item)
            except (ValueError, TypeError, KeyError):
                continue
            if horizon_start <= ev.local_date <= horizon_end:
                out.append(ev)
    return out


__all__ = ["build_evidence_calendar", "events_from_committed_cache"]
