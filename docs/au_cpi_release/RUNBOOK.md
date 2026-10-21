# Australian CPI pre-release nowcast — runbook

Manual, human-triggered CLI for the **ABS Consumer Price Index, Australia** reference month. The frozen fixture `scripts/au_cpi_release/fixtures/pre_2026-10-28/` was built before the **2026-10-28 11:30 Australia/Sydney (+11:00)** release (freeze). September 2026 is a **shadow-only** pre-release nowcast: nothing here writes to `data/temperature_history/`, `data/temperature_scores.json`, `data/macro_ingestion/`, Market Watch launches, `.github/workflows/`, cron, or ACP.

**Freeze semantics:** publication is refused at or after **2026-10-28T11:30:00+11:00** (`generated_after_freeze`). That instant is **2026-10-27T20:30:00-04:00** in America/New_York. Replay of an archived pre-freeze run is allowed (`replay`).

There is **no workflow automation, no schedule, and no auto-merge** for this engine.

Install dependencies once:

```bash
pip install -r requirements-market-state.txt
```

## Commands

| Command | Purpose |
| --- | --- |
| `snapshot --live` | Fetch ABS Data API (+ optional Wayback workbooks) into an immutable snapshot archive |
| `nowcast` | Pre-release forecast from a `snapshot.json` into an immutable run archive |
| `backtest` | Walk-forward pseudo-OOS metrics (+ separate true-vintage section) |
| `replay` | Recompute `nowcast.json` from archived inputs; must be byte-identical |
| `verify-trim` | Rank-and-trim reconstruction diagnostic (offline) |
| `scorecard` | Post-release forecast vs actual (refuses before release time) |

### Live snapshot

```bash
PYTHONPATH=. python3 -m scripts.au_cpi_release snapshot \
  --live \
  --as-of 2026-10-22T09:00:00+11:00 \
  --release 2026-09 \
  --out /tmp/au_cpi_snapshots
```

Requires `--live`. Writes:

```text
<out>/snapshots/asof-<as-of>-<snapshot_sha12>/
  snapshot.json
  manifest.json
  raw/                  # bytes actually fetched (API CSV, RBA G1, optional Wayback xlsx)
```

Exit **0** on success; **2** on `ArchiveConflict`, source errors, or missing `--live`.

**After ABS website maintenance (expected back 2026-10-22):** rerun `snapshot --live` to attach workbook bytes (Tables 7/8, Appendix 1a) that were unavailable during maintenance. Until then, the committed fixture uses the ABS Data API plus archived Wayback/in-repo workbooks documented in `snapshot.json` notes.

### Nowcast schemas (v1 frozen vs v2 publication)

| Schema | Archive directory | Contents |
| --- | --- | --- |
| `au_cpi_nowcast_v1` | `…-<sha12>/` (no suffix) | Full snapshot + raw bytes; immutable pre-repair candidate |
| `au_cpi_nowcast_v2` (default CLI) | `…-<sha12>-v2/` with `--reference-snapshot` | Slim archive: `nowcast.json`, `nowcast.txt`, `manifest.json` + `snapshot_path` / `snapshot_sha256` |

Monthly API hashes on **2026-10-21** matched the frozen fixture (`ede7bc06…` headline original, `1ae31961…` analytical SA, `d32ca991…` CPI_Q); the fixture was **not** replaced. ABS website returned **HTTP 503** on 2026-10-21 so workbook bytes were not refreshed.

Additive quarterly-headline provenance (not part of snapshot `8d11c6256324`): `docs/au_cpi_release/provenance/2026-10-21T183259Z-abs-cpi-headline-quarterly/`.

### Nowcast (fixture — September 2026 v2 candidate)

```bash
PYTHONPATH=. python3 -m scripts.au_cpi_release nowcast \
  --release 2026-09 \
  --as-of 2026-10-22T01:50:00+11:00 \
  --generated-at "$(PYTHONPATH=. python3 -c 'from scripts.au_cpi_release.calendar import sydney_now; print(sydney_now().isoformat())')" \
  --fixture scripts/au_cpi_release/fixtures/pre_2026-10-28/snapshot.json \
  --reference-snapshot \
  --out docs/au_cpi_release/candidates
```

`generated_at` must be timezone-aware and **before** `2026-10-28T11:30:00+11:00`. Default publication schema is **v2**; monthly and legacy quarterly trimmed-mean targets match the frozen **v1** floats.

A full embedded snapshot run (no `--reference-snapshot`) still writes `snapshot.json` and `raw/` under `…-<sha12>/` (see tests).

Writes (`--reference-snapshot`):

```text
<out>/runs/<release>-asof-<as-of>-<sha12>-v2/
  manifest.json
  nowcast.json
  nowcast.txt
```

Exit **0** when `status` is `ok`; **2** when blocked (`NOT PUBLISHED` on stderr).

### Nowcast from a fresh live snapshot

```bash
SNAP=/tmp/au_cpi_snapshots/snapshots/asof-.../
PYTHONPATH=. python3 -m scripts.au_cpi_release nowcast \
  --release 2026-09 \
  --as-of <timezone-aware cutoff >= snapshot retrieved_at> \
  --fixture "$SNAP/snapshot.json" \
  --out /tmp/au_cpi_runs
```

