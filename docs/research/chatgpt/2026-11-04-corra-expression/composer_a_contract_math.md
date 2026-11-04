# Composer A — CORRA expression contract math (research note)

**Evidence:** `frozen_inputs.json` only (pinned commit `612666a21e621e6bb437802cb48ace011f181b7b`).  
**Machine output:** `calc_results.json` from `calc_contracts.py`.  
**Not a trade recommendation.** No probabilities.

---

## Conventions (from frozen inputs)

| Object | Local DV01 / lot | USD conversion |
|--------|------------------|----------------|
| CRA (CORRA 3m) | CAD 25 per 1bp index move; face CAD 1m | `25 × (1/USDCAD)` |
| SR3 (SOFR 3m) | USD 25; face USD 1m | USD 25 |
| IB (AONIA 1m) | A$24.66 published (30/365 on A$3m face) | `24.66 × AUDUSD` |

Long futures / receive rates: **PnL = −DV01_USD × Δrate_bp** per leg (rates up → loss).  
Lot rounding: **floor toward zero**.

---

## 1. Identity checks

**Equal-weight mean (2027 H/M/U/Z expiries):**

\[
\bar r = \frac{1}{4}\sum_{i=1}^{4} r_i
\]

**H-to-Z steepness (bp):**

\[
\Delta_{H\to Z}^{bp} = 100 \times (r_Z - r_H)
\]

**US − CA spread at each expiry (bp):** \(100 \times (r^{US}_i - r^{CA}_i)\).

**Premium vs own cash fixing (bp):** \(100 \times (r^{implied} - r^{cash})\) — not labeled as meeting counts.

**AONIA labeled quarterly proxy:** simple mean of listed calendar months (Mar–May, Jun–Aug, Sep–Nov, Dec27–Feb28). **Not** a compounded IMM quarter.

**Nov 3 journal mids** (not Nov 4 snapshot): recompute average of (2.96, 3.12, 3.235, 3.325); leg bp change vs Nov 4 snapshot = \(100 \times (r^{Nov4}_i - r^{journal}_i)\).

### Compact results

| Item | Value |
|------|------:|
| CORRA H/M/U/Z (%) | 2.97, 3.115, 3.225, 3.31 |
| CORRA mean | 3.155 |
| CORRA H→Z (bp) | 34 |
| SOFR H/M/U/Z (%) | 4.365, 4.495, 4.535, 4.515 |
| SOFR mean | 4.4775 |
| SOFR H→Z (bp) | 15 |
| US−CA spread (bp) Mar/Jun/Sep/Dec | 139.5, 138, 131, 120.5 |
| CA−US H→Z steepener diff (bp) | 19 |
| Cash CORRA / SOFR / AONIA (%) | 2.54 / 3.95 / 4.60 |
| AONIA Q-proxy (%) Mar–May / Jun–Aug / Sep–Nov / Dec-window | 4.9083… / 4.855 / 4.7733… / 4.6867… |
| AONIA contract months Mar/Jun/Sep/Dec 2027 (%) | 4.915 / 4.885 / 4.8 / 4.71 |
| Nov 3 journal average | 3.16 (matches claim) |
| Nov 4 − journal (bp) by leg | +1, −0.5, −1, −1.5 |

Identity check failures: **none** (see `calc_results.json`).

---

## 2. Paper engine (book fields unchanged)

\[
\text{unrealized} = N \times \frac{\text{entry} - \text{mark}}{100}
= 250\times10^6 \times \frac{3.40 - 3.16}{100} = 600{,}000
\]

Realized on the closed slice: original 500m minus residual 250m, times the same 24bp, is **600,000**. That matches the stored realized figure. It is not half of the residual 250m.

\[
\text{paper DV01} = N \times 0.0001 = 25{,}000\ \text{USD/bp}
\]

Risk capital at 100bp shock: **2,500,000 USD** (stored).

**Forward** funding on risk capital (not replacing stored `funding_cost` 24,555.56):

\[
F = K \times \frac{r}{100} \times \frac{\text{days}}{360}
\quad K=2.5\times10^6,\ r=3.95\%
\]

| Horizon | Forward funding (USD) |
|---------|----------------------:|
| 91 ACT/360 | 24,961.81 |
| 182 ACT/360 | 49,923.61 |

Stored `net_after_funding` **1175444.44** — not recomputed here.

---

## 3. FX

\[
\text{usd\_per\_cad} = \frac{1}{\text{USDCAD}} = 0.7155475900915316
\]

(confirms analytics row.)

\[
\text{CRA DV01 USD} = 25 \times \text{usd\_per\_cad} \approx 17.8887
\]

IB unrounded \(3\times10^6 \times 0.0001 \times 30/365 \approx 24.6575\) — **not** used for valuation (published 24.66 × AUDUSD).

---

## 4. Equal-lot CRA receive vs paper DV01

Target: parallel **+1bp** on all four CA legs → **−25,000 USD** (long receive).

Per leg USD DV01 = \(L \times 25 \times \text{usd\_per\_cad}\). Equal lots:

\[
L^\* = \frac{25{,}000}{4 \times 25 \times \text{usd\_per\_cad}} \approx 349.04 \Rightarrow L=349
\]

| Metric | Value |
|--------|------:|
| Achieved parallel DV01 (USD/bp) | 24,972.61 |
| Shortfall (USD/bp) | 27.39 |
| Face CAD per leg / gross 4 legs | 349m / 1,396m CAD |
| Face USD per leg (≈) | 249.72m / 998.89m USD |

