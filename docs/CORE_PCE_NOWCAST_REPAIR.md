# Core PCE nowcast repair contract (G0)

Method version `nowcast_repair_v1`. This document freezes the September 2026 pilot. C1, C2, and C3 implement it in parallel against the interfaces below. They do not reopen the method. C7 point-in-time backtesting and G8 model selection are deferred and are not blockers.

The numerical result is a first-order preliminary forecast. It is not a BEA observation, not a Fisher chain-weighted official core PCE print, and not a calibrated confidence interval.

## What was verified

BEA Table 2.4.4U monthly price indexes, sheet `U20404-M` inside `Section2All_xls.xlsx`, published 2026-09-30, workbook sha256 `6ab82fff44c97fceabf2c2248e44309fcc8a16a6b59646004488f500aec32e44`. The sheet says months are seasonally adjusted, 2017=100, through 2026M08. The extract is `data/core_pce_release/snapshot_2026-09-30/bea_component_history.json` (sha256 `35c4f0ac0d714c5b2aba461347b671ec677ed23726a3352720af45deafa5206f`).

All 215 signed accounting terms in the 2026-09-30 snapshot have July and August indexes. No term needs a zero fill or a parent fallback on this vintage. Parent indexes are still stored so a later suppressed leaf can fall back without renormalizing.

August component monthly changes from that extract, which are August actuals and not September forecasts:

| Line | Component | August MoM |
| --- | --- | ---: |
| 174 | Physician services | 0.066307720871018221361695400% |
| 184 and 359 | Nonprofit hospital services to households (same price series `DNPHRG`) | 0.493478210504367166323008100% |
| 268 | Portfolio management and investment advice | 0.558618378971094392494898100% |
| 346 | Nonprofit hospitals, gross output | 0% exactly (published flat index 132.587, not an unknown) |

Signed weights on 184 and 359 are equal and opposite (`±0.05964622059386821837540292328`). Identical moms cancel. Gross output 346 is a different series (`DHSORG`) and is not a PPI Hospitals line. Proprietary hospitals (185) and government hospitals (186) keep their own baselines.

Portfolio management is implicit on the 2026-09-30 Table 2.4.4 U-D. `PCU5231505231501011` maps to brokerage line 262, not line 268. Replacing the August portfolio baseline with an obsolete −1.6% PPI would move the aggregate by `0.04038609027058780992839884881` percentage points. That mapping is forbidden.

Line 16, employee reimbursement, stores a negative expenditure and a negative `weight_share` while its `sign` field is 1. Aggregation uses `weight_share`. Do not edit the legacy snapshot to "fix" the sign field.

The August first-order sum of `weight_share * component MoM` is `0.2513914988704109365301230746%`. Official `PCEPILFE` August MoM is `0.247439158399483605234644600%`. The gap `0.0039523404709273312954784746` percentage points is approximation error. Do not rescale weights to remove it.

Unchanged-momentum September monthly rates, from the committed `PCEPILFE` vintage, are the months rolling out of each window:

- 3-month: June/May = `0.133286079694289500446855100%`
- 6-month: March/February = `0.255631269376306322406197300%`
- 9-month: December/November = `0.315633268688708651649223100%`

The arithmetic mean of the official June, July, and August core PCE monthly rates is `0.1689697247543891152821540333%`. The prompt's 0.16895% figure is that benchmark rounded. It is not a target the component model must hit.

Recorded October 14 CPI points live in `data/core_pce_release/cpi_cache_2026-10-14.json`. September PPI is absent from that cache. Core CPI `CUSR0000SA0L1E` September/August is context only (`0.334848%` class of figure). It is not a core PCE MoM.

## Central forecast

For every included line, in order:

1. `observed_bls_sa` when the line's policy is `bls_sa_direct`, the registry entry is CPI, `usable_as_pce_rate` is true, and the CPI cache has both the target month and the anchor month. Monthly percent is the BLS SA index ratio. Do not put a seasonal bridge on top. Do not do this for PPI.
2. Otherwise `baseline_last_published_mom`: the BEA component index ratio for anchor over the prior month. This is the pre-PPI assumption for PPI, NSA, mixed, implicit, and unmatched lines.
3. `parent_category_baseline` only when the line itself lacks a positive anchor index or prior index. Use the nearest ancestor in `ancestor_lines` that has both indexes. Do not use a parent when the line has its own history.
4. `integrity_blocked` only when the line still has no positive history after that parent check. A published zero change (line 346) is a real baseline, not a block and not a fill.

Three-month geometric average is the scenario alternative, not the central value. For rates `r1`, `r2`, `r3` in percent over the three months ending at the anchor:

```text
geo = 100 * (((1+r1/100)*(1+r2/100)*(1+r3/100)) ** (1/3) - 1)
```

