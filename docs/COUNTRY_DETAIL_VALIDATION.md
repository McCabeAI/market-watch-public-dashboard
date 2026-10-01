# Country Detail validation

Status: unit-tested integration. A due or superseded release stays out of What Matters Now. Retrieval age alone does not label a latest official print stale. Direction of travel can surface without a historical-percentile breach. A short sample still cannot wear Notable or Outlier. US, CA, AU, NZ, EA, and JP each get the same release-aware review.

## What was integrated

The shared Country Detail renderer is wired into the static dashboard after the live temperature-score step.

- `scripts/country_detail/attention.py` accepts the independent-test calling convention (`country`, `score_state`, `prior_attention_snapshot`, `frozen_packet`) and still accepts `prior=` with an explicit `as_of`. `score_state` is not mutated. `frozen_packet` is not given attention keys. Omitted `as_of` uses the latest observation `retrieved_at`, or `2026-09-30`. Omitted `stale_after_days` is 4.
- Real projection rows that cannot be ranked are qualified without retuning policy thresholds. A known cadence whose periods are not in that form (CA `GDP_monthly_all_industries_v65201210`, stored as quarterly with `YYYY-MM` history) is `unknown_cadence`. A methodology-break token that is not a period (`n/a` on `EA.Consumer.confidence`) is not treated as a break.
- `scripts/apply_country_detail.py` loads `build_projection()`, temperature score state through `scripts.temperature_level.load_state` (read-only), and `stale_after_days` from `data/country_registry.json`, then calls `evaluate_projection` and `render_country_detail`. It injects `country_detail.css` once before the first `</style>`, replaces each `<div class="temp-inputs">` block inside a `cdetail` (div depth matched), and inserts the section after the opening `cdetail` tag when that block is absent. It does not import trader, PM, or freeze modules. Policy / Transmission sentences are then rewritten from `data/policy_state.json`. The page is not scraped for those rates.
- Canonical policy state lives in `data/policy_state.json`, written by `scripts/policy_state.py`. The US record is the federal funds target range parsed from the Federal Reserve monetary-policy feed, the FOMC statement, and its implementation note. A standing decision stays current until a later decision is in force. It does not expire because a fixed number of days passed. SOFR and other overnight fixings are not policy targets. CA, AU, NZ, EA, and JP stay `unavailable`: this repository collects CORRA, AONIA, Bund/€STR, the Japan overnight call fixing, and TONA futures, and the NZ registry has no policy path. Those gaps are explicit. No hard-coded current rate is substituted.
- `.github/workflows/deploy-pages.yml` runs that script on `_site/index.html` after "Apply live temperature scores", so the v8, v10, v11, and temperature-score steps still see the previous markup. The pull request path filter includes the apply script, country-detail CSS, projection, render, attention, country-detail tests, and `docs/COUNTRY_DETAIL_ATTENTION_V1.md`.
- `tests/fixtures/country_detail/review.html` is generated from the real projection and attention result for US, CA, AU, NZ, EA, and JP, plus the renderer's synthetic populated, quiet, and degraded panes. CSS is inlined, the viewport meta tag is present, and radio buttons switch the six real countries.

`data/temperature_scores.json`, `data/temperature_calibration.json`, and `data/temperature_history/` were not modified. `scripts/country_detail/policy.py` now admits direction-of-travel findings without changing score math.

## Unittest totals

```text
PYTHONPATH=. python3 -m unittest tests.test_country_detail_contract tests.test_country_detail_attention tests.test_country_detail_projection tests.test_country_detail_render tests.test_country_detail_apply -v
Ran 40 tests in the Country Detail modules, including direction-of-travel cases.
OK
```

```text
PYTHONPATH=. python3 -m unittest tests.test_temperature_scores tests.test_temperature_level tests.test_six_economy_dashboard tests.test_country_registry -v
Ran 42 tests in 0.182s
OK (skipped=1)
```

`run_acceptance_cases()` returned 0 mismatches.

A local six-country HTML fixture (not the gzip Pages payload) passed the workflow assertions: six `data-country` values US CA AU NZ EA JP, 24 `class="temp-dimension score-detail"`, 24 `50 = structural/policy neutral anchor`, What Matters Now present, the copied petrol sentence absent, and `class="wmn-quiet"` present. The full base64 Pages rebuild was not run.

## Hash check

`data/temperature_scores.json` sha256 before and after the tests and the apply fixture:

```text
be38d6d80d04843613a0b138f80636b500bd3b77e3788a1107a6a6567a072c42
```

The bytes matched.

## AU series ids

The real AU evidence pane has two separate rows:

- monthly `A130200586W`, transformation `mom_pct`
- annual `A130200588A`, transformation `yoy_pct`

Those ids are the projection values. The annual id is the parsed MHSI workbook id, not the fixture stand-in.

## Review file checks

In `tests/fixtures/country_detail/review.html`:

- The AU pane shows `A130200586W` / `mom_pct` and `A130200588A` / `yoy_pct` on separate evidence rows.
- CA AER oil rows are present. Alberta geography is explicit, and both `monthly level` and `calendar-day rate` are visible. Each of those oil histories has 3 points.
- The real EA and JP sections are not identical.
- Stored US Inflation level `63.1` is visible. Attention did not rewrite score levels.
- Real US, CA, NZ, EA, and JP panes are quiet under the source-health and pattern rules. AU surfaces direction-of-travel findings. The synthetic populated pane remains a separate renderer fixture.

## Known source gaps

- CA energy rows are tail points only (3 history points on the AER oil and gas series in this projection). That is too short for a 3-period direction run and too short for Notable or Outlier, so those rows do not clear What Matters Now.
- AU is inside its 12-day registry window. Monthly household spending `A130200586W` ends `+1.2, +1.0, +1.1` and qualifies as persistence. The sample is 12 months, so that finding does not claim a historical percentile badge. The through-the-year series is the same direction and stays a related observation. Stronger short-run patterns outrank it, so the default three cards are the composite PMI reversal, the employment reversal, and household-income acceleration. Spending is the sixth qualifying finding.
- Projection `as_of` is the newest `retrieved_at` (`2026-09-30T14:02:01Z` on the AU annual cache). That timestamp is not a retrieval TTL for other countries. A latest monthly or quarterly print stays eligible until a successor is due or a newer official observation exists. US, CA, AU, NZ, EA, and JP each receive their own review. Due/late rows stay out of What Matters Now. Explicit source stale is still a source-health block and is not inferred from elapsed days.
- One CA GDP monthly series is stored with cadence `quarterly` and month periods, so it is not ranked.
- Stale now wins over a revised or preliminary projection state. Evidence rows use the attention member's label, so the real US and JP panes show Stale. A reloaded browser check of `review.html?v=stale2` showed `Stale · 55.4` on ISM Services PMI and the US quiet sentence. The score file hash was unchanged.
