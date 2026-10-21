# Australian CPI pre-release nowcast — investigation and plan (September 2026 release)

Author role: parent investigator/planner/reviewer (Opus 5.5). Implementation, tests, commits and PR operations are delegated to Grok 4.7 and Composer 2.5 subagents under `ACP_SUBAGENT_POLICY` (`allowed_models: [grok-4.7, composer-2.5]`). Control-plane issue: McCabeAI/agent-control-plane#286.

Target release: **ABS Consumer Price Index, Australia, September 2026**, published **2026-10-28 11:30 Australia/Sydney (+11:00)** = 2026-10-27 20:30 America/New_York. Release date confirmed on the archived ABS August 2026 release page ("Next Release 28/10/2026") and in `data/macro_ingestion/fragments/au.json`.

All outputs are **shadow-only**: no writes to `data/temperature_history/`, `data/temperature_scores.json`, `data/macro_ingestion/catalog.json`, fragments, Market Watch launches, workflows, cron, or ACP.

## 1. Investigation findings (2026-10-21)

### 1.1 Source access

| Source | Status from this environment | Use |
| --- | --- | --- |
| ABS website (`www.abs.gov.au`) | HTTP 503: "The ABS website is currently undergoing maintenance. We'll be back online on 22 October 2026." | Workbooks/methodology pages unavailable for live fetch until 22 Oct. |
| ABS Data API (`https://data.api.abs.gov.au/rest/`) | HTTP 200 | **Primary official live source.** |
| RBA statistical table G1 (`https://www.rba.gov.au/statistics/tables/csv/g1-data.csv`) | HTTP 200, publication date 30-Jul-2026 | Cross-check of quarterly trimmed mean/weighted median (GCPIOCPMTMQP, GCPIOCPMTMYP). |
| Wayback Machine mirror of ABS pages/workbooks | Intermittent (timeouts, "temporarily offline") | Secondary **third-party mirror** only; must be labeled `mirror:web.archive.org` with original ABS URL, capture timestamp and sha256. Never the sole basis of a claim when the ABS API carries the same series. |
| Repo archive `data/temperature_history/raw/au/cpi_64010{1..9}_jul2026.xlsx` | Present | Genuine July-2026 vintage ABS workbooks (Tables 1–9) — the only in-repo true vintage of the complete monthly CPI. |

### 1.2 ABS Data API dataflows (verified)

- `ABS,CPI,2.0.0` — "Consumer Price Index (CPI)": the **complete Monthly CPI** (and its quarterly aggregates). Dimensions `MEASURE.INDEX.TSEST.REGION.FREQ`. MEASURE: 1 index, 2 % change previous period, 3 % change previous year, 4 contribution to CPI index number, 5 change in contribution, 6 contribution to % point change previous period, 7 contribution to annual % point change. TSEST: 10 original, 20 SA, 30 trend. REGION 50 = Australia (weighted average of eight capital cities). Monthly series start **2024-04** (index), MoM from 2024-05, YoY from 2025-04. Latest observation **2026-08** (released 2026-09-30). 158 original index/contribution series and 105 SA index series at the monthly frequency.
  - Headline: INDEX 10001 (All groups CPI), TSEST 10. Aug 2026: index 103.50, MoM +0.4, YoY 4.0.
  - Headline SA: INDEX 999901 (All groups CPI, seasonally adjusted), TSEST 20. Aug 2026: index 107.85, MoM +0.7, YoY 3.9.
  - Monthly trimmed mean: INDEX 999902, TSEST 20, FREQ M. Aug 2026: index 108.1436, MoM +0.2, YoY 3.6.
  - Monthly weighted median: INDEX 999903, TSEST 20, FREQ M. Aug 2026: MoM +0.3, YoY 3.6.
  - Base period: All groups original index = 100.0 in **2025-09** (RBA G1 units "Index, September 2025 month = 100").
- `ABS,CPI_Q,1.0.0` — quarterly CPI incl. **quarterly trimmed mean** INDEX 999902 TSEST 20 FREQ Q: 177 quarters 1982-Q2..2026-Q2. 2026-Q2: index 146.096, QoQ 0.8, YoY 3.6; 2025-Q3 index 142.3925. Matches RBA G1 GCPIOCPMTMQP (2026-Q2 0.8) and the ABS statement that "the quarterly Trimmed mean based on pre-October 2025 methods is available in Appendix 1a". Equivalence of CPI_Q 999902 with Appendix 1a must be verified (T1), not assumed.
- `ABS,CPI_M,1.2.0` — the **discontinued Monthly CPI Indicator** (ends 2025-09). Different methodology/regime (partial basket). Never used as target history for complete-Monthly-CPI targets; at most a separately labeled regime diagnostic.
- `ABS,CPI_WEIGHTS,1.0.0` — basket weights (quarterly-dated, by region). Used for weight provenance only after verification.

