# Temperature V1 independent review — Fable Pass 1

**Reviewer:** Claude Fable 5.1, Review Pass 1 (independent, non-mutating)  
**Repository:** McCabeAI/market-watch-public-dashboard  
**PR:** https://github.com/McCabeAI/market-watch-public-dashboard/pull/66  
**Branch:** `cursor/rebase-market-watch-temperature-gauges-on-one-year-of-data-5986`  
**HEAD reviewed:** `cd6ba6e` (PR CI green: build / validate / market-state packet / overnight dry-run all SUCCESS)  
**Base:** `c39ea02`  
**Date:** 2026-09-21  
**Mutations by this pass:** none except this file. No commits.

---

## Verdict: **APPROVE-WITH-FINDINGS**

The engine, calibration and canonical state are sound: every one of the 16 LEVELs and impulses is reproduced bit-for-bit from `data/temperature_history/*.json` + `data/temperature_calibration.json` + `scripts/temperature_level.py`; 50 has an explicit, defensible economic meaning per component; impulse is separate and never accumulated; weights are unchanged and coverage renormalisation is explicit; the Trader Room reads the same v3 state as the dashboard. The cumulative-impulse index is gone from the score path.

It is **not yet production-clean**. Two BLOCKING repair packages remain, both integration/guard problems rather than methodology defects:

| # | Package | Owner | Why blocking |
|---|---------|-------|--------------|
| **B1** | Shipped dashboard still carries the *old-system narrative* inside the 16 drawers and legacy country-level WARM/COOL + direction pills that are not derived from `temperature_scores.json`; several statements directly contradict the V1 LEVEL beside them (e.g. US Inflation drawer says 3m annualized ≈2.4% while LEVEL 63.1 is computed from 3.05%; US Consumer drawer says Michigan Sep 47.8 is "SCORED … contributing −1.0 point"; 14 × "not yet lineage-pinned"). | **I2 (UI / Trader Room)** | The product shows two competing temperature/direction stories on one page. The parent objective ("dashboard + Trader Room consume the same state, no stale competing paths") is not met for the drawer bodies and country pills. CI greps only for `transition anchor` / `Reindexed`, so this ships. |
| **B2** | No test or CI step asserts that the committed `data/temperature_scores.json` equals `compute_state()` from the committed history + calibration. Demonstrated: mutate one CA unemployment observation in a scratch copy → engine says CA Labor 28.16, disk says 42.16, **all 23 temperature tests pass**, `validate_score_sources.py` passes, and the Pages build would publish 42.16. | **I1 (engine / tests)** | "LEVEL is reproducible from current observations" is the central claim of V1 and nothing enforces it. Without this guard the v3 file can silently become the same kind of stale artifact the reindex ledger was. |

Everything else is NON-BLOCKING or NON-ISSUE and is itemised below.

---

## Findings index

