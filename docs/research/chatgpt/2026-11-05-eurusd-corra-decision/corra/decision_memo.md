# CORRA 2027 receive — decision, 5 November 2026

Research recommendation only. No order, no book change, no ledger event. The 4 November strip rally is not an out-of-sample win.

Evidence clocks, both standing: packet freeze `2026-11-05T04:53:53.458055-05:00`; market-state generation `2026-11-05T10:17:36Z`. CORRA contracts in the snapshot have no separate observation date. The Montréal source page is undated inside the curve object. Open interest and volume are null on every listed CORRA contract. Fixing CORRA **2.53** on 2026-11-03.

Anchor is the snapshot four-quarter average **3.11375** (CRAH27 2.93, CRAM27 3.075, CRAU27 3.185, CRAZ27 3.265). That is **58.375 bp** above the fixing. The path still rises **33.5 bp** from March to December. December 2026 quarterly is 2.725. One-month: Nov 2.515, Dec 2.605, Jan 2.655, Feb **2.775**. December 2028 quarterly is 3.425. Book mark 3.14375 (2026-11-04T12:12:27Z) is 3.0 bp above this anchor, about USD 75,000 if the USD 250 million were remarked. That remark is not canonical P&L. The prior morning vintage average of 3.155 is 4.125 bp higher. Entry 3.40, unrealized USD 640,625, and realized USD 600,000 are history.

Position `pm-chatgpt-595561a1b90f`, side long = receive, equal-weight Mar/Jun/Sep/Dec 2027. Current paper notional USD 250,000,000. Paper identity **USD 25,000 per bp** of the strip average. A receive loses when the average rises: 20 bp costs USD 500,000 at this identity and gains USD 500,000 if the average falls 20 bp. Montréal is CAD 25 per bp per CAD 1 million face. Those CAD lots are a different object. Dollar figures below are the USD paper identity and are not converted. At the 4 November USDCAD close of **1.3935**, a parallel 1 bp on the average is about **348.4 lots in each of the four contracts** at the current identity, and about **139.4 lots per contract** at the USD 10,000 per bp identity used below. Illustration only.

Funding stock USD 24,829.87 is 3.95% ACT/360 on the USD 2.5 million draw. About USD 98,750 per 360-day year at that draw. Not a direction.

## 1. Decision now

**Resize to USD 100 million. Keep the receive. Equal-weight the same four contracts. DV01 USD 10,000 per bp.** Confidence is **low-to-medium**: medium that the back of the 2027 climb is too steep for the cool domestic block, low on how many basis points that is worth in the next two or three months.

**Mechanism I own.** The February one-month contract is already 2.775. The fight is the climb after that. A 2027 average of 3.11375 says the period rate keeps rising through a fixing that already contains the completed hike, by another 33.5 bp from the March contract to the December contract, and on to 3.425 by December 2028. September underlying inflation is **1.85** with impulse **−1.25** (level 48.12, released 2026-10-19). Unemployment transform is **6.5**, and the labor block is cooling (level 40.94, impulse −1.22). The October business-survey transform is **48.2** (impulse −0.6). Ex-energy IPPI is +0.28% and scores stable; RMPI excluding crude energy is −0.43%. That mix does not describe a 2027 that needs the full continuation priced in the back of the strip. The central shape I will defend is **2.90 / 2.98 / 3.05 / 3.10**, average **3.0075**, **10.625 bp** below 3.11375. The front quarterly is only about 3 bp rich. The gap sits in June, September, and December.

**What 3.11375 already requires.** It requires the four 2027 period rates to average 58 bp above the 3 November fixing, with the hiking cycle still extending after the one-month curve has already reached the proxy neighborhood. It is the opposing case priced as the path, not a stall.

