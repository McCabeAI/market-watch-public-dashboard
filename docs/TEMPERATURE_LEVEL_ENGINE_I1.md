# Temperature LEVEL engine (I1)

Single implementation: `scripts/temperature_level.py`. Calibration: `data/temperature_calibration.json` + `docs/TEMPERATURE_LEVEL_CALIBRATION_V1.md`.

## Current LEVELs (2026-09 cutoff, vintage through 2026-09-21)

| Country | Inflation | Labor | Activity | Consumer |
|--------:|----------:|------:|---------:|---------:|
| US | 63.1 | 50.0 | 49.1 | 46.5 |
| CA | 54.8 | 42.2 | 64.4 | 62.1 |
| AU | 63.2 | 50.1 | 43.6 | 54.3 |
| NZ | 64.2 | 36.6 | 38.0 | 48.4 |

G1 ballpark alignment: US Inf/Lab/Act/Con match within ~0.2pt. NZ Inf/Lab/Act match. CA/AU Consumer differ from G1 rough sketches (see below); no anchor retuning applied.

## Coverage (sum of weights with observed LEVEL)

| Country | Inflation | Labor | Activity | Consumer |
|--------:|----------:|------:|---------:|---------:|
| US | 1.00 | 1.00 | 1.00 | 1.00 |
| CA | 1.00 | 1.00 | 0.60 | 0.75 |
| AU | 1.00 | 1.00 | 0.60 | 0.75 |
| NZ | 1.00 | 1.00 | 0.60 | 1.00 |

Missing: CA/AU/NZ business surveys (Activity 0.40); CA BoC CSCE; AU monthly retail (post-2025-06).

## IMPULSE + direction (latest print vs prior print)

Thresholds: warming ≥ +1.0, cooling ≤ −1.0.

| Country | Dimension | Impulse | Direction |
|--------|-----------|--------:|-----------|
| US | Inflation | −0.81 | static |
| US | Labor | +0.36 | static |
| US | Activity | −6.00 | cooling |
| US | Consumer | +3.55 | warming |
| CA | Inflation | 0.00 | static |
| CA | Labor | −2.52 | cooling |
| CA | Activity | +28.38 | warming |
| CA | Consumer | +4.53 | warming |
| AU | Inflation | −1.50 | cooling |
| AU | Labor | −0.30 | static |
| AU | Activity | +4.04 | warming |
| AU | Consumer | +20.00 | warming |
| NZ | Inflation | +4.25 | warming |
| NZ | Labor | −2.10 | cooling |
| NZ | Activity | −28.46 | cooling |
| NZ | Consumer | −4.50 | cooling |

Large Activity impulses reflect GDP q/q SAAR step (QoQ release), not cumulative scoring.

## G1 deltas explained (>3pt)

**CA Consumer (62.1 vs G1 “mid-50s”)** — Renormalized mean over coverage 0.75: retail 3m m/m → LEVEL 65.1 (2026-06), Q2 nominal income +2.12% q/q → 66.8, Q2 real consumption +0.8% q/q → 54.5. Weighted: `(0.25×65.1 + 0.25×66.8 + 0.25×54.5) / 0.75 = 62.1`. G1 narrative was approximate; arithmetic uses pinned anchors (4% SAAR nominal / 2% real).

**AU Consumer (54.3 vs G1 “mixed ~50s”)** — Without retail (unobserved), Westpac Sep 84.4 maps to LEVEL **34.4** (anchor 100), Q2 income LEVEL 49.6, MHSI 3m mean LEVEL 79.0 → coverage-weighted composite 54.3.

## Pathology scan (`data/temperature_history/score_paths.json`)

Nine `large_level_jump` findings (|ΔLEVEL| > 15 month-on-month), all on **Activity** dimensions:

- **US / CA / AU / NZ**: jumps cluster when **quarterly GDP** enters the window (reference_period flips at quarter-end months) while survey weights are zero (coverage 0.60). Example: CA Activity +28.4 from 2026-05→2026-06 when Q2 GDP posts; NZ Activity −28.5 on 2026-05→2026-06 when prior quarter rolls off trailing reconstruction.
- **US Activity** also shows ISM + GDP blend shifts when monthly survey prints change (2026-02→2026-03 +16.0).

No boundary compression (≥3 months at 1 or 100). No monotonic calendar drift with unchanged inputs (LEVEL flat between releases when tested with dummy future index row).

**Counterintuitive checks**: CA/NZ Labor LEVEL falls when unemployment is above u* (hot_direction −1) — consistent. Unemployment up → Labor LEVEL down.

## Outputs

- `data/temperature_scores.json` — version 3 state, structural `baseline_meaning`, per-dimension `lineage`, `component_state`, frozen `components` weights.
- `data/temperature_history/score_paths.json` — monthly LEVEL paths 2025-09 … 2026-09.

## Tests

`tests/test_temperature_level.py` + `tests/test_temperature_history_audit.py`; `scripts/validate_score_sources.py` against v3 state.
