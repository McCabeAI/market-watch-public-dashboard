# Sal Market Data V1

Status: implementation candidate

## Purpose

Sal is the deterministic market-data layer for the Market Watch light dashboard. It performs source retrieval, validation, normalization and arithmetic only. It makes zero model calls. AI reasoning starts downstream, after Sal has produced a validated market-state packet.

V1 covers:

- US, Canada, Australia and New Zealand sovereign benchmark yields;
- curve measures from those tenors;
- matching-tenor cross-country rate spreads;
- the complete 45-pair G10 FX matrix;
- deterministic history statistics used for context, not trade decisions.

This does not add OIS, IRS, cross-currency basis, forwards, options or executable market prices.

## Source policy

Live external authorities remain the source of truth. Sal downloads enough official history on each run to calculate the requested context. It does not create a second canonical historical warehouse in GitHub or Supabase.

| Data | Source | V1 fields |
| --- | --- | --- |
| US rates | U.S. Treasury daily par yield curve | 2Y, 5Y, 10Y, 30Y |
| Canada rates | Bank of Canada Valet benchmark bonds | 2Y, 5Y, 10Y, long |
| Australia rates | RBA F2 government-bond yields | 2Y, 5Y, 10Y |
| New Zealand rates | RBNZ B2 wholesale interest rates | 2Y, 5Y, 10Y |
| G10 FX | ECB euro foreign exchange reference rates | EUR, GBP, AUD, NZD, USD, CAD, CHF, NOK, SEK, JPY |

Source notes:

- RBA F2 values are RBA closing-yield assessments, are not financial benchmarks, are updated weekly for observations two business days earlier, and must be displayed as research context with the observation date.
- RBNZ B2 benchmark government-bond yields are indicative closing rates with a one-day publication lag.
- ECB FX reference rates are information/reference rates and are not executable prices. Sal derives each G10 cross from the same ECB fixing, so no asynchronous legs are mixed.
- Google Finance is not a production source. Google Finance/GOOGLEFINANCE terms restrict professional/commercial reuse, storage and redistribution in ways that are incompatible with this public/professional research workflow.

All public display must attribute the underlying authorities and must not imply their endorsement.

## Data contract

The generated JSON contains `schema_version`, `generated_at`, `window_start`, `rates`, `rate_rv`, `fx`, `sources` and `method`.

Every displayed rate or spread includes an observation date. Cross-country rate spreads use the latest exact common observation date for both countries at that tenor; Sal does not forward-fill one country to match another.

## Deterministic calculations

### Rates

For each available tenor Sal calculates latest yield; 1D, 5D, 1M and 3M basis-point changes; and 1Y/5Y percentile and z-score. Curves are 2s10s and 5s10s. Cross-country RV covers CA-US, AU-US, NZ-US, AU-NZ and CA-AU at 2Y, 5Y and 10Y.

A percentile at or below 10 or at or above 90 is only a statistical-stretch flag. Sal may not label a market cheap/rich or generate a trade.

### FX

The ECB publishes each non-EUR currency as foreign-currency units per EUR. For BASE/QUOTE, Sal computes `BASEQUOTE = QUOTE_per_EUR / BASE_per_EUR` using the same fixing date.

The 10 G10 currencies produce exactly 45 unique pairs. Each pair gets spot reference value; 1D/5D/1M/3M/6M/1Y return; 20D/60D annualized realized volatility; 1Y/5Y spot-level percentile and z-score; distance from 20D/50D/200D moving averages; and 52-week high/low. Positive return means the base currency appreciated against the quote currency under the displayed orientation.

## Runtime and failure behavior

`scripts/sal_market_data.py` is T0 deterministic execution. It must not call an LLM or AI service.

The runtime fails closed when a required source cannot be fetched after bounded retries, required tenors/currencies cannot be identified, the output is not exactly 45 G10 crosses, values fail basic sanity gates, or the output schema is incomplete. A failed Sal build prevents a new Pages artifact from deploying, leaving the last known-good page live.

## Dashboard scope

V1 adds Sovereign Rates Monitor, Rates Relative Value, and G10 FX Focus. All 45 crosses remain available in a collapsed table. The page identifies FX values as reference rates and Australian yields as non-benchmark RBA research data.

## AI boundary

Sal output may be handed to downstream AI together with macro state. AI may identify a discrepancy candidate, explain transmission or pass evidence to the Trader Room. AI may not overwrite Sal observations or deterministic calculations.

`official sources -> Sal -> validated market-state packet -> dashboard -> AI discrepancy interpretation -> Trader Room`
