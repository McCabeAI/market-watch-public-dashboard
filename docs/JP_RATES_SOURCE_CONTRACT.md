# Japan rates / policy source contract (P4)

Status: **pinned for isolated `scripts/japan_rates_data.py` collector** (parent wires into `market_state.py` via I5).

## 1. MOF JGB benchmark yields (2Y / 5Y / 10Y / 30Y)

| Item | Value |
| --- | --- |
| Authority | Ministry of Finance Japan (MOF) |
| English page | https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/index.htm |
| Japanese page | https://www.mof.go.jp/jgbs/reference/interest_rate/ |
| Current CSV (EN) | https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv |
| Historical CSV (EN, 1974–) | https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv |
| Current CSV (JA) | https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv |
| Historical CSV (JA) | https://www.mof.go.jp/jgbs/reference/interest_rate/data/jgbcm_all.csv |
| Cadence | Daily business-day par yields (% per annum) |
| Tenors used | **2Y, 5Y, 10Y, 30Y** from MOF columns `2Y`…`30Y` |
| 30Y availability | **Published** in MOF files (column `30Y`; long history in `jgbcme_all.csv`) |
| Staleness | Treat as stale when latest observation age **> 4 calendar days** (US/CA convention) |
| Revision | Same-day file updates; no separate vintage IDs |

**History assembly:** `fetch_jp_jgb_rates` fetches **both** historical and current English CSVs, parses each with `parse_mof_jgb`, and merges with `merge_mof_jgb_series` (overlapping dates take **current** revisions). If one feed fails, the other may still satisfy the requested window.

**No vendor substitute** (Investing.com, Bloomberg, etc.) for required JGB benchmarks.

## 2. BOJ overnight policy benchmark (TONA block)

| Item | Value |
| --- | --- |
| Primary series | **FM01 `STRDCLUCON`** — *Call Rate, Uncollateralized Overnight, Average (Daily)* |
| API (CSV) | `https://www.stat-search.boj.or.jp/api/v1/getDataCode?format=csv&lang=en&db=FM01&code=STRDCLUCON&startDate=YYYYMM&endDate=YYYYMM` |
| Table page | https://www.stat-search.boj.or.jp/ssi/mtshtml/fm01_d_1_en.html |
| Call-money releases | https://www.boj.or.jp/en/statistics/market/short/mutan/index.htm (provisional/final XLSX) |
| Unit | Percent per annum |
| Cadence | Business days (weekends/holidays `null`) |

### TONA vs uncollateralized overnight call

- **Market label / tradable curve id:** `TONA` (Tokyo Overnight Average Rate), per JPX product definition ([3-Month TONA futures specs](https://www.jpx.co.jp/english/derivatives/products/interest-rate/3m-tona-futures/01.html)).
- **Policy-block overnight feed pinned here:** `STRDCLUCON` daily average uncollateralized overnight **call rate** from BOJ Time-Series Data Search. This is the BOJ’s official published overnight money-market benchmark time series used in FM01 tables.
- **Futures underlying:** **3-month compounded confirmed TONA** over the contract’s interest-rate reference period, quoted as **100 minus annualized rate (Act/365)** — *not* the raw `STRDCLUCON` print. Compounding conventions: [JPX TONA Conventions PDF](https://www.jpx.co.jp/english/derivatives/products/interest-rate/3m-tona-futures/TONA%20Conventions%20(Calculation%20Methodology)%20and%20Example%20of%20Schedule.pdf).

Collector documents this split in `benchmark.underlying_note` so parent can present overnight vs futures fairly.

## 3. OSE 3-Month TONA futures (tradable short-rate curve candidate)

| Item | Value |
| --- | --- |
| Exchange | JPX / OSE, cleared JSCC |
| Product page | https://www.jpx.co.jp/english/derivatives/products/interest-rate/3m-tona-futures/01.html |
| Settlement index | https://www.jpx.co.jp/english/markets/derivatives/settlement-price/index.html |
| Daily CSV pattern | `…/tvdivq00000014l6-att/rb_eYYYYMMDD.csv` (English; date embedded in filename) |
| Quotation | **100 − 3-month compounded TONA** (% p.a., Act/365) |
| Contract months | **20** listings on **Mar/Jun/Sep/Dec** quarterly cycle |
| Stable identification (proved on 2026-09-18 file) | `Issue Name` prefix `FUT_TOA3M_`; `Underlying Name` = `3-Month TONA`; `Issue Code` suffix `091`; `Contract Month` = `YYYYMM` |
| Marks used | `Settlement Price` column |
| Volume/OI | Not required in daily rb_e CSV for policy path (fields often blank for rates futures) |

### Tradable declaration gate

Declare **`tradable_curve.status = ok`** only when:

1. Settlement CSV is fetched deterministically (index-page link or ≤12-day walkback), and  
2. Parser finds **exactly 20** `FUT_TOA3M_*` rows with expected underlying label and issue-code suffix.

Otherwise **`unavailable`** (fail loud in parent preflight; do not invent marks).

Hosted runners: JPX may require browser-like `User-Agent` (reuse `scripts.market_state.BROWSER_USER_AGENT`).

## 4. Official government curve (`official_curves.JP`)

MOF publishes **daily par yields** at standard tenors (1Y–40Y), not a published Svensson/zero grid in the pinned URLs.

- Collector sets `official_curve.kind = benchmark_par_yields_only` using latest MOF 2Y/5Y/10Y/30Y.
- **Do not fabricate** Svensson parameters or zero curves.

Optional context (not required for launch): JPX JGB futures appear in the same `rb_e*.csv` file (`FUT_*` JGB lines) for cross-checks only.

## 5. Module API (`scripts/japan_rates_data.py`)

- `JapanRatesError`
- `parse_mof_jgb(text) -> dict[tenor, dict[date, yield%]]`
- `fetch_jp_jgb_rates(start, end, fetch_bytes)`
- `fetch_tona_history(start, end, fetch_bytes)`
- `collect_jp_policy_path(today, fetch_bytes)`
- `collect_jp_official_curve(today, fetch_bytes)`
- `validate_jp_rates_bundle(payload)`

Helper: `build_jp_rates_bundle` (tests / `--live` smoke only).

## 6. Tests

```bash
PYTHONPATH=. python3 -m unittest tests.test_japan_rates_data
PYTHONPATH=. python3 -m unittest tests.test_japan_rates_data -v  # live smoke if network
```

Fixtures under `tests/fixtures/jp_rates/` — **no network in default unittest**.

Optional live:

```bash
PYTHONPATH=. python3 -m tests.test_japan_rates_data --live
```

## 7. Day-count / quotation summary

| Instrument | Convention |
| --- | --- |
| MOF JGB yields | Par yield, % per annum (MOF table units) |
| BOJ `STRDCLUCON` | Overnight call rate, % per annum, business-day average |
| OSE 3M TONA futures | **IMM index**: price = 100 − R; R = annualized compounded TONA over 3-month reference window, **Act/365**; tick 0.0025 index points |
| Implied rate in bundle | `implied_rate = 100 - settlement_price` (aligned with US/CA/AU policy_path_data) |
