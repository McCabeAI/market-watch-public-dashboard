# Empirical: G10 2Y spread vs FX spot (closed five-pair design)

**Input pin:** content digest `0bc766c9…` (overnight `sha256_json` excluding `packet_sha256`; raw file bytes differ — see `results.json` deviations).  
**Proxy note:** 2Y yields are a **policy-expectation proxy**, not forward carry and not the futures path.  
**Disclaimer:** Correlations only — not causation and **not a trading signal**.

## Panel coverage

| Pair | First | Last | N | Median gap (days) |
|------|-------|------|---|-------------------|
| EURUSD | 2026-05-13 | 2026-11-04 | 121 | 1 |
| AUDUSD | 2026-05-13 | 2026-10-28 | 114 | 1 |
| USDCAD | 2026-05-13 | 2026-11-03 | 116 | 1 |
| AUDCAD | 2026-05-13 | 2026-10-28 | 113 | 1 |
| USDJPY | 2026-05-13 | 2026-11-04 | 115 | 1 |

**NZ_2Y:** 10 stored points, 2026-10-21 → 2026-11-04 (NZ pairs excluded). **NOK/SEK/GBP:** no 2Y history (excluded).

## S2 — contemporaneous Δspread vs 1-step spot return

| Pair | N | r | R² | Holdout sign match? |
|------|---|---|----|---------------------|
| EURUSD | 120 | -0.0445 | 0.0020 | no |
| AUDUSD | 113 | 0.0648 | 0.0042 | yes |
| USDCAD | 115 | 0.1667 | 0.0278 | yes |
| AUDCAD | 112 | 0.2861 | 0.0819 | yes |
| USDJPY | 114 | 0.1770 | 0.0313 | yes |

## S3 h=1 — Δspread vs next 1-step spot return (predictive spec)

| Pair | N | r | R² | Holdout sign match? |
|------|---|---|----|---------------------|
| EURUSD | 120 | 0.2625 | 0.0689 | no |
| AUDUSD | 113 | 0.1803 | 0.0325 | no |
| USDCAD | 115 | 0.5082 | 0.2583 | yes |
| AUDCAD | 112 | 0.1021 | 0.0104 | no |
| USDJPY | 114 | 0.0710 | 0.0050 | yes |

## S1 level / longer horizons (headline)

Level–forward correlations are small at h=1 (|r| mostly &lt; 0.15) except mixed signs at h=5/h=20; h=20 holdout splits are **inconclusive** (N&lt;20) for all pairs. Non-overlapping h=5/h=20 samples are in `results.json`.

## Benchmark B1 (h=1)

Spot momentum (lagged 1-step vs forward 1-step) R² exceeds S1 level R² in-sample for most pairs; S1 beats momentum in-sample only for EURUSD. No pair shows a durable, holdout-stable “edge” from spreads alone.

## Conclusion (≤15 lines)

Contemporaneous (S2) links are **weak to moderate** (|r| ≈ 0.04–0.29); AUDCAD is the strongest contemporaneous association in this sample.  
One-step predictive Δspread (S3 h=1) is **material only for USDCAD** (r≈0.51, R²≈0.26) and **weak elsewhere**; signs split across pairs, so the base-currency appreciation hypothesis is **not uniformly supported**.  
Holdout sign stability is **mixed**: S2 matches in 4/5 pairs; S3 h=1 matches in 2/5.  
Spread **levels** (S1) do not reliably predict the next step; longer overlapping horizons are descriptive and h=20 holdouts are under-sized.  
Kevin’s prior — loose coupling, spreads do not **establish** spot direction — is **consistent** with low R² everywhere except one pair’s in-sample Δspread fit.  
Stored yield histories (~114–121 aligned rows) limit power; NZ/NOK/SEK/GBP gaps are structural exclusions.  
**Not causation; not a trading signal.**
