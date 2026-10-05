# Pages recovery and freeze-score repair approval

- **Verdict:** PASS
- **Reviewer:** parent Grok 4.7 in this provider execution. Composer 2.5 implemented the bounded edits. No other model was used.
- **Starting ref:** `3a4ec335e0d1356586980337d373a9324e6ac16f`
- **Supersedes:** `docs/architecture_repair/N17_APPROVAL.md` for any tree after that commit. The N17 fingerprint does not approve this repair.
- **Unresolved critical findings:** 0
- **Unresolved high findings:** 0
- **Repair fingerprint:** `74ca067504e65ced7fe06670fec8b928bdcfe303618393d7c712ca195cc0ccca`
- **Fingerprint input:** SHA-256 of the five path digests below, each line `hexdigest  path` joined by `\n` and terminated by a final newline. This file, `call_ledger.json`, and `N17_APPROVAL.md` are excluded. The git commit SHA is recorded in PR #167 after this file is committed.

## Root causes

Oct 2 Pages recovery tests copied `data/market_watch_launches` from the working tree. That tree now has Oct 2 reconciled and `mwl-20261005T100821Z-3f9807cb` live, so the suite no longer saw the pending Oct 2 launch or the Oct 5 concurrency block. The tests now copy three pinned git objects into an isolated temp store: the pending Oct 2 launch at `ffec0735582a357277e2ffa6cfe571b29608c6dc`, and the pre-recovery index plus blocked Oct 5 launch at `6ad0214922d677581d1c68aff24c19c86a264dc2`. They do not read the current canonical index as fixture truth. The canonical Oct 2 file remains sha256 `2735b7fd338f61df995f166ebc4fbd20f549c7193ea7235a43c2cd01bc2ba46b`.

`test_freeze_packet_carries_staged_temperature_scores` staged one new score document. Collect already stores that document on the flattened `macro_hard.temperature_scores` field (`_family` merges `extra`) and at the top level. Lineage then wrote a second document at `macro_hard.extra.temperature_scores`. `reject_unequal_score_copies` correctly rejected the pair. Acquire and freeze now copy the lineage document onto the flattened field and the top-level field, so the packet carries one score. The guard is unchanged (`scripts/run_state/replay.py` still hashes to `f309ab79bfd0ca385d718800044c72e9774b19fca0f0136532b9a1af7daeaf7d`). Unequal copies still fail closed.

## Validation observed in this review

- `PYTHONPATH=. python3 -m unittest tests.test_mw_launch_persist_boundary tests.test_mw_launch_pages_recovery tests.test_mw_launch_graph tests.test_mw_launch_quality tests.test_mw_launch_lineage tests.test_mw_launch_completion tests.test_mw_launch_integration -v` — Ran 84 tests in 111.549s, OK.
- `PYTHONPATH=. python3 -m unittest discover -s tests/run_state -v` — Ran 114 tests in 0.012s, OK.
- `PYTHONPATH=. python3 -m unittest tests.test_public_prose tests.test_source_health_and_cross_assets tests.test_quality_gate_macro_overlay tests.test_temperature_level -v` — Ran 38 tests in 0.106s, OK, 1 skipped.

No live acquisition, Market Watch cycle, Trader Room, PM run, workflow dispatch, deployment, or merge was run.

## Approved path digests

```text
fd765edba4a6c267d619792b9786d083d7db2baced4551c658eff13426d51c80  scripts/market_watch_launch/acquire.py
09cea083f95d81fd2edcdd0c963d36f6e031ee43d5766d62aa8e1bbf2a60ab3c  scripts/market_watch_launch/freeze.py
f309ab79bfd0ca385d718800044c72e9774b19fca0f0136532b9a1af7daeaf7d  scripts/run_state/replay.py
b14139d29674af1ab30184eefa98a3bf2a16d67189118215799321fa4fa731b1  tests/test_mw_launch_lineage.py
f1d4328a433261e226aae85eb74c3bba40113ff3612e9e777b34b908530b3889  tests/test_mw_launch_pages_recovery.py
```
