# CORRA 2027 receive, 5 November 2026

Research-only review of the existing ChatGPT CORRA position. Every arithmetic result and scenario gap is reproduced by `extract_paths.py` into `paths.json`. Scenario policy rates are assumptions. They are not probabilities, and a gap is not an expected value. This note does not compute P&L, contract counts, or size.

## Clocks and identity

The packet freeze is `2026-11-05T04:53:53.458055-05:00`. Market-state `as_of` and `generated_at` are both `2026-11-05T10:17:36Z`. Both clocks stand. The gap is not repaired. The macro-hard family inside the same packet still carries `as_of` `2026-11-04T05:35:22-05:00`. Temperature inputs were ingested at `2026-11-05T09:53:53Z`, with scoring cutoff `2026-10`.

The packet identity digest is `0bc766c948f4f88f81ea6e28bc00ad0a67e09ee5605b23b47cb69b039f415b10`. That is the canonical hash of the snapshot with `packet_sha256` removed. It matches. The raw file bytes hash to a different digest because those bytes include the digest field.

## How to read a futures rate

`implied_rate = 100 - price`. Each contract is the period rate of that future. CORRA, SOFR, and TONA are quarterly (`contract_period_months` 3). AONIA is monthly (`contract_period_months` 1). `change_from_overnight_bps` equals the period rate minus the overnight fixing, in basis points. That column is the distance from the fixing. It is not unused tightening, and it is not a meeting probability. A 10-year yield minus the same-day overnight fixing is a curve slope. On 3 November the Canada 10-year is 3.77 percent and CORRA is 2.53 percent, a 124 bp slope. That slope is not a hike count, and it is not the 2027 futures gap.

## Position and the prior claim

Book position `pm-chatgpt-595561a1b90f` is a reduced USD 250 million receive. Side long means receive. The expression is the equal-weight average of CRAH27, CRAM27, CRAU27, and CRAZ27. Entry at 3.40 on 20 September 2026 is historical. The book mark of 3.14375 at `2026-11-04T12:12:27Z` is the prior mark. Unrealized profit since 3.40 is historical profit. It is not current edge. The 4 November action was HOLD.

The saved hypothesis `hyp-chatgpt-corra-2027hz-20260919` (revision 05) says retain that reduced receive and do not add. Its forecast was a lower H/M/U/Z average over one to three months if underlying inflation and labor stayed soft and the energy impulse faded. Its falsifiers were a sustained domestic reacceleration, a renewed deferred-energy shock, and a strip that had already repriced most of the gap. This review uses that claim as the prior. The marks below are recomputed from this snapshot.

## Fixings in this snapshot

| Benchmark | Rate | as_of | What is cited |
| --- | ---: | --- | --- |
| CORRA | 2.53 | 2026-11-03 | The fixing. Single print. |
| SOFR | 3.97 | 2026-11-03 | Latest NY Fed point. The 90-point history is not averaged. |
| AONIA | 4.85 | 04-Nov-2026 | The fixing. |
| TONA call average | 1.227 | 2026-11-02 | BOJ FM01 uncollateralized overnight call average. |
| €STR | 2.442 | 2026-11-04 | Overnight only. |

The TONA futures note says the contracts settle on three-month compounded confirmed TONA, not the raw call print. The stored overnight gap still equals futures minus 1.227. The arithmetic identity holds. The economic objects remain different. Eurex €STR futures are an empty list and EA policy status is partial. New Zealand has no official curve and no futures curve in this packet.

## CORRA shape

SOFR rows carry observation date 2026-11-04. CORRA rows do not carry a separate observation date; they are the contracts in this snapshot. The Montréal source page is undated inside the curve object.

| Expiry | Code | Price | Implied rate | Versus 2.53 fixing, bp |
| --- | --- | ---: | ---: | ---: |
| 2026-09 | CRAU26 | 97.5825 | 2.4175 | -11.25 |
| 2026-12 | CRAZ26 | 97.275 | 2.725 | 19.5 |
| 2027-03 | CRAH27 | 97.07 | 2.93 | 40 |
| 2027-06 | CRAM27 | 96.925 | 3.075 | 54.5 |
| 2027-09 | CRAU27 | 96.815 | 3.185 | 65.5 |
| 2027-12 | CRAZ27 | 96.735 | 3.265 | 73.5 |
| 2028-03 | CRAH28 | 96.665 | 3.335 | 80.5 |
| 2028-06 | CRAM28 | 96.615 | 3.385 | 85.5 |
| 2028-09 | CRAU28 | 96.585 | 3.415 | 88.5 |
| 2028-12 | CRAZ28 | 96.575 | 3.425 | 89.5 |
| 2029-03 | CRAH29 | 96.59 | 3.41 | 88 |
| 2029-06 | CRAM29 | 96.59 | 3.41 | 88 |

