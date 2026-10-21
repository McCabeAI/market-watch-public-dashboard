"""ABS CPI release datetimes with per-entry provenance.

Verified dates were read from archived ABS release pages (web.archive.org
captures of www.abs.gov.au) or from data/macro_ingestion/fragments/au.json.
The complete Monthly CPI back-cast (2024-04..2025-09) uses the first
publication of that series, the October 2025 reference release. Months
without an official page in this table use the last-Wednesday rule and are
labeled ``rule_inferred_last_wednesday``. November reference months are a
known holiday exception (verified: 2025-11 released 2026-01-07; 2026-11
releases 2027-01-06) and that exception is not guessed for other Novembers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

SYDNEY = ZoneInfo("Australia/Sydney")

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_FRAGMENT = REPO_ROOT / "data" / "macro_ingestion" / "fragments" / "au.json"

FIRST_COMPLETE_MONTHLY_REFERENCE = "2025-10"
BACKCAST_START = "2024-04"
BACKCAST_END = "2025-09"
# Quarters are published inside the monthly release from the first complete
# monthly quarter-end month onward (March, June, September, December).
MONTHLY_QUARTER_PUBLICATION_FROM = "2025-12"

MIRROR = "mirror:web.archive.org"
PAGE_BASE = "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/consumer-price-index-australia"

PROVENANCE_WAYBACK = "abs_release_page_via_wayback"
PROVENANCE_FRAGMENT = "catalog_fragment"
PROVENANCE_FUTURE = "abs_aug2026_page_future_releases"
PROVENANCE_WEIGHT_DATE = "abs_aug2026_page_january_2027_weight_release"
PROVENANCE_CLOCK = "standing_release_clock_11_30"
PROVENANCE_BACKCAST = "backcast_first_publication_complete_monthly_cpi"
PROVENANCE_INFERRED = "rule_inferred_last_wednesday"
PROVENANCE_WITH_LAST_MONTH = "published_with_quarter_last_month"


@dataclass(frozen=True)
class ReleaseEntry:
    reference_period: str
    release_at: str
    provenance: tuple[str, ...]
    source: str
    note: str
    frequency: str = "M"
    mirror: str | None = None
    capture_timestamp: str | None = None
    original_url: str | None = None

    def __post_init__(self) -> None:
        if not self.provenance:
            raise ValueError(f"release entry {self.reference_period} has no provenance")


def _page(slug: str) -> str:
    return f"{PAGE_BASE}/{slug}"


def _wayback(capture: str, original: str) -> str:
    return f"https://web.archive.org/web/{capture}/{original}"


def _at_1130(day: date) -> str:
    return datetime(day.year, day.month, day.day, 11, 30, tzinfo=SYDNEY).isoformat()


def _wayback_entry(
    period: str,
    release_day: date,
    *,
    slug: str,
    capture: str,
    quote: str,
    extra_provenance: tuple[str, ...] = (),
) -> ReleaseEntry:
    original = _page(slug)
    return ReleaseEntry(
        reference_period=period,
        release_at=_at_1130(release_day),
        provenance=(PROVENANCE_WAYBACK,) + extra_provenance,
        source=_wayback(capture, original),
        note=quote,
        frequency="M",
        mirror=MIRROR,
        capture_timestamp=capture,
        original_url=original,
    )


def _build_explicit() -> dict[str, ReleaseEntry]:
    """Curated monthly entries. Strings are the release timestamps implied by the cited pages."""
    aug_capture = "20261010043606"
    aug_original = _page("aug-2026")
    aug_source = _wayback(aug_capture, aug_original)
    clock_note = (
        "The future-releases line on the archived August 2026 page prints the calendar date "
        "without a separate clock. 11:30 Australia/Sydney is the standing CPI release time "
        "printed on that page for the August 2026 release ('30/09/2026 11:30am AEST'). "
        "The UTC offset is Australia/Sydney civil time on the release date."
    )
    entries = {
        "2025-10": _wayback_entry(
            "2025-10",
            date(2025, 11, 26),
            slug="oct-2025",
            capture="20251126005454",
            quote=(
                "Archived October 2025 release page: Reference period October 2025; "
                "Released 26/11/2025; clock line '26/11/2025 11:30am AEDT'."
            ),
        ),
        "2025-11": _wayback_entry(
            "2025-11",
            date(2026, 1, 7),
            slug="nov-2025",
            capture="20260107004215",
            quote=(
                "Archived November 2025 release page: Reference period November 2025; "
                "Released 7/01/2026; clock line '07/01/2026 11:30am AEDT'. "
                "This is the holiday exception (not the last Wednesday of December 2025)."
            ),
        ),
        "2025-12": _wayback_entry(
            "2025-12",
            date(2026, 1, 28),
            slug="dec-2025",
            capture="20260128003929",
            quote=(
                "Archived December 2025 release page: Reference period December 2025; "
                "Released 28/01/2026; clock line '28/01/2026 11:30am AEDT'."
            ),
        ),
        "2026-01": _wayback_entry(
            "2026-01",
            date(2026, 2, 25),
            slug="jan-2026",
            capture="20260225003600",
            quote=(
                "Archived January 2026 release page: Reference period January 2026; "
                "Released 25/02/2026; clock line '25/02/2026 11:30am AEDT'."
            ),
        ),
        "2026-02": _wayback_entry(
            "2026-02",
            date(2026, 3, 25),
            slug="feb-2026",
            capture="20260325004012",
            quote=(
                "Archived February 2026 release page: Reference period February 2026; "
                "Released 25/03/2026; clock line '25/03/2026 11:30am AEDT'."
            ),
        ),
        "2026-03": _wayback_entry(
            "2026-03",
            date(2026, 4, 29),
            slug="mar-2026",
            capture="20260429013607",
            quote=(
                "Archived March 2026 release page: Reference period March 2026; "
                "Released 29/04/2026; clock line '29/04/2026 11:30am AEST'."
            ),
        ),
        "2026-04": _wayback_entry(
            "2026-04",
            date(2026, 5, 27),
            slug="apr-2026",
            capture="20260527043917",
            quote=(
                "Archived April 2026 release page: Reference period April 2026; "
                "Released 27/05/2026; clock line '27/05/2026 11:30am AEST'."
            ),
        ),
        "2026-05": _wayback_entry(
            "2026-05",
            date(2026, 6, 24),
            slug="may-2026",
            capture="20260624023948",
            quote=(
                "Archived May 2026 release page: Reference period May 2026; "
                "Released 24/06/2026; clock line '24/06/2026 11:30am AEST'."
            ),
        ),
        "2026-06": _wayback_entry(
            "2026-06",
            date(2026, 7, 29),
            slug="jun-2026",
            capture="20260729081712",
            quote=(
                "Archived June 2026 release page: Reference period June 2026; "
                "Released 29/07/2026; clock line '29/07/2026 11:30am AEST'."
            ),
        ),
        "2026-07": _wayback_entry(
            "2026-07",
            date(2026, 8, 26),
            slug="jul-2026",
            capture="20260827121925",
            quote=(
                "Archived July 2026 release page: Reference period July 2026; "
                "Released 26/08/2026; clock line '26/08/2026 11:30am AEST'."
            ),
        ),
        "2026-08": ReleaseEntry(
            reference_period="2026-08",
            release_at="2026-09-30T11:30:00+10:00",
            provenance=(PROVENANCE_WAYBACK, PROVENANCE_FRAGMENT),
            source=aug_source,
            note=(
                "Archived August 2026 release page (capture 20261010043606): Reference period "
                "August 2026; Released 30/09/2026; 'Release date and time 30/09/2026 11:30am AEST'. "
                "data/macro_ingestion/fragments/au.json maps 2026-09-30T11:30:00+10:00 to 2026-08 "
                "for AU.Inflation.headline and AU.Inflation.underlying."
            ),
            mirror=MIRROR,
            capture_timestamp=aug_capture,
            original_url=aug_original,
        ),
        "2026-09": ReleaseEntry(
            reference_period="2026-09",
            release_at="2026-10-28T11:30:00+11:00",
            provenance=(PROVENANCE_FUTURE, PROVENANCE_FRAGMENT),
            source=aug_source,
            note=(
                "Archived August 2026 page future releases: 'Next Release 28/10/2026 "
                "Consumer Price Index, Australia, September 2026'. Full timestamp "
                "2026-10-28T11:30:00+11:00 is the AU.Inflation.headline entry in "
                "data/macro_ingestion/fragments/au.json (expected_periods)."
            ),
            mirror=MIRROR,
            capture_timestamp=aug_capture,
            original_url=aug_original,
        ),
        "2026-10": ReleaseEntry(
            reference_period="2026-10",
            release_at="2026-11-25T11:30:00+11:00",
            provenance=(PROVENANCE_FUTURE, PROVENANCE_CLOCK),
            source=aug_source,
            note=(
                "Archived August 2026 page future releases: 'Next Release 25/11/2026 "
                "Consumer Price Index, Australia, October 2026'. " + clock_note
            ),
            mirror=MIRROR,
            capture_timestamp=aug_capture,
            original_url=aug_original,
        ),
        "2026-11": ReleaseEntry(
            reference_period="2026-11",
            release_at="2027-01-06T11:30:00+11:00",
            provenance=(PROVENANCE_FUTURE, PROVENANCE_CLOCK),
            source=aug_source,
            note=(
                "Archived August 2026 page future releases: 'Next Release 6/01/2027 "
                "Consumer Price Index, Australia, November 2026'. Holiday exception, "
                "not the last Wednesday of December 2026. " + clock_note
            ),
            mirror=MIRROR,
            capture_timestamp=aug_capture,
            original_url=aug_original,
        ),
        "2027-01": ReleaseEntry(
            reference_period="2027-01",
            release_at="2027-02-24T11:30:00+11:00",
            provenance=(PROVENANCE_WEIGHT_DATE, PROVENANCE_CLOCK),
            source=aug_source,
            note=(
                "Archived August 2026 page: 'The CPI weights will be updated for January 2027, "
                "scheduled for release on 24 February 2027.' " + clock_note
            ),
            mirror=MIRROR,
            capture_timestamp=aug_capture,
            original_url=aug_original,
        ),
    }
    return entries


_EXPLICIT: dict[str, ReleaseEntry] = _build_explicit()


def last_wednesday(year: int, month: int) -> date:
    if month == 12:
        following = date(year + 1, 1, 1)
    else:
        following = date(year, month + 1, 1)
    last = following - timedelta(days=1)
    delta = (last.weekday() - 2) % 7
    return last - timedelta(days=delta)


def _shift_month(period: str, delta: int) -> tuple[int, int]:
    year, month = int(period[:4]), int(period[5:7])
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def inferred_last_wednesday(period: str) -> ReleaseEntry:
    """Last Wednesday of the month after ``period``, labeled as inferred.

    November reference months have a verified holiday exception (2025-11 and
    2026-11). This function does not guess that exception. From February 2027
    the ABS stated CPI moves to the fourth Wednesday; dates produced by this
    rule for releases in that regime are additionally unreliable.
    """
    year, month = _shift_month(period, 1)
    day = last_wednesday(year, month)
    ref_month = int(period[5:7])
    note = (
        f"No archived ABS release page was used for reference {period}. "
        f"Release date is the last Wednesday of {year:04d}-{month:02d} "
        f"({day.isoformat()}) at the standing 11:30 Australia/Sydney clock. "
        "November reference months are a known exception and are not guessed: "
        "verified 2025-11 was released 2026-01-07 (not 2025-12-31) and verified "
        "2026-11 is scheduled 2027-01-06 (not 2026-12-30). The archived August 2026 "
        "page says that from February 2027 CPI moves to the fourth Wednesday, so "
        "this last-Wednesday rule is not applied as fact for that later regime."
    )
    if ref_month == 11:
        note += " This reference month is November, so the inferred date is especially unreliable."
    return ReleaseEntry(
        reference_period=period,
        release_at=_at_1130(day),
        provenance=(PROVENANCE_INFERRED,),
        source="rule:last_wednesday_of_following_month",
        note=note,
        frequency="M",
    )


def _period_in(period: str, start: str, end: str) -> bool:
    return start <= period <= end


def _backcast_entry(period: str) -> ReleaseEntry:
    first = _EXPLICIT[FIRST_COMPLETE_MONTHLY_REFERENCE]
    return ReleaseEntry(
        reference_period=period,
        release_at=first.release_at,
        provenance=(PROVENANCE_BACKCAST, PROVENANCE_WAYBACK),
        source=first.source,
        note=(
            f"Complete Monthly CPI back-cast period {period}. These months were first "
            f"published with the October 2025 reference on {first.release_at}. "
            "They do not have an earlier complete-monthly release date. "
            + first.note
        ),
        frequency="M",
        mirror=first.mirror,
        capture_timestamp=first.capture_timestamp,
        original_url=first.original_url,
    )


def _quarter_end_month(period: str) -> str:
    year_text, quarter_text = period.split("-Q")
    quarter = int(quarter_text)
    if quarter < 1 or quarter > 4:
        raise ValueError(f"bad quarter: {period}")
    return f"{int(year_text):04d}-{quarter * 3:02d}"


def _quarter_entry(period: str) -> ReleaseEntry:
    """Quarterly legacy prints are published with the quarter's last month once monthly CPI covers that month."""
    last_month = _quarter_end_month(period)
    if last_month >= MONTHLY_QUARTER_PUBLICATION_FROM and last_month[5:7] in {"03", "06", "09", "12"}:
        monthly = entry_for(last_month, regime="complete_monthly_cpi")
        return ReleaseEntry(
            reference_period=period,
            release_at=monthly.release_at,
            provenance=(PROVENANCE_WITH_LAST_MONTH,) + monthly.provenance,
            source=monthly.source,
            note=(
                f"Quarter {period} is published with the {last_month} monthly CPI release "
                "(ABS August 2026 page: quarterly tables are added in the March, June, "
                "September and December monthly releases). " + monthly.note
            ),
            frequency="Q",
            mirror=monthly.mirror,
            capture_timestamp=monthly.capture_timestamp,
            original_url=monthly.original_url,
        )
    year, month = _shift_month(last_month, 1)
    day = last_wednesday(year, month)
    return ReleaseEntry(
        reference_period=period,
        release_at=_at_1130(day),
        provenance=(PROVENANCE_INFERRED,),
        source="rule:last_wednesday_of_month_after_quarter_end",
        note=(
            f"No official quarterly release timestamp was fetched for {period}. "
            f"Inferred as the last Wednesday of the month after quarter-end {last_month} "
            f"({day.isoformat()} 11:30 Australia/Sydney). Holiday exceptions are not guessed. "
            "This is not the complete-monthly back-cast timestamp."
        ),
        frequency="Q",
    )


