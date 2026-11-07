# Agent roster and model profiles (architecture + staged migration)

**Status:** stage 2 cutover. The active profile is `candidate-grok-4.7`.
`current-production-grok-4.6` is retired and kept for rollback. The live roster
is 15 seats once `chart-guy` is active (activation 2026-11-07) and three automated PMs.
Derived caps are 21/19/2 daily and 61/31/30 on-demand. Pins dated before
2026-11-07 and the legacy 14-seat pin stay on the previous roster. The pre-cutover
note below still describes the 14-seat shape those historical pins use: 20/18/2 and
57/29/28. Grok roles use `grok-4.7`. Synthesis, the learning examiner, and
the advocate subagent stay on `composer-2.5`. This Market Watch PR must not
merge until ACP PR #395 has set the one-shot `parent_model` to `grok-4.7`.
Do not file a `[launch-market-watch]` request between those merges.

This document is the single architecture reference for:

1. Picking models by role for the manual daily Market Watch graph
   (ACP parent, Composer synthesis, n traders, 3 automated PMs, Composer
   learning examiner) and for the on-demand Trader Room (n advocates, up to n
   conditional rebuttals, up to 2 Composer subagents per advocate). Each launch
   pins its profile.
2. Onboarding a trader from one declarative entry or one small CLI call. The
   new seat gets a cold-start book, memory and learning state, and the call
   budget is derived from the live roster.
3. The boundary with ACP. ACP owns the parent model and the stable provider and
   authority contract. Market Watch owns everything else. See
   [`ACP_MODEL_ROSTER_MIGRATION_CONTRACT.md`](ACP_MODEL_ROSTER_MIGRATION_CONTRACT.md).

## 1. One canonical source

`scripts/trader_room/model_registry.json` (schema v2) is the **only** runtime
authority for role models and the trader roster. Everything below derives from
it through `scripts/trader_room/agent_config.py`. Nothing keeps a second copy.

| Consumer | Before | After |
| --- | --- | --- |
| `scripts/trader_room/constants.py` roster/remits/specialties/ceilings | hard-coded 14 tuple, `grok-4.6` | derived from the live roster and active profile (`ADVOCATE_MODEL` = `advocate`, `DAILY_TRADER_MODEL` = `trader`) |
| `scripts/overnight/constants.py` seats/remits | imports the trader_room tuple | unchanged import path, now derived |
| `scripts/market_watch_launch/call_graph.py` 20/18/2 | literal | `daily_budget(n)` from the pin |
| `scripts/trader_room/budget.py` 28/28 | literal | `ondemand_budget(n)` from the pin |
| `scripts/overnight/scheduled_output.py` parent, allowlist, caps, 14 decisions | literal | from the run's pin |
| `scripts/overnight/books.py` exact seat set | head tuple | explicit roster (pin), with a cold-start for newly live seats |
| `.cursor/hooks/*` | literal `grok-4.6`, 20/18/2, 57 | pin plus a verified `MW_ROLE` per child |
| `.cursor/agents/*.md` `model:` frontmatter | edited by hand | rendered/checked by `agent_config render-agents` / `check-agents` |
| `scripts/pm/models.py`, `scripts/pm/constants.py` | literal `grok-4.6` | active profile `pm_principal` / `pm_subagent_models` |

### Roles by workflow

| Workflow | Role | Launched as | Budget family |
| --- | --- | --- | --- |
| ACP (both) | `parent` | ACP one-shot provider job; **ACP-owned** | grok |
| daily | `synthesis` | direct child, `MW_ROLE=synthesis` | composer |
| daily | `trader` | custom agent per seat (see §1.2) | grok |
| daily | `pm_principal` | custom agent `.cursor/agents/<pm>.md` | grok |
| daily | `learning_examiner` | direct child | composer |
| daily/PM | `pm_subagent_models` | PM-internal (not on the overnight graph) | listed models |
| on-demand | `advocate`, `rebuttal` | custom agent `.cursor/agents/<seat>.md` | grok |
| on-demand | `advocate_subagent` | nested child of an advocate | composer |

