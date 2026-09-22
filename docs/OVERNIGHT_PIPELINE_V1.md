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
| provider run | Cursor via ACP | bounded research -> final packet/hash -> 14 direct trader children -> 3 automated PM children (swinger, pragmatist, grinder) -> one structured output PR |
| PR event | Market Watch | validate data-only output, simulate deterministic book application, append generated state, merge |
| 03:35 | Market Watch | final deterministic market delta |
| 03:50 | Market Watch | assemble canonical morning dataset |
| 04:07 | Market Watch | final publication gate |
| 04:15 | Market Watch | GitHub Pages release |

The deterministic times above are **logical deadlines**, not assumptions that a single GitHub cron delivery will be punctual. GitHub scheduled events are redundant wake-ups. Each wake-up runs `overnight_pipeline.py reconcile`, which catches up every due missing deterministic stage in order and never synthesizes the ACP-owned trader review. Critical pre-02:05 wake-ups include 01:50, 01:55, and 02:00 ET so a delayed earlier cron can still persist the trusted freeze before provider launch.

The 02:05 provider must find the current run's `run.json` and the open review's `evidence_snapshot.json` already committed on its starting ref with `freeze_evidence.status == "succeeded"`. The open review is the latest `frozen` or `accepting` row in `reviews/index.json` (or the latest accepted review when no open review exists). If that trusted freeze is absent or invalid, the provider stops before child/model spend and opens no output PR. It may never regenerate the trusted base freeze locally.

There is no assumed provider completion clock. The scheduled-output PR is the completion event. If it is absent or rejected before assembly, the website may publish the last successful trader books with explicit stale status.

## 3. Session identity and review identity

Every night uses one immutable session id:

```
overnight-YYYYMMDD
```

The date is America/New_York. That id is the deterministic scheduling contract. It is not a decision-cycle id. A session can contain more than one Trader Room / automated-PM review. Each review has its own immutable `review_id`, allocated only by trusted repository code:

```
review-001
review-002
```

Review ids are sequential inside the session, zero-padded, and stable across retries of the same unaccepted review. A later cycle does not reuse an accepted review id and does not overwrite an earlier review. Kevin does not invent the id. The scheduled morning freeze creates `review-001` when the session has no open review. A fresh intraday cycle is opened with:

```
PYTHONPATH=. python3 scripts/overnight_pipeline.py open-review --run-id overnight-YYYYMMDD
```

That command freezes a new review from the current canonical books and the session's collected evidence. It does not apply trader or PM decisions and does not call models.

Session artifacts that are shared by every review stay directly under the session:

```
data/overnight/runs/<overnight_run_id>/run.json
data/overnight/runs/<overnight_run_id>/collect.json
data/overnight/runs/<overnight_run_id>/pre_trader_delta.json
data/overnight/runs/<overnight_run_id>/final_delta.json
data/overnight/runs/<overnight_run_id>/assembled_dataset.json
data/overnight/runs/<overnight_run_id>/reviews/index.json
```

Review-scoped artifacts are immutable once frozen and live only under that review:

```
data/overnight/runs/<overnight_run_id>/reviews/<review_id>/review.json
data/overnight/runs/<overnight_run_id>/reviews/<review_id>/evidence_snapshot.json
data/overnight/runs/<overnight_run_id>/reviews/<review_id>/memory/
data/overnight/runs/<overnight_run_id>/reviews/<review_id>/pm_memory/
data/overnight/runs/<overnight_run_id>/reviews/<review_id>/agent_evidence_packet.json
data/overnight/runs/<overnight_run_id>/reviews/<review_id>/scheduled_output.json
data/overnight/runs/<overnight_run_id>/reviews/<review_id>/trader_review.json
```

`review.json` is the durable identity record. It stores `overnight_run_id`, `review_id`, status (`allocating` → `freezing` → `frozen` → `accepting` → `accepted`), and the canonical trader-book and PM-book SHA-256 captured at freeze. Status becomes `accepted` only after review artifacts and canonical book writes succeed. A partial review never looks accepted.

