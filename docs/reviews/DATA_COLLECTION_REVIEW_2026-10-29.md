# Market Watch collection review — 2026-10-29

Review only. No production configuration, code, score weights, trader behavior, schedules, or ACP settings changed.

## Recommendation

Optimize for current, usable research observations. Repair acquisition and reuse successful collection paths before adding coverage. Keep checks for wrong series, units, reference periods, transformations, and corrupt responses. Remove non-material metadata and unrelated-source failures from the path that makes valid research data available.

The existing system already supports partial publication and carried-forward observations. Extend that behavior selectively rather than adding another validation framework or rebuilding the application.

## Evidence reviewed

Repository main at commit 585255ecb895018a3fbabd98592aa4ecc5f83dbf. Latest inspected launch: mwl-20261029T082431Z-39bb88f4. Compared eight launch source matrices from October 20–29, including October 23's evening launch.

Read current Global Operating Rules, AI Writing Avoid List, Market Watch Operating Hub, Researcher Data Contract, and Agent Contracts. The hub's September operational state is historical; current code and October artifacts take precedence.

Implementation inspected: macro ingestion runner, country adapters, calendar, source-health carry-forward, series preflight, launch ingest/acquire/quality gate, overnight collection, PRIMA producer sources, and macro/market-state workflows. This is a code and recorded-run review, not a live retest of every publisher or an independent verification of every stored economic value.

## What is actually failing

### 1. Repeated budget starvation

The latest merged source matrix contains 224 entries: 115 source_failed, 88 new_observation, 6 license_gap, 12 not_applicable, 2 calendar_unparsed, and 1 checked_unchanged. These are catalog/diagnostic entries, including aliases and a composite AU labor diagnostic; they are not 224 distinct expected releases.

Seventy US entries are budget_deferred. That count recurs in each of the eight reviewed runs. The latest US subset has 93 entries: 89 source_failed, 3 new_observation, and 1 license_gap. Fifteen of the failures record timeouts; two record ISM HTTP 404s.

The runner processes series serially within each country, with scored series ahead of most context and alphabetical ordering within lanes. Launch ingestion gives each country 180 seconds on the first pass and 120 seconds on the retry pass. Repeated slow FRED requests exhaust the US budget before most employment context is attempted. Repeating the same order perpetuates the gap.

Repair:
- Fetch a source document/batch once and fan its observations out to the relevant series. Reuse existing ABS and US employment caches.
- Use bounded parallelism across independent sources/countries, with per-host limits and serialized writes to shared stores.
- After repeated host failures, stop spending that pass's budget on the same host; try the mapped alternative or defer it for later.
- Prioritize due releases and previously deferred items, while reserving capacity for core series.
- Retry failed fetch groups only. Do not repeat a full successful collection.

### 2. Specific adapters are unfinished or broken

Canada's general collector reports unpinned vectors for IPPI, RMPI, participation, and import/export price indexes. PRIMA already contains explicit IPPI/RMPI vector mappings and successfully holds September producer-price observations in the same October 29 market packet. That is an integration gap, not a need to invent another source.

NZ records five empty parses across GDP, income, retail, spending, and wages, plus three 404s for price-index context. NZ CPI still comes from a June-quarter URL and yields Q2 observations after the configured October 22 release date. It is blocked downstream. Fix discovery and the parser rather than removing that block and declaring Q2 current.

AU's domestic-final-demand series is absent from the selected workbook; Westpac confidence explicitly has no primary adapter; SEEK fails period/release-date extraction. Jobs and Skills Australia timeouts recur. JP includes deliberately unimplemented PDF/ZIP parsers.

Repair order: US core macro and starved labor coverage; NZ release discovery/parsers; Canada reuse and missing mappings; AU demand/confidence/labor-leading sources; then secondary EA/JP gaps. Avoid adding more catalog placeholders while these are unresolved.

### 3. Source restrictions unnecessarily eliminate usable research

The NZ rates collector explicitly refuses third-party/vendor feeds after official RBNZ workbook and HTML routes fail. The current packet reports NZ rates unavailable. ESTR settlements and CME positioning also have access failures. Several PMI paths require primary PDFs even when other attributable reporting might provide the actual release.

Adopt explicit fallback maps:
1. Preferred official API/file.
2. Alternate official endpoint, release page, or publisher-hosted document.
3. A preselected reputable distributor carrying the same observation, or clearly attributed reporting of the exact release.
4. Last good observation with its actual date.

An alternate distributor of the identical series is not automatically a proxy. A different instrument, maturity, definition, seasonal basis, or economic concept is not an interchangeable fallback. Make one-time source mapping checks and retain the source/date; do not require routine double sourcing of every successful observation.

For data genuinely unavailable without credentials, choose a supported paid/licensed feed if justified, or explicitly reduce coverage. Do not keep probing the same blocked endpoint indefinitely. No specific vendor has been validated or selected in this review.

