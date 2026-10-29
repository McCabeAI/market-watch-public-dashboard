# Collection repair verdict — 2026-10-29

**Final verdict: PASS.** Parent is Grok 4.7. No production deploy has been run. This does not claim the live site is already healthier.

Branch `cursor/reliable-usable-market-watch-collection-grok-4-7-composer-graph-e865`. Tip after the results note: `718fce9e8106715cb8acf012cb84d712a9b9b336`. Base is main `78fa0367`.

## Invocations

Nine accepted agent invocations, inside the cap of 18. One Grok call (the parent), inside the cap of 2. No node used a second repair attempt. Models were Grok 4.7 for the parent and Composer 2.5 for every other node.

| Node | Role | Result |
| --- | --- | --- |
| P | Plan, ownership, final approval | PASS |
| A | Runner, observation identity, cadence backstop | `e438ff8c` (content of `6ddf6b71` after a history rewrite) |
| B | US labor batching and ISM routes | `8c3b7f6c`. Parent restored three scored US series the commit had dropped. |
| C | NZ release discovery | `54b02c0f` |
| D | CA producer pins and AU workbook routing | `4218f6e8` |
| E | Acceptance, PR CI, data-only catch-up | `a6d63bdc` |
| I | Targeted tests and one isolated live run | `718fce9e`. 95 tests passed. Live exit 0. |
| V1 | Identity, period, units, fallback | PASS |
| V2 | State, freshness, CI, frozen evidence | PASS |

The four acquisition nodes wrote one working tree. A later NZ amend dropped the runner commit; it was cherry-picked back and merged before review.

## What changed

A failing FRED host no longer occupies the whole US pass. In the isolated live run, core PCE, core CPI, PPI, and several other FRED rows are `host_deferred`, while unemployment, payrolls, and participation completed from BLS. ISM manufacturing and services were read from PR Newswire pages that identify the ISM headline (`NAPM` 54.5 and `NMFBAI` 54.9 for September 2026). Canada IPPI and RMPI use the existing PRIMA total vectors `1230995983` and `1230998135`. New Zealand discovery follows the publisher listing and stores the June 2026 quarter that is in the files. Australia domestic final demand `A2304183K` is 2026-Q2, 0.3, from the expenditure-volume workbook, separate from GDP `A2304370T` at 0.4.

Launch ingestion still fetches a country when one weighted series mismatches. Retry health is written from the merged rows. A seeded store classifies an unchanged value as `checked_unchanged` (`test_seed_store_classifies_checked_unchanged`). An empty calendar plus an old period sets the cadence backstop and the research state "previous release retained" without redating the value. Pull-request CI no longer runs the daily market-state live smoke or generator. The data-only CLI writes under an output directory and the frozen-evidence test keeps `evidence_snapshot.json` byte-identical.

## Before and after

The 29 October launch matrix had 224 entries and 115 `source_failed`, including about 70 repeated US `budget_deferred` rows. The retry health file had 89 failures and was not the whole run. Canada IPPI and RMPI were unpinned. New Zealand CPI was still requested from a June-quarter URL.

The repair live run covered only US, Canada, New Zealand, and Australia: 176 health rows (US 93, Australia 37, Canada 29, New Zealand 17). Counts: 130 `new_observation`, 29 `source_failed`, 10 `license_gap`, 5 `not_applicable`, 1 `checked_unchanged`, 1 `calendar_unparsed`. The 130 new rows are first inserts into an empty output directory, not 130 new releases. Euro area and Japan were not in that run.

Checked live observations:

- US unemployment `UNRATE` 2026-09, 4.2 percent, BLS `LNS14000000`. Payrolls September 2026, 29.0 thousand, BLS `CES0000000001`.
- US CPI `CPIAUCSL` September 2026, 336.298, BLS `CUSR0000SA0`. Core CPI was `host_deferred`, not filled with a different index.
- NZ CPI 2026-Q2, 4.1 percent year over year. GDP 0.2 percent quarter over quarter. Retail about -0.53 percent quarter over quarter. Wages about 1.96 percent year over year. Periods were not moved to 29 October.
- CA IPPI September 2026, 150.7 index. RMPI September 2026, 182.7 index.

## Residual gaps

These sources were still unavailable in the live run. They are not marked successful.

- US BEA series (core PCE, income, spending, GDP) and Census retail still depend on FRED or timed out. Sentiment, FHFA, and the mortgage rate stayed on FRED and were deferred or timed out. ADP, Challenger, Conference Board, and the flash PMI remain licensed or unparsed.
- NZ experimental income did not parse on the live page. PPI and trade-price indexes are still unpinned and returned 404. No verified same-series fallback exists for RBNZ bond yields, so official workbook and HTML remain the only routes.
- CA import/export prices and participation have no vector already evidenced in the repo, so they stay unpinned. Bank of Canada confidence and CREA sales remain license gaps.
- AU Westpac confidence has no verified primary adapter. SEEK period extraction and Jobs and Skills Australia requests still failed or timed out.
- Euro area and Japan parsers were not expanded.
- `country_detail_sections.json` from the data-only command is rendered from the repository root, not from the isolated observation directory. The inspected research artifact is the observation store.

## Tests

Integrator suite: 95 passed, 0 failed. Earlier focused runs: runner, calendar, integrity, and NZ tests 56 passed; Canada and Australia adapter tests 41 passed; acceptance and source-health tests 26 passed.
