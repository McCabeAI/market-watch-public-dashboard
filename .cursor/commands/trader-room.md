Run a full Market Watch Trader Room debate in Cursor Cloud.

Read `docs/TRADER_ROOM_PROTOCOL.md`, `docs/TRADER_ROOM_EVIDENCE_CONTRACT.md`, and `docs/TRADER_RESEARCH_METHOD.md` first and follow them exactly. The evidence contract is mandatory for every full run. This command is advocacy/orchestration only. You are not the arbiter. ChatGPT in the Market Watch Trader Room is the sole arbiter.

User topic/hypothesis: use the text supplied after `/trader-room`. If none is supplied, scan the current Market Watch evidence for the most decision-relevant G10 FX disagreements, with emphasis on CAD/AUD/NZD and USD as benchmark, and formulate the scope without inventing a trade.

Execution:

1. Preflight.
   - Confirm all 14 standing subagents listed in the protocol are available.
   - Confirm the Market Watch Supabase MCP connection is available and read-only. If the cloud environment exposes the project-scoped connection under a different tool name, use that connection rather than inventing a replacement.
   - Confirm the Cursor Google Drive plugin is available and can write to Google Drive folder `Market Watch/Trader Room`, folder ID `1NS6Qb6vNGKM18_PW0zPl4NOIJZOLyfUD`.
   - If Google Drive is not authorized or writable, stop before running the debate and report the exact authorization/access blocker. Do not use the public GitHub repository as a fallback for private Trader Room content.
   - Record the current UTC cutoff.
   - Identify which lawful research sources are actually available in this cloud session. Never claim access that you do not have.
   - Attempt and status all four mandatory evidence families from `docs/TRADER_ROOM_EVIDENCE_CONTRACT.md`: temperature gauges + hard-input drill-down; central-bank/article/news research feed; deterministic market-state packet; durable empirical research method. Record each as `available`, `partial`, `stale`, or `unavailable` before launching advocates.
   - If a missing mandatory family is essential to the user question, stop before spending the 14-agent run. Otherwise preserve the gap explicitly and continue with reduced confidence.

2. Build one common evidence packet.
   - Query the relevant Market Watch Supabase operational state and provenance.
   - Load the current US/CA/AU/NZ 1–100 Inflation, Labor, Activity and Consumer temperature gauges, their actual hard inputs/weights or contributions where available, and their corroborating/contextual evidence under the current score contracts. Preserve vintages, provenance and staleness.
   - Load the existing Market Watch central-bank research and normalized article/news feed relevant to the run. Preserve official-vs-commentary distinction, country/category tags, publication times, provenance and retained summaries/synthesis. Fresh web research supplements this feed; it does not silently replace it.
   - Load the freshest valid deterministic market-state snapshot under `docs/MARKET_STATE_FEED_V1.md` / `scripts/market_state.py`, including relevant sovereign rates, curves, cross-market RV, G10 FX, returns, realized-vol/distribution context, provenance and staleness. Preserve explicit unavailable/null states.
   - Load `docs/TRADER_RESEARCH_METHOD.md` in full into the common packet as `research_method`. Apply that retained Bob Elliott / Nonconsensus and David Cervantes / Pinebrook empirical discipline as method, not as directional authority or current trade calls.
   - Pull fresh official/public facts or web sources when time sensitivity requires it.
   - Use available private research/synthesis only when genuinely accessible and lawful. Do not republish paywalled text.
   - Include market levels only when verified with a source and timestamp.
   - The packet must include the named sections `temperature_gauges`, `central_bank_research`, `news_and_research`, `market_state`, `research_method`, `source_index`, and `known_gaps` in addition to any useful legacy protocol fields.
   - List known gaps.
   - Keep the packet focused enough that every advocate can reason from the same evidence without drowning in unrelated material.
   - Freeze this packet. Every advocate receives the exact same packet and cutoff; no advocate may privately fill a missing mandatory input with an unsupported assumption.

3. Round 1.
   - Launch all 14 standing advocates concurrently.
   - Give each the exact same frozen common evidence packet and user topic.
   - Instruct each advocate to apply `research_method` before its archetypal bias: causal mechanism, correct normalization, historical reference, decomposition, triangulation, explicit market-implied assumptions, discrepancy mapping, flow/plumbing separation, falsifiers, and expression where the mispricing lives.
   - Do not show agents one another's Round 1 work.
   - Collect exactly one `TRADER_ROOM_CONTRIBUTION` object from each.
   - If an agent fails schema validation, retry that agent once with the validation error. If it fails again, mark the contribution failed; do not fabricate a replacement.

4. Deterministic validation.
   - Verify 14 unique expected agent names.
   - Verify `type`, `run_id`, `round`, `agent`, `confidence`, `evidence`, `missing_data`.
   - Verify confidence is 0-100.
   - Verify the run ID matches across all contributions.
   - Verify the common packet contains all mandatory evidence sections and four-family availability statuses.
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

7. Assemble and hand off the arbiter packet.
   - Build the exact Markdown arbiter packet specified in the protocol.
   - Include the four-family evidence coverage/status and material gaps so ChatGPT can audit what every advocate actually saw.
   - End the packet itself with exactly `STATUS: AWAITING_CHATGPT_ARBITRATION`.
   - Create one UTF-8 Markdown file in Google Drive folder ID `1NS6Qb6vNGKM18_PW0zPl4NOIJZOLyfUD` named `Trader Room Arbiter Packet - <run_id>.md`.
   - Write the complete packet verbatim.
   - Read the created file back or verify its metadata/content before claiming success.
   - If the Drive write fails, retry once. If it still fails, return a hard failure and preserve the packet only in the active Cloud Agent session. Do not commit, push, publish, or place the packet in the public repository.
   - Never create an official trade-decision record. The packet is unarbitrated input only.

8. Return only a handoff receipt.
   - State the run ID.
   - State `DRIVE_HANDOFF: <Drive file URL>` when the write and verification succeeded.
   - State any hard evidence-access failures.
   - End with exactly `STATUS: AWAITING_CHATGPT_ARBITRATION`.

This workflow is designed to run entirely in Cursor Cloud/Automations. Do not require a local checkout, local terminal, or local Cursor session.