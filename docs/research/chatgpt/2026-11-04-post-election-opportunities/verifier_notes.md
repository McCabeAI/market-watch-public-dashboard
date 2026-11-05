# Independent verifier notes — post-election opportunities

**Written:** 2026-11-05  
**Role:** Independent verifier (did not author rates/FX memos, extractor, `calc_portfolio_math.py`, or integrator)  
**Model:** Composer 2.5 (standard)

## Method

Recomputed arithmetic from `frozen_extract.json` and constants parsed from `calc_results.json` / `portfolio_scenarios.json`. Provenance cross-checked via `git show 612666a21e621e6bb437802cb48ace011f181b7b:…` (no working-tree `data/` reads for marks). Did **not** import `scenario_book.py` or `calc_portfolio_math.py`. Automated checks: `verify_independent.py`.

## Check table

| # | Topic | Result | Independent numbers |
|---|--------|--------|---------------------|
| 1 | Provenance | PASS | Packet SHA `d1a793…3430f`; cutoff `2026-11-04T05:35:22.541505-05:00`; `market_state_generated_at` `2026-11-04T10:52:31Z`; review `accepted`; evidence blob SHA `f4dad4…241` matches `git show` rehash and `frozen_extract.meta.snapshot_file_sha256`. |
| 2 | CORRA strip / book mark | PASS | H/M/U/Z **2.97 / 3.115 / 3.225 / 3.31**; mean **3.155**; vs cash 2.54 **+61.5 bp**; mark 3.16 **+0.5 bp** vs mean; paper gap P&L **−$12,500** at $25k/bp (stored unrealized **$600k** left unchanged). |
| 3 | USDCAD / CRA lots | PASS | USDCAD **1.397531…** (CAD/USD); USD/bp/lot **≈17.889**; **349** lots/leg → parallel **$24,972.61/bp** (4 legs), **$12,486.31/bp** (U+Z only). |
| 4 | SR3 bpv | PASS | **$25/bp/lot** → 200 lots **$5,000/bp**, 1000 lots **$25,000/bp**. |
| 5 | One-quarter roll (assumption) | PASS | Slides H/M/U/Z **−22 / −14.5 / −11 / −8.5 bp**; pay-H minus receive-Z **−13.5 bp**/leg DV01; equal-weight receive avg slide **14.0 bp** × **$25,000** = **$350,000** (label: assumption, not accrual). |
| 6 | Financing | PASS | Nominal **$2.5m × 3.95% × 30/360 = $8,229.1666…**; `portfolio_scenarios.json` uses **ACT/360** on **100 × achieved parallel DV01** → R1 **$8,220.15** (matches recomputed from R1 risk capital within **$1**). |
| 7 | Sign / matched +20bp | PASS | Receive **−DV01×shock**; pay **+DV01×shock**; at achieved CRA DV01 +20bp **−$499,452.22 / +$499,452.22 → ~$0**; `calc_results.json` `futures_pay_4leg_sr3_matched_usd` **−$500,000** (known bug); integrator `self_checks.matched_pay_receive_common_plus_20` **pass**. |
| 8 | Article vs freeze | PASS | Narrative vs UST gaps **−5.2 / −3.7 / −2.7 bp**; oil ratios **88/WTI−1**, **94/Brent−1**; all **UNSYNCHRONIZED** in extract; scenario P&L uses only labeled **ASSUMPTION** rows, not article yields as fills. |
| 9 | Quote-table vs narrative | PASS | 2Y **4.577 vs 4.573** (~**−0.4 bp**); 30Y **5.29 vs 5.293** (~**+0.3 bp**); integrator explicitly warns quote-table is **not** the frozen yield. |
| 10 | Flat rival | PASS | Proposed **R0**; R0/R3 scenario **market_pnl_usd = 0**; close does not book **$600k** unrealized as forward edge. |
| 11 | R1 scenario cross-check | PASS | R1 `common_plus_20` **−$499,452.22** matches recomputed receive P&L. |

## Material issues (non-failing)

1. **`calc_portfolio_math.py` pay-leg sign:** `common_plus_20` records SR3 matched pay **−$500,000** (same sign as receive). Documented in integrator and `portfolio_scenarios.json` `self_checks`; **`scenario_book.py` / portfolio scenarios use corrected pay sign** for matched-book audit.
2. **`math_notes.md` vs snapshot on €STR:** Notes say the €STR benchmark fixing is absent; pinned `evidence_snapshot.json` still carries **€STR cash 2.445** under `policy_paths.countries.EA.benchmark` and `tradable_rate_curves.curves.ESTR.benchmark`. Extract’s top-level `benchmarks.ESTR.rate` is null (FST3 futures empty). **Documentation miss only** — no euro futures trade is promoted.
3. **Roll scenario dollars:** Paper equal-weight roll **$350,000**; R1 `one_quarter_unchanged_curve_roll_ASSUMPTION` market P&L **$349,616.55** (lot-floored futures path from calc) — consistent with integrator using futures receive math, not a silent fusion with article marks.
4. **Financing display:** Readers comparing to **$8,229.17** on nominal **$2.5m** risk capital should note R1 uses **$2,497,261** risk capital from achieved DV01 → **$8,220.15**.

## Economic review (judgment / gaps — not arithmetic failures)

**Diversification:** The pack does **not** claim AUDNZD (or any FX leg) **hedges** the CORRA receive; FX ideas are **conditional**, **at most one** leg, and explicitly **not additive** with the rates book. CORRA + SR3 receive would be **same sign** on parallel selloff — integrator **rejects** DV01-matched SR3 “hedge.”

**R2 (U/Z only):** Rejected on thesis grounds — **halving DV01** by dropping H/M is **not** treated as a better expression; memo states this.

**Roll / article scenarios:** Unchanged-curve roll and “article Treasury −5bp repeated in CRA/SR3” are **labeled ASSUMPTION** paths, not expected value or synchronized marks.

**Reference rates:** ECB-style spots in the FX memo are **reference/fixing family**, not tradable fills without stated conditions.

**Missing inputs (acknowledged in memos / math notes):** CRA open interest, FX forward points, post-election common marks, event probabilities, NZ cash yields, bond-futures DV01, exchange margin — still gaps for sizing live risk.

**Close (R0):** Choosing flat after **$600k** unrealized is **judgment**; scenario arithmetic supports **zero forward market P&L** on rivals R0/R3 and does not treat historical P&L as prospective edge.

**€STR / FST3:** Empty FST3 contract table does not invalidate the flat recommendation; cash **2.445** exists in snapshot policy paths if/when euro STIR is wired.

---

**VERDICT: PASS** (automated failure count **0**)
