# Rates valuation repair

This note is the technical audit for the instrument-specific rates repair. It is not a trading recommendation.

## What changed

Supported outright futures use exchange DV01 instead of a duration-one identity:

| Contract | Venue | Currency | Face | DV01 per contract | Canonical mark |
| --- | --- | --- | --- | --- | --- |
| SR3 | CME | USD | 1,000,000 USD | 25 USD | implied rate, percent; index = 100 − rate |
| CRA | Montréal Exchange | CAD | 1,000,000 CAD | 25 CAD | implied rate, percent; index = 100 − rate |
| IB | ASX | AUD | 3,000,000 AUD | published A$24.66 per bp on a fixed 30/365 quotation | implied rate, percent; monthly average OCR is the settlement reference only |

A 100bp adverse move on one SR3 is 2,500 USD, which is 0.25% of face, not 1%. CRA and IB convert to USD only with a frozen FX pair (`USDCAD` or `AUDUSD`). Missing FX leaves USD P&L and risk unavailable.

Native structures (`calendar_spread`, `butterfly`, `outright_rv`, `curve_rv`) store each leg's contracts, side, currency, DV01, FX, and rate. Package P&L is the sum of leg P&L. `futures_strip_average` remains a strip. It is rejected as a curve label and is not restated as a single contract.

Sovereign holdings and any other rates line without a verified DV01 stay on the original ledger number, are flagged `isolated`, and have corrected P&L `unavailable`. No modified duration is invented.

## Benchmarks

These are mechanics checks, not sample portfolios.

- Long 1 SR3, implied rate 4.00 → 3.99 (−1bp): P&L = +25 USD.
- Long 1 CRA, USDCAD 1.36, implied rate −1bp: P&L = +25 / 1.36 USD.
- IB, every expiry month: DV01 = A$24.66, the published value of a 0.01 price move. February and 31-day months use the same BPV. The unrounded 30/365 identity is about 24.6575 and is not the valuation.
- DV01-balanced SR3 calendar, both rates +1bp: package P&L = 0. Near rate +1bp and far unchanged, long calendar (pay near / receive far): P&L = +near DV01.
- A four-contract strip average is not given a curve-spread label and is not assigned single-contract DV01 when leg quantities were never stored.

## Lot lifecycle

OPEN, ADD, REDUCE, and CLOSE on a stamped outright or structure change integer contracts, not only descriptive notional.

- A request that would close or add less than one lot is not a fill (`sub_lot_request_is_not_a_fill`). Contracts, notional, and P&L stay put. History result is `zero_lot`.
- A partial reduce keeps `floor(old_lots × remaining_notional / old_notional)` and realizes P&L only on the lots removed. Halving 13 lots leaves 6 and closes 7. The 0.5 lot gap is residual DV01, not a fractional fill.
- Each structure leg uses that rule on its own count. A 13/26/13 butterfly and a 13-lot CAD calendar hedged with 10 USD lots therefore close different numbers of contracts. Realized P&L is the sum of those closed lots at the current valid rate and FX.
- Those per-leg floors are only a candidate. The resize is booked when every active role, side, and curve remains (a full close may zero them), every active leg changes together, and the change in signed USD DV01 for the package and for each curve stays within one contract of the largest leg plus the structure's existing unrounded residual (`atomic_package_one_contract_residual`). A 2-lot leg beside a 1-lot leg cannot take a 60% reduce or a 50% add. That request is `size_rejected` and reports the smallest notional step that does pass. No leg, notional, cost basis, P&L, or risk capital changes. `pending_mark` remains the result when the size itself is legal and the current mark or FX is not.
- An outright ADD sizes new contracts from the added face at the current FX and blends entry by those contracts times the current price. Pretrade shocked risk uses that same lot count and FX.
- A real fill with a missing or stale mark or FX is `pending_mark`. It does not invent P&L or change the lot count. A later packet with a valid price and FX can complete the close.
- Single CRA and IB positions refresh `mark_fx_*` (status, as-of, pair, source) on every mark and exit. `entry_fx_*` is not overwritten. USD SR3 stays on the identity rate. If the current CAD or AUD fixing is missing or stale, USD P&L and DV01 are unavailable and the mark price is cleared with the FX.
- Rows that were never stamped `instrument_dv01` and have no legs stay on the legacy duration-one formula. This path does not write contracts onto them.

## Review repairs

- Trader OPEN/HEDGE admission builds the same whole-lot legs as the booked position before the risk cap. A USD 2bn SR3 calendar is 2,000 lots and a USD 5m 100bp-spread shock, not 1% of face.
- A failed or partial structure mark clears the package and every leg. Current and realized P&L stay unavailable. REDUCE/CLOSE with no current mark is `pending_mark` and does not invent a fill. A missing harvest review still does not block a marked REDUCE/CLOSE.
- New bookings use whole exchange lots. Descriptive notional is not rewritten onto the lot count. Floor-toward-zero is the anchor policy (`13.6` lots books `13`, residual disclosed). Hedge legs use nearest half-up.
- Entry FX is stored and kept. Current USD DV01 and P&L use the latest frozen fixing only. A missing or stale fixing does not fall back to the entry rate.
- A new rates, curve, or rates-RV open without verified legs or contract DV01 fails closed. Rows that already have a position id and no instrument stamp keep the legacy vintage for restatement.

## Historical ledgers

`scripts/rates/restatement.py` builds a read-only report. It does not write `data/overnight/books/latest.json`, `data/pm/books/latest.json`, trade files, or realized P&L. Stored rows that already have a position id and no `valuation_method` keep the legacy duration-one formula on the next mark-to-market. New outright futures stamp `instrument_dv01`. New strips stamp the legacy vintage and `corrected_valuation_status=unavailable` because the old booking was one synthetic mark.

Corrected USD P&L for an existing CRA or IB line is unavailable until that line carries a frozen FX observation for the mark. Those rates are not backfilled. Relative analytics still list observed levels only. They do not add historical distributions or carry/roll.

The three pinned-file assertions that fail on this branch also fail against `origin/main` with the same bytes: flat `trend-follower` net is already −191,227.75, flat `swinger` net is already 279,919.04, and the value-guy trade SHA-256 is `a86cff7b…` rather than the older pin `bf9bb075…`. This repair does not rewrite those files.

## Harvest and lessons

Profit-harvest thresholds use instrument DV01 when the position is on that vintage, and they record whether the mark moved with the stored `expected_mark_direction`. Reviews stay advisory. `REDUCE` and `CLOSE` are still not blocked by a missing review.

Existing lessons receive scope only from linked trade fields (`instrument`, `asset_class`, `paper_expression`, and a 6-letter FX pair split into the two stored currency codes). Text, future rule, and history are unchanged. Retrieval counts are not backfilled. A later materially matching decision must record `APPLIES`, `DOES_NOT_APPLY`, or `OVERRIDE`.

Two lessons (`dollar-king` `les-663435a31282`, `perma-bull` `les-4e8a63b10376`) cite reflections and have empty `trade_ids`. Those reflections do not store an instrument, so their scopes stay empty rather than being guessed from the prose.

## Remaining work

- Historical non-USD futures cannot be restated in USD without a frozen FX observation on each mark. The report leaves them unavailable.
- Sovereign DV01 is unavailable until a verified duration or bond-level DV01 source is admitted. Do not substitute duration one.
- ESTR and TONA are not given SR3/CRA DV01. They stay unresolved.
- Applying the restatement onto the live ledger is a separate reviewed migration. This change does not run it.
