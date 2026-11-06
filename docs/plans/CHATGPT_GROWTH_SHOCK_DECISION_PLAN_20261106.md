# ChatGPT PM growth-shock decision plan — 6 November 2026

**Status:** Plan only. This run does not underwrite trades, does not calculate a decision sheet, and does not write the research artifact.

**Repository:** `McCabeAI/market-watch-public-dashboard`

**Planning HEAD:** `7b659a3821ff66797fd548e3f9754eb7350264c4` (same as `origin/main` at planning time)

**Control-plane issue:** https://github.com/McCabeAI/agent-control-plane/issues/400

**Authorized scope:** Kevin authorized the existing ChatGPT discretionary PM to run the 6 November research below, with Grok 4.7 and Composer 2.5 only. This document is the execution specification for that research. It is not a new trader, not a repair, and not permission to change books, ledgers, hypotheses, or site code.

A later execution that is separately authorized would produce:

- `docs/research/chatgpt/2026-11-06-growth-shock-decision-review.md`
- support files only under `docs/research/chatgpt/2026-11-06-growth-shock-decision/`

This plan does not create those paths.

## 1. Question and decision standard

**Research question.** Is the AI/credit selloff creating a sustained growth trade, or an opportunity to fade an overreaction?

**Standard.** Practical decisions under uncertainty. An entry does not require statistical proof or a confirmation gate. Missing evidence narrows the conclusion and the size. It is not permission to retrieve, invent a release, invent a consensus, or manufacture a probability, a fair value, or an expected value.

**Required narrative order in the research note.**

1. Current owned book, first.
2. Whole-market reading.
3. Reconciliation of owned-trade behavior with data, news, and the whole market.
4. Alternatives, then recommended actions.
5. Limitations and a proposed decision sheet. The sheet is research, not an order.

The daily sequence is the same: evaluate the owned book, read the whole market, interpret the owned trades in that context, and only then consider exits, adds, and new trades. Do not open on the cross-market menu, and do not stop after the book.

From-flat and already-owned positions face the same forward test. Prior profit is not a reason to keep risk. A 2.75 neutral proxy is not a defended Bank of Canada forecast. The prior central 2027 path 2.90 / 2.98 / 3.05 / 3.10 was not established as fair value. Carry does not determine spot. A futures price is a priced period path, not automatic cheapness, not carry profit, and not an exact hike count. Front December SR3 is not a two-year-risk substitute.

## 2. What this plan already checked

Planning inspection was read-only, on the working tree at `7b659a3821ff66797fd548e3f9754eb7350264c4`, plus `git show` of the named input commit. The executing run must repeat these checks and stop on a mismatch. Do not treat this section as a substitute for that re-verification.

### 2.1 Content binding

| Claim | Planning result |
| --- | --- |
| Evidence snapshot path | `data/overnight/runs/overnight-20261106/reviews/review-001/evidence_snapshot.json` |
| Git blob | `d875ddc64fab7258cbcf72c6b4a7df0a4ec64d33` at input commit `680297f3898081789794d20b765a5c908b6b93fe` and at planning HEAD |
| Embedded base packet SHA256 | `57cbe09b78e90e4d87a1fc08764ce3f0983ef627fa58c168f36bd2db09081ac8` in `packet_sha256`, and the same value as `base_packet_sha256` on the agent packet and on `scheduled_output.json` |
| Raw file SHA256 of the snapshot JSON | `e7fc28a6109a744129133d55e3a789ce950d4373d01f6c12aef30660a5d08931` |
| Agent packet path | `data/overnight/runs/overnight-20261106/reviews/review-001/agent_evidence_packet.json` |
| Embedded agent packet hash | `packet_sha256` = `2e2b6a923502895d6478c0d4c3ca5aea94fb9ca9e46b5ca07b540a615e8f879c` |
| Agent packet git blob / raw file SHA256 | blob `72ded24c2ae62faabe3d8ae864c49297ec8728fc`; file SHA256 `4b0af5690bd5f09c12335abeb6e25487fabaf7602673c31b6d5b0fae56b6a9cc` |
| Scheduled output | Git blob `6bec37cfa0e24e4e638d58a1b7aaf779d76339f8` at both `data/overnight/runs/overnight-20261106/reviews/review-001/scheduled_output.json` and `data/overnight/inbox/overnight-20261106/scheduled_output.json` |
| Scheduled-output delivery commit named in the job | `f0cadc27229365e20ad9484fbb1eb8409de794d3` is **not** in this clone |
| Commit that puts that blob on the reviews path | `6f2f00f5d6f8b81cee751b3ffaa30e525309c67b` |
| Freeze label | `as_of` and `collect_as_of` `2026-11-06T06:25:49.281876-05:00`. Agent packet `base_evidence_cutoff` and `evidence_cutoff` match. News family `as_of` matches. |
| Later internal market generation | `families.market_state.as_of` and `families.market_state.data.generated_at` are `2026-11-06T11:42:41Z` |
| Own research hash at the input commit | `data/trading/pm/chatgpt/research/index.json` `research_sha256` = `2379d1a520b69dc85bfc2a017073b5aa5ae286dd6d507c87e45502503803c627`, `as_of` `2026-11-05T09:08:48.262750-05:00` |
| Research index and lessons blobs | Identical at the input commit and at planning HEAD |
| Canonical PM book blob | **Different.** Input `3bb1cfa3ae7259b263f094f9cd072ef316b95fff`. Planning HEAD `f52d0682ceb06f253c2a80216e97bfd42b0c28d8`. |

