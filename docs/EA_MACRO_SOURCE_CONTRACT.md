# Euro-area (EA) macro source contract — P1 / I2

Status: **ACTIVE** for EA temperature history collector (`scripts/euro_area_macro_data.py`, `scripts/harvest_ea_pmi.py`).  
Scope: **Euro area (ECB/EUR)**, not EU27, not Germany-only.  
User-Agent: `MarketWatch-MarketState/1.0 (+https://github.com/McCabeAI/market-watch-public-dashboard)`

## API patterns (verified in Cloud Agent environment)

| API | Example (fetched 2026-09-21) |
|---|---|
| Eurostat statistics JSON | `https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/PRC_HICP_MANR?geo=EA&coicop=CP00&sinceTimePeriod=2025-09` |
| Eurostat SDMX 2.1 JSON | `https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/une_rt_m/M.SA.TOTAL.PC_ACT.T.EA21?format=JSON&startPeriod=2025-09` |
| Eurostat SDMX CSV | `https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/prc_hicp_manr/M.RCH_A.CP00.EA?format=SDMX-CSV&startPeriod=2025-09` |
| ECB Data Portal SDMX CSV | `https://data-api.ecb.europa.eu/service/data/INW/Q.I10.N.INWR.000000.4F0.GY.IX?format=csvdata&startPeriod=2024-Q1` |
| S&P PMI listing | `https://www.pmi.spglobal.com/Public/Release/PressReleases` |
| S&P PMI PDF | `https://www.pmi.spglobal.com/Public/Home/PressRelease/0a3fb112708046bba18d27b555ce7ecb` |

---

## Scored components

### Inflation.headline — HICP all-items y/y

| Field | Value |
|---|---|
| series_id | `PRC_HICP_MANR.M.RCH_A.CP00.EA` |
| dataset | `prc_hicp_manr` |
| SDMX key | `M.RCH_A.CP00.EA` |
| statistics URL | `.../statistics/1.0/data/PRC_HICP_MANR?geo=EA&coicop=CP00&sinceTimePeriod=2025-09` |
| geo | **EA** (Eurostat euro-area aggregate). **EA21** returned empty for HICP y/y at collect time. |
| unit | `RCH_A` (annual rate of change) |
| SA | No (y/y rate) |
| frequency | Monthly |
| revision | Eurostat revises with each HICP release; collector stores latest vintage |
| expected lag | ~1 month (flash/final HICP cycle) |
| history start | 1996+ (dataset); window backfill from 2025-09 |
| fetch method | `eurostat_statistics_api` (+ SDMX JSON equivalent) |
| score_role | **scored** (`yoy_pct`, anchor 2.0, scale 12.5 per V1) |
| freshness | Latest month ≤ calendar month − 1 |

### Inflation.underlying — HICP ex energy, food, alcohol & tobacco y/y

| Field | Value |
|---|---|
| series_id | `PRC_HICP_MANR.M.RCH_A.TOT_X_NRG_FOOD.EA` |
| dataset | `prc_hicp_manr` |
| COICOP (ECOICOP 2018 v2) | `TOT_X_NRG_FOOD` — "Overall index excluding energy, food, alcohol and tobacco" |
| statistics URL | `.../PRC_HICP_MANR?geo=EA&coicop=TOT_X_NRG_FOOD&sinceTimePeriod=2025-09` |
| geo | **EA** |
| unit | `RCH_A` |
| SA | No |
| frequency | Monthly |
| revision | Same as headline HICP |
| expected lag | ~1 month |
| fetch method | `eurostat_statistics_api` |
| score_role | **scored** (underlying 60% weight) |
| freshness | Same as headline |

---

### Labor.unemployment

| Field | Value |
|---|---|
| series_id | `UNE_RT_M.M.SA.TOTAL.PC_ACT.T.EA21` |
| dataset | `une_rt_m` |
| SDMX key | `M.SA.TOTAL.PC_ACT.T.EA21` |
| statistics URL | `.../UNE_RT_M?geo=EA21&sex=T&s_adj=SA&age=TOTAL&unit=PC_ACT&sinceTimePeriod=2025-09` |
| geo | **EA21** (Euro area – 21 countries from 2026) |
| unit | `PC_ACT` (%) |
| SA | Yes (`SA`) |
| frequency | Monthly |
| revision | LFS revisions at benchmark/annual re-estimation |
| expected lag | ~1 month |
| fetch method | `eurostat_statistics_api` / SDMX JSON |
| score_role | **scored** |
| freshness | Latest month in window |

