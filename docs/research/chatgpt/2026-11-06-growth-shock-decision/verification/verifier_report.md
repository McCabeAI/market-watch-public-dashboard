# Verifier report: 2026-11-06 growth-shock packet

Process exit code: 0.

## Pass and fail counts

| class | pass | fail |
| --- | ---: | ---: |
| unit | 11 | 0 |
| sign | 10 | 0 |
| lineage | 17 | 0 |
| sample | 4 | 0 |
| horizon | 1 | 0 |
| economic | 11 | 0 |

## Failed checks

No check failed.
## Reproduced figures

- EUR mark-to-market versus entry, 5,000,000 * (1.1224/1.1267 - 1): unrounded -19082.27567231738705955445100, nearest dollar -19082.
- Specified short window is the last 20 observations, which is 19 changes. Published short-window n_changes is 19.
- CA_2Y 19-change sample standard deviation: 5.582449524183669. EURUSD 19-change sample standard deviation: 0.30873265049217075.
- EURUSD median of 126 closes: 1.1467. Median claim 1.1467 passed: True.
- CORRA equal-weight mean 3.05125; gap versus book mark 3.10875 is -5.75000 bp; receive PnL at 100m is 57500.00000.
- Book identity (3.4 - 3.10875) * 100 * 10000 = 291250.00000.
- Financing on the draw, ACT/360, 3.94 percent, 70 calendar days: 500,000 costs 3830.555555555555555555555555; 50,000 costs 383.0555555555555555555555555.
- CORRA 50m to 3.26 PnL -104375.000000; EUR 5m to 1.113 PnL -41874.55452601568068424804000; sum of those nearest dollars -146250.
- Budget-implied CORRA notional 47904191.61676646706586826347; overrun of the 100,000 budget at 50m is 4375.000000.
- SR3 10m receive adverse PnL -7250.00; 10m pay adverse PnL -7500.00; budget-implied receive notional in USD 13793103.44827586206896551724 (10000/(29*25) million dollars, times 1,000,000).

## Objections

Economic rows are judgment limits, not arithmetic failures. They are status pass so they stay on the record and do not change the exit code. Horizon fails only when full-sample std times sqrt(h) is wrong or 70 is under the square root.

- `economic_meeting_price_exclusion` (economic, pass). Objection: derived meeting-price and Fed path estimates are excluded. Calendars keep scheduling metadata only, so policy inference from meeting prices is coarse. This is not an arithmetic error.
  - claimed: `"Derived meeting-price and Fed path estimates are excluded per quarantine: policy_meeting_prices calendar rows keep scheduling metadata only (no rate levels or step deltas); policy_paths terminal nodes and overnight delta fields are named only as quarantined paths; SR1 one-month futures quotes are listed without overnight deltas and flagged as not meeting steps."`
  - reproduced: `"policy inference from meeting prices is coarse"`
- `economic_ca_labor_not_a_print` (economic, pass). Objection: CA labor components are source_failed. A Canadian employment scenario is not a print in this packet.
  - claimed: `[{"series_id": "CA.Labor.employment", "status": "source_failed", "research_status": "unavailable"}, {"series_id": "CA.Labor.unemployment", "status": "source_failed", "research_status": "unavailable"}, {"series_id": "CA.Labor.wages", "status": "source_failed", "research_status": "unavailable"}, {"series_id": "CA.Labor.participation", "status": "source_failed", "research_status": "unavailable"}]`
  - reproduced: `{"source_failed_or_unavailable_rows": [{"series_id": "CA.Labor.employment", "status": "source_failed", "research_status": "unavailable"}, {"series_id": "CA.Labor.unemployment", "status": "source_failed", "research_status": "unavailable"}, {"series_id": "CA.Labor.wages", "status": "source_failed", "research_status": "unavailable"}, {"series_id": "CA.Labor.participation", "status": "source_failed", "research_status": "unavailable"}]}`
- `economic_no_strip_history_proxies` (economic, pass). Objection: there is no CORRA strip history and no SR3 strip history. CA_2Y and US_2Y daily differences are proxies, not the futures strip.
  - claimed: `{"corra_contracts_have_history": false, "sr3_contracts_have_history": false, "proxy_yardsticks": ["CA_2Y", "US_2Y"]}`
  - reproduced: `"CA_2Y and US_2Y are proxies"`
