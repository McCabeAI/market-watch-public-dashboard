# Country Detail Attention V1

Status: **ACTIVE**

This is the frozen contract for the shared Country Detail experience of US, CA, AU, NZ, EA, and JP. The percentile bands, sample minima, and reprint tolerances below were frozen before implementation. They were not fit to current prints. Do not retune them from `data/temperature_history/` or from the latest observation in a live feed.

Executable constants and pure helpers: `scripts/country_detail/policy.py`.
Synthetic oracle: `tests/fixtures/country_detail/acceptance_matrix.json`.
That matrix uses invented series and round rank-carrier numbers. It is not a copy of production prints.

Percentiles describe the historical distribution of comparable observations only. They are not predictive probabilities and do not imply mean reversion.

## 1. Hierarchy

The page order is fixed:

1. A compact four-score block (Inflation, Labor, Activity, Consumer) with level and impulse text.
2. What Matters Now.
3. Searchable, topic-organized Country Evidence.
4. Score and methodology drill-down.

Calibrated 1–100 scores stay available and visually subordinate. Attention does not rewrite them.

Three axes stay separate:

| Axis | Values | Meaning |
|---|---|---|
| `score_role` | `scored`, `context`, `unscored` | Whether the series is allowed to move a calibrated score. Weight may be 0. |
| `attention_status` | `none`, `notable`, `outlier` | How unusual the latest comparable point is. Ordinary rows have no badge. |
| `economic_direction` | score impulse only | Direction stays on the score. Attention color must not imply bullish, bearish, hot, or cold. |

An unscored or context series with weight 0 may lead What Matters Now. That lead must not change any calibrated score, score weight, impulse, or Trader Room evidence.

## 2. Percentile

Inclusive nearest-rank, deterministic, ties use midrank. The latest point is inside the sample.

`percentile = (r - 0.5) / n * 100`, where `n` is the comparable sample size, `x` is the latest comparable value inside that sample, and `r = 1 + count(values < x) + 0.5 * count(values == x)`.

Equality in this formula is exact source equality. The reprint tolerance in section 5 is a different comparison and must not be used to decide ranks. `scripts.country_detail.policy.inclusive_midrank_percentile` is the reference implementation.

For a sample of unique values, this is `100 * k / n`, where `k` is 1 when `x` is the minimum and `n` when `x` is the maximum.

## 3. Bands and sample size

Apply bands only after eligibility. Inequalities are strict. A percentile of exactly 5, 95, 1, or 99 is not a breach of that edge.

- `notable` when percentile < 5 or percentile > 95.
- `outlier` when percentile < 1 or percentile > 99.
- otherwise `attention_status = none`.

Outlier is a subset of the notable region. If both match, the status is `outlier`.

`OUTLIER` in policy is the pair `(1, 99)`, not the quotient `1/99`.

Comparable observations only:

| Cadence | Notable minimum `n` | Outlier minimum `n` |
|---|---|---|
| monthly | 36 | 60 |
| quarterly | 16 | 24 |
| other or unknown | ineligible | ineligible |

- If `n` is below the notable minimum, status is `none` and ineligibility includes `insufficient_history`. A short history never receives an Outlier badge, even when the inclusive percentile would be 100.
- If `n` meets the notable minimum but not the outlier minimum, and the percentile is outside 1/99, status is `notable` (not `outlier`) and ineligibility includes `insufficient_history_for_outlier`.
- Unknown cadence: status `none`, ineligibility `unknown_cadence`. No badge.

`seasonal_adjustment is False` uses a different short-history reason. See section 4.

## 4. Comparability

A comparable sample is one series identity: same `series_id`, transformation, geography, seasonal-adjustment flag, units, and currency or real/nominal basis (`nominal_basis`).

Do not splice across methodology breaks. A break boundary is the first period of a new regime and is inclusive. Observations strictly before the latest break that is at or before the latest period are not in the sample. Record that omission as `excluded_count`. If the latest point itself sits on a broken comparison (`comparison_broken`), status is `none`, data state is `structurally_non_comparable`, and ineligibility is `structurally_non_comparable`.

`seasonal_adjustment is False`: the comparable sample is the same calendar month (monthly) or the same quarter (quarterly) only. Do not compare January with July. If that seasonal-peer sample is below the notable minimum, status is `none` and ineligibility is `seasonal_history_insufficient` (not `insufficient_history`). `seasonal_adjustment is null` does not trigger the same-period filter.

