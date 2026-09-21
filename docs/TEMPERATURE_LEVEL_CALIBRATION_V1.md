# Temperature LEVEL + IMPULSE calibration V1

Status: ACTIVE. Replaces the 2026-09-17 50-baseline cumulative-impulse operational index as the economic meaning of the 1–100 gauges.

Calibration date: **2026-09-21**.  
History window: **2025-09-21 through 2026-09-21**.  
Machine parameters: `data/temperature_calibration.json`.  
Source observations: `data/temperature_history/{us,ca,au,nz}.json`.  
Independent data audit: `docs/TEMPERATURE_HISTORY_AUDIT_C5.md` (PASS-WITH-FINDINGS, no blocking issues).

## 1. What changed

The previous live score was:

`score = 50 + Σ (fixed weight × classified release impulse)` since an arbitrary reindex on 2026-09-17.

That index drifted because releases occurred, treated 50 as a date rather than an economy, and could not be reproduced from current observations alone. It is retained in git history only as a comparison.

The V1 gauges are two separate objects:

1. **LEVEL (1–100):** current economic state. Reproducible from the latest sourced observations + this document’s anchors/scales + deterministic code. A stable economy with no new data does **not** drift.
2. **IMPULSE / direction:** whether the latest print of each component heated or cooled that component’s LEVEL versus its own prior print. Impulse is not accumulated into LEVEL.

Display bands are unchanged: 1–20 Cold, 21–40 Cool, 41–60 Neutral, 61–80 Warm, 81–100 Hot.

## 2. Meaning of 50

50 is a **structural / policy neutral**, not a trailing-year average and not the 2026-09-17 reindex.

| Family | 50 means | Anchor kind |
|---|---|---|
| Inflation | The currency’s inflation **target / target midpoint** on the scoring transform (US: Fed 2% PCE objective on 3-month annualized Core PCE; CA/NZ: 2% y/y; AU: RBA 2–3% **midpoint 2.5%** y/y) | `structural_policy` |
| Unemployment | Country **u\*** / full-employment unemployment rate | `structural_policy` |
| Wages | Inflation target (or AU midpoint) **+ 1.0pp** trend labour productivity | `structural_policy` |
| Employment / payrolls | Employment change consistent with **working-age trend** (documented round-number trend, lower conviction than u\*) | `structural_trend` |
| GDP | **Potential real growth** expressed as SAAR | `structural_policy` |
| Business surveys (PMI) | Diffusion **expansion threshold 50** | `structural_policy` |
| Consumer flows | Period-over-period growth consistent with **real potential ~2% SAAR**, or **nominal (target + 2%)** when the series is nominal | `structural_policy` |
| Consumer confidence | Index-specific par / long-run normal (Michigan ~80; Westpac-MI 100; ANZ-Roy Morgan 100) | `structural_policy` |

No component uses “12-month sample median = 50”. The one-year history is for reconstructing LEVEL paths and checking pathologies, not for anchoring 50.

## 3. Weights (unchanged)

No weight change is made. Missing inputs reduce **coverage**; they are omitted from the LEVEL average rather than treated as 50 and rather than inventing values.

- US Inflation: Core PCE 100%. `mapped_bridge` does **not** enter LEVEL (provisional impulse metadata only).
- CA/AU/NZ Inflation: underlying 60% / headline 40%. CA underlying = **equal average of CPI-trim and CPI-median y/y** for the same month (collapse rule for C5 finding).
- Labor: unemployment 70% / wages 20% / employment or payrolls 10%.
- Activity: GDP 60% / surveys 40%. US surveys: services 28% + manufacturing 12%.
- Consumer: retail 25% / income 25% / spending 25% / confidence 25%.

## 4. LEVEL formula

For a scored component with latest transform value `x`:

```
component_level = clip(50 + hot_direction × (x − anchor) × scale_per_unit, 1, 100)
```

`hot_direction` is `+1` when a higher `x` is hotter, `−1` when a higher `x` is colder (unemployment).

For a dimension with fixed weights `w_i`:

```
coverage = Σ w_i    for components with an observed LEVEL
level    = (Σ w_i × component_level_i) / coverage     if coverage > 0
level    = null                                        if coverage = 0
```

