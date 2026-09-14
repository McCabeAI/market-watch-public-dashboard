# Market Watch — Supabase Persistence V1

Status: ACTIVE

This document governs how the light Market Watch refresh persists normalized operational feed state to the existing `market-watch-dev` Supabase project (`market_watch` schema). It exists because the chat/MCP execution surface can permit read and rollback-test SQL while independently blocking durable DML. The database itself may therefore be healthy even when a refresh cannot persist rows.

This protocol changes write mechanics only. It does not change Market Watch news selection, macro methodology, scoring, evidence hierarchy, or source-of-truth ownership.

## 1. Safety boundary

- Do not widen `.cursor/mcp.json`. The Cursor/Trader Room Supabase connection remains intentionally `read_only=true`.
- Do not use `SECURITY DEFINER`, public write endpoints, relaxed RLS, service-role exposure, or other privilege expansion to work around an execution-surface restriction.
- Do not use `apply_migration` for routine feed DML.
- A connector/tool safety rejection is not evidence that Supabase, Postgres, RLS, or the project is unhealthy.

## 2. Preflight

Before any refresh write, verify with read-only SQL:

1. the target project is `market-watch-dev` / project ref `hnpcevczrwwulaifmqbb`;
2. `current_user`, `session_user`, `transaction_read_only`, and `default_transaction_read_only`;
3. the `market_watch.ingest_runs`, `content_items`, and `content_evidence` tables are reachable;
4. whether the intended run window or `content_fingerprint` rows already exist.

If the session is actually read-only, do not attempt DML. Mark persistence blocked.

## 3. Write shape — deliberately boring

When durable DML is permitted by the execution environment, perform persistence as small sequential calls. One logical write statement per tool/API call.

Never use for the operational refresh:

- multi-statement DML batches;
- writable CTE chains that create a run and child rows in one request;
- `INSERT ... RETURNING` output piped directly into later inserts through CTEs;
- `UNION ALL` to bulk-create unrelated evidence rows;
- a single large transaction containing the entire refresh.

Preferred sequence:

1. **Ingest run:** insert one `market_watch.ingest_runs` row with `status='running'` and the exact window. Then read it back by exact window/run kind to obtain and verify the run ID.
2. **Content items:** upsert one `market_watch.content_items` item at a time using a deterministic unique `content_fingerprint`. After each write, read the item back by fingerprint and capture its ID.
3. **Evidence:** insert/upsert one `market_watch.content_evidence` row at a time using the verified content-item ID and canonical source URL. Read back/verify after each material write.
4. **Completion:** after all intended rows verify, update the ingest run to `status='succeeded'`, set `completed_at`, and set final `items_seen` / `items_written` counts.
5. **Verification:** independently query the completed run, the adopted fingerprints, and evidence-row count. The write phase is incomplete until the readback matches the intended payload.

Each content/evidence write must be idempotent. A retry must not duplicate a feed item or provenance edge.

## 4. Failure behavior

If a durable write is rejected by the execution surface before reaching Postgres:

- stop further DML attempts after confirming the behavior with one simple durable statement;
- do not retry different SQL shapes merely to evade the safety layer;
- do not change permissions or RLS as a workaround;
- continue the public dashboard refresh only if its independent data/source/deployment requirements can still be satisfied;
- classify the overall operational run as **PERSISTENCE PARTIAL** and say explicitly that the public artifact may be current while Supabase is not;
- record the missing window/payload in the Market Watch Project State so it can be replayed when a supported writer is available.

If a write reaches Postgres and fails with an actual database error, diagnose that database error normally. Do not conflate it with a connector safety rejection.

## 5. Unattended 04:00 job

The scheduled ChatGPT task must assume that durable SQL mutation may be unavailable even when interactive/read access works. It must therefore:

- follow this protocol instead of constructing compound SQL;
- verify persistence independently from dashboard deployment;
- never report Supabase current merely because GitHub Pages deployed successfully;
- never let a blocked persistence step erase or corrupt a valid public refresh;
- surface `PERSISTENCE PARTIAL` when the execution environment blocks durable DML.

A future repo-owned or service-owned writer may replace chat/MCP DML once implemented and validated. Until then, do not weaken the existing read-only Cursor trust boundary just to make unattended writes possible.

## 6. Replay rule

A missed persistence window is replayable because adopted feed items use deterministic fingerprints and evidence uses canonical source URLs. Before replay:

1. query the exact window and fingerprints;
2. insert only missing state using the sequential write shape above;
3. verify final counts;
4. update the Market Watch Project State from persistence-partial to fully current only after readback proves completion.
