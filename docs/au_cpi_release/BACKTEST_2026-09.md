# Australian CPI walk-forward backtest — September 2026 candidate

Source: `docs/au_cpi_release/candidates/runs/2026-09-asof-2026-10-22T012500p1100-8d11c6256324/backtest.json` (pseudo-OOS latest vintage, `as_of` 2026-10-22T01:25:00+11:00). Numbers below are copied from that file; do not edit by hand.

### headline_nsa_mom (sub_period=full)

| model | regime | n | MAE | bias | RMSE | eligible |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| component_bottom_up_3 | complete_monthly_cpi | 20 | 0.3491376453 | -0.0026590532 | 0.4362206142 | True |
| component_bottom_up_6 | complete_monthly_cpi | 20 | 0.2982733949 | -0.0178290656 | 0.3770236385 | True |
| sa_persistence_x_seasonal_12 | complete_monthly_cpi | 16 | 0.2737052056 | -0.0488401487 | 0.3687239450 | True |
| sa_persistence_x_seasonal_3 | complete_monthly_cpi | 16 | 0.3628995416 | -0.0375740595 | 0.4434049457 | True |
| sa_persistence_x_seasonal_6 | complete_monthly_cpi | 16 | 0.2942545723 | -0.0172864120 | 0.3726764754 | True |
| seasonal_naive | complete_monthly_cpi | 16 | 0.3499848918 | -0.0979173252 | 0.4287587400 | True |

### headline_nsa_yoy (sub_period=full)

| model | regime | n | MAE | bias | RMSE | eligible |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| component_bottom_up_3 | complete_monthly_cpi | 17 | 0.3902279984 | 0.0076699871 | 0.4783182756 | True |
| component_bottom_up_6 | complete_monthly_cpi | 17 | 0.3268772898 | 0.0150362174 | 0.4040145231 | True |
| sa_persistence_x_seasonal_12 | complete_monthly_cpi | 16 | 0.2825989962 | -0.0489122362 | 0.3802329356 | True |
| sa_persistence_x_seasonal_3 | complete_monthly_cpi | 16 | 0.3746827096 | -0.0369985177 | 0.4573383070 | True |
| sa_persistence_x_seasonal_6 | complete_monthly_cpi | 16 | 0.3038617200 | -0.0164794801 | 0.3847179784 | True |
| seasonal_naive | complete_monthly_cpi | 16 | 0.3604286849 | -0.1001693826 | 0.4403066643 | True |

### headline_sa_mom (sub_period=full)

| model | regime | n | MAE | bias | RMSE | eligible |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| component_sa_3 | complete_monthly_cpi | 20 | 0.3246297035 | 0.0015356739 | 0.4072807316 | True |
| component_sa_6 | complete_monthly_cpi | 20 | 0.2713922673 | -0.0135930142 | 0.3502458744 | True |
| mean_12 | complete_monthly_cpi | 16 | 0.2743729794 | -0.0454348997 | 0.3646042334 | True |
| mean_3 | complete_monthly_cpi | 25 | 0.3087456533 | -0.0339435029 | 0.3927115407 | True |
| mean_6 | complete_monthly_cpi | 22 | 0.2772766335 | -0.0574454604 | 0.3563144093 | True |
| persistence | complete_monthly_cpi | 27 | 0.3402749725 | -0.0144992117 | 0.4632716285 | True |

### headline_sa_yoy (sub_period=full)

| model | regime | n | MAE | bias | RMSE | eligible |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| component_sa_3 | complete_monthly_cpi | 17 | 0.3638761666 | 0.0084566437 | 0.4478303796 | True |
| component_sa_6 | complete_monthly_cpi | 17 | 0.2983362298 | 0.0158471675 | 0.3757674142 | True |
| mean_12 | complete_monthly_cpi | 16 | 0.2832939607 | -0.0457236606 | 0.3761374801 | True |
| mean_3 | complete_monthly_cpi | 17 | 0.3514176336 | -0.0289277609 | 0.4382796232 | True |
| mean_6 | complete_monthly_cpi | 17 | 0.2886358458 | -0.0135041306 | 0.3691381168 | True |
| persistence | complete_monthly_cpi | 17 | 0.3584581400 | -0.0252307968 | 0.5066899307 | True |

### trimmed_mean_monthly_sa_mom (sub_period=full)

