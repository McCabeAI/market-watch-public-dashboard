# Australian CPI pre-release nowcast — methodology

Shadow-only engine for the **complete Monthly CPI** (ABS `ABS,CPI,2.0.0`) and the **legacy quarterly trimmed mean** (`ABS,CPI_Q,1.0.0`). Control-plane context: [agent-control-plane#286](https://github.com/McCabeAI/agent-control-plane/issues/286).

## Source and transform map (targets and primary inputs)

| Canonical id | Role | Dataflow (id, version) | SDMX key | Freq | Regime | Transform | Provenance in fixture |
| --- | --- | --- | --- | --- | --- | --- | --- |
| headline_nsa_mom / yoy | target | CPI, 2.0.0 | 2.10001.10.50.M / 3.10001.10.50.M | M | complete_monthly_cpi | mom / yoy | `abs_cpi_headline_original.csv` (API) |
| headline_sa_mom / yoy | target | CPI, 2.0.0 | 2.999901.20.50.M / 3.999901.20.50.M | M | complete_monthly_cpi | mom / yoy | `abs_cpi_analytical_sa.csv` |
| trimmed_mean_monthly_sa_mom / yoy | target | CPI, 2.0.0 | 2.999902.20.50.M / 3.999902.20.50.M | M | complete_monthly_cpi | mom / yoy | `abs_cpi_analytical_sa.csv` |
| weighted_median_monthly_sa_mom / yoy | shadow diagnostic | CPI, 2.0.0 | 2.999903.20.50.M / 3.999903.20.50.M | M | complete_monthly_cpi | mom / yoy | `abs_cpi_analytical_sa.csv` |
| trimmed_mean_quarterly_legacy_qoq / yoy | target | CPI_Q, 1.0.0 | 2.999902.20.50.Q / 3.999902.20.50.Q | Q | quarterly_legacy_tm | qoq / yoy | `abs_cpi_q.csv`; cross-check `rba_g1.csv` |
| headline_nsa_index | input | CPI, 2.0.0 | 1.10001.10.50.M | M | complete_monthly_cpi | index | API + workbook overlap |
| class NSA / SA indexes | input | CPI, 2.0.0 | per-class INDEX | M | complete_monthly_cpi | index | `abs_cpi_class_original.csv`, `abs_cpi_class_sa.csv` |
| MEASURE 4 contributions | input | CPI, 2.0.0 | per-class contribution | M | complete_monthly_cpi | contribution | API (price-updated weights at t−1) |
| CPI structure | input | CPI, 2.0.0 | structure message | — | complete_monthly_cpi | codelist | `abs_cpi_structure.json` |
| Table 8 seasonal factors | input | workbook 640108 | Table 8 | M | complete_monthly_cpi | seasonal factor | `wayback_aug-2026_640108.xlsx` (`mirror:web.archive.org`) |
| Appendix 1a TM | cross-check | workbook | Appendix 1a | Q | quarterly_legacy_tm | index/qoq | `wayback_jun-2026_64010Appendix1a.xlsx` |
| CPI_M indicator | **not used** | CPI_M, 1.2.0 | 1.10001.10.50.M | M | monthly_cpi_indicator_legacy | — | not fetched; guard refuses as complete-monthly history |

Vintage labelling: API rows carry calendar `published_at` per reference month; in-repo July 2026 workbooks and RBA G1 share a single file vintage date (see `snapshot.json` notes). Wayback captures are labelled `mirror:web.archive.org` with capture timestamp and sha256.

## ABS methodology boundaries

- **Monthly trimmed mean** (complete Monthly CPI, INDEX 999902 monthly) and **legacy quarterly trimmed mean** (pre-October 2025 methods, CPI_Q / Appendix 1a) are **different statistics**. Target ids are never interchangeable; code raises `RegimeBoundaryError` on cross-use.
- **`ABS,CPI_M,1.2.0`** (discontinued Monthly CPI Indicator) is **not** used as target history.
- The existing `methodology_breaks` guard on `Inflation.underlying` in `data/temperature_history/au.json` is **untouched**; this engine does not write scored history.

## Trim reconstruction (gate G5)

Primary variant: `sa_where_available_else_original__weight_t_minus_1` (87 expenditure classes, 15% tail trim on normalised price-updated weights).

From `verify-trim` on the committed fixture (`trim_verification.json`):

| Metric | Value |
| --- | ---: |
| Months covered (with weights) | 20 |
| Mean abs error vs unrounded published TM MoM (pp) | 0.0018449433963161287 |
| Max abs error (pp) | 0.009502236944340436 |
| Rounded MoM matches | 19 / 20 (95%) |
| G5 verdict / claim | pass / **reconstruction** |

Contribution months without MEASURE 4 weights (2024-05..2024-12) are omitted rather than imputed.

## Quarterly legacy equivalence

CPI_Q INDEX 999902 QoQ vs RBA G1 `GCPIOCPMTMQP` vs Appendix 1a (when parsed):

| Check | Result |
| --- | --- |
| Overlap quarters | 177 |
| Rounded QoQ matches | 177 / 177 |
| Verdict | **equivalent** |

This validates **source alignment**, not that monthly TM equals quarterly legacy TM.

## Models

- **Headline NSA MoM:** seasonal naive; SA persistence × implied seasonal factor (3/6/12); component bottom-up (3/6-month class means × Table 8 / implied seasonals).
- **Headline SA MoM:** mean of last 3/6/12 SA MoMs; component SA bottom-up.
- **Monthly TM SA MoM:** persistence; 3/6/12 means; component rank-and-trim diagnostics (not selected unless G5 passes for that variant).
- **Legacy quarterly TM QoQ:** persistence; 4-quarter mean; **proxy bridge** (quarter-average of monthly TM index) is reported but **excluded** from selection (`proxy_bridge_non_equivalent`). September 2026 bridge diagnostic value **1.0437709077788515** % vs selected persistence **0.8125952260030544** % for 2026-Q3.
- **YoY:** always from official index arithmetic on levels using the selected change model; never separately modelled.

**Aggregation identity** (class NSA vs all-groups, 20 full-coverage months): mean abs residual **0.003838771601283243** pp; max abs **0.007761260257528546** pp (`nowcast.json` diagnostics).

## Pre-registered selection + amendment A1

Base rule (`models.SELECTION_RULE`): per change target, eligible models have pseudo-OOS **n ≥ 12** in regime; compare **common-sample MAE** across eligible models and the baseline; require **≥ 0.02 pp** MAE improvement to switch off baseline; YoY inherits the selected change model.

**Amendment A1 (2026-10-21, before release):** selection MAE is evaluated on the **intersection** of periods where every eligible candidate and the baseline have errors. Unequal-sample legacy picks are still reported as `selection_unequal_sample_legacy`.

Bands use the **selected model’s full** walk-forward |error| quantiles (68% / 90%) with a **±0.05 pp** rounding floor; `low_sample` when **n < 20**.

## Uncertainty and leakage

- **`as_of`:** timezone-aware; observation visible iff `published_at <= as_of` (calendar from `calendar.py`, with provenance per entry).
- **Pre-release:** snapshot `retrieved_at` must be **before** `release_time` (`snapshot_retrieved_after_release` otherwise).
- **Freeze:** `generated_at >= release_time` refused for new publication.
- **Backtest labels:** `pseudo_oos_latest_vintage` (latest vintage, seasonal revisions leak) vs separate **`true_vintage`** section (archived bytes only; **n ≈ 1** in this repo — not a skill estimate).

## Pseudo-OOS vs true vintage

| Mode | Label | Use |
| --- | --- | --- |
| Walk-forward on latest API vintage | `pseudo_oos_latest_vintage` | Model selection, bands, BACKTEST_2026-09.md tables |
| Single in-repo workbook vintage | `true_vintage` | Diagnostic only; most rows **blocked** |

Never mix the two in one metric.

## Limitations

- Short monthly history (~**16** common months for several models; widespread `low_sample`).
- Headline NSA bands can be wide under small **n**.
- Quarterly bridge **upside risk** (~**1.04** % QoQ proxy vs **0.81** % persistence selected) — different statistic.
- ABS website maintenance (until **2026-10-22**) blocked live workbook fetch; fixture relies on API + Wayback/in-repo bytes.
- Wayback mirrors are third-party; labelled with capture time — not sole authority when API agrees.
- No official pre-release fuel, electricity-rebate, or travel timing series in the snapshot.
- Latest-vintage SA revisions leak into pseudo-OOS.
- Calendar entries before 2026-08 may be `rule_inferred_last_wednesday` where no ABS page was archived.
