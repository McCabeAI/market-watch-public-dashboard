# Phase 2 — News intelligence implementation spec

Authoritative for Phase 3 coding agents. Phase 1 notes (`phase1_A`–`phase1_D`) are evidence; **parent job decisions** below override Phase 1A caps and Phase 1D’s “keep [:8]/16” row.

## 1. Architecture (one page)

**Goal:** Score every in-window discovery row before any relevance-driven truncation; expose G10 transmission as a deterministic `transmission` object; keep public API and receipt contracts stable.

```
discovery_surfaces()  [news_sources.py]
  → acquire_current_news()  [live_news.py: fetch, receipts, candidates]
       parse_surface(kind, …) per surface  [news_sources.py]
       recall_candidate() on each row  [news_relevance.py, stage 1]
       safety ceiling 60 newest in-window per surface (parse cost only)
  → merge_live_news(baseline, live_candidates, when=)  [news_cluster.py, re-export live_news]
       dedupe URL → token-overlap cluster (unchanged _same_event logic)
       apply_transmission() per cluster representative  [news_relevance.py]
       items = show|assess only, salience sort, cap 24
       research_supplement.news mirrors public list policy (see §5)
       presentation_caps {last_24_hours: 6, top_market_drivers: 3} unchanged
  → build_report(acquisition, merge, …)  [news_diagnostics.py]
```

**Import direction (no cycles):**

| Module | May import |
| --- | --- |
| `news_relevance.py` | stdlib only |
| `news_cluster.py` | `news_relevance` only |
| `news_sources.py` | stdlib; may duplicate small parse helpers or import non-cyclic utils from `live_news` only if 3A extracts shared `_collapse_ws` to a tiny util — prefer parsers self-contained in `news_sources` |
| `live_news.py` | `news_sources`, `news_cluster`; `news_diagnostics` **lazy inside** `acquire_current_news` / optional report hook only if needed |
| `news_diagnostics.py` | no `live_news` at import time; accept plain dicts |

`attribute_country_codes` stays in `live_news.py`. Parsers call it when building candidate dicts (before merge). `news_cluster` does **not** import `live_news`.

**Removed gates (3A/3C):** per-source `[:8]`, merged `_cap_items(16)`. **Not removed:** 24h window, path drops, stage-1 recall, post-assessment 24-item cap, `presentation_caps`, HTML story cap 12 in `apply_overnight_news_refresh.py` (off-limits).

**Accepted research (3B + small `accepted_news.py` change):** Before `overlay_accepted_research` replaces `families["news"]`, run `apply_transmission` on each supplement `news` row, then **drop** rows with `transmission.disposition` in `suppress`, `hold-for-review`. Preserve dict identity for retained rows (shallow copy + `transmission` attach). Do **not** filter `central_bank_research`.

---

## 2. Discovery surfaces

Fetcher: injectable `Fetcher` (`live_news.py` pattern). User-Agent unchanged. No article HTML GETs.

| `source` (receipt) | `kind` | Surface URL / query | `source_name` on items | Notes |
| --- | --- | --- | --- | --- |
| `bloomberg` | `bing_rss` | Existing `BLOOMBERG_QUERY` + Bing RSS (`BLOOMBERG_SURFACE`) | Bloomberg | `REQUIRED_SOURCES`; drives `partial` |
| `reuters` | `reuters_sitemap` | `REUTERS_SURFACE` | Reuters | `REQUIRED_SOURCES` |
| `bloomberg_credit` | `bing_rss` | `site:bloomberg.com (CoreWeave OR neocloud OR "data center" OR hyperscaler) (bond OR debt OR financing OR "credit facility" OR IPO OR CDS OR "credit default")` + same `format=rss` & 7d `qft` | Bloomberg | Distinct receipt; not in `partial` formula |
| `bloomberg_equity` | `bing_rss` | `site:bloomberg.com ("S&P 500" OR Nasdaq OR "bank stocks" OR selloff) (Fed OR yields OR dollar OR Treasury)` + same Bing params | Bloomberg | One equity-stress query is enough |
| `reuters_credit` | `bing_rss` | Phase 1A probe: `site:reuters.com ("private credit" OR "high-yield" OR "credit spread" OR CLO OR "funding stress")` + Bing params | Reuters | Empty RSS = `ok`, `result_count` 0 |
| `fed_monetary` | `rss_official` | `https://www.federalreserve.gov/feeds/press_monetary.xml` | Federal Reserve | |
| `boc_press` | `rss_official` | `https://www.bankofcanada.ca/content_type/press/feed/` | Bank of Canada | |
| `rba_media` | `rss_official` | `https://www.rba.gov.au/rss/rss-cb-media-releases.xml` | Reserve Bank of Australia | |
| `ecb_press` | `rss_official` | `https://www.ecb.europa.eu/rss/press.html` | European Central Bank | |
| `boj_whatsnew` | `rss_official` | `https://www.boj.or.jp/en/rss/whatsnew.xml` | Bank of Japan | Title filter §2.1 |
| `boe_news` | `rss_official` | `https://www.bankofengland.co.uk/rss/news` | Bank of England | Add GB attribution in 3A if headline names BoE/gilt (optional `country_codes`; GBP in `affected_assets`) |

