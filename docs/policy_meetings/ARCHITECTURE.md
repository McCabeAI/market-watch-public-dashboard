# Policy meeting calendars, pricing, and paper instruments

Status: plan of record. Baseline `main` @ `caa9acac`.
Planning review: Opus 5.5 high (`claude-opus-5-5-high`), agent `bc-9ecb41db-2c4c-518e-8f9a-22cd6d3c42ae`.
The tool rejected the bare id `claude-opus-5-5` as unresolved. This document follows that review, with the corrections in §12.

## 1. Scope and non-goals

Six banks, country codes `US CA AU NZ EA JP` (Fed, BoC, RBA, RBNZ, ECB, BoJ):

- Published decision dates, all future dates, not only five.
- Official policy rate as the anchor. Overnight fixings are the basis, never the target.
- One deterministic engine from existing public futures settlements to post-decision policy rates.
- A Monetary policy fold on each country-detail page.
- Synthetic `policy_meeting` paper instruments inside the existing book.

Non-goals: meeting probabilities, RateProbability or WatchTower scraping, paid data, invented quotes, a second ledger, a new schedule or workflow, warning banners, roster or model or capital or score changes, and trades written into existing books.

## 2. Calendar

Persist `data/policy_meetings.json`, separate from overnight run packets.

```
{schema_version: 1, updated_at,
 banks: {US|CA|AU|NZ|EA|JP: {
   timezone, source_url, status: verified|unavailable,
   retrieved_at, last_attempt_at, last_error,
   decisions: [{decision_date, local_time|null, meeting_start|null,
                effective_date, source_url, state: upcoming|past}]}},
 revisions: [{bank, kind: added|removed|date_changed|retired,
              decision_date, previous_date|null, detected_at}]}
```

Decision date is the announcement day. Past decisions stay for 12 months. Next five are upcoming dates strictly after `as_of`, ascending.

| Bank | Zone, time | Decision rule | Ignored |
|---|---|---|---|
| US | America/New_York, 14:00 | Last day of the FOMC range, including `Apr/May 30-1`. `meeting_start` is the first day | Minutes, SEP markers, notation votes |
| CA | America/Toronto, 09:45 | Schedule-table rows whose link text is `Interest rate announcement` | MPR-only rows |
| AU | Australia/Sydney, 14:30 | Monetary Policy Board column only. Second day of the range | Payments System Board, empty months |
| NZ | Pacific/Auckland, 14:00 | OCR announcement dates on the RBNZ schedule page | FSR-only rows when the page separates them |
| EA | Europe/Berlin, 14:15 | Rows whose text is a monetary policy meeting followed by a press conference. Day 2 when the row says Day 2. A single-day monetary policy meeting with a press conference counts | Day 1, non-monetary-policy meetings, General Council |
| JP | Asia/Tokyo, time null | `Date of MPM` column only. Last listed day. First day is `meeting_start` | Outlook, Summary of Opinions, Minutes |

Revision detection compares the newly parsed upcoming set with the stored one. Exactly one removed and one added date within 31 days is `date_changed`. `revisions` is capped at 100.

One bank's fetch or parse failure keeps that bank's last verified decisions and records `last_error`. It does not clear other banks. A bank that has never verified stays `unavailable` with an empty list. Dates are never typed in by hand.

## 3. Effective dates

Weekend skip only. No holiday calendar.

| Bank | Effective date |
|---|---|
| US | Next Mon–Fri after the announcement. Matches the implementation note. |
| CA | Next Mon–Fri. The BoC schedule says the change takes effect the next day. |
| AU | Next Mon–Fri. |
| NZ | Next Mon–Fri. |
| EA | The first Wednesday strictly after the decision. |
| JP | Next Mon–Fri. |

## 4. Anchor and basis

Anchor is the official policy rate.

| Bank | Anchor | Source confirmed on 2026-11-05 |
|---|---|---|
| US | Midpoint of the target range | Existing `policy_state` US block. Do not change `acquire_us_decision`. |
| CA | Target for the overnight rate | BoC Valet `V39079` (same host as CORRA). Live print 2.50 on 2026-11-04. |
| AU | Cash rate target | RBA statistical table A2, column `New Cash Rate Target`. Not F1. F1 has AONIA, OIS, and bank bills only. Live print 4.85 announced 04-Nov-2026. |
| EA | Deposit facility rate | ECB data API `FM.D.U2.EUR.4F.KR.DFR.LEV` (same host as €STR). Live print 2.5 on 2026-11-05. |
| JP | Uncollateralized overnight call-rate guideline | Latest statement linked from `https://www.boj.or.jp/en/mopo/mpmdeci/state_all/index.htm`. Parse the "around X percent" guideline. Do not copy the TONA fixing. |
| NZ | Not collected | RBNZ HTML returned HTTP 403 to this client, and `curl_cffi` is not installed. Leave the explicit gap. Do not invent an OCR. |

