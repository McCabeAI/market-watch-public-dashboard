# Trader Room Protocol

## Purpose

Trader Room turns Market Watch evidence into adversarial FX trade proposals. Cursor supplies independent advocates with persistent archetypal biases. Cursor does not decide the winner. The final arbiter is ChatGPT in the Market Watch Trader Room conversation.

The design objective is productive disagreement. Agents should expose different priors, different preferred expressions, and different reasons a trade can fail. Consensus is not a success condition.

## Standing floor

The standing archetypes are:

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

All standing advocates use Cursor Grok 4.6. They are read-only and run in isolated contexts. They are biased by design. Their bias changes what they search for and how they frame a trade; it does not lower the evidence standard.

Specialists such as commodities/terms-of-trade, balance of payments, fiscal, China, microstructure/execution, or country specialists are not permanent seats yet. Add or summon them only when repeated use proves they are needed.

## Evidence contract

Every run begins with one common evidence packet. Every standing advocate receives the same packet and the same cutoff time.

The parent agent should populate the packet from the best currently available sources:

- Market Watch Supabase operational state, through the project-scoped read-only MCP connection;
- repository technical/research context that is relevant to interpretation;
- current official/public sources and web research for facts that require freshness;
- any private research/methodology that is actually accessible in the current Cursor session;
- user-supplied prices, positions, constraints or hypotheses.

Do not claim access to a source that is not connected. Paid/private research is a first-class input only when its lawful source material or retained synthesis is actually available.

Each evidence item must carry enough lineage to audit it: source name, URL or internal evidence identifier when available, observation/publication time, and verification status when known.

The packet must explicitly list material gaps. Missing data is evidence about confidence, not an invitation to guess.

### Common evidence packet

Use this structure:

```json
{
  "run_id": "UTC timestamp or UUID",
  "as_of": "ISO-8601",
  "topic": "user question / market scope",
  "user_hypothesis": "optional",
  "market_levels": [],
  "macro_state": [],
  "rates_and_policy": [],
  "news_and_research": [],
  "positioning_and_flow": [],
  "cross_asset": [],
  "private_methodology_available": [],
  "source_index": [],
  "known_gaps": []
}
```

## Round 1: independent pitches

Launch all 14 standing advocates in parallel unless the user explicitly requests a smaller floor.

Do not let an advocate see another advocate's Round 1 work before it submits. Independent first passes are required to reduce anchoring.

Each advocate returns exactly one JSON object. No extra prose.

```json
{
  "type": "TRADER_ROOM_CONTRIBUTION",
  "run_id": "...",
  "round": 1,
  "agent": "agent-name",
  "archetype": "short label",
  "stance_summary": "one sentence",
  "trade": {
    "instrument": "e.g. USDCAD, AUDNZD, option structure",
    "direction": "long / short / structure",
    "expression": "plain-English position",
    "horizon": "expected holding period",
    "entry": "verified level/range or null",
    "target": "verified/derived target or null",
    "invalidation": "specific falsifier or null"
  },
  "confidence": 0,
  "thesis": ["..."],
  "why_now": ["..."],
  "pricing_or_mispricing": ["..."],
  "carry_and_holding_cost": ["..."],
  "evidence": [
    {
      "claim": "...",
      "status": "verified | inference | unknown",
      "source": "...",
      "source_ref": "URL/internal ID/null",
      "as_of": "ISO-8601/null"
    }
  ],
  "best_counterargument": "...",
  "what_changes_my_mind": ["..."],
  "questions_for_opponents": ["..."],
  "missing_data": ["..."]
}
```

`trade` may be `null`. Confidence is 0-100 and must fall when the evidence packet has material gaps.

Do not invent executable levels. A null entry or target is preferable to false precision.

## Conflict detection

After Round 1, the parent agent groups genuine conflicts without judging them.

A conflict exists when two or more advocates:

- take opposite directions in the same pair;
- prefer materially different expressions of the same macro view, such as USD spot versus a non-USD cross;
- disagree on whether carry, valuation, positioning, policy, trend or catalyst dominates;
- disagree on whether a trade exists at all.

Do not use majority vote. Do not rank agents by confidence. Confidence scores are self-assessments, not votes.

## Round 2: rebuttal

Choose at most six advocates whose Round 1 proposals form the most decision-relevant conflicts. If there is no meaningful conflict, skip Round 2 and state that explicitly.

Give each selected advocate:
- the unchanged common evidence packet;
- the exact Round 1 contribution(s) it must attack;
- no other hidden synthesis.

Each rebuttal must:
1. identify the opponent's strongest claim;
2. attack the weakest assumption or evidence link;
3. defend or modify its own trade;
4. state one fact that would concede the argument to the opponent;
5. preserve unresolved uncertainty.

Round 2 output:

```json
{
  "type": "TRADER_ROOM_REBUTTAL",
  "run_id": "...",
  "round": 2,
  "agent": "agent-name",
  "opponents": ["..."],
  "strongest_opponent_point": "...",
  "attack": ["..."],
  "defense": ["..."],
  "trade_change": "unchanged | modified | withdrawn",
  "revised_trade": {},
  "concession_trigger": "...",
  "unresolved_question": "..."
}
```

## Cursor stop line

Cursor must stop after assembling the arbiter packet.

Cursor must not:
- choose the winning trade;
- produce a house view;
- average the agents into consensus;
- score a leaderboard;
- call a trade approved;
- create a surrogate chair/PM agent;
- persist an official trade decision.

Those are arbiter functions and belong to ChatGPT in the Trader Room.

## Arbiter packet

Return one final Markdown response containing:

1. run ID and as-of time;
2. source coverage and material gaps;
3. a compact table of all 14 Round 1 pitches;
4. full Round 1 contribution JSON blocks;
5. conflict map;
6. Round 2 rebuttal JSON blocks, if any;
7. unresolved factual questions;
8. an exact final marker:

`STATUS: AWAITING_CHATGPT_ARBITRATION`

Do not append a recommendation after that marker.

## ChatGPT arbitration

When the packet is brought to the Market Watch Trader Room, ChatGPT is expected to:
- verify time-sensitive facts again where material;
- identify which disagreements are factual versus judgmental;
- test the strongest case on each side;
- decide long / short / alternative expression / no trade;
- state the trade horizon, evidence, catalysts, invalidation and remaining uncertainty;
- push durable conclusions to the appropriate Market Watch system only after a real decision exists.

Cursor advocacy is input to the decision, not the decision itself.

## Safety and data integrity

- Advocates are read-only.
- Supabase MCP is project-scoped to `market-watch-dev` and read-only.
- Do not put service-role keys, database passwords, paid-research credentials or other secrets in the repo or prompts.
- Do not write Trader Room tables to Supabase until a real persistence workflow and a least-privilege writer exist.
- Do not republish paywalled source text. Use lawful retained summaries/methodology and provenance.
- Treat unverified social posts as signal, not fact.
- Fail loudly when required evidence cannot be obtained.
