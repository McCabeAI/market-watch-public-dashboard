OVERALL: PASS

Independent recomputation from `evidence_snapshot.json` (content pin `0bc766c9…`) and `data/pm/books/latest.json` (`pms.chatgpt` only). Author Python modules were not imported.

**Bounded recheck (2026-11-05):** After `scenario_book.py` `alternative_uz_half` repair and rerun, check **E** was re-read from `scenario_results.json` / `scenario_results.md` only. Scenarios **A/B/C** MTMs unchanged. Git write boundary unchanged.

**Failed check IDs:** (none)

---

## Source integrity (SRC1)

| Check | Status | Result |
| --- | --- | --- |
| Canonical `packet_sha256` | PASS | `json.dumps` without `packet_sha256`, `indent=2`, `sort_keys=True`, trailing newline → `0bc766c948f4f88f81ea6e28bc00ad0a67e09ee5605b23b47cb69b039f415b10`; field matches. |
| Raw file SHA256 | PASS (recorded) | `13a1b1ca0fb89f4030f427f4106199ab8087894e478db8e980e1cc1d050f2744` (includes digest field). |
| Git blob | PASS | `git hash-object` → `16a74cdf5149e3fa8a9211fa2559b9ba9fc8f2ad`. |
| Freeze `as_of` | PASS | `2026-11-05T04:53:53.458055-05:00` present. |
| `market_state.generated_at` | PASS | `2026-11-05T10:17:36Z` present (dual clocks noted, not corruption). |

---

## A — Book identity

| Item | Expected | Computed |
| --- | ---: | ---: |
| Unrealized P&L | 640625 | `250_000_000 × (3.4 − 3.14375) / 100` = **640625** (matches stored `640625.0`) |
| Side | long = **receive** | stored `long`; yield up is a loss for this book |
| DV01 convention | 25000 USD per bp (strip average) | consistent with scenario MTM formula |

**Status: PASS**

---

## B — Unit signs

| Case | Expected | Computed |
| --- | ---: | ---: |
| Payer +20 bp, 1000×25 USD | +500000 | 500000 |
| Receive same DV01 +20 bp | −500000 | −500000 |
| Receive 25000 USD/bp, 3.160→3.155 | +12500 | 12500 |
| Receive parallel +20 bp | −500000 | 25000×(−20) |
| Receive parallel −20 bp | +500000 | 25000×20 |
| Receive parallel +100 bp | −2500000 | 25000×(−100) |

**Status: PASS**

---

## C — Snapshot CORRA strip

From `tradable_rate_curves.curves.CORRA.contracts` (100 − price):

| Code | Implied % |
| --- | ---: |
| CRAH27 | 2.93 |
| CRAM27 | 3.075 |
| CRAU27 | 3.185 |
| CRAZ27 | 3.265 |
| **Average** | **3.11375** |

CORRA fixing: **2.53** (`as_of` **2026-11-03**). Average minus fixing = **58.375 bp** (informational; not the forward mispricing under scenario A).

**Status: PASS**

---

## D — Scenario MTM (existing receive)

Formula: `usd = 25000 × (3.11375 − scenario_avg) × 100`

| Scenario | Assumption avg | Computed MTM | `scenario_results.json` |
| --- | ---: | ---: | ---: |
| A | 2.75 | **909375** | 909375.0 |
| B | 3.2625 | **−371875** | −371875.0000000004 |
| C | 2.9625 | **378125** | 378125.0000000003 |

**Status: PASS**

---

## E — U/Z half-DV01 trap

U/Z only: CRAU27 3.185, CRAZ27 3.265 → average **3.225**. Gap vs assumption A (2.75) = **47.5 bp**. Half strip DV01 **12500 USD/bp**.

