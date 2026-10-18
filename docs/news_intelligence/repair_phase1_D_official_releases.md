# Phase 1D — official BoJ, BoE, and RBNZ releases

Diagnosis only, 2026-10-17. No source, test, or `data/overnight/accepted_public_news.json` edits. HTTP checks used the discovery user-agent in `scripts/overnight/news_sources.py:14-17`. Feed bodies were read as RSS metadata (title, link, pubDate). Article HTML was not fetched.

`news_relevance.py` has no BoJ/BoE title filter. The allow-list is `_boj_boe_title_kept` in `scripts/overnight/news_sources.py:400-423`. There is no deny-token list. A title is dropped unless it matches the allow rules. `live_news.acquire_current_news` then runs `recall_candidate` (`scripts/overnight/live_news.py:225-226`).

## Verdict

The title filter over-drops BoJ decision-day guideline text, the complementary-deposit-facility amendment, governor interviews, QT letters, financial-stability titles that do not say “financial policy committee”, and FX-intervention wording. It does **not** drop the live Bank Rate headline, BoJ MPM minutes, or the summary of opinions: those match “monetary policy” and then die later, at stage-1 recall, because that headline never says Bank of England, BoE, Bank of Japan, or BoJ.

Fed, ECB, BoC, and RBA do not use this title filter. BoC and RBA are a different defect: their feeds are RSS 1.0 RDF and `parse_surface` returns zero items.

RBNZ has no news or RSS URL anywhere in the repo. Every `www.rbnz.govt.nz` URL checked here returned HTTP 403. No feed was verified. Do not add one.

On the shadow cutoff `2026-10-17T18:35:55-04:00` (`docs/news_intelligence/shadow_20261017.json:4`), zero items in the current BoJ what’s-new feed and zero items in the BoE news feed fall inside the 24-hour window. The filter still records `official_title_filter` and discards the pubDate (`scripts/overnight/news_sources.py:549-551` returns before the window branch). Shadow counts match a re-parse of the live feeds: BoJ 51 items, 46 `official_title_filter`, 5 `window`; BoE 50 items, 43 `official_title_filter`, 7 `window`.

## 1. Allow rules (exact)

Surface gate, `scripts/overnight/news_sources.py:49-52` and `:396-397`. The filter runs only when the surface URL contains one of:

- `boj.or.jp/en/rss/whatsnew`
- `bankofengland.co.uk/rss/news`

Wired surfaces: `boj_whatsnew` `https://www.boj.or.jp/en/rss/whatsnew.xml` (`news_sources.py:127-128`) and `boe_news` `https://www.bankofengland.co.uk/rss/news` (`news_sources.py:134-135`).

`_boj_boe_title_kept` (`news_sources.py:400-423`), case-insensitive substring (`phrase in title`), not word boundaries:

Keep if the title contains any of:

- `monetary policy`
- `policy board`
- `policy rate`
- `interest rate`
- `financial policy committee`
- `monetary policy committee`
- `cpi`
- `inflation`
- `gilt`

Or if it contains any of `bank of japan`, `boj`, `bank of england`, `boe`, `gilt` **and** any of `rate`, `policy`, `inflation`.

Anything else is `official_title_filter` (`news_sources.py:549-550`). `statement` alone does not keep. `QE` is not an allow token. That matches `docs/news_intelligence/phase2_design.md:389` and contradicts the earlier sketch at `phase2_design.md:64-67`, which listed bare `statement` and `QE`. The code is the gate. `tests/test_news_intelligence.py:245-268` locks two behaviors: “Monetary Policy Meeting statement” is kept; “Services Producer Price Index for August” is `official_title_filter`. “Asset Purchase Facility: Gilt Sales – Market Notice” is kept (`tests/test_news_intelligence.py:269-285`).

Substring hazards in the second clause: `rate` matches inside `corporate`, `operate`, `moderate`, and `generate`; `boe` and `cpi` are not word-bounded. On the 51 + 50 live titles fetched today, no false keep came from those inner matches. The false keeps that did occur are the explicit phrases below.

### Important classes versus this allow-list

Checked with `_boj_boe_title_kept` and `recall_candidate(title, "")` against the live feeds and against short titles the live wording does not use. “Title filter” is the first column. “Recall” is stage 1, which still runs if the title filter keeps the row.

