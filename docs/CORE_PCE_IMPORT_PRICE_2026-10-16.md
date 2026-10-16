# Core PCE import-price incremental — October 16, 2026

Frozen bundle: `data/core_pce_release/import_price_2026-10-16/`. G0 replays the **October 15 PPI central** from committed fixtures, then optionally publishes a **model-estimated** line-335 shift when a pre-specified pseudo-OOS gate passes.

## Command

```bash
python -m scripts.core_pce_release import-price --release 2026-09 --out /tmp/pce-import-2026-09
```

Optional `--bundle-dir` overrides the default fixture path. The command does not call BLS, does not run `[run-ppi]`, and does not arm the listener.

## October 15 PPI replay (always reproduced)

| Field | Value |
| --- | ---: |
| `october15_ppi_central_mom_percent` | 0.3674603939775941051607229995 |
| Low scenario MoM % | 0.1766433957314642778172140867 |
| High scenario MoM % | 0.5010010018376246819432868609 |
| Information stage | `ppi_partial` |
| Headline (pre-model) | HOT |

Pre-PPI baseline (empty observations): **0.3688405280179773205064998201** central MoM %.

The **published** `central_mom_percent` equals the October 15 replay when the line-335 gate fails; when the gate passes it moves by the signed expenditure-share effect of replacing the carried line-335 rate with the model estimate. This is **not** an official BEA print.

## Import leg (EIUIV142, NSA)

- September 2026 index **190.8**, August **169.4**
- Index-ratio MoM **12.63282172373081463990554900** (not the published rounded **12.6** display)
- BLS release **USDL-26-1577**, embargo **2026-10-16T08:30:00-04:00**, Table 10

## International PPI leg (PCU4811114811112, NSA)

- September **265.040**, August **276.479**, index-ratio MoM **-4.137384756165929419594254900**
- Footnote **P** (preliminary), retrieved 2026-10-16; **not** in the frozen PPI one-shot raw document

## Line 335 model (`line335_nnls_calendar_sa_v1`)

- BEA seasonal status: **SA by BEA**; carried MoM **3.920759759301939753741850400** (`baseline_last_published_mom`)
- Official BEA weighted-SA composite still **blocked** (`weights_unverified`)
- Pre-specified NNLS calendar-SA regression on import air fares and international scheduled PPI (estimated slopes, not BEA weights)
- Pseudo-OOS walk-forward on latest-revised BLS/BEA history only (not ALFRED real-time)
- NSA proxy envelope label `nsa_proxy_envelope_not_bea_sa` remains for sensitivity endpoints

## Published model-estimated central

On the committed history the pre-specified gate passes. The published central is a model estimate, not an official BEA composite.

| Field | Value |
| --- | ---: |
| Line 335 model MoM % | 4.571824309558639 |
| October 15 PPI central MoM % | 0.3674603939775941051607229995 |
| Model-estimated central MoM % | 0.3700438102701814887788032855 |
| Delta vs October 15 | +0.0025834162925873836180802860 |
| Line 335 signed contribution | +0.0025834162925873836180802860 |
| OOS months | 175 (2012-02 through 2026-08) |
| OOS MAE model / 3-month / carry | 1.3573 / 2.4709 / 3.2160 mom pp |
| OOS bias | +0.0554 mom pp |
| PCE-scale MAE | 0.005386 mom pp |

Estimated slopes on calendar-adjusted NSA moms: intercept 0.1758, import 0.2681, international PPI 0.3807. Those slopes are not BEA weights. September 2026 BEA is not a training label. The backtest uses the 2026-09-30 BEA vintage and the 2026-10-16 BLS vintage, so it is not an ALFRED real-time test.

## G4 review

Grok 4.7 final review **approves** this model-estimated central on the implementation above and **rejects** treating it as BEA's official line-335 composite. The official weighted-SA formula is still unpublished (`weights_unverified`). The approval is limited to the pre-specified `line335_nnls_calendar_sa_v1` estimate: it beats both the prior-month carry and the three-month BEA mean in the full 2012–2026 window and in each half, both slopes stay positive, and the September label was not used in fitting. Headline all-imports inflation is not used. Residual risk is the single revised vintage, preliminary recent PPI months, and a component MAE of about 1.36 percentage points.

## Tests

```bash
python -m unittest tests.core_pce_release.test_import_price_incremental tests.core_pce_release.test_run_ppi_oneshot tests.core_pce_release.test_forecasting
```

## Citations

- BLS Import/Export Price Indexes news release: https://www.bls.gov/news.release/ximpim.nr0.htm
- BEA Table 2.4.4 U-D item 335 workbook: https://apps.bea.gov/national/Release/XLS/Underlying/Section2All_xls.xlsx (sha256 `6ab82fff44c97fceabf2c2248e44309fcc8a16a6b59646004488f500aec32e44`)
- Frozen PPI one-shot raw documents sha256: `f92fcdff3e57dbb19d5f6a2575f77f70986cf22c4c3f1a5ae9a5b747c59b5581`