@lru_cache(maxsize=1)
def catalog_fragment_cpi_schedule() -> dict[str, str]:
    """Map reference period -> release timestamp from the inflation fragment. Read-only."""
    payload = json.loads(CATALOG_FRAGMENT.read_text(encoding="utf-8"))
    found: dict[str, str] = {}
    for series in payload.get("series") or []:
        if series.get("id") not in {"AU.Inflation.headline", "AU.Inflation.underlying"}:
            continue
        rule = series.get("release_rule") or {}
        expected = rule.get("expected_periods") or {}
        for release_at, period in expected.items():
            previous = found.get(period)
            if previous is not None and previous != release_at:
                raise RuntimeError(
                    f"catalog fragment disagrees on {period}: {previous} vs {release_at}"
                )
            found[str(period)] = str(release_at)
    return found


def assert_catalog_fragment_consistent() -> None:
    """Fail if the curated 2026-08/2026-09 timestamps drift from the fragment."""
    schedule = catalog_fragment_cpi_schedule()
    for period in ("2026-08", "2026-09"):
        fragment_at = schedule.get(period)
        curated = _EXPLICIT[period].release_at
        if fragment_at != curated:
            raise RuntimeError(
                f"catalog fragment {period} is {fragment_at!r}; curated calendar has {curated!r}"
            )


