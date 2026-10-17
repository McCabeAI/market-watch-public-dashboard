# Phase 1D — news pipeline contracts

Read-only trace of discovery through public HTML. Later phases must not change these keys, caps' *call sites*, or the files in **Off-limits**. Assessment has to run on the pre-cap set. Today it does not.

Line numbers are from the tree this note was written against.

## 1. Call graph

```
surfaces BLOOMBERG_SURFACE / REUTERS_SURFACE
  live_news.py:22-25
  → acquire_current_news (live_news.py:464)
      → _fetch_source (426) → _parse_bing_rss (305) | _parse_reuters_sitemap (355)
      → _receipt (405) + candidates
  → merge_live_news (721) → _merge_cluster (627) → _cap_items (680)
  → collect_inputs (collect.py:294-358) writes families["news"] on collect.json
  → compute_delta (delta.py:54) may retain Bloomberg (22-38) or swap frozen news (79-84)
  → freeze_snapshot (evidence.py:34) copies families into OVERNIGHT_EVIDENCE_SNAPSHOT (82-113)
  → ACP packet research_supplement is a separate object (review.py:108, provider_stub.py:17)
  → assemble_dataset (assemble.py:44) → overlay_accepted_research (accepted_news.py:33)
  → persist_accepted_public_news_from_assembly (accepted_news.py:125) → build_accepted_public_news (89)
  → apply_overnight_news_refresh (apply_overnight_news_refresh.py:421) then sync_news_summary (sync_news_summary.py:167)
```

Callers of `acquire_current_news`:

- `collect_inputs` when `do_live_news` (`collect.py:293-301`). `do_live_news` is `not offline` unless `acquire_news` is passed, in which case it is `acquire_news and not offline` (`collect.py:293`).
- `compute_delta` only through `collect_inputs` (`delta.py:65-76`). Default `acquire_news` is `(not offline) and stage != "final_delta"`. Final delta does not browse.
- `scripts/market_watch_launch/acquire.py:83` calls `collect_inputs`, not `acquire_current_news`. `offline = mode != "live"` (`acquire.py:71`). Fixture mode never fetches. Live mode does, and copies `families.news.acquisition` onto the stage-02 receipt (`acquire.py:131-133`).
- `scripts/live_news_discovery_smoke.py:14` calls acquire only and prints JSON. No merge, collect, assemble, Pages, or ACP.
- `pipeline.py:111-128` reaches the same collect/delta path. It does not pass `news_fetcher`, so a non-offline run uses `_default_fetcher` (`live_news.py:173`).

Baseline before live merge (`collect.py:227-272`): `load_news_and_research` (`scripts/trader_room/evidence.py:193`) from inbox JSON and `patch_v9/news_rollup.html`, then a newer accepted packet or `data/overnight/accepted_public_news.json` if its cutoff is newer. Live merge replaces `news_items` only when some receipt is `ok` (`collect.py:309-337`). Total failure keeps the baseline and still stores `acquisition`.

`freeze_snapshot` reads `pre_trader_delta.json` families if present, else `collect.json` (`evidence.py:78-82`). It sets `acquisition_allowed: False` (`evidence.py:112`). It does not re-fetch.

Public HTML does **not** read `families.news.items`. `assemble_dataset` sets `agent_research` from `agent_packet.research_supplement` (`assemble.py:159`). `overlay_accepted_research` **replaces** the news family with supplement items and drops `acquisition`, `files`, and `research_supplement` (`accepted_news.py:54-61`). Local dry-run and launch stub supplements start as empty `news` plus AU labor leading rows (`review.py:114-120`, `provider_stub.py:23-29`, `au_labor_handoff.py:125`). They do not copy the live merge. Pages refresh (`deploy-pages.yml`) runs `apply_overnight_news_refresh.py` then `sync_news_summary.py`. `publication_gate` only checks the visible "Last refreshed" date and optional headlines (`publish.py:67-78`, `accepted_news.py:226`).

## 2. Item schema produced today

Discovery candidate, both parsers (`live_news.py:338-351` and `387-400`):

```python
{"published_at", "url", "headline", "summary", "source_name",
 "verification_status", "primary_category", "country_codes",
 "discovery_surface", "distribution_weight"}
```

Bloomberg `verification_status` is `"single_source"`, `distribution_weight` `"high"`, `source_name` `"Bloomberg"`. Reuters summary is the constant `REUTERS_HEADLINE_ONLY` (`live_news.py:91`), `distribution_weight` `"standard"`. Snippet text is collapsed to 400 chars (`_collapse_ws`, `live_news.py:191`).

Merged item (`_merge_cluster`, `live_news.py:662-676`):

