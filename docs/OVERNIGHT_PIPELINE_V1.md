# Market Watch — Overnight Production Pipeline V1

Status: LIVE · ACP SCHEDULE ENABLED

This is the technical contract for the unattended Market Watch morning pipeline. GitHub owns deterministic work. ACP owns every recurring model/provider clock. Market Watch never stores a Cursor credential and never invokes Cursor directly.

## 1. Ownership

| Concern | Owner |
| --- | --- |
| Deterministic collection, snapshots, book mechanics, validation, assembly, Pages | Market Watch GitHub Actions |
| Recurring model/provider launch | ACP scheduled dispatch |
| Provider authentication / model dispatch / provider-call accounting | ACP |
| Research + 14 structured trader decisions | Cursor launched by ACP |
| Optional Swinger / Pragmatist / Grinder PM decisions | Cursor launched by ACP only when the approved schedule explicitly includes the PM layer |
| ChatGPT PM decisions | ChatGPT via the data-only PM decision ingest contract |
| Canonical trader + PM books and P&L | Market Watch deterministic code |
| Website publication | Market Watch GitHub Actions |

The on-demand adversarial Trader Room now ends with three independent model PMs after the 14-seat debate; ChatGPT remains a separate fourth PM. The nightly portfolio review is a separate workflow. The currently approved ACP schedule still runs only the locked 14 trader seats; PM-enabled nightly execution is supported by the target repository but is not active until the ACP schedule is explicitly changed.

## 2. Nightly sequence

All times are America/New_York.

| Time/event | Owner | Work |
| --- | --- | --- |
| 00:07 | Market Watch | deterministic collect + live market-state snapshot |
| 01:40 | Market Watch | deterministic pre-trader delta |
| 01:50 | Market Watch | freeze trusted base evidence packet + prior books |
| 02:05 | ACP | one approved scheduled Cursor parent |
| provider run | Cursor via ACP | current approved contract: bounded research -> final packet/hash -> 14 direct trader children -> one structured output PR; target also supports an explicitly approved 3-PM extension |
| PR event | Market Watch | validate data-only output, simulate deterministic book application, append generated state, merge |
| 03:35 | Market Watch | final deterministic market delta |
| 03:50 | Market Watch | assemble canonical morning dataset |
| 04:07 | Market Watch | final publication gate |
| 04:15 | Market Watch | GitHub Pages release |

There is no assumed provider completion clock. The scheduled-output PR is the completion event. If it is absent or rejected before assembly, the website may publish the last successful trader books with explicit stale status.

## 3. Run identity

Every night uses:

```
overnight-YYYYMMDD
```

The date is America/New_York. Deterministic artifacts live under:

```
data/overnight/runs/<run_id>/
```

The 01:50 base packet is `evidence_snapshot.json` and has a SHA-256. The ACP/Cursor result must reference that exact base hash.

## 4. ACP/Cursor output boundary

The provider may submit only:

```
data/overnight/inbox/<run_id>/scheduled_output.json
```

The scheduled-output PR must be data-only. Market Watch does not execute code from the provider branch.

The JSON contains:

- schedule id and run id;
- trusted 01:50 `base_packet_sha256` and `base_evidence_cutoff`;
- a research-enriched final agent packet, its later final `evidence_cutoff`, and its hash;
- exactly 14 structured seat decisions;
- optionally, exactly three PM decisions for Swinger / Pragmatist / Grinder when the PM-enabled schedule contract is active;
- declared model-usage/cap fields.

It must not contain canonical books, NAV, cash, realized/unrealized P&L, funding charges, net P&L, or competition rank.

## 5. Model policy and hard budget

Approved runtime models:

- `grok-4.6`
- `composer-2.5`

Prohibited:

- Cursor Auto
- every model outside those two
- Cursor Other Models usage

Current approved schedule caps:

- total model calls: 18
- Grok 4.6 calls: 16
- Composer 2.5 calls: 2

Target-repository support for the future three-PM extension is exact and separate:

- `pm_layer: 3`
- total model calls: 21
- Grok 4.6 calls: 19
- Composer 2.5 calls: 2

The PM-enabled variant is not standing authorization; ACP must be explicitly updated before it may run.

The ACP parent counts as total=1 / Grok=1 before any child starts.

`.cursor/hooks/enforce-overnight-budget.py` atomically reserves every `subagentStart` before launch. It blocks a spawn that would exceed any cap. Once an overnight root is active, only that root conversation may spawn children; grandchildren are denied.

`.cursor/hooks/enforce-subagent-models.sh` separately enforces the exact per-run ACP model allowlist.

The approved graph is normally:

- 1 Grok parent;
- 1 Composer research worker;
- 14 Grok trader seats;
- up to one spare Grok and one spare Composer call within the hard caps.

Caps never expand automatically.

## 6. Frozen trader boundary

Research happens before the final agent packet is frozen.

Every trader child must receive:

```
MW_TRADER_FROZEN=1
```

