# CORRA expression review — ChatGPT PM residual receive

**Position:** `pm-chatgpt-595561a1b90f` (trade `trd-pm-chatgpt-pm-chatgpt-595561a1b90f`). Existing seat. Research only. ChatGPT keeps the investment decision.

**Parent verdict:** **Reshape and reduce.** Keep a Canadian receive, shift it from the equal-weight March/June/September/December 2027 strip onto September and December 2027 only, and cut parallel DV01 about in half versus the current 250m duration-one book. Do not add. Do not replace the book with a DV01-neutral March/December flattener or with a DV01-matched SOFR or AONIA pay.

**Parent final review:** **APPROVE** this research artifact. The scenario engine matched an independent recompute (72 checks, 0 failures) after three documentation labels were corrected. Those corrections did not change scenario dollars except where a mis-specified realized-P&L identity was fixed to the stored book.

This note is retrospective. It was written on 2026-11-04 during this research execution, after the accepted review and after the November 4 trader submissions in that freeze. It is not a blind morning forecast, and it does not backdate the authorship.

## Recommendation

| Rank | Expression | Why it is here |
|------|------------|----------------|
| 1 | **Reshape and reduce:** receive CRAU27 and CRAZ27 only, 349 lots each | The premium versus cash is largest in the back (+68.5 bp and +77 bp). Near-term evidence is the part that can validate higher rates. Parallel risk falls by about half. One-quarter roll stays positive. |
| 2 | Retain the equal-weight 250m receive, no add | Preserves the full level disagreement and the best identified roll. It also keeps receiving March, which is where a further near-term hike would show up and where the opposing evidence sits. |
| 3 | Proportional reduce of all four legs | Same mix as today, smaller. Use this if the view is that every 2027 quarter is equally too high. |
| 4 | DV01-neutral pay March / receive December | Zero parallel exposure. One-quarter unchanged-curve roll is a **loss** of about 13.5 bp of leg DV01. It keeps the slope bet and gives up the level edge. |
| 5 | Receive the CORRA strip versus a DV01-matched SOFR pay | Offsets a common selloff and gives up most of the Canada roll and the common rally. US inflation evidence in this freeze is stale. |
| 6 | Receive deferred CORRA versus an AONIA pay | Monthly versus quarterly, thin or missing open interest in the back, and Australia’s trimmed-mean inflation is firmer. |
| — | Close the residual | The strip is 3.155, not back at 3.35–3.40, and September underlying inflation is still 1.85. Closing is the response if the falsifier below is met. |
| — | Fresh 250m equal-weight from flat | The 3.40 entry edge is already marked. A new equal-weight position at today’s size does not clear the hurdle on this packet. |

**Mechanism.** The book is short the market’s 2027 Canadian policy path: quarter-average CORRA futures sit 43 to 77 bp above the 2.54 CORRA fixing. The support for fading that path is September’s trim/median average at 1.85 and a cooling labor mix. The opposition is September headline CPI at 3.09, rising CPI-major breadth, firm deferred Brent versus the July MPR oil assumption, and the PM’s own November 3 statement that the Bank of Canada already hiked. That opposition bears more heavily on the front of the strip than on December 2027.

**Market-implied path.** One-month CORRA futures, which stop in February 2027, go from 2.515 in November (2.5 bp through the fixing) to 2.785 in February (+24.5 bp). The three-month March 2027 contract is 2.97 and December 2027 is 3.31. Those are compounded-quarter rates on a 90/360 basis-point value, not meeting rates, and futures minus cash is not accrued carry.

**Horizon.** Over 1–3 months the P&L is repricing plus, at most, one quarter of roll if the tenor curve is unchanged. Over 3–6 months the December 2027 reference quarter has still not started. No second quarter of roll is identified from this single curve.

**Falsifier.** Close or cut further if underlying inflation, wages, employment, and Bank of Canada communication substantiate more hikes, especially if September and December 2027 back up toward the mid-3.30s to 3.40. A headline or oil jump without that confirmation was already the PM’s own stated non-falsifier. A March-only selloff is the outcome this reshape is built to carry less of.

**Strongest case against this rank.** The front contract has the largest one-quarter slide (−22 bp, versus −8.5 bp on December). If every 2027 quarter is equally too high, equal weight has the better roll and the reshape leaves that carry behind (about $228k on the 349-lot book over the assumed quarter). Halving DV01 also halves the gain if the whole strip rallies. Labor and the 1.85 trim/median average are arguments about the whole path, not only the back.

## Provenance

