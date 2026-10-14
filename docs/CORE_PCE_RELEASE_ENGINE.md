# Core PCE release engine

Manual, one-release CPI/PPI to core PCE calculator. It does not score inflation, write Trader Room state, arm itself, or claim a publication SLA.

## Pilot verdict for the 2026-10-15 September PPI release: NOT READY

A core PCE momentum headline is not available. The 2026-10-14 live BLS pull produced **INCOMPLETE / unresolved_weight**. It did not produce HOT, NEUTRAL, or COLD.

`prepare` prints **PACKET READY**. That only means the September 30, 2026 BEA map, Q2 2026 weights, and October 14, 2026 `PCEPILFE` vintage validate. The same print says **pilot: NOT READY** and **estimate: INCOMPLETE**. Do not read PACKET READY as permission to publish a core PCE number.

Measured on this checkout against `https://api.bls.gov/publicAPI/v2/timeseries/data/` for the 105 verified series in the PPI plan:

| Clock | Seconds | What it is |
| --- | ---: | --- |
| BLS HTTP, 105 series in five requests of 25 | 1.271 | Source acquisition after the API already held the data |
| Flash after the response was in memory | 0.00206 | Local handler |
| Detailed ledger after that | 0.00237 | Local handler |
| Official publication lag from the BLS release instant | UNMEASURED | Not a 5–15 second or 30–90 second claim |

The 5–15 second flash target and the 30–90 second detail target are not claimed. 1.271 seconds is how long the public API took on the afternoon of 2026-10-14, when September CPI was already posted and September PPI was not. It is not the lag from 08:30 America/New_York.

Coverage of that pull, using the committed Q2 weights and no renormalization:

| Result | Value |
| --- | ---: |
| Lines with a BLS-SA CPI rate used in the bridge | 54 |
| Signed weight of those lines | 0.298117 |
| Lines with a raw BLS reference that was not used | 72 |
| Unresolved absolute weight | 0.904491 |
| Fail-closed limit | 0.0025 |
| Resolved contribution | 0.1603, labeled not a core PCE estimate |
| August bridge rows accepted as September carries | 0 |

Core CPI `CUSR0000SA0L1E` September/August was 338.896/337.765, MoM **0.334848%**. That is context only.

## Operator command

Nothing runs because a chat message said "Prepare PPI to core PCE". This repository has no hosted worker, no cron, and no GitHub workflow for the release. A person has to start a foreground process and leave that shell open.

```bash
python -m scripts.core_pce_release prepare ppi --release 2026-09 --out /tmp/pce-ppi-2026-09
python -m scripts.core_pce_release arm \
  --packet /tmp/pce-ppi-2026-09 \
  --inbox /tmp/pce-ppi-2026-09/inbox \
  --max-runtime-seconds 1800 \
  --interval-seconds 10
```

Prerequisites: this checkout, Python 3, and outbound HTTPS to `api.bls.gov`. `prepare` does not fetch. `arm` fetches. `--max-runtime-seconds 0` does one look and exits; the 1800 second bound has to be typed for the morning window. It is not a schedule. Cancel by writing `CANCEL` in the packet directory. `prepare cpi` is the same command with `cpi` instead of `ppi`.

`arm` keeps a ledger. An incomplete batch does not stop the process. A later batch updates the flash and appends `revisions.jsonl` with the 3/6/9 windows, the contribution delta, the source latency, and the handler time. The same observation is ignored. A different rate for the same line, period, and series is kept as a conflict and the line stays unresolved. A response whose latest period moves backward is rejected as a stale cache. A file whose `target_period` is not the armed release is rejected.

The headline becomes HOT, NEUTRAL, or COLD only when unresolved absolute weight is within 0.0025 of core, history is long enough, and a ±25bp / ±50bp shift of any carried PCE rate does not change the class. Otherwise the first line is INCOMPLETE and no core PCE MoM is published.

## Source map

BEA Table 2.4.4 U-D dated **2026-09-30** and Table 2.4.5U Q2 2026 (core line 374 = **$19,556,763 million**) are the source map and weights. Signed dollars reconcile to official core PCE within **$6 million**. Weights are not renormalized.

BLS series ids come from the official PDQ catalogs `POST https://data.bls.gov/PDQWeb/survey/cu` and `POST https://data.bls.gov/PDQWeb/survey/pc`, joined to each catalog's series master. A BEA source name is accepted only when one catalog title equals it after case and whitespace normalization. Near misses stay unmatched. CPI ids are monthly U.S. city average rows (series id character 4 is `R`). Semiannual `CUUS` ids are not used. Rebuild with `python -m scripts.core_pce_release.build_registry` when those catalogs are on disk. The committed registry is `data/core_pce_release/series_registry.json`.

Spot checks of the BLS series pages on 2026-10-14:

| Series | Official item / title | Use |
| --- | --- | --- |
| `CUSR0000SEHA` | Rent of primary residence, seasonally adjusted | PCE rate where BEA says SA CPI |
| `CUSR0000SERF01` | Club membership for shopping clubs, fraternal, or other organizations, or participant sports fees | PCE rate. The letters inside "shopping" are not a PPI source |
| `CUSR0000SA0L1E` | All items less food and energy | Context only |
| `PCU622---622---` | Hospitals, not seasonally adjusted | Raw reference only |
| `PCU5231505231501011` | Brokerage services, equities and ETFs, not seasonally adjusted | Raw reference only |

