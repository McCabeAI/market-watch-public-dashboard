# Canadian monthly industry GDP on the Activity card

## What appears in Country Detail

The macro ingestion observation store may contain **monthly** industry GDP prints on the combined StatCan vector id `monthly_v65201210;quarterly_v1594571783` (for example period `2026-08` with transformation `mom_sa_pct_and_qoq_sa_pct`). Those rows are **not** interchangeable with the calibrated **quarterly expenditure GDP** series (`GDP_real_market_prices_qq_v1594571783`, scored transformation `qoq_sa_pct` / SAAR scoring in `data/temperature_calibration.json`).

Country Detail projection surfaces the latest **YYYY-MM** store row as an extra **context** observation on `CA.Activity.gdp_domestic_demand`:

- `score_role`: context  
- `score_input`: false  
- `weight`: 0  
- Label clarifies monthly industry GDP vs quarterly expenditure GDP used in the score  
- Value and reference period are taken unchanged from the store (no rescaling)

The quarterly scored GDP observation from temperature history is unchanged. The store’s quarterly point on the same combined series id is **not** added as a second score input.

## Methodology boundary

Scoring monthly industry m/m GDP on the Activity card would be an **unapproved methodology change** (different concept, cadence, and calibration anchor from quarterly domestic-demand GDP). That change is **not** implemented. The calibrated Activity GDP component remains the quarterly q/q SA series held in history.