**Deferred (document only):** RBNZ (403), FT/WSJ RSS, Bloomberg markets firehose, unfiltered SEC 8-K, BLS/BEA/EIA feeds, Fed `press_all`/H.8/SLOOS as separate surfaces (link via news headline only if already in wire cluster).

### 2.1 BoJ / BoE title filter (`rss_official`)

Keep item if title (case-insensitive) matches any:

- `monetary policy`, `policy board`, `policy rate`, `interest rate`, `statement` (BoJ/BoE policy statements)
- `Bank of Japan`, `BoJ`, `Bank of England`, `BoE` **and** (`rate` OR `policy` OR `inflation` OR `QE` OR `gilt`)

Drop otherwise → diagnostics `reason=official_title_filter`, `stage=relevance_rejection` (not counted in `result_count`).

### 2.2 Parser contract (`news_sources.parse_surface`)

```text
parse_surface(kind, data, *, surface, cutoff) -> {
  "raw_count": int,      # receipt candidate_count rules below
  "items": list[dict],   # candidate-shaped dicts, uncapped except safety ceiling
  "dropped": list[{headline?, url?, reason}]  # for diagnostics merge
}
```

**`candidate_count` (receipt, unchanged semantics):**

- `bing_rss`: increment after canonical `bloomberg.com` URL resolved (same as today).
- `reuters_sitemap`: increment per sitemap row with headline + loc (same as today).
- `rss_official`: increment per RSS `<item>` with link + title before title filter.

**`result_count`:** count of items returned for that surface **after** path/window/noise mechanical drops **and** `recall_candidate()` true. Apply safety ceiling **after** that; if ceiling binds, set receipt extension field in diagnostics only: `safety_ceiling_applied: true` (do **not** add keys to receipt dict — report only).

**Safety ceiling:** keep newest 60 by `published_at` within 24h window per surface. Sort desc before slice.

**Mechanical drops (all kinds):** `/video`, `/newsletter`, `/podcast` paths; unparsed or out-of-window `published_at`; hard noise with no channel (stage 1 false).

---

## 3. Relevance and salience (`news_relevance.py`)

### 3.1 Function signatures

```python
def score_transmission(headline: str, summary: str) -> dict: ...
def recall_candidate(headline: str, summary: str) -> bool: ...
def apply_transmission(item: dict) -> dict: ...
```

`apply_transmission` deep-copies `item`, sets `transmission` (below) and `market_salience` `{score, distribution, components}` compatible with existing tests. `distribution` = `high` if any edge or `source_name` is Bloomberg else `standard`.

### 3.2 Transmission object (required keys)

```python
{
  "disposition": "show" | "assess" | "suppress" | "hold-for-review",
  "affected_assets": list[str],  # closed set phase1_B
  "channel": str | None,         # primary channel id
  "channels": list[str],
  "reason_code": str,
  "score": int,                  # transmission_score; may be negative
  "components": dict[str, int],
}
```

