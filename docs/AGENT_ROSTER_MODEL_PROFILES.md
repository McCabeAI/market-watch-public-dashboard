# Agent roster and model profiles (architecture + staged migration)

**Status:** stage 0 (compatibility build). Production stays on profile
`current-production-grok-4.6` with the 14-seat roster. The `candidate-grok-4.7`
profile exists so that it can be checked, but nothing activates it, and no 15th
seat is active.

This document is the single architecture reference for:

1. Picking models by role for the manual daily Market Watch graph
   (ACP parent, Composer synthesis, n traders, 3 automated PMs, Composer
   learning examiner) and for the on-demand Trader Room (n advocates, up to n
   conditional rebuttals, up to 2 Composer subagents per advocate). Each launch
   pins its profile.
2. Onboarding a trader from one declarative entry or one small CLI call. The
   new seat gets a cold-start book, memory and learning state, and the call
   budget is derived from the roster.
3. The boundary with ACP. ACP owns the parent model and the stable provider and
   authority contract. Market Watch owns everything else. See
   [`ACP_MODEL_ROSTER_MIGRATION_CONTRACT.md`](ACP_MODEL_ROSTER_MIGRATION_CONTRACT.md).

## 1. One canonical source

`scripts/trader_room/model_registry.json` (schema v2) is the **only** runtime
authority for role models and the trader roster. Everything below derives from
it through `scripts/trader_room/agent_config.py`. Nothing keeps a second copy.

| Consumer | Before | After |
| --- | --- | --- |
| `scripts/trader_room/constants.py` roster/remits/specialties/ceilings | hard-coded 14 tuple, `grok-4.6` | derived from the config's head roster and active profile |
| `scripts/overnight/constants.py` seats/remits | imports the trader_room tuple | unchanged import path, now derived |
| `scripts/market_watch_launch/call_graph.py` 20/18/2 | literal | `daily_budget(n)` from the pin |
| `scripts/trader_room/budget.py` 28/28 | literal | `ondemand_budget(n)` from the pin |
| `scripts/overnight/scheduled_output.py` parent, allowlist, caps, 14 decisions | literal | from the run's pin |
| `scripts/overnight/books.py` exact seat set | head tuple | explicit roster (pin), with a cold-start for newly active seats |
| `.cursor/hooks/*` | literal `grok-4.6`, 20/18/2, 57 | pin plus a verified `MW_ROLE` per child |
| `.cursor/agents/*.md` `model:` frontmatter | edited by hand | rendered/checked by `agent_config render-agents` / `check-agents` |
| `scripts/pm/models.py`, `scripts/pm/constants.py` | literal `grok-4.6` | active profile `pm_principal` / `pm_subagent_models` |

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

The loader validates the config and fails closed on:

- an unknown or extra role, or a missing role;
- a model that is not in `model_families`, or that is in `forbidden_models`,
  `auto`, `inherit` or `default` (case-insensitive), or empty;
- a role whose model's family differs from the role's fixed family. The fixed
  families are: `parent`, `trader`, `advocate`, `rebuttal` and `pm_principal`
  are `grok`; `synthesis`, `learning_examiner` and `advocate_subagent` are
  `composer`. `pm_subagent_models` may mix the two families.
- `trader != advocate` or `advocate != rebuttal`. All three run through the
  same `.cursor/agents/<seat>.md` custom-agent file, and a custom agent has
  exactly one frontmatter model.
- an `active_profile` whose `status` is not `active`, or more than one
  profile with `status: active`;
- duplicate or malformed trader ids (lower-kebab-case), an empty remit, an
  unknown `expression_specialty` (`rates_first`, `spot_only`,
  `options_specialist`), a malformed `activation_date`, or an unknown `status`
  (`active`, `pending`).

A model family is looked up in the explicit `model_families` table. It is never
inferred from a name prefix, so `grok-4.7-high-fast` is rejected rather than
treated as Grok.

## 2. Launch pins

Every launch freezes one `MW_AGENT_ROSTER_PIN`:

```json
{
  "type": "MW_AGENT_ROSTER_PIN", "version": 1, "kind": "daily",
  "profile_id": "current-production-grok-4.6",
  "roles": {"parent": "grok-4.6", "...": "..."},
  "pm_subagent_models": ["grok-4.6", "composer-2.5"],
  "traders": [{"id": "...", "remit": "...", "expression_specialty": "...", "may_no_trade": false, "activation_date": "..."}],
  "automated_pms": ["swinger", "pragmatist", "grinder"],
  "budget": {"version": 1, "total_calls": 20, "grok_family_calls": 18, "composer_calls": 2, "nodes": {"parent": 1, "synthesis": 1, "traders": 14, "automated_pms": 3, "learning_examiner": 1}},
  "legacy": false, "config_override": false,
  "roster_sha256": "...", "pin_sha256": "..."
}
```

- **Daily:** `scripts/overnight/evidence.py:freeze_snapshot` writes the pin into
  the evidence snapshot as `agent_roster_pin`. ACP already binds that
  snapshot's `packet_sha256`, so the pin is covered by the existing hash
  contract. The ACP delegation request keeps its current shape. Its `budget`
  (`parent_model`, caps, `current_graph`) is derived from the pin.
- **On-demand:** the `scripts/trader_room/orchestrator.py` preflight writes the
  same pin (`kind: ondemand`) into `preflight.json` and the launch plan.
- **Historical runs** have no pin. They resolve to `legacy_pin(kind)`, which is
  built from a frozen literal 14-seat / `grok-4.6` table inside
  `agent_config.py`. That table **does not read the config**, so a later roster
  or model edit cannot change how a 2026-11-02 (or older) run validates. A test
  asserts that the legacy table equals today's head roster.
- Validators always use the run's own pin, not the head config. Pins are
  integrity-checked: both SHA-256 values are recomputed, and the budget is
  recomputed from `len(traders)`.
- Only an `active` profile can be pinned. Building a pin from `candidate-*`
  requires the explicit `allow_candidate=True` used by fixture tests. Such a
  pin is stamped `candidate: true` and is refused by every production path:
  the hooks, the scheduled-output acceptance and the ACP request builder.
- `MW_AGENT_CONFIG_PATH` (fixture override) is honoured only by the Python
  loader. Pins built under it are stamped `config_override: true` and are
  refused by acceptance. The hooks never honour it.

## 3. Budgets (derived, no literals)

Daily (n = pinned traders, 3 automated PMs):

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

Both `grok-4.6` and `grok-4.7` debit the Grok-family cap, but each role accepts
only the exact model that its pin names.

## 4. Role identity at the hook

Every child task must carry exactly one role tag:

| Run kind | Tag | Model (from pin) | Cap and ordering |
| --- | --- | --- | --- |
| daily | `MW_ROLE=synthesis` | `roles.synthesis` | at most 1; before the first trader |
| daily | `MW_ROLE=trader:<seat>` | `roles.trader` | seat in pin; each seat once |
| daily | `MW_ROLE=pm:<pm_id>` | `roles.pm_principal` | PM in pin; each once; only after all n traders are admitted |
| daily | `MW_ROLE=learning_examiner` | `roles.learning_examiner` | at most 1; only after all n traders and 3 PMs |
| on-demand | `MW_ROLE=advocate:<seat>` | `roles.advocate` | seat in pin; each once |
| on-demand | `MW_ROLE=rebuttal:<seat>` | `roles.rebuttal` | at most 1 per seat; seat's advocate must be admitted; no subagents |
| on-demand | nested child of an admitted advocate | `roles.advocate_subagent` | at most 2 per advocate; tag optional, but if present it must be `MW_ROLE=advocate_subagent` |

The hook denies a missing, unknown, duplicate or conflicting tag, a wrong model
for the role, a seat outside the pin, a cap breach, an out-of-order PM or
examiner, nesting outside the advocate→Composer layer, a `candidate` pin, and
an `auto` or `inherit` model. If a custom-agent `subagent_type` names a known
seat or PM, it must equal the tagged id.

Trust anchor: for daily runs the pin comes from the **committed** evidence
snapshot (`git show HEAD:…`), exactly as the trusted-freeze check works today.
For on-demand runs it comes from the committed head config. The run-policy
marker must agree with the pin:

- `version: 1` markers (today's ACP emission) are accepted only when the pin
  is equivalent to the legacy pin (14 seats, `grok-4.6` parent, 20/18/2 or
  57/29/28).
- `version: 2` markers carry `profile_id`, `traders` and `roster_sha256`, and
  must match the pin exactly.

## 5. Trader onboarding

```bash
PYTHONPATH=. python -m scripts.trader_room.onboard_trader \
  --id <kebab-id> --remit "<explicit remit>" --expression-specialty rates_first \
  --activation-date YYYY-MM-DD --description "<one line>" --persona-file <real persona.md> \
  [--may-no-trade] [--activate --confirm-live-activation] [--root <repo root>] [--dry-run]
```

- Without `--activate`, the CLI appends one `status: pending` entry and writes
  `.cursor/agents/<id>.md`, with frontmatter rendered from the active profile.
  A pending seat is in no pin or budget.
- `--activate --confirm-live-activation` flips the entry to `active` and
  creates cold-start state:
  - the trading memory files under `data/trading/trader/<id>/`, through the
    existing empty constructors;
  - a `$100m` cold-start seat in `data/overnight/books/latest.json`, built
    with `empty_seat`.

  It never creates positions, lessons or history. It refuses if any state
  already exists for that id. Existing seats and history stay byte-identical.
- Freeze-time `ensure_roster_books` is the idempotent safety net. It adds a
  cold-start seat for an active seat that is missing from `latest.json`, and
  never edits or removes an existing seat.
- Activating a real 15th seat needs the user's real persona and a separate
  authorization. This PR proves the path only with a synthetic seat in temp
  fixtures.

## 6. Staged migration

| Stage | Owner | Change | Gate |
| --- | --- | --- | --- |
| 0 (this PR) | Market Watch | v2 config, pins, derived budgets, role-verified hooks, onboarding CLI, candidate 4.7 profile defined but inactive | merged by a human; no runtime model change |
| 1 | ACP (separately authorized PR in the protected repo) | contract in `ACP_MODEL_ROSTER_MIGRATION_CONTRACT.md`: dedicated one-shot config, disabled schedule removed, parent `grok-4.7`, no MW subagent allowlist or trader count/models in ACP | explicit ACP authorization |
| 2 | Market Watch cutover PR | set `candidate-grok-4.7.status = active`, `active_profile = candidate-grok-4.7`, and the old profile's `status = retired`; run `agent_config render-agents`; verify with `check-agents` | lands only after stage 1 is live and a human authorizes the cutover |
| 3 (optional) | Market Watch | onboard a real 15th trader with the user's persona | explicit user profile and authorization |

Until stage 2, the ACP parent `grok-4.6` and the profile parent `grok-4.6`
agree. If they disagree, the first child spawn is denied before any spend.

### Compatibility matrix

| ACP parent | MW active profile | Marker | Result |
| --- | --- | --- | --- |
| grok-4.6 (today) | current-production-grok-4.6 | v1 or v2 | runs, 14 seats, 20/18/2 |
| grok-4.6 | candidate-grok-4.7 | any | denied at first child (parent mismatch) |
| grok-4.7 (after stage 1) | current-production-grok-4.6 | v2 | denied at first child (parent mismatch); do not run ACP stage 1 live before stage 2 is ready |
| grok-4.7 | candidate-grok-4.7 (stage 2) | v2 | runs; traders/PMs/advocates/rebuttals on grok-4.7, Composer roles on 2.5 |
| any | historical run without pin | v1 | validates against the legacy 14-seat / grok-4.6 pin |

### Roll forward

1. Merge stage 0. Daily and on-demand behaviour is unchanged apart from the
   `MW_ROLE` tags that the updated commands now emit.
2. Get stage 1 authorized and landed in ACP, behind ACP's own disabled flag.
3. Open the stage 2 PR, activate, re-render the agent files, and arm ACP.

### Roll back

- Stage 2: revert the cutover commit (profile status, `active_profile`,
  rendered frontmatter). Runs that are already frozen keep their own pins.
- Stage 0: revert this PR. Snapshots frozen while it was live carry an extra
  `agent_roster_pin` key. The old code ignores that key, and the key stays
  covered by the snapshot hash.
- Onboarding: remove the pending entry and its agent file. An activated
  seat's state is append-only history and is left in place, never deleted.