The 01:50 base packet is that review's `evidence_snapshot.json` and has a SHA-256. The ACP/Cursor result must reference that exact base hash and the frozen `review_id`. Acceptance rejects the output when either id does not match, when the review's starting trader-book or PM-book hash is not the current canonical file hash, or when a later review in the same session is already accepted. Replaying an already accepted review is a no-op. Journal and trade provenance store both `overnight_run_id` and `review_id`; idempotency keys on `review_id`, so a later distinct review may update the evolving books.

### Sep 22 migration

`overnight-20260922` was repaired in place without replaying decisions:

| review_id | status | base packet | meaning |
| --- | --- | --- | --- |
| `review-001` | accepted | `e0ad7dbc8b2990648797b41ff138ce05456c4f1340ef08baea106e0782197a41` | Morning review recovered from git `c89f1f4`. Agent packet `21a1ec3c722518819f9418afe972e4d7933baf6268e2983b68f3036a69dff2f1`. |
| `review-002` | frozen, not accepted | `5c69096c72b8567b8dfde193168b7ff0185332ca2f10fca42b77e5d4508b2619` | 11:28 ET evidence refresh (`2026-09-22T11:28:31.273278-04:00`). No scheduled output and no decisions. |

The morning snapshot did not store `prior_pm_books`. That gap is recorded on `review-001` and `review-002`; those historical hashes are embedded-snapshot bindings, not canonical-file bindings, so they cannot be accepted again. Canonical trader books, PM books, NAV, positions, P&L, funding, and risk state were not rewritten. After this change is merged, the next intraday cycle is a new review from then-current levels:

```
PYTHONPATH=. python3 scripts/overnight_pipeline.py open-review --run-id overnight-20260922
```

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

It must not contain canonical books, NAV, cash, realized/unrealized P&L, funding charges, net P&L, competition rank, or model-authored ledger/P&L facts. Structured postmortems and memory updates are allowed; trusted code validates them.

**`pm_decisions` is required** (not optional). It must contain exactly `swinger`, `pragmatist`, and `grinder` (never ChatGPT) with `principal_model`, `subagent_count` 0–3, and `subagent_models` in `{grok-4.6, composer-2.5}`. Absence or partial roster is invalid and rejects the scheduled-output PR. ChatGPT remains ingest-only and is excluded from automated overnight current-cycle decisions. Parent orchestration contract: `.cursor/commands/overnight-scheduled.md`.

## 5. Model policy and hard budget

Approved runtime models:

- `grok-4.6`
- `composer-2.5`

Prohibited:

- Cursor Auto
- every model outside those two
- Cursor Other Models usage

Run caps (**target-repo contract** enforced by `.cursor/hooks/enforce-overnight-budget.py`):

- total model calls: **19**
- Grok 4.6 calls: **18**
- Composer 2.5 calls: **2**

The ACP parent counts as total=1 / Grok=1 before any child starts.

The enabled ACP `market-watch-weekday-0205` schedule uses the matching **19 / 18 / 2** contract. No Sunday clock or second provider schedule exists. ChatGPT remains excluded from automated current-cycle PM execution.

`.cursor/hooks/enforce-overnight-budget.py` atomically reserves every `subagentStart` before launch. It blocks a spawn that would exceed any cap. Once an overnight root is active, only that root conversation may spawn children; grandchildren are denied.

`.cursor/hooks/enforce-subagent-models.sh` separately enforces the exact per-run ACP model allowlist.

The approved graph is:

- 1 Grok parent;
- 1 Composer research worker;
- 14 Grok trader seats;
- 3 Grok automated PM principals (swinger, pragmatist, grinder custom agents);
- **19 / 18 / 1** declared usage: 1 Grok parent + 14 Grok traders + 3 Grok PM principals + 1 Composer research.

Caps never expand automatically.

## 6. Frozen trader boundary

Research happens before the final agent packet is frozen.

Every trader child must receive:

```
MW_TRADER_FROZEN=1
```

