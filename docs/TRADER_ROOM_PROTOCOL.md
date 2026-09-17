# Trader Room Protocol

## Purpose

Trader Room turns Market Watch evidence into adversarial FX trade proposals. Cursor supplies independent advocates with persistent archetypal biases. Cursor does not decide the winner. The final arbiter is ChatGPT in the Market Watch Trader Room conversation.

The design objective is productive disagreement. Agents should expose different priors, different preferred expressions, and different reasons a trade can fail. Consensus is not a success condition.

The normal execution environment is Cursor Cloud, not a local workstation. A Trader Room run must not require Kevin to open a computer, pull a repository, or run terminal commands.

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

All standing advocates use exact model `grok-4.6` (Cursor frontmatter `grok-4.6[]`). They are read-only and run in isolated contexts. They are biased by design. Their bias changes how they frame a trade from the frozen packet; it does not lower the evidence standard and does not authorize new evidence acquisition.

Do not add, remove, repurpose, promote, or demote these 14 seats, and do not change their archetypal remits, exact `grok-4.6` assignment, or orchestration level unless Kevin separately asks.

### Operating Hub expression mandate

`dollar-king` and `cross-merchant` are intentionally spot-FX specialist seats and remain spot-dedicated.

Every other macro/rates-capable seat must explicitly compare expressions before choosing. First consider executable interest-rate trades: outright duration, curve, and cross-market rates RV. Also consider spot FX. Then choose whichever is genuinely the cleaner expression of that seat's unchanged remit and explain why. Do not force rates if spot is superior.

Vol/options are bottom-of-the-barrel for this mandate because implementation is hard. The `vol-convexity` seat and remit stay unchanged. The broader room must not default to vol and should surface it only when it is unusually compelling versus rates and spot.

The on-demand workflow also seats two aggregators on exact model `grok-4.6`: `conflict-aggregator` and `final-aggregator`. Internal advocate subagents may use only `composer-2.5`, at most two per initial advocate. See `docs/TRADER_ROOM_ON_DEMAND.md`.

Specialists such as commodities/terms-of-trade, balance of payments, fiscal, China, microstructure/execution, or country specialists are not permanent seats yet. Add or summon them only when repeated use proves they are needed.

## Cloud execution and triggers

Ordinary run surfaces are:

1. Kevin says `go` in the Trader Room chat, or launches `/trader-room go`. The repository entrypoint is `python scripts/trader_room_go.py go`.
2. Cursor Automation runs the same on-demand workflow from an intentionally configured cloud schedule or supported private trigger.

Do not require Cursor Desktop or a local terminal for ordinary Trader Room operation.

The approved artifact surface for complete run packets is `trader-room/runs/<run_id>/` in this repository. Sanitized analysis artifacts on that surface are Git-durable so ChatGPT can retrieve the complete 14 submissions, conflict map, rebuttals, and PM handoff. Unsanitized provider-local packets may use `trader-room/runs/.local/` and stay gitignored. Do not commit private, licensed, or raw paid evidence. Do not put project output in ACP. Do not use issues or comments to transport private Trader Room prompts.

## Evidence contract

Every run begins with one common evidence packet. Every standing advocate receives the same packet and the same cutoff time.

The parent agent should populate the packet from the best currently available sources:

- Market Watch Supabase operational state, through the project-scoped read-only MCP connection;
- repository technical/research context that is relevant to interpretation;
- the standalone market-state snapshot from `scripts/market_state.py` when a fresh official rates/G10 FX research packet is needed (command and contract: `docs/MARKET_STATE_FEED_V1.md`);
- any private research/methodology that is actually accessible while the packet is being assembled;
- user-supplied prices, positions, constraints or hypotheses.

After the packet is frozen, advocates and aggregators may use only that packet. No web, search, or new evidence acquisition is allowed during the debate.

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

Launch all 14 standing advocates in parallel unless the user explicitly requests a smaller floor. Each launch must be an independent `grok-4.6` seat. The parent must not synthesize, ghostwrite, substitute, or simulate a seat output if a required Grok seat fails to launch. Fail loudly instead.

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