This is **explicit** coverage renormalization, reported as `coverage` on every dimension. It is not a silent change to the published 70/20/10 (etc.) weights. Missing components do not contribute a fake 50.

US Inflation `mapped_bridge` is never part of `coverage` or `level`.

## 5. Transforms

Transforms are applied to the **pinned series_id** in `data/temperature_calibration.json`. Extra series in the history files are context.

| Transform | Definition |
|---|---|
| `yoy_pct` | Stored official or derived 12-month percent change |
| `mom_sa_compound_annualized_n3` | Last 3 consecutive m/m percent changes, compounded: `((Π(1+m_i/100))^(12/3)−1)×100` |
| `trailing_mean_n3` | Mean of the last 3 period values (payrolls/employment LEVEL; survey LEVEL) |
| `qoq_to_saar` | `((1+q/100)^4−1)×100` on the **latest single quarter** (Activity GDP impulse) |
| `mean_qoq_to_saar_n2` | Mean of SAAR equivalents of the last 2 q/q percent prints: per quarter `((1+q/100)^4−1)×100`, then average (Activity GDP LEVEL for q/q-stored series) |
| `trailing_mean_n2` | Mean of the last 2 published values (Activity GDP LEVEL when storage is already SAAR, e.g. US BEA SAAR) |
| `mom_mean_n3` | Mean of last 3 m/m percent changes (consumer monthly flows) |
| `diffusion_index` | PMI / diffusion level as published |
| `index_level` | Survey index as published |
| `percent` | Unemployment rate as published |

If fewer than `n` points exist, use the longest available trailing window of the same transform (never invent). If only one employment change exists, score that one print and flag `short_window`.

## 6. Component pins and anchors

### Inflation

| Country | Series | Transform | Anchor | Scale | Hot + |
|---|---|---|---:|---:|---|
| US | `PCEPILFE` 3m annualized m/m | `mom_sa_compound_annualized_n3` | 2.0 | 12.5 | higher |
| CA und | mean(CPI-trim, CPI-median) y/y | `yoy_pct` | 2.0 | 12.5 | higher |
| CA head | all-items CPI y/y | `yoy_pct` | 2.0 | 12.5 | higher |
| AU und | trimmed mean y/y `A130400382R` | `yoy_pct` | 2.5 | 12.5 | higher |
| AU head | headline y/y `A130393721F` | `yoy_pct` | 2.5 | 12.5 | higher |
| NZ und | CPI ex food/energy/fuel y/y | `yoy_pct` | 2.0 | 12.5 | higher |
| NZ head | headline CPI y/y | `yoy_pct` | 2.0 | 12.5 | higher |

Scale 12.5 → target±4pp maps to 1–100.

### Labor

| Country | u\* | Wage 50 | Employment-trend 50 | Employment scale |
|---|---:|---:|---|---|
| US | 4.2 (FOMC longer-run ballpark) | 3.0% y/y AHE | **10k** m/m 3-mo avg (2026 Fed breakeven-employment anchor; see `docs/US_PAYROLL_BREAKEVEN_ANCHOR.md`) | 0.20 per thousand |
| CA | 6.0 | 3.0% y/y | +25k m/m 3-mo avg | 0.20 per thousand |
| AU | 4.5 | 3.5% y/y WPI | +25k m/m 3-mo avg | 0.20 per thousand |
| NZ | 4.75 | 3.0% y/y LCI | +8k q/q | 1.0 per thousand |

Unemployment scale: **20 per percentage point**, `hot_direction = −1`.  
Wage scale: **10 per percentage point**, `hot_direction = +1`.

### Activity

| Country | GDP series | LEVEL transform | IMPULSE transform | Potential SAAR | Scale |
|---|---|---|---|---:|---:|
| US | `A191RL1Q225SBEA` | 2Q mean published SAAR (`trailing_mean_n2`) | latest single-quarter SAAR (`identity`) | 2.0 | 10 |
| CA | `GDP_real_market_prices_qq_v1594571783` | 2Q mean q/q→SAAR (`mean_qoq_to_saar_n2`) | latest q/q→SAAR (`qoq_to_saar`) | 1.8 | 10 |
| AU | `A2304370T` (GDP; DFD is context) | `mean_qoq_to_saar_n2` | `qoq_to_saar` | 2.25 | 10 |
| NZ | **`SNEQ.SG01RSC01B01PC` production GDP only** | `mean_qoq_to_saar_n2` | `qoq_to_saar` | 2.0 | 10 |