The base-packet hash is the embedded `packet_sha256`. It is not the raw SHA256 of `evidence_snapshot.json`, and it is not the git blob id. The agent packet hash is the embedded field, not the file hash and not the git blob. Record all three layers so a later reader can see which binding was checked.

`f0cadc27229365e20ad9484fbb1eb8409de794d3` cannot be confirmed here. Do not fetch to hunt it. The scheduled-output blob on planning HEAD matches the named blob, and `base_packet_sha256` inside it matches the frozen packet. State that limitation in the research note.

### 2.2 Clocks that must stay distinct

- Freeze / evidence cutoff: `2026-11-06T06:25:49.281876-05:00`.
- Market-state generation: `2026-11-06T11:42:41Z`. This is later than the freeze label. Do not claim a market-state field was knowable at 06:25 simply because the snapshot file carries the earlier label.
- Score inputs `score_inputs_last_ingested_at`: `2026-11-06T11:25:49Z`. Another clock. Do not collapse it into either of the two above.
- Central-bank research family `as_of`: `2026-11-05T04:53:53.458055-05:00`.
- News item `published_at` values seen in planning run from `2026-11-03T12:33:49-05:00` through `2026-11-06T05:24:52-05:00`, which is before the freeze label. URLs in those items are not to be opened.
- Own book at the input commit: file `as_of` `2026-11-05T09:03:13.403398-05:00`, `evidence_cutoff` `2026-11-05T04:53:53.458055-05:00`, `overnight_run_id` `overnight-20261105`.
- CORRA legs `CRAH27` / `CRAM27` / `CRAU27` / `CRAZ27` have `observation_date: null` and `as_of: null`. Implied rates 2.885 / 3.01 / 3.11 / 3.20 were present. Do not invent an observation time, and do not backdate those legs to the freeze label.
- Series `as_of` dates differ inside one packet. Planning inspection saw US 2Y and 10Y, FX, Nasdaq, Dow, WTI, Brent, and US 10Y breakeven on 2026-11-05; Canada sovereign histories and S&P, VIX, HY OAS, and US 10Y real on 2026-11-04; broad USD on 2026-10-30; euro-area sovereign histories labeled 2026-11-06. Preserve each series date. A date of 2026-11-06 does not by itself prove the print was inside the 06:25 ET cutoff.

### 2.3 Book identity at the authorized commit

Read `pms.chatgpt` only, from commit `680297f3898081789794d20b765a5c908b6b93fe:data/pm/books/latest.json`. The working tree and planning HEAD are later. `prior_pm_books.pms.chatgpt` inside the snapshot matched these two positions in the planning inspection; the executing run still compares the two sources and reports any field difference.

