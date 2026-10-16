# Core PCE import-price sensitivity — October 16, 2026

Frozen bundle: `data/core_pce_release/import_price_2026-10-16/`. G0 decision: **central unchanged**, NSA sensitivity envelope only for BEA line 335 (passenger fares for foreign travel).

## Command

```bash
python -m scripts.core_pce_release import-price --release 2026-09 --out /tmp/pce-import-2026-09
```

Optional `--bundle-dir` overrides the default fixture path. The command does not call BLS, does not run `[run-ppi]`, and does not arm the listener.

## Post–October 15 PPI central (unchanged)

| Field | Value |
| --- | ---: |
| Central MoM % | 0.3674603939775941051607229995 |
| Low scenario MoM % | 0.1766433957314642778172140867 |
| High scenario MoM % | 0.5010010018376246819432868609 |
| Delta vs Oct 15 PPI central | 0 |
| Information stage | `ppi_partial` |
| Headline | HOT |

Pre-PPI baseline (empty observations): **0.3688405280179773205064998201** central MoM %.

## Import leg (EIUIV142, NSA)

- September 2026 index **190.8**, August **169.4**
- Index-ratio MoM **12.63282172373081463990554900** (not the published rounded **12.6** display)
- BLS release **USDL-26-1577**, embargo **2026-10-16T08:30:00-04:00**, Table 10

## International PPI leg (PCU4811114811112, NSA)

- September **265.040**, August **276.479**, index-ratio MoM **-4.137384756165929419594254900**
- Footnote **P** (preliminary), retrieved 2026-10-16; **not** in the frozen PPI one-shot raw document

## Line 335

- BEA seasonal status: **SA by BEA**; carried MoM **3.920759759301939753741850400** (`baseline_last_published_mom`)
- Central revision **blocked** (`weights_unverified`); BEA has not published the import/PPI weights inside line 335
- NSA proxy envelope label `nsa_proxy_envelope_not_bea_sa` (not an official core PCE revision):
  - w = 1 import endpoint contribution delta: **0.03456935692791517287606283182** pp
  - w = 0 PPI endpoint contribution delta: **-0.03197462036763559059953097081** pp

Lines **207**, **336**, and **339** are unchanged versus the October 15 PPI replay.

## G4 review

Grok 4.7 final review does **not** approve a BEA-equivalent core PCE revision. Table 2.4.4 U-D line 335 names a weighted average and publishes no source proportions. Both verified inputs are not seasonally adjusted, and no September 2026 BEA seasonal factor for `E1AFT1` is in the source map. A validated central revision would need primary nonnegative weights that sum to one inside line 335, a documented BEA seasonal factor or SA index for September versus August 2026, and confirmation that no third leg enters the average.

G4 **approves** the blocked result: the October 15 post-PPI central stays `+0.3674603939775941051607229995%`, the central delta is zero, and the NSA endpoint contributions above are a sensitivity bound only. Neither endpoint is the central estimate. Headline all-imports inflation is not used.

## Tests

```bash
python -m unittest tests.core_pce_release.test_import_price_incremental tests.core_pce_release.test_run_ppi_oneshot tests.core_pce_release.test_forecasting
```

## Citations

- BLS Import/Export Price Indexes news release: https://www.bls.gov/news.release/ximpim.nr0.htm
- BEA Table 2.4.4 U-D item 335 workbook: https://www.bea.gov/sites/default/files/2026-10/FAQ521-Sep26-update.xlsx (sha256 `66c53c60cd0c2b1258589e0d8239beed95d0a1ff9822575a640c3dc5da701c7b`)
- Frozen PPI one-shot raw documents sha256: `f92fcdff3e57dbb19d5f6a2575f77f70986cf22c4c3f1a5ae9a5b747c59b5581`