| model | regime | n | MAE | bias | RMSE | eligible |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| component_trim_3 | complete_monthly_cpi | 20 | 0.0698098010 | -0.0042833610 | 0.0939178309 | True |
| component_trim_6 | complete_monthly_cpi | 20 | 0.0615094205 | -0.0205765098 | 0.0871800334 | True |
| mean_12 | complete_monthly_cpi | 16 | 0.0633777519 | -0.0251716414 | 0.0890339292 | True |
| mean_3 | complete_monthly_cpi | 25 | 0.0673016947 | -0.0006729512 | 0.0926021907 | True |
| mean_6 | complete_monthly_cpi | 22 | 0.0597235192 | -0.0149067871 | 0.0827604628 | True |
| persistence | complete_monthly_cpi | 27 | 0.0969977778 | 0.0047112919 | 0.1203019816 | True |

### trimmed_mean_monthly_sa_yoy (sub_period=full)

| model | regime | n | MAE | bias | RMSE | eligible |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| component_trim_3 | complete_monthly_cpi | 17 | 0.0738278300 | -0.0034566102 | 0.1010700301 | True |
| component_trim_6 | complete_monthly_cpi | 17 | 0.0648389200 | -0.0177898853 | 0.0935116529 | True |
| mean_12 | complete_monthly_cpi | 16 | 0.0652308217 | -0.0258767070 | 0.0915564353 | True |
| mean_3 | complete_monthly_cpi | 17 | 0.0675411563 | -0.0117699758 | 0.0942290489 | True |
| mean_6 | complete_monthly_cpi | 17 | 0.0638325767 | -0.0200038009 | 0.0911555587 | True |
| persistence | complete_monthly_cpi | 17 | 0.1016425854 | -0.0029901027 | 0.1283487841 | True |

### trimmed_mean_quarterly_legacy_qoq (sub_period=full)

| model | regime | n | MAE | bias | RMSE | eligible |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| mean_4 | quarterly_legacy_tm | 173 | 0.1868265268 | 0.0234902115 | 0.2605009052 | True |
| persistence | quarterly_legacy_tm | 176 | 0.1818411443 | 0.0095869094 | 0.2408174930 | True |
| proxy_bridge_non_equivalent | quarterly_legacy_tm | 8 | 0.0941630886 | 0.0437515573 | 0.1075565035 | False |

### trimmed_mean_quarterly_legacy_yoy (sub_period=full)

| model | regime | n | MAE | bias | RMSE | eligible |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| mean_4 | quarterly_legacy_tm | 173 | 0.1930745770 | 0.0251441223 | 0.2705972380 | True |
| persistence | quarterly_legacy_tm | 174 | 0.1855908816 | 0.0113802947 | 0.2477294542 | True |

### weighted_median_monthly_sa_mom (sub_period=full)

| model | regime | n | MAE | bias | RMSE | eligible |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| mean_12 | complete_monthly_cpi | 16 | 0.0653960168 | -0.0093994567 | 0.0750977986 | True |
| mean_3 | complete_monthly_cpi | 25 | 0.0702415982 | 0.0059181809 | 0.0826196788 | True |
| mean_6 | complete_monthly_cpi | 22 | 0.0638274736 | -0.0063126124 | 0.0749895823 | True |
| persistence | complete_monthly_cpi | 27 | 0.0777233766 | 0.0049379104 | 0.0882950440 | True |

### weighted_median_monthly_sa_yoy (sub_period=full)

| model | regime | n | MAE | bias | RMSE | eligible |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| mean_12 | complete_monthly_cpi | 16 | 0.0674103690 | -0.0096482236 | 0.0773867403 | True |
| mean_3 | complete_monthly_cpi | 17 | 0.0709222920 | -0.0065212477 | 0.0811932991 | True |
| mean_6 | complete_monthly_cpi | 17 | 0.0688526674 | -0.0122920928 | 0.0808208814 | True |
| persistence | complete_monthly_cpi | 17 | 0.0792936950 | -0.0011361731 | 0.0911245342 | True |

## Common-sample selection (from nowcast.json)