**Channels (ids):** `usd_rates`, `g10_policy`, `global_risk`, `credit_funding`, `oil_energy_tot`, `china_spillover`, `geopolitics_haven`. Primary = max weight among fired; tie order: `oil_energy_tot` → `g10_policy` → `usd_rates` → `credit_funding` → `china_spillover` → `geopolitics_haven` → `global_risk`.

**Reason codes (closed):** `oil_supply_shock`, `china_commodity_spillover`, `g10_policy_path`, `usd_rates_repricing`, `global_risk_beta`, `credit_funding_stress`, `ai_capex_credit`, `geopolitics_haven_or_oil`, `local_non_g10_macro`, `incidental_link_only`, `noise_non_market`, `ambiguous_transmission`, `us_activity_index` (Chicago Fed CFNAI / national activity index).

### 3.3 Stage 1 — `recall_candidate`

Return `False` if: any `NOISE_EXCLUDE` token (`podcast`, `golf`, `celebrity`) **and** no channel would fire on headline+summary.

Return `True` if any:

- Macro/energy/FX/policy token from legacy `MARKET_TOKENS` **except** bare sole hit on `gdp`, `recession`, or `unemployment` (word-boundary; no other recall class);
- Credit/funding: `credit`, `cds`, `spread`, `high-yield`, `clo`, `repo`, `sofr`, `lending`, `default`, `distress`, `bond`, `loan`, `financing`;
- Equity stress: `s&p`, `nasdaq`, `selloff`, `bank stock`, `megacap` + (`fed` or `yield` or `dollar` or `treasury`);
- AI financing: (`ai` or `data center` or `hyperscaler` or `neocloud` or `coreweave`) + (`debt` or `bond` or `financing` or `cds` or `capex`);
- China spillover recall: `china` + (`stimulus` or `property` or `pboc` or `commodity` or `crude` or `iron` or `aud` or `nzd` or `jpy` or `eur`);
- Named G10 body: Fed, FOMC, ECB, BoE, Bank of England, BoJ, BoC, RBA, RBNZ, Bank of Canada, etc. (regex set from phase1_B).

**US domestic activity (explicit):** headline matches `Chicago Fed` or `CFNAI` or (`national activity index` and `Chicago`) → recall true; stage 2 uses `us_activity_index` rule (§3.5).

### 3.4 Stage 2 — scoring (deterministic)

**Subject penalties (apply first; force channels empty if local/incidental/noise):**

| Rule | Match | disposition | reason | `subject_penalty` |
| --- | --- | --- | --- | --- |
| Local non-G10 macro | Vietnam/Indonesia/India-style domestic GDP target, trade balance, CPI, budget, parliament speech; no channel role | suppress | `local_non_g10_macro` | -8 |
| Incidental link | Non-G10 subject; oil/China/G10 name only explains local number (India import bill) | suppress | `incidental_link_only` | -8 |
| Noise | sports/celebrity/local politics w/o haven/oil | suppress | `noise_non_market` | -10 |
| Indonesia fires | `indonesia` + (`fire` or `forest`) + assistance; **ignore** palm oil in summary if headline lacks energy channel | suppress | `local_non_g10_macro` | -8 |

**Channel weights (components, 0 if role fails):** `channel_usd_rates` 5, `channel_g10_policy` 5, `channel_oil_energy` 5, `channel_china_spillover` 5, `channel_credit_funding` 5, `channel_global_risk` 4, `channel_geopolitics` 4.

**Positive pattern hooks (non-exhaustive; implement as regex/keyword tables):**

- Oil/Hormuz/OPEC/blockade/Brent/WTI shock → `oil_energy_tot`; conflict/haven → also `geopolitics_haven`; reason `oil_supply_shock` or `geopolitics_haven_or_oil`.
- China stimulus/growth/property + (`stimulus` or `crude` or `demand` or `commodity`) in headline+summary → `china_spillover`, reason `china_commodity_spillover` (Q3 poll fixture).
- CoreWeave/CDS/distress/AI debt headline → `credit_funding`, reason `ai_capex_credit`, assets include `credit_spreads`, `UST`; disposition `show` when score ≥10.
- G10 policy / USD rates paths → `g10_policy_path` / `usd_rates_repricing`.
- **US activity:** Chicago Fed CFNAI / national activity index (US, not Vietnam GDP) → `usd_rates` or `global_risk` light; reason `us_activity_index`; disposition **`show` if score≥10 else `assess`**; **never** `suppress` or `hold-for-review`.
- Ambiguous China/AI/yields without role → `hold-for-review`, `ambiguous_transmission`, score 0.

