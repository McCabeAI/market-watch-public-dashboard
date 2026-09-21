# Temperature V1 independent review — Fable Pass 2 (final)

**Reviewer:** Claude Fable 5.1, Review Pass 2 (independent, non-mutating; did not perform Pass 1)  
**Repository:** McCabeAI/market-watch-public-dashboard  
**PR:** https://github.com/McCabeAI/market-watch-public-dashboard/pull/66  
**Branch:** `cursor/rebase-market-watch-temperature-gauges-on-one-year-of-data-5986`  
**HEAD reviewed:** `1c32c0e` (= `origin/<branch>`; PR CI at this SHA: build / validate ×2 / Tests and live official-source smoke / market-state packet / overnight dry-run all SUCCESS)  
**Pass 1:** `docs/TEMPERATURE_FABLE_REVIEW_PASS1.md` at `cd6ba6e` — APPROVE-WITH-FINDINGS, blocking B1 (drawer narrative + country pills) and B2 (state ≡ engine guard).  
**Repairs under review:** `8c24b2c` (G1 §11 GDP-window + staleness limitations), `1c32c0e` (engine/disk guard, drawer regeneration, Trader Room weights, CI greps, pill patching).  
**Date:** 2026-09-21  
**Mutations by this pass:** none except this file. No commits. All experiments ran on `git archive` scratch copies under `/tmp`.

---

## Verdict: **APPROVE-WITH-FINDINGS**

Both Pass 1 BLOCKING packages are closed and verified against the reproduced full Pages build, not just the unit-test mini dashboard. No new production-blocking defect was found. The original mission holds: 16 LEVELs reproduce bit-for-bit from history + calibration + engine, 50 is a structural anchor, impulse is separate and non-accumulating, gaps are explicit, the dashboard and Trader Room read the same v3 state (now including weights), weights are unchanged, and no cumulative-impulse index carries economic meaning anywhere in the score path.

The remaining findings are NON-BLOCKING polish: one small logic bug in the new Trader Room staleness helper, a self-contradicting replacement note on three "SCORED" context rows, a handful of residual pre-V1 methodology-status sentences in context blocks that the new greps do not catch, and some test-hygiene items. None changes a number, a colour, a direction, or a weight shown to a reader. There is no Pass 3; these should be picked up as ordinary follow-ups.

---

## A. Pass 1 blocking items — closure verification

### B1 / F1 — drawer "Hard score inputs" narrative — **CLOSED**

Reproduced the full Pages build (v6 base → v7 → v9 → patch_v8 → v10 → v11 → daily refresh → news sync → CI "Apply live temperature scores" step verbatim, `python`→`python3`) to `/tmp/fable2/site/index.html`. BUILD_OK; all CI asserts and all five CI greps pass.

| Check (built `index.html`) | Result |
|---|---|
| `lineage-pinned` | 0 |
| `contributing` (any) | 0 |
| `must not be guessed` | 0 |
| `≈2.4%` / any `≈` | 0 in drawers (the 2 remaining `≈` are Core **CPI** ≈2.0%/≈2.6% horizon cells in the v11 macro-feed table, whose Core PCE 3M cell reads 3.0 % — consistent with V1) |
| `2.4%` | 6, all Core **CPI** y/y (context rows, feed table, news rows); none is a Core PCE run-rate claim |
| `47.8` | 1 — ISM Services *Employment* subindex in the US Activity context row (allowed) |
| `SCORED.*47.8` / `47.8.*SCORED` | 0; Michigan Sep-2026 prelim 47.8 row is removed entirely; US Consumer confidence hard input is Jul 55.2 → LEVEL 25.2 per V1 §6 |
| US Inflation hard input | `V1 scoring transform (3m ann.) 3.0478%`, `Core PCE 3.0478`, `V1 LEVEL 63.1 from transform 3.0478 (registry weight 100%; coverage contribution 100%)` |
| `DIRECT ·` hard-input rows | 39 = number of `observed:true` components in `component_state` (39) |
| `Hard score inputs` / `evidence-block context` / drawers / lineage notes | 16 / 16 / 16 / 16 |
| `Reindexed`, `transition anchor`, `>Temperature Board<`, `72.0`, `75/100`, `69/100`, `74/100` | 0 |