Analytical inputs are git commit `612666a21e621e6bb437802cb48ace011f181b7b` only. Later commits on this branch were not used as market evidence.

| Object | Value |
|--------|--------|
| Accepted review | `overnight-20261104` / `review-001`, status accepted |
| Stated cutoff | `2026-11-04T05:35:22.541505-05:00` |
| Packet SHA-256 | `d1a793edb498fd7c866b54038d6db9cc1139c91301f5b2c8fc20729d8933430f` |
| Agent packet SHA-256 | `a524f07cbfdfafdb44d016a2fd9c6abd31aeae6ab261bda0b8beab172ab571a2` |
| Starting PM books SHA-256 | `4c587999e9a0c375b30844c2463c5a5c059b6103f8c640d33f92e865bcc25716` |
| Market-state digest | `a4a28373c5db64e71f860f73ba0267502bcba92bf32fe09f32ca300068ce2ae9` |
| Market-state `generated_at` | `2026-11-04T10:52:31Z` |

**Ordering.** The stated cutoff is 10:35:22Z. The assigned market state was generated at 10:52:31Z, about seventeen minutes later. This review uses that assigned snapshot and flags the gap. It does not repair it. The composite packet `data/pm/review_packets/chatgpt/prp-chatgpt-overnight-20261104-review-001.json` has `market_state.generated_at` of `2026-11-04T12:12:27Z`. Its later rates were not read.

Contract timestamps inside the snapshot are earlier than both clocks: CORRA fixing 2026-11-02, SOFR futures and FX 2026-11-03, AONIA benchmark dated 03-Nov-2026. The stored book mark is 3.16 as of `2026-11-03T14:35:29Z`. Research arithmetic does not replace that mark or the book’s net P&L.

Reproduction inputs, the calculator, Composer notes, and the verifier live under `docs/research/chatgpt/2026-11-04-corra-expression/`.

## Observed values

**CORRA three-month futures** (Montréal Exchange CRA, implied rate = 100 − price). Cash fixing 2.54 on 2026-11-02.

| Contract | Rate | Versus cash |
|----------|-----:|------------:|
| CRAH27 2027-03 | 2.970 | +43.0 bp |
| CRAM27 2027-06 | 3.115 | +57.5 bp |
| CRAU27 2027-09 | 3.225 | +68.5 bp |
| CRAZ27 2027-12 | 3.310 | +77.0 bp |
| Equal-weight mean | 3.155 | +61.5 bp |
| December minus March | | +34.0 bp |

One-month CORRA (COA), the near-term object, runs only through February 2027: November 2.515 (−2.5 bp), December 2.605 (+6.5), January 2.655 (+11.5), February 2.785 (+24.5). Open interest and volume on the CRA strip are null in this freeze. The strip is paper-markable. Exchange size is not evidenced.

**SOFR three-month futures** (CME SR3), observation date 2026-11-03. Cash SOFR 3.95 on 2026-11-02. Embedded cash history runs 2026-06-25 (3.64) through 2026-11-02 (3.95). That history is not a strategy backtest.

| Contract | Rate | Versus cash | SOFR minus CORRA |
|----------|-----:|------------:|-----------------:|
| SR3H7 2027-03 | 4.365 | +41.5 bp | 139.5 bp |
| SR3M7 2027-06 | 4.495 | +54.5 bp | 138.0 bp |
| SR3U7 2027-09 | 4.535 | +58.5 bp | 131.0 bp |
| SR3Z7 2027-12 | 4.515 | +56.5 bp | 120.5 bp |
| Equal-weight mean | 4.4775 | +52.75 bp | 132.25 bp |
| December minus March | | +15.0 bp | Canada steeper by 19.0 bp |

SR3Z7 open interest is 1,536,682. The US strip is the executable leg. Canada’s premium versus its own cash exceeds the US premium versus its own cash by 8.75 bp on the equal-weight averages. That is a small relative gap next to the 61.5 bp absolute Canada premium.

**AONIA** cash 4.60 dated 03-Nov-2026. Contracts are one-month ASX 30-day interbank futures. A labeled proxy, not a compounded quarter, averages March/April/May 4.908, June/July/August 4.855, September/October/November 4.773, and December 2027/January 2028/February 2028 4.687. Single contract months: March 4.915 (open interest 400), June 4.885 (200), September 4.800 (null), December 4.710 (null). December versus AONIA cash is +11 bp. The back of this curve is not evidenced as executable.

