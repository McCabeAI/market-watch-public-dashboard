# Proxy sensitivity (ZORI proxy, not Cotality SFRI)

All tables and figures use frozen CSVs from `build_inputs.py`. This is **not** a Cotality SFRI validation.

## Lag correlations (descriptive)

Highest **level** year-on-year correlation for `zori_all` vs `oer_sa`: lag **13**, r = 0.835 (n = 115).

Highest **first-difference of yoy** correlation: lag **12**, r = 0.660.

For `zori_sfr` level yoy: best lag **16**, r = 0.930.

Overlapping year-on-year correlations are **not** evidence of a one-month CPI print edge.

## One-month OER SA month-on-month (rolling origin)

Information set: OER and ZORI through **t−1** only (latest revised vintages — **not** a real-time publication test).

### Common sample (all five models finite)

n = 76:

| Model | MAE (pp) | RMSE (pp) |
| --- | --- | --- |
| persist | 0.074 | 0.092 |
| trail3 | 0.064 | 0.082 |
| ar3 | 0.063 | 0.083 |
| ar3_zori_m1 | 0.061 | 0.082 |
| ar3_zori_m12 | 0.066 | 0.089 |

### MAE by window (same five-model common sample)

MAE (pp) by model; n is the count of months in that window where all five models are finite.

| Window | n | persist | trail3 | ar3 | ar3_zori_m1 | ar3_zori_m12 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| through_2019 | 0 | — | — | — | — | — |
| 2020_2022 | 36 | 0.065 | 0.062 | 0.061 | 0.065 | 0.068 |
| from_2023 | 40 | 0.082 | 0.066 | 0.064 | 0.058 | 0.065 |


For the **full** five-model common sample, the through_2019 window has **n = 0**: `ar3_zori_m12` needs 36 training rows with ZORI lag-12, so no month in 2019–2019 qualifies in the intersected sample. That emptiness is a sample definition, not evidence that models tied.

### Secondary common sample (drops `ar3_zori_m12`)

`forecast_1m_oer_sa_common_without_m12` — persist, trail3, ar3, and ar3_zori_m1 only (n = 87). This intersection allows a pre-2020 comparison.

| Window | n | persist | trail3 | ar3 | ar3_zori_m1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| through_2019 | 11 | 0.042 | 0.033 | 0.035 | 0.033 |
| 2020_2022 | 36 | 0.065 | 0.062 | 0.061 | 0.065 |
| from_2023 | 40 | 0.082 | 0.066 | 0.064 | 0.058 |

### `ar3_zori_ksearch` (separate sample)

Lag k is chosen by in-sample training RMSE each origin; this is **not** the five-model common sample. Separate sample n = 87, MAE = 0.061 pp, RMSE = 0.081 pp.

### Robustness: OER NSA month-on-month

Common sample n = 76 (all five models finite on `oer_nsa_mom`):

| Model | MAE (pp) | RMSE (pp) |
| --- | --- | --- |
| persist | 0.075 | 0.094 |
| trail3 | 0.066 | 0.087 |
| ar3 | 0.067 | 0.088 |
| ar3_zori_m1 | 0.068 | 0.087 |
| ar3_zori_m12 | 0.071 | 0.096 |

On NSA, `ar3_zori_m1` (0.068 pp) does **not** beat `trail3` (0.066 pp) or `ar3` (0.067 pp) on common-sample MAE.

## Three-month cumulative OER SA change

**Common-sample horse race (non-overlapping origins, step 3 months):** months where `trail3_x3`, `direct_ar`, and `direct_ar_zori` are all finite. n = 24; MAE (pp): trail3×3 0.170, direct_ar 0.189, direct_ar_zori 0.247.

Common-sample overlapping (every qualifying month): n = 69; MAEs trail3×3 0.187, direct_ar 0.208, direct_ar_zori 0.266.

**Unequal_n_descriptive** (each model scored on its own finite months — not a horse race): non-overlapping trail3×3 MAE 0.153 (n=29); direct_ar 0.167 (n=29); direct_ar_zori 0.247 (n=24).

## Directional OER SA yoy (6- and 12-month)

Non-overlapping 12-month (`zori_all` gap rule): hit rate 70.0% (n=10, zero_count=0).

Non-overlapping 12-month with `zori_sfr` (if present): hit rate 80.0% (n=10).

Non-overlapping 6-month gap hit rate: 80.0% (n=20).

## January 2024 methodology note (BLS SA)

2024-01 `oer_sa` mom = 0.511; `rent_sa` mom = 0.352; difference (OER − rent) = 0.159.

The BLS rent/OER notice described the originally published January 2024 seasonally adjusted changes as about **0.6 percent** for OER and **0.4 percent** for rent ([BLS notice](https://www.bls.gov/cpi/notices/2024/rent-oer-information.htm)). The frozen current vintage here is the recomputed **0.511** and **0.352**. The gap is **seasonal-factor revision**, so a latest-vintage SA backtest is not the real-time print.

**Hist sample A — every month 2015-01 through 2019-12** with both OER SA mom and rent SA mom (n = 60): median gap = -0.036, max = 0.091, share of gaps strictly below 2024-01 = 1.000.

**Hist sample B — pre-break comparison, 2012-02 through 2023-12** (2024-01 excluded; n = 143): median = -0.031, max = 0.094, share strictly below 2024-01 = 1.000.

## As-of snapshot (through 2026-09)

Not a forecast of October 2026 CPI and not an SFRI reading.

| Series | YoY % |
| --- | --- |
| oer_sa | 3.261 |
| oer_nsa | 3.261 |
| rent_sa | 2.782 |
| zori_all | 2.699 |
| zori_sfr | 3.125 |
| zori_all − oer_sa | -0.563 |

See `results/yoy_comparison.svg` for level yoy paths.
