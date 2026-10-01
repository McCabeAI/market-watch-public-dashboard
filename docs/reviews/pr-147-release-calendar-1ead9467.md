# Final review: Country Detail release calendar at `1ead9467`

**Verdict: PASS.** Exact commit `1ead9467d46155f443a849f39805ef96c10b7360` is safe to merge.

Reviewed tree: PR #147 head (`cursor/country-detail-freshness-and-six-country-review-repair-79c6`), parent `0e4dabcdad06710a02a8df14f038ac39d6115ed0`, base `main` at `00beda6e7cd7374499e4cd481ab53e9594bd3d71`. This review did not trust the PR body, did not launch a subagent, and did not modify implementation files.

## What was checked

The repair commit deletes the Country Detail grace table and routes due/late through `scripts/country_detail/release_status.py`, which calls `scripts/macro_ingestion/calendar.py`. The rest of the review is whether that delegation is real, whether the six-country dashboard still isolates attention, and whether score display and Trader Room stay outside the attention path.

Independent checks:

- Read `scripts/country_detail/release_status.py`, `scripts/country_detail/attention.py`, `scripts/country_detail/policy.py`, `scripts/country_detail/projection.py`, `scripts/country_detail/render.py`, `scripts/apply_country_detail.py`, `scripts/macro_ingestion/calendar.py`, and `scripts/macro_ingestion/runner.py` (`_classify_points`).
- Loaded the merged catalog (`load_catalog`: baseline plus country fragments) and classified every release rule.
- Built the on-disk Country Detail projection and ran `evaluate_projection` at the repository `as_of`. This reads local history only. It is not a market-watch launch, trader run, or publication.
- Re-evaluated the real New Zealand observations at the Stats NZ CPI instant.
- Ran the Country Detail unit modules. 52 tests, all passing.

## Grace table is gone

`scripts/country_detail/policy.py` no longer defines `NEXT_RELEASE_GRACE_DAYS`, `successor_due_date`, or `release_is_due`. A repository search at this commit finds no `NEXT_RELEASE_GRACE`, `successor_due_date`, or `release_is_due`. The old rule (monthly successor due 45 days after the next month ends, quarterly successor due 60 days after the next quarter ends) is not reachable.

`docs/COUNTRY_DETAIL_ATTENTION_V1.md` and `docs/COUNTRY_DETAIL_VALIDATION.md` now describe the macro-ingestion calendar instead of that grace table.

## How due/late is decided

`evaluate_observations` calls `assess_release` only when `release_aware` is set. `evaluate_projection` sets that flag for every country. `assess_release` returns `due` only in these cases:

1. The observation already carries repository due state: `status` or `ingestion_status` in `{due_missing, release_due_missing}`, or `release_due` is present and the held `reference_period` does not already cover `due_period`. Production projection rows do not copy those fields, so the live dashboard does not take this branch. It is a reuse of a stored flag, not a second clock.
2. Otherwise the observation's inline `release_rule`, or the merged catalog row for `catalog_id`, is passed to `schedule_parseable` and `latest_due_release`. An unparseable rule or an unusable `as_of` returns `release_calendar=unavailable` and `due=False`. The latest print stays current.
3. If a release instant is at or before `as_of`, successor presence follows the same order as `runner._classify_points`: a `known_fixture.period` that is not covered is due; a slot `expected_periods` binding that is not covered is due; a covered binding is satisfied.
4. If the due slot has no bound period and no uncovered fixture, the held publisher `release_date` must fall on or after that instant's local calendar day. Retrieval time is not used. A missing or earlier publisher date is due.

`_effective_data_state` still ignores `stale_after_days`. Superseded and explicit source `stale` stay ahead of the calendar. Calendar due maps to `due_late`, and `classify_attention` keeps that state at attention status `none`, so it cannot enter What Matters Now.

There is no copied date table in Country Detail. Instants, holiday rolling, and time zones come from `scripts/macro_ingestion/calendar.py` and `scripts/macro_ingestion/holidays.py`.

### Runner difference that is not a blocker

When a due slot has no `expected_periods` entry and no uncovered `known_fixture` period, `runner._classify_points` returns `calendar_unparsed` rather than `due_missing`. It cannot name the missing period, so it refuses an ingestion failure. `calendar.latest_due_release` still documents that missing period as "the date is due but not tied to a reference period."

Country Detail has to decide whether the latest print remains eligible. For an unbound instant it treats the publisher `release_date` as the proof that this print is the one that was released. That comparison lives in `assess_release` and is not a 45/60-day table. It is required for the New Zealand rules actually stored in the catalog: `NZ.Inflation.headline` and `NZ.Inflation.underlying` are `country_local_schedule_required` with a single naive local instant `2026-10-22T10:45:00` in `Pacific/Auckland` and no `expected_periods`.

## Catalog and live projection

Merged catalog: 130 series. Parseable schedules: 24. Of those, 6 bind `expected_periods` and 18 do not. One series (`EA.Activity.flash_composite_pmi`) has `known_fixture.period`. 106 series have an empty or missing date list, including US CPI and US unemployment (`dates: []` after the BLS schedule was not pinned) and Japan CPI (`schedule_unparsed`). Those stay `unavailable` and current. Country Detail does not invent a deadline for them.

Projection `as_of` is `2026-09-30T14:02:01Z` (newest `retrieved_at`). Attention at that instant:

| Country | Evaluated | Eligible | Due/late | Findings | Finding country |
|---|---:|---:|---:|---:|---|
| US | 19 | 19 | 0 | 3 | US |
| CA | 27 | 27 | 0 | 3 | CA |
| AU | 15 | 7 | 8 | 2 | AU |
| NZ | 13 | 13 | 0 | 3 | NZ |
| EA | 11 | 11 | 0 | 3 | EA |
| JP | 11 | 11 | 0 | 3 | JP |

96 observations. 42 have no `release_date`. None of those 42 are marked due at this `as_of`, because their rules are unparseable or their instants are still in the future. EA and JP flash PMI rules are parseable, but those catalog ids are not in the temperature-history projection, so they do not affect the six dashboard countries.

The eight Australian due rows are the calendar, not the deleted grace table:

- Bound slots whose expected period is absent: unemployment `A84423050A` held `2026-07` against slot `2026-09-24` / period `2026-08`; employment change held `2026-07` and employment level held `2025-08` against the same slot; CPI headline and trimmed mean held `2026-07` against `2026-09-30` / `2026-08`; household spending monthly and through-the-year held `2026-07` against `2026-09-30` / `2026-08`. On-disk history still ends at July for those ABS series. The old 45-day rule would have left July CPI current on 30 September. The catalog instant `2026-09-30T11:30:00+10:00` has passed by `14:02:01Z`, so due/late is the correction.
- Unbound slot: composite PMI held `2026-08` with publisher date `2026-09-03`, against `2026-09-24T23:00:00+10:00` and no `expected_periods`. The history gap still says September was not released as of 21 September, and the August print's publisher date is before the scheduled instant. Due/late matches the written unbound rule.

New Zealand at the repository `as_of` is `not_due` for every parseable series, because the catalog instants (CPI 22 October, labour 4 November, retail 23 November, GDP and spending 17 December) are still ahead. Replaying the same real observations:

- `2026-10-22T10:44:00+13:00`: CPI headline and underlying stay `ok` / `not_due`.
- `2026-10-22T10:45:00+13:00`: both CPI series, both transforms, become `due_late` / `due`. Publisher dates on the held Q2 prints are `2026-07-21`.
- `2026-10-21T21:45:00Z`: the same instant in UTC, also `due_late`. One minute earlier stays current.
- Labour, retail, GDP, and consumption stay `not_due` at the CPI instant because their own catalog dates have not been reached.

The unit test `test_nz_cpi_follows_the_repository_release_instant` matches this boundary, and the real history rows do too. A later Q3 print in that test is `satisfied` when its `release_date` is the release day, and the Q2 row becomes `superseded` rather than a second finding.

## Boundaries that stay intact

**Six-country attention.** `evaluate_projection` loops each present country with its own observations, `as_of`, and registry TTL. The TTL is stored as `retrieval_age_days` and is not an eligibility gate. The live run shows six separate reviews, no empty-country padding, and no finding whose country differs from its pane. Australia's eight due rows do not change US, CA, NZ, EA, or JP eligibility.

**UI hierarchy.** `render_country_detail` is still score compact, What Matters Now, score drilldown, then Remaining Country Evidence. Due/late is display label `Due` and is excluded from the finding list by `classify_attention`. Evidence search, topic buttons, and the filter script are still emitted. What Matters Now ids are omitted from Remaining Country Evidence. The repair does not edit `render.py`. The review fixture only changes because Australian due rows now render as Due.

**Score isolation.** `evaluate_observations` reads `score_state` and `frozen_packet` and discards them. It raises if the attention result contains `score_level`, `score_levels`, `score_state`, `impulse`, `temperature`, or `temperature_score`. Score numbers in the fragment come from `score_state` via `_render_score_compact` and `_render_score_drilldown`, including rows that attention has marked due. `apply_country_detail` loads `data/temperature_scores.json` and does not write it.

**Trader Room firewall.** Country Detail modules do not import `scripts.trader_room`, `scripts.trading`, `scripts.pm`, or `scripts/market_watch_launch/freeze.py`. `policy.attention_import_forbidden` and `packet_contains_attention` are unchanged. `tests/test_country_detail_contract.py` still scans those trees for `country_detail` references. This commit does not touch them.

## Tests

`python3 -m unittest tests.test_country_detail_release_review tests.test_country_detail_attention tests.test_country_detail_travel tests.test_country_detail_contract tests.test_country_detail_render tests.test_country_detail_apply tests.test_country_detail_projection`

52 tests, OK. The release-review module covers clock age versus eligibility, due versus superseded, six-country isolation, the NZ CPI instant in both Auckland and UTC, an empty `country_local_schedule_required` rule, a bare series with no catalog rule, and explicit `release_due` / `due_missing` reuse.

## Residual notes, not merge blockers

- Unbound instants use publisher `release_date` because the ingestion runner will not emit `due_missing` without a named period. A future print of an unbound series that omits `release_date` would be marked due even if its reference period is the new one. Current New Zealand CPI rows have publisher dates, and the successor test covers the release-day case. Filling `expected_periods` on those catalog rules would make the bound-period path sufficient.
- An explicit `due_missing` status wins over the clock, including before the instant. The dashboard projection does not set that field.
- `AU.Activity.business_surveys` is due at the current projection `as_of` under the unbound rule. The catalog timestamp is used as stored (`2026-09-24T23:00:00+10:00`). This review did not rewrite that source timestamp.

No implementation change is required for this commit.