| Position | Fields observed at the input commit |
| --- | --- |
| `pm-chatgpt-595561a1b90f` | `CORRA_2027H-Z`, long, notional USD 100,000,000, entry 3.4 at `2026-09-20T02:06:32Z`, book mark 3.10875 at `2026-11-05T11:31:47Z`, stored unrealized USD 291,250, risk capital and funding draw USD 1,000,000 |
| `pm-chatgpt-aef5bacd43d3` | `EURUSD`, long, notional USD 5,000,000, entry 1.1267 dated 2026-11-04, book mark still 1.1267, stored unrealized USD 0, risk capital and funding draw USD 50,000, opened `2026-11-05T08:52:26.537704-05:00` |

Seat funding on that book object: `funding_cost_usd` 25105.56, rate 3.97, convention ACT/360, day count 360. Realized P&L on the seat object was 1,036,875 and total P&L 1,328,125. Those are history. They are not a keep-the-risk argument. `last_action` was `HOLD`.

The frozen CORRA legs are not the book mark. Average of 2.885, 3.01, 3.11, and 3.20 is 3.05125. The indicative mark-to-market change versus the book mark of 3.10875 is a noncanonical research figure. Recompute it. Do not write it back to `latest.json`. The EUR book mark is the entry, not the frozen 1.1224 spot, so stored EUR unrealized of 0 is stale relative to the freeze. Recompute that change and label it noncanonical. The prompt's combined gross figure of +38,418 before financing is a claim to check, not an input to trust.

### 2.4 Own memory that may be read

At the input commit, only:

- `data/pm/books/latest.json`, key `pms.chatgpt` only
- `data/trading/pm/chatgpt/lessons.json`
- `data/trading/pm/chatgpt/research/index.json`
- `data/trading/pm/chatgpt/research/edge/profile.json`
- current open hypothesis files under `data/trading/pm/chatgpt/research/hypotheses/`

Planning inspection: 12 lessons, all `active`. Five hypothesis rows: open `hyp-chatgpt-cadnok-energy-reversal-20261104`, `hyp-chatgpt-corra-2027hz-20260919`, `hyp-chatgpt-eurusd-dollar-repricing-20261105`; rejected `hyp-chatgpt-rejected-cad-fx-20261002` and `hyp-chatgpt-rejected-duration-beta-20261002`. Research `boundaries.runtime_autoload` is false. These files are memory. They are not newer market evidence, and this research must not revise them.

Prior own research, memory only, read with `git show` because neither commit is an ancestor of planning HEAD and `docs/research/chatgpt/` is absent on HEAD:

- `a0c9357097fbd812bbac3e669b314349c0831660` — `docs/research/chatgpt/2026-11-05-election-repricing-review.md` and `docs/research/chatgpt/2026-11-05-election-repricing/`
- `ce43c055657a633d6c8635d39a238d5804a8e602` — `docs/research/chatgpt/2026-11-05-eurusd-corra-decision-review.md` and `docs/research/chatgpt/2026-11-05-eurusd-corra-decision/`

Do not merge, rebase, or cherry-pick those commits.

### 2.5 Where histories actually are

`families.market_state.data.fx.pairs` is a spot screen (`spot`, returns, percentiles, z, `rv_20d`, `rv_60d`). It has no close history. Do not invent one.

Embedded close histories used for yardsticks are `families.market_state.data.opportunities.series[]`, each `history` an array of `[date, value]`. Planning inspection found 126 points on the series below, while the series object and `moves.*.n` say `n: 252`. Use `len(history)`. Do not treat 252 as the sample. The same trap was already called out in the 5 November EURUSD note: a stored history of about 126 rows can sit next to a field that says 252.

Yield histories are in **bp** (`US_2Y` value 446.0 means 4.46 percent). A 100x unit error is the main arithmetic hazard. Confirm `unit` before any difference, volatility, or P&L.

`moves` is a supplied summary. Recompute the one-day change from the last two history points and record agreement or disagreement. Planning inspection saw stored `moves.1D` of Nasdaq −5.6817 percent log, Dow −3.4959 percent log, and US 2Y −12.0 bp, with `as_of` 2026-11-05. S&P value 7688.62 and VIX 16.61 are `as_of` 2026-11-04. They are not contemporaneous calm confirmation of the 5 November equity move.

