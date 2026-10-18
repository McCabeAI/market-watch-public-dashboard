# Canadian CPI Monthly Nowcaster — Cursor build handoff (2026-10-18)

## Objective
Build a **reusable, deterministic, human-triggered pre-release Canadian CPI nowcast** in this repository. **No Astra/LLM is required for monthly runs.** Preserve the US core PCE engine unchanged. First target September 2026 CPI for October 19 release; subsequent months are parameterized. No auto-scheduled execution.

## Prior research (already completed — do not repeat)
- `docs/research/CANADA_CPI_2026_10_17_ASTRA_RESEARCH.md`: full October 17 decision, component architecture, primary links, methods and limitations.
- `docs/research/CANADA_CPI_2026_10_17_RESEARCH_CODE.md`: original experiment scripts and README, recovered from research evidence archive.
- `docs/research/ca_cpi_reference/aggregate_metrics.csv`: historical model/baseline score target.
- `docs/research/ca_cpi_reference/aggregate_predictions.csv`: 2017–2026 research forecast traces.
- `docs/research/ca_cpi_reference/canadian_fuel_monthly.csv`: verified historical NRCan fuel data excerpt.
The original full evidence ZIP is available separately to the chat, but its container copy lacked a valid central directory and its final large component-predictions member was truncated. Above source code and aggregate reference files were recovered intact; verify their provenance and refresh full official StatCan/NRCan input tables legitimately in the build. Do not treat research artifacts as a substitute for source acquisition.

## Model and outputs
- **Central baseline: B2** as specified in report: eight mutually exclusive Canada CPI major groups; rolling Canadian seasonal/momentum baseline + NRCan gasoline and furnace-oil direct bridges + prior-month house-only NHPI replacement-cost bridge. Canada-specific 2026 link weights and proper price updating. Do not double-count parent/children. Do not activate experimental cross-border C2 by default.
- **Underlying inflation must receive equal prominence**: official-style forecast of ex-energy excluding all energy products (distinct from ex-food-and-energy), ex-food-and-energy NSA and SA, and official CPI-trim/CPI-median release forecasts + 3m annualized momentum; where verified data insufficient say estimated/unavailable rather than manufacture official values.
- Headline NSA MoM, index, YoY, SA MoM, ex-gasoline YoY, gasoline contribution, component contribution table, reliable range, source availability, assumptions and comparison with timestamped consensus if legitimately accessible.
- Sept 2026 reference research (not hardcoded result): headline +0.1325% NSA m/m; +0.498% SA; +3.108% YoY; gasoline +0.2133pp contribution; ex-food/energy +0.24% SA and +2.23% YoY; trim ~1.845% YoY; median ~1.904% YoY. Candidate B2 Jan2017–Aug2026 MAE 0.204pp vs A 0.266pp, seasonal average 0.260pp. Independent input-vintage verification required; any discrepancy explained.
- Use empirically validated aggregate residual ranges, not simultaneous-extreme sum or unexplained confidence intervals. Mark historical pseudo-OOS vs true release-vintage scores prominently. Do not claim edge versus consensus without a historical as-of consensus panel.

## Operational contract
- One explicit manual command e.g. `python -m scripts.canadian_cpi_release nowcast --release YYYY-MM --as-of ... --out ...`, with latest eligible StatCan, NRCan, NHPI, optional BLS/BoC inputs and timestamped source manifests. Repeated invocations must be idempotent or produce independent immutable named runs; freeze pre-release information set; never ingest release-month CPI actual before its publication into the forecast; actuals/post-release scoring as separate action.
- Prefer an existing GitHub issue/manual workflow interface for phone-triggering; if a **new** production manual-dispatch Action is necessary, request explicit user authorization before creating it (CI rules prohibit incidental workflow expansion). Do not add cron, listener, automatic retries, model calls, premium tokens, or unsolicited notifications.
- Strict immutable source ID/date/seasonal-status/units/basket-vintage and source-hash provenance; quarantine wrong month, future-publication, overlap and missing mandatory inputs; sensible fallback per missing optional predictor. Fail visibly on stale weights or broken source contracts. Keep older frozen runs/first prints.
- Operational CLI must be testable offline using exact saved fixtures with no live HTTP required; live run fetches official public data with bounded calls/backoff. Run once as Sept 2026 frozen pre-release replay and show full output, without claiming deployment.

## Cursor-only graph and budget
G0 Grok 4.7: review repo architecture, translate existing B2 research into bounded interfaces/testable acceptance; C1 Composer 2.5: source acquisition/registry, vintage-safe cache; C2 Composer 2.5: B2 weighting/forecasts + core metrics (parallel with C1 only disjoint files); C3 Composer 2.5: offline fixtures/CLI/integration/prospective score plan; G4 Grok 4.7: exact-head final acceptance. Planned 5 internal agent invocations, budget cap 10 total incl corrections and Grok cap 3. Only grok-4.7 and composer-2.5. No Opus/Sonnet/Auto.

Deliver one pushed PR with focused tests, source manifest, launch/runbook, dated forecast and backtest comparison. Do not merge, run Market Watch daily/trader/PM, deploy, create schedules or touch ACP code.