Usable PCE rates are the 36 CPI-U SA series whose BEA seasonal status is `SA` and whose policy is `bls_sa_direct`. Signed weight **0.298117**. Every other verified series is a reference.

Raw PPI is not labeled BEA-SA. Where several BLS products share one BEA title, the MoM is shown only if every product prints the same rate, and even then it is not used in the estimate. If the indexes differ, there is no rate.

August 2026 examples from the live pull, all reference-only:

| BEA source | What BLS printed | Decision |
| --- | --- | --- |
| PPI Hospitals | `PCU622---622---` August/July = 253.510/251.940, MoM **0.623164%**, footnote P preliminary. Latest period August. | Shown, not used. This is the same 0.6232% the old bridge quoted, and it is still not a PCE rate because BEA says SA by BEA |
| PPI Offices of physicians | `PCU6211--6211--` and `PCU62111-62111-` are the same index, August MoM **0.034476%** | Shared raw rate shown, not used |
| PPI Home health care services | 4- and 5-digit indexes are 173.369; the 6-digit index is 173.446 | No rate. The titles match and the indexes do not |
| PPI Nursing care facilities | Three titles, three different August indexes | No rate |
| PPI Domestic scheduled passenger air transportation | No current BLS industry-product title equals that string. Nearby titles such as "Scheduled passenger air transportation" and a product named only "Domestic" were not used | Unmatched |

The August bridge file is still not a carry source. Physician services in that file were a CPI table, portfolio management is implicit, and the hospital row was a raw PPI. `accepted_august_bridge_carries` remains 0.

NSA CPI is the same kind of gap. Prescription drugs matched `CUUR` and printed a September reference of about **-1.245%**. BEA does not call that line BLS-published SA, so the engine does not use it. Several CPI names are one character away from a BLS title (`drycleaning` / `dry cleaning`, `sewage` / `sewerage`) and stayed unmatched on purpose.

Mixed, implicit, and missing lines stay unresolved. Portfolio management (line 268) rejects a PPI carry. Mixed lines need explicit leg weights; the prose weights were not parsed. There is no BEA component seasonal-factor file in this run, so no model approximation is substituted for SA-by-BEA.

## Arithmetic that was checked before the repair

October 14, 2026 FRED `PCEPILFE` (not the older file in `data/temperature_history/raw/us/`, which ends in July and has different levels):

| Window through August 2026 | Compounded annualized | Unchanged-momentum September MoM |
| --- | ---: | ---: |
| 3-month | 2.0464% | 0.1333% |
| 6-month | 2.7443% | 0.2556% |
| 9-month | 3.2500% | 0.3156% |

`annualized_N = 100 * ((P(t) / P(t-N))^(12/N) - 1)`. The break-even month is the rate about to roll out of the window. The postmortem scenario table matches this arithmetic at three decimals, except September MoM 0.23% on the 9-month window: the index math is 3.13247%, which rounds to **3.132%**, while the note printed 3.133%.

Core CPI 0.33485% is context only. It is not a core PCE estimate.

## Verdict rule

HOT / NEUTRAL / COLD is the 3/6/9 pattern, not a monthly cutoff.

- A horizon moves only when its annualized rate changes by more than 0.05 percentage point.
- HOT: the 3-month window and at least one other horizon accelerate, and the post 3-month rate is above 2%.
- COLD: at least two horizons decelerate, and the 3-month window itself does not accelerate.
- Otherwise NEUTRAL.
- A 0.28% core PCE month on this vintage is NEUTRAL. It accelerates the 3-month window and leaves 6- and 9-month inside the deadband.

The headline is INCOMPLETE, and no core PCE MoM is published, when unresolved absolute weight exceeds 0.25% of core, history is short, or a ±25bp / ±50bp shift of carried rates changes the class. Missing weight is not filled with zero and not spread onto the lines that did print. Contributions are first-order: `weight_share * component MoM`. That is not a Fisher chain-weighted replica of BEA.

## What was not fixed

- BEA's own seasonal factors for SA-by-BEA and NSA lines are unpublished here, so tomorrow's PPI print cannot enter the estimate even after `arm` sees it.
- Air transportation, several near-miss CPI titles, mixed input-cost lines, implicit portfolio management, and lines with no source stay unresolved.
- Home health and nursing care are not mapped to one BLS id.
- No dashboard, hosted listener, schedule, or Market Watch wiring was added.
- Publication lag at 08:30 ET was not measured. The API can also be late, throttled, or revised (PPI footnote P).

## Tests

`python -m unittest tests.core_pce_release.test_release_engine`

35 tests. They cover the August windows and break-evens, the scenario table, snapshot validation, rejected August bridge carries, no double count, 0.28% not HOT, carry of a rate rather than a price level, PPI replacement leaving CPI unchanged, NSA and wrong-source rejection, mixed legs, implicit portfolio management, stale periods, the October 14 core CPI fixture as context, the recorded October 14 BLS component pull staying INCOMPLETE with the hospital reference at 0.6232% unused, a simulated later PPI batch that updates the reference and still does not publish a class, duplicate and conflict handling, the 25-series API limit, prepare/arm not looping, and cancellation.

Packets written by `prepare` are runtime output. `data/core_pce_release/packets/` is gitignored.