`PYTHONPATH=. python -m scripts.trader_room.agent_config show` prints every
profile grouped this way, plus the live, scheduled (future-dated) and pending
seats.

### 1.1 Changing a model (the supported path)

1. Pick an **approved** exact model id. Approved ids are exactly the keys of
   `model_families`. To approve a new id in an existing budget family, add one
   line there (for example `"grok-4.8": "grok"`).
2. Set the role on a non-active profile:

   ```bash
   PYTHONPATH=. python -m scripts.trader_room.agent_config set-role \
     --profile candidate-grok-4.7 --role trader --model grok-4.7
   ```

   `set-role` validates the whole config before writing and leaves the file
   byte-identical on any error. Setting `advocate` or `rebuttal` sets both.
   It refuses `parent` (ACP-owned, §6) and refuses the active production
   profile unless `--allow-active-profile` is passed for an authorized change.
3. Activate the profile in a reviewed cutover PR (§6), then run
   `agent_config render-agents` and `agent_config check-agents`.

### 1.2 Daily and on-demand trader models can differ

Cursor routes a child to an exact model id only through a custom agent's
frontmatter (`model: <id>[]`). A `Task` model argument produces runtime slugs
such as `cursor-grok-4.6-high-fast`, which the hooks deny. A custom agent has
exactly one frontmatter model, so:

- `.cursor/agents/<seat>.md` carries the **`advocate`** model (on-demand
  advocate and rebuttal).
- When `trader == advocate` (both current profiles), daily traders use the
  same `<seat>` agent. No extra files exist.
- When `trader != advocate`, `render-agents` generates
  `.cursor/agents/daily-<seat>.md` for every roster seat: the same body as
  `<seat>.md`, `name: daily-<seat>`, and the `trader` model. `check-agents`
  fails if a generated file drifts from its source or if a stale `daily-*`
  file remains after the models are re-joined. Trader ids that start with
  `daily-` are rejected.
- `advocate` and `rebuttal` must stay equal: a rebuttal relaunches the
  seat's own debate agent.

`PYTHONPATH=. python -m scripts.trader_room.agent_config agents --kind daily --snapshot <evidence_snapshot.json>`
prints, for the run's pin, each child's `MW_ROLE` tag, custom agent and exact
model. The hook denies a child whose `subagent_type` names a roster agent
other than the one this table expects.

### 1.3 What a registry edit cannot do (explicit constraints)

- **Budget families are fixed to `grok` and `composer`.** Run-policy markers,
  the hooks, scheduled-output acceptance and the ACP delegation request carry
  exactly one cap per family (`grok_cap`, `composer_cap`). The loader rejects
  any other family value (for example a Claude or GPT model) with a
  "re-budget" error. Adding a family is a separately authorized change to all
  of those surfaces and to ACP; it is not a registry edit.
- **Each role has a fixed budget family.** `parent`, `trader`, `advocate`,
  `rebuttal` and `pm_principal` are debited from the grok cap;
  `synthesis`, `learning_examiner` and `advocate_subagent` from the composer
  cap. Moving a role to the other family changes the 20/18/2 split and is
  rejected for the same reason. `pm_subagent_models` may mix the two.
- **Exact ids only.** `auto`, `inherit`, `default` (any case), empty ids,
  anything in `forbidden_models` (Cursor runtime slugs, `-fast` Composer,
  `grok-4.5`) and anything not in `model_families` are rejected. A family is
  looked up in the explicit table, never inferred from a name prefix.
- **The parent is not configurable here** (§6).

### Schema (v2)