**Mismatch:** paper **250m USD** is duration-one **risk** notional (~one year of 90/360 risk), ≈**250m USD face per leg**, not 250m total gross face.

---

## 5. Expression B — pay H / receive Z (CRA)

Same lots both legs (identical local BPV).  
\[
\text{PnL} = \text{DV01}_{leg,USD} \times (\Delta H_{bp} - \Delta Z_{bp})
\]

| Variant | Target leg DV01 | Floored lots | Achieved leg DV01 |
|---------|----------------:|-------------:|------------------:|
| Primary | 25,000 | 1,397 | 24,990.50 |
| Half gross | 12,500 | 698 | 12,484.23 |

Checks (primary, achieved DV01): 1bp flatten (0, −1) → **+24,990.50 USD**; parallel +1bp both → **0**.

---

## 6. Expression C

**Four-leg:** receive CORRA H/M/U/Z vs pay SOFR H/M/U/Z; each book parallel DV01 → 25,000 USD.

| Book | Floored lots/leg | Achieved parallel DV01 |
|------|-----------------:|-----------------------:|
| CRA receive | 349 | 24,972.61 |
| SR3 pay | 250 | 25,000.00 |

**Single quarter:** receive CRAZ27 vs pay SR3Z7 @ 25,000 USD DV01/leg → CRA **1,397** lots, SR3 **1,000** lots.

**AONIA pay Dec-window:** USD DV01 split **25,000/3** per month (Dec27, Jan28, Feb28); size with IB published USD DV01; OI/volume mostly null on far months — **markable, not evidenced executable** in inputs.

**March-only AONIA pay @ 25,000 DV01:** contrast to Dec-window (NOT-like period).

H→Z steepener **difference** (CA − US): **19 bp** (descriptive only; no four-leg CA vs US box built).

---

## 7. One-quarter unchanged-tenor roll (assumption)

Slide leg rate to prior listed quarterly contract’s **current** rate;  
\(\text{slide}^{bp}_\ leg = 100 \times (r^{new} - r^{old})\).

| CORRA leg | Slide (bp) |
|-----------|----------:|
| H / M / U / Z | −22 / −14.5 / −11 / −8.5 |
| Equal-weight avg | −14 |

| SOFR leg | Slide (bp) |
|----------|----------:|
| H / M / U / Z | −20.5 / −13 / −4 / +2 |
| Equal-weight avg | −8.875 |

Flattener P&L per leg DV01 is \(\text{slide}_H - \text{slide}_Z = dH - dZ\) → **−13.5 bp** (a loss). The H–Z spread widens by **13.5 bp** under the same slide; that widen is not a profit.

Cross strip (receive CA roll + pay US roll, floored 349 CRA / 250 SR3 per leg): net **127,741.55 USD** → **5.11 bp** per matched 25k DV01.

---

## 8. Scenario P&L (USD, rate shocks in bp, + = rates up)

Paper (a): \(\text{PnL} = -25{,}000 \times \overline{\Delta^{CA}}_{bp}\) (CA legs only).  
Real legs (b–e): sum signed DV01 × leg shocks; floored sizes from sections 4–6.

Forward funding lines are **separate**, not netted into rate P&L.

| Scenario | (a) Paper | (b) CRA 4-leg | (c) Flattener | (d) CA vs SOFR strip | (e) Z vs AONIA window |
|----------|----------:|--------------:|--------------:|---------------------:|----------------------:|
| S_parallel_selloff_25 | −625,000 | −624,315.27 | 0 | 684.73 | −891.95 |
| S_parallel_rally_25 | 625,000 | 624,315.27 | 0 | −684.73 | 891.95 |
| S_bull_flatten | 125,000 | 124,863.05 | 749,714.99 | 124,863.05 | 499,809.99 |
| S_bear_steepen | −156,250 | −156,078.82 | −749,714.99 | −156,078.82 | −499,809.99 |
| S_common_selloff_20 | −500,000 | −499,452.22 | 0 | 547.78 | −713.56 |
| S_canada_only_25 | −625,000 | −624,315.27 | 0 | −499,315.27 | −499,988.38 |
| S_deescalation | 750,000 | 749,178.33 | 0 | 374,178.33 | 375,392.66 |
| S_roll_1q | 350,000 | 349,616.55 | −337,371.74 | 127,741.55 | 212,419.25 |

---

## 9. Factor line (floored equal CRA receive, 349 lots)

| Shock | USD P&L |
|-------|--------:|
| +1bp H alone | −6,243.15 |
| +1bp M alone | −6,243.15 |
| +1bp U alone | −6,243.15 |
| +1bp Z alone | −6,243.15 |
| +1bp parallel all legs | −24,972.60 |

---

## Approximations (explicit)

1. **90/360** CRA/SR3 BPV vs true IMM accrual dates (exact IMM dates not in pin).  
2. **AONIA** “quarter” = simple average of three monthly futures, not compounded quarter fixings.  
3. **Floor** lot counts → achieved DV01 slightly below 25,000 targets.  
4. **Unchanged-tenor roll** = descriptive slide to prior contract rate, not a forecast or second-quarter roll.  
5. **No convexity** adjustment in module or snapshot.  
6. **FX** dated 2026-11-03 applied to CAD/AUD contract DV01 conversion.

---

*Generated by Composer A (`calc_contracts.py`). Parent later corrected the SOFR slide table to the exact JSON slides (−20.5 / −13 / −4 / +2, average −8.875), set the flattener roll P&L to −13.5 bp per leg DV01, and corrected realized P&L to the closed 250m slice of the original 500m. Scenario USD figures were already on that sign.*