**Book, unchanged.** Entry 3.40 on 2026-09-20 at 500m. Residual 250m after the 2026-11-03 reduce at mark 3.16. Side `long` on the futures-strip average means receive. Stored unrealized 600,000, realized 600,000, total 1,200,000, funding cost 24,555.56, net after funding 1,175,444.44, NAV 1,001,175,444.44. Risk capital 2,500,000 on a 100 bp rate shock. The November 3 journal mids were 2.96 / 3.12 / 3.235 / 3.325, average 3.16. Versus this snapshot the legs moved +1 / −0.5 / −1 / −1.5 bp. The average gap is 0.5 bp, about 12,500 dollars of unmarked paper P&L at 25,000 dollars per bp. The book was not remarked.

**Macro, with the series definition.** Canada underlying inflation 1.85 is the equal average of CPI-trim and CPI-median year-over-year for 2026-09 (released 2026-10-19), anchor 2.0. Headline all-items CPI year-over-year is 3.0928 for the same month. Unemployment 6.5 is the published rate for 2026-09 versus a 6.0 anchor; the release-date status on that labor block is `inherited_or_inconsistent`. Employment −11.6333 is the three-month mean change in thousands versus a +25k trend, not a percent. Wages 2.3382 are year-over-year versus a 3.0 anchor; the wage-component impulse is +3.78, so the level is cool and the latest print heated versus its own prior print. Labor dimension level 40.94, direction cooling. Activity level 49.61 with a large warming impulse; the scored GDP input is a two-quarter mean SAAR of 1.8196 for 2026-Q2 versus potential 1.8, and the three-month PMI mean is 48.73. Consumer level 57.03, coverage 0.75 because confidence is unobserved. Income 2.12 is 2026-Q2 quarter-on-quarter nominal (anchor 1.0). Spending 0.8 is 2026-Q2 quarter-on-quarter real (anchor 0.5). Retail 0.3277 is a three-month mean month-on-month nominal through 2026-08, essentially on its anchor. Those consumer prints are not a current boom.

Australia trimmed-mean year-over-year is 3.6 for 2026-09 versus a 2.5 target midpoint. Headline year-over-year is 4.3. The inflation dimension is warm. The stored unemployment transform is 4.7183; the calibration defines that transform as the published percent, and this note does not round it into a separate official print.

US core inflation in the score is 3.0478 on the three-month annualized month-on-month transform, reference period 2026-07, retrieved 2026-09-21. It is not a year-over-year print, and US source health for that block is carried forward. Unemployment 4.2 for 2026-09 sits on the 4.2 anchor. Wages 3.0245 are near the 3.0 anchor.

**Oil and prices, kept distinct.** Compact Brent `BZ=F` is 103.60 on 2026-11-03. WTI is 96.09 the same day. PRiMA’s December 2026 Brent contract is 117.64 observed 2026-10-30. Deferred December 2027 Brent is 84.88 on 2026-11-03, 14.88 dollars above the July 2026 MPR prose assumption of 70. December 2028 Brent is 77.38. September IPPI energy month-on-month is about +12.1 percent and RMPI crude about +14.4 percent. IPPI excluding energy is about +0.28 percent. RMPI excluding crude energy is slightly down and is not an import-price index. CPI breadth for 2026-09 is 5 of 8 majors with a positive NSA month-on-month change. PRiMA’s own summary is direction STABLE, strength low, front-shock label `parallel_upward_repricing`. The 2.75 “neutral midpoint” next to CORRA 2.54 is that proxy’s input. CORRA is the overnight fixing, not a Governing Council vote.

**Policy record.** The news family in this packet contains a Federal Reserve hold dated 2026-10-28. It does not contain a Bank of Canada decision record. The late-October hike is the PM’s 3 November journal and hypothesis revision 04. The missing common-ingest item is the official target for the overnight rate at that announcement: decision, effective date, and statement.

Sovereign yields are a different family and the position is locked to CORRA futures. Canada 2-year 3.26 on 2026-11-02 and US 2-year 4.61 on 2026-11-03 are a consistency check only (spread 135 bp, near the futures spreads). The official Canada curve in the snapshot is dated 2026-10-14 and is not used as the current path. CME positioning is unavailable. Trader sentences about CFTC Canadian-dollar positioning are not treated as facts. NZ rates are unavailable and do not drive this Canada position.

## Deterministic contract results

Conventions are copied from `scripts/rates/contract_economics.py` at the pinned commit. The script does not import the working tree, which has moved on.

