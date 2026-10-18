# News intelligence follow-up review

Third pass (2026-10-18): BoC/RBA RSS 1.0 parsing, the RBNZ RSS fallback, and the CNBC investing RSS are recorded in `docs/news_intelligence/repair_third_pass.md`. Gate 1 in this file stays unresolved. The limits below that say BoC/RBA parse as zero items, and that RBNZ has no verified feed, are the prior pass. They are superseded by that note.

Branch: `cursor/market-watch-g10-news-intelligence-overhaul-six-phase-grok-composer-graph-bbf3`. Pull request: https://github.com/McCabeAI/market-watch-public-dashboard/pull/215. Not merged. Not deployed. `data/overnight/accepted_public_news.json` was not modified.

Focused tests, 2026-10-17:

```bash
PYTHONPATH=. python3 -m unittest \
  tests.test_news_intelligence \
  tests.test_live_news_acquisition \
  tests.test_accepted_news_architecture \
  tests.test_overnight_news_refresh \
  tests.test_sync_news_summary \
  tests.test_news_sources_repair \
  tests.test_news_cluster_repair \
  tests.test_news_publication_trail
```

71 tests, OK. No full Market Watch run.

## Acceptance gates

| Gate | Result |
| --- | --- |
| 1. CoreWeave 15 Oct URL discoverable from an implemented source during `[2026-10-15T16:52:16Z, 2026-10-16T16:52:16Z]` | **UNRESOLVED BLOCKER** |
| 2. Vietnam GDP and India trade gap rejected; India oil-supply shock retained | **PASS** |
| 3. BoJ/BoE/RBNZ releases not discarded only by a title filter | **PARTIAL.** BoJ/BoE phrases are kept and scored. RBNZ has no verified feed |
| 4. Reason trail reaches the final 6/3/12 webpage slots | **PASS** for `explain_display_slots`. The smoke report does not claim those slots |
| 5. Distinct events stay in separate clusters | **PASS** for the targeted pairs. Same-facet residual remains |
| 6. News engine only | **PASS** |

## Gate 1 evidence

Primary article, HTTP 200 in phase 1A: https://www.cnbc.com/2026/10/15/coreweave-credit-default-swaps-hit-distress-levels-as-investors-sour-on-ai-debt.html. `article:published_time` `2026-10-15T16:52:16Z`.

Replay at `2026-10-17T23:15:50Z` (`docs/news_intelligence/repair_phase4_replay.md`):

- Live `https://www.cnbc.com/sitemap_news.xml` was HTTP 200, 84 news URLs. The target URL was absent. Oldest date in that body was `2026-10-15T23:49:14Z`, about seven hours after publication.
- Parsing that same body at a cutoff inside the article's window (`2026-10-16T12:00:00Z`) kept 21 rows and still did not contain the URL. That is today's sitemap read with an old clock, not an archived sitemap.
- Wayback CDX for `cnbc.com/sitemap_news.xml` from 20261015 through 20261017 was `[]`.
- Wayback captured the article HTML at `20261015165635` and `20261016014202`. Those captures show the page existed. They are not a discovery feed.
- Bing RSS for `cnbc_credit`, extended `reuters_credit`, and `bloomberg_credit` did not return the URL (1, 5, and 0 items).

`tests/test_news_sources_repair.py` feeds a fixture sitemap. That proves the parser. It does not prove the URL was listed during the 24-hour window.

What did ship: a non-required CNBC news sitemap and an optional Bing `site:cnbc.com` credit query. Host `cnbc.com` can become a candidate. `REQUIRED_SOURCES` is still only `bloomberg` and `reuters`, so `partial` is unchanged. At the replay cutoff the parser kept 13 of 84 current sitemap rows. None was the 15 Oct CDS URL. Stage-1 recall still has to drop lifestyle rows the sitemap includes.

A later CNBC row, "Why did CoreWeave stock get crushed this week? Look to this corner of the debt market for clues" (`2026-10-16T20:33:55Z`), is a different URL and is after the window.

## Gate 2

`_subject_rule` suppresses Vietnam/Vietnamese plus `gdp`, India/Indian plus trade deficit, trade gap, or import bill, and Indonesia plus fire, only when `_transmission_role` is false. There is no country deny-list.

Executed after the reviewer fix:

| Text | Result |
| --- | --- |
| Vietnam GDP headline plus a parliament summary | `suppress` / `local_non_g10_macro`, recall false |
| India trade-gap fixture, summary uses oil as the import bill | `suppress` / `incidental_link_only` |
| "Indian trade deficit widened on the import bill" plus an oil-price summary | `suppress` / `incidental_link_only` |
| "India oil-export halt widens the trade deficit" plus a crude-export summary | `assess` / `oil_supply_shock`, kept |
| Same export halt clustered under a newer Bloomberg trade-gap headline | two assessments; the halt stays in `items` |
| India halt plus Hormuz plus trade-gap wording | `show` / `oil_supply_shock` |
| Indonesia fires plus "palm oil", "palm-oil", or "crude palm oil" exports | `suppress` |
| "Indonesia palm oil exports are halted" with no fire | `hold-for-review`, not `oil_supply_shock` |
| Indonesia refinery fire that halts crude exports | `assess` / `oil_supply_shock` |

The issuer name CoreWeave no longer forces `show`. The CDS distress headline is `show` / `ai_capex_credit`. "Analysis:Why CoreWeave is in the crosshairs of the AI scare" and "CoreWeave opens a London office" are `hold-for-review` and are not recalled.

## Gate 3

`_boj_boe_title_kept` now also keeps `bank rate`, `money market operations`, `complementary deposit facility`, `financial stability`, `intervention`, and `official cash rate`. It still drops "Services Producer Price Index for August" and still keeps "Monetary Policy Meeting statement" and gilt sales.

Those kept policy titles are scored, not only recalled. "Bank rate maintained at 3.75%" is `assess` / `g10_policy_path` with GBP. The money-market-operations guideline is `assess` with JPY. "Official Cash Rate unchanged" is `assess` with NZD. Recall uses "monetary policy meeting" and "monetary policy summary", not bare "monetary policy". "Monetary Policy Committee dates for 2027" is not recalled. The title filter still keeps that calendar; stage-1 recall drops it.

RBNZ is unresolved. Every `www.rbnz.govt.nz` URL checked in phase 1D returned HTTP 403, including the B2 workbook already in `scripts/market_state.py`. No RSS URL was verified. None was added. An OCR score is not a feed.

Residuals: BoC and RBA RSS 1.0 bodies still parse as zero items. "Indicators for Core CPI" can still pass on the existing `cpi` token. A governor interview that lacks the new phrases can still be dropped. Reuters and CNBC rows are headline-only, so a transmission link that exists only in the body is invisible.

## Gate 4

`explain_display_slots` in `scripts/apply_overnight_news_refresh.py` calls `_partition_items` and the same 6/3/12 slices as `_last24_html`, `_dated_rollup_html`, and `_rollup_html`. `published` means the row is in one of those slots. A row can be in the 12 and outside the 6; the trail has one dict per slot.

`build_report` maps a merge `shown` row to `research_top_24` (cap 24) and does not copy `presentation_suppression` into `publication_rows`. `overlay_drop_rows` records packet rows that `public_news_rows` drops. The accepted-news envelope keys are unchanged. Schema version of the shadow report stays 1.

The smoke script does not collect, assemble, or write the accepted artifact. Its `publication_rows` are the research pool, not the webpage. A dated row that shares a URL and title with an undated supplement is not marked `published` for the digest; the test `test_dated_twin_outside_window_is_not_published_with_undated_copy` locks that.

## Gate 5

`_same_event` refuses a merge when both facets are non-empty and different, or when only one headline contains CoreWeave. `ormuz` tokenizes as `hormuz`. Same non-empty facet with at least four shared tokens merges even below Jaccard 0.55, which is how the two CoreWeave CDS wires (Jaccard 0.545) stay one item.

Targeted tests cover Hormuz supply versus diplomacy, India trade gap versus Hormuz, the India export halt that also says trade deficit, Vietnam GDP versus Vietnam oil, CoreWeave versus Nvidia boilerplate, the Ormuz alias, and the CDS pair.

Residual: any other same-facet pair with four shared tokens also merges. That includes two different Hormuz supply headlines that copy the same four tokens. The Portuguese IRGC sentence still shares no tokens with the English wire.

## Gate 6

Edits are the news engine, its tests, and `docs/news_intelligence/`. No ACP file, workflow, launch contract, credential, or production publish path was changed. The refresh script's HTML output is unchanged aside from the added explainer. No merge and no deploy.

## Exact limitations

- The 15 Oct CNBC CDS URL is not shown to have been on any implemented feed during its 24-hour window.
- RBNZ releases are not fetched.
- BoC and RBA press feeds are still unread RSS 1.0.
- Bing credit queries can return HTTP 200 with zero or unrelated items. Empty is `ok`.
- Same-facet clustering can still join distinct incidents that share four tokens.
- Headline-only CNBC and Reuters metadata cannot see a transmission link that is only in the article body.
