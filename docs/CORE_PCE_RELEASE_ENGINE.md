# Core PCE release engine

Manual, one-release CPI/PPI to core PCE calculator. It does not score inflation, write Trader Room state, arm itself, or claim a 15-second publication SLA.

**Pilot status for the 2026-10-15 September PPI release: NOT READY.**

`prepare` can still return **PACKET READY**. That means the September 30, 2026 BEA map, Q2 2026 weights, and October 14, 2026 `PCEPILFE` vintage validate. It does not mean a core PCE number is available. With no BEA-adjusted September PPI rates in hand, the estimate headline is **INCOMPLETE**.

## What was checked before implementation

October 14, 2026 FRED `PCEPILFE` (not the older file in `data/temperature_history/raw/us/`, which ends in July and has different levels):

| Window through August 2026 | Compounded annualized | Unchanged-momentum September MoM |
| --- | ---: | ---: |
| 3-month | 2.0464% | 0.1333% |
| 6-month | 2.7443% | 0.2556% |
| 9-month | 3.2500% | 0.3156% |

`annualized_N = 100 * ((P(t) / P(t-N))^(12/N) - 1)`. The break-even month is the rate about to roll out of the window. Putting that rate back in leaves the window unchanged. The postmortem scenario table matches this arithmetic at three decimals, except September MoM 0.23% on the 9-month window: the index math is 3.13247%, which rounds to **3.132%**, while the note printed 3.133%.

Core CPI `CUSR0000SA0L1E` 337.765 → 338.896 is **+0.33485%**. That series is context only. It is not a PCE line.

BEA Table 2.4.4 U-D dated **2026-09-30** and Table 2.4.5U Q2 2026 (published 2026-09-30, core line 374 = **$19,556,763 million**) are the source map and weights. The August bridge file is not the map. Its expenditures differ (physician services 872,798 there versus 873,856 in the September 30 table), portfolio management is now implicit, and air transportation is PPI rather than CPI airline fares.

The priced partition uses expenditure-table leaves. "Less:" rows are negative weights. Food and beverages purchased for off-premises consumption (line 73), gasoline and other energy goods (line 113), and electricity and gas (line 169) are excluded. NPISH receipt lines inherit a household source only when the NIPA code matches one priced line, which is what line 356 of the source map says to do. Signed dollars reconcile to official core PCE within **$6 million** of rounding. Weights are not renormalized. No selected line has a selected ancestor.

Coverage of that partition:

| Policy | Signed weight |
| --- | ---: |
| BLS series already published SA (`bls_sa_direct`) | 0.313 |
| Needs an explicit BEA seasonal adjustment | 0.412 |
| Mixed CPI/PPI legs, weights not parsed from prose | 0.165 |
| Implicit / judgmental, not a PPI carry | 0.034 |
| Missing source | 0.034 |
| Other BEA methods (input cost and similar) | 0.032 |
| Explicit PPI composite | 0.009 |

All 60 `bls_sa_direct` lines are CPI. Club-membership CPI is one of them: the word "shopping" is not a PPI source. **There are zero direct PPI lines.** Hospitals, physicians, and air transportation are PPI with seasonal status "SA by BEA". A raw BLS PPI month is not accepted as the PCE rate. None of the 2026-08 bridge rows are accepted September carries: wrong source, implicit portfolio management, missing August rate, or SA-by-BEA.

## Verdict

HOT / NEUTRAL / COLD is the 3/6/9 pattern, not a monthly cutoff.

- A horizon moves only when its annualized rate changes by more than 0.05 percentage point.
- HOT: the 3-month window and at least one other horizon accelerate, and the post 3-month rate is above 2%.
- COLD: at least two horizons decelerate, and the 3-month window itself does not accelerate.
- Otherwise NEUTRAL.
- A 0.28% core PCE month on this vintage is NEUTRAL. It accelerates the 3-month window and leaves 6- and 9-month inside the deadband.

