# Trader Room Evidence Contract

This contract is mandatory for every full Trader Room run and supplements `docs/TRADER_ROOM_PROTOCOL.md`. The parent orchestrator builds one common packet before any advocate launches. Every standing advocate receives the exact same completed packet and the same cutoff time.

## Mandatory common inputs

The parent must attempt all four Market Watch evidence families below. It must not silently omit one because another source appears sufficient.

### 1. Temperature gauges and hard-input drill-down

Load the current United States, Canada, Australia and New Zealand 1–100 Temperature Inputs: Inflation, Labor, Activity and Consumer, together with the hard inputs that actually determine each score and the corroborating/contextual evidence shown behind the score.

Use the current score contracts as governing definitions: `docs/LABOR_SCORE_V1.md`, `docs/ACTIVITY_SCORE_V1.md`, `docs/CONSUMER_SCORE_V1.md`, `docs/COUNTRY_SCORE_EVIDENCE_V1.md`, and the applicable inflation score contracts including `docs/US_INFLATION_SCORE_V1.md`. Use current Market Watch operational state/Supabase when available for values and provenance. Do not substitute an old static dashboard score for a current score without marking it stale.

For each score include: country, dimension, score, as-of/vintage, hard inputs with values and weights/contributions where available, contextual/corroborating evidence, source/provenance, and staleness. If a hard input is unavailable, preserve the gap explicitly.

### 2. Central-bank research and Market Watch article/news feed

Load the current Market Watch normalized research/news layer relevant to the run, including the official central-bank publication feed and the project's current article/research classifications. Preserve country/category tags, publication time, source URL/internal evidence ID, summary or retained synthesis, and verification status.

The existing Market Watch feed is the first place to look. Fresh web research may supplement it but must not silently replace it. Official central-bank material should remain distinguishable from commentary. Do not republish paywalled text; use lawful retained synthesis/provenance.

### 3. Market-state packet

Load the freshest valid deterministic market-state snapshot produced under `docs/MARKET_STATE_FEED_V1.md` / `scripts/market_state.py`. Include sovereign rates, curve measures, cross-market relative-value spreads, G10 FX crosses, returns, realized volatility/distribution context, provenance and staleness that are relevant to the run.

The market-state packet must also carry the observable **policy-path layer** for the United States, Canada and Australia: current SOFR/CORRA/AONIA benchmarks and public futures/OIS-implied paths. Australia additionally carries official RBA 1M/3M/6M OIS, bank-bill rates and bill-minus-OIS basis context. Sovereign 2Y/5Y levels do not satisfy this requirement. The packet should also include deterministic historical move analogs with prior episode dates and forward outcomes so advocates can test comparable states rather than merely quote percentiles.

Do not invent missing values. A source explicitly marked unavailable or stale remains unavailable/stale in the common packet.

### 4. Durable empirical research method

Load `docs/TRADER_RESEARCH_METHOD.md` in full and place its method in the common packet under `research_method`. This is a standing reasoning discipline for every advocate, not a directional research input. It captures reusable methodology retained from Bob Elliott / Nonconsensus and David Cervantes / Pinebrook. Advocates must apply the process while remaining free to reach conclusions that disagree with either author.

Do not use current Bob/David trade calls, forecasts or positions as authoritative inputs unless they independently enter the evidence packet as properly sourced current research. Method and current view are separate objects.

## Persistent competition state

Load the current canonical paper books from `data/overnight/books/latest.json` and give every advocate the same competition context: current seat net P&L/rank when available, open risk, and the standing funding contract. The competition metric is cumulative **net paper P&L after financing economics**. Every seat except `no-trade-skeptic` pays 5.00% annual ACT/365 on the full $100m allocation every day whether invested or flat. The skeptic instead earns 5.00% ACT/365 on the undeployed portion of its original $100m and loses that yield on capital it deploys. This is context and incentive, not evidence for a macro thesis. A model must never calculate or overwrite canonical P&L, funding, NAV, or rank.

## Required packet shape

In addition to the existing protocol fields, the common packet must contain these named sections:

```json
{
  "temperature_gauges": [],
  "central_bank_research": [],
  "news_and_research": [],
  "market_state": {},
  "research_method": {},
  "trader_competition": {},
  "source_index": [],
  "known_gaps": []
}
```

The legacy `macro_state`, `rates_and_policy`, `market_levels`, `positioning_and_flow`, and `cross_asset` fields may remain when useful, but they do not satisfy the mandatory sections above by themselves.

## Preflight gate

Before launching any of the 14 advocates, the parent must validate that all four mandatory evidence families were attempted and record one of `available`, `partial`, `stale`, or `unavailable` for each. `unavailable` is allowed when the source genuinely cannot be reached; silent omission is not.

A full debate may proceed with partial/unavailable evidence only when the missing family is not essential to the user question. The gap must be copied into `known_gaps`, and advocate confidence must reflect it. If a missing family is essential to the question, fail before spending the 14-agent run.

The on-demand orchestrator (`scripts/trader_room_go.py`) treats all four families as essential by default and fails loud on `unavailable` before any advocate is charged. It also fails before model spend if any US/CA/AU policy path is unavailable; a full Trader Room may not construct short-end rates or policy-RV ideas from sovereign yields alone. After freeze, no advocate may use web/search or otherwise leave the packet.

Every advocate receives the exact same common packet. No advocate may privately replace a missing mandatory input with an unsupported assumption.
