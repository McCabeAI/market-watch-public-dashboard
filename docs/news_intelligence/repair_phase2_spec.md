# Phase 2 — targeted implementation spec (four parallel workstreams)

## Binding amendments (independent challenge, 2026-10-17)

These override any PASS wording below that conflicts.

1. **Gate 1 stays UNRESOLVED BLOCKER** for `https://www.cnbc.com/2026/10/15/coreweave-credit-default-swaps-hit-distress-levels-as-investors-sour-on-ai-debt.html` during `[2026-10-15T16:52:16Z, 2026-10-16T16:52:16Z]`. Wayback CDX for `cnbc.com/sitemap_news.xml` from 20261015–20261017 was `[]`. Wayback HTML captures of the article (`20261015165635`, `20261016014202`, `20261016180248`) prove the page existed. They are not a sitemap or Bing body. A CNBC parser fixture and a sitemap wired on 17 Oct do not pass gate 1. Still add the forward CNBC surface.
2. **Gate 3 is not a pass on recall alone.** `score_transmission` must return `assess` or `show` (not `hold-for-review`) for bank rate, gilt, money market operations, complementary deposit facility, official cash rate, and intervention wording. Recall `monetary policy meeting` and `monetary policy summary`, not bare `monetary policy` (that would keep “Monetary Policy Committee dates for 2027”). RBNZ stays unresolved: no verified 2xx feed. Do not add one. BoC/RBA RDF stays residual.
3. **Palm oil is not an oil-supply role.** `_word(oil)` matches `palm oil`. Indonesia fires plus “palm oil exports” must stay `suppress`. India import-bill fixture stays `suppress`.
4. **Gate 4:** `published` is only for rows the refresh partition actually places in the 6, 3, or 12. Do not stamp `published` on `merged["items"]`. Cap-24 losses stay `presentation_suppression` in `stories` and are not `research_top_24`. Call `_partition_items` and the same slice points as `_last24_html` / `_dated_rollup_html`. Do not bump accepted-news `schema_version`.
5. **Gate 5:** facet splits and the Ormuz alias are the targeted pass. Same-facet pairs with ≥4 shared tokens still merge below Jaccard 0.55 (required for the CDS wires). Any other same-facet join of a different incident is a residual, not a full pass.


Evidence base: `docs/news_intelligence/repair_phase1_*.md`, `docs/NEWS_INTELLIGENCE_REPAIR.md`. Do not contradict verified HTTP results. Unverified historical feed bodies → **UNRESOLVED**, not assumed.

**Deliverable:** code + tests only as scoped below. **Do not** mutate `data/overnight/accepted_public_news.json`, workflows, ACP, credentials, or run full Market Watch / deploy.

---

## File ownership (no overlap)

| Workstream | Owns | Must not edit |
| --- | --- | --- |
| **A** | `scripts/overnight/news_sources.py`, `scripts/overnight/live_news.py` (**only** `acquire_current_news` allowed-host wiring, see A.3), `tests/test_news_sources_repair.py` (new) | `news_relevance.py`, `news_cluster.py`, `news_diagnostics.py`, `accepted_news.py`, refresh/smoke except as noted |
| **B** | `scripts/overnight/news_relevance.py`, `tests/test_news_intelligence.py` | All other production modules |
| **C** | `scripts/overnight/news_cluster.py`, `tests/test_news_cluster_repair.py` (new) | `news_relevance.py` (import only), all other production modules |
| **D** | `scripts/overnight/news_diagnostics.py`, `scripts/live_news_discovery_smoke.py`, `scripts/apply_overnight_news_refresh.py`, `scripts/overnight/accepted_news.py`, `tests/test_news_publication_trail.py` (new) | `news_relevance.py`, `news_cluster.py`, `news_sources.py`, `live_news.py`, `collect.py`, `assemble.py`, workflows, `accepted_public_news.json` |

**Shared rule:** behavior that lives in one file is implemented only by that file’s owner. Other streams call public functions or mirror formulas explicitly documented here—no cross-owner edits.