| Class | Live or synthetic title | Title filter | Stage-1 recall |
| --- | --- | --- | --- |
| Monetary policy statement, when the title says those words | Live test fixture “Monetary Policy Meeting statement” (`tests/test_news_intelligence.py:248`) | keep | false (`monetary policy` is not a recall token, `news_relevance.py:606-642`) |
| BoJ decision as actually titled | “(Reference) Change in the Guideline for Money Market Operations (September 2026 MPM)” `http://www.boj.or.jp/en/mopo/mpmdeci/mpr_2026/k260918b.pdf` pub Fri, 18 Sep 2026 11:54 +0900 | **drop** | false |
| BoJ rate-corridor implementation | “Amendment to Principal Terms and Conditions of Complementary Deposit Facility” `http://www.boj.or.jp/en/mopo/mpmdeci/mpr_2026/mpr260918b.pdf` same day | **drop** | false |
| Bank Rate, live compound title | “Bank rate maintained at 3.75% - September 2026 Monetary Policy Summary and Minutes” `https://www.bankofengland.co.uk/monetary-policy-summary-and-minutes/2026/september-2026` Thu, 17 Sep 2026 12:00 +0100. July issue is the same shape | keep (via `monetary policy`) | **false**. The title never says Bank of England or BoE. `bank rate` is not a recall token |
| Bank Rate, bare | Synthetic “Bank rate maintained at 3.75%” / “Bank Rate reduced to 3.5%” | **drop** | false |
| OCR | Synthetic “Official Cash Rate unchanged” / “OCR unchanged at 2.25 percent”. No RBNZ news item was available to test | **drop** | false (`ocr` is not a recall token; `rbnz` is, `news_relevance.py:616`) |
| Summary of opinions, live title | “Summary of Opinions at the Monetary Policy Meeting on September 17 and 18, 2026” `http://www.boj.or.jp/en/mopo/mpmsche_minu/opinion_2026/opi260918.pdf` | keep | **false** |
| Summary of opinions, bare | Synthetic “Summary of Opinions” | **drop** | false |
| MPM / MPC minutes, live title | “Minutes of the Monetary Policy Meeting on July 30 and 31, 2026” `http://www.boj.or.jp/en/mopo/mpmsche_minu/minu_2026/g260731.pdf` | keep | **false** |
| Minutes, bare or of another committee | Synthetic “Minutes”. Live BoE “Minutes of the SONIA Stakeholder Advisory Group”, Court of Directors, FXJSC, Money Market Committee, banknote imagery advisory group | drop | false, except “Minutes of the Securities Lending Committee” which recall would keep via `lending` (`news_relevance.py:584`) and the title filter correctly drops |
| Financial stability report wording | Synthetic “Financial Stability Report” / “Financial System Report”. Live “Twenty-fifth Meeting of the Council for Cooperation on Financial Stability” `http://www.boj.or.jp/en/finsys/macpru/mac261009a.pdf` | **drop** | false |
| FPC record (stability-adjacent, different words) | “Financial Policy Committee Record – September 2026” and the July record | keep (`financial policy committee`) | false |
| Governor speech that already says monetary policy or inflation | “Speech by Board Member KOEDA in Kumamoto (Economic Activity, Prices, and Monetary Policy in Japan)” `http://www.boj.or.jp/en/about/press/koen_2026/ko261015a.htm`. On the unwired speeches feed: “The outlook for inflation – speech by Clare Lombardelli” | keep | KOEDA **false** (no `boj`). Lombardelli true via `inflation` |
| Governor speech or interview without those words | “Transcript of the Governor's pooled broadcast interview given on 17 September 2026” `https://www.bankofengland.co.uk/news/2026/september/the-governor-interview-transcript-17-september-2026`. Speeches feed: “Financial resilience in an age of repeated shocks - speech by Andrew Bailey” (Thu, 08 Oct 2026); “Remaining anchored: Monetary Policy…” is kept only because it says monetary policy | **drop** on `/rss/news`. Bailey resilience **drop** if that title were on the filtered surface. The speeches URL is not filtered, and it is not fetched | false |
| QT / APF letter | “Exchange of letters between the Governor and the Chancellor regarding QT and the APF - September 2026” | **drop** | false |
| CPI letter beside it | “Exchange of letters between the Governor and the Chancellor regarding CPI Inflation - September 2026” | keep (`cpi`) | true (`cpi`) |
| Gilt sales | “Asset Purchase Facility: Gilt Sales – Market Notice 17 September 2026” | keep (`gilt`) | **false** (`gilt` is not a recall token) |
| FX intervention | No intervention item in either live feed. Synthetic “Foreign exchange intervention operations” and “Foreign Exchange Intervention Operations (July 2026)” | **drop** | false |
| FX intervention that names the Bank | Synthetic “Bank of Japan: Foreign Exchange Market Intervention” | **drop** (institution, but no `rate` / `policy` / `inflation`) | true (`bank of japan`) |
| FX reserves market notice (not an intervention statement) | “Foreign Currency Reserves 2026 – Market Notice 22 September 2026” and the 21 September notice | drop | false |

