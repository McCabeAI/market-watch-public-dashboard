# Core PCE release engine

Manual, one-release CPI/PPI to core PCE nowcast (`nowcast_repair_v1`). It does not score inflation, arm itself, claim an 08:30 ET publication SLA, or install a schedule.

`.github/workflows/run-ppi-oneshot.yml` is a separate one-shot for the issue title `[run-ppi] 2026-09`. It is not the listener, and it does not install a schedule.

## September 2026 PPI pilot

`prepare ppi --release 2026-09` computes the post-CPI / pre-PPI numerical baseline from committed BEA component history and the October 14, 2026 CPI cache. It prints and writes the class, central/low/high scenario moms, horizons, and reliability weights. It does **not** call BLS, does **not** arm a listener, and does **not** mark the estimate INCOMPLETE merely because September PPI is still unpublished.

Reference baseline (full precision in `detailed.json`, four decimal places half-up on the flash):

| | MoM % | Class |
| --- | ---: | --- |
| Central | 0.3688405280179773205064998201 | HOT |
| Low scenario | 0.1759189058295244177603611525 | NEUTRAL |
| High scenario | 0.5030684119319698761678417501 | HOT |

Flash first line (display):

```text
HOT baseline 0.3688% low 0.1759% high 0.5031%
stage: awaiting current PPI
```

The scenario band is **not** a confidence interval. Classification uses unrounded 3-month and 6-month momentum deltas (strictly positive for HOT, strictly negative for COLD, otherwise NEUTRAL). The 9-month direction and gap to 2% are reported separately. For this baseline the classification is **sensitive** (central HOT, low NEUTRAL, high HOT).

Raw BLS PPI enters through `source_news_bridge` or `current_raw_proxy_not_bea_sa` with output seasonal status `modeled_not_bea_sa`. It is never labeled BEA-SA.

`INCOMPLETE` / `integrity blocked` is reserved for snapshot validation failure, missing component history, shared-series divergence, and other integrity guards—not for missing PPI.

C7 point-in-time backtesting and G8 model selection are **not** part of these commands.

## Operator commands

A chat message does not run this calculator. There is no cron and no listener workflow. The one-shot path is an issue titled exactly `[run-ppi] 2026-09`, opened by a human collaborator with admin, maintain, or write permission, with the event sender equal to the issue author. The workflow authenticates that creator, runs `run-ppi` once, comments the numbers, uploads `audit.json`, and exits. It does not arm the listener, poll, retry later, deploy, or call a model.

Missing, stale, or unpublished September PPI is commented as `NOT YET AVAILABLE`. A throttled or failed BLS response is commented as `ERROR`. Neither case replaces the offline baseline.

`import-price` replays the frozen October 15 PPI central from committed fixtures and leaves that central unchanged. The October 16 import-air observation is reported only as a **labeled NSA sensitivity envelope** for BEA line 335. The command does not arm the listener, does not call BLS, and does not change the `[run-ppi]` workflow or trigger. See `docs/CORE_PCE_IMPORT_PRICE_2026-10-16.md`.

```bash
python -m scripts.core_pce_release prepare ppi --release 2026-09 --out /tmp/pce-ppi-2026-09
python -m scripts.core_pce_release run-ppi --release 2026-09 --out /tmp/pce-ppi-2026-09
python -m scripts.core_pce_release import-price --release 2026-09 --out /tmp/pce-import-2026-09
python -m scripts.core_pce_release arm \
  --packet /tmp/pce-ppi-2026-09 \
  --inbox /tmp/pce-ppi-2026-09/inbox \
  --max-runtime-seconds 1800 \
  --interval-seconds 10
```

Optional live-arm flags: `--bls-daily-ceiling N` (int ≥ 0) overrides the per-process local daily HTTP cap for this packet; a higher `N` does not create BLS quota. `--not-before` is a timezone-aware ISO-8601 timestamp that replaces the September 2026 PPI pilot default gate.

**Prerequisites:** this checkout, Python 3, and outbound HTTPS to `api.bls.gov` only when `arm` fetches live data (`--no-live-fetch` uses the inbox only). `prepare` is offline against committed history and CPI cache.

`arm` is a **foreground** process. Live unattended polling is not installed; run `prepare` then `arm` manually. It prints and flushes the prepared baseline immediately, then may fetch BLS (up to 25 priority PPI series for this pilot). `--interval-seconds 10` wakes the listener that often; pacing and the local daily ledger decide how often HTTP runs. Default local ceilings are **8** HTTP calls per Eastern day without a registration key and **24** with `BLS_API_KEY` or `BLS_REGISTRATION_KEY` set, versus public BLS allowances of 25 and 500. A key is not a remaining balance, and other programs' use of the same allowance is unknown, so BLS can still reject requests inside this cap. The September PPI pilot does not call BLS before **2026-10-15 08:30 America/New_York** unless the operator passes `--not-before`. On local ceiling, an unreadable ledger, or BLS throttle, network stops, the last flash remains, and the process prints a `bls_quota: …` status line. An unreadable `{packet}/bls_quota.json` is not replaced with a zero count. Re-arming the same packet the same Eastern day continues that ledger. Each forecast revision is printed and flushed before sleeping and before exit. Cancellation (`CANCEL` file in the packet directory), timeout, and transport errors leave the last valid `flash.txt` in place. `--max-runtime-seconds 0` emits the baseline once and stops. Official publication lag at 08:30 America/New_York is **unmeasured**; recorded times are HTTP and local handler clocks only.

Information stages:

| Stage | Flash text |
| --- | --- |
| `post_cpi_pre_ppi` | `awaiting current PPI` |
| `ppi_partial` | `PPI updated` |
| `blocked` | `integrity blocked` (no central percent) |

`revisions.jsonl` records the baseline and each central change with horizons, `information_stage`, and attribution.

## Source map (summary)

BEA Table 2.4.4U dated 2026-09-30 and Q2 2026 weights anchor the component map. BLS series ids come from the committed `data/core_pce_release/series_registry.json`. Core CPI `CUSR0000SA0L1E` in the CPI cache is context only, not a core PCE MoM.

## Tests

```bash
python -m unittest tests.core_pce_release.test_delivery \
  tests.core_pce_release.test_forecasting \
  tests.core_pce_release.test_model_preparation \
  tests.core_pce_release.test_run_ppi_oneshot \
  tests.core_pce_release.test_import_price_incremental
```

Packets under `--out` are runtime output; `data/core_pce_release/packets/` is gitignored.