| Contract | Local DV01 per bp | Day-count used for the basis-point value |
|----------|-------------------:|------------------------------------------|
| SR3 | 25 USD | 0.01% × 90/360 × 1,000,000 |
| CRA | 25 CAD | 0.01% × 90/360 × 1,000,000 |
| IB | 24.66 AUD published | Fixed 30/365 figure for every month. Unrounded 3,000,000 × 0.0001 × 30/365 = 24.6575 is not the valuation figure. The monthly average settlement period does not change this basis-point value in the module. |

USDCAD 1.3975310850702212 on 2026-11-03. USD per CAD = 0.7155475900915316, matching the snapshot’s analytics row. AUDUSD = 0.6983819578934215. CRA DV01 in USD is 17.8887 per lot. IB DV01 in USD is 17.2221 per lot. Exact IMM start and end dates, futures convexity, and margin schedules are absent.

**Paper engine versus real contracts.** The book values a 1 bp move in the equal-weight average at `250,000,000 × 0.0001 = 25,000` USD. A 100 bp shock is the stored 2,500,000 risk capital. Unrealized `250m × (3.40 − 3.16) / 100 = 600,000`. The closed slice was also 250m (half of the original 500m), so realized is the same 600,000. Stored funding and net-after-funding figures are left as book facts. Forward paper funding on the current risk capital at 3.95% ACT/360 is 24,961.81 for 91 days and 49,923.61 for 182 days. That charge is on risk capital, not on futures face.

Matching 25,000 USD of parallel DV01 with equal CRA lots floors to **349 contracts per expiry** (unrounded 349.38). Achieved DV01 is 24,972.61. Face is 349 million CAD per leg, about 249.7 million USD per leg, and about 999 million USD across four legs. The paper “250m notional” is one year of 90/360 risk. It lines up with about 250 million USD of face on each leg, not with 250 million USD of gross face. The live book has no `instrument_dv01` legs, so the canonical P&L remains the duration-one formula. A 1 percent move in USDCAD scales the USD value of CAD variation by about 1 percent. There is no quanto or convexity term in the inputs.

**Flattener, pay CRAH27 / receive CRAZ27.** Basis-point values match, so equal lots are equal DV01. Primary size, leg DV01 targeted at 25,000, floors to 1,397 lots and 24,990.50 USD per leg. A 1 bp parallel move is worth about zero. A 1 bp fall in December alone is worth about +24,990. The half-gross size (leg DV01 targeted at 12,500) is 698 lots. Under an unchanged tenor curve, March slides −22 bp and December slides −8.5 bp, so the spread widens by 13.5 bp and the flattener **loses** 13.5 × 24,990.50 = **337,371.74** USD. That is the carry identity of this expression on a one-quarter horizon.

**Cross market.** Receive 349 CRA versus pay 250 SR3 on each of the four expiries. Parallel DV01 is 24,972.61 against 25,000, so a common 25 bp selloff leaves a +684.73 residual rather than zero. One-quarter roll on that pair is **+127,741.55** USD, against **+349,616.55** on the CRA strip alone. Receive CRAZ27 versus pay the three AONIA months in the December window, DV01 split in thirds, is markable and not evidenced as executable. The roll row for that pair in the calculator moves only the CRA December leg, because no AONIA tenor slide was defined.

**September/December-only receive at the current per-leg size (349 lots).** Parallel DV01 falls to 12,486.31. Paper-style risk capital at a 100 bp shock would be about 1,248,631, and 91-day funding on that base at 3.95% ACT/360 would be about 12,467. One-quarter roll is **+121,741** USD. Keeping full 25,000 of parallel DV01 on September and December only takes 698 lots per leg, roll **+243,483**, and the same parallel loss as the current strip.

### Scenario P&L in USD

Shocks are assumptions. Positive bp means the implied rate rises. Dollars are rate P&L only. Funding is the separate line above, not subtracted here. Column (a) is the paper duration-one receive. Column (b) is 349 CRA lots on all four expiries. Column (c) is the 1,397-lot flattener. Column (d) is the DV01-matched CORRA receive versus SOFR pay. Column (e) is CRAZ27 versus the AONIA December-window pay. Column (f) is the recommended 349-lot September/December receive.