Read all 16 drawer bodies in plain text. Every hard-input row is generated from `component_state` (`name`, `transform_value`, `as_of`, registry weight, coverage contribution, component LEVEL, component impulse). Spot arithmetic: US retail Jun–Aug (0.3126 − 0.5367 + 1.2407)/3 = 0.3389 ✓ (context row "+1.2% m/m" is the Aug print, consistent); AU spending 1.1 → 50 + (1.1 − 0.375)·40 = 79.0 ✓; NZ unemployment 5.6 → 50 − (5.6 − 4.75)·20 = 33.0 ✓. The patcher also raises `ValueError` if any of the four stale markers or the Michigan-SCORED pattern survives, so a regression cannot ship silently.

### B1 / F2 — country pills — **CLOSED (full Pages path)**

`_patch_country_pills` is applied when the v6 `<h3>UNITED STATES</h3>` … `<div class="pills">` markup is present (i.e. the real build; the unit-test mini dashboard has no pills, see P2-5). Both locations are patched:

| Country | v6 hard-coded (pre-patch) | Built (post-patch) macro card | Built hero `<div class="big">` | State-derived check |
|---|---|---|---|---|
| US | WARM / STATIC | NEUTRAL / STATIC | NEUTRAL / STATIC | mean LEVEL 52.16 → neutral; dirs static,static,cooling,warming → static ✓ |
| CA | NEUTRAL / COOLING | NEUTRAL / WARMING | NEUTRAL / WARMING | 55.86 → neutral; static,cooling,warming,warming → warming ✓ |
| AU | WARM / COOLING | NEUTRAL / WARMING | NEUTRAL / WARMING | 52.83 → neutral; cooling,static,warming,warming → warming ✓ |
| NZ | COOL / WARMING | NEUTRAL / COOLING | NEUTRAL / COOLING | 46.81 → neutral; warming,cooling,cooling,cooling → cooling ✓ |

Derivation = unweighted mean of the four dimension LEVELs through `temperature_class`, majority direction with ties → static. The `scale` bar beneath is a static Cold–Hot legend (CSS `nth-child` colours only), so it no longer implies a position. The patcher raises if it cannot find exactly one macro `pills` block or one hero pill pair per country. The NZ "WARMING vs 3-of-4 cooling" contradiction from Pass 1 is gone.

### B2 / F3 — state ≡ engine guard — **CLOSED**

`tests/test_temperature_level.py::TemperatureLevelEngineTest::test_state_on_disk_matches_engine` exists (full equality of `level/impulse/direction/coverage/temperature_class` + `component_state{observed,as_of,transform_value,level,impulse}` for all 16, plus `paths` and `pathology` equality against `score_paths.json`). `deploy-pages.yml` regenerates both files via `write_state`/`write_paths` into `mktemp -d` and `cmp`s them byte-for-byte against the committed files before `apply_temperature_scores.py` runs. `write_state` is deterministic (`as_of`/`last_refresh_date` come from `calibration.as_of`, not the wall clock), so the scheduled daily build will not break on date alone — confirmed by `cmp` passing locally today against the committed files.

Mutation experiments on a scratch `git archive` copy:

| Experiment | Unit test | CI `cmp` state | CI `cmp` paths |
|---|---|---|---|
| A. Edit committed `temperature_scores.json` (CA Labor 42.16 → 45.0), history untouched | **FAIL** | fail | — |
| B. Pass 1 demo: CA `Labor.unemployment` 2026-08 → 7.4, disk state left stale | **FAIL** (`28.16/−16.52 != 42.16/−2.52`) — full 25-test suite now FAILED (was OK in Pass 1) | **fail** (byte 7292, line 222) | **fail** (byte 901, line 33) |
| C. Re-serialise committed state with `indent=4` (numerically identical) | OK | fail (byte-strict) | — |

Row C is the intended behaviour (only `--write-state`/`--write-paths` output is accepted) but see P2-6.

### F11 — PR path filter — **CLOSED**

`pull_request.paths` now includes `scripts/temperature_level.py`, `data/temperature_calibration.json`, `data/temperature_history/**`, `tests/test_temperature_level.py`, `tests/test_temperature_history_audit.py`.

### F4 — Trader Room weights — **CLOSED**

`load_temperature_gauges()` on live v3 state: 16 gauges, 39 `hard_inputs`, `weight` non-null 39/39, `coverage_contribution` non-null 39/39, 0 mismatches against `component_state`; `score/impulse/direction/coverage` equal the state file for all 16. Fixture `temperature_scores_v3_minimal.json` now uses the engine's keys. (New bug in the accompanying staleness change: P2-1.)

### F7 — live-data constants in engine test — **CLOSED in `test_temperature_level.py`**, re-introduced elsewhere (P2-4)

Formula assertion moved to the inline fixture (0.1/0.2/0.3 → 2.426 % → 55.33 ✓ by hand); live test is now a smoke check.

