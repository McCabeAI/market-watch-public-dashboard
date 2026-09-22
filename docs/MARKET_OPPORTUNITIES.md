# Market Data: opportunity monitor

The Market Data tab starts with a ranked research watchlist. It is designed to direct a rates/FX trader's attention, rather than duplicate a live terminal. Other dashboard tabs are unchanged.

## Views

- **Watchlist:** at most ten qualified screens, ordered by absolute statistical extremeness. No invented conviction score. Related tenors and FX quote exposures are capped at two per group.
- **Curves & rates:** 2s5s, 2s10s, 5s10s, and equal-yield-weight 2s5s10s butterflies; matching-tenor cross-market spreads; outright yield stretches. Click an expression for its history and methodology.
- **Cross-asset:** ten predeclared economically relevant relationships, with model residuals and both 126D and 20D correlations; macro-driver changes and stretches.
- **Carry:** common-date 2Y sovereign yield advantage divided by annualized 60-observation FX volatility. This is a screening proxy, not executable forward carry or bond carry/roll-down. Forward points, funding, basis, costs and duration-neutral construction remain Bloomberg checks.
- **All data:** searchable FX, rates, curves, spreads and macro-driver diagnostics.

## Mathematics and gates

Calculations are deterministic in `scripts/market_opportunities.py`; no model calls.

Level percentiles and population-standard-deviation z-scores use up to 252 **prior** observations, excluding the current observation. At least 200 prior observations are required. Flat samples have a null z-score. Percentiles use midpoint ties. A level screen qualifies at |z| >= 1.5 or the outer 5% of the empirical sample.

Move windows count 1, 5, 21 and 63 observations. Prices/FX use log percentage changes; rates and spreads use basis-point differences. Move z-scores use up to 252 prior same-horizon changes and require at least 60. Overlapping windows are descriptive, not independent statistical tests. A move screen qualifies at |z| >= 2.

Cross-asset regressions use aligned daily log returns or yield/spread changes, never regressions of unrelated trending levels. They fit 126 prior matched daily changes, exclude the latest observation from estimation, and standardize its residual by prior residual dispersion. Gaps over four calendar days are excluded. No forward filling. A divergence alert requires |residual z| >= 2, |126D correlation| >= .35, and the same correlation sign over the latest 20 training observations. These gates are practical screens, not significance or profitability claims. Daily closing/fixing times differ; same calendar date does not guarantee synchronous pricing.

Curve fly = `2 * y5 - y2 - y10`, in basis points. Positive means the 5Y yield is above the wings' average. This is not a DV01-neutral butterfly. Curve slopes = long yield minus short yield. Cross-country spreads = first country minus second, on exact common dates.

Stale, unavailable and insufficient-history screens are excluded from the ranked watchlist. They remain visible in diagnostics. Freshness is measured from the observation date, including as the published page ages, not from the last build timestamp. Broad-dollar source lag differs from market-close series. WTI and Brent use completed continuous-futures daily bars. The UI shows the precise common date of every relationship and carry screen.

## Added regular collection

`market_state.build_snapshot()` now collects these on every normal invocation, including the existing daily workflow, overnight collection and Pages build. No new model schedule, provider, credential, database, or canonical history warehouse is introduced. Raw fetched history remains transient; the packet contains a bounded analytical read model.

| Series | Source / identifier | Caveat |
| --- | --- | --- |
| S&P 500 | FRED / SP500 | Closing price index, not total return |
| Nasdaq Composite | FRED / NASDAQCOM | Closing price index |
| Dow Jones | FRED / DJIA | Closing price index |
| Russell 2000 | Yahoo Finance / ^RUT | Vendor daily close |
| Gold | Yahoo Finance / GC=F | Continuous futures history, roll discontinuities possible |
| WTI | Yahoo Finance / CL=F | Continuous front-contract futures history; roll discontinuities possible |
| Brent | Yahoo Finance / BZ=F | Continuous futures history; roll discontinuities possible |
| Copper | Yahoo Finance / HG=F | Continuous futures history, roll discontinuities possible |
| VIX | FRED / VIXCLS | Index points, not a tradable security |
| US high-yield OAS | FRED / BAMLH0A0HYM2 | Percent converted to bp; FRED history limited to three years |
| US 10Y real yield | FRED / DFII10 | Percent converted to bp |
| US 10Y breakeven | FRED / T10YIE | Percent converted to bp; not a pure inflation forecast |
| Broad USD | FRED / DTWEXBGS | Trade-weighted, not DXY; publication lag |

Requests use five bounded concurrent workers, twenty-second timeouts and two attempts. A failed added series emits explicit source error/status and empty history; no vendor substitution. Current-day Yahoo bars are discarded because they may be incomplete. The original core US/CA/AU/ECB hard-failure policy and NZ-unavailable behavior are preserved.

Primary source notes checked September 18, 2026:
- https://fred.stlouisfed.org/series/SP500
- https://finance.yahoo.com/quote/CL%3DF/
- https://finance.yahoo.com/quote/BZ%3DF/
- https://fred.stlouisfed.org/series/DFII10
- https://fred.stlouisfed.org/series/BAMLH0A0HYM2
- https://finance.yahoo.com/quote/GC%3DF/history/
- https://www.gold.org/goldhub/data/gold-prices (historical LBMA daily data removed; not silently used as a gold feed)

## Verification

Run `PYTHONPATH=. python -m unittest tests.test_market_state tests.test_market_opportunities -v`, `node --check patch_v12/market-data.js`, and the existing Pages reconstruction/patch gates. Verify the deployed tab, all five views, expanded evidence, scope/horizon controls and source coverage. Live source checks are distinct from deterministic tests.

Rollback uses the prior Git version of `patch_v12` and the three generator modules/workflow edits; no database migration is involved.

## Public read model

The daily/internal packet retains the full research calculations. Pages passes `--public`: S&P/Dow underlying levels and history are omitted, leaving derived screens; ICE high-yield index data/statistics are source-link-only because its source notes explicitly restrict redistribution. This does not change the collection schedule or internal evidence coverage.

The live overnight collector previously imported nonexistent `generate_snapshot`; it now calls `build_snapshot`. A regression test exercises the actual live-collection branch with a mocked source packet and verifies the cross-asset payload is retained.
