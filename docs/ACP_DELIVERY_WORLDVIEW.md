# ACP delivery: ChatGPT PM worldview memory

Control-plane issue: https://github.com/McCabeAI/agent-control-plane/issues/404

Target: `McCabeAI/market-watch-public-dashboard`

Branch: `cursor/build-chatgpt-pm-evolving-macro-worldview-memory-atop-market-watch-grok-4-7-composer-2-5-only-b405`

The full commit SHA is the pull-request head that contains this file. It is printed in the agent report after `git rev-parse HEAD`. This document does not invent a SHA before that commit exists.

## What landed

Persistent, revisable macro worldview for the ChatGPT PM, stored inside the existing research tree so the native `[chatgpt-research-memory]` workflow commits it and nothing else.

- `data/trading/pm/chatgpt/research/worldview/state.json` — current global view, six core countries, expandable watchlist, beliefs.
- `worldview/archive/` — append-only revision snapshots.
- `worldview/changes/` — what changed, what did not, why, contrary evidence, implications.
- `index.json` `worldview` block, covered by `research_sha256` `c5f6db2b33bba70a8632ed8a652c9dfc539fed584a7f0ea8f9730a530d1b9565`.
- Schema: `data/pm/schema/chatgpt_worldview.v1.json` and extended `chatgpt_research.v1.json` actions `worldview_patch` and `worldview_review`.
- CLI: `retrieve` includes the compact `worldview` bundle; `show-worldview`, `suggest-worldview`, `seed-worldview`.
- Operating doc: `docs/CHATGPT_WORLDVIEW_V1.md`. Cold start in `docs/CHATGPT_RESEARCH_MEMORY_V1.md` loads worldview before the book.

Seed `rev-worldview-0001` / `wvc-0001` is provisional, `acceptance: awaiting_pm`, `claims.learned_edge: false`. Six Market Watch temperature lines are reused. Derived meeting-price levels are excluded. Iran, Ukraine, and Brazil are retained with `insufficient_authorized_current_evidence` where the frozen packet does not support a view. The watchlist is a list, not a fixed set of three topics.

## Validation

`PYTHONPATH=. python3 -m unittest tests.test_chatgpt_worldview tests.test_chatgpt_research_memory tests.test_chatgpt_research_cold_start -q`

Result after the correction cycle: `Ran 23 tests in 0.664s` — `OK`.

Covered: six-country score lineage, meeting-level exclusion, offline socket guard, path escape, seed collision, patch and review clocks, replay and stale conflict, confidence drop without a new statement, missing-observation retention, unauthored fact rejection, watchlist expansion, bundle cap, and native `apply-from-env` isolation. Existing hypotheses and the 16-lesson record stay in place. Books and other seats are not in the diff.

## Independent verifier

Two read-only Grok 4.7 High reviews (`grok-4.7-high`). The first returned PASS with three residuals. The parent corrected the regime sentence so it matches the labor filter, rejected `http:` and `https:` evidence refs, and added a second trim pass plus sorted `watchlist_ids`. The second review returned PASS. The same 23 tests passed in that review.

## Model accounting

- Parent implementation and integration: this Grok 4.7 session.
- Independent verifier invocations: 2, model handle `grok-4.7-high`.
- Composer 2.5 invocations: 0.

The requested split (Composer 2.5 for storage, retrieval, and seed) was not used. The parent wrote those files so the seed stayed tied to the frozen packet and the existing research CLI. The repository hook allowed the `grok-4.7-high` verifier calls in this run. No other model family was invoked. Counts above are the calls this session made. They are not token totals.

## Limitations

- `suggest-worldview` reads only the frozen file `data/overnight/runs/overnight-20261106/reviews/review-001/evidence_snapshot.json`. It checks file sha256, packet sha256, and git blob. It does not compare that file to a later HEAD.
- A pathological bundle can still exceed 48,000 characters. The two-pass trim shortens readings, watch text, and change history. It does not cut `links_to` or the active-driver list.
- `runtime_autoload` is false. A fresh ChatGPT session does not remember this state until someone runs `retrieve`.
- No merge and no deploy. The seed is not a production memory apply.
