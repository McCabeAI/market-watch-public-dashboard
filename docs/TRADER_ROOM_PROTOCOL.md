# Trader Room Protocol

## Purpose

Trader Room turns Market Watch evidence into adversarial G10 FX/rates trade proposals. Cursor supplies independent advocates with persistent biases. Cursor does not decide the winner. ChatGPT in the Market Watch Trader Room is the final arbiter.

The normal execution environment is Cursor Cloud and ordinary operation must not require Kevin to open a computer, use a local checkout, or run a terminal. The repository dry-run entrypoint is `scripts/trader_room_go.py`.

## Standing floor

The locked standing advocates are:

1. `perma-bull`
2. `perma-bear`
3. `dollar-king`
4. `cross-merchant`
5. `carry-is-king`
6. `rate-hawk`
7. `rate-dove`
8. `value-guy`
9. `trend-follower`
10. `mean-reverter`
11. `positioning-cynic`
12. `catalyst-junkie`
13. `vol-convexity`
14. `no-trade-skeptic`

All standing advocates use exact model `grok-4.6`. Initial advocates alone may use up to two `composer-2.5` subagents on the same frozen packet. Each advocate receives only its own frozen learning-memory sidecar; the common evidence hash stays identical. See `docs/TRADING_LEDGER_MEMORY_V1.md`.

The production conflict stage and final PM handoff are deterministic. The historical `conflict-aggregator` and `final-aggregator` agent files may remain for compatibility/reference, but neither is launched in the production path. ChatGPT remains the only actual arbiter.

## Expression mandate

The room has a strong preference for rates expressions when the same macro discrepancy can be traded cleanly in rates. This is an expression preference, not a quota and not permission to manufacture a rates trade.

- `dollar-king` and `cross-merchant` are dedicated spot-FX specialists and remain spot-only.
- `vol-convexity` remains the dedicated options/convexity specialist.
- Every other seat is rates-first whenever it submits a trade. It must first construct a concrete interest-rate candidate using outright duration, curve, or cross-market rates RV, then construct the best spot-FX alternative, then compare them.
- Rates are the default choice when the two expressions are comparably clean. A rates-first seat may choose spot only when spot is genuinely the cleaner expression and it explicitly states why the rates candidate is inferior or not executable from the frozen packet.
- A rates-first seat may choose options only when unusually compelling versus both rates and spot and must say why.
- `no-trade-skeptic` may still submit no trade. If it endorses a trade, the same rates-first comparison applies.

Every non-null trade carries `asset_class` and `expression_comparison`. The comparison records a rates candidate, a spot candidate, the selected expression family, and the rationale. Deterministic validation rejects a rates-first submission that skips either candidate.

## Context gate

No seat may move from a screen to risk without reconstructing the market context. Every non-null trade must include a validated `context_build` proving:

- **causal mechanism** — what economic/policy mechanism is being tested;
- **path to current price** — multi-horizon price action and the events/information/flow that got the instrument here;
- **known vs new information** — why a known fact can explain a new move now;
- **market-implied assumption** — what the current price/path already requires to be true;
- **specific disagreement** — the exact priced assumption the trader believes is wrong;
- **price decomposition** — level versus change, relevant tenor/components and marginal driver;
- **historical reference** — distribution plus at least one comparable episode (or an explicit statement that no credible analog exists), forward outcome, and structural/regime differences;
- **independent checks** — at least two distinct datasets/markets/measurement approaches;
- **flow/positioning check** — whether non-fundamental ownership/plumbing can explain the move;
- **policy-path check** — for rates, current overnight benchmark and observable market-implied path before sovereign-curve/RV conclusions.

A statistical extreme is a discovery signal, never sufficient evidence. For a short-end US/Canada/Australia rates trade, deterministic validation rejects the idea if the frozen packet lacks the relevant policy path. A 2Y bond percentile is not a substitute for SOFR/CORRA/AONIA-linked pricing.

## Competition and risk incentive

The standing seats are paper portfolio managers competing for **highest cumulative net P&L** across the persistent Trader Book. Analysis is a means to that outcome, not the score.

- The 13 seats other than `no-trade-skeptic` each borrow their full **$100m** paper allocation and pay the **latest published prior-day official NY Fed SOFR, simple ACT/360**, on that full amount for every newly accrued calendar day in that run. Being flat does not stop the vig. The frozen prior-day fixing is used for the run with no later true-up.
- `no-trade-skeptic` is the benchmark cash manager. It pays no funding charge and earns the same official daily SOFR ACT/360 on the undeployed portion of its original $100m allocation. Any capital it deploys stops earning that yield while deployed.
- Leaderboard P&L is gross realized + unrealized trading P&L, **minus funding for the 13 funded traders or plus undeployed-cash yield for the skeptic**.
- `NO TRADE` remains legitimate. For the 13 funded traders it carries a real opportunity/funding cost; for the skeptic it is the positive cash benchmark. Every fresh scheduled daily no-trade-skeptic decision, including `HOLD`, must include a structured `funding_view` (frozen official SOFR, relevant SR3 forward-curve view, whether realized funding is expected higher/lower/about the same, and the cash-versus-risk implication).
- Traders should not optimize for avoiding mistakes. If the frozen packet shows a tradeable discrepancy whose expected edge clears the observed SOFR hurdle and has a defined invalidation, the seat should be willing to risk paper capital.
- Do not force low-quality trades or invent executable levels. The incentive is to make profitable decisions under uncertainty, not to maximize trade count.
- Funding and leaderboard accounting are deterministic book mechanics. Official NY Fed SOFR is the realized funding authority; SR3 is forward context only. There is no fixed 5% assumption. Advocates may reason about the observed hurdle but may not author or alter canonical P&L, funding charges, NAV, or rank.

