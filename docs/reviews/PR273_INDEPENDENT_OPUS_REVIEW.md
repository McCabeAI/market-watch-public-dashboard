# PR #273: independent security and compatibility review

- **PR:** https://github.com/McCabeAI/market-watch-public-dashboard/pull/273
- **Reviewed head:** `5142c4175d8f73bd548cfb0bdfde8d5fafd01077`
- **Base:** `7d91eb5f2a2f97bbd822f8a10746d291bac1e184`
- **Control-plane job:** McCabeAI/agent-control-plane#375, attempt 1 of 1, reviewer only.
- **Reviewer:** a separate Cursor cloud run (`bc-bf96cf13-…`). Its run metadata records `originalModelName: claude-opus-5-5-high`. I cannot verify the thinking level from inside the run beyond that field. I launched no subagents and called no other models.
- **Independence:** I did not reuse the implementation (#373) or repair (#374) transcripts. I read the diff, ran the tests and wrote probes myself.

## Verdict

**APPROVE: merge of STAGE 0 ONLY.**

This approval does not cover activating `candidate-grok-4.7`, a 15th seat, any ACP change, the stage-2 command cutover, or any launch. I found no blocker, no proven regression, and no PR claim contradicted by code or tests. The findings below are non-blocking. M1 is the one to watch on the first production launch after merge.

## Evidence (reproducible)

| Check | Result |
| --- | --- |
| Focused tests: `PYTHONPATH=. python3 -m unittest tests.test_agent_config tests.test_mw_role_guards tests.test_roster_onboarding tests.test_trader_room_budget tests.test_overnight_scheduled_output tests.test_overnight_review_identity tests.test_pm_launch tests.test_mw_current_call_graph` | 155 tests, OK |
| Full suite on head, run alone in a clean worktree: `PYTHONPATH=. python3 -m unittest discover -s tests` | 1,890 tests; 11 failures, 42 errors, 3 skipped |
| Full suite on base, same command, run sequentially after head | 1,800 tests; 11 failures, 42 errors, 3 skipped |
| Failure/error names, head vs base (`diff` of the sorted `FAIL:`/`ERROR:` lines) | **Identical.** Every one is in macro, news, country-detail, market-state, SOFR or launch-quality tests, or is an import error for an optional module (`openpyxl`, `pypdf`, `xlrd`, `playwright`). None touch the roster, hooks or onboarding. |
| CI on head `5142c417` | 7 `pull_request` and 2 `push` workflow runs succeeded. **No workflow runs** `test_agent_config`, `test_mw_role_guards` or `test_roster_onboarding`, so green CI does not establish the hook or onboarding properties. The local run above does. |
| `python -m scripts.trader_room.agent_config check-agents` | OK |
| `agent_config.py hook-models --kind daily\|ondemand\|pm\|trader-room` | `composer-2.5 grok-4.6` for each kind |

Run the two full suites one after the other, not in parallel. The hooks and tests share the fixed paths `/tmp/mw-overnight-active.json` and `/tmp/mw-trader-room-active.json`. `tests.test_overnight_review_identity` dirties the tracked file `data/overnight/runs/overnight-20260922/run.json`. That side effect also exists on base. I restored the file and committed nothing from it.

### Budgets and compatibility

All of these come from direct calls to `scripts/trader_room/agent_config.py`:

- **Daily budget** (\(n+6\) total / \(n+4\) Grok / 2 Composer): 14 seats give 20/18/2; 15 seats give 21/19/2.
- **On-demand budget** (\(4n+1\) / \(2n+1\) / \(2n\)): 14 seats give a maximum of 57/29/28; 15 seats give 61/31/30.
- **Today's head pins** (daily and on-demand) are `legacy_equivalent`. The markers they generate are byte-identical to the literals in `.cursor/commands/{overnight-scheduled,manual-market-watch-review,trader-room}.md`, including the current-graph marker.
- **Old snapshots.** A snapshot with no `agent_roster_pin` resolves to the frozen 14-seat `grok-4.6` legacy pin. `freeze_snapshot` refuses to overwrite an existing snapshot (`scripts/overnight/evidence.py`), so evidence that is already frozen is never re-hashed.
- **Candidate profile.** `build_pin(profile_id="candidate-grok-4.7")` is refused without `allow_candidate`. With that flag set, `assert_acceptable_pin` still refuses the result.
- **Scheduled seats.** A 15th seat dated tomorrow is not in today's pin (14 seats). Once live, its pin is not legacy-equivalent and gets a v2 marker.
- **Diff scope.** Nothing under `data/`, `trader-room/runs/` or `.cursor/agents/` changed. There are no ACP, schedule or workflow changes.

### Hook probes

The probes ran in-process against `.cursor/hooks/enforce-overnight-budget.py`, with state redirected to a temp directory. The overnight freeze was stubbed to the legacy pin. The shell hook ran unmodified with a transcript containing an `ACP_SUBAGENT_POLICY` allowlist of `grok-4.6` and `composer-2.5` plus the v1 overnight marker.

**Valid graph.** A complete overnight graph went through both hooks in `hooks.json` order and every child was allowed: synthesis, then 14 traders with `MW_TRADER_FROZEN=1`, then 3 PMs through the matching custom agents, then the examiner. Final state was 20/18/2, and a 21st child was denied on the cap.

**Denied, as claimed:**
- a repeated identical tag;
- a second, lower-case `mw_role` mention;
- a malformed seat or a trailing period;
- a seat not in the pin;
- a roster `subagent_type` that doesn't match the tag (for example `rate-dove` for `value-guy`, `daily-perma-bear` when daily agents aren't split, or `swinger` for `pm:grinder`);
- `auto`, `grok-4.7`, `cursor-grok-4.6-high`, and `composer-2.5` used for an advocate;
- a missing tag;
- a rebuttal before its advocate, or a duplicate advocate;
- PMs before all traders, or synthesis after a trader;
- a nested child in an overnight run;
- a third Composer child under one advocate;
- any child under a rebuttal;
- a nested child that carries an advocate tag;
- in the shell hook, under the ACP allowlist: `grok-4.7` and `auto`.