- `economic_no_eur_forward_yield_gap_is_not_spot_carry` (economic, pass). Objection: there is no EUR forward. The 2y yield-gap figure is a labeled sensitivity, not carry that predicts spot. US_2Y is dated 2026-11-05 and EA_2Y is dated 2026-11-06.
  - claimed: `{"US_2Y_as_of": "2026-11-05", "EA_2Y_as_of": "2026-11-06", "results_sensitivity": 14680.555555555553}`
  - reproduced: `{"sensitivity_reproduced": "14680.55555555555555555555555", "dates_differ": true}`
- `economic_corra_observation_dates_null` (economic, pass). Objection: CORRA observation dates are null, so the frozen implied average is not assigned to a session.
  - claimed: `{"CRAH27": null, "CRAM27": null, "CRAU27": null, "CRAZ27": null}`
  - reproduced: `"all four CRAH27/CRAM27/CRAU27/CRAZ27 observation_date values are null"`
- `economic_spx_vix_and_broad_usd_dates` (economic, pass). Objection: S&P and VIX are 2026-11-04. Broad USD ends 2026-10-30. They are not a 2026-11-05 confirmation print.
  - claimed: `{"SP500_as_of": "2026-11-04", "VIX_as_of": "2026-11-04", "BROAD_USD_last_date": "2026-10-30"}`
  - reproduced: `{"confirmed": true}`
- `economic_oil_histories_include_rolls` (economic, pass). Objection: WTI and Brent histories include contract rolls. Roll jumps can distort screens. They are not a clean spot path.
  - claimed: `{"WTI": "Daily completed close. Futures history includes contract rolls; roll jumps can distort screens.", "BRENT": "Daily completed close. Futures history includes contract rolls; roll jumps can distort screens."}`
  - reproduced: `"roll jumps can distort screens"`
- `economic_corra_50m_overspends_100k_budget` (economic, pass). Objection: the 50m CORRA proposal overspends a 100000 budget. Adverse loss at 50m is 104375, overrun 4375. Size-from-budget is 47904191.62 USD, about 47.9 million. This objects to treating 50m as exactly the budget. It is not a new trade idea.
  - claimed: `{"proposed_notional_usd": 50000000, "results_budget_implied": 47904191.61676652}`
  - reproduced: `{"adverse_loss_usd": "104375.000000", "budget_usd": "100000", "overrun_usd": "4375.000000", "budget_implied_notional_usd": "47904191.61676646706586826347", "budget_implied_about_millions": "47.9"}`
- `economic_targets_are_not_probabilities_or_fair_values` (economic, pass). Objection: targets are not probabilities and not fair values. A horizon multiple of a sample standard deviation is a scale, not a probability.
  - claimed: `{"target_labels_saying_not_fair_value": ["judgmental range for the equal-weight average, not fair value; 2.98 is the more ambitious receive", "judgmental range given up if flat, not fair value", "judgmental range, not fair value", "references given up if flat, not fair value", "retested judgmental references, not fair value; 1.1356 is the prior arithmetic marker, 1.1467 is the median of these 126 closes", "same retested references as the hold; not fair value"], "horizon_label": "convention_not_a_probability"}`
  - reproduced: `"targets remain judgmental marks"`
- `economic_n252_screens_are_not_the_126_point_sample` (economic, pass). Objection: n=252 screens are not the 126-point sample. Stored n_field is 252 while the history used here has 126 points and 125 changes.
  - claimed: `{"n_field_values_on_126_point_series": [252], "len_history": 126, "num_changes": 125}`
  - reproduced: `"126 points, 125 changes"`
- `economic_one_day_equity_and_yield_moves_are_not_one_cause` (economic, pass). Objection: one-day equity and yield moves are not a single cause. S&P is dated 2026-11-04 while US_2Y and NASDAQ are dated 2026-11-05, and CA_2Y ends 2026-11-04. Sharing a headline date does not make the moves one cause.
  - claimed: `{"SP500_as_of": "2026-11-04", "NASDAQ_as_of": "2026-11-05", "US_2Y_as_of": "2026-11-05", "CA_2Y_as_of": "2026-11-04"}`
  - reproduced: `"one session does not identify one cause"`

## What this report is not

This is an objection list with recomputed figures. It does not choose a position, a size, or a fair value.
