# US payroll breakeven-employment anchor (2026)

## Canonical source

**Title:** Labor force growth, breakeven employment, and potential GDP growth  
**Authors:** Seth Murray and Ivan Vidangos  
**Publisher:** Board of Governors of the Federal Reserve System, FEDS Notes  
**Date:** April 2, 2026  
**URL:** https://www.federalreserve.gov/econres/notes/feds-notes/labor-force-growth-breakeven-employment-and-potential-gdp-growth-20260402.html

### Key quotes (Board, Apr 2026)

On potential labor-force growth in 2026:

> The combination of historically weak population growth and declining potential LFPR would imply that the pool of available workers in the U.S. could grow by **less than 10,000 workers per month in 2026**.

On breakeven employment growth:

> Breakeven employment growth is the number of jobs that must be added to the economy each month to keep the unemployment rate steady while still absorbing the growth in the potential labor force.

> The breakeven pace in 2026 could be significantly lower than even the historic low reached during the pandemic. As discussed above, the rapid slowing of net immigration may translate into such a large drop in labor force growth that the breakeven pace could fall to **nearly zero**, requiring **less than 10,000 new jobs per month in 2026**.

Historical context in the same note: breakeven averaged about **155,000** jobs/month in **2023–24**, fell to an estimated **85,000** in **2025** as net immigration slowed—explaining why a ~150k payroll-neutral anchor is stale for 2026.

## Frozen calibration point

| Field | Value |
|---|---|
| `US.Labor.payrolls.anchor` | **10.0** (thousands of jobs per month) |
| `anchor_kind` | `structural_trend` |
| Scoring transform | `trailing_mean_n3` on PAYEMS m/m change (thousands, SA) |
| `hot_direction` | +1 |
| `scale_per_unit` | 0.2 |
| `replaced_anchor` | 150.0 |

### Point convention

The Board note gives a range-like statement (“near-zero” / “less than 10,000”) rather than a single published point for 2026. We freeze **`anchor: 10.0`** as the **upper bound** of “less than 10,000 new jobs per month”—conservative versus using 0, and far below the retired 150k working-age trend. This is **not** chosen to hold US Labor near 50.

## Range sensitivity (not substitutes)

| Source | Date | URL | Range / comment |
|---|---|---|---|
| St. Louis Fed, Alexander Bick | Mar 24, 2026 | https://www.stlouisfed.org/on-the-economy/2026/mar/breakeven-employment-growth-estimate-range-widens-2026 | **15,000 to 87,000** jobs/month in 2026 (volatile immigration projections) |
| Dallas Fed, Cheremukhin | Mar 31, 2026 | https://www.dallasfed.org/research/economics/2026/0331 | Near zero / slightly negative recently |
| Chicago Fed WP 2026-10 | 2026 | https://www.chicagofed.org/-/media/publications/working-papers/2026/wp2026-10.pdf | Roughly **25k–100k** using CBO projections |

## Sensitivity table (engine, cutoff 2026-09)

Computed in memory from committed history + calibration weights (unemployment and wages held at observed LEVELs). Payroll input: **71.33k** 3-month average (Aug 2026 latest print).

| Breakeven anchor (k/month) | Payroll component LEVEL | US Labor LEVEL |
|---:|---:|---:|
| 0 | 64.27 | 53.00 |
| **10** (frozen) | **62.27** | **52.80** |
| 15 | 61.27 | 52.70 |
| 50 | 54.27 | 52.00 |
| 87 | 46.87 | 51.26 |
| 100 | 44.27 | 51.00 |
| 150 (retired) | 34.27 | 50.00 |

**Before → after (anchor 150 → 10):** payroll component **34.27 → 62.27**; US Labor **50.0 → 52.8** (unemployment **52.0**, wages **50.86** unchanged).

Higher breakeven anchor ⇒ cooler payroll component when realized 3m payrolls are below the old 150k anchor (monotonicity holds for current history).

## Refresh / expiry

- **Refresh:** Review when the Board publishes an updated FEDS Note on breakeven employment or labor-force demographics, or after material BLS population-control / CBO potential-LFPR revisions.
- **`expires_after`:** 2027-04-02 (one year after the canonical FEDS Note), unless refreshed earlier.