the same final common packet/hash, and **only that trader's own frozen memory sidecar / `memory_context_sha256`**. The review freeze writes per-seat hashes on `evidence_snapshot.seat_memory.hashes` and sidecar files under `data/overnight/runs/<overnight_run_id>/reviews/<review_id>/memory/`. Common macro evidence stays identical. One seat's private learning context is never given to another seat. See `docs/TRADING_LEDGER_MEMORY_V1.md`.

`.cursor/hooks/enforce-overnight-runtime.py` blocks tool use for those children. They may not browse, read files, run shell, use MCP, or launch nested agents.

Automated PM children use the same evidence-closed boundary with `MW_PM_FROZEN=1`. They receive the frozen packet, the accepted 14 trader decisions, and only their own PM memory sidecar. They may not browse, read files, run shell, use MCP, or launch nested agents.

Each seat returns structured decisions only:

`OPEN / ADD / HOLD / REDUCE / HEDGE / CLOSE`

Each accepted decision should include the `memory_context_sha256` it used. Risk-expanding `OPEN` / `ADD` / `HEDGE` fail closed on a missing/stale own-seat memory hash or outstanding prior-run `postmortems_due`. `HOLD` / `REDUCE` / `CLOSE` remain possible on memory failure. Canonical ledger, journal, and memory updates are produced by trusted code after acceptance and persisted under `data/trading/`.

The 14 seats are competing portfolio managers. Their standing objective is **highest cumulative net paper P&L**, not highest conviction score, most cautious commentary, or most persuasive prose. Every child receives the same frozen competition contract:
- ranking metric: net paper P&L after financing economics;
- every seat starts with **$100m paper NAV**. Official NY Fed SOFR ACT/360 is the zero-return benchmark: paper NAV may be described as earning SOFR, but it is equally funded/benchmarked at SOFR so those flows cancel;
- every open position consumes trusted **standard-shock risk capital** equal to the absolute MTM loss from the standard adverse move: 1% spot, 100bp outright rates, or 100bp curve/RV; equal risk capital is financed identically across asset classes;
- official SOFR ACT/360 is charged on shocked risk capital, not notional. A completely flat book therefore has zero net financing/competition P&L;
- each seat has a **$10m shocked-risk-capital ceiling** and a **$5m high-water-mark drawdown stop**. A breach triggers trusted-code forced flattening and blocks new OPEN/ADD/HEDGE while risk-stopped;
- `no-trade-skeptic` has no special cash-manager subsidy; when flat its shocked risk capital is simply zero and its competition P&L from financing is zero. Every fresh scheduled skeptic decision, including `HOLD`, still includes a structured `funding_view`;
- no-trade remains valid for every seat; a flat book has no net SOFR alpha, while open risk pays the SOFR hurdle on shocked-risk capital;
- a trader should put on risk when expected edge clears the hurdle and has a defined invalidation. It must not manufacture a trade merely to avoid being flat.

The dedicated spot seats remain spot-only and are not forced through a rates tenor scan. `vol-convexity` retains its options remit. Every other rates-capable seat must complete a STIR/2Y/5Y/10Y/curve/cross-market-RV scan before selecting its best rates candidate and comparing that candidate with spot. Options remain last-resort.

## 7. Deterministic acceptance gate

`.github/workflows/overnight-scheduled-output.yml` uses `pull_request_target` so the gate runs trusted code from `main`, not provider-authored code.

After a successful 14-seat apply, trusted code applies the three automated PM decisions independently, then refreshes the four daily PM review packets from that overnight run's frozen agent packet, accepted trader decisions, research supplement, market state, and canonical books. This is not a second model clock and does not require an on-demand Trader Room run.

The gate:

1. requires a same-repository PR titled `[overnight-output] ...`;
2. requires exactly one provider-authored file at the scheduled-output inbox path;
3. downloads that JSON without checking out provider code;
4. verifies run id, schedule id, base packet hash, final packet hash, 14 seats, **required `pm_decisions` for swinger/pragmatist/grinder**, evidence cutoff and model policy;
5. rejects any model-supplied book/P&L/NAV state;
6. deterministically simulates trader + automated PM `apply_review()` transactionally;
7. runs the overnight tests;
8. generates canonical trader books, **three automated PM books**, P&L/run artifacts and `data/trading/**` from trusted code;
9. appends only those generated files to the PR branch;
10. squashes and merges the accepted PR.

Missing or invalid PM output rejects the PR. Last trusted canonical state is retained. Publication may still show explicit stale/failed PM status when the deterministic morning path runs without a successful provider cycle. A failed gate does not mutate canonical books.

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
- official NY Fed SOFR ACT/360 financing accrual on current standard-shock risk capital for every seat;
- baseline paper-NAV SOFR cash yield matched by an equal SOFR benchmark cost so those flows cancel;
- trusted $10m risk-capital cap, $5m high-water drawdown stop and risk-stop state;
- net P&L after the zero-return SOFR benchmark (trading P&L minus risk-capital financing) and competition rank;
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

The existing front page is preserved. The additive Trader Book tab shows paper books, P&L, overnight position changes and accepted overnight research. Public `trader-books.json` seats and positions always come from the newest canonical `data/overnight/books/latest.json` when present; the assembled morning dataset may overlay `overnight_research` and publication metadata but must not hide newer on-demand book state.

## 11. Dry-run

```bash
PYTHONPATH=. python3 -m unittest \
  tests.test_overnight_pipeline \
  tests.test_overnight_scheduled_output \
  tests.test_pm_scheduled_output \
  tests.test_pm_overnight_packets \
  tests.test_trading_memory -v

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

Target-repo ready marker (hooks/validator in this repository):

```
MW_OVERNIGHT_RUN_POLICY={"version":1,"schedule_id":"market-watch-weekday-0205","total_model_cap":19,"grok_cap":18,"composer_cap":2,"parent_model":"grok-4.6","parent_total":1,"parent_grok":1}
```

Committed ACP `market-watch-weekday-0205` is still **18 / 16 / 2** (ACP commit `f5b75df8`). That live schedule cannot launch 3 Grok-4.6 PM principals after 14 Grok traders without downgrading PM principals or independence. **This repository does not change ACP.** Minimal ACP-only delta required before the weekday job can succeed:

- `total_model_cap` 18 → **19**
- `grok_cap` 16 → **18**
- `composer_cap` remains **2**
- job objective/constraints: after the accepted 14-trader handoff, launch concurrent custom-agent PMs `swinger`, `pragmatist`, and `grinder` (`grok-4.6[]`); ChatGPT excluded; each PM sees the frozen packet + the same 14 decisions + only its own prior book/memory; no nested children
- emit the 19/18/2 policy marker above
- no Sunday clock and no second provider schedule

The parent must perform research first, freeze the final packet, launch the 14 direct trader children, then launch the 3 automated PM children. Each child receives the common frozen packet plus only that child's own frozen memory sidecar. It must not update books/P&L and must not launch grandchildren.

The schedule remains the existing Monday–Friday 02:05 America/New_York occurrence only; ad hoc runs, retries, follow-ups, model substitutions, or other material schedule changes still require fresh explicit authorization.

## 13. Persistence and the Supabase boundary

Shipped durable state is git JSON under `data/overnight/`. That is intentional. Market Watch does not require a new paid service or a Kevin-maintained store.

The existing Supabase path (`docs/SUPABASE_PERSISTENCE_V1.md`, `SUPABASE_DB_URL`, `scripts/persist_market_watch.py`) is a public-feed writer. It is not credentialed or scoped for unattended overnight books, and this pipeline does not block on it.

Migration boundary, when a least-privilege overnight writer exists:

1. Keep `data/overnight/` as the audit snapshot written by Actions.
2. Mirror the same JSON objects into private `market_watch` tables.
3. Do not make the public dashboard query Supabase directly.
4. Do not store secrets, paid research, or raw evidence pointers in git or in the public `trader-books.json`.