| ID | Class | Owner | Summary |
|----|-------|-------|---------|
| F1 | **BLOCKING** | I2 | Drawer "Hard score inputs" bodies are pre-V1 narrative and contradict V1 LEVELs (`patch_v8/*.html` → `_site/index.html`). |
| F2 | **BLOCKING** | I2 | Legacy per-country `pill`/`dir` badges (WARM/STATIC, NEUTRAL/COOLING, WARM/COOLING, COOL/WARMING) in the v6 base are hard-coded, not derived from v3 state; NZ "WARMING" contradicts 3 of 4 V1 dimensions cooling. |
| F3 | **BLOCKING** | I1 | No disk-state ≡ engine reproducibility guard in tests or `deploy-pages.yml`; stale state ships with green CI. |
| F4 | NON-BLOCKING | I2 | Trader Room `hard_inputs[].weight_contribution` is `null` for 39/39 inputs: engine emits `coverage_contribution`, loader reads `weight_contribution`; test fixture uses the loader's key so the test passes against a schema the engine never produces. |
| F5 | NON-BLOCKING | G1 | GDP LEVEL uses single-quarter q/q→SAAR at 10 pts/pp with surveys unobserved (coverage 0.60 → GDP is 100 % of the dimension). CA Activity 64.4 (warm) vs 50.1 on 2Q-average vs 44.0 on y/y; NZ 38.0 (cool) vs 52.2 vs 55.2. Arithmetically honest, but the "state" sign depends on window choice. |
| F6 | NON-BLOCKING | I1 | Engine has no staleness rule: a component that stops updating keeps full weight and its last LEVEL indefinitely (NZ Consumer income is 2026-Q1 while peers are 2026-Q2; CA retail is 2026-06). Only manual `observed:false` removes it. |
| F7 | NON-BLOCKING | I1 | `test_us_inflation_uses_three_month_core_pce_annualized` pins live data values (3.047776 / 63.1); any legitimate US Core PCE refresh or revision breaks the engine test suite. Inline fixture test checks only determinism (a == b), not the formula against a hand value. |
| F8 | NON-BLOCKING | I2 | Dimension `as_of` = cutoff `2026-09` is rendered as "from latest verified observations as of 2026-09" in the lineage note and as Trader Room `staleness: "as_of:2026-09"` for all 16 gauges, although underlying prints are 2026-07 / 2026-Q2 / 2026-Q1. |
| F9 | NON-BLOCKING | C1–C4 | `au.json` `Consumer.retail` gaps still labelled `not yet released` ×13 although the series is documented as ceased (C5 finding #5 not actioned). `Activity.business_surveys` gap reason `methodology unresolved` is not a data-availability reason. |
| F10 | NON-BLOCKING | I1/G1 | `mapped_bridge` role `provisional_impulse_metadata_only` is declared in calibration but the engine emits nothing for it; the v3 state carries no bridge metadata at all, while the drawer still describes it as receiving "a zero score impulse". Vestigial. |
| F11 | NON-BLOCKING | I1 | `deploy-pages.yml` `pull_request.paths` filter omits `scripts/temperature_level.py`, `data/temperature_calibration.json`, `data/temperature_history/**`, `tests/test_temperature_level.py`; a PR touching only those would not run the build/test job. |
| F12 | NON-BLOCKING | G1 | Dimension score docs (`LABOR_SCORE_V1.md` §"Use the existing release temperature-impulse scale", `ACTIVITY_SCORE_V1.md`, `CONSUMER_SCORE_V1.md`, `US_INFLATION_SCORE_V1.md`) still instruct the ±2/4/6 classified scale; marked "legacy note-taking" only in `DAILY_REFRESH_V0.md`. |
| F13 | NON-BLOCKING | C1–C4 | Proprietary single prints (ISM 55.4/54.6, Westpac 84.4, ANZ-RM 98.0) cite landing pages, not release URLs, and were not re-fetched by C5. They carry 40 % of US Activity and 25 % of AU/NZ Consumer. |
| N1 | NON-ISSUE | — | CA/NZ Activity ±28 impulses: not a bug; exact SAAR arithmetic on the pinned production-GDP / market-price-GDP series. |
| N2 | NON-ISSUE | — | US Activity path −39 (2025-11→12): Q3 4.4 % → Q4 0.5 % SAAR, coverage 0.6. Honest data through the formula. |
| N3 | NON-ISSUE | — | Path reconstruction admits observations by reference period, not publication date (Q4 GDP appears at 2025-12). Documented in V1 §8/§11 as latest-vintage, not real-time. |
| N4 | NON-ISSUE | — | G1 §9 said differences >0.2 need a bugfix; CA Consumer 62.1 vs "mid-50s" and AU 54.3 vs "mixed". G1's sketch never computed these; I1 arithmetic is correct from pinned anchors. |
| N5 | NON-ISSUE | — | `patch_v8/*.html` still embeds 72.0/75/69/74: overwritten at build; verified 0 occurrences of `72.0`, `75/100`, `69/100`, `74/100` in built output. |
| N6 | NON-ISSUE | — | AU Consumer.retail has one 2025-06 observation in history; `observed:false` in calibration means it is never scored. Confirmed by `component_state.retail.observed == false`. |

---

## 1. Does LEVEL represent current economic state with a defensible 50 per component?

**Yes, with one methodological caveat (F5).**

Checked every `components.*` entry in `data/temperature_calibration.json` against the V1 doc §2/§6:

| Family | Anchor | Assessment |
|---|---|---|
| Inflation | Fed 2 % on 3m-annualised core PCE; BoC/RBNZ 2 % y/y; RBA 2.5 % midpoint y/y; scale 12.5/pp (±4 pp → 1–100) | Defensible. Note US uses a run-rate transform while CA/AU/NZ use y/y; the US LEVEL is therefore structurally noisier (documented §11). |
| Unemployment | u\* 4.2 / 6.0 / 4.5 / 4.75, `hot_direction −1`, 20/pp | Defensible; within published central-bank ranges. Sign check: NZ u 5.6 → 33.0 (cool) ✓, US 4.1 → 52 ✓. |
| Wages | target + 1 pp productivity (3.0 / 3.0 / 3.5 / 3.0), 10/pp | Defensible. NZ LCI is a quality-adjusted index that historically runs ~1 pp below AHE-type measures; anchor 3.0 may bias NZ wages cold (2.0 → 40). Judgement, not defect. |
| Employment | 150k / 25k / 25k / 8k trend, `structural_trend` | Doc is honest that conviction is lower. With 2026 labour-supply growth, US 150k is arguably high (payrolls 71k 3m-avg → 34.3). Judgement. |
| GDP | potential 2.0 / 1.8 / 2.25 / 2.0 SAAR, 10/pp on latest quarter | Anchors fine; **window choice is the weak point** (F5). |
| Surveys | 50 diffusion threshold, 1:1 | Fine; only US has data. |
| Consumer flows | (target + 2 % real)/12 or /4 nominal; 2 %/12 or /4 real; scale 40 per m/m pp, 15 per q/q pp | Anchors reconcile: 0.3333, 0.1667, 0.375, 1.125, 1.0, 0.5 all recomputed ✓. |
| Confidence | Michigan 80, Westpac-MI 100, ANZ-RM 100 | Par values defensible; 47.8 unsourced Sep Michigan correctly excluded from scoring. |

No component uses a 12-month sample statistic as 50. The one-year history is used only for paths. **50 is structural, not a date.**

## 2. Is impulse separate and non-accumulating?

**Yes.** `score_component` computes `impulse = level(latest) − level(previous print)`; `aggregate_dimension` takes a coverage-weighted mean over components that have an impulse; LEVEL never references impulse. Spot arithmetic: US Consumer retail Jun–Aug mean 0.3389 → 50.22; May–Jul mean 0.237 → 46.14; impulse +4.08 ✓. NZ headline 3.1 → 4.1 y/y: +12.5 ✓. Dimension LEVELs are not `50 + Σ impulses` (US Labor 50.0 vs Σ component impulses +5.1).

Design note: components with one print (ISM, Westpac, ANZ) have `impulse: null` and are excluded from direction — so US Activity "cooling −6.0" is GDP-only even though the drawer text says ISM services rose 54.1 → 55.4. Documented in V1 §7; acceptable.

## 3. Are all 16 scores reproducible from sources + anchors + code?

**Yes.** Independent recompute in this workspace:

```text
compute_state(cal, histories, cutoff="2026-09") vs data/temperature_scores.json: 0 mismatches
  (level, impulse, direction, coverage, temperature_class, full component_state for all 16)
build_paths(...) vs data/temperature_history/score_paths.json: paths equal, pathology equal
```

Hand checks (all within rounding): US core PCE May–Jul 0.359/0.147/0.246 → 3.0478 → 63.10; CA underlying (1.9+2.0)/2 = 1.95 → 49.375; CA GDP 0.8 q/q → 3.2386 SAAR → 64.39; NZ GDP 0.2 → 0.8024 → 38.02; AU u 4.4618 → 50.76; AU MHSI May–Jul (1.2+1.0+1.1)/3 = 1.1 → 79.0.

Reproducibility from **sources**: C5 refetched the official-agency series. The proprietary single prints (F13) are reproducible from the file but not independently from a release document.

**But** reproducibility is unguarded (F3) — see §7.

## 4. History gaps: honest vs fabricated?

**Honest.** Every unobserved input is either an explicit `gaps[]` entry or `observed:false` in calibration; no `value:null`, no filled proprietary paths (C5 §4 confirmed; I re-checked the pinned-series dumps for all 45 components). Sparse rows are what they claim to be: AU Westpac has Aug m/m +6.0 and Sep m/m −5.2 alongside Sep 84.4 index level, and the engine correctly refuses to infer an Aug level.

Residual labelling defects: F9 (AU retail "not yet released" for a ceased series; AU surveys "methodology unresolved").

## 5. Dashboard + Trader Room same state? Stale competing paths?

**Same canonical numbers, yes. Competing narrative paths, yes — that is B1.**

Reproduced the full Pages build locally into `/tmp/site/index.html` (v6 base → v7 → v9 → patch_v8 → v10 → v11 → daily refresh → news sync → `apply_temperature_scores.py`). Result: 16 drawers show V1 LEVELs, 16 structural lineage notes, 1 live board, 0 `Reindexed`, 0 `transition anchor`, 0 legacy 72.0/75/69/74. Trader Room `load_temperature_gauges()` returns 16 gauges from v3 JSON with `score/impulse/direction/coverage` matching the file.

What still competes in the same built page:

- **F1 (I2)** — `_site/index.html` after patch, US Inflation drawer, "Hard score inputs": `3m annualized ≈2.4%` (and `1m annualized ≈2.4%`), while the lineage note two blocks below says `LEVEL 63.1 from latest verified observations`. 63.1 ⇒ 3.05 %. Same drawer: "Recent m/m: 0.4 → 0.3 → 0.2 → 0.3 → 0.1 → 0.2% (Feb–Jul)"; history has May 0.359. US Consumer drawer: `CONFIDENCE EVIDENCE · SCORED / SEP 2026 PRELIM / Michigan sentiment 47.8 / … Classified clearly weaker (−4) in the 25% confidence bucket, contributing −1.0 point to Consumer` — the retired classified-impulse methodology, and V1 §6 says 47.8 must not be scored (LEVEL uses Jul 55.2). Fourteen occurrences of `not yet lineage-pinned` / `still being lineage-pinned` across US/CA/AU/NZ Activity and Consumer hard-input rows, although V1 pins every series. One `must not be guessed merely to move the score` (US manufacturing surveys) although ISM 54.6 is now scored 1:1.
- **F2 (I2)** — v6 base, Macro Snapshot cards and country detail headers: `<span class="pill warm">WARM</span><span class="dir static">STATIC</span>` (US), `neutral/COOLING` (CA), `warm/COOLING` (AU), `cool/WARMING` (NZ) with a Cold–Hot `scale` bar. These are hard-coded editorial badges. V1 state: NZ Inflation warming, Labor/Activity/Consumer cooling; CA Activity +28 warming, Consumer warming (badge says COOLING); AU Activity/Consumer warming (badge says COOLING). Either derive the country pill from state (e.g. coverage-weighted mean of the four LEVELs + majority direction) or relabel it unambiguously as narrative. The Macro Snapshot's own "Core PCE run rate 3M 3.0%" agrees with V1, which makes the drawer's 2.4 % more jarring.
- **F4 (I2)** — `scripts/trader_room/evidence.py:139` reads `component.get("weight_contribution")`; `scripts/temperature_level.py:344` writes `coverage_contribution`. Live output: 39/39 `hard_inputs` have `weight_contribution: null`; the gauge payload carries no weights at all. `tests/fixtures/temperature_scores_v3_minimal.json:22` uses `weight_contribution`, so `test_trader_room_load_temperature_gauges_v3` passes against a shape the engine never emits.
- **F8** — `staleness` is `as_of:2026-09` for every gauge; the informative per-component `as_of` is only inside `hard_inputs`.

Other consumers checked: `scripts/overnight/collect.py` embeds the raw v3 dict and validates nothing schema-specific (fine); `scripts/pm/review_packets.py` only checks presence; `validate_score_sources.py` reads `components` weight map (fine). `all_scores` / Notion paths: absent. `patch_v8/README.md` and G0 doc updated at `cd6ba6e` ✓.

## 6. Pathological jumps (CA/NZ Activity ±28): bug or honest GDP?

**Honest, not a bug (N1).** CA Q1 +0.1 % → Q2 +0.8 % q/q: SAAR 0.40 → 3.24, LEVEL 36.01 → 64.39, Δ +28.38. NZ Q1 +0.9 % → Q2 +0.2 %: 3.65 → 0.80, LEVEL 66.49 → 38.02, Δ −28.46. NZ uses `SNEQ.SG01RSC01B01PC` production GDP only; expenditure rows (incl. 2025-Q2 lookback) are filtered by `series_id` and covered by `test_nz_gdp_pins_production_series_only`.

**But the design amplifies quarterly noise into the LEVEL (F5, G1).** With surveys unobserved the GDP component is 100 % of CA/AU/NZ Activity, and a single quarter's q/q at 10 pts per SAAR-pp has a natural ±20–30 pt swing. Alternative windows on the same pinned data:

| | 1Q SAAR (V1) | 2Q-avg SAAR | y/y |
|---|---:|---:|---:|
| CA Activity | **64.4 warm** | 50.1 | 44.0 |
| NZ Activity | **38.0 cool** | 52.2 | 55.2 |
| AU Activity | 43.6 | 41.6 | 48.7 |

A "current state" measure whose sign flips between warm and cool depending on a defensible window choice is a calibration weakness, not a code defect. Recommendation for G1 V1.1: score the GDP LEVEL on a 2-quarter average SAAR (or y/y), keep the 1Q print as the impulse. Ships as-is only if documented as a known limitation in V1 §11 — it currently is not.

Path scan: 9 `large_level_jump` findings, all Activity, all at GDP reference-quarter boundaries; no boundary compression; no calendar drift (cutoff 2026-09 vs 2099-12 identical; `test_level_stable_when_no_new_observations`). US Activity path is coverage 0.6 through 2026-07 and 1.0 from 2026-08 when the single ISM prints enter — a coverage discontinuity the pathology scanner does not report.

## 7. Do tests/CI guard the new meaning?

**Partially. B2 is the gap.**

What is guarded: version 3 schema; 16 dimensions in 1–100; weights sum to 1 and match registry; missing → coverage not 50; `mapped_bridge` ∉ coverage; no drift on future dummy row; NZ production GDP pinning; CA trim/median collapse; dashboard 16 drawers / 16 lineage notes / 1 live board / no `Reindexed` / no `transition anchor` / no `>Temperature Board<`; Trader Room v3 requirement.

What is not guarded:

- **F3** — No `compute_state() == load_state()` assertion, and `deploy-pages.yml:203-216` runs `--print-levels` (read-only) and never `--write-state` or a diff. Demonstration (scratch copy under `/tmp`, workspace untouched): set CA `Labor.unemployment` 2026-08 to 7.4 → engine CA Labor 28.16, disk 42.16, `unittest tests.test_temperature_history_audit tests.test_temperature_level tests.test_temperature_scores` → OK (23 tests), `validate_score_sources.py` → exit 0. The build would publish 42.16. Fix is one test plus one CI line (`python scripts/temperature_level.py --write-state` into a temp path and `cmp`, or an assertion in `tests/test_temperature_level.py`), and ideally the same for `score_paths.json`.
- **F7** — `test_us_inflation_uses_three_month_core_pce_annualized` asserts live-data constants; this will fail on the next BEA release/revision and invites "fix the test" edits rather than "regenerate state". Formula checks belong on the inline fixture (e.g. 0.1/0.2/0.3 → 2.43 % → 55.4).
- **F1/F2** — CI greps for the two retired phrases only; nothing checks that drawer bodies or country pills agree with state.
- **F4** — fixture/engine key divergence.
- **F11** — PR path filter omits engine, calibration, history and engine tests.

## 8. Any silent weight change?

**No.** `weights_changed: false`; all 16 weight maps equal the pre-PR registry (Labor 0.7/0.2/0.1, Inflation 0.6/0.4 and US 1.0, Activity 0.6/0.4 and US 0.6/0.28/0.12, Consumer 4 × 0.25). Coverage renormalisation is explicit (`coverage` on every dimension, "Coverage 60%; missing inputs omitted" in the lineage note). The economic consequence — GDP becomes 100 % of CA/AU/NZ Activity, three flows become 100 % of CA/AU Consumer — is disclosed but is exactly what makes F5 bite.

## 9. `mapped_bridge` handling

Correct at the LEVEL boundary: `unscored_components.US.Inflation.mapped_bridge.enters_level: false`; `components` = `{core_pce: 1.0}`; coverage 1.0; registry still requires ≥ 2 bridge sources (`validate_score_sources.py:50`); history retains the Jul/Aug snapshot. **F10:** the declared role `provisional_impulse_metadata_only` has no implementation — the engine emits no bridge field, so the v3 state says nothing about the bridge while the drawer still says the mapped PPI subset "receives a zero score impulse" (old vocabulary). Either emit `bridge_metadata` in state or drop the role wording and the drawer row.

## 10. Production-ready or still an operational fudge?

- **Score path (G1 + I1 + C1–C5):** production-grade. Deterministic, anchored, reproducible, documented, coverage-honest. Not a fudge.
- **Presentation (I2):** half-migrated. The numbers, bands, impulse rows, lineage notes and live board are V1; the drawer bodies and country pills are the pre-reindex prototype narrative. A reader of the US Inflation drawer today is told both "3m annualized ≈2.4%" and "LEVEL 63.1 (3.05 %)". That is a fudge by omission and must be cleaned before Pass 2.
- **Guardrails (I1):** the single most important invariant (state ≡ engine(history, calibration)) is unenforced. Until B2 lands, the v3 file is only reproducible because someone remembered to run `--write-state` on 2026-09-21.
- **Calibration judgement (G1):** the 1Q-SAAR GDP window (F5) is the one place where the LEVEL can mislead an economist about "state". Acceptable to ship only if V1 §11 says so explicitly, with a V1.1 note.

---

## Recommended repair routing (≤ 2 invocations)

**Repair 1 — I2 (UI / Trader Room), fixes F1, F2, F4, F8:**
1. Replace or regenerate the "Hard score inputs" rows in `patch_v8/{us,ca,au,nz}.html` from `component_state` (name, transform value, as-of, weight, LEVEL, impulse) so the drawer body cannot disagree with the LEVEL; delete the `SCORED … contributing −1.0 point` Michigan 47.8 row and the `not yet lineage-pinned` / `must not be guessed` text; fix the US Core PCE `≈2.4%` run-rate row (or derive it).
2. Country `pill`/`dir` badges: derive from state or relabel as editorial; add a CI grep that fails on `lineage-pinned`, `contributing −`, `SCORED`, and on any legacy `pill`/`dir` badge that does not match the state-derived class.
3. `evidence.py`: read `coverage_contribution` and include `weight`; align `tests/fixtures/temperature_scores_v3_minimal.json` with the engine output (or generate the fixture from `build_score_state`); make `staleness` use the oldest component `as_of`.

**Repair 2 — I1 (engine / tests / CI), fixes F3, F7, F11 (+ optional F6, F10):**
1. Add `test_state_on_disk_matches_engine` (full-dict equality of `build_score_state(cal, compute_state())` vs `load_state()`) and the same for `score_paths.json`.
2. In `deploy-pages.yml` "Apply live temperature scores": regenerate to a temp path and `cmp` against the committed files; extend the PR `paths` filter.
3. Move numeric formula assertions to the inline fixture; keep the live-data test as a smoke check on determinism only.
4. Optional: per-component `max_age_periods` in calibration (F6) and drop/emit the `mapped_bridge` role (F10).

**G1 (no invocation needed now):** add F5 and F6 to V1 §11 Known limitations; open V1.1 item for the GDP window.

---

## Verification log (read-only)

```text
git log: cd6ba6e (HEAD) … c39ea02 (base)                                  ✓
PYTHONPATH=. python3 -m unittest tests.test_temperature_history_audit \
  tests.test_temperature_level tests.test_temperature_scores \
  tests.test_trader_room_ondemand tests.test_trader_room_dashboard        Ran 50, OK (skipped=1)
PYTHONPATH=. python3 scripts/validate_score_sources.py                    exit 0
PYTHONPATH=. python3 scripts/validate_trader_room.py                      exit 0
compute_state() vs data/temperature_scores.json                           0 mismatches (16 dims, all component_state)
build_paths() vs data/temperature_history/score_paths.json                identical (paths + pathology)
Full Pages build reproduced to /tmp/site/index.html                       BUILD_OK; 16/16/1 guards pass;
                                                                          lineage-pinned=14, 47.8=2 (F1)
Scratch-copy mutation (CA UNRATE 2026-08 → 7.4)                           engine 28.16 vs disk 42.16; tests OK; validate OK (F3)
load_temperature_gauges()                                                 16 gauges; weight_contribution null 39/39 (F4)
gh pr view 66 statusCheckRollup                                           build/validate/market-state/overnight SUCCESS
```

No repository files other than this document were created or modified by this pass.
