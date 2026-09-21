# Japan (JP) macro source contract — P2 / I3

Status: **ACTIVE** for JP temperature history (`scripts/japan_macro_data.py`, `scripts/harvest_jp_pmi.py`).  
Scope: **Japan (JPY / BOJ)**. No scoring in the collector.  
User-Agent: `MarketWatch-MarketState/1.0 (+https://github.com/McCabeAI/market-watch-public-dashboard)`; e-Stat downloads use `curl_cffi` chrome impersonation or `BROWSER_USER_AGENT` from `scripts.market_state`.

## Download patterns (verified 2026-09-21)

| Pattern | Example |
|---|---|
| e-Stat file download | `https://www.e-stat.go.jp/stat-search/file-download?statInfId={statInfId}&fileKind={0=xlsx,1=csv,4=xls}` |
| ESRI GDP SAAR CSV | `https://www.esri.cao.go.jp/jp/sna/data/data_list/sokuhou/files/2026/qe262_2/tables/nritu-jk2622.csv` |
| METI commerce survey | `https://www.meti.go.jp/statistics/tyo/syoudou/result/excel/DB_202607S.xlsx` |
| BOJ Tankan (context) | `https://www.boj.or.jp/en/statistics/tk/gaiyo/2026/tka2606.zip` |
| S&P PMI PDF | `https://www.pmi.spglobal.com/Public/Home/PressRelease/{guid}` |

e-Stat API 3.0 requires an `app-id`; **not used** (no key in repo). Public file downloads only.

---

## Scored components

### Inflation.headline — CPI all items y/y (2025 base)

| Field | Value |
|---|---|
| series_id | `CPI_2025BASE_ALL_ITEMS_YOY` |
| statInfId | `000032103932` |
| fileKind | `1` (CSV) |
| URL | `https://www.e-stat.go.jp/stat-search/file-download?statInfId=000032103932&fileKind=1` |
| units | percent, y/y |
| SA | No |
| frequency | Monthly |
| revision | Revisions with each CPI release; latest vintage in collector |
| lag | ~1 month |
| history | Long; window 2025-09 … 2026-09 |
| fetch | `estat_file_download_csv` |
| score_role | **scored** (`yoy_pct`, anchor 2.0 BOJ target, scale 12.5) |
| freshness | Latest month ≤ calendar − 1 |

### Inflation.underlying — CPI less fresh food & energy (core-core style)

| Field | Value |
|---|---|
| series_id | `CPI_2025BASE_LESS_FRESH_FOOD_ENERGY_YOY` |
| statInfId | `000032103932` (column 6 / “All items, less fresh food and energy”) |
| methodology_breaks | **2025-01**: 2025-base CPI; continuous official y/y in same table |
| score_role | **scored** (underlying 60% inflation weight) |

### Labor.unemployment — LFS unemployment rate SA

| Field | Value |
|---|---|
| series_id | `LFS_1A1_UNEMPLOYMENT_RATE_SA` |
| statInfId | `000031831358` |
| fileKind | `0` (xlsx), sheet `季節調整値` |
| URL | `https://www.e-stat.go.jp/stat-search/file-download?statInfId=000031831358&fileKind=0` |
| units | percent |
| SA | Yes |
| frequency | Monthly |
| revision | Annual benchmark / LFS revisions |
| lag | ~1 month |
| score_role | **scored** (70% labor) |

### Labor.wages — total cash earnings y/y (establishments ≥5)

| Field | Value |
|---|---|
| series_id | `MLS_TOTAL_CASH_EARNINGS_YOY_5PLUS` |
| statInfId | `000032189720` |
| fileKind | `4` (xls) |
| URL | `https://www.e-stat.go.jp/stat-search/file-download?statInfId=000032189720&fileKind=4` |
| units | percent y/y (現金給与総額 — scheduled + non-scheduled; overtime-sensitive) |
| SA | No (official series NSA) |
| frequency | Monthly |
| lag | ~1 month after survey month |
| score_role | **scored** (20% labor); contractual/scheduled-only series exists in same MHLW table set |
| calibration note | Wage “50” often mapped to ~3% (2% inflation + 1% productivity) in V1 docs — verify against `temperature_calibration.json` separately |

### Labor.employment — LFS employed persons SA, m/m Δ thousands

| Field | Value |
|---|---|
| series_id | `LFS_1A1_EMPLOYED_PERSONS_SA` |
| statInfId | `000031831358` (same file as unemployment) |
| units | thousands (derived: Δ employed persons in 万人 × 10) |
| SA | Yes (levels SA; change derived) |
| frequency | Monthly |
| score_role | **scored** (10% labor); AU-style scale 0.20 per thousand in calibration |

### Activity.gdp_domestic_demand — real GDP q/q % SAAR

| Field | Value |
|---|---|
| series_id | `ESRI_REAL_GDP_QOQ_SAAR` |
| URL (pinned) | `https://www.esri.cao.go.jp/jp/sna/data/data_list/sokuhou/files/2026/qe262_2/tables/nritu-jk2622.csv` |
| units | percent, q/q annualized (実質 GDP, first column of `nritu-jk*` table) |
| SA | Yes |
| frequency | Quarterly |
| revision | **Full history revises each quarterly release** |
| lag | ~1–2 months after quarter end |
| discovery | JP/EN `sokuhou_top.html` when reachable; else pinned CSV |
| score_role | **scored** (60% activity level = 2Q mean; impulse = latest quarter) |