| Scenario | (a) | (b) | (c) | (d) | (e) | (f) |
|----------|----:|----:|----:|----:|----:|----:|
| All Canada +25, US +25, AONIA +25 | −625,000 | −624,315 | 0 | +685 | −892 | −312,158 |
| All −25 | +625,000 | +624,315 | 0 | −685 | +892 | +312,158 |
| Canada H +10, M 0, U −10, Z −20 | +125,000 | +124,863 | +749,715 | +124,863 | +499,810 | +187,295 |
| Canada H −10, M +5, U +10, Z +20 | −156,250 | −156,079 | −749,715 | −156,079 | −499,810 | −187,295 |
| Common +20 | −500,000 | −499,452 | 0 | +548 | −714 | −249,726 |
| Canada +25, US +5, AONIA +5 | −625,000 | −624,315 | 0 | −499,315 | −499,988 | −312,158 |
| Canada −30, US −15, AONIA −15 | +750,000 | +749,178 | 0 | +374,178 | +375,393 | +374,589 |
| One-quarter unchanged-curve slide | +350,000 | +349,617 | −337,372 | +127,742 | +212,419 | +121,741 |

Read the last two columns of the slide row with the caveat already stated: (e) does not slide AONIA. The flattener’s large gain in the bull-flatten row is real under that assumed path, and so is its 337k roll loss if the curve merely ages.

## Judgment

**What is priced.** From November 2026 to February 2027 the one-month curve prices a modest step-up, and the November contract is through the fixing. The 43 bp March premium and the 77 bp December premium are premiums of quarter-average futures over a spot fixing. Counting them as 25 bp “hikes” would invent a meeting calendar and a convexity adjustment this packet does not have.

**Where the disagreement is.** Trim/median at 1.85 and unemployment at 6.5 with a negative employment mean are hard to square with a long grind that still rises through December 2027 and, on the same CRA curve, into 2028 (March 2028 is 3.385, December 2028 is 3.475). Headline 3.09, breadth, the September energy-price jumps, and deferred Brent at 84.88 versus a 70 MPR assumption are hard to square with a receive that ignores the front. The 1-month path already prices firming into February. The equal-weight strip averages those two objects together.

**Roll is not the thesis.** If the tenor curve is unchanged, the equal-weight receive gains about 14 bp on the average over one quarter, about 350k dollars at the paper DV01. The flattener loses 13.5 bp of leg DV01 over that same quarter. Preferring the flattener requires the H–Z spread to narrow by more than that roll, on top of any parallel view. The packet does not identify that narrowing. The bull-flatten scenario is a possible story (front validated, back eases). It is an assumption, not a base case. Parallel upward repricing, which is PRiMA’s front-shock label, leaves the flattener flat and hurts the outright. That is a reason to **size** the outright down, not a reason to drop its level exposure to zero.

**The SOFR pay is a hedge, and a full hedge spends the edge.** On a common 20 bp selloff the matched strip is about flat. On Canada +25 and the US +5 the cross still loses about 499k, versus 624k outright, so the US leg saves the 5 bp and no more. On Canada −30 and the US −15 the cross keeps about 374k versus 749k. Roll falls from about 350k to about 128k. The relative cheapness of Canada versus the US on own-cash premia is 8.75 bp. US core inflation in this freeze cannot carry a positive US pay on its own. A full match therefore improves one adverse path and gives up the absolute Canada premium the question asked to preserve. A smaller SOFR overlay would be a new US rates position. This pass does not add one. October’s rejection of a **long** US bond or a **receive** in AONIA was a rejection of more duration in the same direction. It does not decide this pay. The pay still fails as a replacement.

**AONIA does not diversify this book.** Australia’s trimmed mean is 3.6 against a 2.5 midpoint, so a pay has a fundamental story the US leg lacks. The deferred AONIA contracts are the part of that curve that already sits close to cash (+11 bp on December, about +9 bp on the three-month label proxy), while Canadian December is +77 bp. The instruments are a one-month average versus a three-month compound, the basis-point values use different day-counts, and open interest is 400 lots in March and missing further out. Same-direction global repricing is what a DV01 match can offset. Canada-specific oil pass-through is what it cannot. The country code is not the hedge.

**Already owned versus flat.** From a flat book, the 250m equal-weight receive at 3.155 does not clear a fresh hurdle: 24 bp of the original 3.40 entry is already in the mark, the opposing inflation and oil evidence is in the packet, CRA depth is not shown, and the Bank of Canada decision record is missing. From the actual book, the residual is a reduced receive whose falsifier has not fired. Closing it would drop a deferred premium that the labor and trim/median evidence still contest. The continuity choice is to change the mix and the size, not to reopen 250m and not to go to zero on this packet.