### Noise the filter correctly drops

From the live what’s-new and news feeds, these lack every allow phrase and are dropped. That is the filter doing the job `tests/test_news_intelligence.py:245` describes:

- BoJ statistics and operations: current-account balances, money stock, fails, principal figures of financial institutions, corporate goods price index, Tankan, monetary base, services producer price index, flow of funds, JGB holdings, call-money amounts, payment and settlement statistics, consumption activity index, output gap, regional economic report, direct investment, IMES discussion papers, opinion survey, “Meeting on Market Operations”.
- BoJ names the bank and is still dropped, correctly, because the second clause needs `rate` or `policy` or `inflation`: “Bank of Japan Accounts”, “Japanese Government Bonds Held by the Bank of Japan”, “Market Operations by the Bank of Japan”, “Collateral Accepted by the Bank of Japan”.
- BoE admin and markets plumbing: banknote imagery minutes, “four animals that will feature on our next series of banknotes”, Leeds office, EDMC appointments, Chief Cashier, Court minutes, SONIA minutes, FXJSC minutes, RTGS delay, green notice, statistical notices, PRA fines and consultations.

Several of those BoE titles would pass stage 1 (`bank of england`, `fx`, `treasury`, `lending`) and are stopped only by the title filter. Do not replace the allow-list with “any title from these two hosts”.

### Noise the filter fails to drop

These match an allow phrase and are not policy decisions:

- “Average Contract Interest Rates on Loans and Discounts (Aug.)” via `interest rate`. Stage 1 then drops it (`loan` does not match `loans`; `news_relevance.py:48-51`).
- “Indicators for Core CPI” via `cpi`. Stage 1 **keeps** it (`cpi` at `news_relevance.py:617`). This is the one live false keep that would become a candidate inside a 24-hour window.
- “Monetary Policy Committee dates for 2027” via `monetary policy committee`. A calendar. Stage 1 drops it.

`docs/NEWS_INTELLIGENCE_REPAIR.md:100` (“BoJ statistics titles that do not say monetary policy”) is only half right. SPPI, Tankan, and CGPI are dropped. The loans-and-discounts interest-rate print and the core-CPI indicator are not.

### Second gate (not the title filter, still discards the same releases)

`recall_candidate` (`news_relevance.py:653-662`) does not treat `monetary policy`, `bank rate`, `minutes`, `gilt`, `governor`, or `official cash rate` as positive. After a title-filter keep, these live rows still return false: the September and July Bank Rate headlines, both FPC records, BoJ minutes, the summary of opinions, the KOEDA speech, and gilt sales. Broadening only `_boj_boe_title_kept` leaves that discard in place. `MARKET_TOKENS` (`live_news.py:29-67`) is not consulted by `acquire_current_news`.

## 2. RBNZ

Omitted on purpose. `docs/news_intelligence/phase1_A_source_coverage.md:47` records HTTP 403 for `https://www.rbnz.govt.nz/news-and-events/news` and says no RSS href was found. `docs/NEWS_INTELLIGENCE_REPAIR.md:29` and `:99` repeat that. `docs/news_intelligence/phase2_design.md:60` defers RBNZ. `discovery_surfaces()` has no RBNZ entry (`news_sources.py:61-140`).

Wire coverage already exists and is not a release feed: `RBNZ` is in `BLOOMBERG_QUERY` (`news_sources.py:22`), `MARKET_TOKENS` (`live_news.py:56`), and `recall_candidate` (`news_relevance.py:616`). `OFFICIAL_SOURCES` includes `Reserve Bank of New Zealand` (`live_news.py:76`) but nothing fetches it. Country code `NZ` is already attributed (`live_news.py:107-110`).