The 2027 strip average is **3.11375**. Versus the 3 November fixing that is **58.375 bp**. Inside the strip the period rate rises 33.5 bp from CRAH27 to CRAZ27. Successive quarterly changes, in basis points of period rate, are +30.75, +20.5, +14.5, +11, +8, +7, +5, +3, +1, then -1.5 into March 2029. The strip sits in the middle of a climb that is still rising through December 2028 (3.425) and only then flattens. It is not a terminal plateau.

One-month CORRA futures stop at February 2027:

| Expiry | Code | Implied rate | Versus 2.53, bp |
| --- | --- | ---: | ---: |
| 2026-11 | COAX26 | 2.515 | -1.5 |
| 2026-12 | COAZ26 | 2.605 | 7.5 |
| 2027-01 | COAF27 | 2.655 | 12.5 |
| 2027-02 | COAG27 | 2.775 | 24.5 |

The packet's prima proxy stores a neutral midpoint of 2.75 against the same 2.53 CORRA print, a gap of -22 bp. That midpoint is a proxy input dated with the 3 November fixing. It is not a Governing Council estimate. COAG27 at 2.775 is 2.5 bp above it. By February the one-month curve has already done the move back to that midpoint. The quarterly strip then leaves it behind: CRAH27 is 2.93.

Split the 58.375 bp futures-minus-fixing gap with today's objects only:

- 22 bp from the 2.53 fixing up to the stored 2.75 midpoint.
- 36.375 bp from that midpoint up to the 3.11375 strip average.

Those two pieces add to 58.375. The second piece is the forward gap used below. The first piece is largely visible in the one-month curve by February.

## SOFR shape

CME SR3 settlements, observation date 2026-11-04. The fixing is the 3 November SOFR print at 3.97. Contracts through 2028, plus the maximum in the file:

| Expiry | Code | Implied rate | Versus 3.97, bp | Open interest |
| --- | --- | ---: | ---: | ---: |
| 2026-12 | SR3Z6 | 4.165 | 19.5 | 1,657,460 |
| 2027-03 | SR3H7 | 4.36 | 39 | 1,279,849 |
| 2027-06 | SR3M7 | 4.475 | 50.5 | 1,250,953 |
| 2027-09 | SR3U7 | 4.505 | 53.5 | 1,081,811 |
| 2027-12 | SR3Z7 | 4.475 | 50.5 | 1,524,239 |
| 2028-03 | SR3H8 | 4.44 | 47 | 845,744 |
| 2028-06 | SR3M8 | 4.415 | 44.5 | 675,481 |
| 2028-09 | SR3U8 | 4.395 | 42.5 | 672,566 |
| 2028-12 | SR3Z8 | 4.38 | 41 | 557,466 |
| 2036-03 | SR3H6 | 5.005 | 103.5 | 0 |

The 2027 average of SR3H7, SR3M7, SR3U7, and SR3Z7 is **4.45375**, which is **48.375 bp** above 3.97. Quarterly steps from December 2026 through December 2028 are +19.5, +11.5, +3, -3, -3.5, -2.5, -2, -1.5 bp. The liquid high through 2028 is SR3U7 at 4.505. December 2027 is 3 bp under that high, and December 2028 is 4.38. The path rises into September 2027 and then drifts. It does not price a 2027 easing cycle. The file maximum, SR3H6 at 5.005, has zero open interest and zero volume. It is the curve maximum, not the policy peak used here.

The policy block also has a delayed eSignal ICE one-month SOFR path through October 2028. That is a different source from SR3. It is used only in the object comparison below.

## AONIA shape

ASX 30-day interbank cash-rate futures. The end-of-day file name in the source URL is the 4 November 2026 summary. Benchmark as_of is `04-Nov-2026`.

