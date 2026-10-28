# Independent audit: Market Watch PR #259

- PR: https://github.com/McCabeAI/market-watch-public-dashboard/pull/259
- Control-plane issue: https://github.com/McCabeAI/agent-control-plane/issues/345
- Reviewer: Opus 5.5 running as the ACP parent (single provider call, iterate profile). Review only: the reviewer wrote no application, test, script, CSS or data change. This file is its only repository change.
- Reviewed head: `1215e39016d04b33bf2d77444b74cdda920d046e`. Checked at review start: branch had not advanced; base `main` still `22f6192840707a288fe0319a242f179a0c167a36`.
- Date: 2026-10-28

## Decision: PASS (accept with the residual risks below)

No material defect introduced by this PR was found in ingestion, score integrity, provenance or the new evidence UI. No repair was delegated, so no Grok 4.7 or Composer 2.5 worker ran in this review. The issues listed are pre-existing or cosmetic, and none of them block.

## Implementation provenance (from git, not from the PR body)

| Commit | Author role (PR record) | Scope |
|---|---|---|
| `01c9cba4` | earlier run | Date-keyed methodology break no longer blocks CA retail; `_PER_PRINT_FIELDS` stop template inheritance |
| `b30c8635` | stopped-run checkpoint | Evidence UI checkpoint (`indicator.py`, `render.py`, CSS) |
| `14eb096a`, `41c91baa`, `1c8e23bb` | Grok 4.7 | StatCan revision dates, stale test fixtures, release/reference/ingestion separation |
| `15b4e956`, `1215e390` | Composer 2.5 | Ingestion dates on cards, score "why it moved" sentence |

`git diff 22f61928..1215e390 -- data/` is empty. No committed score, history, calibration or market book changed.

## Evidence checked

| Check | Result |
|---|---|
| PR test command (`pytest tests/macro_ingestion tests/test_country_detail_indicator.py tests/test_score_dates.py tests/test_country_detail_render.py tests/test_country_detail_release_review.py tests/test_mw_publication_release.py tests/test_mw_research_pages.py tests/test_dashboard_repair.py`) rerun by reviewer at `1215e390` | **456 passed, 37 subtests passed**, 0 failed. The PR body says 457; I could not reproduce a 457th test. |
| The two changed expectations, run on `main` | Both **fail on main** (`test_au_underlying_store_updates_score_path`, `test_september_ingestion_cutoff_changes_ca_jp_inflation`: `52.5 != 51.5`). |
| CI on `1215e390` | `build` pass (16m37s), `Validate macro ingestion and temperature suites` pass (311 + 154 unittest tests; includes `tests/macro_ingestion` discover, so the new CA retail tests ran), `Market Watch launch unit tests` pass (224). Deploy and launch jobs skipped. |
| Rendered site | Reviewer downloaded CI artifact `github-pages-1` from run 40709469212 (final edition, `mwl-20261028T092641Z-4c970004`, trigger `refresh`) and drove it in headless Chrome at 390x844 and 1280x900. |

## Findings by area

### 1. CA retail freshness and revisions: correct

- Root cause confirmed. `data/temperature_history/ca.json` `Consumer.retail.methodology_breaks` holds `{"date": "2023-03-24"}` with no `period`. On main, `_methodology_blocks` treated that as unusable and blocked every print. `scripts/macro_ingestion/canonical_bridge.py` `_break_period` now maps an ISO date to its month or quarter. Breaks with no period or date, and non-ISO dates (US ISM), still fail closed (`MethodologyBreakKeyTests`).
- Math checked against the committed WDS fixture `tests/macro_ingestion/fixtures/ca/wds_retail_v1446859483_20261028.json`. Jul = 73,684,586 / 74,289,929 − 1 = −0.815%. Aug = 74,567,349 / 73,684,586 − 1 = +1.198%. `_mom_pct_series_from_levels` skips non-consecutive months.
- Release dates are not falsified. Only the newest fetched month (Aug) gets `release_date` 2026-10-23, the WDS `releaseTime`. Earlier months get `revision_status: revised`, `release_date: None` and `latest_release_vintage`. `_append_row` also drops `release_date` for revised points. July therefore shows "no recorded release date" instead of the Aug publication day.
- Revisions versus first publish: already-scored Apr–Jun revisions are skipped (forward-only rule `rewrite_forward_only=True` in `scripts/run_state/identity.py`, gate fixed at merge start), so frozen June stays 0.60 / 2026-08-21. `test_july_and_august_merge_and_only_ca_consumer_moves` proves only CA Consumer moves. `test_committed_scores_reproduce_from_committed_history` proves committed scores still reproduce.
- As-of: CA Consumer will move from retail June to August only at the next ingestion. The live page truthfully says "Retail through Jun 2026".

### 2. Score integrity, scored versus context, contributions: correct

- `indicator.score_class` marks a card "scored" only when the stored component is observed with positive weight. Catalog role alone is not enough.
- `score_windows` shows the period window only when replaying the calibrated transform reproduces the stored `transform_value` within 1e-4. Stored scores are never replaced.
- `contribution_sum_text` prints nothing if the parts miss the stored level by more than 0.06.
- Spot reconciliations on the CI page all match `data/temperature_scores.json`:
  - CA Consumer: 62.12 = 50 + 5.02 + 5.60 + 1.50 (coverage 75%, confidence left out and stated).
  - CA Consumer impulse: (−4.40 + 15.00 + 3.00) / 3 = +4.53.
  - CA Activity impulse: 0.6 × 28.38 + 0.4 × 0.90 = +17.39.
  - CA retail "Score uses +0.71%: average Apr–Jun +0.47, +1.06, +0.60".