Use `Decimal`. The low scenario picks, on each non-observed line, the mom among `{last, geo}` that produces the smaller `weight_share * mom`. The high scenario picks the larger contribution. Observed SA CPI lines stay fixed in all three scenarios. The range is not a confidence interval.

Lines that share a `bea_series_code` in `data/core_pce_release/source_overrides.json` must finish with the same mom. Copy the primary line's mom onto the offset. Do not estimate the offset independently.

Reference recomputation with the committed history and CPI cache, post-CPI and pre-PPI:

| | MoM percent | Class |
| --- | ---: | --- |
| Central | 0.3688405280179773205064998201 | HOT |
| Low | 0.1712571775488444585440198840 | NEUTRAL |
| High | 0.5077301402126498353841830186 | HOT |

Displayed at 4 decimal places, half up: central `0.3688`, low `0.1713`, high `0.5077`. A 0.27% illustration and the unverified chat figure of about 0.23% are not this forecast. An implementation of this formula must match the full-precision central, low, and high strings.

## PPI replacement

Raw BLS stays raw. Component output seasonal status for a PPI or NSA update is `modeled_not_bea_sa`. Never `BEA_SA`.

When a current-period source mom and an anchor-period source mom both exist for a line that is still on the baseline:

```text
updated = baseline_last_published_mom + (source_mom(target) - source_mom(anchor))
```

Method `source_news_bridge`. The aggregate moves by `weight_share * (source_mom(target) - source_mom(anchor))` for that line, once. A second observation with the same fingerprint does not move it again.

Hospital PPI `PCU622---622---` is one news shock. Lines 185 and 186 add that shock to their own baselines. Line 359 copies line 184's full updated mom. Line 346 is not in the group.

Ambiguous physician series `PCU6211--6211--` and `PCU62111-62111-` update line 174 only when both current moms agree. If they disagree, keep the baseline and record the conflict.

If only the target-month source exists, and the line is not `observed_bls_sa`, set the central mom to that raw source mom with method `current_raw_proxy_not_bea_sa`. Keep the historical baseline inside the scenario pair. Still do not label it BEA-SA.

Implicit lines 163, 255, and 268 ignore CPI and PPI observations. Their central value stays the published component history.

Mixed and composite lines without explicit leg weights in `source_overrides.json` stay on their own BEA history. Do not parse prose weights. `name_variants` is empty. Do not invent series ids. Near misses (`dry cleaning`, `sewerage`, domestic air title variants) stay unmatched and keep the historical baseline.

## Classification

No 0.05 annualized-point deadband. No 0.25% unresolved-weight gate. A class that changes in the low or high scenario does not suppress the central number.

```text
HOT if 3-month delta > 0 and 6-month delta > 0
COLD if 3-month delta < 0 and 6-month delta < 0
NEUTRAL otherwise
```

Equality with the unchanged-momentum rate is not acceleration and not deceleration. The 9-month direction is reported on its own. The gap from each post-release annualized rate to 2% is reported on its own and is not an input to the class.

Under this rule a 0.28% September core PCE month is HOT, because the unrounded 6-month delta is about `+0.04995` annualized points. The old deadband called that month NEUTRAL. Tests that encode the old rule have to change.

`INCOMPLETE` is reserved for integrity failures: snapshot validation failure, a line with no history and no parent, a non-positive index on a month that is used, a shared-series group whose moms diverge, or an observation that fails an integrity guard and would otherwise replace a number with a corrupted one. In that last case keep the last valid forecast and do not publish the bad update. Ordinary missing PPI, missing BEA seasonal factors, preliminary PPI footnote `P`, and scenario-sensitive classes are not integrity failures.

Stale period, wrong family for an `observed_bls_sa` slot, non-positive index, monthly percent outside ±15, inconsistent mom versus index ratio, and conflicting fingerprints stay rejected. Those guards stay in `observations.py`.

## Information stages

- `post_cpi_pre_ppi`, stage text `awaiting current PPI`, from prepare until a current-period PPI observation changes at least one line.
- `ppi_partial`, stage text `PPI updated`, after that change. Lines still on a baseline remain visible.
- `blocked`, stage text `integrity blocked`, only for the integrity cases above. No central number.

Prepare does not arm a listener. The packet stores the numeric baseline, the stage, and the scenario range.

## Frozen interfaces

`prepare_model.py`:

```python
def load_component_history(path: Path | None = None) -> dict: ...
def load_cpi_cache(path: Path | None = None) -> dict: ...
def build_baseline(components, history, cpi_points, registry, *, target_period: str, anchor_period: str) -> dict: ...
```