| Expiry | Price | Implied rate | Versus 4.85, bp | Open interest |
| --- | ---: | ---: | ---: | ---: |
| 2026-11 | 95.18 | 4.82 | -3 | 24,949 |
| 2026-12 | 95.14 | 4.86 | 1 | 3,845 |
| 2027-01 | 95.13 | 4.87 | 2 | 1,105 |
| 2027-02 | 95.095 | 4.905 | 5.5 | 476 |
| 2027-03 | 95.075 | 4.925 | 7.5 | 400 |
| 2027-04 | 95.075 | 4.925 | 7.5 | 550 |
| 2027-05 | 95.085 | 4.915 | 6.5 | 350 |
| 2027-06 | 95.1 | 4.90 | 5 | 200 |
| 2027-07 | 95.135 | 4.865 | 1.5 | 350 |
| 2027-08 | 95.175 | 4.825 | -2.5 | 150 |
| 2027-09 | 95.205 | 4.795 | -5.5 | 600 |
| 2027-10 | 95.225 | 4.775 | -7.5 | 1 |
| 2027-11 | 95.28 | 4.72 | -13 | null |
| 2027-12 | 95.31 | 4.69 | -16 | null |
| 2028-01 | 95.315 | 4.685 | -16.5 | null |
| 2028-02 | 95.365 | 4.635 | -21.5 | null |
| 2028-03 | 95.375 | 4.625 | -22.5 | null |
| 2028-04 | 95.415 | 4.585 | -26.5 | null |

The front is a small hump. From November 2026 through April 2027 the rates are 4.82, 4.86, 4.87, 4.905, 4.925, 4.925. The peak is 7.5 bp above the fixing, and the six-month average is 4.88417. August 2027 is the first month back through the fixing. December 2027 is 4.69, 16 bp below it. April 2028 is 4.585, 26.5 bp below it. Open interest is blank from November 2027 onward.

The arithmetic average of the ten months from March 2027 through December 2027 is **4.8335**. That is **1.65 bp below** the 4.85 fixing. The average hides the hump and the easing. The August-December 2027 average is 4.761. The November 2027 through April 2028 average is 4.65667, **19.333 bp below** the fixing.

The policy-path terminal for Australia points at September 2027 (4.795). The futures continue to April 2028. The terminal field is not the end of the path.

Same-day bank bills on 4 November are 4.79 (1m), 4.92 (3m), and 5.26 (6m). The OIS prints in that block are dated 1 December 2022, and bill minus OIS is `unavailable_cross_vintage`. The bill curve is a credit object. It is not the RBA path.

## TONA through 2028

Settlement file name in the source URL is the 5 November 2026 CSV. The call-rate fixing is 2 November.

| Expiry | Code | Implied rate | Versus 1.227 call, bp |
| --- | --- | ---: | ---: |
| 2026-09 | 261215 | 1.205 | -2.2 |
| 2026-12 | 270316 | 1.4475 | 22.05 |
| 2027-03 | 270615 | 1.655 | 42.8 |
| 2027-06 | 270914 | 1.8225 | 59.55 |
| 2027-09 | 271214 | 1.9175 | 69.05 |
| 2027-12 | 280314 | 2.0125 | 78.55 |
| 2028-03 | 280620 | 2.0525 | 82.55 |
| 2028-06 | 280919 | 2.0975 | 87.05 |
| 2028-09 | 281219 | 2.1425 | 91.55 |
| 2028-12 | 290319 | 2.19 | 96.3 |

The path rises in every listed quarter through December 2028. December 2027 is 78.55 bp above the call average. There is no peak and reversal inside this window. The curve in the file keeps rising through June 2031 (2.6375). Japan is discussed after the expression choice.

## Vintage comparison, kept separate

The hypothesis cites the 4 November morning packet: 2.970 / 3.115 / 3.225 / 3.310, average 3.155, fixing 2.54, gap 61.5 bp. Those four rates are not in this snapshot. They are not mixed into the 22 bp plus 36.375 bp split above.

| | Previous morning vintage | This snapshot |
| --- | ---: | ---: |
| H / M / U / Z | 2.970 / 3.115 / 3.225 / 3.310 | 2.93 / 3.075 / 3.185 / 3.265 |
| Average | 3.155 | 3.11375 |
| Own fixing | 2.54 | 2.53 on 2026-11-03 |
| Average minus own fixing | 61.5 bp | 58.375 bp |