### Labor.wages — ECB negotiated wages y/y

| Field | Value |
|---|---|
| series_id | `INW.Q.I10.N.INWR.000000.4F0.GY.IX` |
| flow | `INW` |
| ECB URL | `https://data-api.ecb.europa.eu/service/data/INW/Q.I10.N.INWR.000000.4F0.GY.IX?format=csvdata` |
| geo / ref | `I10` = EA21 fixed composition from 2026-01-01 (ECB metadata title) |
| unit | Annual rate of change (`GY` transformation, index `IX`) |
| SA | NSA (neither seasonally nor working-day adjusted) |
| frequency | Quarterly |
| revision | ECB revises with new agreements / data updates |
| expected lag | ~1 quarter |
| fetch method | `ecb_sdmx_csvdata` |
| score_role | **scored** |
| freshness | Latest published quarter |

### Labor.employment — LFS employment q/q Δ thousands (derived)

| Field | Value |
|---|---|
| series_id | `LFSI_EMP_Q.Q.SA.EMP_LFS.T.Y15-74.THS_PER.EA21` (levels); derived `..._derived_qq_thousands` |
| dataset | `lfsi_emp_q` |
| statistics URL | `.../LFSI_EMP_Q?geo=EA21&indic_em=EMP_LFS&sex=T&age=Y15-74&s_adj=SA&unit=THS_PER` |
| geo | **EA21** |
| unit | Thousands of persons (levels); **derived q/q change in thousands** |
| SA | Yes |
| frequency | Quarterly (no official EA monthly employment Δ thousands in contract) |
| revision | LFS benchmark revisions |
| expected lag | ~1 quarter |
| fetch method | `eurostat_statistics_api_derived` |
| score_role | **scored** (document scale_per_unit for parent: q/q thousands) |
| freshness | Latest quarter |

---

### Activity.gdp_domestic_demand — real GDP q/q %

| Field | Value |
|---|---|
| series_id | `NAMQ_10_GDP.Q.CLV_PCH_PRE.SCA.B1GQ.EA21` |
| dataset | `namq_10_gdp` |
| SDMX key | `Q.CLV_PCH_PRE.SCA.B1GQ.EA21` |
| SDMX URL | `.../sdmx/2.1/data/namq_10_gdp/Q.CLV_PCH_PRE.SCA.B1GQ.EA21?format=JSON&startPeriod=2024-Q1` |
| geo | **EA21** (same values as EA20 for this key in live probe) |
| unit | `CLV_PCH_PRE` (chain-linked volumes, q/q %) |
| SA | **SCA** (seasonally and calendar adjusted) — `SA` alone returned empty |
| frequency | Quarterly |
| revision | Full national accounts revision schedule |
| expected lag | ~2 months after quarter-end |
| fetch method | `eurostat_sdmx_json` |
| score_role | **scored** (`mean_qoq_to_saar_n2` / `qoq_to_saar` per V1) |
| freshness | Latest flash/estimate quarter |

### Activity.business_surveys — S&P Eurozone Composite PMI

| Field | Value |
|---|---|
| series_id | `SP_GLOBAL_EA_COMPOSITE_PMI` |
| publisher | S&P Global |
| listing | `https://www.pmi.spglobal.com/Public/Release/PressReleases` |
| title filter | Exact `S&P Global Eurozone Composite PMI` (English); exclude Deutsch/Français/Germany/EU |
| PDF example | `.../PressRelease/0a3fb112708046bba18d27b555ce7ecb` (Aug 2026 final, collected 2026-09-03) |
| unit | Diffusion index (anchor 50) |
| SA | Yes (as published) |
| frequency | Monthly |
| revision | Final replaces flash; prior months may be restated in later PDFs |
| expected lag | ~3 business days into following month |
| fetch method | `curl_cffi` PDF + committed `data/temperature_history/raw/ea/` + Wayback `id_` fallback |
| score_role | **scored** |
| freshness | Latest final (or flash if final missing, flagged `preliminary`) |
| **Gap note** | Public listing currently exposes **one** English composite row; historical months need committed PDFs / Wayback (documented in `harvest_report.json`). |

