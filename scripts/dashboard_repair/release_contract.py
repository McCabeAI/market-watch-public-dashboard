"""Canonical contract for economic release calendar metadata.

Calendar metadata only: do not collect observations or compute scores. A missing
clock on the source page stays TBA; cadence is not a schedule date.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Mapping, Protocol
from zoneinfo import ZoneInfo

STATUSES = ("verified", "standing", "tba")
DATE_CONFIDENCE = ("confirmed", "provisional")
COUNTRIES = ("US", "CA", "EA", "AU", "NZ", "JP")

_EVENT_FAMILY_PATTERN = re.compile(r"^[a-z0-9_]+$")
_LOCAL_TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


@dataclass(frozen=True)
class SourceDocument:
    """One official document planned for fetch (key is the stable mapping key)."""

    key: str  # stable document id used as the documents mapping key
    url: str  # https only
    description: str


@dataclass(frozen=True)
class EconomicReleaseEvent:
    """One economic release line derived from publisher text, not inferred cadence."""

    event_family: str  # stable snake id, e.g. ca_lfs, au_wpi, jp_gdp
    country: str  # one of COUNTRIES
    title: str  # economic release title, not a series card name
    publisher: str
    local_date: date  # calendar date in `timezone`
    local_time: str | None  # "HH:MM" 24-hour, or None when TBA
    timezone: str  # IANA name
    reference_period: str  # publisher period label; "" if the page has none
    source_url: str  # https
    fetched_at: str  # UTC timestamp ending in Z
    status: str  # verified | standing | tba
    series_ids: tuple[str, ...]  # catalog ids affected; may be empty
    provenance: str  # what was printed, not a cadence guess
    date_confidence: str = "confirmed"  # confirmed | provisional

    def event_id(self) -> str:
        return (
            f"{self.country}:{self.event_family}:"
            f"{self.local_date.isoformat()}:{self.reference_period}"
        )


class CountryScheduleAdapter(Protocol):
    """Per-country parser of already-fetched official documents."""

    country: str

    def source_plan(self) -> tuple[SourceDocument, ...]:
        ...

    def parse_documents(
        self,
        documents: Mapping[str, str],
        *,
        now: datetime,
        fetched_at: str,
    ) -> list[EconomicReleaseEvent]:
        """Parse already-fetched bodies. No network. Never invent a date from cadence or guess a clock."""


def _valid_iana_zone(name: str) -> bool:
    try:
        ZoneInfo(name)
    except Exception:
        return False
    return True


def validate_source_plan(plan: tuple[SourceDocument, ...]) -> None:
    """Raise ValueError if any source document URL is not https or fields are empty."""
    for doc in plan:
        if not doc.key.strip():
            raise ValueError("source plan document has empty key")
        if not doc.description.strip():
            raise ValueError("source plan document has empty description")
        if not doc.url.startswith("https://"):
            raise ValueError(f"source plan document url must start with https://, got {doc.url!r}")


def validate_event(event: EconomicReleaseEvent) -> None:
    """Raise ValueError with a specific reason when ``event`` violates the contract."""
    if event.country not in COUNTRIES:
        raise ValueError(f"country must be one of {COUNTRIES}, got {event.country!r}")
    if event.status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}, got {event.status!r}")
    if event.date_confidence not in DATE_CONFIDENCE:
        raise ValueError(
            f"date_confidence must be one of {DATE_CONFIDENCE}, got {event.date_confidence!r}"
        )
    if not event.event_family or not _EVENT_FAMILY_PATTERN.fullmatch(event.event_family):
        raise ValueError(
            "event_family must be non-empty and match [a-z0-9_]+, "
            f"got {event.event_family!r}"
        )
    for label, val in (
        ("title", event.title),
        ("publisher", event.publisher),
        ("provenance", event.provenance),
        ("source_url", event.source_url),
    ):
        if not str(val).strip():
            raise ValueError(f"{label} must be non-empty")
    if not event.source_url.startswith("https://"):
        raise ValueError(f"source_url must start with https://, got {event.source_url!r}")
    if not _valid_iana_zone(event.timezone):
        raise ValueError(f"timezone is not a valid IANA zone: {event.timezone!r}")
    if not event.fetched_at.endswith("Z"):
        raise ValueError(f"fetched_at must end with Z, got {event.fetched_at!r}")
    if not isinstance(event.local_date, date):
        raise ValueError("local_date must be a datetime.date instance")

    if event.status in ("verified", "standing") and event.local_time is None:
        raise ValueError(f"status {event.status!r} requires local_time to be set")
    if event.status == "tba" and event.local_time is not None:
        raise ValueError("status 'tba' requires local_time to be None")

    if event.local_time is not None:
        if not _LOCAL_TIME_PATTERN.fullmatch(event.local_time):
            raise ValueError(
                f"local_time must be HH:MM in 24-hour form (00:00-23:59), got {event.local_time!r}"
            )

    seen_series: set[str] = set()
    for sid in event.series_ids:
        if sid in seen_series:
            raise ValueError(f"duplicate series_id in series_ids: {sid!r}")
        seen_series.add(sid)


def validate_events(events: list[EconomicReleaseEvent]) -> None:
    """Validate each event and ensure ``event_id`` values are unique."""
    seen_ids: set[str] = set()
    for ev in events:
        validate_event(ev)
        eid = ev.event_id()
        if eid in seen_ids:
            raise ValueError(f"duplicate event_id: {eid!r}")
        seen_ids.add(eid)


def event_to_slot(event: EconomicReleaseEvent) -> dict[str, object]:
    """Shape consumed later by ``calendar_view`` (release slot / card payload)."""
    validate_event(event)
    base: dict[str, object] = {
        "series_ids": list(event.series_ids),
        "country": event.country,
        "name": event.title,
        "publisher": event.publisher,
        "source_url": event.source_url,
        "provenance": event.provenance,
        "reference_period": event.reference_period,
        "clock": event.status,
        "timezone": event.timezone,
        "event_family": event.event_family,
        "event_id": event.event_id(),
        "date_confidence": event.date_confidence,
        "fetched_at": event.fetched_at,
        "local_date": event.local_date.isoformat(),
    }
    if event.local_time is not None:
        base["stamp"] = f"{event.local_date.isoformat()}T{event.local_time}:00"
        base["printed_clock"] = event.local_time
    else:
        base["stamp"] = ""
        base["printed_clock"] = ""
    return base


def events_to_slots(events: list[EconomicReleaseEvent]) -> list[dict[str, object]]:
    """Validate all events, then map to slot dicts."""
    validate_events(events)
    return [event_to_slot(ev) for ev in events]


def instant_in_zone(event: EconomicReleaseEvent) -> datetime | None:
    """Aware local instant in the publisher zone, or None when time is TBA."""
    validate_event(event)
    if event.local_time is None:
        return None
    tz = ZoneInfo(event.timezone)
    h, m = map(int, event.local_time.split(":", 1))
    return datetime(
        event.local_date.year,
        event.local_date.month,
        event.local_date.day,
        h,
        m,
        0,
        tzinfo=tz,
    )


def instant_in_et(event: EconomicReleaseEvent) -> datetime | None:
    """Convert :func:`instant_in_zone` to America/New_York, or None when TBA."""
    z = instant_in_zone(event)
    if z is None:
        return None
    return z.astimezone(ZoneInfo("America/New_York"))


__all__ = [
    "COUNTRIES",
    "DATE_CONFIDENCE",
    "STATUSES",
    "CountryScheduleAdapter",
    "EconomicReleaseEvent",
    "SourceDocument",
    "events_to_slots",
    "event_to_slot",
    "instant_in_et",
    "instant_in_zone",
    "validate_event",
    "validate_events",
    "validate_source_plan",
]