```json
{
  "schema_version": 2,
  "type": "MW_AGENT_MODEL_ROSTER_CONFIG",
  "active_profile": "current-production-grok-4.6",
  "model_families": {"grok-4.6": "grok", "grok-4.7": "grok", "composer-2.5": "composer"},
  "forbidden_models": ["auto", "inherit", "default", "grok-4.5", "composer-2.5-fast", "cursor-grok-4.6-high", "..."],
  "profiles": {
    "current-production-grok-4.6": {
      "status": "active",
      "roles": {
        "parent": "grok-4.6", "trader": "grok-4.6", "advocate": "grok-4.6",
        "rebuttal": "grok-4.6", "pm_principal": "grok-4.6",
        "synthesis": "composer-2.5", "learning_examiner": "composer-2.5",
        "advocate_subagent": "composer-2.5"
      },
      "pm_subagent_models": ["grok-4.6", "composer-2.5"]
    },
    "candidate-grok-4.7": {
      "status": "candidate",
      "requires": ["acp_parent_grok_4_7_migration", "explicit_human_cutover_authorization"],
      "roles": {"parent": "grok-4.7", "trader": "grok-4.7", "...": "..."},
      "pm_subagent_models": ["grok-4.7", "composer-2.5"]
    }
  },
  "roster": {
    "traders": [
      {"id": "perma-bull", "remit": "...", "expression_specialty": "rates_first",
       "may_no_trade": false, "activation_date": "2026-09-18", "status": "active"}
    ],
    "automated_pms": ["swinger", "pragmatist", "grinder"]
  }
}
```

The loader also fails closed on: an unknown, extra or missing role; an
`active_profile` whose `status` is not `active`, or more than one active
profile; duplicate or malformed trader ids (lower-kebab-case), reserved agent
names, PM ids that collide with seats, an empty remit, an unknown
`expression_specialty` (`rates_first`, `spot_only`, `options_specialist`), a
malformed `activation_date`, or an unknown `status` (`active`, `pending`).

## 2. Launch pins

Every launch freezes one `MW_AGENT_ROSTER_PIN`:

```json
{
  "type": "MW_AGENT_ROSTER_PIN", "version": 1, "kind": "daily",
  "profile_id": "current-production-grok-4.6", "profile_status": "active",
  "roster_as_of": "2026-11-03",
  "roles": {"parent": "grok-4.6", "...": "..."},
  "pm_subagent_models": ["grok-4.6", "composer-2.5"],
  "model_families": {"composer-2.5": "composer", "grok-4.6": "grok"},
  "traders": [{"id": "...", "remit": "...", "expression_specialty": "...", "may_no_trade": false, "activation_date": "..."}],
  "automated_pms": ["swinger", "pragmatist", "grinder"],
  "budget": {"version": 1, "total_calls": 20, "grok_family_calls": 18, "composer_calls": 2, "nodes": {"parent": 1, "synthesis": 1, "traders": 14, "automated_pms": 3, "learning_examiner": 1}},
  "legacy": false, "candidate": false, "config_override": false,
  "roster_sha256": "...", "pin_sha256": "..."
}
```

- **Live seats.** A seat is in a pin only when `status` is `active` **and**
  `activation_date <= roster_as_of` (New York calendar date). A seat marked
  active with a future date is "scheduled" and is in no pin or budget.
  The committed registry may not contain scheduled seats: loading it fails,
  so CI and every reader fail closed. The reason is that acceptance, books,
  memory and apply paths still read the live roster rather than the pin, so a
  seat must only go live together with its cold-start state, through
  `onboard_trader --activate`. Future-dated active seats exist only in
  fixture configs (`MW_AGENT_CONFIG_PATH`), where the pin rule is tested.
- **Daily:** `scripts/overnight/evidence.py:freeze_snapshot` pins on the freeze
  date and writes the pin into the evidence snapshot as `agent_roster_pin`.
  ACP already binds that snapshot's `packet_sha256`, so the pin is covered by
  the existing hash contract. The ACP delegation request keeps its current
  shape. Its `budget` (`parent_model`, caps, `current_graph`) is derived from
  the pin.
- **On-demand:** the `scripts/trader_room/orchestrator.py` preflight writes the
  same pin (`kind: ondemand`) into `preflight.json` and the launch plan.
- **Self-contained.** The pin carries the families of its own models.
  `verify_pin` never reads the head config, so a later registry edit (for
  example retiring a model id) cannot change how an old pin validates.
- **Historical runs** have no pin. They resolve to `legacy_pin(kind)`, which is
  built from a frozen literal 14-seat / `grok-4.6` table inside
  `agent_config.py`. A test asserts that the legacy table equals today's head
  roster.
