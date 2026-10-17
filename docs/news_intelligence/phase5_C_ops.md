# Phase 5C operational review

Verdict: **PASS**

No ACP, CI, or credential edit. Receipt dicts still have exactly the seven keys. A fetcher that raises on a non-Bing, non-Reuters URL fails that surface only and does not abort `acquire_current_news` or overnight collect.

Reviewed on `cursor/market-watch-g10-news-intelligence-overhaul-six-phase-grok-composer-graph-bbf3`. No code was edited and nothing was committed. This note is the only file added by the review.

## 1. Tree boundaries

`git diff --stat` (tracked edits only):

```
 scripts/live_news_discovery_smoke.py |  25 +-
 scripts/overnight/accepted_news.py   |   6 +-
 scripts/overnight/assemble.py        |  10 +-
 scripts/overnight/live_news.py       | 699 ++++++++---------------------------
 4 files changed, 181 insertions(+), 559 deletions(-)
```

`git status` also shows untracked files, none of them under the forbidden paths:

- `docs/news_intelligence/phase1_A_source_coverage.md`
- `docs/news_intelligence/phase1_B_g10_transmission.md`
- `docs/news_intelligence/phase1_C_replay_corpus.md`
- `docs/news_intelligence/phase1_D_pipeline_contracts.md`
- `docs/news_intelligence/phase2_design.md`
- `docs/news_intelligence/phase2_review.md`
- `scripts/overnight/news_cluster.py`
- `scripts/overnight/news_diagnostics.py`
- `scripts/overnight/news_relevance.py`
- `scripts/overnight/news_sources.py`
- `tests/test_news_intelligence.py`

`git diff --name-only` against `.github/`, `.cursor/`, `docs/ACP_ONE_SHOT_AUTHORITY.md`, `scripts/market_watch_launch/`, `scripts/overnight/scheduled_output.py`, `scripts/overnight/publish.py`, `scripts/apply_overnight_news_refresh.py`, `scripts/sync_news_summary.py`, and `data/overnight/accepted_public_news.json` is empty. Those paths are not present as untracked files either.

`scripts/overnight/accepted_news.py` and `scripts/overnight/assemble.py` are modified. They are outside that forbidden set.

A scan of the tracked diff and the new `scripts/overnight/news_*.py` modules found no API keys, bearer tokens, private keys, or credential assignments. The only token hits are market-token helpers. `DISCOVERY_USER_AGENT` in `scripts/overnight/news_sources.py` is a public User-Agent string.

## 2. Receipt schema and partial

`scripts/overnight/live_news.py` builds every receipt in `_receipt` (lines 175–193). The dict is exactly:

`source`, `checked_at`, `status`, `candidate_count`, `result_count`, `failure`, `surface`

Offline skipped receipts and live ok/failed receipts all go through that helper. A live probe with the Hormuz Bing fixture and the Reuters sitemap fixture produced 11 receipts and zero dicts whose key set differed. Offline produced the same 11 sources, each `skipped`, same seven keys.

`partial` is computed only from `REQUIRED_SOURCES` (`bloomberg`, `reuters`):

```345:348:scripts/overnight/live_news.py
    statuses = {r["source"]: r["status"] for r in receipts if r["source"] in REQUIRED_SOURCES}
    partial = (
        statuses.get("bloomberg") == "failed" and statuses.get("reuters") == "ok"
    ) or (statuses.get("reuters") == "failed" and statuses.get("bloomberg") == "ok")
```

`bloomberg_credit`, `bloomberg_equity`, `reuters_credit`, and the six official source ids are not in that set. In the probe, all six official surfaces failed and `partial` stayed `False` while `bloomberg` and `reuters` were `ok`.

The receipt list is longer than the old two-wire list (one row per `discovery_surfaces()` entry, bloomberg then reuters then the rest). That is more receipts, not more keys on a receipt.

## 3. Non-Bing / non-Reuters raise

`acquire_current_news` fetches inside a per-surface `try` (`scripts/overnight/live_news.py` lines 281–333). `Exception` becomes one `failed` receipt (`candidate_count` 0, `result_count` 0, `failure` set to `str(exc)`, `surface` set to that URL). The loop continues. The handler does not re-raise.