`cross_assets.series` holds the latest value and `as_of` for BRENT, WTI, NASDAQ, DOW, SP500, VIX, and the other macro drivers. Planning inspection found no observation array there. Histories come from `opportunities.series`.

WTI and Brent notes say the futures history includes contract rolls. Roll jumps are not economic returns. Say so if a yardstick uses those series.

FX notes say ECB same-fixing reference crosses. AUDJPY and AUDNZD spots in this packet are reference crosses with many decimals, not exchange lots. Paper USD sensitivity and lot-based exposure stay separate.

These opportunity histories had **no** `history` and `as_of: null` in the planning inspection: `NZ-US_2Y`, `NZ-US_5Y`, `NZ-US_10Y`, `AU-NZ_2Y`, `AU-NZ_5Y`, `AU-NZ_10Y`. Relationship `AUDNZD~AU-NZ_2Y` had an empty history. A missing AU–NZ yield history narrows the AUDNZD fundamental comparison. It does not authorize a fill from outside the packet. NZDUSD being cheap on its own screen is not independent proof of an AUDNZD short.

CORRA and SOFR objects under `tradable_rate_curves.curves` are a curve snapshot (`contract_period_months` 3), not a strip history. Do not fabricate a CORRA or SOFR strip history. A sovereign yield history used as a movement yardstick must be labeled as a proxy.

`policy_meeting_prices` is present (`construction_version` `policy_meeting_v1`, `as_of` `2026-11-06`, banks AU, CA, EA, JP, NZ, US). Kevin's direct input: the derived front Fed meeting estimate is about 8 bp wrong. Exclude **all** supplied derived meeting-price estimates from entries, sizing, payoff, and policy inference. Calendars may be used as supplied. A calendar cannot repair or replace a price.

Also present, and not the same object: `policy_paths.countries.US.contracts_1m` (codes beginning `SR1`). The source map must label each of those fields as a contract quote or as a derived meeting estimate. Contract quotes may be described. They may not be turned into a meeting-step path that replaces the excluded estimates. Quarterly SR3 `implied_rate` is the priced futures period path and may be used only as that.

Do not read or cite `remotes/origin/cursor/correct-december-fed-sr1-one-month-futures-meeting-pricing-7156` or commit `71a1ea48`. That repair is not an ancestor of planning HEAD. Later repaired meeting outputs are out of scope even if they appear on a branch.

## 3. Evidence boundary

### Allowed

- The frozen snapshot and the agent packet named above, after the bindings in section 2 match.
- `scheduled_output.json` at the blob above. Trader `decisions` and PM `pm_decisions` are competing leads, not votes. `execution` on that file records the overnight graph's model accounting. It is not this research's model budget, and it is not evidence that a simulated seat's action was filled.
- Own book and own research files listed in section 2.4, at the input commit.
- The two prior research commits, as memory.
- Git reads of those objects. No other history.

### Forbidden

- Internet, news, market, or history retrieval. No ingestion, no data refresh, no newer main market files, no article bodies from URLs inside the packet.
- Other seats' private learning and psychology files, including `data/trading/pm/<other>/`, `data/overnight/runs/overnight-20261106/reviews/review-001/memory/`, and other PM memory files. Do not open `learning_state`, `psychology_state`, `reflections`, or `postmortems` for any seat, including ChatGPT, beyond the lesson and research files named above.
- Canonical book, mark, ledger, lesson, hypothesis, edge-profile, or receipt writes. No `[chatgpt-pm-decision]` issue. No `[chatgpt-research-memory]` issue. No trade-memory ingestion. No site build or deploy.
- Derived meeting-price estimates, and the December SR1 repair branch.
- Any model other than Grok 4.7 and Composer 2.5.

Room leads the executing note must verify from `scheduled_output.json`, separating a submitted action from a fill:

- Mean Reverter: SOFR close and AUDNZD short 5m
- Positioning Cynic: Canada payer reduction and AUDNZD short 10m
- Value Guy: AUDNZD short 5m
- Trend Follower: SOFR March receive add 25m
- Rate Hawk: December SOFR pay 10m
- Pragmatist: Canada March receiver 450m to 150m

