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
| Canonical books, P&L, NAV | Market Watch deterministic code |
| Website publication | Market Watch GitHub Actions |

The on-demand adversarial Trader Room is unchanged. The nightly portfolio review is a separate workflow that reuses the locked 14 seat identities/remits/models but does not run aggregators, rebuttals, or ChatGPT arbitration.

## 2. Nightly sequence

All times are America/New_York.

| Time/event | Owner | Work |
| --- | --- | --- |
| 00:07 | Market Watch | deterministic collect + live market-state snapshot |
| 01:40 | Market Watch | deterministic pre-trader delta |
| 01:50 | Market Watch | freeze trusted base evidence packet + prior books |
| 02:05 | ACP | one approved scheduled Cursor parent |
| provider run | Cursor via ACP | bounded research -> final packet/hash -> 14 direct trader children -> one structured output PR |
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

Run caps:

- total model calls: 18
- Grok 4.6 calls: 16
- Composer 2.5 calls: 2

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
- spot FX uses the same-fixing ECB cross; outright sovereign rates use the official yield observation; cross-market RV/curve trades use deterministic spread mids; SOFR/CORRA/AONIA-linked futures use the packet's implied-rate mid;
- derived curve expressions are allowed when every source leg is present in the frozen packet. The position stores the expression definition and trusted code recomputes the derived mid on every review;
- supported derived math includes linear curve/spread combinations and forward swaps/fwd-fwds from `official_curves`. US/Canada/Australia official government zero curves are accepted as the close-enough paper proxy for the corresponding swap/OIS curve. For a forward swap, trusted code uses `(P_start - P_end) / sum(alpha_i * P_i)`; compact expressions such as US 2y2y are resolved and re-marked from the frozen official curve;
- an advocate may use its permitted research/subagent capacity to analyze curve construction, but canonical entry/exit/P&L math is always replayed deterministically from frozen source legs;
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

## 9. Freshness and publication

Required families for OPEN/ADD: macro hard data, news, market state.

- stale/missing/unavailable required evidence blocks OPEN/ADD;
- HOLD/REDUCE/CLOSE remain available;
- invalid macro/news fails publication closed;
- missing/failed nightly trader output does not block the website: last successful books publish as stale.

## 10. Morning dataset and UI

At 03:50 Market Watch assembles one canonical dataset containing:

- deterministic core evidence/freshness;
- overnight ACP research supplement when accepted;
- deterministic trader books/P&L;
- publication decision;
- run ledger.

The existing front page is preserved. The additive Trader Book tab shows paper books, P&L, overnight position changes and accepted overnight research.

## 11. Dry-run

```bash
PYTHONPATH=. python3 -m unittest \
  tests.test_overnight_pipeline \
  tests.test_overnight_scheduled_output -v

PYTHONPATH=. python3 scripts/overnight_pipeline.py dry-run --suffix ci
```

Dry-run consumes zero model calls.

## 12. ACP schedule contract to install

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

The schedule is enabled on ACP `main` as `market-watch-weekday-0205` under Kevin's explicit 2026-09-18 approval (ACP commit `f5b75df8`). That committed definition is standing authorization for its normal weekday 02:05 America/New_York occurrences only; ad hoc runs, retries, follow-ups, model substitutions, or other material schedule changes still require fresh explicit authorization.

## 13. Persistence and the Supabase boundary

Shipped durable state is git JSON under `data/overnight/`. That is intentional. Market Watch does not require a new paid service or a Kevin-maintained store.

The existing Supabase path (`docs/SUPABASE_PERSISTENCE_V1.md`, `SUPABASE_DB_URL`, `scripts/persist_market_watch.py`) is a public-feed writer. It is not credentialed or scoped for unattended overnight books, and this pipeline does not block on it.

Migration boundary, when a least-privilege overnight writer exists:

1. Keep `data/overnight/` as the audit snapshot written by Actions.
2. Mirror the same JSON objects into private `market_watch` tables.
3. Do not make the public dashboard query Supabase directly.
4. Do not store secrets, paid research, or raw evidence pointers in git or in the public `trader-books.json`.