- Validators always use the run's own pin, not the head config. Pins are
  integrity-checked: both SHA-256 values are recomputed, the budget is
  recomputed from `len(traders)`, and every role's family must match.
- Only an `active` profile can be pinned. Building a pin from `candidate-*`
  requires the explicit `allow_candidate=True` used by fixture tests. Such a
  pin is stamped `candidate: true` and is refused by every production path:
  the hooks, the scheduled-output acceptance and the ACP request builder.
- `MW_AGENT_CONFIG_PATH` (fixture override) is honoured only by the Python
  loader. Pins built under it are stamped `config_override: true` and are
  refused by acceptance. The budget hook removes the variable at start-up.

## 3. Budgets (derived, no literals)

Daily (n = pinned live traders, 3 automated PMs):

| n | total | grok-family | composer | nodes |
| ---: | ---: | ---: | ---: | --- |
| 14 | 20 | 18 | 2 | parent 1, synthesis 1, traders 14, PMs 3, examiner 1 |
| 15 | 21 | 19 | 2 | parent 1, synthesis 1, traders 15, PMs 3, examiner 1 |

`total = n + 6`, `grok = n + 4` (parent + traders + PMs), `composer = 2`.

On-demand Trader Room:

| n | total max | grok max | composer max |
| ---: | ---: | ---: | ---: |
| 14 | 57 | 29 | 28 |
| 15 | 61 | 31 | 30 |

`total = 1 parent + n advocates + up to n rebuttals + up to 2n Composer = 4n + 1`.
Rebuttals and Composer subagents are conditional maxima, not targets. Nothing
schedules an extra call automatically.

Every grok-family model debits the grok cap and every composer-family model
the composer cap, but each role accepts only the exact model its pin names.

## 4. Role identity at the hook

Every direct child task carries **exactly one** `MW_ROLE` occurrence. A
repeated tag is denied even when the copies are identical. The tag must be a
standalone token (`MW_ROLE=<role>` or `MW_ROLE=<role>:<seat>`, followed by
whitespace, end of text or a closing quote/backtick). Suffixes such as
`trader:perma-bull/perma-bear` or `trader:perma-bull.x`, lower-case or
prefixed forms are denied as malformed.

| Run kind | Tag | Model (from pin) | Custom agent | Cap and ordering |
| --- | --- | --- | --- | --- |
| daily | `MW_ROLE=synthesis` | `roles.synthesis` | none | at most 1; before the first trader |
| daily | `MW_ROLE=trader:<seat>` | `roles.trader` | `<seat>` or `daily-<seat>` (§1.2) | seat in pin; each seat once |
| daily | `MW_ROLE=pm:<pm_id>` | `roles.pm_principal` | `<pm_id>` | PM in pin; each once; only after all n traders are admitted |
| daily | `MW_ROLE=learning_examiner` | `roles.learning_examiner` | none | at most 1; only after all n traders and 3 PMs |
| on-demand | `MW_ROLE=advocate:<seat>` | `roles.advocate` | `<seat>` | seat in pin; each once |
| on-demand | `MW_ROLE=rebuttal:<seat>` | `roles.rebuttal` | `<seat>` | at most 1 per seat; seat's advocate must be admitted; no subagents |
| on-demand | nested child of an admitted advocate | `roles.advocate_subagent` | none | at most 2 per advocate; tag optional, but if present exactly one `MW_ROLE=advocate_subagent` |

The hook also denies an unknown role, a missing or unexpected seat, a wrong
model for the role, a seat outside the pin, a cap breach, an out-of-order PM
or examiner, nesting outside the advocate→Composer layer, a `candidate` pin,
and an `auto` or `inherit` model. If `subagent_type` names a roster custom
agent, it must be the agent the table above expects for the tagged role.

