# On-demand Trader Room execution contract

This is the production contract for the full adversarial Trader Room. It supplements `docs/TRADER_ROOM_PROTOCOL.md` and `docs/TRADER_ROOM_EVIDENCE_CONTRACT.md`. The repository dry-run entrypoint is `PYTHONPATH=. python scripts/trader_room_go.py go`; live model execution is dispatched separately through the approved control path.

## Architecture

1. Preflight the four required evidence families.
2. Freeze one common evidence packet and SHA-256. No new evidence after freeze.
3. Launch the locked 14 standing advocates independently on exact `grok-4.6`.
4. Each initial advocate may use at most two `composer-2.5` subagents on the same frozen packet.
5. Every advocate returns its full trade pitch plus a compact `conflict_synopsis`.
6. **Deterministic conflict stage:** code reads only the 14 synopses and structured trades. It identifies direct instrument/currency conflicts, theoretical currency-vs-rates tensions, contextual regime tensions, and the no-trade challenge. This stage consumes zero model calls.
7. Only advocates involved in **direct conflicts** receive one Grok rebuttal pass. Theoretical/context tensions remain visible in the handoff but do not automatically spend rebuttal calls.
8. **Deterministic final handoff:** `scripts/trader_room_finalize.py` reads the already-validated originals, conflict map and rebuttals and writes the PM handoff. It consumes zero model calls. No model-based final aggregator is launched.
9. Persist all artifacts under `trader-room/runs/<run_id>/`. ChatGPT remains the final arbiter.

The old model-based conflict-aggregator and final-aggregator agent files remain compatibility/reference artifacts only; neither is in the production execution path.

## Expression selection contract

Before a rates-first advocate can submit its Round 1 trade, it must compare expressions from the frozen packet:

1. one concrete rates candidate: outright duration, curve, or cross-market rates RV;
2. one concrete spot-FX candidate;
3. the selected expression family and why it is cleaner.

Rates are preferred when the comparison is close. Spot is allowed only with an explicit reason the rates candidate is inferior or unavailable. This is not a forced-rates quota.

Dedicated exceptions:
- `dollar-king`, `cross-merchant`: spot only;
- `vol-convexity`: options/convexity remit unchanged;
- `no-trade-skeptic`: may return no trade; if it endorses one, use the rates-first comparison.

Every non-null trade adds:

```json
{
  "asset_class": "spot_fx | rates | curve | rates_rv | options",
  "expression_comparison": {
    "rates_candidate": "concrete rates expression or null for a dedicated specialist",
    "spot_candidate": "concrete spot expression or null for the vol specialist",
    "selected": "rates | spot | options",
    "rationale": "why this expression is cleaner"
  }
}
```

For rates-first seats, both `rates_candidate` and `spot_candidate` are mandatory non-empty strings even when one says it is unavailable and explains why. The selected family must match `asset_class`.

## Round 1 conflict synopsis

Every `TRADER_ROOM_CONTRIBUTION` must include:

```json
{
  "conflict_synopsis": {
    "seat": "<standing seat>",
    "primary_trade": "<short expression or NO_TRADE>",
    "core_view": "<one sentence>",
    "usd_view": "higher|lower|neutral|not_relevant",
    "cad_view": "higher|lower|neutral|not_relevant",
    "aud_view": "higher|lower|neutral|not_relevant",
    "nzd_view": "higher|lower|neutral|not_relevant",
    "us_rates_view": "higher|lower|neutral|not_relevant",
    "ca_rates_view": "higher|lower|neutral|not_relevant",
    "au_rates_view": "higher|lower|neutral|not_relevant",
    "nz_rates_view": "higher|lower|neutral|not_relevant",
    "risk_view": "risk_on|risk_off|neutral|not_relevant",
    "carry_view": "supports_trade|opposes_trade|neutral|not_relevant",
    "time_horizon": "<short label>",
    "key_catalyst": "<one sentence>",
    "key_invalidation": "<one sentence>",
    "confidence": 0,
    "conflict_tags": ["USD_UP"]
  }
}
```

The synopsis is a compression of the already-completed pitch, not a second opinion.

## Deterministic conflict logic

`scripts/trader_room/conflict.py` owns conflict discovery.

**Direct conflicts** trigger rebuttal routing:
- opposite directions in the same instrument;
- opposite directional views on USD, CAD, AUD or NZD that are not already fully captured by the same-instrument conflict.

**Theoretical tensions** are shown in the deterministic final handoff but do not automatically trigger a rebuttal:
- currency higher versus same-country rates lower;
- currency lower versus same-country rates higher.

**Context tensions** are also non-routing context:
- risk-on versus risk-off;
- carry-supportive versus carry-opposed.

The `no-trade-skeptic` challenge is preserved separately and does not force all 13 trade pitches into rebuttal calls.

No majority vote, confidence ranking, winner, or house view is permitted.

## Model routing

| Work | Exact execution |
| --- | --- |
| ACP parent/orchestrator | `grok-4.6` |
| 14 standing advocates | `grok-4.6` |
| advocate-internal subagents | `composer-2.5`, max two per initial advocate |
| conflict map | deterministic Python, zero model calls |
| direct-conflict rebuttals | `grok-4.6`, max one per conflicted seat |
| final handoff | deterministic Python, zero model calls |

Cursor Auto and every Other Models route are prohibited.

## Finite ceilings

The ACP parent is counted explicitly.

- ACP parent = 1 Grok 4.6
- 14 advocates = 14 Grok 4.6
- conflict mapping = 0 model calls
- rebuttals = at most 14 Grok 4.6
- final handoff = 0 model calls
- **Total Grok ceiling including parent = 29**
- **Composer ceiling = 28**
- **Total model-invocation ceiling = 57**

Every full live run carries:

`MW_TRADER_ROOM_RUN_POLICY={"version":1,"run_type":"trader-room-ondemand","total_model_cap":57,"grok_cap":29,"composer_cap":28,"parent_model":"grok-4.6","parent_total":1,"parent_grok":1}`

The repository `subagentStart` hook enforces these ceilings. Only initial advocates tagged `TRADER_ROOM_ADVOCATE=1` may create Composer children.

## Required trade schema

Every advocate except `no-trade-skeptic` must produce one actionable trade with: `instrument`, `asset_class`, `expression_comparison`, `structure`, `direction`, `thesis`, `mispricing`, `why_now`, `evidence_refs`, `horizon`, `entry`, `target`, `stop`, `invalidation`, `catalysts`, `principal_risks`, and `confidence`. Unsupported levels are JSON `null`.

## Artifact sequence

A complete run contains:

- `evidence_packet.json`
- `submissions/<seat>.json` ×14
- `conflict_map.json`
- `rebuttal_assignments.json`
- `rebuttals/<seat>.json` only for directly conflicted seats
- `pm_handoff.json` generated by `scripts/trader_room_finalize.py`
- `artifact_index.json` generated by the same deterministic finalizer
- budget/invocation evidence

The final handoff marker is exactly:

`STATUS: AWAITING_CHATGPT_ARBITRATION`

## Recovery rule

If an agent fails after Round 1, preserve the frozen packet and completed submissions first. Do **not** rerun the 14 advocates merely to recover orchestration state. Materialize the deterministic conflict map from the saved synopses and continue from there.