**Surveys (when observed):** LEVEL = 3-month mean of headline diffusion index (`trailing_mean_n3`); IMPULSE = latest month minus prior month (`identity` on each print). Anchor 50, scale 1.0.

US ISM services/manufacturing: 12 months of official press releases (PR Newswire distribution) through 2026-08; weights 28% / 12%. CA scores S&P Global Canada Composite PMI (Ivey PMI is conflict-only). AU scores Judo Bank / S&P Global Australia Composite PMI. NZ scores BNZ–BusinessNZ PCI GDP-weighted. Remaining months without a retrieved primary file are explicit gaps (`docs/ACTIVITY_SURVEY_SOURCES.md`).

### Consumer

Monthly nominal series (US retail RSAFS, US DSPI, AU MHSI): 50 = **(inflation target + 2% real) / 12** percent m/m, scored on 3-month mean m/m, scale **40 per pp**.

Monthly real series (US PCEC96): 50 = **2%/12** percent m/m, same scale.

Quarterly real (CA/NZ spending, NZ retail): 50 = **2%/4** percent q/q, scale **15 per pp**.

Quarterly nominal income: 50 = **(target+2%)/4** q/q, scale 15.

Confidence:

| Series | 50 | Scale | Current source |
|---|---:|---:|---|
| UMCSENT | 80 | 1.0 | FRED through 2026-07 (55.2). Do **not** use unsourced Michigan Sep 47.8 from the old ledger. |
| Westpac-MI | 100 | 1.0 | Sep 2026 84.4 only |
| ANZ-Roy Morgan | 100 | 1.0 | Aug 2026 98.0 only |
| BoC CSCE | — | — | **unavailable** (coverage down) |

AU retail: ABS monthly retail **ceased** after Jun 2025 → component unobserved, coverage down.

## 7. IMPULSE / direction

Impulse is **not** the old {−6,−4,−2,0,+2,+4,+6} classified scale and is **not** added to LEVEL.

```
component_level_value = transform at latest print using level_scoring_transform (fallback: scoring_transform)
component_impulse_value_latest = transform at latest using impulse_scoring_transform
component_impulse_value_prev   = transform at previous print using impulse_scoring_transform
component_impulse = component_level(impulse_latest) − component_level(impulse_prev)
dimension_impulse = coverage-weighted mean of component impulses that can be computed
direction = warming if dimension_impulse ≥ +1.0
            cooling if dimension_impulse ≤ −1.0
            static otherwise
```

If a component has only one print, it has LEVEL but no impulse (`impulse = null`, excluded from the dimension impulse average). Calendar time with no new print does not change LEVEL or invent impulse.

## 8. Historical paths

For each month-end `t` in 2025-09 through 2026-09, reconstruct LEVEL from observations with `reference_period ≤ t` (latest-vintage reconstruction, **not** real-time first-print vintage). Paths must be inspected for:

- pathological jumps (>15 points m/m on a dimension without a matching data jump)
- boundary compression (stuck at 1 or 100 for ≥3 consecutive months)
- monotonic calendar drift with no input change (forbidden)
- counterintuitive sign (e.g. unemployment up but Labor LEVEL up)

Known limitations of latest-vintage reconstruction are listed in §11.

## 9. Illustrative current LEVELs (pre-implementation, G1 arithmetic)

These are the G1 hand-check using the audited latest observations. I1’s deterministic engine is authoritative; differences >0.2 require a bugfix.

Old comparison scores (cumulative-impulse index, **not targets**): US 52.0 / 50.2 / 49.92 / 48.5; CA 50.0 / 48.8 / 53.2 / 52.5; AU 49.2 / 47.8 / 49.2 / 51.0; NZ 51.6 / 47.0 / 52.0 / 48.5.

G1 expected ballpark:

| | Inflation | Labor | Activity | Consumer |
|---|---:|---:|---:|---:|
| US | ~63 (3m core PCE ~3.05% vs 2%) | ~50 | ~low-50s (GDP 2Q-mean SAAR ~1.8% + ISM 3m LEVELs; parent regenerates) | ~46 (Michigan 55 vs 80) |
| CA | ~55 | ~42 (u 6.4 vs 6.0; wages 2.0 vs 3.0) | ~low-50s (GDP 2Q-mean SAAR ~1.8%; surveys missing, coverage 0.60) | mid-50s, coverage 0.75 |
| AU | ~63 (trim 3.6 / head 3.5 vs 2.5) | ~50 | ~low-40s (GDP 2Q-mean; coverage 0.60) | mixed; retail missing; Westpac 84 |
| NZ | ~64 (head 4.1 / und 2.5 vs 2) | ~36 (u 5.6 vs 4.75) | ~low-50s (GDP 2Q-mean ~2.2% SAAR; large 1Q impulse; coverage 0.60) | ~40s; confidence 98 |

US Inflation **rising** from 52 to ~63 is the intended economic correction: a ~3% Core PCE run rate is above the 2% objective, not “slightly above an arbitrary 50”.

## 10. Implementation contract

I1 (engine) must:

- Read history + `data/temperature_calibration.json`
- Emit current state to `data/temperature_scores.json` version 3 (see calibration file `state_schema`)
- Keep `countries.*.*.components` as the **weight map** so `scripts/validate_score_sources.py` still passes
- Emit `data/temperature_history/score_paths.json` monthly reconstructed LEVELs + impulses
- Provide `scripts/temperature_level.py` as the single scoring implementation
- Not implement dashboard HTML or Trader Room
- Not change weights
- Not fill survey/retail gaps

I2 (dashboard + Trader Room) must:

- Display LEVEL and a distinct IMPULSE/direction on the 16 drawers and live board
- Replace “Reindexed to 50 on 2026-09-17” lineage with V1 structural-50 lineage
- Point Trader Room `load_temperature_gauges()` at `data/temperature_scores.json` (stop parsing unpatched `patch_v8` prototype numbers)
- Preserve unrelated tabs/content
- Update deploy-pages assertions that currently grep the old reindex string

## 11. Known limitations

- Latest-vintage history, not a real-time first-print archive.
- Ivey PMI is retained as a Canada **conflict** series and is not scored. Remaining CA/AU/NZ survey months without a retrieved primary PDF/HTML file are explicit gaps (`docs/ACTIVITY_SURVEY_SOURCES.md`). BoC CSCE remains unavailable.
- AU monthly retail **publication ceased**; Consumer coverage drops by 0.25.
- AU MHSI is **nominal current-price** spending; LEVEL uses a nominal monthly anchor.
- US retail RSAFS and DSPI are nominal.
- US Michigan on FRED ends 2026-07; dashboard ledger Sep 47.8 is **not** an official FRED observation and is not scored.
- **US payrolls** use a documented 2026 **breakeven-employment** anchor (10k/month upper bound from Board FEDS Notes, Apr 2026), not the retired ~150k working-age trend. Alternate breakeven estimates (St. Louis Fed 15–87k, Dallas Fed near-zero, Chicago Fed WP ~25–100k) are sensitivity context in `docs/US_PAYROLL_BREAKEVEN_ANCHOR.md` and `US.Labor.payrolls.sensitivity` in the calibration JSON. CA/AU/NZ employment-trend anchors remain round structural-trend values, not full demographic models.
- US `mapped_bridge` is a two-month PPI-mapped snapshot, not a 12-month micro history; it does not move LEVEL.
- NZ production GDP must be pinned; the history file also contains expenditure-GDP rows (including a 2025-Q2 lookback) that must not be used as “latest”.
- Potential growth / u\* / productivity add-on are judgement-documented constants, frozen in the calibration JSON, not estimated from the one-year sample.
- **Activity GDP LEVEL uses a two-quarter mean SAAR** (per-quarter SAAR then average). **GDP IMPULSE** remains the latest single-quarter SAAR mapped to LEVEL minus the prior quarter’s single-quarter SAAR (release shocks stay visible: e.g. CA ~+28, NZ ~−28 on the GDP component). Survey LEVEL uses a 3-month mean; missing survey months are gapped rather than imputed.
- **No automatic staleness decay.** A component that stops updating keeps its last LEVEL and full weight until it is marked unobserved. NZ Consumer income is 2026-Q1 while peers are 2026-Q2; CA retail is 2026-06. Coverage does not currently fall with age.