```python
{"headline", "url", "summary", "published_at", "source_name",
 "verification_status", "primary_category", "country_codes",
 "source_edges", "id", "market_salience"}
```

`market_salience` is `{score, distribution, components}` (`live_news.py:620-624`). `components` keys: `tier1_relevance`, `transmission`, `novelty`, `distribution_weight`, `recency` (`live_news.py:607-613`). `id` is `news:` + first 16 hex chars of sha256 over sorted edge URLs (`live_news.py:564-567`). Missing `country_codes` defaults to `["US"]` (`live_news.py:670`); live parsers always set the key, so global stories stay `[]`.

Edge (`_edge_from_item`, `live_news.py:552-561`): `source_name`, `url`, `headline`, `published_at`, `snippet`, `distribution_weight`, `discovery_surface`.

`merge_live_news` return (`live_news.py:774-782`):

```python
{"items": merged_items,
 "research_supplement": {
   "summary": None, "news": merged_items,
   "central_bank_research": [], "sources": flat_edges,
   "top_market_driver_candidates": top_3_ids,
   "presentation_caps": {"last_24_hours": 6, "top_market_drivers": 3}}}
```

`collect_inputs` then overwrites `central_bank_research` with the baseline central-bank list (`collect.py:338`).

Acquire return (`live_news.py:526-532`): `mode` (`live`|`offline`), `cutoff`, `partial`, `receipts`, `candidates`.

News family (`_family`, `collect.py:140-151`): `status`, `as_of`, `digest`, `notes`, plus `files`, `items`, and when live: `acquisition`, `research_supplement`.

Do not rename or drop these keys. HTML and acceptance read a subset; extra keys on items are passed through `_normalize_raw_item` (`apply_overnight_news_refresh.py:89`).

## 3. Truncation (the defect)

| Cap | Site | What is dropped | First downstream that sees the short list |
|---|---|---|---|
| per source `[:8]` | `live_news.py:353` and `:402`, after sort by `published_at` desc | qualifying items beyond 8 per surface | `acquire_current_news` `candidates` (`live_news.py:508`, `:519`), then `merge_live_news` via `collect.py:298-301` |
| merged `16` | `_cap_items` (`live_news.py:680-718`), called at `live_news.py:758` | lowest-salience live-only non-Bloomberg, then baseline-only, then lowest score | return value of `merge_live_news`; `collect_inputs` stores it as `families.news.items` (`collect.py:311`) |
| display `[:6]` / `[:3]` / `[:12]` | `_last24_html` `:217`, drivers `:268`, stories `:278` and `:307` | accepted rows outside the HTML windows | built `_site/index.html` only |
| PM compact | `compact_research_supplement` `scripts/pm/review_packets.py:401-404` | news beyond 12, central-bank beyond 8, sources beyond 12 | PM review packets only |

`_text_matches_market_gate` (`live_news.py:227`) and the 24h window run **inside** the parsers **before** `[:8]`. `_apply_salience` runs in `_merge_cluster` **before** `_cap_items`, but only on items that already survived `[:8]`. Rank cannot see a story the parser sliced off. Dropped rows are not returned and are not listed on the receipt.

`result_count` is `len(candidates)` **after** `[:8]` (`live_news.py:443`). It is not the pre-cap qualifying count.

Later phases: run relevance, clustering, novelty, and timestamp checks on the full post-parse set. Apply `[:8]` / `16` / HTML `6`/`3`/`12` only as presentation. Keep the numeric caps until tests and `presentation_caps` are updated together.

## 4. Accepted research schema that must survive

`build_accepted_public_news` (`accepted_news.py:107-116`) top-level keys:

- `schema_version` = `1`
- `type` = `OVERNIGHT_ACCEPTED_PUBLIC_NEWS`
- `overnight_run_id`, `as_of`, `summary`, `news`, `central_bank_research`, `source`

`write_accepted_public_news` rejects any other `type` (`accepted_news.py:120-121`). Path is `data/overnight/accepted_public_news.json` (`accepted_news.py:19`).

Agent-packet supplement, required by `scheduled_output.py:381-389`:

- object `research_supplement`
- `news`, `central_bank_research`, `sources` are lists
- `summary` is a string or null
- `validate_research_supplement_publishability` must pass

Publishability (`research_publishability.py:32-46`): each item needs non-empty `headline` or `title`, and non-empty `summary`. `published_at` absent or `""` is undated and allowed. A non-ISO `published_at` is invalid and fails the build. URL is optional (`apply_overnight_news_refresh.py:76-78`). Central-bank rows may use `title` instead of `headline`.

Tests that lock this:

- `tests/test_accepted_news_architecture.py`: overlay keeps input news unchanged and replaces output `news.items[0].headline` (`:90-110`); packet supplement keys `summary`, `news`, `central_bank_research`, `sources` (`:208-213`); item keys on `FRESH_NEWS_ITEM` are `country_codes`, `headline`, `primary_category`, `published_at`, `source_name`, `summary`, `url` (`:42-49`).
- `tests/test_overnight_news_refresh.py`: urlless news is kept; central-bank `title` without `headline` is kept; undated rows render `data-news-provenance="undated"`; dated rows stay in the rolling window; driver cards 1–3 and stories 1–12 (`apply_overnight_news_refresh.py:403-407`).
- `tests/test_live_news_acquisition.py`: `verification_status`, `source_edges[].source_name`, `market_salience.score`, `id` membership in `top_market_driver_candidates`, `presentation_caps.last_24_hours == 6` and `top_market_drivers == 3` (`:244-245`). Receipt keys `candidate_count`, `result_count`, `status`, `failure`, `checked_at` (`:365-367`).

`verification_status` values the merger emits: `official` (edge `source_name` in `OFFICIAL_SOURCES`, `live_news.py:75-85`), `corroborated` (two publisher families), else a prior status in `{official, corroborated, single_source, unverified}`, else `single_source` (`live_news.py:570-580`). Baseline `dashboard_retained` (`evidence.py:234`) is **not** in that set, so a baseline-only rollup row becomes `single_source` after merge.

## 5. ACP and launch boundaries (off-limits)

This repo discovers public RSS and sitemap XML only (`_default_fetcher`, `live_news.py:173-184`). It must not gain Bloomberg, Reuters, Bing, or other provider credentials, API keys, or paid-search secrets.

Do not edit:

- `docs/ACP_ONE_SHOT_AUTHORITY.md`
- `.github/workflows/` especially `launch-market-watch.yml`, `launch-continuation.yml`, `deploy-pages.yml`, `overnight-pipeline.yml`, `overnight-scheduled-output.yml`, `recover-accepted-finalization.yml`, `reconcile-published-pages.yml`
- `.cursor/` (ACP budget points at `.cursor/commands/overnight-scheduled.md` and `manual-market-watch-review.md`)
- `scripts/market_watch_launch/` (`contract.py`, `acp_handshake.py`, `acquire.py` receipt shape, `freeze.py`, `pages.py`, `provider_stub.py`)
- the external `agent-control-plane` repo
- `scripts/overnight/scheduled_output.py` packet checks, `scripts/overnight/publish.py` gate, `scripts/apply_overnight_news_refresh.py`, `scripts/sync_news_summary.py`
- canonical `data/overnight/accepted_public_news.json`

Stage 02 may keep copying `news_acquisition` onto its receipt. Do not change that receipt's keys (`source`, `checked_at`, `status`, `candidate_count`, `result_count`, `failure`, `surface`). Diagnostics belong beside it, not instead of it.

## 6. Diagnostics gap

An operator can see **discovery transport failure** only.

`_receipt` (`live_news.py:415-423`) is exactly:

```python
{"source", "checked_at", "status", "candidate_count", "result_count", "failure", "surface"}
```

`status` is `ok`, `failed`, or `skipped` (offline). `failure` is `str(exc)` or null. `partial` is true only when one of bloomberg/reuters is `failed` and the other is `ok` (`live_news.py:521-524`). Both failed is `partial: false` with empty candidates; collect keeps the baseline and appends `live news {source} check failed: {failure}` (`collect.py:341-346`).

Pre-freeze Bloomberg loss is visible as note `pre-freeze Bloomberg recheck failed; retained the prior successful acquisition` and `acquisition.delta_retry` (`delta.py:31-37`). Final delta copies the frozen news family and does not record a new browse (`delta.py:79-84`).

Receipts omit, so these are indistinguishable:

- relevance rejection (`_text_matches_market_gate`)
- path drops (`/video`, `/newsletter`, `/podcast`)
- outside the 24h window or unparsed timestamps
- the `[:8]` slice
- `_cap_items` drops
- HTML `[:6]` / `[:3]` / `[:12]`
- ACP overlay replacing frozen live items with a different supplement

`candidate_count` is not "rows fetched". Bing increments it only after a canonical bloomberg.com URL (`live_news.py:328`), **before** path, gate, and window filters. Reuters increments it for every sitemap row with headline and loc (`live_news.py:377`), before the gate. `candidate_count - result_count` mixes excludes, gate rejects, window rejects, and the cap. Golf/noise fixtures depend on that mix (`tests/test_live_news_acquisition.py:152-153` expects `candidate_count == 3`, `result_count == 1`).