**Strongest opposing case.** The Bank has already hiked into underlying 1.85. Headline is **3.0928** with a positive impulse, September CPI breadth is rising (5 of 8 majors, share 0.625), and September IPPI energy and petroleum is **+12.1%** on the month with RMPI crude energy **+14.4%**. Wage impulse inside the labor block is **+3.78** (transform 2.34) even though the block is cooling. Cheaper energy can support demand and keep the Bank tightening. The election does not prove peace, smaller deficits, or a lasting oil decline. Front WTI **88.12** and Brent **94.62** on 4 November are mid-sample (percentiles 56.3 and 59.1 on a screen whose note warns that rolls distort it). Over the 63 stored observations back to 7 August the simple change is about **+13%** (WTI 78.18 to 88.12, Brent 83.55 to 94.62), in the neighborhood of the stated 14%. The activity block’s “warming” label is the Q2 GDP impulse (transform 1.82, released 28 August), not an October boom. If pass-through and that demand channel dominate, 3.11 is fair to cheap and the receive loses.

Prima’s net direction is stable, strength low. Its **2.75** midpoint is the `corra_neutral_gap` input against the 2.53 fixing (gap −22 bp). The note on that input says CORRA is the observed overnight benchmark, not a Governing Council vote. The shock-persistence channel is marked stale because the December 2026 Brent leg is 30 October at 117.64. That leg is not used. Deferred-energy risk here is the front path plus the September energy PPI. The 4 November deferred marks (December 2027 Brent 79.12, still 9.12 above the July MPR’s 70 dollar prose; December 2028 Brent 73.82) are recorded observations, not a curve I am forecasting.

**From-flat test.** Flat today, I would initiate **USD 100 million** of this same receive at 3.11375, DV01 USD 10,000 per bp. I would not initiate USD 250 million. The existing USD 250 million is therefore cut to USD 100 million. Retaining full size fails that test. The old invalidation has not printed, and that absence is not a reason to keep the full face. A 4 bp rally neither spends a large gap nor proves one.

US contrast, not a trade: October surveys in the mid-54s, unemployment transform 4.2, SOFR 2027 average 4.45375 versus a 3.97 fixing. Nothing is added in SOFR. AONIA is a different regime and a monthly cash-rate future. It is not a substitute and not a hedge.

## 2. Two ranges

**Eventual 2027 four-quarter average: 2.80 to 3.20.**

- **2.80 floor.** The completed hike stays, the early-2027 residual mostly arrives, and then the Bank stops. A shape that averages 2.80 is 2.75 / 2.78 / 2.82 / 2.85. That is a stall around the February one-month, not a cutting cycle.
- **3.0075 central.** Modest further firming, then the climb flattens. 2.90 / 2.98 / 3.05 / 3.10. Futures gaps of about 3, 9.5, 13.5, and 16.5 bp.
- **3.20 ceiling.** Pass-through and the demand channel both work, and unemployment at 6.5 still caps the year. A shape that averages 3.20 is 2.95 / 3.10 / 3.30 / 3.45. December can print above today’s December future. The average does not belong above 3.20 on this packet.

The snapshot average sits inside that range, about **31 bp** above the floor and **8.6 bp** below the ceiling, **10.6 bp** above the central shape. The mispricing I will defend is that 10.6 bp, concentrated in the back, not a 36 bp hole.

**2.75 fails as the four-quarter average.** It is 5 bp under the floor. A flat 2.75 on all four quarters fades the February one-month and requires no residual firming after a Bank that has already hiked, with headline at 3.09, breadth rising, wage impulse positive, and an energy PPI jump that has no later CPI in the packet. 2.75 can appear as an early-2027 monthly print. It does not survive as the target. It would re-enter the range only if a later print showed underlying still near 1.85 and headline rolling over as energy fell out. That print is not here. The first report’s flat 2.75 path, its 36.375 bp gap, and the USD 909,000 figure on this DV01 were the proxy. They are not this decision. The energy pass-through path that averaged 3.2625 and the mild-firming path that averaged 2.9625 are not adopted.

