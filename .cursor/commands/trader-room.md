Run a full Market Watch Trader Room debate.

Read `docs/TRADER_ROOM_PROTOCOL.md` first and follow it exactly. This command is advocacy/orchestration only. You are not the arbiter. ChatGPT in the Market Watch Trader Room is the sole arbiter.

User topic/hypothesis: use the text supplied after `/trader-room`. If none is supplied, scan the current Market Watch evidence for the most decision-relevant G10 FX disagreements, with emphasis on CAD/AUD/NZD and USD as benchmark, and formulate the scope without inventing a trade.

Execution:

1. Preflight.
   - Confirm all 14 standing subagents listed in the protocol are available.
   - Confirm the `market-watch-supabase` MCP server is available. It is intentionally project-scoped and read-only.
   - If MCP authentication is required, stop and report only the exact authentication blocker. Do not degrade silently to invented or stale database state.
   - Record the current UTC cutoff.
   - Identify which other lawful research sources are actually available in this session. Never claim access that you do not have.

2. Build one common evidence packet.
   - Query the relevant Market Watch Supabase operational state and provenance.
   - Pull fresh official/public facts or web sources when time sensitivity requires it.
   - Use available private methodology/synthesis only when genuinely accessible.
   - Include market levels only when verified with a source and timestamp.
   - List known gaps.
   - Keep the packet focused enough that every advocate can reason from the same evidence without drowning in unrelated material.

3. Round 1.
   - Launch all 14 standing advocates concurrently.
   - Give each the exact same common evidence packet and user topic.
   - Do not show agents one another's Round 1 work.
   - Collect exactly one `TRADER_ROOM_CONTRIBUTION` object from each.
   - If an agent fails schema validation, retry that agent once with the validation error. If it fails again, mark the contribution failed; do not fabricate a replacement.

4. Deterministic validation.
   - Verify 14 unique expected agent names.
   - Verify `type`, `run_id`, `round`, `agent`, `confidence`, `evidence`, `missing_data`.
   - Verify confidence is 0-100.
   - Verify the run ID matches across all contributions.
   - Reject executable price levels that lack evidence/source support.
   - Preserve nulls rather than filling gaps.

5. Conflict map.
   - Identify actual directional/expression/thesis/no-trade conflicts.
   - Do not vote, rank, synthesize a winner, or treat confidence as a vote.

6. Round 2.
   - Select at most six agents involved in the most decision-relevant conflicts.
   - Launch their rebuttals concurrently using the unchanged common evidence packet plus exact opponent Round 1 objects.
   - Validate each output against `TRADER_ROOM_REBUTTAL`.
   - One retry maximum for malformed output.

7. Return the arbiter packet exactly as specified in the protocol.
   - Include the source coverage and known gaps.
   - Include all 14 Round 1 contributions.
   - Include the conflict map and any Round 2 rebuttals.
   - Do not choose a winner.
   - End with exactly:
     `STATUS: AWAITING_CHATGPT_ARBITRATION`

Do not edit repository files, mutate Supabase, open PRs, or commit anything during a debate run.
