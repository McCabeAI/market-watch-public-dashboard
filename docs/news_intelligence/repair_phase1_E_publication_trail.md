# Phase 1E — publication trail (acquisition to the final webpage)

Read-only trace, 2026-10-17. Line numbers are from this tree. No source, test, or `data/overnight/accepted_public_news.json` edit.

The acceptance gate is why a qualifying article did or did not reach the **final webpage**, not whether it sits in the research top-24. The review slots are the HTML caps **6 / 3 / 12**. `cluster_and_rank` records `presentation_caps` of 6 and 3 and does not apply them.

What the public dashboard renders is `_site/index.html` after `apply_overnight_news_refresh` and then `sync_news_summary` (`.github/workflows/deploy-pages.yml` 266–321). That HTML is built from `agent_research` on the morning dataset, or from `data/overnight/accepted_public_news.json` when no assembled dataset is loaded. It is not built from `families.news.items` or from `core.news.items`.

## 1. Ordered stages

| # | Stage | Function | Cap | What the next stage receives |
| --- | --- | --- | --- | --- |
| 0 | Baseline seed | `collect_inputs` (`scripts/overnight/collect.py:227-272`) via `load_news_and_research`, then `_current_cycle_accepted_research` (`:80`), `_canonical_public_news_artifact` (`:95`), `_latest_accepted_research` (`:121`) | none | `news_items` before any live fetch. A newer accepted packet replaces static rollup rows. |
| 1 | Fetch | `acquire_current_news` (`scripts/overnight/live_news.py:242`) over `discovery_surfaces` (`scripts/overnight/news_sources.py:61`). Fetch is `_default_fetcher` (`live_news.py:161`). | none | Raw bytes per surface, or a failed receipt. Offline returns no `story_drops` (`live_news.py:267-273`). |
| 2 | Parse filter | `parse_surface` (`news_sources.py:143`) → `_parse_bing_rss` (`:269`), `_parse_reuters_sitemap` (`:332`), `_parse_rss_official` (`:456`) / `_append_official_item` (`:534`) | **24-hour window**, not a count. Path block, host, BoJ/BoE title filter, Reuters `publication_name`. | In-window items plus `dropped`. Recorded reasons: `path_drop`, `window`, `unparsed_date`, `publication_name`, `official_title_filter`. |
| 3 | Recall and safety ceiling | `_apply_recall_and_ceiling` (`live_news.py:215`) calls `recall_candidate` (`scripts/overnight/news_relevance.py:653`) | **60 per surface** (`live_news.py:232-238`), newest first | Survivors become `candidates`. Drops append to `story_drops`: `stage1_recall`, or `discovery_failure` / `safety_ceiling`. |
| 4 | Cross-surface URL dedupe | `acquire_current_news` (`live_news.py:335-343`) | none (first URL wins) | `candidates`. **No `story_drops` row.** |
| 5 | Cluster, score, top-24 | `collect_inputs` calls `merge_live_news` (`collect.py:298-301`) → `cluster_and_rank` (`scripts/overnight/news_cluster.py:236`). Score is `apply_transmission` (`news_relevance.py:665`). | **`_PRESENTATION_CAP = 24`** (`news_cluster.py:27`, slice `:248`) of rows whose disposition is `show` or `assess` | `merged["items"]` and `research_supplement.news`. `diagnostics_rows` mark `relevance_rejection` (suppress / hold-for-review), `shown`, or `presentation_suppression` (`:251-261`). Replaces `news_items` only when some receipt is `ok` (`collect.py:309-311`). Total failure keeps the baseline. |
| 5b | Labels that are not slices | `cluster_and_rank` (`news_cluster.py:269-277`) | `top_market_driver_candidates` is the first **3** salience ids. `presentation_caps` is `{last_24_hours: 6, top_market_drivers: 3}` | Metadata on the collect supplement only. Nothing is cut to 6 or 3 here. The HTML driver rank is a different key (stage 10). |
| 6 | Persist the live pool without the trail | `collect_inputs` (`collect.py:303-352`) | none | `families.news.acquisition` keeps `mode`, `partial`, `cutoff`, `receipts`. It **drops `story_drops`**. `diagnostics_rows` are not stored. `research_supplement` is stored only on the family extra. |
| 7 | Delta may swap the family | `compute_delta` (`scripts/overnight/delta.py:54`). Final delta copies the frozen news family (`:79-84`) and does not browse. Pre-freeze Bloomberg failure can retain the prior family (`:22-38`). | none | The family `assemble_dataset` later reads from `final_delta.json`, else the evidence snapshot, else `collect.json` (`assemble.py:28-34`). |
| 8 | ACP supplement is a different object | Dry-run: `review._research_supplement_for_packet` (`scripts/overnight/review.py:108-120`) starts from **empty `news`** plus AU labor rows (`au_labor_handoff.merge_research_supplement`, `:125`). Launch stub: `provider_stub._research_supplement` (`scripts/market_watch_launch/provider_stub.py:17-29`). A real provider packet is whatever ACP submitted. | none | This list is not `merged["items"]` unless the provider copied it. |
| 9 | Overlay filter | `assemble_dataset` (`scripts/overnight/assemble.py:52-56`) → `overlay_accepted_research` (`scripts/overnight/accepted_news.py:34`) → `public_news_rows` (`news_relevance.py:686`) | **no count cap**. Drops disposition `suppress` and `hold-for-review` (`news_relevance.py:693-694`). `central_bank_research` is not filtered (`accepted_news.py:65-73`). | Kept news replaces `families["news"]` entirely (`accepted_news.py:57-63`), which discards `acquisition` and the collect `research_supplement`. Early return leaves the family unchanged when the packet has no research, or the cutoff is missing or invalid (`accepted_news.py:42-51`). **Dropped rows are not recorded.** |
| 10 | Copy onto the object HTML reads | `assemble_dataset` (`assemble.py:142-147`) | none | When packet `news` is non-empty, `agent_research["news"]` becomes `families.news.items` (the kept overlay list). When packet `news` is empty, `agent_research["news"]` stays empty even if the live top-24 is still on the family. `core.news` is the family; the refresh script does not read it. |
| 11 | Accepted artifact | `persist_accepted_public_news_from_assembly` (`accepted_news.py:127`) → `build_accepted_public_news` (`:91`) → `write_accepted_public_news` (`:121`). Skipped on dry-run (`assemble.py:182`). Requires news-family `status == "fresh"` (`accepted_news.py:137-139`). | none | `data/overnight/accepted_public_news.json`. Envelope keys only: `schema_version`, `type`, `overnight_run_id`, `as_of`, `summary`, `news`, `central_bank_research`, `source` (`accepted_news.py:109-118`). The `news` array is the overlay-kept packet list, still uncapped at 6/3/12. |
| 12 | HTML 6 / 3 / 12 | `apply_overnight_news_refresh` (`scripts/apply_overnight_news_refresh.py:421`). Dataset from `--dataset`, else `latest.json` → `assembled_dataset.json`, else `morning_dataset_from_public_news` (`:37-60`, `accepted_news.py:199`). Partition is `_partition_items` (`:100`). | **6, 3, and 12**, on different orders. See below. | The `last24` and `Top Market Drivers` regions of `_site/index.html`. |
| 13 | Summary chrome | `sync_news_summary` (`scripts/sync_news_summary.py:167`) | validates **1–3** driver cards and **1–12** `<details class="story"` (`:69-70`, `:107-108`, `:131-132`, `:186-187`). Does not choose rows. | Rewrites the front alert, "Last scanned", and `.news-count` from the HTML stage 12 already sliced. |
| 14 | Publish check | `assert_site_news_matches_accepted` (`accepted_news.py:228`), called from `publish.py:50` and `:78`. Pages also requires **any one** accepted headline to appear (`deploy-pages.yml:306-313`). | none | Date match on "Last refreshed". Not slot membership. A story cut by 6/3/12 still passes the gate if some other headline is visible. |

