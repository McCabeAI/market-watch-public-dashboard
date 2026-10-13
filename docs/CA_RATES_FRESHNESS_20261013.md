# Canadian benchmark yield freshness (2026-10-13)

## What happened on launch `mwl-20261013T101157Z-bfa76346`

Ingest and acquire succeeded. Stage 03 quality gate returned `no_markable_universe` even though other sovereign legs were usable that morning.

## Collected evidence

- Bank of Canada Valet group `bond_yields_benchmark` last observation: **2026-10-08**
- Calendar age on 2026-10-13: **5 days** → legacy `stale_after_days` (4) marked `CA_rates` stale
- `CA_rates` was in the trader preflight set, so packet `status` became `stale`, the `market_state` family flipped stale, and `evaluate_gate` exited before per-leg isolation

Other legs that morning were fine (US 2026-10-09, AU 2026-10-07, NZ 2026-10-12, EA 2026-10-13, JP 2026-10-09, FX ok).

## Official source check

- The series has **no 2026-10-09 row** (Friday business day; print absent in Valet at diagnosis time)
- **2026-10-12** is Canadian Thanksgiving (closed on the publication calendar)
- **2026-10-13** launch at 10:11:57Z (06:11 ET) was **before** the 09:30–10:00 ET daily publication window

Publication convention (bankofcanada.ca): prior mid-market closing yields, published once per Canadian business day in that morning window, with a brief processing delay. Friday’s close would normally appear on the next Bank publication morning (Tuesday after the holiday weekend); it was not in Valet at diagnosis time. We do **not** assume the Oct 9 mark exists or rewrite Oct 8 forward.

## Behavior change

- Canadian **business-day calendar** plus **one-session publication lag** (`canada_business_day_publication_lag`)
- Provenance on `rates.CA`: `age_calendar_days`, `age_business_days`, `minimum_fresh_observation`, `publication_lag_business_days`
- **CA staleness no longer flips packet preflight** or erases unrelated markable markets in the quality gate when `preflight_stale_sources` is only `CA_rates`
- **CA-dependent new risk** and **existing-book** exposures that need `CA_rates` fail closed with `existing_book_unmarkable`. The gate reads the launch store (`overnight_store_root`), including trader `seats` and PM `pms`, and does not skip a present book that cannot be parsed. Unrelated markets stay listed in `trade_eligible_countries` when the block is the book rather than an empty universe.
- US / AU / FX / CFTC global checks unchanged; no synthetic marks or backdated observations

## Worked example (observation 2026-10-08)

| `today` (ET calendar) | `ca_observation_status` | `minimum_fresh_observation` |
| --- | --- | --- |
| 2026-10-13 | ok | 2026-10-08 |
| 2026-10-14 | stale (if still 2026-10-08) | 2026-10-09 |

Weekends and Bank publication holidays do not age the series; calendar `age_days` may still be 5 on Oct 13 while business-day age is 2.