**Integration order:** Land **A**, **B**, and **C** together (disjoint files). Land **D** after or with them; D must not require changes in A/B/C. C may `from scripts.overnight.news_relevance import …` private helpers (`_word`, `_any_phrase`, `_hormuz_mentioned`, `_hormuz_acute`, `_hormuz_diplomatic`) but must not modify that module.

---

## Workstream A — discovery, CNBC surface, BoJ/BoE title filter

### A.1 `discovery_surfaces()` — new non-required surfaces

Add entries in `scripts/overnight/news_sources.py` → `discovery_surfaces()` (after existing rows, before `fed_monetary` or grouped with other non-required feeds). **Do not** add any id to `REQUIRED_SOURCES` in `live_news.py` (`bloomberg`, `reuters` only). **`partial` semantics unchanged.**

| `source` | `kind` | `surface` | `source_name` | Notes |
| --- | --- | --- | --- | --- |
| `cnbc` | `cnbc_sitemap` | `https://www.cnbc.com/sitemap_news.xml` | `CNBC` | Verified HTTP 200 Google news sitemap (`repair_phase1_B`). |
| `cnbc_credit` (optional Bing) | `bing_rss` | `_bing_surface(CNBC_CREDIT_QUERY)` | `CNBC` | Optional; prefer sitemap over section RSS. |

**Do not add:** Bloomberg markets firehose (`feeds.bloomberg.com/markets/news.rss`), RBNZ (all `rbnz.govt.nz` URLs returned **403** in phase 1), CNBC section RSS firehoses from phase 1B table.

**`REUTERS_CREDIT_QUERY`:** extend with `CoreWeave`, `CDS`, `"credit default"` (OR-group with existing private-credit terms). This improves forward Reuters Bing recall for credit wires; it **does not** recover the Oct 15 CNBC URL and is not historical proof.

**`CNBC_CREDIT_QUERY` (suggested, adjust only if Bing returns garbage):**  
`site:cnbc.com (CoreWeave OR CDS OR "credit default" OR "credit default swap")`  
Same `format=rss` + 7-day `qft` as `_bing_surface`.

### A.2 Parsers (`parse_surface`, private parsers)

**Owner:** `news_sources.py` only.

1. **`_parse_cnbc_sitemap`** (new), wired from `parse_surface` when `kind == "cnbc_sitemap"`:
   - Same **24h window** as `_parse_reuters_sitemap`: `window_start = cutoff - 24h`, inclusive endpoints, reasons `window` / `unparsed_date`.
   - Require `news:publication/news:name` (or equivalent) **CNBC**; else `publication_name` drop (mirror Reuters).
   - `summary`: constant headline-only string (e.g. `CNBC_HEADLINE_ONLY = "Headline-only public metadata; article body was not retrieved."`) — **no article HTML fetch.**
   - `source_name`: `CNBC`, `distribution_weight`: `standard`.
   - Path block via existing `_path_blocked`.

2. **`_canonical_from_bing_link`:** allow host ending with **`cnbc.com`** (in addition to `bloomberg.com`, `reuters.com`).

3. **`_bing_rss`:** unchanged contract; `allowed_hosts` tuple must include `cnbc.com` for `cnbc_credit` surface.

### A.3 `live_news.py` — minimal host wiring (A only)

`_allowed_hosts_for_surface` today (`live_news.py:196-201`) returns only `reuters.com` / `bloomberg.com`. **A** adds:

- In `discovery_surfaces()` entries: optional key **`allowed_hosts`**, e.g. `("cnbc.com",)` for `cnbc_credit`.
- In `acquire_current_news` (~287):  
  `allowed_hosts = tuple(entry.get("allowed_hosts") or ()) or _allowed_hosts_for_surface(source, kind)`  
  Extend `_allowed_hosts_for_surface` so `source == "cnbc_credit"` → `("cnbc.com",)`.

**No other `live_news.py` edits** (recall, ceiling, dedupe stay as-is).

### A.4 BoJ/BoE title filter — `_boj_boe_title_kept`

Add **substring** phrases (case-insensitive, same style as existing list):