The average is 4.125 bp lower. Contract changes are -4, -4, -4, and -4.5 bp. Each vintage's gap versus its own fixing is 3.125 bp narrower. Versus the book mark of 3.14375 at 12:12Z on 4 November, today's average is 3 bp lower. The move since that morning packet is roughly parallel.

## Evidence that bears on the paths

Canadian inflation and labor transforms are September prints. Headline 3.0928 and underlying 1.85 have recorded release date 2026-10-19. The underlying temperature level is 48.12, near the structural anchor of 50, with impulse -1.25. Headline level is 63.66. The inflation block as a whole is neutral and static. Unemployment transform 6.5, wages transform 2.3382, and employment transform -11.6333 are September. The labor block level is 40.94, direction cooling, class neutral. The component rows say current release and checked-unchanged. The temperature release-date status on those three labor series is `inherited_or_inconsistent`, so the release calendar is not clean even though the transforms are in the packet. Participation is a source failure. No later CPI or unemployment print is in the packet.

September CPI breadth is rising: 5 of 8 major components had a positive month-on-month change, share 0.625. September IPPI energy and petroleum was about +12.1 percent on the month, and RMPI crude energy about +14.4 percent. Both are shadow inputs and are excluded from the prima score. Ex-energy IPPI was about +0.28 percent, and RMPI excluding crude energy was about -0.43 percent. The pipeline split is energy versus everything else. Prima's net direction is STABLE, strength low. The demand-pass-through channel is the -22 bp gap to the 2.75 midpoint already used above.

The October Canadian business-survey transform is 48.2, retrieved 5 November. The activity block's "warming" label is the Q2 GDP impulse, release 28 August, retrieved 21 September. It is not an October demand boom.

US core PCE transform 3.0478 is July 2026. The component status is `source_failed`, previous release retained, after a timeout. Headline PCE is unavailable. The inflation block is warm on that stale print. September unemployment transform is 4.2, wages transform 3.0245, labor level 51.26, direction cooling, class neutral. October manufacturing survey transform 54.8667 was released 2 November. October services survey transform 54.9333 was released 4 November and is the one new US activity observation. The activity block's "cooling" direction is dominated by a stale Q2 GDP impulse whose read also timed out. The fresh surveys are still in the mid-54s.

Australian inflation transforms of 4.3 and 3.6 are stored for September, retrieved 28 October, with `inherited_or_inconsistent` release dates. The component rows say checked-unchanged and current release. The macro notes and `known_gaps` list `AU.Inflation.headline` and `AU.Inflation.underlying` as due_missing. The component status field `due_missing` is actually used for two US Chicago Fed nowcast series only. Those statements disagree. No Australian CPI number is treated as a verified print. Wages transform 3.2 is a 2026-Q2 print with recorded release date 13 August. Unemployment transform 4.7183 and the labor block (level 45.74, direction cooling) have the same inconsistent release-date flag as the Canadian labor block. The labor-leading packet is partial. The two stored observations, ANZ-Indeed job ads 125.3 and the NAB employment subindex -1 for September, both have weight 0.0. Several leading series failed or are discovery gaps.

### Oil and other cross assets, each on its own date

The WTI futures mark on 2026-11-04 is 88.12 dollars, stored percentile 56.3. The Brent futures mark on the same date is 94.62 dollars, stored percentile 59.1. The series note says roll jumps can distort that screen. On the screen that exists, oil is near the middle of the window, not historically cheap. The log-percent moves are large on the short window and ordinary to positive on the longer one: WTI about -8.7 one day, -15.4 five days, -1.5 one month, +13.1 three months. Brent about -9.1, -19.8, -6.1, and +13.7 on those same horizons. A headline in the packet says crude fell below 90 dollars. That sentence is narrative. The marks are the ones above.

Deferred Brent in the prima block, observed 2026-11-04: December 2027 at 79.12, down 3.50 dollars on the month, and December 2028 at 73.82, down about 2.06 dollars. Same-day, December 2027 is 15.50 dollars under the 94.62 Brent futures mark. Versus the July 2026 MPR prose assumption of 70 dollars, the packet records December 2027 Brent as still 9.12 dollars higher. The December 2026 Brent input is a different date, 30 October, at 117.64, and that shock-persistence channel is marked stale. The packet's label `parallel_downward_repricing` uses that stale front leg. It is not a same-day oil curve.