`build_baseline` does not fetch and does not classify. It returns `method_version`, `rows`, `central_mom_percent`, `low_mom_percent`, `high_mom_percent`, `reliability_abs_weight` with keys `observed`, `transformed`, `carried`, `proxy`, `baseline`, and `integrity` `{blocked, reasons}`. Each row includes `line`, `name`, `weight_share`, `bea_series_code`, `method`, `method_version`, `mom_percent`, `low_mom_percent`, `high_mom_percent`, `contribution_percent`, `seasonal_status_output`, `source_identity`, `assumption`, `reliability`, `shared_driver_group`, and `replaced_by_observation` (false at baseline).

Reliability of the pre-PPI central rows is `observed` or `carried`. Absolute reliability weights use `abs(weight_share)` and sum to the absolute weight of the 215 lines. Do not renormalize.

`estimates.py`:

```python
def apply_observations(baseline: dict, components, observations, *, target_period: str) -> dict: ...
```

Returns a bundle of the same shape plus `attribution` and `information_stage`. One observation changes a line once. Offset copies are one logical update.

`uncertainty.py`:

```python
def scenario_bounds(rows: list[dict]) -> dict: ...
def classification_sensitive(central: str, low: str, high: str) -> bool: ...
```

`verdict.py`:

```python
def classify_momentum(deltas: dict[int, Decimal], post_3m: Decimal | None = None) -> str: ...
def nine_month_direction(delta_9: Decimal) -> str: ...
def gap_to_two(post_rates: dict[int, Decimal]) -> dict[int, Decimal]: ...
```

`post_3m` is ignored so older callers do not crash. It must not bring back the 2% HOT requirement or the deadband.

`calculator.calculate` keeps the existing positional arguments and adds `baseline=None`. When `baseline` is omitted it loads the committed history, CPI cache, registry, and overrides and builds one. It always fills 3/6/9 before, after, and delta when history is long enough, including when no live observations were passed. `projected_core_pce_mom_percent` is the central string unless `integrity.blocked`.

`bls.fetch_series` enforces `model_spec.json` `bls_budget`: timeout 8 seconds, at most two attempts per request, at most four requests per acquire, overall elapsed time 20 seconds, chunk 25 without a key and 50 with a key. No per-series v1 cascade. Read `BLS_API_KEY` or `BLS_REGISTRATION_KEY` from the environment if set. Do not print the key. Record `requests_made`, `elapsed_seconds`, `budget_exhausted`, and `key_present` as a boolean.

`acquire.fetch_plan` for kind `ppi` returns at most 25 priority PPI series, ordered by absolute weight, excluding implicit lines. CPI series already in the committed cache for the target month are not polled again. Ambiguous PPI candidates are a second request only when the priority request succeeded and budget remains. Raw observations remain `role: raw_bls_reference` with `applied_to_estimate` false at the BLS boundary. The forecast layer reads that raw mom. It does not flip the flag to pretend the print is BEA-SA.

## Delivery that C4 must implement

`prepare ppi --release 2026-09` calculates and saves the numeric post-CPI/pre-PPI baseline. It prints the class and the central, low, and high moms. It does not start a listener.

`arm` prints and flushes that prepared baseline immediately, then fetches. On each meaningful PPI revision it prints and flushes before sleeping and before the process exits. If PPI has not arrived, the stage text remains `awaiting current PPI`. Cancellation, timeout, stale input, and transport errors leave the last valid flash in place. The process is foreground only. Nothing in this contract schedules 2026-10-15, installs a worker, or starts a listener by itself.

## File ownership

| Track | Files |
| --- | --- |
| G0 | this document, `model_spec.json`, `source_overrides.json`, the history extract, the CPI cache |
| C1 | `build_registry.py`, `classify.py`, `snapshot.py`, `prepare_model.py`, `test_model_preparation.py` |
| C2 | `estimates.py`, `uncertainty.py`, `calculator.py`, `observations.py`, `verdict.py`, `test_forecasting.py` |
| C3 | `bls.py`, `acquire.py`, `normalize.py`, `ledger.py`, `test_acquisition.py` |
| C4 | `packet.py`, `listener.py`, `cli.py`, `report.py`, `docs/CORE_PCE_RELEASE_ENGINE.md`, `test_delivery.py` |
| C5 | `test_release_engine.py`, `test_pilot_e2e.py`, fixtures, `docs/CORE_PCE_PILOT_EVIDENCE.md` |
| G6 | `docs/CORE_PCE_PILOT_ACCEPTANCE.md` |

C1 does not change `classify_source` results or `validate_snapshot` failures. Legacy snapshot files stay as committed. C1 may load the history beside the snapshot. C2 and C3 do not rewrite G0 data files.

## Pilot limits

BEA's unpublished seasonal factors are not reproduced. The news bridge is a disclosed model, not a claim that BEA will print the same component. The scenario band is wide because volatile components differ between last month and the three-month geometric average. Official 08:30 ET publication lag is unmeasured. No dashboard, Supabase, temperature score, schedule, or trading action is in this repair.