**Tradable repricing, next 8–12 weeks: −5 to −10 bp from 3.11375, point −8 bp, strip toward 3.03.** Horizon is this receive’s nearer window, shorter than the life of the 2027 contracts. Eight basis points is most of the 10.6 bp distance to 3.0075 and not a move to 2.75 or to 2.80. The rest of the distance to the floor is an eventual outcome, not an 8–12 week target.

What moves the ranges: a Canadian CPI or labor print newer than September (underlying impulse, headline, breadth, unemployment); whether front oil stays near the 4 November marks or retraces the late-October spike (WTI 104.12 on 30 October is the stored reference, not a trigger copied from a deferred strip); and whether the wage impulse keeps rising. The proxy midpoint does not move the range.

## 3. Ordinary movement

No CORRA strip history is in the snapshot. Book marks and the two vintages are not a contract history, and none is fabricated here. Open interest cannot be used to judge positioning.

**Ordinary noise: 8 bp against the receive**, strip average **3.19375**. That is twice the election-window move and still at the top of the outcome range. It does not force an exit. It is a judgment threshold. It is not a measured strip volatility.

**Review and exit: 15 bp against**, strip average **3.26375**. That is 6.4 bp through the 3.20 ceiling. At that price the receive is the wrong side of the range I will defend.

A Canada 2-year sovereign history is in the snapshot: 126 stored points from 2026-05-04 to 2026-11-03, last yield **3.26** (the screen’s `n` of 252 is not the stored count). The quant worker should label that sovereign 2-year volatility separately. It is a sovereign proxy, not strip volatility. The adverse moves to cost on the strip are the ones in the next section, not a 2-year standard deviation.

## 4. Falsifier, exit, slippage, dollars

Receive gains when the average falls.

| | Strip | bp vs 3.11375 | USD at 100m (10k/bp) | USD at current 250m (25k/bp) |
| --- | ---: | ---: | ---: | ---: |
| Tradable target | 3.03375 | −8 | **+80,000** | +200,000 |
| Central 3.0075, if reached | 3.0075 | −10.625 | +106,250 | +265,625 |
| Ordinary noise | 3.19375 | +8 | −80,000 | −200,000 |
| Planned exit | 3.26375 | +15 | **−150,000** | −375,000 |
| Stated 20 bp stress | 3.31375 | +20 | −200,000 | −500,000 |
| Fast 10 bp through the exit | 3.36375 | +25 | **−250,000** | −625,000 |
| Worse stress | 3.41375 | +30 | −300,000 | −750,000 |

**Fundamental falsifier**, independent of the price stop: underlying impulse turning up through zero with the transform rising, and the unemployment transform falling. That is domestic reacceleration. The energy falsifier is a front-oil rebound that restores the September energy-PPI impulse, with WTI back through the 30 October print of 104.12 while no softer CPI has replaced September. Either one closes the receive even if the strip is still under 3.26375.

**Practical exit** is the +15 bp level above. The hypothesis band of 3.35–3.40 is about 24–29 bp from this anchor. It is not the working exit. An 11 bp forward gap does not earn a 24 bp adverse allowance.

**Slippage** is a fast extra 10 bp beyond that exit, to 3.36375. At the recommended size that is a USD 250,000 loss. At the current size it is USD 625,000.

Same-horizon funding, 3.95% ACT/360, draw proportional to DV01. Full size draw USD 2.5 million; the USD 100 million identity draws **USD 1.0 million**. Over 8 weeks (56/360) that is about **USD 6,100**; over 12 weeks (84/360) about **USD 9,200**. The same windows on the USD 2.5 million draw are about USD 15,400 and USD 23,000. Small next to the rate P&L. Not a direction.

**Joint risk, no hedge.** If the strip rises 15 bp and a separate long EURUSD declines in the same window, this book loses **USD 150,000** at USD 100 million (USD 375,000 if the USD 250 million were kept). The EURUSD loss is additional and is not netted. No hedge is proposed. Correlation is not a veto.

## 5. Loss budget, then size

The budget I will spend if the range breaks is **USD 150,000**, which is 15 bp at USD 10,000 per bp. That is the USD 100 million receive. Full USD 250 million spends **USD 375,000** at the same exit to seek a tradable gain of USD 200,000. I will not allocate that.

