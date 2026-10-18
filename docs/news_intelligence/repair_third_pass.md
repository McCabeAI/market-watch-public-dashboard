# News intelligence third-pass source repair

Branch: `cursor/market-watch-g10-news-intelligence-overhaul-six-phase-grok-composer-graph-bbf3`. Pull request: https://github.com/McCabeAI/market-watch-public-dashboard/pull/215. Not merged. Not deployed. `data/overnight/accepted_public_news.json` was not modified. No full Market Watch run.

Checked 2026-10-18 with `MarketWatch-Public-News-Discovery/1.0`. Article HTML was not fetched.

## What changed

- `scripts/overnight/news_sources.py` reads RSS 1.0 RDF. Items are siblings of `channel`, titles and links use the RSS 1.0 namespace, and dates are `dc:date`. `rdf:about` is the URL when `link` text is empty. `http://` links are stored as `https://`.
- `https://www.rbnz.govt.nz/feeds/news` is the `rbnz_news` surface (`rss_official`, source name `Reserve Bank of New Zealand`). It is not a required source.
- `https://www.cnbc.com/id/15839069/device/rss/rss.html` is the `cnbc_investing` surface. Summaries stay the CNBC headline-only constant. It is not a required source.
- Receipts keep `source`, `checked_at`, `status`, `candidate_count`, `result_count`, `failure`, and `surface`. They add `feed_health`:
  - `fetch_failed` — status `failed`. An HTTP 403 stays in `failure` and is not an empty feed.
  - `zero_item_parse` — status `failed`, `failure` `unparsed_feed_items`. Item elements were present and none yielded a headline and link.
  - `empty_feed` — status `ok`, zero item elements.
  - `no_in_window` — status `ok`, items were parsed, and the mechanical filters left none. On this pass that includes date-window drops. A title-filter or path drop that also leaves zero items uses the same label; the story-drop `reason` is the specific cause.
  - `no_relevant_candidates` — status `ok`, in-window items remained, and stage-1 recall kept none.
  - `candidates` — status `ok`, `result_count` > 0.
  - `skipped` — offline.

`partial` still depends only on `bloomberg` and `reuters` status. The accepted-news envelope and the 6/3/12 slot explainer are unchanged.

## Live receipts

Nonpublishing smoke: `acquire_current_news(when=now_ny(), offline=False)` at `2026-10-17T22:05:59.856472-04:00` (`2026-10-18T02:05:59Z`). `mode` `live`, `partial` false. The script was not given `--report`. Nothing was written to the accepted-news artifact.

| Source | HTTP | status | feed_health | candidate_count | result_count |
| --- | --- | --- | --- | --- | --- |
| `boc_press` | 200 `application/rss+xml` | ok | candidates | 10 | 1 |
| `rba_media` | 200 `text/xml` | ok | no_in_window | 1 | 0 |
| `rbnz_news` | 200 `text/xml` | ok | no_in_window | 50 | 0 |
| `cnbc_investing` | 200 `application/xml` | ok | no_in_window | 30 | 0 |
| `cnbc` sitemap | 200 | ok | candidates | 79 | 3 |
| `cnbc_credit` | 200 | ok | candidates | 1 | 1 |
| `ecb_press` | 200 | ok | no_relevant_candidates | 15 | 0 |
| `bloomberg_credit` | 200 | ok | empty_feed | 0 | 0 |

BoC root was `{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF`. Ten items parsed. Nine were outside the 24-hour window. The in-window row was official: "Media roundtable with Governor Macklem", `2026-10-17T05:00:36-04:00`, `https://www.bankofcanada.ca/2026/10/media-roundtable-governor-macklem-2026-10-17/`. Stage-1 recall kept it. That is a press roundtable, not a rate decision.

RBA root was the same RDF form. The one item, "Appointment of Chief Risk Officer" (`https://www.rba.gov.au/media-releases/2026/mr-26-29.html`, `dc:date` `2026-10-14T14:00:00+11:00`), was a window drop. `raw_count` 1, so this is no longer a zero-item parse.