and the same final packet/hash. `.cursor/hooks/enforce-overnight-runtime.py` blocks tool use for those children. They may not browse, read files, run shell, use MCP, or launch nested agents.

Each seat returns structured decisions only:

`OPEN / ADD / HOLD / REDUCE / HEDGE / CLOSE`

The 14 seats are competing portfolio managers. Their standing objective is **highest cumulative net paper P&L**, not highest conviction score, most cautious commentary, or most persuasive prose. Every child receives the same frozen competition contract:
- ranking metric: net paper P&L after financing economics;
- the 13 seats other than `no-trade-skeptic` each borrow the full **$100m** allocation and pay **5.00% per year, simple ACT/365** on that full amount every day, whether deployed or flat;
- `no-trade-skeptic` is the cash hurdle: it pays no borrowing charge and earns **5.00% per year ACT/365** on the undeployed portion of its original $100m allocation;
- when the skeptic deploys $X of notional, that $X stops earning the cash yield for as long as it remains deployed;
- therefore a flat active trader has negative carry while a flat skeptic earns the risk-free hurdle;
- no-trade remains valid for every seat, but inactivity is economically costly for the 13 funded traders;
- a trader should put on risk when expected edge clears the hurdle and has a defined invalidation. It must not manufacture a trade merely to avoid being flat.

The dedicated spot seats remain spot-only. Rates-capable seats compare a rates candidate and a spot candidate before adding risk. Options remain last-resort.

## 7. Deterministic acceptance gate

`.github/workflows/overnight-scheduled-output.yml` uses `pull_request_target` so the gate runs trusted code from `main`, not provider-authored code.

The gate:

1. requires a same-repository PR titled `[overnight-output] ...`;
2. requires exactly one provider-authored file at the scheduled-output inbox path;
3. downloads that JSON without checking out provider code;
4. verifies run id, schedule id, base packet hash, final packet hash, 14 seats, evidence cutoff and model policy;
5. rejects any model-supplied book/P&L/NAV state;
6. deterministically simulates `apply_review()`;
7. runs the overnight tests;
8. generates canonical books/P&L/run artifacts from trusted code;
9. appends only those generated files to the PR branch;
10. squashes and merges the accepted PR.

A failed gate does not mutate canonical books.

## 8. Persistent paper books

Paper-mid convention:
- paper books **enter, add, reduce and exit at the deterministic mid/reference level in the frozen Market Watch packet**. A broker-executable bid/offer is not required for paper trading;
- these values are stored with explicit paper/reference provenance and must never be described as executable prices;
- model-supplied transaction prices are ignored when a deterministic packet mid exists. The model chooses instrument, direction, structure and size; trusted code owns the transaction mark;
- existing positions are re-marked from the newest deterministic market-state packet before P&L is calculated;
- spot FX uses the same-fixing ECB cross; outright sovereign rates use the official yield observation; cross-market RV/curve trades use deterministic spread mids;
- the primary tradable short-rate curves are SOFR via CME `SR3`, CORRA via MX `CRA`, and AONIA via ASX `IB`; direct contracts are marked in implied-rate space;
- the curve family and construction used at OPEN are stored on the position and replayed for every ADD/REDUCE/CLOSE and daily re-mark. An open bond trade never migrates onto SOFR/CORRA/AONIA and a futures-curve trade never migrates onto a government curve;
- derived curve expressions are allowed when every source leg is present in the frozen packet. Linear spreads/flies are deterministic combinations of source legs; futures-curve forward windows/fwd-fwds use `futures_strip_average` with explicit expiries and optional positive weights;
- `official_curves` remains supplemental government zero/forward data for explicitly selected bond-curve expressions. It is not required to synthesize a swap/OIS curve, and swap-spread trading remains out of scope until both legs are deliberately supported;
- an advocate may use its permitted research/subagent capacity to choose a construction, but canonical entry/exit/P&L math is always replayed deterministically from the stored frozen-source expression;
- if a required source leg is missing, that expression is not paper-tradeable. Options likewise remain blocked until the packet contains the premium/IV/strike data needed to mark them.

Rates quote-unit rule:
- outright `rates` marks are stored in **percentage points** (for example, 4.76 means 4.76%); therefore 1bp = a 0.01 mark move;
- `curve` and `rates_rv` marks are stored directly in **basis points**; therefore 1bp = a 1.00 mark move;
- the book engine converts those units before P&L, so under its simplified duration-1 convention a 1bp favorable move on $100m is $10,000 for either representation.

Each seat starts at $100m paper NAV.

Canonical mechanics are implemented only by `scripts/overnight/books.py`:

- position creation/resizing/closing;
- freshness blocks;
- marks;
- realized/unrealized gross P&L;
- 5% annual funding accrual on the full $100m allocation for the 13 funded trading seats;
- 5% annual cash yield on the skeptic's undeployed allocation;
- net P&L after funding/cash yield and competition rank;
- NAV;
- history;
- overnight changes.

Canonical file:

```
data/overnight/books/latest.json
```

No model may calculate or author this file.

## 9. Four PM books