### 1.3 ABS methodology facts relied on (and their evidence)

- Archived ABS Aug-2026 page (web.archive.org capture 20261010043606): quarterly data in Tables 17–18 added in Mar/Jun/Sep/Dec releases; "The quarterly Trimmed mean based on pre-October 2025 methods is available in Appendix 1a"; quarterly CPI "re-referenced and aligned to the new monthly CPI series"; from February 2027 CPI moves to the fourth Wednesday. Electricity +13.2% y/y "largely due to the ending of Commonwealth electricity rebates"; domestic holiday travel −4.9% m/m in August after school holidays.
- Workbook tables: Table 3 (class indexes), Table 5 (contributions to monthly change), Table 6 (analytical series incl. trimmed mean/weighted median), **Table 7 (SA class indexes)**, **Table 8 (combined seasonal factors by expenditure class)**, Appendix 2 (contributions to All-groups index number by city/class).
- Trimmed mean (ABS/RBA convention): weighted mean of the central 70% of the distribution of SA expenditure-class price changes (15% trimmed from each tail), with **price-updated** weights. Whether the complete monthly CPI uses exactly this rule on 87 classes must be **verified by reconstruction** (gate G5) using API MEASURE 4 contributions (price-updated weights at t−1) and SA class indexes (TSEST 20 where seasonally adjusted, original otherwise). Until verified it is a proxy.
- The **monthly trimmed mean and the legacy quarterly trimmed mean are different statistics** (different ranking interval, seasonal adjustment and aggregation). The existing `methodology_breaks` guard on `Inflation.underlying` in `data/temperature_history/au.json` stays untouched; nothing in this engine writes scored history.

### 1.4 Existing repo infrastructure audit

- `scripts/macro_ingestion/adapters/au.py`: `parse_abs_time_series_workbook`, `parse_abs_workbook_columns`, challenge-page detection, sha256 — reusable read-only for archived workbooks. Do not modify behaviour.
- Catalog: `AU.Inflation.headline` = A130393721F (YoY, 640101), `AU.Inflation.underlying` = A130400382R (trimmed-mean YoY, 640106); catalog held through 2026-07.
- `scripts/canadian_cpi_release` + `docs/canadian_cpi_release/RUNBOOK.md`: architecture reference only — snapshot/live acquisition, `published_at` as-of filtering, immutable `runs/<release>-asof-<as_of>-<sha12>/` archives with `manifest.json` + `raw/`, `ArchiveConflict` → exit 2, freeze `generated_after_freeze`, pseudo-OOS labeling, unittest suites. Its statistics (StatCan basket, NRCan fuel bridge) are **not** a template.
- Tests use `unittest`; dependencies in `requirements-market-state.txt` (openpyxl not preinstalled; install before tests).

### 1.5 Mechanics already known (official data, as of 2026-10-21)

- Headline NSA YoY(Sep-26) = 103.50 × (1 + m) / 100.00 − 1, where m = Sep-26 NSA MoM. m = 0 → 3.5%; m = +0.5 → 4.0%. Sep-25 NSA MoM (+0.5) drops out of the year-ended rate.
- Trimmed mean YoY(Sep-26) = 108.1436 × (1 + m_tm) / 104.686 − 1 (Sep-25 TM MoM +0.3 drops out). m_tm = 0.3 → ≈3.6%.
- Legacy quarterly TM YoY(Q3-26) = 146.096 × (1 + q) / 142.3925 − 1. q = 0.8 → ≈3.4%.
- Monthly TM history is short (MoM from 2024-05, 28 points); walk-forward samples will be small and must be reported with n.

## 2. Target definitions (separate, never interchanged)

| Target id | Definition | Source key | Status rule |
| --- | --- | --- | --- |
| `headline_nsa_mom`, `headline_nsa_yoy` | All groups CPI original, Australia | CPI 2.0.0 `1.10001.10.50.M` (+2, +3) | forecast |
| `headline_sa_mom`, `headline_sa_yoy` | All groups CPI seasonally adjusted | CPI 2.0.0 `1.999901.20.50.M` | forecast |
| `trimmed_mean_monthly_sa_mom`, `trimmed_mean_monthly_sa_yoy` | Monthly trimmed mean (complete Monthly CPI) | CPI 2.0.0 `1.999902.20.50.M` | forecast; `proxy` label unless G5 passes for any component-based variant |
| `trimmed_mean_quarterly_legacy_qoq`, `..._yoy` | Quarterly trimmed mean, pre-Oct-2025 methods (Appendix 1a) | CPI_Q 1.0.0 `1.999902.20.50.Q` (verify vs Appendix 1a / RBA G1) | forecast if source equivalence verified, otherwise `blocked` or explicitly `proxy` |
| `weighted_median_monthly_sa_mom/yoy` | Optional shadow diagnostic | CPI 2.0.0 `1.999903.20.50.M` | shadow diagnostic only |

