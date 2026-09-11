# Market Watch — Operating Architecture and Data Pipeline

Last updated: 2026-09-08

This is the canonical technical runbook for the public Market Watch dashboard and its Supabase pilot. It records how the current system is built, what each storage layer owns, the data-source classes in use, the ingestion and verification rules, deployment mechanics, validation gates, and known gaps.

Notion remains the canonical home for durable operating decisions and research state. This document owns technical implementation and rebuild instructions.

## 1. Current system state

The public dashboard is live on GitHub Pages. As of this document:

- v6 provides the 7-day market-news layer, X signal, and 30-day central-bank research feed.
- v7 adds a Last 24 Hours desk summary above the weekly news layer.
- the current news/research collections are curated snapshots, not yet automatically refreshed.
- the Supabase pilot is active in project `market-watch-dev`, private schema `market_watch`.
- Supabase currently stores normalized operational feed state and provenance; it is not the canonical raw-evidence archive or canonical macro time-series warehouse.
- X follow-list ingestion is prepared but waiting for Kevin's requested X data archive.
- public dashboard temperature labels remain prototype/illustrative until the research architecture establishes canonical baselines.

## 2. Source-of-truth ownership

| State | Canonical owner | Notes |
| --- | --- | --- |
| Implementation, deployment workflow, schema migrations | GitHub | This repository is technical truth. |
| Operating rules, research memory, country conclusions, project state | Notion | Market Watch Operating Hub and linked operating pages. |
| Raw files, source documents, transcripts, exports, X archive ZIP | Google Drive | Preserve source artifacts and vintages where revisions matter. |
| Canonical normalized numeric history during pilot | Drive-hosted spreadsheets/workbooks | Do not silently create a competing numeric history in Supabase. |
| Normalized news/research/X feed state, provenance edges, ingest-run state | Supabase `market-watch-dev` | Derived/operational pilot layer only. |
| Live external facts | Original authority | Central banks, statistical agencies, media, X, etc. remain authoritative for their own live content. |

Do not create a second canonical copy of any state without an explicit decision.

## 3. Public dashboard architecture

Repository: `McCabeAI/market-watch-public-dashboard`

Permanent public URL:

`https://mccabeai.github.io/market-watch-public-dashboard/`

Current deploy path:

1. GitHub Actions triggers on every push to `main` or manual workflow dispatch.
2. The workflow reconstructs the known-good v6 HTML from `payload_v6/part*.b64`.
3. It verifies the v6 base by exact byte count and SHA-256.
4. It applies the v7 Last 24 Hours CSS and HTML patches from `patch_v7/`.
5. It verifies the final v7 HTML by exact byte count and SHA-256.
6. Only then is `_site/index.html` uploaded as the GitHub Pages artifact.
7. The deploy job publishes that artifact to GitHub Pages.

Current validation constants in `.github/workflows/deploy-pages.yml`:

- v6 HTML bytes: `134496`
- v6 SHA-256: `2c68341978db2ccc8efdd8f1af7bee4e105c89427f741bb10e7747cb98dde917`
- v7 HTML bytes: `141174`
- v7 SHA-256: `c0c7e973e23b04ada07baac7636fa4fb0e424c0e0d5def2e4ff5305f718f7952`

The unusual base64/patched deployment exists because large binary/text transfer through the connector was unreliable during the build. It is a known-good recovery-safe path, not the desired long-run content-authoring method.

## 4. Dashboard information hierarchy

News & Research is ordered for decision speed:

1. Last 24 Hours desk summary
2. Top Market Drivers
3. 7-Day Quick Digest
4. X Signal
5. 30-Day Central-Bank Research

The intent is to separate three different information speeds:

- immediate market-moving developments;
- the broader one-week macro/news tape;
- slower research and methodology.

X is kept distinct from confirmed news so unverified social signal is not visually or analytically merged with established reporting.

## 5. Data-source universe

### 5.1 Official macro and central-bank sources

Prefer first-party publication pages, releases, speeches, research pages, statistical tables, and official social accounts.

Current central-bank/research universe includes:

- Federal Reserve Board
- all 12 Federal Reserve Banks: New York, Boston, Philadelphia, Cleveland, Richmond, Atlanta, Chicago, St. Louis, Minneapolis, Kansas City, Dallas, San Francisco
- Bank of Canada
- Reserve Bank of Australia
- Reserve Bank of New Zealand
- Bank of England
- European Central Bank
- Bank of Japan
- Swiss National Bank
- Norges Bank
- Sveriges Riksbank

Official statistical agencies and first-party government releases are preferred for macro data. The public dashboard currently uses public official macro releases for the US, Canada, Australia, and New Zealand and related G10 context.

### 5.2 Financial and mainstream news

The news layer searches established financial and mainstream media for material developments involving:

- central banks and monetary-policy expectations;
- national leaders and finance ministries;
- inflation, employment, wages, GDP/growth, consumption, trade and tariffs;
- fiscal policy and elections when economically relevant;
- commodities, especially oil and other globally important inflation/growth inputs;
- rates, FX, credit, liquidity and broad risk repricing;
- geopolitical developments with a credible macro or market transmission channel.

