# Market Watch UX audit and workstation redesign (V1)

Owner: design lead (Claude Opus 5.5). Implementation: Grok 4.7 and Composer 2.5 workers.
Scope: presentation only. Scores, trading logic, risk rules, book valuations, source
pipelines, publication gates and data files are out of scope and unchanged.

## 1. Method

The audit used real renders, not HTML reading:

- Local build reproduced from `.github/workflows/deploy-pages.yml` with
  `scripts/visual_qa/build_site.py` (all `run:` steps, tests included, at
  `239b3e60`). Output was byte-identical in structure to production apart
  from the live schedule-fetch note.
- Production at `https://mccabeai.github.io/market-watch-public-dashboard/`
  captured with the same script. Production matched the local build.
- Headless Chrome via Playwright (`scripts/visual_qa/capture.py`) at three
  widths: wide desktop 1920×1080, 13-inch laptop 1440×900, iPhone portrait
  390×844 at 2×. Every tab, plus country routes. Full-page captures were cut
  into viewport slices and inspected one by one.

Measured defects from the BEFORE capture:

| Check | Result |
| --- | --- |
| Horizontal overflow, iPhone Front | 276 px (page wider than the screen) |
| Horizontal overflow, iPhone Sources | 235 px |
| Horizontal overflow, laptop Front | 9 px |
| Front page height, iPhone | 18,006 px (≈21 screens) |
| Trader Book height, laptop | 8,925 px; iPhone 35,510 px (≈42 screens) |
| Header date | hard-coded `8 SEP 2026` on a page built 24 Oct 2026 |

## 2. Findings by page

Severity: **P0** misleading or blocks the 30-second read; **P1** costly to
interpret; **P2** polish.

### Front page

- **P0 Stale numbers presented beside fresh ones.** The "Macro snapshot" cards
  are September base-page values (US payrolls +162k, UR 4.1%, Core PCE 3.3%)
  with no date. The Country Detail engine already shows the September print
  at +29k. A trader would read +162k as current.
- **P0 Header says `8 SEP 2026`.** The only prominent date on the page is
  seven weeks old and unrelated to the market packet (24 Oct) or score freeze
  (21 Sep).
- **P0 Raw error dumps in the tape.** The NZ 10Y card prints the full RBNZ
  fetch failure, user-agent notes and URLs, about 40 lines, stretching every
  card in the row to the same height and pushing everything below the fold.
- **P1 No answer to "what matters today".** The first screen is a provenance
  banner and 14 equal-weight cards. Nothing ranks moves, nothing says what
  changed, nothing connects a move to a country page.
- **P1 Score board is 6 tall cards × 4 rows.** You have to read about 30 pills
  to find the biggest impulse. "Largest impulse: Consumer ↑ warming +3.55
  (level 46.5 neutral)" is accurate but is prose in a card, not a ranking.
  LEVEL and IMPULSE share a row with similar pill styling, so they read
  as the same kind of number.
- **P1 The score freeze date (21 Sep) is in body copy only.** The scores are
  33 days older than the market packet. That caveat should sit next to the
  scores, not inside a sentence.
- **P2 Visually flat.** Same white card, same border, same weight for
  everything. Long provenance sentences in 12 px muted text everywhere.

### Country Detail

- **P0 Stale September narrative block.** The "Temperature / Consumer /
  Demand / Labor Momentum" panel repeats undated September KPIs (+162k
  payrolls, 4.1% UR) directly under "What Matters Now", which shows newer
  data. Canada's block still says "August employment fell 42k".
- **P1 Machine series titles.** "Real Gross Domestic Product, Percent Change
  from Preceding Period, Seasonally Adjusted Annual Rate" and three identical
  "Personal Consumption Expenditures: Chain-type Price Index, Excluding Food
  and Energy" context rows, which differ only by transformation and cannot be
  told apart.
- **P1 LEVEL vs IMPULSE are not distinguished.** The top tiles read
  "63.1 / Static · impulse -0.8" in one muted line. The score as-of date and
  the input vintage (for example Core PCE through Jul 2026) are not shown.
- **P2 The policy panel is good and dated.** Keep it visible.

### Trader Book and PMs

- **P0 Mislabelled history.** "Overnight position changes" lists all 56
  applied tickets since 19 Sep (`overnight_changes` is the full applied
  history in `scripts/overnight/books.py`). Only 3 are dated on the latest
  book date (23 Oct).
- **P0 Fleet-wide anomalies hidden in each card.** Every seat carries the same
  alert, `funding_accrual_failed_closed: official NY Fed SOFR history is
  missing`. Four positions have "Paper mark unavailable". Neither appears at
  fleet level.