Every output row carries: value (unrounded), value rounded to ABS display precision (1 dp), status (`ok`/`proxy`/`blocked`), method id, uncertainty band with sample size n, and caveats.

## 3. Architecture (new package; existing code read-only)

```
scripts/au_cpi_release/
  __init__.py, __main__.py
  contract.py        # target ids, series keys, regimes, Observation/Snapshot dataclasses
  calendar.py        # ABS release datetimes per reference month with provenance per entry
  sources/abs_sdmx.py    # ABS Data API CSV fetch: exact URL, retrieved_at, http status, bytes, sha256
  sources/abs_workbook.py# archived workbook parsing via scripts.macro_ingestion.adapters.au parsers
  sources/rba.py         # RBA G1 CSV cross-check
  sources/acquire.py     # build/load snapshot, canonical bytes, raw hash verification
  archive.py         # immutable run archive, manifest, conflict/freeze handling
  trim.py            # rank-and-trim reconstruction + verification report (diagnostic)
  models.py          # transparent baselines + component bottom-up for headline
  backtest.py        # walk-forward pseudo-OOS (latest vintage) and true-vintage sections
  uncertainty.py     # empirical error quantiles with n, low-sample flags
  engine.py, report.py, cli.py
scripts/au_cpi_release/fixtures/pre_2026-10-28/   # frozen snapshot.json + raw/ (official bytes)
tests/au_cpi_release/
docs/au_cpi_release/ PLAN.md, RUNBOOK.md, METHODOLOGY.md, SCORECARD_2026-09.md, candidates/
```

Manual CLI (`PYTHONPATH=. python3 -m scripts.au_cpi_release ...`): `snapshot` (live acquisition → immutable snapshot archive), `nowcast`, `backtest`, `replay` (recompute from an archived run and verify hashes), `verify-trim` (reconstruction diagnostic), `scorecard` (post-release only; refuses before release time). No workflow, cron or scheduler.

## 4. Information-set and leakage rules

1. `as_of` is timezone-aware (default Australia/Sydney). Each observation carries `published_at` = ABS release datetime of its reference period (from `calendar.py`, each entry with source: ABS page, catalog fragment, or explicitly labeled `rule_inferred_last_wednesday`). Visible iff `published_at <= as_of`.
2. A snapshot whose `retrieved_at` is at or after the target release time can never feed a pre-release nowcast for that target (`snapshot_retrieved_after_release`): the latest vintage then contains revised seasonal factors/history from the target release, which period filtering alone cannot remove.
3. Candidate publication refused at/after 2026-10-28T11:30+11:00 (`generated_after_freeze`); replay of an archived pre-freeze run is allowed and labeled `replay`.
4. Backtests are labeled `pseudo_oos_latest_vintage` (target t forecast from periods ≤ t−1 of the latest vintage; seasonal-factor revisions leak) vs `true_vintage` (only from archived release-time bytes; expected n ≈ 1–2 → report n or `blocked`). Never mix the two in one metric.
5. Regimes reported separately: `complete_monthly_cpi` (CPI 2.0.0, back-cast 2024-04..2025-09 first published 2025-11-26, live from Oct-2025 reference), `quarterly_legacy_tm` (CPI_Q 1982–2026), sub-regimes for the quarterly history (e.g. pre-2020, 2020–21, 2022–23, 2024+). `monthly_cpi_indicator_legacy` (CPI_M) is diagnostic only.

## 5. Modeling plan (time-boxed; honest before ambitious)