Repo URLs on `rbnz.govt.nz` are rates statistics or one-off bulletin links, not a news feed:

- `RBNZ_URL` `https://www.rbnz.govt.nz/-/media/project/sites/rbnz/files/statistics/series/b/b2/hb2-daily-close.xlsx` (`scripts/market_state.py:125`). B2 daily closes.
- `RBNZ_PAGE` / `RBNZ_HTML_URL` `https://www.rbnz.govt.nz/statistics/series/exchange-and-interest-rates/wholesale-interest-rates` (`scripts/market_state.py:126-130`).
- Bulletin HTML links in `scripts/apply_daily_refresh.py:30` and `scripts/apply_v11_refresh.py:92`. Not feeds. Not requested.

This environment, same user-agent, 2026-10-17:

| URL | Status | Body |
| --- | --- | --- |
| `https://www.rbnz.govt.nz/news-and-events/news` | **403** | `text/html` titled “Website unavailable” |
| `https://www.rbnz.govt.nz/news-and-events` | **403** | same |
| `https://www.rbnz.govt.nz/news-and-events/how-we-release-information` | **403** | same |
| B2 xlsx (`market_state.py:125`) | **403** | same |
| Wholesale-interest-rates page (`market_state.py:126-128`) | **403** | same |

The bank’s public “how we release information” page, as indexed on the open web, describes the news HTML page, an email list, and an X post. It does not name an RSS or Atom URL. Those pages 403’d here, so no `rss` href could be read from them. No other RBNZ feed URL exists in this repo. Residual limitation: RBNZ OCR decisions, MPS, FSR, and governor speeches stay unwired. Do not invent a path and do not scrape the news HTML.

## 3. Fed, ECB, BoC, RBA

They do not have this title-filter bug. `_is_boj_boe_surface` is false for their URLs (`news_sources.py:49-52`). Re-parse with `parse_surface` on the bytes fetched today:

| Surface | HTTP | Parser |
| --- | --- | --- |
| Fed `https://www.federalreserve.gov/feeds/press_monetary.xml` (`news_sources.py:100`) | 200 `text/xml` RSS 2.0, 15 items | `raw_count` 15, all `window`. No `official_title_filter` |
| ECB `https://www.ecb.europa.eu/rss/press.html` (`news_sources.py:121`) | 200 `application/rss+xml`, 15 items | `raw_count` 15. In-window row is “Christine Lagarde: IMFC Statement” (`2026-10-17T01:00:00-04:00`). Stage 1 drops it (`news_relevance.py:653`). Same finding as `docs/news_intelligence/phase5_A_missed.md:94` |
| BoC `https://www.bankofcanada.ca/content_type/press/feed/` (`news_sources.py:107`) | 200 `application/rss+xml` | Root is `{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF`. `root.find("channel")` is `None` (`news_sources.py:500-502`). `raw_count` 0. The file contains 10 RSS 1.0 items, including governor panels and speeches. The title filter never sees them |
| RBA `https://www.rba.gov.au/rss/rss-cb-media-releases.xml` (`news_sources.py:114`) | 200 `text/xml` | Same RDF shape. `raw_count` 0. The one item in the body is “Appointment of Chief Risk Officer” (2026-10-14), which is not a policy decision |

Fed titles such as “Federal Reserve issues FOMC statement” pass the parser. “Minutes of the Federal Open Market Committee, September 15-16, 2026” would also pass the parser and then fail recall: `fomc` and `fed` are word-boundary tokens (`news_relevance.py:48-51`, `:609-610`) and do not match “Federal Open Market Committee”. That is stage 1, not `_boj_boe_title_kept`. The 15 Fed items on this fetch are all outside the shadow window, so tonight’s receipt zero is `window`.

## 4. Smallest repair