- **P1 No comparison surface.** Fourteen tall cards in rank order; P&L, risk
  used, drawdown, conviction and action can't be compared without scrolling
  about 6 screens. No sort, no filter, no "who changed today".
- **P1 Broken research layout.** The "Overnight research" panel squeezes each
  headline note into a 60 px column, about 25 lines tall, above the
  books.
- **P1 Code-like labels.** `carry-is-king`, `CORRA_2027-03`, `SOFR-CORRA_2Y_2027H1`,
  `RATES_RV`, `SPOT_FX`, `OPEN/ADD/REDUCE/HEDGE/CLOSE`, `overnight-20261023`.
- **P2 PM comparison rows don't align** (status text drifts; risk wraps).

### Market Data

- Strongest existing page: ranked, explained, sparkline evidence. Needs the
  theme and type scale only. **P2** "Percentile 0" should read as
  "lowest in the lookback" via the existing label, without changing the maths.

### Releases

- **P1** Each release is a 10-line card. The verification sentence, standing
  clock caveat and score-freeze sentence repeat on every card. Two weeks of
  releases need about 5 laptop screens. Date, country, release, time and
  whether it feeds a score should fit on one row, with the provenance one
  click away.

### Sources

- **P0 Mobile overflow** (235 px) from unbroken URLs and error dumps.
- **P1** Status counts are raw tokens (`carried_forward: 12`,
  `not_applicable: 12`) in a bullet list with no explanation. Failure rows
  inline full Python exception reprs.

## 3. Design decisions (prioritised)

1. **One honest "Desk brief" at the top of the Front page.** It answers what
   matters, what changed, why and where to look, built only from deterministic
   comparisons of published data:
   - *Biggest score impulses*: the top dimension impulses across the six
     economies by |impulse|, with LEVEL and class, labelled with the score
     freeze date. Each links to its country.
   - *New prints since the score freeze*: "What Matters Now" findings from
     the existing attention engine, marked as not yet in the frozen score.
   - *Largest market moves*: tape series ranked by their own change unit (bp
     for yields, % for FX and commodities), with observation dates.
   - *Caveats*: unavailable series, score-freeze age in days, and the next
     dated releases from the calendar model.
   No new narrative is generated. Every sentence is a template over
   published fields.
2. **Dates everywhere, and the right ones.** Replace the hard-coded header date
   with the market packet time, score freeze date and build time. Display
   format: `23 Oct 2026`; periods as `Sep 2026` or `2026 Q2`; ISO stays in
   raw detail.
3. **Stale content is fenced, not deleted.** September base-page snapshots
   (Front macro cards, Country "Temperature / Consumer" hero and Labor
   Momentum) move into a collapsed, conspicuously labelled `details`:
   "September base-page snapshot, not refreshed. Figures may be superseded
   by the dated evidence above." Dated, refreshed panels (Policy /
   Transmission) stay visible.
4. **LEVEL and IMPULSE look different.** LEVEL is the big number with its
   /100 scale and class word. IMPULSE is a signed delta with an arrow and
   the word warming, cooling or static, labelled "vs prior print". A one-line
   legend defines both on Front and Country.
5. **Human names first, raw identifiers on demand.** Series, seats,
   instruments, statuses and source buckets get readable names. Raw IDs move
   into `.mw-raw` monospace inside a disclosure or a `title`.
6. **Trader Book becomes triage-first.** Order: fleet overview (P&L, risk,
   winners and losers, fleet-level flags), then a sortable and filterable seat
   comparison table, then progressive drill-down per seat (positions, thesis,
   invalidation, alerts split into risk flags and watch items, required
   pitch), then latest-dated tickets with the full ticket history collapsed,
   then PMs in the same pattern, then research, collapsed. All existing
   fields and book maths are kept. Totals are computed exactly as before.
7. **Dark workstation theme.** Layered slate surfaces, high-contrast text,
   tabular numerals, restrained semantic colour (green/red only for P&L
   sign, amber for caveats/stale), no glow, no animation beyond 120 ms
   hover/focus transitions. Print falls back to light.
8. **Mobile is first-class.** No horizontal page overflow at 390 px. Nav
   scrolls horizontally in one row. Tables become stacked rows or scroll
   inside their own container. Tap targets ≥ 40 px, body text ≥ 13 px.

## 4. Design system

Tokens live in `scripts/dashboard_repair/theme.css`, injected last by
`scripts/dashboard_repair/apply.py`. The legacy variable names (`--navy`,
`--ink`, `--panel` and so on) are remapped there, so base-page rules inherit
the theme.