| Quantity | Value |
| --- | ---: |
| Independent recompute | **593750** (= 12500 × 47.5) |
| Published `under_A_mtm_usd_half_dv01` | **593750.0000000001** (`scenario_results.json`) |
| `scenario_results.md` U/Z dollar MTM | **593750.00** (no **454687.50** in markdown) |
| Parallel +20 bp on half DV01 | **−250000** (unchanged) |

`alternative_uz_half` prices `receive_mtm_usd(half_dv01, uz_avg, 2.75)`, not the four-leg average on half DV01. Qualitative trap remains: U/Z-under-A **593750** < full-strip **909375** while U/Z gap **47.5 bp** > four-leg **36.375 bp**.

**Status: PASS** (`E.uz_under_A_mtm`)

---

## F — SOFR standalone receive (25000 USD/bp)

SR3H7/M7/U7/Z7 implied average **4.45375**. Scenario A (4.20): gap 25.375 bp → MTM **+634375**. Scenario C: gap 0 → MTM **0**. Sign is **receive** (yield down = gain).

**Status: PASS**

---

## G — AONIA pay stress

Six months Nov 2027–Apr 2028 futures average **4.656666…**. Lots for 25000 AUD/bp: `25000 / (6 × 24.66)` = **168.964585…** (IEEE; prompt’s 168.96188 is the same formula rounded). Pay +20 bp parallel on 25000 AUD/bp → **+500000 AUD** (yield up = gain for payer); published matches.

**Status: PASS**

---

## H — Empirical (independent panel)

Inner-join exact dates on `opportunities.series` histories; log return `100×ln(S_t/S_{t−1})`; S2 and S3 h=1 recomputed without author code. All pairwise |Δr| ≤ 0.002 vs `empirical/results.json`.

Highlights:

| Pair | S3 h=1 r (recomputed) | N | Last date |
| --- | ---: | ---: | --- |
| USDCAD | **0.5082** | 114 | **2026-11-03** (2026-11-04 election day not in aligned panel) |

NZ_2Y length **10**; no NOK 2Y series; five pairs reported separately (not pooled).

**Status: PASS**

---

## I — FX / oil spot (series history)

Simple percent `100×(P4/P3−1)` from stored closes:

| Series | 2026-11-03 | 2026-11-04 | Simple % |
| --- | ---: | ---: | ---: |
| WTI | 96.09 | 88.12 | −8.29 |
| BRENT | 103.60 | 94.62 | −8.67 |
| EURUSD | 1.1179 | 1.1267 | +0.79 |
| USDCAD | 1.3975 | 1.3935 | −0.29 (CAD stronger) |
| CADNOK | 6.6047 | 6.6219 | +0.26 (CAD stronger vs NOK) |
| USDNOK | 9.2303 | 9.2278 | −0.03 |

**Status: PASS**

---

## J — Time alignment

| Rule | Status |
| --- | --- |
| AU_2Y last **2026-10-28**; AUDUSD/AUDCAD panels end **2026-10-28** | PASS |
| CA_2Y **2026-11-03**; US_2Y **2026-11-04** | PASS |
| US_REAL10 (2026-11-03) vs US_BE10 (2026-11-04); memos disclaim same-day real-yield decomposition | PASS |

**Status: PASS**

---

## K — Economic leaps (memo text)

All leap checks **PASS**: 58.375 bp not called edge; gaps not EV; oil not “historically cheap”; no new FX; SOFR/AONIA not book add; empirical not a trading signal; CADNOK close not forecast score; scenario A **Assumption: 2.75** labeled.

**Status: PASS**

---

## L — Write boundary

`git status --short --untracked-files=all`: only paths under `docs/research/chatgpt/2026-11-05-election-repricing/` (including this verification folder). No changes outside research tree.

**Status: PASS**

---

## Summary

All checks **A–L** pass on the frozen evidence and published research outputs. Check **E** passes after the scenario rerun: U/Z-under-A MTM is **593750** (12500 × 47.5 bp), and scenario markdown no longer cites **454687.50** as the U/Z dollar MTM.