The ratio is uncomfortable and is stated as such. At USD 100 million the planned exit loses USD 150,000 and the tradable target gains USD 80,000. Ordinary noise of 8 bp costs the same USD 80,000 as the target. That is why the size is 100 million and not 250 million. Shrinking the exit until the dollars look favorable would turn the ceiling of the range into a stop inside ordinary noise. These figures are not an expected value. There is no probability on the pass-through case.

Compared with initiating the full 250 million: the smaller initial risk is the one that survives the from-flat test. Confirmation can add later. It is not a requirement to hold zero until then, and it is not a reason to keep 250 million while waiting.

## 6. Management

- **Initial exposure after this recommendation:** USD 100 million receive, DV01 USD 10,000 per bp, equal-weight CRAH27, CRAM27, CRAU27, CRAZ27. The higher back-contract rates do not justify dropping the front. The front is where the claim is thinnest, and dropping it would be a smaller book wearing an expression argument.
- **Harvest:** strip average at or through **3.03375** (−8 bp). Cut to USD 50 million. The tradable piece underwritten here has printed. Do not hold the original face for 2.75.
- **Add:** only on a later packet, and only by **USD 50 million** (to USD 150 million, DV01 USD 15,000), if underlying is still near 1.85 with impulse not positive, unemployment is still 6.5 or higher, the survey is not back in a sustained expansion, front WTI has not retaken 104, and the strip is still above **3.05**. Not on this packet. Not back to 250 million.
- **Exit:** strip at **3.26375**, or either fundamental falsifier above.
- **Unproductive receive:** if 12 weeks pass and the average is still between 3.03 and 3.19, exit the residual. The nearer reprice did not happen. The funding bill is not the reason.

## 7. NOW / WAIT / REJECT, anchored at 3.11375

**NOW. Resize to the USD 100 million receive.** This is the decision. It is an unexecuted research plan.

**WAIT**, rejected as the decision. The single condition that would have been worth waiting for is one Canadian CPI or labor print newer than September. It would buy a test of whether the energy PPI passed through and whether the underlying impulse stayed negative. The worse price is a strip that falls about 8 bp, to 3.03, before that print: **USD 80,000** foregone on the 100 million I would hold, and USD 200,000 if the 250 million were left in place. Waiting loses once the average trades through 3.03, because the tradable gap is then gone. Waiting also loses if the strip rises 15 bp before the print while the full face is still on.

**REJECT** retaining USD 250 million, rejecting 2.75 as the target, rejecting an add on this packet, rejecting a SOFR receive, and rejecting AONIA as a hedge or a substitute. The receive direction at USD 100 million is not rejected.

**Foregone-opportunity hypothesis:** if the strip falls about 8 bp toward 3.03 over the next 8–12 weeks while domestic softness and the lower front-oil path persist, a book that waited for a post-September CPI gives up that repricing.

## 8. Judgment under uncertainty

The strongest statement I will sign is a **smaller receive**, not a full-size hold and not a flat book. The 2027 average I will defend is **2.80 to 3.20**, centered near **3.01**. The market at **3.11375** is inside that range and above the center. The trade is the back-end climb, over **8–12 weeks**, for about **8 bp**, with a **15 bp** exit.

No gap in this packet makes every receive size unjustified. September inflation and labor are old, CORRA open interest is null, the futures page is undated, and oil is a mid-sample price after a hard drop that is still up from early August. Those facts are why the face is USD 100 million, why the horizon is weeks and not the life of the contract, and why 2.75 is not the target. They are not a ban.

The result that would make this resize wrong is the opposing case already in the packet: the hike, headline 3.09, rising breadth, the September energy PPI jump, and an oil decline that firms demand instead of ending the cycle. That case is why the ceiling is 3.20 and the exit is 3.26, and why the dollars at risk are a budget rather than a residual of a 36 bp proxy.