### 3. History and release-date provenance: correct, with a safe display guard

- `indicator.credible_release_dates` shows a committed release date only if it falls after the period ends and within 120 days, and only on the newest period sharing that day. This hides real defects in committed history (see residual 3). Examples: CA CPI Sep 2026 is stored as released 2026-09-14; CA retail Jan–May share later vintage days; AU underlying Sep 2026 is stored as released 2026-08-27. All render as "no recorded release date" instead of a false date.
- Release, reference period and ingestion are separate columns. A missing release date is never filled from ingestion.
- `projection._primary_series_rows` changes one What Matters Now card versus main. NZ `Activity.gdp_domestic_demand` now shows its own series `SNEQ.SG01RSC01B01PC` (Q2 2026 0.2) instead of the companion `SNEQ.SG02RSC31B15PC` (0.4) that won "last row". This is a correction; the card says one other series is stored.

### 4. WMN release cards, score labels, six economies, phone and desktop: pass

- CI page: all six panes render 3 WMN cards and 4 score dimensions (Inflation, Labor, Activity, Consumer), each with LEVEL, IMPULSE and "inputs through". No horizontal overflow at 390px or 1280px.
- Each card shows the headline in plain English, current versus prior, three dated prints, the reason (acceleration, persistence, reversal), "Feeds the Consumer score · +5.02 points" or "Context only", and a collapsed history, source and limits section.
- Selection matches main for US, CA, AU, EA and JP.

### 5. The two changed test expectations: legitimate stale-test fixes

- `tests/test_score_dates.py`: JP Inflation level 51.5 → 52.5 matches `data/temperature_scores.json`. It moved in accepted launch finalize `3b111e65` (Oct 26), not in this PR.
- `tests/macro_ingestion/test_catalog_key.py`: AU underlying is committed through 2026-09, so a 2026-08 "forward" fixture is no longer forward. Moving the fixture to 2026-10 restores the test's intent. Both tests fail on main.

### 6. Country pill: real bug, pre-existing, not introduced by this PR

- With Canada selected, only `#c-ca` is checked and only `.cdetail.ca` is visible. The pane and the radio state agree; the scoreboard jump script also sets the radio.
- The selected pill looks *unselected*. The base rule `#c-ca:checked~.app label[for=c-ca]{background:var(--navy)}` resolves to `--navy: #0d141c`, the dark-theme page background. The selected pill (`rgb(13,20,28)`) is therefore darker and borderless, while unselected pills keep the lighter bordered panel style (`rgb(22,32,43)`). The pane has no visible country heading, so on a phone the selected country is hard to tell.
- This PR does not touch that CSS. Screenshot: `review_mobile390_country_pills.png`.

## Residual risks (non-blocking)

1. **Pill selected state (Medium UX, pre-existing).** Fix in `scripts/dashboard_repair/apply.py` dark-theme CSS: give `#c-XX:checked~.app label[for=c-XX]` a distinct accent background and border (for example `var(--mw-accent)` with dark text) or `aria-current` styling, and add a visible country name to the pane header. Follow-up PR.
2. **Ivey labelled as "Composite PMI output" (Medium, pre-existing).** Canada's top WMN card reads "Composite PMI output was 64.3 in Aug 2026" (`Ivey_PMI_conflict`, source Ivey). Further down the same pane, S&P Global `SP_GLOBAL_CA_COMPOSITE` is also titled "Composite PMI output" with Aug at 47.8. A trader sees two conflicting "composite PMI" readings. The name comes from the committed history label "S&P Global Canada Composite PMI Output Index (Ivey PMI conflict-only)"; main renders the same card. Fixing it means correcting the catalog or history label, which is outside this review's no-history-edit remit.
3. **Committed release dates are unreliable (pre-existing data).** Several committed rows carry vintage or template dates (examples in finding 3). The display guard hides them, but they remain in `data/temperature_history/*.json`. Any non-UI consumer of `release_date` should apply the same plausibility rule. The `_PER_PRINT_FIELDS` change stops new rows from inheriting dates.
4. **Mixed vintage in the CA retail 3-month window.** After the next ingestion, the window will be Jun at first vintage (0.60) plus Jul and Aug computed from StatCan's revised June level. This is intended by the forward-only rule, but it is not a single-vintage average.
5. **Stale gap notes.** `Consumer.retail.gaps` still lists 2026-07 and 2026-08 as "not yet released" (as of 2026-09-21). The merge does not clear gaps.
6. **CI coverage gap.** No workflow runs `tests/test_country_detail_indicator.py`, `tests/test_country_detail_render.py`, `tests/test_country_detail_release_review.py` or `tests/test_score_dates.py`. They pass locally (above) but are unguarded in CI.
7. **Number formatting (Low, cosmetic).** `present.format_macro_value` prints whole numbers of 10,000 or more without units but non-integers with two decimals and units. The new print strip and history table show "452,039" next to "464110.40 cubic metres" (Alberta condensate).
8. **Research edition.** Not independently rendered by the reviewer. It is covered by `test_research_banner_is_one_line_with_detail_collapsed` (passed) and the worker's screenshot. Final-edition byte reproducibility depends on the live clock and `--fetch-schedules`, as the PR states.

## Reviewer screenshots (CI artifact, headless Chrome)

- `review_mobile390_country_pills.png`, `review_mobile390_ca_wmn_cards.png`, `review_mobile390_ca_consumer_dropdown.png`, `review_mobile390_ca_remaining_evidence.png`
- `review_desktop1280_*` equivalents

## Not done, by constraint

No merge, deploy, publish, Trader Room run, score recalibration, or history or book edit. No ACP, hook or workflow change. No subagent launched.
