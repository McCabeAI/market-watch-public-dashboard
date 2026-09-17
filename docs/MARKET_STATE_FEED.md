# Market State Feed

Status: minimal operational feed for Trader Room context.

## Purpose

This feed is intentionally small. It gives Market Watch and future Trader Room agents a deterministic daily snapshot of the market backdrop without requiring a paid data vendor, API key, Supabase write, or LLM call.

It is research context, not executable pricing and not a replacement for professional market-data systems.

## Coverage

- U.S. Treasury: 2Y, 5Y, 10Y, 30Y.
- Bank of Canada: 2Y, 5Y, 10Y, long benchmark yields.
- RBA: 2Y, 5Y, 10Y government yields.
- RBNZ: 2Y, 5Y, 10Y government yields.
- G10 FX: all 45 unique crosses constructed from the same ECB daily euro reference fixing.
- Derived context: 1D/5D/1M/3M rate and spread moves; 2s10s and 5s10s curves; CA-US, AU-US, NZ-US, AU-NZ and CA-AU matching-tenor spreads; FX returns, 20D/60D realized vol, percentile/z-score and moving-average distance.

## Run it

```bash
python -m pip install -r requirements-sal.txt
PYTHONPATH=. python scripts/run_market_state.py --output market-state/market_state.json
```

No secrets are required. `run_market_state.py` is the production entrypoint; it keeps the deterministic Sal calculations intact while using the current one-series-per-call Bank of Canada Valet route.

The weekday GitHub Action runs at 09:30 UTC and also supports manual `workflow_dispatch`. The output is uploaded as the `market-state` artifact for three days. The workflow is deliberately independent of the dashboard Pages build and Supabase.

## Trader Room contract

Before a debate, the orchestration layer may run the same command and provide the resulting JSON packet to the agents. Agents may interpret discrepancies and market transmission, but they must not overwrite source observations or present ECB reference rates as live executable FX prices.

Top-level JSON keys are `schema_version`, `generated_at`, `window_start`, `rates`, `rate_rv`, `fx`, `sources`, and `method`.

Each rate/spread/FX observation carries an `as_of` date. Country and FX blocks also carry `age_days`, so stale observations are visible rather than silently replaced. Required source or parser failures terminate the run; the feed does not silently substitute another provider or forward-fill one market to force a cross-market match.

## Scope boundary

Do not add OIS, swaps, options, consensus, CESI, commodities, equities or paid-vendor data merely because they would be useful. Add another feed only when Trader Room usage shows that the missing input repeatedly changes decisions.