Every advocate except `no-trade-skeptic` must end with one cogent actionable trade inside its remit. `no-trade-skeptic` may explicitly submit `trade: null`. Confidence is 0-100 and must fall when the evidence packet has material gaps.

Required trade fields: `instrument`, `structure`, `direction`, `thesis`, `mispricing`, `why_now`, `evidence_refs` into the frozen packet, `horizon`, `entry`, `target`, `stop`, `invalidation`, `catalysts`, `principal_risks`, `confidence`. Unsupported levels must be JSON `null`. Do not invent executable levels.

## Conflict detection

After Round 1, the `conflict-aggregator` (exact model `grok-4.6`) receives all 14 originals and the unchanged frozen packet. It groups genuine conflicts without judging them.

A conflict exists when two or more advocates:

- take opposite directions in the same instrument;
- take opposite currency exposure in the same G10 currency;
- hold incompatible macro, rates, or regime assumptions;
- prefer materially different expressions of the same macro view, such as USD spot versus a non-USD cross;
- disagree on whether a trade exists at all.

Do not use majority vote. Do not rank agents by confidence. Do not choose a winner or house view. Confidence scores are self-assessments, not votes.

## Round 2: rebuttal

Each conflicted advocate gets exactly one rebuttal pass. There is no ranking-based shortlist. Maximum rebuttal Grok calls is 14. If there is no meaningful conflict, skip Round 2 and state that explicitly.

Give each conflicted advocate:
- the unchanged frozen common evidence packet;
- its own original submission;
- the exact opposing original trade(s) from the conflict map;
- no other hidden synthesis;
- no additional subagent calls.

Each rebuttal must:
1. identify the opponent's strongest claim;
2. explicitly shoot holes in the opposing case;
3. defend, amend, or withdraw its own trade;
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

The `final-aggregator` (a separate `grok-4.6` invocation) receives all 14 originals, the conflict map, and every rebuttal. It produces the structured PM handoff. It must not select a winner, vote, ranking, or house view. The handoff must preserve enough thesis, evidence, expression-comparison, catalyst, and invalidation detail for ChatGPT to perform the final investment-committee layer.

Cursor must stop after assembling and delivering the arbiter / PM packet.

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

Build one Markdown packet containing:

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

## Handoff and storage

The approved on-demand artifact surface is `trader-room/runs/<run_id>/` with an immutable run ID and evidence cutoff. Persist the sanitized frozen packet, every original submission, the conflict map, every rebuttal, the PM handoff JSON, the Markdown arbiter packet, and an artifact index ChatGPT can retrieve from Git. `trader-room/runs/INDEX.json` and `trader-room/runs/latest.json` point at the latest published run. Do not leave the complete handoff stranded only in a gitignored Cursor-local directory.

Google Drive folder `Market Watch/Trader Room` (folder ID `1NS6Qb6vNGKM18_PW0zPl4NOIJZOLyfUD`) remains an optional private Markdown copy when the Drive plugin is authorized. It is not required to start the on-demand `go` entrypoint. If Drive is used and the write fails after one retry, fail closed for the Drive copy only; keep the structured packet on the repository artifact surface.

Do not put project output in ACP. Do not write Trader Room tables to Supabase.

ChatGPT retrieves any trader submission or conflict exchange from the artifact index.

## ChatGPT arbitration

When the packet is available in the Market Watch Trader Room, ChatGPT is expected to:
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
- The Google Drive plugin may write only the arbiter handoff file for an ordinary debate run; it must not reorganize or delete Drive content.
- Structured on-demand run artifacts belong only under `trader-room/runs/<run_id>/`. Do not put them in ACP.
- Do not put service-role keys, database passwords, paid-research credentials or other secrets in the repo or prompts.
- Do not write Trader Room tables to Supabase until a real persistence workflow and a least-privilege writer exist.
- Do not republish paywalled source text. Use lawful retained summaries/methodology and provenance.
- Treat unverified social posts as signal, not fact.
- Fail loudly when required evidence cannot be obtained.