| Role | Token | Value |
| --- | --- | --- |
| App background | `--mw-bg` / `--mw-bg-top` | `#0a0f15` / `#0f1720` |
| Panel / raised / hover | `--mw-panel` / `-2` / `-3` | `#111922` / `#16202b` / `#1c2835` |
| Hairline / strong line | `--mw-line` / `--mw-line-strong` | `#233140` / `#34475b` |
| Text / secondary / muted / faint | `--mw-ink` / `-2` / `--mw-muted` / `--mw-faint` | `#e7edf3` / `#c4d0db` / `#93a5b6` / `#6f8294` |
| Accent / focus | `--mw-accent` / `--mw-focus` | `#5ea8e4` / `#9fd0ff` |
| Gain / loss | `--mw-pos` / `--mw-neg` | `#43b883` / `#f07a72` |
| Caveat / failure / info | `--mw-warn` / `--mw-bad` / `--mw-info` | `#e5a83f` / `#f07a72` / `#5ea8e4` |
| Temperature cold → hot | `--mw-cold` … `--mw-hot` | `#4f8fd0 #74b6dc #8e9ba8 #e39d3e #ea6552` |

Type: Inter/system stack; `--mw-fs-micro` 11 px (uppercase labels only),
`--mw-fs-meta` 12.5 px, body 14 px, titles 16 px, KPI 22 px, page 26 px.
Numbers use `font-variant-numeric: tabular-nums`. Raw identifiers use the
monospace stack.