| target | selected model | reason | common_n | common_mae |
| --- | --- | --- | ---: | ---: |
| headline_nsa_mom | sa_persistence_x_seasonal_12 | lowest_common_sample_mae_beats_baseline_by_at_least_0.02pp | 16 | 0.27370520556148425 |
| headline_sa_mom | mean_12 | lowest_common_sample_mae_beats_baseline_by_at_least_0.02pp | 16 | 0.27437297940990457 |
| trimmed_mean_monthly_sa_mom | mean_12 | lowest_common_sample_mae_beats_baseline_by_at_least_0.02pp | 16 | 0.06337775191326035 |
| trimmed_mean_quarterly_legacy_qoq | persistence | baseline_has_lowest_common_sample_mae | 173 | 0.17863498942033962 |
| weighted_median_monthly_sa_mom | persistence | no_model_beats_baseline_by_0.02pp_on_common_sample | 16 | 0.07707707028385274 |

## Quarterly legacy TM sub-regimes

- mean_4 2020_2021: n=8 MAE=0.2321117596 bias=-0.1170117121 RMSE=0.2908267234
- mean_4 2022_2023: n=8 MAE=0.5080021553 bias=-0.0752468291 RMSE=0.5466757702
- mean_4 2024_plus: n=10 MAE=0.1492779580 bias=0.0354662075 RMSE=0.1946442027
- mean_4 pre_2020: n=147 MAE=0.1694374030 bias=0.0356953255 RMSE=0.2375264330
- persistence 2020_2021: n=8 MAE=0.2402817236 bias=-0.0728187740 RMSE=0.2805369927
- persistence 2022_2023: n=8 MAE=0.2907850712 bias=0.0169995832 RMSE=0.3273390516
- persistence 2024_plus: n=10 MAE=0.1620017118 bias=0.0063886327 RMSE=0.1924410645
- persistence pre_2020: n=150 MAE=0.1742365995 bias=0.0137997550 RMSE=0.2359326022
- proxy_bridge_non_equivalent 2024_plus: n=8 MAE=0.0941630886 bias=0.0437515573 RMSE=0.1075565035

## True vintage

n=1 is not a skill estimate. These rows are not included in pseudo-OOS metrics.
- headline_nsa_mom seasonal_naive: status=ok reason=None
- headline_nsa_mom sa_persistence_x_seasonal_3: status=ok reason=None
- headline_nsa_mom sa_persistence_x_seasonal_6: status=ok reason=None
- headline_nsa_mom sa_persistence_x_seasonal_12: status=ok reason=None
- headline_nsa_mom component_bottom_up_3: status=blocked reason=july_2026_workbook_observations contain Table 6 analytical series only; class indexes and contribution weights were not parsed, so this model cannot run
- headline_nsa_mom component_bottom_up_6: status=blocked reason=july_2026_workbook_observations contain Table 6 analytical series only; class indexes and contribution weights were not parsed, so this model cannot run
- headline_sa_mom persistence: status=ok reason=None
- headline_sa_mom mean_3: status=ok reason=None
- headline_sa_mom mean_6: status=ok reason=None
- headline_sa_mom mean_12: status=ok reason=None
- headline_sa_mom component_sa_3: status=blocked reason=july_2026_workbook_observations contain Table 6 analytical series only; class indexes and contribution weights were not parsed, so this model cannot run
- headline_sa_mom component_sa_6: status=blocked reason=july_2026_workbook_observations contain Table 6 analytical series only; class indexes and contribution weights were not parsed, so this model cannot run
- trimmed_mean_monthly_sa_mom persistence: status=ok reason=None
- trimmed_mean_monthly_sa_mom mean_3: status=ok reason=None
- trimmed_mean_monthly_sa_mom mean_6: status=ok reason=None
- trimmed_mean_monthly_sa_mom mean_12: status=ok reason=None
- trimmed_mean_monthly_sa_mom component_trim_3: status=blocked reason=july_2026_workbook_observations contain Table 6 analytical series only; class indexes and contribution weights were not parsed, so this model cannot run
- trimmed_mean_monthly_sa_mom component_trim_6: status=blocked reason=july_2026_workbook_observations contain Table 6 analytical series only; class indexes and contribution weights were not parsed, so this model cannot run
- weighted_median_monthly_sa_mom persistence: status=ok reason=None
- weighted_median_monthly_sa_mom mean_3: status=ok reason=None
- weighted_median_monthly_sa_mom mean_6: status=ok reason=None
- weighted_median_monthly_sa_mom mean_12: status=ok reason=None
- trimmed_mean_quarterly_legacy_qoq None: status=blocked reason=The true-vintage pair is the July 2026 workbook versus the August 2026 monthly release. It does not contain a pre-release vintage of the 2026-Q3 legacy quarterly trimmed mean paired with a first-release quarterly print.
