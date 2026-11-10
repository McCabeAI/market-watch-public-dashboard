PASS

Independent recomputation from frozen BLS and ZORI CSVs (`verification/independent_recompute.py`, Python 3 + numpy only). A **PASS** confirms proxy arithmetic against `results/metrics.json` only; it does **not** convert Zillow ZORI into Cotality SFRI and is **not** a production model recommendation.

## Hard data audits

- [x] No month after 2026-09 in BLS CSV: max=2026-09
- [x] No month after 2026-09 in ZORI CSV: max=2026-09
- [x] 2025-10 oer_sa blank: value=None
- [x] 2025-10 oer_nsa blank: value=None
- [x] 2025-10 rent_sa blank: value=None
- [x] 2025-10 rent_nsa blank: value=None
- [x] 2026-09 oer_sa is 445.195: value=445.195
- [x] OER SA mom missing for 2025-10: mom=None
- [x] OER SA mom missing for 2025-11: mom=None
- [x] OER SA mom present for 2025-12: mom=0.31027179994636

## Metric comparisons vs `results/metrics.json`

- january_2024.oer_sa_mom_2024_01: MATCH — recomputed=0.5112357026245684, metrics.json=0.5112357026245684
- january_2024.rent_sa_mom_2024_01: MATCH — recomputed=0.3520611669706186, metrics.json=0.3520611669706186
- january_2024.difference_2024_01: MATCH — recomputed=0.1591745356539498, metrics.json=0.1591745356539498
- january_2024.hist_2015_2019.n: MATCH — recomputed=60, metrics.json=60
- january_2024.hist_2015_2019.median: MATCH — recomputed=-0.03629880363552607, metrics.json=-0.03629880363552607
- january_2024.hist_2015_2019.maximum: MATCH — recomputed=0.09062810192541626, metrics.json=0.09062810192541626
- january_2024.hist_2015_2019.percentile_rank_strictly_less_than_2024_01: MATCH — recomputed=1.0, metrics.json=1.0
- january_2024.hist_2012_through_2023.n: MATCH — recomputed=143, metrics.json=143
- january_2024.hist_2012_through_2023.median: MATCH — recomputed=-0.03104576504351364, metrics.json=-0.03104576504351364
- january_2024.hist_2012_through_2023.maximum: MATCH — recomputed=0.0943438824475118, metrics.json=0.0943438824475118
- january_2024.hist_2012_through_2023.percentile_rank_strictly_less_than_2024_01: MATCH — recomputed=1.0, metrics.json=1.0
- as_of.as_of_month: MATCH — 2026-09
- as_of.oer_sa_yoy: MATCH — recomputed=3.2613990081969746, metrics.json=3.2613990081969746
- as_of.oer_nsa_yoy: MATCH — recomputed=3.2612476405578406, metrics.json=3.2612476405578406
- as_of.rent_sa_yoy: MATCH — recomputed=2.782056284613099, metrics.json=2.782056284613099
- as_of.zori_all_yoy: MATCH — recomputed=2.6986909671258275, metrics.json=2.6986909671258275
- as_of.zori_sfr_yoy: MATCH — recomputed=3.1252406605605243, metrics.json=3.1252406605605243
- as_of.zori_all_yoy_minus_oer_sa_yoy: MATCH — recomputed=-0.5627080410711471, metrics.json=-0.5627080410711471
- forecast_1m_oer_sa_common.n_common: MATCH — recomputed=76, metrics.json=76
- forecast_1m_oer_sa_common.models.persist.mae: MATCH — recomputed=0.07373152902519439, metrics.json=0.07373152902519439
- forecast_1m_oer_sa_common.models.persist.rmse: MATCH — recomputed=0.0917973723642394, metrics.json=0.0917973723642394
- forecast_1m_oer_sa_common.models.persist.n: MATCH — recomputed=76, metrics.json=76
- forecast_1m_oer_sa_common.models.trail3.mae: MATCH — recomputed=0.06407402333562089, metrics.json=0.06407402333562089
- forecast_1m_oer_sa_common.models.trail3.rmse: MATCH — recomputed=0.08154056062723226, metrics.json=0.08154056062723226
- forecast_1m_oer_sa_common.models.trail3.n: MATCH — recomputed=76, metrics.json=76
- forecast_1m_oer_sa_common.models.ar3.mae: MATCH — recomputed=0.06296823032241723, metrics.json=0.06296823032241723
- forecast_1m_oer_sa_common.models.ar3.rmse: MATCH — recomputed=0.08320601235761294, metrics.json=0.08320601235761294
- forecast_1m_oer_sa_common.models.ar3.n: MATCH — recomputed=76, metrics.json=76
- forecast_1m_oer_sa_common.models.ar3_zori_m1.mae: MATCH — recomputed=0.0613916272978301, metrics.json=0.0613916272978301
- forecast_1m_oer_sa_common.models.ar3_zori_m1.rmse: MATCH — recomputed=0.08156850548613687, metrics.json=0.08156850548613687
- forecast_1m_oer_sa_common.models.ar3_zori_m1.n: MATCH — recomputed=76, metrics.json=76
- forecast_1m_oer_sa_common.models.ar3_zori_m12.mae: MATCH — recomputed=0.06648778325370154, metrics.json=0.06648778325370154
- forecast_1m_oer_sa_common.models.ar3_zori_m12.rmse: MATCH — recomputed=0.08909500096022495, metrics.json=0.08909500096022495
- forecast_1m_oer_sa_common.models.ar3_zori_m12.n: MATCH — recomputed=76, metrics.json=76
- forecast_1m_oer_sa_common.mae_splits.through_2019.persist.n: MATCH — recomputed=0, metrics.json=0
- forecast_1m_oer_sa_common.mae_splits.through_2019.persist.mae: MATCH — recomputed=None, metrics.json=None
- forecast_1m_oer_sa_common.mae_splits.through_2019.trail3.n: MATCH — recomputed=0, metrics.json=0
- forecast_1m_oer_sa_common.mae_splits.through_2019.trail3.mae: MATCH — recomputed=None, metrics.json=None
- forecast_1m_oer_sa_common.mae_splits.through_2019.ar3.n: MATCH — recomputed=0, metrics.json=0
- forecast_1m_oer_sa_common.mae_splits.through_2019.ar3.mae: MATCH — recomputed=None, metrics.json=None
- forecast_1m_oer_sa_common.mae_splits.through_2019.ar3_zori_m1.n: MATCH — recomputed=0, metrics.json=0
- forecast_1m_oer_sa_common.mae_splits.through_2019.ar3_zori_m1.mae: MATCH — recomputed=None, metrics.json=None
- forecast_1m_oer_sa_common.mae_splits.through_2019.ar3_zori_m12.n: MATCH — recomputed=0, metrics.json=0
- forecast_1m_oer_sa_common.mae_splits.through_2019.ar3_zori_m12.mae: MATCH — recomputed=None, metrics.json=None
- forecast_1m_oer_sa_common.mae_splits.2020_2022.persist.n: MATCH — recomputed=36, metrics.json=36
- forecast_1m_oer_sa_common.mae_splits.2020_2022.persist.mae: MATCH — recomputed=0.06492686782032828, metrics.json=0.06492686782032828
- forecast_1m_oer_sa_common.mae_splits.2020_2022.trail3.n: MATCH — recomputed=36, metrics.json=36
- forecast_1m_oer_sa_common.mae_splits.2020_2022.trail3.mae: MATCH — recomputed=0.06202418765554443, metrics.json=0.06202418765554443
- forecast_1m_oer_sa_common.mae_splits.2020_2022.ar3.n: MATCH — recomputed=36, metrics.json=36
- forecast_1m_oer_sa_common.mae_splits.2020_2022.ar3.mae: MATCH — recomputed=0.061291480827600595, metrics.json=0.061291480827600595
- forecast_1m_oer_sa_common.mae_splits.2020_2022.ar3_zori_m1.n: MATCH — recomputed=36, metrics.json=36
- forecast_1m_oer_sa_common.mae_splits.2020_2022.ar3_zori_m1.mae: MATCH — recomputed=0.0647488114591452, metrics.json=0.0647488114591452
- forecast_1m_oer_sa_common.mae_splits.2020_2022.ar3_zori_m12.n: MATCH — recomputed=36, metrics.json=36
- forecast_1m_oer_sa_common.mae_splits.2020_2022.ar3_zori_m12.mae: MATCH — recomputed=0.06782756016266374, metrics.json=0.06782756016266374
- forecast_1m_oer_sa_common.mae_splits.from_2023.persist.n: MATCH — recomputed=40, metrics.json=40
- forecast_1m_oer_sa_common.mae_splits.from_2023.persist.mae: MATCH — recomputed=0.08165572410957389, metrics.json=0.08165572410957389
- forecast_1m_oer_sa_common.mae_splits.from_2023.trail3.n: MATCH — recomputed=40, metrics.json=40
- forecast_1m_oer_sa_common.mae_splits.from_2023.trail3.mae: MATCH — recomputed=0.0659188754476897, metrics.json=0.0659188754476897
- forecast_1m_oer_sa_common.mae_splits.from_2023.ar3.n: MATCH — recomputed=40, metrics.json=40
- forecast_1m_oer_sa_common.mae_splits.from_2023.ar3.mae: MATCH — recomputed=0.06447730486775222, metrics.json=0.06447730486775222
- forecast_1m_oer_sa_common.mae_splits.from_2023.ar3_zori_m1.n: MATCH — recomputed=40, metrics.json=40
- forecast_1m_oer_sa_common.mae_splits.from_2023.ar3_zori_m1.mae: MATCH — recomputed=0.0583701615526465, metrics.json=0.0583701615526465
- forecast_1m_oer_sa_common.mae_splits.from_2023.ar3_zori_m12.n: MATCH — recomputed=40, metrics.json=40
- forecast_1m_oer_sa_common.mae_splits.from_2023.ar3_zori_m12.mae: MATCH — recomputed=0.06528198403563557, metrics.json=0.06528198403563557
- forecast_1m_oer_sa_common_without_m12.n_common: MATCH — recomputed=87, metrics.json=87
- forecast_1m_oer_sa_common_without_m12.models.persist.mae: MATCH — recomputed=0.06970696329626921, metrics.json=0.06970696329626921
- forecast_1m_oer_sa_common_without_m12.models.persist.rmse: MATCH — recomputed=0.08763491361441182, metrics.json=0.08763491361441182
- forecast_1m_oer_sa_common_without_m12.models.persist.n: MATCH — recomputed=87, metrics.json=87
- forecast_1m_oer_sa_common_without_m12.models.trail3.mae: MATCH — recomputed=0.06012561112566337, metrics.json=0.06012561112566337
- forecast_1m_oer_sa_common_without_m12.models.trail3.rmse: MATCH — recomputed=0.07747841194555762, metrics.json=0.07747841194555762
- forecast_1m_oer_sa_common_without_m12.models.trail3.n: MATCH — recomputed=87, metrics.json=87
- forecast_1m_oer_sa_common_without_m12.models.ar3.mae: MATCH — recomputed=0.05944801008497692, metrics.json=0.05944801008497692
- forecast_1m_oer_sa_common_without_m12.models.ar3.rmse: MATCH — recomputed=0.07908604848409917, metrics.json=0.07908604848409917
- forecast_1m_oer_sa_common_without_m12.models.ar3.n: MATCH — recomputed=87, metrics.json=87
- forecast_1m_oer_sa_common_without_m12.models.ar3_zori_m1.mae: MATCH — recomputed=0.05783987852014108, metrics.json=0.05783987852014108
- forecast_1m_oer_sa_common_without_m12.models.ar3_zori_m1.rmse: MATCH — recomputed=0.07755027712733861, metrics.json=0.07755027712733861
- forecast_1m_oer_sa_common_without_m12.models.ar3_zori_m1.n: MATCH — recomputed=87, metrics.json=87
- forecast_1m_oer_sa_common_without_m12.mae_splits.through_2019.persist.n: MATCH — recomputed=11, metrics.json=11
- forecast_1m_oer_sa_common_without_m12.mae_splits.through_2019.persist.mae: MATCH — recomputed=0.04190087280551349, metrics.json=0.04190087280551349
- forecast_1m_oer_sa_common_without_m12.mae_splits.through_2019.trail3.n: MATCH — recomputed=11, metrics.json=11
- forecast_1m_oer_sa_common_without_m12.mae_splits.through_2019.trail3.mae: MATCH — recomputed=0.03284567222050236, metrics.json=0.03284567222050236
- forecast_1m_oer_sa_common_without_m12.mae_splits.through_2019.ar3.n: MATCH — recomputed=11, metrics.json=11
- forecast_1m_oer_sa_common_without_m12.mae_splits.through_2019.ar3.mae: MATCH — recomputed=0.035126488444480124, metrics.json=0.035126488444480124
- forecast_1m_oer_sa_common_without_m12.mae_splits.through_2019.ar3_zori_m1.n: MATCH — recomputed=11, metrics.json=11
- forecast_1m_oer_sa_common_without_m12.mae_splits.through_2019.ar3_zori_m1.mae: MATCH — recomputed=0.033300523328835124, metrics.json=0.033300523328835124
- forecast_1m_oer_sa_common_without_m12.mae_splits.2020_2022.persist.n: MATCH — recomputed=36, metrics.json=36
- forecast_1m_oer_sa_common_without_m12.mae_splits.2020_2022.persist.mae: MATCH — recomputed=0.06492686782032828, metrics.json=0.06492686782032828
- forecast_1m_oer_sa_common_without_m12.mae_splits.2020_2022.trail3.n: MATCH — recomputed=36, metrics.json=36
- forecast_1m_oer_sa_common_without_m12.mae_splits.2020_2022.trail3.mae: MATCH — recomputed=0.06202418765554443, metrics.json=0.06202418765554443
- forecast_1m_oer_sa_common_without_m12.mae_splits.2020_2022.ar3.n: MATCH — recomputed=36, metrics.json=36
- forecast_1m_oer_sa_common_without_m12.mae_splits.2020_2022.ar3.mae: MATCH — recomputed=0.061291480827600595, metrics.json=0.061291480827600595
- forecast_1m_oer_sa_common_without_m12.mae_splits.2020_2022.ar3_zori_m1.n: MATCH — recomputed=36, metrics.json=36
- forecast_1m_oer_sa_common_without_m12.mae_splits.2020_2022.ar3_zori_m1.mae: MATCH — recomputed=0.0647488114591452, metrics.json=0.0647488114591452
- forecast_1m_oer_sa_common_without_m12.mae_splits.from_2023.persist.n: MATCH — recomputed=40, metrics.json=40
- forecast_1m_oer_sa_common_without_m12.mae_splits.from_2023.persist.mae: MATCH — recomputed=0.08165572410957389, metrics.json=0.08165572410957389
- forecast_1m_oer_sa_common_without_m12.mae_splits.from_2023.trail3.n: MATCH — recomputed=40, metrics.json=40
- forecast_1m_oer_sa_common_without_m12.mae_splits.from_2023.trail3.mae: MATCH — recomputed=0.0659188754476897, metrics.json=0.0659188754476897
- forecast_1m_oer_sa_common_without_m12.mae_splits.from_2023.ar3.n: MATCH — recomputed=40, metrics.json=40
- forecast_1m_oer_sa_common_without_m12.mae_splits.from_2023.ar3.mae: MATCH — recomputed=0.06447730486775222, metrics.json=0.06447730486775222
- forecast_1m_oer_sa_common_without_m12.mae_splits.from_2023.ar3_zori_m1.n: MATCH — recomputed=40, metrics.json=40
- forecast_1m_oer_sa_common_without_m12.mae_splits.from_2023.ar3_zori_m1.mae: MATCH — recomputed=0.0583701615526465, metrics.json=0.0583701615526465
- forecast_1m_oer_nsa_common.n_common: MATCH — recomputed=76, metrics.json=76
- forecast_1m_oer_nsa_common.models.persist.mae: MATCH — recomputed=0.07518347200269776, metrics.json=0.07518347200269776
- forecast_1m_oer_nsa_common.models.persist.rmse: MATCH — recomputed=0.0936127275607393, metrics.json=0.0936127275607393
- forecast_1m_oer_nsa_common.models.persist.n: MATCH — recomputed=76, metrics.json=76
- forecast_1m_oer_nsa_common.models.trail3.mae: MATCH — recomputed=0.06614859437946921, metrics.json=0.06614859437946921
- forecast_1m_oer_nsa_common.models.trail3.rmse: MATCH — recomputed=0.08719014787567006, metrics.json=0.08719014787567006
- forecast_1m_oer_nsa_common.models.trail3.n: MATCH — recomputed=76, metrics.json=76
- forecast_1m_oer_nsa_common.models.ar3.mae: MATCH — recomputed=0.0673305032348996, metrics.json=0.0673305032348996
- forecast_1m_oer_nsa_common.models.ar3.rmse: MATCH — recomputed=0.08807012511102032, metrics.json=0.08807012511102032
- forecast_1m_oer_nsa_common.models.ar3.n: MATCH — recomputed=76, metrics.json=76
- forecast_1m_oer_nsa_common.models.ar3_zori_m1.mae: MATCH — recomputed=0.06786134103086038, metrics.json=0.06786134103086038
- forecast_1m_oer_nsa_common.models.ar3_zori_m1.rmse: MATCH — recomputed=0.08744723204257518, metrics.json=0.08744723204257518
- forecast_1m_oer_nsa_common.models.ar3_zori_m1.n: MATCH — recomputed=76, metrics.json=76
- forecast_1m_oer_nsa_common.models.ar3_zori_m12.mae: MATCH — recomputed=0.07119710446845819, metrics.json=0.07119710446845819
- forecast_1m_oer_nsa_common.models.ar3_zori_m12.rmse: MATCH — recomputed=0.09562838987459336, metrics.json=0.09562838987459336
- forecast_1m_oer_nsa_common.models.ar3_zori_m12.n: MATCH — recomputed=76, metrics.json=76
- three_month.non_overlap.n: MATCH — recomputed=24, metrics.json=24
- three_month.non_overlap.trail3_x3.mae: MATCH — recomputed=0.17011599269940816, metrics.json=0.17011599269940816
- three_month.non_overlap.direct_ar.mae: MATCH — recomputed=0.18875460565668542, metrics.json=0.18875460565668542
- three_month.non_overlap.direct_ar_zori.mae: MATCH — recomputed=0.24675389160552996, metrics.json=0.24675389160552996
- directional_12.non_overlap.gap.hit_rate: MATCH — recomputed=0.7, metrics.json=0.7
- directional_12.non_overlap.gap.n: MATCH — recomputed=10, metrics.json=10
- directional_12.non_overlap.gap.zero_count: MATCH — recomputed=0, metrics.json=0
- directional_12.non_overlap.always_decline.hit_rate: MATCH — recomputed=0.5, metrics.json=0.5
- directional_12.non_overlap.always_decline.n: MATCH — recomputed=10, metrics.json=10
- directional_12.non_overlap.always_decline.zero_count: MATCH — recomputed=0, metrics.json=0
- directional_12.non_overlap.momentum.hit_rate: MATCH — recomputed=0.5, metrics.json=0.5
- directional_12.non_overlap.momentum.n: MATCH — recomputed=10, metrics.json=10
- directional_12.non_overlap.momentum.zero_count: MATCH — recomputed=0, metrics.json=0

