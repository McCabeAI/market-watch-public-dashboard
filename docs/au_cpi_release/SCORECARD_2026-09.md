# Australian CPI release scorecard — September 2026 (template)

Pre-release forecasts are from the committed candidate run. Fill **Actual** and **Error** after the ABS release using the `scorecard` command (post-release snapshot required).

**v1 candidate (frozen, schema `au_cpi_nowcast_v1`):** `docs/au_cpi_release/candidates/runs/2026-09-asof-2026-10-22T015000p1100-8d11c6256324/` — score original targets only.  
**v2 candidate (schema `au_cpi_nowcast_v2`, quarterly headline rows):** `docs/au_cpi_release/candidates/runs/2026-09-asof-2026-10-22T015000p1100-8d11c6256324-v2/`  
**Release time:** 2026-10-28T11:30:00+11:00 (Australia/Sydney) = 2026-10-27T20:30:00-04:00 (America/New_York).

## Post-release command

```bash
RUN_DIR=docs/au_cpi_release/candidates/runs/2026-09-asof-2026-10-22T015000p1100-8d11c6256324-v2
PYTHONPATH=. python3 -m scripts.au_cpi_release scorecard \
  --nowcast "$RUN_DIR/nowcast.json" \
  --actual-fixture /path/to/post_release_snapshot.json \
  --out "$RUN_DIR/scorecard"
```

Refuses with exit **2** (`scorecard_before_release`) unless the actual snapshot `retrieved_at` is at or after the release time and contains the target periods. Verifies `manifest.json` hashes when present.

## Forecast table (pre-filled from `nowcast.json`)

| Target | Status | Period | Forecast (unrounded) | 1 dp | Model | Band68 lower | Band68 upper | Band90 lower | Band90 upper | n | low_sample | Actual | Error |
| --- | --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| headline_nsa_mom | ok | 2026-09 | 0.5055526076899186 | 0.5 | sa_persistence_x_seasonal_12 | 0.1410136939253181 | 0.8700915214545191 | -0.12484630555397169 | 1.135951520933809 | 16 | true | | |
| headline_nsa_yoy | ok | 2026-09 | 4.0232469489590805 | 4.0 | sa_persistence_x_seasonal_12 | 3.6459491732127036 | 4.400544724705435 | 3.3707840737516426 | 4.675709824166474 | 16 | true | | |
| headline_sa_mom | ok | 2026-09 | 0.3232749005800978 | 0.3 | mean_12 | -0.05456820799570222 | 0.7011180091558977 | -0.2855287428262233 | 0.9320785439864189 | 16 | true | | |
| headline_sa_yoy | ok | 2026-09 | 3.997166455474477 | 4.0 | mean_12 | 3.6054865317922236 | 4.388846379156686 | 3.366068099636599 | 4.628264811312333 | 16 | true | | |
| headline_nsa_quarterly_qoq | ok | 2026-Q3 | 1.1968092496282612 | 1.2 | quarter_average_of_monthly_nsa (inherits sa_persistence_x_seasonal_12 MoM) | 1.0738789173767582 | 1.3197395818797641 | 0.9842252292947995 | 1.4093932699617229 | 16 | true | | |
| headline_nsa_quarterly_yoy | ok | 2026-Q3 | 3.8148428868771456 | 3.8 | quarter_average_of_monthly_nsa (inherits sa_persistence_x_seasonal_12 MoM) | 3.6887322592461746 | 3.9409535145081165 | 3.596759166305108 | 4.032926607449183 | 16 | true | | |
| trimmed_mean_monthly_sa_mom | ok | 2026-09 | 0.293090608139888 | 0.3 | mean_12 | 0.23953428411088054 | 0.3466469321688955 | 0.15197325208257767 | 0.43420796419719837 | 16 | true | | |
| trimmed_mean_monthly_sa_yoy | ok | 2026-09 | 3.6056003046294416 | 3.6 | mean_12 | 3.550275106577505 | 3.660925502681356 | 3.459822083028463 | 3.751378526230398 | 16 | true | | |
| trimmed_mean_quarterly_legacy_qoq | ok | 2026-Q3 | 0.8125952260030544 | 0.8 | persistence | 0.60048678223239 | 1.0247036697737189 | 0.4125651288231724 | 1.2126253231829365 | 176 | false | | |
| trimmed_mean_quarterly_legacy_yoy | ok | 2026-Q3 | 3.434639550103702 | 3.4 | persistence | 3.2170143577577637 | 3.65226474244964 | 3.0242050322913716 | 3.8450740679160322 | 174 | false | | |
| weighted_median_monthly_sa_mom | ok | 2026-09 | 0.2501764183060695 | 0.3 | persistence | 0.1704452852071059 | 0.32990755140503314 | 0.11127636410079406 | 0.389076472511345 | 27 | false | | |
| weighted_median_monthly_sa_yoy | ok | 2026-09 | 3.435177002100298 | 3.4 | persistence | 3.3529127691651395 | 3.517441235035501 | 3.29186402046151 | 3.578489983739108 | 17 | true | | |

Quarterly headline rows exist only in **v2** `nowcast.json`; the v1 archive remains the immutable pre-repair candidate without these keys. Scored actuals use the same quarter-average identity on monthly `headline_nsa_index` levels (official quarterly observations are recorded separately as `actual_official` when present).

Shadow-only diagnostic: weighted median rows are not Market Watch inputs.
