# Temperature LEVEL engine (I1)

Single implementation: `scripts/temperature_level.py`. Calibration: `data/temperature_calibration.json` + `docs/TEMPERATURE_LEVEL_CALIBRATION_V1.md`.

## Current LEVELs (2026-09 cutoff, vintage through 2026-09-21)

| Country | Inflation | Labor | Activity | Consumer |
|--------:|----------:|------:|---------:|---------:|
| US | 63.1 | 52.8 | 50.6 | 46.5 |
| CA | 54.8 | 42.2 | 49.9 | 62.1 |
| AU | 63.2 | 50.1 | 46.0 | 54.3 |
| NZ | 64.2 | 36.6 | 50.5 | 48.4 |

Repair vs PR #66 pre-repair (single-quarter GDP LEVEL, 150k payrolls, CA/AU/NZ surveys unobserved):

| | US Act | CA Act | AU Act | NZ Act | US Labor |
|---|---:|---:|---:|---:|---:|
| Before | 49.1 | 64.4 | 43.6 | 38.0 | 50.0 |
| After | 50.6 | 49.9 | 46.0 | 50.5 | 52.8 |

## Coverage (sum of weights with observed LEVEL)

| Country | Inflation | Labor | Activity | Consumer |
|--------:|----------:|------:|---------:|---------:|
| US | 1.00 | 1.00 | 1.00 | 1.00 |
| CA | 1.00 | 1.00 | 1.00 | 0.75 |
| AU | 1.00 | 1.00 | 1.00 | 0.75 |
| NZ | 1.00 | 1.00 | 1.00 | 1.00 |

Missing: CA BoC CSCE; AU monthly retail (post-2025-06). Activity surveys are now scored with remaining month-level gaps documented in `docs/ACTIVITY_SURVEY_SOURCES.md`.

## IMPULSE + direction (latest print vs prior print)

Thresholds: warming ≥ +1.0, cooling ≤ −1.0.

| Country | Dimension | Impulse | Direction |
|--------|-----------|--------:|-----------|
| US | Inflation | −0.81 | static |
| US | Labor | +0.36 | static |
| US | Activity | −3.36 | cooling |
| US | Consumer | +3.55 | warming |
| CA | Inflation | 0.00 | static |
| CA | Labor | −2.52 | cooling |
| CA | Activity | +17.39 | warming |
| CA | Consumer | +4.53 | warming |
| AU | Inflation | −1.50 | cooling |
| AU | Labor | −0.30 | static |
| AU | Activity | +4.83 | warming |
| AU | Consumer | +20.00 | warming |
| NZ | Inflation | +4.25 | warming |
| NZ | Labor | −2.10 | cooling |
| NZ | Activity | −16.40 | cooling |
| NZ | Consumer | −4.50 | cooling |

GDP **component** impulses remain the latest single-quarter SAAR step (CA GDP +28.4, NZ GDP −28.5). Dimension Activity impulse is smaller because surveys now take 40% weight and GDP **LEVEL** is a two-quarter mean SAAR.

AU survey LEVEL is `short_window` (July 2026 flash only; Apr–Jun gapped), so the 3m mean collapses to the latest flash print.

## Pathology scan (`data/temperature_history/score_paths.json`)

Zero `large_level_jump` findings after the 2Q GDP LEVEL window plus scored surveys. Previously nine Activity jumps at quarter boundaries when surveys were unobserved.

No boundary compression. No monotonic calendar drift.

## Outputs

After changing history or calibration, regenerate committed state with:

`PYTHONPATH=. python3 scripts/temperature_level.py --write-state --write-paths`

CI `cmp`s those files byte-for-byte against the engine output.

## Tests

`tests/test_temperature_level.py`, `tests/test_temperature_history_audit.py`, `tests/test_payroll_breakeven_anchor.py`; `scripts/validate_score_sources.py` against v3 state.
