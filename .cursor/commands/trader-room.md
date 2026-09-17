Run the on-demand Market Watch Trader Room debate. If the user says `go` or supplies no extra topic, that is sufficient.

Read `docs/TRADER_ROOM_PROTOCOL.md`, `docs/TRADER_ROOM_EVIDENCE_CONTRACT.md`, `docs/TRADER_RESEARCH_METHOD.md`, and `docs/TRADER_ROOM_ON_DEMAND.md` first and follow them exactly. The evidence contract and on-demand execution contract are mandatory. This command is advocacy/orchestration only. You are not the arbiter. ChatGPT in the Market Watch Trader Room is the sole arbiter.

The single repository entrypoint is:

```bash
PYTHONPATH=. python scripts/trader_room_go.py go --topic "<user text or go>"
```

Default `go` freeze-validates the packet and runs the complete 14-advocate -> conflict aggregator -> one-pass rebuttal -> final aggregator workflow as a dry-run. It does not consume the production Trader Room model budget and must not launch the real 14-trader research run. Refuse `--live` unless a later authenticated human has armed `TRADER_ROOM_LIVE=1`. When armed, `--live` uses Cursor native parent-agent orchestration: one grok-4.6 parent invokes the 14 standing grok-4.6 seats and both aggregators against the identical frozen packet. `LiveRunner` does not synthesize model output.

User topic/hypothesis: use the text supplied after `/trader-room` or `go`. If none is supplied, use `go` and let the frozen packet define G10 FX scope, with emphasis on CAD/AUD/NZD and USD as benchmark, without inventing a trade.

Execution:

1. Preflight.
   - Confirm all 14 standing advocates and both aggregators are available as `grok-4.6[]` seats.
   - Write `TRADER_ROOM_MODEL_POLICY` from `scripts/trader_room/models.py` into the run context. Advocates and aggregators are exact model `grok-4.6`. Internal advocate subagents allowlist only `composer-2.5`.
   - Confirm the Market Watch Supabase MCP connection is available and read-only when assembling live evidence. If the cloud environment exposes the project-scoped connection under a different tool name, use that connection rather than inventing a replacement.
   - Record the current UTC cutoff.
   - Attempt and status all four mandatory evidence families from `docs/TRADER_ROOM_EVIDENCE_CONTRACT.md`: temperature gauges + hard-input drill-down; central-bank/article/news research feed; deterministic market-state packet; durable empirical research method. Record each as `available`, `partial`, `stale`, or `unavailable` before launching advocates.
   - If a missing mandatory family is essential to the user question, stop before spending the 14-agent run. Otherwise preserve the gap explicitly and continue with reduced confidence. The mechanical orchestrator treats all four families as essential by default.

2. Build and freeze one common evidence packet.
   - Query the relevant Market Watch Supabase operational state and provenance when assembling a live packet.
   - Load the current US/CA/AU/NZ 1–100 Inflation, Labor, Activity and Consumer temperature gauges, their actual hard inputs/weights or contributions where available, and their corroborating/contextual evidence under the current score contracts. Preserve vintages, provenance and staleness.
   - Load the existing Market Watch central-bank research and normalized article/news feed relevant to the run. Preserve official-vs-commentary distinction, country/category tags, publication times, provenance and retained summaries/synthesis.
   - Load the freshest valid deterministic market-state snapshot under `docs/MARKET_STATE_FEED_V1.md` / `scripts/market_state.py`, including relevant sovereign rates, curves, cross-market RV, G10 FX, returns, realized-vol/distribution context, provenance and staleness. Preserve explicit unavailable/null states.
   - Load `docs/TRADER_RESEARCH_METHOD.md` in full into the common packet as `research_method`.
   - Use available private research/synthesis only while assembling the packet and only when genuinely accessible and lawful. Do not republish paywalled text.
   - The packet must include the named sections `temperature_gauges`, `central_bank_research`, `news_and_research`, `market_state`, `research_method`, `source_index`, and `known_gaps`.
   - Freeze this packet. Every advocate receives the exact same packet and cutoff. After freeze, no web, search, or new evidence acquisition.

3. Round 1.
   - Launch all 14 standing advocates concurrently, each exact model `grok-4.6`.
   - Give each the exact same frozen common evidence packet and user topic.
   - Instruct each advocate to apply `research_method` before its archetypal bias.
   - Each advocate may make at most two internal subagent calls, model `composer-2.5` only, on the same frozen packet.
   - Do not show agents one another's Round 1 work.
   - Every advocate except `no-trade-skeptic` must return one cogent actionable trade. The skeptic may submit no-trade.
   - Collect exactly one `TRADER_ROOM_CONTRIBUTION` object from each.
   - Do not retry in a way that silently exceeds the Grok ceiling of 30 or Composer ceiling of 28.

4. Deterministic validation.
   - Verify 14 unique expected agent names and remits.
   - Verify required trade schema fields and packet `evidence_refs`.
   - Verify confidence is 0-100.
   - Verify the run ID and packet hash match across all contributions.
   - Verify the common packet contains all mandatory evidence sections and four-family availability statuses.
   - Reject executable price levels that lack evidence/source support.
   - Preserve nulls rather than filling gaps.

5. Conflict map.
   - Launch `conflict-aggregator` on exact model `grok-4.6` with all 14 originals and the frozen packet.
   - Identify opposite directions, opposite currency exposures, incompatible macro/rates/regime assumptions, and trade-versus-no-trade conflicts.
   - Do not vote, rank, synthesize a winner, or treat confidence as a vote.

6. Round 2.
   - Each conflicted advocate gets exactly one rebuttal pass. Max 14 rebuttal Grok calls.
   - Give the unchanged frozen packet, the advocate's own original, and the opposing original trade(s).
   - No additional subagent calls. No new evidence.
   - The advocate may defend, amend, or withdraw and must explicitly shoot holes in the opposing case.
   - Validate each output against `TRADER_ROOM_REBUTTAL`.

7. Final aggregation and artifact persist.
   - Launch `final-aggregator` on exact model `grok-4.6` with all originals, the conflict map, and every rebuttal.
   - Produce the structured PM handoff: all proposed trades, agreement clusters, conflicts, strongest evidence on each side, rebuttals, amendments/withdrawals, shared assumptions, unresolved questions/gaps, and durable artifact references.
   - Do not select a winner or house view.
   - Persist complete run artifacts under `trader-room/runs/<run_id>/` with immutable run ID and evidence cutoff.
   - End the packet itself with exactly `STATUS: AWAITING_CHATGPT_ARBITRATION`.
   - Google Drive folder ID `1NS6Qb6vNGKM18_PW0zPl4NOIJZOLyfUD` is an optional private Markdown copy, not a required preflight for `go`.
   - Never create an official trade-decision record. The packet is unarbitrated input only.
   - Do not put project output in ACP.

8. Return only a handoff receipt.
   - State the run ID and evidence cutoff.
   - State `ARTIFACT_HANDOFF: trader-room/runs/<run_id>/` when persist and verification succeeded.
   - State any hard evidence-access failures.
   - End with exactly `STATUS: AWAITING_CHATGPT_ARBITRATION`.

Ceilings: baseline main Grok invocations = 16 plus only conflict rebuttal Grok calls; max 14 rebuttals; total Grok ceiling 30. Composer subagent ceiling = 28. No retries/model reroutes may silently exceed these ceilings.

This workflow is designed to run entirely in Cursor Cloud/Automations. Do not require a local checkout, local terminal, or local Cursor session for the user to say `go`.