---

### Consumer.retail — retail trade volume m/m %

| Field | Value |
|---|---|
| series_id | `STS_TRTU_M.M.SCA.VOL_SLS.G47.PCH_PRE.EA21` |
| dataset | `sts_trtu_m` |
| statistics URL | `.../STS_TRTU_M?geo=EA21&indic_bt=VOL_SLS&nace_r2=G47&s_adj=SCA&unit=PCH_PRE` |
| geo | **EA21** |
| unit | `PCH_PRE` (m/m %) |
| SA | **SCA** |
| frequency | Monthly |
| revision | STS revisions with later vintages |
| expected lag | ~1 month |
| fetch method | `eurostat_statistics_api` |
| score_role | **scored** |
| freshness | Latest month |

### Consumer.income — household adjusted disposable income real per capita q/q %

| Field | Value |
|---|---|
| series_id | `NASQ_10_KI.Q.PC.SCA.S14_S15.B7G_R_HAB_GR.EA21` |
| dataset | `nasq_10_ki` |
| statistics URL | `.../NASQ_10_KI?geo=EA21&sector=S14_S15&na_item=B7G_R_HAB_GR&unit=PC&s_adj=SCA` |
| geo | **EA21**, sector `S14_S15` |
| unit | Per-capita q/q % (`B7G_R_HAB_GR`) |
| SA | **SCA** |
| frequency | Quarterly |
| revision | Quarterly national accounts |
| expected lag | ~2 months |
| fetch method | `eurostat_statistics_api` |
| score_role | **scored** |
| freshness | Latest quarter |

### Consumer.spending — household final consumption q/q %

| Field | Value |
|---|---|
| series_id | `NAMQ_10_GDP.Q.CLV_PCH_PRE.SCA.P31_S15.EA21` |
| dataset | `namq_10_gdp` |
| SDMX key | `Q.CLV_PCH_PRE.SCA.P31_S15.EA21` |
| geo | **EA21** |
| unit | `CLV_PCH_PRE` |
| SA | **SCA** |
| frequency | Quarterly |
| revision | National accounts |
| fetch method | `eurostat_sdmx_json` |
| score_role | **scored** |
| freshness | Latest quarter |

### Consumer.confidence — EC consumer confidence indicator

| Field | Value |
|---|---|
| series_id | `EI_BSCO_M.M.SA.BS-CSMCI.BAL.EA21` |
| dataset | `ei_bsco_m` |
| statistics URL | `.../EI_BSCO_M?geo=EA21&indic=BS-CSMCI&s_adj=SA&unit=BAL` |
| geo | **EA21** |
| unit | `BAL` (balance, long-run mean **below zero**, not PMI 50) |
| SA | Yes |
| frequency | Monthly |
| revision | Minor revisions on EC release |
| expected lag | ~3 weeks |
| fetch method | `eurostat_statistics_api` |
| score_role | **scored** (transform `index_level`; **par requires calibration review**, not 50) |
| freshness | Latest month |

---

## Context-only (not scored)

### European Commission Economic Sentiment Indicator (ESI)

| Field | Value |
|---|---|
| series_id | `TEIBS010.BS-ESI-I.EA21` |
| statistics URL | `.../statistics/1.0/data/teibs010?geo=EA21&indic=BS-ESI-I&s_adj=SA&sinceTimePeriod=2025-09` |
| score_role | **context** (stored under `context.economic_sentiment_indicator` in `ea.json`) |
| note | BCS/sector detail not mapped to PMI 50-scale per V1 plan |

---

## Unavailable / stale handling

- **No** Bloomberg, Reuters, Trading Economics, or paid PMI substitutes.
- Required series fetch failures raise `SeriesUnavailableError` in strict mode (`collect_macro(strict=True)`).
- PMI history gaps are explicit in `data/temperature_history/raw/ea/harvest_report.json` when listing/Wayback do not yield PDFs.

---

## Collector output

- Normalized history: `data/temperature_history/ea.json` (schema aligned with `ca.json` / `au.json`).
- Raw PMI artifacts: `data/temperature_history/raw/ea/` (+ `harvest_report.json`).