`basis = latest fixing − anchor`, in percent, held constant across the horizon of one snapshot. Fixings: SOFR, CORRA, AONIA, €STR, TONA, already collected on the policy-path block. No anchor or no fixing means that bank's prices are `unavailable`.

A parallel +5 bp move in the fixing and the anchor leaves basis and post-decision rates unchanged. An anchor-only move recomputes basis, shifts the policy-rate level one for one, and leaves cumulative bp unchanged. Cumulative instruments also store `base_rate` at entry so a later anchor print cannot restate old P&L.

## 5. Pricing

One function, `price_bank`, used at entry and at every later mark.

- Contract implied fixing `F = 100 − price`.
- Each calendar day is `policy_in_force + basis`. A contract equals the calendar-day-weighted simple average. No compounding.
- Monthly window: the calendar month of `expiry` (`YYYY-MM`). Products: SR1, ASX IB, MX 1M when present.
- Quarterly window: the third Wednesday of the expiry month through the third Wednesday three months later, exclusive. Products: SR3, CRA, TOA3M, FST3.
- Prefer a monthly contract over a quarterly one when both can price the meeting.
- Elapsed days in a window use the official policy rate then in force. If that history is missing, drop the contract.
- A meeting with an official outcome in `policy_state` is known from its effective date. The Fed outcome is the midpoint.

Solve meetings in effective-date order. For unresolved meeting `k`, with earlier rates known:

1. **Identified.** A contract whose window days are only known rates or the post-`k` rate, with at least 7 days at that rate. Prefer monthly, then more days at the unknown rate, then the earliest window. `x = (N·(F − basis) − Σ known) / D`.
2. **equal_step.** Otherwise the earliest-ending contract (monthly preferred) with at least 7 days after `k` takes effect. Every unresolved meeting effective inside that window gets the same step `s = (N·(F − basis) − Σ base) / Σ m`, where `m` is how many of those meetings are in force that day. Label `equal_step`. No probabilities.
3. **Unavailable.** If neither applies, this meeting and every later meeting are unavailable. Earlier meetings still publish. Other banks are unaffected.

`incremental_bp = (post − previous post)·100`. `cumulative_bp = (post − current anchor)·100`. Round rates to 4 decimal percent and bp to 2 decimals at output only. Each row stores the contracts it used.

## 6. Gaps

- NZ: no short-rate strip in the repo, and the RBNZ site returned 403 here. Calendar and prices stay unavailable until a fetch succeeds. No bank-bill proxy.
- EA: €STR exists. FST3 still has no reliable public settlement feed. Sovereign Bunds are not a meeting anchor. Calendar and DFR can publish. Prices stay unavailable until `contracts_3m` actually parses. Do not add a feed.
- JP prices only when TONA `contracts_3m` and the BoJ anchor both exist. Two meetings in a quarter will usually be `equal_step`.
- A bank with no anchor is unavailable even if futures exist. Never substitute the fixing for the target.

## 7. Snapshot and history

Market state carries `policy_meeting_prices`:

```
{schema_version: 1, construction_version: "policy_meeting_v1", as_of,
 banks: {US: {status: ok|partial|unavailable, reason|null,
   anchor, fixing, basis_bp, futures_as_of, calendar_retrieved_at,
   meetings: [{instrument_id, decision_date, effective_date, post_rate,
               incremental_bp, cumulative_bp,
               method: identified|equal_step|official|unavailable,
               contracts, chg_1d_bp, chg_1w_bp}]}}}
```

`data/policy_meeting_history.json` keeps the last 10 sessions, keyed by `as_of`, of `{bank → decision_date → post_rate, cumulative_bp, method}`. Same-day reruns replace that session. `chg_1d_bp` uses the latest earlier session. `chg_1w_bp` uses the latest session on or before `as_of − 7 days`. Match on bank plus decision date. A calendar re-key does not rewrite history or open books.

## 8. Paper instruments