### Stage 12 slot rules (the final webpage)

`_partition_items` (`apply_overnight_news_refresh.py:100-134`) drops a row with no title or no summary (`:87-88`), drops a malformed `published_at` (`:119`), and dedupes on `(url, title)` keeping the newest (`:121-129`). News and `central_bank_research` share one pool. A central-bank row can occupy a slot a news row would have had.

- **Last 24 Hours, cap 6.** `_last24_html` (`:215-217`): dated rows with `cutoff-24h <= published <= cutoff`, already newest-first, then `[:6]`. Order is publication time, not salience and not the HIGH-impact rank. Zero rows render an empty state. The section does not have to contain 6 cards.
- **Top Market Drivers, cap 3.** Dated path: `_dated_rollup_html` (`:263-268`) sorts the **7-day** digest by `(impact == HIGH, published)` descending and takes `[:3]`. Undated-only path: `_undated_block_html` (`:297-302`) uses `(impact == HIGH, title)` and `[:3]`. `_assert_refresh_output` requires 1–3 `driver-card` nodes (`:403-405`). These three are not `top_market_driver_candidates` from stage 5b.
- **Digest stories, cap 12.** Dated path: `digest[:12]` (`:278`) is the **12 newest** in the 7-day window, not the impact rank. A driver can sit outside those 12, and a story in the 12 can miss the driver cards. If the dated digest has fewer than 12 stories, `_rollup_html` (`:370-376`) fills the remainder from undated rows via `_undated_supplement_html` (`:330-342`, hard max 12). Undated-only: `ranked[:12]` (`:307`). If the dated digest already has 12 stories, undated rows are not rendered. A dated row older than 7 days is in neither the digest nor last-24.