`calendar_day_rate` is a transformation. It is not seasonal adjustment. Canadian `monthly_level` and `calendar_day_rate` are different observation identities and are never ranked as one series, even when they share a `series_id`. Alberta geography is `AB`. The country remains `CA`. Do not label an Alberta row as CA national.

Resolve vintages before ranking. The sample contains one value per `reference_period`: the current vintage. Do not rank a prior vintage beside the current one.

## 5. Materiality and freshness

A percentile breach is necessary and not sufficient. Eligible series whose percentile is inside the closed interval [5, 95] have status `none` and ineligibility `not_material`. There is no extra numeric materiality cutoff.

Unchanged reprint: if value, reference period, transformation, and revision status match the prior persisted attention snapshot for that observation id, do not create a fresh alert. The finding may remain visible with `alert_freshness=unchanged`. It must not be duplicated and must not sort above a genuinely new or revised qualifying finding. Vintage is not part of the unchanged match. A vintage change without a value change stays unchanged.

Value tolerance, applied with decimal conversion of the source numbers (`Decimal(str(value))`), not binary float dust:

- Percent-like units (`percent`, a string starting with `percent `, `%`, or `pct`): absolute difference < 0.05.
- Other units: relative difference < 0.001 (0.1%) against `abs(previous)`.
- Zero previous value: absolute difference < 1e-9.

Revised: `revision_status` in `{revised, preliminary}`, or a vintage change together with a value change, is data state `revised` and may qualify as fresh (`alert_freshness=revised`). A value change that is not an unchanged reprint and not a revised data state is `alert_freshness=new`.

Missing, stale, revised, structurally non-comparable, and failed fetch are distinct data states. Display labels:

| Data state | Text |
|---|---|
| `missing` | Missing |
| `stale` | Stale |
| `revised` | Revised |
| `structurally_non_comparable` | Not comparable |
| `failed_fetch` | Source failed |

`failed_fetch` must not advance `retrieved_at` or `observed_at`. The timestamp stays at the last successful observation. Source failed must not show a newer timestamp.

Stale uses whole UTC calendar days from the last successful `retrieved_at` to the evaluation `as_of`, and only when that age is strictly greater than the country's `stale_after_days` in `data/country_registry.json`. Do not invent a second table of day counts. Policy does not read the registry; the caller passes the registry value. An otherwise extreme stale row has status `none`, ineligibility `stale`, and no Outlier badge.

Ineligibility reasons, and no others:

`insufficient_history`, `insufficient_history_for_outlier`, `seasonal_history_insufficient`, `structurally_non_comparable`, `missing_value`, `stale`, `failed_fetch`, `unchanged_reprint`, `not_material`, `correlated_companion`, `unknown_cadence`.

Classification priority when several could apply: missing, failed fetch, structurally non-comparable, stale, unknown cadence, seasonal history, insufficient history, then the bands.

## 6. What Matters Now

Show 0 to 3 findings initially (`MAX_FINDINGS_INITIAL = 3`). The architecture allows expansion to 5 (`MAX_FINDINGS_EXPANDED = 5`). There is no forced quota. A quiet country shows zero findings and `p.wmn-quiet` with the text `No finding clears the attention rules.` Do not pad.

One release or theme occupies at most one slot. The correlation key is `(country, topic, release_family, reference_period)`. `release_family` is a stable id for series published together. Examples, not a closed catalog: `au_mhsi_total`, `au_cpi` (headline and trimmed mean), `aer_st3_oil` (Alberta oil rows from one AER workbook).

Within a group, keep the stronger status (`outlier` over `notable` over `none`). Tie-break: larger distance outside the nearest band edge already crossed (99 or 1 if the point is in the outlier region, otherwise 95 or 5). That prefers the qualifying transform over a companion that did not qualify. If status and distance still tie, the lexicographically smaller `observation_id` wins.

Companions stay on the surviving finding as `related_observation_ids`. They do not get a slot, and their ineligibility includes `correlated_companion`. Their own attention status remains available to Country Evidence. A group whose strongest member has status `none` produces no finding.

After dedup, sort findings by freshness (`new`, then `revised`, then `unchanged`), then by status and extremity. Unchanged reprints sort after new and revised findings. Dedup runs before that freshness sort: a fresh companion in the same release does not open a second slot.

The headline is the transformation that qualified. If AU household spending through-the-year percent is the qualifying signal, the card headline is that annual measure. The monthly percent change may appear only as a related observation. Display text may format the source value. The stored number remains the observation's source value.

## 7. Observation identity