1. Keep the allow-list. Do not keep every BoJ/BoE title, and do not add bare `minutes`, bare `statement`, bare `speech`, or bare `bank of japan`. Those would admit SONIA/Court/FXJSC minutes, accounts, JGB holdings, and banknote copy that stage 1 would otherwise accept.
2. Add these substring phrases to `_boj_boe_title_kept`: `bank rate`, `money market operations`, `complementary deposit facility`, `financial stability`, `intervention`, `official cash rate`. Optionally `summary of opinions` for the bare form. The live compound titles for Bank Rate, minutes, and the summary of opinions already pass.
3. Teach `recall_candidate` the same policy phrases, plus `gilt` and `monetary policy`, so a row the title filter already keeps is not discarded at `news_relevance.py:653`. Without that, the September Bank Rate headline, MPM minutes, the summary of opinions, gilt sales, and the KOEDA speech still never become candidates.
4. Leave `https://www.boj.or.jp/en/rss/statistics.xml` unwired. It is HTTP 200 RSS and is linked from `https://www.boj.or.jp/en/tips.htm` next to what’s-new, and it is the daily FX fixings and statistics duplicate `phase1_A` already rejected.
5. `https://www.bankofengland.co.uk/rss/speeches` is HTTP 200 RSS 2.0 (50 items) and is linked from `https://www.bankofengland.co.uk/rss`, but it is not a `discovery_surfaces()` entry. Adding it does not by itself keep governor speeches: most of those titles fail stage 1 (“Financial resilience… speech by Andrew Bailey”, “The world today – remarks by Andrew Bailey”). The index also links `/rss/statistics`, `/rss/prudential-regulation-publications`, `/rss/publications`, `/rss/events`, `/rss/bank-insights`, and `/rss/knowledgebank`. Those were not fetched this pass. Do not add them to escape the title filter.
6. Do not add an RBNZ surface until some URL returns 2xx and the body is RSS, Atom, or an HTML list of releases. That did not happen here.

BoC/RBA RDF (`news_sources.py:500-502`) is a separate parser gap. It is not fixed by editing `_boj_boe_title_kept`.

## Verified feeds (this run)

| URL | In repo or official index | Status | What came back |
| --- | --- | --- | --- |
| `https://www.boj.or.jp/en/rss/whatsnew.xml` | `news_sources.py:128` | **200** `application/xml` | RSS 2.0, 51 items |
| `https://www.boj.or.jp/en/rss/statistics.xml` | href on `https://www.boj.or.jp/en/tips.htm` (200) | **200** `application/xml` | RSS 2.0, 54 items. Not wired |
| `https://www.boj.or.jp/en/tips.htm` | `phase1_A` | **200** `text/html` | RSS hrefs: `/en/rss/whatsnew.xml`, `/en/rss/statistics.xml` only |
| `https://www.bankofengland.co.uk/rss/news` | `news_sources.py:135` | **200** `text/xml` | RSS 2.0, 50 items |
| `https://www.bankofengland.co.uk/rss/speeches` | href on `https://www.bankofengland.co.uk/rss` | **200** `text/xml` | RSS 2.0, 50 items. Not wired |
| `https://www.bankofengland.co.uk/rss` | `phase1_A` | **200** `text/html` | Index of the section feeds listed above |
| `https://www.federalreserve.gov/feeds/press_monetary.xml` | `news_sources.py:100` | **200** `text/xml` | RSS 2.0, 15 items |
| `https://www.bankofcanada.ca/content_type/press/feed/` | `news_sources.py:107` | **200** `application/rss+xml` | RDF / RSS 1.0, 10 items, parser reads 0 |
| `https://www.rba.gov.au/rss/rss-cb-media-releases.xml` | `news_sources.py:114` | **200** `text/xml` | RDF / RSS 1.0, 1 item, parser reads 0 |
| `https://www.ecb.europa.eu/rss/press.html` | `news_sources.py:121` | **200** `application/rss+xml` | RSS 2.0, 15 items |

## Unverified

- Any RBNZ RSS, Atom, or news-list URL. Official pages and the repo’s B2 URLs returned 403. No alternate feed is in the repo.
- Whether an RBNZ title in the wild uses “Official Cash Rate”, “OCR”, or “Monetary Policy Statement”. The synthetic OCR titles above are the class test, not a fetched release.
- An FX-intervention title on the current BoJ or BoE feeds. None was present. The drop result is from the allow-list applied to intervention wording, not from a live item.
- BoE section feeds other than `/rss/news` and `/rss/speeches` (statistics, prudential regulation, publications, events, bank insights, knowledge bank). They are linked from the 200 index and were not fetched.
- That any of the `official_title_filter` rows were inside the shadow’s 24-hour window. Feed pubDates say they were not. The drop record itself still has no timestamp.
