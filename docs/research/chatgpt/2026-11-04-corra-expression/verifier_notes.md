# Independent verifier notes (Composer V)

Sources: `frozen_inputs.json`, `calc_results.json`; snapshot confirm via git `612666a21e621e6bb437802cb48ace011f181b7b` `data/overnight/runs/overnight-20261104/reviews/review-001/evidence_snapshot.json`.

**Run result:** 72 PASS, 0 FAIL

## Checks

- **corra_equal_weight_mean:** PASS (expected 3.1550000000000002, got 3.1550000000000002)
- **sofr_equal_weight_mean:** PASS (expected 4.4775, got 4.4775)
- **corra_H_to_Z_bp:** PASS (expected 33.999999999999986, got 33.999999999999986)
- **sofr_H_to_Z_bp:** PASS (expected 14.999999999999947, got 14.999999999999947)
- **us_minus_ca_spread_2027-03:** PASS (expected 139.5, got 139.5)
- **us_minus_ca_spread_2027-06:** PASS (expected 138.0, got 138.0)
- **us_minus_ca_spread_2027-09:** PASS (expected 131.0, got 131.0)
- **us_minus_ca_spread_2027-12:** PASS (expected 120.49999999999996, got 120.49999999999996)
- **ca_minus_us_H_to_Z_steepener_diff_bp:** PASS (expected 19.00000000000004, got 19.00000000000004)
- **corra_premium_2027-03:** PASS (expected 43.000000000000014, got 43.000000000000014)
- **corra_premium_2027-06:** PASS (expected 57.500000000000014, got 57.500000000000014)
- **corra_premium_2027-09:** PASS (expected 68.5, got 68.5)
- **corra_premium_2027-12:** PASS (expected 77.0, got 77.0)
- **sofr_premium_2027-03:** PASS (expected 41.5, got 41.5)
- **sofr_premium_2027-06:** PASS (expected 54.49999999999999, got 54.49999999999999)
- **sofr_premium_2027-09:** PASS (expected 58.5, got 58.5)
- **sofr_premium_2027-12:** PASS (expected 56.49999999999995, got 56.49999999999995)
- **aonia_quarter_Mar_Apr_May:** PASS (expected 4.908333333333334, got 4.908333333333334)
- **aonia_quarter_Jun_Jul_Aug:** PASS (expected 4.855, got 4.855)
- **aonia_quarter_Sep_Oct_Nov:** PASS (expected 4.773333333333333, got 4.773333333333333)
- **aonia_quarter_Dec27_Jan28_Feb28:** PASS (expected 4.6866666666666665, got 4.6866666666666665)
- **usd_per_cad:** PASS (expected 0.7155475900915316, got 0.7155475900915316)
- **CRA_dv01_usd:** PASS (expected 17.88868975228829, got 17.88868975228829)
- **SR3_dv01_usd:** PASS (expected 25.0, got 25.0)
- **IB_dv01_usd_published_24_66:** PASS (expected 17.222099081651773, got 17.222099081651773)
- **IB_unrounded_not_for_valuation:** PASS (expected 24.65753424657534, got 24.65753424657534)
- **equal_lot_floored:** PASS (expected 349, got 349)
- **equal_lot_achieved_parallel_dv01:** PASS (expected 24972.61089419445, got 24972.61089419445)
- **flattener_floored_lots:** PASS (expected 1397, got 1397)
- **flattener_achieved_leg_dv01:** PASS (expected 24990.49958394674, got 24990.49958394674)
- **corra_slide_H:** PASS (expected -22.00000000000002, got -22.00000000000002)
- **sofr_slide_H:** PASS (expected -20.500000000000007, got -20.500000000000007)
- **corra_slide_M:** PASS (expected -14.500000000000002, got -14.500000000000002)
- **sofr_slide_M:** PASS (expected -12.99999999999999, got -12.99999999999999)
- **corra_slide_U:** PASS (expected -10.999999999999988, got -10.999999999999988)
- **sofr_slide_U:** PASS (expected -4.0000000000000036, got -4.0000000000000036)
- **corra_slide_Z:** PASS (expected -8.499999999999996, got -8.499999999999996)
- **sofr_slide_Z:** PASS (expected 2.000000000000046, got 2.000000000000046)
- **composer_a_markdown_sofr_slide_table_matches_json:** PASS (expected 'markdown shows −20.5/−13/−4/+2 and avg −8.875', got "exact legs {'H': -20.500000000000007, 'M': -12.99999999999999, 'U': -4.0000000000000036, 'Z': 2.000000000000046} avg -8.87499999999999")
- **flattener_roll_economic_sign_negative:** PASS (expected 'negative bp and USD on roll', got 'bp=-13.500000000000025 usd=-337371.74')
- **section7_flattener_field_matches_economic_sign:** PASS (expected 'same sign as legDV01*(dH-dZ)', got 'section7=-13.500000000000025 economic=-13.500000000000025') — section7 field is slide_H - slide_Z
- **roll_flattener_usd_vs_recompute:** PASS (expected -337371.74, got -337371.74)
- **cross_strip_roll_net_usd:** PASS (expected 127741.55, got 127741.55)
- **paper_unrealized_250m:** PASS (expected 600000.0, got 599999.9999999994)
- **scenario_S_parallel_selloff_25:** PASS (expected -625000.0, got -625000.0)
- **scenario_S_bull_flatten:** PASS (expected 125000.0, got 125000.0)
- **scenario_S_bear_steepen:** PASS (expected -156250.0, got -156250.0)
- **scenario_S_deescalation:** PASS (expected 750000.0, got 750000.0)
- **canada_only_cross_approx_ca_loss_minus_us_pay:** PASS (expected -499315.27, got -499315.27)
- **composer_B_journal_gap_is_half_bp:** PASS (expected 0.5, got 0.49999999999998934) — journal 3.16 vs snapshot 3.155
- **composer_B_premium_2027-03:** PASS (expected 43.0, got 43.000000000000014)
- **composer_B_premium_2027-06:** PASS (expected 57.5, got 57.500000000000014)
- **composer_B_premium_2027-09:** PASS (expected 68.5, got 68.5)
- **composer_B_premium_2027-12:** PASS (expected 77.0, got 77.0)
- **composer_B_avg_premium_61_5:** PASS (expected 61.5, got 61.50000000000001)
- **composer_B_HZ_slope_34bp:** PASS (expected 34.0, got 33.999999999999986)
- **uz_only_parallel_selloff_25:** PASS (expected -312157.64, got -312157.64)
- **uz_only_roll:** PASS (expected 121741.48, got 121741.48)
- **reduced_slice_realized_matches_book:** PASS (expected True, got 599999.9999999994)
- **snapshot_match_USDCAD spot:** PASS (expected 1.3975310850702212, got 1.3975310850702212)
- **snapshot_match_AUDUSD spot:** PASS (expected 0.6983819578934215, got 0.6983819578934215)
- **snapshot_match_CORRA cash:** PASS (expected 2.54, got 2.54)
- **snapshot_match_SOFR cash:** PASS (expected 3.95, got 3.95)
- **snapshot_match_AONIA cash:** PASS (expected 4.6, got 4.6)
- **snapshot_match_CRA_2027-03:** PASS (expected 2.97, got 2.97)
- **snapshot_match_SR3_2027-03:** PASS (expected 4.365, got 4.365)
- **snapshot_match_CRA_2027-06:** PASS (expected 3.115, got 3.115)
- **snapshot_match_SR3_2027-06:** PASS (expected 4.495, got 4.495)
- **snapshot_match_CRA_2027-09:** PASS (expected 3.225, got 3.225)
- **snapshot_match_SR3_2027-09:** PASS (expected 4.535, got 4.535)
- **snapshot_match_CRA_2027-12:** PASS (expected 3.31, got 3.31)
- **snapshot_match_SR3_2027-12:** PASS (expected 4.515, got 4.515)

## Flattener roll sign (item 5)

- Economic: pay H / receive Z, `PnL = legDV01 × (dH − dZ)` with dH≈−22 bp, dZ≈−8.5 bp → **−13.5 bp per leg DV01 (loss)**.
- First Composer V run (before parent label fixes) found three documentation fails: SOFR markdown rounded the Z slide to −2 and the average to −10; `section_7` stored +13.5 with the opposite sign of `dH−dZ`; Composer B called the 3.16 versus 3.155 gap 1 bp.
- Parent corrected those labels in the calculator, Composer A note, and Composer B note. This file is the re-run. Scenario USD for the flattener roll was already the economic loss and did not change.
- A separate calculator bug treated realized P&L as half of the residual 250m. The closed slice was 250m of the original 500m. That identity now matches the stored 600,000.

## Composer B arithmetic

- Journal **3.16%** versus snapshot mean **3.155%** is **+0.5 bp**.
- Premia **+43/+57.5/+68.5/+77**, average **+61.5**, H→Z **+34 bp** match the frozen inputs.

No trade recommendation.