Official surfaces are the non-Bing, non-Reuters URLs in `discovery_surfaces()`: `fed_monetary`, `boc_press`, `rba_media`, `ecb_press`, `boj_whatsnew`, `boe_news`.

Probe fetcher: Bing URLs returned the locked Hormuz RSS, `reuters.com` returned the locked sitemap, every other URL raised `RuntimeError`. Result:

- Failed only: those six official sources.
- Ok: `bloomberg`, `reuters`, `bloomberg_credit`, `bloomberg_equity`, `reuters_credit`.
- `partial` is `False`.
- The Hormuz Bloomberg URL is still in `candidates`.

`tests/test_live_news_acquisition.py` was re-run in this review: `python3 -m unittest tests.test_live_news_acquisition -v`, 16 tests, OK (2.149s). `_news_fetcher` in that file raises `RuntimeError` on any URL that is not Bing and not Reuters, and the collect tests in that file use it. They passed with the official surfaces present.

## 4. Return keys

Both functions still exist.

`acquire_current_news` still returns `mode`, `cutoff`, `partial`, `receipts`, and `candidates` on the live and offline paths (`live_news.py` lines 267–273 and 350–357). The live path adds `story_drops`. Offline does not. Extra keys are allowed; the prior keys are present.

`merge_live_news` still exists in `scripts/overnight/news_cluster.py` (lines 287–293) and is re-exported from `live_news.py`. It returns `cluster_and_rank`, which still has `items` and `research_supplement` and adds `diagnostics_rows`. The probe confirmed those three keys. The keyword signature is still `baseline`, `live_candidates`, `when`.

## 5. Shadow script

`scripts/live_news_discovery_smoke.py` calls `acquire_current_news`. With `--report` it also calls `merge_live_news`, `build_report`, and `write_report`. It does not call `collect`, `assemble`, or `launch`. Those names are absent from the file. `news_cluster.py` does not call `collect_inputs`, `assemble_dataset`, or `launch`.

## 6. Diagnostics stages

`scripts/overnight/news_diagnostics.py` defines four distinct stage strings and four distinct count keys: `discovery_failure`, `relevance_rejection`, `presentation_suppression`, `shown` (lines 13–23).

`safety_ceiling` is not `presentation_suppression`.

- The ceiling drop is written as `stage="discovery_failure"`, `reason="safety_ceiling"` in `_apply_recall_and_ceiling` (`live_news.py` lines 232–237).
- `_extra_row_stories` forces `reason == "safety_ceiling"` to `discovery_failure` before counting (lines 85–86).
- A merge row tagged `presentation_suppression` with reason `safety_ceiling` is skipped, not counted in that bucket (lines 99–100). `news_cluster.py` does not emit `safety_ceiling`.

Probe: 65 recall-passing rows on one source kept 60 and dropped 5, all with stage `discovery_failure`. The shadow report counted `discovery_failure: 5` and `presentation_suppression: 0`.

## 7. Official raise versus overnight collect

`collect_inputs` does not wrap the live acquisition (`scripts/overnight/collect.py` lines 294–302). An exception that left `acquire_current_news` would fail the collect. An official feed raise does not leave it.

The same probe fetcher was passed as `news_fetcher` to `collect_inputs` (`offline=False`). Collect returned a snapshot. `families.news.acquisition.partial` was `False`. The six official receipts were `failed`. The Hormuz URL was still in `families.news.items`.

There is no second fetch of those official URLs on the collect path. `news_fetcher` is used only as the `acquire_current_news` fetcher.

## Residual notes (not MATERIAL)

These do not meet the MATERIAL bar (ACP/CI/credential edit, receipt-schema break, or one surface exception aborting acquire).

- Official failures are stored on `families.news.acquisition.receipts`. They are copied into `news_notes` only when `partial` is true, or when every receipt failed (`collect.py` lines 309–346). With both wires `ok`, the probe notes did not mention the six official failures.
- `any_ok` is any receipt with status `ok`, not only bloomberg/reuters. A successful official surface can therefore take the merge path when both wires failed. The raise path does not do that: a raised official surface is `failed` and does not by itself set `any_ok`.
- A merge diagnostic row that is already labeled `presentation_suppression` / `safety_ceiling` is dropped from the shadow report rather than rewritten to `discovery_failure`. The live ceiling path does not emit that pair; it records `discovery_failure` directly.