**Shock:** +0 routine, +2 material, +3 acute (blockade, emergency funding, policy surprise, CDS distress).

**Assets:** +2 one named asset from closed list, +3 two+.

`transmission_score` = sum(channel weights + asset + shock + subject_penalty).

**Disposition (uses `transmission_score` only, not tie-break):**

- `show`: score ≥ 10, ≥1 channel, no subject penalty.
- `assess`: 7–9 with channel.
- `hold-for-review`: ambiguous rule.
- `suppress`: penalty or noise.

**`market_salience.score`** = `max(0, transmission_score) + tie_break` (max +3):

| Component | Weight |
| --- | --- |
| `recency` | +1 if published within 12h of `when` |
| `novelty` | +1 if cluster has live edge (tie-break only) |
| `distribution_weight` | +1 if Bloomberg edge |

`market_salience.components` = transmission channel/asset/shock/penalty keys **plus** the three tie-break keys. **Invariant:** tie-break cannot promote `suppress`/`hold` to `show`. Hormuz live row must sort above diplomacy baseline (both may be `show`).

---

## 4. Clustering and merge (`news_cluster.py`)

### 4.1 Signatures

```python
def cluster_and_rank(baseline: list, live: list, when: datetime) -> dict:
    # keys: items, research_supplement, diagnostics_rows

def merge_live_news(baseline, live_candidates, *, when) -> dict:
    # same public shape as today + optional diagnostics_rows
```

### 4.2 Behavior

1. **URL dedupe** on edges before token clustering.
2. **Event merge:** keep existing `_same_event` token overlap (≥4 shared tokens, Jaccard ≥0.55).
3. **Timestamps:** normalize `published_at` to ISO-8601 via `isoformat(parse(...))` on merged cluster; `published_at` on cluster = max edge time.
4. **Stable `id`:** keep `news:` + sha256(sorted edge URLs)[:16].
5. Run `apply_transmission` on merged dict (headline/summary from display edge rules today).
6. **Output `items`:** include only `disposition` in (`show`, `assess`); sort by `market_salience.score` desc; **cap 24** (safety). Rows that would be `show` but fall outside cap → diagnostics `presentation_suppression`, stage `presentation_suppression`.
7. **`research_supplement`:** same keys as today; `news` = same list as `items` (or assess rows included — both show+assess); `top_market_driver_candidates` = first three **`show`** ids by salience (if fewer than 3 show, pad with next assess ids — match current “top 3 ids” test intent: highest salience regardless only if tests require; **existing test** uses merged top 3 by order — use top 3 of `items` after sort).
8. **Do not** put `suppress`/`hold` in `items`. Full assessed rows go to `diagnostics_rows` from `cluster_and_rank`; optional `assessed_items` on merge result **only** if no caller iterates unknown keys — prefer diagnostics report over extending merge return.
9. Remove `_cap_items(16)` entirely.

---

## 5. Schema additions

| Location | Field | Purpose |
| --- | --- | --- |
| Item | `transmission` | §3.2 |
| Item | `published_at` | normalized ISO string |
| Item | `id` | unchanged algorithm |
| Candidate | `discovery_surface`, `distribution_weight` | unchanged |
| Official candidates | `verification_status` | `"official"` when `source_name in OFFICIAL_SOURCES` |
| Merge return | `diagnostics_rows` | optional list of story-level rows for 3D |
| Diagnostics report | `stories[]` | `{headline, url, source, published_at, stage, reason}` |
| Diagnostics report | `stages` | `discovery_failure`, `relevance_rejection`, `presentation_suppression`, `shown` |

**Receipt dict:** exactly seven keys (no new receipt fields). `partial` unchanged: one of `{bloomberg,reuters}` failed and the other ok.

