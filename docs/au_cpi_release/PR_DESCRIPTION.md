# Australian CPI pre-release nowcast — v2 quarterly headline repair (Sep 2026)

## Summary
Adds schema **`au_cpi_nowcast_v2`** with first-class **quarterly headline NSA QoQ/YoY** (quarter-average identity of monthly indexes) while keeping the frozen **`au_cpi_nowcast_v1`** candidate byte-replayable. Legacy quarterly trimmed-mean selection is unchanged (persistence **0.8125952260030544** % QoQ); proxy bridge remains ineligible (**1.0437709077788515** %).

**PR:** https://github.com/McCabeAI/market-watch-public-dashboard/pull/233  
**Branch head (after commits):** _filled below after commit._

## Candidates
| Schema | Directory | `nowcast.json` sha256 | Notes |
| --- | --- | --- | --- |
| v1 (frozen) | `docs/au_cpi_release/candidates/runs/2026-09-asof-2026-10-22T015000p1100-8d11c6256324` | `2cf6f2da67f2d259d3cb1cdacc9bc4b84ec95237a80c01ea8e24b46cc5edfa12` | Unchanged targets; replay exit 0 |
| v2 | `docs/au_cpi_release/candidates/runs/2026-09-asof-2026-10-22T015000p1100-8d11c6256324-v2` | _(see manifest)_ | `--reference-snapshot`; quarterly headline QoQ **1.1968092496282612** / YoY **3.8148428868771456** |

## Identity & provenance
- Archived API pull: `docs/au_cpi_release/provenance/2026-10-21T183259Z-abs-cpi-headline-quarterly/` (sha256 `bb6cbc42…`, latest **2026-Q2**; **2026-Q3** absent).
- Monthly fixture hashes unchanged; ABS website **503** on 2026-10-21 — no workbook refresh.
- v1 run `snapshot.json` + `raw/*` deduped via symlinks to the fixture (manifest hashes preserved).

## Trimmed-mean audit
Documented in `METHODOLOGY.md`: **0.81** vs **1.04** are different statistics; bridge not selected; no retuning to external consensus ranges.

## TEST RESULTS
```text
PYTHONPATH=. python3 -m unittest discover -s tests/au_cpi_release -t .
# Ran 51 tests in ~9s — OK

PYTHONPATH=. python3 -m unittest discover -s tests/core_pce_release -t .
# Ran 134 tests — OK

PYTHONPATH=. python3 -m unittest tests.canadian_cpi_release.test_nowcast
# Ran 12 tests — OK

PYTHONPATH=. python3 -m unittest discover -s tests/macro_ingestion -t .
# Ran 296 tests — FAILED (failures=2, same on origin/main):
#   test_oct20_expanded_september_idempotent_second_merge
#   test_oct20_stage_verified_lineage_succeeds
#   (tests.macro_ingestion.test_ca_score_lineage.CaInflationOct20LineageTests)

replay v1 + v2 run directories: exit 0
```

## Manual commands
See `docs/au_cpi_release/RUNBOOK.md` (`nowcast` with `--reference-snapshot`, `replay`, scorecard).

**Shadow-only.** No workflows, temperature scores, macro-ingestion catalogs, or Market Watch writes.