`decisions` keys present at planning time: the fourteen trader seats. `pm_decisions` keys: `grinder`, `pragmatist`, `swinger`. No crowding claim follows from these simulated seats. If a prompt figure disagrees with the JSON, the JSON wins and the disagreement is reported.

## 4. Work the research must do

### 4.1 Owned book

Re-underwrite the CORRA receive at USD 100m against cut-to-50m and close. Use remaining return and giveback, and credible conditional domestic and policy paths. The prospective trading target 3.03375, adverse review 3.26375, 8–12 week horizon, and the idea of harvesting to 50m at the target are prior management marks. They are not grandfathered. Recompute remaining gap versus the frozen four-leg average 3.05125. State a judgmental economic range. Do not adopt 2.75, and do not adopt 2.90 / 2.98 / 3.05 / 3.10 as fair value unless the note separately defends that path from packet evidence and labels it as judgment.

Review EURUSD hold, reduce, exit, and add. The position exists because the PM overrode the 5 November research rejection: the broad-dollar thesis was accepted without an EUR-specific residual. That override is a fact about the book. It is not a proof the residual has since appeared. Test oil rebound and USD demand against ordinary volatility. Frozen spot in the packet is 1.1224 on 2026-11-05, entry 1.1267. Prior targets 1.1356–1.1472, daily-close review 1.1179, and the worse-gap illustration 1.113 are management marks to re-test, not inherited targets. No resting orders. Missing forwards: financing is a clearly labeled cost sensitivity, not an FX forward and not a spot forecast.

### 4.2 AUDJPY short versus AUDNZD short

Compare them. No desired winner and no forced trade. Kevin's earlier AUDNZD example was coaching, not an instruction.

Use supplied histories, domestic fundamentals, the risk and oil response, and catalysts that are actually in the packet.

- AUDJPY: investment, growth, and risk exposure. The countercase includes Japan's own AI exposure and Japan's oil-import burden. Do not drop that countercase because the cross sold off, or because it did not.
- AUDNZD: separate a real relative-repricing rationale from a percentile fade. The spot screen is extreme (`pctile_1y` about 97 and `pctile_5y` about 99 in the planning inspection). A percentile is a screen. AU–NZ yield histories are absent, so a rates-spread fair value cannot be computed. NZDUSD cheap is not proof.

### 4.3 US rates rally

Challenge the rally. Compare SOFR receive continuation, a tactical pay, and wait/flat. Defend the contract and the period, or decline to. Use supplied labor indicators, inflation, and the reaction function. Build strong and weak US and Canadian employment scenarios only from fields that exist. Planning inspection saw US labor component ids such as `US.Labor.payrolls`, `US.Labor.unemployment`, and `US.Labor.wages` with observation period 2026-09 and research status `current release`, plus Chicago Fed labor fields with period 2026-10. If consensus, a newer release, or a named labor field is absent, say so and narrow the claim. Do not invent the print.

Context that must be recomputed from the packet rather than copied from this plan: Nasdaq 5 November log return near −5.68 percent, Dow near −3.50 percent, US 2Y 4.46 (−12 bp), US 10Y 4.84 (−6 bp), EURUSD 1.1224, Brent 98.29, WTI 90.52. Oil rebound and growth stress can both be true. One day does not identify the cause.

### 4.4 Decision card for every serious hold or new-trade candidate

Each card contains:

- preferred action
- entry now versus a named wait, and the cost of waiting
- judgmental economic target or range
- repricing horizon
- actual normal-movement yardstick, proxy labeled, no fabricated strip history
- fundamental falsifier
- practical exit or time review
- dollar loss budget
- size derived from the adverse path
- target payoff
- planned-exit loss
- gap or stress loss
- same-horizon financing, with the assumptions written down

Targets, volatility, and payoff ratios are not win probabilities and not expected value. No false precision. Round to the precision the inputs support.

Compare candidates at explicit risk sizes. Decompose policy, growth, inflation, energy, currency, liquidity, financing, horizon, and path. Show aggregate adverse scenarios for the recommended set. Positive or negative correlation is not an automatic veto and not an automatic hedge requirement. Different nominal sizes are not proof of diversification. Keep paper USD sensitivity distinct from exchange lots, and monthly contracts distinct from quarterly contracts.

