# Market Watch — Persistent Trader Psychology: Architecture and Execution Graph

Status: PLAN ONLY · NOT IMPLEMENTED · NO LIVE BEHAVIOR CHANGED
Date: 2026-09-26
Planning parent: Claude Fable 5.1 (single provider execution, no subagents)
Control-plane issue: McCabeAI/agent-control-plane#167

## 0. Authorities inspected

| Authority | Ref | SHA | Role in this plan |
| --- | --- | --- | --- |
| `origin/main` | live baseline | `c4e526d65327ec1a0cf0c674b007c579b97fa933` | What Market Watch does today |
| PR #130 head (`cursor/implement-market-watch-trader-learning-v2-6769`) | unmerged Learning V2 | `7d271caf9305899eaf26e537fbb14d8229446a7c` | Proposed causal-learning layer; treated as a dependency, not as production |
| merge-base(main, #130) | | `d425eb62fb711f607b6b6b090c95395ad4ff98fd` | `main` has advanced one commit (`c4e526d`, carry-forward of US vintages/oil marks) past the #130 branch point; that commit does not touch `scripts/trading/**` |

This planning branch was cut from the PR #130 head so that the design can reference the Learning V2 modules (`scripts/trading/learning.py`, `learning_state.json`, lesson maturity, retrieval, learning default, examiner). Every place the design depends on #130 rather than `main` is marked **[#130]**. If #130 is rejected or reshaped, the sections marked **[#130]** must be re-planned; the core state engine (sections 4–6) does not depend on #130.

Baseline verification performed during planning (read-only): `tests.test_trader_psychology`, `tests.test_trader_learning_v2`, `tests.test_trading_memory` — 66 tests, all green at `7d271ca`.

Live data inspected (read-only): `data/trading/**` at `7d271ca` — 17 ledger trades (12 open, 5 closed), 120 journal events (98 `OVERNIGHT_DECISION`, 22 `PM_DECISION`) across 4 overnight runs (`overnight-20260922..25`) and 2 on-demand Trader Room runs; 0 performance reflections; 0 trader lessons (1 legacy ChatGPT PM lesson); 5 outstanding `postmortems_due` (catalyst-junkie 1, cross-merchant 1, positioning-cynic 2, value-guy 1); no `learning_state.json` files exist yet (confirms #130 has never run against production state).

---

## 1. Objective and non-goals

### 1.1 Objective

Give each of the 14 trader seats (and the 3 automated PMs) a **persistent, bounded, evidence-derived psychological state** that:

1. evolves only from that identity's own accepted trading history and already-authorized competitive facts;
2. decays toward a persona-specific baseline so no state is permanent;
3. is injected privately at decision time and makes specific self-check questions mandatory when specific risks are elevated;
4. never chooses, sizes, forces, or blocks a de-risking action, and never touches canonical marks, P&L, NAV, risk limits, funding, or rank;
5. is reproducible from an append-only event ledger, auditable, and idempotent under replay;
6. makes personas diverge through their histories (same event, persona-specific response) using transparent coefficient tables rather than per-seat bespoke logic.

### 1.2 Non-goals (explicit)

- No cartoon moods, random mood dice, sentiment prose, or a single opaque "emotion score".
- No public exposure. The state is private decision machinery. A later UI project may expose a curated view; this plan reserves nothing for it beyond keeping the schema clean.
- No change to canonical ledger/P&L/NAV/risk/funding semantics or to `HOLD`/`NO_TRADE`/`REDUCE`/`CLOSE` executability.
- No change to ACP, schedules, model caps, or shared policy.
- No rewriting of historical trades and no fabrication of unavailable mental states.
- No cross-identity information flow.

---

## 2. Diagnosis: what exists today versus what is missing

### 2.1 Layer map of the current system

| Surface | File / contract | Layer it actually implements |
| --- | --- | --- |
| Persona prompts | `.cursor/agents/<seat>.md` (14 traders, `swinger.md`, `pragmatist.md`, `grinder.md`) | Stable temperament as **prompt text only**; no numeric trait, no state |
| Own-book consequence | `scripts/trading/consequence.py::build_trader_consequence` / `build_pm_consequence` | Objective performance context: `net_pnl_usd`, `nav_usd`, `session_pnl_change_usd`, `drawdown_usd`, `giveback_usd`, `risk_capital_utilization`, `competition_rank`, `rank_change`, `recent_pattern` (`flat`/`drawdown`/`heater`/`mixed`), `pressure_flags` (`material_drawdown`, `risk_capital_pressure`, `rank_shock`) |
| Consequence snapshot | `consequence.py::record_consequence_observation` → `consequence_state.json` | Last-observation snapshot (`last_net_pnl_usd`, `last_competition_rank`, `last_drawdown_usd`, `last_high_water_nav_usd`) plus PM-only counters (`best_trader_outearn_streak`, `grinder_flat_snapshots`, `swinger_uncompensated_episodes`, episode anchors) |
| Allocator pressure (PM only) | `scripts/trading/capital_owner.py::build_capital_owner` | Mandate standing `good_standing`/`watch`/`probation`, PM-specific notes, `force_deployment: false` always |
| Reflection triggers | `scripts/trading/memory.py::performance_triggers`, `ensure_reflections_due` | Threshold events at `MATERIAL_DRAWDOWN_FRACTION (0.40) × max_drawdown` = **$2M trader / $20M PM**: `material_drawdown`, `material_loss`, `material_win`, `giveback`, `new_high`, `rank_shock (+4)` |
| Reflection self-reports | `memory.py::accept_performance_reflection` → `reflections.json` | Model-authored `pressure_effect`, `skill_vs_luck`, `overconfidence_risk`, `chase_or_revenge`, `attribution`, **[#130]** `causal` block |
| Pressure self-check gate | `scripts/trading/gate.py::requires_pressure_assessment`, `_pressure_assessment_valid` | Requires `pressure_assessment` (`judgment_effect`, `junior_vs_self`, `chase_temptation`, `protecting_gains`, `heater_risk`, `allocator_vs_noise`) — **only when PM competitive flags or PM standing apply** |
| Learning gate | `gate.py::learning_gate_reason`, `evaluate_decision_actions` | Per-action fail-closed on `OPEN`/`ADD`/`HEDGE` for stale hash, prior-run `postmortems_due`/`reflections_due`, missing pressure assessment, **[#130]** unaddressed matching lessons |
| Apply / persistence | `scripts/trading/apply.py::apply_trader_review_with_memory`, `apply_pm_decision_with_memory`, `_prepare_identity` | Reflections applied → **[#130]** `settle_learning_compliance` → gate → book apply → ledger sync → journal → marks → consequence observation → `build_memory_context` |
| Memory context / sidecar | `memory.py::build_memory_context`, `scripts/trading/snapshot.py::compact_memory_for_packet` | The provider-visible private block hashed as `memory_context_sha256` (`MEMORY_SCHEMA_VERSION = 3` **[#130]**) |
| Learning V2 state **[#130]** | `learning.py`, `learning_state.json` | `learning_status`, `learning_default_*`, `competition_eligible`, `retrieved_lessons`, `repeated_error_escalations`; lesson `maturity`, `scope`, `future_rule`, `history`; examiner contract |
| Public boundary | `scripts/overnight/public_prose.py` (`_MACHINE_PATTERNS`, `_SCRUB_RES`, `_PRIVATE_ALERT_MARKERS`), `books.public_books_view`, `pm.books.public_pm_view` | Strips private psychology/learning machinery from public prose and alerts |
| Provider contract | `.cursor/commands/overnight-scheduled.md`, `trader-room.md`, `portfolio-managers.md`; `scripts/overnight/scheduled_output.py::validate_output`, `FORBIDDEN_MODEL_STATE_KEYS`; `scripts/pm/automated.py`; `scripts/trader_room/paper_book.py::_learning_fields`; hooks in `.cursor/hooks/` | What the model receives, what it may return, what is forbidden |

### 2.2 What today's system already does well (keep, do not rebuild)

1. **Objective consequence is clean and own-book only.** `assert_trader_consequence_clean` forbids peer P&L keys; rank is the only competitive fact traders see. PMs see spread-to-leader and best-trader gap by explicit design.
2. **De-risk is never blocked.** `evaluate_decision_actions` keeps `HOLD`/`NO_TRADE`/`REDUCE`/`CLOSE` executable; `raise_if_unexecutable` only raises for pure invalid expansion.
3. **Hash chain.** `memory_context_sha256` covers the whole context body; any injected block automatically participates in stale-context detection at `scheduled_output.validate_output` and `learning_gate_reason`.
4. **Idempotent apply.** `find_event` / `decision_fingerprint` / `ReviewAlreadyApplied` make replay of an accepted review a no-op per seat.
5. **PM-specific allocator pressure** is already episode-based (Swinger) and opportunity-aware (Grinder), with `force_deployment: false` hard-coded.
6. **[#130]** Causal reflections, lesson maturity, own-lesson retrieval with mandatory `APPLIES`/`DOES_NOT_APPLY`/`OVERRIDE`, learning default with competitive-eligibility removal, and a one-call examiner that cannot author trades.

### 2.3 What is missing (the gap this plan fills)

| # | Gap | Evidence | Consequence |
| --- | --- | --- | --- |
| G1 | **No persistent psychological state.** `consequence_state.json` stores only the last observation and a few PM counters. Nothing carries mood-like information across runs; nothing decays. | `record_consequence_observation` patch keys | Personas are stateless prompt costumes; histories do not differentiate them |
| G2 | **Trader pressure self-check never fires.** `requires_pressure_assessment` returns `False` unless `behind_leading_pm`/`best_trader_ahead`/`competitive_pressure` (PM-only flags) or PM `capital_owner.standing ∈ {watch, probation}`. Trader flags (`material_drawdown`, `risk_capital_pressure`, `rank_shock`) are ignored. | `gate.py` L97–115 | Traders have no mandatory pressure check even after a rank shock or material drawdown |
| G3 | **Decision-time self-reports are not persisted.** `pressure_assessment` is validated at the gate but `record_event`/`compact_actions` never store it; `_learning_fields` passes it through from Trader Room contributions only to be dropped. | `journal.py::compact_actions`, `apply.py::record_event` calls | Cannot later score whether pressure sharpened or distorted judgment |
| G4 | **Reflection self-reports have no feedback.** `pressure_effect`, `chase_or_revenge`, `overconfidence_risk`, `skill_vs_luck` are stored in `reflections.json` and echoed in `recent_performance_reflections`, but nothing consumes them. | `memory.py` L767–891 | Honest admissions have no consequence; dishonest ones have no cost |
| G5 | **Thresholds are dormant at live scale.** Reflection triggers require $2M (trader) / $20M (PM) moves; the largest live seat P&L is +$418,551 (dollar-king), largest drawdown $116,327 (cross-merchant). | `data/overnight/books/latest.json` at `7d271ca` | No `reflections_due` has ever been created in production; the existing "psychology" layer has never engaged |
| G6 | **Trade-level events are not turned into state.** Stop-outs, quick re-entries after a loss, size escalation after wins, holding through pain — none are detected. | `ledger.py` records facts; nothing reads them for behavior | Revenge/complacency/attachment are unobservable today |
| G7 | **No persona differentiation in response.** The same drawdown produces the same `pressure_flags` for Dollar King and No-Trade Skeptic. | `consequence.py::_trader_pressure_flags` | Convergent dynamics |
| G8 | **[#130] Three journal triggers read dead fields.** `journal_learning_triggers` reads `close_path`, `expression_vs_thesis`, `reaction_vs_expectation` on CLOSE events; `record_lifecycle_event` has no such parameters and no caller writes them (verified by repository-wide search). Only `exit_reason_category`-based triggers (`thesis_invalidated`, `stop_or_forced_exit`) can fire, and only if the model supplies `exit_reason_category` (none of the 5 live closed trades has one). | `learning.py` L473–498 vs `ledger.py` L200–214 | `close_reason_diverges`, `right_thesis_wrong_expression`, `catalyst_or_reaction_diverged` never fire; psychology V1 must not depend on them |
| G9 | **[#130] Lesson dispositions are not persisted.** `record_retrieved_lessons` stores `(lesson_id, run_id, at)` only; `lesson_considerations` (`APPLIES`/`DOES_NOT_APPLY`/`OVERRIDE` + rationale) are validated then discarded. | `learning.py` L393–413 | Cannot detect "successful correction of a learned mistake" or "override that failed" |
| G10 | **No flat-period tracking for traders.** Grinder has `grinder_flat_snapshots`; traders have nothing. | `consequence.py` L392–401 | Chase/FOMO unobservable for 14 seats |
| G11 | **No separation of trait vs. state vs. context vs. lesson.** Persona lives in prose; consequence and PM counters live together in `consequence_state.json`; reflections live in `reflections.json`. | store layout | Double counting risk when a new layer is added without an explicit event ledger |

### 2.4 Objective consequence signals vs. true persistent psychology

Objective consequence signals (exist; L1 below): P&L, NAV, drawdown, HWM, giveback, risk utilization, rank, rank change, PM spread/gap, allocator standing, learning status, reflection/postmortem debt, closed-trade facts (realized, MFE/MAE, holding period, conviction, exit category).

True persistent psychology (missing; L2 below): a bounded state per identity that integrates those signals over time with persona-specific gains and decay, records *why* it moved, and shapes deliberation through mandatory self-checks and recorded overrides without ever choosing an action.

---

## 3. Four-layer model and double-counting rules

| Layer | Name | Owner | Mutability | Contents | Where it lives |
| --- | --- | --- | --- | --- | --- |
| L0 | Persona / temperament | Trusted code (versioned table) | Static per `profile_version`; changed only by a reviewed commit | Per-identity axis baselines, per-axis gain multipliers, per-axis half-life multipliers, remit tags (e.g. `flat_by_design`) | NEW `scripts/trading/psychology_profiles.py` |
| L1 | Objective consequence / performance context | Trusted code (exists) | Rebuilt every context build from canonical books/ledger | Everything in §2.4 "objective" | `consequence.py`, `capital_owner.py`, `ledger.py`, **[#130]** `learning.py` |
| L2 | Transient psychological state | Trusted code (NEW engine) | Updated **once per accepted decision cycle** from a canonical psych-event ledger; decays toward L0 baseline | 8 bounded axes, streak counters, instrument tags, active risk flags, provenance, metrics | NEW `psychology_events.json`, `psychology_state.json` |
| L3 | Durable learned lessons | Trusted code + model-authored structured lessons (**[#130]** semantics unchanged) | Lesson ops `add`/`reinforce`/`refine`/`contradict`/`retire` | Lessons, maturity, scope, future rule, history; reflections; postmortems | `lessons.json`, `reflections.json`, `postmortems.json`, `learning_state.json` |

### 3.1 Single-home rule

Every fact has exactly one *home* layer. L2 never stores facts; it stores **events derived from facts** plus the **deltas applied**. L1 facts are read, never written, by L2. L3 lessons are read, never written, by L2.

### 3.2 Double-counting prevention

1. **One P&L observation → at most one P&L event family per cycle.** Session delta (`session_gain`/`session_loss`) is computed from `consequence_state.last_net_pnl_usd` exactly as `session_pnl_change_usd` is today. Trade-close events (`trade_win_close`/`trade_loss_close`) are keyed by `trade_id` and fire once. A closed trade contributes to *both* a trade event and the session delta, by design: the trade event carries instrument-tagged evidence (revenge), the session event carries book-level evidence (frustration/defensiveness). Their base deltas are sized so the sum stays inside the per-cycle cap (§5.4).
2. **Reflections do not re-apply P&L.** When a reflection is accepted for a `reflections_due` item, the underlying `material_*` event already moved L2 when it happened. The reflection may only add small *self-report admission* events (§5.3, E21–E23), which can raise risk axes or lower `self_trust`, never the reverse.
3. **Lessons do not move L2 by existing.** Creating/reinforcing/refining a lesson has zero L2 effect. Only three L3-derived *new facts* move L2: `lesson_contradicted_after_retrieval` (**[#130]** repeated-error escalation), `correction_success` / `override_failed` / `override_vindicated` (requires G9 fix), and `learning_default_entered/cleared` (**[#130]**).
4. **L1 pressure flags are not re-counted.** `material_drawdown`, `rank_shock`, PM competitive flags remain L1 facts shown to the model as today. L2 consumes the *transition* (e.g. rank change value, standing change), not the standing flag, except the slow-build PM competitive event (E26) which is explicitly per-cycle and capped.
5. **Trusted verdicts feed one axis pair only.** `verdict_distorted`/`verdict_sharpened` move `self_trust` and `frustration` by small fixed amounts and increment metrics; they do not re-touch the axes that produced the flag.

---

## 4. Persistent psychological state model

### 4.1 Dimension evaluation

| Candidate | Behaviorally meaningful? | Measurable from own objective events? | Decision |
| --- | --- | --- | --- |
| Confidence / self-trust | Yes — weight on own view vs. packet; sizing steadiness | Yes — win/loss vs. conviction, correction successes, verdicts | **Retain** as `self_trust` (bipolar around baseline: fragile ↔ inflated) |
| Frustration | Yes — impulsivity, shortened patience | Yes — stop-outs, givebacks, blocked expansions, learning default, repeated failures | **Retain** as `frustration` (short half-life) |
| Loss aversion | Yes — reluctance to deploy / premature cut after losses | Partly — proxied by drawdown, loss streaks, risk-cut closes | **Merge** into `defensiveness` |
| Gain-protection tendency | Yes — locking gains, reducing valid positions to defend P&L/rank | Partly — giveback after new high, reduces while thesis intact | **Merge** into `defensiveness`. Both produce the same observable bias (premature de-risk, reluctance to add) and the same self-check ("is this de-risk thesis-driven or P&L-driven?"). The driver differs and is kept as event provenance (`source: loss` vs `source: gain`), not as a second axis |
| Chase / FOMO pressure | Yes — manufacturing trades when flat or behind | Yes — flat streaks while the market packet is fresh, rank drops, blocked expansions | **Retain** as `chase_pressure` |
| Revenge impulse | Yes — re-engaging the instrument that hurt, larger | Yes — loss close followed by same-family re-entry within N cycles, size vs. prior loss | **Retain** as `revenge_pressure` with instrument-family tags; kept separate from chase because trigger, target and half-life differ |
| Complacency / heater risk | Yes — size creep, skipped invalidation, overconfidence after streaks | Yes — win streaks, new highs, size escalation after streaks, rank 1–3 | **Retain** as `complacency` (asymmetric: falls faster than it rises) |
| Thesis attachment / stubbornness | Yes — holding through invalidation, adding to losers, overriding own lessons | Yes — hold-through-pain cycles, repeated same-thesis failures, `OVERRIDE` dispositions that failed **[#130]** | **Retain** as `thesis_attachment` |
| Allocator / competitive pressure | Yes — but the *objective* part already exists in L1 (rank, standing, spread) | The *felt* accumulation is measurable from rank shocks, standing changes, learning default, persistent behind-flags | **Retain the felt state** as `external_pressure`; the objective part stays in L1 unchanged |
| Conviction stability | Meaningful as a symptom, not a driver | Yes — stdev of stated conviction across recent decisions | **Reject as a state axis**; report `conviction_volatility` as an L1 descriptive metric inside the psychology block; it feeds nothing |

Retained: **8 axes**. Every axis is a float in `[0, 1]`, stored to 4 decimals, shown to the model at 2 decimals with a band label.

### 4.2 Axis definitions (neutral baseline profile; PROPOSED values, not observed facts)

| Axis | Meaning at 0 → 1 | Neutral baseline | Half-life (accepted cycles) | Bands (enter / exit hysteresis) |
| --- | --- | --- | --- | --- |
| `self_trust` | 0 = fragile, will not back own read; 1 = inflated, dismisses disconfirming evidence | 0.50 | 12 | `fragile` ≤0.30 (exit >0.35); `steady` 0.30–0.70; `inflated` ≥0.75 (exit <0.70) |
| `frustration` | accumulated irritation from adverse/blocked outcomes | 0.10 | 3 | `elevated` ≥0.40 (exit <0.30); `high` ≥0.60 (exit <0.50) |
| `defensiveness` | reluctance to hold/add risk; urge to protect the book | 0.20 | 6 | `elevated` ≥0.45 (exit <0.35); `high` ≥0.60 (exit <0.50) |
| `chase_pressure` | urge to put on risk for non-thesis reasons (flat, behind) | 0.10 | 4 | `elevated` ≥0.35 (exit <0.25); `high` ≥0.50 (exit <0.40) |
| `revenge_pressure` | urge to re-engage what hurt | 0.05 | 2 | `elevated` ≥0.30 (exit <0.20); `high` ≥0.45 (exit <0.35) |
| `complacency` | streak-driven confidence detached from process | 0.10 | 5 | `elevated` ≥0.40 (exit <0.30); `high` ≥0.55 (exit <0.45) |
| `thesis_attachment` | resistance to invalidation | 0.25 | 8 | `elevated` ≥0.45 (exit <0.35); `high` ≥0.60 (exit <0.50) |
| `external_pressure` | felt rank/allocator/learning-default pressure | 0.10 | 6 | `elevated` ≥0.35 (exit <0.25); `high` ≥0.50 (exit <0.40) |

Hysteresis prevents band flapping from noisy daily P&L.

### 4.3 Interactions (explicit, few)

| Interaction | Rule (applied when computing an event's deltas) |
| --- | --- |
| Frustration amplifies revenge | `Δrevenge × (1 + 0.5 × frustration)` |
| External pressure amplifies chase | `Δchase × (1 + 0.5 × external_pressure)` |
| Complacency dampens defensiveness gains | positive `Δdefensiveness × (1 − 0.5 × complacency)` |
| Fragile self-trust amplifies defensiveness gains | positive `Δdefensiveness × (1 + 0.5 × max(0, 0.5 − self_trust))` |
| Correction success relieves attachment and frustration | encoded directly in event E17 deltas |
| Streak multipliers | loss streak k ≥ 2: `× min(2.0, 1 + 0.25(k−1))` on `frustration`/`revenge`/`defensiveness` deltas of loss events; win streak k ≥ 2: same multiplier on `complacency` deltas of win events |

No other cross-axis coupling. Interactions are multiplicative on the *delta*, never on the stored value, so they cannot create drift without events.

### 4.4 Derived risk flags (transparent thresholds; these gate self-checks)

| Flag | Activation (enter) | Deactivation (exit) | Relevant actions |
| --- | --- | --- | --- |
| `revenge_risk` | (a) `revenge_pressure ≥ 0.45` → relevant to **all** `OPEN`/`ADD`; or (b) any active revenge tag (created by E4/E5, ttl 3 cycles, refreshed by a new loss in the family) → relevant only to `OPEN`/`ADD` **in the tagged instrument family**, at any level. The `basis` names the family and the loss run | (a) `< 0.30`; (b) tag expiry | `OPEN`/`ADD` (required check). The tag is the memory of the wound; the level says how hot it is. A re-entry into a family that hurt within the last 3 cycles always answers the three revenge questions; the check never blocks |
| `heater_risk` | `complacency ≥ 0.55`, or `≥ 0.45` with win streak ≥ 3 | `< 0.45` | `OPEN`/`ADD` (required) |
| `chase_risk` | `chase_pressure ≥ 0.50` | `< 0.40` | `OPEN` (required) |
| `stubbornness_risk` | `thesis_attachment ≥ 0.60` | `< 0.50` | `ADD` (required); any `lesson_considerations.disposition = OVERRIDE` (required) **[#130]**; `HOLD` with an open position in unrealized loss ≥ 1 unit (recorded, optional) |
| `capitulation_risk` | `defensiveness ≥ 0.60` **and** `frustration ≥ 0.40` | either falls below its exit band | `REDUCE`/`CLOSE` (recorded, optional — never blocks); `NO_TRADE`/`HOLD` with fresh packet (recorded, optional) |
| `rank_distortion_risk` | `external_pressure ≥ 0.50` | `< 0.40` | `OPEN`/`ADD`/`HEDGE` (required for traders; for PMs a valid existing `pressure_assessment` satisfies it) |
| `fragile_confidence` | `self_trust ≤ 0.30` | `> 0.35` | informational; pairs with `capitulation_risk` prompt |
| `inflated_confidence` | `self_trust ≥ 0.75` | `< 0.70` | informational; pairs with `heater_risk` prompt |

A flag never maps to an action. It maps to a **required or optional check** (§7).

---

## 5. Event catalog and update mechanics

### 5.1 Update rule

One accepted cycle is processed in a fixed order: **decay first, then events, then cap**. The decay tick represents the cycle that elapsed since the identity's last accepted cycle; the events represent what happened in this cycle. Ordering it this way means the model sees this cycle's experience at full strength at its next decision, and that older state has already faded by exactly one half-life step.

Step 1 — exactly one decay tick (skipped on the very first accepted cycle after seeding, when state equals baseline):

```
x0 = b + (x − b) × 2^(−1 / (H[axis] × Hmult[identity][axis]))
```

`b` is the L0 baseline, `H` the neutral half-life in accepted cycles. The tick is keyed by `(run_id, review_id)` and applied once per identity per accepted cycle. It is **never** applied inside `build_memory_context`, which is called many times per cycle and must be a pure read.

Step 2 — for each canonical psych event `e` of the cycle, with normalized magnitude `m ∈ [0, 1]`, base delta table `B[e][axis]`, persona gain `G[identity][axis]`, interaction multiplier `I` (§4.3, evaluated on the post-decay state `x0`), streak multiplier `S`:

```
raw   = B[e][axis] × m × G[identity][axis] × I × S
delta = raw × (1 − x)   if raw > 0      # saturating toward 1
      = raw × x         if raw < 0      # saturating toward 0
```

Step 3 — the summed per-axis event deltas are capped at `±PSYCH_CYCLE_CAP = 0.25`, then applied: `x' = clip(x0 + capped_sum, 0, 1)`.

### 5.2 Magnitude normalization

```
unit           = PSYCH_UNIT_FRACTION (0.25) × material_threshold
material_threshold = MATERIAL_DRAWDOWN_FRACTION (0.40) × max_drawdown_usd   # unchanged existing constant
                   = $2,000,000 trader → unit $500,000 ; $20,000,000 PM → unit $5,000,000
dead_band      = PSYCH_DEAD_BAND_FRACTION (0.02) × material_threshold  # $40,000 trader / $400,000 PM
m(Δ)           = 0 if |Δ| < dead_band else min(1, |Δ| / unit)
```

This makes psychology live at current activity levels (dollar-king's +$418,551 run would register `m ≈ 0.84`) **without changing the existing reflection thresholds**, which stay at 100% of material.

### 5.3 Canonical event catalog

Detection is deterministic and runs in the post-apply observer (§9). Base deltas are PROPOSED and will be tuned only via the fixture scenarios (§12); they are not production facts. Blank = 0.

| ID | Event | Source / detection | m | self_trust | frustration | defensiveness | chase | revenge | complacency | thesis_att. | ext_pressure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E1 | `session_gain` | L1 `session_pnl_change_usd > dead_band` | m(Δ) | +0.04 | −0.06 | −0.03 | −0.02 | −0.04 | +0.06 | | −0.02 |
| E2 | `session_loss` | L1 `session_pnl_change_usd < −dead_band` | m(Δ) | −0.04 | +0.08 | +0.06 | | +0.03 | −0.10 | +0.02 | +0.02 |
| E3 | `trade_win_close` | ledger CLOSE with `realized_pnl_usd > dead_band` | m(realized) | +0.06 | −0.05 | −0.02 | | −0.05 | +0.05 | −0.02 | |
| E4 | `trade_loss_close` | ledger CLOSE with `realized_pnl_usd < −dead_band`; creates revenge tag `(instrument_family, side, run_id, ttl=3)` | m(realized) | −0.06 | +0.08 | +0.05 | | +0.08 | −0.08 | +0.03 | |
| E5 | `stop_or_risk_cut_close` | CLOSE with `exit_reason_category = risk_cut` **or** book alert "max drawdown breached" forced flat; supersedes E4 for that trade | m(realized) | −0.06 | +0.12 | +0.10 | | +0.10 | −0.15 | +0.02 | +0.03 |
| E6 | `giveback` | HWM > starting NAV and drawdown newly ≥ 1 unit (scaled analogue of existing `giveback` trigger, which stays at material) | m(drawdown) | −0.03 | +0.08 | +0.12 | | +0.02 | −0.20 | | +0.02 |
| E7 | `new_high` | HWM rose by ≥ 1 unit above prior HWM and above starting NAV | m(ΔHWM) | +0.05 | −0.05 | −0.02 | −0.02 | −0.02 | +0.10 | +0.02 | −0.03 |
| E8 | `rank_shock` | L1 `rank_change ≥ +4` (existing) | 1 | −0.03 | +0.08 | | +0.10 | | −0.05 | | +0.20 |
| E9 | `rank_drop_minor` | `rank_change ∈ {+2, +3}` | 1 | | +0.03 | | +0.04 | | | | +0.08 |
| E10 | `rank_gain_major` | `rank_change ≤ −3` | 1 | +0.02 | −0.03 | | −0.03 | | +0.05 | | −0.08 |
| E11 | `flat_with_market` | identity has no open positions, action ∈ {HOLD, NO_TRADE}, frozen `market_state` family `fresh`, `flat_cycles ≥ 3`; fires once per cycle | 1 | | +0.02 | | +0.05 | | | | +0.02 |
| E12 | `blocked_expansion` | own `OPEN`/`ADD`/`HEDGE` recorded `result = blocked` this cycle | 1 per action, cap 2 | | +0.05 | | +0.02 | | | | +0.02 |
| E13 | `learning_default_entered` **[#130]** | `learning_status` transitioned to `learning_default` this cycle | 1 | −0.05 | +0.10 | | | | | | +0.20 |
| E14 | `learning_default_cleared` **[#130]** | transitioned away from `learning_default` | 1 | +0.03 | −0.10 | | | | | | −0.15 |
| E15 | `lesson_contradicted_after_retrieval` **[#130]** | `repeated_error_escalations` count increased this cycle | 1 per escalation, cap 2 | −0.08 | +0.10 | | | +0.03 | −0.05 | +0.15 | +0.03 |
| E16 | `override_failed` **[#130 + G9 fix]** | CLOSE with realized < −dead_band on a trade whose opening decision carried `disposition = OVERRIDE` or `DOES_NOT_APPLY` for a materially matching lesson | m(realized) | −0.06 | +0.06 | | | | −0.05 | +0.12 | |
| E17 | `correction_success` **[#130 + G9 fix]** | CLOSE with realized ≥ 0 on a trade whose opening decision carried `disposition = APPLIES` for a materially matching lesson | max(0.5, m) | +0.10 | −0.10 | −0.03 | | −0.05 | | −0.10 | −0.03 |
| E18 | `override_vindicated` **[#130 + G9 fix]** | CLOSE with realized > dead_band after `OVERRIDE` | m(realized), cap 0.5 | +0.04 | −0.02 | | | | +0.04 | +0.03 | |
| E19 | `size_escalation_after_streak` | expansion whose position risk capital > 1.5 × trailing mean of own last 4 openings, with win streak ≥ 2 | 1 | | | −0.02 | | | +0.10 | | |
| E20 | `reentry_same_family_after_loss` | `OPEN`/`ADD` matching an active revenge tag (family + either side) within ttl | 1 (×1.5 if notional > lost trade's initial notional) | | +0.02 | | | +0.15 | | +0.03 | |
| E21 | `self_report_admission_chase_or_revenge` | accepted reflection with `chase_or_revenge = yes` | 1 | | | | +0.05 | +0.05 | | | |
| E22 | `self_report_admission_overconfidence` | reflection `overconfidence_risk = yes` | 1 | | | | | | +0.05 | | |
| E23 | `self_report_admission_pressure_distorting` | reflection `pressure_effect = distorting` or decision-time `pressure_read = distorting` | 1 | −0.03 | | | | | | | +0.05 |
| E24 | `hold_through_pain` | open position with unrealized loss ≥ 1 unit for ≥ 3 consecutive cycles with no `REDUCE`; fires per cycle, cap 3 per position | 1 | | +0.02 | | | | | +0.06 | |
| E25 | `allocator_standing_worsened` (PM) | `capital_owner.standing` moved good→watch or watch→probation | 1 | −0.02 | +0.05 | +0.03 | +0.03 | | | | +0.25 |
| E26 | `competitive_flag_active` (PM) | `behind_leading_pm` or `best_trader_ahead` present this cycle | 1 per cycle | | +0.01 | | +0.02 | | | | +0.05 |
| E27 | `allocator_standing_restored` (PM) | standing returned to `good_standing` | 1 | +0.02 | −0.05 | | | | | | −0.15 |
| E28 | `verdict_distorted` | trusted post-outcome verdict (§7.5) | 1 | −0.05 | +0.05 | | | | | | |
| E29 | `verdict_sharpened` | trusted verdict | 1 | +0.05 | −0.03 | | | | | | |
| E30 | `decay_tick` | once per accepted cycle | — | decay | decay | decay | decay | decay | decay | decay | decay |

Events **not** used in V1 because their inputs have no writer (G8): anything requiring `close_path`, `expression_vs_thesis`, `reaction_vs_expectation`. "Right thesis / wrong expression" is represented in V1 only through the model's own reflection `attribution ∈ {expression}` + `causal.decision_quality_attribution = expression` on an accepted reflection, which yields a **softened** E4 (frustration ×0.5, thesis_attachment 0) when the reflection is accepted in the same or next cycle — see scenario S3.

### 5.4 Per-cycle bound

Sum of all event deltas per axis per cycle is clipped to ±0.25 (after decay, before applying). With neutral gains and `m = 1`, a worst-case losing cycle (E2 + E5 + E6 + E8) would raise `frustration` by ~0.36 raw; the cap holds it at 0.25. This bounds the response to any single bad day regardless of stacking. A consequence worth stating: because the cap and decay work together, no axis can reach a `high` band or a level-based required-check threshold from its neutral baseline in one cycle (persona baseline shifts keep this true for every flag except `stubbornness_risk` for the personas with a raised `thesis_attachment` baseline, which is intended: their stubbornness sits closer to the surface), and a low-intensity recurring event (E26 alone, E11 alone) converges to a plateau below the required-check thresholds — e.g. `external_pressure` under E26 every cycle plateaus at ≈0.38 for the neutral profile, below `rank_distortion_risk` (0.50). Crossing a required-check threshold always needs a discrete adverse event on top of the grind.

### 5.5 Provenance

Each event record stores: `event_id`, `seq`, `run_id`, `review_id` (or `review_packet_id`/`trader_room_run_id`), `at`, `kind`, `magnitude`, `subject` (`trade_id`, `position_id`, `instrument`, `lesson_id`, `reflection_id`, `rank_from/to`, `standing_from/to` as applicable), `source` (`layer: L1|L3|verdict|self_report`, `refs: [...]`), `multipliers` (`persona`, `interaction`, `streak`, `saturation`), `deltas_applied` (per axis, after saturation, before cap), `cap_applied` (bool), `provenance: live|backfilled|fixture`. The state file stores `last_event_seq` and a `state_sha256`; `replay(events[0..seq], profile) == state` is a test invariant.

---

## 6. Event → state transitions for representative sequences

Illustrative trajectories use the **neutral profile** unless a persona is named. Values are PROPOSED/ILLUSTRATIVE outputs of the §5 rules (decay → events → cap, §5.1), rounded to 2 decimals, not production observations. Each value is the end-of-cycle state the seat would see at its next decision. `unit` = $500K (trader). The same arithmetic was checked with a throwaway script outside the repository; the fixtures in node A2 will make these trajectories executable tests.

| Sequence | Cycle-by-cycle events | Resulting state movement (illustrative) | Flags |
| --- | --- | --- | --- |
| Three consecutive winning sessions + new high | E1 m=0.8; E1 m=1.0 (streak 2, ×1.25); E1 m=1.0 + E7 m=1.0 (streak 3, ×1.5) | `complacency` 0.10 → 0.14 → 0.20 → 0.34; `self_trust` 0.50 → 0.52 → 0.53 → 0.58; `frustration` drifts to 0.08 | none yet (`heater_risk` needs 0.55, or 0.45 with win streak ≥ 3 → roughly one more winning session at a new high) |
| Three consecutive losing sessions | E2 m=0.6; E2 m=0.8 (×1.25); E2 m=1.0 (×1.5) | `frustration` 0.10 → 0.14 → 0.20 → 0.28; `defensiveness` 0.20 → 0.23 → 0.27 → 0.33; `self_trust` 0.50 → 0.49 → 0.47 → 0.46; `complacency` → 0.08 | none (frustration `elevated` needs 0.40) |
| Stop-out (risk_cut) after a loss streak | prior state from row above, then E5 m=1.0 + E2 m=1.0 (streak 4, ×1.75) | `frustration` 0.28 → 0.49 (raw sum ≈0.31, cap 0.25 binds); `revenge` 0.13 → 0.33 with a tag on the instrument family; `defensiveness` 0.33 → 0.50; `complacency` → 0.06 | `frustration elevated`; `defensiveness elevated`; `revenge_risk` is required on the next OPEN/ADD in the tagged family (tag rule) but not on other instruments (general threshold 0.45) |
| Giveback after new high | state: `complacency` 0.45, HWM +$1.2M; then E6 m=1.0 + E2 m=1.0 | `complacency` 0.45 → 0.28 (falls fast: −0.30 raw on a 0.45 base); `defensiveness` 0.20 → 0.32; `frustration` 0.10 → 0.24 | none required; `capitulation_risk` not active (needs defensiveness 0.60 and frustration 0.40) |
| New highs repeatedly (5 cycles) | E1+E7 each cycle, win streak 5 (×2.0 capped) | `complacency` 0.15 → 0.30 → 0.41 → 0.50 → 0.57; `self_trust` → 0.66 by cycle 5 | `heater_risk` from cycle 4 (0.50 ≥ 0.45 with streak ≥ 3; unconditional 0.55 at cycle 5); `inflated_confidence` (0.75) not reached |
| Repeated same-thesis failures **[#130]** | E4 m=0.6 (lesson created); next cycle `OVERRIDE` on that lesson → E4 m=0.7 → E16 m=0.7 + E15 (escalation) | `thesis_attachment` 0.25 → 0.26 → 0.45 (E16 +0.12, E15 +0.15 saturated; cap not reached); `self_trust` → 0.40; `frustration` → 0.32 | `thesis_attachment elevated`; `stubbornness_risk` (0.60) after one more attachment event; `OVERRIDE` dispositions require a `stubbornness_risk` check only once the flag is active |
| Right thesis / wrong expression | E4 m=0.5 with same-cycle accepted reflection attributing `expression` → softened E4 | `frustration` +0.02 only; `thesis_attachment` unchanged; `self_trust` −0.015 | none |
| Lucky win (reflection `skill_vs_luck = luck`, MAE deep before recovery) | E3 m=1.0 (complacency +0.05 saturated); reflection records `luck` (no state change, by anti-gaming rule) but the trusted verdict later uses it | `complacency` +0.045 (0.10 → 0.15); `self_trust` +0.03 | none; the `luck` admission caps nothing but is stored for §7.5 |
| Long flat period, credible market (No-Trade Skeptic vs. Catalyst Junkie) | E11 per cycle from cycle 3 | Skeptic (`chase` gain 0.4 × `flat_by_design` 0.25): 0.10 → 0.12 by cycle 6 (decay dominates). Catalyst Junkie (gain 1.5): 0.10 → 0.17 → 0.23 → 0.27 → 0.30 over cycles 3–6 | Neither reaches `chase elevated` (0.35) on flatness alone; the Junkie needs a rank event on top (see S4). Sitting out is never, by itself, enough to trigger a required check |
| Long flat period, no credible market (`market_state` not fresh) | no E11 | no chase movement for anyone | none |
| Rank shock (3 → 9) | E8 | `external_pressure` 0.10 → 0.28; `chase` 0.10 → 0.20; `frustration` 0.10 → 0.17 | none yet; a second shock or `learning_default_entered` would bring `rank_distortion_risk` to its threshold |
| Allocator pressure (PM → watch) | E25 + E26, then E26 per cycle while behind | `external_pressure` 0.10 → 0.35 (cap binds) → 0.36 → 0.36 → 0.37 … plateau ≈0.38; `frustration` +0.05 | `external elevated`; `rank_distortion_risk` (0.50) is **unreachable** from E26 alone — it needs a further standing step (watch → probation), a learning default (E13) or a rank shock. Existing PM `pressure_assessment` requirement already applies and is not duplicated |
| Learning-default event **[#130]** | E13; while default persists no further E13 (transition-only) | `external_pressure` 0.10 → 0.28; `frustration` 0.10 → 0.19; `self_trust` 0.50 → 0.475 | if combined with an earlier rank shock → `rank_distortion_risk` reaches threshold |
| Successful correction of a learned mistake **[#130 + G9]** | E17 m=1.0 | `self_trust` +0.05 (saturating); `frustration` −0.01 from baseline or −0.10 from 0.40; `thesis_attachment` −0.025 from 0.25 or −0.08 from 0.55 (event plus that cycle's decay) | may clear `stubbornness_risk` when attachment falls under 0.50 |

---

## 7. Decision-time contract

### 7.1 What is injected (private sidecar only)

`build_memory_context` gains a `psychology` block (pure read of `psychology_state.json`; no side effects; no clock):

```json
"psychology": {
  "schema_version": 1,
  "profile_version": 1,
  "state_sha256": "<sha256 of psychology_state.json body>",
  "axes": {
    "self_trust":        {"value": 0.57, "band": "steady",   "trend": "up"},
    "frustration":       {"value": 0.12, "band": "calm",     "trend": "flat"},
    "defensiveness":     {"value": 0.19, "band": "calm",     "trend": "flat"},
    "chase_pressure":    {"value": 0.08, "band": "calm",     "trend": "down"},
    "revenge_pressure":  {"value": 0.04, "band": "calm",     "trend": "flat"},
    "complacency":       {"value": 0.47, "band": "elevated", "trend": "up"},
    "thesis_attachment": {"value": 0.33, "band": "calm",     "trend": "flat"},
    "external_pressure": {"value": 0.09, "band": "calm",     "trend": "flat"}
  },
  "streaks": {"session_win": 3, "session_loss": 0, "flat_cycles": 0},
  "active_flags": [
    {"id": "heater_risk",
     "basis": "complacency 0.47 with 3 consecutive winning sessions and a new high on the prior cycle",
     "relevant_actions": ["OPEN", "ADD"],
     "check": "required"}
  ],
  "required_checks": {"heater_risk": ["size_vs_trailing_average", "invalidation_explicit", "what_would_make_me_wrong_now"]},
  "recent_events": [
    {"kind": "new_high", "run_id": "overnight-20260924", "magnitude": 1.0},
    {"kind": "session_gain", "run_id": "overnight-20260924", "magnitude": 0.84}
  ],
  "metrics": {"conviction_volatility": 0.06, "distortion_verdicts": 0, "sharpened_verdicts": 0, "self_report_mismatches": 0},
  "boundary": "Private decision machinery. Never quote or paraphrase in public prose. This state never sizes, forces, or blocks a trade."
}
```

Rules: values rounded to 2 dp; `basis` strings are machine-generated from templates (no free prose); at most 5 `recent_events`; no peer identifiers anywhere (`assert_psychology_clean` reuses the `FORBIDDEN_TRADER_CONSEQUENCE_KEYS` logic and additionally forbids any `owner_id` other than the identity's own). Because the block sits inside the hashed context body, `memory_context_sha256` changes whenever state changes and the existing stale-context gate covers it for free.

### 7.2 Mandatory self-check object

The model returns `psychology_check` on the decision (trader review, PM decision, or Trader Room contribution/rebuttal) whenever an **active flag is relevant to an action in the decision**:

```json
"psychology_check": {
  "state_sha256": "<must equal sidecar psychology.state_sha256>",
  "flags_acknowledged": ["heater_risk"],
  "answers": {
    "heater_risk": {
      "size_vs_trailing_average": "smaller|same|larger",
      "invalidation_explicit": "yes|no",
      "what_would_make_me_wrong_now": "<substantive text>"
    },
    "revenge_risk": {
      "would_take_if_flat_and_unscarred": "yes|no|unsure",
      "size_vs_prior_loss": "smaller|same|larger|not_applicable",
      "what_changed_in_evidence": "<substantive text>"
    },
    "chase_risk": {
      "catalyst_or_mispricing_identified": "yes|no",
      "would_pitch_if_rank_hidden": "yes|no|unsure",
      "why_now": "<substantive text>"
    },
    "stubbornness_risk": {
      "invalidation_touched": "yes|no|partially",
      "new_information_since_entry": "<substantive text>",
      "thesis_unchanged_because": "<substantive text>"
    },
    "rank_distortion_risk": {
      "decision_same_if_rank_hidden": "yes|no|unsure",
      "pressure_read": "sharpening|distorting|neither"
    },
    "capitulation_risk": {
      "thesis_still_valid": "yes|no|unsure",
      "derisk_reason": "thesis|risk_limit|pnl_pain|mandate|other"
    }
  },
  "proceed_despite_flags": true,
  "override_rationale": "<substantive text, required when proceed_despite_flags is true and any answer is adverse>"
}
```

Validation (trusted, in `gate.py`):

- enumerations exact; free text through the existing `substantive_text` (platitude rejection, **[#130]**) so "I feel fine" does not pass;
- `state_sha256` must equal the frozen sidecar's; mismatch → `psychology_gate: stale_psychology_state`;
- every flag whose `relevant_actions` intersect the decision's **expanding** actions must appear in `flags_acknowledged` with complete answers, else `psychology_gate: missing_psychology_check <flag>`; for the family-scoped form of `revenge_risk` (§4.4 b) only expanding actions whose `instrument` maps to the tagged family count, using the same instrument-family normalization the observer used to create the tag;
- an *adverse* answer set (e.g. `would_take_if_flat_and_unscarred = no`, `size_vs_prior_loss = larger`; `catalyst_or_mispricing_identified = no`; `invalidation_touched = yes` with `ADD`; `decision_same_if_rank_hidden = no`) with `proceed_despite_flags = true` requires a substantive `override_rationale`, else `psychology_gate: adverse_check_without_override_rationale`;
- `proceed_despite_flags = false` while the decision still expands → `psychology_gate: check_declines_but_expands` (the model must reconcile its own check with its actions);
- for PMs, a valid existing `pressure_assessment` satisfies `rank_distortion_risk` (no duplicate question).

Gate semantics are identical to the existing lesson gate: the reason blocks **only the expanding actions**; `HOLD`/`NO_TRADE`/`REDUCE`/`CLOSE` execute regardless; a pure invalid expansion raises `LearningGateError` (reuse) and mixed decisions keep their de-risk. Blocked rows record the deterministic reason in book history/alerts exactly like today; `public_alerts` strips them (§10).

### 7.3 Optional checks (never blocking)

For `capitulation_risk` on `REDUCE`/`CLOSE` and `stubbornness_risk` on `HOLD` with pain, the check is **optional**. If absent, the action executes and trusted code records `psychology_check_status = "missing_optional"` on the journal event. This mirrors the existing `rationale_status = missing_required` pattern for exits: execute, annotate, learn later. It does not create debt and does not affect eligibility.

### 7.4 Explicit override

There is no separate permission. A complete check with `proceed_despite_flags = true` **is** the override. It is always accepted when well-formed. Psychology therefore can never force `NO_TRADE`; it forces **acknowledgment on the record**. The override is journaled (§7.6) and scored later (§7.5).

### 7.5 Trusted verdict: did pressure sharpen or distort?

At `CLOSE` of any trade whose opening/adding decision carried a `psychology_check` with `proceed_despite_flags = true` (or a `missing_optional` de-risk), trusted code computes a **deterministic verdict**, stored as an event (E28/E29 or `verdict_inconclusive`), never on the canonical trade record:

| Condition | Verdict |
| --- | --- |
| Flagged + overridden expansion; `realized_pnl_usd ≤ −1 unit` **and** (accepted postmortem `causal.decision_quality_attribution ∈ {sizing, timing, entry}` **or** reflection `chase_or_revenge = yes` **or** `exit_reason_category = risk_cut`) | `distorted` |
| Flagged + overridden expansion; `realized_pnl_usd ≥ +1 unit` **and** accepted postmortem `skill_vs_luck ≠ luck` (from the linked reflection when present) | `sharpened` |
| `capitulation_risk` de-risk with `derisk_reason = pnl_pain` (or missing) whose position, had it been held, is unknowable → | `inconclusive` (V1 does not simulate counterfactual holds) |
| everything else | `inconclusive` |

The model's own `pressure_effect` (reflection) and `pressure_read` (check) are stored beside the verdict. A disagreement (`distorting` self-report vs `sharpened` verdict, or `sharpening`/`neither` vs `distorted`) increments `metrics.self_report_mismatches`. At **3** mismatches the flag `self_report_unreliable` activates (informational, plus it raises `rank_distortion_risk`/`heater_risk` relevance to include `HEDGE`), decaying by one per 6 clean cycles. This is the anti-gaming lever for self-reports.

### 7.6 What trusted code records at decision time

`journal.record_event` gains an `extra` payload key `psychology` = `{ "state_sha256", "active_flags": [ids], "check": <validated psychology_check or null>, "check_status": "provided|missing_required_blocked|missing_optional|not_required" }`. Only the validated object is stored (the same `durable_structured_payload` filter applies). `compact_actions` is unchanged; the payload lives at event level.

---

## 8. Persona layer: transparent coefficients (L0)

One table, one file, one `profile_version`. Each identity row: `baseline[axis]`, `gain[axis]`, `half_life_mult[axis]`, `tags`. Values below are PROPOSED starting points; the DAG includes a fixture-driven review before they are adopted. Absent entries = neutral (baseline from §4.2, gain 1.0, half-life ×1.0).

| Identity | Baseline shifts | Gain multipliers | Half-life multipliers | Tags |
| --- | --- | --- | --- | --- |
| `dollar-king` | `self_trust` 0.60, `thesis_attachment` 0.35 | `complacency` 1.3, `defensiveness` 0.8 | `complacency` 1.2 | `spot_only` |
| `cross-merchant` | | `revenge_pressure` 1.1, `chase_pressure` 1.1 | | `spot_only` |
| `carry-is-king` | | `complacency` 1.2, `defensiveness` 0.8, `frustration` 0.9 | `complacency` 1.3 (carry lulls) | |
| `rate-hawk` | `thesis_attachment` 0.35 | `external_pressure` 1.0, `thesis_attachment` 1.2 | | |
| `rate-dove` | `thesis_attachment` 0.35 | `thesis_attachment` 1.2 | | |
| `value-guy` | | `thesis_attachment` 1.3, `chase_pressure` 0.6, `frustration` 0.9 | `thesis_attachment` 1.3 | |
| `trend-follower` | | `complacency` 1.2, `defensiveness` 0.8, `revenge_pressure` 0.8 | `frustration` 0.8 | |
| `mean-reverter` | | `thesis_attachment` 1.4, `frustration` 1.2, `revenge_pressure` 1.2 | | |
| `positioning-cynic` | | `chase_pressure` 0.6, `complacency` 0.8, `self_trust` 1.2 | | |
| `catalyst-junkie` | | `chase_pressure` 1.5, `thesis_attachment` 0.7, `revenge_pressure` 0.9 | `frustration` 0.7 (moves on quickly) | |
| `vol-convexity` | | `defensiveness` 0.7, `frustration` 1.2, `complacency` 0.8 | | `flat_by_design` (E11 gain ×0.5) |
| `no-trade-skeptic` | `defensiveness` 0.35, `self_trust` 0.55 | `chase_pressure` 0.4, `complacency` 0.6, `external_pressure` 0.6 | | `flat_by_design` (E11 gain ×0.25) |
| `perma-bull` | `thesis_attachment` 0.40 | `thesis_attachment` 1.3, `complacency` 1.1 | | |
| `perma-bear` | `thesis_attachment` 0.40 | `thesis_attachment` 1.3, `defensiveness` 1.1 | | |
| `swinger` (PM) | | `complacency` 1.4, `defensiveness` 0.6, `external_pressure` 0.8, `revenge_pressure` 1.2 | | |
| `pragmatist` (PM) | | `external_pressure` 1.1 | | |
| `grinder` (PM) | `defensiveness` 0.35 | `chase_pressure` 0.5, `external_pressure` 1.2, `frustration` 0.8 | | `flat_by_design` (E11 gain ×0.5) |
| `chatgpt` (PM) | — | — | — | `not_applicable` in V1 (decisions arrive via Git ingest outside Cursor; no sidecar prompt to inject into) |

Guard rails on the table (enforced by a unit test): baselines within `[0.05, 0.60]` (`self_trust` within `[0.40, 0.65]`), gains within `[0.4, 1.6]`, half-life multipliers within `[0.6, 1.5]`. These bounds make it impossible for any profile to produce a permanent state or to disable an axis.

Why coefficients rather than per-seat logic: every seat runs the same engine and the same event catalog; divergence is a product of (a) different gains/baselines and (b) different histories. This is auditable, testable (§13 "persona differentiation" row), and cheap to tune.

---

## 9. Persistence schema and update timing

### 9.1 Files (Git-backed, inside the existing `data/trading/<owner_type>/<owner_id>/` layout; no new service)

`psychology_events.json` — append-only:

```json
{"schema_version": 1, "type": "TRADER_PSYCHOLOGY_EVENTS", "owner_type": "trader", "owner_id": "dollar-king",
 "events": [
   {"seq": 1, "event_id": "pse-…", "run_id": "overnight-20260929", "review_id": "review-001", "kind": "decay_tick",
    "skipped_reason": "first_cycle_after_seed", "provenance": "live"},
   {"seq": 2, "event_id": "pse-…", "run_id": "overnight-20260929", "review_id": "review-001", "at": "…",
    "kind": "session_gain", "magnitude": 0.84,
    "subject": {"session_pnl_change_usd": 418551.29},
    "source": {"layer": "L1", "refs": ["consequence_state:last_net_pnl_usd"]},
    "multipliers": {"persona": {"complacency": 1.3}, "interaction": {}, "streak": 1.0},
    "deltas_applied": {"self_trust": 0.0134, "frustration": -0.005, "complacency": 0.0590, "…": 0},
    "cap_applied": false, "provenance": "live"}
 ]}
```

`psychology_state.json` — derived, rewritten each cycle:

```json
{"schema_version": 1, "type": "TRADER_PSYCHOLOGY_STATE", "owner_type": "trader", "owner_id": "dollar-king",
 "profile_version": 1, "engine_version": 1, "provenance": "seeded_baseline_v1",
 "cycle_count": 1, "last_run_id": "overnight-20260929", "last_review_id": "review-001", "last_event_seq": 2,
 "axes": {"self_trust": {"value": 0.6134, "baseline": 0.60, "half_life_cycles": 12, "delta_last_cycle": 0.0134}, "…": {}},
 "streaks": {"session_win": 1, "session_loss": 0, "trade_win": 0, "trade_loss": 0, "flat_cycles": 0},
 "tags": {"revenge": [], "hold_through_pain": []},
 "flags": [],
 "metrics": {"conviction_volatility": 0.0, "distortion_verdicts": 0, "sharpened_verdicts": 0, "self_report_mismatches": 0},
 "last_learning_status": "compliant", "last_capital_owner_standing": null,
 "trailing_open_risk_capital_usd": [550000.0],
 "state_sha256": "…"}
```

Both are created by `TradingStore._ensure_identity_files` with a seeded baseline (§11). `context.json` embeds the §7.1 block. Sidecars (`memory/<seat>.json`, `pm_memory/<pm>.json`, PM `packet["memory"]`) inherit it via `build_memory_context` / `compact_memory_for_packet`.

### 9.2 Timing within one accepted cycle

| Phase | When | What happens to L2 | Purity |
| --- | --- | --- | --- |
| T0 Freeze | 01:50 ET overnight freeze (`evidence.freeze_snapshot` → `snapshot_overnight_traders/pms`), Trader Room freeze, PM packet build | `build_memory_context` **reads** `psychology_state.json`, embeds §7.1 block, hash frozen in `seat_memory.hashes` / `pm_memory.hashes` | Pure read |
| T1 Decision | 02:05 provider run / Trader Room / PM principals | Model reads block; returns `psychology_check` when required | No state access |
| T2 Accept / apply | `scheduled_output._apply_validated` → `apply_trader_review_with_memory`; `pm.automated` → `apply_pm_decision_with_memory`; Trader Room `reviews_from_run` → same trader path | (a) `_prepare_identity`: `apply_reflections` (L3), **[#130]** `settle_learning_compliance`, gate incl. psychology gate; (b) book apply, ledger sync, journal (with §7.6 payload), marks, `record_consequence_observation`; **(c) NEW `observe_psychology_cycle(store, owner_type, owner_id, run_id, review_id, …)`** records one decay tick, detects E1–E29 from this cycle's facts, appends events, applies saturated deltas and the cap (§5.1 order), writes state; (d) `build_memory_context` picks the new state into `context.json` | (c) is the only writer |
| T3 Next cycle T0 | | Frozen with the post-(c) state | |

`observe_psychology_cycle` is inserted immediately after `record_consequence_observation` and before `build_memory_context` in both apply paths (`apply.py` trader loop and PM function). It is skipped for seats whose review is already applied (`existing[seat]`), preserving idempotency. Its event keys are `(run_id, review_id or review_packet_id, kind, subject_id)`; a re-run with the same keys appends nothing and does not re-tick decay.

### 9.3 Reproducibility

- `replay(events, profile_version) → state` is a pure function; test asserts equality with the stored state for every identity in `data/trading` after each accepted cycle (a `tests/` invariant and a `scripts/trading/psychology_replay.py --check` CLI usable in workflows).
- Changing `profile_version` requires replaying all events under the new profile; the stored state records which version produced it. No silent re-interpretation.
- `state_sha256` is a digest of the state body excluding itself; it is what the model must echo in `psychology_check.state_sha256`.

---

## 10. Boundary and isolation

1. **Public prose**: add to `_MACHINE_PATTERNS`, `_SCRUB_RES`, `_PRIVATE_ALERT_MARKERS`: `psychology`, `psychology_check`, `psychology_gate`, `state_sha256`, `pse-[0-9a-f]+`, every flag id (`revenge_risk`, `heater_risk`, `chase_risk`, `stubbornness_risk`, `capitulation_risk`, `rank_distortion_risk`, `fragile_confidence`, `inflated_confidence`, `self_report_unreliable`), and the axis names when followed by a number (`complacency 0.47`). `public_books_view` / `public_pm_view` already route alerts through `public_alerts`; theses through `sanitize_public_prose`. Add a test that a thesis containing "my complacency is 0.47 so I am sizing down" loses the machine clause.
2. **Model output**: add `psychology`, `psychology_state`, `psychology_events`, `axes`, `active_flags` to `scheduled_output.FORBIDDEN_MODEL_STATE_KEYS` and to `constants.FORBIDDEN_MODEL_FACT_KEYS`; only `psychology_check` is accepted from the model.
3. **Identity isolation**: state files live under the identity directory; `assert_psychology_clean` runs on the block; the observer reads only own-identity ledger/journal/learning state plus the already-authorized L1 consequence (rank for traders; spread/gap/standing for PMs). No peer psychology, lessons, or P&L is ever read.
4. **No canonical mutation**: the engine imports from `ledger.py`/`consequence.py` read-only; a test monkeypatches `store.write_trade`, `write_books`, `write_lessons` to raise during `observe_psychology_cycle` and asserts no call.
5. **Hooks**: `.cursor/hooks/enforce-overnight-runtime.py` already blocks tools for frozen children; nothing new is needed for the provider run. The psychology block adds roughly 1.5–2.5 KB per sidecar; well inside prompt discipline (§14 of `TRADING_LEDGER_MEMORY_V1.md`).

---

## 11. Historical initialization and backtraining policy

### 11.1 What can be reconstructed from stored data at `7d271ca`

| Signal | Reconstructable? | Source |
| --- | --- | --- |
| Per-seat session P&L deltas for `overnight-20260922..25` | Yes | `data/overnight/runs/<run>/reviews/<review>/evidence_snapshot.json.prior_books` and `trader_review.json.books` |
| Rank sequence | Yes (derivable from the same books) | same |
| 5 closed trades with realized, MFE/MAE, holding, conviction | Yes | `data/trading/trades/*.json` |
| Trader Room run outcomes (`tr-20260920*`) | Partially (proposals journaled; book effects folded into books) | `journal.json`, `trader-room/runs/*` |
| Exit categories, dispositions, reflections, lessons | **No** (none exist) | — |
| Any mental state | **No** — and must not be fabricated | — |

### 11.2 Policy

1. **Seed neutral.** Every identity starts at its L0 baseline with `provenance: seeded_baseline_v1`, `cycle_count: 0`, empty events. This is the only initialization applied to live state in V1.
2. **Shadow replay, report only.** A T0 script (`psychology_replay.py --shadow --from-books`) reconstructs the 4 overnight sessions + 5 closed trades into `provenance: backfilled` events **in a temporary directory**, runs the engine, and emits a report. The report is committed only as a test fixture (`tests/fixtures/psychology/shadow_report_7d271ca.json`) and summarized in the implementation PR description; it is **not** written under `data/overnight/runs/**` or `data/trading/**`. Purpose: verify that real-scale events produce bounded, sane deltas (expected: dollar-king `complacency` ≈ 0.15–0.25 after its single +$418K session, nothing near a flag).
3. **Reversibility.** If upstream later chooses to apply a backfill, it must (a) be a separate file `psychology_backfill_events.json` with `provenance: backfilled`, (b) be replayable and deletable without touching `psychology_events.json` live entries, (c) never alter any canonical trade or book, (d) carry a `backfill_id` echoed in the state's `provenance`. This plan recommends **not** applying it: 4 sessions and 5 tiny closed trades add no differentiating history and would only add provenance complexity.
4. **Bounded calibration scenarios** (fixtures, not backtraining): six synthetic multi-cycle fixtures in `tests/fixtures/psychology/` — win streak → giveback; loss streak → stop-out → revenge re-entry; flat-with-market (skeptic vs junkie); rank shock + learning default; lesson override → failure → correction; PM allocator watch → payoff → restore. These are the tuning surface for §5.3 base deltas and §8 coefficients and double as acceptance tests (§13).

---

## 12. Scenario walkthroughs

All numbers are PROPOSED/ILLUSTRATIVE engine outputs under §4–§8 rules (decay → events → cap per cycle; values are end-of-cycle, i.e. what the seat sees at its next decision); none are observed production facts. `unit` = $500K trader / $5M PM. "Prompt" shows the sidecar `active_flags`/`required_checks` the seat would see at its next decision. Persona coefficients used are those of §8.

### S1 — Dollar King: heater after four winning sessions

| Cycle | Events | complacency | self_trust | Flags / prompt |
| --- | --- | --- | --- | --- |
| 0 | seed | 0.10 | 0.60 | — |
| 1 | E1 m=0.84 (the live +$418,551 run) | 0.16 | 0.61 | — |
| 2 | E1 m=1.0 (streak 2, ×1.25) | 0.24 | 0.63 | — |
| 3 | E1 m=1.0 + E7 m=1.0 (streak 3, ×1.5) | 0.41 | 0.66 | `complacency elevated`; `heater_risk` not yet (0.41 < 0.45) |
| 4 | E1 m=1.0 + E7 m=1.0 (streak 4, ×1.75; second new high) | 0.54 | 0.69 | **`heater_risk`** active (≥0.45 with streak ≥3). Prompt: "complacency 0.54 after 4 consecutive winning sessions and two new highs (overnight-…); required on OPEN/ADD: size_vs_trailing_average, invalidation_explicit, what_would_make_me_wrong_now" |
| 5 | Dollar King submits `ADD` 2× trailing size; check: `larger`, `yes`, substantive; `proceed_despite_flags: true` → E19 fires | 0.56 | 0.68 | `ADD` executes (never blocked). Journal stores the check. If the trade later closes ≤ −1 unit with `sizing` attribution → E28 `distorted`, `self_trust` −0.03 |
| 6–9 | HOLDs, flat P&L | decays 0.51 → 0.47 → 0.43 → 0.39 | 0.67 | flag exits below 0.45 at cycle 8; `elevated` band exits below 0.30 later still |

Contrast (same 4 event cycles, No-Trade Skeptic profile, `complacency` gain 0.6): 0.10 → 0.13 → 0.16 → 0.25 → 0.33 — never reaches `heater_risk`, nor even the `elevated` band (0.40).

### S2 — Mean Reverter: three stop-outs on the same fade

| Cycle | Events | frustration | thesis_att. | revenge | Flags / prompt |
| --- | --- | --- | --- | --- | --- |
| 1 | E5 m=0.5 (SOFR_2027-03 long, `risk_cut`); tag `SOFR family, long, ttl 3` | 0.17 | 0.26 | 0.11 | `revenge_risk` (tag form) now required for any SOFR-family OPEN/ADD, not for other instruments |
| 2 | re-open same family — check answered, `proceed_despite_flags: true` — then E20 ×1.0 + E5 m=0.7 (streak 2 ×1.25) | 0.28 | 0.31 | 0.34 (cap binds) | `revenge_pressure elevated`; tag refreshed. Verdict on the cycle-2 OPEN: flagged + overridden + `risk_cut`, but realized −$350K is under 1 unit → `inconclusive` (verdicts need material outcomes; no E28) |
| 3 | re-open larger (E20 ×1.5) + E5 m=0.9 (streak 3 ×1.5; frustration→revenge interaction ×1.14) | 0.42 | 0.36 | 0.51 (cap binds) | **`revenge_risk`** (≥0.45) required on all OPEN/ADD; `frustration elevated`. Prompt: "revenge 0.51; you closed SOFR_2027-03 long at a loss on overnight-A, -B, -C and re-entered larger each time; required: would_take_if_flat_and_unscarred, size_vs_prior_loss, what_changed_in_evidence" |
| 4 | Mean Reverter submits `HOLD` + `NO_TRADE` | 0.35 | 0.35 | 0.37 | HOLD executes with no check needed; `revenge_risk` stays active by hysteresis (exit < 0.30); `frustration elevated` likewise (exit < 0.30) |
| 5 | reflection accepted for `stop_or_forced_exit` due **[#130]** with lesson "fade needs a reversal condition, not just an extreme" (candidate) | 0.30 | 0.34 | 0.28 | lesson creation itself moves nothing (§3.2). `revenge_risk` exits (0.28 < 0.30) for non-SOFR instruments; the SOFR tag (ttl 3, refreshed at cycle 3) still forces the check on a SOFR OPEN/ADD through cycle 6 |

Contrast (same events, Catalyst Junkie profile: `revenge` gain 0.9, `frustration` half-life ×0.7): revenge peaks 0.47 at cycle 3 (flag active, held through cycle 4 by hysteresis, exits at cycle 5 at 0.26); frustration peaks 0.36 — never `elevated` — and is 0.23 by cycle 5. The Junkie "moves on" faster, by coefficient not by bespoke code.

### S3 — Catalyst Junkie: right thesis, wrong expression

| Cycle | Events | frustration | thesis_att. | self_trust | Notes |
| --- | --- | --- | --- | --- | --- |
| 1 | CLOSE AONIA_2026-10 −$2,750 → below dead-band ($40K) → **no E4** | 0.10 | 0.25 | 0.50 | Tiny losses do not move state (dead-band). Postmortem still due (unchanged existing behavior) |
| 2 | Larger case: CLOSE −$300K (m=0.6) with same-cycle accepted reflection `attribution: expression`, `causal.decision_quality_attribution: expression` → softened E4 | 0.12 | 0.25 | 0.48 | thesis_attachment untouched; the trader's thesis was right |
| 3 | lesson (scope `expression`) created; next OPEN with `setup_fingerprint` matching → `APPLIES` disposition (persisted via G9 fix) | 0.12 | 0.25 | 0.48 | — |
| 4 | that trade closes +$400K → E3 m=0.8 + **E17 correction_success** | 0.10 | 0.23 | 0.56 | Recovery path: correcting a learned mistake is the largest positive `self_trust` event in the catalog (+0.08 net in one cycle versus +0.03 for an ordinary win) |

### S4 — No-Trade Skeptic vs Catalyst Junkie: eight flat cycles with a fresh market

| Cycle | Skeptic chase (gain 0.4 × `flat_by_design` 0.25 = 0.10) | Junkie chase (gain 1.5) | Notes |
| --- | --- | --- | --- |
| 1–2 | 0.10, 0.10 | 0.10, 0.10 | E11 needs `flat_cycles ≥ 3` |
| 3 | 0.11 | 0.17 | |
| 4 | 0.11 | 0.23 | |
| 5 | 0.11 | 0.27 | |
| 6 | 0.12 | 0.30 | Junkie sidecar shows `chase_pressure` 0.30, still `steady` (elevated needs 0.35): four flat cycles alone do not produce even a band change |
| 7 (rank drops 4 → 7: E9) | 0.13 | 0.38 → `chase elevated` (E9 +0.04 ×1.5 × external interaction) | no required check yet (`chase_risk` at 0.50) |
| 8 (rank shock 7 → 11: E8) | 0.17 | 0.50 → **`chase_risk`** at threshold | Junkie prompt on next OPEN: "catalyst_or_mispricing_identified, would_pitch_if_rank_hidden, why_now". Skeptic never approaches a flag (0.17 after the same rank shock); sitting out remains legitimate and un-nagged |

Flat with `market_state` not fresh: no E11 for either; both stay at baseline.

### S5 — Trend Follower: giveback after new high, then a REDUCE

| Cycle | Events | complacency | defensiveness | frustration | Notes |
| --- | --- | --- | --- | --- | --- |
| 1–3 | E1 m=1.0, E1+E7, E1+E7 (streak 3; two new highs) | 0.17 → 0.33 → 0.46 | 0.20 → 0.19 → 0.18 | 0.09 → 0.08 | `heater_risk` at cycle 3 (0.46 ≥ 0.45 with streak 3) |
| 4 | E6 m=1.0 + E2 m=1.0 (giveback −$1.1M) | 0.46 → 0.27 | 0.18 → 0.28 (gain 0.8) | 0.08 → 0.23 | `heater_risk` exits (< 0.45). Complacency lost in one cycle what took two to build |
| 5 | Trend Follower `REDUCE` 50% | | | | `capitulation_risk` not active (needs def 0.60 & frus 0.40) → no check even optional; REDUCE executes; journal `check_status: not_required` |
| Alt 5 | if instead def 0.62 / frus 0.44 (deeper giveback + stop) | | | | `capitulation_risk` **optional** check on REDUCE: `thesis_still_valid`, `derisk_reason`. Absent → executes, `missing_optional` recorded. Verdict later `inconclusive` unless `derisk_reason = pnl_pain` and the position would have… (not simulated) → stays `inconclusive` |

### S6 — Perma-Bull: rank shock 3 → 9 then learning default

| Cycle | Events | external_pressure | chase | frustration | Flags |
| --- | --- | --- | --- | --- | --- |
| 1 | E8 (rank_change +6) | 0.28 | 0.20 | 0.17 | `external elevated` not yet (0.35) |
| 2 | HOLD with unresolved prior-run `reflections_due` → **[#130]** `learning_default` → E13 | 0.41 | 0.18 | 0.24 | `external_pressure elevated`; competitive eligibility removed by #130 (L1 fact shown as today) |
| 3 | still in default (no new E13; transition-only) + E12 blocked OPEN | 0.39 | 0.19 | 0.25 | `elevated` held by hysteresis (exit < 0.25) |
| 4 | reflection accepted → E14 cleared | 0.30 | 0.17 | 0.20 | relief; band exits once below 0.25 (about two more quiet cycles) |

Had a second shock landed at cycle 3 instead: 0.39 (post-decay) + 0.20×(1−0.39) ≈ 0.50 → **`rank_distortion_risk`** at threshold → required on any expansion: `decision_same_if_rank_hidden`, `pressure_read`. Note the persona lever: Perma-Bull `thesis_attachment` baseline 0.40 means its stubbornness flag sits closer than Dollar King's, so a same-thesis re-add after the shock would trip `stubbornness_risk` earlier.

### S7 — Swinger PM: allocator watch under repeated uncompensated drawdown

| Cycle | Events | external_pressure (gain 0.8) | complacency (gain 1.4) | frustration | Flags |
| --- | --- | --- | --- | --- | --- |
| 1 | E2 m=1.0 (−$6M) + E26 | 0.15 | 0.09 | 0.18 | — |
| 2 | E2 m=1.0 (streak 2) + E26 | 0.19 | 0.08 | 0.26 | — |
| 3 | second episode opens → existing `swinger_uncompensated_episodes = 2` → standing `watch` → E25 + E26 | 0.38 | 0.08 | 0.27 | `external elevated`. Existing `pressure_assessment` already required by `requires_pressure_assessment` (PM path). No duplicate psychology check for `rank_distortion_risk` (inactive at 0.38) |
| 4 | Swinger OPEN concentrated; `pressure_assessment` valid; `heater_risk` inactive → no psychology check required; E26 continues | 0.37 | 0.08 | 0.24 | Executes. Journal payload records `active_flags: []` (bands are not flags), `check_status: not_required`, and the pressure_assessment (G3 fixed) |
| 5 | payoff +$30M → E1 m=1.0 + E7 + standing restored E27 | 0.29 | 0.29 | 0.18 | complacency jumps (gain 1.4) but stays under `elevated`; Swinger's next heater is now closer than a Grinder's would be |

Contrast Grinder under an equivalent `watch` (`missed_opportunity_zero_alpha`): `external_pressure` gain 1.2 → 0.10 → 0.35 in one cycle (raw +0.27, the per-cycle cap binds at +0.25); subsequent flat cycles with opportunities present (E11 with `flat_by_design` ×0.5) do not lift it further — 0.33, 0.31 — because decay outruns the small E11 delta. `rank_distortion_risk` (0.50) would require a standing step to `probation` or a learning default on top. Grinder's sidecar shows the `elevated` band; the existing PM `pressure_assessment` requirement applies as today; `force_deployment` stays false; sitting out remains executable.

### S8 — Grinder PM: learning default on HOLD, cleared next run **[#130]**

| Cycle | Events | external_pressure | frustration | self_trust | Notes |
| --- | --- | --- | --- | --- | --- |
| 1 | HOLD with prior `reflections_due` unresolved → E13 (gain 1.2) | 0.10 → 0.32 | 0.10 → 0.17 | 0.50 → 0.475 | Standing floor `probation` (**[#130]** L1) shown as today |
| 2 | causal `no_new_lesson` accepted → E14 | 0.32 → 0.24 | 0.17 → 0.15 | 0.49 | `elevated` band never entered (0.32 < 0.35): a single learning default is a nudge, not a crisis |

Double-punishment check: the flat P&L that made the reflection due did not fire E1/E2 (inside dead-band), and E13/E14 fire on transitions only, so Grinder was moved once for entering default and once for leaving it.

### S9 — Value Guy: lucky win

| Cycle | Events | complacency | self_trust | Notes |
| --- | --- | --- | --- | --- |
| 1 | CLOSE +$600K (m=1.0) → E3; MAE was −$450K before recovering | 0.10 → 0.15 | 0.50 → 0.53 | — |
| 2 | reflection for `material_win`? Not due (below $2M) — no reflection. If the trader volunteers a postmortem with `skill_vs_luck: luck`: **no state change** (self-reports never lower risk axes and this one would lower nothing anyway) | 0.14 | 0.53 | The `luck` admission is stored and used only in §7.5 verdicts |

Persistence of humility is therefore *not* rewarded with lower checks; it is rewarded with a lower mismatch count when a later verdict lands `inconclusive`/`distorted`.

### S10 — Any seat: drawdown then long recovery (no permanent fear)

| Cycle | Events | defensiveness | self_trust | frustration |
| --- | --- | --- | --- | --- |
| 1–3 | E2 m=1.0 each cycle (streak); E4 loss close at 2; E5 risk-cut at 3 | 0.20 → 0.25 → 0.34 → 0.49 | 0.50 → 0.48 → 0.43 → 0.39 | 0.10 → 0.17 → 0.33 → 0.50 (cap binds at 3) |
| 4 | E2 + second E5 (streak 4, ×1.75) | 0.61 | 0.36 | 0.62 → **`capitulation_risk`** (def ≥0.60 & frus ≥0.40); `frustration high`, `defensiveness high` |
| 5–8 | HOLD, flat (dead-band) | decay H=6: 0.57 → 0.53 → 0.49 → 0.46 | H=12: 0.37 → 0.38 → 0.38 → 0.39 | H=3: 0.51 → 0.43 → 0.36 → 0.31 (flag exits at cycle 7 when defensiveness < 0.50) |
| 9 | one E1 m=0.5 | 0.42 | 0.41 | 0.26 |
| 10–16 | flat | → 0.30 by cycle 16 | → 0.44 | → 0.13 |

Self-trust bottoms at 0.36 here — above the `fragile` band (0.30) — and decay alone carries it back toward 0.50 (H=12, so roughly half the gap closes every 12 accepted cycles). Reaching 0 would require maximal negative events every cycle indefinitely; nothing in the engine can hold an axis away from its baseline without fresh events. No state is permanent.

### S11 — Positioning Cynic: successful correction after an override failure **[#130 + G9]**

| Cycle | Events | thesis_att. | self_trust | frustration | Flags |
| --- | --- | --- | --- | --- | --- |
| 1 | OPEN with `OVERRIDE` on matching lesson; later CLOSE −$550K → E4 m=1.0 + E16 m=1.0 + E15 (escalation) | 0.25 → 0.48 (three attachment events in one cycle; +0.23 after saturation, under the cap) | 0.50 → 0.38 (`self_trust` gain 1.2) | 0.10 → 0.32 | `thesis_attachment elevated` |
| 2 | second `OVERRIDE` attempt → **`stubbornness_risk`?** 0.46 < 0.60 → no required check yet, but the sidecar shows `elevated` and `repeated_error_escalations` (L1 **[#130]**) | 0.46 | 0.39 | 0.27 | |
| 3 | OPEN with `APPLIES` (uses the lesson's `future_rule`) → CLOSE +$300K → E3 m=0.6 + E17 | 0.46 → 0.39 | 0.39 → 0.49 | 0.27 → 0.21 | `elevated` held by hysteresis until < 0.35 (about four more quiet cycles at H=8); the correction restored `self_trust` almost to baseline in one cycle |

### S12 — Cross-Merchant: revenge on AUDCAD, override, verdict

Live context at `7d271ca`: cross-merchant closed AUDCAD short at −$49,946 (below dead-band → no E4 in V1 at this size) and holds AUDCAD long. Scaled-up hypothetical for the mechanism:

| Cycle | Events | revenge (gain 1.1) | Flags / prompt |
| --- | --- | --- | --- |
| 1 | CLOSE AUDCAD short −$600K → E4 m=1.0; tag `AUDCAD, short, ttl 3` | 0.05 → 0.14 | — |
| 2 | OPEN AUDCAD **long** $15M (> lost $10M) → E20 ×1.5 (tag matches family either side) | 0.14 → 0.35 | Frozen state at decision time: revenge 0.14 with an active `AUDCAD` tag → **`revenge_risk` required** on this OPEN by the tag rule (§4.4 b). Model answered: `would_take_if_flat_and_unscarred: unsure`, `size_vs_prior_loss: larger`, substantive evidence text, `proceed_despite_flags: true`, `override_rationale` substantive → OPEN executes; journal stores the check. E20 is then recorded by the observer |
| 3 | CLOSE −$700K, `exit_reason_category: risk_cut` → E5 (tag refreshed) + trusted verdict on the cycle-2 OPEN: flagged, overridden, realized ≤ −1 unit, `risk_cut` → **`distorted`** (E28) | 0.35 → 0.37 (E5 offsets decay) | `self_trust` 0.47 → 0.42; `metrics.distortion_verdicts = 1`; if the reflection then says `pressure_effect: sharpening` → `self_report_mismatches = 1`. `revenge_risk` remains required on any AUDCAD-family expansion for three more cycles; the general (all-instrument) form (0.45) was never reached |

Contrast Trend Follower (`revenge` gain 0.8): same facts give 0.27 at cycle 2 and 0.29 at cycle 3. The tag rule makes the same AUDCAD check required for the Trend Follower too — the wound is objective — but the Trend Follower is further from the general 0.45 flag, so its other instruments stay unencumbered longer. Personas diverge in *how far* identical facts carry them, not in *whether* facts are recorded. Note also the deliberate one-cycle lag: flags are evaluated on the **frozen** state, never on the decision being made, so a check cannot depend on the very action it is checking.

---

## 13. Acceptance-test matrix

| ID | Property | Test (deterministic unless noted) | Node |
| --- | --- | --- | --- |
| A1 | Bounded | Property test: 500 random event sequences × all 17 profiles → every axis ∈ [0,1]; per-cycle net change ≤ 0.25 | D1 |
| A2 | Decaying | After any event burst, N ≥ 4·H flat cycles bring each axis within 0.07 of baseline; no axis can stay ≥ band-enter without new events | D1 |
| A3 | Persona-differentiated | S1/S2/S4/S12 fixtures: identical event streams produce ordered, different trajectories for ≥4 named profiles; assert the specific inequalities in §12 | D1 |
| A4 | No ledger/risk corruption | Monkeypatched `write_trade`/`write_books`/`write_lessons`/`write_learning_state` raise during `observe_psychology_cycle`; books/ledger digests identical before/after; `FORBIDDEN_MODEL_STATE_KEYS` rejects `psychology`/`axes`/`active_flags` in model output | D2 |
| A5 | No peer leakage | `assert_psychology_clean` on every identity block; JSON dump of dollar-king sidecar contains no other seat id, no other seat P&L; PM block contains only already-authorized PM facts | D2 |
| A6 | Safe de-risking | Decision `[CLOSE, REDUCE]` with all flags active and no `psychology_check` → both execute, `check_status = missing_optional`, no alert on public view; mixed `[CLOSE, OPEN]` with missing required check → CLOSE executes, OPEN blocked with `psychology_gate: missing_psychology_check <flag>` | D2 |
| A7 | No forced deployment | With every flag inactive and `chase_pressure = 0.99`, `HOLD`/`NO_TRADE` never produce a gate reason; `force_deployment` remains false in `capital_owner`; no code path maps a flag to an action (static assertion: engine module exports no function returning an action) | D1/D2 |
| A8 | Learning V2 interaction **[#130]** | E13/E14 fire once per transition across 5 cycles in default; E15 increments with `repeated_error_escalations`; lesson `add`/`reinforce`/`refine`/`retire` move no axis; E16/E17/E18 fire only with persisted dispositions; examiner-dropped submissions produce no E21–E23 | D2 |
| A9 | Deterministic replay / idempotency | `replay(events) == state` for all identities after a 3-cycle fixture; re-applying the same accepted review (`ReviewAlreadyApplied` path) appends zero events and zero decay ticks; `build_memory_context` called 5× yields identical `memory_context_sha256` | D2 |
| A10 | Hash chain | Sidecar `psychology.state_sha256` equals `psychology_state.json` digest; a `psychology_check` with a stale `state_sha256` blocks expansion only | D2 |
| A11 | Public boundary | Thesis/alerts containing flag ids, axis+number, `psychology_check`, `pse-…` are scrubbed by `public_books_view`/`public_pm_view`; `public_prose_issues` flags them | C1 |
| A12 | Anti-gaming | Reflection with `chase_or_revenge: no` moves no axis; `skill_vs_luck: luck` moves no axis; 3 mismatches activate `self_report_unreliable`; profile-table guard rails reject out-of-range coefficients | D1 |
| A13 | Scenario behavior | S1–S12 fixtures assert flag activation cycle, exit cycle, and required-check set as tabulated in §12 (values within ±0.03 after tuning freeze) | D1 |
| A14 | Prompt contract | `paper_book._learning_fields` carries `psychology_check` from contribution/rebuttal; `pm/automated.validate_pm_decisions` passes it through; `scheduled_output.validate_output` accepts it and rejects `psychology` state keys | B6/D2 |
| A15 | Regression | All existing suites in the #130 PR validation list plus `tests/test_public_prose.py`, `test_pm_scheduled_output.py`, `test_overnight_scheduled_output.py`, `test_mw_launch_*` remain green | D3 |
| A16 | Shadow replay sanity (real data) | `psychology_replay.py --shadow` on `data/trading` + `data/overnight/runs` at the merge commit: every axis within 0.20 of baseline; zero flags active; report committed as fixture | D4 |

---

## 14. Smallest safe architecture, touchpoints, and what NOT to build in V1

### 14.1 New modules

| File | Purpose | Size estimate |
| --- | --- | --- |
| `scripts/trading/psychology_profiles.py` | L0 table (§8), `PROFILE_VERSION`, guard-rail validator | ~150 lines |
| `scripts/trading/psychology.py` | Engine: constants, event base-delta table (§5.3), `apply_event`, `decay_tick`, `derive_flags`, `replay`, `state_digest`, `assert_psychology_clean`, `psychology_block_for_context` | ~450 lines |
| `scripts/trading/psychology_events.py` | Observer: `observe_psychology_cycle(store, owner_type, owner_id, *, run_id, review_id, review_packet_id, books/consequence inputs, decision, blocked, when)` — detection of E1–E29 from own facts; verdict computation | ~400 lines |
| `scripts/trading/psychology_gate.py` | `psychology_gate_reason(decision, context, owner_id)`, `validate_psychology_check`, adverse-answer logic | ~200 lines |
| `scripts/trading/psychology_replay.py` | CLI: `--check` (replay equality over `data/trading`), `--shadow --from-books` (report only, temp dir) | ~150 lines |
| `tests/test_trader_psychology_state.py`, `tests/test_trader_psychology_gate.py`, `tests/test_trader_psychology_integration.py`, `tests/fixtures/psychology/*.json` | §13 | ~900 lines |

### 14.2 Exact touchpoints in existing code (surgical)

| File | Change |
| --- | --- |
| `scripts/trading/constants.py` | `PSYCH_UNIT_FRACTION = 0.25`, `PSYCH_DEAD_BAND_FRACTION = 0.02`, `PSYCH_CYCLE_CAP = 0.25`, `PSYCH_SCHEMA_VERSION = 1`, flag id tuple, check enumerations; `MEMORY_SCHEMA_VERSION` 3 → **4**; extend `FORBIDDEN_MODEL_FACT_KEYS` |
| `scripts/trading/store.py` | `psychology_events_path`, `psychology_state_path`, `read/write_psychology_events`, `read/write_psychology_state`; seed in `_ensure_identity_files` |
| `scripts/trading/memory.py::build_memory_context` | add `"psychology": psychology_block_for_context(store, owner_type, owner_id)` (pure read) before digest |
| `scripts/trading/snapshot.py::compact_memory_for_packet` | include `"psychology"` |
| `scripts/trading/gate.py::learning_gate_reason` | after lesson considerations: `reason = psychology_gate_reason(decision, decision.get("_memory_context"), owner_id=owner_id)`; extend `_journal_action_rows` untouched; `requires_pressure_assessment` **unchanged** (PM path keeps working; the trader gap G2 is closed by `rank_distortion_risk`) |
| `scripts/trading/apply.py` | trader loop: after `record_consequence_observation(...)` insert `observe_psychology_cycle(...)`; same in `apply_pm_decision_with_memory`; pass `blocked_by_seat[seat]` / `blocked` and the validated `psychology_check` into `record_event(extra={"psychology": …})` for both trader and PM events (G3: also persist `pressure_assessment` in the same `extra`) |
| `scripts/trading/journal.py` | none required (`extra` already supported); optionally add `"psychology"` to a documented `extra` key list |
| `scripts/trading/learning.py::record_retrieved_lessons` **[#130]** | G9 fix: accept `dispositions: dict[lesson_id → disposition]` and store `disposition` on each `retrieved_lessons` row; `apply._prepare_identity` passes dispositions from `lesson_considerations` |
| `scripts/trader_room/paper_book.py::_learning_fields` | add `"psychology_check"` to `keys` |
| `scripts/pm/automated.py` | pass `psychology_check` through unchanged (verify no key whitelist drops it) |
| `scripts/overnight/scheduled_output.py` | extend `FORBIDDEN_MODEL_STATE_KEYS` (§10.2) |
| `scripts/overnight/public_prose.py` | extend the three pattern tuples (§10.1) |
| `.cursor/commands/overnight-scheduled.md`, `trader-room.md` ("Learning memory, consequence, and reflections"), `portfolio-managers.md` ("Consequence, allocator pressure, and reflections") | one paragraph each: read `psychology` in the sidecar; when `active_flags` list a `required` check relevant to your actions, return `psychology_check`; `HOLD`/`NO_TRADE`/`REDUCE`/`CLOSE` never require it; never mention state in public prose |
| `.cursor/agents/*.md` (14 + 3) | one shared sentence appended to the existing memory paragraph (same text for all; personality stays in the L0 table, not in prompt tone) |
| `docs/TRADING_LEDGER_MEMORY_V1.md` | new §15 "Psychology (private)" + file layout lines; or a sibling `docs/TRADER_PSYCHOLOGY_V1.md` referenced from it |
| Workflows | none — `data/trading/**` is already persisted wholesale by `overnight-scheduled-output.yml` and `pm-chatgpt-decision.yml` |

### 14.3 Not in V1 (deliberately)

- No UI / dashboard exposure; no curated public view.
- No ChatGPT PM psychology (no Cursor prompt to inject into; would require changing the ChatGPT ingest contract).
- No examiner grading of `psychology_check` quality (V1.1 candidate; keeps the 20/18/2 contract untouched).
- No changes to `MATERIAL_DRAWDOWN_FRACTION`, reflection triggers, or `capital_owner` logic.
- No natural-language mood text; `basis` strings are templated.
- No psychology-driven sizing suggestions, position limits, or cooling-off periods.
- No counterfactual-hold simulation for capitulation verdicts.
- No backfill applied to live state (shadow report only).
- No per-instrument mood beyond the 3-cycle revenge tag.
- No dependence on the dead #130 CLOSE fields (`close_path`, `expression_vs_thesis`, `reaction_vs_expectation`).
- No new external service, database, or embeddings.

---

## 15. Feedback loop with Learning V2 **[#130]** — summary of constraints

| Learning V2 element | Effect on L2 | Effect of L2 on it |
| --- | --- | --- |
| Causal reflection accepted | E21–E23 admissions only (raise risk axes / lower self_trust; small) | none |
| Candidate lesson created / reinforced / refined / retired | none | none |
| Established lesson | none | none |
| Relevant lesson retrieval (`materially_matching_lessons`) | none at retrieval; dispositions persisted (G9) enable E16–E18 at CLOSE | `stubbornness_risk` makes `OVERRIDE` require a check; never changes matching or dispositions |
| Repeated-error escalation | E15 once per increment | none |
| Learning default entered / cleared | E13 / E14 once per transition | none — psychology never alters `learning_status`, eligibility, or standing floors |
| Examiner | drops inadequate submissions before they reach `apply_reflections`, so dropped reflections cannot produce E21–E23 | none |
| `postmortems_due` / `reflections_due` debt | none directly (debt is L1 and stays gate-blocking as today) | none |

Runaway prevention: L2 has exactly three inbound hooks from L3 (transition-only, count-only, disposition-outcome-only) and zero outbound writes. Combined with per-cycle caps and decay, a feedback loop cannot form.

---

## 16. Dispatch-ready implementation DAG (for a later run; not executed here)

Model roles: **T0** = deterministic code/CLI with no model call; **C** = Composer 2.5 (bounded implementation and test volume); **G** = Grok 4.7 (architecture-sensitive integration, debugging, verification); **F** = one optional Fable 5.1 review gate after integration. No Auto/other models. Upstream note: the repository's `enforce-subagent-models.sh` default list is `composer-2.5 grok-4.6 grok-4.5`; if implementation runs as Cursor subagents rather than ACP-dispatched jobs, the ACP `allowed_models` list must include `grok-4.7` or the G nodes must run as the ACP parent.

### 16.1 Stop gates

| Gate | Condition | Blocks |
| --- | --- | --- |
| G0 | PR #130 merged to `main` **or** upstream confirms the implementation branch will be cut from the #130 head; both SHAs recorded in the implementation PR | everything |
| G1 | Lane A engine tests (A1, A2, A3, A7, A12, A13) green | Lane B integration |
| G2 | Integration tests (A4–A6, A8–A10, A14) green **and** A15 regression green | Lane C prompt/doc finalization, D4 |
| G3 | Shadow replay (A16) bounded; public-boundary (A11) green | D5 / merge readiness |
| G4 (optional) | Fable review finds no invariant violation (double counting, gaming, de-risk safety, isolation) | merge |

### 16.2 Nodes

| Node | Lane | Depends on | Owner surface | Model | Artifacts | Deterministic tests | Repair loop |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A1 constants + profiles | A | G0 | `constants.py` (psych constants only), `psychology_profiles.py` | C | table + guard-rail validator | `test_profiles_within_guard_rails` | ≤2 |
| A2 event detection | A | A1 | `psychology_events.py` (pure detectors over passed-in facts; no store writes) | C | detectors for E1–E29 | unit tests per detector with synthetic facts | ≤2 |
| A3 state engine | A | A1 | `psychology.py` | C | `apply_event`, `decay_tick`, `derive_flags`, `replay`, `state_digest`, block builder | A1, A2, A7, A12 (property + unit) | ≤2 |
| A4 fixtures + scenario tests | A | A2, A3 | `tests/fixtures/psychology/*.json`, `test_trader_psychology_state.py` | C | S1–S12 fixtures | A3, A13 | ≤2 (tuning of §5.3/§8 only within guard rails; every tuned value documented in the PR) |
| B1 store + seed | B | A1 | `store.py` | C | paths, read/write, seeding | `test_store_seeds_psychology_files` | ≤1 |
| B2 context + snapshot injection | B | A3, B1 | `memory.py::build_memory_context`, `snapshot.py::compact_memory_for_packet`, `MEMORY_SCHEMA_VERSION` bump | G | block in context/sidecar/PM packet | A5, A9 (hash stability), A10 | ≤2 |
| B3 apply hooks + idempotency | B | B2, A2 | `apply.py` (two insertion points), `psychology_events.observe_psychology_cycle` (store-writing wrapper) | G | events/state written once per accepted cycle | A4, A9 | ≤2 |
| B4 gate + check validation | B | B2 | `psychology_gate.py`, `gate.py::learning_gate_reason` | G | per-action block reasons | A6, A7, A10 | ≤2 |
| B5 journal payload | B | B4 | `apply.py::record_event(extra=…)` for trader + PM (adds `pressure_assessment` persistence, G3) | C | `payload.psychology` on journal events | `test_journal_records_psychology_check` | ≤1 |
| B6 pass-through surfaces | B | B4 | `paper_book._learning_fields`, `pm/automated.py`, `scheduled_output.FORBIDDEN_MODEL_STATE_KEYS` | C | model output accepted/rejected correctly | A14 | ≤1 |
| B7 disposition persistence **[#130]** | B | G0 | `learning.py::record_retrieved_lessons`, `apply._prepare_identity` | C | `disposition` on `retrieved_lessons` rows | `test_retrieved_lessons_record_disposition` | ≤1 |
| B8 verdicts | B | B3, B5, B7 | `psychology_events.py` verdict section | G | E28/E29/inconclusive events; mismatch metric | `test_verdict_rules`, A12 mismatch case | ≤2 |
| C1 public boundary | C | A1 | `public_prose.py` | C | patterns | A11 | ≤1 |
| C2 prompt contract | C | B4 | `.cursor/commands/*.md`, `.cursor/agents/*.md` | C | one paragraph / one sentence | doc lint: grep that the 17 agent files contain the shared sentence exactly once | ≤1 |
| C3 docs | C | B4, B8 | `docs/TRADING_LEDGER_MEMORY_V1.md` §15 or `docs/TRADER_PSYCHOLOGY_V1.md` | C | contract doc mirroring this plan's §4–§10 as adopted | none | ≤1 |
| D1 engine verification | D | A4 | run Lane A suites | T0 | test log | A1–A3, A7, A12, A13 | — |
| D2 integration tests | D | B3, B4, B5, B6, B7, B8, C1 | `test_trader_psychology_integration.py`, `test_trader_psychology_gate.py` | G | end-to-end via `apply_trader_review_with_memory`, `apply_pm_decision_with_memory`, `scheduled_output.simulate_output`, Trader Room `reviews_from_run` | A4–A6, A8–A10, A14 | ≤2 |
| D3 full regression | D | D2, C2, C3 | all `tests/test_*.py` listed in A15 | T0 | log | A15 | — (failure → owning node's repair loop) |
| D4 shadow replay | D | B3 | `psychology_replay.py --shadow` over committed `data/trading` + `data/overnight/runs` in a temp dir | T0 | `tests/fixtures/psychology/shadow_report_<sha>.json` | A16 | — |
| D5 Fable review (optional) | D | D3, D4 | read-only review of diff against §3.2, §7, §10, §15 invariants | F (1 call) | review note in PR | — | 0 (findings go back to owning node, ≤1 loop) |

### 16.3 Parallel lanes and integration order

Execution proceeds in waves; every node in a wave may run in parallel, and a wave starts only when its listed dependencies (and any gate) are satisfied.

| Wave | Nodes (parallel) | Waits for |
| --- | --- | --- |
| 0 | — | G0 |
| 1 | A1, B7 | G0 |
| 2 | A2, A3, B1, C1 | A1 |
| 3 | A4 | A2, A3 |
| 4 | D1 | A4 → **G1** |
| 5 | B2 | G1, B1 |
| 6 | B3, B4 | B2 (B3 also needs A2) |
| 7 | B5, B6 | B4 |
| 8 | B8, D4 | B3, B5, B7 (B8); B3 (D4) |
| 9 | D2 | B3, B4, B5, B6, B7, B8, C1 → **G2** |
| 10 | C2, C3 | G2 |
| 11 | D3 | D2, C2, C3 |
| 12 | (G3 check: D3 green, D4 bounded, A11 green) → D5 (optional) → **G4** | D3, D4 |

```
Lane A (engine)       : A1 → {A2, A3} → A4 → D1 ═══ G1
Lane B (integration)  : B1 ─┐  B7 ─┐
                        G1 ─┴─ B2 → {B3, B4} → {B5, B6} → B8 → D2 ═══ G2
Lane C (boundary/docs): C1 (after A1) ─────────────────────────→ C2, C3 (after G2)
Lane D (verification) : D1 (wave 4) · D4 (after B3) · D2 (wave 9) · D3 → G3 → D5 → G4
```

Lanes A, B1, B7 and C1 run in parallel after G0. B2 waits for G1 so the block schema is frozen before it is hashed into contexts. B3/B4 run in parallel after B2; B5/B6 follow B4; B8 needs B3 (events), B5 (journal payload) and B7 (dispositions). D2 integrates everything in Lane B. C2/C3 finalize only after G2 so the prompt text mirrors the accepted check schema. D3 and D4 then gate D5.

### 16.4 Invocation ceilings and token-efficiency rationale

| Model | Ceiling | Rationale |
| --- | --- | --- |
| T0 | unlimited (no model) | file scaffolding, running suites, shadow replay, doc lint |
| Composer 2.5 | **≤ 12 calls** (A1, A2, A3, A4, B1, B5, B6, B7, C1, C2, C3 + 1 spare) | pure functions, tables, fixtures and pass-through edits are high-volume, low-ambiguity; each node has a closed spec in this plan and deterministic tests |
| Grok 4.7 | **≤ 8 calls** (B2, B3, B4, B8, D2 + up to 3 repair passes) | the hash chain, idempotency around `find_event`/`ReviewAlreadyApplied`, per-action gate semantics, and verdict rules are where a wrong edit silently breaks invariants; worth the stronger model |
| Fable 5.1 | **≤ 1 call** (D5) | single cross-cutting read of the integrated diff against the invariants; not for authoring |
| **Total** | **≤ 21 model calls** | plus T0 |

Any node exhausting its repair loop stops the graph at the nearest gate and reports upstream; no automatic cap expansion.

---

## 17. Objections, risks, and open questions for upstream review

1. **PR #130 dead fields (G8).** Three of five `journal_learning_triggers` cannot fire. This plan avoids them; upstream may want #130 to either wire `close_path`/`expression_vs_thesis`/`reaction_vs_expectation` through `record_lifecycle_event` or drop the dead triggers before merge.
2. **PR #130 disposition persistence (G9).** E16–E18 (override failed / correction success / override vindicated) — the most important *recovery* mechanism in this design — require the small B7 change. If upstream declines it, V1 still works but loses the explicit "learned mistake corrected" signal.
3. **Trader pressure gap (G2).** `requires_pressure_assessment` is PM-only. This plan closes the gap for traders via `rank_distortion_risk` rather than editing that function. If upstream prefers a single unified mechanism, B4 should also route PM `rank_distortion_risk` through `pressure_assessment` (already proposed) and V2 can retire one of the two.
4. **Scale.** The dead-band/unit fractions (2% / 25% of material) make psychology live at today's activity without touching reflection thresholds. If book activity grows tenfold, the same fractions scale automatically with `max_drawdown_usd`; no constant needs to change.
5. **Prompt cost.** ~2 KB per sidecar × 17 identities per cycle. Inside prompt discipline; no cap change.
6. **Cycle definition.** Decay is per accepted decision cycle, not per calendar day. Traders get one overnight cycle per weekday plus occasional Trader Room cycles; a weekend does not decay anything. Upstream may prefer a calendar component; the engine can accept an optional `elapsed_days` multiplier on `H` later without schema change.
7. **ChatGPT PM excluded.** Its decisions arrive via Git ingest without a Cursor sidecar; including it would touch `pm-chatgpt-decision.yml` and the ingest schema. Recommend V2.
8. **Coefficient tuning is a judgment call.** §5.3 and §8 values are starting points bounded by guard rails and fixed by fixtures; upstream should treat A4's tuning freeze as the moment they become contract.
9. **Merge ordering.** Implementation must branch from the #130 head (or from `main` after #130 merges). Branching from current `main` (`c4e526d`) would miss `learning.py`, `learning_state.json`, and lesson maturity, and E13–E18 would have nothing to hook.

---

## 18. Delivery

- Artifact: `docs/plans/market-watch-persistent-trader-psychology-plan-2026-09-26.md` (this file)
- Planning branch: `cursor/market-watch-persistent-trader-psychology-architecture-and-execution-graph-e971`, cut from PR #130 head `7d271caf9305899eaf26e537fbb14d8229446a7c`
- No production code, tests, data, workflows, schemas, live state, ACP, schedules, or shared policy were modified. No PR opened. No implementation subagents launched.
