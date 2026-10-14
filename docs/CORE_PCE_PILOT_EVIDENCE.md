# Core PCE September 2026 PPI pilot evidence (track C5)

Factual record from the committed checkout and the unittest run documented below. Method version `nowcast_repair_v1` (G0); no schedules or live network listeners were added in this track.

## Command prerequisites

- Checkout this repository and Python 3.
- Offline baseline: `python -m scripts.core_pce_release prepare ppi --release 2026-09 --out <dir>` uses committed BEA component history (`data/core_pce_release/snapshot_2026-09-30/`) and CPI cache (`data/core_pce_release/cpi_cache_2026-10-14.json`). No BLS calls.
- Live fetch: `arm` needs outbound HTTPS to `api.bls.gov` only when a human runs it without `--no-live-fetch`. Nothing in the repo arms or schedules a release by itself.

## Prepare output (2026-09 PPI, offline)

First flash line:

```text
HOT baseline 0.3688% low 0.1759% high 0.5031%
```

Full-precision scenario moms (central / low / high):

| | MoM % |
| --- | ---: |
| Central | 0.3688405280179773205064998201 |
| Low | 0.1759189058295244177603611525 |
| High | 0.5030684119319698761678417501 |

Classification: central **HOT**, low scenario **NEUTRAL**, high scenario **HOT** (sensitive across the scenario range).

Horizons (annualized %, before → after → delta) with unchanged-momentum monthly thresholds from `model_spec.json`:

| Window | Before | After | Delta | Unchanged-momentum MoM % |
| --- | ---: | ---: | ---: | ---: |
| 3-month | 2.046398408308198674504153700 | 3.010011452941926280034213200 | +0.963613044633727605530059500 | 0.133286079694289500446855100 |
| 6-month | 2.744271114822287402650029700 | 2.976441015962943524610234700 | +0.232169901140656121960205000 | 0.255631269376306322406197300 |
| 9-month | 3.249969468981784987499425400 | 3.322994092058747847779467400 | +0.073024623076962860280042000 | 0.315633268688708651649223100 |

Stage after prepare: `post_cpi_pre_ppi` / flash text `awaiting current PPI`.

## August sentinels (BEA component history, not September forecasts)

| Line | Component | August MoM % |
| --- | --- | ---: |
| 174 | Physician services | 0.066307720871018221361695400 |
| 184 & 359 | Nonprofit hospital services to households (`DNPHRG`) | 0.493478210504367166323008100 |
| 268 | Portfolio management and investment advice | 0.558618378971094392494898100 |
| 346 | Nonprofit hospitals, gross output | 0 (flat published index) |

Rejected obsolete portfolio PPI at **−1.6%** on line 268 (implicit; does not replace the August baseline). Replacing the August component rate with that PPI would move the first-order aggregate by **0.04038609027058780992839884881** percentage points, which is `weight_share × (August mom − (−1.6))`, not the weight times −1.6 alone.

## Synthetic hospital PPI exercise

Fixture: `tests/core_pce_release/fixtures/synthetic_september_ppi_hospitals.json` (**synthetic**, not an official BLS release).

| Field | Value |
| --- | --- |
| Series | `PCU622---622---` |
| August PPI MoM | 1.0% |
| September PPI MoM | 1.5% |
| `role` | `raw_bls_reference` |
| `source_family` | PPI |
| `seasonal_status` (observation) | BLS_NSA |
| Footnote | P |
| Output `seasonal_status_output` on moved lines | `modeled_not_bea_sa` |

News bridge (+0.5 pp shock on the PPI versus August anchor) updates lines **185** and **186**; **184** and **359** share the same updated mom (offset pair, net zero contribution from the shared mom); **346** gross output stays at **0%** mom.

| | Central MoM % |
| --- | ---: |
| Post-CPI / pre-PPI baseline | 0.3688405280179773205064998201 |
| After synthetic September PPI | 0.3830049119704749807788056203 |
| Aggregate delta | 0.0141643839524976602723058002 |

The aggregate delta matches `(weight_share_185 + weight_share_186) × 0.5` (184/359 cancel).

## Local handler timing (in-process stub)

Measured with `time.perf_counter` in `tests/core_pce_release/test_pilot_e2e.py` (`test_listener_synthetic_hospital_ppi_revision`): clock starts when the synthetic PPI observation dict is already in memory inside the stub `fetch`, stops when `emit` returns the flash whose body includes `stage: PPI updated`.

| Metric | Seconds |
| --- | ---: |
| Response-received → flash (same run) | 0.013863693000075727 |
| First-detection → flash (in-process stub handler) | 0.013863693000075727 |
| Official 08:30 America/New_York publication lag | **UNMEASURED** |

## Assumptions and limitations

- First-order signed expenditure shares; not Fisher chain-weighted official core PCE.
- BEA unpublished seasonal factors are not reproduced; PPI enters via disclosed bridge/proxy with `modeled_not_bea_sa`, never labeled BEA-SA on raw BLS.
- Low/high scenario band is not a confidence interval; classification can differ across scenarios without suppressing the central print.
- Component classification and weights are scenario-sensitive; Q2 2026 weights anchor the map.
- No point-in-time backtest in this pilot (C7 / G8 deferred).

## Unittest

```bash
python3 -m unittest tests.core_pce_release
```

Result from the run that produced this document:

```text
Ran 78 tests in 1.076s

OK
```