- `bank rate`
- `money market operations`
- `complementary deposit facility`
- `financial stability`
- `intervention`
- `official cash rate`

**Do not add:** bare `minutes`, `statement`, `speech`, `bank of japan`, `summary of opinions` (unless product later asks—out of scope here).

**Regression (must stay green in `tests/test_news_intelligence.py`, owned by B):**

| Title | Title filter |
| --- | --- |
| Monetary Policy Meeting statement | **keep** |
| Services Producer Price Index for August | **drop** (`official_title_filter`) |
| Asset Purchase Facility: Gilt Sales – Market Notice | **keep** (`gilt`) |

New assertions for A go in **`tests/test_news_sources_repair.py`** (call `_boj_boe_title_kept` / `parse_surface` with fixtures).

### A.5 BoC/RBA RDF (residual unless trivial)

`boc_press` / `rba_media` return `raw_count` 0 because `_parse_rss_official` expects RSS 2.0 `channel` (`repair_phase1_D`). **Optional:** if A can add **≤15 lines** in `_parse_rss_official` to read RSS 1.0 RDF items **without** widening recall noise, do it. If it risks pulling unrelated press into candidates without B’s transmission gates, **leave residual** documented in A’s PR note. Do not wire new URLs.

### A.6 Historical gate — Oct 15 CNBC CoreWeave CDS (honest)

**Article (verified HTTP 200, phase 1A):**

- URL: `https://www.cnbc.com/2026/10/15/coreweave-credit-default-swaps-hit-distress-levels-as-investors-sour-on-ai-debt.html`
- `article:published_time`: `2026-10-15T16:52:16Z`

**Diagnosis-time fact:** live `https://www.cnbc.com/sitemap_news.xml` oldest `n:publication_date` was `2026-10-15T18:55:01-04:00` (~2h after publication). The URL was **not** in that sitemap body on 2026-10-17.

| Claim | Expected after Phase 2 |
| --- | --- |
| Forward: CNBC sitemap surface emits in-window CNBC rows | **PASS** (parser + unit fixtures) |
| Forward: optional Bing `cnbc_credit` can emit `cnbc.com` when Bing lists them | **PASS** when Bing returns items (live may be empty-ok) |
| Historical: that exact URL discoverable from saved feed in `[2026-10-15T16:52:16Z, 2026-10-16T16:52:16Z]` | **UNRESOLVED BLOCKER** unless archived sitemap (or Bing RSS) body from that interval is obtained and contains the URL |
| Scoring CDS headline `show` / `ai_capex_credit` | **PASS** (B; injected strings only—not recall proof) |

**Do not** fabricate a historical sitemap containing the URL and call it proof. Injected XML in `test_news_sources_repair.py` proves **parser** behavior only.

### A.7 Tests — `tests/test_news_sources_repair.py`

- CNBC sitemap fixture: in-window row kept, `publication_name` ≠ CNBC dropped, 24h window, headline-only summary.
- `_canonical_from_bing_link` accepts CNBC Bing redirect URL.
- `parse_surface` + `allowed_hosts=("cnbc.com",)` for Bing fixture.
- Title filter cases above + new phrases (e.g. synthetic “Bank rate maintained at 3.75%” **keep**; “Foreign exchange intervention operations” **keep**).
- Extended `REUTERS_CREDIT_QUERY` appears in `discovery_surfaces()` entry for `reuters_credit` (string contains new tokens).

---

## Workstream B — transmission, recall, CoreWeave

**Owner:** `scripts/overnight/news_relevance.py`, `tests/test_news_intelligence.py`.

### B.1 `transmission_role` / subject suppress

Refactor `_subject_rule` (`news_relevance.py:112-164`) so Vietnam GDP, India trade phrases, and Indonesia fire suppress **only when no transmission role**.

Implement **`_oil_supply_role(text)`** (name may vary; behavior fixed):

