# Labor Score V1 — Cross-Country Weighting

Status: ACTIVE

This document governs the **Labor** input inside the lightweight Market Watch 1–100 temperature interface for the United States, Canada, Australia and New Zealand. It overrides the generic Labor weights in `docs/DAILY_REFRESH_V0.md` wherever they conflict.

## 1. Fixed cross-country weights

Use the same fixed Labor weights for all four economies:

- **Unemployment rate: 70%**
- **Wage / earnings growth: 20%**
- **Employment / payroll growth: 10%**

Do not renormalize these weights because of release timing, stale data or missing inputs.

## 2. Rationale

The Labor score is intended to measure labor-market tightness / slack, not reward raw job creation mechanically.

Employment or payroll growth receives only 10% because:

- raw job growth is difficult to interpret without population, migration and labor-force growth context;
- establishment / payroll estimates can be materially revised;
- the same absolute jobs gain can imply very different labor-market tightness in economies with different population growth;
- employment growth remains useful confirmation, but should not dominate the score.

Unemployment receives 70% because it is the primary score variable for realized labor-market slack. Wage / earnings growth receives 20% because it captures labor-cost pressure and worker bargaining power.

## 3. Score mechanics

Use the existing release temperature-impulse scale:

- clearly hotter / tighter: `+4`
- modestly hotter / tighter: `+2`
- mixed / economically unchanged: `0`
- modestly cooler / looser: `-2`
- clearly cooler / looser: `-4`
- exceptional shock: `+6` / `-6` only when genuinely warranted

Orientation:

- lower unemployment = hotter Labor
- higher unemployment = cooler Labor
- stronger wage / earnings growth = hotter Labor
- weaker wage / earnings growth = cooler Labor
- stronger employment / payroll growth = hotter Labor, but only at 10% weight
- weaker employment / payroll growth = cooler Labor, but only at 10% weight

Example: a clearly stronger payroll print with no change in unemployment or wages contributes `10% × +4 = +0.4` to the Labor score, not +1.4 and not +4.

A clearly higher unemployment rate classified as `-4` contributes `70% × -4 = -2.8`.

## 4. Employment-growth context

When interpreting the 10% employment / payroll component, show the broader context when available:

- population and working-age population growth;
- labor-force growth;
- participation rate;
- employment-to-population ratio;
- revisions to prior employment / payroll estimates;
- population-adjusted or labor-force-adjusted employment growth when a clean official denominator is available.

These contextual measures do not receive additional score weight unless this methodology is explicitly changed.

## 5. Context-only labor indicators

Important labor releases still belong on country pages even when they do not move the score. Examples include:

- ADP or other private payroll estimates;
- JOLTS openings, hires, quits and layoffs;
- initial / continuing claims;
- survey employment subindexes such as ISM employment;
- layoff announcements;
- vacancies and vacancy rates;
- participation and employment-to-population ratios;
- population / migration data relevant to interpreting employment growth.

Retain these as time series and present them under the country-page data standard in `docs/DAILY_REFRESH_V0.md`. Their score role is `CONTEXT ONLY` unless they are one of the three defined Labor inputs above.

## 6. Transition rule

The currently displayed Labor scores remain transition anchors:

- United States: 75
- Canada: 38
- Australia: 50
- New Zealand: 32

Do not retroactively rebuild them from historical data merely because the weights changed. From this change forward, all new Labor score moves must use 70% unemployment / 20% wages / 10% employment-payroll growth.

Preserve fractional score moves internally and show at least one decimal place when a weighted release changes the score by a fraction.