## 5. Execution graph

One later provider run. Internal graph only. No external follow-up and no retry beyond the single correction cycle below.

**Models.** Grok 4.7 and Composer 2.5 only. ACP allowlist strings: `grok-4.7` and `composer-2.5`. Do not use Auto, Opus, Sonnet, inherit, or any other family. Composer 2.5 is an exact catalog id in this environment. Bare `grok-4.7` is not; the catalog exposes `grok-4.7-high` and the other effort suffixes. The executing run passes `grok-4.7` and `composer-2.5`. If the tool rejects bare `grok-4.7`, stop and report that limitation. Do not substitute a different family. This plan does not grant a suffix workaround.

**Caps.** Total model invocations ≤ 16, Grok ≤ 12, Composer ≤ 4 including the parent. The parent is Grok, so the Composer count is only Composer nodes.

**Base graph (7 calls: Grok 5, Composer 2).**

| Node | Model | Writes only | Job |
| --- | --- | --- | --- |
| A | Composer 2.5 | `.../source/` | Extract authorized evidence, vintages, units, and exact histories into a compact source map. No trade opinion. |
| B | Grok 4.7 | `.../book/` | Owned-book re-underwriting. Starts only after A is on disk. Does not read C or D. |
| C | Grok 4.7 | `.../fx/` | AUDJPY versus AUDNZD. Independent of B and D after A. |
| D | Grok 4.7 | `.../rates/` | SOFR continuation versus tactical pay versus flat. Independent of B and C after A. |
| E | Composer 2.5 | `.../quant/` | Reproducible payoff, volatility, and financing from B, C, and D proposals and from the embedded numbers. No new economic thesis. |
| F | Grok 4.7 | `.../verification/` | Reproduce signs, units, currency conversions, sample sizes, horizons, source lineage, and economic objections. F does not author or edit B, C, D, or E. |
| Parent | Grok 4.7 | the review markdown and `decision_cards.json` only | Integrate checked outputs. Drop or quarantine anything F did not pass. |

B, C, and D use separate directories and do not revise each other. The parent owns the recommendation.

**One correction cycle.** If F fails a check, the parent sends that failure once to the node that owns it (B, C, D, or E), then F runs once more on the corrected artifact. That is the only extra cycle. Do not loop. Worst case inside the cap: base 7, plus one writer and one verifier, = 9 calls, Grok ≤ 7, Composer ≤ 3. Leave the unused budget unused.

Node F's report is an objection list with reproduced figures. It is not a second strategy memo.

## 6. File layout for the later research run

Follow the 5 November decision note's shape: a front recommendation table, book first, then the rejected or competing expressions, then what would change the view. Support files stay beside the note.

```text
docs/research/chatgpt/2026-11-06-growth-shock-decision-review.md
docs/research/chatgpt/2026-11-06-growth-shock-decision/
  source/source_map.json
  source/source_map.md
  source/extract.py
  book/judgment.json
  book/decision_memo.md
  fx/judgment.json
  fx/decision_memo.md
  rates/judgment.json
  rates/decision_memo.md
  quant/inputs.json
  quant/calc.py
  quant/results.json
  quant/assumption_ledger.md
  verification/verify.py
  verification/verifier_checks.json
  verification/verifier_report.md
  decision_cards.json
```

`extract.py` reads only the authorized snapshot and writes `source_map.json`. `calc.py` reads `source_map.json` plus the three judgment files and writes `results.json`. `verify.py` recomputes from `source_map.json` and `results.json` and does not import the analysts' prose as data. Scripts use the standard library. No new dependencies. No project test suite and no CI changes.

The review markdown states the integration clock separately from the freeze clock and the market-generation clock, the same way the 5 November note did.

## 7. Source map (node A)

`source_map.json` records, for every series the later nodes use:

- json path
- series id
- `unit`
- `as_of`
- `len(history)`, first date, last date, first value, last value
- whether `n` or `moves.*.n` disagrees with `len(history)`
- recomputed last change versus stored `moves.1D`
- source observation time if present, otherwise an explicit null