US 10-year breakeven on 2026-11-04 is 226 bp, percentile 23.4, five-day move -12 bp. US 10-year real yield on 2026-11-03 is 265 bp, percentile 90.1, one-month move -27 bp, five-day move +1 bp. Nominal 10-year on 2026-11-04 is 490 bp. These three dates do not support a same-day split of the nominal yield into real yield, breakeven, and oil. High-yield OAS on 2026-11-03 is 340 bp, percentile 98.2, up 28 bp on the month and 69 bp on the quarter. Credit is stressed on that date. VIX on 2026-11-03 is 20.83.

Sovereign yields, in percent, from the bp series:

| Series | as_of | Age, days | Yield |
| --- | --- | ---: | ---: |
| CA 2Y / 10Y | 2026-11-03 | 2 | 3.26 / 3.77 |
| US 2Y / 10Y | 2026-11-04 | 1 | 4.58 / 4.90 |
| AU 2Y / 10Y | 2026-10-28 | 8 | 4.951 / 5.208 |
| JP 2Y / 10Y | 2026-11-04 | 1 | 1.891 / 2.855 |

The official Japanese 2-year par yield on 2026-11-04 is also 1.891. Australia's sovereign curve is eight days older than the AONIA futures. The Australian official zero curve is 30 September. Canada's official zero curve is 14 October and its forward curve is empty. None of those stale curves is subtracted from a fresher futures rate.

News inside the packet is narrative. The items used as color, not as marks: a Democratic House and Senate sweep with lower Treasury yields and lower oil; the Fed held on 28 October, body not retrieved; Norges held with the option of another hike; BoJ minutes of 17-18 September have an empty summary; a BoJ-hold headline says underlying inflation aligned with 2 percent, body not retrieved. Hormuz mine and shipping headlines are in the packet from 30 October and 1 November. They are the narrative behind scenario B. They are not an oil mark.

## Three conditional paths

Probabilities are unknown. Each assumed rate is a judgment about the period rate under that conditional, written so it can be compared with the futures period rate. Gap = futures period rate minus assumed period rate, in basis points. A positive gap means the futures rate is above the assumption.

### A. Sustained cheaper oil

Oil stays near the 4 November marks or lower, and the disinflation is treated as persistent. The stored percentiles stay in view: this is a mid-distribution oil price that has just fallen hard, not a historically cheap oil regime. Deferred December 2027 Brent at 79.12 would have to be accepted as the new neighborhood, rather than a pause on the way back up.

**Bank of Canada. Assumption: 2.75 flat on CRAH27, CRAM27, CRAU27, and CRAZ27.** The stall level is the packet's own proxy midpoint. The assumption does not cut through that midpoint. It is the less dovish version of A. A path below 2.75 would widen the gap.

| Contract | Futures | Assumption | Gap, bp |
| --- | ---: | ---: | ---: |
| CRAH27 | 2.93 | 2.75 | 18 |
| CRAM27 | 3.075 | 2.75 | 32.5 |
| CRAU27 | 3.185 | 2.75 | 43.5 |
| CRAZ27 | 3.265 | 2.75 | 51.5 |
| Average | 3.11375 | 2.75 | **36.375** |

What supports A in Canada: underlying transform 1.85 with a negative impulse, labor temperature 40.94 and unemployment transform 6.5, ex-energy prices stable to slightly down, and a large five-day oil decline. What contradicts it: headline 3.0928, rising September breadth, the September energy jump already in IPPI and RMPI, and December 2027 Brent still 9.12 dollars above the July MPR's 70 dollar prose assumption. The October survey at 48.2 does not look like a demand boom, and it is only one print.

**Fed. Assumption: 4.20 flat on SR3H7, SR3M7, SR3U7, and SR3Z7.** That is a stall about 23 bp above the 3.97 fixing, not a return to the fixing. Firm surveys and a 4.2 unemployment transform argue against assuming cuts even if oil disinflation is treated as persistent. The July core PCE transform of 3.05 is warm and stale.

