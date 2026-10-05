# N10 rollback note

## Removed in N10

No production code or modules were deleted. The consumer audit found no path with zero callers outside its definition.

No dead helper functions were removed (none identified that are unreferenced in both production and tests).

## Kept (explicit)

- `_merge_ingestion_rows` in `scripts/market_watch_launch/ingest.py` (append-only merge; sole writer)
- `apply_lineage_to_macro_hard` and lineage score staging (`scripts/market_watch_launch/lineage.py`)
- `bind_scores` / `reject_unequal_score_copies` in `scripts/run_state/`
- `scripts/run_state/publication.py` (offline-only publication)
- All `patch_v*` directories used by `.github/workflows/deploy-pages.yml`
- `scripts/macro_ingestion/calendar.py` `release_due` and `scripts/macro_freshness.py` `release_due`
- `room_data_caveat` in `scripts/overnight/public_prose.py`

## Artifacts added in N10 (docs + tests only)

- `docs/architecture_repair/consumer_audit.md`
- `docs/architecture_repair/rollback_note.md`
- `tests/run_state/test_no_redundant_writers.py`

## Restore pre-N10 tree (if a future commit deletes code)

N10 made no deletions. If a later commit on this branch removes files, restore with:

```bash
git revert <n10-or-later-deletion-commit-sha>
```

Or reset the branch to the parent of the deletion commit:

```bash
git log --oneline -5   # locate pre-deletion SHA
git checkout <pre-n10-sha> -- <path>
```

No N10 commit was created in this execution (per instruction: do not commit).
