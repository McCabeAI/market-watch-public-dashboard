# Scenario results — ChatGPT CORRA receive

Snapshot average **3.11375** (packet `0bc766c948f4…`).

## Existing position (USD MTM, futures-only)

| Case | Scenario avg | Gap (bp) | Receive MTM USD |
| --- | ---: | ---: | ---: |
| A | 2.7500 | 36.375 | 909,375.00 |
| B | 3.2625 | -14.875 | -371,875.00 |
| C | 2.9625 | 15.125 | 378,125.00 |
| Stress +20 bp parallel | — | +20 | -500,000.00 |
| Stress −20 bp parallel | — | −20 | 500,000.00 |

## U/Z half-DV01 trap (rejected)

Lower stress loss reflects half DV01, not a better expression; U/Z average gap vs 2.75 (47.500 bp) exceeds four-leg scenario-A gap (36.375 bp) while dollar MTM under A (593750.00) is smaller than full strip (909375.00).

## Rejected SOFR and AONIA

A standalone equal-weight **receive** on SR3H7–SR3Z7 (not held) would show scenario-A MTM **634,375 USD** and scenario-C MTM **0 USD** on matched 25k USD/bp; the research owner rejected adding SOFR.

A **pay** on AONIA Nov-2027–Apr-2028 (illustrative 168.96 lots/month for 25k AUD/bp) has bucket futures average **4.65667**; ±20 bp parallel pay MTM is **500,000** / **-500,000 AUD**. Scenario sign flips for this bucket were argued in the rates memo; this script does not convert them into an expected value. Not combined with the CORRA book.