**Challenger arguments, not votes.** Rate-dove and the PM’s own hypothesis still receive the strip or the level. Carry-is-king receives March. Perma-bull, the positioning cynic, and the rate hawk pay March. The contested contract in the room is March, which is the leg this reshape drops. The no-trade skeptic’s point that one overnight is the wrong horizon for a multi-meeting curve is right about accrual: nothing in the next one to two quarters realizes the December 2027 fixing. Vol-convexity is flat because the freeze has no listed option surface. AUDNZD’s historical extreme is outside this decision.

**Scenarios as economics, without probabilities.** A common energy or inflation selloff hurts the outright in proportion to DV01 and leaves a matched flattener or a matched SOFR pay roughly flat. A Canada-only pass-through hurts the outright and is only partly offset by a foreign pay. De-escalation and weaker domestic demand pay the receive, and they pay a back-weighted receive if the back leads. The flattener pays only when the spread narrows. None of these paths is assigned a probability. There is no fair-value estimate and no out-of-sample backtest. The embedded SOFR history is a four-month cash path. Temperature history files outside the snapshot were not opened.

## What each alternative gives up

- **Equal-weight retain** gives up a smaller loss if March sells off on a further hike, and it keeps the best roll.
- **The September/December reduce** gives up about 228k dollars of one-quarter roll versus the 349-lot four-leg book, and about half of any parallel rally.
- **The flattener** gives up the 61.5 bp level premium and starts the quarter with a negative roll.
- **The SOFR pay** gives up common-curve rallies and about 222k dollars of the one-quarter Canada roll (350k down to 128k).
- **The AONIA pay** gives up period alignment and evidenced depth, and it pays a contract that is not the rich part of the Australian curve.
- **Close** gives up the remaining deferred disagreement and the positive roll on September and December.

## Gaps that would change the work

Common-ingest requests, not private substitutes:

1. Official Bank of Canada target decision for the late-October 2026 announcement: action, effective date, statement.
2. One-month CORRA futures beyond February 2027, so the March contract’s accrual window can be compared with a monthly path.
3. CRA open interest and volume.
4. Exchange margin, if funding is to be compared with the paper book’s SOFR-on-risk-capital charge.
5. A Canada official curve dated with the futures, if anyone wants a bond cross-check newer than 2026-10-14.
6. A US core inflation print newer than the July 2026 three-month annualized observation carried forward from 2026-09-21.
7. IMM reference-quarter dates and a convexity convention, if accrual alignment needs to be tighter than 90/360 and the published 24.66 AUD basis-point value.

## Verification and model roles

| Role | Model requested | What it did |
|------|-----------------|-------------|
| Parent, economic owner and final approver | grok-4.7 | Evidence boundary, synthesis, label repairs, this verdict |
| Composer A | composer-2.5 | `calc_contracts.py`, contract note, `calc_results.json` |
| Composer B | composer-2.5 | Adversarial economics note. Its retain-no-add rank is an input. The parent rank differs. |
| Composer V | composer-2.5 | `verify_independent.py`. First run 66 pass, 3 fail, all documentation. |

Four model invocations. No second Grok call. `composer-2.5` was the selectable non-fast slug; `composer-2.5-fast` was not used. This note cannot see a hidden serving revision behind an accepted slug.

`python3 docs/research/chatgpt/2026-11-04-corra-expression/calc_contracts.py` and `python3 docs/research/chatgpt/2026-11-04-corra-expression/verify_independent.py` were re-run after the label fixes. Verifier result: **72 pass, 0 fail**. The first V failures were: the SOFR markdown slide table (Z shown as −2 and the average as −10; JSON was −20.5 / −13 / −4 / +2 and −8.875); the section-7 flattener field stored +13.5 while scenario dollars were already the economic −337,371.74 loss; Composer B called the 3.16 versus 3.155 gap 1 bp. The calculator had also tested realized P&L as half of the residual 250m (300,000) against the stored 600,000. The closed slice is 250m of the original 500m, and that identity matches.

Composer B’s retain rank treated a full SOFR pay as a double loss in a common selloff and treated 34 bp as flattener carry. Both are rejected here. A common selloff leaves the matched pay about flat. The 34 bp is the spread. The flattener’s one-quarter roll is a 13.5 bp loss per leg DV01.

## Decision line

Reshape the residual receive onto September and December 2027 at 349 lots each (about 12,486 USD per bp), no add, no flattener, no foreign pay. Revisit if September/December rates move back toward 3.35–3.40 or if underlying inflation, wages, employment, and a documented Bank of Canada decision substantiate another hike. ChatGPT still decides whether to do it.
