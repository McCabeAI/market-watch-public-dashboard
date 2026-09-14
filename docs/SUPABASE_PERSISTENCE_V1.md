# Market Watch — Supabase Persistence V1

Status: ACTIVE

This document governs how the light Market Watch refresh persists normalized operational feed state to the existing `market-watch-dev` Supabase project (`market_watch` schema). It exists because the chat/MCP execution surface can permit read and rollback-test SQL while independently blocking durable DML. The database itself may therefore be healthy even when a refresh cannot persist rows.

This protocol changes write mechanics only. It does not change Market Watch news selection, macro methodology, scoring, evidence hierarchy, or source-of-truth ownership.

## 1. Safety boundary

- Do not widen `.cursor/mcp.json`. The Cursor/Trader Room Supabase connection remains intentionally `read_only=true`.
- Do not use `SECURITY DEFINER`, public write endpoints, relaxed RLS, service-role exposure, or other privilege expansion to work around an execution-surface restriction.
- Do not use `apply_migration` for routine feed DML.
- A connector/tool safety rejection is not evidence that Supabase, Postgres, RLS, or the project is unhealthy.
- Never place private/paid research, Gmail/Drive/Notion URLs, raw evidence pointers, secrets, or proprietary market data in the public repository staging payload.

## 2. Preflight

Before any refresh write, verify with read-only SQL:

1. the target project is `market-watch-dev` / project ref `hnpcevczrwwulaifmqbb`;
2. `current_user`, `session_user`, `transaction_read_only`, and `default_transaction_read_only`;
3. the `market_watch.ingest_runs`, `content_items`, and `content_evidence` tables are reachable;
4. whether the intended run window or `content_fingerprint` rows already exist.

If the session is actually read-only, do not attempt chat/MCP DML. Use the service-side handoff described below if it is configured.

## 3. Direct write shape — deliberately boring

When durable DML is permitted by the execution environment, perform persistence as small sequential calls. One logical write statement per tool/API call.

Never use for the operational refresh:

- multi-statement DML batches;
- writable CTE chains that create a run and child rows in one request;
- `INSERT ... RETURNING` output piped directly into later inserts through CTEs;
- `UNION ALL` to bulk-create unrelated evidence rows;
- a single giant transaction submitted through the chat/MCP surface.

Preferred sequence:

1. **Ingest run:** insert one `market_watch.ingest_runs` row with `status='running'` and the exact window. Then read it back by exact window/run kind to obtain and verify the run ID.
2. **Content items:** upsert one `market_watch.content_items` item at a time using a deterministic unique `content_fingerprint`. After each write, read the item back by fingerprint and capture its ID.
3. **Evidence:** insert/upsert one `market_watch.content_evidence` row at a time using the verified content-item ID and canonical source URL. Read back/verify after each material write.
4. **Completion:** after all intended rows verify, update the ingest run to `status='succeeded'`, set `completed_at`, and set final `items_seen` / `items_written` counts.
5. **Verification:** independently query the completed run, the adopted fingerprints, and evidence-row count. The write phase is incomplete until the readback matches the intended payload.

Each content/evidence write must be idempotent. A retry must not duplicate a feed item or provenance edge.

## 4. Service-side fallback for unattended writes

A narrow repo-owned writer now exists:

- workflow: `.github/workflows/persist-supabase-feed.yml`
- writer: `scripts/persist_market_watch.py`
- staging contract: `ops/supabase/inbox/README.md`
- trigger payload: `ops/supabase/inbox/latest.json`

The writer is intentionally not a general SQL executor. It accepts only the documented public feed JSON shape, validates that `public_only=true`, rejects private-host URLs and raw-evidence pointers, and writes only the existing `market_watch.ingest_runs`, `content_items`, and `content_evidence` tables.

The workflow requires one repository secret: `SUPABASE_DB_URL`. Use a server-side Supabase Postgres connection string suitable for GitHub Actions. Never commit or paste this value into repository files, task prompts, or chat.

When direct durable DML is blocked by the chat/MCP surface:

1. build `ops/supabase/inbox/latest.json` using the exact public staging schema;
2. commit/push that file to `main` together with or immediately after the dashboard refresh;
3. let `Persist Market Watch Supabase Feed` run;
4. inspect the workflow result;
5. independently read back the run/fingerprints from Supabase before declaring persistence current.

Until `SUPABASE_DB_URL` is configured, the workflow will fail loudly at the secret check and the run remains `PERSISTENCE PARTIAL`.

## 5. Failure behavior

If a durable chat/MCP write is rejected before reaching Postgres:

- stop further DML attempts after confirming the behavior with one simple durable statement;
- do not retry different SQL shapes merely to evade the safety layer;
- do not change permissions or RLS as a workaround;
- use the service-side staging fallback if configured;
- continue the public dashboard refresh only if its independent data/source/deployment requirements can still be satisfied;
- classify the overall operational run as **PERSISTENCE PARTIAL** until either direct readback or the service-side workflow proves persistence;
- say explicitly that the public artifact may be current while Supabase is not.

If a write reaches Postgres and fails with an actual database error, diagnose that database error normally. Do not conflate it with a connector safety rejection.

## 6. Unattended 04:00 job

The scheduled ChatGPT task must assume that direct durable SQL mutation may be unavailable even when interactive/read access works. It must therefore:

- follow this protocol instead of constructing compound SQL;
- try the direct sequential path only when permitted;
- fall back to the public staging payload + GitHub writer when direct DML is blocked;
- verify persistence independently from dashboard deployment;
- never report Supabase current merely because GitHub Pages deployed successfully;
- never let a blocked persistence step erase or corrupt a valid public refresh;
- surface `PERSISTENCE PARTIAL` when neither write path verifies successfully.

Do not weaken the existing read-only Cursor trust boundary just to make unattended writes possible.

## 7. Replay rule

A missed persistence window is replayable because adopted feed items use deterministic fingerprints and evidence uses canonical source URLs.

Before replay:

1. query the exact window and fingerprints;
2. persist only missing state through either the direct sequential path or the service-side staging writer;
3. verify final counts and fingerprints;
4. update the Market Watch Project State from persistence-partial to fully current only after readback proves completion.