### F5 / F6 — **Documented by G1 (`8c24b2c`) in V1 §11**; not re-opened per instructions.

---

## B. Original mission — re-confirmed at `1c32c0e`

| Requirement | Evidence |
|---|---|
| 16 reproducible LEVELs | `compute_state(cal, histories, "2026-09")` ≡ disk (unit test + byte-exact `cmp`, both green locally and in PR CI) |
| Structural 50 | `baseline_meaning: structural_policy_neutral_not_reindex_date`; anchors per component in calibration; lineage note "50 = structural/policy neutral anchor" ×16 |
| Separate impulse | `impulse = level(latest) − level(prior)`; never fed back into LEVEL; dashboard renders "Cooling · impulse −28.5" separately from the LEVEL colour; single-print components (ISM, Westpac, ANZ) show `impulse n/a` |
| Honest gaps | `coverage` 0.60 / 0.75 rendered as "Coverage 60%; missing inputs omitted from LEVEL"; unobserved components produce no hard-input row (39 rows = 39 observed) |
| Same state in dashboard + Trader Room | Both read `data/temperature_scores.json`; gauges match state 16/16, hard inputs 39/39 incl. weights |
| Weights unchanged | All 16 weight maps equal the pre-PR registry (0.7/0.2/0.1; 0.6/0.4; 1.0; 0.6/0.28/0.12; 4×0.25); `validate_score_sources.py` exit 0 |
| No cumulative-impulse index as economic meaning | Score path (`temperature_level.py`, `apply_temperature_scores.py`, `evidence.py`) contains no ledger/accumulation logic; the only "reindex" strings are the guard that rejects it. Two cosmetic "indexed score" phrases survive in prose (P2-3) |

---

## C. New findings (all NON-BLOCKING)