Minimum series set:

- FX histories: `EURUSD`, `AUDJPY`, `AUDNZD`, `AUDUSD`, `NZDUSD`, `USDJPY`, and the other G10 spots only if a cross-section is actually used
- Macro drivers: `NASDAQ`, `DOW`, `SP500`, `VIX`, `WTI`, `BRENT`, `GOLD`, `HY_OAS`, `US_BE10`, `US_REAL10`, `BROAD_USD`, `COPPER`, `RUSSELL`
- Sovereign: `US_2Y`, `US_10Y`, `CA_2Y`, `CA_10Y`, `AU_2Y`, `AU_10Y`, `JP_2Y`, `JP_10Y`, `EA_2Y`, `EA_10Y`
- Explicit empties: `AU-NZ_*`, `NZ-US_*`, relationship `AUDNZD~AU-NZ_2Y`
- Curves: CORRA `CRAH27`, `CRAM27`, `CRAU27`, `CRAZ27` with price, implied rate, expiry, and null observation dates; SOFR contracts the rates memo actually names, including the front December code `SR3Z6` and the March contract if Trend Follower's lead is discussed
- Quarantine block: entire `policy_meeting_prices`, plus any `contracts_1m` field labeled derived. The quarantine block stores the path and the reason, not the levels, so later nodes cannot casually copy them.

Also extract, without interpretation:

- `fx.pairs` spot, `ret_1d`, percentiles, and realized-vol fields for the pairs under comparison, labeled as screen fields that the 126-day history cannot recompute when the screen claims a five-year window
- macro component ids, observation periods, and statuses for US and Canadian labor and inflation actually used
- news item id, `published_at`, and headline for items the book or rates memos cite
- own-book position fields from the input commit, and the snapshot `prior_pm_books.pms.chatgpt` fields, with a diff
- scheduled-output action text for the six leads in section 3, plus `execution` status if the file distinguishes submitted from filled

`source_map.md` is a human index of those rows. It contains no recommendation.

## 8. Calculation rules (node E)

Recompute. Do not import the prompt's P&L.

**CORRA mark change.** Equal-weight average of the four frozen implied rates minus the book mark 3.10875. Planning arithmetic: (2.885 + 3.01 + 3.11 + 3.20) / 4 = 3.05125; difference = −0.0575, which is 5.75 bp in the receive's favor if the quote is percent. Dollar result depends on the DV01 identity. The 5 November note used USD 10,000 per bp at USD 100m. Confirm that identity from the book's own risk fields before using it: stored unrealized USD 291,250 on a mark move from 3.40 to 3.10875 is 29.125 bp, and 29.125 × 10,000 = 291,250. If that identity holds, 5.75 bp is USD 57,500. Label the result noncanonical. It is not the stored unrealized P&L.

**EUR mark change.** Long USD notional on EURUSD: notional × (spot / entry − 1). Entry 1.1267 and spot 1.1224 give (1.1224 / 1.1267 − 1) × 5,000,000 ≈ −19,082. Use the packet spot, not a rounded prompt figure, and show the unrounded value. This is paper USD P&L on a USD-notional identity. It is not an exchange lot count. Stored book unrealized remains 0 because the book mark was never updated. Do not add the two.

**Financing.** Separate three numbers and never net them into a directional edge:

1. Stock charge already on the book (`funding_cost_usd` 25105.56 at 3.97 percent ACT/360 on the existing draw). State the draw it applies to.
2. Same-horizon prospective financing on the risk-capital draw the card keeps, at a rate taken from the packet's SOFR fixing history (`funding_context.sofr.history` or the curve benchmark history). State day count, the fixing date, and the horizon in days.
3. EURUSD carry sensitivity only. Executable forward points are absent. A sovereign or overnight rate gap is not an FX forward. Write the formula, the two rates, their dates, and the day-count basis. State that the gap is not a spot forecast.

**Yardsticks.** Sample standard deviation with N−1 on daily log returns for prices, and on daily differences for yields in bp. Horizon scaling by √h is a labeled convention, not a probability. Report the window (last 20 observations, and the full 125 returns from 126 points if used). Overlapping best and worst excursions may be described and must be labeled descriptive. For CORRA and SOFR, the yardstick is a named proxy such as the Canada or US 2Y history. Say the strip history is absent.

