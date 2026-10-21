# Australian CPI pre-release nowcast engine (Sep 2026, shadow-only)

## Summary
Shadow-only Australian CPI pre-release nowcast for September 2026 (ABS release 2026-10-28 11:30 Australia/Sydney). Manual CLI only; no workflows, schedules, or writes to temperature history, macro ingestion, or Market Watch.

## Context
- ACP: https://github.com/McCabeAI/agent-control-plane/issues/286
- Opus: plan/review; Grok 4.7: data layer + models; Composer 2.5: integration, scorecard, docs, candidate archives
- **Integrity:** first candidate run was superseded (`tool_git_dirty: true`, commit `39cd380c`) because it was generated from an uncommitted working tree; replaced by clean-tree archives with `tool_git_dirty: false`.
- **Backtest:** outputs now live under `candidates/backtests/...` with `au_cpi_backtest_archive_manifest_v1` (no longer uncaptured files in the run dir).

## What changed
- `scripts/au_cpi_release/` — engine, archives (incl. backtest), scorecard, fixtures
- `tests/au_cpi_release/` — gates G1–G4, nowcast, scorecard, trim
- `docs/au_cpi_release/` — PLAN, RUNBOOK, METHODOLOGY, BACKTEST, SCORECARD, candidates

## September 2026 candidate
- Run: `docs/au_cpi_release/candidates/runs/2026-09-asof-2026-10-22T015000p1100-8d11c6256324`
- Backtest: `docs/au_cpi_release/candidates/backtests/2026-09-asof-2026-10-22T015000p1100-8d11c6256324`
- `as_of`: 2026-10-22T01:50:00+11:00
- `generated_at`: 2026-10-22T01:50:06+11:00
- `nowcast.json` sha256: `2cf6f2da67f2d259d3cb1cdacc9bc4b84ec95237a80c01ea8e24b46cc5edfa12`
- Run manifest: `tool_git_commit`=e971245992fbe268f08316374072e7e0c6a6c484, `tool_git_dirty`=False
- Backtest manifest: `tool_git_commit`=1eb9f331315010c4b4ab83238805e1b7023a44db, `tool_git_dirty`=False

| Target | status | unrounded | 1dp | model | band68 | band90 | n | low_sample |
| --- | --- | ---: | ---: | --- | --- | --- | ---: | --- |
| headline_nsa_mom | ok | 0.5055526076899186 | 0.5 | sa_persistence_x_seasonal_12 | [0.1410136939253181, 0.8700915214545191] | [-0.12484630555397169, 1.135951520933809] | 16 | True |
| headline_nsa_yoy | ok | 4.0232469489590805 | 4.0 | sa_persistence_x_seasonal_12 | [3.6459491732127036, 4.400544724705435] | [3.3707840737516426, 4.675709824166474] | 16 | True |
| headline_sa_mom | ok | 0.3232749005800978 | 0.3 | mean_12 | [-0.05456820799570222, 0.7011180091558977] | [-0.2855287428262233, 0.9320785439864189] | 16 | True |
| headline_sa_yoy | ok | 3.997166455474477 | 4.0 | mean_12 | [3.6054865317922236, 4.388846379156686] | [3.366068099636599, 4.628264811312333] | 16 | True |
| trimmed_mean_monthly_sa_mom | ok | 0.293090608139888 | 0.3 | mean_12 | [0.23953428411088054, 0.3466469321688955] | [0.15197325208257767, 0.43420796419719837] | 16 | True |
| trimmed_mean_monthly_sa_yoy | ok | 3.6056003046294416 | 3.6 | mean_12 | [3.550275106577505, 3.660925502681356] | [3.459822083028463, 3.751378526230398] | 16 | True |
| trimmed_mean_quarterly_legacy_qoq | ok | 0.8125952260030544 | 0.8 | persistence | [0.60048678223239, 1.0247036697737189] | [0.4125651288231724, 1.2126253231829365] | 176 | False |
| trimmed_mean_quarterly_legacy_yoy | ok | 3.434639550103702 | 3.4 | persistence | [3.2170143577577637, 3.65226474244964] | [3.0242050322913716, 3.8450740679160322] | 174 | False |
| weighted_median_monthly_sa_mom | ok | 0.2501764183060695 | 0.3 | persistence | [0.1704452852071059, 0.32990755140503314] | [0.11127636410079406, 0.389076472511345] | 27 | False |
| weighted_median_monthly_sa_yoy | ok | 3.435177002100298 | 3.4 | persistence | [3.3529127691651395, 3.517441235035501] | [3.29186402046151, 3.578489983739108] | 17 | True |

## Key evidence
- G5 trim reconstruction (fixture verify-trim primary variant): 20 months, mean abs error 0.0018449433963161287 pp, max 0.009502236944340436 pp, rounded MoM 19/20
- Quarterly CPI_Q vs RBA G1 vs Appendix 1a: 177/177 rounded QoQ match (`equivalent`)
- Aggregation identity: n_full=20 mean_abs_residual_pp=0.003838771601283243 max_abs_residual_pp=0.007761260257528546
- Amendment A1: model selection uses **common-sample** pseudo-OOS MAE (unequal-sample legacy still reported)
- Quarterly proxy bridge (not selected): value 1.0437709077788515 vs persistence QoQ 0.8125952260030544; overlap n=8

## Caveats / blockers
- Low sample (n<20) on most monthly targets; wide headline bands
- ABS website maintenance until 2026-10-22; Wayback mirrors labelled
- No pre-release fuel/rebate/travel official signals
- True-vintage backtest n≈1 (blocked items in backtest.json)

## Validation
```bash
PYTHONPATH=. python3 -m unittest discover -s tests/au_cpi_release -t .  # 43 OK
PYTHONPATH=. python3 -m unittest discover -s tests/core_pce_release -t .  # 134 OK
PYTHONPATH=. python3 -m unittest tests.test_australia_housing_data  # 4 OK
PYTHONPATH=. python3 -m unittest discover -s tests/macro_ingestion -t .  # 296 run, 2 preexisting failures
PYTHONPATH=. python3 -m unittest tests.canadian_cpi_release.test_nowcast  # 12 OK
git diff --name-only 59c3a9be..HEAD  # only au_cpi_release paths
```
Preservation: temperature_scores.json, macro_ingestion catalog/au fragment sha256 unchanged vs `59c3a9be`.

## Manual rerun
See `docs/au_cpi_release/RUNBOOK.md` (snapshot --live after ABS returns; nowcast; backtest to `candidates/backtests/`; replay; scorecard post-release).

**No workflows, no schedule, no auto-merge, shadow-only.**

## PR creation status
No allowed implementation subagent (Grok 4.7 or Composer 2.5) had a pull-request creation tool in this run (no ManagePullRequest; GitHub MCP namespace in error state), and the parent Opus planner is barred from PR operations by the ACP role boundary. The branch is pushed; a human can open the draft PR against `main` from https://github.com/McCabeAI/market-watch-public-dashboard/compare/main...cursor/australian-cpi-nowcast-opus-planning-grok-composer-implementation-f8bf using this file as the description. Do not auto-merge.
