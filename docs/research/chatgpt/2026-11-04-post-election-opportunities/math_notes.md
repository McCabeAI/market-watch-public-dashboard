# Math notes — post-election opportunities (evidence cycle 2026-11-04)

**Written:** 2026-11-05  
**Role:** Composer 2.5 math/data extraction only; no portfolio recommendation.

## Evidence provenance

| Item | Value |
|------|--------|
| Git commit (market + book) | `612666a21e621e6bb437802cb48ace011f181b7b` |
| Review | `overnight-20261104` / `review-001`, status **accepted** |
| `packet_sha256` (review field) | `d1a793edb498fd7c866b54038d6db9cc1139c91301f5b2c8fc20729d8933430f` |
| `frozen_at` / cutoff | `2026-11-04T05:35:22.541505-05:00` |
| Snapshot blob SHA-256 | `f4dad4a2657be919f6b6e991761bc260ee93a5527a004b5c7f9f9af8f3041241` |
| `market_state.generated_at` | `2026-11-04T10:52:31Z` |
| `families.market_state.digest` | `a4a28373c5db64e71f860f73ba0267502bcba92bf32fe09f32ca300068ce2ae9` |

All market fields are loaded with `git show <commit>:<path>` inside `extract_frozen.py`. Working-tree `data/` files and `data/pm/review_packets` were not read.

ChatGPT position economics come only from `git show …:data/pm/books/latest.json` → `pms.chatgpt`.

Prior research conventions (re-derived, not copied): commit `250bf6f4a6d00e1f115fc6305d0a998a632f9651` — `calc_contracts.py`, `calc_results.json`, `2026-11-04-corra-expression-review.md`.

## How to rerun

From repository root:

```bash
python3 docs/research/chatgpt/2026-11-04-post-election-opportunities/extract_frozen.py
python3 docs/research/chatgpt/2026-11-04-post-election-opportunities/calc_portfolio_math.py
```

Outputs: `frozen_extract.json`, `calc_results.json` in the same directory.

## Paper accounting vs exchange futures economics

- **Paper DV01 (book):** `notional_usd × 0.0001` → **$25,000 per bp** at **$250m** notional. This matches the book’s 100 bp shock ≈ 1% of notional framing. It is **not** the DV01 of a single 3-month STIR contract.
- **CME SR3:** **$25 per bp per lot** — **ASSUMPTION** from prior `calc_contracts.py`; not stated in the pinned snapshot.
- **CRA:** **C$25 per bp per lot**, **C$1,000,000** face per lot — **ASSUMPTION** from prior research; USD leg DV01 = `25 × (1/USDCAD)` with **USDCAD** = CAD per USD from frozen FX.
- **ASX 30-day interbank (AONIA):** prior research **A$24.66 per bp**; calc also shows unrounded `3_000_000 × 0.0001 × 30/365` for transparency — **not** used as exchange truth unless snapshot specifies it (it does not).
- **TONA:** No JPY bpv in snapshot → futures lot counts for TONA are **null / conditional**; no hypothesis invented.

**Financing:** `risk_capital × 0.0395 × days/360` on **100 bp paper DV01** (rates) or **1% shock risk capital** (FX unit). Label: evidenced book convention (SOFR charged on standard shock loss), **not** exchange initial margin or futures variation margin.

## Quarter vs month

- CORRA / SOFR strips use **3-month quarterly** contracts (2027 H/M/U/Z).
- AONIA comparisons use **1-month** contracts; Mar–May and Sep–Nov windows are **simple averages of listed months** (label proxies), not compounded IMM quarters.
- CORRA 1m path is extracted from `policy_paths.CA.contracts_1m` separately from the 3m strip.

## Assumptions in calc

1. **One-quarter unchanged-curve roll:** Each 2027 leg rate is compared to the mapped prior-quarter contract (CORRA: H←CRAZ26, M←CRAH27, U←CRAM27, Z←CRAU27; SOFR: H←SR3Z6, M←SR3H7, U←SR3M7, Z←SR3U7). Pay-H / receive-Z P&L per leg DV01 = `slide_H − slide_Z` (≈ **−13.5 bp** on pinned inputs — scenario label, **not** guaranteed accrual).
2. **Equal-lot CRA sizing:** Target parallel USD DV01 split evenly across four legs; lots **floored** toward zero (prior floored **349** at $25k/bp parallel).
3. **Scenario shocks:** Named assumption paths only; de-escalation / escalation include optional FX spot moves on **$250m** notional unit where specified; WTI not in rates book.
4. **Cross-market cash spreads:** Foreign minus US at each country’s own tenor `as_of`. **AU 2Y/10Y** flagged **stale-mismatched** when AU `2026-10-28` vs US `2026-11-03`.

## Missing or absent inputs (snapshot)

- **NZ cash yields:** unavailable (RBNZ B2 blocked); tenor fields **null** preserved.
- **ESTR futures:** empty `contracts`, `status: unavailable` with error string preserved.
- **US CPI headline / core numeric levels:** not in `macro_hard.components[].provenance/extra` or `extra.score_lineage` for those catalog ids → **value null** with looked paths recorded; CA/AU/US labor and CA/AU/US core PCE where available use **`families.macro_hard.temperature_scores`** supplement (documented separately from component provenance).
- **Dedicated TIPS / inflation breakeven time series:** no `breakeven` / `TIPS` / `real_yield` / `real_rate` **keys** in snapshot JSON; string hits include **US 10Y breakeven** / **real yield** **labels** under `cross_assets.series` and `opportunities.series` only.
- **€STR benchmark rate:** ESTR block has no fixing in pinned evidence (unavailable curve family).

## Article context (unsynchronized)

`article_context` in `frozen_extract.json` is **not** merged into frozen marks. Gaps vs frozen UST cash yields, compact WTI/Brent, and narrative vs quote-table 2Y/30Y are labeled **UNSYNCHRONIZED** in `article_context_gaps`.

## Prior research check (strip mean)

Re-derived equal-weight 2027 CORRA mean from pinned snapshot should match prior `calc_results.json` **section_1** mean (**3.155**); any delta is reported in `calc_results.json` → `prior_vs_rederived_strip_mean_delta_bp`.

## Files owned by this worker

- `extract_frozen.py` / `frozen_extract.json`
- `calc_portfolio_math.py` / `calc_results.json`
- `math_notes.md` (this file)