- Headline NSA MoM: (a) seasonal naive (same-month-last-year NSA MoM), (b) SA-persistence × implied seasonal factor (NSA/SA index ratio of the same month last year), (c) component bottom-up: per-class forecast (SA persistence × class seasonal factor, or seasonal naive for non-SA classes) weighted by price-updated contribution shares at t−1; contributions must reconcile to the All-groups change (residual reported).
- Headline SA MoM: mean of last 3/6/12 SA MoMs, and bottom-up SA aggregate.
- Monthly TM SA MoM: persistence, 3/6/12-month means, optional median-of-models; component rank-and-trim only as diagnostic unless G5 passes.
- Legacy quarterly TM QoQ: persistence, 4-quarter mean, and a bridge from monthly TM quarter-average (Jul, Aug actual + Sep forecast) labeled `proxy_bridge_non_equivalent` with its measured gap on overlap quarters.
- YoY always derived from index arithmetic on official levels, never modeled separately.
- **Pre-registered selection rule**: per target, pick the model with lowest pseudo-OOS MAE in the target regime with n ≥ 12; if n < 12 or no model beats persistence by ≥ 0.02 pp, use the simplest baseline. Rule recorded in output before any post-release data exist.
- Component signals allowed only if official, pre-release and archived: mechanical base effects, official seasonal factors. No ABS/RBA pre-release fuel, electricity-rebate-timing or travel series is known; these are documented as unmodeled risks, not invented. No consensus or market data.
- Uncertainty: empirical |error| quantiles (68/90%) from walk-forward with n; `low_sample` flag when n < 20; include ±0.05 pp rounding floor.

## 6. Dependency graph and allocation

```
T0 plan commit (Composer 2.5)
  └─> T1 data layer (Grok 4.7): contract, calendar, ABS SDMX + RBA sources, workbook reuse,
        snapshot/acquire, immutable archive, frozen fixture pre_2026-10-28, trim reconstruction verifier,
        CPI_Q vs Appendix 1a / RBA G1 equivalence check; `snapshot` + `verify-trim` CLI
        └─> T2 models (Grok 4.7): models, walk-forward backtest, uncertainty, engine, report,
              `nowcast` / `backtest` / `replay` CLI, freeze + leakage guards
              └─> T3 integration (Composer 2.5): focused tests, RUNBOOK/METHODOLOGY/SCORECARD docs,
                    pre-release candidate archive, regression + preservation checks, push, PR
                    └─> T4 review (Opus) ─> T5 repairs (Grok 4.7 / Composer 2.5)
```

## 7. Acceptance gates

- **G0** this plan committed by an allowed subagent.
- **G1 provenance**: every raw input has URL (exact query), dataflow id+version, retrieved_at, HTTP status, bytes, sha256; fixture loads offline and re-verifies hashes; snapshot canonical hash stable across loads.
- **G2 methodology boundaries**: distinct target ids for monthly TM vs legacy quarterly TM; code and tests refuse to substitute one for the other or to use CPI_M as complete-monthly history; existing `methodology_breaks` guard untouched.
- **G3 as-of**: injected future observation (e.g. a fake 2026-09 print) does not change the forecast; snapshot retrieved after release refused; tests.
- **G4 archive**: immutable run dir; conflicting bytes → exit 2 with prior files intact; raw hash mismatch → fail; `replay` reproduces identical `nowcast.json` bytes.
- **G5 trim reconstruction**: report months covered, class count, mean/max abs error vs published TM MoM. Claim "reconstruction" only if rounded MoM matches on ≥ 90% of ≥ 12 months and max abs error ≤ 0.05 pp; else label proxy and document why.
- **G6 backtest**: per target × model × regime: n, MAE, bias, RMSE; true-vintage section with n or blocked reason.
- **G7 candidate**: every target has value or explicit blocked reason, uncertainty with n, selected model per pre-registered rule, caveats; archived before freeze with manifest.
- **G8 preservation**: existing suites (`tests/canadian_cpi_release`, `tests/macro_ingestion`, `tests/core_pce_release`, AU tests) pass; sha256 of `data/temperature_scores.json`, `data/temperature_history/*.json`, `data/macro_ingestion/catalog.json`, `data/macro_ingestion/fragments/au.json` unchanged; no `.github/` changes.

## 8. Assumptions and known blockers

- ABS website maintenance until 2026-10-22: Appendix 1a, Table 7/8 for August, and methodology notes cannot be live-fetched today; the ABS Data API is used instead. Rerun `snapshot` after the site returns to add workbook bytes.
- True-vintage backtests are essentially unavailable (one in-repo vintage, July 2026); results are pseudo-OOS and labeled so.
- Release-date history before 2026-08 may need rule inference; labeled per entry.
- No fabricated series, weights, seasonal factors, rebates, consensus or model skill.

## 9. Reviewer amendment A1 (2026-10-21, before the 2026-10-28 release)

Selection is evaluated on the common sample of eligible candidates and the baseline. Reason: unequal-sample MAE comparisons are not like-for-like. This amendment was made before any September 2026 outcome exists. Both the common-sample result and the earlier unequal-sample result are reported.
