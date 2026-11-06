# Release calendar ownership

One owner per file. Country workers must not edit shared files owned by another group.

## G2 (shared contract)

- `scripts/dashboard_repair/release_contract.py`
- `scripts/dashboard_repair/schedules/__init__.py` (docstring only)
- `docs/dashboard_repair/RELEASE_CALENDAR_OWNERSHIP.md`
- `tests/test_release_calendar_contract.py`

## US

- `scripts/dashboard_repair/schedules/us.py`
- `tests/test_release_calendar_us.py`
- `tests/fixtures/release_calendar/us/`

## CA

- `scripts/dashboard_repair/schedules/ca.py`
- `tests/test_release_calendar_ca.py`
- `tests/fixtures/release_calendar/ca/`

## EA

- `scripts/dashboard_repair/schedules/ea.py`
- `tests/test_release_calendar_ea.py`
- `tests/fixtures/release_calendar/ea/`

## AU

- `scripts/dashboard_repair/schedules/au.py`
- `tests/test_release_calendar_au.py`
- `tests/fixtures/release_calendar/au/`

## NZ

- `scripts/dashboard_repair/schedules/nz.py`
- `tests/test_release_calendar_nz.py`
- `tests/fixtures/release_calendar/nz/`

## JP

- `scripts/dashboard_repair/schedules/jp.py`
- `tests/test_release_calendar_jp.py`
- `tests/fixtures/release_calendar/jp/`

## Integrator

- `scripts/dashboard_repair/release_pipeline.py`
- Edits to `scripts/dashboard_repair/official_schedule.py` and `scripts/dashboard_repair/calendar_view.py`
- `data/dashboard_repair/official_release_cache.json`
- `tests/test_release_calendar_pipeline.py`
- `tests/fixtures/release_calendar/pipeline/`
- A one-line addition of the new unittest modules on the existing `tests.test_dashboard_repair` command in `.github/workflows/deploy-pages.yml` (no second workflow)

## Nobody

Do not edit `data/macro_ingestion/catalog.json`, scorecard books, generated site HTML, or ACP for this workstream.

---

## Slot contract

Events are validated `EconomicReleaseEvent` instances; slots are plain dicts with at least:

- `series_ids`, `country`, `name` (release title), `publisher`, `source_url`, `provenance`, `reference_period`
- `clock`: release clock status (`verified` \| `standing` \| `tba`) — not a series card name
- `timezone`, `event_family`, `event_id`, `date_confidence`, `fetched_at`
- `stamp`: naive local `YYYY-MM-DDTHH:MM:00` when a time is known (no offset; `timezone` holds the IANA zone), or `""` when TBA
- `local_date`: ISO calendar date
- `printed_clock`: `HH:MM` or `""`

**Integrator note:** `calendar_view._stamp_event` currently treats only `clock == "verified"` as a timed instant. `standing` still carries a real `stamp` and must keep that instant while labeling the clock as standing. TBA has a date and an empty `stamp` and must render “time TBA”, not be dropped. The integrator updates `calendar_view` accordingly. Country adapters only return `EconomicReleaseEvent` objects.

## Status meanings

- **verified:** The release line prints both the date and the clock.
- **standing:** The date is printed for that release, and the clock is the publisher’s standing time printed on the same official page (not necessarily on that row).
- **tba:** The date is printed and no clock is confirmed. Do not guess one.
- **date_confidence provisional:** The publisher printed the date and marked it provisional. Still not a cadence guess.
