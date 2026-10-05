# N17 exact-tree approval

> This PASS approves only commit `3a4ec335e0d1356586980337d373a9324e6ac16f`. It does not approve the later Pages-recovery and freeze-score repair. That tree is covered by `docs/architecture_repair/PAGES_LINEAGE_REPAIR_APPROVAL.md`.

- **Verdict:** PASS
- **Reviewer:** parent Grok 4.7, in-process. A fresh `grok-4.7` subagent was denied by the repository hook (allowlist composer-2.5, grok-4.6, grok-4.5). This review is not an additional provider invocation. grok-4.6 was not used.
- **Baseline:** `07d6406f2a360c57c52d7be034f3f2530daae7e9`
- **Unresolved critical findings:** 0
- **Unresolved high findings:** 0
- **Implementation fingerprint:** `08b420de29661467fcd5acf137ef5a0e6c8a5ce617f5699524eac2b3db4bc6a4`
- **Fingerprint input:** SHA-256 of the 43 approved path digests below, each line `hexdigest  path` joined by `\n` and terminated by a final newline. This file is excluded from the fingerprint. N18 must confirm those 43 blobs still match and must not edit them.

## Closed review findings

N11 F1–F5 are closed in the approved tree: a partial canonical state list cannot clear an uncovered legacy country block; a known occurred expectation outranks a catalog-unknown definition; deploy acknowledgement rejects an artifact hash mismatch; `assemble_series_run_state` validates the expectation; policy parsing does not call `datetime.now`.

N14 A1–A2 are closed: satisfaction requires a period match plus non-empty units and transformation, and equality with `expected_units` / `expected_transformation` when the expectation carries them; `publish_offline` rejects a non-empty timestamp that is not an aware datetime at or before cutoff, except an explicit `date_only` date on or before the cutoff date.

## What this PASS covers

- Versioned `SeriesDefinition`, `ReleaseExpectation`, `AcquisitionAttempt`, `SchedulerEvent`, `ObservationVersion`, `SeriesRunState`, `EvidenceItem`, and `RunManifest`, with validators that keep unknown calendars null rather than not-due.
- Offline October 5 replay: primary labor timeouts preserved, retries recorded as `skipped_retry`, September 2026 Employment Situation occurred by the October 5 cutoff, `macro:US` blocked with other countries eligible, one score binding, gate/freeze/cutoff shared, public caveat does not claim no release was due.
- Critical-first admission. Skipped admission is a scheduler event, not an `AcquisitionAttempt`. `budget_deferred` is not an attempt result.
- Scores bind through unchanged `component_level`. Fetch failure does not replace `score_input_observation_id`.
- Publication is offline from an approved bundle. Forbidden bundle keys `opener`, `fetch`, and `rescore` are rejected. Deploy acknowledgement is idempotent on `launch_id:artifact_sha256`.
- `run-report.json` and `run-report.html` are produced from the same manifest.
- N10 deleted no production path. Calibration, packet/book bindings, raw receipts, and country isolation stay in place.
- Hermetic `tests/run_state`: 114 tests OK in 0.011s. Adjacent prose, source-health, quality-gate overlay, and temperature-level tests: 38 tests OK, 1 skip. No network and no live acquisition.

## Residuals (not critical or high)

- `scripts/macro_ingestion/calendar.py` `release_due()` still returns false on empty dates for legacy tests. Canonical expectations do not treat that bool as proof of not-due.
- Superseded patch, payload, and bridge paths remain because the consumer audit found live readers. No deletion in this cut.
- Unknown calendar is reported and does not by itself block a country.
- Checkpoints are an in-memory compare-and-swap store. This migration does not add a database.
- A started primary row that has no `attempt_history` and is later merged with `budget_deferred` is labeled `skipped_admission`. The October 5 replay seeds `attempt_history` and records `skipped_retry`, and the timeout error is kept. The empty-history label is a residual typing edge, not the incident path.
- `build_run_report` recounts due and satisfied from expectation flags when the caller supplies them. `assemble_series_run_state` stores carry reason and observation ids; the manifest coverage is the authoritative count when states are omitted.
- `tests/test_mw_launch_pages_recovery.py` fails on clean `07d6406` with the same 12 failures and 1 error (12 + `FileNotFoundError: unknown launch_id mwl-20261005T100821Z-3f9807cb`). This branch did not edit `data/market_watch_launches/mwl-20261002T094056Z-1d0ebea5/launch.json` (blob `cdfa0ff65b9131d071ecc39906a3af7de2a3873f`, sha256 `2735b7fd338f61df995f166ebc4fbd20f549c7193ea7235a43c2cd01bc2ba46b`). The suite was not patched.
- No live shadow run is authorized.

## Approved path digests