| Contract | Futures | Assumption | Gap, bp |
| --- | ---: | ---: | ---: |
| SR3H7 | 4.36 | 4.20 | 16 |
| SR3M7 | 4.475 | 4.20 | 27.5 |
| SR3U7 | 4.505 | 4.20 | 30.5 |
| SR3Z7 | 4.475 | 4.20 | 27.5 |
| Average | 4.45375 | 4.20 | **25.375** |

US evidence fits A poorly. The fresh surveys are expansionary, labor is near the temperature anchor, and oil's level percentile is ordinary. The breakeven decline and the wide high-yield spread are the parts of the packet that keep a disinflation reading possible. They have different dates from each other.

**RBA. Assumption: March 2027 at 4.75, then -5 bp of period rate each month, to 4.30 in December 2027.** Average assumption 4.525. Futures average 4.8335. Gap **30.85 bp** on the ten-month average. The later bucket, November 2027 through April 2028, continues the same -5 bp step. Its futures average is 4.65667 and its assumption average is 4.225, gap **43.167 bp**. Under A the later Australian months are too high, which is a receive, not a pay. Domestic support is the cooling labor block and the oil decline. Domestic contradiction is the unresolved inflation block: the stored transforms are warm, and the packet also flags them due_missing. A is not a clean Australian base.

### B. Renewed physical disruption

The Hormuz and energy-shock headlines reassert, and oil premia return. September's energy jump in Canadian producer prices is the domestic fact that makes this more than a headline. The 4 November spot drop is the fact that makes B a conditional, not a description of the latest mark.

**Bank of Canada. Assumption: 3.00, 3.20, 3.35, 3.50.** Average assumption 3.2625. Gap **-14.875 bp**. The futures path would be slightly low if this path were realized, with the largest shortfall in CRAZ27 (futures 3.265 versus assumption 3.50, gap -23.5 bp). Under B the receive is the wrong side.

**Fed. Assumption: 4.45, 4.60, 4.70, 4.75.** Average assumption 4.625. Gap **-17.125 bp**. The priced plateau near 4.50 would be too low, and the 3 bp giveback from SR3U7 to SR3Z7 would be the wrong direction.

**RBA. Assumption: 5.00 flat from March through December 2027.** Futures average 4.8335. Gap **-16.65 bp**. The later bucket gap is **-34.333 bp**. Under B the easing in the back of the AONIA curve is the conflict, and a pay of those later months is the expression. The front hump is only a few basis points under 5.00. Paying the whole March-December average smears that.

### C. Stronger demand

Oil is lower because supply fear faded. Growth and labor do not weaken, so reaction functions do not ease just because oil fell.

**Bank of Canada. Assumption: 2.85, 2.95, 3.00, 3.05.** Average assumption 2.9625. Gap **15.125 bp**. Even this conditional, which refuses cuts and allows a further firming toward 3 percent, leaves the strip above the assumption. The 2028 continuation to 3.425 is further outside it. Canadian evidence contradicts the premise: unemployment transform 6.5 and a cool labor block are not "labor does not weaken." The October survey at 48.2 does not repair that. C is the worst domestic fit of the three for Canada, and the futures path is still above it.

**Fed. Assumption: the SR3 period rates themselves, 4.36, 4.475, 4.505, 4.475.** Gap **0 bp** by that judgment. October surveys in the mid-54s, unemployment transform 4.2, and a warm if stale core print are what a rise-then-plateau looks like. High-yield OAS at the 98th percentile keeps C from being a clean boom. It does not create a receive. A zero gap means this conditional does not identify a conflict. It does not mean the futures are an expected value.

**RBA. Assumption: 4.90 flat across March-December 2027.** Futures average 4.8335. Gap **-6.65 bp**. March is 2.5 bp above 4.90. December is 21 bp below it. The later bucket gap is **-24.333 bp**. The average is almost flat to the assumption because the front hump and the back easing cancel. A cooling labor block contradicts the "labor does not weaken" premise, with the same release-date caveat as above.

## The most mispriced path

The largest conflict is the Bank of Canada's still-rising 2027 and 2028 CORRA period-rate path. CRAH27 at 2.93, CRAZ27 at 3.265, and CRAZ28 at 3.425 keep climbing after the one-month curve has already reached the 2.75 proxy midpoint by February. The base reading is scenario A: underlying inflation near 1.85, a cool labor block around an unemployment transform of 6.5, and an ex-energy pipeline that is not reaccelerating. Under the flat 2.75 assumption the strip average is **36.375 bp** above the path, and the gap is larger in the back of the strip than in CRAH27.

