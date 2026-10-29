# Independent-review remediation — 2026-10-29

**Parent verdict: PASS.** No merge, deploy, or schedule change. Code tip before this note: `e5ebc0c2`. Branch `cursor/reliable-usable-market-watch-collection-grok-4-7-composer-graph-e865`.

## What the review found, and what changed

The data-only catch-up was rendering `country_detail_sections.json` from the repository projection. It now passes the output observation directory into `render_dashboard_sections`. A same-series store row (catalog `series_id`, transformation, and units when both sides have them) overlays that series in the research HTML. Frozen evidence and score files are not written. `promote_stores` is not called on this path.

Normal launch copies non-empty `us`/`ca`/`au`/`nz` (and `ea` when the launch wrote it) observation files back to `data/macro_ingestion/observations`. An empty launch file does not replace a non-empty store. The next launch seeds those files, so a repeated identical point is `checked_unchanged`. The repo still ships only `ea.json`; the live dump was not committed.

A deferred FRED host is not called again in that pass. A series with a same-series BLS mapping is admitted on the BLS host (`scheduler_skip_fred_primary`). Series with no mapping stay `host_deferred`. Protected labor retries run, then the budget is read again before lower-tier retries. That is why `test_protected_budget_retry_ordering` now keeps the unrelated series at one call.

A failed fetch that still has a verified same-series prior is research status "previous release retained" with that period. Cadence backstop and `release_due` still block new risk and marks. A mismatched series or transformation is not attached.

The five Canada failures were stale expectations. Committed Consumer retail is `as_of` 2026-08, and July/August are already in history, so those merges append nothing. October lineage appends the three CPI prints only. History and scores were not rolled back.

## Invocations

Seven accepted invocations. One Grok 4.7 parent. Every other node was Composer 2.5. No node used a second repair. No other model was used.

| Node | Role | Result |
| --- | --- | --- |
| P | Plan, ownership, final review | PASS |
| A | Catch-up projection and launch store promotion | `a82189ec` |
| B | FRED alternate admission and protected retry order | `c330954d` |
| C | Previous-release status and Canada expectations | `bc6a1ba0` |
| I | Merge and full macro suite, one live render | `6155e6d0`, `133b0ad6`, `e5ebc0c2` |
| V1 | Series identity, projection, persistence | PASS |
| V2 | Retry, freshness, former CI failures, frozen evidence | PASS |

## Proof

Isolated live command, exit 0, output only under `/tmp/mw-live-catchup` (not committed):

`python -m scripts.macro_ingestion.cli --data-only-catch-up --mode live --country US,CA,AU,NZ --output-dir /tmp/mw-live-catchup`

Stored observation: US `PAYEMS`, period `2026-09`, value `29.0`, transformation `mm_change_thousands_sa`.

Rendered US section: `Nonfarm payrolls rose 29k in Sep 2026, after +162k in Aug 2026.`

Evidence `data/overnight/runs/overnight-20260923/reviews/review-001/evidence_snapshot.json` SHA256 before and after: `41ad9248149d7f4337f20f8080a63a6932a618fc987f12afe048371d0b7a944b`.

Health rows for that run: 134 `new_observation`, 25 `source_failed`, 10 `license_gap`, 5 `not_applicable`, 1 `calendar_unparsed`, 1 `checked_unchanged`. The 134 rows are first inserts into an empty output directory, not 134 new releases.

Cross-launch identity: `test_launch_seed_then_repeat_fetch_is_checked_unchanged` and `test_seed_store_classifies_checked_unchanged` passed. A seeded prior point stays `checked_unchanged` on the next identical fetch.

## Tests

Macro-ingestion discovery: 341 passed. The rest of the macro-ingestion CI modules plus source-health: 162 passed, 1 skipped. The six former failures in run 40867942515 all passed. V1 ran 32 targeted tests, V2 ran the retry, freshness, and former-failure tests. No new workflow or required check was added.

## Remaining limits

BEA and other FRED series with no BLS mapping still defer when FRED is down. Licensed and unpinned series are unchanged. Euro area and Japan were not expanded. This live run did not fill the committed observation store; a normal launch does that promotion. Research can show a dated previous print while marks stay blocked. No schedule was enabled and nothing was deployed.