`presentation_caps` does not mention 12. The 12 exists only in this file (and as a validator in `sync_news_summary`).

`compact_research_supplement` (`scripts/pm/review_packets.py:401-404`) also slices news to 12. That is the PM review packet, not `_site/index.html`.

### Tests that lock the caps

- Top-24 and the unused 6/3 labels: `tests/test_news_intelligence.py:219-220`, `:302-307`. Same 6/3 labels in `tests/test_live_news_acquisition.py:244-245`.
- Webpage 3 and 12: `tests/test_overnight_news_refresh.py:211-212` (undated fixture renders 3 drivers and 12 stories). Driver and story bounds: `apply_overnight_news_refresh.py:403-407`.
- Chrome rewrites counts, it does not select: `tests/test_sync_news_summary.py`.

## 2. Where diagnostics stop

`docs/NEWS_INTELLIGENCE_REPAIR.md:63` is still true: the smoke report does not see the HTML 6/3/12 slices.

`scripts/live_news_discovery_smoke.py:30-37` does only this:

1. `acquire_current_news`
2. `merge_live_news(baseline=[], live_candidates=candidates, when=when)`
3. `build_report` / `write_report`

It does not call `collect_inputs`, `overlay_accepted_research`, `assemble_dataset`, `persist_accepted_public_news_from_assembly`, `apply_overnight_news_refresh`, or `sync_news_summary`. `baseline=[]` hides stories that enter only as accepted or static baseline (`collect.py:298-300`).

`build_report` (`scripts/overnight/news_diagnostics.py:132-162`) emits four stages:

| Stage | Stop line | Means |
| --- | --- | --- |
| `discovery_failure` | failed receipts (`:62-76`) and `safety_ceiling` (`:85-86`) | Surface transport failure, or the newest-60 ceiling. Headline is null on a receipt row; `url` is the surface. |
| `relevance_rejection` | `story_drops` plus merge rows (`:143-151`, `:255-256`) | Parse filter, `stage1_recall`, or transmission `suppress` / `hold-for-review`. |
| `presentation_suppression` | `news_cluster.py:261` | Scored `show` or `assess`, then cut by the **24** cap. |
| `shown` | `news_cluster.py:259` | In `merged["items"]` (the research top-24). |

`shown` is the research pool. It is not a webpage slot.

`_extra_row_stories` and `_merge_diagnostics_stories` **drop any stage outside those four** (`news_diagnostics.py:87-88`, `:101-102`). A later overlay or display reason cannot be appended to `story_drops` or `diagnostics_rows` and survive `build_report` unless `news_diagnostics.py` grows a separate list.

Rows the report cannot explain even before HTML:

- Bing rows with no canonical URL or a disallowed host never increment `raw_count` and never enter `dropped` (`news_sources.py:293-297`). Reuters rows with no headline or loc (`:357-358`) and official rows with no headline or link (`:478-479`, `:510-511`) are the same.
- Duplicate URLs removed at `live_news.py:335-343`.
- A headline absorbed by `_same_event` inside `_cluster_baseline_live` (`news_cluster.py:209-233`) has no diagnostics row. One merged item is scored.
- `public_news_rows` (`news_relevance.py:693-694`) discards suppress / hold with no row. That is the ACP path. The smoke merge never sees packet rows the live feeds did not return.
- Empty packet `news` leaves the live top-24 off `agent_research` (`assemble.py:146-147`). The webpage list is then empty of those items. No drop row is written.
- Collect does not store `story_drops` or `diagnostics_rows` (`collect.py:303-308`). After a successful overlay, the family no longer carries `acquisition` either (`accepted_news.py:57-63`).

So a story can be `shown` in the shadow report and still miss the webpage, and a story can be absent from the shadow report and still be the one the webpage publishes (ACP packet row, baseline row, or central-bank row).

## 3. Fields a reason trail must carry