| Kind | Id | Quote |
|---|---|---|
| meeting | `PM:US:2026-12-09` | Post-decision policy rate, percent |
| cumulative | `PMC:US:2026-12-09` | `(post − base_rate)·100` bp, `base_rate` stored at entry |
| calendar_spread | `PMS:US:2026-12-09:2027-01-28` | Later post minus earlier post, bp. Same bank, earlier date first |
| cross_country | `PMX:US:2026-12-09:CA:2026-12-10` | First cumulative bp minus second, each against its own stored base |

`paper_expression = {type: "policy_meeting", construction_version: "policy_meeting_v1", kind, bank, decision_dates, side}`. Position side is `long` or `short` and must match. Long profits when the quote falls.

`pnl = −sign × Δquote_bp × lots × local_dv01 × fx`.

`Δquote_bp` is `(mark − entry)·100` for a meeting and `mark − entry` for bp quotes. `local_dv01` is the anchor future's published bp value: SR3 USD 25, CRA CAD 25, IB AUD 24.66. TOA3M is JPY 2,500 per bp on JPY 100m face, stored on the meeting position only, not added to `contract_economics.SPECS`. EA would be EUR 25 and is not bookable while FST3 is absent. `lots` are locked at entry from `notional_usd` via the existing face-to-lot helper. Cross-country risk is sized in the first bank's currency.

The position stores `valuation_method: policy_meeting_dv01`, entry quote, lots, local dv01, currency, base rates, and underlying `{product, expiry, weight}`.

OPEN and ADD take the canonical snapshot quote. REDUCE and CLOSE take that same day's quote. Replay uses the stored entry and the snapshot. No new ledger file.

Settlement: once `as_of` is on or after the effective date and `policy_state` has the official outcome, that leg freezes at the official post rate (Fed midpoint) with method `official`. Spreads lock the settled leg and keep marking the other. With no official outcome, the futures mark remains. A missing decision date holds the last good mark with `mark_status: held_calendar_revision`.

`assess_expression` accepts `policy_meeting` only when every referenced row is `identified` or `equal_step`. Settled, unknown, NZ, and EA rows are not new risk. Existing expression types keep their valuation path. `mark_admission.py` stays unchanged.

## 9. UI

One `<details class="policy-meetings">` inside each country-detail section, summary `Monetary policy`. Table columns: decision date, implied rate, incremental bp, cumulative bp, 1d, 1w, method. One source line under the table (anchor, futures as-of, basis, calendar retrieved). `.policy-meetings .table-wrap { overflow-x: auto }`. An unavailable bank still renders its dates or, with no calendar, one reason line. A missing bank does not raise. No caveat banner.

## 10. Files

- `scripts/policy_calendar.py` — parse, effective date, merge, revisions, next five, refresh, load/write.
- `scripts/policy_state.py` — collectors for CA, AU, EA, JP. NZ stays a gap. US acquisition unchanged.
- `scripts/policy_meeting_pricing.py` — windows, `price_bank`, snapshot, history, instrument quote.
- `scripts/country_detail/policy_meetings.py` — HTML. Call it from `render_country_detail`. CSS in `country_detail.css`.
- Integration after those exist: `market_state.py` adds the block on the normal refresh and best-effort calendar plus policy-state refresh. `macro_ingestion/cli.py` `run_data_only_catch_up` writes calendars under the output dir only and does not touch books or canonical trader stores. `executable_catalog.py`, `paper_marks.py`, and `valuation.py` gain the `policy_meeting` branch.

Do not touch: `model_registry.json`, `.cursor/`, `data/overnight/runs/**`, roster and capital caps, score calibration, `mark_admission.py`, `.github/workflows/**`.

## 11. Tests

No new workflow. Cover a mid-month identified meeting, two meetings in one quarter as `equal_step`, a missing later contract, constant basis, a revised date that leaves other banks alone, a 403 that keeps the prior bank, long and short P&L for all four kinds, OPEN/ADD/REDUCE/CLOSE on the snapshot quote, settlement to the official midpoint, an old book with no `policy_meeting` position valuing as before, and six-country HTML with one bank unavailable.

## 12. Corrections to the planning review

- Bank keys are the repo country codes, not `FED`/`BOC`/`RBA`.
- The RBA cash-rate target is table A2 `New Cash Rate Target`. F1 does not carry that column.
- `curl_cffi` is not installed in this environment. RBNZ returned HTTP 403. NZ stays an explicit gap until a later successful fetch. No dates are filled in.
- ECB key `FM.D.U2.EUR.4F.KR.DFR.LEV` resolved live.
- Cumulative bp is invariant to an anchor-only shift once basis is recomputed. The level moves. Section 4 is the rule.