The PM layer sits above the 14 Trader Room seats and has four independent books:

- **ChatGPT PM** — unrestricted synthesis; no requirement to trade.
- **The Swinger** — aggressive concentration/high utilization; `HEDGE` is prohibited, so weakened risk is reduced or closed.
- **The Pragmatist** — takes large asymmetric bets when available and compounds smaller opportunities otherwise.
- **The Grinder** — prioritizes consistency and drawdown avoidance; small repeatable edges and unused capacity are acceptable.

Each PM has a hard **$1bn gross-notional ceiling**. This is not a borrowed-NAV funding game: PM performance is paper trade P&L, and idle capacity does not earn a synthetic hurdle.

PM output is untrusted decision data only. Models/chat may choose `OPEN / ADD / HOLD / REDUCE / HEDGE / CLOSE`, instrument, side, structure, notional, thesis and invalidation. Trusted code in `scripts/pm_layer.py` owns entry/exit marks, locked curve construction, realized/unrealized P&L and the gross-risk limit.

Canonical PM state:

```
data/pm/books/latest.json
```

At 03:50 the deterministic assemble stage re-marks every open PM position from the newest market-state packet and persists those marks even when no PM changes risk. The Trader Book webpage publishes all four PM books.

Independent PM decision ingest uses a same-repository data-only PR titled `[pm-decision] ...` containing one file under:

```
data/pm/inbox/<review_id>/pm_decisions.json
```

`.github/workflows/pm-decision-output.yml` validates the source packet/hash, rejects model-authored pricing/P&L/book state, applies trusted marks, appends canonical PM books and merges.

## 10. Freshness and publication

Required families for OPEN/ADD: macro hard data, news, market state.

- stale/missing/unavailable required evidence blocks OPEN/ADD;
- HOLD/REDUCE/CLOSE remain available;
- invalid macro/news fails publication closed;
- missing/failed nightly trader output does not block the website: last successful books publish as stale.

## 11. Morning dataset and UI

At 03:50 Market Watch assembles one canonical dataset containing:

- deterministic core evidence/freshness;
- overnight ACP research supplement when accepted;
- deterministic trader books/P&L;
- four deterministically marked PM books/P&L;
- publication decision;
- run ledger.

The existing front page is preserved. The additive Trader Book tab shows the four $1bn PM books first, then the 14 trader-seat books, P&L, overnight position changes and accepted overnight research.

## 12. Dry-run

```bash
PYTHONPATH=. python3 -m unittest \
  tests.test_overnight_pipeline \
  tests.test_overnight_scheduled_output \
  tests.test_pm_layer -v

PYTHONPATH=. python3 scripts/overnight_pipeline.py dry-run --suffix ci
```

Dry-run consumes zero model calls.

## 13. ACP schedule contract

ACP remains the only place where the real 02:05 schedule may be enabled. The target job must use:

- id: `market-watch-weekday-0205`
- timezone: `America/New_York`
- weekdays: Mon-Fri
- time: `02:05`
- provider: Cursor
- parent model: `grok-4.6`
- allowed subagent models: `composer-2.5`, `grok-4.6`
- `max_attempts: 1`
- target: `McCabeAI/market-watch-public-dashboard`
- starting ref: `main`
- delivery: PR
- title prefix: `[overnight-output]`
- provider-authored target path: only `data/overnight/inbox/<run_id>/scheduled_output.json`
- run policy marker:

```
MW_OVERNIGHT_RUN_POLICY={"version":1,"schedule_id":"market-watch-weekday-0205","total_model_cap":18,"grok_cap":16,"composer_cap":2,"parent_model":"grok-4.6","parent_total":1,"parent_grok":1}
```

The parent must perform research first, freeze the final packet, then launch the 14 direct trader children. It must not update books/P&L and must not launch grandchildren.

The schedule is enabled on ACP `main` as `market-watch-weekday-0205` under Kevin's prior explicit approval. Its current committed definition is the 14-seat 18/16/2 contract above. The target repository is ready for the exact 21/19/2 three-PM variant, but changing ACP to that definition is a material schedule change and therefore requires Kevin's current explicit ACP/control-plane authorization. Ad hoc runs, retries, follow-ups or model substitutions also require fresh authorization.

## 14. Persistence and the Supabase boundary

Shipped durable state is git JSON under `data/overnight/`. That is intentional. Market Watch does not require a new paid service or a Kevin-maintained store.

The existing Supabase path (`docs/SUPABASE_PERSISTENCE_V1.md`, `SUPABASE_DB_URL`, `scripts/persist_market_watch.py`) is a public-feed writer. It is not credentialed or scoped for unattended overnight books, and this pipeline does not block on it.

Migration boundary, when a least-privilege overnight writer exists:

1. Keep `data/overnight/` as the audit snapshot written by Actions.
2. Mirror the same JSON objects into private `market_watch` tables.
3. Do not make the public dashboard query Supabase directly.
4. Do not store secrets, paid research, or raw evidence pointers in git or in the public `trader-books.json`.