`enforce-subagent-models.sh` is a coarse second gate. When the transcript has
an ACP `allowed_models` list, that list governs. Otherwise, when it has an
`MW_OVERNIGHT_RUN_POLICY` or `MW_TRADER_ROOM_RUN_POLICY` marker, it admits the
active profile's daily or on-demand role models
(`agent_config hook-models --kind daily|ondemand`), so a profile model change
does not need a hook edit.

### Trust anchor and markers

For daily runs the pin comes from the **committed** evidence snapshot
(`git show HEAD:…`), exactly as the trusted-freeze check works today. For
on-demand runs it is built from the committed head config on today's New York
date.

The **first** run-policy marker of a kind in the parent transcript governs;
later copies are ignored, and markers of two different kinds deny. The caps the
hook enforces are always the marker's values, and the marker must equal the
pin:

- `version: 1` markers (the literal in today's commands and, per the operator,
  in today's ACP prompt) are accepted only when the pin is legacy-equivalent:
  the 14 legacy seat ids in order, all-`grok-4.6`/`composer-2.5` roles, the
  three PMs, legacy PM subagent models and 20/18/2 or 57/29/28. Current
  production pins are legacy-equivalent, so current launches are unaffected.
- `version: 2` markers carry `profile_id`, `traders` and `roster_sha256`, must
  have exactly the expected keys, and must match the pin exactly.
- Consequence: while the v1 literal is the first marker in the transcript (in
  the command text or the ACP prompt), any non-legacy pin (a 15th live seat, a
  split trader model, or the 4.7 profile) is denied at the first child before
  child spend. Running a non-legacy pin therefore also needs the literal
  removed from `.cursor/commands/*` and from the ACP prompt, with the parent
  emitting the lines printed by `agent_config markers` (contract item 6).
- The hook cannot observe the parent's actual runtime model. It compares the
  marker's declared `parent_model` with the pin. ACP must therefore emit a
  marker whose `parent_model` is the parent it actually launched (contract
  items 4 and 6).

## 5. Trader onboarding

```bash
PYTHONPATH=. python -m scripts.trader_room.onboard_trader \
  --id <kebab-id> --remit "<explicit remit>" --expression-specialty rates_first \
  --activation-date YYYY-MM-DD --description "<one line>" --persona-file <real persona.md> \
  [--may-no-trade] [--activate --confirm-live-activation] [--root <repo root>] [--dry-run]
PYTHONPATH=. python -m scripts.trader_room.onboard_trader --recover [--root <repo root>]
```

- Without `--activate`, the CLI appends one `status: pending` entry and writes
  `.cursor/agents/<id>.md`, with frontmatter rendered from the active profile.
  A pending seat is in no pin or budget. The activation date may be in the
  future.
- `--activate --confirm-live-activation` is the explicit human activation. It
  is refused while `activation_date` is after today's New York date, so a seat
  cannot be activated early; register it as pending and activate on or after
  the date. It is also refused while the latest daily review is open
  (`allocating`, `freezing`, `frozen` or `accepting`): that review was frozen
  with the old roster, and its acceptance still checks the live roster. Activate
  after the day's review is accepted and before the next freeze. On success it
  creates cold-start state:
  - the trading memory files under `data/trading/trader/<id>/` plus the index
    row, through the existing empty constructors;
  - a `$100m` cold-start seat in `data/overnight/books/latest.json`, built
    with `empty_seat`;
  - the agent file, then the config flip to `active` **last** (the commit
    point).
- **Checkpoint and rollback.** Before writing, the CLI validates the new config
  in memory and creates `<root>/.mw-onboarding-checkpoint.json` exclusively.
  It holds the prior bytes (or absence) of every path it will touch, and it
  also serves as the lock. Each file is replaced atomically. If any stage
  raises, every recorded path is restored and the checkpoint is removed. If
  the process dies mid-way, the checkpoint remains, the next onboarding call
  refuses, and `--recover` restores the recorded prior state.
- It never creates positions, lessons or history, and it refuses if any state
  already exists for that id. Existing seats, identity files and history stay
  byte-identical.
- Freeze-time `ensure_roster_books` is the idempotent safety net. It adds a
  cold-start seat for a live seat that is missing from `latest.json`, and
  never edits or removes an existing seat.
- Activating a real 15th seat needs the user's real persona and a separate
  authorization. This PR proves the path only with a synthetic seat in temp
  fixtures.

## 6. Staged migration

| Stage | Owner | Change | Gate |
| --- | --- | --- | --- |
| 0 (this PR) | Market Watch | v2 config, pins, derived budgets, role-verified hooks, split daily/debate agents, onboarding CLI, candidate 4.7 profile defined but inactive | merged by a human; no runtime model change |
| 1 | ACP (separately authorized PR in the protected repo) | contract in `ACP_MODEL_ROSTER_MIGRATION_CONTRACT.md`: dedicated one-shot config with one parent-model field, parent equality gate, no MW subagent allowlist or trader count/models in ACP, marker emitted truthfully | explicit ACP authorization; launch freeze during cutover |
| 2 (this change) | Market Watch cutover PR | set `candidate-grok-4.7.status = active`, `active_profile = candidate-grok-4.7`, and the old profile's `status = retired`; remove the candidate `requires` list; remove the v1 literal markers from `.cursor/commands/*`; run `agent_config render-agents`; verify with `check-agents` | ACP PR #395 must merge first; Kevin authorized the cutover on 2026-11-05 |
| 3 (optional) | Market Watch | onboard a real 15th trader with the user's persona and a real activation date | explicit user profile and authorization; requires stage 1 item 6 |

The parent model is changed in exactly one place, ACP's one-shot config, in
the same coordinated cutover as stage 2. The Market Watch profile `parent`
value mirrors it so a mismatch is refused (by ACP's equality gate, and by the
hook when the marker is truthful).

### Compatibility matrix

| ACP parent | MW active profile | First marker | Result |
| --- | --- | --- | --- |
| grok-4.6 (today) | current-production-grok-4.6, 14 live seats | v1 literal | runs, 14 seats, 20/18/2 |
| grok-4.6 | current-production, 15th seat pending (any date) | v1 literal | runs with 14 seats (seat not in the pin) |
| grok-4.6 | registry with an active seat whose date is in the future | any | refused: the committed registry fails to load (keep the seat pending) |
| grok-4.6 | current-production, 15th seat live | v1 literal | denied at first child: v1 is valid only for a legacy-equivalent pin. Needs stage 1 item 6 and the stage 2 command change |
| grok-4.6 | current-production with split trader model | v1 literal | denied at first child (not legacy-equivalent); same prerequisite |
| grok-4.6 | candidate-grok-4.7 | any | ACP gate refuses the request (`parent_model` mismatch); without the gate, the hook denies the first child |
| grok-4.7 (after stage 1) | current-production-grok-4.6 | n/a | ACP gate refuses before the provider call; launches are paused until stage 2 lands |
| grok-4.7 | candidate-grok-4.7 (stage 2) | v2 from `agent_config markers` | runs; grok roles on grok-4.7, Composer roles on 2.5 |
| any | historical run without pin | v1 | validates against the legacy 14-seat / grok-4.6 pin |

### Roll forward

1. Merge stage 0. Daily and on-demand behaviour is unchanged apart from the
   `MW_ROLE` tags that the updated commands now emit.
2. Declare a launch freeze (no `[launch-market-watch]` request), confirm no
   launch is in flight, and land the separately authorized ACP stage 1 PR.
   From then on ACP refuses any request whose `budget.parent_model` differs
   from its configured parent.
3. Merge stage 2, re-render the agent files, run `check-agents`, and lift the
   launch freeze. The next launch needs a fresh human authorization.

### Roll back

- Stage 2: revert the cutover commit (profile status, `active_profile`,
  rendered frontmatter, command markers) and, in the same freeze window, set
  ACP's parent field back to `grok-4.6`. Runs that are already frozen keep
  their own pins.
- Stage 0: revert this PR. Snapshots frozen while it was live carry an extra
  `agent_roster_pin` key. The old code ignores that key, and the key stays
  covered by the snapshot hash.
- Onboarding: remove the pending entry and its agent file. An activated
  seat's state is append-only history and is left in place, never deleted.