| ID | Owner | Finding |
|----|-------|---------|
| **P2-1** | I2 | `scripts/trader_room/evidence.py::_dimension_staleness_as_of` takes `min()` of raw strings across mixed `YYYY-MM` and `YYYY-Qn` periods; `'0' < 'Q'` so any month always "wins" over any quarter. Effect on live state: NZ Consumer `staleness = as_of:2026-08` although income is 2026-Q1 (the **newest** component is reported as the staleness, the opposite of the comment's intent); US Activity → 2026-08 (GDP 2026-Q2 is older); AU Labor → 2026-07 (wages 2026-Q2 older); AU Consumer → 2026-07 (income 2026-Q2 older). 4 of 16 gauges wrong; the other 12 are correct by coincidence of cadence. Fix: order with `scripts.temperature_level.parse_period` (already exists). The dashboard is unaffected. |
| **P2-2** | I2 | `_scrub_stale_narrative` replaces any note containing "contributing" with the fixed text *"V1 corroboration only; retired classified bucket impulses are not shown."* Three affected rows keep their role label `… · SCORED` (US Retail & food services +1.2 %, AU Westpac–MI 84.4, NZ Real GDP +0.2 % q/q) and all three **are** scored V1 inputs (0.3389, 84.4, 0.8024 in the rows above). Label says SCORED, note says corroboration-only. Either drop the `· SCORED` suffix from context rows or make the note "Scored via the V1 hard input above". Cosmetic; the numbers agree. |
| **P2-3** | I2 | Residual pre-V1 methodology-status prose in context blocks not covered by the new greps: AU Activity "Domestic final demand … is a candidate for the 60% hard bucket **once the exact transformation is pinned**" (GDP is pinned and scored at 60 % two rows above); NZ Consumer "Household-income and broader spending series **still need a precise production owner before they can become the scored 25% buckets**" (income 2.1 and spending 0.1 are scored at 25 % each in the same drawer); US Inflation "does not freeze the rest of the **indexed score**" and the Sep-10 PPI release row "can affect the indexed score" (`apply_v11_refresh.py:137`); CA Inflation "under the current **V0 method**"; US Activity "Survey subcomponents route across dimensions without double counting" (V1 scores ISM headlines 1:1 in Activity only); US Inflation score-hint "current run rate **+ interim CPI/PPI bridge**" (bridge does not enter LEVEL; F10 residual). None contradicts a number; all contradict the *status* the hard-input rows assert. Recommend adding `once the exact transformation is pinned`, `precise production owner`, `indexed score`, `V0 method` to `STALE_NARRATIVE_MARKERS` and the CI grep, and editing `patch_v8/{au,nz,us,ca}.html` + `apply_v11_refresh.py` accordingly. |
| **P2-4** | I1 | Test hygiene: (a) `test_state_on_disk_matches_engine` hard-codes `cutoff="2026-09"` while `write_state` uses `cal["as_of"][:7]`; when calibration `as_of` advances the test will diverge from the artefact CI `cmp`s — pass `cutoff=None`. (b) The test compares a key slice (omits `weight`, `coverage_contribution`, `components`); acceptable because CI `cmp` is byte-exact, but the unit test alone is weaker than its name. (c) `tests/test_temperature_scores.py::test_apply_scores_real_state_us_inflation_hard_inputs` asserts the literal `"3.0478"` — the F7 pattern moved from the engine test into the dashboard test; the next BEA revision will break it until state is regenerated. |
| **P2-5** | I2 | No unit test exercises `_patch_country_pills`/`_country_pill_spans` (the mini dashboard lacks the v6 `<h3>`/`pills`/`big` markup). Only the full Pages build runs it; it raises on anchor failure, so a regression fails CI loudly rather than shipping — acceptable, but a small v6-shaped fixture test would lock the derivation rule (mean LEVEL + majority direction). |
| **P2-6** | I1/G1 | CI `cmp` is byte-strict (experiment C). Correct, but no doc tells a maintainer that after editing `data/temperature_history/*.json` or the calibration they must run `python scripts/temperature_level.py --write-state --write-paths` and commit both outputs; `DAILY_REFRESH_V0.md` §"LEVEL changes when…" and `TEMPERATURE_LEVEL_ENGINE_I1.md` should say so explicitly. |
| **P2-7** | I2 | F8 residual: the dashboard lineage note still reads "as of 2026-09" (dimension `as_of` = cutoff) on all 16 drawers while the underlying prints are 2026-06 … 2026-Q2; the Trader Room side was fixed (modulo P2-1). |

Pass 1 non-blocking items still open and unchanged: F9 (AU retail "not yet released" gap labels; AU surveys "methodology unresolved"), F10 (`mapped_bridge` role declared, nothing emitted), F12 (dimension score docs still describe ±2/4/6 scale), F13 (proprietary single prints cite landing pages). N1–N6 remain non-issues.

---

## D. Why not REJECT

The Pass 1 blockers were about (i) a reader being told two different temperature stories on one page and (ii) the central reproducibility claim being unenforced. Both are now enforced by code that fails the build: the drawer generator raises on stale markers, CI greps for them, and CI refuses to build if `temperature_scores.json` or `score_paths.json` differ by a single byte from the engine's output. The residual prose in P2-2/P2-3 is status wording in secondary "context" rows beneath authoritative, machine-generated hard-input rows and does not state a competing number, class, or direction. P2-1 is a metadata field in an internal evidence payload. None of these can cause the dashboard or the Trader Room to publish a LEVEL, colour, direction, weight, or coverage that disagrees with `data/temperature_scores.json`.

---

## Verification log (read-only)

```text
git symbolic-ref HEAD                          cursor/rebase-market-watch-temperature-gauges-on-one-year-of-data-5986
git rev-parse HEAD / origin                    1c32c0e / 1c32c0e; git status clean before writing this file
gh pr view 66 statusCheckRollup                build, validate ×2, Tests and live official-source smoke,
                                               Generate market-state packet, Overnight contracts SUCCESS; deploy SKIPPED (PR)
PYTHONPATH=. python3 -m unittest tests.test_temperature_history_audit \
  tests.test_temperature_level tests.test_temperature_scores \
  tests.test_trader_room_ondemand                                        Ran 49, OK (skipped=1)
PYTHONPATH=. python3 scripts/validate_score_sources.py                  exit 0
PYTHONPATH=. python3 scripts/validate_trader_room.py                    exit 0
Full Pages build → /tmp/fable2/site/index.html                          BUILD_OK; CMP state OK; CMP paths OK;
                                               16/16/16/1 guards; 5 CI greps pass; DIRECT rows 39 = observed 39
Drawer text dump (16 drawers)                  hard inputs all V1; 3.0478 present; ≈2.4% absent; Michigan 47.8 row absent
Country pills (macro + hero)                   patched, equal state-derived class/direction for US/CA/AU/NZ
Scratch A: edit disk state                     unit test FAIL
Scratch B: CA UNRATE 2026-08 → 7.4             unit test FAIL (28.16 vs 42.16); cmp state exit 1; cmp paths exit 1
Scratch C: reformat disk state                 unit test OK; cmp exit 1 (byte-strict)
load_temperature_gauges()                      16 gauges; weight 39/39; coverage_contribution 39/39; 0 mismatches
staleness per gauge                            4/16 wrong ordering (P2-1)
```

No repository files other than this document were created or modified by this pass.