The headline is INCOMPLETE, and no core PCE MoM is published, when unresolved absolute weight exceeds 0.25% of core, history is short, or a ±25bp / ±50bp shift of carried rates changes the class. Absolute weight can exceed 1 when gross lines and offsetting receipts are both unresolved. Missing weight is not filled with zero and not spread onto the lines that did print. The 0.25% limit is an engineering fail-closed gate, not a BEA statistic. The ±25bp and ±50bp shifts are sensitivity cases, not estimated standard errors.

Contributions are first-order: `weight_share * component MoM`. That is not a Fisher chain-weighted replica of BEA.

## Commands

Nothing runs until one of these is invoked. `prepare` does not arm a listener. `arm` is a foreground process for the selected release, polls an inbox, and exits on a result, cancel file, or deadline. The default max runtime is 0 seconds (one look, then stop). There is no cron, workflow, or hosted worker.

```bash
python -m scripts.core_pce_release prepare ppi --release 2026-09 --out /tmp/pce-ppi-2026-09
python -m scripts.core_pce_release run --packet /tmp/pce-ppi-2026-09 --observations ./observations.json
python -m scripts.core_pce_release arm --packet /tmp/pce-ppi-2026-09 --inbox /tmp/ppi-inbox --max-runtime-seconds 900 --interval-seconds 10
```

Cancel a running arm by writing `CANCEL` in the packet directory. `prepare cpi` is the same command with `cpi` instead of `ppi`.

An observation file looks like this. A PPI line is counted only with `seasonal_status` `BEA_SA` and an `adjustment_method`. `SA` is rejected for those lines. A prior-month `mom_percent` can be carried. An index level without a base is not a carry.

```json
{
  "target_period": "2026-09",
  "source_available_at": "2026-10-15T12:30:00Z",
  "observations": [
    {
      "line": 184,
      "period": "2026-09",
      "mom_percent": "0.20",
      "seasonal_status": "BEA_SA",
      "adjustment_method": "operator-supplied BEA seasonal factor",
      "source_family": "PPI"
    }
  ]
}
```

`source_available_at` is recorded. It is not proof of when BLS published.

Live component fetch is **NOT READY**. The series registry contains only `CUSR0000SA0L1E`, and that id maps to no PCE line. The engine will not guess BLS ids.

## Latency

Measured on this checkout, 50 passes over the full 215-line basket plus flash and detailed rendering: about **0.3 ms** to calculate and **0.4 ms** to render. That is handler time after the inputs were already in memory.

Official BLS/BEA publication latency is **UNMEASURED**. The 5–15 second flash target and 30–90 second detailed target are not claimed. A local `arm` still waits on a file a person or a separate fetch drops in the inbox.

## Layout

| Path | Role |
| --- | --- |
| `scripts/core_pce_release/classify.py` | Source-text family and policy |
| `scripts/core_pce_release/build_snapshot.py` | Rebuilds the snapshot from the official workbooks (needs openpyxl; not on the hot path) |
| `data/core_pce_release/snapshot_2026-09-30/` | Map, weights, PCEPILFE vintage, August bridge dispositions |
| `scripts/core_pce_release/calculator.py` | Shared bridge |
| `scripts/core_pce_release/verdict.py` | 3/6/9 headline |
| `scripts/core_pce_release/packet.py` / `listener.py` / `cli.py` | Manual prepare, one-shot run, bounded arm |
| `tests/core_pce_release/test_release_engine.py` | History, mapping, carry, replacement, replay, prepare/arm |

Packets written by `prepare` are runtime output. `data/core_pce_release/packets/` is gitignored.

## Tests

`python -m unittest tests.core_pce_release.test_release_engine`

Covers the August windows and break-evens, the scenario table, snapshot validation, rejected August bridge carries, no double count, 0.28% not HOT, carry of a rate rather than a price level, PPI replacement leaving CPI unchanged, NSA and wrong-source rejection, mixed legs, implicit portfolio management, stale periods, the October 14 core CPI fixture as context, partial coverage staying INCOMPLETE, prepare READY/NOT READY, and a listener that stops without sleeping when max runtime is 0.

An independent review caught two fail-open cases, both fixed: CPI club membership was treated as mixed because the letters "ppi" occur inside "shopping", and a core CPI index row was accepted as a PCE-line MoM when a line number was attached. Core CPI is now context-only even if a line is present.