## Evidence contract

Every run uses one common frozen evidence packet. All 14 advocates receive the exact same packet and cutoff. After freeze, advocates and rebuttals may not browse, search, fetch, or acquire new evidence; the deterministic finalizer only reads the saved structured artifacts.

The packet follows `docs/TRADER_ROOM_EVIDENCE_CONTRACT.md` and includes current temperature gauges/hard inputs, central-bank and news research, deterministic market state, durable research method, provenance and known gaps. Missing essential evidence must fail closed before the expensive debate.

## Round 1

Launch all 14 standing advocates concurrently and independently. Do not show them one another's work.

Every advocate except `no-trade-skeptic` must return one actionable primary debate trade. The skeptic may return `trade: null`. That single debate trade is not a one-position limit.

Before submitting, each advocate must read only its own frozen memory sidecar/current `open_positions`. Every submission must include a non-empty final `paper_actions` list for its competition book. The list may manage any number of simultaneous positions within the $1m trusted 1%-shock risk-capital ceiling. Existing positions are managed by `position_id`; the advocate should `ADD`, `REDUCE`, `CLOSE`, `HEDGE`, or explicitly `HOLD` rather than opening a duplicate position by default. Notional is descriptive and may exceed $100m when shocked risk remains inside the cap.

Every submission must include the full validated trade schema and a compact `conflict_synopsis` containing:
- one-sentence core view;
- primary trade;
- USD/CAD/AUD/NZD directional views;
- US/CA/AU/NZ rates directional views;
- risk view;
- carry view;
- horizon, catalyst, invalidation, confidence;
- simple machine-readable conflict tags.

The synopsis is not a new analysis. It compresses the completed pitch so conflict detection never needs to reread fourteen long research notes.

## Conflict detection

After Round 1, run deterministic conflict mapping with `scripts/trader_room/conflict.py` or `scripts/trader_room_conflict_map.py`.

The deterministic stage:
- identifies opposite same-instrument directions;
- identifies opposite USD/CAD/AUD/NZD views;
- records theoretical currency-versus-domestic-rates tensions such as CAD higher versus Canada rates lower;
- records risk/carry context tensions;
- preserves the no-trade challenge;
- produces `conflict_map.json` and `rebuttal_assignments.json`;
- consumes zero model calls.

Only **direct conflicts** route an advocate into Round 2. Theoretical/context tensions remain visible in the deterministic final handoff without automatically spending rebuttal calls.

No voting, ranking, confidence weighting, winner selection, or house view.

## Round 2

Each directly conflicted advocate gets exactly one `grok-4.6` rebuttal pass. Give it:
- the unchanged frozen packet;
- its own original pitch;
- its deterministic conflict bundle;
- only the opposing original trades relevant to that bundle.

No subagents and no new evidence.

A rebuttal may defend, amend, or withdraw. It must identify the strongest opposing claim, attack weaknesses, state its defense, preserve uncertainty, and say what would concede the argument. For new live runs the rebuttal also returns the final `paper_actions` list. If it amends the trade, that list replaces the Round-1 book intent. If it withdraws, it may not retain an expanding `OPEN`, `ADD`, or `HEDGE` for the withdrawn idea. Trusted validation fails closed on an amended/withdrawn rebuttal whose final book intent is omitted or contradictory.

## Final handoff

After Round 2, run `scripts/trader_room_finalize.py` against the run directory. Deterministic code reads the 14 validated originals, deterministic conflict map, routed rebuttals, theoretical/context tensions and known gaps, then writes the structured PM handoff and artifact index. This stage consumes zero model calls and performs no new analysis.

Cursor must stop after the handoff.

Cursor must not:
- choose the winning trade;
- produce a house view;
- average agents into consensus;
- score a leaderboard;
- call a trade approved;
- create a surrogate PM/chair;
- persist an official trade decision.

Final marker:

`STATUS: AWAITING_CHATGPT_ARBITRATION`

## Handoff and storage

The authoritative artifact surface is `trader-room/runs/<run_id>/` in the public `market-watch-public-dashboard` repository. Project output never belongs in ACP.

Google Drive folder ID `1NS6Qb6vNGKM18_PW0zPl4NOIJZOLyfUD` remains an optional private Markdown copy. If that optional copy fails after one retry, fail closed for the Drive copy only and preserve the repository artifacts.

## Recovery

If orchestration fails after Round 1, first persist every completed submission and its `conflict_synopsis`. Do not rerun completed traders just to restore state. Resume from deterministic conflict mapping and only then launch required rebuttals/final aggregation.

## ChatGPT arbitration

After the PM handoff exists, ChatGPT rechecks material time-sensitive facts, distinguishes factual from judgmental disagreements, tests the strongest case on each side, and makes the actual long/short/alternative/no-trade decision.