**Size.** Choose the adverse path first, in price units. Size = loss budget / loss per unit on that path. Then compute target payoff, planned-exit loss, and gap/stress on that same size. Do not pick a notional and then invent a stop that makes the ratio look acceptable.

**Portfolio.** For the recommended set, show at least: the domestic reacceleration path that hurts the CORRA receive, the dollar-demand and oil-rebound path that hurts EURUSD, and a risk-off path that hurts an AUDJPY or AUDNZD short if one is recommended. Add the financing charge for the same horizon. Correlation is a comment, not a hedge instruction.

**Units to pin in `assumption_ledger.md`.** Yield bp versus percent. EURUSD quoted USD per EUR. AUDJPY and AUDNZD as reference crosses. CORRA and SOFR implied rates in percent with price = 100 − rate, confirmed against the stored price (planning inspection: CRAH27 implied 2.885, price 97.115). Quarterly versus monthly contract codes. USD notional versus risk-capital draw (the CORRA draw is USD 1,000,000 on USD 100,000,000 notional; do not finance the full notional by accident).

Node F re-implements the sign and the unit conversion independently. A match to more than the input precision is a bug, not extra accuracy.

## 9. Analyst rules (nodes B, C, D)

- Cite source-map ids and dates. Do not cite a number that is not in the source map.
- Room output is a lead. Agree or disagree in prose. Do not count seats.
- One day of equity, oil, and rates can be described. It cannot be given a single cause.
- Screens (`pctile_5y`, z, `rv_20d`) are not the thesis. The 126-day file cannot rebuild a five-year percentile. Say that when a screen is quoted.
- Do not use `policy_meeting_prices` levels even as a "rough" check.
- Do not update the open hypotheses. The note may say what a later human research ticket could record. It does not write one.
- Incomplete labor or inflation evidence narrows the rates conclusion. It does not start a data hunt.

## 10. Parent integration

The parent writes the review only from artifacts F marked pass. A failed figure is omitted or shown as failed, with F's objection. The parent does not silently replace a number.

The note ends with a decision sheet: one row per serious candidate, the card fields from section 4.4, and an explicit "no trade" row where the comparison declined a candidate. The sheet is the proposal Kevin reviews. It is not an order and not a book update.

Limitations that must appear even if every check passes:

- Derived meeting prices excluded, so policy inference is coarser than the packet's meeting object.
- No CORRA or SOFR strip history; yardsticks are proxies.
- No EURUSD forward points.
- No AU–NZ or NZ–US yield history.
- S&P and VIX are 4 November; broad USD ends 30 October; Canada yields end 4 November; euro-area yield `as_of` is 6 November and must not be backdated.
- CORRA contract observation times are null.
- Scheduled-output commit `f0cadc…` was not in the planning clone; the blob on HEAD was what could be checked.
- Own prior research commits are not on this branch's history.
- Canonical book on HEAD is later than the input commit and was not used.
- Simulated room actions are not market positioning.
- No win probabilities and no fair values were estimated.

## 11. Acceptance checks before the research commit

The later run, not this plan, does these:

1. Re-run section 2 bindings. Stop on a hash, blob, or book-blob mismatch.
2. `python3 docs/research/chatgpt/2026-11-06-growth-shock-decision/source/extract.py`
3. `python3 docs/research/chatgpt/2026-11-06-growth-shock-decision/quant/calc.py`
4. `python3 docs/research/chatgpt/2026-11-06-growth-shock-decision/verification/verify.py` exits 0, and `verifier_checks.json` has no failed unit, sign, or lineage check.
5. `git diff --stat` against the branch start shows only the two research paths named in the header. No changes under `data/`, `scripts/`, `tests/`, or other `docs/` paths.
6. Commit and push that research branch. No merge or rebase of `main`. No pull request unless a later instruction asks for one.

## 12. This plan run's boundary

This run writes this file only. It does not launch the graph, does not create the research directory, and does not authorize another provider call. Model caps in section 5 apply to a later authorized execution. They are not a request for one.