```text
09ecf01d582b248995730f8b3eeed7f47ebf89f305f6ee525b7e3b45655d8ffe  docs/architecture_repair/N00_REPAIR_PLAN.md
949a33d02f473788cf22fa915e58b4eca6e14521b2ca1d06e6f02d64220e53e3  docs/architecture_repair/N11_REVIEW.md
0a709ccbb55d505ffec4d35cb90b59bece3c1b66f4f9ec46dc2867687c14c4fd  docs/architecture_repair/N14_REVIEW.md
865ee7892d35210f4517fa1260ba30114c193e8c1b7de42f21582bffada782bf  docs/architecture_repair/N16_E2E.md
1ef6afe1156c5c6634437368c65a161295a07ff40719d0a12108c960213b468d  docs/architecture_repair/call_ledger.json
dd1ba7a373855dd3507272ff019dbbdb44b9b32ee441a2f5aa35429663bfdf0a  docs/architecture_repair/consumer_audit.md
be6c19a8f52bf7ccd265d1545f5b8a1022805fe1eebb178655cce00e42c4fa00  docs/architecture_repair/rollback_note.md
c7a5774f9f665745f04b1733f133b28bcefa753bba62e0b6d070628406e104e6  scripts/market_watch_launch/freeze.py
cb664c618dce9c898c0fb61550de734a3a97a9a886a24ef419a002153dbbd3ea  scripts/market_watch_launch/ingest.py
ee770b5be42bfb1b31a6b14e073f6be86ea73cf5e51c1e56ea66ea571c737944  scripts/market_watch_launch/quality_gate.py
3daf5fdb3e7b9483869e02dc51d6f9977b4b8f4c0554d7566374164d96f8efc0  scripts/overnight/public_prose.py
a26e023a3dfa242279ea96fdfc5da4d8eadaacd38935867b289780066c581188  scripts/run_state/__init__.py
f429647384aff6dbc90251fa7670a5fb97f119c5c4f9d03f9250544385e5dd12  scripts/run_state/compiler.py
8eda3c1023dd9d451396b04108f521020c3a098685e93cdc5c32325c46258510  scripts/run_state/evidence.py
cceb47d073f414091c8991e6ec7e165f1992e2233a415131d3332ddda53fdadd  scripts/run_state/expectations.py
2d63905b8d4af28f794f449f905f3dae96fd27a3d9a6a3d0004910affa0f688a  scripts/run_state/lifecycle.py
4df53a8e1049a11beae137e19cb00fcbbb5b4dc1cd1f2e65998cee5439467917  scripts/run_state/observations.py
e3431a7ba4175490fe84d8613efff38c042a517869cc58d67de06fe0a406e99c  scripts/run_state/policy.py
6e90004d4dffc81392c90fe4702635119f74abff79e6e633c08790c7c9396d67  scripts/run_state/prose.py
f9d8a5be9190b3fda0671ef5bb358c31f9ee0b552a8d0439c044049d578aefdf  scripts/run_state/publication.py
f309ab79bfd0ca385d718800044c72e9774b19fca0f0136532b9a1af7daeaf7d  scripts/run_state/replay.py
82002f533fc09bdf69961f3c126eb509f6639a9da571665d915c7ba06e7a881a  scripts/run_state/report.py
a08382c4329be6c25b86ab717a45a89302f73576cc8051de765f3eff1129d385  scripts/run_state/scheduler.py
88eb51809739902ce44709ad43d0264e3988d71e646e5b80c6b635608edf5511  scripts/run_state/schema.py
e12ed12d57a2f28d26f287b3d8ae45b4e3b7e0d97c47a3d93dec341bc75ae294  scripts/run_state/scores.py
a8f4794459b72fd96765a8e86b1175ebda77dd99b01ea6402d41864ff50dff10  scripts/run_state/state.py
441aff84b4c6cd7bf6a6f64550322eb06e04a09bb5334d0b8c32e4bab472e5ae  tests/fixtures/run_state/oct2/recovery_identity.json
dad8f2b0578f0cd81b887cd211b6b31bf3794995765377fad4ab034919a4042a  tests/fixtures/run_state/oct5/incident.json
2197f4fae6d44856185ceb216376ae2550ea740b9356f38622366f9312879b87  tests/run_state/__init__.py
b4a775135e4c601dff2d154efeb605d0cee6327ae22f9df42649c1197f8bfa93  tests/run_state/clock.py
036a683f77cff5843975410b3bfc738e8dbbfd06dbacbde08b1e6afbe7db2e8e  tests/run_state/test_compiler.py
f16e49305976c974db8196d506c84062ea36b405f9fae9a5e6a41e727b0d1417  tests/run_state/test_e2e_matrix.py
2ebe0ba135f3cdbbdb0e10e8b524f7f58be1313e5fe36f61dc3583b1dbbf4e00  tests/run_state/test_evidence_prose.py
31d2105c7e239fc77fbe2d257641dc21d1a4c3aa5f3a890e683eedc5ee70af0f  tests/run_state/test_fixtures_and_incident.py
a092052aa7531790f719eb9d32dbceab03d4a2223b0d33349793efd13ee79389  tests/run_state/test_lifecycle.py
105fc13afe265ca4614219837db7b1208591ca734140f7380e84dd68de0b68e6  tests/run_state/test_no_redundant_writers.py
2723fdd794f4ae967bee74dddc873e3b1535405b675a13bd724bc5f5a4ddcf68  tests/run_state/test_observations.py
96b3f41fd070691dcd9de56541de9c64c50206562abacee708997ea507b46dfe  tests/run_state/test_oct5_replay.py
dbd801418f4c0397c9c66fbce653639212438ece12b478a1b4fcca607cd566cb  tests/run_state/test_policy_overlay.py
86f38d6318f44fbac8d2fc32bfb43d8f5bf624b1b9adc21bde21b44ba15c18e7  tests/run_state/test_policy_scores.py
c5dfd8ef58bde885ee3fb46a3bd954ff0faab5ec02ac4de2d133e44b662d2784  tests/run_state/test_report.py
2b57855ce1c703121594c559618b1d8b330b81f18c0a44dd3e934d28fae1fe51  tests/run_state/test_scheduler.py
d3678696d3b59ad8362875d94c231158518806a33ddc10ad2354d4e19b604d7f  tests/run_state/test_schema.py
```