That is a conflict with the evidence. It is not the 58.375 bp futures-minus-fixing distance, and it is not the 124 bp 10-year slope.

The futures path would be right if scenario B arrives: the September energy jump and the rising breadth pass into underlying inflation, deferred Brent stops declining, and the BoC treats the shock as persistent. It would also be closer to right if Canadian labor reaccelerates and scenario C stops being contradicted by the 6.5 transform. Either of those is a falsifier. Neither has a probability attached.

The Fed's 48.375 bp futures-minus-fixing gap is a smaller conflict because the better-supported US conditional, C, has a zero gap, and the US domestic prints do not look like Canada's. Australia's March-December average is 1.65 bp from the fixing. The back-end easing is a real shape, and its sign versus the assumptions flips from receive under A to pay under B and C. The CPI print that would pin that sign is unresolved inside the packet, and the months that carry the easing have no recorded open interest. Canada is the mispricing.

## Expression

**Keep the existing equal-weight receive of CRAH27, CRAM27, CRAU27, and CRAZ27.** The claim is that the whole rising 2027 period-rate path is too high versus a stall at 2.75. Every contract is above that assumption, from 18 bp on CRAH27 to 51.5 bp on CRAZ27. The recent vintage move was about 4 bp and roughly parallel, so the position that matches the claim is the strip that was already on.

**Shorter calendar, pay CRAH27 and receive CRAZ27.** The futures spread, December minus March, is 33.5 bp. Under assumption A the spread is 0, so the slope gap is 33.5 bp. That is smaller than the 36.375 bp level gap, and the calendar pays CRAH27, which is itself 18 bp above the assumption. Paying the front is the wrong side of that contract. A still shorter pair, CRAU27 against CRAZ27, is only an 8 bp period-rate step. The parallel 4 bp rally would have paid a calendar almost nothing. The calendar is rejected as a replacement.

Receiving only CRAU27 and CRAZ27 has a larger gap versus 2.75 (their average is 3.225, gap 47.5 bp). It drops two contracts that are also above the assumption and changes the bet toward the later path. Higher implied rates on U and Z do not make that the better expression of this level claim. The prior rejection of a U/Z-only book stands.

**Receive SOFR 2027, SR3H7, SR3M7, SR3U7, and SR3Z7.** This is the strongest rejected alternative. The futures-minus-fixing gap, 48.375 bp, looks like Canada's 58.375 bp, which is why the receive is tempting. Under assumption A the Fed gap is 25.375 bp. Under assumption C, the conditional that fits the mid-54 surveys and the 4.2 unemployment transform, the gap is 0. Oil at the 56th percentile does not turn a five-day drop into a Fed easing cycle. The saved hypothesis claim is the CORRA strip. This review tested the weaker SOFR alternative and does not upgrade it.

**Pay AONIA where the later easing sits, and receive Canada against pay Australia.** The later bucket is the ASX months from November 2027 through April 2028, average 4.65667. Under assumption A that bucket is 43.167 bp above the assumed path. Under B it is 34.333 bp below. Under C it is 24.333 bp below. The sign flips, the CPI evidence is internally inconsistent, and open interest is blank. The March-December average gap under C is only -6.65 bp because the front hump cancels the back. A single "pay Australia" smears unlike months. Pairing it with the CORRA receive adds a second policy bet the Canadian evidence does not require. The RV is rejected. Correlation between the legs is a risk to understand if someone later puts it on. It is not a reason to put it on now.

**Japan.** Paying TONA would say the climb from 1.227 to 2.0125 by December 2027, and to 2.19 by December 2028, is too low. Receiving would say it is too high. September inflation transforms are 2.2, with release dates not recorded. The labor block is slightly warm, the wages transform for August is 3.9, and the consumer block is cool (level 33.74). The 2-year par yield is 1.891 on 4 November. That yield and the TONA futures are different objects, on different fixings, and they are not subtracted into a basis. A more credible normalization story is already a long, monotonic climb. The gap is not large and evidenced in either direction. No new Japan trade.

## Monthly AONIA is not a CORRA quarter