def monthly_entries() -> tuple[ReleaseEntry, ...]:
    """Continuous monthly entries from the back-cast start through January 2027."""
    assert_catalog_fragment_consistent()
    out: list[ReleaseEntry] = []
    period = BACKCAST_START
    while period <= "2027-01":
        out.append(entry_for(period, regime="complete_monthly_cpi"))
        year, month = _shift_month(period, 1)
        period = f"{year:04d}-{month:02d}"
    return tuple(out)


def entry_for(period: str, regime: str | None = None) -> ReleaseEntry:
    """Release entry for a monthly reference period or a quarter."""
    assert_catalog_fragment_consistent()
    if "-Q" in period:
        if regime == "complete_monthly_cpi":
            raise ValueError(f"{period} is not a complete-monthly period")
        return _quarter_entry(period)
    regime = regime or "complete_monthly_cpi"
    if regime == "complete_monthly_cpi" and _period_in(period, BACKCAST_START, BACKCAST_END):
        return _backcast_entry(period)
    explicit = _EXPLICIT.get(period)
    if explicit is not None:
        return explicit
    return inferred_last_wednesday(period)


def published_at_for(period: str, regime: str | None = None) -> str:
    return entry_for(period, regime=regime).release_at


def parse_timestamp(value: str, *, date_only: str = "end") -> datetime:
    """Parse an ISO timestamp. Date-only values are Sydney civil start or end."""
    text = value.strip().replace("Z", "+00:00")
    if len(text) == 10:
        day = date.fromisoformat(text)
        if date_only == "end":
            return datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=SYDNEY)
        return datetime(day.year, day.month, day.day, 0, 0, tzinfo=SYDNEY)
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SYDNEY)
    return parsed


def published_on_or_before(published_at: str | None, as_of: str) -> bool:
    """Visible iff published_at <= as_of. A missing timestamp is not visible."""
    if not published_at:
        return False
    return parse_timestamp(published_at, date_only="end") <= parse_timestamp(as_of, date_only="end")


def sydney_now() -> datetime:
    return datetime.now(SYDNEY).replace(microsecond=0)
