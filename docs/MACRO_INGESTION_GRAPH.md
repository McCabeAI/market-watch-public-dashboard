# Ingestion graph log

Parent model: Grok 4.7. Subagent allowlist: `composer-2.5` only. Caps: 1 frontier parent call, up to 9 Composer tasks. No second Grok call, no other model.

| Step | Model | State |
| --- | --- | --- |
| Audit main at `54673b377165a21911f6569665bbc17ff5cdb1a5`, write matrix, architecture, Drive plan, baseline catalog | Grok 4.7 parent | done (`8f8fdaa`) |
| Shared platform contract | Composer 2.5 | done (`3929605`, then graph note `06d2ff2`) |
| Country US | Composer 2.5 | done (parallel task; committed in `7efb3b0`) |
| Country CA | Composer 2.5 | done (parallel task; committed in `7efb3b0`) |
| Country AU | Composer 2.5 | done (parallel task; committed in `7efb3b0`) |
| Country NZ | Composer 2.5 | done (parallel task; committed in `7efb3b0`) |
| Country EA | Composer 2.5 | done (parallel task; committed in `7efb3b0`) |
| Country JP | Composer 2.5 | done (parallel task; committed in `7efb3b0`) |
| Integration / QA | Composer 2.5 | done (`27bc50a`, 73 tests at that commit) |
| Bounded correction | Composer 2.5 | done (`7617bdb`, scheduled windows set to live) |
| Independent final review | Grok 4.7 parent (same call) | done, this section |

Parallelism: the six country tasks were launched together after the shared contract was on the branch. They did not run as one sequential generalist.

## Parent review (after `7617bdb`)

Reviewed against the plan in `docs/MACRO_INGESTION_ARCHITECTURE.md` and the inventory in `docs/MACRO_INGESTION_COVERAGE_MATRIX.md`.

### Preserved

- `data/temperature_calibration.json` SHA-256 `f28d68f846c87a8f675398620d59c5a7bc1ab30c8771b316817251a08ba1cb5b` (as_of `2026-09-21`, weights unchanged).
- `overnight-20260923` review-001 `evidence_snapshot.json` SHA-256 `41ad9248149d7f4337f20f8080a63a6932a618fc987f12afe048371d0b7a944b`.
- Canonical trader books and PM books hashes unchanged from the pre-implementation tree.
- ACP 02:05, `scripts/overnight/constants.py` stage clocks, trader seats, PM personas, and funding economics were not edited.
- PR #108 `tests.test_macro_freshness` still passes. The 12-business-day quiet window remains only on that older path.

### Tests run in this review

`python3 -m unittest` on the macro ingestion suite plus `tests.test_macro_freshness`: **75 tests, OK**.

That includes contract, calendar (Sep 23 03:59 vs 04:00 ET), post-freeze path refusal, runner, six country adapter suites, the EA flash miss fixture, and the coverage gate.

### Live smoke (country workers, this session)

| Country | What responded | What did not |
| --- | --- | --- |
| US | FRED 200 for PCEPILFE (2026-07), CPIAUCSL, WPSFD49207, IR, IQ (2026-08) | BLS schedule 403, so no CPI/employment calendar day was pinned. ISM page not found |
| CA | StatCan WDS 200 unemployment 2026-08 6.4% and CPI headline y/y about 3.03 | S&P listing 403. IPPI/RMPI/trade-price/participation vectors left unpinned rather than guessed. CSCE stays `license_gap` |
| AU | ABS labour and PPI topic pages 200. Participation `A84423051C`, PPI `A2314865F`, import `A2295765J`, export `A2294886K` pinned from workbook headers | S&P/Judo listing 403. Domestic final demand `A2304183K` absent from the current key-aggregates workbook. Retail stays ceased after 2025-06 |
| NZ | Stats NZ CPI release 200. BNZ August 2026 PSI PDF 200. Participation `HLFQ.S1E3S`. Local release instants pinned from the fetched schedule excerpt | Overseas trade and business-price URLs 404, so import/export/PPI ids were not invented. ANZ confidence page did not yield a new parseable index |
| EA | Eurostat HICP 200, latest 2026-08 = 3.2. ECB negotiated wages 200, 2026-Q2 = 2.45. PPI key pinned from a live Eurostat response | S&P listing **403**, no primary September flash PDF, no September value stored. Import/export price indexes and participation marked `not_applicable` after the EA21 datasets that were checked |
| JP | e-Stat CPI CSV 200. BOJ CGPI page 200 (HTML index of PDFs only) | CGPI levels not parsed from PDF, so domestic/import/export price rows are `source_failed` rather than filled. S&P Japan listing 403. Tankan and METI IIP unparsed |

Sep 23 Flash Eurozone PMI remains the alert in `data/macro_ingestion/alerts/ea_flash_sep23.json`: schedule `2026-09-23T08:00:00Z` / `04:00` ET, HTTP 403, `value: null`, `cutoff_class: post_freeze`, August final unchanged. That instant is after the 01:50 ET freeze and after the 03:35 ET final delta, so it is not claimed as part of review-001.

### Correction required and made

The first integration workflow ran the new crons offline, which would not have checked primary sources. The correction commit switches scheduled runs to live mode, stores raw bytes, and refuses commits that touch overnight reviews, calibration, temperature scores, temperature history, or PM paths.

### Limitations that remain

- S&P public PDFs are blocked from this environment (HTTP 403). Existing `harvest_*_pmi.py` curl_cffi fallbacks were reused where the country adapter calls them; several live listing checks still ended `license_gap` or `source_failed`. No wire-service PMI number was copied in.
- US and Canada scored series do not yet have publisher calendar dates. Empty dates stay `calendar_unparsed` and do not clear a country risk gate. They are not a 12-business-day guess.
- The live runner appends the new observation store under `data/macro_ingestion/observations/`. It does **not** rewrite `data/temperature_history/*.json` or `data/temperature_scores.json`. Structural gauges therefore stay on the PR #108 FRED/StatCan refresher until a later verified history merge. Post-freeze deltas are the public record for prints after 01:50 ET.
- Google Drive export is documented and marked `not_exported_no_credentials`. No new secret, Supabase migration, or Notion write.
- `baseline_catalog.json` still lists `NZ.Consumer.confidence` twice; the loader keeps the scored row (weight 0.25). Unique catalog size is 119.