### 4. Freshness can be both noisy and falsely reassuring

Of 66 scored catalog entries, 49 have no release dates. calendar.release_due returns false for an absent/unparsed calendar. The source-health layer can then carry old observations as not due. The latest gate calls the US scored state ok while carrying July core PCE/income/spending and August ISM observations through repeated failed fetches.

Conversely, the classifier can label successfully retrieved data calendar_unparsed when there is no schedule. Missing scheduling metadata should not disqualify an economically valid observation.

Repair:
- Keep observation period, successful source check, and expected next release distinct.
- Discover releases from current publisher indexes; avoid hard-coded vintage URLs.
- Use a lightweight cadence-based age backstop when an exact calendar is unavailable. It should prompt another source attempt or identify an older release, not invalidate a correctly identified value.
- Treat recurring timeouts/404s as persistent repair needs, not indefinitely transient.
- Preserve and display valid previous observations. Never refresh their observation date merely because the process ran.

### 5. Collection state is recreated and diagnostics disagree

Each launch creates a new observations directory and does not seed it from the previous launch's observations. That causes identical observations to be classified as new to that store. For example, the October 28 and 29 NZ stores share six identical series/period/transform/value/raw-hash tuples. Repeated new_observation counts therefore do not measure fresh economic releases.

The retry call overwrites ingestion/health/latest.json with only its retry subset. On October 29 it contains 89 failures, while the merged source matrix contains 224 entries and many successes.

Repair:
- Reuse the existing persistent observation state between launches; freeze a snapshot for traders.
- Compare period/value against prior observations before labeling an economic update.
- Write the merged final collection outcome to the existing health surface after retries.
- Reuse raw artifacts by content hash when possible. Avoid a separate monitoring system or competing warehouse.

### 6. Refresh frequency and CI are coupled to the wrong work

Macro ingestion is manual-only. Daily Market State is also manual/PR driven. A full trader cycle is unnecessary to recover a late release.

Keep trader/provider launches manual. Add a cheap data-only catch-up path using the existing collectors that refreshes research data and pages without rerunning traders or rewriting their frozen evidence. Optional release-window scheduling can be agreed separately; this review enables no schedule.

CI also has avoidable external dependencies. daily-market-state.yml runs live-source smoke before generation, and generation runs for PR events with hard assertions on selected live sources. macro-ingestion.yml's PR tests apply broadly via paths-ignore.

Use focused offline parser/calculation tests on affected PRs. Exercise live endpoints in the actual collection run or a relevant integration check. Publisher downtime should produce a source gap, not veto unrelated code changes. No new workflows, matrices, required checks, or validator agents are needed for this repair.

## Research acceptance policy proposed

Accept a numeric observation when its source, identity, value, reference period, units, and transformation are clear. A missing precise publication timestamp, unavailable consensus, absent revision label, missing future calendar, or temporary failure to re-download an unchanged observation should not hide it.

Preserve actual errors: wrong series, wrong units, wrong period, HTML challenge mistaken for data, and incorrect transformations. Restrict only the affected observation/calculation. In particular, a weighted-series mismatch currently blocks acquisition for the entire country; valid unrelated source retrieval should continue.

Research display can show dated older observations. Freshness needed to mark paper positions or add risk remains a separate use-specific decision. Simplifying research collection is not permission to invent marks or substitute different instruments.

Use short user-facing states: current release; previous release retained; unavailable. Explain only gaps that materially change interpretation. Keep transport/parser diagnostics in existing technical logs.

## Smallest useful delivery plan

1. Fix US request/budget behavior and core fallback mappings; repair NZ discovery/parsers; connect Canada's working producer collectors.
2. Reuse persistent observations, merge retry results, and make release discovery/cadence handling practical.
3. Simplify acceptance and PR CI; expose data-only catch-up through existing project controls.
4. Evaluate optional automated release-window pulls after the repaired manual collection is demonstrated.

This is a bounded multi-file repair. Main maintenance burden is publisher HTML/PDF changes and genuine access restrictions. Prefer stable machine-readable sources and existing collectors; no database migration or ACP redesign is needed.

## Acceptance without a new audit layer

Replay the observed failure cases with focused existing tests, run one live end-to-end collection, and inspect the resulting data and research page. Specifically:
- A failed FRED host does not prevent unrelated US labor sources from receiving an attempt.
- NZ resolves the current publisher release and preserves the correct period.
- Canada general macro and PRIMA consume the same mapped producer observations.
- An unchanged observation is not counted as a new economic release.
- A metadata-only problem does not hide a usable value.
- A true series/unit/period mismatch remains excluded.
- A data-only refresh leaves trader evidence snapshots unchanged.

Measure usable current coverage among the expected priority series, release-to-availability delay, and repeated missed attempts using the existing matrix. Exclude aliases and nonexistent equivalents from the denominator. Do not use passing CI or raw new_observation counts as the success metric.
