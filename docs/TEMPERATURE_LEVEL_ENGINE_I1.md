# Temperature LEVEL engine (I1)

Single implementation: `scripts/temperature_level.py`. Calibration: `data/temperature_calibration.json` + `docs/TEMPERATURE_LEVEL_CALIBRATION_V1.md`.

## Current LEVELs (2026-09 cutoff)

Numeric table in `data/temperature_scores.json` is **stale until the parent regenerates** disk state after merge. Engine changes in this repair:

- **GDP Activity LEVEL** = two-quarter mean SAAR (`level_scoring_transform`); **GDP impulse** = single-quarter SAAR step (unchanged visibility on CA +28 / NZ −28 component impulses).
- **US ISM** surveys: 12 months of press-release history; LEVEL = 3m mean, impulse = 1m delta; Activity coverage returns to **1.00** when recomputed.

Qualitative: CA/NZ Activity GDP LEVEL moves toward neutral (~50) vs the old single-quarter pathology (~64 / ~38).

## Coverage (sum of weights with observed LEVEL)

| Country | Inflation | Labor | Activity | Consumer |
|--------:|----------:|------:|---------:|---------:|
| US | 1.00 | 1.00 | 1.00 (GDP+ISM) | 1.00 |
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

Large Activity **component** impulses on GDP still reflect the latest q/q→SAAR **single-quarter** step (release shock). **LEVEL** uses the 2Q-mean SAAR so dimension LEVEL no longer tracks a lone hot/cold quarter.

## G1 deltas explained (>3pt)

**CA Consumer (62.1 vs G1 “mid-50s”)** — Renormalized mean over coverage 0.75: retail 3m m/m → LEVEL 65.1 (2026-06), Q2 nominal income +2.12% q/q → 66.8, Q2 real consumption +0.8% q/q → 54.5. Weighted: `(0.25×65.1 + 0.25×66.8 + 0.25×54.5) / 0.75 = 62.1`. G1 narrative was approximate; arithmetic uses pinned anchors (4% SAAR nominal / 2% real).

**AU Consumer (54.3 vs G1 “mixed ~50s”)** — Without retail (unobserved), Westpac Sep 84.4 maps to LEVEL **34.4** (anchor 100), Q2 income LEVEL 49.6, MHSI 3m mean LEVEL 79.0 → coverage-weighted composite 54.3.

## Pathology scan (`data/temperature_history/score_paths.json`)

Nine `large_level_jump` findings (|ΔLEVEL| > 15 month-on-month), all on **Activity** dimensions:

- **CA / AU / NZ**: GDP still drives 60% coverage; 2Q-mean LEVEL dampens quarter-end GDP spikes vs the prior single-quarter LEVEL rule. Component impulses remain large on GDP releases.
- **US Activity**: full ISM history restores survey weight (28%/12%); path jumps may still appear when ISM 3m LEVEL shifts alongside GDP.

No boundary compression (≥3 months at 1 or 100). No monotonic calendar drift with unchanged inputs (LEVEL flat between releases when tested with dummy future index row).

**Counterintuitive checks**: CA/NZ Labor LEVEL falls when unemployment is above u* (hot_direction −1) — consistent. Unemployment up → Labor LEVEL down.

## Outputs

After changing history or calibration, regenerate committed state with:

`PYTHONPATH=. python scripts/temperature_level.py --write-state --write-paths`

CI `cmp`s those files byte-for-byte against the engine output.

## Tests

`tests/test_temperature_level.py` + `tests/test_temperature_history_audit.py`; `scripts/validate_score_sources.py` against v3 state.