RBNZ `https://www.rbnz.govt.nz/news-and-events/news` was HTTP 403, body titled "Website unavailable". The same check of `https://www.rbnz.govt.nz/feeds/news` was HTTP 200 RSS 2.0, 50 items, publisher text "Press releases issued by the Reserve Bank of New Zealand". All 50 were outside the 24-hour window. The newest titles were the 15 Oct 2026 joint APRA stress test and the cyber/AI supervisory note. Item links were stored from the feed. Those HTML pages were not fetched. `feeds/media`, `feeds/speeches`, `feeds/publications`, and `feeds/monetary-policy` on the same host returned 403 and were not added.

## Credit / AI financing

Historical gate, unchanged: **unresolved**. Presence of `https://www.cnbc.com/2026/10/15/coreweave-credit-default-swaps-hit-distress-levels-as-investors-sour-on-ai-debt.html` on a feed fetched at `2026-10-18T02:05:59Z` does not show that the URL was listed during `[2026-10-15T16:52:16Z, 2026-10-16T16:52:16Z]`. No archived sitemap or RSS capture from that window was found in the prior pass. This pass did not add one.

At the smoke cutoff the investing RSS contained that URL and dropped it as `window`, with the other CoreWeave rows "The Austin Powers steamroller: How to trade CoreWeave's slow moving crisis" (`https://www.cnbc.com/2026/10/16/playing-the-coreweave-disconnect.html`) and "Traders pile into 'bubble puts' on CoreWeave as neocloud stocks plunge" (`https://www.cnbc.com/2026/10/14/coreweave-put-options-ai-trade.html`). `candidate_count` 30, `result_count` 0. The final candidate list did not contain the 15 Oct CDS URL. The CNBC news sitemap's in-window rows also did not contain it.

A fixture with that headline, that URL, and an in-window `pubDate` is kept, with `CNBC_HEADLINE_ONLY` as the summary. That is parser proof for the next item that lands inside 24 hours. It is not historical recall.

Evaluated and not wired:

- `https://www.ft.com/markets?format=rss` was HTTP 200 (25 items), including "Sizing CoreWeave’s ‘unlimited’ insurance capital" (Fri, 16 Oct 2026 10:24:31 GMT) and "Anthropic assigned highest junk credit rating in June" (Fri, 16 Oct 2026 04:00:18 GMT). Both were already outside a 24-hour window at this check. The feed is a markets section, so it was left unwired.
- `https://www.ft.com/credit?format=rss` redirected to an HTML page, not an RSS document.
- A Google News search RSS returned the 15 Oct CNBC URL among current results. That is a keyword index with non-canonical links. It was not wired, and it is not evidence about the original 24-hour window.
- Bing `bloomberg_credit` was a healthy empty feed. `cnbc_credit` returned one in-window row and still did not put the 15 Oct CDS URL in the final candidate list.

## Tests

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

82 tests, OK, on 2026-10-18. Fixtures only, except the live smoke above. No full Market Watch run.

The RDF fixtures use a live-shaped `rdf:RDF` root, the RSS 1.0 default namespace, and `dc:date`. One item has a canonical URL only on `rdf:about`. An item element with no title and no link is `feed_parse=unparsed` and the receipt is `zero_item_parse`, not `ok`. An empty `<channel>` is `empty_feed`. An in-window cafeteria headline is `no_relevant_candidates`. A fetcher error whose text contains `403` is `fetch_failed` and is distinct from `empty_feed`.

## Known limitations

- Gate 1 stays unresolved. Do not treat tonight's investing-RSS hit as proof the 15 Oct URL was discoverable in its original day.
- RBNZ HTML on `www.rbnz.govt.nz` still returns 403 from this environment. The news RSS is the fallback. There was no in-window OCR or MPS item at the smoke cutoff. Feed descriptions that name the Reserve Bank can pass stage-1 recall once they fall inside 24 hours, including non-decision releases.
- BoC press includes speeches and roundtables. The parser does not apply a second title filter.
- RBA's only current media-release item was outside the window.
- `no_in_window` is also used when a title filter or path rule removes every parsed row. Read `story_drops` for the reason.
- Bing credit queries were not expanded. Private-credit coverage still depends on those queries plus whatever an in-window CNBC investing headline says.
- Same-facet clustering can still join distinct incidents that share four tokens.
- CNBC and Reuters rows remain headline-only.

## Merge recommendation

Do not merge on this pass. The RDF parser, the RBNZ RSS, and the CNBC investing RSS are verified and ready for review. Gate 1 is still an unresolved historical-recall blocker, and this note does not close it.