### Activity.business_surveys — Japan Composite PMI

| Field | Value |
|---|---|
| series_id | `SP_GLOBAL_JP_COMPOSITE_PMI` |
| publisher | S&P Global / au Jibun Bank |
| sources | Flash Japan PMI PDF; **final** composite from Japan Services PMI final PDF prose |
| listing | `https://www.pmi.spglobal.com/Public/Release/PressReleases` |
| example GUIDs | Flash: `84f9fd5cee644a10b5c316097628ce76` (2026-03); Services/final: `55b418e617f34269b3e1b0f056317a30` (2026-08 composite 53.5) |
| units | diffusion index (>50 expansion) |
| SA | Yes (headline indices SA) |
| frequency | Monthly |
| revision | Final services release supersedes flash composite for same month |
| score_role | **scored** (40% activity; survey anchor 50) |
| gaps | 2025-09 … 2025-12, 2026-09 not recovered from public PDFs in initial harvest (listing/history) |

### Consumer.retail — METI Current Survey of Commerce

| Field | Value |
|---|---|
| series_id | `METI_CSC_RETAIL_SALES_YOY` |
| URL | `https://www.meti.go.jp/statistics/tyo/syoudou/result/excel/DB_202607S.xlsx` (roll forward `DB_{yymm}S.xlsx`) |
| sheet | `DB_MainC_Graph` |
| units | percent y/y |
| SA | Yes |
| score_role | **scored** (25% consumer basket) |

### Consumer.income — FIES worker households, nominal y/y

| Field | Value |
|---|---|
| series_id | `FIES_WORKER_HH_REAL_INCOME_NOMINAL_YOY` |
| statInfId | `000040270658` |
| row | `実収入` on sheet `名目増減率（月）` |
| units | percent y/y (nominal; label in e-Stat is real-income table family) |
| SA | No |
| score_role | **scored** |
| note | Worker households among two-or-more-person HH; not all-household income |

### Consumer.spending — FIES two+ HH consumption, nominal y/y

| Field | Value |
|---|---|
| series_id | `FIES_TWO_PLUS_HH_CONSUMPTION_NOMINAL_YOY` |
| statInfId | `000040270657` |
| row | `消費支出` |
| score_role | **scored** |

### Consumer.confidence — Cabinet Office Consumer Sentiment Index SA

| Field | Value |
|---|---|
| series_id | `CO_CONSUMER_SENTIMENT_INDEX_SA` |
| statInfId | `000040450603` |
| fileKind | `0` |
| units | index (diffusion-style; par ~50 TBD in calibration) |
| SA | Yes |
| score_role | **scored** |

---

## Context (not scored)

### context.Tankan_large_manufacturing_di

| Field | Value |
|---|---|
| series_id | `BOJ_TANKAN_LARGE_MFG_BUSINESS_CONDITIONS_DI` |
| URL | `https://www.boj.or.jp/en/statistics/tk/gaiyo/2026/tka2606.zip` |
| score_role | **context** / corroboration only (not monthly scored survey) |

---

## Unavailable / deferred

| Item | Status |
|---|---|
| e-Stat API 3.0 JSON | No `app-id` in repo — not used |
| stat.go.jp FIES longtime `kinh-n.xls` / `zenh-n.xls` | Stale (~2017); superseded by e-Stat 657/658 |
| Dedicated “Japan Composite PMI” listing row | Often absent from first listing page; use Flash + Services PDFs and seed GUIDs |
| PMI 2025-09 … 2025-12 | Not in initial `harvest_report.json` recovered set — extend GUID discovery / Wayback |
| PMI 2026-09 | Not yet released as of 2026-09-21 cutoff |

---

## Recommended calibration anchors (provenance only — do not edit `temperature_calibration.json` here)

| Parameter | Suggested anchor | Provenance |
|---|---|---|
| Inflation u* / target | 2.0% | BOJ price stability target |
| Underlying CPI | core-core less fresh food & energy | e-Stat `000032103932` |
| Unemployment u* | ~2.4% SA | LFS 2025–2026 window mean (~2.3–2.5%) |
| Wages “50” | ~3.0% y/y total cash | BOJ 2% + ~1% productivity rule-of-thumb; MHLW total cash series |
| Employment trend | ~+10–30k/mo SA Δ | LFS derived thousands |
| GDP potential SAAR | ~0.5–1.0% q/q SAAR | ESRI long-run post-2020 mean below cyclical 2026 prints |
| PMI survey | 50.0 | Standard diffusion neutral |
| Confidence par | ~50 (verify) | Cabinet Office index centered below 50 in 2025–26 — confirm in calibration pass |

---

## Revision / base-year notes

- **CPI**: 2025-base from 2025-01; headline and core-core y/y in one official CSV.
- **GDP**: ESRI quarterly flash/final revisions change entire SA history each release.
- **PMI**: Flash composite preliminary; Japan Services final PDF restates prior month and headline composite level.
- **FIES / METI / MHLW**: Routine revisions on benchmark updates; collector stores latest vintage only.