The same id and the same numeric value are shared when an observation appears in What Matters Now, Country Evidence, and a score audit. Do not copy the number into a second stored field that can drift. Score audit references `observation_id` only. `headline_text` is display formatting derived from that single value.

`observation_id` is the lowercase hex SHA-256 of a canonical JSON object: sorted keys, no whitespace, `ensure_ascii`, UTF-8. The object contains exactly:

`country`, `series_id`, `reference_period`, `transformation`, `geography`, `seasonal_adjustment` (`true`, `false`, or `null`), `units`, `nominal_basis` (`nominal`, `real`, `physical`, `index`, `balance`, or `unknown`).

Country codes are `US`, `CA`, `AU`, `NZ`, `EA`, `JP`. National geography uses that same code. Alberta uses `AB`. `series_id` is required and non-empty. Extra keys are not hashed. Value, weight, and vintage are not part of the id.

Worked synthetic identity (no production value is hashed):

```text
{"country":"CA","geography":"AB","nominal_basis":"physical","reference_period":"2024-01","seasonal_adjustment":false,"series_id":"AER_ST3_OIL_TOTAL_PRODUCTION_M3","transformation":"calendar_day_rate","units":"cubic metres per calendar day"}
db39eda0756f780a58bad21b4efb912cfaa21c41c3812136500d947b6c5a9ac0
```

## 8. Topics

Stable ids: `inflation`, `labor`, `activity`, `consumer`, `housing`, `energy_physical`, `rates_fx`, `external`, `other`.

| Signal | Topic |
|---|---|
| Score dimension Inflation, Labor, Activity, Consumer | `inflation`, `labor`, `activity`, `consumer` |
| Physical production, including Alberta oil and gas cubic metres (`nominal_basis=physical`) | `energy_physical` |
| Real manufacturing, wholesale, and building volume indexes | `activity` |
| Retail volume | `consumer` |
| Housing series | `housing` |
| Rates, yields, FX | `rates_fx` |
| Merchandise trade, including `CA.Activity.crude_export_volume` | `external` |
| Anything else | `other` |

A catalog id prefix is not a topic. `CA.Activity` volume indexes that are not physical production are not `energy_physical`. Physical production is `energy_physical` even if a catalog id looks like activity.

## 9. AU household spending

Two observation identities, both structured and sourced. Never collapse them, and never build the annual measure by compounding monthly percent changes.

Monthly, from catalog `AU.Consumer.spending`:

- `series_id` `A130200586W`
- transformation `mom_pct`
- `seasonal_adjustment` true
- geography `AU`
- units `percent`
- `nominal_basis` `nominal`
- `score_role` `scored`
- weight `0.25` on this transform only
- topic `consumer`
- release family `au_mhsi_total`

Annual: the ABS through-the-year / corresponding-month-of-previous-year percent on the seasonally adjusted total in the same MHSI workbook family.

- `series_id` is required and is **not** assigned in this contract. Parse it from the official workbook column. `AU_HOUSEHOLD_SPENDING_ANNUAL["series_id"]` is `None` on purpose.
- transformation `yoy_pct`
- `seasonal_adjustment` true for that SA total column
- its own `source_url`, `reference_period`, units, vintage, and `series_id`
- `score_role` `unscored`, weight `0`
- same release family `au_mhsi_total`

If that workbook column is absent, `data_state=missing` with a limitation reason. Do not fabricate the series or the value. The acceptance fixture id `FIXTURE_MHSI_TTY_NOT_AN_ABS_ID` is a stand-in so the matrix can hash an identity. Do not write it into the catalog. The +7.0% year-over-year figure in the product brief is an illustration of headline promotion, not a value to store.

## 10. Data states and the score patcher

Country Evidence and, when a row also qualifies, What Matters Now show the display label from section 5. A revised row can carry both the label `Revised` and a `Notable` or `Outlier` badge. Those are different axes. Badge text is exactly `Notable` or `Outlier`, and only when the status is that value. Status `none` renders no badge.

The score drill-down stays compatible with `scripts/apply_temperature_scores.py`:

- `details` class attribute exactly `temp-dimension score-detail`
- hard-score block titled `Hard score inputs`
- context block class `evidence-block context`
- lineage note containing `50 = structural/policy neutral anchor`

## 11. Renderer hooks

`render_country_detail(country_code, projection, attention, score_state)` returns an HTML string. This contract does not implement it. Required hooks:

- `section.country-detail[data-country]`
- `.score-compact` with four buttons or summaries (Inflation, Labor, Activity, Consumer), level and impulse, visually compact
- `section.what-matters-now` with `ol.wmn-list`, or `p.wmn-quiet` when there are zero findings
- each finding `article.wmn-finding[data-observation-id][data-attention]`
- `.wmn-reason` is the deterministic reason from policy
- `.wmn-headline` is the qualifying transformation's label and value
- `section.country-evidence` with `input[type=search]`, topic controls (buttons or a select) using the topic ids, and evidence articles that reuse `data-observation-id` when the same observation is a finding
- `details.score-detail.temp-dimension` as specified in section 10
- no horizontal overflow
- keyboard use is native `button`, `summary`, `input`, and `a[href]`
- attention badges do not use temperature classes `hot`, `warm`, `cold`, or `cool`

EA and JP each use their own narrative text. Do not reuse US, CA, AU, NZ, or each other's sentences.

## 12. Trader Room firewall

Presentation and attention output must never be imported by:

- `scripts/trader_room/`
- `scripts/trading/`
- `scripts/pm/`
- `scripts/market_watch_launch/freeze.py`

Attention ranks and research narratives must not appear in frozen trader packets. Holding source data constant, this work must not change calibrated scores, score methodology, packet contents, or packet hashes. The acceptance case `score_firewall` includes a fake packet hash and expects attention output to be absent from that packet.

## 13. Module layout

| Path | Owner |
|---|---|
| `scripts/country_detail/policy.py` | this contract |
| `scripts/country_detail/__init__.py` | re-exports policy constants only |
| `scripts/country_detail/projection.py` | data worker |
| `scripts/country_detail/attention.py` | attention worker |
| `scripts/country_detail/render.py` | UI worker |
| `tests/fixtures/country_detail/acceptance_matrix.json` | this contract |
| `docs/COUNTRY_DETAIL_ATTENTION_V1.md` | this contract |

Projection, attention, and render are not part of this change. Call the policy helpers instead of re-deriving bands, ids, or tie-breaks.

## 14. Acceptance matrix

`tests/fixtures/country_detail/acceptance_matrix.json` is the oracle. Compare percentiles with absolute tolerance `1e-9`. Cases:

1. `unscored_zero_weight_leads` — weight 0 physical series, monthly SA, n=60, percentile 100, leads. Scored series percentile 50 does not. Score levels stay at the fixture numbers.
2. `au_spending_headline` — monthly inside the band, annual percentile `100 * 59 / 60` (notable, not outlier), one slot, annual headline, monthly id related.
3. `extreme_vs_nonextreme_vs_short` — statuses `outlier`, `none`, `none`. The n=10 series is `insufficient_history` and must not say `Outlier`.
4. `ca_daily_vs_monthly_and_alberta` — distinct ids, only the calendar-day rate qualifies, geography `AB`, `sa=false`, eight same-month peers are `seasonal_history_insufficient`.
5. `quiet_country` — findings empty.
6. `dedup_and_unchanged` — one CPI slot; a within-tolerance reprint is `unchanged` and sorts after a new finding.
7. `data_states` — Missing, Stale, Revised, Not comparable, Source failed. Failed fetch keeps `2024-05-01T00:00:00Z`. A break at `2015-01` excludes 10 older points.
8. `score_firewall` — attention stays out of the fake frozen packet.

`boundary_probes` locks the strict edges (exactly 5, 95, 1, and 99), the monthly 35/36 and quarterly 15/16/24 sample cutoffs, and unknown cadence.

## 15. Choices frozen with this contract

- Exactly 5, 95, 1, and 99 are not breaches.
- `seasonal_adjustment is null` does not use same-month peers. Only explicit `false` does.
- `not_material` means the sample is eligible and the percentile is not strictly outside 5/95.
- Unchanged reprints do not require the vintage to match. A vintage change without a value change stays unchanged.
- A value move that is neither an unchanged reprint nor a revised data state is freshness `new`.
- Within a release, status and extremity choose the slot before freshness does. Across findings, freshness sorts first and unchanged is last.
- Equal status and equal band distance: smaller `observation_id` wins.
- Stale age is whole UTC days and uses a strict greater-than against the registry count.
- Percent-like units are `percent`, `%`, `pct`, or a string starting with `percent `.
- Zero baseline means the previous value is exactly zero.
- Band distance uses the tightest edge already crossed (1/99 in the outlier region, otherwise 5/95).
- `CA.Activity.crude_export_volume` is topic `external`.
- The annual MHSI `series_id` is parsed from the workbook. This contract does not invent an ABS id.