**Acquire return:** unchanged keys `mode`, `cutoff`, `partial`, `receipts`, `candidates`.

---

## 6. Diagnostics (`news_diagnostics.py`)

```python
def build_report(acquisition: dict, merge: dict, *, when, extra_rows=()) -> dict: ...
def write_report(path: str | Path, report: dict) -> None: ...
```

**Story-level row `stage`:**

| stage | When |
| --- | --- |
| `discovery_failure` | Surface fetch/parse failed; no item |
| `relevance_rejection` | suppress, hold-for-review, stage-1 drop, path/window drop, `official_title_filter`, hard noise |
| `presentation_suppression` | scored show/assess but omitted by post-assessment 24 cap or (downstream) display caps |
| `shown` | in final `items` list |

Do not collapse buckets. Include acquisition receipts summary and per-surface drop counts from `parse_surface.dropped`.

---

## 7. Shadow cycle

```bash
# Unchanged stdout behavior:
python scripts/live_news_discovery_smoke.py

# Extended (3D): JSON report, no collect/assemble/pages/launch
python scripts/live_news_discovery_smoke.py --report /tmp/news_shadow_report.json
```

Report may call `merge_live_news(baseline=[], live_candidates=acquisition["candidates"], when=now_ny())` and `build_report`. Stdout JSON unchanged when `--report` absent.

---

## 8. Phase 3 task cards

| Card | Owns | Deliverables | Non-goals |
| --- | --- | --- | --- |
| **3A** | `news_sources.py`, `live_news.py` | `discovery_surfaces`, `parse_surface`, wire all surfaces, receipts, remove [:8], safety 60, re-export `merge_live_news`, `attribute_country_codes`, `acquire_current_news` | `news_relevance.py`, `news_cluster.py` bodies, diagnostics, tests file, off-limits paths |
| **3B** | `news_relevance.py` | `score_transmission`, `recall_candidate`, `apply_transmission`; tables in §3 | discovery URLs, cluster, receipts |
| **3C** | `news_cluster.py` | `cluster_and_rank`, `merge_live_news`; dedupe URL; post-assess cap 24; no `_cap_items(16)` | `live_news.py` edits after 3A handoff |
| **3D** | `news_diagnostics.py`, `live_news_discovery_smoke.py` | `build_report`, `write_report`, `--report` flag | receipt shape, `collect`, HTML refresh |
| **Overlay** | `accepted_news.py` (minimal) | Score + filter suppress/hold on supplement `news` only; preserve order of kept rows; FRESH_NEWS_ITEM first | `central_bank_research`, off-limits JSON artifact content |

**Order:** 3B and 3C can start in parallel once this doc lands; 3A wires parsers first; 3A final pass imports 3C merge; 3D consumes merge diagnostics.

---

## 9. Test plan (`tests/test_news_intelligence.py`)

Injected `fetcher` only; no network.

| Case | Assert |
| --- | --- |
| Bloomberg fixture | `candidate_count==3`, `result_count==1`; golf/newsletter/video absent from candidates |
| CoreWeave | Inject headline on Reuters sitemap + Bloomberg RSS item; `disposition==show`, `reason_code==ai_capex_credit` |
| Vietnam GDP / India deficit | `suppress`; `local_non_g10_macro` / `incidental_link_only` |
| Chicago Fed ACTIVITY_ITEM | `show` or `assess`; never suppress/hold |
| Overlay order | After overlay helper with FRESH + ACTIVITY, oil headline first; both retained |
| Hormuz vs diplomacy | Live Bloomberg salience > diplomacy; both `show` |
| China Q3 stimulus | headline+summary with stimulus + crude demand → `show`, `china_commodity_spillover` |
| Indonesia fires | suppress even if summary mentions palm oil |
| Official BoJ filter | statistics title dropped → diagnostics `official_title_filter` |
| Safety ceiling | fixture with >60 rows → diagnostics `safety_ceiling` |
| Merge cap 24 | 30 show rows → `len(items)==24`, suppressed rows in diagnostics not in `items` |
| `presentation_caps` | still 6 and 3 on supplement |
| `partial` | bloomberg fail + reuters ok → true; both fail → false |
| Stage-02 | `bing.com` substring in fetch URLs for macro surface |