**Allowed:**
- a `grok-4.6[]` model;
- an untagged nested child under an advocate, and one tagged `advocate_subagent`.

A denial never writes state, so a corrected respawn is admitted.

## Findings (severity-ranked; none blocking)

**M1, Medium (operational): `MW_ROLE` tags are a new hard requirement on production children.**
- **What changed.** The base hook had no tag check. Every overnight and on-demand child is now denied unless its task contains exactly one strictly formatted tag (`.cursor/hooks/enforce-overnight-budget.py` lines 71-75 and 324-333).
- **Formats that are denied:**
  - `(MW_ROLE=trader:x)`
  - `**MW_ROLE=trader:x**`
  - `MW_ROLE=trader:x,` (trailing comma)
  - `MW_ROLE=trader:x.` (trailing period)
  - any second mention of `MW_ROLE` in the task.
- **Why it isn't a blocker:**
  - the commands now tell the parent to add the tag;
  - `agent_config agents` prints the exact tags;
  - denials are stateless, so the parent can respawn the child;
  - nothing spends before the deny.
- **Remaining risk.** If the parent fails to recover, the run is lost and the single-use grant with it.
- **ACP prompt not verified.** I could not verify that the ACP prompt points the parent at `.cursor/commands/manual-market-watch-review.md`. The delegation request names it as `launch_command`.
- **Minimal correction (optional):** add "put the tag alone on its own line" to the three command files, or let the lookahead in `_STRICT_ROLE_TAG_RE` accept `.,;)*`. Either way, watch the first launch after merge.

**L1, Low: a `subagent_type` outside the roster bypasses the identity check.**
- `_check_subagent_type` returns early when the type isn't a roster agent name (lines 404-406). So `generalPurpose`, or any unknown agent, with the exact pinned model is admitted for any role.
- The model, seat, order and caps are still enforced. Base had no identity check at all.
- PR/docs wording ("if `subagent_type` names a roster custom agent") is accurate, so this is not an unsupported claim.
- Fix if wanted: deny unknown non-empty types for the `trader` and `pm_principal` roles.

**L2, Low: the generic fallback allowlist now includes `grok-4.7`.**
- `.cursor/hooks/enforce-subagent-models.sh` line 4 adds `grok-4.7` to `DEFAULT_MODELS`. That list applies only when no ACP, MW, PM or Trader Room policy is in the transcript, so Market Watch runs are unaffected (probe above).
- It does make `grok-4.7` usable for non-Market Watch subagents in this repo before any authorized cutover.
- Revert that one token if it wasn't intended.