Do not add keys to the accepted artifact. `build_accepted_public_news` writes exactly `schema_version`, `type` (`OVERNIGHT_ACCEPTED_PUBLIC_NEWS`), `overnight_run_id`, `as_of`, `summary`, `news`, `central_bank_research`, `source` (`accepted_news.py:109-118`). `write_accepted_public_news` rejects a different `type` (`:122-123`). Do not add a trail field onto objects inside `news`: those objects are stored by `list(news)` and would ship in `data/overnight/accepted_public_news.json`. Kept rows already carry `transmission` because `public_news_rows` returns the scored copy (`news_relevance.py:691-695`). That explains a **kept** row's disposition. It does not list dropped rows, and it does not say which HTML slot was used.

Keep the shadow-report envelope `build_report` already returns: `type` (`NEWS_INTELLIGENCE_SHADOW_REPORT`), `schema_version`, `cutoff`, `partial`, `receipts`, `counts`, `stories` (`news_diagnostics.py:154-162`). Story identity stays `headline`, `url`, `source`, `published_at`, `stage`, `reason` (`StoryRow.as_dict`, `:35-43`). Tests lock those stages (`tests/test_news_intelligence.py:338-404`).

Add a **second list** on that sidecar report, not a new `stories[].stage` and not a new accepted-news key. Name it `publication_rows`. Unknown stages in `stories` are discarded, so overlay and display outcomes do not belong in `counts`.

Each `publication_rows` element:

| Field | Values | Why it is required |
| --- | --- | --- |
| `headline`, `url`, `source`, `published_at` | same types as `StoryRow` | Match a story whose packet `url` is null. |
| `id` | `news:` + 16 hex, or null | Set only after `cluster_and_rank` (`news_cluster.py:68-71`). Null before cluster. |
| `family` | `news` or `central_bank_research` | Both families share the 6/3/12 slots. |
| `outcome` | `not_fetched`, `fetched_filtered`, `scored_suppress`, `research_top_24`, `overlay_drop`, `display_slot_drop`, `published` | The seven explanations. One terminal label. |
| `reason` | existing reason string | Do not invent a parallel reason code. |
| `cap` | `60`, `24`, `6`, `3`, `12`, or null | The numeric cap that decided the outcome. Null when a filter was not a count. |
| `slot` | `last_24_hours`, `top_market_drivers`, `digest_stories`, or null | Which webpage slot. Null before stage 12. |

`published` means the row was emitted into **at least one** slot. A row can be published in `digest_stories` and still be out of the other two. Carry one `publication_rows` element per slot decision (same identity, different `slot`), or the trail cannot say "in the 12, not in the 6, not in the 3".

Map outcomes onto evidence that already exists, and onto the holes that do not:

| Outcome | `reason` to copy | `cap` | Where the row comes from today |
| --- | --- | --- | --- |
| `not_fetched` | receipt `failure`, or no matching headline/url in candidates, `story_drops`, or `diagnostics_rows` | null | Receipt rows only (`news_diagnostics.py:62-76`). A named article that no surface returned has **no row**; the outcome is the absence plus receipt status. Do not synthesize a row per missing headline inside the accepted artifact. |
| `fetched_filtered` | `path_drop`, `window`, `unparsed_date`, `publication_name`, `official_title_filter`, `stage1_recall`, `mechanical_drop` | null, or `60` when `reason` is `safety_ceiling` | `story_drops` (`live_news.py:204-212`, `:299-309`). `safety_ceiling` stays `discovery_failure` in `stories` and is also `fetched_filtered` here because the bytes were parsed. Pre-count skips and URL dedupe still have no source row. |
| `scored_suppress` | transmission `reason_code` (`local_non_g10_macro`, `incidental_link_only`, and the other suppress / hold codes) | null | `diagnostics_rows` when `stage` is `relevance_rejection` and disposition is `suppress` or `hold-for-review` (`news_cluster.py:255-256`). |
| `research_top_24` | same `reason_code` | `24` | `diagnostics_rows` `stage == "shown"` (`news_cluster.py:258-259`). The complement, eligible but outside 24, stays `presentation_suppression` in `stories` and is **not** one of the seven webpage outcomes. |
| `overlay_drop` | same `reason_code` from the `public_news_rows` discard | null | **Not recorded.** Has to be emitted beside `public_news_rows` / `overlay_accepted_research`, into `publication_rows` only. |
| `display_slot_drop` | `outside_24h`, `beyond_6`, `beyond_3`, `outside_7d`, `beyond_12`, `deduped`, `malformed_timestamp`, `missing_title_or_summary`, `dated_digest_full` | `6`, `3`, `12`, or null | **Not recorded.** Has to be emitted from `_partition_items`, `_last24_html`, `_dated_rollup_html`, `_undated_block_html`, `_undated_supplement_html`. |
| `published` | `in_slot` | `6`, `3`, or `12` matching `slot` | **Not recorded.** True only after the HTML string for that slot is built. `sync_news_summary` must not be the writer; it only counts tags. |