Reuters is a current primary news source in the Last 24 Hours layer. Other established financial/mainstream outlets may be included when useful. Each normalized feed item should retain its canonical source URL and named source; a source should not be inferred or hidden behind an unattributed summary.

### 5.3 X / social signal

Current state:

- public X posts can be searched and used;
- official central-bank, government, leader and institutional accounts are preferred;
- media or commentator X posts should not be treated as confirmed news solely because they were posted on X;
- media/social claims should be corroborated against an underlying report or another reliable source before being promoted as confirmed news.

Planned personalized source universe:

- Kevin's account: `@McCabe_N`;
- exact Following membership will come from the requested X data archive rather than public-web inference;
- the raw X archive belongs in Drive;
- a hashed/vintaged snapshot and resolved account universe belong in Supabase.

### 5.4 Paid/private research

Paid written research, including the user's priority sources such as Bob Elliott/Pinebrook and David's Signal and Noise work, is not a public dashboard source unless publication rights permit it.

Raw paid-source evidence should remain in the private evidence architecture. Durable methodology and conclusions may be promoted to Notion with provenance. Do not reconstruct or republish paywalled material publicly.

## 6. Time windows

Current dashboard windows:

- Last 24 Hours: rolling one-day desk summary.
- 7-Day Quick Digest: material market-moving news from the previous week.
- Central-Bank Research: strict rolling 30-day publication window.
- `NEW` research designation: currently based on a recent-publication cutoff within that 30-day scan; this should become computed from refresh time when automation is built.

A publication outside the stated window must be excluded even if analytically useful. Example from the build: the NY Fed tariff pass-through paper dated 2026-08-01 was removed from the strict Aug 10–Sep 8 30-day window.

## 7. Normalization and analytical rules

Every normalized news/research/X item should preserve enough structure to support filtering and auditability.

Core fields in Supabase `market_watch.content_items` include:

- `content_type`: `news`, `research`, or `x_post`
- headline
- summary
- market read
- publication and observation timestamps
- country codes
- primary and secondary categories
- institution / author / account
- source name
- canonical URL / external ID
- unique content fingerprint
- verification status
- market-impact rank
- top-driver / last-24-hours flags
- raw-evidence pointer when applicable
- lineage JSON

Verification states:

- `official`: direct official source;
- `corroborated`: supported by multiple/underlying reliable sources;
- `single_source`: credible source but not independently corroborated;
- `unverified`: retained as signal only and must not be presented as established fact.

Current impact labels are `high`, `medium`, `low`.

## 8. Macro categorization

Primary/secondary categories are intended to make the feed queryable rather than force every story into one narrow bucket. Current categories include:

- jobs / labor
- wages
- inflation
- GDP / growth
- consumer
- monetary policy
- rates / r-star / expectations
- FX
- trade / tariffs
- fiscal policy
- credit
- liquidity
- financial conditions
- productivity / AI
- commodities / energy
- risk / cross-asset

Country and category tags should reflect the actual transmission channel, not merely the country where an article was published.

## 9. News ranking logic

Current ranking is analyst/agent judgment, not a deterministic model. The hierarchy is:

1. Does this materially change the expected policy path, growth/inflation trajectory, risk premium, or cross-asset transmission?
2. Is it fresh relative to what the market already knew?
3. Is the source sufficiently reliable for the confidence assigned?
4. Is the item relevant to G10 rates/FX, with emphasis on CAD, AUD and NZD and US as the benchmark?
5. Is it distinct from existing items, or merely repetition?

Top Market Drivers should contain only the small set most likely to matter to price formation. The 7-day digest can be broader. The Last 24 Hours layer should synthesize what changed, not repeat the weekly chronology verbatim.

## 10. Supabase pilot

Project: `market-watch-dev`

Schema: `market_watch`

Migrations:

- `supabase/migrations/20260908233336_create_market_watch_operational_store.sql`
- `supabase/migrations/20260908233527_add_operational_store_fk_indexes.sql`

Tables:

- `ingest_runs` — durable status and audit trail for refresh/import jobs
- `content_items` — normalized news/research/X items
- `content_evidence` — source/provenance/corroboration edges
- `x_follow_snapshots` — vintaged X Following archive imports
- `x_accounts` — resolved/classified X accounts
- `x_follow_memberships` — exact account membership for each snapshot

Current seeded state at initial pilot creation:

- one completed bootstrap ingest run;
- six Last 24 Hours news items;
- six evidence/provenance records;
- no X follow snapshot yet.

### Security

The pilot is deliberately private:

- schema is not public-facing;
- RLS is enabled on all six tables;
- `anon` and `authenticated` have no schema usage or table grants;
- only privileged server-side/service-role access is currently granted;
- the public dashboard does not query Supabase directly yet.

Do not expose the operational tables to the browser. When the dashboard becomes data-driven, create the minimum narrow read surface required and apply an explicit authorization/public-data policy.

## 11. X archive import runbook

When Kevin uploads the X archive:

1. Save the unchanged archive ZIP to the designated Market Watch raw-evidence location in Google Drive.
2. Calculate and retain the archive SHA-256.
3. Identify the archive's Following/follow-list file(s).
4. Start an `x_archive_import` row in `market_watch.ingest_runs`.
5. Parse the exact account membership without inferring missing follows from public search.
6. Insert one `x_follow_snapshots` record with archive filename, SHA, as-of time and Drive pointer.
7. Upsert resolved accounts into `x_accounts` using X user ID when available; preserve handles/display names when resolvable.
8. Insert every exact membership into `x_follow_memberships`, preserving the raw archive entry in `raw_entry` for auditability.
9. Classify accounts by macro relevance and institution type: central bank, government, journalist, economist, research, market, commodity, politics, other.
10. Mark only suitable accounts as `is_market_watch_source = true`.
11. Complete the ingest run with counts and any unresolved IDs.
12. Validate snapshot account count against the parsed source file and report unresolved account resolution separately.

Never replace the raw archive with the normalized database representation.

## 12. Current manual refresh runbook

Until automated ingestion exists:

1. Define the exact time window.
2. Search official sources, financial/mainstream media and public X for relevant developments.
3. Prefer first-party sources where available.
4. Deduplicate repeated coverage of the same event.
5. Separate confirmed reporting from social signal.
6. Assign country, primary category, secondary categories, verification state and market-impact rank.
7. Write a concise factual summary and a separate market read.
8. Preserve canonical URLs/provenance.
9. Populate/update the relevant dashboard section.
10. Write normalized operational rows to Supabase for the adopted feed workflow.
11. Run deterministic validation before deployment.
12. Deploy through GitHub Actions only after the artifact hash/content gate passes.
13. Verify the actual deployed artifact when practical, not only the workflow status.
14. Update the Notion Project State capsule only if project state materially changed.

## 13. Planned automated refresh flow

Not implemented yet. The intended direction is:

source discovery -> fetch/normalize -> deduplicate -> classify -> corroborate/verify -> rank -> write Supabase operational state -> generate public read model -> build dashboard -> validate -> deploy

Automation must preserve the same epistemic separation now enforced manually:

- official source vs media reporting vs X signal;
- fact vs market interpretation;
- publication time vs observation/ingestion time;
- source provenance and reproducibility;
- canonical raw evidence outside Supabase where required.

Do not call the automated refresh complete until the full public artifact is validated end to end.

## 14. Research architecture boundary

The public news/research dashboard is not the Market Watch analytical research engine.

The separate research architecture remains:

Ivory evidence -> country/thematic experts -> validator when required -> ingest/digest/compress

The dashboard may surface public information from that ecosystem, but it should not silently turn prototype dashboard labels into canonical country state. Canonical temperature/direction belongs to the governed research process.

## 15. Validation and failure behavior

Deployment should fail closed.

Current controls include:

- exact payload/base byte counts;
- gzip integrity checks where applicable;
- exact SHA-256 checks for the reconstructed HTML;
- explicit build failure when patch anchors are not unique or the v7 patch is already present;
- GitHub Pages deploy only after the build job succeeds.

Database validation performed at pilot creation included:

- schema/table inspection;
- test write/read/delete cycle;
- verification of zero `anon`/`authenticated` schema usage and table grants;
- Supabase security and performance advisor review;
- indexes added for initially flagged foreign keys.

Informational advisor warnings about RLS enabled with no policy are intentional under the current deny-by-default private-schema design.

## 16. Recovery and rollback

Dashboard:

- Git history is the rollback mechanism.
- v6 payload remains in the repository as a known-good base.
- v7 is applied as a small deterministic patch, so reverting the patch/build commit restores the previous known-good artifact.
- never delete known-good payloads while a new content-generation path is still being proven.

Supabase:

- schema changes must be represented as migrations in GitHub;
- use forward migrations for changes to an already-applied remote schema;
- raw evidence is recoverable from Drive and should not depend on the database;
- do not treat current Supabase data as the only copy of source evidence.

## 17. Known gaps / next work

- News and central-bank feeds are still snapshots, not scheduled refreshes.
- X Following personalization is waiting for the X archive.
- The public dashboard does not yet consume a narrow read model from Supabase.
- The repo's current compressed-payload/patch authoring path is reliable but awkward; a normal source/generator pipeline should replace it once automation is built and validated.
- Current source discovery is not yet represented as a machine-maintained source registry in code. Do not create one until the refresh workflow is actively using it.
- Market tape remains a public snapshot, not a licensed live feed.

## 18. Repo map

- `.github/workflows/deploy-pages.yml` — exact Pages build and validation gate
- `payload_v6/` — known-good compressed/base64 v6 dashboard base
- `patch_v7/` — Last 24 Hours v7 patch
- `supabase/migrations/` — version-controlled database schema changes
- `docs/OPERATING_ARCHITECTURE.md` — this canonical technical runbook

When implementation changes materially, update this document in the same commit or immediately adjacent commit. Do not rely on chat history as the technical record.