## 7. Phase 3 file split (non-overlapping)

Only one phase edits `scripts/overnight/live_news.py`: **3A**. Other phases add new modules and do not patch call sites. 3A wires imports after those modules exist. Do not leave cluster/relevance edits inside `live_news.py` or 3A and 3C will conflict.

| Phase | Owns | Must not edit |
|---|---|---|
| 3A discovery | `scripts/overnight/live_news.py`, new `scripts/overnight/news_sources.py` | relevance, cluster, diagnostics modules; ACP; workflows; HTML refresh |
| 3B relevance | new `scripts/overnight/news_relevance.py` | `live_news.py` (3A moves `_text_matches_market_gate`, `_primary_category`, `attribute_country_codes`, `MARKET_TOKENS` call) |
| 3C cluster | new `scripts/overnight/news_cluster.py` | `live_news.py`. Do **not** keep merge in `live_news.py`. `_tokenize_headline`, `_same_event`, `_merge_cluster`, `_cap_items`, `_apply_salience`, `merge_live_news` move here. 3A keeps `merge_live_news` as a one-line re-export so callers (`collect.py`, tests) stay stable. |
| 3D diagnostics | new `scripts/overnight/news_diagnostics.py` | receipt dict shape. Add a side report; do not remove `_receipt` fields. |
| tests | new `tests/test_news_intelligence.py` | do not weaken existing modules |

`news_sources.py` should hold surface URLs, fetch, and raw parse into **uncapped** records plus per-row drop reasons. `news_relevance.py` should score those records without slicing. `news_cluster.py` should cluster and score, then expose the presentation slice as a separate function from the full assessed list. `news_diagnostics.py` should record counts for: fetch failure, parse drop, relevance reject, window reject, per-source cap, merge cap, presentation cap.

Preserve callable names `acquire_current_news` and `merge_live_news` and their return keys.

### Brittle assertions (existing tests must stay green)

No test asserts the literals 8 or 16. Behavior around them is still locked:

- `tests/test_live_news_acquisition.py:152-153`: Bing fixture `candidate_count == 3`, `result_count == 1` (oil kept; newsletter and video counted then dropped).
- `:244-245`: `presentation_caps` 6 and 3.
- `:109`, `:260`, `:408`: fetcher and stage-02 look for the substring `bing.com`. The surface is `https://www.bing.com/news/search?q=...&format=rss` (`live_news.py:22-24`).
- `MARKET_TOKENS` (`live_news.py:29-67`) plus `NOISE_EXCLUDE` (`:69`): the golf headline is excluded. Widening tokens so that fixture matches will change candidate URLs, salience order, and the Hormuz-outranks-diplomacy test (`:179-207`).
- Exact `country_codes` lists, including `[]` for Brent/Hormuz with no economy alias (`:629-654`, `:709-726`).
- `verification_status` `single_source` vs `corroborated` and Bloomberg-edge preference (`:195-202`, `:292-302`).
- Stage-02 fixture mode must **not** set `details.news_acquisition` (`:380`). Live mode must (`:410-416`).
- HTML refresh: anchors `last24` / `Top Market Drivers`, "Last refreshed {d Mon YYYY}", 1–3 driver cards, 1–12 stories. `sync_news_summary` rewrites counts from `<details class="story"` (`test_sync_news_summary.py`).

New tests go in `tests/test_news_intelligence.py`. Cover pre-cap assessment vs post-cap display with injected fetchers, not the network.

## 8. Shadow cycle (non-publishing)

Use `scripts/live_news_discovery_smoke.py`. It already calls `acquire_current_news(when=now_ny(), offline=False, fetcher=None)` and prints `{mode, partial, cutoff, receipts, candidate_preview}` (`:12-36`). `offline=False` hits the network. Tests must keep passing a `fetcher`.

Do not add a second entry point. Extend this script later (3D owns the report writer; 3A may add the flag only if 3D is not allowed to touch the smoke file — prefer 3D edits the smoke file and leaves `live_news.py` to 3A):

- optional `--report PATH`
- default remains stdout only
- if set, write JSON under that path (a temp file, or an untracked path). Do not write `data/overnight/`, `_site/`, `data/market_watch_launches/`, or `accepted_public_news.json`
- may call `merge_live_news(baseline=[], live_candidates=..., when=now)` so the report shows assessed vs capped rows
- must not call `collect_inputs`, `compute_delta`, `freeze_snapshot`, `assemble_dataset`, `apply_overnight_news_refresh`, Pages, or anything under `scripts/market_watch_launch/`

A shadow run is not a launch and not a collect artifact.