```text
_hormuz_mentioned(text)   # hormuz, ormuz, estreito de ormuz
OR _word(text, "opec")
OR (
    _any_word(text, ("oil", "crude", "brent", "wti"))
    AND _any_word(text, ("export", "exports", "halt", "halts", "embargo", "blockade", "outage", "shutdown", "supply"))
)
```

**Bare `oil` alone is NOT a supply role** (India import-bill fixture must stay suppress).

**`_transmission_role(text)`** = `_oil_supply_role(text)` OR existing channel predicates the subject rule should respect: at minimum `_credit_funding`, `_ai_financing_recall`, `_g10_policy_fires`, `_usd_rates_fires`, `_fiscal_interest`, and sanctions with `_energy_context` (same as phase 1C §5).

Apply:

```text
if (vietnam_gdp or india_trade or indonesia_fire) and not _transmission_role(text):
    suppress as today
else:
    fall through (do not return suppress for that subject)
```

**Acceptance examples** (`score_transmission(headline, summary)`):

| Input | Disposition | reason_code |
| --- | --- | --- |
| `INDIA_HEADLINE` + `INDIA_SUMMARY` (fixtures) | `suppress` | `incidental_link_only` |
| `India oil-export halt widens the trade deficit` + crude/Brent in blob | `assess` or `show` (Hormuz acute → `show` 15) | **not** `incidental_link_only` |
| `Vietnam Prime Minister Targets…GDP…` + parliament summary | `suppress` | `local_non_g10_macro` |
| `Vietnam GDP slump cuts crude exports` / export halt + Brent | not suppress; oil path | `oil_supply_shock` (assess 7 if no Hormuz acute) |
| Indonesia fixtures (fires + palm oil) | `suppress` | `local_non_g10_macro` |
| `Indonesia refinery fire halts crude exports` | not suppress | `oil_supply_shock` |
| Palm-oil-only export story (no fire token) | not subject fire rule | unchanged assess path |

### B.2 Noise — Ormuz escape

`_noise_would_suppress` and `_subject_rule` supply escape: use **`_hormuz_mentioned(text)`** instead of the hormuz-only tuple (`repair_phase1_C`). Podcast + Ormuz in headline → not noise suppress.

### B.3 CoreWeave — `_coreweave_rule` and recall

1. **`_coreweave_rule`:** remove `if _word(text, "coreweave"): return True`. Keep CDS branch: `(cds or credit default) and (ai|debt|distress|coreweave)`.

2. **`_recall_positive_classes`:** remove issuer-only `if _word(text, "coreweave"): return True` (lines ~570-571).