**L3, Low: onboarding temp and checkpoint files aren't gitignored.**
- `.mw-onboarding-checkpoint.json` sits at the repo root (`scripts/trader_room/onboard_trader.py` line 36) and holds base64 copies of books, identity and index. The `*.tmp` and `*.validate.tmp` siblings are also untracked.
- After a crash, a `git add -A` would commit them.
- Fix: add them to `.gitignore`.
- The rollback and `--recover` paths otherwise cover every file that `cold_start_identity` writes.

**L4, Low: the on-demand hook skips the future-dated-seat refusal.**
- `_resolve_trader_room_pin` loads the HEAD registry through a temp path, so `load_config` skips its "active seat with a future date" refusal (`agent_config.py` lines 438-447). It then sets `_source` to `default` (hook lines 238-239).
- Practical exposure is nil today, because CI and the import-time `load_config()` both reject such a registry.
- Fix if wanted: call `scheduled_traders(cfg)` there and deny if it returns anything.

## Notes for later stages (not stage 0 merge conditions)

**N1, before stage 3 (a 15th live seat).** Several consumers still default to the head roster at import time rather than the pin:
- `scripts/overnight/review.py` (e.g. line 582);
- `scripts/overnight/scheduled_output.py` line 658 (`validate_books` with no `roster`);
- `scripts/pm/review_packets.py`;
- `scripts/trading/consequence.py`.

The "refuse activation while a review is open" guard (`onboard_trader.py` lines 536-541) protects in-flight runs, so stage 0 is safe. Activating a seat before stage 2 still fails closed at the first child (v1 marker with a non-legacy pin) and consumes the grant. No code prevents that early activation; only the docs and the `--confirm-live-activation` flag stand in the way.

**N2, at stage 2.** `PM_PRINCIPAL_MODEL` (`scripts/pm/models.py`) and `EXAMINER_MODEL` (`scripts/trading/learning.py`) come from the head profile, not the pin. After a 4.6→4.7 cutover, re-validating a pre-cutover output would fail. The launch freeze in the contract covers in-flight runs.

**N3, ACP.** I could not read ACP source: `gh api repos/McCabeAI/agent-control-plane/contents/...` returns 404, and the GitHub MCP namespace has no file tools. The following are therefore **OPERATOR-VERIFIED (supplied external evidence), not reviewer-verified**:
- `src/acp/mw_one_shot.py` calls `load_schedules(plane.config)` and clones the disabled `market-watch-weekday-0205`;
- that schedule has a `grok-4.6` parent, 20/18/2 caps and an ACP child allowlist in `config/schedules.v1.json`.

Taking those as given, the contract in `docs/ACP_MODEL_ROSTER_MIGRATION_CONTRACT.md` is coherent:
- its parent-equality gate (item 4) runs before the provider call, and a refusal ends the grant;
- it doesn't rely on an arm toggle;
- the existing grant (human launch, single use, no overlap, no retry) plus a launch freeze is what orders the cutover.

If the gate is missing, the Market Watch hook still fails closed at the first child, but the grant is spent. The ACP PR must therefore implement item 4 before stage 2 lands. The ACP parent stays ACP-owned: `set-role` refuses `parent`, and the hook only checks the `parent_model` in the marker against the pin.

## Requirement checklist

| Requirement | Status |
| --- | --- |
| Role/model routing and family budgets: one family table in the pin; roles fixed to `grok` or `composer`; any other family refused | Verified |
| `advocate == rebuttal` (one shared custom agent); daily `trader` may differ via generated `daily-<seat>` agents | Verified (config validation and pin check) |
| Deny repeated identical tag, malformed tag, wrong roster identity, unknown seat, `auto`, runtime slug, unpinned model | Verified by probe and tests |
| Deny unknown non-roster `subagent_type` | Not enforced; see L1 (documented behavior, not a regression) |
| Hook order (shell then Python) does not reject a normal valid graph | Verified for a correctly tagged 20/18/2 graph; see M1 for formatting |
| NY activation dates, pending vs active, refusal while a review is open, checkpoint, rollback, `--recover`, byte-identical prior books/identity | Verified by code reading and `tests.test_roster_onboarding` (fault injection at each stage) |
| 14/15-seat daily and on-demand budgets; old frozen runs | Verified |
| v1 literals in `.cursor/commands/*` valid only for a legacy pin; v2 cutover coherent; no executable unsupported family | Verified |
| No schedule, ACP, `data/` or agent-file changes in the diff | Verified |