### Backtest

```bash
PYTHONPATH=. python3 -m scripts.au_cpi_release backtest \
  --release 2026-09 \
  --as-of 2026-10-22T01:50:00+11:00 \
  --fixture scripts/au_cpi_release/fixtures/pre_2026-10-28/snapshot.json \
  --out docs/au_cpi_release/candidates
```

Writes `<out>/backtests/<release-or-all>-asof-<as-of>-<snapshot_sha12>/` with `backtest.json`, `backtest.txt`, and `manifest.json`. Label inside JSON: **pseudo_oos_latest_vintage** (not true vintage).

### Replay

**v1 (frozen, embedded snapshot):**

```bash
PYTHONPATH=. python3 -m scripts.au_cpi_release replay \
  --run-dir docs/au_cpi_release/candidates/runs/2026-09-asof-2026-10-22T015000p1100-8d11c6256324
```

**v2 (reference snapshot):**

```bash
PYTHONPATH=. python3 -m scripts.au_cpi_release replay \
  --run-dir docs/au_cpi_release/candidates/runs/2026-09-asof-2026-10-22T015000p1100-8d11c6256324-v2
```

Replay reads `schema_version` from archived `nowcast.json`. When `snapshot.json` is absent, it loads `manifest.snapshot_path` from the repo root and verifies `snapshot_sha256`.

Exit **0** only if recomputed `nowcast.json` matches archived bytes and manifest hashes verify.

### Verify trim (G5)

```bash
PYTHONPATH=. python3 -m scripts.au_cpi_release verify-trim \
  --fixture scripts/au_cpi_release/fixtures/pre_2026-10-28/snapshot.json \
  --out /tmp/au_trim_out
```

### Scorecard (post-release only)

```bash
RUN_DIR=docs/au_cpi_release/candidates/runs/2026-09-asof-2026-10-22T015000p1100-8d11c6256324
PYTHONPATH=. python3 -m scripts.au_cpi_release scorecard \
  --nowcast "$RUN_DIR/nowcast.json" \
  --actual-fixture /path/to/post_release_snapshot.json \
  --out "$RUN_DIR/scorecard"
```

Exit **2** with `scorecard_before_release` when:

- actual snapshot `retrieved_at` is **before** the nowcast `release_time`, or
- required target periods are missing from the actual snapshot.

Also exit **2** on manifest hash mismatch when `manifest.json` is present.

## Exit codes

| Code | Meaning |
| ---: | --- |
| 0 | Success |
| 2 | Publication blocked (`NOT PUBLISHED` + reason on stderr) |

Common `reason` tokens: `generated_after_freeze`, `snapshot_retrieved_after_release`, `archive_conflict`, `archive_hash_mismatch`, `fixture_stale_for_release`, `scorecard_before_release`, `manifest_hash_mismatch`, `replay_mismatch`.

## Archive layout

- **Snapshots:** `<out>/snapshots/asof-<as-of>-<sha12>/`
- **Runs:** `<out>/runs/<release>-asof-<as-of>-<sha12>/` (v1) or `…-<sha12>-v2/` (v2 reference snapshot)
- **Backtests:** `<out>/backtests/<release-or-all>-asof-<as-of>-<sha12>/`

Each archive includes `manifest.json` with per-file `sha256` and `bytes`. Identical bytes are idempotent; conflicting bytes raise `ArchiveConflict` and leave prior files untouched.

## September 2026 committed candidate

| Field | Value |
| --- | --- |
| Run directory | `docs/au_cpi_release/candidates/runs/2026-09-asof-2026-10-22T015000p1100-8d11c6256324` |
| Backtest archive | `docs/au_cpi_release/candidates/backtests/2026-09-asof-2026-10-22T015000p1100-8d11c6256324` |
| `as_of` | 2026-10-22T01:50:00+11:00 |
| `generated_at` | 2026-10-22T01:50:06+11:00 |
| `nowcast.json` sha256 | `2cf6f2da67f2d259d3cb1cdacc9bc4b84ec95237a80c01ea8e24b46cc5edfa12` |
| `tool_git_dirty` (run manifest) | false |
| Supersedes | `2026-09-asof-2026-10-22T012500p1100-8d11c6256324` (removed; had `tool_git_dirty: true` from uncommitted working tree) |
| Fixture `retrieved_at` | 2026-10-21T13:26:33Z |

See `SCORECARD_2026-09.md` for the forecast table and post-release scorecard command.

## Failure behaviour

- **Network / ABS API:** `snapshot --live` fails closed; no partial publish.
- **Stale fixture for release:** nowcast blocked if the information set cannot include the month before the target.
- **Leakage:** observations with `published_at` after `as_of` are ignored; snapshots retrieved at or after release time cannot feed a pre-release nowcast.
- **Freeze:** `nowcast` refuses `generated_at >= release_time`.
- **Archive conflict:** exit 2; existing directory unchanged.

## Explicit non-goals

- No GitHub Actions workflows, cron, or schedules for this package.
- Shadow-only: does **not** modify temperature scores/history, macro ingestion catalogs, or Market Watch.