Existing `test_live_news_acquisition.py` and `test_accepted_news_architecture.py` must stay green without weakening.

---

## 10. Explicit non-goals

- Credentials, paid APIs, article HTML fetch, CNBC as discovery surface.
- Editing off-limits files (`apply_overnight_news_refresh.py`, workflows, ACP, `accepted_public_news.json`, etc.).
- ML/embeddings/classifiers for relevance.
- Changing HTML story cap 12, `sync_news_summary`, or `publish.py` gate.
- SEC 8-K issuer firehose, RBNZ scrape, FT/WSJ/Bloomberg firehose RSS.
- New receipt keys or altering `partial` formula for auxiliary surfaces.
- Claiming verified `reuters.com` article HTML for CoreWeave wires.

---

## 11. Fixture anchors (Phase 4+)

| Story | Expected |
| --- | --- |
| CoreWeave CDS (CNBC URL 2026-10-15) | show, `ai_capex_credit` |
| FRESH_NEWS_ITEM (oil/Iran) | show; stays first in overlay test |
| ACTIVITY_ITEM (Chicago Fed CFNAI) | show or assess |
| Vietnam GDP / India trade deficit | suppress |
| China Q3 stimulus poll | show, `china_commodity_spillover` |
| Indonesia forest-fire assistance | suppress |

**Residual risks:** Official RSS volume spikes if title filter drifts; Bing zero-item credit queries are normal; UK `country_codes` may stay empty while GBP appears in `affected_assets`.

## 12. Phase 2 review revisions (authoritative)

`docs/news_intelligence/phase2_review.md` is **REVISE**. This section overrides §§1–4 where they disagree.

### 12.1 Public list

`overlay_accepted_research` filters supplement `news` only. `assemble_dataset` today copies the raw packet into `agent_research`, and `persist_accepted_public_news_from_assembly` writes that list. Filtering only `families["news"]` would leave Vietnam and India in `accepted_public_news.json` and in HTML.

Required behavior:

- `news_relevance.public_news_rows(news: list) -> list` deep-copies each dict, calls `apply_transmission`, drops `suppress` and `hold-for-review`, preserves order. It does not mutate inputs.
- `overlay_accepted_research` stores that list on `families["news"]["items"]` when supplement `news` is non-empty. `central_bank_research` is not filtered. Digest is the hash of the kept list.
- `assemble.py` builds a shallow copy of the packet supplement. When the original supplement `news` is non-empty, `agent_research["news"]` becomes `families["news"]["items"]` (the kept list). `central_bank_research` stays the packet list. Envelope keys are unchanged. Do not edit `apply_overnight_news_refresh.py` or `data/overnight/accepted_public_news.json`.

`FRESH_NEWS_ITEM` then `ACTIVITY_ITEM` stay in that order. Both are show or assess.

### 12.2 Normative scores

`apply_transmission` sets transmission and a base `market_salience` whose score is `max(0, transmission_score)` and whose tie-break components are 0. `news_cluster` adds tie-break after merge. Tie-break does not change disposition. Missing or unparsable `published_at` has recency 0. A timestamp after `when` has recency 0. Do not substitute `when` for a missing timestamp.

Any fired channel with `transmission_score` < 7 is **assess**, not dropped. `show` is still ≥ 10 with a channel and no subject penalty. `assess` is 7–9, or any fired channel under 7.

Subject rules run first and zero every channel:

| Pattern | disposition | reason | penalty |
| --- | --- | --- | --- |
| `vietnam` and `gdp` | suppress | `local_non_g10_macro` | -8 |
| `india` and (`trade deficit` or `trade gap` or `import bill`) | suppress | `incidental_link_only` | -8 |
| `indonesia` and (`fire` or `forest`) | suppress | `local_non_g10_macro` | -8 |
| `podcast` or `golf` or `celebrity`, and no Hormuz/OPEC/Brent/WTI/crude supply role | suppress | `noise_non_market` | -10 |

