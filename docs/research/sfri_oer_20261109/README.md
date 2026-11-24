# SFRI / OER public-data research package

Research information cutoff: **2026-11-09**. The direct CoreLogic/Cotality Single-Family Rent Index (SFRI) out-of-sample test was **not run** (`direct_sfri_test`: blocked in `provenance/manifest.json`).

This folder is research-only: frozen public inputs, bibliographic press-release citations, and a **ZORI proxy sensitivity** exercise clearly labeled as not SFRI. No production dashboards, CI, schedules, or model weights are changed here.

## Rerun from the repository root

```bash
python3 docs/research/sfri_oer_20261109/scripts/build_inputs.py
python3 docs/research/sfri_oer_20261109/scripts/proxy_sensitivity.py
```

`build_inputs.py` refetches live BLS shelter CPI and Zillow ZORI (United States row only) and overwrites the CSV snapshot and `provenance/manifest.json`. The committed CSVs are the study vintage; rerunning can change numbers because BLS SA series are revised and Zillow restates full ZORI history each release.

Requirements: **Python 3**, standard library, and **numpy** only (no new package dependencies).

## Outputs

| Path | Role |
| --- | --- |
| `REPORT.md` | Dated decision: no SFRI context series and no demonstrated 1-month CPI edge |
| `G0_SOURCE_FEASIBILITY.md` | Why the direct SFRI history is blocked |
| `SOURCE_LEDGER.md` | Source identities, lags, and acquisition request |
| `PROXY_ANALYSIS.md` | ZORI-only sensitivity, generated from `results/metrics.json` |
| `verification/VERIFICATION.md` | Independent recomputation of the proxy arithmetic |
| `data/*.csv` | Frozen BLS and ZORI inputs (months through 2026-09) |
| `results/*` | Lag correlations, 1-month errors, metrics, SVG |