3. **Score 11 / `show` / `ai_capex_credit`:** only when credit/CDS/AI-debt/**financing** channel present—via existing `_coreweave_rule` (second disjunct), `_ai_financing_recall`, or CDS + ai/debt/distress path in `score_transmission` (~381-394, ~545-558). **Do not** assign 11 on name alone.

| Headline | disposition | reason_code |
| --- | --- | --- |
| `COREWEAVE_HEADLINE` (CDS fixture) | `show` | `ai_capex_credit` |
| `CoreWeave opens a London office` | `hold-for-review` (or assess if another channel fires) | **not** `ai_capex_credit` |
| `Analysis:Why CoreWeave is in the crosshairs of the AI scare` | `hold-for-review` | **not** `ai_capex_credit`; recall false unless financing tokens added |

### B.4 Recall tokens for official titles (stage 1)

In `_recall_positive_classes`, add phrase/substring recall (headline + summary blob) for tokens the title filter keeps—**without** recalling all BoJ statistics:

Add: `monetary policy`, `bank rate`, `gilt`, `official cash rate`, `money market operations`, `complementary deposit facility`, `financial stability`, `intervention`.

**Must stay not recalled:** `Services Producer Price Index` (no new broad stat tokens). **`Indicators for Core CPI`** may still recall via existing `cpi` token—do not expand CPI logic.

### B.5 Tests — `tests/test_news_intelligence.py`

- **Update** `test_coreweave_shows_without_macro_tokens`: CDS assertions unchanged; scare headline **not** `ai_capex_credit`; recall false for scare (after recall shortcut removed).
- **Add:** India oil-export retained despite `trade deficit` in same blob.
- **Add:** Vietnam GDP suppress; Vietnam GDP + `oil_supply_role` retained.
- **Add:** India/Vietnam oil-supply retention cases (phase 1C table).
- **Keep green:** Chicago Fed, China stimulus, Hormuz/Ormuz ordering, sanctions/fiscal, overlay order, India oil-color discovery test, public_rows immutability, diagnostics stages, BoJ title tests (filter side exercised via parse in same file), safety ceiling, post-assessment cap.

---

## Workstream C — clustering facets

**Owner:** `scripts/overnight/news_cluster.py` — edit **`_tokenize_headline`** and **`_same_event` only** (`repair_phase1_F`).

### C.1 Tokenizer

After regex tokenization and `DEDUP_STOP` removal: map token **`ormuz` → `hormuz`**.

### C.2 Facets (headline string only)

Compute facet label (first match wins) using imports from `news_relevance`:

| Facet | Rule |
| --- | --- |
| `india_trade` | `_word(india)` and `_any_phrase(trade deficit, trade gap, import bill)` |
| `india_oil` | `_word(india)` and (`oil`/`crude`/`hormuz`/`supply` via `_word`/`_any_word`) and not `india_trade` |
| `vietnam_gdp` | `_word(vietnam)` and `_word(gdp)` |
| `vietnam_oil` | `_word(vietnam)` and oil/crude/hormuz/supply and not `vietnam_gdp` |
| `hormuz_diplomacy` | `_hormuz_mentioned` and `_hormuz_diplomatic` and not `_hormuz_acute` |
| `hormuz_supply` | `_hormuz_mentioned` otherwise |
| `coreweave_cds` | token `coreweave` and (`cds` or phrases credit default / `debt` / `distress` in headline) |
| `coreweave_other` | token `coreweave` else |
| `""` | none |

**Issuer bit:** `coreweave` present on a side → non-empty bit; else empty.

### C.3 `_same_event(a, b)` (after alias tokens)

1. Both facets non-empty and different → **false**.
2. Exactly one side has `coreweave` token → **false**.
3. Shared tokens &lt; 4 → **false**.
4. Both facets non-empty and equal → **true** (even if Jaccard &lt; 0.55 — fixes CDS pair at 0.545).
5. Else Jaccard ≥ **0.55** (unchanged).

Do **not** add models, dependencies, or new modules. Do **not** edit `news_relevance.py`.

### C.4 Tests — `tests/test_news_cluster_repair.py` (from phase 1F §3)

1. `test_hormuz_supply_does_not_merge_with_diplomacy` — two items.
2. `test_coreweave_cds_wires_merge` — one item, two URLs.
3. `test_coreweave_cds_does_not_merge_unrelated_ai` — CoreWeave vs Nvidia boilerplate → two clusters.
4. `test_india_trade_gap_does_not_merge_oil_shock` — both display orders; trade stays `incidental_link_only`, Hormuz/oil stays `show`.
5. `test_vietnam_gdp_does_not_merge_g10_oil` — both display orders.
6. `test_ormuz_alias_merges_with_hormuz_wire` — one item.
7. Keep **`test_same_event_keeps_bloomberg_edge`** behavior (live_news or news_intelligence)—C tests call `cluster_and_rank` / `merge_live_news` directly.

Use `cluster_and_rank` with fixed `CUTOFF` like existing tests.

---

## Workstream D — publication trail (`publication_rows`)

**Owner files listed above. Do not change HTML output or accepted envelope keys.**

### D.1 Shadow report sidecar

Extend `build_report` / `write_report` in `news_diagnostics.py`:

- Add top-level **`publication_rows`** (list). Bump `SCHEMA_VERSION` if tests lock version.
- **Do not** add stages to `stories[]` that `_extra_row_stories` would strip.
- **Do not** add keys to `build_accepted_public_news` envelope.

Row shape (phase 1E):

| Field | Values |
| --- | --- |
| `headline`, `url`, `source`, `published_at` | same as `StoryRow` |
| `id` | `news:` + 16 hex after cluster, else null |
| `family` | `news` \| `central_bank_research` |
| `outcome` | see below |
| `reason` | existing reason string (no parallel taxonomy) |
| `cap` | `60`, `24`, `6`, `3`, `12`, or null |
| `slot` | `last_24_hours`, `top_market_drivers`, `digest_stories`, or null |

**Terminal outcomes:**

| Outcome | Meaning |
| --- | --- |
| `not_fetched` | No candidate/drop row; receipt `failure` or absent from acquire |
| `fetched_filtered` | Parse/recall/ceiling before score (`path_drop`, `window`, `official_title_filter`, `stage1_recall`, `safety_ceiling`, …) |
| `scored_suppress` | `suppress` / `hold-for-review` in merge diagnostics |
| `research_top_24` | In merged `items` (research pool)—**not** webpage |
| `overlay_drop` | Dropped by `public_news_rows` inside overlay |
| `display_slot_drop` | In overlay-kept list but not in slot slice |
| `published` | Emitted to **≥1** HTML slot |

**`published`:** row appears in at least one of:

- **6** — Last 24 Hours (`_last24_html`)
- **3** — Top Market Drivers (`_dated_rollup_html` / `_undated_block_html`)
- **12** — Digest (`digest[:12]` / undated supplement)

**`research_top_24` ≠ `published`.**

One row may need **multiple** `publication_rows` elements (same identity, different `slot` / outcome).

### D.2 Pure partition explainer (no full Market Watch run)

Add a **pure function** (prefer in `apply_overnight_news_refresh.py` so slice math stays single-sourced):

- e.g. `explain_display_slots(items: list[dict], *, cutoff: datetime) -> list[dict]`
- Input: overlay-kept `agent_research` shape (news + central_bank_research items), same normalization as `_partition_items` / `_normalize_raw_item`.
- **Call or mirror** `_partition_items`, `_last24_html` row selection (first 6 dated in 24h), driver `[:3]`, digest `[:12]` — **identical** ordering and dedupe to `apply_overnight_news_refresh.py:100-134`, `:215-217`, `:261-278`, `:296-307`, `:330-342`.
- If extracting helpers would force editing another owner’s file, **duplicate the slice formulas in D’s file** with a comment pointing to refresh line numbers and a test that locks parity.

Map drops to `display_slot_drop` reasons: `outside_24h`, `beyond_6`, `beyond_3`, `outside_7d`, `beyond_12`, `deduped`, `malformed_timestamp`, `missing_title_or_summary`, `dated_digest_full`.

### D.3 `overlay_accepted_research` / `accepted_news.py`

`public_news_rows` returns kept rows only. **D** may add a sibling helper, e.g. `overlay_drop_rows(packet_news) -> list[dict]`, comparing input vs output **inside `accepted_news.py`** without changing returned news list or envelope. Wire `publication_rows` with `outcome=overlay_drop` and transmission `reason_code`.

### D.4 `build_report` orchestration

Given `acquisition`, `merge`, optional `packet_news` / overlay-kept list:

1. Map `story_drops` + merge `diagnostics_rows` → `fetched_filtered` / `scored_suppress` / `research_top_24`.
2. If packet provided, run overlay drop recorder.
3. If kept list + cutoff provided, run `explain_display_slots` → `published` / `display_slot_drop`.

**`live_news_discovery_smoke.py`:** after `build_report`, pass merge output + optional explainer on merged items. **Still no** collect, assemble, or `accepted_public_news.json` write. May attach `publication_rows` for research pool + display projection from empty baseline.

### D.5 Tests — `tests/test_news_publication_trail.py`

- Fixture scored items: assert `research_top_24` vs `presentation_suppression` vs slot outcomes.
- Overlay: suppress row → `overlay_drop`, assess row → kept then slot assignment.
- `published` requires slot membership; top-24 only → not `published`.
- Existing `tests/test_overnight_news_refresh.py`, `tests/test_accepted_news_architecture.py` stay green without edits.

---

## Gate checklist (expected after Phase 2)

Honest status for replay corpus (`docs/NEWS_INTELLIGENCE_REPAIR.md` § Replay).

| # | Gate | After implementation |
| --- | --- | --- |
| 1 | **CoreWeave CDS distress** — Oct 15 CNBC URL in live discovery during its 24h window | **UNRESOLVED BLOCKER** for that specific URL without archived sitemap/Bing body in `[2026-10-15T16:52:16Z, 2026-10-16T16:52:16Z]`; **PASS** forward CNBC surface + scorer on injected headline |
| 2 | **CoreWeave “AI scare”** — no `show` on issuer name alone | **PASS** (`hold-for-review` / dropped at overlay) |
| 3 | **Vietnam GDP** domestic headline | **PASS** `suppress` / `local_non_g10_macro` |
| 4 | **India trade deficit** import-bill fixture | **PASS** `suppress`; **PASS** retain India crude-export halt when `oil_supply_role` present (B + C no false merge) |
| 5 | **Indonesia fires** (palm oil in summary only) | **PASS** `suppress` |
| 6 | **Hormuz** — refusal vs diplomacy salience; Ormuz recall; supply≠diplomacy cluster | **PASS** (B ordering + C facets); **residual:** Portuguese IRGC headline still zero-token cluster with English wire |

**Residuals (not gates):** Reuters headline-only body, post-score cap 24, HTML 6/3/12, RBNZ 403, BoC/RBA RDF if not fixed, Bloomberg 403 on direct article GET, thin-day sanctions `assess`.

---

## Phase 4 — historical replay (manual, not fixtures-as-proof)

When validating gate 1 historically:

1. **Fetch live** (save raw bytes + UTC timestamp + user-agent `DISCOVERY_USER_AGENT`):
   - `https://www.cnbc.com/sitemap_news.xml`
   - Optional: Bing RSS for extended `reuters_credit` and `cnbc_credit` queries (same URL shape as `_bing_surface`).
2. **Search bodies** for:
   - CNBC URL above, or
   - Verified `reuters.com` / `bloomberg.com` canonical URL for the same story (phase 1A: no verified Reuters canonical; Bloomberg GET 403).
3. **Record:** present / absent / oldest sitemap `publication_date` vs `2026-10-15T16:52:16Z`.
4. If no archive from the 24h window after publication → gate 1 remains **UNRESOLVED BLOCKER** for that URL; forward CNBC wiring still ships.

**Do not** treat unit-test XML as historical recall proof.

---

## Test command (full suite after all streams)

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

---

## Out of scope

ACP files, workflows, launch contracts, credentials, `data/overnight/accepted_public_news.json` mutation, full Market Watch run, merge/deploy, new dependencies, Bloomberg markets firehose, RBNZ scrape, FT/WSJ feeds, article HTML for CNBC/Reuters bodies, changing `presentation_caps` application in `news_cluster.py`, editing `collect.py` / `assemble.py` / `publish.py` for trail.

---

## Quick acceptance matrix (cross-stream)

| Headline / scenario | Expected end state |
| --- | --- |
| Oct 15 CNBC CDS URL, cutoff Oct 16 12:00 ET, **no archive** | Not in candidates; publication trail `not_fetched` or `fetched_filtered` (window/sitemap gap)—not `published` |
| CNBC CDS headline injected as candidate | `show` / `ai_capex_credit`; cluster CDS wires → **1** item (C) |
| AI scare headline | recall false; overlay drop or `hold-for-review` |
| Vietnam GDP headline | `suppress`; cluster vs oil wire → **2** items (C) |
| India import bill fixture | `suppress`; remains in discovery tests |
| India export halt + trade deficit text | `assess`/`show` oil; **2** cluster items if both headlines present |
| Hormuz supply vs diplomacy (Jaccard 0.6) | **2** items (C) |
| Official “Bank rate maintained…” + recall tokens (B) | passes title filter (A) + `recall_candidate` true (B) |
| In research top-24 but rank 25+ for HTML | `research_top_24` or `display_slot_drop`, not `published` |