An average of three AONIA months is an arithmetic mean of 30-day cash-rate futures. A CORRA or SOFR quarter is one three-month implied rate. Matching DV01 would still leave different accrual, a different fixing, and different exposure to a policy step inside the quarter. The three-month buckets on the AONIA curve, which are illustrations and not synthetic quarters:

| Months | Rates | Arithmetic average | First to last, bp |
| --- | --- | ---: | ---: |
| Mar, Apr, May 2027 | 4.925, 4.925, 4.915 | 4.92167 | -1 |
| Jun, Jul, Aug 2027 | 4.90, 4.865, 4.825 | 4.86333 | -7.5 |
| Sep, Oct, Nov 2027 | 4.795, 4.775, 4.72 | 4.76333 | -7.5 |
| Dec 2027, Jan, Feb 2028 | 4.69, 4.685, 4.635 | 4.67 | -5.5 |

The front bucket is almost flat. The middle buckets fall 7.5 bp from the first month to the last. One quarterly number cannot show that intra-quarter decline. Canadian one-month futures stop in February 2027, so CRAH27 has no monthly siblings in this packet at all.

The US one-month path is a second illustration, and it is a different source from SR3, so the residual is not a basis to trade. March, April, and May 2027 one-month rates average 4.30583, against SR3H7 at 4.36, a 5.417 bp difference, while the monthly path itself rises 12.75 bp from March to May. By the September and December buckets the one-month average and the SR3 print are within a few basis points, and the monthly range has compressed. The object difference is largest where the path is moving inside the three months.

The March-December 2027 AONIA average of 4.8335 minus the CORRA 2027 average of 3.11375 is **171.975 bp of rate**. That is the level gap between two policy regimes. It is not P&L and it is not the mispricing.

## The forward gap is still there

The existing strip competes on the distance from today's 3.11375 average to the scenario path. It does not compete on the profit since 3.40, and it does not compete on the prior mark of 3.14375.

Under assumption A the remaining gap is 36.375 bp. The election window, measured as the separate vintage comparison, has taken 4.125 bp off the morning-packet average and 3 bp off the 12:12Z book mark. That is a small parallel rally against a 36 bp gap. It has not consumed the edge. The keep stands. This note does not size it, and it does not convert the residual into an add. The less dovish construction matters: the 36.375 bp figure stalls at 2.75 rather than assuming cuts, so the keep does not depend on a forecast of easing through the midpoint.

## Falsifiers and horizon

The horizon runs into the 2027 H/M/U/Z contracts. The review trigger is the next shared packet. There is no forced hedge and no fiscal or term-premium point estimate.

1. Underlying inflation, wages, and employment reaccelerate enough to validate period rates above the 2.75 stall. The September headline transform of 3.0928 and the rising major-component breadth are the evidence already in the packet that could start that pass-through.
2. Deferred oil premia return. December 2027 Brent at 79.12 on 4 November is the mark to watch, alongside whether the stale front of the prima oil curve gets a same-day replacement.
3. The four-contract average cheapens back through roughly 3.35 to 3.40 with domestic confirmation. That review trigger is carried forward from the hypothesis. It is not a new mechanical stop.
4. A later packet shows the four-contract average no longer materially above the 2.75 assumption. The keep is about the remaining forward gap. If that gap closes because the thesis worked, the position has to be judged again.

## Data gaps

- The freeze clock and the 10:17Z market-state clock are both real. Macro-hard's family timestamp is still the 4 November morning.
- €STR futures are empty. EA policy status is partial. New Zealand has no official curve and no futures.
- US core PCE is a retained July print after a failed read. Headline PCE is missing. Several US consumer series are July or August.
- Australian CPI is unresolved: stored transforms, a current-release component row, a due_missing note, and an inconsistent release date, all at once. Labor-leading series are partial and zero-weight.
- No Canadian CPI or unemployment print newer than September is in the packet.
- Australian sovereigns are 28 October. The RBA official curve is 30 September. Canadian official zeros are 14 October, with no forwards. Bill-OIS is cross-vintage.
- Real yield, breakeven, and oil do not share one date. The prima front Brent contract is 30 October and the deferred contracts are 4 November.
- CME positioning is unavailable. CORRA and TONA open interest and volume are null. AONIA open interest is null from November 2027.
- BoJ minutes have an empty summary. The Fed-hold and BoJ-hold items are headline-only.
