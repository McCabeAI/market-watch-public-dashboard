# Trader psychology (private)

Psychology is private decision machinery for the 14 trader seats and the three automated PMs. ChatGPT is not applicable. It does not choose, size, force, or block `HOLD`, `NO_TRADE`, `REDUCE`, or `CLOSE`. It never writes the ledger, books, lessons, P&L, NAV, funding, or risk limits.

## State

Eight axes live in `data/trading/<owner_type>/<owner_id>/psychology_state.json`: `self_trust`, `frustration`, `defensiveness`, `chase_pressure`, `revenge_pressure`, `complacency`, `thesis_attachment`, `external_pressure`.

`psychology_events.json` is append-only. `replay(events)` rebuilds the state. One accepted identity cycle decays toward the persona baseline, applies evidence events in parallel against that post-decay state, then clips the net move to ±0.25. The first cycle after a seed does not decay. Axes stay in `[0, 1]`.

Persona differences are coefficients in `scripts/trading/psychology_profiles.py` (baselines, gains, half-lives, and a flat-by-design scale). There is no per-seat control flow.

## When it moves

Trusted code records events only from the identity's own accepted cycle: session P&L outside a dead band, closes, givebacks, new highs, rank changes, opportunity-aware flat cycles, blocked expansions, learning-default transitions, repeated-lesson count increases, and the outcome of a persisted `APPLIES` / `DOES_NOT_APPLY` / `OVERRIDE` disposition. A lesson existing, being added, or being reinforced does not move state.

Flat pressure requires a fresh market and at least three flat cycles. No-Trade Skeptic, Grinder, and vol-convexity scale that event down. It never creates a deployment obligation.

Same-family revenge tags last three cycles and then expire. They make the revenge questions relevant only for that family.

## Decision contract

`build_memory_context` only reads psychology. The block is inside the memory hash. When a required flag intersects `OPEN`, `ADD`, or `HEDGE`, the seat returns `psychology_check` echoing `state_sha256`. A missing, stale, or declining check blocks only that expansion. A substantive override is allowed and is journaled with `pressure_assessment` for later outcome scoring.

`psychology_check` is required only for that intersection. De-risking stays executable in every state.

Trusted code later scores an overridden expansion as `distorted`, `sharpened`, or `inconclusive`. Ambiguous cases stay inconclusive. Self-reported pressure, chase, or luck cannot improve state. Repeated disagreement with the trusted verdict can mark self-report unreliable. That flag is informational. It does not assign a competence label.

## Privacy

Axes, flags, Learning Default, lesson matching, examiner notes, and psychology checks stay out of public trader prose, PM prose, and dashboard output.

## September shadow

Replaying the committed September 2026 books in temporary memory, without writing `data/trading`, leaves every axis within 0.26 of its baseline and raises no flag. The largest move is mean-reverter `external_pressure` after real rank changes. That is below the 0.50 rank-distortion check. The plan's illustrative 0.20 bound assumed the roughly $50k closes were inside the $40k dead band; those closes are slightly outside it, and their revenge tags expire inside the same four-session window. Coefficients stay at the plan's proposed values.