`research_top_24` is not `published`. `overlay_drop` is not `scored_suppress` when the row never passed through `cluster_and_rank` (ACP-only headlines). `display_slot_drop` applies only to rows that are in the `agent_research` list the refresh partitions.

Write `publication_rows` only on the shadow report path (`write_report`, `news_diagnostics.py:165-170`) or another path outside `data/overnight/`. Do not pass the list through `build_accepted_public_news`.

## 4. File owners (functions, not a redesign)

Later edits should stay inside the function that already makes that decision. The HTML caps and the top-24 cap are different functions; recording one inside the other will double-count.

| Decision | Owner | Functions | Leave alone |
| --- | --- | --- | --- |
| Surfaces, parse drops, 24h window | `scripts/overnight/news_sources.py` | `discovery_surfaces`, `parse_surface`, `_parse_bing_rss`, `_parse_reuters_sitemap`, `_parse_rss_official`, `_append_official_item` | `live_news.py` acquire loop, cluster, HTML |
| Recall, ceiling of 60, `story_drops`, silent URL dedupe | `scripts/overnight/live_news.py` | `acquire_current_news`, `_apply_recall_and_ceiling`, `_drop_row`, `_receipt` | Receipt keys (`source`, `checked_at`, `status`, `candidate_count`, `result_count`, `failure`, `surface`) |
| Recall predicate and disposition | `scripts/overnight/news_relevance.py` | `recall_candidate`, `apply_transmission`, `score_transmission`, `public_news_rows` | Do not slice 24 or 6/3/12 here. `public_news_rows` is the overlay discard; it currently returns only kept rows. |
| Top-24 and `diagnostics_rows` | `scripts/overnight/news_cluster.py` | `cluster_and_rank`, `merge_live_news`, `_diagnostics_row` | `presentation_caps` and `top_market_driver_candidates` are labels. Do not make them the HTML slice. |
| Four-stage smoke report | `scripts/overnight/news_diagnostics.py` | `StoryRow`, `build_report`, `write_report`, `_extra_row_stories`, `_merge_diagnostics_stories` | New outcomes go in `publication_rows`. Do not push them through `_COUNT_KEYS`. |
| Smoke entry | `scripts/live_news_discovery_smoke.py` | `main` | It stops at acquire + `merge_live_news(baseline=[])` + `build_report`. It does not call collect, assemble, or the refresh. |
| Live pool on the family, trail stripped | `scripts/overnight/collect.py` | `collect_inputs`, `_current_cycle_accepted_research`, `_canonical_public_news_artifact` | Acquisition dict shape. Delta freeze is `scripts/overnight/delta.py` `compute_delta`, `_frozen_news_family`, `_retain_prior_bloomberg_if_recheck_failed`. |
| Packet vs live list | `scripts/overnight/review.py` `_research_supplement_for_packet`; `scripts/market_watch_launch/provider_stub.py` `_research_supplement`; `scripts/macro_ingestion/au_labor_handoff.py` `merge_research_supplement` | those three | Do not copy `merged["items"]` into the stub as part of a diagnostics change. |
| Overlay replace and artifact envelope | `scripts/overnight/accepted_news.py` | `overlay_accepted_research`, `persist_accepted_public_news_from_assembly`, `build_accepted_public_news`, `write_accepted_public_news`, `morning_dataset_from_public_news` | Envelope keys. `assert_site_news_matches_accepted` checks the date, not slots. |
| Which list HTML receives | `scripts/overnight/assemble.py` | `assemble_dataset` (`:52-56`, `:142-147`, `:182-189`) | Do not filter a second time here. |
| Webpage 6 / 3 / 12 | `scripts/apply_overnight_news_refresh.py` | `_partition_items`, `_last24_html`, `_dated_rollup_html`, `_undated_block_html`, `_undated_supplement_html`, `_rollup_html`, `apply_overnight_news_refresh`, `_assert_refresh_output` | This is the only place a display-slot row can be true. |
| Counts on the page | `scripts/sync_news_summary.py` | `sync_news_summary`, `_sync_front_alert`, `_sync_undated_news_summary` | No selection. |
| Not the webpage | `scripts/pm/review_packets.py` `compact_research_supplement` | news `[:12]` for PM packets only | Do not treat it as the dashboard cap. |

`scripts/overnight/publish.py` and `deploy-pages.yml` consume the HTML. They do not choose the 6/3/12 membership. A trail does not need an edit there to be true.
