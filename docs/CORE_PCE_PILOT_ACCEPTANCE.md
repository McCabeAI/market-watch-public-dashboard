# Core PCE September 2026 pilot acceptance (G6)

**Verdict: PILOT READY — PRELIMINARY FORECAST**

This is an independent check of `nowcast_repair_v1` after tracks C1–C5. It is not a BEA observation, not a calibrated confidence interval, and not authorization to merge, deploy, schedule, or start tomorrow's listener.

## What was rechecked

The review reran `python3 -m unittest tests.core_pce_release` (`Ran 78 tests in 1.090s`, `OK`) and recomputed the forecast from the committed BEA history, CPI cache, and snapshot outside those tests.

Post-CPI / pre-PPI central, low, and high moms match `data/core_pce_release/model_spec.json`:

| | MoM percent | Class |
| --- | ---: | --- |
| Central | 0.3688405280179773205064998201 | HOT |
| Low | 0.1759189058295244177603611525 | NEUTRAL |
| High | 0.5030684119319698761678417501 | HOT |

`prepare ppi --release 2026-09` prints `HOT baseline 0.3688% low 0.1759% high 0.5031%` and `stage: awaiting current PPI`. The packet saves that number. Prepare does not arm a listener.

Unchanged-momentum thresholds from the committed `PCEPILFE` vintage, recomputed as the month rolling out of each window, are 0.133286079694289500446855100% (3-month), 0.255631269376306322406197300% (6-month), and 0.315633268688708651649223100% (9-month). Central 3-month and 6-month annualized deltas are both positive, so the class is HOT. The 9-month window also accelerates and is reported separately. A month exactly equal to the 6-month threshold leaves that delta at 0 and is not HOT. A 0.28% month is HOT because the unrounded 6-month delta is about +0.050 annualized points, inside the old 0.05 deadband that this pilot removed.

August published component rates used as baselines, not as September prints: physician services (line 174) 0.066307720871018221361695400%, nonprofit hospital services (lines 184 and 359, series `DNPHRG`) 0.493478210504367166323008100%, portfolio management (line 268) 0.558618378971094392494898100%. Line 346, nonprofit hospital gross output, is a published flat index and stays at 0. Lines 184 and 359 have equal and opposite weights, so a shared mom contributes nothing. Line 268 ignores brokerage PPI, including an obsolete −1.6% rate. Swapping the August portfolio baseline for that rate would move the aggregate by 0.04038609027058780992839884881 percentage points.

A synthetic `PCU622---622---` path (August PPI mom 1.0%, September 1.5%, raw BLS, footnote P, not an official release) raises lines 184, 185, and 186 by 0.50 percentage point from their own baselines and copies line 184 onto line 359. Output seasonal status is `modeled_not_bea_sa`. Line 346 does not move. The aggregate rises by 0.0141643839524976602723058002 percentage points, the positive-weight hospital remainder after the offset pair cancels. The same observations do not move the forecast a second time. The stage becomes `ppi_partial` (`PPI updated`).

The listener emits and flushes the prepared baseline before fetch, emits a changed forecast before it returns, and leaves `flash.txt` in place on cancel, deadline, and transport error. Local response-received-to-flash time on the in-process stub in `docs/CORE_PCE_PILOT_EVIDENCE.md` is 0.013863693000075727 seconds. Official 08:30 America/New_York publication lag is unmeasured.

## Not blockers

Missing BEA seasonal-factor files, a scenario class that differs from the central class, and the deferred point-in-time backtest (C7) and model selection (G8) do not withhold this preliminary number. The August first-order component sum differs from official core PCE by about 0.00395 percentage points; that gap is disclosed approximation error, not a rescale of the weights.

## Manual use

A person runs, in the foreground, from this checkout with Python 3:

```bash
python -m scripts.core_pce_release prepare ppi --release 2026-09 --out /tmp/pce-ppi-2026-09
python -m scripts.core_pce_release arm \
  --packet /tmp/pce-ppi-2026-09 \
  --inbox /tmp/pce-ppi-2026-09/inbox \
  --max-runtime-seconds 1800 \
  --interval-seconds 10
```

Prepare is offline. Arm fetches only when that second command is typed, and it needs HTTPS to `api.bls.gov`. `--max-runtime-seconds 0` prints the baseline and stops. Cancel by writing `CANCEL` in the packet directory. This acceptance does not start that process, merge the branch, or create a schedule.