## Skipped

- `forecast_1m_ar3_zori_ksearch`: not re-derived (k-search omitted).

## Lookahead audit (`scripts/proxy_sensitivity.py` read as text)

**Same-month feature at prediction month t (1m models):** none found.

Quoted feature lines:
- `L205: persist = mom.get(m1) if m1 else None (persist = mom.get(m1))`
- `L254: x_new = [1.0, mom[t1], mom[t2], mom[t3]]  # type: ignore (ar3 prediction features at t-1..t-3)`
- `L263: ar3_z1 = fit_ar3(lambda s: zori_yoy.get(prev_month(s)) if prev_month(s) else None) (ar3_zori_m1 uses zori_yoy at prev_month(s))`
- `L264: ar3_z12 = fit_ar3( (ar3_zori_m12 uses zori_yoy at s-12)`

**3-month training outcomes:** Training origins require `add_months(s, 2) <= prev_month(t)`, so the realized 3-month window for training row `s` ends at `s+2` and cannot extend past `t-1`. Guard present: True.

## Lookahead checks

- lookahead: no same-month ZORI/OER feature at t for 1m models: PASS — no leak detected
- lookahead: 3m training outcome window ends by t-1: PASS — add_months(s,2)<=prev_month(t) guard present

## Full check list

| Check | Result | Detail |
| --- | --- | --- |
| No month after 2026-09 in BLS CSV | PASS | max=2026-09 |
| No month after 2026-09 in ZORI CSV | PASS | max=2026-09 |
| 2025-10 oer_sa blank | PASS | value=None |
| 2025-10 oer_nsa blank | PASS | value=None |
| 2025-10 rent_sa blank | PASS | value=None |
| 2025-10 rent_nsa blank | PASS | value=None |
| 2026-09 oer_sa is 445.195 | PASS | value=445.195 |
| OER SA mom missing for 2025-10 | PASS | mom=None |
| OER SA mom missing for 2025-11 | PASS | mom=None |
| OER SA mom present for 2025-12 | PASS | mom=0.31027179994636 |
| january_2024.oer_sa_mom_2024_01 | PASS | recomputed=0.5112357026245684, metrics.json=0.5112357026245684 |
| january_2024.rent_sa_mom_2024_01 | PASS | recomputed=0.3520611669706186, metrics.json=0.3520611669706186 |
| january_2024.difference_2024_01 | PASS | recomputed=0.1591745356539498, metrics.json=0.1591745356539498 |
| january_2024.hist_2015_2019.n | PASS | recomputed=60, metrics.json=60 |
| january_2024.hist_2015_2019.median | PASS | recomputed=-0.03629880363552607, metrics.json=-0.03629880363552607 |
| january_2024.hist_2015_2019.maximum | PASS | recomputed=0.09062810192541626, metrics.json=0.09062810192541626 |
| january_2024.hist_2015_2019.percentile_rank_strictly_less_than_2024_01 | PASS | recomputed=1.0, metrics.json=1.0 |
| january_2024.hist_2012_through_2023.n | PASS | recomputed=143, metrics.json=143 |
| january_2024.hist_2012_through_2023.median | PASS | recomputed=-0.03104576504351364, metrics.json=-0.03104576504351364 |
| january_2024.hist_2012_through_2023.maximum | PASS | recomputed=0.0943438824475118, metrics.json=0.0943438824475118 |
| january_2024.hist_2012_through_2023.percentile_rank_strictly_less_than_2024_01 | PASS | recomputed=1.0, metrics.json=1.0 |
| as_of.as_of_month | PASS | 2026-09 |
| as_of.oer_sa_yoy | PASS | recomputed=3.2613990081969746, metrics.json=3.2613990081969746 |
| as_of.oer_nsa_yoy | PASS | recomputed=3.2612476405578406, metrics.json=3.2612476405578406 |
| as_of.rent_sa_yoy | PASS | recomputed=2.782056284613099, metrics.json=2.782056284613099 |
| as_of.zori_all_yoy | PASS | recomputed=2.6986909671258275, metrics.json=2.6986909671258275 |
| as_of.zori_sfr_yoy | PASS | recomputed=3.1252406605605243, metrics.json=3.1252406605605243 |
| as_of.zori_all_yoy_minus_oer_sa_yoy | PASS | recomputed=-0.5627080410711471, metrics.json=-0.5627080410711471 |
| forecast_1m_oer_sa_common.n_common | PASS | recomputed=76, metrics.json=76 |
| forecast_1m_oer_sa_common.models.persist.mae | PASS | recomputed=0.07373152902519439, metrics.json=0.07373152902519439 |
| forecast_1m_oer_sa_common.models.persist.rmse | PASS | recomputed=0.0917973723642394, metrics.json=0.0917973723642394 |
| forecast_1m_oer_sa_common.models.persist.n | PASS | recomputed=76, metrics.json=76 |
| forecast_1m_oer_sa_common.models.trail3.mae | PASS | recomputed=0.06407402333562089, metrics.json=0.06407402333562089 |
| forecast_1m_oer_sa_common.models.trail3.rmse | PASS | recomputed=0.08154056062723226, metrics.json=0.08154056062723226 |
| forecast_1m_oer_sa_common.models.trail3.n | PASS | recomputed=76, metrics.json=76 |
| forecast_1m_oer_sa_common.models.ar3.mae | PASS | recomputed=0.06296823032241723, metrics.json=0.06296823032241723 |
| forecast_1m_oer_sa_common.models.ar3.rmse | PASS | recomputed=0.08320601235761294, metrics.json=0.08320601235761294 |
| forecast_1m_oer_sa_common.models.ar3.n | PASS | recomputed=76, metrics.json=76 |
| forecast_1m_oer_sa_common.models.ar3_zori_m1.mae | PASS | recomputed=0.0613916272978301, metrics.json=0.0613916272978301 |
| forecast_1m_oer_sa_common.models.ar3_zori_m1.rmse | PASS | recomputed=0.08156850548613687, metrics.json=0.08156850548613687 |
| forecast_1m_oer_sa_common.models.ar3_zori_m1.n | PASS | recomputed=76, metrics.json=76 |
| forecast_1m_oer_sa_common.models.ar3_zori_m12.mae | PASS | recomputed=0.06648778325370154, metrics.json=0.06648778325370154 |
| forecast_1m_oer_sa_common.models.ar3_zori_m12.rmse | PASS | recomputed=0.08909500096022495, metrics.json=0.08909500096022495 |
| forecast_1m_oer_sa_common.models.ar3_zori_m12.n | PASS | recomputed=76, metrics.json=76 |
| forecast_1m_oer_sa_common.mae_splits.through_2019.persist.n | PASS | recomputed=0, metrics.json=0 |
| forecast_1m_oer_sa_common.mae_splits.through_2019.persist.mae | PASS | recomputed=None, metrics.json=None |
| forecast_1m_oer_sa_common.mae_splits.through_2019.trail3.n | PASS | recomputed=0, metrics.json=0 |
| forecast_1m_oer_sa_common.mae_splits.through_2019.trail3.mae | PASS | recomputed=None, metrics.json=None |
| forecast_1m_oer_sa_common.mae_splits.through_2019.ar3.n | PASS | recomputed=0, metrics.json=0 |
| forecast_1m_oer_sa_common.mae_splits.through_2019.ar3.mae | PASS | recomputed=None, metrics.json=None |
| forecast_1m_oer_sa_common.mae_splits.through_2019.ar3_zori_m1.n | PASS | recomputed=0, metrics.json=0 |
| forecast_1m_oer_sa_common.mae_splits.through_2019.ar3_zori_m1.mae | PASS | recomputed=None, metrics.json=None |
| forecast_1m_oer_sa_common.mae_splits.through_2019.ar3_zori_m12.n | PASS | recomputed=0, metrics.json=0 |
| forecast_1m_oer_sa_common.mae_splits.through_2019.ar3_zori_m12.mae | PASS | recomputed=None, metrics.json=None |
| forecast_1m_oer_sa_common.mae_splits.2020_2022.persist.n | PASS | recomputed=36, metrics.json=36 |
| forecast_1m_oer_sa_common.mae_splits.2020_2022.persist.mae | PASS | recomputed=0.06492686782032828, metrics.json=0.06492686782032828 |
| forecast_1m_oer_sa_common.mae_splits.2020_2022.trail3.n | PASS | recomputed=36, metrics.json=36 |
| forecast_1m_oer_sa_common.mae_splits.2020_2022.trail3.mae | PASS | recomputed=0.06202418765554443, metrics.json=0.06202418765554443 |
| forecast_1m_oer_sa_common.mae_splits.2020_2022.ar3.n | PASS | recomputed=36, metrics.json=36 |
| forecast_1m_oer_sa_common.mae_splits.2020_2022.ar3.mae | PASS | recomputed=0.061291480827600595, metrics.json=0.061291480827600595 |
| forecast_1m_oer_sa_common.mae_splits.2020_2022.ar3_zori_m1.n | PASS | recomputed=36, metrics.json=36 |
| forecast_1m_oer_sa_common.mae_splits.2020_2022.ar3_zori_m1.mae | PASS | recomputed=0.0647488114591452, metrics.json=0.0647488114591452 |
| forecast_1m_oer_sa_common.mae_splits.2020_2022.ar3_zori_m12.n | PASS | recomputed=36, metrics.json=36 |
| forecast_1m_oer_sa_common.mae_splits.2020_2022.ar3_zori_m12.mae | PASS | recomputed=0.06782756016266374, metrics.json=0.06782756016266374 |
| forecast_1m_oer_sa_common.mae_splits.from_2023.persist.n | PASS | recomputed=40, metrics.json=40 |
| forecast_1m_oer_sa_common.mae_splits.from_2023.persist.mae | PASS | recomputed=0.08165572410957389, metrics.json=0.08165572410957389 |
| forecast_1m_oer_sa_common.mae_splits.from_2023.trail3.n | PASS | recomputed=40, metrics.json=40 |
| forecast_1m_oer_sa_common.mae_splits.from_2023.trail3.mae | PASS | recomputed=0.0659188754476897, metrics.json=0.0659188754476897 |
| forecast_1m_oer_sa_common.mae_splits.from_2023.ar3.n | PASS | recomputed=40, metrics.json=40 |
| forecast_1m_oer_sa_common.mae_splits.from_2023.ar3.mae | PASS | recomputed=0.06447730486775222, metrics.json=0.06447730486775222 |
| forecast_1m_oer_sa_common.mae_splits.from_2023.ar3_zori_m1.n | PASS | recomputed=40, metrics.json=40 |
| forecast_1m_oer_sa_common.mae_splits.from_2023.ar3_zori_m1.mae | PASS | recomputed=0.0583701615526465, metrics.json=0.0583701615526465 |
| forecast_1m_oer_sa_common.mae_splits.from_2023.ar3_zori_m12.n | PASS | recomputed=40, metrics.json=40 |
| forecast_1m_oer_sa_common.mae_splits.from_2023.ar3_zori_m12.mae | PASS | recomputed=0.06528198403563557, metrics.json=0.06528198403563557 |
| forecast_1m_oer_sa_common_without_m12.n_common | PASS | recomputed=87, metrics.json=87 |
| forecast_1m_oer_sa_common_without_m12.models.persist.mae | PASS | recomputed=0.06970696329626921, metrics.json=0.06970696329626921 |
| forecast_1m_oer_sa_common_without_m12.models.persist.rmse | PASS | recomputed=0.08763491361441182, metrics.json=0.08763491361441182 |
| forecast_1m_oer_sa_common_without_m12.models.persist.n | PASS | recomputed=87, metrics.json=87 |
| forecast_1m_oer_sa_common_without_m12.models.trail3.mae | PASS | recomputed=0.06012561112566337, metrics.json=0.06012561112566337 |
| forecast_1m_oer_sa_common_without_m12.models.trail3.rmse | PASS | recomputed=0.07747841194555762, metrics.json=0.07747841194555762 |
| forecast_1m_oer_sa_common_without_m12.models.trail3.n | PASS | recomputed=87, metrics.json=87 |
| forecast_1m_oer_sa_common_without_m12.models.ar3.mae | PASS | recomputed=0.05944801008497692, metrics.json=0.05944801008497692 |
| forecast_1m_oer_sa_common_without_m12.models.ar3.rmse | PASS | recomputed=0.07908604848409917, metrics.json=0.07908604848409917 |
| forecast_1m_oer_sa_common_without_m12.models.ar3.n | PASS | recomputed=87, metrics.json=87 |
| forecast_1m_oer_sa_common_without_m12.models.ar3_zori_m1.mae | PASS | recomputed=0.05783987852014108, metrics.json=0.05783987852014108 |
| forecast_1m_oer_sa_common_without_m12.models.ar3_zori_m1.rmse | PASS | recomputed=0.07755027712733861, metrics.json=0.07755027712733861 |
| forecast_1m_oer_sa_common_without_m12.models.ar3_zori_m1.n | PASS | recomputed=87, metrics.json=87 |
| forecast_1m_oer_sa_common_without_m12.mae_splits.through_2019.persist.n | PASS | recomputed=11, metrics.json=11 |
| forecast_1m_oer_sa_common_without_m12.mae_splits.through_2019.persist.mae | PASS | recomputed=0.04190087280551349, metrics.json=0.04190087280551349 |
| forecast_1m_oer_sa_common_without_m12.mae_splits.through_2019.trail3.n | PASS | recomputed=11, metrics.json=11 |
| forecast_1m_oer_sa_common_without_m12.mae_splits.through_2019.trail3.mae | PASS | recomputed=0.03284567222050236, metrics.json=0.03284567222050236 |
| forecast_1m_oer_sa_common_without_m12.mae_splits.through_2019.ar3.n | PASS | recomputed=11, metrics.json=11 |
| forecast_1m_oer_sa_common_without_m12.mae_splits.through_2019.ar3.mae | PASS | recomputed=0.035126488444480124, metrics.json=0.035126488444480124 |
| forecast_1m_oer_sa_common_without_m12.mae_splits.through_2019.ar3_zori_m1.n | PASS | recomputed=11, metrics.json=11 |
| forecast_1m_oer_sa_common_without_m12.mae_splits.through_2019.ar3_zori_m1.mae | PASS | recomputed=0.033300523328835124, metrics.json=0.033300523328835124 |
| forecast_1m_oer_sa_common_without_m12.mae_splits.2020_2022.persist.n | PASS | recomputed=36, metrics.json=36 |
| forecast_1m_oer_sa_common_without_m12.mae_splits.2020_2022.persist.mae | PASS | recomputed=0.06492686782032828, metrics.json=0.06492686782032828 |
| forecast_1m_oer_sa_common_without_m12.mae_splits.2020_2022.trail3.n | PASS | recomputed=36, metrics.json=36 |
| forecast_1m_oer_sa_common_without_m12.mae_splits.2020_2022.trail3.mae | PASS | recomputed=0.06202418765554443, metrics.json=0.06202418765554443 |
| forecast_1m_oer_sa_common_without_m12.mae_splits.2020_2022.ar3.n | PASS | recomputed=36, metrics.json=36 |
| forecast_1m_oer_sa_common_without_m12.mae_splits.2020_2022.ar3.mae | PASS | recomputed=0.061291480827600595, metrics.json=0.061291480827600595 |
| forecast_1m_oer_sa_common_without_m12.mae_splits.2020_2022.ar3_zori_m1.n | PASS | recomputed=36, metrics.json=36 |
| forecast_1m_oer_sa_common_without_m12.mae_splits.2020_2022.ar3_zori_m1.mae | PASS | recomputed=0.0647488114591452, metrics.json=0.0647488114591452 |
| forecast_1m_oer_sa_common_without_m12.mae_splits.from_2023.persist.n | PASS | recomputed=40, metrics.json=40 |
| forecast_1m_oer_sa_common_without_m12.mae_splits.from_2023.persist.mae | PASS | recomputed=0.08165572410957389, metrics.json=0.08165572410957389 |
| forecast_1m_oer_sa_common_without_m12.mae_splits.from_2023.trail3.n | PASS | recomputed=40, metrics.json=40 |
| forecast_1m_oer_sa_common_without_m12.mae_splits.from_2023.trail3.mae | PASS | recomputed=0.0659188754476897, metrics.json=0.0659188754476897 |
| forecast_1m_oer_sa_common_without_m12.mae_splits.from_2023.ar3.n | PASS | recomputed=40, metrics.json=40 |
| forecast_1m_oer_sa_common_without_m12.mae_splits.from_2023.ar3.mae | PASS | recomputed=0.06447730486775222, metrics.json=0.06447730486775222 |
| forecast_1m_oer_sa_common_without_m12.mae_splits.from_2023.ar3_zori_m1.n | PASS | recomputed=40, metrics.json=40 |
| forecast_1m_oer_sa_common_without_m12.mae_splits.from_2023.ar3_zori_m1.mae | PASS | recomputed=0.0583701615526465, metrics.json=0.0583701615526465 |
| forecast_1m_oer_nsa_common.n_common | PASS | recomputed=76, metrics.json=76 |
| forecast_1m_oer_nsa_common.models.persist.mae | PASS | recomputed=0.07518347200269776, metrics.json=0.07518347200269776 |
| forecast_1m_oer_nsa_common.models.persist.rmse | PASS | recomputed=0.0936127275607393, metrics.json=0.0936127275607393 |
| forecast_1m_oer_nsa_common.models.persist.n | PASS | recomputed=76, metrics.json=76 |
| forecast_1m_oer_nsa_common.models.trail3.mae | PASS | recomputed=0.06614859437946921, metrics.json=0.06614859437946921 |
| forecast_1m_oer_nsa_common.models.trail3.rmse | PASS | recomputed=0.08719014787567006, metrics.json=0.08719014787567006 |
| forecast_1m_oer_nsa_common.models.trail3.n | PASS | recomputed=76, metrics.json=76 |
| forecast_1m_oer_nsa_common.models.ar3.mae | PASS | recomputed=0.0673305032348996, metrics.json=0.0673305032348996 |
| forecast_1m_oer_nsa_common.models.ar3.rmse | PASS | recomputed=0.08807012511102032, metrics.json=0.08807012511102032 |
| forecast_1m_oer_nsa_common.models.ar3.n | PASS | recomputed=76, metrics.json=76 |
| forecast_1m_oer_nsa_common.models.ar3_zori_m1.mae | PASS | recomputed=0.06786134103086038, metrics.json=0.06786134103086038 |
| forecast_1m_oer_nsa_common.models.ar3_zori_m1.rmse | PASS | recomputed=0.08744723204257518, metrics.json=0.08744723204257518 |
| forecast_1m_oer_nsa_common.models.ar3_zori_m1.n | PASS | recomputed=76, metrics.json=76 |
| forecast_1m_oer_nsa_common.models.ar3_zori_m12.mae | PASS | recomputed=0.07119710446845819, metrics.json=0.07119710446845819 |
| forecast_1m_oer_nsa_common.models.ar3_zori_m12.rmse | PASS | recomputed=0.09562838987459336, metrics.json=0.09562838987459336 |
| forecast_1m_oer_nsa_common.models.ar3_zori_m12.n | PASS | recomputed=76, metrics.json=76 |
| forecast_1m_ar3_zori_ksearch | PASS | not re-derived (k-search skipped by verifier) |
| three_month.non_overlap.n | PASS | recomputed=24, metrics.json=24 |
| three_month.non_overlap.trail3_x3.mae | PASS | recomputed=0.17011599269940816, metrics.json=0.17011599269940816 |
| three_month.non_overlap.direct_ar.mae | PASS | recomputed=0.18875460565668542, metrics.json=0.18875460565668542 |
| three_month.non_overlap.direct_ar_zori.mae | PASS | recomputed=0.24675389160552996, metrics.json=0.24675389160552996 |
| directional_12.non_overlap.gap.hit_rate | PASS | recomputed=0.7, metrics.json=0.7 |
| directional_12.non_overlap.gap.n | PASS | recomputed=10, metrics.json=10 |
| directional_12.non_overlap.gap.zero_count | PASS | recomputed=0, metrics.json=0 |
| directional_12.non_overlap.always_decline.hit_rate | PASS | recomputed=0.5, metrics.json=0.5 |
| directional_12.non_overlap.always_decline.n | PASS | recomputed=10, metrics.json=10 |
| directional_12.non_overlap.always_decline.zero_count | PASS | recomputed=0, metrics.json=0 |
| directional_12.non_overlap.momentum.hit_rate | PASS | recomputed=0.5, metrics.json=0.5 |
| directional_12.non_overlap.momentum.n | PASS | recomputed=10, metrics.json=10 |
| directional_12.non_overlap.momentum.zero_count | PASS | recomputed=0, metrics.json=0 |
| lookahead: no same-month ZORI/OER feature at t for 1m models | PASS | no leak detected |
| lookahead: 3m training outcome window ends by t-1 | PASS | add_months(s,2)<=prev_month(t) guard present |