India stays incidental even when the summary says oil, Middle East, or conflict. Indonesia stays suppressed even when the summary says palm oil.

Then these assignments. They are the locked examples, not suggestions:

| Story | Points | Score | Disposition | Reason |
| --- | --- | --- | --- | --- |
| Hormuz refusal / crude bounced (`won't soften`, `rejected`, `demands`, or `bounced`, plus Hormuz or crude) | oil 5, geopolitics 4, Brent+USD asset 3, shock 3 | 15 | show | `oil_supply_shock` |
| Hormuz reopening / diplomatic progress / easing tensions | oil 5, geopolitics 4, Brent asset 2, shock 2 | 13 | show | `oil_supply_shock` |
| China plus stimulus or property, and crude or commodity or demand | china 5, AUD+iron_ore asset 3, shock 2 | 10 | show | `china_commodity_spillover` |
| CoreWeave or (`cds` or `credit default`) plus (`ai` or `debt` or `distress`) | credit 5, credit_spreads+UST asset 3, shock 3 | 11 | show | `ai_capex_credit` |
| Chicago Fed or CFNAI or national activity index | usd_rates 5, USD asset 2, shock 0 | 7 | assess | `us_activity_index` |

Live Hormuz cluster tie-break is +3 (within 12h, live edge, Bloomberg) so salience is 18. Diplomacy baseline dated 2026-09-26 against cutoff 2026-09-27 18:00 ET is +0, salience 13. The Bloomberg id stays inside `top_market_driver_candidates`, which are the first three ids of salience-sorted `items`.

Other G10 policy or USD rates text (Fed, FOMC, ECB, BoE, BoJ, BoC, RBA, RBNZ, CPI, inflation, yields, Treasury) fires `g10_policy` and/or `usd_rates` at 5, plus asset 2 and shock 2 when a decision or inflation print is named, and follows the same thresholds. A bare oil/Brent/WTI/crude mention with no Hormuz pattern is oil 5 + Brent asset 2 = 7, **assess**, `oil_supply_shock`. China with no commodity and no AUD/NZD/JPY/EUR link is `hold-for-review`, score 0, `ambiguous_transmission`.

### 12.3 Recall, receipts, imports

`parse_surface` does **not** import `live_news` or call `recall_candidate`. It returns in-window items after path drops (`/video`, `/newsletter`, `/podcast`), after the official title filter, and after the host check. `raw_count` follows today’s candidate_count rules (Bing: after canonical host URL; Reuters sitemap: headline+loc; official RSS: item with title+link, before the title filter).

`live_news.acquire_current_news` calls `recall_candidate` and sets `result_count` to how many rows survive recall and the safety ceiling. Stage-1 failures are not candidates. `recall_candidate` is false for a **sole** `gdp` / `recession` / `unemployment` hit. Overlay does not use recall; it always calls `apply_transmission`.

Dedupe the acquire `candidates` list by URL so three Bing surfaces parsing one fixture do not triple `source_name == Bloomberg`. Per-receipt counts stay pre-dedupe.

Each surface is fetched in its own try. An unexpected URL raises into that receipt’s `failed` status only. `partial` is true only when one of source ids `bloomberg` and `reuters` failed and the other is `ok`. Offline returns before any fetch, with `skipped` receipts for every configured surface.

`attribute_country_codes` stays in `live_news.py` unchanged, including `UK Treasury bond sale` → `[]`. Stamp `country_codes` on candidates in `live_news` after parse. Do not add a GB code.

BoJ/BoE keep titles that contain `monetary policy`, `policy board`, `policy rate`, or `interest rate`, or that contain (`bank of japan` or `boj` or `bank of england` or `boe` or `gilt`) and (`rate` or `policy` or `inflation`). Do not keep a title merely because it contains `statement`.

Rows removed by the newest-60 ceiling are `discovery_failure` with reason `safety_ceiling`, not `presentation_suppression`. The shadow report does not claim to see HTML 6/3/12 drops.

`news_sources` may import `news_relevance` only if it does not call it. Prefer no import. `news_cluster` imports `news_relevance` only. `news_relevance` imports stdlib only. `accepted_news.py` may import `public_news_rows`.
