# Rates valuation repair

This note is the technical audit for the instrument-specific rates repair. It is not a trading recommendation.

## What changed

Supported outright futures use exchange DV01 instead of a duration-one identity:

| Contract | Venue | Currency | Face | DV01 per contract | Canonical mark |
| --- | --- | --- | --- | --- | --- |
| SR3 | CME | USD | 1,000,000 USD | 25 USD | implied rate, percent; index = 100 − rate |
| CRA | Montréal Exchange | CAD | 1,000,000 CAD | 25 CAD | implied rate, percent; index = 100 − rate |
| IB | ASX | AUD | 3,000,000 AUD | 3,000,000 × 0.01% × days in month / 365 AUD | implied rate, percent; AONIA month average |

A 100bp adverse move on one SR3 is 2,500 USD, which is 0.25% of face, not 1%. CRA and IB convert to USD only with a frozen FX pair (`USDCAD` or `AUDUSD`). Missing FX leaves USD P&L and risk unavailable.

Native structures (`calendar_spread`, `butterfly`, `outright_rv`, `curve_rv`) store each leg's contracts, side, currency, DV01, FX, and rate. Package P&L is the sum of leg P&L. `futures_strip_average` remains a strip. It is rejected as a curve label and is not restated as a single contract.

Sovereign holdings and any other rates line without a verified DV01 stay on the original ledger number, are flagged `isolated`, and have corrected P&L `unavailable`. No modified duration is invented.

## Benchmarks

These are mechanics checks, not sample portfolios.

- Long 1 SR3, implied rate 4.00 → 3.99 (−1bp): P&L = +25 USD.
- Long 1 CRA, USDCAD 1.36, implied rate −1bp: P&L = +25 / 1.36 USD.
- IB November 2026 (30 days): DV01 = 24.6575342466 AUD. IB October 2026 (31 days): DV01 = 25.4794520548 AUD.
- DV01-balanced SR3 calendar, both rates +1bp: package P&L = 0. Near rate +1bp and far unchanged, long calendar (pay near / receive far): P&L = +near DV01.
- A four-contract strip average is not given a curve-spread label and is not assigned single-contract DV01 when leg quantities were never stored.

## Historical ledgers

`scripts/rates/restatement.py` builds a read-only report. It does not write `data/overnight/books/latest.json`, `data/pm/books/latest.json`, trade files, or realized P&L. Stored rows that already have a position id and no `valuation_method` keep the legacy duration-one formula on the next mark-to-market. New outright futures stamp `instrument_dv01`. New strips stamp the legacy vintage and `corrected_valuation_status=unavailable` because the old booking was one synthetic mark.

Corrected USD P&L for an existing CRA or IB line is unavailable until that line carries a frozen FX observation for the mark. Those rates are not backfilled.

## Harvest and lessons

Profit-harvest thresholds use instrument DV01 when the position is on that vintage, and they record whether the mark moved with the stored `expected_mark_direction`. Reviews stay advisory. `REDUCE` and `CLOSE` are still not blocked by a missing review.

Existing lessons receive scope only from linked trade fields (`instrument`, `asset_class`, `paper_expression`, and a 6-letter FX pair split into the two stored currency codes). Text, future rule, and history are unchanged. Retrieval counts are not backfilled. A later materially matching decision must record `APPLIES`, `DOES_NOT_APPLY`, or `OVERRIDE`.

Two lessons (`dollar-king` `les-663435a31282`, `perma-bull` `les-4e8a63b10376`) cite reflections and have empty `trade_ids`. Those reflections do not store an instrument, so their scopes stay empty rather than being guessed from the prose.

## Remaining work

- Historical non-USD futures cannot be restated in USD without a frozen FX observation on each mark. The report leaves them unavailable.
- Sovereign DV01 is unavailable until a verified duration or bond-level DV01 source is admitted. Do not substitute duration one.
- ESTR and TONA are not given SR3/CRA DV01. They stay unresolved.
- Applying the restatement onto the live ledger is a separate reviewed migration. This change does not run it.