Shared classes (defined in `theme.css`; reuse them, don't fork them):

- `.mw-chip` plus `--ok | --warn | --bad | --info`: status badge, always with text.
- `.mw-asof`: date or vintage label.
- `.mw-label`: uppercase micro label.
- `.mw-num`: tabular numerals.
- `.mw-up | .mw-down | .mw-flat`: signed change colour. Always pair with a sign or arrow.
- `.mw-raw`: raw identifier or diagnostic text.

Status vocabulary (use exactly these words):

| State | Chip | Meaning |
| --- | --- | --- |
| Official close / completed daily | `ok` "Official close" | dated prior-close observation; not live |
| Stale | `warn` "Stale" | older than its expected cadence |
| Carried forward | `warn` "Carried forward" | latest verified vintage reused; no new release |
| Unavailable | `bad` "Unavailable" | missing; never back-filled |
| Restricted | `warn` "New risk restricted" | trading permission gate |
| Research only | `info` "Research only" | not a book instruction |

Never use the word "live" for any figure on this site.

## 5. Workstreams and file ownership

Workers share one checkout and own disjoint files. Each builds into its own
directory:

```bash
python3 scripts/visual_qa/build_site.py --from-checkpoint /tmp/qa/checkpoint \
  --market-state /tmp/qa/market-state.json --site-dir _site_<name>
python3 scripts/visual_qa/capture.py --serve _site_<name> /tmp/qa/<name> [--full] [--only=front]
```

| Workstream | Model | Owns |
| --- | --- | --- |
| W1 Front + Country | Grok 4.7 | `scripts/dashboard_repair/{apply,tape,scoreboard,brief}.py`, `scripts/country_detail/{render,present}.py`, `scripts/country_detail/country_detail.css`, `scripts/apply_country_detail.py`, related tests |
| W2 Trader Book + PM | Grok 4.7 | `patch_v13/*`, Trader Book/PM dashboard tests |
| W3 Design system + Market Data / Releases / Sources | Composer 2.5 | `scripts/dashboard_repair/theme.css` (below the token block), `scripts/dashboard_repair/{calendar_view,sources_view}.py`, `patch_v12/market_data.css`, presentation tests (merged into `tests/test_dashboard_repair.py`, which CI already runs) |
| V Independent verification | Composer 2.5 | read-only review against §6 |
| I Integration | Composer 2.5 (planned Grok 4.7; the repository subagent hook rejected that slug) | fixes from V; full build; tests |

## 6. Acceptance criteria (design QA)

1. On the laptop Front first screen, a reader can name the biggest score
   impulse, a fresh post-freeze print, the largest market move, and the
   score-freeze date without scrolling past the brief.
2. No undated September figure is visible by default on Front or Country.
3. No raw error dump, URL list or Python repr is visible by default. All of
   them are still reachable in a disclosure.
4. Every number in the brief, tape and score board carries a unit and a date
   or vintage.
5. Country tiles show LEVEL and IMPULSE as visibly different elements, with
   the score as-of date.
6. Trader Book: fleet P&L, risk used, winners and losers, and fleet-level
   flags are on the first laptop screen. The seat table sorts and filters
   with keyboard and mouse. A seat's thesis, invalidation and positions open
   in one interaction. Seat and PM totals equal the BEFORE build exactly.
7. Zero horizontal page overflow at 390, 1440 and 1920 px on every tab.
8. Visible focus ring on every interactive element. All state is conveyed by
   text as well as colour.
9. All existing CI greps in `deploy-pages.yml` and all existing tests pass.
   Six countries, existing tabs and removed tabs (Feed, Relative, Trader Room)
   stay as they are.

## 7. Change inventory

Presentation only. Score math, data contracts, JSON sidecars, trading and
portfolio logic, source pipelines and workflows are unchanged.

| Area | Files | Change |
| --- | --- | --- |
| Design tokens | `scripts/dashboard_repair/theme.css` | `--mw-*` colour, type, spacing and status tokens. Shared chips, as-of stamps, numeric and raw-disclosure classes. Nav, focus ring, tables, panels, print and reduced-motion. Mobile nav wraps to two rows. |
| Front header and brief | `scripts/dashboard_repair/apply.py`, `brief.py` (new) | Dated header with the score-freeze date. Desk brief: largest score impulses, prints released after the freeze, largest rates moves (bp) and FX moves (%) as separate lists, and caveats. Undated September panels fenced in a labelled "archived" disclosure. |
| Market tape | `scripts/dashboard_repair/tape.py` | Compact cards with unit, change and date. Series with no change field say so and are left out of rankings. Source detail moved into a disclosure. |
| Score board | `scripts/dashboard_repair/scoreboard.py` | LEVEL and IMPULSE matrix per country and dimension, with the as-of date. Values are read straight from `temperature_scores.json`. |
| Country Detail | `scripts/apply_country_detail.py`, `scripts/country_detail/{render,present}.py`, `country_detail.css` | September hero and momentum fenced as a stale snapshot. Policy and Transmission stay visible. Plain series names with a short transformation mark (`· m/m`, `· y/y`). Raw codes moved into Technical detail. |
| Trader Book and PMs | `patch_v13/trader-book.js`, `trader_book.css`, `trader_book_page.html` | Fleet KPIs (P&L, risk used, best and worst seat, drawdown, funding). Fleet flags aggregated by type, with shared failures stated once. Sortable and filterable seat and PM tables with drawers. Latest dated tickets first, full history collapsed. Instrument names humanised (`USD/CAD`, `SOFR Sep 2027`). |
| Market Data | `patch_v12/market_data.css` | Dark workstation surfaces. Mobile rows stack. |
| Releases | `scripts/dashboard_repair/calendar_view.py` | Compact release rows with status chips and their definitions. |
| Sources | `scripts/dashboard_repair/sources_view.py`, `apply.py` | Human series names (display only, so the `source-health.json` contract is unchanged). Status chips with definitions. Raw errors and URLs moved into disclosures. |
| Visual QA tooling | `scripts/visual_qa/{build_site,capture}.py` | Local copy of the Pages build, with a fast offline replay, and Playwright captures at 1920, 1440 and 390 px. |
| Tests | `tests/test_dashboard_repair.py`, `tests/test_pm_dashboard.py`, `tests/test_country_detail_{present,render}.py`, `tests/trader_book_{presentation,ui_smoke}.js` | Presentation assertions added to modules CI already runs. No new workflow or job. |

## 8. Final QA results

- Data parity with BEFORE: `source-health.json`, `trader-books.json`,
  `pm-books.json`, `trader-room.json` and `market-state.json` are
  byte-identical. `release-calendar.json` differs only in schedule-fetch
  metadata, because the offline replay skips the live fetch.
- Trader and PM fleet totals ($16.1k and $1.01m) match BEFORE, as do all 14
  seats. All 24 score-board cells equal `temperature_scores.json`.
- Zero horizontal overflow and zero page errors on all 11 views at 1920,
  1440 and 390 px. BEFORE had 276 px of overflow on iPhone Front and 235 px
  on Sources.
- The full CI-equivalent build (`scripts/visual_qa/build_site.py`, with
  workflow tests and the live schedule fetch) ends in `BUILD OK`. The
  targeted unit modules and `node --check` pass.
- Three test failures exist on `main` (239b3e60) without this change:
  `test_country_detail_prima_pressure` ×2 and `test_country_detail_travel`
  (`au_household_spending`). They come from data drift, are not run by the
  Pages workflow, and are left unchanged.
- §6 acceptance criteria 1–9 pass on the final captures.

Known limits: cross-asset series have no change field in the packet, so
they show "Change not in packet" rather than a computed move. Score values
are as of the 21 Sep 2026 freeze and are labelled that way. No fresher score
is implied.
