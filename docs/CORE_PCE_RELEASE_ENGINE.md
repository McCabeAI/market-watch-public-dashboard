# Core PCE release engine

Manual, one-release CPI/PPI to core PCE nowcast (`nowcast_repair_v1`). It does not score inflation, arm itself, claim an 08:30 ET publication SLA, or install a schedule.

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

Nothing runs because a chat message said “prepare PPI”. There is no cron, GitHub workflow, or hosted worker in this repository.

```bash
python -m scripts.core_pce_release prepare ppi --release 2026-09 --out /tmp/pce-ppi-2026-09
python -m scripts.core_pce_release arm \
  --packet /tmp/pce-ppi-2026-09 \
  --inbox /tmp/pce-ppi-2026-09/inbox \
  --max-runtime-seconds 1800 \
  --interval-seconds 10
```

**Prerequisites:** this checkout, Python 3, and outbound HTTPS to `api.bls.gov` only when `arm` fetches live data (`--no-live-fetch` uses the inbox only). `prepare` is offline against committed history and CPI cache.

`arm` is a **foreground** process. It prints and flushes the prepared baseline immediately, then polls BLS (up to 25 priority PPI series for this pilot). Each forecast revision is printed and flushed before sleeping and before exit. Cancellation (`CANCEL` file in the packet directory), timeout, and transport errors leave the last valid `flash.txt` in place. `--max-runtime-seconds 0` emits the baseline once and stops. Official publication lag at 08:30 America/New_York is **unmeasured**; recorded times are HTTP and local handler clocks only.

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
  tests.core_pce_release.test_model_preparation
```

Packets under `--out` are runtime output; `data/core_pce_release/packets/` is gitignored.
